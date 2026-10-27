#!/usr/bin/env python3
import argparse
import hashlib
import os
import re
import sqlite3
import sys
import unicodedata
import urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext, localcontext

getcontext().prec = 100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KST = timezone(timedelta(hours=9))
ZERO = Decimal(0)
CCY = "USD"
UNIT_SIG = 18
BC_PREC = 28
USD_TOL = Decimal("0.0000001")
ADJ_EVENTS = frozenset({"EXF_ADJUST", "EX_ADJUST", "LP_ADJUST"})
FEE_ACCT = {"EXF_FEE": "Expenses:Fee:Trade", "EXF_WD_FEE": "Expenses:Fee:Withdraw"}
GAS_ACCT = "Expenses:Fee:Gas"
XFER_ACCT = "Expenses:Fee:Transfer"
XOUT = "Equity:Transfer-Out"
PNL, OTHER, OPENING, RECON = "Income:PnL:Realized", "Income:Other", "Equity:Opening-Balances", "Equity:Reconciliation"


def day_of(ts) -> str:
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d")


def num(d) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def unit_of(cost: Decimal, q: Decimal) -> Decimal:
    with localcontext() as c:
        c.prec = UNIT_SIG
        u = cost / q
    return Decimal(num(u))


def qstr(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


_CM_BAD = re.compile(r"[^A-Z0-9'._-]")
_AC_BAD = re.compile(r"[^A-Za-z0-9-]")


def commodity_names(groups: dict) -> dict:
    def base(g):
        s = unicodedata.normalize("NFKD", str(groups[g][0] or "").split("#", 1)[0]).encode("ascii", "ignore").decode().upper()
        s = _CM_BAD.sub("", s)
        if s and not ("A" <= s[0] <= "Z"):
            s = "X" + s
        s = s[:20].rstrip("'._-")
        return s if len(s) >= 2 else "G%d" % g
    used, out = {CCY, "TRUE", "FALSE", "NULL"}, {}
    for g in sorted(groups, key=lambda g: ("#" in str(groups[g][0] or ""), g)):
        b = base(g)
        n = b
        if n in used:
            n = "%s-%d" % (b[:23 - len(str(g))].rstrip("'._-"), g)
        while n in used:
            n = "G%d-%s" % (g, n)[:24]
        used.add(n)
        out[g] = n
    return out


def _name(s) -> str:
    s = _AC_BAD.sub("-", str(s or "")).strip("-") or "X"
    return s[0].upper() + s[1:] if "a" <= s[0] <= "z" else (s if s[0].isalnum() else "X" + s)


def _addr(s, n) -> str:
    s = _AC_BAD.sub("-", str(s or ""))[:n].strip("-") or "X"
    return s if ("A" <= s[0] <= "Z" or s[0].isdigit()) else "X" + s


def account_of(loc: str, n: int = 8) -> str:
    p = str(loc or "").split(":")
    if p[0] == "exchange" and len(p) >= 2:
        return "Assets:Exchange:" + ":".join(_name(x) for x in p[1:])
    if p[0] in ("wallet", "out", "lp") and len(p) >= 3:
        head = {"wallet": "Assets:Wallet:", "out": "Equity:External:", "lp": "Assets:LP:"}[p[0]]
        return head + _name(p[1]) + "".join(":" + _addr(x, n) for x in p[2:])
    return "Assets:Other:" + ":".join(_addr(x, n) for x in p)


def account_names(locs) -> dict:
    out = {}
    for n in (8, 16, 64):
        todo = sorted(set(locs) - set(out))
        cand = defaultdict(list)
        for loc in todo:
            cand[account_of(loc, n)].append(loc)
        for a, ls in cand.items():
            if len(ls) == 1 and a not in out.values():
                out[ls[0]] = a
    seen = set(out.values())
    for loc in sorted(set(locs) - set(out)):
        a0, k = account_of(loc, 64), 2
        while "%s-%d" % (a0, k) in seen:
            k += 1
        out[loc] = "%s-%d" % (a0, k)
        seen.add(out[loc])
    return out


def ledger_path(arg) -> str:
    return arg or os.path.join(os.environ.get("TJ_BASE") or ROOT, "state", "ledger.db")


def open_ro(path: str, immutable: bool = False) -> sqlite3.Connection:
    uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + ("?immutable=1" if immutable else "?mode=ro")
    c = sqlite3.connect(uri, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def load_ledger(conn) -> dict:
    conn.execute("BEGIN")
    try:
        return _load(conn)
    finally:
        conn.rollback()


def _load(conn) -> dict:
    groups = {r[0]: (r[1], int(r[2] if r[2] is not None else 18)) for r in conn.execute("SELECT group_id, name, norm_decimals FROM asset_groups")}
    assets = {}
    for r in conn.execute("SELECT asset_id, group_id, decimals, kind, chain, address, symbol FROM assets"):
        gid = r[1]
        if gid is None:
            gid = -int(r[0])
            groups.setdefault(gid, (str(r[6] or "ASSET") + "#a%d" % r[0], 18))
        assets[r[0]] = (gid, r[2], r[3], r[4], r[5], r[6])
    cols = "posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, leg_kind, event"
    postings = [tuple(r) for r in conn.execute("SELECT %s FROM postings ORDER BY event_ts, posting_id" % cols)]
    positions = {(r[0], r[1]): Decimal(r[2]) for r in conn.execute("SELECT group_id, location, qty_norm FROM positions")}
    prices = {}
    try:
        for r in conn.execute("SELECT day, group_id, px_usd FROM snapshots WHERE px_usd IS NOT NULL ORDER BY day, location"):
            prices.setdefault((r[0], r[1]), r[2])
    except sqlite3.OperationalError:
        pass
    return {"groups": groups, "assets": assets, "postings": postings, "positions": positions, "prices": prices}


def qty_of(ld: dict, aid, qty_base) -> Decimal:
    dec = ld["assets"][aid][1]
    return Decimal(int(qty_base)) / (Decimal(10) ** (dec if dec is not None else 18))


def _dec(v):
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def export(ld: dict, title: str = "tj-bot") -> tuple:
    cm = commodity_names(ld["groups"])
    acct = account_names({p[7] for p in ld["postings"]} | {loc for _, loc in ld["positions"]})
    lots = defaultdict(deque)
    st = defaultdict(int)
    by_src, order = defaultdict(list), []
    for p in ld["postings"]:
        k = (p[1], p[2], p[3])
        if k not in by_src:
            order.append(k)
        by_src[k].append(p)
    txs, used, first = [], set(), None

    def take(dq, q):
        got = []
        while q > 0 and dq:
            lot = dq[0]
            t = min(q, lot[0])
            got.append([t, lot[1], lot[2], lot[3]])
            lot[0] -= t
            q -= t
            if lot[0] == 0:
                dq.popleft()
        return got, q

    for k in order:
        legs = sorted(by_src[k], key=lambda p: (p[4], p[0]))
        day = day_of(min(p[5] for p in legs))
        first = min(first or day, day)
        lines, explicit, pool, ins = [], [], defaultdict(deque), set()
        sale, ev = False, {p[11] for p in legs}
        for p in legs:
            q = qty_of(ld, p[6], p[8])
            if q >= 0:
                continue
            a, c, q, kind, cost = acct[p[7]], cm[ld["assets"][p[6]][0]], -q, p[10], _dec(p[9])
            got, short = take(lots[(a, c)], q)
            if short > 0:
                got.append([short, ZERO, day, "short"])
                st["shortfall"] += 1
            px = unit_of(cost, q) if cost is not None and kind in ("disp", "gas") and q > 0 else None
            for t, u, d, unk in got:
                lines.append((a, -t, c, u, d, unk, px))
            basis = sum((t * u for t, u, _, _ in got), ZERO)
            if kind == "move_out":
                pool[c].extend([t, u, d, unk] for t, u, d, unk in got)
            elif kind == "gas":
                explicit.append((FEE_ACCT.get(p[11], GAS_ACCT), cost if cost is not None else basis))
                sale = sale or cost is not None
            elif kind == "disp" and cost is not None:
                sale = True
        for p in legs:
            q = qty_of(ld, p[6], p[8])
            if q <= 0:
                continue
            a, c, kind, cost = acct[p[7]], cm[ld["assets"][p[6]][0]], p[10], _dec(p[9])
            if kind == "move_in":
                ins.add(c)
                got, left = take(pool[c], q)
                if left > 0:
                    got.append([left, ZERO, day_of(p[5]), True])
                    st["unknown_in"] += 1
            else:
                got = [[q, unit_of(cost, q), day_of(p[5]), False]] if cost is not None else [[q, ZERO, day_of(p[5]), True]]
                st["unknown_lot"] += cost is None
            for t, u, d, unk in got:
                lines.append((a, t, c, u, d, unk, None))
                lots[(a, c)].append([t, u, d, unk])
        for c, dq in pool.items():
            if not dq:
                continue
            if c in ins:
                explicit.append((XFER_ACCT, sum((t * u for t, u, _, _ in dq), ZERO)))
                continue
            for t, u, d, unk in dq:
                lines.append((XOUT, t, c, u, d, unk, None))
        w = sum((t * u for _, t, _, u, _, _, _ in lines), ZERO) + sum((x for _, x in explicit), ZERO)
        absorber = None
        if w != 0:
            absorber = PNL if sale else RECON if ev & ADJ_EVENTS else OPENING if "OPENING" in ev or any(p[10] == "opening" for p in legs) else OTHER
        meta = {"src": "%s/%s/%s" % k}
        if ev & ADJ_EVENTS:
            meta["why"] = ",".join(sorted(ev & ADJ_EVENTS))
        txs.append((day, sorted(ev), meta, lines, explicit, absorber))
        used |= {ln[0] for ln in lines} | {x[0] for x in explicit} | ({absorber} if absorber else set())
        st["tx"] += 1
        st["postings"] += len(lines) + len(explicit) + (1 if absorber else 0)
    first = first or "1970-01-01"
    out = [";; %s 원장 → Beancount (tools/export_beancount.py · 읽기 전용 내보내기 · 로트 = 계정별 선입선출)" % title,
           'option "title" %s' % qstr(title), 'option "operating_currency" "%s"' % CCY, 'option "booking_method" "NONE"',
           'option "inferred_tolerance_default" "%s:%s"' % (CCY, num(USD_TOL)), ""]
    for a in sorted(used):
        out.append("%s open %s" % (first, a))
    out.append("")
    for g in sorted({ld["assets"][p[6]][0] for p in ld["postings"]}, key=lambda g: cm[g]):
        out += ["%s commodity %s" % (first, cm[g]), "  name: %s" % qstr(ld["groups"][g][0]), "  gid: %s" % qstr(g),
                "  tolerance: %s" % qstr(num(Decimal(1).scaleb(-ld["groups"][g][1])))]
    out.append("")
    for (d, g), px in sorted(ld["prices"].items()):
        if g in cm and _dec(px) is not None:
            out.append("%s price %s %s %s" % (d, cm[g], num(_dec(px)), CCY))
            st["price"] += 1
    out.append("")
    for day, evs, meta, lines, explicit, absorber in txs:
        out.append("%s * %s" % (day, qstr(" ".join(evs))))
        out += ["  %s: %s" % (mk, qstr(mv)) for mk, mv in meta.items()]
        for a, t, c, u, d, unk, px in lines:
            out.append("  %s  %s %s {%s %s, %s}%s" % (a, num(t), c, num(u), CCY, d, " @ %s %s" % (num(px), CCY) if px is not None else ""))
            if unk and t > 0 or unk == "short":
                out.append('    cost: "unknown"' + ('\n    shortfall: TRUE' if unk == "short" else ""))
        for a, x in explicit:
            out.append("  %s  %s %s" % (a, num(x), CCY))
        if absorber:
            out.append("  " + absorber)
        out.append("")
    st["accounts"] = len(used)
    st["commodities"] = len({ld["assets"][p[6]][0] for p in ld["postings"]})
    return "\n".join(out) + "\n", dict(st), acct, cm


_POST = re.compile(r"^  ([A-Z][A-Za-z0-9:-]*)(?:\s+(-?[0-9.]+) ([A-Z][A-Z0-9'._-]*)(?: \{(-?[0-9.]+) ([A-Z]+), (\d{4}-\d\d-\d\d)\})?(?: @ ([0-9.]+) [A-Z]+)?)?\s*$")


def check_text(text: str) -> dict:
    bad, units, opened, tx = [], defaultdict(lambda: ZERO), {}, 0
    bal, bal_days, cur = 0, set(), None

    def close(cur):
        if cur is None:
            return
        w, w28, miss = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), 0
        for a, q, c, u, cc in cur[1]:
            if q is None:
                miss += 1
                continue
            k, v = (cc, q * u) if u is not None else (c, q)
            w[k] += v
            with localcontext() as ctx:
                ctx.prec = BC_PREC
                w28[k] = w28[k] + (q * u if u is not None else +q)
        if miss > 1 or (miss == 0 and any(v != 0 for v in w.values())):
            bad.append("분개 합 ≠ 0 · %s %s" % (cur[0], dict((k, num(v)) for k, v in w.items() if v != 0) or "빈 줄 %d" % miss))
        elif miss == 0 and any(abs(v) > (USD_TOL if k == CCY else 0) for k, v in w28.items()):
            bad.append("28자리 합 허용오차 넘음 · %s %s" % (cur[0], dict((k, num(v)) for k, v in w28.items() if v != 0)))

    for ln in text.split("\n"):
        m = re.match(r"^(\d{4}-\d\d-\d\d) (open|balance|\*) ?(.*)$", ln)
        if m:
            close(cur)
            cur = None
            d, kind, rest = m.groups()
            if kind == "open":
                opened[rest.strip()] = d
            elif kind == "balance":
                bal += 1
                bal_days.add(d)
                a = rest.split()[0]
                if a not in opened or opened[a] > d:
                    bad.append("open 앞 balance " + a)
            else:
                tx += 1
                cur = (d, [])
            continue
        if cur is None or not ln.startswith("  ") or ln.startswith("    "):
            continue
        pm = _POST.match(ln)
        if not pm:
            if not re.match(r"^  [a-z][\w-]*: ", ln):
                bad.append("읽지 못한 줄 " + ln.strip()[:60])
            continue
        a, q, c, u, cc, _, _ = pm.groups()
        if a not in opened or opened[a] > cur[0]:
            bad.append("open 앞 사용 " + a)
        if q is None:
            cur[1].append((a, None, None, None, None))
            continue
        q, u = Decimal(q), (Decimal(u) if u is not None else None)
        cur[1].append((a, q, c, u, cc))
        units[(a, c)] += q
    close(cur)
    return {"bad": bad, "units": dict(units), "balance": bal, "balance_days": len(bal_days), "tx": tx}


def positions_diff(ld: dict, units: dict, acct: dict, cm: dict) -> list:
    want = defaultdict(lambda: ZERO)
    for (g, loc), q in ld["positions"].items():
        want[(acct.get(loc) or account_of(loc), cm.get(g))] += q
    keys = {k for k in want if want[k] != 0} | {k for k, v in units.items() if v != 0 and not k[0].startswith(("Equity:Transfer-Out", "Expenses:", "Income:", "Equity:Opening", "Equity:Recon"))}
    return sorted((k[0], k[1], num(want.get(k, ZERO)), num(units.get(k, ZERO))) for k in keys if want.get(k, ZERO) != units.get(k, ZERO))


def demo_ledger() -> tuple:
    h = lambda s: hashlib.sha256(("tj-demo:" + s).encode()).hexdigest()
    w1, w2, ext = "0x" + h("w1")[:40], "0x" + h("w2")[:40], "0x" + h("ext")[:40]
    groups = {1: ("KRW#upbit", 18), 2: ("ETH", 18), 3: ("USDC", 18), 4: ("TKJ#base:0x" + h("tkj")[:40], 18), 5: ("ETH#upbit", 18)}
    assets = {1: (1, 0, "exchange_currency", None, None, "KRW"), 2: (5, 18, "exchange_currency", None, None, "ETH"),
              3: (2, 18, "native", "eth", None, "ETH"), 4: (3, 6, "token", "eth", "0x" + h("usdc")[:40], "USDC"),
              5: (3, 6, "token", "base", "0x" + h("usdcb")[:40], "USDC"), 6: (4, 18, "token", "base", "0x" + h("tkj")[:40], "TKJ")}
    E, U = 10 ** 18, 10 ** 6
    t0 = 1767225600
    up, l1, l2 = "exchange:upbit", "wallet:eth:" + w1, "wallet:base:" + w2
    rows = [
        ("exchange", "upbit:deposit", "d1", 0, t0, 1, up, 5000000, "3700", "acq", "EX_DEPOSIT"),
        ("opening", "eth", "open1", 0, t0, 3, l1, E, None, "opening", "OPENING"),
        ("exchange", "upbit:order", "o1", 0, t0 + 86400, 2, up, E, "2000", "acq", "EX_BUY"),
        ("exchange", "upbit:order", "o1", 1, t0 + 86400, 1, up, -2700000, "2000", "disp", "EX_BUY"),
        ("exchange", "upbit:order", "o2", 0, t0 + 2 * 86400, 2, up, E // 2, "1500", "acq", "EX_BUY"),
        ("exchange", "upbit:order", "o2", 1, t0 + 2 * 86400, 1, up, -2025000, "1500", "disp", "EX_BUY"),
        ("exchange", "upbit:withdraw", "x1", 0, t0 + 3 * 86400, 2, up, -8 * E // 10, None, "move_out", "EX_WITHDRAW"),
        ("exchange", "upbit:withdraw", "x1", 1, t0 + 3 * 86400, 2, up, -2 * E // 1000, None, "gas", "EXF_WD_FEE"),
        ("chain_tx", "eth", "tx1", 0, t0 + 3 * 86400 + 600, 3, l1, 8 * E // 10, None, "move_in", "EX_WITHDRAW"),
        ("chain_tx", "eth", "tx2", 0, t0 + 4 * 86400, 3, l1, -12 * E // 10, "3600", "disp", "SWAP"),
        ("chain_tx", "eth", "tx2", 1, t0 + 4 * 86400, 4, l1, 3590 * U, "3590", "acq", "SWAP"),
        ("chain_tx", "eth", "tx2", 2, t0 + 4 * 86400, 3, l1, -E // 1000, "3", "gas", "SWAP"),
        ("chain_tx", "base", "tx3", 0, t0 + 5 * 86400, 4, l1, -1000 * U, None, "move_out", "BRIDGE"),
        ("chain_tx", "base", "tx3", 1, t0 + 5 * 86400, 5, l2, 999 * U, None, "move_in", "BRIDGE"),
        ("chain_tx", "base", "tx4", 0, t0 + 6 * 86400, 5, l2, -500 * U, None, "move_out", "TRANSFER_OUT"),
        ("chain_tx", "base", "tx4", 1, t0 + 6 * 86400, 5, "out:base:" + ext, 500 * U, None, "move_in", "TRANSFER_OUT"),
        ("exchange", "upbit:recon", "r1", 0, t0 + 6 * 86400, 1, up, -1000, None, "opening", "EX_ADJUST"),
        ("chain_tx", "base", "tx5", 0, t0 + 7 * 86400, 6, l2, -50 * E, "25", "disp", "SWAP"),
        ("chain_tx", "base", "tx5", 1, t0 + 7 * 86400, 5, l2, 25 * U, "25", "acq", "SWAP"),
    ]
    postings = [(i + 1, r[0], r[1], r[2], r[3], r[4], r[5], r[6], str(r[7]), r[8], r[9], r[10]) for i, r in enumerate(rows)]
    ld = {"groups": groups, "assets": assets, "postings": postings, "positions": {}, "prices": {}}
    pos = defaultdict(lambda: ZERO)
    for p in postings:
        pos[(assets[p[6]][0], p[7])] += qty_of(ld, p[6], p[8])
    ld["positions"] = dict(pos)
    ld["prices"] = {(day_of(t0 + 4 * 86400), 2): "3000", (day_of(t0 + 4 * 86400), 3): "1"}
    return ld


def same_file(out: str, ledger: str) -> bool:
    ro, rl = os.path.realpath(out), os.path.realpath(ledger)
    for f in (ledger, ledger + "-wal", ledger + "-shm", ledger + "-journal", rl + "-wal", rl + "-shm", rl + "-journal"):
        if ro == os.path.realpath(f):
            return True
        try:
            if os.path.exists(out) and os.path.exists(f) and os.path.samefile(out, f):
                return True
        except OSError:
            return True
    return False


def in_state_dir(out: str) -> bool:
    sd = os.path.dirname(os.path.realpath(ledger_path(None)))
    d = os.path.dirname(os.path.realpath(out))
    while True:
        try:
            if d == sd or (os.path.isdir(d) and os.path.isdir(sd) and os.path.samefile(d, sd)):
                return True
        except OSError:
            return True
        up = os.path.dirname(d)
        if up == d:
            return False
        d = up


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="원장 → Beancount 내보내기(읽기 전용)")
    ap.add_argument("--ledger", help="원장 경로(기본 = $TJ_BASE/state/ledger.db)")
    ap.add_argument("--immutable", action="store_true", help="원장 사본을 immutable 로 열기(쓰는 프로세스가 없는 사본만)")
    ap.add_argument("--demo", action="store_true", help="합성 원장으로 내보내기")
    ap.add_argument("--out", help="쓸 파일(기본 = 표준 출력)")
    ap.add_argument("--check", action="store_true", help="만든 글 스스로 검사(분개 합 · positions 대조)")
    a = ap.parse_args(argv)
    path = ledger_path(a.ledger)
    if a.out and same_file(a.out, path):
        print("출력 파일이 원장과 같아요 — 거부: %s" % a.out, file=sys.stderr)
        return 2
    if a.out and in_state_dir(a.out):
        print("출력 파일이 state 폴더 안이에요 — 다른 폴더로: %s" % a.out, file=sys.stderr)
        return 2
    if a.demo:
        ld = demo_ledger()
    else:
        try:
            conn = open_ro(path, a.immutable)
            try:
                ld = load_ledger(conn)
            finally:
                conn.close()
        except sqlite3.Error as e:
            print("원장을 읽지 못했어요: %s (%s)" % (path, e), file=sys.stderr)
            return 2
    text, st, acct, cm = export(ld, "tj-bot demo" if a.demo else "tj-bot")
    if a.out:
        with open(a.out, "w", encoding="utf-8", opener=lambda f, fl: os.open(f, fl, 0o600)) as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    rc = 0
    if a.check:
        r = check_text(text)
        diff = positions_diff(ld, r["units"], acct, cm)
        st.update(check_bad=len(r["bad"]), positions_diff=len(diff))
        for b in r["bad"][:10]:
            print("검사: " + b, file=sys.stderr)
        rc = 1 if r["bad"] or diff else 0
    print("요약 " + " · ".join("%s %d" % kv for kv in sorted(st.items())), file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())

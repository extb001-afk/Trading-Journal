"""Matches outgoing transfers to known destinations."""
import re
from decimal import Decimal

import acct_norm

_HEX64 = re.compile(r"^(?:0[xX])?([0-9a-fA-F]{64})$")
_B58SIG = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{64,100}$")
STABLES = {"USDT", "USDC", "FDUSD", "BUSD", "DAI", "TUSD", "USD1", "PYUSD", "USDE"}
_ALIAS = {"USDC.E": "USDC", "USDBC": "USDC", "USDT0": "USDT", "USD₮0": "USDT", "USD₮": "USDT", "BSC-USD": "USDT",
          "USDT.E": "USDT"}
FEE_REL = Decimal("0.005")
FEE_ABS_STABLE = Decimal("2")
WIN_BEFORE = 120
WIN_AFTER = 6 * 3600
SPECIAL_DESTS = ("multi", "?")
FULL_RETURN = Decimal("0.98")


def norm_txid(t) -> str:
    t = str(t or "").strip()
    m = _HEX64.match(t)
    if m:
        return "0x" + m.group(1).lower()
    return t


def fmt_q(q) -> str:
    t = f"{Decimal(q):,.6f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def canon_sym(s, ex=None) -> str:
    s = acct_norm.canon(s, ex)
    return _ALIAS.get(s, s)


def _hash_family(t: str) -> str:
    if _HEX64.match(t or ""):
        return "evm"
    if _B58SIG.match(t or ""):
        return "sol"
    return ""


def qty_fits(sent: Decimal, credited: Decimal, sym: str) -> bool:
    if sent <= 0 or credited <= 0:
        return False
    hi = sent * (Decimal(1) + Decimal("1e-9"))
    lo = sent * (Decimal(1) - FEE_REL) - (FEE_ABS_STABLE if canon_sym(sym) in STABLES else Decimal(0))
    return lo <= credited <= hi


def match(sends, deposits, mine_txids=frozenset(), deposit_exchange=None, no_auto=frozenset()):
    matches, sugg, proven = {}, {}, {}
    dcs = {id(d): canon_sym(d["cur"], d.get("ex")) for d in deposits}
    scs = {}

    def _scs(s0):
        k0 = id(s0)
        if k0 not in scs:
            scs[k0] = canon_sym(s0["sym"])
        return scs[k0]
    dep_by_txn = {}
    for d in deposits:
        if d.get("txn"):
            dep_by_txn.setdefault(d["txn"], []).append(d)
    used = set()
    live = [s for s in sends if s["dest"] not in no_auto]
    r1_ex = {}
    for s in live:
        ds = dep_by_txn.get(s["txn"]) or []
        if not ds:
            continue
        cs0 = _scs(s)
        same = [d for d in ds if dcs[id(d)] == cs0]
        if not same and len(ds) == 1 and qty_fits(s["qty"], ds[0]["amt"], s["sym"]):
            same = ds
        d = same[0] if same else ds[0]
        matches[s["pid"]] = {"basis": "txid", "ex": d["ex"], "uuid": d["uuid"] if same else None, "cur": d["cur"],
                             "dt": int(d["ts"] - s["ts"]) if d.get("ts") else None}
        if same:
            used.add((d["ex"], d["uuid"]))
            r1_ex.setdefault(s["dest"], set()).add(d["ex"])
    for s in live:
        if s["dest"] in SPECIAL_DESTS or s["dest"] in proven:
            continue
        exs = r1_ex.get(s["dest"]) or set()
        h = deposit_exchange(s["chain"], s["dest"]) if deposit_exchange else None
        if h:
            exs = exs | {h}
        if len(exs) == 1:
            proven[s["dest"]] = (next(iter(exs)), "txid" if s["dest"] in r1_ex else "list")
        elif len(exs) > 1:
            proven[s["dest"]] = (None, "conflict")
    pool = [d for d in deposits if (d["ex"], d["uuid"]) not in used and not (d.get("txn") and d["txn"] in mine_txids)]
    pool_by = {}
    for d in pool:
        pool_by.setdefault(dcs[id(d)], []).append(d)
    cand_s, cand_d = {}, {}
    live_ids = {s["pid"] for s in live}
    for s in sends:
        if s["pid"] in matches or not s.get("ok") or s["dest"] in SPECIAL_DESTS:
            continue
        cs = _scs(s)
        pex = proven.get(s["dest"], (None, ""))[0]
        for d in pool_by.get(cs, ()):
            if not d.get("ts"):
                continue
            dt = d["ts"] - s["ts"]
            if dt < -WIN_BEFORE or dt > WIN_AFTER or not qty_fits(s["qty"], d["amt"], cs):
                continue
            of = d.get("origin_from")
            if of and of != s["dest"] and not d.get("origin_mine"):
                continue
            if pex and d["ex"] != pex:
                continue
            cand_s.setdefault(s["pid"], []).append(d)
            cand_d.setdefault((d["ex"], d["uuid"]), []).append(s["pid"])
    by_pid = {s["pid"]: s for s in sends}
    for pid, ds in cand_s.items():
        if pid not in live_ids:
            continue
        s = by_pid[pid]
        if len(ds) == 1 and len(cand_d[(ds[0]["ex"], ds[0]["uuid"])]) == 1:
            d = ds[0]
            matches[pid] = {"basis": "amount_time", "ex": d["ex"], "uuid": d["uuid"], "cur": d["cur"], "dt": int(d["ts"] - s["ts"])}
            used.add((d["ex"], d["uuid"]))
        else:
            for d in ds[:3]:
                sugg.setdefault(s["dest"], []).append({
                    "kind": "exchange", "ex": d["ex"], "uuid": d["uuid"], "pid": pid, "dt": int(d["ts"] - s["ts"]),
                    "evidence": f"{s['sym']} {fmt_q(s['qty'])} 보냄 → {int((d['ts'] - s['ts']) // 60)}분 뒤 "
                                f"{d['ex']} 입금 {fmt_q(d['amt'])} (후보 {len(ds)}건 · 그 입금의 후보 전송 "
                                f"{len(cand_d[(d['ex'], d['uuid'])])}건 — 유일하지 않아 자동 안 함)"})
    for s in live:
        if s["pid"] in matches or not s.get("ok") or s["dest"] in SPECIAL_DESTS or proven.get(s["dest"], (None, ""))[0]:
            continue
        cs = _scs(s)
        h0 = str(s["dest"]).lower() if str(s["dest"]).startswith("0x") else s["dest"]
        ds = [d for d in pool_by.get(cs, ()) if (d["ex"], d["uuid"]) not in used and d.get("ts") and d.get("origin_from") == h0
              and -WIN_BEFORE <= d["ts"] - s["ts"] <= WIN_AFTER
              and Decimal(0) < d["amt"] <= s["qty"] * (Decimal(1) + Decimal("1e-9"))]
        if len(ds) < 2 or len({d["ex"] for d in ds}) != 1:
            continue
        tot = sum((d["amt"] for d in ds), Decimal(0))
        if not qty_fits(s["qty"], tot, cs):
            continue
        rival = [s2 for s2 in sends if s2["pid"] != s["pid"] and s2["dest"] == s["dest"] and _scs(s2) == cs
                 and any(-WIN_BEFORE <= d["ts"] - s2["ts"] <= WIN_AFTER for d in ds)]
        if rival:
            continue
        ds.sort(key=lambda d: d["ts"])
        matches[s["pid"]] = {"basis": "hop_split", "ex": ds[0]["ex"], "uuid": None, "uuids": [d["uuid"] for d in ds],
                             "amts": [d["amt"] for d in ds], "cur": ds[0]["cur"], "dt": int(ds[0]["ts"] - s["ts"])}
        for d in ds:
            used.add((d["ex"], d["uuid"]))
    for s in live:
        if s["pid"] in matches or not s.get("ok"):
            continue
        ex, how = proven.get(s["dest"], (None, ""))
        if ex:
            matches[s["pid"]] = {"basis": "address", "ex": ex, "uuid": None, "cur": s["sym"], "dt": None, "how": how}
    return matches, sugg, proven


_FAMILY = {"WETH": "ETH", "WBNB": "BNB", "WSOL": "SOL", "WBTC": "BTC", "BTCB": "BTC", "CBBTC": "BTC", "WPOL": "POL",
           "WMATIC": "POL", "MATIC": "POL", "WAVAX": "AVAX"}
BRIDGE_REL = Decimal("0.01")
BRIDGE_ABS_STABLE = Decimal("1")
BRIDGE_WINDOW = 3600
XSTABLES = frozenset(STABLES | {"USDM", "USDG", "CUSD", "NUSD"})
XSTABLE_REL = Decimal("0.01")
_BRIDGE_DESTS = None


def bridge_dests() -> frozenset:
    global _BRIDGE_DESTS
    if _BRIDGE_DESTS is None:
        out = set()
        try:
            import json
            import os
            import common
            out |= {str(a).lower() for a in (common.seed_json("bridge_contracts.json", [], base_dir=common.BASE_DIR) or []) if isinstance(a, str)}
            out |= {str(a).lower() for a in (common.seed_json("bridge_labels.json", {}, base_dir=common.BASE_DIR) or {}) if isinstance(a, str) and not a.startswith("_")}
        except Exception:
            pass
        _BRIDGE_DESTS = frozenset(out)
    return _BRIDGE_DESTS


def xstable_fits(sent: Decimal, got: Decimal) -> bool:
    if sent <= 0 or got <= 0:
        return False
    return abs(got - sent) <= max(Decimal(1), sent * XSTABLE_REL)
LEDGER_BRIDGE_WINDOW = 21600
OFT_SEND_SEL = "0xc7c7f5b3"
OFT_WINDOW = 21600
OFT_QTY_TOL = Decimal("0.001")


def family(s) -> str:
    c = canon_sym(s)
    return _FAMILY.get(c, c)


def bridge_fits(sent: Decimal, got: Decimal, sym: str) -> bool:
    if sent <= 0 or got <= 0:
        return False
    lo = sent * (Decimal(1) - BRIDGE_REL) - (BRIDGE_ABS_STABLE if family(sym) in STABLES else Decimal(0))
    return lo <= got <= sent * (Decimal(1) + Decimal("1e-9"))


def bridge_match(sends, arrivals, competitors=(), skip=frozenset(), no_auto=frozenset(), window=BRIDGE_WINDOW):
    by_fam = {}
    for a in arrivals:
        if a.get("ok", True):
            by_fam.setdefault(family(a["sym"]), []).append(a)
    cs, ca = {}, {}
    pool = [(s, False) for s in sends if s["pid"] not in skip] + [(c, True) for c in competitors]
    for s, comp in pool:
        if not s.get("ok") or s["qty"] <= 0:
            continue
        fs = family(s["sym"])
        cands = list(by_fam.get(fs) or ())
        xs = (not comp) and s.get("stable") is True and fs in XSTABLES and str(s.get("dest") or "").lower() in bridge_dests()
        if xs:
            cands += [a for f9 in sorted(by_fam) if f9 != fs and f9 in XSTABLES for a in by_fam[f9] if a.get("stable") is True]
        for a in cands:
            if a["chain"] == s["chain"]:
                continue
            dt = a["ts"] - s["ts"]
            if comp:
                fit = -600 <= dt <= LEDGER_BRIDGE_WINDOW and a["qty"] <= s["qty"] * Decimal("1.02")
            elif s.get("oft"):
                fit = family(a["sym"]) == fs and 0 <= dt <= OFT_WINDOW and abs(a["qty"] - s["qty"]) <= s["qty"] * OFT_QTY_TOL
            elif family(a["sym"]) == fs:
                fit = 0 <= dt <= window and bridge_fits(s["qty"], a["qty"], s["sym"])
            else:
                fit = 0 <= dt <= window and xstable_fits(s["qty"], a["qty"])
            if fit:
                cs.setdefault(s["pid"], []).append(a)
                ca.setdefault(a["key"], []).append(s["pid"])
    comp_ids = {c["pid"] for c in competitors} | {s["pid"] for s in sends if s["dest"] in no_auto}
    m, amb = {}, {}
    for pid, v in cs.items():
        if pid in comp_ids:
            continue
        if len(v) == 1 and len(ca[v[0]["key"]]) == 1:
            m[pid] = v[0]
        else:
            amb[pid] = v[:3]
    return m, amb


def bridge_hints(sends, arrivals, window=BRIDGE_WINDOW):
    return bridge_match(sends, arrivals, window=window)[0]


def return_kind(sent_usd, returned_usd):
    sent_usd = Decimal(str(sent_usd or 0)); returned_usd = Decimal(str(returned_usd or 0))
    if returned_usd <= 0:
        return None
    if sent_usd > 0 and returned_usd >= sent_usd * FULL_RETURN:
        return "full"
    if returned_usd >= 1:
        return "partial"
    return None

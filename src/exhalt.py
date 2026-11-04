from __future__ import annotations

import functools
import os
from collections.abc import Callable
from datetime import datetime

import acct_norm
import alert_prefs as AP
import calcguard
import num_parse
import paths
import spamguard
import statefile
from timeutil import KST

FILE = "ex_wallet_status.json"
EVERY = 600
FRESH = 3 * EVERY
SHOW_MAX = 2 * 3600
STALE_WARN = 3600
CLEAR_HOLD = 900
CONFIRM_N = 2
PX_AGREE = 2.0
NAMES = {"upbit": "업비트", "bithumb": "빗썸", "binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트",
         "coinbase": "코인베이스", "hyperliquid": "하이퍼리퀴드"}
DIR_KO = {"d": "입금", "w": "출금", "m": "입출금"}
_CACHE = {"v": (None, None)}
_f = functools.partial(num_parse.to_float, default=0.0)


def load(path: str = None) -> dict:
    p = path or paths.state(FILE)
    try:
        st = os.stat(p)
        sig = (p, st.st_mtime_ns, st.st_size)
    except OSError:
        return {"ex": {}}
    got = _CACHE["v"]
    if got[0] == sig:
        return got[1]
    try:
        d = statefile.read_json(p, {}) or {}
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("exhalt:load", e, expected=True)
        return got[1] if got[1] is not None else {"ex": {}, "bad": 1}
    d = d if isinstance(d, dict) and isinstance(d.get("ex"), dict) else {"ex": {}, "bad": 1}
    _CACHE["v"] = (sig, d)
    return d


def blocked(e: dict, sym: str, dk: str):
    r = ((e.get("c") or {}).get(sym) or {}).get(dk)
    return r if isinstance(r, dict) and r.get("st") == "on" else None


NATIVE_EX_TICKER = {"TON": "GRAM"}


def cid(sym: str, ex: str = None, native: bool = False) -> str:
    tk = acct_norm.norm_ticker(sym)
    return acct_norm.canon(NATIVE_EX_TICKER.get(tk, tk) if native else tk, ex)


def _gid_kinds(conn, gids) -> dict:
    out = {}
    ids = sorted(gids)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for g, k, ch, ca in conn.execute("SELECT group_id, kind, chain, address FROM assets WHERE group_id IN (%s)" % ",".join("?" * len(part)), part):
            o = out.setdefault(g, {"native": False, "pairs": []})
            if k == "native":
                o["native"] = True
            elif k == "token" and ca:
                o["pairs"].append((ch, ca))
    return out


def _wallet_ok(gid, sym, kinds, proof):
    k = kinds.get(gid) or {}
    exs = sorted({str(ex) for ex, cur in proof.get(gid) or () if cid(cur, ex) == cid(sym, None, bool(k.get("native")))})
    ng = bool(k.get("native")) or any(spamguard.is_genuine(ch, ca) for ch, ca in k.get("pairs") or ())
    return (bool(exs) or ng), exs, ng


def holdings(rows: list, ex_gid: dict, kinds: dict, proof: dict) -> dict:
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym, key = str(r.get("sym") or "").upper(), str(r.get("key") or "")
        usd = _f(r.get("qty")) * _f(r.get("price"))
        if not sym or usd <= 0:
            continue
        gid = int(key[1:]) if key[:1] == "g" and key[1:].isdigit() else None
        ex = "upbit" if key.startswith("ub:") else ex_gid.get(gid) if gid is not None else None
        if ex:
            h = out.setdefault(cid(sym, ex), {"ex": {}, "wp": []})
            h["ex"][ex] = [(h["ex"].get(ex) or [0.0])[0] + usd, sym]
        elif gid is not None:
            ok, exs, ng = _wallet_ok(gid, sym, kinds, proof)
            if ok:
                names = [str(lc.get("w")) for lc in r.get("locs") or [] if isinstance(lc, dict) and lc.get("ch") and lc.get("w")]
                out.setdefault(cid(sym, None, bool((kinds.get(gid) or {}).get("native"))), {"ex": {}, "wp": []})["wp"].append(
                    [usd, exs, names, _f(r.get("price")), ng])
    return out


def _agree(pa, pb) -> bool:
    return pa > 0 and pb > 0 and 1 / PX_AGREE <= pa / pb <= PX_AGREE


def _px(px, ex, sym) -> float:
    try:
        return _f(px(ex, sym))
    except Exception as err:   # noqa: BLE001 [fallback]
        calcguard.swallowed("exhalt:px", err, expected=True)
        return 0.0


def _held_usd(h, ex, sym, dk, px):
    if dk == "w":
        return (h["ex"].get(ex) or [0.0])[0], [NAMES.get(ex, ex)]
    p_ex = _px(px, ex, sym)
    usd, where = 0.0, []
    for u2, exs, names, p2, ng in h.get("wp") or ():
        if ex in exs or _agree(p_ex, p2) or (ng and p_ex <= 0):
            usd += u2
            where += [nm for nm in names if nm not in where]
    for e2, (u2, s2) in sorted(h["ex"].items()):
        if e2 != ex and _agree(p_ex, _px(px, e2, s2)):
            usd += u2
            where.append(NAMES.get(e2, e2))
    return usd, where


def _coin_row(ex, e, sym, dk, ctx):
    hold, dust, px, now = ctx
    r = ((e.get("c") or {}).get(sym) or {}).get(dk)
    if not isinstance(r, dict):
        return None
    full = r.get("st") == "on"
    part = not full and int(_f(r.get("pn"))) >= CONFIRM_N and bool(r.get("nb"))
    if not (full or part):
        return None
    usd, where = _held_usd(hold[cid(sym, ex)], ex, sym, dk, px)
    if usd <= 0 or usd < dust:
        return None
    return {"key": f"{ex}|{sym}|{dk}", "ex": ex, "exN": NAMES.get(ex, ex), "sym": sym, "dir": dk, "part": part,
            "nets": list(r.get("nb") if part else r.get("bn") or [])[:6], "since": int(_f(r.get("s"))), "usd": round(usd, 2),
            "where": where[:6], "pre": bool(r.get("pre")), "mt": bool(r.get("mt")), "age": int(max(0, now - _f(e.get("at"))))} \
        | ({"eo": int(_f(r["eo"]))} if _f(r.get("eo")) > now else {}) | ({"bs": str(r["bs"])[:20]} if r.get("bs") else {})


def _ex_rows(ex, e, ctx):
    hold, dust, _px, now = ctx
    m = e.get("maint") if isinstance(e.get("maint"), dict) else None
    mset = set(m.get("set") or []) if m else set()
    rows, mhit, pre = [], [], []
    for sym in sorted(x for x in (e.get("c") or {}) if cid(x, ex) in hold):
        for dk in ("d", "w"):
            row = _coin_row(ex, e, sym, dk, ctx)
            if row and f"{sym}|{dk}" in mset:
                mhit.append(row)
            elif row and row["pre"]:
                pre.append(row)
            elif row:
                rows.append(row)
    if mhit:
        per = {}
        for x in mhit:
            per[x["sym"]] = max(per.get(x["sym"], 0.0), x["usd"])
        rows.append({"key": f"{ex}|*|m", "ex": ex, "exN": NAMES.get(ex, ex), "sym": "*", "dir": "m", "part": False, "nets": [],
                     "since": int(_f(m.get("since"))), "usd": round(sum(per.values()), 2), "where": sorted(per)[:6], "n": len(per),
                     "pre": False, "age": int(max(0, now - _f(e.get("at"))))})
    return rows, pre


def view(doc: dict, hold: dict, dust: float, px: Callable, now: float) -> dict:
    rows, pre, exs = [], [], {}
    ctx = (hold, max(0.0, _f(dust)), px, now)
    for ex, e in sorted((doc.get("ex") or {}).items()):
        if not isinstance(e, dict):
            continue
        at = _f(e.get("at"))
        exs[ex] = {"at": int(at) or None, "ok": bool(at) and now - at <= FRESH, "err": str(e.get("err") or "")[:120], "gen": int(_f(e.get("gen")))}
        if at and now - at <= SHOW_MAX:
            new_rows, pre_rows = _ex_rows(ex, e, ctx)
            rows, pre = rows + new_rows, pre + pre_rows
    rows.sort(key=lambda x: (-x["usd"], x["key"]))
    pre.sort(key=lambda x: (-x["usd"], x["key"]))
    return {"v": 1, "rows": rows, "pre": [{k: x[k] for k in ("exN", "sym", "dir", "usd")} for x in pre[:80]], "preN": len(pre), "ex": exs}


def part(sb: object, rows: list, ex_gid: dict, conn: object, dust: float, now: float) -> dict:
    try:
        doc = load()
        if not doc.get("ex"):
            return {}
        wg = {int(r["key"][1:]) for r in rows if isinstance(r, dict) and str(r.get("key") or "")[:1] == "g" and str(r["key"])[1:].isdigit()
              and int(r["key"][1:]) not in ex_gid}
        kinds = _gid_kinds(conn, wg) if wg else {}
        pc = sb.__dict__.get("_cex_proof_cache")
        proof = pc[1] if isinstance(pc, tuple) and len(pc) == 2 and isinstance(pc[1], dict) else {}
        sb.spot.want_ex(set(doc["ex"]))
        return {"exHalt": view(doc, holdings(rows, ex_gid, kinds, proof), dust, sb.spot.ex_price, now)}
    except Exception as e:   # noqa: BLE001 [optional]
        calcguard.swallowed("exhalt:part", e)
        return {}


def health_items(now: float, path: str = None) -> list:
    out = []
    base = {"unit": "tj-exf", "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "exwallet"}
    for ex, e in sorted((load(path).get("ex") or {}).items()):
        if not isinstance(e, dict):
            continue
        nm, at, tr = NAMES.get(ex, ex), _f(e.get("at")), _f(e.get("try"))
        since = at or _f(e.get("f0")) or _f(e.get("err_at"))
        if (e.get("err") and since and now - since >= STALE_WARN) or (at and now - at >= SHOW_MAX):
            deny = "HTTP 401" in str(e.get("err")) or "HTTP 403" in str(e.get("err"))
            out.append(dict(base, cid=f"exwallet:{ex}", level="warn", title=f"{nm} 코인 입출금 상태 못 받음",
                            detail=(f"마지막 성공 {int((now - at) // 60)}분 전" if at else "아직 한 번도 못 받음") + (f" · {str(e.get('err'))[:120]}" if e.get("err") else ""),
                            action=("API 키에 조회 권한이 있는지 확인하세요(6시간마다 다시 시도) — 그동안 대시보드의 입출금 중지 표기·알림이 멈춰요" if deny
                                    else "10분마다 저절로 다시 받아요 — 계속되면 tj-exf 로그 '입출금 상태' 확인")))
        elif tr and now - _f(e.get("err_at")) < 86400 and at >= _f(e.get("err_at")):
            out.append(dict(base, cid=f"exwallet:{ex}", level="ok", title=f"{nm} 코인 입출금 상태", detail="정상"))
    return out


def _hm(ts, now) -> str:
    t = datetime.fromtimestamp(_f(ts) or now, KST)
    return t.strftime("%H:%M") if t.date() == datetime.fromtimestamp(now, KST).date() else t.strftime("%m-%d %H:%M")


def _open_text(rs, inp, now, fmt):
    money, link = fmt
    f = ((inp.get("out") or {}).get("fields")) or {}
    cur, rate = inp.get("cur") or "KRW", f.get("rate")
    r = max(rs, key=lambda x: x["usd"])
    exn, sym, t0 = r["exN"], r["sym"], _hm(min(x["since"] for x in rs), now)
    if r["dir"] == "m":
        txt = (f"🔴 {exn} 입출금 점검 중이에요 — 코인 여럿이 한꺼번에 막혔어요\n점검이 끝날 때까지 보내거나 빼지 마세요 — 끝나면 알려 드릴게요.\n"
               f"영향받는 내 코인 {r.get('n') or len(r['where'])}개({', '.join(r['where'][:4])}) · {money(r['usd'], cur, rate)} · {t0}부터")
    elif len({x["dir"] for x in rs}) == 2:
        txt = (f"🔴 {exn} {sym} 입출금이 모두 막혔어요\n보내지도 빼지도 마세요 — {exn} 공지를 확인하세요.\n"
               f"내 보유 {money(r['usd'], cur, rate)} · {' · '.join(r['where'][:3])} · {t0}부터")
    elif r["dir"] == "d":
        txt = (f"🔴 {exn} {sym} 입금이 막혔어요\n지금은 {exn} 입금 주소로 보내도 들어가지 않아요 — 팔려면 다른 곳을 쓰거나 풀릴 때까지 기다리세요.\n"
               f"내 보유 {money(r['usd'], cur, rate)} · {' · '.join(r['where'][:3])} · {t0}부터")
    else:
        txt = (f"🔴 {exn} {sym} 출금이 막혔어요\n{exn}에 있는 {sym} 코인을 밖으로 옮길 수 없어요 — {exn} 공지를 확인하세요(거래소 안에서 팔기는 될 수 있어요).\n"
               f"{exn} 보유 {money(r['usd'], cur, rate)} · {t0}부터")
    return AP.alert_line("EX_HALT", txt + link(inp, "dash"), key=r["key"], ex=r["ex"], sym=sym, dirs=sorted({x["dir"] for x in rs}))


def _clear_text(key, part=False, left=()):
    ex, sym, dk = (key.split("|") + ["", "", ""])[:3]
    exn = NAMES.get(ex, ex)
    if dk == "m" and left:
        txt = (f"✅ {exn} 점검은 끝났지만 {len(left)}개는 아직 막혀 있어요\n대시보드에서 하나씩 확인하세요.\n"
               + " · ".join(left[:8]) + (f" 외 {len(left) - 8}개" if len(left) > 8 else ""))
    else:
        txt = (f"✅ {exn} 입출금 점검이 끝났어요\n할 일은 없어요." if dk == "m"
               else f"✅ {exn} {sym} {DIR_KO.get(dk, '입출금')}이 {'일부 네트워크로 ' if part else ''}다시 돼요\n할 일은 없어요.")
    return AP.alert_line("EX_HALT", txt, key=key, ex=ex, sym=sym, resolved=True)


def _gone(inc, key, h, now, on):
    ex, sym, dk = (key.split("|") + ["", "", ""])[:3]
    e = (load().get("ex") or {}).get(ex)
    if not isinstance(e, dict):
        return True, None
    if not ((h.get("ex") or {}).get(ex) or {}).get("ok"):
        return False, None
    m = inc[key]
    if dk == "m":
        if isinstance(e.get("maint"), dict):
            m["hid"] = 1
            return False, None
        if not m.get("clr"):
            m["clr"] = int(now)
        if now - _f(m["clr"]) < CLEAR_HOLD:
            return False, None
        left = [f"{row['sym']} {DIR_KO.get(row['dir'], '')}" for row in h.get("rows") or [] if isinstance(row, dict) and row.get("ex") == ex
                and row.get("dir") in ("d", "w") and not row.get("part")]
        return True, (_clear_text(key, False, left) if m.get("at") and on and not m.get("hid") else None)
    r = ((e.get("c") or {}).get(sym) or {}).get(dk)
    st = r.get("st") if isinstance(r, dict) else None
    if st == "on":
        m["hid"] = 1
        return False, None
    if st == "unk":
        return True, None
    if st == "off":
        return False, None
    return True, (_clear_text(key, bool(isinstance(r, dict) and r.get("pn"))) if m.get("at") and on and not m.get("hid") else None)


def _gen_reset(mem, inc, h):
    gens = mem.setdefault("gen", {})
    for ex, x in (h.get("ex") or {}).items():
        g = int(_f((x or {}).get("gen")))
        if g and gens.get(ex) not in (None, g):
            for k in [k for k in inc if k.split("|", 1)[0] == ex]:
                inc.pop(k, None)
        if g:
            gens[ex] = g


def prod_exhalt(inp: dict, doc: dict, st: dict, now: float, conn: object, on: bool, fmt: tuple) -> list:
    out = inp.get("out") or {}
    h = (out.get("fields") or {}).get("exHalt")
    mem = st.setdefault("exhalt", {})
    inc = mem.setdefault("inc", {})
    if not out or now - _f(out.get("builtAt")) > 6 * 3600:
        return []
    if not isinstance(h, dict):
        cur_doc = load()
        if not cur_doc.get("ex") and not cur_doc.get("bad"):
            inc.clear()
        return []
    first = not mem.get("init")
    mem["init"] = 1
    _gen_reset(mem, inc, h)
    rows = {r["key"]: r for r in h.get("rows") or [] if isinstance(r, dict) and r.get("key") and not r.get("part")}
    opened = {}
    for k, r in rows.items():
        s0 = int(_f(r.get("since")))
        if isinstance(inc.get(k), dict) and int(_f(inc[k].get("s"))) == s0:
            inc[k].pop("clr", None)
            inc[k].pop("hid", None)
            continue
        mk = inc.get(f"{r['ex']}|*|m") if r.get("mt") else None
        at0 = (mk or {}).get("at", 0)
        quiet = first or not on or r.get("pre") or isinstance(mk, dict)
        inc[k] = {"s": s0, "at": at0 if quiet else int(now)}
        if not quiet:
            opened.setdefault((r["ex"], r["sym"]), []).append(r)
    res = []
    for k in [k for k in inc if k not in rows]:
        drop, line = _gone(inc, k, h, now, on)
        if drop:
            inc.pop(k, None)
        if line:
            res.append(line)
    return res + _open_lines(opened, inp, now, fmt)


BURST = 5


def _open_lines(opened, inp, now, fmt):
    by_ex, out = {}, []
    for (ex, _sym), rs in opened.items():
        by_ex.setdefault(ex, []).append(rs)
    for ex, groups in by_ex.items():
        if len(groups) < BURST:
            out += [_open_text(rs, inp, now, fmt) for rs in groups]
            continue
        money, link = fmt
        f = ((inp.get("out") or {}).get("fields")) or {}
        top = sorted((max(rs, key=lambda x: x["usd"]) for rs in groups), key=lambda x: -x["usd"])
        exn = top[0]["exN"]
        lst = " · ".join(f"{x['sym']} {DIR_KO.get(x['dir'], '')}" for x in top[:8]) + (f" 외 {len(top) - 8}개" if len(top) > 8 else "")
        txt = (f"🔴 {exn} 내 코인 {len(top)}개의 입출금이 한꺼번에 막혔어요\n보내거나 빼기 전에 {exn} 공지를 확인하세요 — 대시보드에 하나씩 보여요.\n"
               f"{lst} · 합 {money(sum(x['usd'] for x in top), inp.get('cur') or 'KRW', f.get('rate'))}")
        out.append(AP.alert_line("EX_HALT", txt + link(inp, "dash"), key=f"{ex}|*|n", ex=ex, n=len(top)))
    return out

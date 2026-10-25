from __future__ import annotations

import re
import sqlite3
import threading

import db as dbm
import paths

SIDE_K = "gid_ids"
MARK_K = "gid_ids_epoch"
UNKNOWN = "?"
NO_MARK = "-"
DICT_SECTIONS = ("cost_overrides", "cost_breakeven", "risk_overrides", "plans")
SECTION_KO = {"cost_overrides": "원가 지정", "cost_breakeven": "손익 0 처리", "risk_overrides": "스캠 판정 지정",
              "plans": "목표가·계획", "ignored": "무시"}
_RX_G = re.compile(r"g([0-9]{1,12})(?:f[0-9]{1,6})?")
_RX_IGN = re.compile(r"(?:unkh|gasnopx|noproc|unvlost|unv|be):([0-9]{1,12})|risk:g([0-9]{1,12})")
_LOCAL_LOCK = threading.Lock()
WRITE_LOCK_FN = None


def write_lock():
    return WRITE_LOCK_FN() if WRITE_LOCK_FN is not None else _LOCAL_LOCK


def gid_of(section: str, key: object) -> int | None:
    if not isinstance(key, str):
        return None
    m = (_RX_IGN if section == "ignored" else _RX_G).fullmatch(key)
    return int(m.group(1) or m.group(2)) if m else None


def entries(prefs: dict):
    for sec in DICT_SECTIONS:
        d = prefs.get(sec)
        if isinstance(d, dict):
            for k in d:
                g = gid_of(sec, k)
                if g is not None:
                    yield sec, k, g
    ig = prefs.get("ignored")
    if isinstance(ig, list):
        for k in ig:
            g = gid_of("ignored", k)
            if g is not None:
                yield "ignored", k, g


def ident_map(conn: "sqlite3.Connection", gid: int = None) -> dict:
    q = ("SELECT g.group_id, g.name, a.kind, a.chain, a.address FROM asset_groups g"
         " LEFT JOIN assets a ON a.group_id = g.group_id")
    rows = conn.execute(q + " WHERE g.group_id = ?", (int(gid),)).fetchall() if gid is not None else conn.execute(q).fetchall()
    names, parts = {}, {}
    for r in rows:
        gid_, name_ = int(r[0]), str(r[1])
        names[gid_] = name_
        if "#" in name_ and r[2] is not None:
            parts.setdefault(gid_, []).append(f"{r[2]}:{r[3] or ''}:{r[4] or ''}")
    return {gid_: name_ if "#" not in name_ else name_ + "|" + ",".join(sorted(parts.get(gid_, ()))) for gid_, name_ in names.items()}


def ledger_epoch(conn: "sqlite3.Connection") -> str:
    r = conn.execute("SELECT v FROM meta WHERE k = 'ledger_epoch'").fetchone()
    return str(r[0]) if r else ""


def _side(prefs: dict) -> dict:
    s = prefs.get(SIDE_K)
    return s if isinstance(s, dict) else {}


def resolve(prefs: dict, idents: dict, epoch: str):
    side = _side(prefs)
    mark = prefs.get(MARK_K)
    legacy_ok = mark is None or str(mark) == str(epoch or "")
    drop, hold, bind = set(), [], {}
    for sec, key, gid in entries(prefs):
        sk = f"{sec}:{key}"
        cur = idents.get(gid)
        st = side.get(sk)
        if not isinstance(st, str):
            st = bind[sk] = (cur if cur is not None else UNKNOWN) if legacy_ok else UNKNOWN
        if cur is not None and st == cur:
            continue
        drop.add((sec, key))
        if cur is not None:
            hold.append({"sec": sec, "key": key, "gid": gid, "was": st, "now": cur})
    if not drop:
        return prefs, hold, bind
    eff = dict(prefs)
    for sec in {sec_ for sec_, _key in drop}:
        if sec == "ignored":
            eff[sec] = [k_ for k_ in prefs[sec] if ("ignored", k_) not in drop]
        else:
            eff[sec] = {k_: v_ for k_, v_ in prefs[sec].items() if (sec, k_) not in drop}
    return eff, hold, bind


def bind_doc(prefs: dict, bind: dict, mark: str):
    side = _side(prefs)
    live = {f"{sec_}:{k_}" for sec_, k_, _gid in entries(prefs)}
    if not live and not side and MARK_K not in prefs:
        return None
    new = {k_: v_ for k_, v_ in side.items() if k_ in live}
    for k_, v_ in bind.items():
        if k_ in live and not isinstance(new.get(k_), str):
            new[k_] = v_
    if new == side and prefs.get(MARK_K) == mark:
        return None
    return dict(prefs, **{SIDE_K: new, MARK_K: mark})


def needs_write(prefs: dict, bind: dict, epoch: str) -> bool:
    return bind_doc(prefs, bind, epoch) is not None


def touch(prefs: dict, section: str, key: str) -> None:
    side = prefs.get(SIDE_K)
    if isinstance(side, dict):
        side.pop(f"{section}:{key}", None)


def bind_now(prefs: dict, section: str, key: str) -> None:
    touch(prefs, section, key)
    gid = gid_of(section, key)
    box = prefs.get(section)
    if gid is None or not (key in box if isinstance(box, (dict, list)) else False):
        return
    try:
        conn = dbm.open_db(paths.DB_PATH, readonly=True)
        try:
            cur = ident_map(conn, gid).get(gid)
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return
    if cur is not None:
        side = prefs.get(SIDE_K) if isinstance(prefs.get(SIDE_K), dict) else {}
        side[f"{section}:{key}"] = cur
        prefs[SIDE_K] = side


def applies(prefs: dict, section: str, key: str, conn: "sqlite3.Connection") -> bool:
    gid = gid_of(section, key)
    if gid is None:
        return True
    cur = ident_map(conn, gid).get(gid)
    if cur is None:
        return False
    eff, _hold, _bind = resolve({section: {key: True} if section != "ignored" else [key], SIDE_K: _side(prefs),
                             **({MARK_K: prefs[MARK_K]} if MARK_K in prefs else {})}, {gid: cur}, ledger_epoch(conn))
    return bool(eff.get(section))


def hold_sym(ident: str) -> str:
    if not ident or ident == UNKNOWN:
        return "확인 불가"
    return str(ident).split("|", 1)[0].split("#", 1)[0] or "?"


def diag(pi: dict) -> dict:
    hold = (pi or {}).get("hold") or []
    return {"n": len(hold), "top": [f"{SECTION_KO.get(h_['sec'], h_['sec'])} g{h_['gid']} {hold_sym(h_['was'])}→{hold_sym(h_['now'])}"
                                    for h_ in hold[:3]]}


def pend_rows(hold: list, ignored_u: set, t_str: str) -> list:
    out = []
    for h_ in hold or ():
        pkey = f"prefid:{h_['sec']}:{h_['key']}"
        if pkey in ignored_u:
            continue
        was_s, now_s = hold_sym(h_["was"]), hold_sym(h_["now"])
        out.append({
            "key": pkey, "t": t_str, "kind": "복원 뒤 확인 필요한 설정", "sym": now_s, "chain": "—",
            "onchain": f"{SECTION_KO.get(h_['sec'], h_['sec'])}(g{h_['gid']}) — 정할 때 자산 {was_s} · 지금 그 번호 {now_s}",
            "ex": "—", "gap": "원장을 되돌리거나 새로 만든 뒤 같은 번호를 다른 자산이 써서 이 설정은 계산·표시에 적용하지 않았어요",
            "why": "지금 자산에도 맞는 설정이면 그 코인에서 다시 지정하세요(다시 저장하면 지금 자산으로 묶여요). 아니면 무시해도 돼요 — 원장은 그대로예요.",
            "gkey": f"g{h_['gid']}", "costOv": None, "cands": [], "candsHint": "", "qty": 0, "usd": None})
    return out[::-1]


def health_item(wd: dict):
    pf = wd.get("prefid") if isinstance(wd, dict) and isinstance(wd.get("prefid"), dict) else None
    if pf is None:
        return None
    n_held = int(pf.get("n") or 0)
    return (("prefs:ident", "tj-web", f"복원 뒤 확인 필요한 설정 {n_held}칸" if n_held else "설정 자산 정체성", "warn" if n_held else "ok",
             " · ".join(str(x) for x in (pf.get("top") or [])[:3]) if n_held else "원가 지정·손익 0·스캠 지정·계획·무시가 모두 지금 원장의 같은 자산을 가리킴",
             "계산에서 뺀 설정 — 확인 필요 목록의 '복원 뒤 확인 필요한 설정' 줄: 지금 자산에도 맞으면 그 코인에서 다시 지정, 아니면 무시"),
            {"persist": 0, "resolve": 600, "notify": False, "remind": False, "kind": "ledger"})

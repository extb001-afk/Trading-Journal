from __future__ import annotations

import logging
import time

import statefile

log = logging.getLogger('tj-evm')

RING_DENSE = 12
RING_MAX = 24
WHY = "깊은 재편(reorg) — 확정 깊이보다 깊은 블록이 바뀜: 그 구간에 이미 기장한 거래가 사라진 갈래일 수 있음(검토 뒤 reorg_ack)"


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def settings(cc: dict) -> dict:
    cc = cc if isinstance(cc, dict) else {}
    return {"ack": _int(cc.get("reorg_ack")), "check": cc.get("reorg_check") is not False}


def held(cur: dict) -> dict:
    r = cur.get("_reorg") if isinstance(cur, dict) else None
    return r if isinstance(r, dict) else None


def hb_fact(cur: dict) -> dict:
    r = held(cur)
    return {"reorg": r} if r is not None else {}


def _acked(rec: dict, st: dict) -> bool:
    ack, frm = _int((st or {}).get("ack")), _int((rec or {}).get("from"))
    return ack is not None and frm is not None and ack >= frm


def ack_start(w: object, cc: dict) -> None:
    r = held(w.cursor)
    if r is not None and _acked(r, settings(cc)):
        log.warning("%s 깊은 재편 보류 해제(설정 reorg_ack %s ≥ 블록 %s · 탐색기 경로)", w.chain, cc.get("reorg_ack"), r.get("from"))
        w.cursor.pop("_reorg", None)
        statefile.atomic_write_json(w.cursor_path, w.cursor)


def ring_of(cur: dict) -> list:
    out = []
    raw = cur.get("_ring") if isinstance(cur.get("_ring"), list) else []
    for e in raw:
        if isinstance(e, list) and len(e) == 2 and _int(e[0]) is not None and isinstance(e[1], str) and e[1]:
            out.append([int(e[0]), e[1].lower()])
    return sorted(out)


def _hashes(w, blks) -> dict:
    if not blks:
        return {}
    try:
        res = w._batch([("eth_getBlockByNumber", [hex(int(b)), False]) for b in blks])
    except Exception as e:  # noqa: BLE001 [optional]
        log.info("%s 재편 확인(블록 해시) 실패 — 다음 주기: %s", w.chain, str(e)[:120])
        return {}
    out = {}
    for b, r in zip(blks, res or []):
        if not isinstance(r, dict) or not isinstance(r.get("hash"), str):
            continue
        try:
            n = int(r.get("number"), 16) if isinstance(r.get("number"), str) else _int(r.get("number"))
        except ValueError:
            n = None
        if n == int(b):
            out[int(b)] = r["hash"].lower()
    return out


def _rewind(w, rw: int) -> int:
    cur = w.cursor
    ns = cur.get("_ns") if isinstance(cur.get("_ns"), dict) else {}
    for m in ("_st_memo", "_bal_memo", "_snap_memo"):
        if isinstance(w.__dict__.get(m), dict):
            w.__dict__[m].clear()
    back, n = [], 0
    for a in w.wallets:
        v = _int(cur.get(a))
        if v is not None and v > rw:
            cur[a] = int(rw)
            n += 1
            if ns.pop(a, None) is not None:
                back.append(a)
    for k in ("_scan", "_peek_to", "_peek_wdone", "_peek_ns"):
        cur.pop(k, None)
    try:
        st = w._states([(a, int(rw)) for a in back]) if back else {}
        for a in back:
            ns[a] = [int(rw), int(st[(a, int(rw))][0]), str(int(st[(a, int(rw))][1])), 0, "0"]
    except Exception as e:  # noqa: BLE001 [fallback]
        log.warning("%s 재편 되감은 블록 %d 상태 못 읽음 — 네이티브 기준점 새로(로그 없는 이동은 잔고 대사): %s", w.chain, rw, str(e)[:120])
    return n


def _found(w, ring: list) -> bool:
    got = _hashes(w, [b for b, _h in ring])
    last = ring[-1]
    if last[0] not in got or got[last[0]] == last[1]:
        log.info("%s 재편 의심 블록 %d 다시 물으니 같거나 못 받음 — 그대로(다음 주기 다시 확인)", w.chain, last[0])
        return False
    bad = [b for b, h in ring if b in got and got[b] != h]
    good = [b for b, h in ring if got.get(b) == h and b < min(bad)]
    anc = max(good) if good else None
    rw = anc if anc is not None else max(0, _int(w.cursor.get("_start")) or 0)
    curs = [v for v in (_int(w.cursor.get(a)) for a in w.wallets) if v is not None]
    top = max([last[0]] + curs)
    n = _rewind(w, rw)
    prev = held(w.cursor)
    rec = {"at": int(time.time()), "from": int(rw) + 1, "top": int(top), "anc": anc, "n": 1, "why": WHY}
    if prev:
        rec["from"] = min(int(prev.get("from") or rec["from"]), rec["from"])
        rec["top"] = max(int(prev.get("top") or 0), rec["top"])
        rec["n"] = int(prev.get("n") or 1) + 1
    w.cursor["_reorg"] = rec
    w.cursor["_ring"] = [r for r in ring if anc is not None and r[0] <= anc]
    statefile.atomic_write_json(w.cursor_path, w.cursor)
    log.warning("★%s 깊은 재편 감지 — 공통 조상 %s · 영향 블록 %d~%d · 지갑 커서 %d개 되감음 · 대사 보류(config chains.%s.reorg_ack: %d 로 해제)★",
                w.chain, anc if anc is not None else "고리 밖(더 깊음)", rec["from"], rec["top"], n, w.chain, rec["from"])
    return True


def cycle_check(w: object, safe: int) -> int:
    st = getattr(w, "reorg_set", None) or settings({})
    cur = w.cursor
    if held(cur) is not None and _acked(cur["_reorg"], st):
        log.warning("%s 깊은 재편 보류 해제(설정 reorg_ack %s ≥ 블록 %s)", w.chain, st.get("ack"), cur["_reorg"].get("from"))
        cur.pop("_reorg", None)
    if not st.get("check", True):
        return safe
    ring = ring_of(cur)
    last = ring[-1] if ring else None
    want = ([last[0]] if last else []) + ([int(safe)] if not last or int(safe) > last[0] else [])
    got = _hashes(w, want)
    if not last:
        if int(safe) not in got:
            curs = [v for v in (_int(cur.get(a)) for a in w.wallets) if v is not None]
            return _miss(w, safe, min(curs) if curs else safe)
        cur["_ring"] = [[int(safe), got[int(safe)]]]
        w.__dict__["_reorg_miss"] = 0
        return safe
    if last[0] not in got or (int(safe) > last[0] and int(safe) not in got):
        return _miss(w, safe, last[0])
    if got[last[0]] != last[1]:
        if not _found(w, ring):
            return _miss(w, safe, last[0])
        if int(safe) in got:
            cur["_ring"] = _thin(ring_of(cur) + [[int(safe), got[int(safe)]]])
        return safe
    w.__dict__["_reorg_miss"] = 0
    if int(safe) > last[0]:
        cur["_ring"] = _thin(ring + [[int(safe), got[int(safe)]]])
    return safe


MISS_MAX = 3


def _miss(w, safe: int, last: int) -> int:
    n = int(w.__dict__.get("_reorg_miss") or 0) + 1
    if n < MISS_MAX:
        w.__dict__["_reorg_miss"] = n
        log.info("%s 재편 확인 못 함(블록 %d · %d번째) — 이번 주기 수집 상한 = 확인된 블록", w.chain, last, n)
        return min(int(safe), int(last))
    w.__dict__["_reorg_miss"] = 0
    w.cursor["_ring"] = []
    log.warning("%s 재편 확인 블록 %d 을 %d번 연속 못 받음 — 고리를 새로 시작(그 사이 깊은 재편은 감지 못 함)", w.chain, last, n)
    return safe


def _thin(ring: list) -> list:
    while len(ring) > RING_MAX:
        i = min(range(1, len(ring) - RING_DENSE), key=lambda j: ring[j + 1][0] - ring[j - 1][0])
        del ring[i]
    return ring


def health_items(add: object, obs: dict, units: object, open_ids: object, names: dict) -> None:
    if "tj-evm" not in units:
        return
    for chain, src in sorted((((obs.get("hb") or {}).get("evm") or {}).get("sources") or {}).items()):
        r = src.get("reorg") if isinstance(src, dict) else None
        cid = f"evm:reorg:{chain}"
        if not isinstance(r, dict) and cid not in open_ids:
            continue
        nm = names.get(chain, chain)
        if not isinstance(r, dict):
            add(cid, "tj-evm", f"{nm} 깊은 재편", "ok", "보류 해제됨", "", persist=0, resolve=600, remind=False, kind="ledger")
            continue
        anc = r.get("anc") if r.get("anc") is not None else "고리 밖"
        add(cid, "tj-evm", f"{nm} 깊은 재편(리오그) — 대사 보류", "warn",
            f"블록 {r.get('from')}~{r.get('top')} 사이 갈래가 바뀜(공통 조상 {anc} · {r.get('n') or 1}번째) — 수집기는 그 구간을 다시 훑었고"
            " (새 갈래 거래 반영) 이미 기장한 옛 갈래 거래는 원장에 그대로 · 그 체인 잔고 대사 보류",
            f"그 구간 내 거래를 탐색기에서 확인(사라진 거래는 손으로 정리) 뒤 config chains.{chain}.reorg_ack: {r.get('from')} + tj-evm 재시작",
            persist=0, resolve=600, remind=False, kind="ledger")

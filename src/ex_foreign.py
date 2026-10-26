"""Collectors for global exchanges (Binance, Bybit, OKX, KuCoin, Gate)."""
from __future__ import annotations
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuidlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acct_norm, config, envfile, paths, runtime, statefile  # noqa: E402
from envfile import acct_hist, acct_hist_slot, acct_progress  # noqa: E402
import cgplan, settings_store  # noqa: E402
import logs  # noqa: E402
if __name__ == "__main__":
    runtime.cpu_reserve_apply()
import unit_beat  # noqa: E402
import bf_engine  # noqa: E402
import depaddr  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
from exf_net import (  # noqa: F401
    _acct,
    _ACCT_TL,
    _add_to,
    _ak,
    _Bal,
    _BAL_SRC_HAD,
    _bal_src_had_load,
    _BAL_SRC_HAD_PATH,
    _BAL_SRC_OFF,
    _balance_rows,
    _BN_W_FAPI,
    _CLOCK,
    _CLOCK_ON,
    _COOL_MAPS,
    _COOL_ON,
    _cool_path,
    _CoolMap,
    _cv_fill,
    _DENY_SIGS,
    _DEP_DENIED,
    _err_body,
    _FUT_MULTI,
    _fut_path,
    _fut_write,
    _gov_buckets,
    _GOV_HOLD,
    _gov_prepare,
    _GOV_Q,
    _http_json_err,
    _HTTP_JSON_IMPL,
    _invalidate_balance_snapshot,
    _is_time_fix,
    _iso_epoch,
    _keep_view,
    _LATE_CYC,
    _late_tag,
    _mark_seen,
    _PartialConvertRows,
    _POLL_HINT,
    _px_safe,
    _recon_hold,
    _recon_hold_clear,
    _rl_check,
    _rl_key,
    _RL_OFF,
    _rows_to_emit,
    _save_state,
    _srv_ms,
    _sub_bal,
    _WD_OFF,
    _WD_TOUCH,
    _xm,
    CLOCK_MAX_OFF_MS,
    CLOCK_PATH_NAME,
    CLOCK_SRC,
    COOL_PATH_NAME,
    DAY,
    DENY_COOL_SEC,
    ERR_BODY_MAX,
    fut_rcpt,
    http_json,
    HTTP_MAX_BYTES,
    HTTP_MAX_BYTES_PATH,
    norm_fill,
    norm_row,
    PACE,
    PEND_FINAL,
    POLL_SEC,
    PX_BN_FAIL_MAX,
    PX_CALLS_MAX,
    RateLimited,
    ResponseTooLarge,
    SEEN_NOTIME,
)

log = logging.getLogger("tj-exf")
_exf_fmt = logging.Formatter("%(asctime)s %(levelname)s [tj-exf] %(message)s")
_exf_out = logging.StreamHandler(sys.stdout)
_exf_out.setLevel(logging.INFO)
_exf_out.addFilter(lambda r: r.levelno < logging.WARNING)
_exf_out.setFormatter(_exf_fmt)
_exf_err = logging.StreamHandler(sys.stderr)
_exf_err.setLevel(logging.WARNING)
_exf_err.setFormatter(_exf_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_exf_out, _exf_err])
logs.add_secret_filter([_exf_out, _exf_err])
logs.install_excepthook()

_quiet_n = {}


def _env() -> dict:
    return envfile.read_env_file()


SUB_EX = envfile.SUB_EXCHANGES
SUB_MAX = envfile.SUB_MAX


class _acct_ctx:

    def __init__(self, tag: str):
        self.tag, self.prev = tag or "", None

    def __enter__(self):
        self.prev = getattr(_ACCT_TL, "tag", "")
        _ACCT_TL.tag = self.tag
        return self

    def __exit__(self, *a):
        _ACCT_TL.tag = self.prev
        return False


sub_key_names = envfile.sub_key_names


def acct_envs(env: dict, ex: str, need=None) -> list:
    return [a for a in envfile.exchange_accounts(env, ex, need or (FETCHERS.get(ex) or (None, ()))[1])
            if (ex, a[0]) not in _IDENT_BAD and (ex, a[0]) not in _DUP]


def sub_tags(env: dict, ex: str) -> list:
    return [t for t, _e in acct_envs(env, ex)[1:]]


class _AcctState(dict):
    root = None


def acct_state(state: dict, ex: str, tag: str, now: int = None) -> dict:
    a9 = state.setdefault(ex, {"seen": {}, "backfilled_until": 0}).setdefault("accts", {})
    st = a9.get(tag)
    if not isinstance(st, dict):
        st = a9[tag] = {"seen": {}, "backfilled_until": 0, "dest_bf": int(now or time.time()), "added": int(now or time.time())}
    return st


def _slot_uid(ex: str, tag: str, kfp: str, kperm: dict, state: dict = None):
    rec = kperm.get(f"{ex}_sub{tag[1:]}" if tag else ex) if isinstance(kperm, dict) else None
    uid = str(rec["uid"]) if isinstance(rec, dict) and rec.get("uid") and rec.get("kfp") == kfp else None
    cur = ((state.get(ex) or {}).get("accts") or {}).get(tag) if tag and not uid and isinstance(state, dict) else None
    if isinstance(cur, dict) and cur.get("uid") and cur.get("kfp") == kfp:
        uid = str(cur["uid"])
    return uid if uid and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uid) else None


def acct_dups(env: dict, ex: str, need: tuple, kperm: dict, state: dict = None) -> dict:
    first, parent = {}, {}

    def root(tag):
        while parent[tag] != tag:
            tag = parent[tag]
        return tag
    for tag, env_a in envfile.exchange_accounts(env, ex, need):
        parent[tag] = tag
        kfp = cgplan.kfp(env_a.get(need[0]))
        ids = [("k", kfp)] + [("u", u) for u in (_slot_uid(ex, tag, kfp, kperm, state),) if u]
        hits = {root(first[i]) for i in ids if i in first}
        if hits:
            keep = next(t for t in parent if t in hits)
            for t in hits | {tag}:
                parent[t] = keep
        for i in ids:
            first.setdefault(i, tag)
    return {tag: root(tag) for tag in parent if root(tag) != tag}


def _dup_scan(env: dict, kperm: dict, state: dict, only: str = None) -> None:
    for key in [k for k in _DUP if only is None or k[0] == only]:
        del _DUP[key]
    for dex, (_fetch, dneed) in FETCHERS.items():
        if only is None or dex == only:
            _DUP.update({(dex, dtag): first for dtag, first in acct_dups(env, dex, dneed, kperm, state).items()})


def _legacy_same(cur: dict, rec, kfp: str) -> tuple:
    prog = acct_progress(cur)
    kat = rec.get("kat", rec.get("at")) if isinstance(rec, dict) else None
    if not acct_hist(cur) or not isinstance(kat, (int, float)) or isinstance(kat, bool):
        return True, None
    if (rec.get("kkfp") or rec.get("kfp") or kfp) != kfp:
        return True, None
    if kat < prog:
        return True, None
    pk, pkat = rec.get("pkfp"), rec.get("pkat")
    return False, (pk if isinstance(pk, str) and re.fullmatch(r"[0-9a-f]{8}", pk) and isinstance(pkat, (int, float)) and pkat < prog else None)


def acct_ident(state: dict, ex: str, tag: str, key: str, kperm: dict, now: int, active: dict = None) -> bool:
    subs = state.setdefault(ex, {"seen": {}, "backfilled_until": 0}).setdefault("accts", {})
    kfp = cgplan.kfp(key)
    uid = _slot_uid(ex, tag, kfp, kperm)
    backs = [t for t, v in sorted(subs.items()) if t.startswith(tag + "@") and isinstance(v, dict)
             and ((uid and str(v.get("uid") or "") == uid) or (v.get("kfp") == kfp and not (uid and v.get("uid") and str(v["uid"]) != uid)))]
    back_tag = backs[0] if backs else None
    cur = subs.get(tag)
    old_kfp, same = None, False
    if isinstance(cur, dict):
        if uid and cur.get("uid"):
            same = str(cur["uid"]) == uid
        elif cur.get("kfp"):
            same = cur["kfp"] == kfp
        else:
            same, old_kfp = _legacy_same(cur, kperm.get(f"{ex}_sub{tag[1:]}") if isinstance(kperm, dict) else None, kfp)
    if not acct_hist(subs.get(back_tag) if back_tag else (cur if same else None)):
        other = acct_hist_slot(subs, tag, uid, kfp, active, ex)
        if other is not None:
            raise RuntimeError(f"같은 계정 이력이 {other} 칸에 있음(원래 칸에 넣으세요 · 여기서 다시 받으면 두 번 기장)")
    map_keep = tag in ((((envfile.ident_read().get("ex") or {}).get(ex) or {}).get("fut_keep")) or ())
    if isinstance(cur, dict):
        if same and not back_tag:
            new = dict(cur, kfp=kfp, **({"uid": uid} if uid and not cur.get("uid") else {}), **({"fut_keep": 1} if map_keep else {}))
            if new == cur:
                return False
            cur.update(new)
            return True
    ops = []
    legacy = isinstance(cur, dict) and not same and not cur.get("uid") and not cur.get("kfp")
    keep = map_keep or legacy or any(isinstance(v, dict) and v.get("fut_keep") for v in ([cur] if isinstance(cur, dict) and not same else []) + [subs[t] for t in backs])
    if isinstance(cur, dict) and not same:
        if legacy:
            cur = dict(cur, **({"kfp": old_kfp} if old_kfp else {}))
        old_tag = f"{tag}@u{cur['uid']}" if cur.get("uid") else (f"{tag}@k{cur['kfp']}" if cur.get("kfp") else f"{tag}@x{acct_progress(cur)}")
        subs[old_tag] = dict(cur, **({"fut_keep": 1} if keep else {}))
        ops.append([tag, old_tag])
        log.warning("%s 서브 칸 %s 에 다른 계정 키 — 옛 계정 상태는 %s 로 물려 두고(마지막 잔고 0 아니면 대사 보류) 새 계정은 처음부터 받음", ex, tag, old_tag)
    if back_tag:
        ops.append([back_tag, tag])
    for extra in backs[1:]:
        ops.append([extra, tag, "rows"])
        del subs[extra]
    subs[tag] = subs.pop(back_tag) if back_tag else {"seen": {}, "backfilled_until": 0, "dest_bf": int(now), "added": int(now)}
    subs[tag].update({"kfp": kfp, **({"uid": uid} if uid else {}), **({"fut_keep": 1} if keep else {})})
    if keep:
        ops = [[tag, tag, "unraw"]] if not same else []
    if ops:
        state[ex].setdefault("fut_retag", []).extend(ops)
    return True


def _fut_retag_pending(state: dict, ex: str) -> None:
    todo = state.get(ex, {}).get("fut_retag") if isinstance(state.get(ex), dict) else None
    while isinstance(todo, list) and todo:
        op = list(todo[0])
        if op[2:] == ["unraw"]:
            _fut_unraw(ex, op[0])
        else:
            _fut_retag(ex, op[0], op[1], raw=op[2:] != ["rows"])
        todo.pop(0)
        if not todo:
            state[ex].pop("fut_retag", None)
        try:
            _save_state(state)
        except (Exception, SystemExit):   # noqa: BLE001 [fallback]
            todo.insert(0, op)
            state[ex]["fut_retag"] = todo
            raise


_DUP = {}
_IDENT_BAD = set()


def _ident_ok(state: dict, ex: str, acct: tuple, need, kperm: dict, now: int, active: dict = None) -> bool:
    tag, env_a = acct
    if not tag:
        return True
    try:
        if acct_ident(state, ex, tag, env_a.get(need[0]), kperm, now, active):
            _save_state(state)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [isolate]
        _IDENT_BAD.add((ex, tag))
        log.warning("%s[%s] 서브 계정 정체 확인 실패(이번 주기 빼냄 · 그 거래소 잔고 승격 보류): %s", ex, tag, _xm(repr(e))[:140])
        return False
    try:
        _fut_retag_pending(state, ex)
    except (Exception, SystemExit) as e:   # noqa: BLE001 [isolate]
        ops = state.get(ex, {}).get("fut_retag") or [[tag, tag]]
        _IDENT_BAD.update((ex, str(t).split("@")[0]) for op in ops for t in op[:2])
        log.warning("%s 서브 선물 딱지 옮기기 실패(%s · 대기 칸 이번 주기 빼냄): %s", ex, [op[:2] for op in ops], _xm(repr(e))[:140])
    return (ex, tag) not in _IDENT_BAD


def _ident_all(state: dict, ex: str, env: dict, need, kperm: dict, now: int) -> None:
    slots = envfile.exchange_accounts(env, ex, need)
    live = {tag: (_slot_uid(ex, tag, cgplan.kfp(env_a.get(need[0])), kperm), cgplan.kfp(env_a.get(need[0]))) for tag, env_a in slots if tag}
    for slot in slots:
        _ident_ok(state, ex, slot, need, kperm, now, live)


def _main_gate(state: dict, env: dict, kperm: dict) -> dict:
    out, dirty, now = dict(env), False, int(time.time())
    for ex, (_fn, need) in FETCHERS.items():
        on, kfp = all(env.get(k) for k in need), cgplan.kfp(env.get(need[0]))
        stx = state.setdefault(ex, {"seen": {}, "backfilled_until": 0}) if on else state.get(ex)
        if not isinstance(stx, dict):
            continue
        hold = stx.get("main_hold")
        try:
            how, rec, slot = envfile.main_ident(stx, _slot_uid(ex, "", kfp, kperm), kfp, ex) if on else ("off", None, None)
        except Exception as e:   # noqa: BLE001 [fallback]
            log.warning("%s 메인 칸 계정 확인 실패(종전대로 받음): %s", ex, _xm(repr(e))[:140])
            continue
        if how == "hold":
            if not isinstance(hold, dict) or hold.get("slot") != slot:
                stx["main_hold"], dirty = {"slot": slot, "at": now}, True
                log.error("★%s 메인 칸에 %s 칸에서 기록을 받던 계정 키 — 같은 거래 두 번 기장이라 이 거래소 수집 보류(원래 메인 키를 다시 넣으면 풀림)★", ex, slot)
            for k in [k for n in range(SUB_MAX + 1) for k in (sub_key_names(ex, n, need) if n else need)]:
                out.pop(k, None)
            _invalidate_balance_snapshot(ex)
            continue
        if stx.pop("main_hold", None) is not None:
            stx["main_hold_off"], dirty = now, True
        if how == "new":
            log.warning("%s 메인 칸 계정이 바뀜 — 다른 칸 이력 계정은 아니라 종전대로 받음(다른 칸에서 옮겨 온 계정이면 원래 칸에 넣으세요)", ex)
        if rec is not None and rec != stx.get("main_id"):
            stx["main_id"], dirty = rec, True
    if dirty:
        _save_state(state)
    return out


def acct_vstate(state: dict, ex: str, tag: str, now: int = None) -> _AcctState:
    v9 = _AcctState({ex: acct_state(state, ex, tag, now)})
    v9.root = state
    return v9


def _acct_id(ex: str, tag: str, v):
    s9 = str(v or "")
    p9 = f"{ex}:"
    if not tag or not s9.startswith(p9) or s9.startswith(f"{p9}{tag}:"):
        return v
    return f"{p9}{tag}:{s9[len(p9):]}"


class _AcctWriter:

    def __init__(self, inner, ex: str, tag: str, st: dict):
        self.w, self.ex, self.tag, self.st = inner, ex, tag, st

    def append(self, rec):
        if not isinstance(rec, dict) or rec.get("exchange") != self.ex or rec.get("kind") not in ("ex_snapshot", "exf_fills"):
            return self.w.append(rec)
        seen9 = self.st.get("seen") if isinstance(self.st.get("seen"), dict) else {}
        r2 = dict(rec)
        fix9 = 0
        for k9 in ("deposits", "withdraws"):
            if isinstance(rec.get(k9), list):
                rows9 = []
                for r in rec[k9]:
                    r = dict(r) if isinstance(r, dict) else r
                    if isinstance(r, dict):
                        if not rec.get("lc") and _is_time_fix(r, seen9):
                            if not r.get("late"):
                                fix9 += 1
                            r["late"] = 1
                        r["uuid"] = _acct_id(self.ex, self.tag, r.get("uuid"))
                        r["acct"] = self.tag
                    rows9.append(r)
                r2[k9] = rows9
        if isinstance(rec.get("fills"), list):
            r2["fills"] = [dict(f, id=_acct_id(self.ex, self.tag, f.get("id")), acct=self.tag) if isinstance(f, dict) else f for f in rec["fills"]]
        if fix9:
            _invalidate_balance_snapshot(self.ex)
        return self.w.append(r2)


def _clock_restore() -> int:
    p9 = paths.state(CLOCK_PATH_NAME)
    try:
        d = statefile.read_json(p9, {}) if os.path.exists(p9) else {}
    except SystemExit:
        d = {}
    n = 0
    for ex, v in ((d.get("ex") or {}).items() if isinstance(d, dict) and isinstance(d.get("ex"), dict) else ()):
        try:
            off9, at9 = int(v["off"]), float(v["at"])
        except (KeyError, TypeError, ValueError):
            continue
        if ex in CLOCK_SRC and abs(off9) <= CLOCK_MAX_OFF_MS:
            _CLOCK[ex] = {"off": off9, "at": at9, "rtt": int(v.get("rtt") or 0)}
            n += 1
    _CLOCK_ON[0] = True
    return n


from exf_okx import (  # noqa: F401
    _bal_okx,
    _fut_okx,
    _okx_fills_floor,
    _okx_get,
    _okx_notional,
    _px_okx,
    convert_okx,
    fetch_okx,
    fills_okx,
)


DEST_FIELDS = ("address", "tag", "network")


from exf_binance import (  # noqa: F401
    _bal_binance,
    _binance_caller,
    _binance_signed,
    _bn_deriv_get,
    _bn_split,
    _BN_UNI,
    _fut_binance,
    _px_binance,
    binance_fills_t0,
    BN_FIRST_SWEEP_SEC,
    BN_UNI_NAME,
    convert_binance,
    convert_binance_dust,
    dividend_binance,
    fetch_binance,
    fills_binance,
    fills_binance_replay,
)
from exf_bybit import (  # noqa: F401
    _bal_bybit,
    _bb_hold_keep,
    _BB_UNI,
    _bybit_get,
    _bybit_internal_rows,
    _fut_bybit,
    _px_bybit,
    BB_INT_DENY,
    BB_TLOG_TYPES,
    convert_bybit,
    fetch_bybit,
    fills_bybit,
    PX_BB_EX_OFF_MS,
)
from exf_gate import (  # noqa: F401
    _bal_gate,
    _gate_get,
    _gate_range,
    convert_gate,
    fetch_gate,
    fills_gate,
)


def bybit_internal_pass(env: dict, state: dict, writer, now: int, window: int) -> str:
    need = FETCHERS.get("bybit", (None, ()))[1]
    if "bybit" not in FETCHERS or not all(env.get(k) for k in need) or "bybit" not in state:
        return "skip"
    st = state["bybit"]
    if not st.get("backfilled_until"):
        return "wait"
    if time.time() < float(_WD_OFF.get(_ak("bybit") + ":internal", 0) or 0):
        return "cooldown"
    it = st.setdefault("int", {})
    lo_want = int(now - window)
    ext = st.get("ext") or {}
    if ext.get("wd_from"):
        lo_want = min(lo_want, int(ext["wd_from"]))
    tg9 = bf_engine.SINCE.target("bybit")
    if tg9:
        lo_want = min(lo_want, int(tg9))
    hist_done = bool(it.get("lo")) and int(it["lo"]) <= lo_want + 60
    t0 = max(lo_want, min(int(now - 7 * DAY), int(it.get("until") or lo_want))) if hist_done else lo_want
    try:
        rows = _bybit_internal_rows(env, t0, now)
    except Exception as e:   # noqa: BLE001 [fallback]
        msg = _xm(repr(e))[:200]
        if any(k in msg for k in _DENY_SIGS + BB_INT_DENY):
            _WD_OFF[_ak("bybit") + ":internal"] = time.time() + DENY_COOL_SEC
            log.warning("bybit 내부 이체 입금 조회 권한 없음 — 6h 뒤 재시도(수집 하한 유지 · 권한이 생기면 빠진 구간부터): %s", msg[:120])
            return "denied"
        log.warning("bybit 내부 이체 입금 조회 실패(다음 주기): %s", msg[:140])
        return "error"
    seen, seen_txids, seen_dest = st.setdefault("seen", {}), st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
    new_d = _rows_to_emit(rows, seen, seen_txids)
    for r in new_d:
        r["late"] = 1
    if new_d:
        _invalidate_balance_snapshot("bybit")
        lb9 = f"bybit:int:{int(now)}:{uuidlib.uuid4().hex[:10]}"
        nch9 = (len(new_d) + 499) // 500
        for k9, i in enumerate(range(0, len(new_d), 500)):
            writer.append(_late_tag({"v": 1, "kind": "ex_snapshot", "exchange": "bybit", "ts": int(now), "deposits": new_d[i:i + 500],
                                     "withdraws": [], "lb": lb9, "lbi": k9, "lbn": nch9}, "bybit", force=True))
        _mark_seen(new_d, seen, seen_txids, seen_dest, st.setdefault("pend_ts", {}))
    if not hist_done:
        it["lo"] = int(lo_want)
        log.info("bybit 내부 이체 입금 이력(%s~): %d건 · 신규 방출 %d", time.strftime("%Y-%m-%d", time.gmtime(lo_want)), len(rows), len(new_d))
    it["until"] = int(now)
    state["bybit"] = st
    _save_state(state)
    return "ok"


from exf_coinbase import (  # noqa: F401
    bal_coinbase,
    convert_coinbase,
    fetch_coinbase,
    fills_coinbase,
)
from exf_kucoin import (  # noqa: F401
    _bal_kucoin,
    _kucoin_fut_get,
    _kucoin_get,
    _kucoin_pub_get,
    convert_kucoin,
    fetch_kucoin,
    fills_kucoin,
)


def _wd_window(st: dict, now: int, window: int) -> tuple:
    t0 = max(now - window, min(now - 7 * DAY, int(st.get("backfilled_until") or now - window)))
    hold = st.get("dep_hold")
    floor = now - window
    ew = (st.get("ext") or {}).get("wd_from") if isinstance(st.get("ext"), dict) else None
    if isinstance(ew, int) and ew < floor:
        floor = ew
    dt0 = max(floor, min(t0, int(hold))) if isinstance(hold, int) else t0
    return t0, dt0


DEP_HOLD_V = 1


def _dep_hold_migrate(ex: str, st: dict, now: int, window: int) -> bool:
    if ex != "gate" or st.get("dep_hold_v") == DEP_HOLD_V:
        return False
    floor = int(now - window)
    ew = (st.get("ext") or {}).get("wd_from") if isinstance(st.get("ext"), dict) else None
    if isinstance(ew, int) and ew < floor:
        floor = ew
    h = st.get("dep_hold")
    st["dep_hold"] = min(int(h), floor) if isinstance(h, int) else floor
    st["dep_hold_v"] = DEP_HOLD_V
    log.info("gate 입금 보류 표식 1회 이관 — 입금을 %s 부터 다시 확인(배포 전 권한 거부로 빠졌을 수 있는 입금 · late 흡수)",
             time.strftime("%Y-%m-%d", time.gmtime(st["dep_hold"])))
    return True


def _dep_hold_update(ex: str, st: dict, dep_t0: int):
    if _ak(ex) in _DEP_DENIED:
        h = st.get("dep_hold")
        st["dep_hold"] = min(int(h), int(dep_t0)) if isinstance(h, int) else int(dep_t0)
    else:
        st.pop("dep_hold", None)


from exf_bithumb import (  # noqa: F401
    _bal_bithumb,
    _BITHUMB_ASC_CACHE,
    _bithumb_caller,
    _bithumb_ext_fills,
    _bithumb_ext_part,
    _bithumb_fill,
    _bithumb_get,
    _bithumb_orders_state,
    _bithumb_retime,
    _bithumb_row_ts,
    _bithumb_track,
    BITHUMB_REG_BUDGET,
    fetch_bithumb,
    fetch_bithumb_krw,
    fills_bithumb,
)


FETCHERS = {
    "binance": (fetch_binance, envfile.EX_KEYS["binance"]),
    "bybit": (fetch_bybit, envfile.EX_KEYS["bybit"]),
    "okx": (fetch_okx, envfile.EX_KEYS["okx"]),
    "kucoin": (fetch_kucoin, envfile.EX_KEYS["kucoin"]),
    "gate": (fetch_gate, envfile.EX_KEYS["gate"]),
    "bithumb": (fetch_bithumb, envfile.EX_KEYS["bithumb"]),
    "coinbase": (fetch_coinbase, envfile.EX_KEYS["coinbase"]),
}


def bn_gap_step(env, st: dict, ext: dict, stop_at: int, now: int, deadline: float, emit, save) -> bool:
    lo9 = int((ext.get("bn_replay") or {}).get("hi") or ext.get("hi0") or stop_at)
    gp = ext.get("bn_gap")
    if not isinstance(gp, dict) or int(gp.get("lo") or 0) != lo9:
        gp = ext["bn_gap"] = {"lo": lo9, "hi": int(now), "pos": {}, "done": []}
        save()
    try:
        fin = FILL_REPLAY["binance"](env, st.get("fills") or {}, gp, deadline, emit, save)
    except Exception as e:  # noqa: BLE001 [fallback]
        ext["fills_err"] = _xm(repr(e))[:160]
        save()
        return False
    if fin:
        ext["bn_gap_done"] = int(time.time())
        ext.pop("fills_err", None)
        save()
    return bool(fin)


CV_DENY = ("retCode=10005", "retCode=10003", "retCode=10004", "okx 50120", "okx 50030", "okx 50125", "okx 50119",
           '"code":-2015', '"code":-1002',
           "kucoin 400007", "kucoin 400006", "HTTPError 404", "HTTP 404")


CONVERT_FETCHERS = {"binance": convert_binance, "okx": convert_okx, "bybit": convert_bybit,
                    "kucoin": convert_kucoin, "gate": convert_gate, "coinbase": convert_coinbase}
CONVERT_EXTRA = {"binance": (("dust", convert_binance_dust), ("div", dividend_binance))}
CONVERT_LABEL = {"cv": "간편전환", "cv_dust": "소액 자산 BNB 전환", "cv_div": "배당·에어드랍·Earn 이자 지급 내역"}
_DIV_OFF = [False]
CV_RETRY_SEC = 1800
DUST_IDLE_SEC = 24 * 3600


def convert_rows(ex, env, fst: dict, now: int, window: int) -> list:
    out = []
    fn = CONVERT_FETCHERS.get(ex)
    if fn is not None:
        out += _convert_src(ex, "cv", fn, env, fst, now, window)
    for key9, fn9 in CONVERT_EXTRA.get(ex, ()):
        if key9 == "div" and _DIV_OFF[0]:
            _recon_hold_clear(fst, "cv:cv_div")
            continue
        out += _convert_src(ex, "cv_" + key9, fn9, env, fst, now, window)
    if ex == "binance" and out:
        fst["extra_bases"] = sorted(set(fst.get("extra_bases") or []) | {f["base"] for f in out if f.get("base")}
                                    | {f["quote"] for f in out if f.get("quote")})
    return out


def _convert_src(ex, key, fn, env, fst: dict, now: int, window: int) -> list:
    cv = fst.setdefault(key, {})
    label = CONVERT_LABEL.get(key, key)
    ck9 = f"{_ak(ex)}:{key}"
    hk9 = "cv:" + key
    unres9 = hk9 in (fst.get("hold_since") or {})
    if time.time() < max(float(cv.get("off_until") or 0), float(_CV_OFF.get(ck9, 0) or 0) if _COOL_ON[0] else 0.0):
        if unres9:
            _recon_hold(fst, hk9, now, f"{label} 조회 실패 뒤 재시도 대기")
        return []
    if key == "cv_dust" and cv.get("bf") and now - int(cv.get("until") or 0) < DUST_IDLE_SEC \
            and not (fst.get("bn_last_dirty") or []) and not unres9:
        return []
    lo = int(now - window)
    t0 = lo if not cv.get("bf") else max(lo, min(int(now - 3 * DAY), int(cv.get("until") or lo)))
    tg9 = bf_engine.SINCE.target(ex)
    ext_lo = int(tg9) if tg9 and int(tg9) < lo else None
    if ext_lo is not None and int(cv.get("bf_lo") or lo) > ext_lo + 60:
        t0 = ext_lo
    try:
        rows = fn(env, t0, now)
    except RateLimited:
        _recon_hold(fst, hk9, now, f"{label} 조회 레이트 제한")
        return []
    except Exception as e:  # noqa: BLE001 [fallback]
        msg = _xm(repr(e))[:200]
        deny = any(k in msg for k in _DENY_SIGS + CV_DENY)
        cv["off_until"] = time.time() + (DENY_COOL_SEC if deny else CV_RETRY_SEC)
        _CV_OFF[ck9] = cv["off_until"]
        cv["err"], cv["err_at"] = msg, int(now)
        held9 = False
        if deny:
            _recon_hold_clear(fst, hk9)
        else:
            held9 = _recon_hold(fst, hk9, now, f"{label} 조회 실패")
        log.warning("%s %s 내역 조회 생략(%s — 체결·잔고 수집은 계속%s): %s", ex, label,
                    "권한 없음 · 6h 뒤 재시도" if deny else "30분 뒤 재시도", " · 성공 때까지 잔고 대사 보류" if held9 else "", msg[:160])
        return []
    if isinstance(rows, _PartialConvertRows):
        msg = rows.error
        deny = any(k in msg for k in _DENY_SIGS + CV_DENY)
        cv["off_until"] = time.time() + (DENY_COOL_SEC if deny else CV_RETRY_SEC)
        _CV_OFF[ck9] = cv["off_until"]
        cv["err"], cv["err_at"] = msg, int(now)
        if deny:
            _recon_hold_clear(fst, hk9)
        else:
            _recon_hold(fst, hk9, now, f"{label} 일부만 조회")
        return list(rows)
    if not cv.get("bf"):
        log.info("%s %s 과거분 백필 완료: %d건 (창 %s~)", ex, label, len(rows), time.strftime("%Y-%m-%d", time.gmtime(t0)))
    cv["bf"] = cv.get("bf") or int(now)
    if ext_lo is not None and t0 == ext_lo:
        cv["bf_lo"] = int(ext_lo)
        log.info("%s %s 과거 창 확장: %d건 (%s~)", ex, label, len(rows), time.strftime("%Y-%m-%d", time.gmtime(ext_lo)))
    cv["until"] = int(now)
    cv.pop("err", None)
    cv.pop("off_until", None)
    _CV_OFF.pop(ck9, None)
    _recon_hold_clear(fst, hk9)
    return rows


def _cool_restore():
    now = time.time()
    try:
        d = statefile.read_json(_cool_path(), {}) if os.path.exists(_cool_path()) else {}
    except SystemExit:
        d = {}
    n = 0
    for kind, m in _COOL_MAPS.items():
        dict.clear(m)
        src = d.get(kind) if isinstance(d, dict) else None
        for k, v in (src.items() if isinstance(src, dict) else ()):
            try:
                if float(v) <= now:
                    continue
            except (TypeError, ValueError):
                continue
            kk = tuple(k.split("|", 1)) if kind == "bal" and "|" in k else k
            dict.__setitem__(m, kk, float(v))
            n += 1
    _COOL_ON[0] = True
    if n:
        log.info("쿨다운 복원 %d건(권한 거부·레이트 제한 — 만료 후 자동 재시도)", n)
    return n


BAL_FETCHERS = {"binance": _bal_binance, "bybit": _bal_bybit, "okx": _bal_okx,
                "kucoin": _bal_kucoin, "gate": _bal_gate, "bithumb": _bal_bithumb, "coinbase": bal_coinbase}


FILL_FETCHERS = {
    "binance": fills_binance, "bybit": fills_bybit, "okx": fills_okx,
    "kucoin": fills_kucoin, "gate": fills_gate, "bithumb": fills_bithumb, "coinbase": fills_coinbase,
}
FILL_REPLAY = {"binance": fills_binance_replay}


def _seen_state(v) -> str:
    return str(v or "").split("#", 1)[0]


class _CycleWriter:

    def __init__(self, writer, state: dict):
        self.w, self.state = writer, state

    def append(self, rec):
        if isinstance(rec, dict) and rec.get("kind") in ("ex_snapshot", "exf_fills") and not rec.get("lc"):
            ex = str(rec.get("exchange") or "")
            st = self.state.get(ex) if isinstance(self.state, dict) else None
            seen = st.get("seen") if isinstance(st, dict) and isinstance(st.get("seen"), dict) else {}
            fix = 0
            for r in (rec.get("deposits") or []) + (rec.get("withdraws") or []):
                if _is_time_fix(r, seen):
                    if not r.get("late"):
                        fix += 1
                    r["late"] = 1
            if fix:
                _invalidate_balance_snapshot(ex)
            _late_tag(rec, ex)
        return self.w.append(rec)


PEND_RECHECK_SEC = 6 * 3600
PEND_MAX_QUERIES = 28
PEND_MAX_WINDOWS = 3


def _pend_nq(v) -> int:
    try:
        return int(v[2]) if isinstance(v, list) and len(v) > 2 else 0
    except (TypeError, ValueError):
        return 0


def pending_recheck_pass(env: dict, state: dict, writer, now: int, window: int, fetchers=None) -> dict:
    out = {}
    for ex, (fn, need) in (fetchers or FETCHERS).items():
        if not all(env.get(k) for k in need) or ex not in state:
            continue
        st = state[ex]
        if not st.get("backfilled_until"):
            continue
        rc = st.setdefault("pend_rc", {})
        if now - int(rc.get("at") or 0) < PEND_RECHECK_SEC:
            continue
        seen = st.setdefault("seen", {})
        pend = st.setdefault("pend_ts", {})
        reg_lo = max(now - window, min(now - 7 * DAY, int(st.get("backfilled_until") or now)))
        scan = not st.get("pend_scan")
        legacy = {u for u, s9 in seen.items() if str(s9).upper() not in PEND_FINAL and u not in pend}
        wins = []
        if scan:
            ext = st.get("ext") or {}
            lo9 = int(now - window)
            if ext.get("wd_from"):
                lo9 = min(lo9, int(ext["wd_from"]))
            wins.append((min(lo9, reg_lo), now))
        else:
            for u in [u for u, v in pend.items() if not isinstance(v, list) or len(v) < 2
                      or _seen_state(seen.get(u)).upper() in PEND_FINAL or _pend_nq(v) >= PEND_MAX_QUERIES]:
                v9 = pend.pop(u)
                if _seen_state(seen.get(u)).upper() not in PEND_FINAL and isinstance(v9, list) and len(v9) >= 2:
                    log.info("%s 비종결 입출금 %s 상태 재확인 %d회 — 거래소가 그대로라 추적 종료(%s)", ex, u, _pend_nq(v9), seen.get(u))
            olds = sorted((int(v[0]), _pend_nq(v)) for v in pend.values() if int(v[0]) < reg_lo)
            allw = []
            for t9, nq9 in olds:
                if allw and t9 - DAY <= allw[-1][1]:
                    allw[-1] = [allw[-1][0], max(allw[-1][1], t9 + DAY), min(allw[-1][2], nq9)]
                else:
                    allw.append([t9 - DAY, t9 + DAY, nq9])
            wins = [(w9[0], w9[1]) for w9 in sorted(allw, key=lambda w9: (w9[2], w9[0]))[:PEND_MAX_WINDOWS]]
        rc["at"] = int(now)
        if not wins:
            if scan:
                st["pend_scan"] = int(now)
            _save_state(state)
            continue
        rows_w, rows_d = [], []
        int_ok = None
        try:
            for a9, b9 in wins:
                w9, d9 = fn(env, int(a9), int(min(b9, now)))
                rows_w += w9
                rows_d += d9
                if ex == "bybit" and not scan and any(str(u).startswith("bybit:int:") and isinstance(v, list) and len(v) >= 2
                                                      and a9 <= int(v[0]) <= b9 for u, v in pend.items()):
                    if time.time() < float(_WD_OFF.get(_ak("bybit") + ":internal", 0) or 0):
                        int_ok = False
                        continue
                    try:
                        rows_d += _bybit_internal_rows(env, int(a9), int(min(b9, now)))
                        int_ok = True if int_ok is None else int_ok
                    except Exception as e9:   # noqa: BLE001 [fallback]
                        int_ok = False
                        if any(k in _xm(repr(e9)) for k in _DENY_SIGS + BB_INT_DENY):
                            _WD_OFF[_ak("bybit") + ":internal"] = time.time() + DENY_COOL_SEC
                        log.warning("bybit 내부 입금 상태 재확인 실패(그 행만 다음 회): %s", _xm(repr(e9))[:120])
        except Exception as e:   # noqa: BLE001 [isolate]
            rc["err"] = _xm(repr(e))[:160]
            _save_state(state)
            log.warning("%s 비종결 입출금 재확인 실패(6시간 뒤 다시): %s", ex, rc["err"])
            out[ex] = "error"
            continue
        rc.pop("err", None)
        if not scan:
            for u, v in pend.items():
                if str(u).startswith("bybit:int:") and int_ok is False:
                    continue
                if isinstance(v, list) and len(v) >= 2 and any(a9 <= int(v[0]) <= b9 for a9, b9 in wins):
                    pend[u] = [int(v[0]), int(v[1]), _pend_nq(v) + 1]
        seen_txids, seen_dest = st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
        new_w = _rows_to_emit(rows_w, seen, seen_txids, seen_dest)
        new_d = _rows_to_emit(rows_d, seen, seen_txids)
        for r in new_w + new_d:
            r["late"] = 1
        if new_w or new_d:
            _invalidate_balance_snapshot(ex)
            both = sorted([("d", r) for r in new_d] + [("w", r) for r in new_w], key=lambda x: (str(x[1].get("currency") or ""), x[1]["uuid"]))
            lb9 = f"{ex}:pend:{int(now)}:{uuidlib.uuid4().hex[:10]}"
            nch9 = (len(both) + 499) // 500
            for k9, i in enumerate(range(0, len(both), 500)):
                ch9 = both[i:i + 500]
                writer.append(_late_tag({"v": 1, "kind": "ex_snapshot", "exchange": ex, "ts": int(now),
                                         "deposits": [r for t9, r in ch9 if t9 == "d"], "withdraws": [r for t9, r in ch9 if t9 == "w"],
                                         "lb": lb9, "lbi": k9, "lbn": nch9}, ex, force=True))
        _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, pend)
        if scan:
            for r in rows_w + rows_d:
                if r["uuid"] in legacy and str(r.get("state") or "").upper() not in PEND_FINAL and r["uuid"] not in pend:
                    c9 = _iso_epoch(r.get("created_at"))
                    if c9:
                        pend[r["uuid"]] = [c9, int(now)]
            miss9 = sum(1 for u in legacy if u not in pend and _seen_state(seen.get(u)).upper() not in PEND_FINAL)
            st["pend_scan"] = int(now)
            log.info("%s 입출금 저장 창 재조회(1회): 행 %d · 상태 변경·신규 방출 %d · 비종결 추적 %d%s", ex, len(rows_w) + len(rows_d),
                     len(new_w) + len(new_d), len(pend), f" · 거래소가 더는 안 주는 비종결 {miss9}건" if miss9 else "")
        elif new_w or new_d:
            log.info("%s 비종결 입출금 재확인: 상태 변경 방출 %d건(추적 %d)", ex, len(new_w) + len(new_d), len(pend))
        _save_state(state)
        out[ex] = len(new_w) + len(new_d)
    return out


def dest_backfill_pass(env: dict, state: dict, writer, now: int, window: int, fetchers=None) -> dict:
    out = {}
    for ex, (fn, need) in (fetchers or FETCHERS).items():
        if not all(env.get(k) for k in need):
            continue
        st = state.setdefault(ex, {"seen": {}, "backfilled_until": 0})
        if st.get("dest_bf"):
            continue
        fail9 = st.get("dest_bf_fail") or {}
        if now < int(fail9.get("next") or 0):
            out[ex] = "backoff"
            continue
        lo = int(now - window)
        ext = st.get("ext") or {}
        if ext.get("wd_from"):
            lo = min(lo, int(ext["wd_from"]))
        try:
            w_rows, _d = fn(env, lo, now)
        except Exception as e:  # noqa: BLE001 [isolate]
            n9 = int(fail9.get("n") or 0) + 1
            wait9 = min(12 * 3600, 1800 * (2 ** (n9 - 1)))
            st["dest_bf_fail"] = {"n": n9, "next": int(now + wait9)}
            state[ex] = st
            _save_state(state)
            log.warning("%s 출금 목적지 소급 실패 %d회(%d분 뒤 재시도): %s", ex, n9, wait9 // 60, repr(e)[:140])
            out[ex] = "error"
            continue
        seen, _seen_txids, seen_dest = st["seen"], st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
        new_w = [r for r in w_rows if r["uuid"] in seen and r.get("address") and not seen_dest.get(r["uuid"])]
        for i in range(0, len(new_w), 500):
            writer.append({"v": 1, "kind": "ex_snapshot", "exchange": ex, "ts": now,
                           "deposits": [], "withdraws": new_w[i:i + 500]})
        for r in new_w:
            seen_dest[r["uuid"]] = True
        st["dest_bf"] = now
        st.pop("dest_bf_fail", None)
        state[ex] = st
        _save_state(state)
        log.info("%s 출금 목적지 소급: 조회 %d · 보강 방출 %d", ex, len(w_rows), len(new_w))
        out[ex] = len(new_w)
    return out


def krw_backfill_pass(env: dict, state: dict, writer, now: int, window: int) -> str:
    need = FETCHERS.get("bithumb", (None, ()))[1]
    if "bithumb" not in FETCHERS or not all(env.get(k) for k in need):
        return "skip"
    st = state.setdefault("bithumb", {"seen": {}, "backfilled_until": 0})
    lo = int(now - window)
    t9 = bf_engine.SINCE.target("bithumb")
    if t9:
        lo = min(lo, int(t9))
    ext = st.get("ext") or {}
    if ext.get("wd_from"):
        lo = min(lo, int(ext["wd_from"]))
    if int(st.get("krw_bf_from") or (1 << 62)) <= lo:
        return "done"
    try:
        w_rows, d_rows = fetch_bithumb_krw(env, lo, now, require_complete=True)
    except Exception as e:  # noqa: BLE001 [fallback]
        log.warning("bithumb 원화 입출금 소급 실패(다음 주기): %s", repr(e)[:140])
        return "error"
    seen, seen_txids, seen_dest = st["seen"], st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
    new_w = _rows_to_emit(w_rows, seen, seen_txids, seen_dest)
    new_d = _rows_to_emit(d_rows, seen, seen_txids)
    if new_w or new_d:
        _invalidate_balance_snapshot("bithumb")
        writer.append({"v": 1, "kind": "ex_snapshot", "exchange": "bithumb", "ts": now, "deposits": new_d, "withdraws": new_w})
        _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, st.setdefault("pend_ts", {}))
    st["krw_bf_from"] = lo
    state["bithumb"] = st
    _save_state(state)
    log.info("bithumb 원화 입출금 소급(%s~): 입금 %d · 출금 %d (신규 방출 %d)", time.strftime("%Y-%m-%d", time.gmtime(lo)),
             len(d_rows), len(w_rows), len(new_w) + len(new_d))
    return "ok"


WD_FLY_MAX = 24 * 3600
_WD_TERMINAL = set(PEND_FINAL) | {"CANCELED", "REFUNDED"}
SNAP_AGREE_REL = 1e-4
SNAP_AGREE_ABS = 1e-6
_SNAP_MISS = {}
SNAP_MISS_CAP = 6
_SNAP_MISS_ST = {}


def _wd_inflight(rows, now: int) -> list:
    out = []
    for r in rows or ():
        if not isinstance(r, dict) or str(r.get("state") or "").upper() in _WD_TERMINAL:
            continue
        c9 = _iso_epoch(r.get("created_at"))
        if c9 and int(now) - c9 <= WD_FLY_MAX:
            out.append(r)
    return out


def _snap_flat(snap: dict, ex: str = ""):
    off_fiat = acct_norm.ex_off_ledger(ex)
    out = {}
    for fld, pfx in (("balances", ""), ("debts", "부채 ")):
        d = snap.get(fld) if isinstance(snap, dict) else None
        if d is None:
            continue
        if not isinstance(d, dict):
            return None
        for k, v in d.items():
            ku = str(k).upper()
            if ku in off_fiat:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return None
            if fv != fv:
                return None
            out[pfx + ku] = out.get(pfx + ku, 0.0) + fv
    return out


def _snap_agree(a: dict, b: dict, ex: str = ""):
    fa, fb = _snap_flat(a, ex), _snap_flat(b, ex)
    if fa is None or fb is None:
        return False, "형식 오류"
    pa, pb = (a or {}).get("fut_part"), (b or {}).get("fut_part")
    if isinstance(pa, dict) and isinstance(pb, dict):
        for fx9, p9 in ((fa, pa), (fb, pb)):
            for k9, v9 in p9.items():
                ku9 = str(k9).upper()
                try:
                    fv9 = float(v9)
                except (TypeError, ValueError):
                    return False, "형식 오류"
                if ku9 in fx9:
                    fx9[ku9] -= fv9
    for k in sorted(set(fa) | set(fb)):
        x, y = fa.get(k, 0.0), fb.get(k, 0.0)
        m = max(abs(x), abs(y))
        if abs(x - y) > max(SNAP_AGREE_REL * m, SNAP_AGREE_ABS):
            return False, f"{k} {(y - x) / m * 100:+.4f}%" if m else k
    return True, ""


def _snap_miss_save():
    try:
        _SNAP_MISS_ST["seen"] = set(_SNAP_MISS_ST.get("seen") or ()) | set(_SNAP_MISS_ST.get("ex") or {})
        statefile.atomic_write_json(paths.state("exf_snap_miss.json"), {"v": 1, "ts": int(time.time()), "ex": _SNAP_MISS_ST.get("ex") or {},
                                                  "seen": sorted(_SNAP_MISS_ST["seen"])})
    except Exception as e:   # noqa: BLE001 [optional]
        log.warning("잔고 표본 불일치 상태 쓰기 실패: %s", repr(e)[:120])


def _snap_promote_ok(ex, prevp, snap9, now=None):
    now = int(time.time() if now is None else now)
    if "ex" not in _SNAP_MISS_ST:
        try:
            d9 = statefile.read_json(paths.state("exf_snap_miss.json"), {}) or {}
        except (Exception, SystemExit):   # noqa: BLE001 [fallback]
            d9 = {}
        _SNAP_MISS_ST["ex"] = {str(k): v for k, v in ((d9.get("ex") if isinstance(d9.get("ex"), dict) else {}) or {}).items() if isinstance(v, dict)}
        _SNAP_MISS_ST["seen"] = {str(x) for x in (d9.get("seen") if isinstance(d9.get("seen"), list) else [])}
    st9 = _SNAP_MISS_ST["ex"]
    agree9, why9 = _snap_agree(prevp, snap9, ex)
    if agree9:
        _SNAP_MISS.pop(ex, None)
        if st9.pop(ex, None) is not None:
            _SNAP_MISS_ST.setdefault("seen", set()).add(ex)
            _snap_miss_save()
        return True, ""
    e9 = st9.setdefault(ex, {"since": now, "n": 0, "k": 0})
    e9["n"] = int(e9.get("n") or 0) + 1
    e9["k"] = int(e9.get("k") or 0) + 1
    e9["why"], e9["at"] = str(why9)[:80], now
    _SNAP_MISS[ex] = e9["n"]
    if e9["n"] % 6 == 1:
        log.info("%s 잔고 표본 불일치(%s · 연속 %d주기) — 승격 보류, 다음 주기 표본과 다시 비교", ex, why9, e9["n"])
    if e9["k"] >= SNAP_MISS_CAP:
        e9["k"], e9["forced"], e9["nf"] = 0, now, int(e9.get("nf") or 0) + 1
        _snap_miss_save()
        log.warning("★%s 잔고 표본이 %d주기 연속 달라(%s) — 일치 확인 없이 직전 표본 반영(대사가 멈춰 총자산이 굳지 않게 · 상태 패널 '잔고 표본 계속 다름')★",
                    ex, SNAP_MISS_CAP, why9)
        return "forced", why9
    _snap_miss_save()
    return False, why9


_FUT_OFF = _CoolMap("fut")
_CV_OFF = _CoolMap("cv")


def _fut_merge(ex, tags, denied=()):
    docs9 = []
    for tag in tags:
        p9 = paths.state(f"futraw_{ex}_{tag or 'main'}.json")
        try:
            d9 = statefile.read_json(p9, None) if os.path.exists(p9) else None
        except (Exception, SystemExit):   # noqa: BLE001 [fallback]
            log.warning("%s 선물 계정 원본 읽기 실패(%s) — 정본 갱신 보류", ex, tag or "main")
            return
        if isinstance(d9, dict) and d9.get("ts"):
            docs9.append((tag, d9))
    if not docs9:
        return
    evs9, seen9, pos9 = [], set(), []
    try:
        prev9 = statefile.read_json(paths.state(f"futures_{ex}.json"), {}) or {}
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
        log.warning("%s 선물 정본 읽기 실패 — 합치기 보류", ex)
        return
    bal9, bal_ok9, note9 = 0.0, True, None
    for tag, d9 in docs9:
        for r9 in d9.get("events") or []:
            if not isinstance(r9, dict):
                continue
            u9 = (tag, r9.get("uid") or f"{r9.get('t')}:{r9.get('kind')}:{r9.get('amount')}:{r9.get('symbol')}")
            if u9 in seen9:
                continue
            seen9.add(u9)
            evs9.append(dict(r9, acct=tag) if tag else r9)
        for q9 in d9.get("positions") or []:
            pos9.append(dict(q9, acct=tag) if tag and isinstance(q9, dict) else q9)
        w9 = d9.get("wallet") if isinstance(d9.get("wallet"), dict) else {}
        note9 = note9 or w9.get("note")
        b9 = w9.get("balance")
        if isinstance(b9, (int, float)) and not isinstance(b9, bool):
            bal9 += float(b9)
        elif b9 is not None:
            bal_ok9 = False
    live_ids = _fut_live_ids(ex, [t9 for t9, _d in docs9 if t9])
    for prev_row in (prev9.get("events") if isinstance(prev9, dict) else None) or []:
        if isinstance(prev_row, dict):
            key = (prev_row.get("acct") or "", prev_row.get("uid") or f"{prev_row.get('t')}:{prev_row.get('kind')}:{prev_row.get('amount')}:{prev_row.get('symbol')}")
            if "@" in key[0] and any((tag, key[1]) in seen9 for tag, ids in live_ids.items() if ids & _fut_name_ids(key[0])):
                continue
            if key not in seen9:
                seen9.add(key)
                evs9.append(prev_row)
    nums9 = [isinstance((d9.get("wallet") or {}).get("balance"), (int, float)) for _t, d9 in docs9]
    wallet9 = {"balance": round(bal9, 8) if any(nums9) and bal_ok9 else None, "note": note9}
    ts9 = min(int(d9.get("ts") or 0) for _t, d9 in docs9)
    cov9 = min(int(d9.get("inc_cov_ts") if isinstance(d9.get("inc_cov_ts"), (int, float)) and not isinstance(d9.get("inc_cov_ts"), bool)
                   else d9.get("ts") or 0) for _t, d9 in docs9)
    got9 = {t9 for t9, _d in docs9}
    if any(t9 not in got9 and t9 not in denied for t9 in tags):
        cov9 = 0
    main9 = next((d9 for t9, d9 in docs9 if not t9), {})
    out9 = {"ts": ts9, "wallet": wallet9, "positions": pos9, "events": sorted(evs9, key=lambda r: r.get("t") or 0),
            "cursor": main9.get("cursor"), "accts": [t9 or "main" for t9, _d in docs9]}
    if cov9 < ts9:
        out9["inc_cov_ts"] = cov9
    statefile.atomic_write_json(paths.state(f"futures_{ex}.json"), out9)


def _fut_name_ids(tag: str) -> set:
    return {f"{k[0]}:{v}" for k, v in (envfile.acct_key({}, tag) or {}).items()}


def _fut_live_ids(ex: str, tags: list) -> dict:
    try:
        subs = ((statefile.read_json(paths.state("exf_state.json"), {}) or {}).get(ex) or {}).get("accts") or {}
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
        subs = {}
    return {t: {f"{k[0]}:{v}" for k, v in (envfile.acct_key(subs.get(t)) or {}).items()} for t in tags if isinstance(subs, dict)}


def _fut_retag(ex, old, new, raw=True):
    can = paths.state(f"futures_{ex}.json")
    doc = statefile.read_json(can, {}) if os.path.exists(can) else {}
    if isinstance(doc, dict) and any(isinstance(r, dict) and r.get("acct") == old for r in doc.get("events") or []):
        have = {r.get("uid") for r in doc.get("events") or [] if isinstance(r, dict) and r.get("acct") == new and r.get("uid")}
        evs = [dict(r, acct=new) if isinstance(r, dict) and r.get("acct") == old else r for r in doc.get("events") or []
               if not (isinstance(r, dict) and r.get("acct") == old and r.get("uid") in have)]
        statefile.atomic_write_json(can, dict(doc, events=evs, positions=[q for q in doc.get("positions") or [] if not (isinstance(q, dict) and q.get("acct") == old)]))
    src = paths.state(f"futraw_{ex}_{old}.json")
    if os.path.exists(src):
        if raw:
            statefile.atomic_write_json(paths.state(f"futraw_{ex}_{new}.json"), statefile.read_json(src, {}))
        os.remove(src)


def _fut_unraw(ex, tag):
    src = paths.state(f"futraw_{ex}_{tag}.json")
    if not os.path.exists(src):
        return
    got = statefile.read_json(src, {}) or {}
    can = paths.state(f"futures_{ex}.json")
    doc = statefile.read_json(can, {}) if os.path.exists(can) else {}
    doc = doc if isinstance(doc, dict) else {}

    def key(r):
        return r.get("uid") or f"{r.get('t')}:{r.get('kind')}:{r.get('amount')}:{r.get('symbol')}"
    evs = list(doc.get("events") or [])
    have = {(r.get("acct") or "", key(r)) for r in evs if isinstance(r, dict)}
    rows = got.get("events") if isinstance(got, dict) and isinstance(got.get("events"), list) else []
    add = [dict(r, acct=tag) for r in rows if isinstance(r, dict) and (tag, key(r)) not in have]
    if add:
        statefile.atomic_write_json(can, dict(doc, events=sorted(evs + add, key=lambda r: (r.get("t") or 0) if isinstance(r, dict) else 0)))
    os.remove(src)


def _fut_seed_main(ex):
    raw9 = paths.state(f"futraw_{ex}_main.json")
    can9 = paths.state(f"futures_{ex}.json")
    if not os.path.exists(can9):
        return
    d9 = statefile.read_json(can9, {}) or {}
    if not isinstance(d9, dict):
        return
    old_raw = statefile.read_json(raw9, {}) if os.path.exists(raw9) else None
    if isinstance(old_raw, dict) and ("accts" in d9 or int(d9.get("ts") or 0) < int(old_raw.get("ts") or 0)):
        return
    d9 = dict(d9)
    d9["events"] = [r for r in d9.get("events") or [] if isinstance(r, dict) and not r.get("acct")]
    have = {r.get("uid") for r in d9["events"] if r.get("uid")}
    d9["events"] = sorted(d9["events"] + [r for r in (old_raw or {}).get("events") or [] if isinstance(r, dict) and r.get("uid") and r["uid"] not in have],
                          key=lambda r: r.get("t") or 0)
    d9["positions"] = [q for q in d9.get("positions") or [] if isinstance(q, dict) and not q.get("acct")]
    d9.pop("accts", None)
    statefile.atomic_write_json(raw9, d9)


def futures_snapshot_all(env):
    for ex, fn, need in (("binance", _fut_binance, ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET")),
                         ("bybit", _fut_bybit, ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET")),
                         ("okx", _fut_okx, ("TJ_OKX_KEY", "TJ_OKX_SECRET",
                                            "TJ_OKX_PASSPHRASE"))):
        accts9 = acct_envs(env, ex, need)
        if not accts9:
            continue
        multi9 = len(accts9) > 1
        _FUT_MULTI[ex] = multi9
        try:
            if multi9:
                _fut_seed_main(ex)
        except (Exception, SystemExit) as e:   # noqa: BLE001 [isolate]
            log.warning("%s 선물 여러 계정 모드 준비 실패(다음 주기): %s", ex, _xm(repr(e))[:140])
            _FUT_MULTI[ex] = False
            continue
        denied9 = set()
        for tag9, env_a in accts9:
            with _acct_ctx(tag9):
                exl9 = ex if not tag9 else f"{ex}[{tag9}]"
                if time.time() < _FUT_OFF.get(_ak(ex), 0):
                    denied9.add(tag9)
                    continue
                try:
                    fn(env_a)
                except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
                    msg = _xm(repr(e))
                    if any(k in msg for k in ("HTTP 401", "HTTP 403", "HTTPError 401",
                                              "HTTPError 403", '"code":-2015', '"code":-1002')):
                        _FUT_OFF[_ak(ex)] = time.time() + DENY_COOL_SEC
                        denied9.add(tag9)
                        log.error("★%s 선물 스냅샷 6h 비활성(권한/IP 불일치) — 만료 후 자동 재시도: %s★",
                                  exl9, msg[:120])
                    else:
                        log.warning("%s 선물 스냅샷 실패(다음 주기): %s", exl9, msg[:140])
        if multi9:
            try:
                _fut_merge(ex, [t9 for t9, _e in accts9], denied=denied9)
            except (Exception, SystemExit) as e:   # noqa: BLE001 [isolate]
                log.warning("%s 선물 계정 합치기 실패(다음 주기): %s", ex, _xm(repr(e))[:140])


def _lev_body(fn, rl_host=None):
    def f(*a, **k):
        try:
            return fn(*a, **k)
        except urllib.error.HTTPError as e:
            try:
                body = _err_body(e)[:300]
            except Exception:   # noqa: BLE001 [fallback]
                body = ""
            if rl_host and e.code == 403 and "too frequent" in body.lower():
                k9 = _rl_key(rl_host)
                _RL_OFF[k9] = max(float(_RL_OFF.get(k9, 0) or 0), time.time() + 600.0)
                log.warning("%s HTTP 403(IP 한도 — access too frequent) — 600초 동안 이 호스트 호출 중단", rl_host)
                raise RateLimited(f"{rl_host} HTTP 403 — access too frequent · 600초 백오프", 403) from None
            raise RuntimeError(f"HTTP {e.code}: {_xm(body)}") from None
    return f


def leverage_getters(env):
    return {
        "binance": {"sapi": lambda p, q=None: _binance_signed(env, p, q),
                    "fapi": lambda p, q=None: _bn_deriv_get(env, "fapi.binance.com", p, q),
                    "dapi": lambda p, q=None: _bn_deriv_get(env, "dapi.binance.com", p, q)},
        "bybit": {"get": _lev_body(lambda p, q=None: _bybit_get(env, p, q), rl_host="api.bybit.com")},
        "okx": {"get": _lev_body(lambda p, q=None: _okx_get(env, p, q))},
        "kucoin": {"get": _lev_body(lambda p: _kucoin_get(env, p)), "fut": _lev_body(lambda p: _kucoin_fut_get(env, p)), "pub": _lev_body(_kucoin_pub_get)},
        "gate": {"get": _lev_body(lambda p, q=None: _gate_get(env, p, q))},
    }


def leverage_pass(env, cfg=None):
    cfg = cfg if isinstance(cfg, dict) else {}
    xc9 = cfg.get("exf")
    if isinstance(xc9, dict) and xc9.get("leverage") is False:
        return None
    import leverage
    doc = leverage.collect(env, leverage_getters(env), now=int(time.time()), cycle_sec=config.exf_poll_sec(cfg),
                           fresh_sec=config.exf_fresh_sec(cfg), pace=lambda: time.sleep(PACE), log=log, cfg=cfg)
    leverage.write(doc)
    bad = [f"{p['ex']}:{p['product']}={p['status']}" for p in doc["products"] if p["status"] in ("error", "rate_limited")]
    if bad:
        log.info("레버리지·대출 스냅숏: 조회 실패 %d줄(%s) — 직전 값은 '낡음' 표시로 유지", len(bad), ", ".join(bad)[:200])
    return doc


EXT_CHUNK = 30 * DAY
EXT_BUDGET = 240
EXT_HARD_LIMIT = {("okx", "fills"): 90 * DAY}
EXT_HARD_LIMIT[("bybit", "fills")] = 730 * DAY - DAY
_EXT_LIMIT_RX = (
    (re.compile(r"(?:earlier|older) than (\d+) years?", re.I), 365),
    (re.compile(r"(?:earlier|older) than (\d+) days?", re.I), 1),
    (re.compile(r"more than (\d+) days", re.I), 1),
)
_EXT_LIMIT_STRICT = 2
_EXT_RANGE_WORDS = re.compile(r"range|interval|span|between|window|period|duration|start_?time|end_?time|startAt|endAt|"
                              r"time difference|gap|exceed|too (?:long|wide|large)|maximum", re.I)
EXT_SOFT_LIMIT_SEC = 7 * DAY


def ext_fills_floor(ex: str, now: int, ext: dict = None):
    cands = []
    if ex == "okx":
        cands.append(_okx_fills_floor(now))
    elif (ex, "fills") in EXT_HARD_LIMIT:
        cands.append(int(now - EXT_HARD_LIMIT[(ex, "fills")]))
    days = (ext or {}).get("fills_hard_days")
    if days:
        try:
            cands.append(int(now - float(days) * DAY + DAY))
        except (TypeError, ValueError):
            pass
    soft = (ext or {}).get("fills_soft_limit")
    if isinstance(soft, dict):
        try:
            if now < float(soft.get("until") or 0):
                cands.append(int(now - float(soft["days"]) * DAY + DAY))
        except (TypeError, ValueError, KeyError):
            pass
    return max(cands) if cands else None


def _learn_fills_limit(msg: str):
    return _fills_limit_kind(msg)[0]


def _fills_limit_kind(msg: str):
    m9 = msg or ""
    for i, (rx, mul) in enumerate(_EXT_LIMIT_RX):
        m = rx.search(m9)
        if m:
            try:
                d9 = int(m.group(1)) * mul
            except ValueError:
                return None, None
            if i >= _EXT_LIMIT_STRICT and _EXT_RANGE_WORDS.search(m9):
                return None, None
            return d9, ("strict" if i < _EXT_LIMIT_STRICT else "soft")
    return None, None


def ext_trigger_target(now: int, window: int):
    target9 = bf_engine.SINCE.target(None) or (now - window)
    if any(int(bf_engine.SINCE.target(ex9) or target9) < now - window for ex9 in FETCHERS):
        return int(target9)
    return None


def extension_pass(env: dict, state: dict, writer, target: int, now: int, window: int):
    import threading as _th
    from concurrent.futures import ThreadPoolExecutor as _TPE
    wlock = _th.Lock()
    active = [ex for ex, (fn, need) in FETCHERS.items() if all(env.get(k) for k in need) and ex in state]
    prog = bf_engine.progress("exf")
    tag_x = _acct()

    def _save():
        with wlock:
            for i9 in range(3):
                try:
                    snap9 = json.loads(json.dumps(getattr(state, "root", None) or state, ensure_ascii=False))
                    break
                except RuntimeError:
                    if i9 == 2:
                        raise
            statefile.atomic_write_json(paths.state("exf_state.json"), snap9)

    def one(ex, target=target):
        with _acct_ctx(tag_x):
            return one_(ex, target)

    def one_(ex, target=target):
        target = min(int(target), int(bf_engine.SINCE.target(ex) or target))
        if target >= now - window:
            return
        fn = FETCHERS[ex][0]
        st = state[ex]
        ext = st.setdefault("ext", {})
        if ext.get("fills_hard_days") and ext.get("fills_hard_src") != "strict":
            try:
                d9 = int(float(ext["fills_hard_days"]))
            except (TypeError, ValueError):
                d9 = 0
            ext.pop("fills_hard_days", None)
            if d9 > 0:
                ext["fills_soft_limit"] = {"days": d9, "until": int(now + EXT_SOFT_LIMIT_SEC)}
            log.info("%s 옛 체결 보존 한도(%s일 · 출처 미상) → 7일 임시 한도로 전환(만료 뒤 다시 시도)", ex, d9)
            _save()
        if ext.get("target") != target:
            ext["target"] = int(target)
            ext["n_emit"] = 0
            ext.setdefault("wd_from", int(now - window))
            ext.setdefault("fills_from", int(now - window))
        hi0 = int(ext.setdefault("hi0", max(int(ext["wd_from"]), int(ext["fills_from"]), int(now - window))))
        deadline = time.time() + EXT_BUDGET
        n_w = n_f = 0
        while ext["wd_from"] > target and time.time() < deadline:
            a, b = max(int(target), int(ext["wd_from"]) - EXT_CHUNK), int(ext["wd_from"])
            try:
                w_rows, d_rows = fn(env, a, b)
            except Exception as e:  # noqa: BLE001 [fallback]
                ext["wd_err"] = _xm(repr(e))[:160]
                break
            seen, seen_txids, seen_dest = st["seen"], st.setdefault("seen_txids", {}), st.setdefault("seen_dest", {})
            if _ak(ex) in _DEP_DENIED:
                h9 = st.get("dep_hold")
                st["dep_hold"] = min(int(h9), int(a)) if isinstance(h9, int) else int(a)
            new_w = _rows_to_emit(w_rows, seen, seen_txids, seen_dest)
            new_d = _rows_to_emit(d_rows, seen, seen_txids)
            if new_w or new_d:
                _invalidate_balance_snapshot(ex)
                with wlock:
                    writer.append({"v": 1, "kind": "ex_snapshot", "exchange": ex, "ts": int(time.time()),
                                   "deposits": new_d, "withdraws": new_w, "ext": True})
                _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, st.setdefault("pend_ts", {}))
                n_w += len(new_w) + len(new_d)
            eb_new = {str(r.get("currency") or "").upper() for r in (w_rows or []) + (d_rows or []) if r.get("currency")}
            if eb_new:
                f9 = st.setdefault("fills", {})
                eb0 = set(f9.get("extra_bases") or [])
                if not eb_new <= eb0:
                    f9["extra_bases"] = sorted(eb0 | eb_new)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(new_w) + len(new_d)
            ext["wd_from"] = a
            ext.pop("wd_err", None)
            _save()
        floor = ext_fills_floor(ex, now, ext)
        stop_at = max(int(target), floor) if floor else int(target)
        if floor and floor > target:
            ext["fills_limit"] = f"API 이력 한도: {time.strftime('%Y-%m-%d', time.gmtime(floor))} 이전 체결은 이 API 로 불가"
        if ex == "binance" and ext["fills_from"] > stop_at and time.time() < deadline:
            rp = ext.get("bn_replay")
            if not isinstance(rp, dict) or int(rp.get("lo") or 0) != int(stop_at):
                rp = ext["bn_replay"] = {"lo": int(stop_at), "hi": int(ext["fills_from"]), "pos": {}, "done": []}
                _save()

            def _emit(rows):
                nonlocal n_f
                _invalidate_balance_snapshot(ex)
                with wlock:
                    for i in range(0, len(rows), 500):
                        writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                       "fills": rows[i:i + 500], "ext": True})
                n_f += len(rows)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
            try:
                fin = FILL_REPLAY["binance"](env, st.get("fills") or {}, rp, deadline, _emit, _save)
            except Exception as e:  # noqa: BLE001 [fallback]
                ext["fills_err"] = _xm(repr(e))[:160]
                fin = False
            if fin:
                ext["fills_from"] = int(stop_at)
                ext.pop("fills_err", None)
            _save()
        if ex == "binance" and ext["fills_from"] <= stop_at and not ext.get("bn_gap_done") and time.time() < deadline:
            def _emit_g(rows):
                nonlocal n_f
                _invalidate_balance_snapshot(ex)
                with wlock:
                    for i in range(0, len(rows), 500):
                        writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                       "fills": rows[i:i + 500], "ext": True})
                n_f += len(rows)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
            bn_gap_step(env, st, ext, stop_at, now, deadline, _emit_g, _save)
        while ex != "binance" and ext["fills_from"] > stop_at and time.time() < deadline:
            a, b = max(stop_at, int(ext["fills_from"]) - EXT_CHUNK), int(ext["fills_from"])
            if ex == "bithumb" and "bithumb" in FILL_FETCHERS:
                def _emit_bt(rows):
                    nonlocal n_f
                    _invalidate_balance_snapshot(ex)
                    with wlock:
                        for i in range(0, len(rows), 500):
                            writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                           "fills": rows[i:i + 500], "ext": True})
                    n_f += len(rows)
                    ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
                try:
                    fin = _bithumb_ext_fills(_bithumb_caller(env), st.get("fills") or {}, ext, a, b, deadline, _emit_bt, _save)
                except Exception as e:  # noqa: BLE001 [fallback]
                    ext["fills_err"] = _xm(repr(e))[:160]
                    _save()
                    break
                if not fin:
                    ext.pop("fills_err", None)
                    _save()
                    break
                ext.pop("bt_scan", None)
                ext["fills_from"] = a
                ext.pop("fills_err", None)
                _save()
                continue
            overlap_s = 1 if b < hi0 else 0
            edge_prev = ext.get("fills_edge") if isinstance(ext.get("fills_edge"), dict) else {}
            edge_skip = set(edge_prev.get("ids") or []) if int(edge_prev.get("b") or -1) == b else set()
            try:
                cp9 = json.loads(json.dumps(st.get("fills") or {}))
                rows = FILL_FETCHERS[ex](env, cp9, a, b + overlap_s)
                if _bb_hold_keep(st, cp9):
                    _save()
            except Exception as e:  # noqa: BLE001 [fallback]
                ext["fills_err"] = _xm(repr(e))[:160]
                days9, kind9 = _fills_limit_kind(repr(e))
                sl9 = ext.get("fills_soft_limit") if isinstance(ext.get("fills_soft_limit"), dict) else {}
                if days9 and ((kind9 == "strict" and int(ext.get("fills_hard_days") or 0) != days9)
                              or (kind9 == "soft" and (int(sl9.get("days") or 0) != days9 or now >= float(sl9.get("until") or 0)))):
                    if kind9 == "strict":
                        ext["fills_hard_days"] = days9
                        ext["fills_hard_src"] = "strict"
                    else:
                        ext["fills_soft_limit"] = {"days": days9, "until": int(now + EXT_SOFT_LIMIT_SEC)}
                    fl9 = ext_fills_floor(ex, now, ext)
                    if fl9 and fl9 > stop_at:
                        stop_at = fl9
                        ext["fills_limit"] = (f"API 이력 한도: {time.strftime('%Y-%m-%d', time.gmtime(fl9))} 이전 체결은 이 API 로 불가"
                                              f"(거래소 응답 {days9}일)")
                        log.warning("%s 과거 체결 보존 한도 %d일(API 응답) — %s 에서 멈춤", ex, days9,
                                    time.strftime("%Y-%m-%d", time.gmtime(fl9)))
                        _save()
                        continue
                break
            hi_ms = b * 1000 + (999 if overlap_s else 0)
            rows = [f for f in rows if a * 1000 <= int(f.get("ts") or 0) <= hi_ms and str(f.get("id")) not in edge_skip]
            ext["fills_edge"] = {"b": int(a), "ids": sorted({str(f.get("id")) for f in rows if int(f.get("ts") or 0) < (a + 1) * 1000})}
            if rows:
                _invalidate_balance_snapshot(ex)
                with wlock:
                    for i in range(0, len(rows), 500):
                        writer.append({"v": 1, "kind": "exf_fills", "exchange": ex, "ts": int(time.time()),
                                       "fills": rows[i:i + 500], "ext": True})
                n_f += len(rows)
                ext["n_emit"] = int(ext.get("n_emit") or 0) + len(rows)
            ext["fills_from"] = a
            ext.pop("fills_err", None)
            _save()
        if ext["fills_from"] <= stop_at:
            ext.pop("fills_err", None)
        span = max(1, hi0 - target)
        part9 = _bithumb_ext_part(ext) if ex == "bithumb" else 0
        done = (min(span, max(0, hi0 - ext["wd_from"])) + (min(span, max(0, hi0 - ext["fills_from"] + part9))
                                                           if ext["fills_from"] > stop_at else span)) / 2.0
        gap9 = ex == "binance" and not ext.get("bn_gap_done")
        if gap9 and ext["fills_from"] <= stop_at:
            fs9 = st.get("fills") or {}
            nk9 = len(fs9.get("pair_cursor") or {}) + len(fs9.get("margin_cursor") or {})
            done = min(done, span * len((ext.get("bn_gap") or {}).get("done") or []) / max(1, nk9))
        phase9 = "extend" if (ext["wd_from"] > target or ext["fills_from"] > stop_at or gap9) else "done"
        note9 = ext.get("fills_limit") or ext.get("wd_err") or ext.get("fills_err")
        sig9 = [phase9, int(ext["wd_from"]), int(ext["fills_from"]), note9, int(target), int(ext.get("n_emit") or 0), int(part9), int(done)]
        if ext.get("_psig") != sig9 or (phase9 != "done" and time.time() - float(ext.get("_pat") or 0) >= 1800):
            if not _acct():
                prog.update(f"{ex}:extend", phase=phase9, unit="sec", done=int(done), total=int(span),
                            target=time.strftime("%Y-%m-%d", time.gmtime(target)), note=note9,
                            wd_from=ext["wd_from"], fills_from=ext["fills_from"], emitted=int(ext.get("n_emit") or 0))
            old9 = ext.get("_psig")
            keep9 = (phase9 == "done" and isinstance(old9, list) and len(old9) >= 7 and old9[0] == "done"
                     and all(old9[i] == sig9[i] for i in (1, 2, 4, 5, 6)) and ext.get("_pat"))
            ext["_psig"], ext["_pat"] = sig9, (int(ext["_pat"]) if keep9 else int(time.time()))
            _save()
        if n_w or n_f:
            log.info("%s 과거 창 확장: 입출금 %d · 체결 %d (하한 입출금 %s / 체결 %s)", ex, n_w, n_f,
                     time.strftime("%Y-%m-%d", time.gmtime(ext["wd_from"])),
                     time.strftime("%Y-%m-%d", time.gmtime(ext["fills_from"])))

    if not active:
        return
    with _TPE(max_workers=len(active)) as ex9:
        list(ex9.map(one, active))


_VIEW_CYC = {}


def _view_snap(bal9) -> dict:
    snap9 = {"ts": int(time.time()), "balances": dict(bal9)}
    if isinstance(getattr(bal9, "debts", None), dict):
        snap9["debts"] = {k9: v9 for k9, v9 in bal9.debts.items() if v9 < 0}
    if isinstance(getattr(bal9, "sources", None), list):
        snap9["sources"] = sorted(set(bal9.sources))
    if getattr(bal9, "loans", None):
        snap9["loans"] = list(bal9.loans)
    return snap9


def sub_passes(env: dict, state: dict, cw, now: int, window: int) -> dict:
    out = {}
    for ex, (_fn, need) in FETCHERS.items():
        for tag, env_a in acct_envs(env, ex, need)[1:]:
            vst = acct_vstate(state, ex, tag, now)
            aw = _AcctWriter(cw, ex, tag, vst[ex])
            fx = {ex: FETCHERS[ex]}
            jobs = [("출금 목적지 소급", lambda: dest_backfill_pass(env_a, vst, aw, now, window, fetchers=fx)),
                    ("비종결 입출금 재확인", lambda: pending_recheck_pass(env_a, vst, aw, now, window, fetchers=fx))]
            if ex == "bybit":
                jobs.append(("바이비트 내부 입금", lambda: bybit_internal_pass(env_a, vst, aw, now, window)))
            with _acct_ctx(tag):
                for nm9, f9 in jobs:
                    try:
                        out[f"{ex}[{tag}]:{nm9}"] = f9()
                    except Exception as e:   # noqa: BLE001 [isolate]
                        log.warning("%s[%s] %s 실패(다음 주기): %s", ex, tag, nm9, _xm(repr(e))[:160])
    return out


def sub_extension_pass(env: dict, state: dict, writer, target: int, now: int, window: int) -> None:
    for ex, (_fn, need) in FETCHERS.items():
        for tag, env_a in acct_envs(env, ex, need)[1:]:
            vst = acct_vstate(state, ex, tag, now)
            with _acct_ctx(tag):
                try:
                    extension_pass(env_a, vst, _AcctWriter(writer, ex, tag, vst[ex]), target, now, window)
                except Exception as e:   # noqa: BLE001 [isolate]
                    log.warning("%s[%s] 과거 창 확장 실패(다음 주기): %s", ex, tag, _xm(repr(e))[:160])


def _sub_denied(msg: str) -> bool:
    m9 = str(msg or "")
    l9 = m9.lower()
    return (any(k in m9 for k in _DENY_SIGS) or "bybit 10005" in m9 or "permission" in l9
            or "58209" in m9 or "not support sub" in l9 or "sub-accounts don't support" in l9)


def acct_wait(st: dict, accts: list) -> list:
    a9 = st.get("accts") if isinstance(st.get("accts"), dict) else {}
    out = []
    for tag, _e in accts[1:]:
        s9 = a9.get(tag) if isinstance(a9.get(tag), dict) else {}
        wd9 = s9.get("backfilled_until") or (time.time() - int(s9.get("wd_denied") or 0) < DENY_COOL_SEC + 3600)
        if not wd9 or not (s9.get("fills") or {}).get("backfilled_until"):
            out.append(tag)
    return out


def _lb_nonzero(lb: dict) -> bool:
    for part in (lb.get("b"), lb.get("d")):
        if part and not isinstance(part, dict):
            return True
        for qty in (part or {}).values():
            try:
                if float(qty) != 0:
                    return True
            except (TypeError, ValueError):
                return True
    return False


def acct_held(ex: str, state: dict, accts: list, loud: bool = False) -> list:
    exst = state.get(ex) if isinstance(state.get(ex), dict) else {}
    subs = exst.get("accts")
    active = {tag for tag, _env in accts}
    held, dropped = [], False
    dup = {t: f for (dex, t), f in _DUP.items() if dex == ex and (dex, t) not in _IDENT_BAD}
    for tag, sub in sorted((subs or {}).items()) if isinstance(subs, dict) else ():
        if not tag or tag in active or not isinstance(sub, dict) or not isinstance(sub.get("last_bal"), dict):
            continue
        if tag in dup:
            del sub["last_bal"]
            dropped = True
            continue
        if _lb_nonzero(sub["last_bal"]):
            held.append(tag)
        else:
            del sub["last_bal"]
            dropped = True
    if held != (exst.get("sub_held") or []):
        exst["sub_held"] = held
        dropped = True
    if dup != (exst.get("sub_dup") or {}):
        exst["sub_dup"] = dup
        dropped = True
    if dropped:
        _save_state(state)
    if dup and loud:
        log.warning("%s 같은 계정 키가 두 칸에 있음(%s) — 뒤 칸은 잔고·이력에서 빼고 셈 · 그 칸 키를 지우세요", ex,
                    ",".join(f"{t}={f or 'main'}" for t, f in sorted(dup.items())))
    if held and loud:
        log.warning("%s 서브 키 제외됨(%s) — 마지막 잔고가 0 이 아니라 잔고 대사 보류(표시용만 · 같은 계정 키를 다시 넣으면 풀림)", ex, ",".join(held))
    return held


def _bal_all(ex: str, accts: list, st: dict = None):
    if not accts:
        raise RuntimeError(f"{ex} 키 없음")
    a9 = (st.get("accts") if isinstance(st, dict) and isinstance(st.get("accts"), dict) else {}) or {}
    on9 = {t for t, _e in accts}
    frozen9 = [t for t, v in sorted(a9.items()) if t and t not in on9 and ((ex, t) not in _DUP or (ex, t) in _IDENT_BAD) and isinstance(v, dict) and isinstance(v.get("last_bal"), dict)]
    if len(accts) == 1 and not frozen9:
        return BAL_FETCHERS[ex](accts[0][1])
    out = _Bal()
    got9 = {}
    for tag, env_a in accts:
        with _acct_ctx(tag):
            b9 = BAL_FETCHERS[ex](env_a)
        got9[tag] = b9
    for tag, b9 in got9.items():
        pre9 = f"{tag}:" if tag else ""
        for k, v in b9.items():
            out[k] = out.get(k, 0) + v
        for k, v in (getattr(b9, "debts", None) or {}).items():
            out.debts[k] = out.debts.get(k, 0) + v
        out.sources += [pre9 + str(x) for x in (getattr(b9, "sources", None) or [])] + ([f"{tag}:spot"] if tag else [])
        for l9 in (getattr(b9, "loans", None) or []):
            out.loans.append(dict(l9, acct=tag) if tag and isinstance(l9, dict) else l9)
        for s9, d9 in (getattr(b9, "by_src", None) or {}).items():
            if isinstance(d9, dict):
                t9 = out.by_src.setdefault(s9, {})
                for k, v in d9.items():
                    t9[k] = t9.get(k, 0) + v
        if tag and isinstance(a9.get(tag), dict):
            a9[tag]["last_bal"] = {"ts": int(time.time()), "b": dict(b9), "d": dict(getattr(b9, "debts", None) or {}),
                                   "src": [pre9 + str(x) for x in (getattr(b9, "sources", None) or [])] + [f"{tag}:spot"]}
    for tag in frozen9:
        lb9 = a9[tag]["last_bal"]
        for k, v in (lb9.get("b") or {}).items():
            out[k] = out.get(k, 0) + float(v)
        for k, v in (lb9.get("d") or {}).items():
            out.debts[k] = out.debts.get(k, 0) + float(v)
        out.sources += [str(x) for x in (lb9.get("src") or [f"{tag}:spot"])]
        if _quiet_n.get(ex, 0) % 10 == 1:
            log.warning("%s 서브계정 %s 키가 설정에 없음 — 마지막 잔고(%s)를 표시용 합에만 더하고 잔고 대사 보류 · 다시 넣으면 이어서 받음",
                        ex, tag, time.strftime("%Y-%m-%d %H:%M", time.localtime(int(lb9.get("ts") or 0))))
    return out


def balance_prefetch(env: dict, cyc: int, fetchers=None) -> dict:
    out = {}
    for ex, (_fn, need) in (fetchers or FETCHERS).items():
        if not all(env.get(k) for k in need):
            continue
        if _VIEW_CYC.get(ex, -9) >= cyc - 1:
            out[ex] = "skip"
            continue
        try:
            snap9 = _view_snap(_bal_all(ex, acct_envs(env, ex, need)))
            statefile.atomic_write_json(paths.state(f"exf_balances_{ex}.json.view"), snap9)
            out[ex] = "ok"
            log.info("%s: 잔고 %d종 먼저 읽음(표시용 — 옛 기록 수집 전)", ex, len(snap9["balances"]))
        except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
            out[ex] = _xm(repr(e))[:160]
            log.info("%s 잔고 먼저 읽기 실패(주기 끝에 다시): %s", ex, out[ex][:120])
    return out


def _hl_on(cfg) -> bool:
    try:
        import hl_spot
        return bool(hl_spot.addresses(cfg))
    except Exception:   # noqa: BLE001 [fallback]
        return False


def main():
    runtime.cpu_reserve_apply()
    paths.ensure_dirs()
    unit_beat.start("exf")
    writer = SegmentWriter(os.path.join(paths.INBOX_DIR, "ex"))
    n9 = logs.scrub_secret_file(paths.state("exf_state.json"))
    if n9:
        log.info("exf_state: 수정 전 오류 문구 %d칸 비밀값 가림", n9)
    state = statefile.read_json(paths.state("exf_state.json"), {})
    _cool_restore()
    _clock_restore()
    depaddr.start_background(_env)
    try:
        import perp_dex
        perp_dex.start_background()
    except Exception as e:   # noqa: BLE001 [boundary]
        log.warning("퍼프 덱스 수집 스레드 시작 실패(거래소 수집은 계속): %s", repr(e)[:160])
    try:
        import liq_watch
        liq_watch.start_background(_env, _RL_OFF)
    except Exception as e:   # noqa: BLE001 [boundary]
        log.warning("청산 빠른 감시 스레드 시작 실패(거래소 수집은 계속): %s", repr(e)[:160])
    cyc9 = 0
    while True:
        env = _env()
        kperm = settings_store.read_settings().get("key_perm") or {}
        env = _main_gate(state, env, kperm)
        cfg = config.load_config()
        poll9 = config.exf_poll_sec(cfg)
        _POLL_HINT[0] = poll9
        _DIV_OFF[0] = not config.exf_binance_dividends(cfg)
        months = 0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 5)
        window = int((months or 5) * 30 * DAY)
        now = int(time.time())
        _dup_scan(env, kperm, state)
        hl_on9 = _hl_on(cfg)
        try:
            statefile.atomic_write_json(paths.state("exf_active.json"),
                                     {"v": 1, "ts": now, "active": sorted([ex for ex, (_f9, need) in FETCHERS.items()
                                                                           if all(env.get(k) for k in need)] + (["hyperliquid"] if hl_on9 else [])
                                                                          + [f"{ex}~{t9}" for ex, (_f9, need) in FETCHERS.items()
                                                                             for t9 in sub_tags(env, ex)])})
        except Exception as e:   # noqa: BLE001 [boundary]
            log.warning("연결 거래소 목록 기록 실패(무시): %s", repr(e)[:120])
        _LATE_CYC["id"], _LATE_CYC["ex"] = f"c{now}:{uuidlib.uuid4().hex[:10]}", set()
        cyc9 += 1
        try:
            balance_prefetch(env, cyc9)
        except Exception as e:   # noqa: BLE001 [boundary]
            log.warning("잔고 먼저 읽기 실패(종전 순서로 계속): %s", repr(e)[:160])
        if hl_on9:
            try:
                import hl_spot
                m9 = hl_spot.prefetch_view(cfg, poll=poll9)
                if m9.startswith("ok"):
                    log.info("hyperliquid: 잔고 먼저 읽음(표시용 — 옛 기록 수집 전): %s", m9)
            except (Exception, SystemExit) as e:   # noqa: BLE001 [boundary]
                log.info("hyperliquid 잔고 먼저 읽기 실패(주기 끝 수집은 그대로): %s", repr(e)[:160])
        cw = _CycleWriter(writer, state)
        for ex, (fn, need) in FETCHERS.items():
            if not all(env.get(k) for k in need):
                continue
            st = state.setdefault(ex, {"seen": {}, "backfilled_until": 0})
            _quiet_n[ex] = _quiet_n.get(ex, 0) + 1
            loud9 = _quiet_n[ex] % 10 == 1
            _IDENT_BAD.difference_update({k for k in _IDENT_BAD if k[0] == ex})
            _ident_all(state, ex, env, need, kperm, now)
            _dup_scan(env, kperm, state, ex)
            accts9 = acct_envs(env, ex, need)
            agg_ok9, agg_new9, agg_fly9, agg_rl9, agg_trk9 = not any(k[0] == ex for k in _IDENT_BAD), 0, [], False, False
            for tag9, env_a in accts9:
                with _acct_ctx(tag9):
                    st_a = st if not tag9 else acct_state(state, ex, tag9, now)
                    cw_a = cw if not tag9 else _AcctWriter(cw, ex, tag9, st_a)
                    exl9 = ex if not tag9 else f"{ex}[{tag9}]"
                    _dep_hold_migrate(ex, st_a, now, window)
                    t0, dep_t0 = _wd_window(st_a, now, window)
                    wd_ok = True
                    try:
                        w_rows, d_rows = fn(env_a, t0, now, dep_t0=dep_t0) if ex == "gate" else fn(env_a, t0, now)
                    except Exception as e:  # noqa: BLE001 [isolate]
                        w_rows, d_rows = [], []
                        wd_ok = False
                        if tag9 and _sub_denied(_xm(repr(e))):
                            if now - int(st_a.get("wd_denied") or 0) >= DENY_COOL_SEC:
                                log.warning("%s 서브 키로 입출금 이력 조회 권한 없음 — 이 서브의 입출금은 빼고 체결·잔고·대사는 계속(권한이 생기면 그때부터 받음): %s",
                                            exl9, _xm(repr(e))[:140])
                            st_a["wd_denied"] = now
                        else:
                            log.warning("%s 입출금 수집 실패(다음 주기 재시도): %s", exl9, repr(e)[:140])
                            _invalidate_balance_snapshot(ex)
                    seen = st_a["seen"]
                    seen_txids = st_a.setdefault("seen_txids", {})
                    seen_dest = st_a.setdefault("seen_dest", {})
                    new_w = _rows_to_emit(w_rows, seen, seen_txids, seen_dest)
                    new_d = _rows_to_emit(d_rows, seen, seen_txids)
                    if wd_ok and tag9 and st_a.pop("wd_denied", None):
                        for r9 in new_w + new_d:
                            r9["late"] = 1
                    if new_w or new_d:
                        _invalidate_balance_snapshot(ex)
                        cw_a.append(_late_tag({"v": 1, "kind": "ex_snapshot", "exchange": ex,
                                             "ts": now, "deposits": new_d, "withdraws": new_w}, ex))
                        if new_d:
                            depaddr.notify(ex)
                        _mark_seen(new_w + new_d, seen, seen_txids, seen_dest, st_a.setdefault("pend_ts", {}))
                    if wd_ok:
                        st_a["backfilled_until"] = now
                        _dep_hold_update(ex, st_a, dep_t0)
                    if not tag9:
                        state[ex] = st_a
                    _save_state(state)
                    if new_w or new_d or loud9:
                        log.info("%s: 출금 %d(신규 %d) · 입금 %d(신규 %d)",
                                 exl9, len(w_rows), len(new_w), len(d_rows), len(new_d))
                    wd_fly9 = _wd_inflight(w_rows, now) if wd_ok else []
                    fills_ok, fills_new = False, 0
                    fills_rl = False
                    fst = None
                    try:
                        fst = json.loads(json.dumps(st_a.get("fills") or {}))
                        fst["extra_bases"] = sorted(set(fst.get("extra_bases") or []) |
                                                    {r["currency"] for r in w_rows + d_rows
                                                     if r.get("currency")})
                        _WD_TOUCH[_ak(ex)] = {str(r["currency"]).upper() for r in new_w + new_d if r.get("currency")}
                        ft0 = max(now - window, min(now - 3 * DAY, int(fst.get("backfilled_until") or now - window)))
                        if ex == "binance":
                            ft0 = binance_fills_t0(st_a, now, window)
                        f_rows = FILL_FETCHERS[ex](env_a, fst, ft0, now)
                        partial9 = fst.pop("partial", None)
                        f_rows = f_rows + convert_rows(ex, env_a, fst, now, window)
                        hold9 = fst.pop("recon_hold", None)
                        fseen = fst.setdefault("seen", {})
                        new_f = [f for f in f_rows if f["id"] not in fseen]
                        if new_f:
                            _invalidate_balance_snapshot(ex)
                        lb9 = f"{ex}:{now}:{uuidlib.uuid4().hex[:10]}" if any(f.get("late") or f.get("src") == "convert" for f in new_f) else None
                        nch9 = (len(new_f) + 499) // 500
                        for k9, i in enumerate(range(0, len(new_f), 500)):
                            rec9 = {"v": 1, "kind": "exf_fills", "exchange": ex, "ts": now, "fills": new_f[i:i + 500]}
                            if lb9:
                                rec9.update(lb=lb9, lbi=k9, lbn=nch9)
                            cw_a.append(_late_tag(rec9, ex, force=bool(lb9)))
                        cutoff = (now - 14 * DAY) * 1000
                        for f in new_f:
                            fseen[f["id"]] = f["ts"]
                        for k in [k for k, v in fseen.items() if v < cutoff]:
                            del fseen[k]
                        if not partial9:
                            fst["backfilled_until"] = now
                        st_a["fills"] = fst
                        _save_state(state)
                        fills_ok, fills_new = not partial9 and not hold9, len(new_f)
                        fills_rl = bool(partial9) and ex == "binance"
                        if new_f or loud9:
                            log.info("%s: 체결 %d건 (신규 %d)", exl9, len(f_rows), len(new_f))
                        if hold9 and not partial9:
                            log.info("%s 잔고 승격 보류(부가 수집 미완 — %s): 받은 체결·커서는 반영, 다음 주기 다시", exl9, str(hold9)[:200])
                        if partial9:
                            log.info("%s 체결 부분 주기(받은 몫·커서 보존, 백필 도장·잔고 승격 보류 — 다음 주기에 이어서): %s", exl9, partial9)
                    except Exception as e:  # noqa: BLE001 [isolate]
                        fills_rl = isinstance(e, RateLimited)
                        log.warning("%s 체결 수집 실패(다음 주기 재시도): %s", exl9, repr(e)[:140])
                        try:
                            eb9 = set((st_a.get("fills") or {}).get("extra_bases") or []) | set((fst or {}).get("extra_bases") or [])
                            bd9 = set((st_a.get("fills") or {}).get("bn_dirty") or []) | set((fst or {}).get("bn_dirty") or [])
                            if eb9 != set((st_a.get("fills") or {}).get("extra_bases") or []) or bd9 != set((st_a.get("fills") or {}).get("bn_dirty") or []):
                                st_a.setdefault("fills", {})["extra_bases"] = sorted(eb9)
                                if bd9:
                                    st_a["fills"]["bn_dirty"] = sorted(bd9)
                                _save_state(state)
                        except Exception as e9:  # noqa: BLE001 [isolate]
                            log.warning("%s 체결 후보 통화 보존 실패: %s", exl9, repr(e9)[:120])
                    agg_ok9 = agg_ok9 and fills_ok
                    agg_new9 += fills_new
                    agg_fly9 += list(wd_fly9 or [])
                    agg_rl9 = agg_rl9 or fills_rl
                    agg_trk9 = agg_trk9 or bool((st_a.get("fills") or {}).get("track_pending") or (st_a.get("fills") or {}).get("open_unknown"))
            fills_ok, fills_new, wd_fly9, fills_rl = agg_ok9, agg_new9, agg_fly9, agg_rl9
            wait9 = acct_wait(st, accts9)
            if wait9 and loud9:
                log.info("%s 서브계정 %s 이력 받는 중 — 잔고 대사 보류(다 받으면 메인+서브 합으로)", ex, ",".join(wait9))
            held_subs = acct_held(ex, state, accts9, loud9)
            bp9 = paths.state(f"exf_balances_{ex}.json")
            pend_bp = bp9 + ".pending"
            try:
                if wd_fly9 and fills_ok and not fills_new and loud9:
                    log.info("%s 진행 중 출금 %d건(종결 전) — 잔고 승격 보류(출금 기장 전 잔고로 대사 금지)", ex, len(wd_fly9))
                if not fills_ok or fills_new or wd_fly9 or agg_trk9 or wait9 or held_subs:
                    _keep_view(bp9, pend_bp)
                    for p9 in (bp9, pend_bp):
                        if os.path.exists(p9):
                            os.remove(p9)
                    if (not fills_ok or (wd_fly9 and not fills_new) or wait9 or held_subs) and not fills_rl:
                        try:
                            bal9 = _bal_all(ex, accts9, st)
                            if st.get("accts"):
                                _save_state(state)
                            snap9 = {"ts": int(time.time()), "balances": dict(bal9)}
                            if isinstance(getattr(bal9, "debts", None), dict):
                                snap9["debts"] = {k9: v9 for k9, v9 in bal9.debts.items() if v9 < 0}
                            if isinstance(getattr(bal9, "sources", None), list):
                                snap9["sources"] = sorted(set(bal9.sources))
                            if getattr(bal9, "loans", None):
                                snap9["loans"] = list(bal9.loans)
                            statefile.atomic_write_json(bp9 + ".view", snap9)
                            _VIEW_CYC[ex] = cyc9
                        except (Exception, SystemExit) as e9v:   # noqa: BLE001 [isolate]
                            if loud9:
                                log.info("%s 표시용 잔고 갱신 생략(체결 실패 주기): %s", ex, _xm(repr(e9v))[:120])
                else:
                    bal9 = _bal_all(ex, accts9, st)
                    if st.get("accts"):
                        _save_state(state)
                    prevp = statefile.read_json(pend_bp, {})
                    prev_balances = prevp.get("balances")
                    snap9 = {"ts": int(time.time()), "balances": dict(bal9)}
                    if isinstance(getattr(bal9, "debts", None), dict):
                        snap9["debts"] = {k9: v9 for k9, v9 in bal9.debts.items() if v9 < 0}
                    if isinstance(getattr(bal9, "sources", None), list):
                        snap9["sources"] = sorted(set(bal9.sources))
                    if getattr(bal9, "loans", None):
                        snap9["loans"] = list(bal9.loans)
                    if ex == "binance" and isinstance((getattr(bal9, "by_src", None) or {}).get("futures"), dict):
                        snap9["fut_part"] = dict(bal9.by_src["futures"])
                    if isinstance(prev_balances, dict) and (prev_balances or not bal9):
                        agree9, why9 = _snap_promote_ok(ex, prevp, snap9)
                        if agree9:
                            statefile.atomic_write_json(bp9, prevp)
                            if loud9:
                                log.info("%s: 잔고 스냅샷 승격 (%d종)%s", ex, len(prev_balances), " — 일치 확인 없이(연속 불일치 상한)" if agree9 == "forced" else "")
                    statefile.atomic_write_json(pend_bp, snap9)
                    statefile.atomic_write_json(bp9 + ".view", snap9)
                    _VIEW_CYC[ex] = cyc9
                    if loud9:
                        log.info("%s: 잔고 %d종 (pending)", ex, len(bal9))
            except (Exception, SystemExit) as e:   # noqa: BLE001 [isolate]
                log.warning("%s 잔고·주소 수집 실패(다음 주기): %s", ex, repr(e)[:140])
        if hl_on9:
            try:
                import hl_spot
                msg9 = hl_spot.run_pass(state, cw, cfg, now=now, save=lambda: _save_state(state))
                (log.info if msg9.startswith(("ok", "off", "대기")) else log.warning)("hyperliquid 현물: %s", msg9)
            except Exception as e:   # noqa: BLE001 [boundary]
                log.warning("hyperliquid 현물 수집 실패(다음 주기): %s", repr(e)[:160])
        try:
            dest_backfill_pass(env, state, cw, now, window)
        except Exception as e:  # noqa: BLE001 [boundary]
            log.warning("출금 목적지 소급 실패(다음 주기): %s", repr(e)[:160])
        try:
            krw_backfill_pass(env, state, cw, now, window)
        except Exception as e:  # noqa: BLE001 [boundary]
            log.warning("빗썸 원화 입출금 소급 실패(다음 주기): %s", repr(e)[:160])
        try:
            bybit_internal_pass(env, state, cw, now, window)
        except Exception as e:  # noqa: BLE001 [boundary]
            log.warning("바이비트 내부 입금 패스 실패(다음 주기): %s", repr(e)[:160])
        try:
            pending_recheck_pass(env, state, cw, now, window)
        except Exception as e:  # noqa: BLE001 [boundary]
            log.warning("비종결 입출금 재확인 실패(다음 주기): %s", repr(e)[:160])
        try:
            sub_passes(env, state, cw, now, window)
        except Exception as e:   # noqa: BLE001 [boundary]
            log.warning("서브계정 부가 패스 실패(다음 주기): %s", repr(e)[:160])
        for ex9 in sorted(_LATE_CYC["ex"]):
            try:
                writer.append({"v": 1, "kind": "exf_late_cycle", "exchange": ex9, "ts": int(time.time()), "lc": _LATE_CYC["id"]})
            except Exception as e:   # noqa: BLE001 [isolate]
                log.warning("%s 늦은 행 주기 끝 표시 실패(core 는 1시간 뒤 흡수): %s", ex9, repr(e)[:120])
        _LATE_CYC["id"], _LATE_CYC["ex"] = None, set()
        target9 = ext_trigger_target(now, window)
        ext_sec = 0.0
        if target9 is not None:
            t_ext = time.time()
            try:
                extension_pass(env, state, writer, int(target9), now, window)
            except Exception as e:  # noqa: BLE001 [boundary]
                log.warning("과거 창 확장 실패(다음 주기): %s", repr(e)[:160])
            try:
                sub_extension_pass(env, state, writer, int(target9), now, window)
            except Exception as e:   # noqa: BLE001 [boundary]
                log.warning("서브계정 과거 창 확장 실패(다음 주기): %s", repr(e)[:160])
            ext_sec = time.time() - t_ext
        futures_snapshot_all(env)
        try:
            leverage_pass(env, cfg)
        except Exception as e:   # noqa: BLE001 [boundary]
            log.warning("레버리지·대출 스냅숏 실패(다음 주기): %s", logs.safe_err(repr(e))[:160])
        active = any(all(env.get(k) for k in need) for _, need in FETCHERS.values()) or hl_on9
        time.sleep(max(60.0, poll9 - ext_sec) if active else 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")

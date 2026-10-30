from __future__ import annotations
import glob
import os
import time
from datetime import datetime
import config, envfile, logs, paths
from chk_base import EX_NAME
from chk_base import INT_PROGRESS
from chk_base import INT_STALL_SEC
from chk_base import KST
from chk_base import NATIVE_SYM
from chk_base import PACE_GRACE_SEC
from chk_base import PACE_NOTE_FILL
from chk_base import PACE_NOTE_HEAD
from chk_base import SOL_WAIT_WHY
from chk_base import _CHALLENGE_RX
from chk_base import _PERMANENT_RX
from chk_base import _READ_FAIL
from chk_base import _TRANSIENT_RX
from chk_base import _read
from chk_base import fmt_ago
from chk_base import fmt_ts
from chk_logs import _cname
from chk_logs import _mem_ts

def is_challenge(msg) -> bool:
    return bool(msg) and bool(_CHALLENGE_RX.search(str(msg)))


def es_reset_text(now: float = None) -> str:
    now = time.time() if now is None else now
    return time.strftime("%H:%M", time.localtime((int(now) // 86400 + 1) * 86400 + 300))


def pace_alive(src: dict, now: float):
    if (src or {}).get("ok") is False:
        return None
    try:
        pa = float((src or {}).get("paced_at") or 0)
        ls = float((src or {}).get("last_success_ts") or 0)
    except (TypeError, ValueError):
        return None
    if pa <= 0 or now - pa > 600:
        return None
    if ls <= 0 or now - ls > PACE_GRACE_SEC:
        return None
    return pa


def fill_paced(sub: str, budget: float, keep: float = 0.02, now: float = None) -> bool:
    now = time.time() if now is None else now
    day = int(now // 86400)
    n = 0
    try:
        d = os.path.join(paths.quota_dir(), sub)
        for f in os.listdir(d):
            if f.endswith(".json"):
                j = _read(os.path.join(d, f), None)
                if isinstance(j, dict) and j.get("day") == day:
                    n += int(j.get("n") or 0)
    except (OSError, TypeError, ValueError):
        return False
    return n >= budget * ((now % 86400) / 86400.0) - budget * keep


def fill_slow(obs: dict, bu: str, key: str, it: dict = None, now: float = None) -> bool:
    if not (obs.get("fill_paced") or {}).get(bu):
        return False
    now = time.time() if now is None else now
    try:
        pa9 = float((it or {}).get("paced_at") or 0)
    except (TypeError, ValueError):
        pa9 = 0.0
    if pa9 <= 0 or now - pa9 > 3600:
        return False
    ps9 = (((obs.get("hb") or {}).get(bu) or {}).get("sources") or {}).get(str(key).split(":")[0]) or {}
    if bu == "sol" and ps9.get("primary") == "open":
        return False
    return (bu == "evm" and ps9.get("kind") == "etherscan") or (bu == "sol" and bool(ps9.get("helius_budget")))


def _fill_paced_map(cfg: dict, now: float) -> dict:
    try:
        import bf_engine
        es9 = (cfg or {}).get("etherscan") or {}
        if float(es9.get("pace_burst_pct", 4)) >= 100:
            return {"evm": False, "sol": False}
        keep = min(50.0, max(0.0, float(es9.get("fill_keep_pct", 2)))) / 100.0
        es = float(es9.get("daily_budget") or 80000)
        burst = max(0.0, float(es9.get("pace_burst_pct", 4))) / 100.0
        return {"evm": bf_engine.es_ledger_rooms(now, es, burst, keep)["fill"] <= 0,
                "sol": bf_engine.ledger_rooms("helius_budget", bf_engine.helius_day_budget(cfg), burst, keep, now, floor=bf_engine.helius_head_min(cfg), flex=bf_engine.helius_flex(cfg))["fill"] <= 0}
    except Exception:   # noqa: BLE001 [fallback]
        return {}


def _pace_note(cfg: dict, now: float, unit: str) -> str:
    ff = None
    try:
        import bf_engine
        es9 = (cfg or {}).get("etherscan") or {}
        keep = min(50.0, max(0.0, float(es9.get("fill_keep_pct", 2)))) / 100.0
        burst = max(0.0, float(es9.get("pace_burst_pct", 4))) / 100.0
        if unit == "sol":
            ff = bf_engine.ledger_rooms("helius_budget", bf_engine.helius_day_budget(cfg), burst, keep, now, floor=bf_engine.helius_head_min(cfg), flex=bf_engine.helius_flex(cfg)).get("fillFirst")
        else:
            ff = bf_engine.es_ledger_rooms(now, float(es9.get("daily_budget") or 80000), burst, keep).get("fillFirst")
    except Exception:   # noqa: BLE001 [fallback]
        ff = None
    return PACE_NOTE_HEAD if ff is False else PACE_NOTE_FILL


def human_err(msg, label: str = "") -> str:
    if not msg:
        return msg
    m = logs.redact_secret_text(str(msg))
    if is_challenge(m):
        return "외부 탐색기가 사람 확인 화면으로 막는 중(HTTP 403 · 우리 쪽 문제 아님)"
    if _PERMANENT_RX.search(m):
        return m
    low = m.lower()
    who = f"{label} RPC" if label else "RPC"
    if "-32008" in m or "/minute" in low or "per minute" in low:
        return f"{who} 분당 한도 — 속도 낮춰 재시도 중"
    if "-32007" in m or "request limit reached" in low or "per second" in low or "/second" in low:
        return f"{who} 초당 한도 — 속도 낮춰 재시도 중"
    if "max usage" in low or "quota" in low:
        return f"{who} 사용량 한도 소진 — 한도가 풀리면 이어서"
    if "429" in m or "too many requests" in low or "rate limit" in low:
        return f"{who} 호출 한도 — 잠시 쉬었다 재시도 중"
    if "timed out" in low or "timeout" in low or "deadline exceeded" in low:
        return f"{who} 응답 시간 초과 — 다음 주기 재시도"
    if "circuit open" in low:
        return f"{who} 연속 실패로 잠시 쉬는 중"
    return logs.redact_urls(m)


def _transient_err(err) -> bool:
    if not err:
        return True
    t = str(err)
    return not _PERMANENT_RX.search(t) and bool(_TRANSIENT_RX.search(t))


def _source(st, now, key, unit, label, kind, cur_ts, err=None, extra=None):
    rec = _mem_ts(st, key, cur_ts)
    if rec["first"] is None:
        rec["first"] = now
    return {"key": key, "unit": unit, "label": label, "kind": kind, "last_success": rec["last"],
            "first_seen": rec["first"], "err": err, "extra": extra}


def _bs_partial_text(chain: str, bs: dict, bs_ts: float, now: float) -> str:
    lag = bs.get("lag_sec")
    try:
        lag = float(lag) if lag is not None else None
    except (TypeError, ValueError):
        lag = None
    if lag is None and bs_ts:
        lag = now - float(bs_ts)
    if lag and 5400 <= lag < 172800:
        h9, m9 = divmod(int(lag) // 60, 60)
        lag_s = f"{h9}시간" + (f" {m9}분" if m9 else "")
    else:
        lag_s = fmt_ago(lag)
    head = f"블록스카웃 {lag_s} 지연(외부)" if lag else "블록스카웃 응답 대기(외부)"
    late = f"{NATIVE_SYM.get(chain, '네이티브')} 송금·내부 이동"
    try:
        nbf = int(bs.get("wallets_backfilling") or 0)
    except (TypeError, ValueError):
        nbf = 0
    if nbf > 0:
        ids = [str(x)[:6] for x in (bs.get("backfilling_ids") or []) if x][:3]
        late += f"과 새 지갑 {nbf}개" + (f"({', '.join(ids)}{'…' if nbf > len(ids) else ''})" if ids else "") + " 기초잔고"
        late += "는"
    else:
        late += "은"
    tail = (f" · 블록스카웃 마지막 성공 {fmt_ts(bs_ts)}" if bs_ts
            else f" · 블록스카웃 반영 {fmt_ts(now - lag)}까지" if lag else "")
    return f"{head} — 토큰 이동은 실시간, {late} 복구 후 자동 반영{tail}"


def _int_track(st: dict, chain: str, bs: dict, now: float):
    if not isinstance(st, dict) or not isinstance(bs, dict):
        return None
    mem = st.setdefault("mem", {})
    k = f"intidx:{chain}"
    if bs.get("indexing_state") != "internal":
        if bs.get("ok") and not bs.get("indexing_unknown") and bs.get("indexing_state") is not None:
            mem.pop(k, None)
        return None
    try:
        r = round(float(bs.get("internal_ratio")), 4)
    except (TypeError, ValueError):
        return None
    rec = mem.get(k)
    if not isinstance(rec, dict):
        rec = None
    else:
        try:
            if "base" not in rec:
                rec = {"base": float(rec.get("ratio")), "since": float(rec.get("since") or now),
                       "start": float(rec.get("since") or now)}
            else:
                rec = {"base": float(rec["base"]), "since": float(rec.get("since") or now),
                       "start": float(rec.get("start") or rec.get("since") or now)}
        except (TypeError, ValueError):
            rec = None
    if rec is None:
        rec = {"base": r, "since": now, "start": now}
    elif r >= rec["base"] + INT_PROGRESS - 1e-9:
        rec.update(base=r, since=now)
    elif r < rec["base"] - 0.2:
        rec.update(base=r, since=now)
    mem[k] = rec
    return {"stall": max(0.0, now - rec["since"]), "below_since": min(rec["start"], now)}


def _int_stall(st: dict, chain: str, bs: dict, now: float):
    tr = _int_track(st, chain, bs, now)
    return tr["stall"] if tr else None


def _bs_internal_text(chain: str, bs: dict, stall_sec=None):
    if not bs.get("ok"):
        return None
    intf = bs.get("int_fill") if isinstance(bs.get("int_fill"), dict) else None
    nat = NATIVE_SYM.get(chain, "네이티브")
    if bs.get("indexing_state") == "internal":
        try:
            pct = f"{float(bs.get('internal_ratio')) * 100:.0f}%"
        except (TypeError, ValueError):
            pct = "미완"
        if stall_sec is not None and stall_sec >= INT_STALL_SEC:
            txt = (f"외부 탐색기 색인 {pct}에서 {fmt_ago(stall_sec)}째 정체 — 내부 이동({nat} 전송) 일부 누락 가능"
                   f" · 거래·토큰 목록은 최신, 색인이 다시 움직여 끝나면 자동으로 채움")
        else:
            txt = f"거래·토큰 목록 최신, 내부 이동({nat} 전송 일부)은 외부 탐색기 색인 {pct} 대기 — 끝나면 자동으로 채움"
        if bs.get("indexing_unknown"):
            txt += "(색인 상태 조회 실패 — 마지막 관측 유지)"
    elif intf:
        txt = f"거래·토큰 목록 최신, 내부 이동({nat} 전송 일부)은 탐색기 색인이 끝나 지금 자동으로 채우는 중"
    else:
        return None
    try:
        nbf = int(bs.get("wallets_backfilling") or 0)
    except (TypeError, ValueError):
        nbf = 0
    if nbf > 0:
        ids = [str(x)[:6] for x in (bs.get("backfilling_ids") or []) if x][:3]
        txt += f" · 새 지갑 {nbf}개" + (f"({', '.join(ids)}{'…' if nbf > len(ids) else ''})" if ids else "") + " 과거 기록 수집 중"
    return txt


def leaf_overflow_text(cur: dict, warn: int = 100_000):
    try:
        n = int((cur or {}).get("_leaf_overflow") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    if n <= 0:
        return None
    t = f"내부 입금 확인 대기 잎 블록 {n:,}개(큐 넘침 — 노드 trace 회복 뒤 자동)"
    return ("넘침 경고: " + t + " · 추적(trace) 노드 확인 필요") if n >= warn else t


def trace_later_drop_text(cur: dict, warn: int = 100_000):
    try:
        n = int((cur or {}).get("_trace_later_dropped") or 0)
        o = int((cur or {}).get("_trace_later_overflow") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    out = []
    if o > 0:
        t = f"내부 이동 확인 대기 거래 {o:,}건(늦은 채움 큐 넘침 — 노드 trace 회복 뒤 자동)"
        out.append(("넘침 경고: " + t + " · 추적(trace) 노드 확인 필요") if o >= warn else t)
    if n > 0:
        out.append(f"넘침 경고: 늦은 채움(내부 이동 trace) 큐에서 {n:,}건을 뺐어요 — 그 거래의 내부 이동은 미확인 · 추적(trace) 노드 확인 필요")
    return " · ".join(out) or None


def uncollected_text(rt):
    if not isinstance(rt, dict):
        return None

    def _d(t):
        return datetime.fromtimestamp(float(t), KST).strftime("%Y-%m-%d") \
            if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0 else None
    try:
        a, b = int(rt.get("from") or 0), int(rt.get("to") or 0)
    except (TypeError, ValueError):
        return None
    if b <= 0:
        return None
    da, db = _d(rt.get("from_ts")), _d(rt.get("floor_ts"))
    per = f"({da or '?'}~{db}" + " 전)" if db else (f"({da}부터)" if da else "")
    return (f"옛 구간 미수집: 블록 {a:,}~{b:,}{per} — 로그 노드가 보관하지 않아 못 받음 · "
            "그 앞 보유는 기초 잔고(원가 미확인)로 맞춤")


def collect_sources(cfg: dict, st: dict, now: float) -> list:
    S = paths.STATE_DIR
    out = []
    chains = (cfg.get("chains") or {}) if cfg else {}
    hb = read_heartbeats(cfg)
    hb_src = {}
    for unit, doc in hb.items():
        for k, s in ((doc.get("sources") or {}).items()):
            hb_src[(unit, k)] = s
    used_hb = set()

    def hbinfo(unit, k):
        s = hb_src.get((unit, k))
        if not s:
            return None, None, None
        used_hb.add((unit, k))
        le = s.get("last_error") or {}
        err = le.get("msg") if s.get("ok") is False else None
        ex = []
        if s.get("current_source"):
            ex.append(str(s["current_source"]))
        if s.get("lag_sec") is not None:
            ex.append(f"지연 {fmt_ago(s['lag_sec'])}")
        elif s.get("lag_blocks") is not None:
            ex.append(f"{s['lag_blocks']}블록 뒤")
        return s.get("last_success_ts"), err, " · ".join(ex) or None

    rpcfb9 = _read(os.path.join(S, "rpc_fallback.json"), {}) or {}
    rpcfb9 = rpcfb9 if isinstance(rpcfb9, dict) else {}
    pn9 = None
    evm_ch9 = {w.get("chain") for w in ((cfg or {}).get("wallets") or []) if isinstance(w, dict) and w.get("type", "evm") == "evm"}
    for c in sorted(chains):
        if not isinstance(chains[c], dict):
            continue
        if c not in evm_ch9:
            used_hb.update({("evm", c), ("evm", f"{c}:rpclog")})
            continue
        p = os.path.join(S, f"cursor_evm_{c}.json")
        pr = os.path.join(S, f"cursor_rpc_{c}.json")
        if not chains[c].get("_auto") and not os.path.exists(p) and not os.path.exists(pr) \
                and ("evm", c) not in hb_src and ("evm", f"{c}:rpclog") not in hb_src:
            continue
        cands = []
        d = _read(p, {}) or {}
        if d.get("_synced_at"):
            cands.append(float(d["_synced_at"]))
        dr = _read(pr, {}) if os.path.exists(pr) else {}
        if (dr or {}).get("rpc_synced_at"):
            cands.append(float(dr["rpc_synced_at"]))
        hts, herr, hex_ = hbinfo("evm", c)
        if hts:
            cands.append(float(hts))
        pa9 = pace_alive(hb_src.get(("evm", c)), now)
        if pa9:
            cands.append(pa9)
            if pn9 is None:
                pn9 = _pace_note(cfg, now, "evm")
            hex_ = " · ".join(x for x in (hex_, pn9) if x)
        esu9 = (hb_src.get(("evm", c)) or {}).get("es_daily_until")
        if isinstance(esu9, (int, float)) and not isinstance(esu9, bool) and esu9 > now:
            hex_ = " · ".join(x for x in (hex_, f"이더스캔 하루 한도 쉼 — {time.strftime('%H:%M', time.localtime(float(esu9)))} 저절로 복귀") if x)
        rts, _rerr, _rex = hbinfo("evm", f"{c}:rpclog")
        if rts:
            cands.append(float(rts))
        partial9 = False
        pkind9 = None
        sr9 = hb_src.get(("evm", f"{c}:rpclog")) or {}
        bs9i = hb_src.get(("evm", c)) or {}
        itr9 = _int_track(st, c, bs9i, now) if not herr else None
        int9 = None if herr else _bs_internal_text(c, bs9i, itr9["stall"] if itr9 else None)
        if rts and sr9.get("ok") and now - float(rts) < 1800:
            ex9 = []
            bs_ts9 = max([float(x) for x in (d.get("_synced_at"), hts) if x] or [0])
            if herr or (hts is None and not d.get("_synced_at")) or (bs_ts9 and now - bs_ts9 > 900):
                ex9.append(_bs_partial_text(c, hb_src.get(("evm", c)) or {}, bs_ts9, now))
                partial9, pkind9 = True, "bs_lag"
            elif int9:
                ex9.append(int9)
                partial9, pkind9 = True, "internal"
            else:
                ex9.append("RPC 로그 트랙 실시간")
            nw9 = sr9.get("nw") if isinstance(sr9.get("nw"), dict) else None
            if nw9:
                eta9 = nw9.get("eta")
                ex9.append(f"신규 지갑 백필 {float(nw9.get('pct') or 0):.0f}%" + (f"(남은 {fmt_ago(eta9)})" if eta9 else ""))
            if partial9 or nw9:
                herr, hex_ = None, " · ".join(ex9)
        elif int9:
            partial9, pkind9, hex_ = True, "internal", int9
        gs9 = [g for g in ((d or {}).get("_retention_gaps") or []) if isinstance(g, dict)] if isinstance(d, dict) else []
        rt9 = uncollected_text({"from": min(int(g.get("from") or 0) for g in gs9), "to": max(int(g.get("to") or 0) for g in gs9),
                                "from_ts": min(gs9, key=lambda g: int(g.get("from") or 0)).get("from_ts"),
                                "floor_ts": max(gs9, key=lambda g: int(g.get("to") or 0)).get("floor_ts")}) if gs9 \
            else uncollected_text((hb_src.get(("evm", c)) or {}).get("retention"))
        if rt9:
            hex_ = " · ".join(x for x in (hex_, rt9) if x)
        lo9 = leaf_overflow_text(d) if isinstance(d, dict) else None
        if lo9:
            hex_ = " · ".join(x for x in (hex_, lo9) if x)
        td9 = trace_later_drop_text(d) if isinstance(d, dict) else None
        if td9:
            hex_ = " · ".join(x for x in (hex_, td9) if x)
        bk9h = (hb_src.get(("evm", c)) or {}).get("rpc_bk")
        if isinstance(bk9h, dict):
            t9 = []
            if bk9h.get("new"):
                t9.append(f"새 지갑 {int(bk9h['new'])}개 과거 기록 수집 중")
            if bk9h.get("internal"):
                t9.append(f"지갑 {int(bk9h['internal'])}개 내부 이동(internal) RPC 로 다시 채우는 중")
            if bk9h.get("extend"):
                t9.append(f"지갑 {int(bk9h['extend'])}개 과거 창 확장 중")
            if t9:
                hex_ = " · ".join(x for x in (hex_, " · ".join(t9) + f"(옛 구간 {float(bk9h.get('pct') or 0):.0f}%)") if x)
        hbs9 = hb_src.get(("evm", c)) or {}
        fb9h = hbs9.get("rpc_fb")
        if "rpc_fb" not in hbs9:
            r9 = rpcfb9.get(c) if isinstance(rpcfb9.get(c), dict) else {}
            fb9h = r9 if r9.get("active") and r9.get("text") else None
        if not (isinstance(fb9h, dict) and fb9h.get("text")):
            fb9h = None
        if fb9h:
            hex_ = " · ".join(x for x in (hex_, str(fb9h["text"])[:200]) if x)
        else:
            lim9h = (hb_src.get(("evm", c)) or {}).get("rpc_limited")
            if isinstance(lim9h, str) and lim9h:
                hex_ = " · ".join(x for x in (hex_, f"제한된 백업({lim9h[:80]})") if x)
            try:
                import inflow_probe
                if1 = inflow_probe.health_text(hbs9.get("inflow"), now)
                if if1:
                    hex_ = " · ".join(x for x in (hex_, if1) if x)
            except Exception:   # noqa: BLE001 [optional]
                pass
        out.append(_source(st, now, f"chain:{c}", "tj-evm", _cname(c), "chain",
                           max(cands) if cands else None, human_err(herr, _cname(c)), hex_))
        out[-1]["err_raw"] = logs.redact_urls(logs.redact_secret_text(logs.redact_urls(herr), generic=False)) if herr else None
        if rt9:
            out[-1]["uncollected"] = True
        if chains[c].get("_auto") and not cands and not out[-1]["last_success"]:
            acts9 = [float(v.get("activatedAt")) for k9, v in (_activity_pairs() or {}).items()
                     if str(k9).split(":", 1)[0] == c and isinstance(v, dict) and v.get("active") and v.get("activatedAt")]
            out[-1]["new_chain"] = min(acts9) if acts9 else out[-1]["first_seen"]
            lc9 = (hb_src.get(("evm", c)) or {}).get("last_cycle_ts")
            out[-1]["last_cycle"] = float(lc9) if isinstance(lc9, (int, float)) and not isinstance(lc9, bool) else None
            mrec9 = st.setdefault("mem", {}).setdefault(f"chain:{c}", {"last": None, "first": None})
            if out[-1]["last_cycle"] is not None:
                mrec9["cyc"] = max(out[-1]["last_cycle"], float(mrec9.get("cyc") or 0))
            elif mrec9.get("cyc"):
                out[-1]["last_cycle_mem"] = float(mrec9["cyc"])
            sd9 = (hb.get("evm") or {}).get("started")
            if out[-1]["last_cycle"] is None and isinstance(sd9, (int, float)) and not isinstance(sd9, bool) \
                    and float(sd9) > float(out[-1]["new_chain"] or 0) and float(sd9) <= now:
                out[-1]["restart_at"] = float(sd9)
        wl9 = {str(w9.get("address") or "").lower() for w9 in (cfg.get("wallets") or [])
               if isinstance(w9, dict) and w9.get("type", "evm") == "evm" and w9.get("chain") == c
               and str(w9.get("address") or "").lower().startswith("0x") and len(str(w9.get("address") or "")) == 42}
        dd9 = d if isinstance(d, dict) else {}
        cfail9 = p in _READ_FAIL
        bw9 = set() if cfail9 else {w9 for w9 in wl9 if not isinstance(dd9.get(w9), int) or isinstance(dd9.get(w9), bool)}
        job9 = dd9.get("_bfjob")
        if (isinstance(job9, dict) and job9.get("kind") == "extend"
                and isinstance(job9.get("wallets"), list)):
            bw9 |= {str(x).lower() for x in job9["wallets"] if str(x).lower() in wl9}
        if not cfail9:
            for k9, v9 in dd9.items():
                w9 = str(k9)[4:].lower() if str(k9).startswith("_bk:") else ""
                if w9 in wl9 and isinstance(v9, dict) and v9.get("why") == "new":
                    done9, to9 = v9.get("done"), v9.get("to")
                    if type(done9) is int and type(to9) is int and done9 < to9:
                        bw9.add(w9)
        if chains[c].get("rpc_log_discovery") and config.chain_discovery(c, chains[c]) != "rpc" and isinstance(dr, dict):
            for k9, v9 in dr.items():
                w9 = str(k9)[4:].lower() if str(k9).startswith("_nw:") else ""
                if w9 in wl9 and isinstance(v9, dict):
                    done9, to9 = v9.get("done"), v9.get("to")
                    if type(done9) is int and type(to9) is int and done9 < to9:
                        bw9.add(w9)
        if bw9:
            out[-1]["backfill_wallets"] = sorted(bw9)
        if partial9:
            out[-1]["partial"] = True
            bs9 = hb_src.get(("evm", c)) or {}
            out[-1]["partial_wallets"] = sorted({str(x).lower() for x in list(bs9.get("backfilling_ids") or []) + list(bs9.get("wallets_failing") or [])
                                                 if x and len(str(x)) >= 6})
            out[-1]["partial_kind"] = pkind9
            intf9 = bs9.get("int_fill") if isinstance(bs9.get("int_fill"), dict) else {}
            if intf9.get("wallets"):
                out[-1]["partial_native_wallets"] = sorted({str(x).lower() for x in intf9["wallets"] if x and len(str(x)) >= 6})
        pm9 = st.setdefault("mem", {}) if isinstance(st, dict) else {}
        if partial9:
            pr9 = pm9.get(f"partial:{c}")
            try:
                ps9 = float(pr9.get("since")) if isinstance(pr9, dict) and pr9.get("since") else None
            except (TypeError, ValueError):
                ps9 = None
            if ps9 is None or ps9 > now:
                ps9 = now
            pm9[f"partial:{c}"] = {"since": ps9}
            if pkind9 == "internal" and itr9:
                ps9 = min(ps9, float(itr9["below_since"]))
            out[-1]["partial_since"] = ps9
        else:
            pm9.pop(f"partial:{c}", None)
    if os.path.exists(os.path.join(S, "cursor_bsc.json")) or ("bsc", "bsc") in hb_src:
        d = _read(os.path.join(S, "cursor_bsc.json"), {}) or {}
        hts, herr, hex_ = hbinfo("bsc", "bsc")
        cands = [float(x) for x in (d.get("_synced_at"), hts) if x]
        out.append(_source(st, now, "chain:bsc", "tj-bsc", "BSC", "chain", max(cands) if cands else None, human_err(herr, "BSC"), hex_))
    if (os.path.exists(os.path.join(S, "cursor_sol.json")) or ("sol", "sol") in hb_src) and not runner_waiting("sol", SOL_WAIT_WHY, now):
        d = _read(os.path.join(S, "cursor_sol.json"), {}) or {}
        hts, herr, hex_ = hbinfo("sol", "sol")
        cands = [float(x) for x in (d.get("_synced_at"), hts) if x]
        pa9 = pace_alive(hb_src.get(("sol", "sol")), now)
        if pa9:
            cands.append(pa9)
            hex_ = " · ".join(x for x in (hex_, _pace_note(cfg, now, "sol")) if x)
        hcu9 = (hb_src.get(("sol", "sol")) or {}).get("helius_daycap_until")
        if isinstance(hcu9, (int, float)) and not isinstance(hcu9, bool) and hcu9 > now:
            hex_ = " · ".join(x for x in (hex_, f"헬리우스 하루 한도 쉼 — {time.strftime('%H:%M', time.localtime(float(hcu9)))} 저절로 복귀") if x)
        out.append(_source(st, now, "chain:sol", "tj-sol", "Solana", "chain", max(cands) if cands else None, human_err(herr, "Solana"), hex_))
    for (unit, k), s in hb_src.items():
        if (unit, k) in used_hb or (unit == "evm" and k.endswith(":rpclog")):
            continue
        un = unit if unit.startswith("tj-") else f"tj-{unit}"
        hts, herr, hex_ = hbinfo(unit, k)
        if unit == "sol" and k == "sol_stake":
            n9 = s.get("accounts")
            out.append(_source(st, now, f"hb:{unit}:{k}", un, "Solana 스테이킹", "stake", hts, herr,
                               (f"계정 {n9}개" if n9 is not None else None)))
            continue
        out.append(_source(st, now, f"hb:{unit}:{k}", un, _cname(k), "chain", hts, herr, hex_))
    exf = _read(os.path.join(S, "exf_state.json"), {}) or {}
    act9 = _read(os.path.join(S, "exf_active.json"), None)
    active9 = None
    if isinstance(act9, dict) and isinstance(act9.get("active"), list):
        active9 = {str(x) for x in act9["active"] if isinstance(x, str)}
    for ex, v in sorted(exf.items()):
        if not isinstance(v, dict):
            continue
        if active9 is not None and ex not in active9:
            continue
        dw = v.get("backfilled_until")
        fl = (v.get("fills") or {}).get("backfilled_until")
        vals = [float(x) for x in (dw, fl) if x]
        cur = min(vals) if len(vals) == 2 else None
        which = None
        if len(vals) == 2 and abs(float(dw) - float(fl)) > 1800:
            which = "입출금" if float(dw) < float(fl) else "체결"
        held = [str(t)[1:].replace("@", " 이전 계정 ") for t in (v["sub_held"] if isinstance(v.get("sub_held"), list) else []) if active9 is not None]
        dup = sorted(v["sub_dup"].items()) if isinstance(v.get("sub_dup"), dict) and active9 is not None else []
        dup = " · ".join(f"서브{str(t)[1:]} = " + (f"서브{str(d)[1:]}" if d else "메인") for t, d in dup)
        out.append(_source(st, now, f"ex:{ex}", "tj-exf", EX_NAME.get(ex, ex), "exchange", cur, None, " · ".join(x for x in (
            f"{which} 수집 지연" if which else None, held and f"서브 키 제외됨 — 대사 보류(서브{', 서브'.join(held)} 마지막 잔고가 0 이 아님 · 같은 계정 키를 다시 넣으면 풀림)",
            dup and f"같은 계정 중복 칸 빼고 셈({dup} · 뒤 칸 키를 지우세요)") if x) or None))
        for tag9, a9 in sorted((v.get("accts") or {}).items()) if isinstance(v.get("accts"), dict) else ():
            if not isinstance(a9, dict) or (active9 is not None and f"{ex}~{tag9}" not in active9):
                continue
            dw9 = a9.get("backfilled_until")
            fl9 = (a9.get("fills") or {}).get("backfilled_until")
            v9 = [float(x) for x in (dw9, fl9) if x]
            nm9 = f"{EX_NAME.get(ex, ex)} 서브{str(tag9)[1:]}"
            out.append(_source(st, now, f"ex:{ex}~{tag9}", "tj-exf", nm9, "exchange", min(v9) if len(v9) == 2 else None,
                               None, None if len(v9) == 2 else "서브계정 이력 받는 중 — 다 받을 때까지 이 거래소 잔고 대사 보류"))
    ub = os.path.join(S, "upbit_balances.json")
    if os.path.exists(ub) and upbit_connected():
        d = _read(ub, {}) or {}
        syp9 = os.path.join(S, "upbit_sync.json")
        sy = _read(syp9, None)
        cur9, err9, ex9 = d.get("ts"), None, None
        if sy is None and syp9 in _READ_FAIL:
            cur9, ex9 = None, "완주 기록(upbit_sync.json) 읽기 실패 — 판단 보류"
        elif isinstance(sy, dict):
            try:
                lok9 = float(sy.get("last_ok") or 0) or None
            except (TypeError, ValueError):
                lok9 = None
            try:
                bts9 = float(d.get("ts") or 0) or None
            except (TypeError, ValueError):
                bts9 = None
            cur9 = min(bts9, lok9) if (bts9 and lok9) else None
            le9 = sy.get("last_err") if isinstance(sy.get("last_err"), dict) else {}
            try:
                if le9.get("msg") and float(le9.get("ts") or 0) > float(lok9 or 0):
                    err9 = human_err(str(le9["msg"])[:200], "업비트")
            except (TypeError, ValueError):
                pass
            bits9 = [f"잔고 스냅샷 {fmt_ago(now - bts9)} 전" if bts9 else "잔고 스냅샷 없음",
                     f"체결·입출금 마지막 완주 {fmt_ago(now - lok9)} 전" if lok9 else "체결·입출금 완주 기록 없음"]
            try:
                if int(sy.get("track_pending") or 0) > 0:
                    bits9.append(f"체결 확정 대기 {int(sy['track_pending'])}건")
            except (TypeError, ValueError):
                pass
            ex9 = " · ".join(bits9)
        out.append(_source(st, now, "ex:upbit", "tj-ex", "업비트", "upbit", cur9, err9, ex9))
        if isinstance(sy, dict):
            try:
                out[-1]["track_pending"] = int(sy.get("track_pending") or 0)
                out[-1]["pending_since"] = float(sy.get("pending_since") or 0) or None
            except (TypeError, ValueError):
                out[-1]["track_pending"], out[-1]["pending_since"] = 0, None
            out[-1]["pending_block"] = bool(err9) and le9.get("kind") == "pending"
            out[-1].update({"partial": True, "partial_kind": "internal", "partial_since": sy["watch_hold"]["since"], "extra": " · ".join(x for x in (out[-1].get("extra"), str(sy["watch_hold"].get("msg") or "")[:160]) if x)} if isinstance(sy.get("watch_hold"), dict) and isinstance(sy["watch_hold"].get("since"), (int, float)) else {})
    sp = _read(os.path.join(S, "spot.json"), None)
    if isinstance(sp, dict):
        tk9 = sp.get("tick") if isinstance(sp.get("tick"), dict) else {}
        ex9 = (f"마지막 한 바퀴 {float(tk9.get('sec') or 0):.0f}초" + (f"(가장 느린 단계: {tk9['slowest']})" if tk9.get("slowest") else "")
               if tk9.get("sec") and float(tk9["sec"]) > 60 else None)
        has9 = any(isinstance(sp.get(k9), dict) and sp.get(k9) for k9 in ("usd", "ex_usd", "dex_usd"))
        wt9 = sp.get("want") if isinstance(sp.get("want"), dict) else None
        try:
            need9 = wt9 is None or bool(wt9.get("ex")) or int(wt9.get("dex") or 0) > 0
        except (TypeError, ValueError):
            need9 = True
        if not has9 and need9:
            ex9 = " · ".join(x for x in (ex9, "받은 시세 없음(바퀴는 돎)") if x)
        out.append(_source(st, now, "price:spot", "tj-web", "시세 갱신", "price", sp.get("updated") if (has9 or not need9) else None, None, ex9))
        usd_ts = [float(v) for v in (sp.get("usd_ts") or {}).values() if isinstance(v, (int, float))]
        if usd_ts:
            out.append(_source(st, now, "price:global", "tj-web", "글로벌 시세", "price", max(usd_ts)))
        want = sp.get("want") if isinstance(sp.get("want"), dict) else None
        dex = [float(v) for v in (sp.get("dex_ts") or {}).values() if isinstance(v, (int, float))]
        if want is not None and int(want.get("dex") or 0) > 0 and dex:
            wd = _read(os.path.join(S, "web_diag.json"), None)
            da = (wd or {}).get("dex_age") if isinstance(wd, dict) else None
            ts_dex, ex_dex = max(dex), None
            if isinstance(da, dict) and now - float(wd.get("ts") or 0) < 600 and da.get("p90w") is not None:
                ts_dex = float(wd["ts"]) - float(da["p90w"])
                ex_dex = f"보유 평가액 90%가 {fmt_ago(float(da['p90w']))} 안 가격 · 가장 낡은 보유 {fmt_ago(da.get('max'))}"
            out.append(_source(st, now, "price:dex", "tj-web", "DEX 가격", "dex_price", ts_dex, None, ex_dex))
        by_ex = {}
        for k, v in (sp.get("ex_ts") or {}).items():
            if isinstance(v, (int, float)) and ":" in k:
                ex = k.split(":", 1)[0]
                by_ex[ex] = max(by_ex.get(ex, 0), float(v))
        for ex in sorted(set((want or {}).get("ex") or [])):
            out.append(_source(st, now, f"price:ex:{ex}", "tj-web", f"{EX_NAME.get(ex, ex)} 시세", "ex_price",
                               by_ex.get(ex)))
    return out


def upbit_connected() -> bool:
    try:
        import paths
        env9 = {}
        try:
            with open(paths.ENV_PATH, "r", encoding="utf-8-sig") as f9:
                for line9 in f9:
                    kv9 = envfile.parse_env_line(line9)
                    if kv9 and kv9[0]:
                        env9[kv9[0]] = kv9[1]
        except FileNotFoundError:
            env9 = {}
        return bool((os.environ.get("UPBIT_ACCESS") or env9.get("UPBIT_ACCESS")) and (os.environ.get("UPBIT_SECRET") or env9.get("UPBIT_SECRET")))
    except Exception:   # noqa: BLE001 [fallback]
        return True


def runner_waiting(unit: str, whys: tuple, now: float = None) -> bool:
    rb = _read(paths.state(f"runner_{unit}.json"), None)
    if not isinstance(rb, dict) or rb.get("state") != "waiting" or rb.get("by") == "reload":
        return False
    try:
        age = (time.time() if now is None else float(now)) - float(rb.get("ts"))
    except (TypeError, ValueError):
        return False
    return -60 <= age < 120 and any(str(rb.get("why") or "").startswith(w) for w in whys)


def read_heartbeats(cfg: dict = None) -> dict:
    out = {}
    off = set((cfg or {}).get("_disabled_chains") or ())
    evm_wait = False
    if cfg is not None and not any(isinstance(w, dict) and w.get("type", "evm") == "evm" for w in cfg.get("wallets") or []):
        rb = _read(paths.state("runner_evm.json"), None)
        evm_wait = (isinstance(rb, dict) and rb.get("state") == "waiting" and rb.get("why") == "EVM 지갑 없음"
                    and isinstance(rb.get("ts"), (int, float)) and 0 <= time.time() - float(rb["ts"]) < 120)
    for p in glob.glob(os.path.join(paths.state("health"), "*.json")):
        d = _read(p, None)
        if isinstance(d, dict) and d.get("ts") and d.get("schema") == 1 and isinstance(d.get("sources"), dict):
            unit = str(d.get("unit") or os.path.basename(p)[:-5])
            if unit == "evm" and evm_wait:
                continue
            if unit == "sol" and runner_waiting("sol", SOL_WAIT_WHY):
                continue
            if unit == "evm" and off:
                d = dict(d, sources={k: v for k, v in d["sources"].items() if str(k).split(":", 1)[0] not in off})
            out[unit] = d
    return out


def _activity_pairs() -> dict:
    d = _read(paths.state("chain_activity.json"), None)
    p = d.get("pairs") if isinstance(d, dict) else None
    return p if isinstance(p, dict) else {}

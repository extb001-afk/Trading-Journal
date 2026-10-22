from __future__ import annotations
import glob
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
from datetime import datetime
from datetime import timedelta
import config, logs, net_http, paths
import db as dbm
from chk_base import CALC_BUG_SHOW_S
from chk_base import CALC_UNIT
from chk_base import DEFAULTS
from chk_base import FUT_FB_SHOW_S
from chk_base import FUT_PLACE_FRESH_S
from chk_base import FUT_WAIT_FRESH_S
from chk_base import FUT_WAIT_WARN_S
from chk_base import KST
from chk_base import RUNNER_STALE_SEC
from chk_base import SNAP_MISS_SHOW_S
from chk_base import STABLE_USD
from chk_base import TAILSCALE_BINS
from chk_base import _NON_EVM
from chk_base import _READ_FAIL
from chk_base import _read
from chk_base import fmt_ago
from chk_base import fmt_ts
from chk_logs import LogWatch
from chk_sources import _activity_pairs
import logging

log = logging.getLogger('tj-alert')

def _unreadable_rules(rel: str):
    m = re.fullmatch(r"cursor_(?:evm|rpc)_([A-Za-z0-9_.-]+)\.json", rel)
    if m:
        return [r"sync:chain:" + re.escape(m.group(1))], {m.group(1)}
    m = re.fullmatch(r"cursor_(bsc|sol)\.json", rel)
    if m:
        return [r"sync:chain:" + m.group(1)], {m.group(1)}
    m = re.fullmatch(r"health/([A-Za-z0-9_.-]+)\.json", rel)
    if m:
        u = m.group(1)
        un = u if u.startswith("tj-") else "tj-" + u
        rules = [re.escape("hb:" + un), r"sync:hb:" + re.escape(u) + r":.+"]
        if u == "evm":
            return rules + [r"sync:chain:(?!(?:bsc|sol)$).+", r"gaps:evm:.+"], {"*evm"}
        if u in _NON_EVM:
            return rules + [r"sync:chain:" + u] + ([r"quota:helius"] if u == "sol" else []), {u}
        return rules, set()
    m = re.fullmatch(r"exf_balances_([A-Za-z0-9_.-]+)\.json", rel)
    if m:
        return [r"exbal:stale", r"debt:margin"], set()
    table = {
        "onchain_check.json": [r"balcheck:(?:mismatch|stale|disc)"],
        "exf_state.json": [r"sync:ex:(?!upbit$).+"],
        "exf_active.json": [r"sync:ex:(?!upbit$).+"],
        "upbit_balances.json": [r"sync:ex:upbit", r"upbit:pending"],
        "upbit_sync.json": [r"sync:ex:upbit", r"upbit:pending"],
        "spot.json": [r"sync:price:.+"],
        "web_diag.json": [r"sync:price:dex", r"goplus:queue", r"ledger:neg", r"price:proof", r"price:unpriced", r"web:build", r"web:buildmode", r"rabby:gap"],
        "daily_cache.json": [r"daily:close"],
        "reviews_llm.json": [r"review:daily"],
        "chain_sweep.json": [r"chainsweep:(?:untracked|stale)"],
        "chain_activity.json": [r"chainsweep:untracked"],
        "backups/backup_status.json": [r"backup:age"],
        "backups/offsite_status.json": [r"offsite:age", r"offsite:kid"],
        "backfill_status.json": [r"bfstall:.+"],
        "ext_rebuild_status.json": [r"rebuild:ext"],
        "tg_cursor.json": [r"tg:dmlag"],
        "ledger.db": [r"inbox:.+"],
        "recon_hold.json": [r"ledger:recon_hold:.+"],
        "recon_adj.json": [r"ledger:adj"],
    }
    return list(table.get(rel, [])), set()


def collect_unreadable(st: dict, now: float) -> dict:
    base = os.path.realpath(paths.STATE_DIR)
    cur = {}
    for p9, err9 in list(_READ_FAIL.items()):
        rp9 = os.path.realpath(p9)
        rel = os.path.relpath(rp9, base) if rp9.startswith(base + os.sep) else os.path.basename(p9)
        cur[rel] = err9
    mem = st.setdefault("unreadable", {}) if isinstance(st, dict) else {}
    for rel in [r9 for r9 in mem if r9 not in cur]:
        mem.pop(rel, None)
    for rel in cur:
        mem.setdefault(rel, now)
    rules, fch = set(), set()
    for rel in cur:
        r9, c9 = _unreadable_rules(rel)
        rules.update(r9)
        fch.update(c9)
    return {"files": cur, "since": {r9: float(mem.get(r9) or now) for r9 in cur}, "rules": sorted(rules), "fail_chains": sorted(fch)}


def expected_day(now: float, deadline_min: int):
    nk = datetime.fromtimestamp(now, KST)
    back = 1 if nk.hour * 60 + nk.minute >= deadline_min else 2
    return nk - timedelta(days=back)


def run_since(day, run: int, deadline_min: int) -> float:
    first = day - timedelta(days=max(1, run) - 1) + timedelta(days=1)
    return datetime(first.year, first.month, first.day, deadline_min // 60, deadline_min % 60, tzinfo=KST).timestamp()


def missing_run(keys, day, fmt: str, limit: int = 14) -> int:
    n = 0
    while n < limit and (day - timedelta(days=n)).strftime(fmt) not in keys:
        n += 1
    return n


def collect_daily_review(now: float, logs: LogWatch, h: dict = None) -> tuple:
    S = paths.STATE_DIR
    t = (h or DEFAULTS)["t"]
    dc = _read(os.path.join(S, "daily_cache.json"), None)
    daily = None
    if isinstance(dc, dict):
        y = expected_day(now, t["daily_warn_min"])
        run = missing_run(dc, y, "%Y-%m-%d")
        daily = {"date": y.strftime("%Y-%m-%d"), "present": y.strftime("%Y-%m-%d") in dc,
                 "run": run, "since": run_since(y, run, t["daily_warn_min"])}
        ent9 = dc.get(daily["date"]) if daily["present"] else None
        if isinstance(ent9, dict):
            try:
                est9 = float(ent9.get("est") or 0)
                val9 = float(ent9.get("val") or 0)
            except (TypeError, ValueError):
                est9, val9 = 0.0, 0.0
            daily.update(src=ent9.get("src"), est=est9, val=val9, pend=ent9.get("pend"), why=ent9.get("why"),
                         xs=bool(ent9.get("xs")))
        ra = dc.get("_reset_at")
        try:
            ra = float(ra) if ra else None
        except (TypeError, ValueError):
            ra = None
        y_close = datetime(y.year, y.month, y.day, tzinfo=KST).timestamp() + 86400
        if ra and y_close <= ra and now - ra < float(t.get("daily_heal_sec") or 3 * 3600):
            daily["healing"] = ra
    rv = _read(os.path.join(S, "reviews_llm.json"), None)
    rsum = logs.units.get("tj-review", {}).get("review") if logs else None
    y = expected_day(now, t["review_min"])
    rkeys = set()
    for k9 in (rv or {}) if isinstance(rv, dict) else ():
        k9 = str(k9)
        rkeys.add(k9[5:] if len(k9) == 10 and k9[4] == "-" else k9)
    run = missing_run(rkeys, y, "%m-%d")
    review = {"date": y.strftime("%m-%d"), "present": isinstance(rv, dict) and y.strftime("%m-%d") in rkeys,
              "exists": isinstance(rv, dict), "run": run, "since": run_since(y, run, t["review_min"]),
              "outcome": rsum[1] if rsum else None, "outcome_msg": rsum[2] if rsum else None}
    if isinstance(rv, dict):
        nk9 = datetime.fromtimestamp(now, KST)
        for back9 in range(0, 3):
            d9 = nk9 - timedelta(days=back9)
            if d9.date() < y.date():
                break
            ent9 = rv.get(d9.strftime("%Y-%m-%d")) or rv.get(d9.strftime("%m-%d"))
            if isinstance(ent9, dict):
                review["latest"] = d9.strftime("%m-%d")
                review["latestTpl"] = ent9.get("model") == "template"
                break
    return daily, review


def collect_poison():
    try:
        import tsfix
        return tsfix.status()
    except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
        log.warning("격리 기록 집계 실패: %s", e)
        return {"error": logs.safe_err(e)[:160]}


def collect_nonevm_gaps(cfg: dict) -> dict:
    try:
        import chain_registry as _reg9
        chains9 = [c9 for c9 in _reg9.configured_chains(cfg or {}) if _reg9.available(c9)]
    except Exception:   # noqa: BLE001 [fallback]
        return {}
    out = {}
    for c9 in chains9:
        try:
            import chain_state as _cst9
            own9 = _reg9.owners(cfg, c9)
            st9 = _cst9.ChainState(c9, paths.STATE_DIR)
            gs9 = [g9 for g9 in st9.unresolved_gaps() if g9[1].get("owner") in own9]
            ids9 = {g9[0] for g9 in gs9}
            why9 = [str(x.get("why") or "") for x in st9.d["gaps"] if isinstance(x, dict) and str(x.get("id")) in ids9]
            out[c9] = {"n": len(gs9), "why": why9[-1][:160] if why9 else ""}
        except (Exception, SystemExit) as e:   # noqa: BLE001 [fallback]
            log.warning("[%s] 수집 상태(상세 누락) 읽기 실패: %s", c9, logs.safe_err(e)[:160])
            out[c9] = None
    return out


def collect_recon_hold(cfg: dict) -> dict:
    try:
        import chain_registry as _reg9
        chains9 = {c9 for c9 in _reg9.configured_chains(cfg or {}) if _reg9.available(c9)}
    except Exception:   # noqa: BLE001 [fallback]
        return {}
    if not chains9:
        return {}
    d9 = _read(paths.state("recon_hold.json"), {})
    out = {}
    for c9, r9 in (d9.items() if isinstance(d9, dict) else ()):
        if c9 in chains9 and isinstance(r9, dict):
            try:
                out[c9] = {"why": str(r9.get("why") or "")[:240], "since": float(r9.get("since")), "at": float(r9.get("at"))}
            except (TypeError, ValueError):
                continue
    return out


def _sweep_scope():
    try:
        import copy
        import chainsweep as _cs9
        cf9 = _read(paths.CONFIG_PATH, None)
        if not isinstance(cf9, dict) or not isinstance(cf9.get("wallets"), list):
            return set(), {}
        cf9 = copy.deepcopy(cf9)
        cf9.setdefault("chains", {})
        off9 = {}
        for n, cc in (cf9.get("chains") or {}).items():
            if isinstance(cc, dict) and not config.chain_enabled(n, cc):
                co9 = cc.get("_chainoff") if isinstance(cc.get("_chainoff"), dict) else {}
                try:
                    off9[n] = float(co9["at"]) if co9.get("auto") is True and co9.get("at") else None
                except (TypeError, ValueError):
                    off9[n] = None
        config.apply_activity_gate(cf9)
        return {pr for pr in _cs9.wallets(cf9)[2] if pr[0] not in off9}, off9
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
        return set(), {}


def collect_chainsweep():
    d = _read(paths.state("chain_sweep.json"), None)
    if not isinstance(d, dict):
        return None
    fs = [f for f in (d.get("findings") or []) if isinstance(f, dict)]
    joined9, off9 = _sweep_scope()
    fs = [f for f in fs if (str(f.get("chain") or ""), str(f.get("wallet") or "").lower()) not in joined9]
    n_off = 0
    if off9:
        act9 = _activity_pairs()
        keep9 = []
        for f in fs:
            c9 = str(f.get("chain") or "")
            if c9 in off9:
                at9 = off9[c9]
                a9 = (act9.get(f"{c9}:{str(f.get('wallet') or '').lower()}") or {}).get("activatedAt")
                try:
                    new9 = at9 is not None and a9 is not None and float(a9) > at9
                except (TypeError, ValueError):
                    new9 = False
                if not new9:
                    n_off += 1
                    continue
            keep9.append(f)
        fs = keep9
    try:
        import chainsweep as _cs9
        sp9 = _read(paths.BACKFILL_SPEED_PATH, None) or {}
        cf9 = _read(paths.CONFIG_PATH, None) or {}
        auto9 = bool(((cf9.get("chain_sweep") or {}) if isinstance(cf9, dict) else {}).get("auto_enable") is True)
        fs = [_cs9.refresh_reason(f, (sp9.get("chains") or {}) if isinstance(sp9, dict) else {}, auto9) for f in fs]
    except Exception:   # noqa: BLE001 [optional]
        pass
    return {"checkedAt": d.get("checkedAt"), "findings": fs, "off": n_off,
            "auto": len(d.get("autoEnabled") or []), "errors": len(d.get("errors") or []), "chains": len(d.get("chains") or {})}


def _offsite_obs(cfg, st: dict = None, now: float = None) -> dict:
    o = ((cfg or {}).get("backup") or {}).get("offsite") if isinstance((cfg or {}).get("backup"), dict) else None
    if not (isinstance(o, dict) and o.get("enabled") is True):
        if isinstance(st, dict):
            st.pop("offsite_since", None)
        return None
    since = None
    if isinstance(st, dict):
        since = st.setdefault("offsite_since", float(time.time() if now is None else now))
    return {"enabled": True, "warn_h": o.get("warn_h") if isinstance(o.get("warn_h"), (int, float)) and not isinstance(o.get("warn_h"), bool) else 36,
            "since": since, "status": _read(paths.state("backups", "offsite_status.json"), None)}


def collect_inbox(st: dict, now: float):
    mem = st.setdefault("inbox", {})
    try:
        conn = dbm.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=2)
        try:
            rows = conn.execute("SELECT stream, seg, off FROM inbox_offsets").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        _READ_FAIL[paths.DB_PATH] = type(e).__name__
        if not mem:
            return None
        return {s9: {"unknown": True, "err": logs.safe_err(e)[:120]} for s9 in sorted(mem)}
    out = {}
    for stream, seg, off in rows:
        d = os.path.join(paths.INBOX_DIR, stream)
        try:
            segs = sorted(int(f.split(".")[0]) for f in os.listdir(d) if f.endswith(".jsonl"))
        except OSError:
            continue
        backlog = 0
        for s in segs:
            try:
                sz = os.path.getsize(os.path.join(d, f"{s:09d}.jsonl"))
            except OSError:
                continue
            if s > seg:
                backlog += sz
            elif s == seg:
                backlog += max(0, sz - int(off))
        pos = [int(seg), int(off)]
        m = mem.get(stream) or {}
        if m.get("pos") != pos or backlog == 0:
            m = {"pos": pos, "since": now}
        out[stream] = {"backlog": backlog, "stalled_since": m["since"] if backlog > 0 else None}
        mem[stream] = m
    return out


def _tcp(host, port, timeout=3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_alive(port, timeout=3.0) -> bool:
    conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=timeout)
    try:
        conn.request("GET", "/api/auth/status", headers={"Connection": "close"})
        conn.getresponse()
        return True
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def _tailnet_ip():
    for b in TAILSCALE_BINS:
        try:
            out = subprocess.run([b, "ip", "-4"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        ip = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
        return ip if ip.startswith("100.") else ""
    return None


def collect_web(cfg: dict, st: dict, now: float):
    if os.environ.get("TJ_HEALTH_NO_NET") == "1":
        return None
    web = (cfg or {}).get("web") or {}
    port = int(web.get("port", 8023))
    lo = _http_alive(port)
    mode = web.get("bind", "loopback")
    res = {"lo": lo, "tail_mode": mode == "tailscale", "tail_ip": None, "ext": None}
    if mode == "tailscale":
        cache = st.setdefault("tailcache", {})
        if now - float(cache.get("at") or 0) > 300:
            cache.update(at=now, ip=_tailnet_ip())
        ip = cache.get("ip")
        res["tail_ip"] = ip
        if ip:
            res["ext"] = _tcp(ip, port)
    return res


def collect_fut_wait(now: float, path: str = None) -> list:
    d = _read(path or paths.state("exf_fut_wait.json"), None)
    if not isinstance(d, dict):
        return []
    out = []
    try:
        fresh = now - float(d.get("ts") or 0) <= FUT_WAIT_FRESH_S
    except (TypeError, ValueError):
        fresh = False
    names = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}
    act = "tj-exf 로그의 '선물 스냅샷' 실패(권한·IP·시간 오차) 확인 — 선물 정산 수집이 되살아나면 대사가 저절로 이어져요"
    base = {"unit": "tj-core", "action": act, "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "futwait"}
    w = d.get("wait") if isinstance(d.get("wait"), dict) else {}
    warn_w = {}
    for ex, it in sorted(w.items()):
        if not fresh or not isinstance(it, dict) or it.get("fallback"):
            continue
        try:
            age = now - float(it.get("since") or now)
        except (TypeError, ValueError):
            continue
        if age >= FUT_WAIT_WARN_S:
            warn_w[str(ex)] = age
    fb_live = {}
    for ex, it in sorted(w.items()):
        if fresh and isinstance(it, dict) and it.get("fallback"):
            try:
                fb_live[str(ex)] = float(it.get("since") or now)
            except (TypeError, ValueError):
                continue
    fb_at = {}
    for x in [x for x in (d.get("fb") or []) if isinstance(x, dict)]:
        ex = str(x.get("ex") or "")
        try:
            at = float(x.get("at") or 0)
        except (TypeError, ValueError):
            continue
        if ex and now - at <= FUT_FB_SHOW_S:
            fb_at[ex] = max(fb_at.get(ex, 0.0), at)
    for ex in sorted(set(names) | set(w) | {str(x.get("ex") or "") for x in (d.get("fb") or []) if isinstance(x, dict)} - {""}):
        nm = names.get(ex, ex)
        if ex in warn_w:
            out.append(dict(base, cid=f"futwait:{ex}", title=f"선물 정산 기다리며 {nm} 대사 미룸 {fmt_ago(warn_w[ex])}", level="warn",
                            detail="선물 정산 파일이 잔고 시각을 아직 못 덮어 그 거래소 잔고 대사를 미루는 중 — 3시간 넘으면 종전 규칙으로 대사"
                                   "(그 사이 선물 정산은 지난날로 들어갈 수 있음)"))
        else:
            out.append(dict(base, cid=f"futwait:{ex}", title=f"{nm} 선물 정산 대기 없음", level="ok", detail="잔고 대사 정상 진행"))
        if ex in fb_live:
            out.append(dict(base, cid=f"futwait:fb:{ex}", title=f"{nm} 선물 정산 못 받아 종전 규칙으로 대사 중 ({fmt_ago(now - fb_live[ex])}째)", level="warn",
                            detail="선물 정산 파일이 3시간 넘게 잔고를 못 덮어 종전 규칙으로 대사하는 중 — 그 사이 선물 정산은 정산 시각이 아니라 "
                                   "지난날로 들어갈 수 있어요(원장 합·보유는 맞음 · 이중 계상 없음) · 선물 수집이 되살아나면 저절로 풀려요"))
        elif ex in fb_at:
            out.append(dict(base, cid=f"futwait:fb:{ex}", title=f"{nm} 선물 정산 못 받아 종전 규칙으로 대사 ({fmt_ago(now - fb_at[ex])} 전)", level="warn",
                            detail="선물 정산 파일이 3시간 넘게 잔고를 못 덮어 종전 규칙으로 대사 — 그 사이 선물 정산은 정산 시각이 아니라 "
                                   "지난날로 들어갔을 수 있어요(원장 합·보유는 맞음 · 이중 계상 없음)"))
        else:
            out.append(dict(base, cid=f"futwait:fb:{ex}", title=f"{nm} 선물 정산 종전 규칙 전환 없음(최근 하루)", level="ok", detail="정상"))
    try:
        pfresh = now - float(d.get("ts") or 0) <= FUT_PLACE_FRESH_S
    except (TypeError, ValueError):
        pfresh = False
    pl = d.get("place") if isinstance(d.get("place"), dict) else {}
    pbase = dict(base, kind="futplace", action="상세 사유는 tj-core 로그 '선물 정산 재배치' · 미리보기 python3 tools/exf_fut_place.py — 선물 정산 수집이 되살아나거나"
                                                " 원장 백업이 생기면 다음 대사에 저절로 옮겨요(그 전 정산은 옛 배치 그대로 · 합은 맞음)")
    for ex in sorted(set(names) | {str(k) for k in pl}):
        nm = names.get(ex, ex)
        it = pl.get(ex) if pfresh and isinstance(pl.get(ex), dict) else None
        if it:
            out.append(dict(pbase, cid=f"futplace:{ex}", title=f"선물 재배치 대기: {nm} — {str(it.get('why') or '사유 모름')[:120]}", level="warn",
                            detail="지난 대사가 지난날로 보낸 선물 정산을 정산 시각으로 다시 놓는 1회 작업을 이 거래소만 미뤘어요(다른 거래소는 옮김)"))
        else:
            out.append(dict(pbase, cid=f"futplace:{ex}", title=f"{nm} 선물 재배치 대기 없음", level="ok", detail="정상"))
    return out


def collect_snap_miss(now: float, path: str = None) -> list:
    d = _read(path or paths.state("exf_snap_miss.json"), None)
    if not isinstance(d, dict) or not isinstance(d.get("ex"), dict):
        return []
    names = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "hyperliquid": "하이퍼리퀴드", "coinbase": "코인베이스"}
    base = {"unit": "tj-exf", "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "snapmiss",
            "action": "보통 선물·봇 거래가 잦아 10분마다 잔고가 움직이는 계정 — 할 일 없음(총자산이 최대 1시간 늦게 따라와요). 거래가 없는데 이어지면 tj-exf 로그 '잔고 표본 불일치' 확인"}
    out = []
    for ex in sorted({str(k) for k in d["ex"]} | {str(x) for x in (d.get("seen") if isinstance(d.get("seen"), list) else [])}):
        it = d["ex"].get(ex)
        nm = names.get(ex, ex)
        try:
            live = isinstance(it, dict) and it.get("forced") and now - float(it.get("at") or 0) <= SNAP_MISS_SHOW_S
        except (TypeError, ValueError):
            live = False
        if live:
            out.append(dict(base, cid=f"snapmiss:{ex}", title=f"잔고 표본 계속 다름: {nm} {str(it.get('why') or '').split(' ')[0]}", level="warn",
                            detail=f"10분마다 받는 잔고 표본이 {int(it.get('n') or 0)}주기째 서로 달라({str(it.get('why') or '')[:60]}) 일치 확인 없이"
                                   f" 약 1시간마다 반영 중 — 마지막 반영 {fmt_ts(float(it['forced']))}"))
        else:
            out.append(dict(base, cid=f"snapmiss:{ex}", title=f"{nm} 잔고 표본 일치", level="ok", detail="정상"))
    return out


def collect_calcguard(now: float, state_dir: str = None) -> list:
    d0 = state_dir or paths.STATE_DIR
    try:
        names = sorted(f for f in os.listdir(d0) if f.startswith("calcguard_") and f.endswith(".json"))
    except OSError:
        return []
    bug, sus, other = [], [], {}
    for fn in names:
        d = _read(os.path.join(d0, fn), None)
        if not isinstance(d, dict) or not isinstance(d.get("sites"), dict):
            continue
        proc = str(d.get("proc") or fn[len("calcguard_"):-5])
        if fn.endswith("_build.json"):
            proc += "_build"
        for site, it in d["sites"].items():
            if not isinstance(it, dict):
                continue
            try:
                last = float(it.get("last") or 0)
                nb = int(it.get("bug") or 0)
                n = int(it.get("n") or 0)
                bl = float(it.get("bug_last") or 0) if "bug_last" in it else last
                ns = int(it.get("sus") or 0)
                sl = float(it.get("sus_last") or 0)
            except (TypeError, ValueError):
                continue
            if nb > 0 and now - bl <= CALC_BUG_SHOW_S:
                bug.append((proc, str(site), nb, str(it.get("bug_why") or it.get("why") or "")[:120], bl))
            elif ns > 0 and now - sl <= CALC_BUG_SHOW_S:
                sus.append((proc, str(site), ns, str(it.get("sus_why") or "")[:120], sl))
            elif now - last <= CALC_BUG_SHOW_S:
                o = other.setdefault(proc, [0, 0])
                o[0] += 1
                o[1] += n
    out = []
    if bug:
        bug.sort(key=lambda x: -x[4])
        units = sorted({CALC_UNIT.get(b[0], "tj-web") for b in bug})
        out.append({"cid": "calc:bug", "unit": units[0], "title": "계산 코드 오류를 삼킴 — 숫자가 틀렸을 수 있음", "level": "crit",
                    "detail": " · ".join("%s %d회(%s)" % (b[1], b[2], b[3]) for b in bug[:5]) + (" 외 %d곳" % (len(bug) - 5) if len(bug) > 5 else ""),
                    "action": "개발자 확인 필요 — 화면 숫자를 믿기 전에 로그(그 자리 이름)와 최근 배포를 확인. 계산은 멈추지 않고 종전처럼 계속 중",
                    "persist": 0, "resolve": 0, "notify": True, "remind": True, "kind": "calcbug"})
    else:
        out.append({"cid": "calc:bug", "unit": "tj-web", "title": "계산 코드 오류 삼킴 없음", "level": "ok", "detail": "정상",
                    "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "calcbug"})
    if sus:
        sus.sort(key=lambda x: -x[4])
        out.append({"cid": "calc:suspect", "unit": CALC_UNIT.get(sus[0][0], "tj-web"), "title": "계산 중 의심스러운 예외를 넘김 — 숫자 확인 필요",
                    "level": "warn",
                    "detail": " · ".join("%s %d회(%s)" % (b[1], b[2], b[3]) for b in sus[:5]) + (" 외 %d곳" % (len(sus) - 5) if len(sus) > 5 else ""),
                    "action": "데이터 이상일 수도, 코드 실수일 수도 있음 — 그 자리 이름으로 로그를 보고 판단. 계산은 멈추지 않고 그 단계만 건너뜀",
                    "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "calcsuspect"})
    if other:
        out.append({"cid": "calc:swallow", "unit": "tj-web", "title": "계산 중 넘어간 예외(데이터 이상 등)", "level": "ok",
                    "detail": " · ".join("%s %d곳 %d회" % (p9, v9[0], v9[1]) for p9, v9 in sorted(other.items())) + " — 하루 안(정보 · 알림 없음)",
                    "persist": 0, "resolve": 0, "notify": False, "remind": False, "kind": "calcswallow"})
    return out


def collect_disk():
    try:
        du = shutil.disk_usage(paths.STATE_DIR)
        return {"free": du.free, "total": du.total}
    except OSError:
        return None


def collect_dm(st: dict, now: float, tg_configured: bool):
    if not tg_configured:
        st.pop("dm", None)
        return None
    cur = _read(paths.state("tg_cursor.json"), {}) or {}
    lag = 0
    for fn in ("pending_dm.jsonl", "alerts_web.jsonl", "alerts_fast.jsonl"):
        p = paths.state(fn)
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        if fn in cur:
            lag += max(0, sz - int(cur.get(fn) or 0))
    m = st.setdefault("dm", {"lag": 0, "since": None, "min": None})
    if lag == 0:
        m.update(lag=0, since=None, min=None)
    elif m.get("since") is None or lag < (m.get("min") or 0):
        m.update(lag=lag, since=now, min=lag)
    else:
        m["lag"] = lag
    return {"lag": lag, "since": m.get("since")}


def collect_tunnel(h: dict, pm2):
    if os.environ.get("TJ_HEALTH_NO_NET") == "1":
        return None
    tn = h.get("tunnel") if isinstance(h.get("tunnel"), dict) else {}
    unit = tn.get("unit") or ""
    if not unit or (pm2 is not None and unit not in pm2):
        return None
    url = tn.get("ready_url") or ""
    if not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        return None
    try:
        with net_http.urlopen(url, timeout=3) as r:
            d = json.loads(r.read().decode() or "{}")
        return {"ok": True, "n": int(d.get("readyConnections") or 0)}
    except Exception as e:   # noqa: BLE001 [fallback]
        n = None
        try:
            n = int(json.loads(e.read().decode()).get("readyConnections") or 0)
        except Exception:   # noqa: BLE001 [optional]
            pass
        return {"ok": False, "n": n or 0, "err": f"{type(e).__name__}: {logs.safe_err(e)[:100]}"}


def collect_exbal(now: float) -> list:
    out = []
    for p in sorted(glob.glob(paths.state("exf_balances_*.json"))):
        ex = os.path.basename(p)[len("exf_balances_"):-5]
        d = _read(p, None)
        if not isinstance(d, dict):
            continue
        bal = d.get("balances") if isinstance(d.get("balances"), dict) else {}
        try:
            krw = float(bal.get("KRW") or 0)
        except (TypeError, ValueError):
            krw = 0.0
        if not bal:
            continue
        out.append((ex, max(0.0, now - float(d.get("ts") or 0)), krw))
    return out


def collect_debt(logs, now: float, h: dict):
    S = paths.STATE_DIR
    sp9 = _read(os.path.join(S, "spot.json"), {}) or {}
    exu9 = sp9.get("ex_usd") if isinstance(sp9.get("ex_usd"), dict) else {}
    ext9 = sp9.get("ex_ts") if isinstance(sp9.get("ex_ts"), dict) else {}

    def px_of(ex, a):
        k9 = f"{ex}:{a}"
        try:
            v9, t9 = float(exu9.get(k9) or 0), float(ext9.get(k9) or 0)
        except (TypeError, ValueError):
            return None
        return v9 if 0 < v9 < float("inf") and 0 <= now - t9 <= 3600 else None
    out, from_file = {}, set()
    for p in glob.glob(os.path.join(S, "exf_balances_*.json")):
        ex = os.path.basename(p)[len("exf_balances_"):-5]
        d = _read(p, None)
        if not isinstance(d, dict):
            continue
        db = d.get("debts") if isinstance(d.get("debts"), dict) else (d.get("debt") if isinstance(d.get("debt"), dict) else None)
        if db is not None:
            from_file.add(ex)
            loan_q = {}
            for ln in (d.get("loans") if isinstance(d.get("loans"), list) else ()):
                for a, q in ((ln.get("debt") or {}).items() if isinstance(ln, dict) and isinstance(ln.get("debt"), dict) else ()):
                    try:
                        loan_q[str(a).upper()] = loan_q.get(str(a).upper(), 0.0) + abs(float(q))
                    except (TypeError, ValueError):
                        continue
            for k, v in db.items():
                items = v.items() if isinstance(v, dict) else [(k, v)]
                src = k if isinstance(v, dict) else "margin"
                for a, q in items:
                    try:
                        q = -abs(float(q))
                    except (TypeError, ValueError):
                        continue
                    lq = min(loan_q.get(str(a).upper(), 0.0), -q) if not isinstance(v, dict) else 0.0
                    if lq > 0:
                        out[(ex, "loan", str(a))] = -lq
                        q += lq
                    if q < -1e-12:
                        out[(ex, src, str(a))] = q
        for a, q in ((d.get("balances") or {}).items() if isinstance(d.get("balances"), dict) else ()):
            if isinstance(q, (int, float)) and q < 0:
                out[(ex, "spot", str(a))] = float(q)
    u = (logs.units.get("tj-exf") or {}) if logs else {}
    for (ex, src, a), (ts, v) in (u.get("debt") or {}).items():
        if ex in from_file or now - ts > float(h["t"].get("debt_keep_sec", 7200)):
            continue
        out.setdefault((ex, src, a), v)
    rows = []
    for (ex, src, a), q in out.items():
        pr = 1.0 if a.upper() in STABLE_USD else (px_of(ex, a) or px_of(ex, a.upper()))
        rows.append((ex, src, a, q, abs(q) * float(pr) if pr else None))
    rows.sort(key=lambda r: -(r[4] or 0))
    return rows


def _intent_entries(doc) -> list:
    out = []
    if not isinstance(doc, dict):
        return out
    try:
        if doc.get("unit") and doc.get("ts"):
            out.append((str(doc["unit"]), float(doc["ts"]), 1, f"{doc['unit']}:{doc['ts']}", None))
        for e in doc.get("entries") or []:
            if isinstance(e, dict) and e.get("unit") and e.get("ts"):
                out.append((str(e["unit"]), float(e["ts"]), max(1, int(e.get("n") or 1)), f"{e['unit']}:{e['ts']}",
                            float(e["win"]) if e.get("win") else None))
    except (TypeError, ValueError):
        pass
    return out


def _kind_t(kind: str, t: dict):
    return {"chain": ("chain_warn", "chain_crit"), "exchange": ("exchange_warn", "exchange_crit"),
            "upbit": ("upbit_warn", "upbit_crit"), "price": ("price_warn", "price_crit"),
            "ex_price": ("ex_price_warn", "ex_price_crit"), "dex_price": ("dex_price_warn", "dex_price_crit"),
            "stake": ("stake_warn", "stake_crit")}.get(kind)


def collect_keys(cfg: dict, now: float = None) -> dict:
    try:
        import settings_store
        return {"evm": settings_store.needs_etherscan(cfg or {}), "etherscan": bool(settings_store.env_value("TJ_ETHERSCAN_KEY")),
                "alchemyNeed": settings_store.needs_alchemy(cfg or {}), "alchemy": bool(settings_store.env_value("TJ_ALCHEMY_KEY")),
                "ankrNeed": settings_store.needs_ankr(cfg or {}), "ankr": bool(settings_store.env_value("TJ_ANKR_KEY")),
                "heliusNeed": settings_store.needs_helius(cfg or {}), "helius": bool(settings_store.env_value("TJ_HELIUS_KEY")),
                "alchemyRej": _alch_rej()}
    except Exception:   # noqa: BLE001 [fallback]
        return {}


def _alch_rej():
    try:
        import nodekeys
        return nodekeys.alch_rejected()
    except Exception:   # noqa: BLE001 [fallback]
        return None


def _liq_blind_checks(add, st9: dict, now: float) -> None:
    for sec9 in ("venues", "risk"):
        for k9, v9 in ((st9.get(sec9) if isinstance(st9.get(sec9), dict) else {}) or {}).items():
            if not isinstance(v9, dict) or "bl" not in v9:
                continue
            try:
                bl9 = int(v9.get("bl") or 0)
                since9 = float(v9.get("since") or 0) or None
            except (TypeError, ValueError):
                continue
            where9 = str(v9.get("where") or k9)[:60]
            lvl9 = "crit" if bl9 >= 2 else "warn" if bl9 == 1 else "ok"
            if lvl9 == "ok":
                add(f"liq:see:{k9}", "tj-exf", f"청산 감시 · {where9}", "ok", "정상", "", persist=0, resolve=60, notify=False, remind=False, kind="liqblind")
                continue
            if v9.get("read"):
                last9 = f"마지막 정상 {fmt_ts(since9)}({fmt_ago(now - since9)} 전)" if since9 else "마지막 정상 —"
            elif v9.get("prev_read"):
                last9 = f"마지막 정상 {fmt_ts(v9['prev_read'])}(재시작 전) · 재시작 뒤 한 번도 못 읽음"
            else:
                last9 = "감시 시작 뒤 한 번도 못 읽음"
            why9 = {"perm": "API 키 권한 오류", "net": "연결 실패·시간 초과", "rl": "거래소 호출 한도"}.get(v9.get("kind"), "")
            if v9.get("ok") is not False:
                why9 = "조회 대기(호출 한도·쉼)"
            det9 = (f"{last9} · 마지막으로 본 위험도: {str(v9.get('worst') or '—')[:120]}"
                    + (f" · 원인: {why9}" if why9 else "") + (f"({str(v9.get('err'))[:80]})" if v9.get("err") else ""))
            if bl9 == 1:
                title9, det9 = f"청산 감시가 {where9} 못 봄", det9 + " · 열린 포지션·대출은 없어요 — 새로 열면 발견이 늦어요"
            else:
                title9 = f"청산 감시가 {where9} 못 봄" + (" — 마지막에 위험 구간" if bl9 >= 3 else "")
            add(f"liq:see:{k9}", "tj-exf", title9, lvl9, det9,
                "거래소(앱·웹)에서 포지션·대출을 직접 확인 · 권한 오류면 API 키·IP 허용 목록 확인(설정 › 거래소 키) — 텔레그램은 청산 감시가 직접 보내요",
                since=since9, persist=0, resolve=60, notify=False, remind=False, kind="liqblind")


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, TypeError, ValueError):
        return True


def runner_alive(rec, now: float):
    if not isinstance(rec, dict) or rec.get("by") == "reload":
        return None
    try:
        age = now - float(rec.get("ts"))
    except (TypeError, ValueError):
        return None
    pid = rec.get("pid")
    alive_pid = _pid_alive(pid) if pid else True
    if age > RUNNER_STALE_SEC:
        return False, f"마지막 기록 {fmt_ago(age)} 전" + (" · 프로세스는 있음(멈춤)" if pid and alive_pid else " · 프로세스 없음")
    if not alive_pid:
        return False, f"기록 {fmt_ago(age)} 전 · 그 프로세스(pid {pid})가 없음"
    why = str(rec.get("why") or "")
    return True, ("대기: " + why[:80] if rec.get("state") == "waiting" and why else "실행 중") + f" · 기록 {fmt_ago(max(0.0, age))} 전 (pm2 없음 — 러너 기록)"


def ledger_wait_item(rc, now: float, db_path: str = None):
    if not isinstance(rc, dict) or rc.get("state") != "waiting" or rc.get("by") == "reload":
        return None
    try:
        if not now - float(rc.get("ts")) < 600:
            return None
    except (TypeError, ValueError):
        return None
    why = str(rc.get("why") or "")
    dbp = db_path or paths.DB_PATH
    ev = " · ".join(str(x) for x in (rc.get("evidence") or [])[:4])
    try:
        since = int(float(rc.get("since") or rc.get("ts")))
    except (TypeError, ValueError):
        since = None
    if why.startswith("원장 파일 없음") and not os.path.exists(dbp):
        return {"id": "ledger:missing", "kind": "missing", "title": "원장 파일 없음 — 복구 필요", "since": since,
                "detail": "예전 원장 흔적: " + ev + " — 빈 원장을 만들지 않고 기다리는 중(수집은 인박스에 쌓임)",
                "action": "python3 tools/ledger_restore.py list → restore <번호>(미리보기) → --apply · 정말 새로 시작이면 tools/ledger_restore.py new --apply"}
    if why.startswith("원장이 이 코드보다 새") and os.path.exists(dbp):
        return {"id": "ledger:newer", "kind": "newer", "title": "원장이 코드보다 새 판 — 코드 업데이트 필요", "since": since,
                "detail": why[:300] + " — core 를 띄우지 않고 기다리는 중(수집은 인박스에 쌓임)",
                "action": "README '업데이트' 절대로 코드를 최신으로(git pull → bash tools/setup.sh → 재시작) · 옛 코드를 써야 하면 python3 tools/ledger_restore.py list"}
    if why.startswith("원장 손상") and os.path.exists(dbp):
        return {"id": "ledger:corrupt", "kind": "corrupt", "title": "원장 손상 — 복구 필요", "since": since,
                "detail": "검사 결과: " + (ev or "?") + " — 원장을 열지 않고 기다리는 중(수집은 인박스에 쌓임 · 되돌리면 지금 원장은 보존본으로 남음)",
                "action": "python3 tools/ledger_restore.py list → restore <번호>(미리보기) → 유닛 정지 → --apply → pm2 start tj-core"}
    return None

"""Process runner for collector units."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import settings_store as ss
import ledger_backup

SCRIPTS = {"evm": "evm_watch.py", "sol": "sol_watch.py", "bsc": "bsc_watch.py", "core": "core.py", "web": "web.py"}
CHECK_SEC = float(os.environ.get("TJ_RUNNER_CHECK_SEC", "15"))
SETTLE_SEC = float(os.environ.get("TJ_RUNNER_SETTLE_SEC", "10"))
STOP_GRACE = 20

DEFAULT_MAX_MB = {"web": 3072}
MEM_FLOOR_MB = 256
MEM_CHECK_N = 2
MEM_KEEP_S = 86400

log = common.setup_logging("tj-runner")
NO_LEDGER_WHY = "원장 파일 없음 — 백업에서 되돌리기 필요(python3 tools/ledger_restore.py list)"
_stop = {"sig": None}
_MEM = {"restarts": [], "last": None, "rss_mb": None, "max_mb": 0}


def max_mb(unit, env=None, cfg=None) -> int:
    key = f"TJ_RUNNER_MAX_MB_{str(unit).upper()}"
    cands = [os.environ.get(key)]
    try:
        cands.append((env if env is not None else ss.read_env()).get(key))
    except Exception:
        pass
    try:
        rc = cfg if cfg is not None else ss.read_config_raw()
        mm = (rc.get("runner") or {}).get("max_mb") if isinstance(rc, dict) and isinstance(rc.get("runner"), dict) else None
        cands.append(mm.get(unit) if isinstance(mm, dict) else None)
    except Exception:
        pass
    for v in cands:
        if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
            continue
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            continue
        if n <= 0:
            return 0
        return max(MEM_FLOOR_MB, n)
    return int(DEFAULT_MAX_MB.get(unit, 0))


def rss_mb(pid):
    try:
        with open(f"/proc/{pid}/status", "r", encoding="ascii", errors="replace") as f:
            for ln in f:
                if ln.startswith("VmRSS:"):
                    return int(ln.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5).stdout.strip()
        return int(out.split()[0]) // 1024 if out else None
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def _mem_view(now=None):
    now = time.time() if now is None else now
    _MEM["restarts"] = [t for t in _MEM["restarts"] if now - t < MEM_KEEP_S]
    if not _MEM["max_mb"] and not _MEM["restarts"]:
        return None
    return {"max_mb": _MEM["max_mb"], "rss_mb": _MEM["rss_mb"], "restarts": list(_MEM["restarts"]), "last": _MEM["last"]}


def _evaluate(unit):
    try:
        cfg = ss.load_config_quiet()
    except BaseException as e:
        if isinstance(e, FileNotFoundError):
            return False, "config.json 없음 — bash tools/setup.sh 로 만드세요", "err"
        if isinstance(e, ValueError) and hasattr(e, "lineno"):
            return False, f"config.json 형식 오류 {e.lineno}행 {getattr(e, 'colno', '?')}열 — 쉼표·따옴표·괄호를 확인하세요", "err"
        if isinstance(e, PermissionError):
            return False, "config.json 을 읽을 권한이 없어요 — 파일 소유자를 확인하세요", "err"
        return False, f"config.json 읽기 실패: {type(e).__name__} — 필수 항목(wallets 등)을 확인하세요", "err"
    return ss.unit_inputs(unit, cfg)


def _beat(unit, **kw):
    try:
        mv9 = _mem_view()
        if mv9 is not None:
            kw["mem"] = mv9
        common.atomic_write_json(os.path.join(common.STATE_DIR, f"runner_{unit}.json"),
                                 dict(kw, unit=unit, pid=os.getpid(), ts=int(time.time())))
    except Exception:
        pass


def _stop_child(p):
    if p.poll() is not None:
        return
    for sig, wait in ((signal.SIGINT, STOP_GRACE), (signal.SIGTERM, 10)):
        try:
            p.send_signal(sig)
        except OSError:
            return
        t0 = time.time()
        while time.time() - t0 < wait:
            if p.poll() is not None:
                return
            time.sleep(0.2)
    try:
        p.kill()
    except OSError:
        pass
    p.wait()


def _on_signal(sig, _frm):
    _stop["sig"] = sig


def main():
    unit = sys.argv[1] if len(sys.argv) > 1 else ""
    if unit not in SCRIPTS:
        raise SystemExit("사용법: unit_runner.py evm|sol|bsc|core|web")
    common.ensure_dirs()
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), SCRIPTS[unit])
    backoff = 5.0
    last_why = None
    no_ledger_logged = False
    while _stop["sig"] is None:
        ready, why, fp = _evaluate(unit)
        if not ready:
            if why != last_why:
                log.info("[%s] 대기: %s — 웹 설정 화면에서 입력하면 자동 시작", unit, why)
                last_why = why
            _beat(unit, state="waiting", why=why, fp=fp)
            _sleep(CHECK_SEC)
            continue
        last_why = None
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        if unit == "core" and not os.path.exists(common.DB_PATH):
            ev9 = ledger_backup.prior_ledger_evidence()
            if ev9 and not ledger_backup.new_ledger_ok(consume=True):
                why9 = NO_LEDGER_WHY
                if not no_ledger_logged:
                    log.error("[core] 원장 파일 없음(%s) — 예전 원장 흔적이 있어 빈 원장을 만들지 않고 기다려요: %s. "
                              "백업에서 되돌리기: python3 tools/ledger_restore.py list → restore <백업> --apply "
                              "· 정말 새 원장으로 시작: python3 tools/ledger_restore.py new --apply", common.DB_PATH, " · ".join(ev9))
                    no_ledger_logged = True
                _beat(unit, state="waiting", why=why9, fp=fp, evidence=ev9[:6])
                _sleep(CHECK_SEC)
                continue
            env["TJ_ALLOW_NEW_LEDGER"] = "1"
            log.info("[core] 원장 없음 — %s 빈 원장 생성 허용", "새 원장 허용 표식으로" if ev9 else "첫 설치로 보고")
        log.info("[%s] 시작 (설정 지문 %s)", unit, fp)
        p = subprocess.Popen([sys.executable, script], env=env)
        started = time.time()
        _beat(unit, state="running", why="", fp=fp, child=p.pid)
        reason = None
        next_check = time.time() + CHECK_SEC
        over9 = 0
        while _stop["sig"] is None:
            if p.poll() is not None:
                reason = f"자식 종료 rc={p.returncode}"
                break
            if time.time() >= next_check:
                next_check = time.time() + CHECK_SEC
                cap9 = max_mb(unit)
                rss9 = rss_mb(p.pid) if cap9 else None
                _MEM["max_mb"], _MEM["rss_mb"] = cap9, rss9
                over9 = over9 + 1 if (cap9 and rss9 is not None and rss9 > cap9) else 0
                if over9 >= MEM_CHECK_N:
                    reason = f"메모리 상한 넘음(RSS {rss9:,}MB > 상한 {cap9:,}MB · {MEM_CHECK_N}번 연속) — 정상 종료 뒤 다시 시작"
                    _MEM["restarts"].append(int(time.time()))
                    _MEM["last"] = {"ts": int(time.time()), "rss_mb": rss9, "max_mb": cap9}
                    break
                r2, _w2, fp2 = _evaluate(unit)
                if fp2 != fp and fp2 != "err":
                    _sleep(SETTLE_SEC)
                    r3, _w3, fp3 = _evaluate(unit)
                    if fp3 == fp2:
                        reason = "설정 변경 감지 — 새 설정으로 재시작"
                        break
                _beat(unit, state="running", why="", fp=fp, child=p.pid)
            time.sleep(0.5)
        if _stop["sig"] is not None:
            _stop_child(p)
            break
        if reason.startswith("메모리"):
            log.warning("[%s] %s", unit, reason)
            _beat(unit, state="restarting", why=reason, fp=fp)
            _stop_child(p)
            backoff = 5.0 if time.time() - started > 120 else min(60.0, backoff * 2)
            _sleep(backoff)
            continue
        log.info("[%s] %s", unit, reason)
        if reason.startswith("설정"):
            log.info("[%s] 정지 신호(SIGINT) 전송 — 이어지는 KeyboardInterrupt 트레이스백은 정상 종료 과정", unit)
            _stop_child(p)
            backoff = 5.0
            continue
        backoff = 5.0 if time.time() - started > 120 else min(60.0, backoff * 2)
        _beat(unit, state="restarting", why=reason, fp=fp)
        _sleep(backoff)
    log.info("[%s] 러너 종료", unit)


def _sleep(sec):
    t0 = time.time()
    while _stop["sig"] is None and time.time() - t0 < sec:
        time.sleep(0.3)


if __name__ == "__main__":
    main()

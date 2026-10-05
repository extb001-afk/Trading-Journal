"""Process runner for collector units."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import settings_store as ss

SCRIPTS = {"evm": "evm_watch.py", "sol": "sol_watch.py", "bsc": "bsc_watch.py", "core": "core.py", "web": "web.py"}
CHECK_SEC = float(os.environ.get("TJ_RUNNER_CHECK_SEC", "15"))
SETTLE_SEC = float(os.environ.get("TJ_RUNNER_SETTLE_SEC", "10"))
STOP_GRACE = 20

log = common.setup_logging("tj-runner")
_stop = {"sig": None}


def _evaluate(unit):
    try:
        cfg = ss.load_config_quiet()
    except BaseException as e:
        return False, f"config.json 읽기 실패: {type(e).__name__}", "err"
    return ss.unit_inputs(unit, cfg)


def _beat(unit, **kw):
    try:
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
            env["TJ_ALLOW_NEW_LEDGER"] = "1"
            log.info("[core] 원장 없음 — 첫 설치로 보고 빈 원장 생성 허용")
        log.info("[%s] 시작 (설정 지문 %s)", unit, fp)
        p = subprocess.Popen([sys.executable, script], env=env)
        started = time.time()
        _beat(unit, state="running", why="", fp=fp, child=p.pid)
        reason = None
        next_check = time.time() + CHECK_SEC
        while _stop["sig"] is None:
            if p.poll() is not None:
                reason = f"자식 종료 rc={p.returncode}"
                break
            if time.time() >= next_check:
                next_check = time.time() + CHECK_SEC
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

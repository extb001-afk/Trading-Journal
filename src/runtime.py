import json
import logging
import os
import sys

import envfile
import paths

__all__ = ["CPU_RESERVE_MIN", "BUILD_PROC_MODES", "build_proc_mode", "cpu_plan", "SQLITE_MEMSTAT_WHY", "sqlite_memstatus_off",
           "parent_watch_start", "cpu_reserve_apply"]


CPU_RESERVE_MIN = 4
BUILD_PROC_MODES = ("auto", "off", "fork")
_CPU_PLAN = None
_CPU_APPLIED = False


def _env_file_value(key: str):
    if not os.path.exists(paths.ENV_PATH):
        return None
    return envfile.read_env_file().get(key)


def build_proc_mode():
    for src, get in (("env", lambda: os.environ.get("TJ_BUILD_PROC")), (".env", lambda: _env_file_value("TJ_BUILD_PROC")),
                     ("config", lambda: _cfg_build_proc())):
        try:
            v = get()
        except Exception:   # noqa: BLE001 [fallback]
            v = None
        if v is not None and str(v).strip():
            return str(v).strip().lower(), src
    return "auto", "기본"


def _cfg_build_proc():
    try:
        with open(paths.CONFIG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    v = d.get("build_proc") if isinstance(d, dict) else None
    return v if isinstance(v, str) else None


def cpu_plan() -> dict:
    global _CPU_PLAN  # noqa: PLW0603
    if _CPU_PLAN is not None:
        return _CPU_PLAN
    mode, msrc = build_proc_mode()
    p = {"on": False, "core": None, "cores": os.cpu_count() or 1, "why": ""}
    bad = mode not in BUILD_PROC_MODES and mode not in ("0", "no", "false")
    if bad:
        mode = "auto"
    inh = str(os.environ.get("TJ_CPU_PLAN") or "")
    aff = None
    if hasattr(os, "sched_getaffinity"):
        try:
            aff = sorted(os.sched_getaffinity(0))
        except OSError:
            aff = None
    if mode in ("off", "0", "no", "false"):
        p["why"] = f"꺼짐(TJ_BUILD_PROC=off · {msrc}) — 웹 안에서 빌드"
    elif not hasattr(os, "fork"):
        p["why"] = "fork 없음 — 웹 안에서 빌드"
    elif mode == "fork":
        p.update(on=True, why=f"강제(TJ_BUILD_PROC=fork · {msrc})")
        if aff and len(aff) >= CPU_RESERVE_MIN:
            p.update(core=aff[-1], cores=len(aff))
    elif not sys.platform.startswith("linux") or aff is None:
        p["why"] = "리눅스 아님 — 웹 안에서 빌드(코어 지정 기능 없음)"
    elif inh.count("/") == 1 and inh.split("/")[0].isdigit() and inh.split("/")[1].isdigit():
        c9, n9 = (int(x) for x in inh.split("/"))
        p.update(on=True, core=c9, cores=n9, why=f"코어 {n9}개 — {c9}번 = 화면 계산 전용(물려받음)")
    elif len(aff) < 2:
        p.update(cores=len(aff), why="코어 1개 — 웹 안에서 빌드")
    elif len(aff) < CPU_RESERVE_MIN:
        p.update(on=True, cores=len(aff), why=f"코어 {len(aff)}개 — {CPU_RESERVE_MIN}개 미만이라 전용 코어 없이 빌드 자식만")
    else:
        p.update(on=True, core=aff[-1], cores=len(aff), why=f"코어 {len(aff)}개 — {aff[-1]}번 = 화면 계산 전용")
    if bad:
        p["why"] += " · 모르는 TJ_BUILD_PROC 값이라 auto 로"
    if p["on"] and p["core"] is not None and not inh:
        os.environ["TJ_CPU_PLAN"] = f"{p['core']}/{p['cores']}"
    _CPU_PLAN = p
    return p


SQLITE_MEMSTAT_WHY = [""]


def _sqlite_lib():
    import ctypes
    import ctypes.util
    import importlib.util
    try:
        spec = importlib.util.find_spec("_sqlite3")
        origin = getattr(spec, "origin", None) if spec is not None else None
    except (ImportError, ValueError):
        origin = None
    try:
        if origin == "built-in":
            lib = ctypes.CDLL(None)
            if hasattr(lib, "sqlite3_config"):
                return lib, "builtin"
        elif origin and os.path.isfile(origin):
            lib = ctypes.CDLL(origin)
            if hasattr(lib, "sqlite3_config"):
                return lib, "ext"
    except OSError:
        pass
    return ctypes.CDLL(ctypes.util.find_library("sqlite3") or "libsqlite3.so.0"), "name"


def _memstatus_apply(lib) -> object:
    import ctypes
    rc = lib.sqlite3_config(9, ctypes.c_int(0))
    if rc == 21 and "sqlite3" not in sys.modules and "_sqlite3" not in sys.modules:
        lib.sqlite3_shutdown()
        rc = lib.sqlite3_config(9, ctypes.c_int(0))
    if rc != 0:
        SQLITE_MEMSTAT_WHY[0] = f"설정 거부(코드 {rc} — 이미 초기화)"
        return False
    try:
        import sqlite3 as _s9
        c9 = _s9.connect(":memory:")
        try:
            c9.execute("CREATE TABLE t9 (x)")
            c9.executemany("INSERT INTO t9 VALUES (?)", [(i,) for i in range(200)])
            c9.execute("SELECT sum(x) FROM t9").fetchall()
            rc2 = lib.sqlite3_config(9, ctypes.c_int(0))
            fn9 = lib.sqlite3_memory_used
            fn9.restype = ctypes.c_int64
            used9 = int(fn9())
            lv9 = lib.sqlite3_libversion
            lv9.restype = ctypes.c_char_p
            ver9 = (lv9() or b"").decode("ascii", "replace")
        finally:
            c9.close()
    except Exception as e:   # noqa: BLE001 [fallback]
        SQLITE_MEMSTAT_WHY[0] = f"확인 불가({type(e).__name__})"
        return "unverified"
    if rc2 == 0:
        SQLITE_MEMSTAT_WHY[0] = "파이썬 sqlite3 는 다른 SQLite 사본을 씀(끈 것은 안 쓰는 사본)"
        return False
    if ver9 != _s9.sqlite_version:
        SQLITE_MEMSTAT_WHY[0] = f"버전이 다름(끈 것 {ver9[:16]} · 파이썬 {_s9.sqlite_version[:16]})"
        return False
    if used9 != 0:
        SQLITE_MEMSTAT_WHY[0] = "파이썬 쪽 통계가 여전히 셈(memory_used > 0)"
        return False
    SQLITE_MEMSTAT_WHY[0] = "파이썬 sqlite3 와 같은 라이브러리에서 확인"
    return True


def sqlite_memstatus_off():
    if not sys.platform.startswith("linux") or not cpu_plan().get("on"):
        return None
    try:
        lib, src9 = _sqlite_lib()
        r9 = _memstatus_apply(lib)
        if src9 == "name" and r9 is not False:
            SQLITE_MEMSTAT_WHY[0] += " · 이름으로 찾은 사본"
        return r9
    except (OSError, AttributeError, TypeError, ValueError) as e:
        SQLITE_MEMSTAT_WHY[0] = f"못 끔({type(e).__name__})"
        return False


def parent_watch_start(env_key: str = "TJ_RUNNER_PID", every: float = 2.0) -> bool:
    try:
        want = int(os.environ.pop(env_key, "") or 0)
    except ValueError:
        want = 0
    if want <= 1:
        return False
    import signal
    import threading
    import time as _t
    if os.getppid() != want:
        try:
            os.kill(want, 0)
            return False
        except ProcessLookupError:
            logging.getLogger("tj").warning("부모 러너(pid %s)가 이미 없음 — 정상 종료(고아 방지)", want)
            os.kill(os.getpid(), signal.SIGINT)
            return True
        except OSError:
            return False

    def _loop():
        while True:
            _t.sleep(every)
            if os.getppid() != want:
                logging.getLogger("tj").warning("부모 러너(pid %s)가 사라짐 — 정상 종료(고아 방지)", want)
                os.kill(os.getpid(), signal.SIGINT)
                return
    threading.Thread(target=_loop, name="parent-watch", daemon=True).start()
    return True


def cpu_reserve_apply():
    global _CPU_APPLIED  # noqa: PLW0603
    if _CPU_APPLIED:
        return
    _CPU_APPLIED = True
    try:
        c9 = cpu_plan().get("core")
        if c9 is None or not hasattr(os, "sched_setaffinity"):
            return
        cur = set(os.sched_getaffinity(0))
        rest = cur - {c9}
        if rest and rest != cur:
            os.sched_setaffinity(0, rest)
    except (OSError, ValueError, TypeError):
        pass

"""Ledger writer lock (flock on core_writer.lock): one ledger writer per state folder (core, repair tools, restore)."""
from __future__ import annotations

import contextlib
import fcntl
import os
import threading
import time

LOCK_NAME = "core_writer.lock"
POLL_S = 0.2
REOPEN_MAX = 20

_HELD = {}
_MU = threading.Lock()


class LedgerBusy(SystemExit):
    pass


def lock_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), LOCK_NAME)


def _busy_msg(who: str, path: str) -> str:
    return (f"[{who}] ★원장 작성자 잠금({path})을 다른 프로세스가 쥐고 있어요 — 라이브 tj-core(또는 다른 원장 도구·복원)가 돌고 있음."
            f" 멈추고 다시(pm2 stop tj-core …) · 누가 쥐었나: lsof {path} · 원장은 그대로 뒀어요★")


def _same_file(fd: int, path: str) -> bool:
    try:
        a, b = os.fstat(fd), os.stat(path)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _flock(fd: int, wait: bool | float, who: str, path: str) -> None:
    if wait is True:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    end = time.monotonic() + max(0.0, float(wait or 0))
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            left = end - time.monotonic()
            if left <= 0:
                raise LedgerBusy(_busy_msg(who, path)) from None
            time.sleep(min(POLL_S, left))


def _reuse(path: str):
    ent = _HELD.get(path)
    if ent is None:
        return None
    if _same_file(ent[0], path):
        ent[1] += 1
        return ent[0]
    del _HELD[path]
    return None


def acquire(db_path: str, who: str, wait: bool | float = False) -> int:
    path = lock_path(db_path)
    with _MU:
        fd = _reuse(path)
    if fd is not None:
        return fd
    for _ in range(REOPEN_MAX):
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _flock(fd, wait, who, path)
        except BaseException:
            os.close(fd)
            raise
        if _same_file(fd, path):
            with _MU:
                _HELD[path] = [fd, 1]
            return fd
        os.close(fd)
    raise LedgerBusy(f"[{who}] ★원장 잠금 파일이 계속 바뀜({path}) — state 폴더를 바꾸는 작업(배포 롤백 등)이 끝난 뒤 다시★")


def release(fd: int) -> None:
    with _MU:
        for path, ent in list(_HELD.items()):
            if ent[0] == fd:
                ent[1] -= 1
                if ent[1] > 0:
                    return
                del _HELD[path]
                break
        else:
            return
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(fd)


@contextlib.contextmanager
def hold(db_path: str, who: str, wait: bool | float = False):
    fd = acquire(db_path, who=who, wait=wait)
    try:
        yield fd
    finally:
        release(fd)


def hold_if(cond: bool, db_path: str, who: str, wait: bool | float = False):
    return hold(db_path, who=who, wait=wait) if cond else contextlib.nullcontext()

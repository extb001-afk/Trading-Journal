"""File I/O conventions: atomic writes (temp file, fsync, rename), exclusive create, file locks and request-file claim."""
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import secrets
import stat
import threading
import weakref
from typing import IO, Any, Callable, Iterator, Optional, Tuple, Union

TMP_PREFIX = ".tmp_"
TMP_SUFFIX = ".tmp"
LOCK_SUFFIX = ".lock"
CLAIM_INFIX = ".claim."
_BASE_MAX = 40
_TRIES = 64
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NO_LINK = frozenset(e for e in (errno.EPERM, getattr(errno, "ENOTSUP", None), getattr(errno, "EOPNOTSUPP", None),
                                 getattr(errno, "ENOSYS", None), errno.EXDEV, errno.EMLINK) if e is not None)

PathLike = Union[str, "os.PathLike[str]"]


class _Mark:
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return "fsio." + self.name


KEEP = _Mark("KEEP")
UNCHANGED = _Mark("UNCHANGED")
DELETE = _Mark("DELETE")
Mode = Union[int, None, _Mark]


class DirSyncError(OSError):
    pass


class CreateError(OSError):
    pass


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _perm_for(path: str, mode: Mode) -> Optional[int]:
    if mode is None:
        return None
    if mode is KEEP:
        try:
            return stat.S_IMODE(os.stat(path).st_mode)
        except FileNotFoundError:
            return 0o600
    return int(mode)


def _open_temp(path: str, mode: Mode, *, create_error: bool = False) -> Tuple[int, str]:
    d = os.path.dirname(path) or "."
    base = os.path.basename(path)[:_BASE_MAX]
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    create = 0o666 if mode is None else 0o600
    for _ in range(_TRIES):
        tmp = os.path.join(d, "%s%s.%s%s" % (TMP_PREFIX, base, secrets.token_hex(6), TMP_SUFFIX))
        try:
            fd = os.open(tmp, flags, create)
        except FileExistsError:
            continue
        except OSError as e:
            if create_error:
                raise CreateError(e.errno, "새 파일을 만들지 못함: %s" % (e.strerror or e), path) from e
            raise
        break
    else:
        raise (CreateError if create_error else FileExistsError)(errno.EEXIST, "임시 파일 이름을 만들지 못함", path)
    try:
        perm = _perm_for(path, mode)
        if perm is not None:
            os.fchmod(fd, perm)
    except BaseException:
        os.close(fd)
        _unlink_quiet(tmp)
        raise
    return fd, tmp


def _fsync_dir(d: str) -> None:
    try:
        fd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        raise DirSyncError(e.errno, "폴더 fsync 실패(교체는 끝남): %s" % (e.strerror or e), d) from e


@contextlib.contextmanager
def atomic_open(path: PathLike, *, binary: bool = False, mode: Mode = 0o600, fsync: bool = True, dir_fsync: bool = True,
                makedirs: bool = True) -> Iterator[IO]:
    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    if makedirs:
        os.makedirs(d, exist_ok=True)
    fd, tmp = _open_temp(path, mode)
    try:
        f = os.fdopen(fd, "wb") if binary else os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        _unlink_quiet(tmp)
        raise
    try:
        with f:
            yield f
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise
    if dir_fsync:
        _fsync_dir(d)


def atomic_write_bytes(path: PathLike, data: bytes, *, mode: Mode = 0o600, fsync: bool = True, dir_fsync: bool = True,
                       makedirs: bool = True) -> None:
    with atomic_open(path, binary=True, mode=mode, fsync=fsync, dir_fsync=dir_fsync, makedirs=makedirs) as f:
        f.write(data)


def atomic_write_text(path: PathLike, text: str, *, mode: Mode = 0o600, fsync: bool = True, dir_fsync: bool = True,
                      makedirs: bool = True) -> None:
    with atomic_open(path, mode=mode, fsync=fsync, dir_fsync=dir_fsync, makedirs=makedirs) as f:
        f.write(text)


def atomic_write_json(path: PathLike, obj: Any, *, mode: Mode = 0o600, fsync: bool = True, dir_fsync: bool = True,
                      makedirs: bool = True, newline: bool = False, **json_kw) -> None:
    with atomic_open(path, mode=mode, fsync=fsync, dir_fsync=dir_fsync, makedirs=makedirs) as f:
        json.dump(obj, f, **json_kw)
        if newline:
            f.write("\n")


def _create_direct(path: str, data: bytes, mode: Mode, fsync: bool) -> bool:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC, 0o666 if mode is None else 0o600)
    except FileExistsError:
        return False
    except OSError as e:
        raise CreateError(e.errno, "대상 이름을 만들지 못함: %s" % (e.strerror or e), path) from e
    try:
        try:
            perm = _perm_for(path, 0o600 if mode is KEEP else mode)
            if perm is not None:
                os.fchmod(fd, perm)
            f = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with f:
            f.write(data)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
    except BaseException:
        _unlink_quiet(path)
        raise
    return True


def create_exclusive(path: PathLike, data: bytes, *, mode: Mode = 0o600, fsync: bool = True, dir_fsync: bool = True,
                     makedirs: bool = True) -> bool:
    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    if makedirs:
        os.makedirs(d, exist_ok=True)
    fd, tmp = _open_temp(path, mode, create_error=True)
    try:
        try:
            f = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with f:
            f.write(data)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError as e:
            if e.errno not in _NO_LINK:
                raise CreateError(e.errno, "대상 이름을 만들지 못함: %s" % (e.strerror or e), path) from e
            if not _create_direct(path, data, mode, fsync):
                return False
    finally:
        _unlink_quiet(tmp)
    if dir_fsync:
        _fsync_dir(d)
    return True


def claim(path: PathLike) -> Optional[str]:
    path = os.fspath(path)
    dst = "%s%s%d" % (path, CLAIM_INFIX, os.getpid())
    try:
        os.rename(path, dst)
    except FileNotFoundError:
        return None
    return dst


_TGUARD = threading.Lock()
_TLOCKS = {}
_TOWNER = {}
_RLOCKS = weakref.WeakSet()


def lock_path(path: PathLike) -> str:
    return os.fspath(path) + LOCK_SUFFIX


def _tlock(key: str) -> threading.Lock:
    with _TGUARD:
        lk = _TLOCKS.get(key)
        if lk is None:
            lk = _TLOCKS[key] = threading.Lock()
        return lk


def _lock_fd(lp: str) -> int:
    os.makedirs(os.path.dirname(lp) or ".", mode=0o700, exist_ok=True)
    try:
        fd = os.open(lp, os.O_RDONLY | os.O_CREAT | _O_CLOEXEC, 0o600)
    except PermissionError as e:
        raise PermissionError(e.errno, "잠금 파일을 열 수 없음(다른 사용자·root 가 만든 파일?) — 소유자를 이 사용자로 바꾸거나 지운 뒤 다시: %s" % lp,
                              lp) from e
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _unlock_fd(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(path: PathLike, *, lock_file: Optional[PathLike] = None) -> Iterator[None]:
    lp = os.path.abspath(os.fspath(lock_file) if lock_file is not None else lock_path(path))
    me = threading.get_ident()
    if _TOWNER.get(lp) == me:
        raise RuntimeError("fsio.locked 중첩 — 이 스레드가 같은 잠금을 이미 쥠: %s" % lp)
    tl = _tlock(lp)
    tl.acquire()
    try:
        _TOWNER[lp] = me
        fd = _lock_fd(lp)
        try:
            yield
        finally:
            _unlock_fd(fd)
    finally:
        _TOWNER.pop(lp, None)
        tl.release()


class FileRLock:

    def __init__(self, lock_file: Union[PathLike, Callable[[], PathLike]]):
        self._lock_file = lock_file
        self._reset()
        _RLOCKS.add(self)

    def _reset(self) -> None:
        self._rlock = threading.RLock()
        self._depth = 0
        self._owner = None
        self._fd = None

    def path(self) -> str:
        lf = self._lock_file
        return os.path.abspath(os.fspath(lf() if callable(lf) else lf))

    def acquire(self) -> bool:
        self._rlock.acquire()
        if self._depth == 0:
            try:
                self._fd = _lock_fd(self.path())
            except BaseException:
                self._rlock.release()
                raise
            self._owner = threading.get_ident()
        self._depth += 1
        return True

    def release(self) -> None:
        if self._depth <= 0 or self._owner != threading.get_ident():
            raise RuntimeError("잡지 않은 FileRLock 풀기")
        self._depth -= 1
        if self._depth == 0:
            fd, self._fd, self._owner = self._fd, None, None
            try:
                _unlock_fd(fd)
            finally:
                self._rlock.release()
        else:
            self._rlock.release()

    def __enter__(self) -> "FileRLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def _after_fork_child() -> None:
    global _TGUARD, _TLOCKS, _TOWNER
    _TGUARD = threading.Lock()
    _TLOCKS = {}
    _TOWNER = {}
    for r in list(_RLOCKS):
        r._reset()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


def _load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def locked_update_json(path: PathLike, fn: Callable[[Any], Any], *, load: Optional[Callable[[str], Any]] = None,
                       lock_file: Optional[PathLike] = None, write: Optional[Callable[[str, Any], None]] = None) -> Any:
    path = os.fspath(path)
    with locked(path, lock_file=lock_file):
        new = fn((load or _load_json)(path))
        if new is UNCHANGED:
            return new
        if new is DELETE:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            return new
        if new is None:
            raise TypeError("locked_update_json: fn 이 None 을 돌려줌 — 그대로면 fsio.UNCHANGED, 지우려면 fsio.DELETE")
        (write or atomic_write_json)(path, new)
        return new

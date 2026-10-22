import json
import logging
import os

import fsio

__all__ = ["atomic_write_json", "write_json_if_changed", "append_durable_jsonl", "read_json", "read_control_json"]


def atomic_write_json(path: str, obj) -> None:
    fsio.atomic_write_json(path, obj, ensure_ascii=False, separators=(",", ":"))


_JSON_LAST = {}


def write_json_if_changed(path: str, obj) -> bool:
    import hashlib as _hl
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=isinstance(obj, dict))
    dg = _hl.sha1(data.encode("utf-8")).hexdigest()
    last = _JSON_LAST.get(path)
    if last and last[0] == dg:
        try:
            st = os.stat(path)
            if (st.st_mtime_ns, st.st_size) == last[1:]:
                return False
        except OSError:
            pass
    atomic_write_json(path, obj)
    try:
        st = os.stat(path)
        _JSON_LAST[path] = (dg, st.st_mtime_ns, st.st_size)
    except OSError:
        _JSON_LAST.pop(path, None)
    return True


def append_durable_jsonl(path: str, obj) -> None:
    existed = os.path.exists(path)
    with open(path, "a+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    if not existed:
        d = os.path.dirname(path) or "."
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        dir_fd = os.open(d, flags)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit(f"상태 파일 손상: {path}: {e}")


def read_control_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (ValueError, OSError) as e:
        import time as _t
        dst = path + ".bad"
        if os.path.exists(dst):
            dst = f"{path}.bad.{int(_t.time())}_{os.getpid()}"
        try:
            os.replace(path, dst)
        except OSError:
            dst = "(옮기지 못함)"
        logging.getLogger("tj").warning("제어 파일 형식 오류 — 요청 없음으로 보고 계속(원본 → %s): %s: %s",
                                        os.path.basename(dst), os.path.basename(path), str(e)[:160])
        return default

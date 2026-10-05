"""Event inbox shared by collectors and the ledger core."""
import fcntl
import json
import os
import time

SEG_MAX_BYTES = 8 * 1024 * 1024
SEG_MAX_AGE_SEC = 3600
LOCK_FILE = ".queue.lock"


class SegmentWriter:
    def __init__(self, dirpath: str):
        self.dir = dirpath
        os.makedirs(dirpath, exist_ok=True)
        self._fh = None
        self._seg = None
        self._opened_at = 0.0
        self._needs_dir_fsync = False

    def _seg_path(self, seg: int) -> str:
        return os.path.join(self.dir, f"{seg:09d}.jsonl")

    def _latest_seg(self) -> int:
        segs = [int(f.split(".")[0]) for f in os.listdir(self.dir) if f.endswith(".jsonl")]
        return max(segs) if segs else 1

    def _resume_seg(self) -> int:
        seg = self._latest_seg()
        path = self._seg_path(seg)
        if os.path.exists(path) and os.path.getsize(path):
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                complete = f.read(1) == b"\n"
            if not complete:
                with open(path, "ab") as f:
                    f.write(b"\n")
                    f.flush()
                    os.fsync(f.fileno())
                seg += 1
        return seg

    def _open(self, seg: int) -> None:
        self._fh = open(self._seg_path(seg), "ab", buffering=0)
        self._seg = seg
        self._opened_at = time.time()
        self._needs_dir_fsync = True

    def append(self, record: dict) -> None:
        with open(os.path.join(self.dir, LOCK_FILE), "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                self._append_locked(record)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _append_locked(self, record: dict) -> None:
        seg = self._resume_seg()
        if self._fh is None:
            self._open(seg)
        elif self._seg != seg or not os.path.exists(self._seg_path(self._seg)):
            self._fh.close()
            self._open(seg)
        if (os.path.getsize(self._seg_path(self._seg)) >= SEG_MAX_BYTES
                or time.time() - self._opened_at >= SEG_MAX_AGE_SEC):
            self._fh.close()
            self._open(self._seg + 1)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        pending = memoryview((line + "\n").encode("utf-8"))
        while pending:
            written = self._fh.write(pending)
            if not written:
                raise OSError("inbox 부분 쓰기: 진행 없음")
            pending = pending[written:]
        self._fh.flush()
        os.fsync(self._fh.fileno())
        if self._needs_dir_fsync:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            dir_fd = os.open(self.dir, flags)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            self._needs_dir_fsync = False

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


class SegmentReader:

    def __init__(self, dirpath: str):
        self.dir = dirpath
        os.makedirs(dirpath, exist_ok=True)

    def _segs(self):
        return sorted(int(f.split(".")[0]) for f in os.listdir(self.dir) if f.endswith(".jsonl"))

    def _path(self, seg: int) -> str:
        return os.path.join(self.dir, f"{seg:09d}.jsonl")

    def read_batch(self, seg: int, off: int, max_records: int = 500):
        out = []
        segs = self._segs()
        if not segs:
            return out, seg, off
        if seg not in segs:
            later = [s for s in segs if s > seg]
            if not later:
                return out, seg, off
            seg, off = later[0], 0
        while len(out) < max_records:
            path = self._path(seg)
            try:
                with open(path, "rb") as f:
                    f.seek(off)
                    while len(out) < max_records:
                        pos = f.tell()
                        line = f.readline()
                        if not line:
                            break
                        if not line.endswith(b"\n"):
                            return out, seg, pos
                        try:
                            rec = json.loads(line)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            rec = {"kind": "_corrupt", "raw": line.decode("utf-8", errors="replace")[:200],
                                   "raw_hex": line.hex()}
                        out.append((rec, seg, f.tell()))
                    off = f.tell()
            except FileNotFoundError:
                pass
            nxt = [s for s in self._segs() if s > seg]
            at_eof = not os.path.exists(self._path(seg)) or off >= os.path.getsize(self._path(seg))
            if nxt and at_eof and len(out) < max_records:
                seg, off = nxt[0], 0
                continue
            break
        return out, seg, off

    def gc(self, consumed_seg: int, consumed_off: int) -> None:
        with open(os.path.join(self.dir, LOCK_FILE), "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                self._gc_locked(consumed_seg)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _gc_locked(self, consumed_seg: int) -> None:
        segs = self._segs()
        if not segs:
            return
        active = segs[-1]
        for s in segs:
            if s >= active or s >= consumed_seg:
                continue
            try:
                os.unlink(self._path(s))
            except OSError:
                pass

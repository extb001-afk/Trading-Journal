"""Scheduled ledger backups."""
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import common

KST = timezone(timedelta(hours=9))
BACKUP_DIR = os.path.join(common.STATE_DIR, "backups")
STATUS_PATH = os.path.join(BACKUP_DIR, "backup_status.json")
AT_HM = (4, 30)
KEEP_DB = 3
KEEP_DB_MAX = 30
KEEP_JSON = 30
MIN_FREE = 10 * 1024 ** 3
RETRY_S = 3600
START_GRACE_S = 600
_DB_RX = re.compile(r"^ledger_(\d{8})\.db$")
_JS_RX = re.compile(r"^prefs_(\d{8})\.json$")
_FD_RX = re.compile(r"^files_(\d{8})$")
KEEP_FILES = 30
FILES_STATE = ("daily_px.json",)
FILES_STATE_RX = re.compile(r"^reviews_llm[\w-]*\.json$")
CONFIG_KEYS = ("wallets", "exchange_addresses")

_lock = threading.Lock()
_thread = None
_t0 = time.time()
_perm_done = False
_last_check = 0.0
CHECK_EVERY_S = 60


def _read_status() -> dict:
    try:
        d = json.load(open(STATUS_PATH, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_status(d: dict):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    common.atomic_write_json(STATUS_PATH, d)


def _secure_perms(db_path: str):
    for p in (db_path, db_path + "-wal", db_path + "-shm"):
        try:
            if os.path.exists(p) and (os.stat(p).st_mode & 0o077):
                os.chmod(p, 0o600)
        except OSError:
            pass


def keep_db(config_path: str = None) -> int:
    try:
        cfg = json.load(open(config_path or common.CONFIG_PATH, encoding="utf-8"))
        v = (cfg.get("backup") or {}).get("keep_db") if isinstance(cfg, dict) else None
        if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= KEEP_DB_MAX:
            return v
    except (OSError, ValueError, AttributeError):
        pass
    return KEEP_DB


def _rotate(rx, keep: int):
    names = sorted((n for n in os.listdir(BACKUP_DIR) if rx.match(n)), reverse=True)
    gone = []
    for n in names[keep:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, n))
            gone.append(n)
        except OSError:
            pass
    return gone


def due(now: float, st: dict) -> bool:
    k = datetime.fromtimestamp(now, KST)
    if (k.hour, k.minute) < AT_HM:
        return False
    if st.get("last_date") == k.strftime("%Y%m%d"):
        return False
    return now - float(st.get("last_try") or 0) >= RETRY_S


def dump_prefs(db_path: str, state_dir: str) -> dict:
    out = {"ts": int(time.time())}
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(db_path), uri=True, timeout=30)
        try:
            c.row_factory = sqlite3.Row
            out["decisions"] = [dict(r) for r in c.execute("SELECT * FROM decisions").fetchall()]
        finally:
            c.close()
    except sqlite3.Error as e:
        out["decisions_err"] = common.safe_err(e)[:200]
    for name in ("ui_prefs.json", "outflow_decisions.json"):
        p = os.path.join(state_dir, name)
        if os.path.exists(p):
            try:
                out[name[:-5]] = json.load(open(p, encoding="utf-8"))
            except (OSError, ValueError) as e:
                out[name[:-5] + "_err"] = common.safe_err(e)[:200]
    return out


def backup_files(day: str, state_dir: str, config_path: str = None) -> dict:
    d9 = os.path.join(BACKUP_DIR, f"files_{day}")
    os.makedirs(d9, exist_ok=True)
    try:
        os.chmod(d9, 0o700)
    except OSError:
        pass
    out = {}

    def _put(name, data: bytes):
        tmp = os.path.join(d9, name + ".tmp")
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, os.path.join(d9, name))
        out[name] = len(data)

    names = [n for n in FILES_STATE if os.path.exists(os.path.join(state_dir, n))]
    try:
        names += sorted(n for n in os.listdir(state_dir) if FILES_STATE_RX.match(n))
    except OSError:
        pass
    for n in names:
        try:
            with open(os.path.join(state_dir, n), "rb") as f:
                _put(n, f.read())
        except OSError as e:
            out[n] = f"err: {common.safe_err(e)}"[:200]
    sl9 = os.path.join(state_dir, "seed_local")
    if os.path.isdir(sl9):
        for root9, _d9, fs9 in os.walk(sl9):
            for f9 in sorted(fs9):
                if not f9.endswith(".json"):
                    continue
                rel9 = os.path.relpath(os.path.join(root9, f9), sl9).replace(os.sep, "__")
                try:
                    with open(os.path.join(root9, f9), "rb") as fh9:
                        _put("seed_local__" + rel9, fh9.read())
                except OSError as e:
                    out["seed_local__" + rel9] = f"err: {common.safe_err(e)}"[:200]
    cp = config_path or common.CONFIG_PATH
    if os.path.exists(cp):
        try:
            cfg = json.load(open(cp, encoding="utf-8"))
            sub = {k: cfg.get(k) for k in CONFIG_KEYS if isinstance(cfg, dict) and k in cfg}
            _put("config_subset.json", json.dumps(sub, ensure_ascii=False, indent=1).encode("utf-8"))
        except (OSError, ValueError) as e:
            out["config_subset.json"] = f"err: {common.safe_err(e)}"[:200]
    return out


def _rotate_dirs(rx, keep: int):
    names = sorted((n for n in os.listdir(BACKUP_DIR) if rx.match(n) and os.path.isdir(os.path.join(BACKUP_DIR, n))), reverse=True)
    gone = []
    for n in names[keep:]:
        try:
            shutil.rmtree(os.path.join(BACKUP_DIR, n))
            gone.append(n)
        except OSError:
            pass
    return gone


def run_once(db_path: str = None, now: float = None, log=None) -> dict:
    db_path = db_path or common.DB_PATH
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, KST).strftime("%Y%m%d")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    try:
        os.chmod(BACKUP_DIR, 0o700)
    except OSError:
        pass
    st = _read_status()
    st.setdefault("created", int(now))
    st["last_try"] = int(now)
    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    free = shutil.disk_usage(BACKUP_DIR).free
    st["free"] = int(free)
    if free < max(MIN_FREE, int(size * 1.2)):
        st.update(skip="disk", skip_at=int(now))
        _write_status(st)
        if log:
            log.warning("원장 정기 백업 건너뜀 — 디스크 여유 %.1fGB < 필요 %.1fGB(1시간 뒤 재시도)",
                        free / 1024 ** 3, max(MIN_FREE, size * 1.2) / 1024 ** 3)
        return st
    t0 = time.time()
    dst_path = os.path.join(BACKUP_DIR, f"ledger_{day}.db")
    tmp = dst_path + ".tmp"
    try:
        for sfx in ("", "-wal", "-shm", "-journal"):
            if os.path.exists(tmp + sfx):
                os.remove(tmp + sfx)
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        os.close(fd)
        src = sqlite3.connect(common.sqlite_ro_uri(db_path), uri=True, timeout=60)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            jm = (dst.execute("PRAGMA journal_mode=DELETE").fetchone() or [""])[0]
            ok = dst.execute("SELECT count(*) FROM meta").fetchone()
            if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise sqlite3.DatabaseError("백업본 무결성 검사 실패 — 기존 백업 유지")
        finally:
            dst.close()
            src.close()
        if not ok or not ok[0]:
            raise sqlite3.DatabaseError("백업본 meta 비어 있음")
        if str(jm).lower() != "delete":
            raise sqlite3.DatabaseError(f"백업본 저널 전환 실패({jm})")
        for sfx in ("-wal", "-shm"):
            if os.path.exists(tmp + sfx):
                os.remove(tmp + sfx)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dst_path)
        prefs = dump_prefs(db_path, os.path.dirname(db_path))
        jp = os.path.join(BACKUP_DIR, f"prefs_{day}.json")
        fd = os.open(jp + ".tmp", os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False)
        os.replace(jp + ".tmp", jp)
        try:
            st["files"] = backup_files(day, os.path.dirname(db_path))
            st["files_err"] = None
        except Exception as e9:
            st["files_err"] = f"{type(e9).__name__}: {common.safe_err(e9)}"[:200]
        gone = _rotate(_DB_RX, keep_db()) + _rotate(_JS_RX, KEEP_JSON) + _rotate_dirs(_FD_RX, KEEP_FILES)
        st.update(last_ok=int(time.time()), last_date=day, last_path=dst_path, size=os.path.getsize(dst_path),
                  dur=round(time.time() - t0, 1), skip=None, err=None)
        _write_status(st)
        if log:
            log.info("원장 정기 백업 완료: %s (%.2fGB, %.0f초)%s", os.path.basename(dst_path), st["size"] / 1024 ** 3, st["dur"],
                     f" · 회전 삭제 {len(gone)}개" if gone else "")
    except Exception as e:
        for sfx in ("", "-wal", "-shm", "-journal"):
            try:
                if os.path.exists(tmp + sfx):
                    os.remove(tmp + sfx)
            except OSError:
                pass
        st.update(err=f"{type(e).__name__}: {common.safe_err(e)}"[:200], skip=None)
        _write_status(st)
        if log:
            log.warning("원장 정기 백업 실패(1시간 뒤 재시도): %s", st["err"])
    return st


def tick(log=None, now: float = None, db_path: str = None) -> bool:
    global _thread, _perm_done, _last_check
    try:
        now = time.time() if now is None else now
        if now - _last_check < CHECK_EVERY_S:
            return False
        _last_check = now
        db_path = db_path or common.DB_PATH
        if not _perm_done:
            _perm_done = True
            _secure_perms(db_path)
            if not os.path.exists(STATUS_PATH):
                _write_status({"created": int(now)})
        if now - _t0 < START_GRACE_S:
            return False
        with _lock:
            if _thread is not None and _thread.is_alive():
                return False
            if not due(now, _read_status()):
                return False
            _thread = threading.Thread(target=run_once, args=(db_path, None, log), daemon=True, name="ledger-backup")
            _thread.start()
        return True
    except Exception as e:
        if log:
            log.warning("원장 정기 백업 점검 실패(다음 주기): %s", e)
        return False

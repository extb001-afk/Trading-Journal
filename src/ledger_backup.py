"""Scheduled ledger backups."""
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime

import logs, paths, statefile
import db as dbm
import fsio

from timeutil import KST
AT_HM = (4, 30)
KEEP_DB = 3
KEEP_DB_MAX = 30
KEEP_JSON = 30
MIN_FREE = 512 * 1024 ** 2
RETRY_S = 3600
START_GRACE_S = 600
_DB_RX = re.compile(r"^ledger_(\d{8})\.db$")
_JS_RX = re.compile(r"^prefs_(\d{8})\.json$")
_FD_RX = re.compile(r"^files_(\d{8})$")
KEEP_FILES = 30
FILES_STATE = ("daily_px.json", "other_assets.json", "settings.json", "nft_prefs.json", "day_memos.json",
               "first_seen_px.json",
               "genuine_tokens.json")
FILES_STATE_RX = re.compile(r"^reviews_llm[\w-]*\.json$")
CONFIG_KEYS = ("wallets", "exchange_addresses", "chain_wallets")

_lock = threading.Lock()
_thread = None
_t0 = time.time()
_perm_done = False
_last_check = 0.0
CHECK_EVERY_S = 60


def _read_status() -> dict:
    try:
        d = json.load(open(paths.state("backups", "backup_status.json"), encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_status(d: dict):
    os.makedirs(paths.state("backups"), exist_ok=True)
    statefile.atomic_write_json(paths.state("backups", "backup_status.json"), d)


def _secure_perms(db_path: str):
    for p in (db_path, db_path + "-wal", db_path + "-shm"):
        try:
            if os.path.exists(p) and (os.stat(p).st_mode & 0o077):
                os.chmod(p, 0o600)
        except OSError:
            pass


def keep_db(config_path: str = None) -> int:
    try:
        cfg = json.load(open(config_path or paths.CONFIG_PATH, encoding="utf-8"))
        v = (cfg.get("backup") or {}).get("keep_db") if isinstance(cfg, dict) else None
        if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= KEEP_DB_MAX:
            return v
    except (OSError, ValueError, AttributeError):
        pass
    return KEEP_DB


def _rotate(rx, keep: int):
    names = sorted((n for n in os.listdir(paths.state("backups")) if rx.match(n)), reverse=True)
    gone = []
    for n in names[keep:]:
        try:
            os.remove(os.path.join(paths.state("backups"), n))
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
        c = dbm.connect(paths.sqlite_ro_uri(db_path), uri=True, timeout=30)
        try:
            c.row_factory = sqlite3.Row
            out["decisions"] = [dict(r) for r in c.execute("SELECT * FROM decisions").fetchall()]
        finally:
            c.close()
    except sqlite3.Error as e:
        out["decisions_err"] = logs.safe_err(e)[:200]
    for name in ("ui_prefs.json", "outflow_decisions.json"):
        p = os.path.join(state_dir, name)
        if os.path.exists(p):
            try:
                out[name[:-5]] = json.load(open(p, encoding="utf-8"))
            except (OSError, ValueError) as e:
                out[name[:-5] + "_err"] = logs.safe_err(e)[:200]
    return out


def backup_files(day: str, state_dir: str, config_path: str = None) -> dict:
    d9 = os.path.join(paths.state("backups"), f"files_{day}")
    os.makedirs(d9, exist_ok=True)
    try:
        os.chmod(d9, 0o700)
    except OSError:
        pass
    out = {}

    def _put(name, data: bytes):
        fsio.atomic_write_bytes(os.path.join(d9, name), data, fsync=False, dir_fsync=False, makedirs=False)
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
            out[n] = f"err: {logs.safe_err(e)}"[:200]
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
                    out["seed_local__" + rel9] = f"err: {logs.safe_err(e)}"[:200]
    cp = config_path or paths.CONFIG_PATH
    if os.path.exists(cp):
        try:
            cfg = json.load(open(cp, encoding="utf-8"))
            sub = {k: cfg.get(k) for k in CONFIG_KEYS if isinstance(cfg, dict) and k in cfg}
            _put("config_subset.json", json.dumps(sub, ensure_ascii=False, indent=1).encode("utf-8"))
        except (OSError, ValueError) as e:
            out["config_subset.json"] = f"err: {logs.safe_err(e)}"[:200]
    return out


def _rotate_dirs(rx, keep: int):
    names = sorted((n for n in os.listdir(paths.state("backups")) if rx.match(n) and os.path.isdir(os.path.join(paths.state("backups"), n))), reverse=True)
    gone = []
    for n in names[keep:]:
        try:
            shutil.rmtree(os.path.join(paths.state("backups"), n))
            gone.append(n)
        except OSError:
            pass
    return gone


def run_once(db_path: str = None, now: float = None, log=None) -> dict:
    db_path = db_path or paths.DB_PATH
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, KST).strftime("%Y%m%d")
    os.makedirs(paths.state("backups"), exist_ok=True)
    try:
        os.chmod(paths.state("backups"), 0o700)
        for left in os.listdir(paths.state("backups")):
            if re.match(r"^ledger_\d{8}\.db\.tmp(?:-wal|-shm|-journal)?$", left):
                os.remove(os.path.join(paths.state("backups"), left))
    except OSError:
        pass
    st = _read_status()
    st.setdefault("created", int(now))
    st["last_try"] = int(now)
    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    free = shutil.disk_usage(paths.state("backups")).free
    st["free"] = int(free)
    if free < max(MIN_FREE, int(size * 1.2)):
        st.update(skip="disk", skip_at=int(now), need=int(max(MIN_FREE, size * 1.2)))
        _write_status(st)
        if log:
            log.warning("원장 정기 백업 건너뜀 — 디스크 여유 %.1fGB < 필요 %.1fGB(1시간 뒤 재시도)",
                        free / 1024 ** 3, max(MIN_FREE, size * 1.2) / 1024 ** 3)
        return st
    t0 = time.time()
    dst_path = os.path.join(paths.state("backups"), f"ledger_{day}.db")
    tmp = dst_path + ".tmp"
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        os.close(fd)
        src = dbm.connect(paths.sqlite_ro_uri(db_path), uri=True, timeout=60)
        dst = dbm.connect(tmp)
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
        jp = os.path.join(paths.state("backups"), f"prefs_{day}.json")
        fsio.atomic_write_json(jp, prefs, ensure_ascii=False, fsync=False, dir_fsync=False, makedirs=False)
        try:
            st["files"] = backup_files(day, os.path.dirname(db_path))
            st["files_err"] = None
        except Exception as e9:  # noqa: BLE001 [fallback]
            st["files_err"] = _err_text(e9)[:200]
        gone = _rotate(_DB_RX, keep_db()) + _rotate(_JS_RX, KEEP_JSON) + _rotate_dirs(_FD_RX, KEEP_FILES)
        st.update(last_ok=int(time.time()), last_date=day, last_path=dst_path, size=os.path.getsize(dst_path),
                  dur=round(time.time() - t0, 1), skip=None, err=None)
        _write_status(st)
        if log:
            log.info("원장 정기 백업 완료: %s (%.2fGB, %.0f초)%s", os.path.basename(dst_path), st["size"] / 1024 ** 3, st["dur"],
                     f" · 회전 삭제 {len(gone)}개" if gone else "")
    except Exception as e:  # noqa: BLE001 [boundary]
        for sfx in ("", "-wal", "-shm", "-journal"):
            try:
                if os.path.exists(tmp + sfx):
                    os.remove(tmp + sfx)
            except OSError:
                pass
        st.update(err=_err_text(e)[:200], skip=None)
        _write_status(st)
        if log:
            log.warning("원장 정기 백업 실패(1시간 뒤 재시도): %s", st["err"])
    return st


def _err_text(e) -> str:
    m = logs.safe_err(e)
    if re.search(r"[가-힣]", m):
        return m
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "디스크가 가득 찼어요 — state/backups 여유를 확보하세요"
    if isinstance(e, sqlite3.OperationalError) and "full" in m.lower():
        return "디스크가 가득 찼어요(sqlite) — state/backups 여유를 확보하세요"
    if isinstance(e, PermissionError):
        return f"권한이 없어요 — {m}"
    return f"{type(e).__name__}: {m}"


def tick(log=None, now: float = None, db_path: str = None) -> bool:
    global _thread, _perm_done, _last_check
    try:
        now = time.time() if now is None else now
        if now - _last_check < CHECK_EVERY_S:
            return False
        _last_check = now
        db_path = db_path or paths.DB_PATH
        if not _perm_done:
            _perm_done = True
            _secure_perms(db_path)
            if not os.path.exists(paths.state("backups", "backup_status.json")):
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
    except Exception as e:  # noqa: BLE001 [fallback]
        if log:
            log.warning("원장 정기 백업 점검 실패(다음 주기): %s", e)
        return False


STREAM_STATE = {
    "evm": (re.compile(r"^emitted_(?:evm|rpc)_[\w.-]+\.json$"),),
    "sol": (re.compile(r"^emitted_sol\.json$"),),
    "bsc": (re.compile(r"^emitted_bsc\.json$"),),
    "ex": (re.compile(r"^upbit_orders_state\.json$"), re.compile(r"^exf_state\.json$")),
}
try:
    import chain_registry as _reg9
    STREAM_STATE.update({c9: (re.compile("^" + re.escape(_reg9.SPECS[c9].emitted_file) + "$"),) for c9 in _reg9.CHAINS})
except Exception:   # noqa: BLE001 [optional]
    pass
NEW_LEDGER_OK = "ledger_new_ok.json"
NEW_LEDGER_OK_TTL = 3600


def _nonempty_json(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return os.path.exists(path)
    return bool(d)


def inbox_segments(inbox_dir: str, stream: str) -> list:
    d = os.path.join(inbox_dir, stream)
    try:
        return sorted(int(f.split(".")[0]) for f in os.listdir(d) if f.endswith(".jsonl") and f.split(".")[0].isdigit())
    except OSError:
        return []


def prior_ledger_evidence(state_dir: str = None, db_path: str = None) -> list:
    sd = state_dir or paths.STATE_DIR
    dbp = db_path or os.path.join(sd, "ledger.db")
    base = os.path.basename(dbp)
    out = []
    bdir = os.path.join(sd, "backups")
    try:
        bk = sorted(n for n in os.listdir(bdir) if _DB_RX.match(n) or _JS_RX.match(n) or n == "backup_status.json")
    except OSError:
        bk = []
    if bk:
        dbs = [n for n in bk if _DB_RX.match(n)]
        out.append(f"원장 백업 {len(dbs)}개(state/backups)" if dbs else "백업 기록(state/backups)")
    try:
        side = sorted(n for n in os.listdir(os.path.dirname(dbp) or ".") if n.startswith((base + ".", base + "-")))
    except OSError:
        side = []
    if side:
        out.append("이전 원장 보존본·부속 파일: " + ", ".join(side[:3]) + (" …" if len(side) > 3 else ""))
    if os.path.exists(os.path.join(sd, "backfill_done")):
        out.append("백필 완료 표식(state/backfill_done)")
    ib = os.path.join(sd, "inbox")
    try:
        names = os.listdir(sd)
    except OSError:
        names = []
    for stream, rxs in STREAM_STATE.items():
        segs = inbox_segments(ib, stream)
        if segs and segs[0] > 1:
            out.append(f"인박스 {stream} 앞부분(세그먼트 1~{segs[0] - 1})을 예전 원장이 이미 읽고 지움")
            continue
        if not segs:
            sent = [n for n in names if any(rx.match(n) for rx in rxs) and _nonempty_json(os.path.join(sd, n))]
            if sent:
                out.append(f"수집기 {stream} 가 보낸 기록({sent[0]}{' 외' if len(sent) > 1 else ''})은 있는데 인박스가 비어 있음")
    return out


def new_ledger_ok(state_dir: str = None, consume: bool = False, now: float = None) -> bool:
    p = os.path.join(state_dir or paths.STATE_DIR, NEW_LEDGER_OK)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        ok = isinstance(d, dict) and 0 <= (time.time() if now is None else now) - float(d.get("ts") or 0) <= NEW_LEDGER_OK_TTL
    except (OSError, ValueError, TypeError):
        return False
    if consume:
        try:
            os.remove(p)
        except OSError:
            pass
    return ok


CORRUPT_WHY = "원장 손상 — 백업에서 되돌리기 필요(python3 tools/ledger_restore.py list)"
DEEP_PRESTART_MAX = 512 * 1024 ** 2
_LIGHT_TABLES = ("meta", "postings", "raw_txs", "raw_ex", "inbox_offsets", "positions", "decisions", "wallets", "assets", "transfers", "tx_class")
_CORRUPT_MSG = ("malformed", "not a database", "corrupt", "disk image")


def corrupt_error(e) -> bool:
    m = str(e).lower()
    return isinstance(e, sqlite3.DatabaseError) and any(x in m for x in _CORRUPT_MSG)


def _ro_connect(path: str):
    last = None
    for imm in (False, True):
        c = None
        try:
            c = dbm.connect(paths.sqlite_ro_uri(path, immutable=imm), uri=True, timeout=10)
            c.execute("SELECT 1").fetchone()
            return c
        except sqlite3.OperationalError as e:
            last = e
            if c is not None:
                c.close()
    raise last


def ledger_check_light(path: str) -> tuple:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            hdr = f.read(100)
    except OSError as e:
        return True, f"검사 못 함: {logs.safe_err(e)[:120]}"
    if size < 512 or not hdr.startswith(b"SQLite format 3\x00"):
        return False, f"파일 머리가 SQLite 원장이 아님(크기 {size:,}바이트 — 덮어쓰기·잘림)"
    ps = int.from_bytes(hdr[16:18], "big")
    ps = 65536 if ps == 1 else ps
    if ps < 512 or ps > 65536 or ps & (ps - 1):
        return False, f"머리의 페이지 크기 칸 손상({ps})"
    if size % ps:
        return False, f"파일 크기({size:,})가 페이지 크기({ps}) 배수가 아님 — 잘림·덧붙음"
    try:
        c = _ro_connect(path)
    except sqlite3.Error as e:
        return (False, f"열기 실패: {logs.safe_err(e)[:160]}") if corrupt_error(e) else (True, f"검사 못 함: {logs.safe_err(e)[:120]}")
    try:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "meta" not in names:
            return False, "meta 표 없음(원장 형식 아님)"
        c.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        for t in _LIGHT_TABLES:
            if t in names:
                c.execute(f'SELECT max(rowid) FROM "{t}"').fetchone()
                c.execute(f'SELECT rowid FROM "{t}" LIMIT 1').fetchone()
        return True, ""
    except sqlite3.Error as e:
        return (False, f"읽기 실패: {logs.safe_err(e)[:160]}") if corrupt_error(e) else (True, f"검사 못 함: {logs.safe_err(e)[:120]}")
    finally:
        c.close()


def ledger_check_deep(path: str) -> tuple:
    try:
        c = _ro_connect(path)
    except sqlite3.Error as e:
        return (False, f"열기 실패: {logs.safe_err(e)[:160]}") if corrupt_error(e) else (True, f"검사 못 함: {logs.safe_err(e)[:120]}")
    try:
        rows = [r[0] for r in c.execute("PRAGMA quick_check").fetchall()]
    except sqlite3.Error as e:
        return (False, f"빠른 검사 실패: {logs.safe_err(e)[:160]}") if corrupt_error(e) else (True, f"검사 못 함: {logs.safe_err(e)[:120]}")
    finally:
        c.close()
    if rows == ["ok"]:
        return True, ""
    return False, "빠른 검사(quick_check) 실패: " + "; ".join(str(x) for x in rows[:3])[:200]


def fsync_file(path: str):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_dir(path: str) -> bool:
    try:
        fd = os.open(path or ".", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return False
    try:
        os.fsync(fd)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


class SwapRefused(RuntimeError):
    pass


def _settle_wal(live: str, timeout: float) -> str:
    wal = live + "-wal"
    if not ((os.path.exists(wal) and os.path.getsize(wal) > 0) or os.path.exists(live + "-journal")):
        return "ok"
    try:
        c = dbm.connect(live, timeout=timeout)
        try:
            c.execute("SELECT count(*) FROM sqlite_master").fetchone()
            busy, nlog, ncp = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            c.close()
    except sqlite3.DatabaseError as e:
        m = str(e).lower()
        if "locked" in m or "busy" in m:
            return "busy"
        if corrupt_error(e) or any(x in m for x in ("unable to open", "readonly", "read-only")):
            return "unreadable"
        return "failed"
    return "ok" if not busy or (nlog >= 0 and nlog == ncp) else "busy"


def swap_in(live: str, new: str, keep_as: str = None, log=None, wal_timeout: float = 30.0) -> dict:
    d = os.path.dirname(os.path.abspath(live))
    fsync_file(new)
    linked, kept = False, None
    if os.path.exists(live):
        if not keep_as:
            raise ValueError("live 가 있으면 keep_as 필요(옛 원장 보존 이름)")
        if os.path.lexists(keep_as):
            raise FileExistsError(keep_as)
        settled = _settle_wal(live, wal_timeout)
        if settled == "busy":
            raise SwapRefused("옛 원장 WAL 을 본문에 합치지 못함 — 다른 연결이 원장을 쥐고 있음(원장을 여는 유닛·프로세스를 멈추고 다시 · 원장 무변)")
        if settled == "failed":
            raise SwapRefused("옛 원장 WAL·저널을 본문에 합치다 실패(디스크 여유·입출력 오류 확인 뒤 다시 · 원장 무변)")
        try:
            os.link(live, keep_as)
            linked = True
        except OSError as e:
            if log:
                log.warning("원장 하드 링크 실패(%s) — 이름 바꾸기 두 번으로 교체", e)
        moved, renamed = [], False
        try:
            for sfx in ("-wal", "-shm", "-journal"):
                if os.path.exists(live + sfx):
                    os.replace(live + sfx, keep_as + sfx)
                    moved.append(sfx)
            if not linked:
                os.replace(live, keep_as)
                renamed = True
            os.replace(new, live)
        except BaseException:
            if renamed and not os.path.exists(live):
                os.replace(keep_as, live)
            for sfx in reversed(moved):
                if os.path.exists(keep_as + sfx) and not os.path.exists(live + sfx):
                    os.replace(keep_as + sfx, live + sfx)
            if linked and os.path.exists(keep_as) and os.path.exists(live) and os.path.samefile(keep_as, live):
                os.remove(keep_as)
            fsync_dir(d)
            raise
        kept = keep_as
        fsync_dir(d)
        return {"linked": linked, "kept": kept}
    os.replace(new, live)
    fsync_dir(d)
    return {"linked": linked, "kept": kept}


RELIEF_FAILED_AGE_S = 3 * 86400
RELIEF_STALE_S = 12 * 3600
_FAILED_RX = re.compile(r"^state\.failed_hotfixt_(\d{8}_\d{6})(?:_\d+)?$")
_SHADOW_RX = re.compile(r"^tj_shadow_extrebuild_(\d{8}_\d{6})$")


def dev_of(path: str) -> int:
    return os.stat(path).st_dev


def _ts_name(s: str):
    try:
        return time.mktime(time.strptime(s, "%Y%m%d_%H%M%S"))
    except (ValueError, OverflowError):
        return None


def _age(path: str, ts: str, now: float) -> float:
    t = _ts_name(ts) or 0.0
    try:
        t = max(t, os.lstat(path).st_mtime)
    except OSError:
        pass
    return now - t


def _gain(paths: list) -> int:
    seen = {}
    for p in paths:
        if not os.path.lexists(p):
            continue
        if os.path.isdir(p) and not os.path.islink(p):
            walk = ((dp, fns) for dp, _dn, fns in os.walk(p))
            files = (os.path.join(dp, fn) for dp, fns in walk for fn in fns)
        else:
            files = (p,)
        for f in files:
            try:
                st = os.lstat(f)
            except OSError:
                continue
            k = (st.st_dev, st.st_ino)
            e = seen.setdefault(k, [st.st_nlink, 0, st.st_size if not os.path.islink(f) else 0])
            e[1] += 1
    return sum(sz for nl, n, sz in seen.values() if n >= nl)


RESTORE_TABLES = ("meta", "postings", "raw_txs", "raw_ex", "inbox_offsets")
_WAL_MAGIC = (0x377F0682, 0x377F0683)
_VERIFIED = {}
_VERIFIED_MAX = 256


def _wal_head(wal: str, ps: int) -> str:
    with open(wal, "rb") as f:
        h = f.read(32)
    if len(h) < 32:
        return "WAL 머리 잘림"
    magic = int.from_bytes(h[:4], "big")
    if magic not in _WAL_MAGIC:
        return "WAL 머리 손상(매직)"
    if int.from_bytes(h[8:12], "big") != ps:
        return f"WAL 페이지 크기 {int.from_bytes(h[8:12], 'big')} ≠ 원장 {ps}"
    bo = "big" if magic & 1 else "little"
    s0 = s1 = 0
    for i in range(0, 24, 8):
        s0 = (s0 + int.from_bytes(h[i:i + 4], bo) + s1) & 0xFFFFFFFF
        s1 = (s1 + int.from_bytes(h[i + 4:i + 8], bo) + s0) & 0xFFFFFFFF
    if (s0, s1) != (int.from_bytes(h[24:28], "big"), int.from_bytes(h[28:32], "big")):
        return "WAL 머리 체크섬 불일치"
    return ""


def _restore_state(path: str, size: int, deep: bool) -> tuple:
    try:
        with open(path, "rb") as f:
            hdr = f.read(100)
    except OSError as e:
        return "unknown", f"검사 못 함: {logs.safe_err(e)[:120]}"
    if size < 512 or not hdr.startswith(b"SQLite format 3\x00"):
        return "invalid", f"파일 머리가 SQLite 원장이 아님(크기 {size:,}바이트 — 덮어쓰기·잘림)"
    ps = int.from_bytes(hdr[16:18], "big")
    ps = 65536 if ps == 1 else ps
    if ps < 512 or ps > 65536 or ps & (ps - 1):
        return "invalid", f"머리의 페이지 크기 칸 손상({ps})"
    if size % ps:
        return "invalid", f"파일 크기({size:,})가 페이지 크기({ps}) 배수가 아님 — 잘림·덧붙음"
    wal = path + "-wal"
    use_wal = 2 in (hdr[18], hdr[19]) and os.path.isfile(wal) and os.path.getsize(wal) > 0
    if use_wal:
        try:
            w9 = _wal_head(wal, ps)
        except OSError as e:
            return "unknown", f"WAL 검사 못 함: {logs.safe_err(e)[:120]}"
        if w9:
            return "invalid", w9
    else:
        n9 = int.from_bytes(hdr[28:32], "big")
        if n9 and hdr[24:28] == hdr[92:96] and n9 * ps > size:
            return "invalid", f"파일이 머리의 페이지 수보다 짧음({size:,} < {n9 * ps:,}바이트 — 잘림)"
    has_journal = os.path.exists(path + "-journal")
    try:
        c = dbm.connect(paths.sqlite_ro_uri(path, immutable=not (use_wal or has_journal)), uri=True, timeout=10)
    except sqlite3.Error as e:
        return ("invalid" if corrupt_error(e) else "unknown"), f"열기 실패: {logs.safe_err(e)[:160]}"
    try:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        miss = [t for t in RESTORE_TABLES if t not in names]
        if miss:
            return "invalid", "표 없음: " + ", ".join(miss)
        meta = dict(c.execute("SELECT k, v FROM meta WHERE k IN ('schema_version', 'rebuild_incomplete', 'data_rev')").fetchall())
        sv = meta.get("schema_version")
        if sv is None or str(sv) != str(dbm.SCHEMA_VERSION):
            return "invalid", f"원장 세대 {sv} ≠ 코드 {dbm.SCHEMA_VERSION}(이 코드로 되돌릴 수 없음)"
        if meta.get("rebuild_incomplete"):
            return "invalid", "재파생 미완 표식(rebuild_incomplete)"
        try:
            if int(str(meta.get("data_rev") or 0).strip()) > dbm.DATA_REV:
                return "invalid", f"데이터 개정 {meta.get('data_rev')} > 코드 {dbm.DATA_REV}"
        except ValueError:
            return "invalid", "데이터 개정 번호(meta data_rev) 해석 불가"
        for t in _LIGHT_TABLES:
            if t in names:
                c.execute(f'SELECT max(rowid) FROM "{t}"').fetchone()
                c.execute(f'SELECT rowid FROM "{t}" LIMIT 1').fetchone()
        if deep:
            rows = [r[0] for r in c.execute("PRAGMA quick_check").fetchall()]
            if rows != ["ok"]:
                return "invalid", "빠른 검사(quick_check) 실패: " + "; ".join(str(x) for x in rows[:3])[:200]
        return "valid", ""
    except sqlite3.Error as e:
        return ("invalid" if corrupt_error(e) else "unknown"), f"읽기 실패: {logs.safe_err(e)[:160]}"
    finally:
        c.close()


def restore_state(path: str, deep: bool = True) -> tuple:
    try:
        st = os.stat(path)
        wst = os.stat(path + "-wal") if os.path.exists(path + "-wal") else None
    except FileNotFoundError:
        return "invalid", "파일 없음"
    except OSError as e:
        return "unknown", f"검사 못 함: {logs.safe_err(e)[:120]}"
    key = (os.path.abspath(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns,
           (wst.st_size, wst.st_mtime_ns) if wst else None)
    if deep and key in _VERIFIED:
        return _VERIFIED[key]
    try:
        res = _restore_state(path, st.st_size, deep)
    except Exception as e:  # noqa: BLE001 [fallback]
        res = ("unknown", f"검사 못 함: {type(e).__name__}: {logs.safe_err(e)[:120]}")
    if deep and res[0] != "unknown":
        if len(_VERIFIED) >= _VERIFIED_MAX:
            _VERIFIED.clear()
        _VERIFIED[key] = res
    return res


def _verified_split(paths: list) -> tuple:
    if len(paths) < 2:
        return 0, {}
    held = {}
    for i in range(len(paths) - 1, -1, -1):
        st9, why9 = restore_state(paths[i], deep=True)
        if st9 == "valid":
            return i, {k: w + " — 안 지움(더 오래된 검증된 사본을 보호본으로)" for k, w in held.items()}
        held[i] = ("복구 검사 실패: " if st9 == "invalid" else "복구 검사 못 함: ") + why9
    return 0, {k: w + " — 검증된 사본이 하나도 없어 이 계열은 안 지움" for k, w in held.items()}


def _off_short(path: str, devs) -> bool:
    if devs is None:
        return False
    try:
        return dev_of(path) not in devs
    except OSError:
        return False


OFF_SHORT_WHY = "다른 디스크(모자란 디스크가 아님 — 지워도 도움 안 됨)"


def relief_candidates(step: str, db_path: str, home: str = None, now: float = None, devs=None) -> list:
    now = time.time() if now is None else now
    sd = os.path.dirname(os.path.abspath(db_path))
    base = os.path.basename(db_path)
    out = []
    try:
        names = os.listdir(sd)
    except OSError:
        names = []
    if step == "leftover":
        rx = re.compile(re.escape(base) + r"\.extnew_(\d{8}_\d{6})$")
        for n in sorted(names):
            m = rx.match(n)
            p = os.path.join(sd, n)
            if m and os.path.isfile(p) and not os.path.islink(p) and _age(p, m.group(1), now) >= RELIEF_STALE_S:
                out.append({"name": n, "kind": "extnew", "paths": [p + s for s in ("", "-wal", "-shm", "-journal")], "dir": False})
        if home and os.path.isdir(home):
            for n in sorted(os.listdir(home)):
                m = _SHADOW_RX.match(n)
                p = os.path.join(home, n)
                if m and os.path.isdir(p) and not os.path.islink(p) and _age(p, m.group(1), now) >= RELIEF_STALE_S:
                    out.append({"name": n, "kind": "shadow", "paths": [p], "dir": True, "parent": home, "rx": _SHADOW_RX})
    elif step == "pre_extrebuild":
        rx = re.compile(re.escape(base) + r"\.pre_extrebuild_(\d{8}_\d{6})$")
        pres = sorted(n for n in names if rx.match(n) and os.path.isfile(os.path.join(sd, n)))
        if len(pres) > 1 and _off_short(sd, devs):
            out += [{"name": n, "kind": "pre_extrebuild", "skip": OFF_SHORT_WHY} for n in pres[:-1]]
            pres = []
        k9, held9 = _verified_split([os.path.join(sd, n) for n in pres])
        for n in pres[:k9]:
            p = os.path.join(sd, n)
            out.append({"name": n, "kind": "pre_extrebuild", "paths": [p + s for s in ("", "-wal", "-shm", "-journal")], "dir": False})
        out += [{"name": pres[i9], "kind": "pre_extrebuild", "skip": w9} for i9, w9 in sorted(held9.items())]
    elif step == "daily":
        bd = os.path.join(sd, "backups")
        try:
            days = sorted(n for n in os.listdir(bd) if _DB_RX.match(n) and os.path.isfile(os.path.join(bd, n)))
        except OSError:
            days = []
        if len(days) > 1 and _off_short(bd, devs):
            out += [{"name": "backups/" + n, "kind": "daily", "skip": OFF_SHORT_WHY} for n in days[:-1]]
            days = []
        k9, held9 = _verified_split([os.path.join(bd, n) for n in days])
        for n in days[:k9]:
            out.append({"name": "backups/" + n, "kind": "daily", "paths": [os.path.join(bd, n)], "dir": False})
        out += [{"name": "backups/" + days[i9], "kind": "daily", "skip": w9} for i9, w9 in sorted(held9.items())]
    elif step == "failed":
        bdir = os.path.dirname(sd)
        try:
            fns = sorted(os.listdir(bdir))
        except OSError:
            fns = []
        for n in fns:
            m = _FAILED_RX.match(n)
            p = os.path.join(bdir, n)
            if not m or os.path.islink(p) or not os.path.isdir(p) or _age(p, m.group(1), now) < RELIEF_FAILED_AGE_S:
                continue
            if os.path.isdir(os.path.join(p, "state")) and not os.path.isfile(os.path.join(p, "LEDGER_SWAPPED")):
                out.append({"name": n, "kind": "failed", "skip": "롤백 교체 미완(state 있고 LEDGER_SWAPPED 없음) — 남김"})
                continue
            out.append({"name": n, "kind": "failed", "paths": [p], "dir": True, "parent": bdir, "rx": _FAILED_RX})
    return out


def _remove(c: dict):
    if c.get("dir"):
        p = c["paths"][0]
        rp = os.path.realpath(p)
        if (os.path.islink(p) or os.path.dirname(rp) != os.path.realpath(c["parent"]) or not c["rx"].match(os.path.basename(rp))):
            raise OSError("안전 확인 실패(위치·이름·링크)")
        shutil.rmtree(rp)
        return
    for p in c["paths"]:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


RELIEF_STEPS = ("leftover", "pre_extrebuild", "daily", "failed")


def relieve(db_path: str, short, home: str = None, now: float = None, log=None, rounds: int = 2) -> dict:
    now = time.time() if now is None else now
    rec = {"at": int(now), "ok": False, "freed": 0, "removed": [], "skipped": []}
    skipped = {}
    try:
        need = short()
        for _r in range(max(1, rounds)):
            did = False
            for step in RELIEF_STEPS:
                if not need:
                    break
                cands = relief_candidates(step, db_path, home=home, now=now, devs=set(need))
                for c in cands:
                    if c.get("skip"):
                        skipped[c["name"]] = c["skip"]
                        continue
                    try:
                        dv = dev_of(c["paths"][0])
                    except OSError:
                        continue
                    if dv not in need:
                        skipped[c["name"]] = "다른 디스크(모자란 디스크가 아님 — 지워도 도움 안 됨)"
                        continue
                    g = _gain(c["paths"])
                    if g <= 0 or (not c.get("dir") and _gain(c["paths"][:1]) <= 0):
                        skipped[c["name"]] = "하드 링크(다른 곳과 같은 inode — 지워도 공간이 안 생김)"
                        continue
                    try:
                        _remove(c)
                    except OSError as e:
                        skipped[c["name"]] = "지우기 실패: " + logs.safe_err(e)[:120]
                        continue
                    skipped.pop(c["name"], None)
                    rec["removed"].append({"name": c["name"], "kind": c["kind"], "bytes": int(g)})
                    rec["freed"] += int(g)
                    did = True
                if cands:
                    need = short()
            if not need or not did:
                break
        rec["ok"] = not need
    except Exception as e:  # noqa: BLE001 [fallback]
        skipped["(자동 정리)"] = "오류: " + logs.safe_err(e)[:160]
    rec["skipped"] = [{"name": k, "why": v} for k, v in list(skipped.items())[:20]]
    if log and rec["removed"]:
        log.warning("재구축 자동 공간 확보: %d개 지움(≈%.1fGB) — %s%s", len(rec["removed"]), rec["freed"] / 1024 ** 3,
                    ", ".join(r["name"] for r in rec["removed"][:8]), " …" if len(rec["removed"]) > 8 else "")
    return rec

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
import common

BK_DIR = os.path.join(common.STATE_DIR, "backups")
OUT_DIR = os.path.join(BK_DIR, "offsite")
STATUS = os.path.join(BK_DIR, "offsite_status.json")
STAMP_RX = re.compile(r"^(tjoff_\d{8}_\d{4})\.(db\.gz|files\.tar\.gz|manifest\.json)$")
DEFAULTS = {"enabled": False, "mode": "push", "port": 22, "keep": 2, "keep_local": 1, "bwlimit_kbps": 4096, "every_h": 24, "warn_h": 36}
CHUNK = 8 << 20
RETRY_S = 3 * 3600
FRESH_MAX_AGE_S = 26 * 3600


def conf(cfg: dict = None) -> dict:
    if cfg is None:
        try:
            with open(common.CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    o = ((cfg or {}).get("backup") or {}).get("offsite") if isinstance((cfg or {}).get("backup"), dict) else None
    out = dict(DEFAULTS)
    if isinstance(o, dict):
        out.update({k: v for k, v in o.items() if v is not None})
    for k, lo, hi in (("port", 1, 65535), ("keep", 1, 30), ("keep_local", 0, 30), ("bwlimit_kbps", 0, 10 ** 7), ("every_h", 1, 24 * 30),
                      ("warn_h", 1, 24 * 60)):
        try:
            out[k] = min(hi, max(lo, int(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULTS[k]
    out["enabled"] = out.get("enabled") is True
    out["mode"] = "outbox" if out.get("mode") == "outbox" else "push"
    if out.get("key"):
        out["key"] = os.path.expanduser(str(out["key"]))
    return out


def problems(c: dict) -> list:
    p = []
    if c["mode"] == "push":
        for k in ("host", "user", "path"):
            if not str(c.get(k) or "").strip():
                p.append(f"backup.offsite.{k} 없음")
        if c.get("host") and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-:\[\]]*", str(c["host"])):
            p.append("host 형식")
        if c.get("user") and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._\-]*", str(c["user"])):
            p.append("user 형식")
        pth = str(c.get("path") or "")
        if pth and (not re.fullmatch(r"(?:/|~/)[A-Za-z0-9_./-]+", pth)
                    or any(part in (".", "..") for part in pth.rstrip("/").split("/")[1:])):
            p.append("path 는 /… 또는 ~/… (영문·숫자·_ . - / 만 · '..' 금지)")
        if c.get("key") and not os.path.isfile(c["key"]):
            p.append(f"키 파일 없음: {c['key']}")
    return p


def read_status() -> dict:
    try:
        with open(STATUS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(d: dict):
    os.makedirs(BK_DIR, exist_ok=True)
    common.atomic_write_json(STATUS, d)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def _latest_local_backup(now: float):
    try:
        names = sorted((n for n in os.listdir(BK_DIR) if re.match(r"^ledger_\d{8}\.db$", n)), reverse=True)
    except OSError:
        return None
    for n in names:
        p = os.path.join(BK_DIR, n)
        if now - os.path.getmtime(p) <= FRESH_MAX_AGE_S:
            return p
        break
    return None


def snapshot(dst: str, src: str = None):
    src = src or common.DB_PATH
    for sfx in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(dst + sfx):
            os.remove(dst + sfx)
    fd = os.open(dst, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    os.close(fd)
    s = sqlite3.connect(common.sqlite_ro_uri(src), uri=True, timeout=60)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE").fetchone()
    finally:
        d.close()
        s.close()


def ledger_facts(path: str, check: bool = True) -> dict:
    c = sqlite3.connect(common.sqlite_ro_uri(path, immutable=True), uri=True, timeout=30)
    try:
        ok = c.execute("PRAGMA quick_check").fetchone()[0] if check else "skipped"
        sv = c.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        t = [r[0] for r in c.execute("SELECT ingested_at FROM raw_txs ORDER BY rowid DESC LIMIT 200") if r[0]]
        t += [r[0] for r in c.execute("SELECT observed_at FROM raw_ex ORDER BY rowid DESC LIMIT 200") if r[0]]
    finally:
        c.close()
    return {"quick_check": ok, "schema_version": sv[0] if sv else None, "data_until": int(max(t)) if t else None}


def _gzip(src: str, dst: str) -> tuple:
    h_raw = hashlib.sha256()
    tmp = dst + ".part"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as raw_out, gzip.GzipFile(filename=os.path.basename(src), mode="wb", fileobj=raw_out, compresslevel=6, mtime=0) as gz, \
            open(src, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h_raw.update(b)
            gz.write(b)
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, dst)
    return h_raw.hexdigest(), _sha256(dst)


def _files_bundle(dst: str) -> dict:
    try:
        names = os.listdir(BK_DIR)
    except OSError:
        names = []
    fdirs = sorted((n for n in names if re.match(r"^files_\d{8}$", n) and os.path.isdir(os.path.join(BK_DIR, n))), reverse=True)
    prefs = sorted((n for n in names if re.match(r"^prefs_\d{8}\.json$", n)), reverse=True)
    inc = ([fdirs[0]] if fdirs else []) + ([prefs[0]] if prefs else [])
    if not inc:
        return {}
    tmp = dst + ".part"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)

    def _flt(ti):
        base = os.path.basename(ti.name)
        if base.startswith(".env") or base.endswith((".pem", ".key")):
            return None
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti
    with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz") as tf:
        for n in inc:
            tf.add(os.path.join(BK_DIR, n), arcname=n, filter=_flt)
    os.replace(tmp, dst)
    return {"name": os.path.basename(dst), "sha256": _sha256(dst), "size": os.path.getsize(dst), "includes": inc}


def build(now: float = None, check: bool = True, log=print) -> dict:
    now = time.time() if now is None else now
    os.makedirs(OUT_DIR, mode=0o700, exist_ok=True)
    os.chmod(OUT_DIR, 0o700)
    stamp = "tjoff_" + time.strftime("%Y%m%d_%H%M", time.gmtime(now + 9 * 3600))
    src = _latest_local_backup(now)
    tmp_db = None
    size = os.path.getsize(common.DB_PATH) if os.path.exists(common.DB_PATH) else 0
    free = shutil.disk_usage(BK_DIR).free
    need = int((size if src else size * 1.6) * 0.7) + (512 << 20)
    if free < need:
        raise RuntimeError(f"디스크 여유 부족(여유 {free / 1024 ** 3:.1f}GB < 필요 {need / 1024 ** 3:.1f}GB)")
    if not src:
        if not os.path.exists(common.DB_PATH):
            raise RuntimeError("원장 파일 없음")
        tmp_db = os.path.join(OUT_DIR, f"{stamp}.snap.db")
        log("오늘 정기 백업이 없어 원장 스냅숏을 새로 떠요")
        snapshot(tmp_db)
        src = tmp_db
    try:
        facts = ledger_facts(src, check=check)
        if check and facts["quick_check"] != "ok":
            raise RuntimeError(f"원장 스냅숏 검사 실패: {str(facts['quick_check'])[:120]}")
        dbgz = os.path.join(OUT_DIR, f"{stamp}.db.gz")
        h_raw, h_gz = _gzip(src, dbgz)
        files = _files_bundle(os.path.join(OUT_DIR, f"{stamp}.files.tar.gz"))
        man = {"v": 1, "stamp": stamp, "created": int(now), "source": os.path.basename(src) if src != tmp_db else "snapshot",
               "db": {"name": os.path.basename(dbgz), "sha256": h_gz, "size": os.path.getsize(dbgz), "raw_sha256": h_raw,
                      "raw_size": os.path.getsize(src), **facts},
               "files": files}
        common.atomic_write_json(os.path.join(OUT_DIR, f"{stamp}.manifest.json"), man)
        os.chmod(os.path.join(OUT_DIR, f"{stamp}.manifest.json"), 0o600)
    finally:
        if tmp_db and os.path.exists(tmp_db):
            os.remove(tmp_db)
    return man


def local_stamps() -> list:
    try:
        return sorted({m.group(1) for n in os.listdir(OUT_DIR) for m in [STAMP_RX.match(n)] if m and n.endswith(".manifest.json")})
    except OSError:
        return []


def prune_local(keep: int) -> list:
    st = local_stamps()
    gone = []
    for s in st[:max(0, len(st) - keep)]:
        for n in os.listdir(OUT_DIR):
            if n.startswith(s + "."):
                os.remove(os.path.join(OUT_DIR, n))
                gone.append(n)
    for n in os.listdir(OUT_DIR):
        if n.endswith((".part", ".snap.db")):
            os.remove(os.path.join(OUT_DIR, n))
    return gone


def ssh_cmd(c: dict) -> list:
    a = ["ssh", "-p", str(c["port"]), "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30",
         "-o", "StrictHostKeyChecking=accept-new"]
    if c.get("key"):
        a += ["-i", c["key"], "-o", "IdentitiesOnly=yes"]
    return a


def scp_cmd(c: dict) -> list:
    a = ["scp", "-q", "-P", str(c["port"]), "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30",
         "-o", "StrictHostKeyChecking=accept-new"]
    if c.get("key"):
        a += ["-i", c["key"], "-o", "IdentitiesOnly=yes"]
    return a


def transfer_tool(c: dict) -> tuple:
    if not shutil.which("ssh"):
        return None, "ssh 가 없어요(OpenSSH 클라이언트 설치)"
    if shutil.which("rsync"):
        return "rsync", "rsync(이어받기 · 속도 상한)"
    if shutil.which("scp"):
        return "scp", "scp(rsync 없음 — 끊기면 처음부터 · 속도 상한은 scp -l)"
    return None, "rsync·scp 가 둘 다 없어요(rsync 설치 권장)"


def remote(c: dict, script: str, timeout: float = 120) -> str:
    r = subprocess.run(ssh_cmd(c) + [f"{c['user']}@{c['host']}", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"원격 명령 실패 rc={r.returncode}: {(r.stderr or r.stdout).strip()[-200:]}")
    return r.stdout


def _rpath(c: dict) -> str:
    p = str(c["path"]).rstrip("/")
    return p if not p.startswith("~") else "$HOME" + p[1:]


def _q(p: str) -> str:
    return '"$HOME"' + shlex.quote(p[5:]) if p.startswith("$HOME") else shlex.quote(p)


def rsync_protect_args(version_text: str = None) -> list:
    if version_text is None:
        try:
            version_text = subprocess.run(["rsync", "--version"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    m = re.search(r"rsync\s+version\s+v?(\d+)\.(\d+)\.(\d+)", version_text or "")
    if not m:
        return []
    v = tuple(int(x) for x in m.groups())
    return ["-s"] if (3, 0, 0) <= v < (3, 2, 4) else []


def send(c: dict, files: list, timeout: float = 6 * 3600):
    inc = _rpath(c) + "/.incoming/"
    dest = f"{c['user']}@{c['host']}:" + (inc.replace("$HOME/", "") if inc.startswith("$HOME/") else inc)
    if shutil.which("rsync"):
        a = ["rsync", "-t", "--partial", "--chmod=F600"] + rsync_protect_args() + ["-e", " ".join(shlex.quote(x) for x in ssh_cmd(c))]
        if c["bwlimit_kbps"]:
            a.append(f"--bwlimit={int(c['bwlimit_kbps'])}")
    else:
        a = scp_cmd(c) + (["-l", str(int(c["bwlimit_kbps"]) * 8)] if c["bwlimit_kbps"] else [])
    r = subprocess.run(a + files + [dest], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"보내기 실패 rc={r.returncode}: {(r.stderr or r.stdout).strip()[-200:]}")


TMP_RX = re.compile(r"^\.(tjoff_\d{8}_\d{4})\.(db\.gz|files\.tar\.gz|manifest\.json)\.[A-Za-z0-9]{6}$")


def stale_incoming(names, cur_stamp: str) -> list:
    out = []
    for n in names:
        n = str(n).strip()
        m = STAMP_RX.match(n) or TMP_RX.match(n)
        if m and m.group(1) != cur_stamp:
            out.append(n)
    return sorted(out)


def push(c: dict, man: dict, log=print) -> dict:
    rp = _rpath(c)
    remote(c, f"mkdir -p {_q(rp + '/.incoming')} && chmod 700 {_q(rp)} {_q(rp + '/.incoming')}")
    old9 = stale_incoming(remote(c, "ls -1A " + _q(rp + "/.incoming") + " 2>/dev/null || true").split("\n"), man["stamp"])
    if old9:
        remote(c, "rm -f -- " + " ".join(_q(rp + "/.incoming/" + n) for n in old9))
    names = [man["db"]["name"]] + ([man["files"]["name"]] if man.get("files") else [])
    t0 = time.time()
    send(c, [os.path.join(OUT_DIR, n) for n in names])
    want = {man["db"]["name"]: man["db"]["sha256"]}
    if man.get("files"):
        want[man["files"]["name"]] = man["files"]["sha256"]
    out = remote(c, "cd " + _q(rp + "/.incoming") + " && sha256sum -- " + " ".join(shlex.quote(n) for n in names), timeout=3600)
    got = {ln.split(None, 1)[1].strip().lstrip("*"): ln.split(None, 1)[0] for ln in out.splitlines() if len(ln.split(None, 1)) == 2}
    bad = [n for n in names if got.get(n) != want[n]]
    if bad:
        remote(c, "rm -f -- " + " ".join(_q(rp + "/.incoming/" + n) for n in bad))
        raise RuntimeError("원격 sha256 불일치(받은 파일 지움): " + ", ".join(bad))
    send(c, [os.path.join(OUT_DIR, f"{man['stamp']}.manifest.json")])
    mv = " && ".join(f"mv -f -- {_q(rp + '/.incoming/' + n)} {_q(rp + '/' + n)}" for n in names + [f"{man['stamp']}.manifest.json"])
    remote(c, mv)
    gone = prune_remote(c)
    return {"dur": round(time.time() - t0, 1), "remote_pruned": gone}


def remote_stamps(c: dict) -> list:
    out = remote(c, "ls -1 " + _q(_rpath(c)) + " 2>/dev/null || true")
    return sorted({m.group(1) for n in out.split() for m in [STAMP_RX.match(n)] if m and n.endswith(".manifest.json")})


def prune_remote(c: dict) -> list:
    st = remote_stamps(c)
    old = st[:max(0, len(st) - c["keep"])]
    if not old:
        return []
    rp = _rpath(c)
    files = [f"{s}{sfx}" for s in old for sfx in (".manifest.json", ".db.gz", ".files.tar.gz")]
    remote(c, "rm -f -- " + " ".join(_q(rp + "/" + n) for n in files))
    return old


def recv(c: dict, name: str, dst: str, timeout: float = 6 * 3600):
    rp = _rpath(c)
    src = f"{c['user']}@{c['host']}:" + ((rp + "/").replace("$HOME/", "") if rp.startswith("$HOME/") else rp + "/") + name
    a = ["rsync", "-t", "--partial"] + rsync_protect_args() + ["-e", " ".join(shlex.quote(x) for x in ssh_cmd(c))] if shutil.which("rsync") else \
        scp_cmd(c)
    r = subprocess.run(a + [src, dst], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"받기 실패 {name}: {(r.stderr or r.stdout).strip()[-200:]}")


def fetch(c: dict, stamp: str = None, log=print) -> str:
    st = remote_stamps(c)
    if not st:
        raise RuntimeError("원격에 묶음이 없어요")
    stamp = stamp or st[-1]
    if stamp not in st:
        raise RuntimeError(f"원격에 없는 묶음: {stamp} (있는 것: {', '.join(st)})")
    d = os.path.join(BK_DIR, "offsite_fetch", stamp)
    os.makedirs(d, mode=0o700, exist_ok=True)
    names = [f"{stamp}.manifest.json", f"{stamp}.db.gz", f"{stamp}.files.tar.gz"]
    for n in names:
        try:
            recv(c, n, os.path.join(d, n))
        except RuntimeError:
            if n != names[-1]:
                raise
    with open(os.path.join(d, names[0]), encoding="utf-8") as f:
        man = json.load(f)
    if _sha256(os.path.join(d, names[1])) != man["db"]["sha256"]:
        raise RuntimeError("받은 원장 압축본 sha256 불일치")
    out = os.path.join(d, f"ledger_{stamp[6:]}.db")
    h = hashlib.sha256()
    fd = os.open(out + ".part", os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with gzip.open(os.path.join(d, names[1]), "rb") as g, os.fdopen(fd, "wb") as f:
        for b in iter(lambda: g.read(CHUNK), b""):
            h.update(b)
            f.write(b)
    if h.hexdigest() != man["db"]["raw_sha256"]:
        raise RuntimeError("풀린 원장 sha256 불일치")
    os.replace(out + ".part", out)
    return out


def err_text(e) -> str:
    m = common.safe_err(e)
    if re.search(r"[가-힣]", m):
        return m
    if isinstance(e, subprocess.TimeoutExpired):
        return "시간 초과(보내기·원격 명령이 끝나지 않음) — 연결·속도 상한(bwlimit_kbps)을 확인하세요"
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "디스크가 가득 찼어요 — 이 컴퓨터 state/backups 여유를 확보하세요"
    if isinstance(e, PermissionError):
        return f"권한이 없어요 — {m}"
    return f"{type(e).__name__}: {m}"


def due(c: dict, st: dict, now: float) -> bool:
    return now - float(st.get("last_built") or st.get("last_ok") or 0) >= c["every_h"] * 3600 - 1800


def _lock(blocking: bool):
    os.makedirs(BK_DIR, exist_ok=True)
    f = open(os.path.join(BK_DIR, ".offsite.lock"), "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except OSError:
        f.close()
        return None
    return f


def confirm(stamp: str, sha256: str, log=print) -> int:
    if not re.fullmatch(r"tjoff_\d{8}_\d{4}", str(stamp or "")) or not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "").lower()):
        log("형식: confirm tjoff_YYYYMMDD_HHMM <sha256 64자>")
        return 2
    try:
        with open(os.path.join(OUT_DIR, f"{stamp}.manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        log(f"이 컴퓨터에 없는 묶음이에요: {stamp}(이미 회전됐으면 더 새 묶음으로)")
        return 1
    if str((man.get("db") or {}).get("sha256") or "") != sha256.lower():
        log("sha256 이 다릅니다 — 받은 파일이 깨졌을 수 있어요(다시 가져간 뒤 다시)")
        return 1
    lk = _lock(True)
    try:
        st = read_status()
        cr9 = int(man.get("created") or 0)
        if cr9 > int(st.get("confirmed_created") or 0):
            st.update(last_ok=cr9, confirmed_stamp=stamp, confirmed_created=cr9, err=None,
                      size=(man.get("db") or {}).get("size"), dest="outbox(받는 쪽 확인)")
            write_status(st)
    finally:
        if lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
            lk.close()
    log(f"확인됨: {stamp}")
    return 0


def run(force: bool = False, check: bool = True, cfg: dict = None, now: float = None, log=print) -> int:
    c = conf(cfg)
    now = time.time() if now is None else now
    if not c["enabled"]:
        log("서버 밖 백업 꺼짐(config backup.offsite.enabled) — 할 일 없음")
        return 0
    pr = problems(c)
    st = read_status()
    if pr:
        st.update(last_try=int(now), err="설정: " + " · ".join(pr), mode=c["mode"])
        write_status(st)
        log("설정 문제: " + " · ".join(pr))
        return 2
    if not force and not due(c, st, now):
        return 0
    if not force and st.get("err_at") and now - float(st["err_at"]) < RETRY_S:
        return 0
    lockf = _lock(False)
    if lockf is None:
        log("다른 서버 밖 백업이 도는 중 — 이번엔 건너뜀")
        return 0
    st = read_status()
    try:
        try:
            os.nice(10)
        except OSError:
            pass
        st.update(last_try=int(now), mode=c["mode"], running=True)
        st.setdefault("first_try", int(now))
        write_status(st)
        t0 = time.time()
        try:
            man = build(now=now, check=check, log=log)
            prune_local(max(1, c["keep_local"]))
            res = push(c, man, log=log) if c["mode"] == "push" else {}
            prune_local(max(c["keep_local"], 1 if c["mode"] == "outbox" else c["keep_local"]))
            t_end9 = int(now + (time.time() - t0))
            st.update(last_built=t_end9, last_stamp=man["stamp"], raw_size=man["db"]["raw_size"],
                      data_until=man["db"].get("data_until"), dur=round(time.time() - t0, 1), err=None, running=False,
                      remote_pruned=res.get("remote_pruned"))
            if c["mode"] == "push":
                st.update(last_ok=t_end9, size=man["db"]["size"], dest=f"{c['host']}:{c['path']}")
            else:
                st.update(dest="outbox(받는 쪽 확인 대기)")
            write_status(st)
            log(("서버 밖 백업 완료" if c["mode"] == "push" else "서버 밖 백업 묶음 만듦(받는 쪽 confirm 대기)")
                + f": {man['stamp']} ({man['db']['size'] / 1024 ** 3:.2f}GB 압축 · {st['dur']:.0f}초)")
            return 0
        except Exception as e:
            st.update(err=err_text(e)[:240], err_at=int(now + (time.time() - t0)), running=False)
            write_status(st)
            log("서버 밖 백업 실패: " + st["err"])
            for n in os.listdir(OUT_DIR) if os.path.isdir(OUT_DIR) else []:
                if n.endswith((".part", ".snap.db")):
                    os.remove(os.path.join(OUT_DIR, n))
            return 1
    finally:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
        lockf.close()


EPILOG = """설정(config.json — 값은 예시):
  "backup": {"offsite": {"enabled": true, "mode": "push", "host": "backup.example.net", "user": "backup", "port": 22,
                         "key": "~/.ssh/tj_offsite", "path": "/srv/tj_offsite", "keep": 2, "keep_local": 1,
                         "bwlimit_kbps": 4096, "every_h": 24, "warn_h": 36}}
  mode push   = 이 컴퓨터가 ssh(rsync · 없으면 scp)로 보냄 — 받는 쪽 authorized_keys 에 이 컴퓨터 공개 키
  mode outbox = 묶음만 state/backups/offsite/ 에 만들고 받는 쪽이 가져감(이 컴퓨터에서 밖으로 ssh 를 못 나갈 때).
                가져간 뒤 받는 쪽이 sha256 을 알려 줘야 '성공'(상태 패널) — 받는 쪽 크론 예:
                rsync -a --partial -e "ssh -i ~/.ssh/<키>" <사용자>@<이 컴퓨터>:<설치 폴더>/state/backups/offsite/ /srv/tj_offsite/ &&
                m=$(ls /srv/tj_offsite/tjoff_*.manifest.json | tail -1) && s=$(basename "$m" .manifest.json) &&
                h=$(sha256sum "/srv/tj_offsite/$s.db.gz" | cut -d' ' -f1) &&
                ssh -i ~/.ssh/<키> <사용자>@<이 컴퓨터> "cd <설치 폴더> && python3 tools/offsite_backup.py confirm $s $h"
크론(매시 — 하루 1번만 보냄 · 실패 뒤 3시간 쉼):  17 * * * * cd <설치 폴더> && python3 tools/offsite_backup.py run
묶음 = 원장 압축본(.db.gz) · 원장 밖 사본(.files.tar.gz — .env 제외) · manifest(sha256) — 받는 쪽 sha256 이 같을 때만 제자리로.
되돌리기 = fetch → python3 tools/ledger_restore.py restore <받은 경로>.
보안(NC7 ⑤): 묶음은 압축만 하고 ★암호화하지 않아요★ — 받는 컴퓨터에 접근할 수 있는 사람은 원장(거래·주소·금액)을 읽을 수 있으니 믿는 컴퓨터만.
  처음 접속 때 원격 호스트 키를 묻지 않고 받아들여요(StrictHostKeyChecking=accept-new — 그 뒤 키가 바뀌면 거부). 처음부터 확인하려면
  먼저 ssh -p <포트> -i <키> <사용자>@<호스트> 로 한 번 접속해 지문을 원격 관리자에게 받은 값과 맞춰 known_hosts 에 넣으세요.
  test = ssh 연결 · 원격 폴더·여유 · 보낼 도구(rsync → 없으면 scp)와 원격 rsync 까지 확인."""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="서버 밖 둘째 백업", epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--force", action="store_true", help="간격과 무관하게 지금")
    r.add_argument("--no-check", action="store_true", help="압축 전 quick_check 생략")
    sub.add_parser("status")
    sub.add_parser("test")
    sub.add_parser("list-remote")
    f = sub.add_parser("fetch")
    f.add_argument("stamp", nargs="?")
    cf = sub.add_parser("confirm", help="outbox: 받는 쪽이 가져간 묶음 확인(sha256)")
    cf.add_argument("stamp")
    cf.add_argument("sha256")
    a = ap.parse_args(argv)
    c = conf()
    if a.cmd == "run":
        return run(force=a.force, check=not a.no_check)
    if a.cmd == "confirm":
        return confirm(a.stamp, a.sha256)
    if a.cmd == "status":
        st = read_status()
        print(json.dumps({"config": {k: v for k, v in c.items() if k != "key"}, "status": st}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("test", "list-remote", "fetch"):
        pr = problems(c)
        if c["mode"] != "push" or pr:
            print("원격 설정이 없거나 outbox 모드예요: " + " · ".join(pr or ["mode=outbox"]))
            return 2
        if a.cmd == "test":
            tool9, why9 = transfer_tool(c)
            if tool9 is None:
                print("보낼 도구 없음: " + why9)
                return 1
            try:
                out = remote(c, f"mkdir -p {_q(_rpath(c))} && df -Pk {_q(_rpath(c))} | tail -1 && command -v sha256sum"
                                " && (command -v rsync >/dev/null && echo TJ_RSYNC_OK || echo TJ_RSYNC_NO)")
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                print("연결 실패: " + common.safe_err(e)[:300])
                return 1
            lines9 = [x for x in out.strip().splitlines() if x.strip()]
            if tool9 == "rsync" and "TJ_RSYNC_OK" not in lines9:
                print("원격에 rsync 가 없어요 — 이 컴퓨터는 rsync 로 보내므로 실패해요(원격에 rsync 설치)")
                return 1
            print("연결 정상 · 보내기: " + why9 + " · 원격 여유: " + (lines9[0] if lines9 else "?"))
            return 0
        if a.cmd == "list-remote":
            for s in remote_stamps(c):
                print(s)
            return 0
        p = fetch(c, a.stamp)
        print(f"받음: {p}\n되돌리기(미리보기): python3 tools/ledger_restore.py restore {p}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

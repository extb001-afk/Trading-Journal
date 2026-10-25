#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
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
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DEPLOY_LOCK = os.path.join(ROOT, ".deploy.lock")
EX_TEMPFAIL = 75
_BARRIER = []


def deploy_barrier(cmd, wait_s=None, log=print):
    if not cmd:
        return None
    try:
        wait_s = float(os.environ.get("TJ_DEPLOY_BARRIER_WAIT") or 600) if wait_s is None else float(wait_s)
    except ValueError:
        wait_s = 600.0
    try:
        fd = os.open(DEPLOY_LOCK, os.O_RDONLY | os.O_CREAT, 0o600)
    except OSError as e:
        log("배포 장벽 잠금 파일을 못 엶(%s: %s) — 아무것도 안 함 · 다음에 다시(75)" % (DEPLOY_LOCK, e.strerror))
        return EX_TEMPFAIL
    end = time.time() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            _BARRIER.append(fd)
            return None
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                os.close(fd)
                log("배포 장벽 잠금 실패(%s) — 아무것도 안 함 · 다음에 다시(75)" % e.strerror)
                return EX_TEMPFAIL
        if cmd == "run":
            os.close(fd)
            log("배포 중(트리 뿌리 .deploy.lock 배타 잠금) — 이번 서버 밖 백업은 건너뜀(다음 정시에 다시)")
            return 0
        if time.time() >= end:
            os.close(fd)
            log("배포가 %d초 안에 안 끝남(.deploy.lock) — 아무것도 안 함 · 다음에 다시(75)" % wait_s)
            return EX_TEMPFAIL
        time.sleep(1)


def _cmd_of(argv):
    if any(a in ("-h", "--help") for a in argv):
        return None
    cmd = next((a for a in argv if not a.startswith("-")), None)
    return cmd if cmd in ("run", "status", "test", "list-remote", "fetch", "confirm", "open", "auth-key") else None


if __name__ == "__main__":
    _rc9 = deploy_barrier(_cmd_of(sys.argv[1:]))
    if _rc9 is not None:
        sys.exit(_rc9)
sys.path[:0] = [os.path.join(ROOT, "src"), HERE]
import fsio, logs, offsite_seal as seal, paths, statefile  # noqa: E402
import backup_complete as bc  # noqa: E402
import ledger_backup as lb  # noqa: E402

BK_DIR = os.path.join(paths.STATE_DIR, "backups")
OUT_DIR = os.path.join(BK_DIR, "offsite")
STATUS = os.path.join(BK_DIR, "offsite_status.json")
AUTH_KEY, KNOWN_HOSTS = os.path.join(BK_DIR, "offsite_auth.key"), os.path.join(BK_DIR, "known_hosts_offsite")
STAMP_RX = re.compile(r"^(tjoff_\d{8}_\d{4})\.(db\.gz|files\.tar\.gz|manifest\.json)$")
DEFAULTS = {"enabled": False, "mode": "push", "port": 22, "keep": 2, "keep_local": 1, "bwlimit_kbps": 4096, "every_h": 24, "warn_h": 36}
CHUNK = 8 << 20
RETRY_S = 3 * 3600
FRESH_MAX_AGE_S = 26 * 3600


def conf(cfg: dict = None) -> dict:
    if cfg is None:
        try:
            with open(paths.CONFIG_PATH, encoding="utf-8") as f:
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
    out["host_key_fpr"] = seal.parse_fprs(out.get("host_key_fpr"))
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
        if any(not seal.FPR_RX.fullmatch(x) for x in c.get("host_key_fpr") or []):
            p.append("host_key_fpr 형식(SHA256:… · 여럿이면 쉼표 — ssh-keygen -lf <호스트 공개 키>)")
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
    statefile.atomic_write_json(STATUS, d)


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
    src = src or paths.DB_PATH
    for sfx in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(dst + sfx):
            os.remove(dst + sfx)
    fd = os.open(dst, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    os.close(fd)
    s = sqlite3.connect(paths.sqlite_ro_uri(src), uri=True, timeout=60)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE").fetchone()
    finally:
        d.close()
        s.close()


def ledger_facts(path: str, check: bool = True) -> dict:
    c = sqlite3.connect(paths.sqlite_ro_uri(path, immutable=True), uri=True, timeout=30)
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
    complete = {}
    if fdirs:
        s0 = bc.files_dir_state(os.path.join(BK_DIR, fdirs[0]))
        complete[fdirs[0]] = _brief_state(s0)
        lc = bc.last_complete_dir(BK_DIR, before=fdirs[0]) if isinstance(s0, dict) and s0.get("ok") is False else None
        if lc:
            inc.insert(1, lc)
            complete[lc] = _brief_state(bc.files_dir_state(os.path.join(BK_DIR, lc)))
            if f"prefs_{lc[6:]}.json" in prefs[1:]:
                inc.append(f"prefs_{lc[6:]}.json")
    tmp = dst + ".part"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)

    def _flt(ti):
        base = os.path.basename(ti.name)
        if base.startswith(".env") or base.endswith((".pem", ".key")):
            return None
        if ti.islnk():
            ti.type, ti.linkname = tarfile.REGTYPE, ""
            ti.size = os.lstat(os.path.join(BK_DIR, ti.name)).st_size
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti
    with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz") as tf:
        for n in inc:
            tf.add(os.path.join(BK_DIR, n), arcname=n, filter=_flt)
    os.replace(tmp, dst)
    return {"name": os.path.basename(dst), "sha256": _sha256(dst), "size": os.path.getsize(dst), "includes": inc, "complete": complete}


def _brief_state(s) -> dict:
    if not isinstance(s, dict):
        return {"ok": None}
    return {"ok": s.get("ok") is True, "n_expected": len(s.get("expected") or []), "n_copied": len(s.get("copied") or []),
            "failed": sorted(s.get("failed") or {})[:50], "n_failed": int(s.get("n_failed") or len(s.get("failed") or {}))}


def incomplete_lines(man: dict) -> list:
    out = []
    for d9, s9 in sorted(((man.get("files") or {}).get("complete") or {}).items(), reverse=True) if isinstance(man.get("files"), dict) else ():
        if isinstance(s9, dict) and s9.get("ok") is False:
            out.append(f"★원장 밖 사본 {d9} 불완전 — 빠진 것 {s9.get('n_failed') or len(s9.get('failed') or [])}개: "
                       + ", ".join(str(x) for x in (s9.get("failed") or [])[:8]) + "★")
    return out


def stamp_of(now: float) -> str:
    return "tjoff_" + time.strftime("%Y%m%d_%H%M", time.gmtime(now + 9 * 3600))


def build(now: float = None, check: bool = True, log=print) -> dict:
    now = time.time() if now is None else now
    os.makedirs(OUT_DIR, mode=0o700, exist_ok=True)
    os.chmod(OUT_DIR, 0o700)
    st0 = read_status()
    if not os.path.lexists(AUTH_KEY) and (st0.get("last_stamp") or st0.get("kid")):
        raise RuntimeError(f"열쇠 파일이 없음(state/backups/offsite_auth.key · 지난 묶음 {st0.get('last_stamp') or '?'} kid {st0.get('kid') or '?'})"
                           " — 새 열쇠를 만들지 않고 멈춤: 서버 밖에 둔 열쇠 사본을 제자리로 되돌리거나(kid 대조), 새 열쇠가 맞으면"
                           " python3 tools/offsite_backup.py auth-key 로 만든 뒤 --export 로 사본 보관")
    key = seal.load_key(AUTH_KEY, create=True)
    stamp = stamp_of(now)
    if os.path.lexists(os.path.join(OUT_DIR, f"{stamp}.manifest.json")):
        raise RuntimeError(f"같은 분 묶음이 이미 있음({stamp}) — 1분 뒤 다시")
    src = _latest_local_backup(now)
    tmp_db = None
    size = os.path.getsize(paths.DB_PATH) if os.path.exists(paths.DB_PATH) else 0
    free = shutil.disk_usage(BK_DIR).free
    need = int((size if src else size * 1.6) * 0.7) + (512 << 20)
    if free < need:
        raise RuntimeError(f"디스크 여유 부족(여유 {free / 1024 ** 3:.1f}GB < 필요 {need / 1024 ** 3:.1f}GB)")
    if not src:
        if not os.path.exists(paths.DB_PATH):
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
        for ln9 in incomplete_lines({"files": files}):
            log(ln9 + " — 묶음에 마지막 완전 사본도 같이 넣음(있으면)")
        man = {"v": 1, "stamp": stamp, "created": int(now), "source": os.path.basename(src) if src != tmp_db else "snapshot",
               "db": {"name": os.path.basename(dbgz), "sha256": h_gz, "size": os.path.getsize(dbgz), "raw_sha256": h_raw,
                      "raw_size": os.path.getsize(src), **facts},
               "files": files}
        statefile.atomic_write_json(os.path.join(OUT_DIR, f"{stamp}.manifest.json"), seal.seal(man, key))
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


ORPHAN_RX = re.compile(r"^(tjoff_\d{8}_\d{4})\.(?:db\.gz|files\.tar\.gz|snap\.db(?:-[A-Za-z]+)?)$")


def _prev_local_kid(cur: str) -> str:
    for s in reversed([x for x in local_stamps() if x < cur]):
        try:
            with open(os.path.join(OUT_DIR, s + ".manifest.json"), encoding="utf-8") as f:
                k = _kid_of(json.load(f))
        except (OSError, ValueError, RecursionError):
            continue
        if k:
            return k
    return ""


def prune_orphans(keep_stamp: str = None) -> list:
    try:
        names = os.listdir(OUT_DIR)
    except OSError:
        return []
    have, gone = set(local_stamps()), []
    for n in names:
        m = ORPHAN_RX.match(n)
        if m and m.group(1) not in have and m.group(1) != keep_stamp:
            os.remove(os.path.join(OUT_DIR, n))
            gone.append(n)
    return gone


def prune_local(keep: int, cur: str = None) -> list:
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
    return gone + prune_orphans(cur)


def ssh_cmd(c: dict, scp: bool = False) -> list:
    a = (["scp", "-q", "-P"] if scp else ["ssh", "-p"]) + [str(c["port"]), "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                                                          "-o", "ServerAliveInterval=30"] + seal.host_opts(c, KNOWN_HOSTS)
    if c.get("key"):
        a += ["-i", c["key"], "-o", "IdentitiesOnly=yes"]
    return a


def scp_cmd(c: dict) -> list:
    return ssh_cmd(c, scp=True)


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
    gone = prune_remote(c, _kid_of(man))
    return {"dur": round(time.time() - t0, 1), "remote_pruned": gone}


def remote_stamps(c: dict) -> list:
    out = remote(c, "ls -1 " + _q(_rpath(c)) + " 2>/dev/null || true")
    return sorted({m.group(1) for n in out.split() for m in [STAMP_RX.match(n)] if m and n.endswith(".manifest.json")})


def remote_manifests(c: dict, stamps: list) -> dict:
    res = {}
    for s in stamps:
        if not seal.STAMP_RX.fullmatch(str(s)):
            continue
        try:
            d = json.loads(remote(c, "cat -- " + _q(_rpath(c) + "/" + s + ".manifest.json") + " 2>/dev/null || true"))
        except (ValueError, RecursionError):
            d = None
        res[s] = d if isinstance(d, dict) else None
    return res


REGRESS_SIZE = 0.5
REGRESS_UNTIL_S = 86400


def _kid_of(man) -> str:
    a = man.get("auth") if isinstance(man, dict) else None
    k = a.get("kid") if isinstance(a, dict) else None
    return k if isinstance(k, str) and re.fullmatch(r"[0-9a-f]{8}", k) else ""


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if f == f and abs(f) != float("inf") else None


def regress_reasons(ref, man: dict) -> list:
    if not isinstance(ref, dict):
        return ["원격 마지막 manifest 를 못 읽음(비교 불가)"]
    try:
        return _regress(ref, man)
    except Exception as e:   # noqa: BLE001
        return [f"원격 마지막 manifest 비교 실패({type(e).__name__})"]


def _regress(ref: dict, man: dict) -> list:
    out = []
    rk, mk = _kid_of(ref), _kid_of(man)
    if "auth" in ref and not rk:
        out.append("원격 마지막 manifest 의 인증 칸 꼴 아님(비교 불가)")
    elif rk and mk and rk != mk:
        out.append(f"열쇠가 다름(원격 마지막 {ref.get('stamp')} kid {rk} · 이번 kid {mk})")
    rd = ref.get("db") if isinstance(ref.get("db"), dict) else {}
    md = man.get("db") or {}
    rs, ms = _num(rd.get("raw_size")), _num(md.get("raw_size"))
    if rs is None or rs <= 0:
        out.append("원격 마지막 manifest 에 원장 크기가 없음·꼴 아님(비교 불가)")
    elif ms is not None and ms < rs * REGRESS_SIZE:
        out.append(f"원장 크기 후퇴({rs / 1024 ** 2:.1f}MB → {ms / 1024 ** 2:.1f}MB)")
    ru, mu = _num(rd.get("data_until")), _num(md.get("data_until"))
    if ru is not None and ru > 0 and (mu is None or mu < ru - REGRESS_UNTIL_S):
        def fm(t):
            try:
                return time.strftime("%Y-%m-%d %H:%M KST", time.gmtime(t + 9 * 3600)) if t is not None else "없음"
            except (OverflowError, OSError, ValueError):
                return str(t)[:24]
        out.append(f"자료 시각 후퇴({fm(ru)} → {fm(mu)})")
    elif "data_until" not in rd or (rd.get("data_until") is not None and ru is None):
        out.append("원격 마지막 manifest 의 자료 시각이 없음·숫자가 아님(비교 불가)")
    return out


def check_remote(c: dict, man: dict, allow_regress: bool = False, log=print) -> None:
    rp = _rpath(c)
    try:
        out = remote(c, f"{{ mkdir -p {_q(rp)} && ls -1 {_q(rp)}; }} 2>/dev/null || echo __TJ_LS_FAIL__")
    except (UnicodeDecodeError, subprocess.TimeoutExpired) as e:
        raise RegressError("원격 목록을 못 읽음(글자 깨짐·시간 초과) — 보내기·회전 멈춤 · 원격 폴더 확인") from e
    if "__TJ_LS_FAIL__" in out.split():
        raise RegressError("원격 폴더 목록을 못 읽음(권한 등) — 보내기·회전 멈춤 · 원격 폴더 확인")
    st = sorted({m.group(1) for n in out.split() for m in [STAMP_RX.match(n)] if m and n.endswith(".manifest.json")})
    if man["stamp"] in st:
        raise RegressError(f"원격에 같은 이름 묶음이 이미 있음({man['stamp']}) — 이번 묶음 지우고 멈춤 · 1분 뒤 다시")
    if not st:
        return
    try:
        ref = remote_manifests(c, [st[-1]]).get(st[-1])
    except Exception:   # noqa: BLE001
        ref = None
    why = regress_reasons(ref, man)
    if why and not allow_regress:
        raise RegressError(f"원격 마지막 묶음 {st[-1]} 대비 " + " · ".join(why) + " — 보내기·회전 멈춤(새 서버·빈 원장·열쇠 분실이면 원격 정상 묶음이"
                           " 회전으로 지워짐) · 맞으면 python3 tools/offsite_backup.py run --force --allow-regress")
    if why:
        log("경고(--allow-regress): " + " · ".join(why) + " — 그래도 보냄(다른 열쇠 묶음은 회전에서 안 지움)")


class RegressError(RuntimeError):
    pass


def prune_remote(c: dict, kid: str = None) -> list:
    try:
        st = remote_stamps(c)
    except UnicodeDecodeError:
        return []
    if kid:
        try:
            mans = remote_manifests(c, st)
        except Exception:   # noqa: BLE001
            return []
        st = [s for s in st if _kid_of(mans.get(s)) == kid]
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


def fetch(c: dict, stamp: str = None, log=print, key=None, allow_unsigned: bool = False) -> str:
    st = remote_stamps(c)
    if not st:
        raise RuntimeError("원격에 묶음이 없어요")
    stamp = stamp or st[-1]
    if stamp not in st:
        raise RuntimeError(f"원격에 없는 묶음: {stamp} (있는 것: {', '.join(st)})")
    d = os.path.join(BK_DIR, "offsite_fetch", stamp)
    os.makedirs(d, mode=0o700, exist_ok=True)
    key, mp = seal.load_key(AUTH_KEY) if key is None else key, os.path.join(d, f"{stamp}.manifest.json")
    try:
        recv(c, f"{stamp}.manifest.json", mp)
        for n, _h in seal.manifest_parts(seal.load_manifest(mp, stamp, key, allow_unsigned, log=lambda *a: None), stamp):
            recv(c, n, os.path.join(d, n))
        return seal.open_bundle(d, stamp, d, key, allow_unsigned, log)
    except seal.AuthError:
        for n in os.listdir(d):
            if n.startswith(stamp + "."):
                os.remove(os.path.join(d, n))
        raise


def _link_new(src: str, dst: str) -> bool:
    try:
        os.link(src, dst)
        return True
    except FileExistsError:
        return False


FILES_MEMBER_RX = re.compile(r"^(files_\d{8})(?:/((?!\.)[\w.@-]+)(/(?!\.)[\w.-]+(?:/(?!\.)[\w.-]+)?)?)?$|^(prefs_\d{8}\.json)$")


def unpack_files(src_dir: str, stamp: str, key, allow_unsigned: bool = False, dst_dir: str = None, log=print) -> list:
    dst_dir = dst_dir or BK_DIR
    man = seal.load_manifest(os.path.join(src_dir, stamp + ".manifest.json"), stamp, key, allow_unsigned, log=lambda *a: None)
    parts = dict(seal.manifest_parts(man, stamp))
    fname = stamp + ".files.tar.gz"
    if fname not in parts:
        return []
    os.makedirs(dst_dir, mode=0o700, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".offsite_unpack_", dir=dst_dir)
    placed = []
    try:
        tp, h = os.path.join(tmp, ".bundle.tar.gz"), hashlib.sha256()
        with open(os.path.join(src_dir, fname), "rb") as f, fsio.atomic_open(tp, binary=True, mode=0o600, makedirs=False) as g:
            for b in iter(lambda: f.read(CHUNK), b""):
                h.update(b)
                g.write(b)
        if h.hexdigest() != parts[fname]:
            raise RuntimeError("원장 밖 사본 sha256 불일치")
        with tarfile.open(tp, "r:gz") as tf:
            for m in tf:
                mm = FILES_MEMBER_RX.match(m.name)
                if mm and mm.group(3) and mm.group(2) != lb.CANDLES:
                    mm = None
                if m.isdir() and mm and mm.group(1) and (not mm.group(2) or mm.group(2) == lb.CANDLES):
                    continue
                if not mm or not m.isfile() or (mm.group(2) == lb.CANDLES and (mm.group(3) or "").count("/") != 2):
                    log(f"원장 밖 사본: 건너뜀 {m.name[:80]}")
                    continue
                out = os.path.join(tmp, m.name)
                if os.path.lexists(out):
                    continue
                os.makedirs(os.path.dirname(out), mode=0o700, exist_ok=True)
                with fsio.atomic_open(out, binary=True, mode=0o600, makedirs=False) as f, tf.extractfile(m) as g:
                    shutil.copyfileobj(g, f)
        os.remove(tp)
        for top in sorted(os.listdir(tmp)):
            src9, dst = os.path.join(tmp, top), os.path.join(dst_dir, top)
            placed.append(top)
            pairs = [(src9, dst)]
            if os.path.isdir(src9):
                try:
                    os.mkdir(dst, 0o700)
                except FileExistsError:
                    if os.path.islink(dst) or not os.path.isdir(dst):
                        log(f"원장 밖 사본: {top} 자리가 폴더가 아니라 그대로 둠")
                        continue
                pairs = [(os.path.join(src9, n), os.path.join(dst, n)) for n in sorted(os.listdir(src9)) if n != lb.CANDLES]
                cand_dir = os.path.join(dst, lb.CANDLES)
                if os.path.isdir(os.path.join(src9, lb.CANDLES)):
                    for sub, fn in lb.candle_files(os.path.join(src9, lb.CANDLES)):
                        dd = os.path.join(cand_dir, sub)
                        if os.path.islink(cand_dir) or os.path.islink(dd):
                            continue
                        try:
                            os.makedirs(dd, mode=0o700, exist_ok=True)
                        except OSError:
                            continue
                        pairs.append((os.path.join(src9, lb.CANDLES, sub, fn), os.path.join(dd, fn)))
            kept = [os.path.basename(d) for s9, d in pairs if not _link_new(s9, d)]
            if kept:
                log(f"원장 밖 사본: {top} 안 {len(kept)}개가 이미 있어 그대로 둠(덮지 않음)" if os.path.isdir(src9)
                    else f"원장 밖 사본: {top} 이 이미 있어 그대로 둠(덮지 않음)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return placed


def err_text(e) -> str:
    m = logs.safe_err(e)
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


def run(force: bool = False, check: bool = True, cfg: dict = None, now: float = None, log=print, allow_regress: bool = False) -> int:
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
            kid9 = _kid_of(man)
            if not st.get("kid"):
                st["kid"] = _prev_local_kid(man["stamp"]) or None
            if st.get("kid") and kid9 and st["kid"] != kid9:
                st.update(kid_prev=st["kid"], kid_changed_at=int(now + (time.time() - t0)))
                log(f"경고: 서버 밖 백업 열쇠가 바뀜(kid {st['kid']} → {kid9}) — 그 전 묶음은 옛 열쇠로만 열림")
            if kid9 and st.get("kid") != kid9:
                st["kid"] = kid9
                write_status(st)
            if c["mode"] == "push":
                try:
                    check_remote(c, man, allow_regress, log)
                except RegressError:
                    for n in os.listdir(OUT_DIR):
                        if n.startswith(man["stamp"] + "."):
                            os.remove(os.path.join(OUT_DIR, n))
                    raise
                except Exception:
                    prune_local(max(1, c["keep_local"]), man["stamp"])
                    raise
            prune_local(max(1, c["keep_local"]), man["stamp"])
            res = push(c, man, log=log) if c["mode"] == "push" else {}
            prune_local(max(c["keep_local"], 1 if c["mode"] == "outbox" else c["keep_local"]), man["stamp"])
            t_end9 = int(now + (time.time() - t0))
            st.update(last_built=t_end9, last_stamp=man["stamp"], raw_size=man["db"]["raw_size"],
                      data_until=man["db"].get("data_until"), dur=round(time.time() - t0, 1), err=None, running=False,
                      remote_pruned=res.get("remote_pruned"))
            if c["mode"] == "push":
                st.update(last_ok=t_end9, size=man["db"]["size"], dest=f"{c['host']}:{c['path']}", hostkey="고정" if c["host_key_fpr"] else "미고정")
            else:
                st.update(dest="outbox(받는 쪽 확인 대기)")
            write_status(st)
            log(("서버 밖 백업 완료" if c["mode"] == "push" else "서버 밖 백업 묶음 만듦(받는 쪽 confirm 대기)")
                + f": {man['stamp']} ({man['db']['size'] / 1024 ** 3:.2f}GB 압축 · {st['dur']:.0f}초)")
            return 0
        except Exception as e:   # noqa: BLE001
            st.update(err=err_text(e)[:240], err_at=int(now + (time.time() - t0)), running=False)
            write_status(st)
            log("서버 밖 백업 실패: " + st["err"])
            for n in os.listdir(OUT_DIR) if os.path.isdir(OUT_DIR) else []:
                if n.endswith((".part", ".snap.db")):
                    os.remove(os.path.join(OUT_DIR, n))
            prune_orphans(stamp_of(now))
            return 1
    finally:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
        lockf.close()


RESTORE_ORDER = """복구 순서(새 설치도 · tj-core 는 마지막에):
  1 원장  python3 tools/ledger_restore.py restore {p}  (미리보기 → pm2 stop … → --apply · tj-core 는 아직 띄우지 않음)
  2 원장 밖 사본  python3 tools/ledger_restore.py files {day}  (미리보기 → pm2 stop tj-web tj-review → --apply)
  3 config 지갑  state/backups/files_{day}/config_subset.json 의 wallets · chain_wallets · exchange_addresses 를 config.json 에 옮김
  4 그 다음에 pm2 start tj-core  (지갑 없이 띄우면 원장을 지갑 없는 기준으로 다시 기장)"""

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
                받는 쪽 회전은 직접 — rsync 는 지우지 않아 묶음이 쌓임 · --delete 는 쓰지 말 것(이 컴퓨터 outbox 가 비거나 새 서버면 받는 쪽 정상 묶음도
                지워짐) · confirm 이 성공한 묶음 중 최신 N벌만 남기고 지우되, 새 묶음이 지난 것보다 크게 작으면(원장 크기 raw_size) 지우지 말고 확인.
크론(매시 — 하루 1번만 보냄 · 실패 뒤 3시간 쉼):  17 * * * * cd <설치 폴더> && python3 tools/offsite_backup.py run
배포 중(설치 폴더 .deploy.lock 배타 잠금 — 배포 도구가 잡음): run = 건너뜀(0) · confirm 등 = 끝날 때까지 기다림(TJ_DEPLOY_BARRIER_WAIT 초 · 기본 600) ·
  시간 초과 = 75(받는 쪽 크론이 다음에 다시 보내면 됨 — 위 예시는 비0 이면 다음 날 다시).
묶음 = 원장 압축본(.db.gz) · 원장 밖 사본(.files.tar.gz — .env 제외 · 첫 정기 백업 전엔 없음) · manifest(sha256 + HMAC) · 되돌리기 = fetch(또는 open —
  원장 + 원장 밖 사본을 state/backups/files_<날>/ · prefs_<날>.json 으로 · 이미 있으면 그대로) → 원장 restore → ledger_restore files <날> →
  config 지갑(config_subset.json) → 마지막에 tj-core · test = ssh 연결 · 원격 폴더·여유 · 보낼 도구(rsync → 없으면 scp)와 원격 rsync 까지 확인.\n""" + seal.HELP


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="서버 밖 둘째 백업", epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--force", action="store_true", help="간격과 무관하게 지금")
    r.add_argument("--no-check", action="store_true", help="압축 전 quick_check 생략")
    r.add_argument("--allow-regress", action="store_true",
                   help="원격 마지막 묶음보다 원장이 크게 작거나 오래됐거나 다른 열쇠여도 보냄(되돌린 원장·새 열쇠가 맞을 때만 · 다른 열쇠 묶음은 회전에서 안 지움)")
    sub.add_parser("status")
    sub.add_parser("test")
    sub.add_parser("list-remote")
    f = sub.add_parser("fetch")
    f.add_argument("stamp", nargs="?")
    o = sub.add_parser("open", help="로컬 묶음 확인·풀기(ssh 없음 · 받는 쪽·outbox): HMAC → sha256 → 원장 풀기")
    o.add_argument("dir")
    o.add_argument("stamp")
    for p9 in (f, o):
        p9.add_argument("--auth-key", help="HMAC 열쇠 사본(없으면 이 설치 state/backups/offsite_auth.key)")
        p9.add_argument("--allow-unsigned", action="store_true", help="서명(auth) 없는 옛 묶음 허용(경고 · sha256 만)")
    sub.add_parser("auth-key", help="HMAC 열쇠 kid(없으면 만듦) · --export <파일> = 사본(0600)").add_argument("--export")
    cf = sub.add_parser("confirm", help="outbox: 받는 쪽이 가져간 묶음 확인(sha256)")
    cf.add_argument("stamp")
    cf.add_argument("sha256")
    a = ap.parse_args(argv)
    c = conf()
    if a.cmd == "run":
        return run(force=a.force, check=not a.no_check, allow_regress=a.allow_regress)
    if a.cmd == "confirm":
        return confirm(a.stamp, a.sha256)
    if a.cmd == "auth-key":
        rc = seal.key_cli(AUTH_KEY, a.export)
        if rc == 0 and a.export:
            lk = _lock(True)
            try:
                st = read_status()
                k9 = seal.load_key(AUTH_KEY)
                if "kid_changed_at" in st or (k9 and st.get("kid") != seal.kid(k9)):
                    st.pop("kid_changed_at", None)
                    st.pop("kid_prev", None)
                    if k9:
                        st["kid"] = seal.kid(k9)
                    write_status(st)
            finally:
                if lk:
                    fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
                    lk.close()
        return rc
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
                print("연결 실패: " + logs.safe_err(e)[:300])
                return 1
            lines9 = [x for x in out.strip().splitlines() if x.strip()]
            if tool9 == "rsync" and "TJ_RSYNC_OK" not in lines9:
                print("원격에 rsync 가 없어요 — 이 컴퓨터는 rsync 로 보내므로 실패해요(원격에 rsync 설치)")
                return 1
            print("연결 정상 · 보내기: " + why9 + " · 원격 여유: " + (lines9[0] if lines9 else "?") + " · 호스트 키 " + ("고정" if c["host_key_fpr"] else "미고정"))
            return 0
        if a.cmd == "list-remote":
            try:
                st9 = remote_stamps(c)
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                print("연결 실패: " + err_text(e)[:300], file=sys.stderr)
                return 1
            for s in st9:
                print(s)
            if not st9:
                print("원격에 묶음이 없어요(" + str(c.get("path")) + ")", file=sys.stderr)
            return 0
    try:
        key = seal.read_key_file(a.auth_key) if a.auth_key else seal.load_key(AUTH_KEY)
        p = fetch(c, a.stamp, key=key, allow_unsigned=a.allow_unsigned) if a.cmd == "fetch" else \
            seal.open_bundle(a.dir, a.stamp, os.path.join(BK_DIR, "offsite_fetch", a.stamp), key, a.allow_unsigned)
        stamp9 = os.path.basename(os.path.dirname(p)) if a.cmd == "fetch" else a.stamp
        put9 = unpack_files(os.path.dirname(p) if a.cmd == "fetch" else a.dir, stamp9, key, a.allow_unsigned)
    except seal.AuthError as e:
        print("인증 실패(묶음을 믿을 수 없음): " + err_text(e)[:300])
        return 3
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print("가져오기 실패: " + err_text(e)[:300])
        return 1
    days9 = sorted({re.sub(r"\D", "", x)[:8] for x in put9 if x.startswith(("files_", "prefs_"))}, reverse=True)
    day9 = max((x[6:14] for x in put9 if x.startswith("files_")), default=None) or (days9[0] if days9 else "<YYYYMMDD>")
    print(f"받음: {p}" + (f"\n원장 밖 사본 자리: state/backups/{' · '.join(put9)}" if put9 else ""))
    try:
        man9 = seal.load_manifest(os.path.join(os.path.dirname(p) if a.cmd == "fetch" else a.dir, stamp9 + ".manifest.json"), stamp9, key,
                                  a.allow_unsigned, log=lambda *x: None)
        for ln9 in incomplete_lines(man9):
            print(ln9 + " — ledger_restore files <날> 미리보기에 빠진 이름 · 마지막 완전 사본 날짜가 나와요")
    except (RuntimeError, OSError, seal.AuthError):
        pass
    print(RESTORE_ORDER.format(p=p, day=day9))
    for d9 in days9:
        if d9 != day9 and f"prefs_{d9}.json" in put9 and f"files_{d9}" not in put9:
            print(f"  (+ 날짜가 다른 state/backups/prefs_{d9}.json 은 ui_prefs·outflow_decisions 칸만 손으로 state/ui_prefs.json·state/outflow_decisions.json 에"
                  " — files {d9} 통째 적용은 그날 다른 사본까지 옛 값으로 덮을 수 있음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

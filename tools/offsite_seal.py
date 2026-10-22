from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import subprocess

import fsio

__all__ = ["KEY_LEN", "FPR_RX", "HELP", "AuthError", "load_key", "read_key_file", "export_key", "key_cli", "kid", "canon", "seal",
           "verify", "manifest_parts", "load_manifest", "open_bundle", "host_opts", "key_fpr", "parse_fprs"]

KEY_LEN = 32
ALG = "hmac-sha256"
CHUNK = 8 << 20
STAMP_RX = re.compile(r"tjoff_\d{8}_\d{4}")
FPR_RX = re.compile(r"SHA256:[A-Za-z0-9+/]{43}")
KH_PATH_RX = re.compile(r"/[A-Za-z0-9._/-]+")
_SCANNED = set()
HELP = """송신자 인증: manifest 에 HMAC(auth 칸) — 열쇠 state/backups/offsite_auth.key(32바이트 · 0600 · 첫 run 때 만듦 · 원격에 안 감).
  받기·열기 차례 = manifest 인증 → sha256(원장 압축본 · 원장 밖 사본 있으면) → 풀기 → raw_sha256 · 인증 실패 = rc 3(fetch 는 받은 것 지움) ·
  서명 없는 옛 묶음 = --allow-unsigned 일 때만(경고) · 다른 컴퓨터에서 = --auth-key <열쇠 사본>. 서버를 잃어도 확인하려면
  auth-key --export <파일> 로 사본을 서버 밖에 보관. 원격이 manifest·묶음을 바꾸면(sha256 까지 맞춰도) HMAC 이 달라 거부.
보안(NC7 ⑤): 묶음은 압축만 하고 ★암호화하지 않아요★ — 받는 컴퓨터에 접근할 수 있는 사람은 원장(거래·주소·금액)을 읽을 수 있으니 믿는 컴퓨터만.
  호스트 키: backup.offsite.host_key_fpr = "SHA256:…"(여럿 = 쉼표 · 받는 쪽에서 ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub) 이면
  그 지문의 키만 state/backups/known_hosts_offsite 에 두고 StrictHostKeyChecking=yes(원격 명령마다 대조 · 다르면 접속 전 실패 ·
  OpenSSH 8.5 이상 · 고정 땐 프록시(ProxyCommand·ProxyJump)·DNS SSHFP·GSS 키 교환 끔 · 사용자 ssh_config 의 IgnoreUnknown 은 이 명령 값이 먼저) · 없으면 처음 접속 때 받아들임(accept-new — 그 뒤 키가 바뀌면 거부 · status 의 hostkey '미고정')."""


class AuthError(RuntimeError):
    pass


def _read_exact(path: str) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as f:
        return f.read(KEY_LEN + 1)


def load_key(path: str, create: bool = False):
    if create and not os.path.lexists(path):
        fsio.create_exclusive(path, os.urandom(KEY_LEN), mode=0o600)
    try:
        k = _read_exact(path)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise AuthError("열쇠 파일을 못 읽음(%s): %s" % (path, e.strerror or e)) from e
    if len(k) != KEY_LEN:
        raise AuthError("열쇠 길이가 %d바이트가 아님(%s) — 손상 · 묶음을 만들지 않음" % (KEY_LEN, path))
    return k


def read_key_file(path: str) -> bytes:
    k = load_key(os.path.expanduser(path))
    if k is None:
        raise AuthError("열쇠 사본이 없음: %s" % path)
    return k


def export_key(key: bytes, dst: str) -> str:
    if not fsio.create_exclusive(os.path.expanduser(dst), key, mode=0o600, makedirs=False):
        raise FileExistsError("이미 있는 파일: %s(덮지 않음)" % dst)
    return kid(key)


def key_cli(path: str, export: str = None, out=print) -> int:
    try:
        key = load_key(path, create=True)
        out("열쇠 kid %s" % (export_key(key, export) + " · 사본 = " + export if export else kid(key)))
    except (RuntimeError, OSError) as e:
        out("열쇠 실패: %s" % e)
        return 1
    return 0


def kid(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def canon(man: dict) -> bytes:
    return json.dumps({k: v for k, v in man.items() if k != "auth"}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def seal(man: dict, key: bytes) -> dict:
    man["auth"] = {"alg": ALG, "kid": kid(key), "mac": hmac.new(key, canon(man), hashlib.sha256).hexdigest()}
    return man


def verify(man: dict, key: bytes) -> None:
    a = man.get("auth") if isinstance(man, dict) else None
    if not isinstance(a, dict) or a.get("alg") != ALG or not re.fullmatch(r"[0-9a-f]{64}", str(a.get("mac"))) \
            or not re.fullmatch(r"[0-9a-f]{8}", str(a.get("kid"))) or not isinstance(a["mac"], str) or not isinstance(a["kid"], str):
        raise AuthError("manifest 인증 칸 꼴이 아님")
    if a["kid"] != kid(key):
        raise AuthError("다른 열쇠로 봉인된 묶음(kid %s · 이 열쇠 %s)" % (a["kid"], kid(key)))
    try:
        want = hmac.new(key, canon(man), hashlib.sha256).hexdigest()
    except (TypeError, ValueError) as e:
        raise AuthError("manifest 를 정규화할 수 없음(꼴 아님)") from e
    if not hmac.compare_digest(a["mac"], want):
        raise AuthError("manifest HMAC 이 맞지 않음(변조 또는 다른 열쇠)")


def load_manifest(path: str, stamp: str, key, allow_unsigned: bool = False, log=print) -> dict:
    if not STAMP_RX.fullmatch(str(stamp or "")):
        raise RuntimeError("묶음 이름 형식: tjoff_YYYYMMDD_HHMM")
    try:
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError("manifest 를 못 읽음: %s" % os.path.basename(path)) from e
    if not isinstance(man, dict):
        raise RuntimeError("manifest 꼴이 아님")
    if "auth" in man:
        if key is None:
            raise AuthError("봉인된 묶음인데 열쇠가 없음 — --auth-key <오너 사본>")
        verify(man, key)
    elif not allow_unsigned:
        raise AuthError("서명 없는 묶음(옛 판) — 믿을 때만 --allow-unsigned")
    else:
        log("경고: 서명 없는 묶음을 --allow-unsigned 로 엶(보낸 쪽 확인 없음 · sha256 만)")
    if man.get("stamp") != stamp:
        raise RuntimeError("manifest 묶음 이름이 다름")
    return man


def manifest_parts(man: dict, stamp: str) -> list:
    out = []
    for part, tail, need in (("db", ".db.gz", True), ("files", ".files.tar.gz", False)):
        p = man.get(part)
        if not p and not need:
            continue
        if not isinstance(p, dict) or p.get("name") != stamp + tail or not re.fullmatch(r"[0-9a-f]{64}", str(p.get("sha256") or "")):
            raise RuntimeError("manifest %s 칸 꼴이 아님(이름·sha256)" % part)
        out.append((p["name"], p["sha256"]))
    return out


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def open_bundle(src_dir: str, stamp: str, out_dir: str, key, allow_unsigned: bool = False, log=print) -> str:
    man = load_manifest(os.path.join(src_dir, stamp + ".manifest.json"), stamp, key, allow_unsigned, log)
    parts = manifest_parts(man, stamp)
    for name, want in parts:
        p = os.path.join(src_dir, name)
        if not os.path.isfile(p):
            raise RuntimeError("묶음 파일 없음: %s" % name)
        if _sha256(p) != want:
            raise RuntimeError("%s sha256 불일치" % ("받은 원장 압축본" if name.endswith(".db.gz") else "원장 밖 사본"))
    raw = str((man.get("db") or {}).get("raw_sha256") or "")
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    out = os.path.join(out_dir, "ledger_%s.db" % stamp[6:])
    h = hashlib.sha256()
    with fsio.atomic_open(out, binary=True, mode=0o600) as f, gzip.open(os.path.join(src_dir, parts[0][0]), "rb") as g:
        for b in iter(lambda: g.read(CHUNK), b""):
            h.update(b)
            f.write(b)
        if not hmac.compare_digest(h.hexdigest(), raw):
            raise RuntimeError("풀린 원장 sha256 불일치")
    return out


def parse_fprs(v) -> list:
    items = [] if v is None else v.split(",") if isinstance(v, str) else list(v) if isinstance(v, (list, tuple)) else [repr(v)]
    out = []
    for x in items:
        s = str(x).strip()
        s = s.rstrip("=") or s
        if s and s not in out:
            out.append(s)
    return out


def key_fpr(blob_b64: str) -> str:
    try:
        raw = base64.b64decode(blob_b64, validate=True)
    except (ValueError, TypeError):
        return ""
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")


def _pattern(c: dict) -> str:
    return str(c["host"]) if int(c["port"]) == 22 else "[%s]:%d" % (c["host"], int(c["port"]))


def _kh_lines(text: str) -> list:
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            p = ln.split()
            out.append((p[0], p[1], p[2]) if len(p) >= 3 else ("", "", ""))
    return out


def _ensure_known_hosts(c: dict, kh: str) -> None:
    want, pat = set(c["host_key_fpr"]), _pattern(c)
    if any(not FPR_RX.fullmatch(str(x)) for x in want):
        raise RuntimeError("host_key_fpr 형식이 아님 — 접속하지 않음")
    if not KH_PATH_RX.fullmatch(kh):
        raise RuntimeError("known_hosts 경로에 영문·숫자·_ . - / 밖 글자가 있어 지문 고정을 못 함(ssh 가 다르게 읽을 수 있음): %s" % kh)
    try:
        with open(kh, encoding="utf-8") as f:
            cur = _kh_lines(f.read())
    except OSError:
        cur = []
    have = {key_fpr(b) for _p, _t, b in cur}
    if cur and all(p == pat for p, _t, _b in cur) and have <= want and (have == want or (pat, frozenset(want)) in _SCANNED):
        return
    try:
        r = subprocess.run(["ssh-keyscan", "-T", "15", "-p", str(int(c["port"])), str(c["host"])], capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError("호스트 키를 못 읽음(ssh-keyscan): %s" % e) from e
    keep = sorted({(t, b) for _p, t, b in _kh_lines(r.stdout) if t and key_fpr(b) in want})
    if not keep:
        raise RuntimeError("원격 호스트 키 지문이 설정(backup.offsite.host_key_fpr)과 다름 — 접속하지 않음")
    _SCANNED.add((pat, frozenset(want)))
    fsio.atomic_write_text(kh, "".join("%s %s %s\n" % (pat, t, b) for t, b in keep), mode=0o600)


def host_opts(c: dict, kh: str) -> list:
    if not c.get("host_key_fpr"):
        return ["-o", "StrictHostKeyChecking=accept-new"]
    _ensure_known_hosts(c, kh)
    return ["-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + kh, "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "KnownHostsCommand=none", "-o", "VerifyHostKeyDNS=no", "-o", "NoHostAuthenticationForLocalhost=no",
            "-o", "ProxyCommand=none", "-o", "ProxyJump=none", "-o", "UpdateHostKeys=no", "-o", "CheckHostIP=no",
            "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-o", "IgnoreUnknown=GSSAPIKeyExchange,NoHostAuthenticationForProxyCommand", "-o", "GSSAPIKeyExchange=no",
            "-o", "NoHostAuthenticationForProxyCommand=no"]

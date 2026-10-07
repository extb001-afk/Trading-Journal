from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
import unicodedata
import urllib.parse

import common
import settings_store as ss

log = logging.getLogger("tj-web")

AUTH_PATH = os.path.join(common.STATE_DIR, "auth.json")
SESS_PATH = os.path.join(common.STATE_DIR, "auth_sessions.json")
INTERNAL_PATH = os.path.join(common.STATE_DIR, "auth_internal_token")
SETUP_CODE_PATH = os.path.join(common.STATE_DIR, "auth_setup_code")
SETUP_CODE_REL = "state/auth_setup_code"
_SC_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
V2_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "v2")
COOKIE = "tj_session"
INTERNAL_HDR = "X-TJ-Internal"

ITER = 600_000
MIN_ITER = 200_000
PW_MIN, PW_MAX = 10, 256
MAX_SESSIONS = 20
SEEN_SAVE_SEC = 600
BODY_MAX = 4096
FAIL_MAX, FAIL_WINDOW = 5, 600
LOCK_BASE, LOCK_CAP = 900, 86400
LOCK_DECAY = 86400
GLOBAL_FAILS, GLOBAL_WINDOW = 50, 600
RL_MAX_KEYS = 10000
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{43}")
PROXY_HDRS = ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "Forwarded", "X-Real-Ip", "Via", "Cdn-Loop",
              "Cf-Connecting-Ip", "Cf-Ray", "Cf-Visitor", "Cf-Warp-Tag-Id", "True-Client-Ip")
_PROXY_PREFIX = ("cf-", "x-forwarded-")
_PROXY_HDRS = PROXY_HDRS
LOGIN_CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
_COMMON_WEAK = {"password12", "password123", "password1234", "password12345", "passw0rd12", "qwertyuiop", "qwerty1234",
                "qwerty12345", "1q2w3e4r5t", "1q2w3e4r5t6y", "1qaz2wsx3edc", "asdfghjkl;", "asdfghjkl1", "zxcvbnm123",
                "iloveyou12", "admin12345", "admin123456", "letmein123", "welcome123", "abc1234567", "abcd123456",
                "qwer123456", "a123456789", "1234567890a", "1234qwer!@", "q1w2e3r4t5"}

_now = time.time


def _int(v, dflt, lo, hi):
    try:
        if isinstance(v, bool):
            raise TypeError
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return dflt


class Settings:
    def __init__(self, raw):
        r = raw if isinstance(raw, dict) else {}
        self.enabled = raw is not False and r.get("enabled") is not False
        self.session_days = _int(r.get("session_days"), 30, 1, 365)
        self.idle_days = min(_int(r.get("idle_days"), 7, 1, 365), self.session_days)
        self.secure = r.get("secure_cookie") is True


BEHIND_PROXY = False
S = Settings({"enabled": False})
_LOCK = threading.RLock()
_AUTH = {"sig": False, "rec": None, "err": None}
_SESS = {"sig": False, "d": {}, "saved": 0.0}
_HASH_SEM = threading.BoundedSemaphore(2)


def init(cfg: dict) -> Settings:
    global S, BEHIND_PROXY
    w = (cfg or {}).get("web") if isinstance((cfg or {}).get("web"), dict) else {}
    S = Settings(w.get("login", None))
    BEHIND_PROXY = w.get("behind_proxy") is True
    if BEHIND_PROXY:
        log.info("web.behind_proxy = true — 모든 요청을 리버스 프록시 경유로 취급(첫 비밀번호는 tools/reset_password.py)")
    if S.enabled:
        common.ensure_dirs()
        rotate_internal_token()
        st = password_state()[0]
        log.info("웹 로그인 켜짐 — 세션 %d일 · 미사용 %d일 · 비밀번호 %s", S.session_days, S.idle_days,
                 {"set": "설정됨", "none": "없음(이 컴퓨터에서 /login 으로 만드세요)", "damaged": "파일 손상(tools/reset_password.py)"}[st])
        if st == "none":
            setup_code(create=True)
        elif st == "set":
            drop_setup_code()
    else:
        try:
            os.unlink(INTERNAL_PATH)
        except OSError:
            pass
    return S


def _norm(pw: str) -> str:
    return unicodedata.normalize("NFC", pw)


def hash_password(pw: str, iters: int = None, salt: bytes = None) -> dict:
    iters = int(iters or ITER)
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", _norm(pw).encode("utf-8"), salt, iters)
    return {"v": 1, "algo": "pbkdf2_sha256", "iter": iters, "salt": salt.hex(), "hash": dk.hex(), "set_at": int(_now())}


def _rec_ok(rec) -> bool:
    try:
        return (isinstance(rec, dict) and rec.get("algo") == "pbkdf2_sha256"
                and type(rec.get("iter")) is int and MIN_ITER <= rec["iter"] <= 10_000_000
                and len(bytes.fromhex(rec.get("salt") or "")) >= 16 and len(bytes.fromhex(rec.get("hash") or "")) == 32)
    except (TypeError, ValueError):
        return False


def verify_password(pw, rec) -> bool:
    if not isinstance(pw, str) or not pw or len(pw) > PW_MAX or not _rec_ok(rec):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", _norm(pw).encode("utf-8"), bytes.fromhex(rec["salt"]), rec["iter"])
    return hmac.compare_digest(dk, bytes.fromhex(rec["hash"]))


def _is_run(s: str) -> bool:
    if len(s) < 4:
        return False
    d = {((int(b) - int(a)) % 10 if a.isdigit() and b.isdigit() else ord(b) - ord(a)) for a, b in zip(s, s[1:])}
    return d in ({1}, {-1}, {9})


def password_problem(pw) -> str | None:
    if not isinstance(pw, str):
        return "비밀번호 형식 오류"
    p = _norm(pw)
    if len(p) < PW_MIN:
        return f"{PW_MIN}자 이상으로 만들어 주세요"
    if len(p) > PW_MAX:
        return f"{PW_MAX}자 이하로 만들어 주세요"
    if any(ord(c) < 32 or ord(c) == 127 for c in p):
        return "줄바꿈·제어 문자는 넣을 수 없어요"
    if p.strip() != p:
        return "앞뒤 공백은 넣을 수 없어요"
    if len(set(p)) == 1:
        return "같은 글자만 반복한 비밀번호는 쓸 수 없어요"
    if p.isdigit() and len(p) < 12:
        return "숫자로만 만들 땐 12자 이상이어야 해요"
    low = p.lower()
    if low in _COMMON_WEAK or _is_run(low) or _is_run(low.rstrip("!@#$%^&*.?~")):
        return "너무 쉬운 비밀번호예요 — 다른 걸로 만들어 주세요"
    for k in (2, 3):
        if low == (low[:k] * (len(low) // k + 1))[:len(low)]:
            return "같은 글자 묶음을 반복한 비밀번호는 쓸 수 없어요"
    return None


def _sig(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size, st.st_mode)


def _tighten(path):
    try:
        if os.stat(path).st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            os.chmod(path, 0o600)
            log.warning("%s 권한이 넓어 0600 으로 좁혔습니다", os.path.basename(path))
    except OSError:
        pass


def _write(path, obj):
    ss._atomic_write_text(path, json.dumps(obj, separators=(",", ":")), 0o600)


def _auth_locked():
    sig = _sig(AUTH_PATH)
    if sig != _AUTH["sig"]:
        rec, err = None, None
        if sig is not None:
            _tighten(AUTH_PATH)
            try:
                with open(AUTH_PATH, "r", encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                rec = None
            if not _rec_ok(rec):
                rec, err = None, "damaged"
                log.error("state/auth.json 손상 — 로그인 불가(복구: python3 tools/reset_password.py)")
        _AUTH.update(sig=sig, rec=rec, err=err)
    return _AUTH


def password_state():
    with _LOCK:
        a = _auth_locked()
        if a["err"]:
            return "damaged", None
        return ("set", a["rec"]) if a["rec"] else ("none", None)


class AuthChanged(Exception):
    pass


def _pg(rec) -> str:
    return hashlib.sha256(("%s:%s" % (rec.get("salt"), rec.get("hash"))).encode("ascii")).hexdigest()[:32] if rec else ""


def set_password(pw: str, iters: int = None, expected=None) -> dict:
    rec = hash_password(pw, iters)
    with _LOCK:
        if expected is not None and password_state() != ("set", expected):
            raise AuthChanged()
        _write(AUTH_PATH, rec)
        _AUTH.update(sig=_sig(AUTH_PATH), rec=rec, err=None)
    return rec


def _sessions_locked() -> dict:
    sig = _sig(SESS_PATH)
    if sig != _SESS["sig"]:
        d = {}
        if sig is not None:
            _tighten(SESS_PATH)
            try:
                with open(SESS_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                d = {k: v for k, v in raw.items() if isinstance(k, str) and len(k) == 64 and isinstance(v, dict)
                     and all(type(v.get(x)) is int for x in ("c", "s", "e"))} if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                log.warning("state/auth_sessions.json 을 읽지 못함 — 세션 전부 무효(다시 로그인)")
                d = {}
        _SESS.update(sig=sig, d=d)
    return _SESS["d"]


def _save_sessions_locked():
    _write(SESS_PATH, _SESS["d"])
    _SESS.update(sig=_sig(SESS_PATH), saved=_now())


def _tid(tok: str) -> str:
    return hashlib.sha256(tok.encode("ascii")).hexdigest()


def _alive(ent, now) -> bool:
    return now < ent["e"] and now - ent["s"] <= S.idle_days * 86400


def new_session(rec) -> str:
    tok = secrets.token_urlsafe(32)
    now = int(_now())
    with _LOCK:
        d = _sessions_locked()
        for k in [k for k, v in d.items() if not _alive(v, now)]:
            d.pop(k, None)
        while len(d) >= MAX_SESSIONS:
            d.pop(min(d, key=lambda k: (d[k]["c"], d[k]["s"])), None)
        d[_tid(tok)] = {"c": now, "s": now, "e": now + S.session_days * 86400, "pg": _pg(rec)}
        _save_sessions_locked()
    return tok


def check_session(tok):
    if not isinstance(tok, str) or not _TOKEN_RE.fullmatch(tok):
        return None
    tid = _tid(tok)
    now = _now()
    with _LOCK:
        d = _sessions_locked()
        ent = d.get(tid)
        if ent is None:
            return None
        st, rec = password_state()
        if st != "set" or not hmac.compare_digest(str(ent.get("pg") or ""), _pg(rec)):
            return None
        if not _alive(ent, now):
            d.pop(tid, None)
            _save_sessions_locked()
            return None
        if now - ent["s"] >= 60:
            ent["s"] = int(now)
            if now - _SESS["saved"] >= SEEN_SAVE_SEC:
                _save_sessions_locked()
        return dict(ent, tid=tid)


def revoke(tid=None, keep=None) -> int:
    with _LOCK:
        d = _sessions_locked()
        ks = [tid] if tid is not None else [k for k in d if k != keep]
        n = sum(1 for k in ks if d.pop(k, None) is not None)
        if n or tid is None:
            _save_sessions_locked()
        return n


def session_count() -> int:
    now = _now()
    with _LOCK:
        st, rec = password_state()
        if st != "set":
            return 0
        pg = _pg(rec)
        return sum(1 for v in _sessions_locked().values() if _alive(v, now) and v.get("pg") == pg)


def _sess_csrf(tok: str) -> str:
    return hmac.new(tok.encode("ascii"), b"tj-login-csrf-v1", hashlib.sha256).hexdigest()


def internal_token(create=False) -> str:
    try:
        with open(INTERNAL_PATH, "r", encoding="ascii") as f:
            t = f.read().strip()
        if len(t) >= 32:
            return t
    except (OSError, UnicodeDecodeError):
        pass
    if not create:
        return ""
    os.makedirs(os.path.dirname(INTERNAL_PATH), exist_ok=True)
    try:
        fd = os.open(INTERNAL_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _tighten(INTERNAL_PATH)
        return internal_token(False)
    t = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(t + "\n")
    return t


def _sc_norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())[:64]


def setup_code(create=False) -> str:
    with _LOCK:
        if password_state()[0] != "none":
            return ""
        return _setup_code_locked(create)


def _setup_code_locked(create=False) -> str:
    bad = False
    try:
        with open(SETUP_CODE_PATH, "r", encoding="ascii") as f:
            c = _sc_norm(f.read())
        if len(c) == 16:
            _tighten(SETUP_CODE_PATH)
            return c
        bad = True
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError):
        bad = True
    if not create:
        return ""
    os.makedirs(os.path.dirname(SETUP_CODE_PATH), exist_ok=True)
    if bad:
        try:
            os.unlink(SETUP_CODE_PATH)
        except FileNotFoundError:
            pass
        except OSError:
            return ""
    try:
        fd = os.open(SETUP_CODE_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _setup_code_locked(False)
    except OSError:
        return ""
    c = "".join(secrets.choice(_SC_ALPHA) for _ in range(16))
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write("-".join(c[i:i + 4] for i in range(0, 16, 4)) + "\n")
    log.info("첫 비밀번호 설정 코드를 만들었어요 — 이 컴퓨터의 %s 파일(첫 비밀번호 화면에 넣기 · 쓰고 나면 지워짐)", SETUP_CODE_REL)
    return c


def drop_setup_code() -> None:
    try:
        os.unlink(SETUP_CODE_PATH)
    except OSError:
        pass


def rotate_internal_token() -> str:
    t = secrets.token_urlsafe(32)
    ss._atomic_write_text(INTERNAL_PATH, t + "\n", 0o600)
    return t


def internal_headers() -> dict:
    t = internal_token(False)
    return {INTERNAL_HDR: t} if t else {}


def _ip(s):
    try:
        a = ipaddress.ip_address((s or "").strip())
    except ValueError:
        return None
    return a.ipv4_mapped if getattr(a, "ipv4_mapped", None) else a


def _peer(h):
    return _ip(h.client_address[0] if h.client_address else "")


def _proxy_marked(hd) -> bool:
    if any(hd.get(k) is not None for k in PROXY_HDRS):
        return True
    try:
        return any(str(k).lower().startswith(_PROXY_PREFIX) for k in hd.keys())
    except Exception:
        return False


def mark_conn(h) -> None:
    try:
        if not getattr(h, "tj_conn_proxied", False) and _proxy_marked(h.headers):
            h.tj_conn_proxied = True
    except Exception:
        pass


def proxied(h) -> bool:
    if BEHIND_PROXY or getattr(h, "tj_conn_proxied", False):
        return True
    return _proxy_marked(h.headers)


def direct_loopback(h) -> bool:
    p = _peer(h)
    return bool(p is not None and p.is_loopback and not proxied(h))


def client_ip(h) -> str:
    p = _peer(h)
    if p is not None and p.is_loopback:
        xff = (h.headers.get("X-Forwarded-For") or "").split(",")[-1]
        x = _ip(xff)
        if x is not None:
            return str(x)
    return str(p) if p is not None else "?"


def _bucket(ip: str) -> str:
    a = _ip(ip)
    if a is None:
        return ip
    if a.version == 6:
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(a)


def bucket_of(h) -> str:
    p = _peer(h)
    if not (p is not None and p.is_loopback and proxied(h)):
        return _bucket(client_ip(h))
    x = _ip((h.headers.get("X-Forwarded-For") or "").split(",")[-1])
    return "p:" + _bucket(str(x)) if x is not None and not x.is_loopback else "p:?"


def proxied_https(h) -> bool:
    p = _peer(h)
    xfp = (h.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    return bool(p is not None and p.is_loopback and xfp == "https")


def is_https(h) -> bool:
    return bool(S.secure or proxied_https(h))


def _hostname(h) -> str:
    x = (h.headers.get("Host") or "").strip().lower()
    if x.startswith("["):
        return x[1:x.find("]")] if "]" in x else x
    return x.rsplit(":", 1)[0] if x.count(":") == 1 else x


def setup_allowed(h) -> bool:
    return direct_loopback(h) and _hostname(h) in ("127.0.0.1", "localhost", "::1")


def _cookies(h, name=COOKIE):
    out = []
    for raw in h.headers.get_all("Cookie") or []:
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                out.append(v.strip().strip('"'))
    return out


def session_of(h):
    cs = _cookies(h)
    for c in cs:
        s = check_session(c)
        if s is not None:
            return s, c, True
    return None, None, bool(cs)


def _set_cookie(h, tok, max_age):
    return ("Set-Cookie", f"{COOKIE}={tok}; Path=/; Max-Age={int(max_age)}; HttpOnly; SameSite=Strict"
            + ("; Secure" if is_https(h) else ""))


def _internal_ok(h) -> bool:
    v = h.headers.get(INTERNAL_HDR)
    if not v:
        return False
    if not direct_loopback(h):
        p9 = _peer(h)
        if not (BEHIND_PROXY and p9 is not None and p9.is_loopback and not getattr(h, "tj_conn_proxied", False) and not _proxy_marked(h.headers)):
            return False
    t = internal_token(False)
    return bool(t) and hmac.compare_digest(v.encode("utf-8", "replace"), t.encode("ascii"))


class Limiter:
    def __init__(self):
        self.ip = {}
        self.glob = []
        self.lock = threading.Lock()
        self.gen = False

    def reset(self):
        with self.lock:
            self.ip.clear()
            self.glob = []

    def _st(self, b, now):
        st = self.ip.get(b)
        if st is None:
            st = self.ip[b] = {"f": [], "until": 0.0, "n": 0, "last": now}
        if st["n"] and now - st["last"] > LOCK_DECAY and st["until"] <= now:
            st["n"] = 0
        st["f"] = [t for t in st["f"] if now - t < FAIL_WINDOW]
        return st

    def wait(self, b, direct) -> int:
        now = _now()
        with self.lock:
            st = self.ip.get(b)
            if st and st["until"] > now:
                return max(1, int(st["until"] - now + 0.999))
            if not direct:
                self.glob = [t for t in self.glob if now - t < GLOBAL_WINDOW]
                if len(self.glob) >= GLOBAL_FAILS:
                    return max(1, int(self.glob[0] + GLOBAL_WINDOW - now + 0.999))
        return 0

    def fail(self, b) -> int:
        now = _now()
        with self.lock:
            st = self._st(b, now)
            st["f"].append(now)
            st["last"] = now
            self.glob.append(now)
            if len(self.glob) > GLOBAL_FAILS * 4:
                self.glob = [t for t in self.glob if now - t < GLOBAL_WINDOW]
            if len(st["f"]) >= FAIL_MAX:
                st["n"] += 1
                dur = min(LOCK_CAP, LOCK_BASE * (2 ** (st["n"] - 1)))
                st["until"] = now + dur
                st["f"] = []
                self._prune(now)
                return int(dur)
            self._prune(now)
            return 0

    def left(self, b) -> int:
        now = _now()
        with self.lock:
            st = self.ip.get(b)
            return FAIL_MAX - len([t for t in (st or {}).get("f", []) if now - t < FAIL_WINDOW])

    def ok(self, b):
        with self.lock:
            st = self.ip.get(b)
            if st:
                st["f"] = []
                st["n"] = 0

    def _prune(self, now):
        if len(self.ip) <= RL_MAX_KEYS:
            return
        for k in [k for k, v in self.ip.items() if v["until"] <= now and now - v["last"] > LOCK_DECAY]:
            self.ip.pop(k, None)
        if len(self.ip) > RL_MAX_KEYS:
            for k, _v in sorted(self.ip.items(), key=lambda kv: kv[1]["last"])[:len(self.ip) - int(RL_MAX_KEYS * 0.9)]:
                self.ip.pop(k, None)


LIM = Limiter()


def _mins(sec) -> str:
    m = max(1, int((sec + 59) // 60))
    return f"{m // 60}시간 {m % 60}분" if m >= 120 else f"{m}분"


def _json(h, code, obj, extra=()):
    data = json.dumps(obj, ensure_ascii=False).encode()
    h._send_bytes(code, data, None, "application/json; charset=utf-8", extra=tuple(extra))
    return True


def _file(h, name, ctype):
    with open(os.path.join(V2_DIR, name), "rb") as f:
        raw = f.read()
    extra = (("Referrer-Policy", "no-referrer"),)
    if ctype.startswith("text/html"):
        extra += (("Content-Security-Policy", LOGIN_CSP),)
    h._send_bytes(200, raw, None, ctype, extra=extra)
    return True


def safe_next(n) -> str:
    if not isinstance(n, str) or not n.startswith("/") or n.startswith("//") or n.startswith("/\\") or len(n) > 512:
        return "/"
    if any(ord(c) < 33 or ord(c) == 127 or c == "\\" for c in n):
        return "/"
    if n == "/login" or n.startswith("/login?") or n.startswith("/login/") or n.startswith("/api/"):
        return "/"
    return n


def _is_page(path: str) -> bool:
    last = path.rsplit("/", 1)[-1]
    return "." not in last or last.endswith(".html")


def _read_json(h, limit=BODY_MAX):
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        return None
    if n < 0 or n > limit:
        return None
    if n == 0:
        return {}
    h.connection.settimeout(10)
    try:
        d = json.loads(h.rfile.read(n).decode("utf-8"))
    except (ValueError, OSError):
        return None
    return d if isinstance(d, dict) else None


def _post_ok(h, onboarding, csrf_tok=None) -> bool:
    sfs = (h.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if not onboarding.origin_ok(h, required=True) or sfs not in ("", "same-origin"):
        _json(h, 403, {"ok": False, "error": "출처(Origin) 확인 실패 — 같은 화면에서만 요청할 수 있습니다"})
        return False
    if csrf_tok is not None:
        got = (h.headers.get("X-TJ-CSRF") or "").encode("utf-8", "replace")
        good = bool(got) and (hmac.compare_digest(got, _sess_csrf(csrf_tok).encode())
                              or hmac.compare_digest(got, ss.csrf_token().encode()))
        if not good:
            _json(h, 403, {"ok": False, "error": "CSRF 토큰 불일치 — 페이지를 새로고침하세요"})
            return False
    if not (h.headers.get("Content-Type") or "").lower().startswith("application/json"):
        _json(h, 415, {"ok": False, "error": "JSON 요청만 받습니다"})
        return False
    return True


def _sync_limiter() -> None:
    with _LOCK:
        sig = _auth_locked()["sig"]
        if getattr(LIM, "gen", False) is not False and LIM.gen != sig:
            LIM.reset()
        LIM.gen = sig


def _limited(h, b, direct) -> bool:
    _sync_limiter()
    w = LIM.wait(b, direct)
    if not w:
        return False
    _json(h, 429, {"ok": False, "error": f"로그인 시도가 너무 많아요 — {_mins(w)} 뒤에 다시 해 주세요", "retryAfter": w},
          (("Retry-After", str(w)),))
    return True


def _verify_limited(h, b, pw, rec, label):
    if not _HASH_SEM.acquire(timeout=10):
        _json(h, 503, {"ok": False, "error": "잠시 바빠요 — 몇 초 뒤 다시 해 주세요"})
        return False, True
    try:
        if _limited(h, b, direct_loopback(h)):
            return False, True
        good = verify_password(pw, rec)
    finally:
        _HASH_SEM.release()
    if good:
        LIM.ok(b)
        return True, False
    dur = LIM.fail(b)
    if dur:
        log.warning("%s 실패 반복 — %s 잠금 %s", label, b, _mins(dur))
        _json(h, 429, {"ok": False, "error": f"로그인 시도가 너무 많아요 — {_mins(dur)} 뒤에 다시 해 주세요", "retryAfter": dur},
              (("Retry-After", str(dur)),))
        return False, True
    log.info("%s 실패(%s)", label, b)
    return False, False


def _status(h):
    _sync_limiter()
    st, _rec = password_state()
    sess, tok, _had = session_of(h)
    d = {"ok": True, "enabled": True, "passwordSet": st == "set", "damaged": st == "damaged", "authed": sess is not None,
         "sessionDays": S.session_days, "idleDays": S.idle_days, "pwMin": PW_MIN}
    if st == "none":
        d["canSetup"] = setup_allowed(h)
        if d["canSetup"]:
            setup_code(create=True)
            d["setupCodePath"] = SETUP_CODE_REL
    if sess is not None:
        d.update(csrf=_sess_csrf(tok), exp=sess["e"], sessions=session_count())
    else:
        w = LIM.wait(bucket_of(h), direct_loopback(h))
        if w:
            d["retryAfter"] = w
    return _json(h, 200, d)


def _login(h, onboarding):
    if not _post_ok(h, onboarding):
        return True
    st, rec = password_state()
    if st == "damaged":
        return _json(h, 503, {"ok": False, "error": "인증 파일이 손상됐어요 — 서버에서 python3 tools/reset_password.py 로 다시 만드세요"})
    if st == "none":
        return _json(h, 409, {"ok": False, "setup": True, "error": "아직 비밀번호가 없어요 — 이 컴퓨터에서 먼저 만드세요"})
    b, direct = bucket_of(h), direct_loopback(h)
    if _limited(h, b, direct):
        return True
    body = _read_json(h)
    if body is None:
        return _json(h, 400, {"ok": False, "error": "본문 형식 오류(JSON 객체, 4KB 이하)"})
    pw = body.get("password")
    if not isinstance(pw, str) or not pw:
        return _json(h, 400, {"ok": False, "error": "비밀번호를 넣어 주세요"})
    good, done = _verify_limited(h, b, pw, rec, "로그인")
    if done:
        return True
    if not good:
        return _json(h, 401, {"ok": False, "error": "비밀번호가 맞지 않아요", "left": max(0, LIM.left(b))})
    changed = {"ok": False, "error": "비밀번호가 방금 바뀌었어요 — 새로고침 후 다시 로그인해 주세요"}
    with _LOCK:
        if password_state() != ("set", rec):
            return _json(h, 409, changed)
        if rec["iter"] < ITER:
            try:
                rec = set_password(pw, expected=rec)
            except AuthChanged:
                return _json(h, 409, changed)
            except OSError:
                pass
        old, _tok, _had = session_of(h)
        if old is not None:
            revoke(old["tid"])
        tok = new_session(rec)
    log.info("로그인 성공(%s)", b)
    return _json(h, 200, {"ok": True}, (_set_cookie(h, tok, S.session_days * 86400),))


def _setup(h, onboarding):
    if not _post_ok(h, onboarding):
        return True
    st, _rec = password_state()
    if st != "none":
        return _json(h, 409, {"ok": False, "error": "이미 비밀번호가 있어요 — 로그인해 주세요" if st == "set"
                              else "인증 파일이 손상됐어요 — 서버에서 python3 tools/reset_password.py 로 다시 만드세요"})
    if not setup_allowed(h):
        return _json(h, 403, {"ok": False, "error": "첫 비밀번호는 이 컴퓨터에서만 만들 수 있어요 — 서버에서 http://127.0.0.1:포트/login 으로 여세요"})
    body = _read_json(h)
    if body is None:
        return _json(h, 400, {"ok": False, "error": "본문 형식 오류(JSON 객체, 4KB 이하)"})
    want = setup_code(create=True)
    got = _sc_norm(body.get("code"))
    if not want or not got or not hmac.compare_digest(got.encode("ascii"), want.encode("ascii")):
        if got:
            log.info("첫 비밀번호 설정 코드 틀림(%s)", bucket_of(h))
        msg = ("설정 코드가 맞지 않아요" if got else "설정 코드를 넣어 주세요") + f" — 이 컴퓨터의 {SETUP_CODE_REL} 파일 내용(터미널: cat {SETUP_CODE_REL})"
        return _json(h, 403, {"ok": False, "code": True, "error": msg})
    pw = body.get("password")
    prob = password_problem(pw)
    if prob:
        return _json(h, 400, {"ok": False, "error": prob})
    with _LOCK:
        if password_state()[0] != "none":
            return _json(h, 409, {"ok": False, "error": "이미 비밀번호가 있어요 — 로그인해 주세요"})
        rec = set_password(pw)
        revoke(None)
        tok = new_session(rec)
        drop_setup_code()
    log.info("웹 로그인 비밀번호 설정(첫 실행)")
    return _json(h, 200, {"ok": True}, (_set_cookie(h, tok, S.session_days * 86400),))


def _session_post(h, onboarding, path, sess, tok):
    if not _post_ok(h, onboarding, csrf_tok=tok):
        return True
    clear = _set_cookie(h, "", 0)
    if path == "/api/logout":
        revoke(sess["tid"])
        log.info("로그아웃")
        return _json(h, 200, {"ok": True}, (clear, ("Clear-Site-Data", '"cache"')))
    if path == "/api/auth/logout_all":
        n = revoke(None)
        log.info("모든 기기 로그아웃(%d개 세션)", n)
        return _json(h, 200, {"ok": True, "revoked": n}, (clear, ("Clear-Site-Data", '"cache"')))
    b = bucket_of(h)
    if _limited(h, b, direct_loopback(h)):
        return True
    body = _read_json(h)
    if body is None:
        return _json(h, 400, {"ok": False, "error": "본문 형식 오류(JSON 객체, 4KB 이하)"})
    cur, new = body.get("current"), body.get("new")
    st, rec = password_state()
    if st != "set":
        return _json(h, 503, {"ok": False, "error": "인증 파일을 읽지 못했어요 — 서버에서 python3 tools/reset_password.py"})
    if not isinstance(cur, str) or not cur:
        return _json(h, 400, {"ok": False, "error": "지금 비밀번호를 넣어 주세요"})
    prob = password_problem(new)
    if prob:
        return _json(h, 400, {"ok": False, "error": prob})
    good, done = _verify_limited(h, b, cur, rec, "비밀번호 변경")
    if done:
        return True
    if not good:
        return _json(h, 403, {"ok": False, "error": "지금 비밀번호가 맞지 않아요", "left": max(0, LIM.left(b))})
    if hmac.compare_digest(_norm(cur).encode(), _norm(new).encode()):
        return _json(h, 400, {"ok": False, "error": "지금과 다른 비밀번호로 바꿔 주세요"})
    with _LOCK:
        if check_session(tok) is None:
            return _json(h, 409, {"ok": False, "error": "비밀번호가 방금 바뀌었어요 — 새로고침 후 다시 해 주세요"})
        try:
            nrec = set_password(new, expected=rec)
        except AuthChanged:
            return _json(h, 409, {"ok": False, "error": "비밀번호가 방금 바뀌었어요 — 새로고침 후 다시 해 주세요"})
        n = revoke(None)
        ntok = new_session(nrec)
    log.info("웹 로그인 비밀번호 변경 — 다른 세션 %d개 로그아웃 · 이 기기 새 세션", max(0, n - 1))
    return _json(h, 200, {"ok": True, "revoked": max(0, n - 1), "csrf": _sess_csrf(ntok)},
                 (_set_cookie(h, ntok, S.session_days * 86400),))


def _deny(h, method, path, query, had_cookie):
    st = password_state()[0]
    setup = st == "none"
    extra = [("X-TJ-Login", "setup" if setup else "required")]
    if had_cookie:
        extra.append(_set_cookie(h, "", 0))
    if method != "GET" or path.startswith("/api/") or not _is_page(path):
        if method == "GET" and not path.startswith("/api/"):
            h._send_bytes(401, b"login required", None, "text/plain; charset=utf-8", extra=tuple(extra))
            return True
        body = {"ok": False, "error": "login required", "setup": setup}
        if setup:
            body["hint"] = "비밀번호를 먼저 만드세요 — 이 컴퓨터에서 /login"
        return _json(h, 401, body, extra)
    nxt = safe_next(path + ("?" + query if query else ""))
    loc = "/login" + ("?next=" + urllib.parse.quote(nxt, safe="/") if nxt != "/" else "")
    h._send_bytes(302, b"", None, "text/plain; charset=utf-8", extra=tuple(extra) + (("Location", loc),))
    return True


def _off(h, method, path, query) -> bool:
    if method != "GET":
        return False
    if path == "/api/auth/status":
        import onboarding
        if not onboarding.guard(h, "GET"):
            return True
        return _json(h, 200, {"ok": True, "enabled": False, "demo": bool(onboarding.DEMO)})
    if path == "/login":
        import onboarding
        if not onboarding.guard(h, "GET"):
            return True
        h._send_bytes(302, b"", None, "text/plain; charset=utf-8", extra=(("Location", "/"),))
        return True
    return False


def _refuse_proxied(h) -> bool:
    body = {"ok": False, "error": "proxy requires login",
            "hint": "리버스 프록시·터널로 열려면 config.json 의 web.login 을 켜고(enabled true 또는 키 삭제) tj-web 을 다시 시작하세요"}
    h.close_connection = True
    _json(h, 403, body)
    return True


def handle(h, method: str, path: str, query: str = "") -> bool:
    import onboarding
    if not S.enabled and not onboarding.DEMO and proxied(h):
        try:
            return _refuse_proxied(h)
        except Exception:
            return True
    if not S.enabled or onboarding.DEMO:
        try:
            return _off(h, method, path, query)
        except Exception as e:
            log.warning("로그인 상태 조회 오류: %s", type(e).__name__)
            return False
    try:
        return _handle(h, onboarding, method, path, query)
    except Exception as e:
        log.warning("로그인 게이트 오류: %s", type(e).__name__)
        try:
            _json(h, 503, {"ok": False, "error": "로그인 확인 중 오류 — 잠시 뒤 다시"})
        except Exception:
            pass
        return True


def _handle(h, onboarding, method, path, query):
    if not onboarding.guard(h, method):
        return True
    if not os.path.exists(INTERNAL_PATH):
        internal_token(create=True)
    if method == "GET":
        if path == "/login":
            sess, _t, _h = session_of(h)
            if sess is not None:
                nx = safe_next(urllib.parse.parse_qs(query).get("next", ["/"])[0])
                h._send_bytes(302, b"", None, "text/plain; charset=utf-8", extra=(("Location", nx),))
                return True
            return _file(h, "login.html", "text/html; charset=utf-8")
        if path == "/v2/login.js":
            return _file(h, "login.js", "application/javascript; charset=utf-8")
        if path == "/api/auth/status":
            return _status(h)
        if _internal_ok(h):
            return False
    elif method == "POST":
        if path == "/api/login":
            return _login(h, onboarding)
        if path == "/api/auth/setup":
            return _setup(h, onboarding)
    sess, tok, had = session_of(h)
    if sess is None:
        return _deny(h, method, path, query, had)
    if method == "POST" and path in ("/api/logout", "/api/auth/password", "/api/auth/logout_all"):
        return _session_post(h, onboarding, path, sess, tok)
    return False

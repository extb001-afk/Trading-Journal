from __future__ import annotations

import hashlib
import hmac
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

import paths
import csrf_gate
import fsio
import login_device
import login_limits
import reqclass
import settings_store as ss

log = logging.getLogger("tj-web")

AUTH_PATH = paths.state("auth.json")
SESS_PATH = paths.state("auth_sessions.json")
INTERNAL_PATH = paths.state("auth_internal_token")
DEV_PATH = paths.state("auth_devices.json")
SETUP_CODE_PATH = paths.state("auth_setup_code")
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
PRE_AUTH_BODY_MIN_SEC, PRE_AUTH_BODY_RATE = 10.0, 4096
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{43}")
_PUB_FONT_RE = re.compile(r"/v2/fonts/(?:plex\.css|[a-z]{1,16}-[0-9]{3}-[0-9a-f]{12}\.woff2)")
LOGIN_CSP = ("default-src 'self'; style-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; require-trusted-types-for 'script'; trusted-types 'none'",
             None)
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
    def __init__(self, raw, proxy: bool = False):
        r = raw if isinstance(raw, dict) else {}
        self.enabled = raw is not False and r.get("enabled") is not False
        self.session_days = _int(r.get("session_days"), 30, 1, 365)
        self.idle_days = min(_int(r.get("idle_days"), 7, 1, 365), self.session_days)
        self.secure = r.get("secure_cookie") is True or (proxy and r.get("secure_cookie") is not False)
        self.allow_lan = r.get("allow_lan_without_password") is True


S = Settings({"enabled": False})
_LOCK = threading.RLock()
_AUTH = {"sig": False, "rec": None, "err": None}
_SESS = {"sig": False, "d": {}, "saved": 0.0, "g": None}
DEVICES = login_device.DeviceStore(DEV_PATH)


def init(cfg: dict, lan: str | None = None) -> Settings:
    global S  # noqa: PLW0603
    w = (cfg or {}).get("web") if isinstance((cfg or {}).get("web"), dict) else {}
    S = Settings(w.get("login", None), proxy=w.get("behind_proxy") is True)
    lan = lan or ("테일넷" if w.get("bind") == "tailscale" else None)
    if lan and not S.enabled and not S.allow_lan:
        log.error("★기동 거부: 웹 로그인이 꺼져 있는데 %s 에도 열도록(bind) 돼 있어요 — 같은 네트워크 누구나 자산 전부를 볼 수 있어요★ 고치는 법: "
                  "config.json web.login.enabled 를 true 로(또는 키 삭제) · 또는 web.bind 를 \"loopback\" 으로. 그래도 비밀번호 없이 열려면 "
                  "web.login 에 allow_lan_without_password 키를 true 로 적으세요(권장 안 함). 그다음 tj-web 다시 시작", lan)
        raise SystemExit(2)
    reqclass.BEHIND_PROXY = w.get("behind_proxy") is True
    if reqclass.BEHIND_PROXY:
        log.info("web.behind_proxy = true — 모든 요청을 리버스 프록시 경유로 취급(첫 비밀번호는 tools/reset_password.py)")
        if not S.secure:
            log.error("web.behind_proxy = true 인데 web.login.secure_cookie = false — 로그인 쿠키에 Secure 가 안 붙어요(평문으로 오갈 수 있음) · HTTPS 프록시면 그 키를 지우세요")
    if S.enabled:
        paths.ensure_dirs()
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
    fsio.atomic_write_text(path, json.dumps(obj, separators=(",", ":")), mode=0o600)


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
    try:
        ss.rotate_csrf_token()
    except Exception as e:   # noqa: BLE001 [optional]
        log.warning("CSRF 토큰 교체 실패(비밀번호는 저장됨): %s", type(e).__name__)
    return rec


def _sessions_locked() -> dict:
    sig = _sig(SESS_PATH)
    if sig != _SESS["sig"]:
        d, g = {}, None
        if sig is not None:
            _tighten(SESS_PATH)
            try:
                with open(SESS_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                d = {k: v for k, v in raw.items() if isinstance(k, str) and len(k) == 64 and isinstance(v, dict)
                     and all(type(v.get(x)) is int for x in ("c", "s", "e"))} if isinstance(raw, dict) else {}
                g = raw.get("_g") if isinstance(raw, dict) and isinstance(raw.get("_g"), str) and len(raw["_g"]) >= 16 else None
            except (OSError, ValueError):
                log.warning("state/auth_sessions.json 을 읽지 못함 — 세션 전부 무효(다시 로그인)")
                d = {}
        _SESS.update(sig=sig, d=d, g=g)
    return _SESS["d"]


def _save_sessions_locked():
    _SESS["g"] = _SESS["g"] or secrets.token_urlsafe(16)
    _write(SESS_PATH, dict(_SESS["d"], _g=_SESS["g"]))
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
    t = secrets.token_urlsafe(32)
    if not fsio.create_exclusive(INTERNAL_PATH, (t + "\n").encode("ascii"), mode=0o600, fsync=False, dir_fsync=False):
        _tighten(INTERNAL_PATH)
        return internal_token(False)
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
    c = "".join(secrets.choice(_SC_ALPHA) for _ in range(16))
    try:
        made = fsio.create_exclusive(SETUP_CODE_PATH, ("-".join(c[i:i + 4] for i in range(0, 16, 4)) + "\n").encode("ascii"), mode=0o600,
                                     fsync=False, dir_fsync=False)
    except fsio.CreateError:
        return ""
    if not made:
        return _setup_code_locked(False)
    log.info("첫 비밀번호 설정 코드를 만들었어요 — 이 컴퓨터의 %s 파일(첫 비밀번호 화면에 넣기 · 쓰고 나면 지워짐)", SETUP_CODE_REL)
    return c


def drop_setup_code() -> None:
    try:
        os.unlink(SETUP_CODE_PATH)
    except OSError:
        pass


def rotate_internal_token() -> str:
    t = secrets.token_urlsafe(32)
    fsio.atomic_write_text(INTERNAL_PATH, t + "\n", mode=0o600)
    return t


def internal_headers() -> dict:
    t = internal_token(False)
    return {INTERNAL_HDR: t} if t else {}


def is_https(h) -> bool:
    return bool(S.secure or reqclass.proxied_https(h))


def _cookies(h, name=COOKIE):
    out = []
    for raw in h.headers.get_all("Cookie") or []:
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                out.append(v.strip().strip('"'))
    return out


def cookie_name(h: object, base: str = COOKIE) -> str:
    return "__Host-" + base if is_https(h) else base


def session_of(h):
    cs = _cookies(h, cookie_name(h))
    for c in cs:
        s = check_session(c)
        if s is not None:
            return s, c, True
    return None, None, bool(cs or _cookies(h))


def _set_cookie(h, tok, max_age, name=None):
    name = name or cookie_name(h)
    return ("Set-Cookie", f"{name}={tok}; Path=/; Max-Age={int(max_age)}; HttpOnly; SameSite=Strict" + ("; Secure" if is_https(h) or name.startswith("__Host-") else ""))


def _cookies_out(h, tok=None):
    if tok:
        return (_set_cookie(h, tok, S.session_days * 86400),) + ((_set_cookie(h, "", 0, COOKIE),) if is_https(h) else ())
    return tuple(_set_cookie(h, "", 0, n) for n in (COOKIE, "__Host-" + COOKIE))


def _device_of(h, touch=False):
    toks = _cookies(h, cookie_name(h, login_device.COOKIE))[:4]
    if not toks:
        return None
    with _LOCK:
        st, rec = password_state()
        _sessions_locked()
        if st != "set":
            return None
        pg, sg = _pg(rec), _SESS["g"]
        tid = next((t for t in (DEVICES.check(c, pg, sg) for c in toks) if t), None)
        if tid and touch:
            DEVICES.touch(tid, pg, sg)
        return tid


def _dev_cookie(h, rec, keep=None) -> tuple:
    if keep and DEVICES.touch(keep, _pg(rec), _SESS["g"]):
        return ()
    try:
        dtok, age = DEVICES.issue(_pg(rec), _SESS["g"])
    except (OSError, ValueError) as e:
        log.warning("기기 등록 실패(로그인은 됨): %s", type(e).__name__)
        return ()
    old = (_set_cookie(h, "", 0, login_device.COOKIE),) if is_https(h) else ()
    return (_set_cookie(h, dtok, age, cookie_name(h, login_device.COOKIE)),) + old


def _internal_ok(h) -> bool:
    v = h.headers.get(INTERNAL_HDR)
    if not v:
        return False
    if not reqclass.direct_loopback(h):
        if not (reqclass.BEHIND_PROXY and reqclass.loopback_unmarked(h)):
            return False
    t = internal_token(False)
    return bool(t) and hmac.compare_digest(v.encode("utf-8", "replace"), t.encode("ascii"))


def _json(h, code, obj, extra=()):
    data = json.dumps(obj, ensure_ascii=False).encode()
    h._send_bytes(code, data, None, "application/json; charset=utf-8", extra=tuple(extra))
    return True


def _file(h, name, ctype):
    with open(os.path.join(V2_DIR, name), "rb") as f:
        raw = f.read()
    csp = zip(("Content-Security-Policy", "Content-Security-Policy-Report-Only"), LOGIN_CSP) if ctype.startswith("text/html") else ()
    extra = (("Referrer-Policy", "no-referrer"),) + tuple((name, value) for name, value in csp if value)
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


def _read_json(h, limit=BODY_MAX, pre_auth=False):
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        return None
    if n < 0 or n > limit:
        return None
    if n == 0:
        return {}
    h.connection.settimeout(10)
    rd = getattr(h, "tj_read_within", None) if pre_auth else None
    try:
        raw = rd(n, max(PRE_AUTH_BODY_MIN_SEC, n / PRE_AUTH_BODY_RATE)) if callable(rd) else h.rfile.read(n)
        d = json.loads(raw.decode("utf-8"))
    except (ValueError, OSError, RecursionError):
        return None
    return d if isinstance(d, dict) else None


def _post_ok(h, onboarding, need_csrf=False) -> bool:
    sfs = (h.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if not onboarding.origin_ok(h, required=True) or sfs not in ("", "same-origin"):
        _json(h, 403, {"ok": False, "error": "출처(Origin) 확인 실패 — 같은 화면에서만 요청할 수 있습니다"})
        return False
    if need_csrf and not csrf_gate.check(h):
        _json(h, 403, {"ok": False, "error": "CSRF 토큰 불일치 — 페이지를 새로고침하세요"})
        return False
    if not (h.headers.get("Content-Type") or "").lower().startswith("application/json"):
        _json(h, 415, {"ok": False, "error": "JSON 요청만 받습니다"})
        return False
    return True


def _sync_limiter() -> None:
    with _LOCK:
        sig = _auth_locked()["sig"]
        if getattr(login_limits.LIM, "gen", False) is not False and login_limits.LIM.gen != sig:
            login_limits.LIM.reset()
        login_limits.LIM.gen = sig


def _limit_ctx(h):
    tid = _device_of(h)
    return ("d:" + tid[:16], True, tid) if tid else (reqclass.bucket_of(h), reqclass.direct_loopback(h), None)


def _limited(h, b, direct) -> bool:
    _sync_limiter()
    w = login_limits.LIM.wait(b, direct)
    if not w:
        return False
    _json(h, 429, {"ok": False, "error": f"로그인 시도가 너무 많아요 — {login_limits.mins(w)} 뒤에 다시 해 주세요", "retryAfter": w},
          (("Retry-After", str(w)),))
    return True


def _verify_limited(h, ctx, pw, rec, label):
    b, direct, tid = ctx
    sem = login_limits.HASH_SEM_DEV if tid else login_limits.HASH_SEM
    if not sem.acquire(timeout=10):
        _json(h, 503, {"ok": False, "error": "잠시 바빠요 — 몇 초 뒤 다시 해 주세요"})
        return False, True
    try:
        if tid and _device_of(h) != tid:
            _json(h, 409, {"ok": False, "error": "기기 등록이 방금 바뀌었어요 — 다시 시도해 주세요"})
            return False, True
        if _limited(h, b, direct):
            return False, True
        good = verify_password(pw, rec)
    finally:
        sem.release()
    if good:
        login_limits.LIM.ok(b)
        return True, False
    dur = login_limits.LIM.fail(b, glob=tid is None)
    if dur:
        log.warning("%s 실패 반복 — %s 잠금 %s", label, b, login_limits.mins(dur))
        _json(h, 429, {"ok": False, "error": f"로그인 시도가 너무 많아요 — {login_limits.mins(dur)} 뒤에 다시 해 주세요", "retryAfter": dur},
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
        d["canSetup"] = reqclass.setup_allowed(h)
        if d["canSetup"]:
            setup_code(create=True)
            d["setupCodePath"] = SETUP_CODE_REL
    if sess is not None:
        d.update(csrf=_sess_csrf(tok), exp=sess["e"], sessions=session_count())
        _device_of(h, touch=True)
    else:
        w = login_limits.LIM.wait(*_limit_ctx(h)[:2])
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
    ctx = _limit_ctx(h)
    b = ctx[0]
    if _limited(h, b, ctx[1]):
        return True
    body = _read_json(h, pre_auth=True)
    if body is None:
        return _json(h, 400, {"ok": False, "error": "본문 형식 오류(JSON 객체, 4KB 이하)"})
    pw = body.get("password")
    if not isinstance(pw, str) or not pw:
        return _json(h, 400, {"ok": False, "error": "비밀번호를 넣어 주세요"})
    good, done = _verify_limited(h, ctx, pw, rec, "로그인")
    if done:
        return True
    if not good:
        return _json(h, 401, {"ok": False, "error": "비밀번호가 맞지 않아요", "left": max(0, login_limits.LIM.left(b))})
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
        dev = _dev_cookie(h, rec, ctx[2])
    log.info("로그인 성공(%s)", b)
    return _json(h, 200, {"ok": True}, _cookies_out(h, tok) + dev)


def _setup(h, onboarding):
    if not _post_ok(h, onboarding):
        return True
    st, _rec = password_state()
    if st != "none":
        return _json(h, 409, {"ok": False, "error": "이미 비밀번호가 있어요 — 로그인해 주세요" if st == "set"
                              else "인증 파일이 손상됐어요 — 서버에서 python3 tools/reset_password.py 로 다시 만드세요"})
    if not reqclass.setup_allowed(h):
        return _json(h, 403, {"ok": False, "error": "첫 비밀번호는 이 컴퓨터에서만 만들 수 있어요 — 서버에서 http://127.0.0.1:포트/login 으로 여세요"})
    body = _read_json(h, pre_auth=True)
    if body is None:
        return _json(h, 400, {"ok": False, "error": "본문 형식 오류(JSON 객체, 4KB 이하)"})
    want = setup_code(create=True)
    got = _sc_norm(body.get("code"))
    if not want or not got or not hmac.compare_digest(got.encode("ascii"), want.encode("ascii")):
        if got:
            log.info("첫 비밀번호 설정 코드 틀림(%s)", reqclass.bucket_of(h))
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
        dev = _dev_cookie(h, rec)
        drop_setup_code()
    log.info("웹 로그인 비밀번호 설정(첫 실행)")
    return _json(h, 200, {"ok": True}, _cookies_out(h, tok) + dev)


def _session_post(h, onboarding, path, sess, tok):
    if not _post_ok(h, onboarding, need_csrf=True):
        return True
    clear = _cookies_out(h)
    if path == "/api/logout":
        revoke(sess["tid"])
        log.info("로그아웃")
        return _json(h, 200, {"ok": True}, clear + (("Clear-Site-Data", '"cache"'),))
    if path == "/api/auth/logout_all":
        with _LOCK:
            nd = DEVICES.revoke_all(keep=_device_of(h))
            n = revoke(None)
        log.info("모든 기기 로그아웃(%d개 세션 · 등록 기기 %d개)", n, nd)
        return _json(h, 200, {"ok": True, "revoked": n}, clear + (("Clear-Site-Data", '"cache"'),))
    ctx = _limit_ctx(h)
    b = ctx[0]
    if _limited(h, b, ctx[1]):
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
    good, done = _verify_limited(h, ctx, cur, rec, "비밀번호 변경")
    if done:
        return True
    if not good:
        return _json(h, 403, {"ok": False, "error": "지금 비밀번호가 맞지 않아요", "left": max(0, login_limits.LIM.left(b))})
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
        dev = _dev_cookie(h, nrec)
    log.info("웹 로그인 비밀번호 변경 — 다른 세션 %d개 로그아웃 · 이 기기 새 세션", max(0, n - 1))
    return _json(h, 200, {"ok": True, "revoked": max(0, n - 1), "csrf": _sess_csrf(ntok)}, _cookies_out(h, ntok) + dev)


def _deny(h, method, path, query, had_cookie):
    st = password_state()[0]
    setup = st == "none"
    extra = [("X-TJ-Login", "setup" if setup else "required")]
    extra.extend(_cookies_out(h) if had_cookie else ())
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
    csrf_gate.begin(h)
    import onboarding
    if not S.enabled and not onboarding.DEMO and reqclass.proxied(h):
        try:
            return _refuse_proxied(h)
        except Exception:   # noqa: BLE001 [fallback]
            return True
    if not S.enabled or onboarding.DEMO:
        try:
            return _off(h, method, path, query)
        except Exception as e:   # noqa: BLE001 [fallback]
            log.warning("로그인 상태 조회 오류: %s", type(e).__name__)
            return False
    try:
        return _handle(h, onboarding, method, path, query)
    except Exception as e:   # noqa: BLE001 [boundary]
        log.warning("로그인 게이트 오류: %s", type(e).__name__)
        try:
            _json(h, 503, {"ok": False, "error": "로그인 확인 중 오류 — 잠시 뒤 다시"})
        except Exception:   # noqa: BLE001 [optional]
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
        if pub_file := {"/v2/login.js": ("login.js", "application/javascript; charset=utf-8"), "/v2/login.css": ("login.css", "text/css; charset=utf-8")}.get(path):
            return _file(h, *pub_file)
        if _PUB_FONT_RE.fullmatch(path):
            return False
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
    _device_of(h, touch=True)
    csrf_gate.use_session(h, _sess_csrf(tok))
    if method == "POST" and path in ("/api/logout", "/api/auth/password", "/api/auth/logout_all"):
        return _session_post(h, onboarding, path, sess, tok)
    return False

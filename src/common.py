"""Shared paths, configuration loading and small utilities."""
import json
import urllib.parse
import logging
import os
import sys
import tempfile

BASE_DIR = os.environ.get("TJ_BASE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(BASE_DIR, "state")
INBOX_DIR = os.path.join(STATE_DIR, "inbox")
CONFIG_PATH = os.environ.get("TJ_CONFIG", os.path.join(BASE_DIR, "config.json"))
DB_PATH = os.path.join(STATE_DIR, "ledger.db")
DEMO_ISOLATED = False
if os.environ.get("TJ_DEMO") == "1":
    STATE_DIR = os.environ.get("TJ_DEMO_STATE") or ""
    if not STATE_DIR:
        import atexit as _atexit9
        import shutil as _shutil9
        STATE_DIR = tempfile.mkdtemp(prefix="tj_demo_state_")
        _owner9 = os.getpid()
        _atexit9.register(lambda d=STATE_DIR: _shutil9.rmtree(d, ignore_errors=True) if os.getpid() == _owner9 else None)
    os.environ["TJ_DEMO_STATE"] = STATE_DIR
    INBOX_DIR = os.path.join(STATE_DIR, "inbox")
    DB_PATH = os.path.join(STATE_DIR, "ledger.db")
    DEMO_ISOLATED = True
    if not os.environ.get("TJ_CONFIG"):
        CONFIG_PATH = os.path.join(STATE_DIR, "config.json")
ENV_PATH = os.path.join(STATE_DIR if DEMO_ISOLATED else BASE_DIR, ".env")


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [" + name + "] %(message)s",
        stream=sys.stdout,
    )
    add_secret_filter()
    return logging.getLogger(name)


CPU_RESERVE_MIN = 4
BUILD_PROC_MODES = ("auto", "off", "fork")
_CPU_PLAN = None
_CPU_APPLIED = False


def parse_env_line(line: str):
    s = str(line or "").strip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    if s.startswith("export "):
        s = s[7:].lstrip()
    k, v = s.split("=", 1)
    k, v = k.strip(), v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    return (k, v) if k else None


def net_error_text(e) -> str:
    import socket as _so
    import ssl as _ssl
    import urllib.error as _ue
    r = getattr(e, "reason", None) if isinstance(e, _ue.URLError) else None
    x = r if isinstance(r, BaseException) else e
    if isinstance(e, _ue.HTTPError):
        return f"상대 서버가 거부했어요(HTTP {e.code}) — 키·권한·IP 허용 목록을 확인하세요"
    if isinstance(x, (_so.timeout, TimeoutError)) or "timed out" in str(x).lower():
        return "응답이 없어요(시간 초과) — 인터넷 연결·방화벽을 확인하고 잠시 뒤 다시 시도하세요"
    if isinstance(x, _so.gaierror):
        return "주소를 찾지 못했어요(DNS) — 인터넷 연결을 확인하세요"
    if isinstance(x, _ssl.SSLError) or "certificate" in str(x).lower():
        return "보안 연결(SSL)에 실패했어요 — 컴퓨터 시계가 맞는지, 회사·학교 프록시가 끼어 있지 않은지 확인하세요"
    if isinstance(x, ConnectionRefusedError):
        return "연결이 거부됐어요 — 방화벽·프록시 설정을 확인하세요"
    if isinstance(x, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "연결이 중간에 끊겼어요 — 잠시 뒤 다시 시도하세요"
    if isinstance(x, OSError):
        return "네트워크 오류로 연결하지 못했어요 — 인터넷 연결을 확인하세요"
    return "연결하지 못했어요 — 잠시 뒤 다시 시도하고, 계속되면 tj-web 로그를 확인하세요"


HTTP_BODY_MAX = 32 * 1024 * 1024
HTTP_ERR_BODY_MAX = 64 * 1024


class ResponseTooLarge(ValueError):
    pass


def read_capped(r, cap: int = None) -> bytes:
    cap = HTTP_BODY_MAX if cap is None else max(0, int(cap))
    n9 = cap + 1
    ln9 = getattr(r, "length", None)
    if isinstance(ln9, int) and not isinstance(ln9, bool) and ln9 >= 0:
        if ln9 > cap:
            raise ResponseTooLarge(f"응답 본문 {ln9:,}바이트가 상한 {cap:,}바이트를 넘음 — 이 요청 실패")
        n9 = ln9 + 1
    raw = r.read(n9) or b""
    if len(raw) > cap:
        raise ResponseTooLarge(f"응답 본문이 상한 {cap:,}바이트를 넘음 — 이 요청 실패")
    return raw


def read_env_file(path: str = None) -> dict:
    out = {}
    try:
        with open(path or ENV_PATH, "r", encoding="utf-8-sig") as f:
            for line in f:
                kv = parse_env_line(line)
                if kv:
                    out[kv[0]] = kv[1]
    except OSError:
        pass
    return out


def _env_file_value(key: str):
    if not os.path.exists(ENV_PATH):
        return None
    return read_env_file().get(key)


def build_proc_mode():
    for src, get in (("env", lambda: os.environ.get("TJ_BUILD_PROC")), (".env", lambda: _env_file_value("TJ_BUILD_PROC")),
                     ("config", lambda: _cfg_build_proc())):
        try:
            v = get()
        except Exception:
            v = None
        if v is not None and str(v).strip():
            return str(v).strip().lower(), src
    return "auto", "기본"


def _cfg_build_proc():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    v = d.get("build_proc") if isinstance(d, dict) else None
    return v if isinstance(v, str) else None


def cpu_plan() -> dict:
    global _CPU_PLAN
    if _CPU_PLAN is not None:
        return _CPU_PLAN
    mode, msrc = build_proc_mode()
    p = {"on": False, "core": None, "cores": os.cpu_count() or 1, "why": ""}
    bad = mode not in BUILD_PROC_MODES and mode not in ("0", "no", "false")
    if bad:
        mode = "auto"
    inh = str(os.environ.get("TJ_CPU_PLAN") or "")
    aff = None
    if hasattr(os, "sched_getaffinity"):
        try:
            aff = sorted(os.sched_getaffinity(0))
        except OSError:
            aff = None
    if mode in ("off", "0", "no", "false"):
        p["why"] = f"꺼짐(TJ_BUILD_PROC=off · {msrc}) — 웹 안에서 빌드"
    elif not hasattr(os, "fork"):
        p["why"] = "fork 없음 — 웹 안에서 빌드"
    elif mode == "fork":
        p.update(on=True, why=f"강제(TJ_BUILD_PROC=fork · {msrc})")
        if aff and len(aff) >= CPU_RESERVE_MIN:
            p.update(core=aff[-1], cores=len(aff))
    elif not sys.platform.startswith("linux") or aff is None:
        p["why"] = "리눅스 아님 — 웹 안에서 빌드(코어 지정 기능 없음)"
    elif inh.count("/") == 1 and inh.split("/")[0].isdigit() and inh.split("/")[1].isdigit():
        c9, n9 = (int(x) for x in inh.split("/"))
        p.update(on=True, core=c9, cores=n9, why=f"코어 {n9}개 — {c9}번 = 화면 계산 전용(물려받음)")
    elif len(aff) < 2:
        p.update(cores=len(aff), why="코어 1개 — 웹 안에서 빌드")
    elif len(aff) < CPU_RESERVE_MIN:
        p.update(on=True, cores=len(aff), why=f"코어 {len(aff)}개 — {CPU_RESERVE_MIN}개 미만이라 전용 코어 없이 빌드 자식만")
    else:
        p.update(on=True, core=aff[-1], cores=len(aff), why=f"코어 {len(aff)}개 — {aff[-1]}번 = 화면 계산 전용")
    if bad:
        p["why"] += " · 모르는 TJ_BUILD_PROC 값이라 auto 로"
    if p["on"] and p["core"] is not None and not inh:
        os.environ["TJ_CPU_PLAN"] = f"{p['core']}/{p['cores']}"
    _CPU_PLAN = p
    return p


SQLITE_MEMSTAT_WHY = [""]


def _sqlite_lib():
    import ctypes
    import ctypes.util
    import importlib.util
    try:
        spec = importlib.util.find_spec("_sqlite3")
        origin = getattr(spec, "origin", None) if spec is not None else None
    except (ImportError, ValueError):
        origin = None
    try:
        if origin == "built-in":
            lib = ctypes.CDLL(None)
            if hasattr(lib, "sqlite3_config"):
                return lib, "builtin"
        elif origin and os.path.isfile(origin):
            lib = ctypes.CDLL(origin)
            if hasattr(lib, "sqlite3_config"):
                return lib, "ext"
    except OSError:
        pass
    return ctypes.CDLL(ctypes.util.find_library("sqlite3") or "libsqlite3.so.0"), "name"


def _memstatus_apply(lib) -> object:
    import ctypes
    rc = lib.sqlite3_config(9, ctypes.c_int(0))
    if rc == 21 and "sqlite3" not in sys.modules and "_sqlite3" not in sys.modules:
        lib.sqlite3_shutdown()
        rc = lib.sqlite3_config(9, ctypes.c_int(0))
    if rc != 0:
        SQLITE_MEMSTAT_WHY[0] = f"설정 거부(코드 {rc} — 이미 초기화)"
        return False
    try:
        import sqlite3 as _s9
        c9 = _s9.connect(":memory:")
        try:
            c9.execute("CREATE TABLE t9 (x)")
            c9.executemany("INSERT INTO t9 VALUES (?)", [(i,) for i in range(200)])
            c9.execute("SELECT sum(x) FROM t9").fetchall()
            rc2 = lib.sqlite3_config(9, ctypes.c_int(0))
            fn9 = lib.sqlite3_memory_used
            fn9.restype = ctypes.c_int64
            used9 = int(fn9())
            lv9 = lib.sqlite3_libversion
            lv9.restype = ctypes.c_char_p
            ver9 = (lv9() or b"").decode("ascii", "replace")
        finally:
            c9.close()
    except Exception as e:
        SQLITE_MEMSTAT_WHY[0] = f"확인 불가({type(e).__name__})"
        return "unverified"
    if rc2 == 0:
        SQLITE_MEMSTAT_WHY[0] = "파이썬 sqlite3 는 다른 SQLite 사본을 씀(끈 것은 안 쓰는 사본)"
        return False
    if ver9 != _s9.sqlite_version:
        SQLITE_MEMSTAT_WHY[0] = f"버전이 다름(끈 것 {ver9[:16]} · 파이썬 {_s9.sqlite_version[:16]})"
        return False
    if used9 != 0:
        SQLITE_MEMSTAT_WHY[0] = "파이썬 쪽 통계가 여전히 셈(memory_used > 0)"
        return False
    SQLITE_MEMSTAT_WHY[0] = "파이썬 sqlite3 와 같은 라이브러리에서 확인"
    return True


def sqlite_memstatus_off():
    if not sys.platform.startswith("linux") or not cpu_plan().get("on"):
        return None
    try:
        lib, src9 = _sqlite_lib()
        r9 = _memstatus_apply(lib)
        if src9 == "name" and r9 is not False:
            SQLITE_MEMSTAT_WHY[0] += " · 이름으로 찾은 사본"
        return r9
    except (OSError, AttributeError, TypeError, ValueError) as e:
        SQLITE_MEMSTAT_WHY[0] = f"못 끔({type(e).__name__})"
        return False


def cpu_reserve_apply():
    global _CPU_APPLIED
    if _CPU_APPLIED:
        return
    _CPU_APPLIED = True
    try:
        c9 = cpu_plan().get("core")
        if c9 is None or not hasattr(os, "sched_setaffinity"):
            return
        cur = set(os.sched_getaffinity(0))
        rest = cur - {c9}
        if rest and rest != cur:
            os.sched_setaffinity(0, rest)
    except (OSError, ValueError, TypeError):
        pass


BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
              " Chrome/128.0.0.0 Safari/537.36")
BROWSER_UA_HOSTS = set()


def ua_for(url: str, default: str) -> str:
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        host = ""
    return BROWSER_UA if host and host.lower() in BROWSER_UA_HOSTS else default


DEFAULT_DISABLED_CHAINS = set()

DEFAULT_DISCOVERY = {"robinhood": "rpc", "arc": "rpc",
                     "base": "rpc"}

DEFAULT_NATIVE_SYMBOL = {"arc": "USDC"}


BS_BLOCKED = frozenset(("base", "arbitrum", "polygon"))


def bs_blocked(name: str, cc) -> bool:
    v = (cc or {}).get("discovery") if isinstance(cc, dict) else None
    return name in BS_BLOCKED and str(v or "").lower() != "explorer"


def chain_discovery(name: str, cc) -> str:
    v = (cc or {}).get("discovery") if isinstance(cc, dict) else None
    v = str(v or DEFAULT_DISCOVERY.get(name) or "explorer").lower()
    return "rpc" if v == "rpc" else "explorer"


def chain_enabled(name: str, cc) -> bool:
    if isinstance(cc, dict) and "enabled" in cc:
        return cc.get("enabled") is True
    return name not in DEFAULT_DISABLED_CHAINS


EXTRA_CHAINS = {
    "monad": ("Monad", "MON", 143, "0x3bd359c1119da7da1d913d1c4d2b7c461115433a"),
    "megaeth": ("MegaETH", "ETH", 4326, "0x4200000000000000000000000000000000000006"),
    "plasma": ("Plasma", "XPL", 9745, "0x6100e367285b01f48d07953803a2d8dca5d19873"),
    "xlayer": ("X Layer", "OKB", 196, "0xe538905cf8410324e03a5a23c1c177a474d59b2b"),
    "kaia": ("Kaia", "KAIA", 8217, "0x19aac5f612f524b754ca7e7c41cbfa2e981a4432"),
    "fraxtal": ("Fraxtal", "FRAX", 252, "0xfc00000000000000000000000000000000000002"),
    "bob": ("BOB", "ETH", 60808, "0x4200000000000000000000000000000000000006"),
    "story": ("Story", "IP", 1514, "0x1514000000000000000000000000000000000000"),
    "somnia": ("Somnia", "SOMI", 5031, "0x046ede9564a72571df6f5e44d0405360c0f4dcab"),
    "avalanche": ("Avalanche", "AVAX", 43114, "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7"),
    "stable": ("Stable", "USDT", 988, None),
    "abstract": ("Abstract", "ETH", 2741, "0x3439153eb7af838ad19d56e1571fbd09333c2809"),
}
NATIVE_MIRROR = {"arc": ("0x3600000000000000000000000000000000000000", 10 ** 12),
                 "stable": ("0x779ded0c9e1022225f8e0630b35a9b54be713736", 10 ** 12)}
ZK_STACK = {"zksync": ("0x000000000000000000000000000000000000800a", "0x0000000000000000000000000000000000008001"),
            "abstract": ("0x000000000000000000000000000000000000800a", "0x0000000000000000000000000000000000008001")}


_URL_ANY_RE = None


def redact_urls(msg) -> str:
    global _URL_ANY_RE
    import re as _re9
    import urllib.parse as _up9
    if msg is None:
        return msg
    if _URL_ANY_RE is None:
        _URL_ANY_RE = _re9.compile(r"(?i)(?:https?|wss?)://\S+")

    def host(m9):
        tok = m9.group(0)
        core = tok.rstrip(".,;:!?)]}'\"")
        tail = tok[len(core):]
        for t9 in (core, tok):
            try:
                h9 = _up9.urlsplit(t9).hostname
            except ValueError:
                h9 = None
            if h9:
                return h9 + (tail if t9 is core else "")
        return "(주소 숨김)" + tail
    return _URL_ANY_RE.sub(host, str(msg))


_SECRET_NAME_RE = None
_SECRET_CACHE = {"sig": None, "grams": frozenset(), "checked": 0.0}
_SECRET_MIN = 8


def _secret_name(name) -> bool:
    global _SECRET_NAME_RE
    import re as _re9
    if _SECRET_NAME_RE is None:
        _SECRET_NAME_RE = _re9.compile(r"(?i)(?:key|secret|token|pass|access|refresh|client_id|account)")
    return bool(_SECRET_NAME_RE.search(str(name or "")))


def _secret_values() -> list:
    import re as _re9
    vals = []
    envp = ENV_PATH
    try:
        with open(envp, "r", encoding="utf-8-sig") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if _secret_name(k):
                    vals.append(v)
                    ev = os.environ.get(k)
                    if ev:
                        vals.append(ev)
    except OSError:
        pass
    for k, v in os.environ.items():
        if (k.startswith("TJ_") or k.startswith("UPBIT_")) and _secret_name(k):
            vals.append(v)

    def walk(o, name=""):
        if isinstance(o, dict):
            for k9, v9 in o.items():
                if isinstance(k9, str) and "://" in k9:
                    walk(k9)
                walk(v9, str(k9))
        elif isinstance(o, list):
            for v9 in o:
                walk(v9, name)
        elif isinstance(o, str):
            if _re9.match(r"(?i)(?:https?|wss?)://", o):
                try:
                    sp = urllib.parse.urlsplit(o)
                except ValueError:
                    return
                parts = [p for p in sp.path.split("/") if p] + [q for _, q in urllib.parse.parse_qsl(sp.query)]
                if sp.password:
                    parts.append(sp.password)
                vals.extend(p for p in parts if len(p) >= 16 and _re9.fullmatch(r"[A-Za-z0-9_\-]+", p))
            elif _secret_name(name):
                vals.append(o)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            walk(json.load(f))
    except (OSError, ValueError):
        pass
    return [v for v in vals if isinstance(v, str) and len(v) >= _SECRET_MIN]


def _secret_grams() -> frozenset:
    import time as _t9
    c = _SECRET_CACHE
    now = _t9.time()
    if c["sig"] is not None and now - c["checked"] < 5:
        return c["grams"]
    sig = []
    for p in (ENV_PATH, CONFIG_PATH):
        try:
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((p, None, None))
    envsig = tuple(sorted((k, len(v)) for k, v in os.environ.items() if k.startswith(("TJ_", "UPBIT_"))))
    sig = (tuple(sig), envsig)
    c["checked"] = now
    if sig != c["sig"]:
        grams = set()
        for v in _secret_values():
            for i in range(len(v) - _SECRET_MIN + 1):
                g = v[i:i + _SECRET_MIN]
                if not g.isdigit():
                    grams.add(g)
        c["sig"], c["grams"] = sig, frozenset(grams)
    return c["grams"]


_KV_SECRET_RE = None
_ORIGIN_RE = None
_LONG_RE = None


def redact_secret_text(text, generic: bool = True, extra=()) -> str:
    global _KV_SECRET_RE, _ORIGIN_RE, _LONG_RE
    import re as _re9
    if text is None:
        return text
    try:
        s = str(text)
        if _KV_SECRET_RE is None:
            names = (r"api[_\-]?key|apikey|access[_\-]?key|secret[_\-]?key|secret|passphrase|password|signature|"
                     r"(?:access|auth|refresh|api|bot)[_\-]?token|x-bapi-api-key|x-mbx-apikey|ok-access-key|kc-api-key")
            _KV_SECRET_RE = (
                _re9.compile(r"(?i)((?:" + names + r"|sign|token)[\"']?\s*[=:]\s*[\"']?)([^\s&,;\"'\]\)}]+)"),
                _re9.compile(r"(?i)((?:" + names + r")[\"']?\s*[=:]\s*[\"']?)([^\s&,;\"'\]\)}]+)"))
            _ORIGIN_RE = _re9.compile(r"(?i)(origin_string)\s*[\[\(:=]?\s*[^\]\)\n]*[\]\)]?")
            _LONG_RE = _re9.compile(r"(?<![0-9A-Za-z+/=_\-])(?!0x[0-9a-fA-F]+(?![0-9A-Za-z+/=_\-]))[0-9A-Za-z+/=_\-]{24,}")
        s = _ORIGIN_RE.sub(lambda m: m.group(1) + "[***]", s)
        s = _KV_SECRET_RE[0 if generic else 1].sub(lambda m: m.group(1) + "***", s)
        grams = _secret_grams()
        xg = set()
        for v in extra or ():
            v = str(v or "")
            if len(v) >= _SECRET_MIN:
                xg.update(v[i:i + _SECRET_MIN] for i in range(len(v) - _SECRET_MIN + 1))
        if grams or xg:
            hit = [False] * len(s)
            for i in range(len(s) - _SECRET_MIN + 1):
                g = s[i:i + _SECRET_MIN]
                if g in grams or g in xg:
                    for j in range(i, i + _SECRET_MIN):
                        hit[j] = True
            if any(hit):
                out, i = [], 0
                while i < len(s):
                    if hit[i]:
                        while i < len(s) and hit[i]:
                            i += 1
                        out.append("***")
                    else:
                        out.append(s[i])
                        i += 1
                s = "".join(out)
        if generic:
            s = redact_urls(s)
            s = _LONG_RE.sub("***", s)
        return s
    except Exception:
        return "(오류 문구 숨김)"


class SecretLogFilter(logging.Filter):

    def filter(self, record):
        try:
            msg = record.getMessage()
            red = redact_secret_text(msg, generic=False)
            if red != msg:
                record.msg, record.args = red, None
            if record.exc_info and not getattr(record, "exc_text", None):
                record.exc_text = redact_secret_text(logging.Formatter().formatException(record.exc_info), generic=False)
        except Exception:
            record.msg, record.args = "(로그 문구 숨김 — 가리기 실패)", None
        return True


SECRET_FIELD_KEYS = frozenset({"wd_err", "fills_err", "err", "error", "errors", "last_error", "lastError", "msg", "note",
                               "collector_error", "partial_sample", "detail", "err_raw", "stop", "hist", "message",
                               "text", "resolved_detail", "why", "bind_err", "files_err", "decisions_err"})


def safe_err(x) -> str:
    return redact_secret_text(x if isinstance(x, str) else str(x))


def scrub_secrets(obj, keys=SECRET_FIELD_KEYS, _under=False):
    n = 0
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k], c = scrub_secrets(v, keys, _under or keys is None or k in keys)
            n += c
        return out, n
    if isinstance(obj, list):
        out = []
        for v in obj:
            v2, c = scrub_secrets(v, keys, _under)
            out.append(v2)
            n += c
        return out, n
    if isinstance(obj, str) and (_under or keys is None):
        s2 = redact_urls(redact_secret_text(obj, generic=False))
        return s2, int(s2 != obj)
    return obj, 0


def scrub_secret_file(path: str, keys=SECRET_FIELD_KEYS) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0
    d2, n = scrub_secrets(d, keys)
    if n:
        try:
            atomic_write_json(path, d2)
        except OSError:
            return 0
    return n


def add_secret_filter(handlers=None) -> None:
    for h in (handlers if handlers is not None else logging.getLogger().handlers):
        if not any(isinstance(f, SecretLogFilter) for f in h.filters):
            h.addFilter(SecretLogFilter())


def fill_chain_table(tbl: dict, col: int = 0) -> dict:
    for k, v in EXTRA_CHAINS.items():
        tbl.setdefault(k, str(v[col]) if col == 2 else v[col])
    try:
        import chainsweep as _cs9
        idx9 = {0: 0, 1: 2, 2: 1}.get(col)
        for k, v in _cs9.SWEEP_CHAINS.items():
            if idx9 is not None and k not in tbl:
                tbl[k] = str(v[idx9]) if col == 2 else v[idx9]
    except Exception:
        pass
    return tbl


ACTIVITY_GATE_PATH = os.path.join(STATE_DIR, "chain_activity.json")
BACKFILL_SPEED_PATH = os.path.join(STATE_DIR, "chain_backfill_speed.json")


QUOTA_STATE_DIR = None


def quota_dir() -> str:
    return QUOTA_STATE_DIR or STATE_DIR


def rebase_state(state_dir: str, db_path: str = None) -> None:
    global STATE_DIR, INBOX_DIR, DB_PATH, ACTIVITY_GATE_PATH, BACKFILL_SPEED_PATH
    STATE_DIR = state_dir
    INBOX_DIR = os.path.join(state_dir, "inbox")
    DB_PATH = db_path or os.path.join(state_dir, "ledger.db")
    ACTIVITY_GATE_PATH = os.path.join(state_dir, "chain_activity.json")
    BACKFILL_SPEED_PATH = os.path.join(state_dir, "chain_backfill_speed.json")


def _registered_evm(cfg: dict):
    labels = {}
    for w in cfg.get("wallets") or []:
        if w.get("type", "evm") in ("evm", "bsc_rpc"):
            a = str(w.get("address") or "").lower()
            if a.startswith("0x") and len(a) == 42 and a not in labels:
                labels[a] = w.get("label") or ""
    return labels


def gate_decisions(cfg: dict, gate: dict = None, speed: dict = None) -> list:
    gate = read_json(ACTIVITY_GATE_PATH, {}) if gate is None else gate
    speed = read_json(BACKFILL_SPEED_PATH, {}) if speed is None else speed
    labels = _registered_evm(cfg)
    chains = cfg.get("chains") or {}
    explicit = {(w.get("chain"), str(w.get("address") or "").lower()) for w in cfg.get("wallets") or []
                if w.get("type", "evm") == "evm"}
    configured = {c for c, cc in chains.items() if isinstance(cc, dict) and not cc.get("_auto")}
    out = []
    for key, ent in sorted(((gate or {}).get("pairs") or {}).items()):
        if not isinstance(ent, dict) or not ent.get("active") or ":" not in key:
            continue
        c, a = key.split(":", 1)
        a = a.lower()
        if c == "bsc" or a not in labels or (c, a) in explicit:
            continue
        since = ent.get("since_block")
        d = {"chain": c, "addr": a, "label": labels[a], "since": since, "since_state": ent.get("since_state"),
             "ok": False, "reason": "", "block": None}
        cc = chains.get(c)
        if isinstance(cc, dict) and "enabled" in cc and cc.get("enabled") is not True:
            d["reason"] = "설정에서 끈 체인"
        elif c in configured:
            if since is None:
                d["reason"] = "이미 이력이 있는 지갑 — 자동으로는 안 켜요 · 설정 › 지갑 추가에서 같은 주소에 이 체인을 고르면 등록"
            else:
                d["ok"], d["reason"] = True, "새 활동(추적 체인)"
        else:
            try:
                import chaincatalog
                blk, why = chaincatalog.block_for(c, since is not None, ((speed or {}).get("chains") or {}).get(c))
            except ImportError:
                blk, why = None, "카탈로그 없음"
            d["block"], d["ok"], d["reason"] = blk, blk is not None, why
        out.append(d)
    return out


def apply_activity_gate(cfg: dict) -> list:
    sw = cfg.get("chain_sweep")
    if not isinstance(sw, dict) or sw.get("auto_enable") is not True:
        return []
    added = []
    chains = cfg.setdefault("chains", {})
    for d in gate_decisions(cfg):
        if not d["ok"]:
            continue
        c = d["chain"]
        if c not in chains and d["block"]:
            chains[c] = d["block"]
            try:
                import chaincatalog
                rt9 = chaincatalog.recon_tokens_for(cfg, c)
            except ImportError:
                rt9 = {}
            if rt9:
                chains[c]["recon_tokens"] = dict(chains[c].get("recon_tokens") or {}, **rt9)
            try:
                import chaincatalog
                sym, wr = chaincatalog.native_of(c)
            except ImportError:
                sym, wr = None, None
            if sym:
                cfg.setdefault("native_symbol", {}).setdefault(c, sym)
            if wr:
                cfg.setdefault("wrapped_native", {}).setdefault(c, wr)
        if c not in chains:
            continue
        row = {"type": "evm", "chain": c, "address": d["addr"], "label": d["label"], "_auto": "activity"}
        if d["since"] is not None:
            row["since_block"] = int(d["since"])
            if isinstance(d.get("since_state"), list) and len(d["since_state"]) == 2:
                row["since_state"] = [int(d["since_state"][0]), str(d["since_state"][1])]
        cfg.setdefault("wallets", []).append(row)
        added.append((c, d["addr"]))
    if added:
        cfg["_auto_pairs"] = sorted(f"{c}:{a}" for c, a in added)
    off9 = {n for n, cc in chains.items() if isinstance(cc, dict) and not chain_enabled(n, cc)}
    if off9:
        for d in gate_decisions(_as_enabled(cfg)):
            if d["ok"] and d["chain"] in off9:
                _keep_disabled_pair(cfg, d)
    return added


def _as_enabled(cfg: dict) -> dict:
    c2 = dict(cfg)
    ch = dict(cfg.get("chains") or {})
    for n, cc in list(ch.items()):
        if isinstance(cc, dict) and not chain_enabled(n, cc):
            if auto_off_block(cc):
                ch.pop(n)
            else:
                ch[n] = {k: v for k, v in cc.items() if k not in ("enabled", "_chainoff")}
    c2["chains"] = ch
    return c2


def auto_off_block(cc) -> bool:
    if not isinstance(cc, dict):
        return False
    mk = cc.get("_chainoff") if isinstance(cc.get("_chainoff"), dict) else {}
    if mk.get("created"):
        return True
    return not mk and {k for k in cc if not str(k).startswith("_")} == {"enabled"}


def history_wallets(cfg: dict) -> list:
    return list((cfg or {}).get("wallets") or []) + [w for w in ((cfg or {}).get("_disabled_wallets") or []) if isinstance(w, dict)]


def _keep_disabled_pair(cfg: dict, d: dict) -> None:
    c = d["chain"]
    cfg.setdefault("_disabled_wallets", []).append({"type": "evm", "chain": c, "address": d["addr"], "label": d.get("label") or "", "_auto": "activity"})
    try:
        import chaincatalog
        sym, wr = chaincatalog.native_of(c)
    except ImportError:
        sym, wr = None, None
    if sym:
        cfg.setdefault("native_symbol", {}).setdefault(c, sym)
    if wr:
        cfg.setdefault("wrapped_native", {}).setdefault(c, wr)


def _drop_disabled_chains(cfg: dict) -> None:
    chains = cfg.get("chains") or {}
    off = sorted(n for n, cc in chains.items() if not chain_enabled(n, cc))
    if not off:
        return
    for n in off:
        chains.pop(n, None)
    keep = []
    for w in (cfg.get("wallets") or []):
        if w.get("type", "evm") == "evm" and w.get("chain") in off:
            cfg.setdefault("_disabled_wallets", []).append(dict(w))
        else:
            keep.append(w)
    cfg["wallets"] = keep
    cfg["_disabled_chains"] = off
    logging.getLogger("tj").info("비활성 체인(설정 제외): %s — 켜려면 chains.<name>.enabled=true", ", ".join(off))


_CFG_LOADED = [False]


def _config_fail(msg: str, exc=None):
    if _CFG_LOADED[0]:
        if exc is not None:
            raise exc
        raise SystemExit(msg)
    logging.getLogger("tj").critical("★%s — 고친 뒤 저절로 다시 떠요(pm2)★", msg)
    if os.environ.get("pm_id") is not None:
        try:
            wait = float(os.environ.get("TJ_CONFIG_FAIL_WAIT") or 45)
        except ValueError:
            wait = 45.0
        import time as _t
        _t.sleep(max(0.0, min(wait, 600.0)))
    raise SystemExit(msg)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        _config_fail(f"설정 파일 형식 오류: {os.path.basename(CONFIG_PATH)} {e.lineno}줄 {e.colno}칸 — {e.msg}", e)
    if not isinstance(cfg, dict):
        _config_fail(f"설정 파일이 JSON 객체가 아님: {os.path.basename(CONFIG_PATH)}")
    for key in ("chains", "wallets"):
        if key not in cfg:
            _config_fail(f"config.json 에 필수 키 없음: {key}")
    try:
        apply_activity_gate(cfg)
    except (Exception, SystemExit) as e:
        logging.getLogger("tj").warning("활동 게이트 적용 실패(게이트 없이 계속): %s", e)
    _drop_disabled_chains(cfg)
    ns9 = cfg.get("native_symbol")
    if not isinstance(ns9, dict):
        ns9 = cfg["native_symbol"] = {}
    _book9 = set(cfg.get("chains") or {}) | set(cfg.get("_disabled_chains") or [])
    for _name, _sym in DEFAULT_NATIVE_SYMBOL.items():
        if _name in _book9:
            ns9.setdefault(_name, _sym)
    BROWSER_UA_HOSTS.clear()
    for _name, _cc in (cfg.get("chains") or {}).items():
        if isinstance(_cc, dict) and _cc.get("browser_ua") and _cc.get("blockscout"):
            _h = urllib.parse.urlsplit(str(_cc["blockscout"])).hostname
            if _h:
                BROWSER_UA_HOSTS.add(_h.lower())
    for _name, _meta in EXTRA_CHAINS.items():
        if _name in _book9:
            if not isinstance(cfg.get("native_symbol"), dict):
                cfg["native_symbol"] = {}
            if not isinstance(cfg.get("wrapped_native"), dict):
                cfg["wrapped_native"] = {}
            cfg["native_symbol"].setdefault(_name, _meta[1])
            if _meta[3]:
                cfg["wrapped_native"].setdefault(_name, _meta[3])
    _CFG_LOADED[0] = True
    try:
        import nodekeys
        nodekeys.apply(cfg)
    except Exception as e:
        logging.getLogger("tj").warning("노드 키 적용 실패(종전 설정으로 계속): %s", type(e).__name__)
    return cfg


EXF_POLL_DEFAULT = 600
UPBIT_POLL_DEFAULT = 60


def _poll_cfg(cfg, sect: str, dflt: int, lo: int, hi: int) -> int:
    try:
        v = float(((cfg or {}).get(sect) or {}).get("poll_sec"))
    except (TypeError, ValueError, AttributeError):
        return dflt
    if v != v or v <= 0:
        return dflt
    return int(min(hi, max(lo, v)))


def exf_poll_sec(cfg) -> int:
    return _poll_cfg(cfg, "exf", EXF_POLL_DEFAULT, 60, 6 * 3600)


def upbit_poll_sec(cfg) -> int:
    return _poll_cfg(cfg, "upbit", UPBIT_POLL_DEFAULT, 10, 3600)


def exf_fresh_sec(cfg) -> int:
    return max(1800, 3 * exf_poll_sec(cfg))


def upbit_fresh_sec(cfg) -> int:
    return max(600, 4 * upbit_poll_sec(cfg))


def ensure_dirs() -> None:
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    os.makedirs(INBOX_DIR, mode=0o700, exist_ok=True)


def sqlite_ro_uri(path: str, immutable: bool = False) -> str:
    q = urllib.parse.quote(os.fspath(path), safe="/:\\")
    return "file:" + q + "?mode=ro" + ("&immutable=1" if immutable else "")


def tighten_config_mode(path: str = None) -> bool:
    p = path or CONFIG_PATH
    try:
        st = os.stat(p)
        if (st.st_mode & 0o170000) != 0o100000 or not (st.st_mode & 0o077) or (hasattr(os, "getuid") and st.st_uid != os.getuid()):
            return False
        os.chmod(p, st.st_mode & 0o700)
        return True
    except OSError:
        return False


def atomic_write_json(path: str, obj) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        dir_fd = os.open(d, flags)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


HIST_DIRTY = "hist_dirty.json"
HIST_DIRTY_KEEP = 200


def mark_hist_dirty(ts, state_dir: str = None) -> str:
    import fcntl
    import time as _time
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    sd = state_dir or STATE_DIR
    iso = _dt.fromtimestamp(int(ts), _tz(_td(hours=9))).strftime("%Y-%m-%d")
    p = os.path.join(sd, HIST_DIRTY)
    os.makedirs(sd, exist_ok=True)
    with open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            cur = read_json(p, None)
        except SystemExit:
            cur = None
            logging.getLogger("tj").warning("hist_dirty.json 손상 — 새로 씀")
        cur = cur if isinstance(cur, dict) else {}
        seq = int(cur.get("seq") or 0) + 1
        marks = [m for m in (cur.get("marks") or []) if isinstance(m, list) and len(m) >= 3] + [[seq, iso, int(_time.time())]]
        if len(marks) > HIST_DIRTY_KEEP:
            marks.sort(key=lambda m: int(m[0]))
            keep9, fold9 = marks[:HIST_DIRTY_KEEP - 1], marks[HIST_DIRTY_KEEP - 1:]
            marks = keep9 + [[seq, min(m[1] for m in fold9), int(_time.time())]]
        atomic_write_json(p, {"from": min(m[1] for m in marks), "seq": seq, "marks": marks})
    return iso


def hist_dirty_update(fn, state_dir: str = None):
    import fcntl
    sd = state_dir or STATE_DIR
    p = os.path.join(sd, HIST_DIRTY)
    with open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            cur = read_json(p, None)
        except SystemExit:
            cur = None
        new = fn(cur if isinstance(cur, dict) else None)
        if new is None:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        elif new is not cur:
            atomic_write_json(p, new)
        return new


EXF_LATE_PFX = "exflate:"


def exf_is_debt_int(event, leg_seq, source_ns, source_id) -> bool:
    try:
        seq9 = int(leg_seq or 0)
    except (TypeError, ValueError):
        return False
    return (event == "EXF_ADJUST" and seq9 == 2 and str(source_ns or "").endswith(":recon")
            and not str(source_id or "").startswith(EXF_LATE_PFX))


EXF_FUT_NS = "futpnl"


def exf_is_fut(event, source_ns) -> bool:
    return event == "EXF_ADJUST" and str(source_ns or "").endswith(":" + EXF_FUT_NS)


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


SEED_SET_LISTS = {
    "bridge_contracts.json": ((),),
    "sale_contracts.json": (("cca_factories",), ("chains",)),
    "xchain_bridges.json": (("sol_lp_markers",), ("evm_contracts", "*", "chains")),
    "zero_value_companions.json": (("tokens",),),
}
SEED_ID_LISTS = {"coverage/api_limits.json": (("exchanges",), ("chains",), ("perps",))}


def _seed_path_in(path: tuple, pats) -> bool:
    return any(len(p) == len(path) and all(a == "*" or a == b for a, b in zip(p, path)) for p in pats)


def seed_set_key(v):
    if isinstance(v, str):
        s = v.strip()
        return s.lower() if s[:2].lower() == "0x" else s
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def seed_list_kind(rel, path: tuple) -> str:
    r9 = str(rel or "").replace(os.sep, "/")
    if _seed_path_in(path, SEED_SET_LISTS.get(r9, ())):
        return "set"
    if _seed_path_in(path, SEED_ID_LISTS.get(r9, ())):
        return "id"
    return ""


def seed_merge(base, over, rel=None, _path=()):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = seed_merge(base[k], v, rel, _path + (str(k),)) if k in base else v
        return out
    if rel and isinstance(base, list) and isinstance(over, list):
        kind = seed_list_kind(rel, _path)
        if kind == "set":
            out, seen = [], set()
            for v in list(base) + list(over):
                k9 = seed_set_key(v)
                if k9 in seen:
                    continue
                seen.add(k9)
                out.append(k9 if isinstance(v, str) else v)
            return out
        if kind == "id" and all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in list(base) + list(over)):
            ids = {x["id"] for x in over}
            return list(over) + [x for x in base if x["id"] not in ids]
    return over


def seed_canon(o, rel=None, _path=()):
    if isinstance(o, dict):
        return {k: seed_canon(v, rel, _path + (str(k),)) for k, v in o.items()}
    if isinstance(o, list):
        if rel and seed_list_kind(rel, _path) == "set":
            return sorted({seed_set_key(v) for v in o})
        return [seed_canon(v, rel, _path) for v in o]
    return o


def seed_json(rel: str, default=None, base_dir: str = None, strict: bool = False):
    def _one(p, strict9):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return True, json.load(f)
        except FileNotFoundError:
            return False, None
        except (json.JSONDecodeError, OSError, ValueError) as e:
            if strict9:
                raise SystemExit(f"seed 파일 손상: {p}: {e}")
            return False, None
    root = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hb, b = _one(os.path.join(root, "seed", rel), strict)
    ho, o = _one(os.path.join(STATE_DIR, "seed_local", rel), True)
    if not hb and not ho:
        return default
    if not ho:
        return b
    if not hb:
        return o
    return seed_merge(b, o, rel)


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


def iso_epoch(s):
    if s is None or s == "":
        return None
    try:
        import datetime as _dt
        t = str(s).strip()
        if t.endswith(("Z", "z")):
            t = t[:-1] + "+00:00"
        d = _dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return int(d.timestamp())
    except (ValueError, TypeError):
        return None


def tool_ref(name: str, alt: str) -> str:
    return f"tools/{name}" if os.path.isfile(os.path.join(BASE_DIR, "tools", name)) else alt


_LINK_RES = None
LINK_KEEP = frozenset((
    "gate.io", "crypto.com", "xt.com",
    "pump.fun", "letsbonk.fun", "bonk.fun", "four.meme", "bags.fm",
    "jup.ag", "li.fi", "gas.zip", "ether.fi", "friend.tech", "io.net",
    "gmgn.ai", "axiom.trade",
    "opensea.io", "magiceden.io", "blur.io",
))


def strip_links(text):
    global _LINK_RES
    if not isinstance(text, str) or not text:
        return text
    if _LINK_RES is None:
        import re as _re9
        _LINK_RES = (
            _re9.compile(r"(?i)(?:https?|wss?|ftp|tg)://\S+"),
            _re9.compile(r"([A-Za-z0-9._%+-]+)@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}"),
            _re9.compile(r"(?<![A-Za-z0-9._%+@-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?:[a-z]{2,24}|(?i:com|net|org|xyz|info)))"
                         r"(?![A-Za-z0-9-])([/?#]\S*|:\d+\S*)?"),
            _re9.compile(r"(?<![A-Za-z0-9_.@])@[A-Za-z][A-Za-z0-9_]+"),
            _re9.compile(r"\(\s*\)|\[\s*\]"),
            _re9.compile(r"[ \t]{2,}"),
            _re9.compile(r"\s+([.,;:!?)])(?!\d)"),
            _re9.compile(r"\d[\d.]*"),
        )
    url, mail, dom, handle, empty, spaces, before_p, num = _LINK_RES
    s = url.sub("", text)
    s = mail.sub(lambda m: m.group(1) if num.fullmatch(m.group(1)) else "", s)
    s = dom.sub(lambda m: m.group(0) if m.group(1).lower() in LINK_KEEP and not m.group(2) else "", s)
    s = handle.sub("", s)
    if s == text:
        return text
    s = empty.sub("", s)
    s = spaces.sub(" ", s)
    s = before_p.sub(r"\1", s)
    return s.strip()

import json
import logging
import os
import re
import sys
import threading
import traceback
import urllib.parse
from typing import Callable, Iterable, Optional, TextIO

import statefile

__all__ = ["set_sources", "redact_urls", "redact_secret_text", "safe_err", "scrub_secrets", "SECRET_FIELD_KEYS",
           "SecretLogFilter", "add_secret_filter", "install_excepthook", "format_exception_redacted", "print_request_error",
           "strip_bidi", "setup_logging", "scrub_secret_file", "is_secret_name"]

_SOURCES = [None]


def set_sources(fn: Optional[Callable[[], tuple]]) -> None:
    _SOURCES[0] = fn


def _source_paths() -> tuple:
    fn = _SOURCES[0]
    if fn is None:
        return "", ""
    envp, cfgp = fn()
    return envp or "", cfgp or ""


def redact_urls(msg) -> str:
    if msg is None:
        return msg
    s, out, p = str(msg), [], 0
    for m in _AUTH_CUT_RE.finditer(s):
        out.append(_shrink_urls(s[p:m.start()], cut=True))
        out.append(m.group(1) + ("***" if m.end() > m.end(1) else ""))
        p = m.end()
    out.append(_shrink_urls(s[p:], cut=False))
    return "".join(out)


_URL_ANY_RE = re.compile(r"(?i)(?:https?|wss?)://\S+")
_AUTH_CUT_RE = re.compile(r"(?i)(authorization)[^\r\n]*")


def _host_as_written(netloc: str, hostname: str) -> str:
    hp = netloc.rpartition("@")[2]
    _, br, rest = hp.partition("[")
    written = rest.partition("]")[0] if br else hp.partition(":")[0]
    return written if written.lower() == hostname.lower() else "(주소 숨김)"


def _shrink_urls(seg: str, cut: bool) -> str:
    def host(m):
        tok = m.group(0)
        if cut and m.end() == len(seg):
            return "(주소 숨김)"
        core = tok.rstrip(".,;:!?)]}'\"")
        tail = tok[len(core):]
        for cand in (core, tok):
            try:
                sp = urllib.parse.urlsplit(cand)
            except ValueError:
                continue
            if sp.hostname:
                return _host_as_written(sp.netloc, sp.hostname) + (tail if cand is core else "")
        return "(주소 숨김)" + tail
    return _URL_ANY_RE.sub(host, seg)


_SECRET_NAME_RE = None
_SECRET_CACHE = {"sig": None, "grams": frozenset(), "checked": 0.0}
_SECRET_MIN = 8


def _secret_name(name) -> bool:
    global _SECRET_NAME_RE
    import re as _re9
    if _SECRET_NAME_RE is None:
        _SECRET_NAME_RE = _re9.compile(r"(?i)(?:key|secret|token|pass|access|refresh|client_id|account)")
    return bool(_SECRET_NAME_RE.search(str(name or "")))


def is_secret_name(name: object) -> bool:
    return _secret_name(name)


def _secret_values() -> list:
    import re as _re9
    vals = []
    envp, cfgp = _source_paths()
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
        with open(cfgp, "r", encoding="utf-8") as f:
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
    for p in _source_paths():
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


_AUTH_RE = re.compile(
    r"(?i)(?<![a-z0-9])authorization(?:(?:\\*[\"'])?[ \t]*[:=]|\\*[\"'][ \t]*,)[ \t]*")
_EOL_RE = re.compile(r"[\r\n]")
_AUTH_QMAX = 256
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)[ \t]+([A-Za-z0-9._~+/=-]{8,})")
_BOT_URL_RE = re.compile(r"(/bot)\d{5,12}:[A-Za-z0-9_-]{20,64}")
_BOT_BARE_RE = re.compile(r"(?<![A-Za-z0-9_])\d{5,12}:AA[A-Za-z0-9_-]{20,62}(?![A-Za-z0-9_-])")
_PATH_KEY_RE = re.compile(r"(?i)(/(v\d{1,2}|rpc|key|keys|apikey|api-key|token)/)([A-Za-z0-9_-]{16,})")
_PREFIX_HEX_RE = re.compile(r"(?i)((?:개인[ \t]?키|비밀[ \t]?키|시크릿|(?<![가-힣])키|secret|private[ _-]?key|priv[_-]?key|privkey)"
                            r"[\"']?[ \t]*(?:(?:[:=]|는|은|=>)[ \t]*)?[\"']?)0x[0-9a-f]{64}(?![0-9a-f])")
_B58 = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
_HEX0X_RE = re.compile(r"0x[0-9a-fA-F]+")


def _cred_like(v: str) -> bool:
    return len(v) >= 16 or any(c.isdigit() or c in "+/=" for c in v)


def _path_key_span(m):
    kw, v = m.group(2).lower(), m.group(3)
    if _HEX0X_RE.fullmatch(v) or (kw == "token" and 32 <= len(v) <= 44 and set(v) <= _B58):
        return None
    if len(v) < 32 and not any(c.isdigit() for c in v):
        return None
    return m.span(3)


def _auth_span(s: str, a: int, end: int) -> tuple:
    i = a
    while i < end and s[i] == "\\":
        i += 1
    if i >= end or s[i] not in "\"'":
        return a, end
    k, q, j = i - a, s[i], i + 1
    for _ in range(_AUTH_QMAX):
        j = s.find(q, j, end)
        if j < 0:
            break
        n = 0
        while n <= k and j - 1 - n > i and s[j - 1 - n] == "\\":
            n += 1
        if n == k:
            return i + 1, j - k
        j += 1
    return i + 1, end


def _auth_spans(s: str) -> list:
    out, eol, upto = [], -1, -1
    for m in _AUTH_RE.finditer(s):
        a = m.end()
        if a < upto == eol:
            continue
        if a > eol:
            nl = _EOL_RE.search(s, a)
            eol = nl.start() if nl else len(s)
        sp = _auth_span(s, a, eol)
        if sp[1] > sp[0]:
            out.append(sp)
            upto = max(upto, sp[1])
    return out


_UNCONF_RULES = (
    (_BEARER_RE, lambda m: m.span(2) if _cred_like(m.group(2)) else None),
    (_BOT_URL_RE, lambda m: (m.end(1), m.end())),
    (_BOT_BARE_RE, lambda m: m.span()),
    (_PATH_KEY_RE, _path_key_span),
    (_PREFIX_HEX_RE, lambda m: (m.end(1), m.end())),
)


def _rule_hits(s: str, hit: list, kv, patterns=()) -> set:
    starts = set()
    for m in _ORIGIN_RE.finditer(s):
        starts.add(m.end(1))
        hit[m.end(1):m.end()] = [True] * (m.end() - m.end(1))
    for m in kv.finditer(s):
        hit[m.start(2):m.end(2)] = [True] * (m.end(2) - m.start(2))
    for rx in patterns:
        for m in rx.finditer(s):
            hit[m.end(1):m.end()] = [True] * (m.end() - m.end(1))
    for a, b in _auth_spans(s):
        hit[a:b] = [True] * (b - a)
    for rx, span in _UNCONF_RULES:
        for m in rx.finditer(s):
            sp = span(m)
            if sp and sp[1] > sp[0]:
                hit[sp[0]:sp[1]] = [True] * (sp[1] - sp[0])
    return starts


def _extra_sets(extra, extra_min, dashless) -> tuple:
    lo = max(1, int(extra_min))
    vals = [v for v in (str(x or "") for x in extra or ()) if len(v) >= lo]
    if dashless:
        vals += [d for d in (v.replace("-", "") for v in vals if "-" in v) if d]
    xg, short = set(), []
    for v in vals:
        if len(v) >= _SECRET_MIN:
            xg.update(v[i:i + _SECRET_MIN] for i in range(len(v) - _SECRET_MIN + 1))
        else:
            short.append(v)
    return xg, short


def _value_hits(s: str, hit: list, grams, xg, short) -> None:
    if grams or xg:
        for i in range(len(s) - _SECRET_MIN + 1):
            g = s[i:i + _SECRET_MIN]
            if g in grams or g in xg:
                hit[i:i + _SECRET_MIN] = [True] * _SECRET_MIN
    for v in short:
        i = s.find(v)
        while i >= 0:
            hit[i:i + len(v)] = [True] * len(v)
            i = s.find(v, i + 1)


def _render(s: str, hit: list, bracket=frozenset()) -> str:
    if not any(hit):
        return s
    out, i = [], 0
    while i < len(s):
        if hit[i]:
            out.append("[***]" if i in bracket else "***")
            while i < len(s) and hit[i]:
                i += 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _redact(text: object, generic: bool, extra: Iterable = (), extra_min: int = _SECRET_MIN, dashless: bool = False,
            patterns: Iterable = ()) -> str:
    global _KV_SECRET_RE, _ORIGIN_RE, _LONG_RE
    s = str(text)
    if _KV_SECRET_RE is None:
        names = (r"api[_\-]?key|apikey|access[_\-]?key|secret[_\-]?key|secret|passphrase|password|signature|"
                 r"(?:access|auth|refresh|api|bot)[_\-]?token|x-bapi-api-key|x-mbx-apikey|ok-access-key|kc-api-key")
        _KV_SECRET_RE = (
            re.compile(r"(?i)((?:" + names + r"|sign|token)[\"']?\s*[=:]\s*[\"']?)([^\s&,;\"'\]\)}]+)"),
            re.compile(r"(?i)((?:" + names + r")[\"']?\s*[=:]\s*[\"']?)([^\s&,;\"'\]\)}]+)"))
        _ORIGIN_RE = re.compile(r"(?i)(origin_string)\s*[\[\(:=]?\s*[^\]\)\n]*[\]\)]?")
        _LONG_RE = re.compile(r"(?<![0-9A-Za-z+/=_\-])(?!0x[0-9a-fA-F]+(?![0-9A-Za-z+/=_\-]))[0-9A-Za-z+/=_\-]{24,}")
    if generic:
        s = redact_urls(s)
    hit = [False] * len(s)
    starts = _rule_hits(s, hit, _KV_SECRET_RE[0 if generic else 1], patterns)
    if generic:
        keep = set()
        for m in _KV_SECRET_RE[0].finditer(s):
            keep.update(range(m.start(1), m.end(1)))
        for m in _LONG_RE.finditer(s):
            for j in range(m.start(), m.end()):
                if j not in keep:
                    hit[j] = True
    xg, short = _extra_sets(extra, extra_min, dashless)
    _value_hits(s, hit, _secret_grams(), xg, short)
    s = _render(s, hit, starts)
    if generic:
        s = redact_urls(s)
        s = _LONG_RE.sub("***", s)
    return s


def redact_secret_text(text: object, generic: bool = True, extra: Iterable = (), extra_min: int = _SECRET_MIN,
                       dashless: bool = False, patterns: Iterable = ()) -> str:
    if text is None:
        return text
    try:
        return _redact(text, generic, extra, extra_min, dashless, patterns)
    except Exception:   # noqa: BLE001 [fallback]
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
        except Exception:   # noqa: BLE001 [fallback]
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
        s2 = redact_urls(redact_secret_text(redact_urls(obj), generic=False))
        return s2, int(s2 != obj)
    return obj, 0


def add_secret_filter(handlers=None) -> None:
    for h in (handlers if handlers is not None else logging.getLogger().handlers):
        if not any(isinstance(f, SecretLogFilter) for f in h.filters):
            h.addFilter(SecretLogFilter())


def _type_name(etype) -> str:
    try:
        mod, q = getattr(etype, "__module__", ""), getattr(etype, "__qualname__", "") or "Exception"
        return q if mod in ("builtins", "__main__", "", None) else "%s.%s" % (mod, q)
    except Exception:   # noqa: BLE001 [fallback]
        return "Exception"


def format_exception_redacted(etype: object, value: object, tb: object) -> str:
    try:
        return "".join(_redact(x, False) for x in traceback.format_exception(etype, value, tb))
    except Exception:   # noqa: BLE001 [fallback]
        return "Traceback (most recent call last):\n  (추적 숨김 — 가리기 실패)\n%s\n" % _type_name(etype)


def _write_err(text: str, stream: Optional[TextIO] = None) -> None:
    err = stream if stream is not None else sys.stderr
    if err is None:
        return
    try:
        err.write(text)
        err.flush()
    except Exception:   # noqa: BLE001 [boundary]
        pass


def _sys_hook(etype, value, tb) -> None:
    _write_err(format_exception_redacted(etype, value, tb))


def _thread_hook(args) -> None:
    if args.exc_type is SystemExit:
        return
    stream = sys.stderr if sys.stderr is not None else getattr(args.thread, "_stderr", None)
    name = redact_secret_text(args.thread.name, generic=False) if args.thread is not None else threading.get_ident()
    _write_err("Exception in thread %s:\n" % name + format_exception_redacted(args.exc_type, args.exc_value, args.exc_traceback), stream)


def install_excepthook() -> None:
    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def print_request_error(client_address: object, file: Optional[TextIO] = None) -> None:
    et, ev, tb = sys.exc_info()
    _write_err("-" * 40 + "\nException occurred during processing of request from %s\n" % (client_address,)
               + format_exception_redacted(et, ev, tb) + "-" * 40 + "\n", file)


_BIDI_RE = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def strip_bidi(text: Optional[str]) -> Optional[str]:
    return text if text is None else _BIDI_RE.sub("", str(text))


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [" + name + "] %(message)s", stream=sys.stdout)
    add_secret_filter()
    install_excepthook()
    return logging.getLogger(name)


def scrub_secret_file(path: str, keys=SECRET_FIELD_KEYS) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0
    d2, n = scrub_secrets(d, keys)
    if n:
        try:
            statefile.atomic_write_json(path, d2)
        except OSError:
            return 0
    return n

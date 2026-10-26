import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root():
    env = os.environ.get("TJ_TEST_ROOT")
    cands = [env] if env else [os.path.join(HERE, ".."), os.path.join(HERE, "..", "..")]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "src", "version.py")):
            return os.path.abspath(c)
    raise SystemExit("tests: src/version.py(뿌리 표식)를 찾지 못했어요 — TJ_TEST_ROOT=<src 가 든 폴더> 로 지정하세요")


ROOT = _find_root()
SRC = os.path.join(ROOT, "src")
README = os.path.abspath(os.path.join(HERE, "..", "README.md"))

def mod_src(base: str, prefix: str, src_dir: str = None) -> str:
    d = src_dir or SRC
    names = [base + ".py"] + sorted(f for f in os.listdir(d) if f.startswith(prefix) and f.endswith(".py"))
    parts = []
    for i, nm in enumerate(names):
        t = open(os.path.join(d, nm), encoding="utf-8").read()
        if i:
            t = t.replace("from __future__ import annotations\n", "\n")
        parts.append(t)
    return "\n".join(parts)


def core_src(src_dir: str = None) -> str:
    return mod_src("core", "core_", src_dir)


def patch_cls_attr(cls, name, value):
    setattr(cls, name, value)
    for b in cls.__mro__[1:]:
        if name in b.__dict__:
            setattr(b, name, value)


def patch_moved(name, value, prefixes=("core_", "view_", "http_", "accounting_", "fsio")):
    for mn, m in list(sys.modules.items()):
        if mn.startswith(prefixes) and m is not None and hasattr(m, name):
            setattr(m, name, value)


def _app_js_stripped(s: str, t: str, n: str, fn: str) -> str:
    tl = t.split("\n")
    i = tl.index("  } = X;") + 1
    if i < len(tl) and tl[i].startswith("  let ") and tl[i + 1] == "  const __late = L => {":
        i = tl.index("  };", i + 1) + 1
    j = max(k for k, l in enumerate(tl) if l == "  return {")
    body = tl[i:j]
    al = s.split("\n")
    k = [x for x, l in enumerate(al) if l.startswith("  } = tjTab('%s', {" % n)]
    if len(k) != 1:
        raise AssertionError("app_js(공개 빌드): app.js 의 tjTab('%s' 자리가 하나가 아님" % n)
    a = max(x for x in range(k[0]) if al[x] == "  const {")
    b = next(x for x in range(k[0], len(al)) if al[x] == "  });")
    rest = [l for l in al[b + 1:] if not l.startswith("  tjLate_%s(" % n)]
    return "\n".join(al[:a] + body + rest)


def app_js(root: str = None) -> str:
    v2 = os.path.join(root or ROOT, "web", "v2")
    s = open(os.path.join(v2, "app.js"), encoding="utf-8").read()
    for fn in sorted(f for f in os.listdir(v2) if f.startswith("tab_") and f.endswith(".js")):
        n = fn[4:-3]
        t = open(os.path.join(v2, fn), encoding="utf-8").read()
        b0, b1 = "  // ★BEGIN tab:%s★\n" % n, "  // ★END tab:%s★\n" % n
        if "★tab:%s★" % n not in s and b0 not in t:
            s = _app_js_stripped(s, t, n, fn)
            continue
        if t.count(b0) != 1 or t.count(b1) != 1:
            raise AssertionError("app_js: %s 의 BEGIN·END 표식이 하나가 아님" % fn)
        body = t[t.index(b0) + len(b0):t.index(b1)]
        lines = s.split("\n")
        i0 = [i for i, l in enumerate(lines) if l.startswith("  // ★tab:%s★" % n)]
        i1 = [i for i, l in enumerate(lines) if l.endswith("// ★/tab:%s★" % n)]
        if len(i0) != 1 or len(i1) != 1 or i1[0] < i0[0]:
            raise AssertionError("app_js: app.js 의 ★tab:%s★ 자리 표식이 하나가 아님" % n)
        rest = [l for l in lines[i1[0] + 1:] if not l.endswith("// ★late:%s★" % n) and "// ★late:%s★ " % n not in l]
        s = "\n".join(lines[:i0[0]]) + "\n" + body + "\n".join(rest)
    return s


_APP_JS_TMP = {}


def app_js_path(root: str = None) -> str:
    r = root or ROOT
    v2 = os.path.join(r, "web", "v2")
    if not any(f.startswith("tab_") and f.endswith(".js") for f in os.listdir(v2)):
        return os.path.join(v2, "app.js")
    if r not in _APP_JS_TMP:
        d = tempfile.mkdtemp(prefix="tj_appjs_")
        atexit.register(shutil.rmtree, d, True)
        p = os.path.join(d, "app.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(app_js(r))
        _APP_JS_TMP[r] = p
    return _APP_JS_TMP[r]


def v2_css(root: str = None) -> str:
    v2 = os.path.join(root or ROOT, "web", "v2")
    return "".join(open(os.path.join(v2, n), encoding="utf-8").read() for n in ("app.css", "mods.css", "wow.css"))


def web_src() -> str:
    names = ["web.py"] + sorted(f for f in os.listdir(SRC) if f.startswith(("view_", "http_", "accounting_")) and f.endswith(".py"))
    parts = []
    for i, nm in enumerate(names):
        t = open(os.path.join(SRC, nm), encoding="utf-8").read()
        if i:
            t = t.replace("from __future__ import annotations\n", "\n")
        parts.append(t)
    return "\n".join(parts)

if not os.path.isfile(README):
    README = os.path.join(ROOT, "README.md")

README_PARTS = ("docs/SCREENS.md", "docs/INSTALL.md", "docs/FEATURES.md", "docs/OPERATIONS.md", "docs/CONFIG.md",
                "docs/SECURITY_DATA.md", "docs/README_EN.md")


def doc_text(name: str = "README.md", base: str = None) -> str:
    base = base or os.path.dirname(README)
    with open(os.path.join(base, name), encoding="utf-8") as f:
        parts = [f.read()]
    if os.path.normpath(name) != "README.md":
        return parts[0]
    have = [rel for rel in README_PARTS if os.path.isfile(os.path.join(base, rel))]
    if have and len(have) != len(README_PARTS):
        raise FileNotFoundError("README 나눈 문서 일부 없음: " + ", ".join(sorted(set(README_PARTS) - set(have))))
    for rel in have:
        with open(os.path.join(base, rel), encoding="utf-8") as f:
            parts.append(f.read())
    return "\n".join(parts)

for _k in [k for k in os.environ if k.startswith("TJ_") and not k.startswith("TJ_TEST_")]:
    del os.environ[_k]
if os.environ.get("TJ_TEST_STRICT") == "1":
    os.environ["TJ_STRICT"] = "1"
for _k in [k for k in os.environ if k.lower() in ("http_proxy", "https_proxy", "all_proxy")]:
    del os.environ[_k]
TMP = tempfile.mkdtemp(prefix="tj_test_")
atexit.register(shutil.rmtree, TMP, True)
os.environ["TJ_BASE"] = TMP
os.makedirs(os.path.join(TMP, "state"), exist_ok=True)

NET_TRIES = []
_LOOP = ("127.0.0.1", "::1", "localhost")
_connect, _connect_ex, _gai = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo


def _host_of(addr):
    return addr[0] if isinstance(addr, tuple) else addr


def _guard_connect(self, addr):
    h = _host_of(addr)
    if h not in _LOOP:
        NET_TRIES.append(str(h))
        raise OSError("시험: 바깥 연결 차단")
    return _connect(self, addr)


def _guard_connect_ex(self, addr):
    h = _host_of(addr)
    if h not in _LOOP:
        NET_TRIES.append(str(h))
        raise OSError("시험: 바깥 연결 차단")
    return _connect_ex(self, addr)


def _guard_gai(host, *a, **k):
    h = host.decode() if isinstance(host, bytes) else host
    if h is not None and h not in _LOOP:
        NET_TRIES.append(str(h))
        raise socket.gaierror("시험: 바깥 이름 조회 차단")
    return _gai(host, *a, **k)


socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
socket.getaddrinfo = _guard_gai
socket.gethostbyname = lambda h: _guard_gai(h, None)[0][4][0]


def _guard_urlopen(url, *a, **k):
    u = getattr(url, "full_url", url)
    NET_TRIES.append("urlopen " + str(u)[:120])
    raise OSError("시험: 바깥 연결 차단")


import urllib.request  # noqa: E402
urllib.request.urlopen = _guard_urlopen
sys.path.insert(0, SRC)

def sigint_default():
    signal.signal(signal.SIGINT, signal.SIG_DFL)


PASS = 0
FAILS = []


def chk(ok, msg, extra=None):
    global PASS  # noqa: PLW0603
    if ok:
        PASS += 1
        print("PASS " + msg, flush=True)
    else:
        FAILS.append(msg)
        try:
            tail = "" if extra is None else "  — " + json.dumps(extra, ensure_ascii=False, default=str)[:900]
        except (TypeError, ValueError):
            tail = "  — " + repr(extra)[:900]
        print("FAIL " + msg + tail, flush=True)


REQUIRE_NODE = os.environ.get("TJ_TEST_REQUIRE_NODE") == "1"


def node_path():
    return shutil.which("node")


def node_required(alias=False):
    return REQUIRE_NODE or bool(alias)


def node_unusable(what, why, required=None):
    if node_required() if required is None else required:
        chk(False, "%s — %s 못 돌림(TJ_TEST_REQUIRE_NODE=1)" % (why, what))
    else:
        print("SKIP %s — %s 건너뜀" % (why, what), flush=True)


def node_bin(what, required=None):
    n = node_path()
    if n:
        return n
    node_unusable(what, "node 없음", required)
    return None


def safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:   # noqa: BLE001
        return {"_exc": f"{type(e).__name__}: {e}"}


CASE_OUT_ENV = "TJ_TEST_CASE_OUT"
_CASE_N = [0]


def case_emit(out) -> None:
    txt = json.dumps(out, default=str, ensure_ascii=False)
    path = os.environ.get(CASE_OUT_ENV)
    if path:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(txt)
        os.replace(path + ".tmp", path)
    sys.stdout.write("CASE " + txt + "\n")
    sys.stdout.flush()


def case_run(argv, timeout=600, cwd=None) -> dict:
    _CASE_N[0] += 1
    path = os.path.join(TMP, "case_%d_%d.json" % (os.getpid(), _CASE_N[0]))
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, **{CASE_OUT_ENV: path}))
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError) as e:
        return {"_err": "결과 파일 없음·깨짐(%s) · 종료값 %s" % (type(e).__name__, r.returncode), "stdout": r.stdout[-600:], "stderr": r.stderr[-1500:]}
    if r.returncode != 0:
        return {"_err": "결과 뒤 비정상 종료 · 종료값 %s" % r.returncode, "result": got, "stdout": r.stdout[-600:], "stderr": r.stderr[-1500:]}
    return got


def _outside_stdlib():
    out = []
    for name, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None) or ""
        if ("site-packages" in f or "dist-packages" in f) and not name.startswith(("_distutils_hack", "distutils")):
            out.append(name)
    return sorted(set(n.split(".")[0] for n in out))


def finish():
    chk(not NET_TRIES, f"바깥 연결 시도 {len(NET_TRIES)}건(0이어야 함)", sorted(set(NET_TRIES))[:10])
    uo = urllib.request.urlopen
    if uo is not _guard_urlopen and not getattr(uo, "_tj_test_mock", False):
        chk(False, "urlopen 차단기가 기록 없는 함수로 바뀜(차단 = 하네스 한 곳 · 목이면 _tj_test_mock 표시)", getattr(uo, "__qualname__", repr(uo)))
    ext = _outside_stdlib()
    chk(not ext, "표준 라이브러리 밖 모듈 0", ext)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n결과: {PASS} PASS · {len(FAILS)} FAIL")
    if FAILS:
        print("실패: " + " | ".join(FAILS)[:2000])
    sys.exit(1 if FAILS else 0)

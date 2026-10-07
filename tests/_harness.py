import atexit
import json
import os
import shutil
import socket
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root():
    env = os.environ.get("TJ_TEST_ROOT")
    cands = [env] if env else [os.path.join(HERE, ".."), os.path.join(HERE, "..", "..")]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "src", "common.py")):
            return os.path.abspath(c)
    raise SystemExit("tests: src/common.py 를 찾지 못했어요 — TJ_TEST_ROOT=<src 가 든 폴더> 로 지정하세요")


ROOT = _find_root()
SRC = os.path.join(ROOT, "src")
README = os.path.abspath(os.path.join(HERE, "..", "README.md"))
if not os.path.isfile(README):
    README = os.path.join(ROOT, "README.md")

for _k in [k for k in os.environ if k.startswith("TJ_") and not k.startswith("TJ_TEST_")]:
    del os.environ[_k]
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


import urllib.request
urllib.request.urlopen = _guard_urlopen
sys.path.insert(0, SRC)

PASS = 0
FAILS = []


def chk(ok, msg, extra=None):
    global PASS
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


def safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        return {"_exc": f"{type(e).__name__}: {e}"}


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

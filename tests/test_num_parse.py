#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import __future__  # noqa: E402
import ast  # noqa: E402
import importlib  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import textwrap  # noqa: E402
import warnings  # noqa: E402
from decimal import Decimal, InvalidOperation  # noqa: E402
from fractions import Fraction  # noqa: E402

sys.path.insert(0, T.SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import num_parse  # noqa: E402

chk = T.chk
warnings.simplefilter("ignore")
BASE = "b81991b745f3954f505285ca7911ac798b3cc517"

ORIG = {
    'acct_norm._dec': r'''
def _dec(v):
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None
''',
    'addr_ai._num': r'''
def _num(x):
    """숫자 → float | None(없음·숫자 아님·NaN·무한 = 모름 — 0 으로 바꾸지 않는다)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
''',
    'addr_ai.cband': r'''
def cband(n) -> str | None:
    """거래 수 구간."""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return None
    return "0" if v <= 0 else "1~9" if v < 10 else "10~99" if v < 100 else "100~999" if v < 1000 else "1천~9999" if v < 10000 else "1만 이상"
''',
    'alert_bot._num_ts': r'''
def _num_ts(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if 1e9 < x < 1e11 else 0.0
''',
    'alert_watch._f': r'''
def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None
''',
    'bf_engine._pol_num': r'''
def _pol_num(v, default, typ, lo, hi):
    """정책 수치(config 로 들어온 문자열·null·NaN·inf 포함) → typ, [lo, hi]. 해석 불가 = default (게이트 생성이 예외로 막히지 않게)."""
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return typ(min(hi, max(lo, x)))
''',
    'candles._f': r'''
def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None
''',
    'cgplan._num': r'''
def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", "")
        if not re.fullmatch(r"\d{1,13}(\.\d+)?", v):
            return None
    if not isinstance(v, (int, float, str)):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x < 0 or x >= 1e13:
        return None
    return x
''',
    'cgplan.approx': r'''
def approx(n) -> str:
    """'하루 ~1,600' 처럼 어림(두 자리 유효숫자로 내림) — 1,666 → 1,600 · 13,333 → 1.3만."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 1000:
        p = 10 ** (len(str(n)) - 2)
        n = n // p * p
    return man(n)
''',
    'cgplan.man': r'''
def man(n) -> str:
    """사람이 읽는 수 — 10,000 이상은 '만'(50만 · 1.3만 · 200만), 그 아래는 천 단위 쉼표."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 10000:
        v = n / 10000.0
        s = f"{v:.1f}".rstrip("0").rstrip(".") if v < 100 else f"{v:.0f}"
        return s + "만"
    return f"{n:,}"
''',
    'core_exf_late.ExfLateMixin._exf_hist_touch': r'''
def _exf_hist_touch(self, ts):
    """지난 시점 posting 이 바뀜 — 그 원장 쓰기 뒤 · 같은 트랜잭션 커밋 앞에서 부른다: 일별 동결 무효화 표식(_inval_seq — 변경과 함께 커밋)
    + 옛 신호·장기 곡선 표식 재료(가장 이른 시각 — 커밋 뒤 _exf_hist_flush 가 파일 삭제·hist_dirty 로)."""
    self._inval_seq()
    self._exf_hist_dirty = True
    try:
        t9 = int(ts)
    except (TypeError, ValueError):
        return
    cur9 = getattr(self, "_exf_hist_from", None)
    self._exf_hist_from = t9 if cur9 is None else min(cur9, t9)
''',
    'core_upbit.UpbitMixin._upbit_q8': r'''
def _upbit_q8(amount):
    """업비트 실도착량(사람 단위, 8자리 이하) → base(1e-8) 정수. 8자리 초과·무효 = None(거부).
    (설계검수 R1 [1]: 체인 base-unit 을 나눠 양자화하지 않는다 — amount 가 이미 정본)"""
    try:
        a = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not a.is_finite() or a <= 0:
        return None
    q = a * (Decimal(10) ** 8)
    if q != q.to_integral_value():
        return None
    return int(q)
''',
    'exf_net._dstr': r'''
def _dstr(x) -> str:
    try:
        d = Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    if not d.is_finite():
        return "0"
    return format(d.normalize(), "f") if d != 0 else "0"
''',
    'exf_net._int_or': r'''
def _int_or(v, d=-999):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d
''',
    'exprov._num': r'''
def _num(v) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None
''',
    'flowev._d': r'''
def _d(v):
    try:
        x = Decimal(str(v))
        return x if x.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None
''',
    'fut_rcpt.num': r'''
def num(v):
    """외부 숫자 → 유한 float | None(None·bool·빈 문자열·형식 오류·비유한)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None
''',
    'lev_view._f': r'''
def _f(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
''',
    'leverage.num': r'''
def num(x):
    """거래소 문자열/숫자 → 유한 float, 빈 값·형식 오류·비유한 = None (0 으로 채우지 않는다)."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, str):
        x = x.strip()
        if not x:
            return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
''',
    'liq_watch._f': r'''
def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None
''',
    'liq_watch._int': r'''
def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
''',
    'nft._num': r'''
def _num(v):
    """숫자·숫자 문자열 → 유한 float | None."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and abs(x) < 1e18 else None
''',
    'ops_requests._fin': r'''
def _fin(v):
    """보고서 숫자 재료 — 정수·실수(bool 아님)이고 유한할 때만 float, 아니면 None(빠진 재료 = fail-closed · 105a: None→0 · NaN 허용 금지)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None
''',
    'perp_dex._big': r'''
def _big(v, d=0.0):
    """정수 배율 원본(GMX 1e30 등) → 유한 float(상한 없음 — 나눈 뒤 결과는 _ev·_clean_pos 가 다시 검사)."""
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return d
    return x if math.isfinite(x) else d
''',
    'perp_dex._f': r'''
def _f(v, d=0.0):
    """외부 숫자 → 유한 float(비유한·1e15 초과·형식 오류 = d) — 코덱스 tjperp1 #2(1e309·Infinity 가 저장돼 web 빌드 전체 실패)."""
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return d
    return x if math.isfinite(x) and abs(x) <= 1e15 else d
''',
    'pricing._vol_zero': r'''
def _vol_zero(v) -> bool:
    """24h 거래량 필드가 '확실히 0' 인가 — 없음·해석 불가는 False(모름 ≠ 0, 종전 동작)."""
    if v is None or v == "":
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f == 0.0
''',
    'rabby._num': r'''
def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and abs(v) != float("inf") else 0.0
''',
    'sale_match._dec': r'''
def _dec(x):
    try:
        d = Decimal(str(x))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None
''',
    'search_index.krw_rate': r'''
def krw_rate(v):
    """fxui1009(U12): 화면이 보낸 원화 환율(원/달러) — 숫자이고 100~10,000 일 때만(그 밖 = 없음 = 종전 달러 대조만)"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if 100 <= x <= 10000 else None
''',
    'view_fut._fin': r'''
def _fin(v):
    """유한 float 또는 None(비유한·형식 오류) — 선물 스냅숏 방어(코덱스 tjperp1 #2)."""
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None
''',
    'view_misc._dec_or0': r'''
def _dec_or0(x) -> Decimal:
    try:
        d9 = Decimal(str(x))
        return d9 if d9.is_finite() else Decimal(0)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)
''',
    'wow2._f': r'''
def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else d
    except (TypeError, ValueError):
        return d
''',
    'xchain_match.D': r'''
def D(x) -> Decimal:
    try:
        d = Decimal(str(x))
        return d if d.is_finite() else Decimal(0)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)
''',
    'xfer_match._dec': r'''
def _dec(s):
    try:
        d = Decimal(str(s).strip())
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None
''',
    'xparts.num': r'''
def num(v):
    """유한한 수 | None (bool 제외)."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
''',
}

KEPT = {
    "bf_engine _num": "0x 16진수 문자열 · ValueError 만 잡음(문자열 아닌 값은 AttributeError 가 올라감) · 양수만",
    "chk_balance _fq": "nan·inf 를 글자('nan'·'inf')로 찍음 — to_float 은 비유한을 기본값으로 바꿈(표시 함수)",
    "core_classify ClassifyMixin._zk_norm.ival": "int(v or 0) — bool(v) 를 try 안에서 부름(__bool__ 예외도 0) · 중첩 함수",
    "evm_base _int_or": "int(v or 0) — 없음·빈 값 = 0 · 깨짐 = dflt(기본값 둘) · OverflowError 도 잡음",
    "exf_net _iso": "숫자 못 읽으면 원래 값 문자열로 ISO 보정 · nan·inf 는 gmtime 예외 — 시각 변환 함수",
    "hl_spot _dec": "TypeError 를 잡지 않음(str() 의 TypeError 가 올라감) · |x| ≤ AMT_MAX 상한",
    "other_assets _num": "쉼표 제거 · 범위 · (값, 오류 문구) 짝 반환 — 입력 검증기",
    "review_progress pid_alive": "int 변환과 os.kill 이 같은 try — 숫자 파서가 아님",
    "sale_match _decimals": "int(str(v).strip()) · 0~255 밖 = default — str() 예외도 잡음(to_int 로 옮기면 try 밖으로 나감)",
    "sellchart _f": "float(str(x).replace(',', '')) — bool 도 None · str() 예외도 잡음 · 큰 정수는 inf → None(OverflowError 아님)",
    "ubfill _dec": "None·''·bool = dflt 인데 깨짐·비유한 = None(기본값 둘)",
    "view_daily DailyMixin._hold_today.fpos": "양수만 + 유효숫자 8자리로 다시 반올림 · 큰 메서드 안 중첩 함수(따로 불러 비교할 수 없음)",
    "view_misc _recon_q": "못 바꿈 = str(q) 그대로 · 비유한 = '0'(기본값 둘) — 표시 형식 함수",
}

chk(num_parse.__all__ == ["to_float", "to_int", "to_dec"], "N0 num_parse.__all__ = to_float · to_int · to_dec", num_parse.__all__)
_np_tree = ast.parse(open(os.path.join(T.SRC, "num_parse.py"), encoding="utf-8").read())
_np_imps = sorted({a.name.split(".")[0] for n in ast.walk(_np_tree) if isinstance(n, ast.Import) for a in n.names} |
                  {n.module.split(".")[0] for n in ast.walk(_np_tree) if isinstance(n, ast.ImportFrom) and n.module})
chk(_np_imps == ["__future__", "decimal", "math"], "N0 num_parse 는 표준 라이브러리(math · decimal)만 가져옴", _np_imps)


def _node(tree, qual):
    body, node = tree.body, None
    for part in qual.split("."):
        node = next((x for x in body if isinstance(x, (ast.FunctionDef, ast.ClassDef)) and x.name == part), None)
        if node is None:
            return None
        body = node.body
    return node


def _src_of(text, qual):
    node = _node(ast.parse(text), qual)
    if node is None:
        return None
    lines = text.split("\n")
    return textwrap.dedent("\n".join(lines[node.lineno - 1:node.end_lineno]))


def _git_show(mod):
    try:
        r = subprocess.run(["git", "-C", T.ROOT, "show", "%s:src/%s.py" % (BASE, mod)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


_base_txt = {m: _git_show(m) for m in sorted({k.split(".", 1)[0] for k in ORIG})}
if all(v is None for v in _base_txt.values()):
    print("SKIP N1 기준 커밋 원문 대조 — git 기록 없음(공개 배치 등)")
else:
    bad1 = [k for k in ORIG if _base_txt.get(k.split(".", 1)[0]) is None or
            _src_of(_base_txt[k.split(".", 1)[0]], k.split(".", 1)[1]) != ORIG[k].strip("\n")]
    chk(not bad1, "N1 ORIG 원문 %d개 = 기준 커밋 %s 원문" % (len(ORIG), BASE[:8]), bad1)


class Boom:
    def __init__(self, exc):
        self.exc = exc

    def _r(self, *a):
        raise self.exc("boom")
    __float__ = __int__ = __index__ = __str__ = __bool__ = __eq__ = __lt__ = __gt__ = __le__ = __ge__ = __abs__ = _r
    __hash__ = object.__hash__

    def __repr__(self):
        return "Boom(%s)" % self.exc.__name__


def _conv_cls(tag, **meth):
    ns = {"__repr__": lambda self, t=tag: "Obj(%s)" % t}
    ns.update(meth)
    return type("Obj_" + tag, (), ns)()


class S(str):
    pass


SENT = _conv_cls("sentinel")
OBJS = [
    _conv_cls("float_nan", __float__=lambda s: float("nan")), _conv_cls("float_inf", __float__=lambda s: float("inf")),
    _conv_cls("float_2.5", __float__=lambda s: 2.5), _conv_cls("int_7", __int__=lambda s: 7),
    _conv_cls("index_7", __index__=lambda s: 7), _conv_cls("str_3.25", __str__=lambda s: "3.25"),
    _conv_cls("str_nan", __str__=lambda s: "nan"), _conv_cls("str_notstr", __str__=lambda s: 5),
    _conv_cls("falsy_int9", __bool__=lambda s: False, __int__=lambda s: 9, __float__=lambda s: 9.0),
    _conv_cls("float_overflow", __float__=lambda s: (_ for _ in ()).throw(OverflowError("x"))),
    object(), [], {}, (), set(), complex(1, 0), b"12", b" 1.5 ", b"abc", bytearray(b"7"),
    S("1.5"), S(" 2 "), S(""), S("nan"),
] + [Boom(e) for e in (ValueError, TypeError, OverflowError, RuntimeError, ZeroDivisionError, InvalidOperation, AttributeError)]
NUMS = [0, 1, -1, 2, 7, 9, 99, 100, 255, 256, 999, 1000, 1666, 9999, 10000, 13333, 99999, 10 ** 6, 10 ** 9, 10 ** 9 + 1,
        1700000000, 10 ** 11, 10 ** 12, 10 ** 12 + 1, 10 ** 13 - 1, 10 ** 13, 10 ** 15, 10 ** 15 + 1, 10 ** 18 - 1, 10 ** 18, 10 ** 20,
        2 ** 53 + 1, 2 ** 63, 10 ** 308, 10 ** 309, 10 ** 400, -10 ** 400, 2 ** 1024, -5, -1000,
        0.0, -0.0, 0.5, -0.5, 1.5, -2.75, 0.1, 1e-9, 1e-8, 5e-9, 99.99, 100.0, 10000.0, 10000.01, 1e9, 1e11, 1e13, 1e15, 1e15 + 0.5,
        1e18, -1e18, 1e300, 1.7e308, -1.7e308, 5e-324, float("nan"), float("inf"), float("-inf"), True, False, None]
STRS = ["", " ", "  \t\n", "0", "-0", "00", "1", "-1", "+5", "1.5", "-2.75", ".5", "5.", "1e3", "1E-3", "1e-8", "1e400", "-1e400",
        "1e-400", "1e999999999", "nan", "NaN", "-nan", "inf", "-inf", "+inf", "Infinity", "-Infinity", "sNaN", "infinity ",
        "1,234", "1,234.5", "12,345,678", ",", "1,,2", " 12 ", "　 7.5  ", "\xa03\xa0", "\x1c4\x1c", "\x85" + "5", "1_000",
        "1__0", "_1", "0x10", "0X1f", "0b11", "12abc", "abc", "None", "True", "1.5e", "٣", "١٢.٥", "1700000000", "1700000000.5",
        "1700000000000", "100", "10000", "99.99", "0.00000001", "0.000000001", "123.45678912", "12.345678901234567890",
        "100000000000000000000", "9999999999999", "10000000000000", "-0.0", "0e5", "1e+2", "  -3  ", "--3", "1 2", "1\x00"]
DECS = [Decimal("1.50"), Decimal("-0"), Decimal("0E-8"), Decimal("1E+2"), Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"),
        Decimal("-Infinity"), Decimal("1e400"), Decimal("1700000000.25"), Decimal("0.00000001"), Decimal("5E-9"), Decimal("123456789.123456789"),
        Fraction(1, 3), Fraction(10 ** 400, 1), Fraction(-7, 2)]
rnd = random.Random(4707)
RAND = []
for _ in range(1200):
    x = rnd.choice([rnd.uniform(-1e6, 1e6), rnd.uniform(-1e16, 1e16), 10 ** rnd.uniform(-12, 20), rnd.randint(-10 ** 14, 10 ** 14)])
    RAND.append(x)
    s = rnd.choice(["%s", "%.3f", "%e", "%d", "{:,}", " %s ", "%s,", "-%s"])
    try:
        RAND.append(s.format(x) if "{" in s else s % x)
    except (TypeError, ValueError):
        RAND.append(str(x))
CORPUS = NUMS + STRS + DECS + OBJS + RAND

EXTRA = {
    "wow2._f": [(), (None,), (-1.0,), (SENT,)],
    "perp_dex._big": [(), (None,), (-1.0,), (SENT,)],
    "perp_dex._f": [(), (None,), (-1.0,), (SENT,)],
    "exf_net._int_or": [(), (None,), (0,), (SENT,)],
    "bf_engine._pol_num": [(5, int, 1, 10), (0.5, float, 0.0, 1.0), (None, float, -1e9, 1e9), (SENT, int, -3, 3)],
}


def outcome(fn, *a):
    try:
        r = fn(*a)
    except Exception as e:   # noqa: BLE001
        return ("err", type(e).__name__)
    return ("ok", type(r).__name__, repr(r))


def _cur(key):
    mod, qual = key.split(".", 1)
    try:
        obj = importlib.import_module(mod)
    except ImportError as e:
        if "No module named" in str(e):
            return None
        raise
    for part in qual.split("."):
        obj = getattr(obj, part)
    return obj


_ns = {}
for _k in sorted(ORIG):
    _m = _k.split(".", 1)[0]
    exec(compile(ORIG[_k].strip("\n"), "<ORIG %s>" % _k, "exec", __future__.annotations.compiler_flag, True),   # noqa: S102
         _ns.setdefault(_m, {"math": math, "re": re, "Decimal": Decimal, "InvalidOperation": InvalidOperation}))


def _old(key):
    mod, qual = key.split(".", 1)
    fn = _ns[mod][qual.split(".")[-1]]
    return fn.__func__ if isinstance(fn, staticmethod) else fn


class _Self:
    def __init__(self, start):
        self.calls = 0
        if start is not _MISSING:
            self._exf_hist_from = start

    def _inval_seq(self):
        self.calls += 1


_MISSING = object()


def _cmp_method(old, cur):
    diff = []
    for start in (_MISSING, None, 5, 1700000000, -3):
        for v in CORPUS:
            a, b = _Self(start), _Self(start)
            ra, rb = outcome(old, a, v), outcome(cur, b, v)
            sa, sb = repr(sorted(vars(a).items())), repr(sorted(vars(b).items()))
            if ra != rb or sa != sb:
                diff.append((repr(v)[:40], ra, rb, sa[:80], sb[:80]))
    return diff


n_ok = n_cmp = 0
skipped = []
for key in sorted(ORIG):
    cur = _cur(key)
    if cur is None:
        skipped.append(key)
        continue
    old = _old(key)
    if key == "core_exf_late.ExfLateMixin._exf_hist_touch":
        diff = _cmp_method(old, cur)
        n = 5 * len(CORPUS)
    else:
        diff, n = [], 0
        for extra in EXTRA.get(key, [()]):
            for v in CORPUS:
                n += 1
                ra, rb = outcome(old, v, *extra), outcome(cur, v, *extra)
                if ra != rb:
                    diff.append((repr(v)[:40], extra[:1], ra, rb))
    n_cmp += n
    n_ok += not diff
    chk(not diff, "N2 %s — 종전 사본 ↔ 지금 함수 %d개 입력 결과·예외 형 같음" % (key, n), diff[:6])
chk(len(ORIG) == 35 and n_ok + len(skipped) == len(ORIG), "N2 바꾼 자리 %d개(공개 배치에 없는 모듈 %d) · 비교 %d번" %
    (len(ORIG), len(skipped), n_cmp), skipped)
def _calls_num_parse(node):
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name) and
               c.func.value.id == "num_parse" and c.func.attr in num_parse.__all__ for c in ast.walk(node))


not_using = []
for key in sorted(ORIG):
    mod, qual = key.split(".", 1)
    p = os.path.join(T.SRC, mod + ".py")
    if not os.path.isfile(p):
        continue
    with open(p, encoding="utf-8") as f:
        node = _node(ast.parse(f.read()), qual)
    if node is None or not _calls_num_parse(node):
        not_using.append(key)
chk(not not_using, "N2 바꾼 자리 %d개 모두 num_parse.to_* 를 부름(원문이 남지 않음)" % len(ORIG), not_using)


try:
    import _arch_py_defs as D   # noqa: E402
except ImportError:
    D = None


def _walk(body, qual, out, mod):
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            q = qual + [n.name]
            if D.is_num_parser(n):
                out.add("%s %s" % (mod, ".".join(q)))
            _walk(n.body, q, out, mod)
        elif isinstance(n, ast.ClassDef):
            _walk(n.body, qual + [n.name], out, mod)
        else:
            for f in ("body", "orelse", "finalbody", "handlers"):
                sub = getattr(n, f, None)
                if isinstance(sub, list):
                    _walk(sub, qual, out, mod)


if D is None:
    print("SKIP N3 남긴 사본 목록 — _arch_py_defs 없음(공개 배치)")
else:
    found = set()
    for root, _dirs, files in os.walk(T.SRC):
        for f in sorted(files):
            if f.endswith(".py") and not f.startswith("num_parse"):
                rel = os.path.relpath(os.path.join(root, f), T.SRC)[:-3].replace(os.sep, ".")
                _walk(ast.parse(open(os.path.join(root, f), encoding="utf-8").read()).body, [], found, rel)
    pub = not os.path.isdir(os.path.join(T.ROOT, "dev"))
    want = set(KEPT) if not pub else {k for k in KEPT if os.path.isfile(os.path.join(T.SRC, k.split(" ")[0] + ".py"))}
    chk(found == want, "N3 남은 숫자 파서 사본 %d개 = KEPT(이유 태그 %d)" % (len(found), len(KEPT)),
        {"새로 생김(이유 태그 없음)": sorted(found - want), "목록에만 있음": sorted(want - found)})
    chk(all(len(v) > 10 for v in KEPT.values()), "N3 KEPT 마다 이유가 적혀 있음")

T.finish()

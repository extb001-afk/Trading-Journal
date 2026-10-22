#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import collections  # noqa: E402
import dataclasses  # noqa: E402
import datetime as _dt  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import threading  # noqa: E402
from decimal import Decimal  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "golden_v2.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/golden_v2.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import golden_v2 as G  # noqa: E402
import _golden_fp as P  # noqa: E402


def code_ast(path):
    with open(path, encoding="utf-8") as f:
        t = ast.parse(f.read())
    if t.body and isinstance(t.body[0], ast.Expr) and isinstance(t.body[0].value, ast.Constant):
        t.body = t.body[1:]
    return ast.dump(t, include_attributes=False)


chk(code_ast(os.path.join(TOOLS, "golden_v2.py")) == code_ast(os.path.join(T.HERE, "_golden_fp.py")),
    "V1 시험 안 사본(_golden_fp) = 도구(golden_v2) 코드 AST 같음(닫힌 형 표·재귀·정규화 표 동일)")


def fp(o, enc=None, path="x", norm=None):
    return (enc or G.Encoder()).fingerprint(path, o, norm)["d"]


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Slot:
    __slots__ = ("a", "b")

    def __init__(self, a, b=None):
        self.a = a
        if b is not None:
            self.b = b


@dataclasses.dataclass(eq=False)
class DC:
    m: dict
    it: list


class FrozenSub(_dt.datetime):
    pass


utc, kst = _dt.timezone.utc, _dt.timezone(_dt.timedelta(hours=9))
pairs = [
    (Decimal("1.0"), Decimal("1.00"), "Decimal 끝 0"), (Decimal("1E+2"), Decimal("100"), "Decimal 지수"),
    (1, 1.0, "int ↔ float"), ({"a": 1, "b": 2}, {"b": 2, "a": 1}, "dict 삽입 순서"),
    (Obj(x=Decimal("2.0")), Obj(x=Decimal("2.00")), "객체 칸 Decimal"), (Slot(1), Slot(1, 2), "__slots__ 칸"),
    (DC({"q": Decimal("1")}, [1]), DC({"q": Decimal("1.0")}, [1]), "dataclass 안 dict 값"),
    (_dt.datetime(2026, 1, 1, tzinfo=utc), _dt.datetime(2026, 1, 1, 9, tzinfo=kst), "datetime 시간대(같은 순간 · 다른 표기)"),
    (FrozenSub(2026, 1, 1), FrozenSub(2026, 1, 2), "datetime 하위형 값"), (_dt.timedelta(seconds=1), _dt.timedelta(seconds=2), "timedelta"),
    ((1, 2), [1, 2], "tuple ↔ list"), (collections.defaultdict(list), collections.defaultdict(dict), "defaultdict 기본값 함수"),
    (float("nan"), "nan", "NaN ↔ 글자"), (b"ab", bytearray(b"ab"), "bytes ↔ bytearray"), (True, 1, "bool ↔ int"),
]
od1, od2 = collections.OrderedDict([("a", 1), ("b", 2)]), collections.OrderedDict([("a", 1), ("b", 2)])
od2.move_to_end("a")


class Mangled:
    __slots__ = ("__k",)

    def __init__(self, k):
        self.__k = k


pairs += [(od1, od2, "OrderedDict move_to_end 순서"), (Mangled(1), Mangled(2), "'__x' 슬롯(이름 바꿈) 값"),
          ({"q": Decimal("1")}, {"q": "D:1"}, "Decimal ↔ 'D:' 글자")]
bad = [why for a, b, why in pairs if fp(a) == fp(b)]
chk(not bad, "V2 값 구분(형 이름으로 안 줄임 · %d쌍)" % len(pairs), bad)

s1, s2 = {"x", "y", "z", (1, 2)}, set()
for v in ((1, 2), "z", "y", "x"):
    s2.add(v)
shared = [1, 2]
e = G.Encoder()
a1 = e.fingerprint("a", {"k": shared, "j": shared})["d"]
a2 = e.fingerprint("b", {"k": shared, "j": shared})["d"]
chk(fp(s1) == fp(s2) and fp(Obj(m={"a": [Decimal("1")]})) == fp(Obj(m={"a": [Decimal("1")]})) and a1 == a2,
    "V3 같은 값 = 같은 지문(set 순서 무관 · 다른 객체 같은 내용 · 최상위마다 지나간 집합 새로)")

cyc = {"a": 1}
cyc["self"] = cyc
lst = [1]
two = {"p": lst, "q": lst}
eF = G.Encoder(full=True)
v_cyc = eF.fingerprint("c", cyc)["v"]
v_two = eF.fingerprint("t", two)["v"]
chk(v_cyc[3][1][1] == ["ref", ""] and v_two[3][1][1] == ["ref", ".p"] and fp(two) != fp({"p": [1], "q": [1]}),
    "V4 재귀 안전 — 자기 참조·같은 객체 두 번 = ref(최상위 값 안 상대 경로) · 공유와 사본은 다른 지문", (v_cyc, v_two))


class LenSpy(list):
    calls = 0

    def __len__(self):
        LenSpy.calls += 1
        return 99


ls = LenSpy([1, 2])
r_len = G.Encoder().fingerprint("l", ls)
chk(r_len.get("n") == 2 and LenSpy.calls == 0, "V3 길이 = 내장 구현(하위형이 재정의한 __len__ 은 안 부름 · 부작용 0)", (r_len, LenSpy.calls))

import subprocess  # noqa: E402
import tempfile  # noqa: E402
fake = tempfile.mkdtemp(prefix="tj_gv2_")
try:
    open(os.path.join(fake, ".golden_copy"), "w").close()
    gout = os.path.join(os.path.expanduser("~"), "tj_golden", "out")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_BASE"] = fake
    bad_pairs = [("w50zz.json", "W50ZZ.json"), ("w50zz.json", "w50zz.v2.JSON.x"), ("w50zz.v2.json", "w50zz2.v2.json"),
                 ("w50zz.json", "w50zz.json")]
    res = []
    for o9, v9 in bad_pairs:
        pr = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "golden_dump.py"), "--src", T.SRC, "--now", "1", "--out",
                             os.path.join(gout, o9), "--v2", os.path.join(gout, v9)], capture_output=True, text=True, timeout=60, env=env)
        res.append((o9, v9, pr.returncode, "--v2 는" in pr.stderr))
finally:
    shutil.rmtree(fake, ignore_errors=True)
chk(all(rc != 0 and hit for _o, _v, rc, hit in res),
    "V9 golden_dump --v2 이름 검사 — 대소문자만 다른 같은 이름 · '.v2.json' 아님 · 옛 이름이 .v2.json = 빌드 전에 거부(옛 골든을 안 덮음)", res)

class Builder:
    pass


e5 = G.Encoder(builder_cls=Builder)
conn = sqlite3.connect(":memory:")
try:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 1 AS a, 'x' AS b").fetchone()
    r5 = e5.fingerprint("h", {"lk": threading.Lock(), "c": conn, "m": os, "sb": Builder(), "f": len, "row": row})
finally:
    conn.close()
chk(not r5.get("fail") and sorted(e5.opaque) == [["h.c", "Connection"], ["h.lk", "lock"], ["h.m", "module"], ["h.sb", "Builder"]],
    "V5 표식 — 잠금·연결·모듈·빌더 = opaque (경로, 형) · callable·sqlite3.Row = 값(opaque 아님)", e5.opaque)

e6 = G.Encoder()
r_c = e6.fingerprint("m", {"mv": memoryview(b"x")})
deep = cur = []
for _ in range(G.MAX_DEPTH + 5):
    nxt = []
    cur.append(nxt)
    cur = nxt
r_d = e6.fingerprint("d", deep)


class BadTz(_dt.tzinfo):
    def utcoffset(self, dt):
        raise ValueError("x")


r_x = e6.fingerprint("z", {"tz": BadTz()})
chk(r_c.get("fail") and r_d.get("fail") and r_x.get("fail") and len(e6.fails) == 3 and ["m.mv", "memoryview"] in e6.opaque
    and any(o[1] == "<deep>" for o in e6.opaque),
    "V6 닫힌 형 표 밖(C 상태)·깊이 초과·직렬화 중 예외 = 실패로 남김(fails · opaque · 덤프를 멈추지 않음)", (e6.fails, e6.opaque[:3]))

NI = [(("ino",), "drop", "inode")]
n1, n2, n3 = fp({"ino": 1, "off": 5}, norm=NI), fp({"ino": 2, "off": 5}, norm=NI), fp({"ino": 2, "off": 6}, norm=NI)
SK = G.norm_for("hidden._lpx_cache")
sk_same = fp({"_db": 1, 5: [1], 7: [2]}, norm=SK) == fp({"_db": 1, 7: [2], 5: [1]}, norm=SK) != fp({"_db": 1, 7: [3], 5: [1]}, norm=SK)


class _TopK:
    __slots__ = ("th", "seq")


def topk(th, seq):
    x = _TopK()
    x.th, x.seq = th, seq
    return x


heap_same = fp(topk([(1, -2, "a"), (3, -1, "b")], [1, 2])) == fp(topk([(3, -1, "b"), (1, -2, "a")], [1, 2]))
heap_diff = fp(topk([(1, -2, "a")], [1, 2])) != fp(topk([(1, -2, "a")], [2, 1])) and fp(topk([(1, -2, "a")], [1])) != fp(topk([(2, -2, "a")], [1]))
eb = G.Encoder(base=("/r/runs/t.1",))
base_same = eb.fingerprint("p", {"f": "/r/runs/t.1/state/x.json"})["d"] == G.Encoder(base=("/r/runs/t.2",)).fingerprint(
    "p", {"f": "/r/runs/t.2/state/x.json"})["d"] != G.Encoder(base=("/r/runs/t.2",)).fingerprint("p", {"f": "/r/runs/t.2/state/y.json"})["d"]
whole = G.Encoder().fingerprint("hidden._built_sig", [1], G.norm_for("hidden._built_sig"))["d"] == \
    G.Encoder().fingerprint("hidden._built_sig", [2], G.norm_for("hidden._built_sig"))["d"]
chk(n1 == n2 and n2 != n3 and whole and fp([[9, 1]], norm=G.norm_for("hidden._flow_cache_hit")) ==
    fp([[8, 1]], norm=G.norm_for("hidden._flow_cache_hit")) and sk_same and heap_same and heap_diff and base_same,
    "V7 정규화 표 — 지정 칸만(inode·입력 서명 = <norm> · 메모 캐시 = 열쇠 순서 무관 · _TopK 힙 = 원소 다중집합 · 동결 사본 경로 = <BASE>) · "
    "다른 칸 차이는 그대로", (sk_same, heap_same, heap_diff, base_same))


@dataclasses.dataclass
class Books:
    tax_rows: list
    lp_events: list


@dataclasses.dataclass
class Ctx:
    conn: object
    now: float


bk, cx = Books([1], [2]), Ctx(threading.Lock(), 1.5)
scope = {"books": bk, "ctx": cx, "tax_rows": bk.tax_rows, "G": {"g": 1}}


class RR:
    def as_old_names(self):
        return dict(scope)


e8a, e8b = G.Encoder(), G.Encoder()
c1 = G.capture_scope(e8a, scope, ["G", "tax_rows", "nope"], ["tax_rows", "lp_events"], ["conn", "now"])
c2 = G.capture_scope(e8b, RR(), ["G", "tax_rows", "nope"], ["tax_rows", "lp_events"], ["conn", "now"])
chk(c1 == c2 and c1["nope"] == {"t": "<missing>"} and c1["tax_rows"] == c1["books.tax_rows"]
    and set(c1) == {"G", "tax_rows", "nope", "books.tax_rows", "books.lp_events", "ctx.conn", "ctx.now"}
    and e8a.opaque == [["boundary.ctx.conn", "lock"]],
    "V8 경계 펼침 — dict·as_old_names 같은 결과 · books./ctx. 필드 · 없는 이름 <missing> · 같은 객체 지문 재사용", (c1, e8a.opaque))
T.finish()

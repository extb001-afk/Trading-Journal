#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import Reader  # noqa: E402

import ast  # noqa: E402
import dataclasses  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pickle  # noqa: E402

import chain_event  # noqa: E402
import config  # noqa: E402
import core  # noqa: E402
import inbox_rec as R  # noqa: E402
import paths  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
J = lambda r: json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode("utf-8")   # noqa: E731
CONSTS = {n: getattr(R, n) for n in ("EVM_TX", "SOL_TX", "CHAIN_DELTA", "EX_SNAPSHOT", "EX_FILLS", "EX_ORDER_TRADES", "EXF_FILL_RETIME",
                                     "EXF_FILLS", "EXF_LATE_CYCLE", "CORRUPT")}


def parse(rel):
    return ast.parse(open(os.path.join(T.ROOT, rel), encoding="utf-8").read(), rel)


ci = parse("src/core_inbox.py")
cr = next(b for c in ci.body if isinstance(c, ast.ClassDef) for b in c.body if isinstance(b, ast.FunctionDef) and b.name == "_consume_record")
pname = cr.args.args[1].arg
order, bad = [], []
node = next((n for n in cr.body if isinstance(n, ast.If)), None)
while isinstance(node, ast.If):
    t = node.test
    ok = (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq) and isinstance(t.left, ast.Call)
          and isinstance(t.left.func, ast.Attribute) and t.left.func.attr == "get" and isinstance(t.left.func.value, ast.Name)
          and t.left.func.value.id == pname and len(t.left.args) == 1 and not t.left.keywords
          and isinstance(t.left.args[0], ast.Constant) and t.left.args[0].value == "kind")
    cmp = t.comparators[0] if isinstance(t, ast.Compare) else None
    if ok and isinstance(cmp, ast.Attribute) and isinstance(cmp.value, ast.Name) and cmp.value.id == "inbox_rec" and cmp.attr in CONSTS:
        order.append(CONSTS[cmp.attr])
    elif ok and isinstance(cmp, ast.Attribute) and isinstance(cmp.value, ast.Name) and cmp.value.id == "chain_event" and cmp.attr == "KIND":
        order.append(chain_event.KIND)
    else:
        bad.append((node.lineno, ast.unparse(t)))
    node = node.orelse[0] if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If) else None
chk(not bad, "A1 소비 분기 조건 = rec.get(\"kind\") == inbox_rec 상수(또는 chain_event.KIND) — 글자 그대로·다른 꼴 0", bad)
chk(order == list(R.KINDS), "A1 분기 차례 = inbox_rec.KINDS 차례(빠짐·남음 0)", (order, list(R.KINDS)))
chk(all(isinstance(x, ast.If) for x in cr.body[:1]) and node is None, "A1 분기 = if/elif 사슬 하나(디스패처·분기 표 0)")

uses = {}
for dp, dn, fns in os.walk(T.SRC):
    dn[:] = sorted(d for d in dn if d != "__pycache__")
    for f in sorted(fns):
        if not f.endswith(".py") or f == "inbox_rec.py":
            continue
        rel = os.path.relpath(os.path.join(dp, f), T.ROOT)
        tr = parse(rel)
        for x in ast.walk(tr):
            if isinstance(x, ast.Import) and any(a.name == "inbox_rec" for a in x.names):
                uses.setdefault(rel, set()).add("import")
            elif isinstance(x, ast.ImportFrom) and x.module == "inbox_rec":
                uses.setdefault(rel, set()).add("from")
            elif isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == "inbox_rec":
                uses.setdefault(rel, set()).add(x.attr)
chk(set(uses) == {"src/core_inbox.py"} and "from" not in uses["src/core_inbox.py"],
    "A2 src 에서 inbox_rec 을 쓰는 곳 = core_inbox 하나(생산자 0 → 재시작 범위 = tj-core)", sorted(uses))
chk(uses.get("src/core_inbox.py", set()) - {"import"} <= set(CONSTS), "A2 core 가 쓰는 inbox_rec 이름 = 종류 상수만(소비 길 from_dict 0)",
    sorted(uses.get("src/core_inbox.py", set())))

rt = parse("src/inbox_rec.py")
imps = set()
for x in ast.walk(rt):
    if isinstance(x, ast.Import):
        imps |= {a.name.split(".")[0] for a in x.names}
    elif isinstance(x, ast.ImportFrom):
        imps.add((x.module or "").split(".")[0])
chk(imps <= {"dataclasses", "typing", "chain_event", "__future__"}, "A3 계약 모듈 import = 표준 라이브러리(dataclasses·typing) + chain_event 만", sorted(imps))
chk(R.CHAIN_DELTA is chain_event.KIND and not any(isinstance(x, ast.Constant) and x.value == chain_event.KIND for x in ast.walk(rt)),
    "A3 CHAIN_DELTA = chain_event.KIND(import · 글자 사본 0)")
nlines = len(open(os.path.join(T.SRC, "inbox_rec.py"), encoding="utf-8").read().splitlines())
chk(nlines <= 400, "A3 계약 모듈 ≤ 400줄", nlines)
chk(set(R.__all__) >= set(CONSTS) | {"KINDS", "from_dict"} | {c.__name__ for c in R.KINDS.values()}, "A3 __all__ = 상수·클래스·KINDS·from_dict", R.__all__)
shape = []
for k, cls in R.KINDS.items():
    p = cls.__dataclass_params__
    if not (p.frozen and not p.eq and not p.repr):
        shape.append((k, "모양"))
    if cls.KIND != k or "kind" not in cls.REQUIRED or not set(cls.REQUIRED) <= set(cls.keys()) or cls.keys()[0] != "kind":
        shape.append((k, "KIND·REQUIRED"))
    if {f.name for f in dataclasses.fields(cls)} - set(cls.keys()) != {"extra", "_order"}:
        shape.append((k, "extra·_order"))
chk(not shape and len(R.KINDS) == 10, "A3 10종 = frozen·eq·repr 끔 · KIND = KINDS 열쇠 · 필수 ⊆ 계약 · 필수에 kind · 칸 extra·_order", shape)
chk(R.required_keys(R.EVM_TX) == ("kind", "chain", "txhash", "snapshot") and R.required_keys(R.SOL_TX) == ("kind", "txhash")
    and R.required_keys(R.CHAIN_DELTA) == ("kind", "chain", "tx_uid", "ts")
    and all(R.required_keys(k) == ("kind",) for k in R.KINDS if k not in (R.EVM_TX, R.SOL_TX, R.CHAIN_DELTA)),
    "A3 필수 = 지금 소비자가 rec[...] 로 읽는 열쇠(evm 3 · sol 1 · 새 체인 3 · 나머지 0)", {k: R.required_keys(k) for k in R.KINDS})

if os.path.isfile(os.path.join(TOOLS, "inbox_kinds.py")):
    sys.path.insert(0, TOOLS)
    import inbox_kinds as K  # noqa: E402
    tab, src9 = K.table(T.ROOT), "inbox_kinds 지금 표"
else:
    bp = os.path.join(T.HERE, "arch_baseline", "inbox_kinds.json")
    tab, src9 = (json.load(open(bp, encoding="utf-8")) if os.path.isfile(bp) else None), "기준선 json(공개판 배치)"
if tab is None:
    chk(True, "A4 생산·소비 표 없음(도구·기준선 둘 다 없는 배치) · 건너뜀")
else:
    chk(tab["kinds"] == list(R.KINDS), "A4 계약 표(%s) 종류·차례 = KINDS" % src9, tab["kinds"])
    miss_c = {k: sorted(set(tab["consumers"][k]["reads"]) - set(R.contract_keys(k))) for k in tab["kinds"]}
    chk(not any(miss_c.values()), "A4 소비 처리기가 레코드에서 읽는 열쇠 ⊆ 계약(%s)" % src9, miss_c)
    miss_p = {}
    for k in tab["kinds"]:
        for p in tab["producers"][k]:
            m = sorted(set(p["keys"]) - set(R.contract_keys(k)))
            if m:
                miss_p.setdefault(k, []).append((p["file"], p["func"], m))
    chk(not miss_p, "A4 생산 dict 글자 최상위 열쇠 ⊆ 그 종류 계약(%s · ** 펼침 0)" % src9, miss_p)
    allk = set().union(*(set(R.contract_keys(k)) for k in R.KINDS))
    chk(all(a["key"] in allk for a in tab["appended"]), "A4 생산 뒤 덧붙이는 열쇠 ⊆ 계약(%s)" % src9, sorted({a["key"] for a in tab["appended"]} - allk))
    chk(chain_event.VERSION == 1 and all(set(v) <= {"1", "chain_event.VERSION"} for v in tab["v"].values()), "A4 판 번호 v = 1(모든 생산 자리)", tab["v"])

U = {"한글": "값 ✓", "f": [0.1, 1e-300, 1.0000000000000002, -0.0, 2.5e+20], "big": 2 ** 70, "b": [True, False, None], "n": {"z": 1, "a": {"q": []}}}


def sample(cls, i):
    return {k: ("" if k == "kind" else {"i": i, "k": k, "u": U}) for k in cls.keys()}


def variants(cls):
    full = sample(cls, 1)
    full["kind"] = cls.KIND
    keys = list(full)
    old = {k: full[k] for k in cls.REQUIRED}
    yield "선언 차례", full
    yield "거꾸로", {k: full[k] for k in reversed(keys)}
    yield "모르는 열쇠 앞·가운데·끝", dict([("zz_new", U)] + [(k, full[k]) for k in keys[:2]] + [("extra", 1), ("_order", [2])]
                                       + [(k, full[k]) for k in keys[2:]] + [("끝", "한")])
    yield "옛 판(필수만)", old
    yield "옛 판 + 모르는 열쇠", dict(old, later={"x": 1.5})


rt_bad, val_bad, err_bad = [], [], []
for k, cls in R.KINDS.items():
    for nm, d in variants(cls):
        o = R.from_dict(d)
        back = o.to_dict()
        if J(back) != J(d) or list(back) != list(d) or type(o) is not cls:
            rt_bad.append((k, nm))
        if any(back[x] is not d[x] for x in d):
            val_bad.append((k, nm))
        pk = pickle.loads(pickle.dumps(o))
        if J(pk.to_dict()) != J(d) or type(pk) is not cls:
            rt_bad.append((k, nm, "pickle"))
    for req in cls.REQUIRED:
        d = dict(sample(cls, 2), kind=cls.KIND)
        d.pop(req)
        for fn in (R.from_dict, cls.from_dict):
            try:
                fn(d)
                err_bad.append((k, req, fn.__qualname__, "안 막힘"))
            except KeyError as e:
                if e.args != (req,):
                    err_bad.append((k, req, fn.__qualname__, repr(e)))
            except Exception as e:  # noqa: BLE001
                err_bad.append((k, req, fn.__qualname__, repr(e)))
chk(not rt_bad, "B1 종류마다 5꼴(차례·거꾸로·모르는 열쇠·옛 판) to_dict 직렬화 바이트·열쇠 차례 = 원래 · pickle 뒤도 같음", rt_bad)
chk(not val_bad, "B1 값 그대로(형 변환·복사 0 — 같은 객체)", val_bad)
chk(not err_bad, "B2 필수 열쇠 빠짐(kind 포함) = KeyError(그 이름) — 모듈 from_dict·클래스 from_dict 둘 다", err_bad)

o = R.from_dict({"kind": "evm_tx", "chain": "eth", "txhash": "0xa", "snapshot": {}, "extra": 7})
try:
    o.chain = "x"
    frozen = False
except dataclasses.FrozenInstanceError:
    frozen = True
chk(frozen and o.extra == {"extra": 7} and o._order == ("kind", "chain", "txhash", "snapshot", "extra"), "B3 고정(대입 = FrozenInstanceError) · 'extra' 열쇠 = extra 칸에 보존")
errs = []
for bad_in, want in (([1], TypeError), ("x", TypeError), (None, TypeError), ({}, KeyError), ({"kind": "zz"}, ValueError), ({"kind": []}, ValueError),
                     ({"kind": {}}, ValueError), ({"kind": 1}, ValueError), ({"kind": None}, ValueError)):
    try:
        R.from_dict(bad_in)
        errs.append((repr(bad_in), "안 막힘"))
    except want:
        pass
    except Exception as e:  # noqa: BLE001
        errs.append((repr(bad_in), repr(e)))
try:
    R.SolTx.from_dict({"kind": "evm_tx", "txhash": "x"})
    errs.append(("종류 다름", "안 막힘"))
except ValueError:
    pass
chk(not errs, "B4 dict 아님 = TypeError · kind 없음 = KeyError · 모르는 종류(글자 아닌 kind 포함) = ValueError · 클래스와 종류 다름 = ValueError", errs)
dflt = {k: {f: getattr(R.from_dict({x: ("" if x != "kind" else k) for x in R.required_keys(k)}), f) for f in R.contract_keys(k)
            if f not in R.required_keys(k)} for k in R.KINDS}
want_nonnull = {R.EVM_TX: {"wallets": []}, R.SOL_TX: {"wallets": [], "deltas": []}, R.CHAIN_DELTA: {"network": "mainnet", "deltas": [], "fees": []},
                R.EX_SNAPSHOT: {"exchange": "upbit"}}
got_nonnull = {k: {f: v for f, v in d.items() if v is not None} for k, d in dflt.items()}
chk(got_nonnull == {k: want_nonnull.get(k, {}) for k in R.KINDS}, "B5 없는 선택 열쇠 = 소비자 .get 기본(wallets·deltas·fees = [] · network = mainnet · ex exchange = upbit · 그 밖 None)",
    got_nonnull)
a1 = R.from_dict({"kind": "sol_tx", "txhash": "a"})
a2 = R.from_dict({"kind": "sol_tx", "txhash": "b"})
chk(a1.wallets is not a2.wallets and a1 != a2 and R.from_dict({"kind": "sol_tx", "txhash": "a"}) != a1, "B5 목록 기본값 객체마다 따로 · eq 끔(같은 내용도 다른 객체)")
mk = R.EvmTx(kind=R.EVM_TX, chain="eth", txhash="0xb", snapshot={"tx": {}}, ts=5, extra={"zz": 1})
chk(list(mk.to_dict()) == ["kind", "chain", "txhash", "snapshot", "ts", "zz"], "B6 직접 만든 객체(_order 빔) = 필수 + 기본값과 다른 선택 + extra", mk.to_dict())

real = os.environ.get("TJ_TEST_FROZEN_INBOX") or os.path.join(os.path.expanduser("~"), "tj_golden", "base0", "state", "inbox")
if os.path.isdir(real) and os.path.isfile(os.path.join(TOOLS, "inbox_census.py")):
    sys.path.insert(0, TOOLS)
    import inbox_census as C  # noqa: E402
    cen = C.census(real, T.ROOT)
    chk(cen["lines"] > 0 and cen["inbox_rec"] == {} and cen["roundtrip_diff"] == {} and cen["corrupt"] == 0,
        "C1 내부 게이트: 동결 사본 inbox 전 줄 from_dict → to_dict 직렬화 바이트 = 원래(다름 0)",
        {"lines": cen["lines"], "inbox_rec": cen["inbox_rec"], "rt": cen["roundtrip_diff"]})
else:
    print("SKIP C1 동결 사본 inbox(또는 inbox_census 도구) 없음 — 내부 게이트 줄 건너뜀", flush=True)

c = core.Core(config.load_config())
c.conn.commit()
PZ, DMQ = paths.state("poison.jsonl"), paths.state("pending_dm.jsonl")


def lines(p):
    return [json.loads(x) for x in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def feed(rec):
    p0, d0, n0 = len(lines(PZ)), len(lines(DMQ)), c.conn.total_changes
    ret = c._drain_stream("evm", Reader([rec]), 0, 0)
    off = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='evm'").fetchone()
    got = {"ret": ret, "poison": lines(PZ)[p0:], "dm": lines(DMQ)[d0:], "off": tuple(off) if off else None, "changes": c.conn.total_changes - n0}
    c.conn.execute("DELETE FROM inbox_offsets")
    c.conn.commit()
    return got


HEAD = "🔴 거래 기록 1건을 처리하지 못해 따로 보관했어요\n원본은 그대로 있어요 — 같은 일이 계속되면 상태 패널에서 원인을 보세요.\n"
H = "0x" + "ab" * 32
NOATTR = "AttributeError(\"'%s' object has no attribute 'get'\")"
D = [("evm txhash 없음", {"v": 1, "kind": "evm_tx", "chain": "eth", "snapshot": {"tx": {}}, "wallets": [_ingest.W]}, "KeyError('txhash')", None, "txhash"),
     ("evm snapshot 없음", {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": H, "wallets": [_ingest.W]}, "KeyError('snapshot')", H, "snapshot"),
     ("evm chain 없음", {"v": 1, "kind": "evm_tx", "txhash": H, "snapshot": {"tx": {}}}, "KeyError('chain')", H, "chain"),
     ("sol txhash 없음", {"v": 1, "kind": "sol_tx", "chain": "sol", "slot": 1, "ts": 1700000000, "wallets": [_ingest.SOLW]}, "KeyError('txhash')", None, "txhash"),
     ("새 체인 tx_uid 없음", {"v": 1, "kind": "chain_delta_tx", "chain": "tron", "ts": 1700000000, "txhash": "aa"},
      "ContractError('tx_uid 형식 오류(영숫자·._-+/= 220자 이하)')", "aa", "tx_uid"),
     ("목록", [1, 2], NOATTR % "list", None, None), ("글자", "x", NOATTR % "str", None, None), ("정수", 7, NOATTR % "int", None, None),
     ("null", None, NOATTR % "NoneType", None, None), ("실수", 1.5, NOATTR % "float", None, None)]
dbad = []
for nm, rec, err, txh, req in D:
    g = feed(rec)
    if not (g["ret"] == (0, 1, 1) and g["off"] == (0, 1) and len(g["poison"]) == 1 and g["poison"][0]["err"] == err and g["poison"][0]["rec"] == rec
            and len(g["dm"]) == 1 and g["dm"][0]["kind"] == "POISON" and g["dm"][0]["text"] == HEAD + err[:140] and g["dm"][0]["payload"] == {"txhash": txh}):
        dbad.append((nm, g))
    try:
        R.from_dict(rec)
        dbad.append((nm, "계약 from_dict 안 막힘"))
    except KeyError as e:
        if req is None or e.args != (req,):
            dbad.append((nm, "계약 KeyError", repr(e)))
    except TypeError:
        if req is not None:
            dbad.append((nm, "계약 TypeError"))
chk(not dbad, "D1 필수 열쇠 빠진·dict 아닌 레코드 = 격리 1줄(err 글·원본) · DM 글·payload · 오프셋 전진 = 기준 트리와 같은 값 · 계약도 같은 열쇠 이름으로 거부", dbad)

E = [("kind 목록", {"kind": []}), ("kind 사전", {"kind": {}}), ("kind 숫자", {"kind": 1}), ("kind null", {"kind": None}), ("kind 없음", {}),
     ("kind 참", {"kind": True}), ("모르는 종류", {"v": 1, "kind": "zz_unknown"})]
ebad = []
for nm, rec in E:
    g = feed(rec)
    if not (g["ret"] == (0, 1, 1) and g["off"] == (0, 1) and len(g["poison"]) == 1 and g["poison"][0]["rec"] == rec
            and str(g["poison"][0]["err"]).startswith("ValueError(") and "모르는 인박스 레코드 종류" in str(g["poison"][0]["err"])
            and len(g["dm"]) == 1 and g["dm"][0]["kind"] == "POISON" and g["changes"] == 1):
        ebad.append((nm, g))
chk(not ebad, "E1 글자 아닌 kind·kind 없음·모르는 종류 = 어느 분기에도 안 듦 → 격리 1줄(원문 보존) · DM 1 · 원장 변경 = 오프셋 한 줄 · 전진", ebad)
c.conn.close()

T.finish()

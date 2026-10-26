#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import NamedTuple


sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(HERE, "arch_baseline")
ENV = {k: os.environ.get(k, "")
       for k in ("TJ_TEST_ARCH_STALE_FAIL", "TJ_TEST_REQUIRE_NODE", "TJ_TEST_ARCH_BASE_REF")}
UPDATE = "python3 public/tests/_arch_ratchet.py --update-lower"


class Spec(NamedTuple):
    name: str
    kind: str
    fields: tuple
    title: str
    doc: str
    fix: dict


_JS = "JS 원본 = web/**/*.js(fonts 제외 — 지금 web/v2/*.js·web/support.js) · web/**/*.html 인라인 <script>(정의 = _arch_js 머리)"
SPECS = {s.name: s for s in [
    Spec("js_size", "max", ("lines", "bytes"), "JS·HTML 파일 크기(600줄·48KB 넘는 파일)",
         "web/ 의 .js·.html 중 600줄 또는 48,000바이트 넘는 파일 — 줄·바이트 상한(늘면 실패 · 새 파일은 600줄·48KB 이하).",
         {"*": "파일을 늘리지 말고 나눠라(목표 600줄·48KB · 하드 800줄)"}),
    Spec("js_funcs", "bag", ("lines",), "JS 함수 길이(80줄 넘는 함수 · 모듈 감싸개 제외)",
         "80줄 넘는 JS 함수(블록 몸통 · 모듈 감싸개 제외) — 열쇠 = 감싸는 함수 이름 사슬(파일 이름 없음). " + _JS,
         {"*": "함수를 쪼개라(목표 60줄 · 하드 80줄) — 기준선 올리기 금지"}),
    Spec("js_longlines", "max", ("n",), "JS 140자 넘는 줄 수(파일별)",
         "파일별 140자(코드포인트) 넘는 JS 줄 수 — .js 는 모든 줄 · .html 은 <script> 안만.",
         {"*": "줄을 140자 안으로 나눠라"}),
    Spec("js_esc", "max", ("n",), "esc 사본 수('&amp;' 리터럴 · 파일별)",
         "코드 속 값이 정확히 '&amp;' 인 문자열·템플릿 리터럴 수 = HTML 이스케이프 구현 수(목표 전체 1벌).",
         {"*": "새 이스케이프 함수를 만들지 말고 그 파일의 기존 esc(또는 공용 esc)를 써라"}),
    Spec("js_1384", "max", ("n",), "1384 리터럴 수(JS·파이썬 · 파일별)",
         "원화 환율 고정 대체값 1384 를 숫자로 다시 쓴 자리(JS 숫자 토큰 + src·tools 파이썬 NUMBER 토큰) — 목표 = 상수 1(서버 → 화면).",
         {"*": "1384 를 새로 쓰지 말 것 — 서버는 acct_norm.DEFAULT_KRW_USD · 화면은 서버가 준 환율(D.rate) 사용"}),
    Spec("hyg_tests", "max", ("str_checks", "str_neg", "patch_attr", "patch_call", "patch_foreign", "round_labels"),
         "시험 위생(파일별 · 소스 문자열 검사·몽키패치·회차 라벨)",
         "public/tests 파일별 위생 지표 상한(정의 = _arch_hyg 머리) — exempt 줄 = 소스 문자열 검사를 세지 않는 정적 분석(lint) 시험(총괄 승인).",
         {"str_checks": "소스 원문 문자열 검사 대신 동작(함수 호출·출력)으로 검사하라(정적 분석 시험이면 exempt 줄 — 총괄 승인)",
          "str_neg": "'X 가 없어야' 소스 검사는 코드가 옮겨지면 공허해진다 — 동작으로 검사하라",
          "patch_attr": "모듈 속성 바꿔 끼우기를 늘리지 말고 인자·주입(포트)으로 넘겨라",
          "patch_call": "setattr·patch_moved 바꿔 끼우기를 늘리지 말고 인자·주입(포트)으로 넘겨라",
          "patch_foreign": "정의 모듈이 아닌 곳을 바꿔 끼우지 말 것 — 정의 모듈(→ 뒤 이름)을 바꾸거나 T.patch_moved 를 써라",
          "round_labels": "결과 줄 이름에 회차(날짜·코덱스 번호·세션)를 넣지 말고 동작을 적어라(이력은 커밋·CHANGELOG)"}),
    Spec("hyg_checks", "min", ("n",), "시험 검사 수(파일별 하한 + 총합 바닥)",
         "시험 파일(test_*.py)별 검사 수(chk·감싸개 호출 자리 + assert 문) 하한과 총합 바닥 — 줄면 실패(시험 약화) · 지운·합친 파일은 총합으로.",
         {"*": "검사를 지우지 말 것 — 합치거나 옮겼으면 같은 수의 검사가 다른 시험에 있어야 한다"}),
    Spec("hyg_names", "set", (), "회차 이름 시험 파일(목록 동결)",
         "이름에 날짜·세션·리뷰 번호가 든 시험 파일 목록 — 새로 생기면 실패(이름은 동작으로).",
         {"*": "시험 파일 이름을 동작으로 지어라(날짜·세션·리뷰 번호 금지)"}),
    Spec("hyg_tools", "set", (), "도구 위생(원장 쓰는 1회성 도구·날짜 붙은 도구 · 목록 동결)",
         "tools/ 최상위: ledger_writers = 원장 표에 쓰는 도구 · dated = 이름에 날짜 붙은 파일 — 새로 생기면 실패 · why = 이름으로 부르는 곳(이름 고정 사유).",
         {"ledger_writers": "1회성 원장 고치기 도구를 새로 만들지 말 것(9막 번호 마이그레이션 · 그 전엔 총괄 승인)",
          "dated": "도구 이름에 날짜를 붙이지 말 것(동작 이름 · 이력은 커밋)"}),
    Spec("hyg_srctext", "set", (), "src 원문을 여는 동작 시험(목록 동결 · 아키텍처 시험 분류)",
         "test_*.py 중 이름이 test_arch_ 가 아닌데 src 원문을 여는 파일(정의 = _arch_hyg_cls 머리) — 이 목록 + test_arch_* = 아키텍처 시험"
         "(run_all --kind arch) · 새로 생기면 실패.",
         {"*": "소스 글을 읽어 단언하지 말고 동작(함수 호출·출력)으로 검사하라 — 원문 검사가 목적인 정적 분석 시험이면 이름을 test_arch_ 로"}),
    Spec("hyg_untested", "set", (), "직접 임포트하는 시험이 없는 src 모듈(목록 동결)",
         "src 모듈 중 그것을 직접 임포트하는 test_*.py 가 없는 것(정의 = _arch_hyg_cls 머리) — 새 모듈이 들어오면 실패 · 기존 것은 채우지 않아도 됨.",
         {"*": "새 모듈엔 그 모듈을 직접 임포트해 동작을 보는 시험 하나를 같이 넣어라"}),
    Spec("hyg_docs", "max", ("bytes",), "README 크기",
         "public/README.md 바이트 상한(목표 30KB + docs/ — 줄이기만).",
         {"*": "README 를 늘리지 말고 docs/ 로 옮겨라(README 내용을 읽는 시험 목록은 test_arch_hyg 안내 줄)"}),
]}


def repo_layout() -> bool:
    return os.path.basename(os.path.dirname(HERE)) == "public" and os.path.isfile(os.path.join(HERE, "..", "..", "src", "version.py"))


def _root() -> str:
    return os.path.abspath(os.path.join(HERE, "..", "..") if repo_layout() else os.path.join(HERE, ".."))


def _doc(items=None, total=None, exempt=None, meta=None) -> dict:
    return {"items": items if items is not None else {}, "total": total, "exempt": exempt or {}, "meta": meta or {}}


def current_js(root: str) -> tuple[dict, dict]:
    import _arch_js as J
    m = J.metrics(root)
    lim = J.LIMITS
    size = {p: dict(v) for p, v in m["size"].items() if v["lines"] > lim["file_lines"] or v["bytes"] > lim["file_bytes"]}
    funcs: dict[str, list] = {}
    for f in m["fns"]:
        if not f["wrapper"] and f["lines"] > lim["fn_lines"]:
            funcs.setdefault(f["qual"], []).append({"file": f["file"], "lines": f["lines"], "start": f["start"]})
    n1384 = dict(m["n1384"])
    n1384.update(J.py_1384(root))
    n = lambda d: {k: {"n": v} for k, v in d.items() if v}  # noqa: E731
    return {"js_size": _doc(size), "js_funcs": _doc(funcs), "js_longlines": _doc(n(m["long"])),
            "js_esc": _doc(n(m["esc"])), "js_1384": _doc(n(n1384))}, m


def current_hyg(root: str, tests_dir: str, readme: str, exempt: dict | None = None) -> tuple[dict, dict]:
    import _arch_hyg as H
    import _arch_hyg_tools as HT
    th = H.test_hygiene(tests_dir, os.path.join(root, "src"))
    fields = SPECS["hyg_tests"].fields
    tests, checks = {}, {}
    for fn, r in th.items():
        if fn.startswith("test_"):
            checks[fn] = {"n": r["checks"]}
        vals = {f: r[f] for f in fields if r[f] and not (exempt and fn in exempt and f.startswith("str_"))}
        if vals:
            tests[fn] = dict(vals, _at={f: r["lines"][f][:6] for f in vals})
    names = {"round_named_tests": {fn: None for fn in th if fn.startswith("test_") and H.round_named(fn)}}
    tools = HT.tools_hygiene(root)
    sizes = HT.docs_sizes(root, readme)
    docs = {os.path.relpath(readme, root).replace(os.sep, "/"): {"bytes": sizes["readme"]}}
    cur = {"hyg_tests": _doc(tests, exempt=dict(exempt or {})), "hyg_checks": _doc(checks, total=sum(v["n"] for v in checks.values())),
           "hyg_names": _doc(names), "hyg_tools": _doc({k: {x: None for x in v} for k, v in tools.items()}), "hyg_docs": _doc(docs)}
    cur.update(current_cls(root, tests_dir))
    return cur, {"tests": th, "tools": tools, "sizes": sizes}


def current_cls(root: str, tests_dir: str) -> dict:
    import _arch_hyg_cls as HC
    return {"hyg_srctext": _doc({"src_readers": {fn: None for fn in HC.src_readers(tests_dir)}}),
            "hyg_untested": _doc({"modules": {m: None for m in HC.untested(tests_dir, os.path.join(root, "src"))}})}


def parse(spec: Spec, text: str) -> dict:
    doc = _doc()
    for i, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            raise ValueError(f"{spec.name}.jsonl {i}번 줄이 JSON 이 아님(병합 충돌 표식?): {line[:80]}") from None
        if "_doc" in rec:
            doc["meta"] = {k: v for k, v in rec.items() if k not in ("_doc", "kind", "spec")}
            continue
        if "total" in rec:
            doc["total"] = int(rec["total"])
        elif "exempt" in rec:
            doc["exempt"][rec["exempt"]] = rec.get("why", "")
        elif spec.kind == "max":
            doc["items"][rec["key"]] = {f: int(rec.get(f, 0)) for f in spec.fields}
        elif spec.kind == "bag":
            doc["items"].setdefault(rec["key"], []).append({"file": rec.get("file", ""), "lines": int(rec["lines"])})
        elif spec.kind == "set":
            doc["items"].setdefault(rec["set"], {})[rec["key"]] = rec.get("why")
        else:
            doc["items"][rec["key"]] = {"n": int(rec["n"])}
    return doc


def dump(spec: Spec, doc: dict) -> str:
    out = [json.dumps(dict(doc.get("meta") or {}, _doc=spec.doc, kind=spec.kind, spec=spec.name), ensure_ascii=False, sort_keys=True)]
    if doc.get("total") is not None:
        out.append(json.dumps({"total": doc["total"]}))
    out += [json.dumps({"exempt": k, "why": w}, ensure_ascii=False) for k, w in sorted(doc.get("exempt", {}).items())]
    recs = []
    for k, v in doc["items"].items():
        if spec.kind in ("max", "min"):
            vals = {f: v[f] for f in spec.fields if v.get(f)}
            if vals:
                recs.append(((k,), dict(key=k, **vals)))
        elif spec.kind == "bag":
            recs += [((k, -e["lines"], e["file"]), {"key": k, "file": e["file"], "lines": e["lines"]}) for e in v]
        else:
            for x, why in v.items():
                recs.append(((k, x), dict({"set": k, "key": x}, **({"why": why} if why else {}))))
    out += [json.dumps(r, ensure_ascii=False) for _s, r in sorted(recs, key=lambda t: t[0])]
    return "\n".join(out) + "\n"


def _path(name: str) -> str:
    return os.path.join(BASE_DIR, name + ".jsonl")


GROWTH_FILE = "hyg_growth.jsonl"
_WHY_FILLER = re.compile(r"허용|성장|allow(?:ed)?|[\W\d_]+", re.I)


def _why_ok(why) -> bool:
    return isinstance(why, str) and len(why.strip()) >= 20 and len(_WHY_FILLER.sub("", why)) >= 4


def parse_growth(text: str) -> tuple[list, list]:
    rows, bad = [], []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        try:
            g = json.loads(ln)
        except ValueError:
            bad.append(ln.strip()[:160])
            continue
        if isinstance(g, dict) and "_doc" in g:
            continue
        sp = SPECS.get(g.get("spec")) if isinstance(g, dict) else None
        to = g.get("to") if isinstance(g, dict) else None
        if (sp is not None and sp.kind == "max" and g.get("f") in sp.fields and isinstance(g.get("key"), str) and g["key"].strip()
                and isinstance(to, int) and not isinstance(to, bool) and to >= 0
                and all(isinstance(g.get(x), str) and g[x].strip() for x in ("why", "commit")) and _why_ok(g["why"])):
            rows.append(g)
        else:
            bad.append(ln.strip()[:160])
    return ([] if bad else rows), bad


def load_growth() -> tuple[list, list]:
    p = os.path.join(BASE_DIR, GROWTH_FILE)
    if os.path.islink(p):
        return [], [GROWTH_FILE + " 이 심볼릭 링크 — 실제 파일이어야 함"]
    if not os.path.isfile(p):
        return [], []
    with open(p, encoding="utf-8") as f:
        return parse_growth(f.read())


def grown(spec: Spec, base: dict, growth) -> tuple[dict, list[str]]:
    rows = [g for g in growth or () if g["spec"] == spec.name]
    if not rows:
        return base, []
    items = {k: dict(v) for k, v in base["items"].items()}
    for g in rows:
        it = items.setdefault(g["key"], {f: 0 for f in spec.fields})
        it[g["f"]] = max(int(it.get(g["f"], 0) or 0), g["to"])
    return dict(base, items=items), [f"{g['key']}: {g['f']} ≤ {g['to']} — {g['why']} ({g['commit']})" for g in rows]


def load(name: str) -> dict | None:
    p = _path(name)
    if os.path.islink(BASE_DIR) or os.path.islink(p):
        raise ValueError(f"기준선 {'폴더' if os.path.islink(BASE_DIR) else name + '.jsonl'} 이 심볼릭 링크 — 실제 파일이어야 함")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return parse(SPECS[name], f.read())


def _fix(spec: Spec, field: str) -> str:
    return spec.fix.get(field) or spec.fix.get("*", "")


def _at(v: dict, f: str) -> str:
    lines = (v.get("_at") or {}).get(f) or []
    return f" (예: 줄 {'·'.join(map(str, lines))})" if lines else ""


def _cmp_max(spec, cur, base, bad, stale):
    for k, v in sorted(cur["items"].items()):
        b = base["items"].get(k)
        if b is None:
            first = next((f for f in spec.fields if v.get(f)), spec.fields[0])
            vals = " · ".join(f"{f} {v.get(f, 0)}" for f in spec.fields if v.get(f))
            bad.append(f"{k}: 새 위반({vals}){_at(v, first)} — {_fix(spec, first)}")
            continue
        for f in spec.fields:
            c, o = v.get(f, 0), b.get(f, 0)
            if c > o:
                bad.append(f"{k}: {f} {o}→{c} 늘어남{_at(v, f)} — {_fix(spec, f)}")
            elif c < o:
                stale.append(f"{k}: {f} {o}→{c} 줄었음")
    stale += [f"{k}: 기준선에 있는데 이제 한도 안이거나 없어짐" for k in sorted(set(base["items"]) - set(cur["items"]))]


def _cmp_bag(spec, cur, base, bad, stale):
    for k in sorted(set(cur["items"]) | set(base["items"])):
        c = sorted(cur["items"].get(k, []), key=lambda e: -e["lines"])
        b = sorted(base["items"].get(k, []), key=lambda e: -e["lines"])
        for i, e in enumerate(c):
            where = f"{e['file']}:{e['start']}" if e.get("start") else e["file"]
            if i >= len(b):
                bad.append(f"{where} {k} {e['lines']}줄: 새 위반 — {_fix(spec, '*')}")
            elif e["lines"] > b[i]["lines"]:
                bad.append(f"{where} {k}: {b[i]['lines']}→{e['lines']}줄 늘어남 — {_fix(spec, '*')}")
            elif e["lines"] < b[i]["lines"]:
                stale.append(f"{where} {k}: {b[i]['lines']}→{e['lines']}줄 줄었음")
        stale += [f"{e['file']} {k}: {e['lines']}줄 → 한도 안이 되거나 없어짐" for e in b[len(c):]]


def _cmp_set(spec, cur, base, bad, stale):
    for k in sorted(set(cur["items"]) | set(base["items"])):
        c, b = cur["items"].get(k, {}), base["items"].get(k, {})
        bad += [f"{k}: 새 항목 {x} — {_fix(spec, k)}" for x in sorted(set(c) - set(b))]
        stale += [f"{k}: {x} 없어짐" for x in sorted(set(b) - set(c))]


def _cmp_min(spec, cur, base, bad, stale):
    for k, v in sorted(cur["items"].items()):
        b = base["items"].get(k)
        floor = b["n"] if b else 0
        if v["n"] < floor:
            bad.append(f"{k}: 검사 수 {floor}→{v['n']} 줄어듦(시험 약화) — {_fix(spec, '*')}")
        elif v["n"] > floor:
            stale.append(f"{k}: 검사 수 {floor}→{v['n']} 늘었음(바닥 올리기)")
    gone = sorted(set(base["items"]) - set(cur["items"]))
    if gone:
        stale.append(f"지운·옮긴 시험 파일 {len(gone)}개(총합으로 봄): {', '.join(gone[:8])}")
    ct, bt = cur.get("total") or 0, base.get("total") or 0
    if ct < bt:
        bad.append(f"검사 수 총합 {bt}→{ct} 줄어듦 — 지운·합친 시험의 검사를 다른 시험으로 옮겨라")
    elif ct > bt:
        stale.append(f"검사 수 총합 {bt}→{ct} 늘었음(바닥 올리기)")


def _succ(spec: Spec, side: dict, base: dict, work: dict) -> tuple[dict, dict, list[str], dict]:
    if spec.name != "js_esc":
        return side, base, [], {}
    import _sec_succession as SUCC
    n = lambda d: {"n": {k: v.get("n", 0) for k, v in d["items"].items()}}  # noqa: E731
    v = SUCC.judge("js_esc", "n", n(side), n(base), n(work))
    doc = lambda d, items: dict(d, items={k: {"n": x} for k, x in items.items()})  # noqa: E731
    bad = [f"{k}: 새 위반(n {c} · 기준 {b}) — 8막 승계 거부: {why}" for k, c, b, why in v.bad]
    return doc(side, v.side), doc(base, v.base), bad, v.granted


def _renamed(spec: Spec, doc: dict, present: set, absent: set | None = None) -> dict:
    if not spec.name.startswith("hyg_"):
        return doc
    import _arch_hyg_rename as RN
    return RN.renamed(spec, doc, present, absent=absent)


def judge_now(spec: Spec, cur: dict, base: dict, growth=()) -> tuple[list[str], list[str], dict]:
    base = grown(spec, _renamed(spec, base, set(cur["items"])), growth)[0]
    side, base2, bad, succ = _succ(spec, cur, base, cur)
    bad0, stale = compare(spec, side, base2)
    return bad + bad0, stale, succ


def judge_ref(spec: Spec, base: dict, old: dict, cur: dict) -> list[str]:
    old = _renamed(spec, old, set(base["items"]) | set(cur["items"]), set(cur["items"]))
    new2, old2, bad, _succ_keys = _succ(spec, base, old, cur)
    return bad + increases(spec, new2, old2, set(cur["items"]))


def lower(spec: Spec, cur: dict, base: dict) -> dict:
    base = _renamed(spec, base, set(cur["items"]))
    new = tighten(spec, cur, base)
    new["items"].update({k: {"n": x} for k, x in _succ(spec, cur, base, cur)[3].items()})
    return new


def compare(spec: Spec, cur: dict, base: dict) -> tuple[list[str], list[str]]:
    bad: list[str] = []
    stale: list[str] = []
    {"max": _cmp_max, "bag": _cmp_bag, "set": _cmp_set, "min": _cmp_min}[spec.kind](spec, cur, base, bad, stale)
    bad += [f"정적 분석 예외(exempt)에 새 파일 {x}(총괄 승인 필요)" for x in sorted(set(cur.get("exempt", {})) - set(base.get("exempt", {})))]
    return bad, stale


def tighten(spec: Spec, cur: dict, base: dict) -> dict:
    out = _doc(exempt=dict(base.get("exempt", {})))
    for k, b in base["items"].items():
        c = cur["items"].get(k)
        if spec.kind == "max" and c is not None:
            out["items"][k] = {f: min(b.get(f, 0), c.get(f, 0)) for f in spec.fields}
        elif spec.kind == "bag" and c:
            cs, bs = sorted(c, key=lambda e: -e["lines"]), sorted(b, key=lambda e: -e["lines"])
            out["items"][k] = [{"file": e["file"], "lines": min(e["lines"], o["lines"])} for e, o in zip(cs, bs)]
        elif spec.kind == "set" and c is not None:
            out["items"][k] = {x: b[x] for x in b if x in c}
        elif spec.kind == "min" and c is not None:
            out["items"][k] = {"n": max(b["n"], c["n"])}
    if spec.kind == "min":
        out["items"].update({k: {"n": v["n"]} for k, v in cur["items"].items() if k not in base["items"]})
        out["total"] = max(base.get("total") or 0, cur.get("total") or 0)
    return out


def freeze(spec: Spec, cur: dict, base: dict | None) -> dict:
    base = base or _doc()
    items = {}
    for k, v in cur["items"].items():
        if spec.kind == "bag":
            items[k] = [{"file": e["file"], "lines": e["lines"]} for e in v]
        elif spec.kind == "set":
            items[k] = {x: (base["items"].get(k, {}).get(x) or w) for x, w in v.items()}
        else:
            items[k] = {f: v.get(f, 0) for f in spec.fields}
    return _doc(items, cur.get("total"), dict(base.get("exempt", {})) or dict(cur.get("exempt", {})))


def increases(spec: Spec, new: dict, ref: dict, present: set | None = None) -> list[str]:
    fix = "기준선 허용치를 올렸음 — 되돌리고 코드를 고쳐라(올리기는 총괄이 refactor 에서만)"
    bad = compare(spec._replace(fix={"*": fix}), new, ref)[0]
    if spec.kind == "min" and present is not None:
        bad += [f"{k}: 바닥 줄을 지웠음(파일은 그대로 있음) — {fix}" for k in sorted(set(ref["items"]) - set(new["items"])) if k in present]
    return bad


class Ref(NamedTuple):
    sha: str | None
    top: str | None
    why: str
    error: bool


def _git(root: str, *args: str) -> str | None:
    g = shutil.which("git")
    if not g:
        return None
    try:
        p = subprocess.run([g, "-C", root, *args], capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def base_ref(root: str) -> Ref:
    want = ENV["TJ_TEST_ARCH_BASE_REF"].strip()
    if want.lower() in ("skip", "none", "off", "0"):
        return Ref(None, None, f"TJ_TEST_ARCH_BASE_REF={want} — 명시적으로 건너뜀", False)
    how = " — TJ_TEST_ARCH_BASE_REF=<커밋·브랜치> 로 기준을 주거나 skip"
    if not shutil.which("git"):
        return Ref(None, None, "git 없음" + how, True)
    top = _git(root, "rev-parse", "--show-toplevel")
    if not top:
        return Ref(None, None, "git 저장소 아님" + how, True)
    if want:
        sha = _git(root, "rev-parse", "--verify", "--quiet", want + "^{commit}")
        if sha:
            return Ref(sha, top, f"TJ_TEST_ARCH_BASE_REF={want}", False)
        return Ref(None, top, f"TJ_TEST_ARCH_BASE_REF={want} 를 못 찾음" + how, True)
    sha = _git(root, "merge-base", "HEAD", "refactor")
    return Ref(sha, top, "merge-base(HEAD, refactor)", False) if sha else Ref(None, top, "merge-base(HEAD, refactor) 못 구함" + how, True)


def ref_doc(ref: Ref, name: str) -> dict | None:
    if os.path.islink(HERE) or os.path.islink(os.path.dirname(HERE)):
        raise ValueError("시험 폴더(public/tests)가 심볼릭 링크 — 실제 폴더여야 함")
    rel = "public/tests/arch_baseline/" + name + ".jsonl"
    listed = _git(ref.top, "ls-tree", "--name-only", ref.sha, "--", rel)
    if listed is None:
        raise ValueError(f"git ls-tree 실패({ref.sha[:8]})")
    if not listed:
        return None
    text = _git(ref.top, "show", f"{ref.sha}:{rel}")
    if text is None:
        raise ValueError(f"git show 실패({ref.sha[:8]}:{rel})")
    return parse(SPECS[name], text)


def rename_ref_check(ref: Ref, git=None) -> list[str]:
    import _arch_hyg_rename as RN
    git = git or _git
    name = RN.RENAME_FILE
    try:
        rels = git(ref.top, "ls-tree", "--name-only", ref.sha, "--", "public/tests/")
        listed = git(ref.top, "ls-tree", "--name-only", ref.sha, "--", "public/tests/arch_baseline/" + name)
        if rels is None or listed is None or not rels:
            raise ValueError(f"git ls-tree 실패·빈 결과({ref.sha[:8]}:public/tests/)")
        raw = git(ref.top, "show", f"{ref.sha}:public/tests/arch_baseline/{name}") if listed else ""
        if raw is None:
            raise ValueError(f"git show 실패({ref.sha[:8]}:{name})")
        ref_table = json.loads(raw).get("renames") if raw else {}
        if not isinstance(ref_table, dict):
            raise ValueError(f"기준 커밋 {name} 꼴 틀림(renames 가 dict 아님)")
        return RN.rename_ref_errors(RN.renames(), ref_table, {os.path.basename(r) for r in rels.split("\n") if r})
    except ValueError as e:
        return [str(e)]


def check(T, root: str, cur: dict) -> None:
    ref = base_ref(root)
    if ref.error:
        T.chk(False, "기준선 변조 검사 기준(merge-base · TJ_TEST_ARCH_BASE_REF) 정함", ref.why)
    if ref.sha and any(n in ("hyg_tests", "hyg_checks") for n in cur):
        errs = rename_ref_check(ref)
        T.chk(not errs, f"시험 이름 승계 표가 {ref.why} {ref.sha[:8]} 대비 줄만 더함 · 이름 바꾸기만", errs[:10])
    growth, gbad = load_growth()
    T.chk(not gbad, f"성장 사유 표({GROWTH_FILE}) 줄 = 상한 지표 spec · 열쇠 key · 칸 f · 절대 상한 to(0 이상 정수) · 사유 why(20자 이상 · 빈말만 금지) · "
          "커밋 commit", gbad[:5])
    if ref.sha and growth:
        old9 = _git(ref.top, "show", f"{ref.sha}:public/tests/arch_baseline/{GROWTH_FILE}")
        seen9 = {json.dumps(g, sort_keys=True, ensure_ascii=False) for g in parse_growth(old9 or "")[0]}
        for g in growth:
            if g["spec"] in cur and json.dumps(g, sort_keys=True, ensure_ascii=False) not in seen9:
                print(f"  검수 [{GROWTH_FILE}] {ref.why} {ref.sha[:8]} 뒤 새 줄: {g['spec']} {g['key']} {g['f']} ≤ {g['to']} — {g['why']} ({g['commit']})")
    for name in sorted(cur):
        spec = SPECS[name]
        try:
            base = load(name)
        except ValueError as e:
            T.chk(False, f"[{name}] 기준선 파일 읽힘", str(e))
            continue
        if base is None:
            T.chk(False, f"[{name}] 기준선 파일 있음(arch_baseline/{name}.jsonl)", "없음 — 총괄이 --freeze 로 만든다")
            continue
        try:
            bad, stale, succ = judge_now(spec, cur[name], base, growth)
        except ValueError as e:
            T.chk(False, f"[{name}] 시험 이름 승계 표 읽힘", str(e))
            continue
        T.chk(not bad, f"[{name}] {spec.title} — 새 위반·나빠짐 0", bad[:40])
        for x in grown(spec, base, growth)[1]:
            print(f"  허용 [{name}] 성장 사유 표: {x}")
        if succ:
            print(f"  안내 [{name}] 8막 승계 인정(_sec_succession): {', '.join(sorted(succ))}")
        if stale:
            print(f"  안내 [{name}] 좋아진 값 {len(stale)}건 — 기준선 조이기: {UPDATE}")
            for x in stale[:8]:
                print("    " + x)
            if ENV["TJ_TEST_ARCH_STALE_FAIL"] == "1":
                T.chk(False, f"[{name}] 좋아진 값이 기준선에 반영됨(TJ_TEST_ARCH_STALE_FAIL=1)", stale[:20])
        if ref.sha:
            try:
                old = ref_doc(ref, name)
            except ValueError as e:
                T.chk(False, f"[{name}] {ref.why} 기준선 읽힘(변조 검사)", str(e))
                continue
            if old is None:
                print(f"  ({name}: {ref.why} {ref.sha[:8]} 에 기준선 없음 — 처음 생기는 커밋이라 변조 검사 통과)")
            else:
                try:
                    inc = judge_ref(spec, base, old, cur[name])
                except ValueError as e:
                    T.chk(False, f"[{name}] 시험 이름 승계 표 읽힘(변조 검사)", str(e))
                    continue
                T.chk(not inc, f"[{name}] 기준선 허용치가 {ref.why} {ref.sha[:8]} 보다 늘지 않음", inc[:20])
    if not ref.sha and not ref.error:
        print(f"  (기준선 변조 검사 건너뜀: {ref.why})")


_CHECKED: list = []


def checked_with(root: str) -> tuple[str, list]:
    if not _CHECKED:
        import _arch_js_acorn as JA
        _CHECKED.append(JA.verify(root))
    return _CHECKED[0]


def main(argv: list[str]) -> int:
    mode = next((a for a in argv if a.startswith("--")), "--show")
    want = [a for a in argv if not a.startswith("--")]
    if mode not in ("--show", "--update-lower", "--freeze") or any(w not in SPECS for w in want):
        print(__doc__)
        return 2
    if not repo_layout():
        print("저장소 배치가 아님(공개판 배치) — 기준선이 없어 할 일 없음")
        return 1
    root = _root()
    readme = os.path.join(root, "public", "README.md")
    old_tests = load("hyg_tests")
    cur = dict(current_js(root)[0])
    cur.update(current_hyg(root, HERE, readme, old_tests["exempt"] if old_tests else None)[0])
    names = want or sorted(cur)
    os.makedirs(BASE_DIR, exist_ok=True)
    import _arch_hyg_tools as HT
    for name in names:
        spec, base = SPECS[name], load(name)
        if mode == "--show":
            bad, stale = compare(spec, cur[name], grown(spec, base or _doc(), load_growth()[0])[0])
            print(f"[{name}] 실패 {len(bad)} · 좋아짐 {len(stale)}" + ("" if base else " (기준선 없음)"))
            for x in (bad + stale)[:12]:
                print("   " + x)
            continue
        if base is None and mode == "--update-lower":
            print(f"[{name}] 기준선 없음 — --freeze(총괄)로 처음 만든다")
            continue
        new = lower(spec, cur[name], base) if mode == "--update-lower" else freeze(spec, cur[name], base)
        if name == "hyg_tools":
            pins = HT.tool_pins(root, sorted({x for xs in new["items"].values() for x in xs}))
            new["items"] = {k: {x: pins[x] for x in xs} for k, xs in new["items"].items()}
        if name.startswith("js_"):
            note, diff = checked_with(root)
            if diff:
                print(f"[{name}] 안 씀 — 파이썬 측정이 acorn 과 다름(토크나이저를 먼저 고쳐라): {diff[:2]}")
                continue
            new["meta"] = {"checked_with": note}
        text = dump(spec, new)
        old_text = None
        if os.path.isfile(_path(name)):
            with open(_path(name), encoding="utf-8") as f:
                old_text = f.read()
        if text != old_text:
            with open(_path(name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"[{name}] 기준선 씀 — {sum(1 for _ in text.splitlines()) - 1}줄")
        else:
            print(f"[{name}] 그대로")
        if mode == "--update-lower":
            left = compare(spec, cur[name], new)[0]
            if left:
                print(f"[{name}] 여전히 실패 {len(left)}건 — 기준선은 안 올림(코드를 고쳐라): {left[0][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not all(os.path.isfile(os.path.join(TOOLS, f)) for f in ("web_inv.mjs", "js_proof.mjs", "jsstr_map.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/web_inv.mjs·js_proof.mjs·jsstr_map.py) 없음 · 건너뜀")
    T.finish()
import _xss_abs as X  # noqa: E402

NODE = T.node_bin("화면 보안 도구(acorn) 시험")


def run(args, timeout=180):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    return p.returncode, p.stdout, p.stderr


SYN = os.path.join(T.TMP, "syn")
os.makedirs(os.path.join(SYN, "web", "v2"))
for fn9, body9 in {
    "app.js": "function f(el, n) {\n  el[`innerHTML`] = n;\n  el['outerHTML'] = n;\n  Reflect.set(el, 'innerHTML', n);\n  Object.assign(el, { innerHTML: n });\n"
              "  el['insertAdjacentHTML']('beforeend', n);\n  const f9 = el.insertAdjacentHTML;\n  f9.call(el, 'x', n);\n  const g9 = el['insertAdjacentHTML'];\n"
              "  el.setAttribute('srcdoc', n);\n  const w9 = document.write;\n  const r9 = el.innerHTML;\n  el.setAttribute('style', 'x');\n  document.createElement('style');\n  img.src = 'https://cdn.jsdelivr.net/x';\n"
              "  [el.innerHTML] = [n];\n  ({ v: el.outerHTML } = { v: n });\n  for (el.innerHTML of [n]) {}\n  el.setAttribute(`style`, 'x');\n"
              "  document.createElement(`style`);\n  const \\u0061b9 = 1;\n}\n",
    "index.html": "<html><body><div style=\"a\"></div><style>.a{}</style><script>v.innerHTML = 1;</script></body></html>\n",
}.items():
    with open(os.path.join(SYN, "web", "v2", fn9), "w", encoding="utf-8") as f9:
        f9.write(body9)

if NODE:
    for tree, tag in ((T.ROOT, "작업 트리"), (SYN, "합성 트리")):
        out = os.path.join(T.TMP, "web_inv_%s.json" % ("work" if tree == T.ROOT else "syn"))
        rc, so, se = run([NODE, "--expose-internals", os.path.join(TOOLS, "web_inv.mjs"), "--root", tree, "--json", out])
        chk(rc == 0 and os.path.isfile(out), "V1 %s web_inv 실행(구문 오류 0)" % tag, (rc, se[-300:], so[-300:]))
        if not os.path.isfile(out):
            continue
        with open(out, encoding="utf-8") as f9:
            inv = json.load(f9)
        rows = inv["rows"]
        py = X.census(tree)

        def cnt(rs):
            o = {}
            for r in rs:
                o[r["file"]] = o.get(r["file"], 0) + 1
            return dict(sorted(o.items()))

        def cnt_n(rs):
            o = {}
            for r in rs:
                o[r["file"]] = o.get(r["file"], 0) + int(r["detail"].get("n", 1))
            return dict(sorted(o.items()))

        pairs = {
            "HTML 싱크": (cnt(rows["sink"]), X.by_file(py["sink"])),
            "동적 <style>(createElement·문자열 태그)": (cnt([r for r in rows["dynstyle"] if r["detail"]["kind"] != "setAttribute(style)"]), X.by_file(py["dynstyle"])),
            "setAttribute('style')": (cnt([r for r in rows["dynstyle"] if r["detail"]["kind"] == "setAttribute(style)"]), X.by_file(py["setattr_style"])),
            "app.js img.src(로고)": (cnt([r for r in rows["url"] if r["file"] == "app.js" and r["detail"]["kind"] == "src="]), X.by_file(py["logo_src"])),
            "cdn.jsdelivr.net 상수": (cnt(rows["cdn"]), X.by_file(py["cdn"])),
            "마크업 style 속성": (cnt_n([r for r in rows["html"] if r["detail"]["kind"] == "style 속성"]), X.by_file(py["markup_style"])),
            "<style> 블록": (cnt([r for r in rows["html"] if r["detail"]["kind"] == "<style> 블록"]), X.by_file(py["style_block"])),
            "식별자 이스케이프": (cnt(rows["ident_escape"]), X.by_file(py["ident_escape"])),
        }
        for what, (a, b) in pairs.items():
            chk(a == b, "V1 %s %s 파일별 수: acorn(web_inv) = 파이썬(_xss_abs)" % (tag, what), {"acorn": a, "파이썬": b})
        chk(inv["summary"]["errors"] == 0 and inv["summary"]["sink_total"] == len(py["sink"]) and len(py["sink"]) > 0,
            "V1 %s 합계 같음 · 구문 오류 0 · 싱크 자리를 찾음(조사기 고장 아님)" % tag, inv["summary"]["sink_total"])
    rc, so, se = run([NODE, "--expose-internals", os.path.join(TOOLS, "js_proof.mjs"), "--selftest"])
    bad = [ln for ln in so.splitlines() if ln.startswith("XX ")]
    chk(rc == 0 and "자체 시험 통과" in so and not bad, "V2 js_proof 자체 시험 — 합성 짝 전부 기대대로", (rc, bad[:5], se[-300:]))
    chk(so.count("기대 PASS") >= 5 and so.count("기대 FAIL") >= 20, "V2 짝 수(PASS ≥ 5 · FAIL ≥ 20 — 반례가 줄면 실패)",
        (so.count("기대 PASS"), so.count("기대 FAIL")))
    v2 = os.path.join(T.ROOT, "web", "v2")
    for mode, extra in (("subst", []), ("unfold", ["--fn", "derive"])):
        for fn in ("app.js", "search.js") if mode == "subst" else ("app.js",):
            p = os.path.join(v2, fn)
            rc, so, se = run([NODE, "--expose-internals", os.path.join(TOOLS, "js_proof.mjs"), mode, "--base", p, "--new", p] + extra)
            chk(rc == 0 and so.startswith("PASS "), "V3 js_proof %s %s 같은 파일끼리 = 통과(바뀐 자리 0)" % (mode, fn), (rc, so[-300:], se[-300:]))
    rc, so, se = run([NODE, "--expose-internals", os.path.join(TOOLS, "codemod_tjdom.mjs"), "--selftest"])
    chk(rc == 0 and "SELFTEST 통과" in so, "V3b codemod_tjdom 자체 시험 — 바꾼 글 = js_proof subst 증명 · 값 쓰는 자리·+=·부작용 대상·지역 TJDOM 은 그대로", (rc, so[-300:], se[-300:]))
else:
    chk(not T.node_required(), "node 없음 — V1~V3 건너뜀(TJ_TEST_REQUIRE_NODE=1 이면 실패)")

rc, so, se = run([sys.executable, "-I", os.path.join(TOOLS, "jsstr_map.py"), "--selftest"])
chk(rc == 0 and "자체 시험 통과" in so, "V4 jsstr_map 자체 시험", (rc, so[-400:], se[-400:]))
mp = os.path.join(T.TMP, "jsstr_map.json")
rc, so, se = run([sys.executable, "-I", os.path.join(TOOLS, "jsstr_map.py"), "--root", T.ROOT, "--json", mp])
doc = json.load(open(mp, encoding="utf-8")) if rc == 0 and os.path.isfile(mp) else {}
sm = doc.get("summary", {})
chk(rc == 0 and sm.get("tests", 0) >= 20 and sm.get("cut", 0) >= 10, "V4 실제 트리 표: 화면 원문을 읽는 시험 · 자르기 표식이 있음", {k: sm.get(k) for k in ("tests", "rows", "cut")})
chk(rc == 0 and sm.get("rows", 0) > 0 and sm.get("miss", 0) * 10 <= sm.get("rows", 0), "V4 못 찾음 ≤ 10%(표식 → 소스 줄 이어짐)", {k: sm.get(k) for k in ("rows", "miss")})
cuts = [r for r in doc.get("rows", []) if r["kind"] == "cut" and r["test"] == "test_fx_src_ui.py"]
chk(any(s["file"] == "app.js" and s["end"] > s["line"] for r in cuts for s in r["sites"]), "V4 derive 를 자르는 시험(test_fx_src_ui) → app.js 줄 범위", [r["sites"] for r in cuts][:2])
T.finish()

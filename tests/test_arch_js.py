#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch_ratchet as R  # noqa: E402
import _harness as T  # noqa: E402

import time  # noqa: E402
import _arch_js as J  # noqa: E402
import _arch_js_acorn as JA  # noqa: E402

chk = T.chk
t0 = time.time()

SNIP = r"""(function () {
  const a = 10 / 2 / 1, re = /[/{]+/g, half = x => x / re.lastIndex;
  // 주석 속 { function nope() { 와 '따옴표
  /* 블록 주석 } */ const s = '{ "}" \' ', t = `a ${[1, 2].map(v => { return `${v}}`; })} b ${'}'}`;
  function decl(p) {
    if (p) { return /}/.test(p) ? 1 : 0; }
    return p;
  }
  const obj = { m(x) { return x; }, get g() { return 1; }, k: function () { return 2; } };
  el.addEventListener('click', e => {
    const esc = v => String(v).replace(/&/g, '&amp;');
    return 1384 + 1_384.0 * 0;
  });
  class C { static async run() { return `${a}`; } }
})();
"""
fns = J.find_functions(J.tokenize(SNIP))
J.qualify(fns, J.nlines(SNIP))
got = [(f["qual"], f["start"], f["end"], f["kind"], f["wrapper"]) for f in fns]
want = [("<wrapper>", 1, 15, "expr", True), ("map()", 4, 4, "arrow", False), ("decl", 5, 8, "decl", False),
        ("m", 9, 9, "method", False), ("g", 9, 9, "method", False), ("k", 9, 9, "expr", False),
        ("addEventListener()", 10, 13, "arrow", False), ("run", 14, 14, "method", False)]
chk(got == want, "[0] 합성 JS 함수 = 감싸개(IIFE) + 블록 함수 7개(템플릿 안 화살표·메서드·getter·클래스 메서드) · 식 몸통 화살표는 안 셈", got)
m0 = J.unit_metrics(J.Unit("synthetic.js", 0, SNIP))
chk((m0["esc"], m0["n1384"], m0["error"]) == (1, 2, None), "[0] '&amp;' 1개 · 1384 숫자 2개(1384 · 1_384.0) · 주석·문자열 속 1384 없음", m0)
decl = "function main() {\n  return 1;\n}\n"
f1 = J.find_functions(J.tokenize(decl))
J.qualify(f1, J.nlines(decl))
chk(len(f1) == 1 and not f1[0]["wrapper"], "[0] 파일을 덮는 최상위 함수 선언은 감싸개 아님(함수식·화살표만 감싸개)", f1)
asi = "const enabled = true\nfunction render() {\n" + "  draw();\n" * 85 + "}\nconst g = 1 +\nfunction () {\n  return 2;\n}\n"
f3 = J.find_functions(J.tokenize(asi))
J.qualify(f3, J.nlines(asi))
chk([(f["kind"], f["wrapper"], f["lines"]) for f in f3] == [("decl", False, 87), ("expr", False, 3)],
    "[0] 세미콜론 없는 줄 다음 function = 선언(ASI · 감싸개로 빠지지 않음) · 연산자 다음 줄 function = 함수식", f3)
dflt = "const init = (cb = function work() {\n" + "  draw();\n" * 85 + "}) => {};\n"
f4 = J.find_functions(J.tokenize(dflt))
J.qualify(f4, J.nlines(dflt))
chk([(f["name"], f["parent"], f["wrapper"]) for f in f4] == [("work", 1, False), ("init", -1, True)],
    "[0] 인자 기본값 속 함수 = 바깥 함수의 자식(머리~끝 구간 포함) — 감싸개로 빠지지 않음", f4)
expr_arrow = "const init = (cb = function work() {\n" + "  draw();\n" * 85 + "}) => cb;\n"
f5 = J.find_functions(J.tokenize(expr_arrow))
J.qualify(f5, J.nlines(expr_arrow))
chk([(f["name"], f["wrapper"]) for f in f5] == [("work", False)], "[0] 식 몸통 화살표의 인자 기본값 속 함수식 = 괄호 안이라 감싸개 아님", f5)
body85 = "  draw();\n" * 85
slots = {"팩터리 => function": ("const make = cfg => function work() {\n" + body85 + "};\n", False),
         "호출 인자 콜백": ("setTimeout(function work() {\n" + body85 + "}, 0);\n", False),
         "묶음 괄호 IIFE": ("(function () {\n" + body85 + "})();\n", True),
         "단항 IIFE": ("!function () {\n" + body85 + "}();\n", True),
         "문장 자리 대입": ("(window.T = window.T || {}).a = function (X) {\n" + body85 + "};\n", True),
         "화살표 몸통 안 대입": ("const make = cfg => cache = function work() {\n" + body85 + "};\n", False),
         "호출 인자 안 대입": ("run(x = function () {\n" + body85 + "});\n", False),
         "대입된 묶음 괄호 IIFE": ("const API = (function () {\n" + body85 + "})();\n", True),
         "사슬·계산 속성 대입": ("var a = window['b'].c = function () {\n" + body85 + "};\n", True)}
got6 = {}
for k, (src6, _w) in slots.items():
    f6 = J.find_functions(J.tokenize(src6))
    J.qualify(f6, J.nlines(src6))
    got6[k] = f6[0]["wrapper"]
chk(got6 == {k: v[1] for k, v in slots.items()}, "[0] 감싸개 자리 = 문장 맨 앞 대입(왼쪽 사슬 거슬러 확인)·묶음 괄호 IIFE·단항 IIFE 만"
    "(팩터리·화살표 몸통 안 대입·콜백 인자는 함수 길이로 셈)", got6)
for bad_js, why in (("function f() {\n  if (x) {\n}\n", "닫히지"), ("const s = 'abc\n", "끝나지 않은 문자열"), ("a = `x ${b\n", "템플릿")):
    try:
        J.find_functions(J.tokenize(bad_js))
        err = None
    except J.JSError as e:
        err = str(e)
    chk(err is not None and why in err, f"[0] 깨진 JS = JSError({why})", err)

L150, L160 = "x" * 150, "y" * 160
DIFF = "\n".join([
    "diff --git a/web/x.js b/web/x.js", "--- a/web/x.js", "+++ b/web/x.js",
    "@@ -3 +3 @@", "-" + L150, "+" + L160,
    "@@ -10,0 +11,2 @@", "+" + L150, "+short",
    "@@ -20 +22 @@", "-" + L160, "+short",
    "@@ -30 +32 @@", "--- " + L150, "+++ " + L160,
    "diff --git a/web/n.js b/web/n.js", "new file mode 100644", "--- /dev/null", "+++ b/web/n.js",
    "@@ -0,0 +1,2 @@", "+ok", "+" + L150,
    "diff --git a/web/d.js b/web/d.js", "deleted file mode 100644", "--- a/web/d.js", "+++ /dev/null",
    "@@ -1 +0,0 @@", "-" + L160,
    'diff --git "a/web/q\\tn.js" "b/web/q\\tn.js"', '--- "a/web/q\\tn.js"', '+++ "b/web/q\\tn.js"',
    "@@ -1 +1 @@", "-short", "+" + L150,
    "diff --git a/web/\uac00.js b/web/\uac00.js", "--- a/web/\uac00.js", '+++ "b/web/\\352\\260\\200.js"', "@@ -0,0 +1 @@", "+" + L150,
    'diff --git "a/web/\uac00\\tn.js" "b/web/\uac00\\tn.js"', '--- "a/web/\uac00\\tn.js"', '+++ "b/web/\uac00\\tn.js"', "@@ -1 +1 @@", "-s", "+" + L150,
    "diff --git a/web/s p.js b/web/s p.js", "--- a/web/s p.js\t", "+++ b/web/s p.js\t", "@@ -1 +1 @@", "-short", "+" + L150,
    "diff --git a/web/c.js b/web/c.js", "--- a/web/c.js", "+++ b/web/c.js", "@@ -1,3 +1,3 @@", "-a", "+b", " ctx", "+" + L150, "-" + "z", ""])
CUR_LONG = {"web/x.js": {3, 11, 32}, "web/n.js": {2}, "web/q\tn.js": {1}, "web/\uac00.js": {1}, "web/s p.js": {1}, "web/c.js": {3}, "web/\uac00\tn.js": {1}}
got_dl = J.diff_long_lines(DIFF, CUR_LONG)
chk(got_dl == [("web/x.js", 11), ("web/n.js", 2), ("web/q\tn.js", 1), ("web/\uac00.js", 1), ("web/\uac00\tn.js", 1), ("web/s p.js", 1), ("web/c.js", 3)], "[0] 새 긴 줄 = 더한 긴 줄 − 같은 덩어리에서 지운 긴 줄(고친 기존 긴 줄·줄인 줄·지운 파일 = 통과 · 새 줄·새 파일·따옴표 꼴 경로 = 실패)", got_dl)
lu = J.long_lines([J.Unit("web/a.html", 10, "short\n" + L150 + "\n"), J.Unit("web/b.js", 0, L160 + "\r\nok")])
chk(lu == {"web/a.html": {12}, "web/b.js": {1}}, "[0] 지금 긴 줄 = 파일 줄 번호(HTML <script> 는 원본 줄 + offset · 끝 \\r 빼고 셈)", lu)

units = J.js_units(T.ROOT)
res = [J.unit_metrics(u) for u in units]
errs = [(u.path, r["error"]) for u, r in zip(units, res) if r["error"]]
chk(bool(units) and not errs, f"[1] JS 원본 {len(units)}개 토큰화·괄호 짝 성공(실패 = 토크나이저 한계 — _arch_js 머리의 '못 잡는 꼴')", errs[:5])

ac = JA.acorn_report(units)
if ac is None or isinstance(ac, tuple):
    why = "node 없음" if ac is None else ac[1]
    if T.node_required():
        chk(False, "[2] node 내장 acorn 대조(TJ_TEST_REQUIRE_NODE=1)", why)
    else:
        print("SKIP %s — [2] acorn 대조 건너뜀" % why)
else:
    base_meta = (R.load("js_funcs") or {}).get("meta", {}) if R.repo_layout() else {}
    print(f"[2] 대조 도구 = acorn {ac.get('acorn')} · node {ac.get('node')} (기준선을 쓸 때: {base_meta.get('checked_with', '기록 없음')})")
    ac = ac["units"]
    diff = JA.acorn_diff(units, res, ac)
    nf = sum(len(a["fns"]) for a in ac)
    chk(not diff, f"[2] node 내장 acorn 과 같음 — 원본 {len(units)}개 · 블록 함수 {nf}개 구간·꼴·'&amp;'·1384 수(다르면 acorn 이 정본 — "
        "_arch_js 토크나이저를 고쳐라)", diff[:5])

cur, m = R.current_js(T.ROOT)
if not R.repo_layout():
    print("[3] 공개판 배치 — 래칫 건너뜀")
else:
    R.check(T, T.ROOT, cur)
    ref = R.base_ref(T.ROOT)
    if ref.sha:
        d9 = R._git(ref.top, "-c", "diff.interHunkContext=0", "-c", "core.quotePath=true", "diff", "-U0", "--no-color", "--no-ext-diff", "--no-relative", "--src-prefix=a/",
                    "--dst-prefix=b/", ref.sha, "--", "web")
        new9 = J.diff_long_lines(d9, J.long_lines(units)) if d9 is not None else None
        chk(new9 == [], f"[3b] {ref.why} {ref.sha[:8]} 뒤 새로 생긴 140자 넘는 JS 줄 0 — 줄을 140자 안으로 나눠라(기존 긴 줄은 기준선)",
            (new9 or [])[:20] if new9 is not None else "git diff 실패")
    else:
        print(f"  ([3b] 새 긴 줄 검사 건너뜀: {ref.why})")

lim = J.LIMITS
over = lambda v: v["lines"] > lim["file_lines"] or v["bytes"] > lim["file_bytes"]  # noqa: E731
for label, ext in (("JS 파일(web/v2/*.js · web/support.js)", ".js"), ("HTML 인라인 <script>", ".html")):
    fs = [f for f in m["fns"] if f["file"].endswith(ext) and not f["wrapper"]]
    wr = sum(1 for f in m["fns"] if f["file"].endswith(ext) and f["wrapper"])
    tot = {k: sum(v for p, v in m[k].items() if p.endswith(ext)) for k in ("long", "esc", "n1384")}
    print(f"[4] {label}: 함수 {len(fs)}개(80줄↑ {sum(1 for f in fs if f['lines'] > lim['fn_lines'])} · 60줄↑ "
          f"{sum(1 for f in fs if f['lines'] > lim['fn_target'])}) · 모듈 감싸개 {wr} · 140자↑ 줄 {tot['long']} · "
          f"esc {tot['esc']} · 1384 {tot['n1384']}")
js = {p: v for p, v in m["size"].items() if p.endswith(".js")}
html = {p: v for p, v in m["size"].items() if p.endswith(".html")}
py1384 = sum(v["n"] for k, v in cur["js_1384"]["items"].items() if k.endswith(".py"))
print(f"[4] 파일 크기: .js 800줄↑ {sum(1 for v in js.values() if v['lines'] > lim['file_hard_lines'])} · .js 600줄↑·48KB↑ "
      f"{sum(1 for v in js.values() if over(v))} · .html 600줄↑·48KB↑ {sum(1 for v in html.values() if over(v))} · "
      f"파이썬 1384 {py1384} · {time.time() - t0:.1f}초")
T.finish()

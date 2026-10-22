#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

TJD = os.path.join(T.ROOT, "web", "v2", "tjdom.js")
if not os.path.isfile(TJD):
    T.chk(True, "tjdom.js 없음(8-1 앞 트리) · 건너뜀")
    T.finish()
node = T.node_bin("tjdom.js 순수 함수 시험")
if not node:
    T.finish()
SRC = open(TJD, encoding="utf-8").read()
D = L.js_defs(SRC, ["words", "RAW", "tjst", "decls", "ST_BAD", "declBad"])
T.chk(sorted(D) == ["RAW", "ST_BAD", "declBad", "decls", "tjst", "words"], "tjdom.js 에서 순수 함수 정의를 찾음(words·RAW·tjst·decls·ST_BAD·declBad)", sorted(D))
APP_ESC = """const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));"""

JS = r"""
const vm = require('vm'), fs = require('fs');
const IN = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {};
function load(tt, twice) {   // 가짜 창: window = 전역 자신 · document.implementation.createHTMLDocument · location.origin
  const calls = [];
  const g = { location: { origin: 'http://127.0.0.1:9' }, document: { implementation: { createHTMLDocument: () => ({}) } } };
  g.window = g;
  if (tt === 'ok') g.trustedTypes = { createPolicy: (n, o) => { calls.push(n); return { createHTML: o.createHTML }; } };
  if (tt === 'throw') g.trustedTypes = { createPolicy: () => { throw new TypeError('dup'); } };
  const before = new Set(Object.keys(g));
  vm.createContext(g);
  vm.runInContext(IN.src, g);
  if (twice) vm.runInContext(IN.src, g);
  return { g, calls, added: Object.keys(g).filter(k => !before.has(k)) };
}
const A = load('ok', true), N = load('none'), X = load('throw');
const TJ = A.g.TJDOM;
out.added = A.added; out.frozen = Object.isFrozen(TJ); out.api = Object.keys(TJ).sort(); out.calls = A.calls; out.callsNone = N.calls;
out.noneTJ = typeof N.g.TJDOM; out.throwTJ = typeof X.g.TJDOM; out.throwErr = X.g.TJDOM.report().policyErr; out.policy = [A.g.TJDOM.report().policy, N.g.TJDOM.report().policy];
const r = TJ.report(); out.repFrozen = Object.isFrozen(r) && Object.isFrozen(r.items);
try { TJ.set = null; } catch (e) { /* 얼림 */ } out.setKept = typeof TJ.set === 'function';
const appEsc = new Function(IN.appEsc + '\nreturn esc;')();
out.esc = IN.esc.map(v => [TJ.esc(v), appEsc(v)]);
out.escNil = [TJ.esc(null), TJ.esc(undefined), TJ.esc(0), TJ.esc(12.5), TJ.esc({ toString: () => '<o>' })];
out.url = IN.urls.map(([u, k]) => TJ.safeUrl(u, k));
out.urlNil = [TJ.safeUrl(null), TJ.safeUrl(undefined)];
const P = new Function(IN.defs + '\nreturn { tjst, decls, declBad };')();
out.tjst = IN.tj.map(s => P.tjst(s));
out.tjst2 = IN.tj.map(s => P.tjst(P.tjst(s)));
out.decls = IN.decls.map(s => P.decls(s));
out.declBad = IN.declBad.map(([n, v]) => P.declBad(n, v));
process.stdout.write(JSON.stringify(out));
"""
ESC_IN = ["", "a", "<img src=x onerror=alert(1)>", '"><svg onload=1>', "' onfocus='x", "&lt;b&gt;", "a&b", "‮x", "${x}", "가나 다", "`"]
ORIGIN = "http://127.0.0.1:9"
URLS = [
    ("/x", None, None), ("./a", None, None), ("../a", None, None), ("#top", None, None), ("?q=1&b=2", None, None), ("", None, None),
    ("https://e.example/a?b=1&c='x'", None, None), ("http://e.example", None, None), ("HTTPS://E.EXAMPLE", None, None),
    ("mailto:a@e.example", None, None), ("tel:+82-10", None, None), ("//e.example/a", None, None), ("a/b:c", None, None),
    (ORIGIN + "/blob", None, None), ("blob:" + ORIGIN + "/1234-5678", None, None),
    ("data:image/png;base64,AAAA", "img", None), ("data:image/jpeg,xx", "img", None), ("data:image/webp;base64,A", "img", None),
    ("javascript:alert(1)", None, "#"), ("JaVaScRiPt:alert(1)", None, "#"), (" javascript:alert(1)", None, "#"), ("\tjavascript:x", None, "#"),
    ("java\tscript:x", None, "#"), ("java\nscript:x", None, "#"), ("java\rscript:x", None, "#"), ("\x01javascript:x", None, "#"),
    ("java\x01script:x", None, "#"), ("javascript&#58;alert(1)", None, "#"), ("javascript&#x3A;x", None, "#"), ("javascript&colon;x", None, "#"),
    ("java&Tab;script:x", None, "#"), ("&#106;avascript:x", None, "#"), ("&#0000106avascript:x", None, "#"), ("vbscript:x", None, "#"),
    ("data:text/html,<script>x</script>", None, "#"), ("data:image/png;base64,AA", None, "#"), ("data:image/svg+xml,<svg/>", "img", "#"),
    ("data:text/html,x", "img", "#"), ("file:///etc/passwd", None, "#"), ("blob:https://other.example/1", None, "#"),
    ("blob:" + ORIGIN + ".evil/1", None, "#"), ("filesystem:x", None, "#"), ("x-unknown:1", None, "#"), ("\u0000javascript:x", None, "#"),
    ("javascript\u0000:x", None, "#"), ("j&#97;vascript:x", None, "#"),
]
TJ = [
    ('<b style="color:red">x</b>', '<b data-tjst="color:red">x</b>'),
    ('글자 style="x" 그대로 <i>a</i>', None),
    ('<b title="a>b" style="c">t</b>', '<b title="a>b" data-tjst="c">t</b>'),
    ("<b style='c'>x</b>", None), ("<b style=c>x</b>", None), ('</b style="c">', None), ('<b data-style="c" xstyle="d">', None),
    ('<B STYLE="c">x</B>', '<B data-tjst="c">x</B>'), ('<b style = "c">', '<b data-tjst = "c">'),
    ('<!-- <b style="c"> -->', None), ('<textarea> <b style="c"> </textarea><i style="d">', '<textarea> <b style="c"> </textarea><i data-tjst="d">'),
    ('<title><b style="c"></title>', None),
    ('<svg><title><tspan style="c"/></title></svg>', '<svg><title><tspan data-tjst="c"/></title></svg>'),
    ('<svg><![CDATA[ x > <b style="c"> ]]><g style="d"/></svg><textarea style="e">', '<svg><![CDATA[ x > <b style="c"> ]]><g data-tjst="d"/></svg><textarea data-tjst="e">'),
    ('<a href="x" class="y" style="z" title="t">', '<a href="x" class="y" data-tjst="z" title="t">'),
    ('<div\nstyle="a"\nclass=b>', '<div\ndata-tjst="a"\nclass=b>'),
    ('<b title=a>b style="c">', '<b title=a>b style="c">'),
    ('a < b style="c" · 3<4', None), ('<?x style="c"?><!x style="d">', None), ('<b/style="c">', '<b/data-tjst="c">'),
    ('<b ="x" style="c">', '<b ="x" data-tjst="c">'), ('<b style="c"', '<b data-tjst="c"'), ('<b style', None),
    ('<span class="pv" style="width:40%;--n:3">', '<span class="pv" data-tjst="width:40%;--n:3">'),
]
DECLS = [("a:1;b:2", ["a:1", "b:2"]), ("a:url('x;y');b:2", ["a:url('x;y')", "b:2"]), ('font-family:"a;b", c;d:1', ['font-family:"a;b", c', "d:1"]),
         ("a:calc(1px;2px);b:1", ["a:calc(1px;2px)", "b:1"]), (";;a:1; ;", ["a:1"]), ("", [])]
DECLBAD = [(["behavior", "x"], True), (["-moz-binding", "x"], True), (["color", "red"], False), (["position", "relative"], False)]
r = subprocess.run([node, "-e", JS], input=json.dumps({"src": SRC, "appEsc": APP_ESC, "esc": ESC_IN, "urls": [[u, k] for u, k, _ in URLS],
                    "defs": "\n".join(D[n] for n in ("words", "RAW", "decls", "tjst", "ST_BAD", "declBad")), "declBad": [a for a, _ in DECLBAD], "tj": [a for a, _ in TJ], "decls": [a for a, _ in DECLS]}),
                   capture_output=True, text=True, timeout=60)
T.chk(r.returncode == 0, "node 실행", (r.stderr or r.stdout)[-600:])
if r.returncode == 0:
    O = json.loads(r.stdout)
    print("P1 esc")
    T.chk(all(a == b for a, b in O["esc"]), "P1 TJDOM.esc = 8-1 앞 app.js esc(같은 입력 %d개 → 같은 글)" % len(ESC_IN), [x for x in O["esc"] if x[0] != x[1]])
    T.chk(not any(c in a for a, _ in O["esc"] for c in "<>\"'"), "P1 결과에 < > \" ' 없음")
    T.chk(O["escNil"] == ["", "", "0", "12.5", "&lt;o&gt;"], "P1 null·undefined → '' · 숫자·객체 → String", O["escNil"])
    print("P2 safeUrl")
    bad = [(u, k, got, exp if exp is not None else u) for (u, k, exp), got in zip(URLS, O["url"]) if got != (exp if exp is not None else u)]
    T.chk(not bad, "P2 safeUrl 표 %d개(통과 = 원래 글 그대로 · 막힘 = '#')" % len(URLS), bad)
    T.chk(O["urlNil"] == ["", ""], "P2 safeUrl(null·undefined) = ''", O["urlNil"])
    print("P3 글 바꾸기 토큰기")
    bad = [(a, got, exp if exp is not None else a) for (a, exp), got in zip(TJ, O["tjst"]) if got != (exp if exp is not None else a)]
    T.chk(not bad, "P3 tjst 표 %d개(시작 태그 안 큰따옴표 style 만 · 나머지 글 그대로)" % len(TJ), bad)
    T.chk(O["tjst2"] == O["tjst"], "P3 두 번 = 한 번(바꾼 글을 다시 넣어도 같음)")
    print("P4 선언 나누기")
    bad = [(a, got, exp) for (a, exp), got in zip(DECLS, O["decls"]) if got != exp]
    T.chk(not bad, "P4 decls 표 %d개" % len(DECLS), bad)
    T.chk(O["declBad"] == [e for _, e in DECLBAD], "P4b declBad: 늘 금지 style 이름(behavior·-moz-binding) = 뺌 · 정상 선언 = 통과", O["declBad"])
    print("P5 전역·정책")
    T.chk(O["added"] == ["TJDOM"], "P5 전역에 더한 이름 = TJDOM 하나", O["added"])
    T.chk(O["frozen"] and O["setKept"] and O["api"] == sorted(["set", "insert", "replace", "clear", "esc", "safeUrl", "report"]),
          "P5 TJDOM = Object.freeze · API 7개(set·insert·replace·clear·esc·safeUrl·report)", O["api"])
    T.chk(O["calls"] == ["tj-html"], "P5 createPolicy('tj-html') 한 번(두 번 실어도 — 이미 있으면 다시 만들지 않음)", O["calls"])
    T.chk(O["noneTJ"] == "object" and O["policy"] == [True, False], "P5 trustedTypes 없으면 정책 없이 같은 길", O["policy"])
    T.chk(O["throwTJ"] == "object" and "TypeError" in O["throwErr"], "P5 createPolicy 가 던져도 TJDOM 생김 · report().policyErr 기록", O["throwErr"])
    T.chk(O["repFrozen"], "P5 report() = 얼린 사본(items 포함)")
T.finish()

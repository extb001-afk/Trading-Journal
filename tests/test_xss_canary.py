#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

t0 = time.time()
V2 = os.path.join(T.ROOT, "web", "v2")
SRC = {u: s for u, s in L.js_units(T.ROOT)}
SRC["app.js"] = T.app_js()


def defs(unit, names):
    d = L.js_defs(SRC.get(unit, ""), names)
    miss = [n for n in names if n not in d]
    T.chk(not miss, "%s: 카나리아 대상 정의 찾음(%s)" % (unit, ", ".join(names)), {"못 찾음": miss, "고칠 곳": "test_xss_canary.py RENDERS 표(이름이 바뀌었으면 새 이름으로)"})
    return "\n".join(d[n] for n in names if n in d)


_TJ = SRC.get("tjdom.js")
TJ_ESC = defs("tjdom.js", ["esc"]) if _TJ is not None else "const esc = v => String(v);"
TJ_URL = (defs("tjdom.js", list(L.SAFE_URL_DEFS)) if _TJ is not None else "const safeUrl = u => (u == null ? '' : '#');")
FAKE_TJDOM = ("const TJDOM = (() => { const location = { origin: 'https://tj.test' };\n%s\n%s\n"
              " return { esc, safeUrl, set(el, v) { el.innerHTML = v === null ? '' : String(v); }, clear(el) { el.innerHTML = ''; } }; })();\n"
              % (TJ_ESC, TJ_URL))
APP_ESC = FAKE_TJDOM + defs("app.js", ["esc"])
RENDERS = [
    ("search.mark", "const ST = { copyArm: null };\n" + FAKE_TJDOM + defs("search.js", ["esc", "arr"]), defs("search.js", ["mark", "termsOf", "shortMark", "actBtn"]),
     ["mark", "shortMark", "actBtn"],
     ["G.mark(p, ['img'])", "G.mark(p, [])", "G.mark(p, ['on', 'x'])", "G.shortMark(p, { type: 'text', text: 'x', hex: '' })",
      "G.shortMark('0x' + p + p, { type: 'hex', text: '', hex: '0x' })"]),
    ("search.actBtn", "const ST = { copyArm: null };\n" + FAKE_TJDOM + defs("search.js", ["esc"]), defs("search.js", ["actBtn"]), ["actBtn"],
     ["G.actBtn({ ext: p, t: p }, 'v', true)", "G.actBtn({ t: p }, 'v', false)"]),
    ("salelink.xl", "const X = () => null;\n" + FAKE_TJDOM + defs("salelink.js", ["esc"]), defs("salelink.js", ["xl"]), ["xl"],
     ["G.xl(p, p)", "G.xl('', p)"]),
    ("tab_out.exLink", "const S = { rand: false };\n" + APP_ESC + "\n" + defs("app.js", ["short"]), defs("tab_out.js", ["EXPL", "EXPL_NX", "exUrl", "exLink"]),
     ["exLink"], ["G.exLink('eth', p, false, '')", "G.exLink('eth', p, true, '')", "G.exLink('ton', p, false, '')", "G.exLink('sui', p, true, '')",
                  "G.exLink(p, p, false, '')"]),
    ("app.icon", APP_ESC, defs("app.js", ["CHAIN_KEY", "TW", "symColor", "letter", "chainBadge", "icon"]), ["icon"],
     ["G.icon(p, true, { chain: p, ck: 'eth', ca: p })", "G.icon(p, 'xs', {})", "G.icon(p, false, { chain: 'Base', ck: p, ca: '0x' })"]),
    ("app.toast", "const CAP = {}; const $ = sel => ({ set innerHTML(v) { CAP[sel] = v; }, get innerHTML() { return CAP[sel] || ''; } });\n"
     "const S = { hide: false, rand: false }; const hideUnknown = () => false; const setTimeout = () => 0, clearTimeout = () => {};\n"
     + APP_ESC + "\n" + defs("app.js", ["errTxt"]), "let toastT = null;\n" + defs("app.js", ["toast"]), ["toast", "CAP"],
     ["(G.toast(p, false), G.CAP['#toast'])", "(G.toast(p, true), G.CAP['#toast'])"]),
]

JS = r'''
'use strict';
const fs = require('fs');
const IN = JSON.parse(fs.readFileSync(0, 'utf8'));
const P = IN.payloads;
// 실행 꼴 판정 = 결과 HTML 의 실제 태그(속성 이름 포함) 구조가 무해한 입력('img on x')일 때와 다르거나(새 태그·새 속성) on* 속성이 있으면.
//   이스케이프돼 글자로만 남은 '&lt;img … onerror=' 는 태그가 아니라 걸리지 않는다 · 도우미가 원래 내보내는 태그(<img class="lg"> 등)는 무해 입력에도 있다
const TAG = /<([a-zA-Z][\w:-]*)((?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*\/?>/g;
const ATTR = /\s+([^\s"'>\/=]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?/g;
const sigs = h => { const s = new Set(); for (const m of String(h).matchAll(TAG)) s.add(m[1].toLowerCase() + '(' + [...m[2].matchAll(ATTR)].map(a => a[1].toLowerCase()).sort().join(',') + ')'); return s; };
const onAttr = h => [...String(h).matchAll(TAG)].some(m => [...m[2].matchAll(ATTR)].some(a => /^on/i.test(a[1])));
const BENIGN = 'img on x';
const decode = s => s.replace(/&(amp|lt|gt|quot|#39|#x27);/g, (m, e) => ({ amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", '#x27': "'" }[e]));
const urlVals = h => [...String(h).matchAll(/\s(?:href|src|action|formaction|xlink:href)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/gi)]
  .map(m => decode(m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3] || '').replace(/[\u0000-\u0020]/g, ''));   // 큰·작은따옴표·따옴표 없음 모두
const badUrl = u => /^(?:javascript|vbscript):/i.test(u) || /^data:(?!image\/(?:png|gif|jpe?g|webp)[;,])/i.test(u);
const BIDI = /[‪-‮⁦-⁩]/;
const R = { esc: {}, render: {}, ok: {} };
const hrefs = h => [...String(h).matchAll(/\shref="([^"]*)"/g)].map(m => decode(m[1]));   // [C] 큰따옴표 href 값(되읽기)
for (const e of IN.escapers) {
  const r = R.esc[e.id] = R.esc[e.id] || { abs: [], known: [] };   // 같은 이름의 분기(X() null / app.js esc)는 결과를 합친다
  let f;
  try { f = new Function(e.prelude + '\n' + e.src + '\nreturn ' + e.name + ';')(); } catch (err) { r.abs.push('load: ' + err.message); continue; }
  for (const p of P) {
    const o = String(f(p));
    if (/[<>]/.test(o)) r.abs.push('<> 그대로: ' + JSON.stringify(p));
    if (/"/.test(o)) r.abs.push('" 그대로: ' + JSON.stringify(p));
    if (!/^<a title="[^"<>]*">x<\/a>$/.test('<a title="' + o + '">x</a>')) r.abs.push('큰따옴표 속성 탈출: ' + JSON.stringify(p));
    if (p.indexOf('&lt;') >= 0 && o.indexOf('&amp;lt;') < 0) r.abs.push('이미 이스케이프된 &lt; 를 다시 안 바꿈');
    if (/'/.test(o) && r.known.indexOf('sq') < 0) r.known.push('sq');
    if (BIDI.test(o) && r.known.indexOf('bidi') < 0) r.known.push('bidi');
  }
  if (badUrl(decode(String(f('javascript:alert(1)'))))) r.known.push('url_scheme');
}
for (const g of IN.renders) {
  const r = R.render[g.id] = { issues: [], err: [] };
  let G;
  try { G = new Function(g.prelude + '\n' + g.src + '\nreturn { ' + g.ret.join(', ') + ' };')(); } catch (err) { r.err.push('load: ' + err.message); continue; }
  for (const c of g.calls) {
    const call = new Function('G', 'p', 'return ' + c + ';');
    let base;
    try { base = sigs(String(call(G, BENIGN))); } catch (err) { r.err.push(c + ' · 무해 입력 → ' + err.message); continue; }
    for (const p of P) {
      let o;
      try { o = String(call(G, p)); } catch (err) { r.err.push(c + ' · ' + JSON.stringify(p).slice(0, 40) + ' → ' + err.message); continue; }
      const add = k => { if (r.issues.indexOf(k) < 0) r.issues.push(k); };
      if ([...sigs(o)].some(x => !base.has(x)) || onAttr(o)) add('exec_markup');
      if (urlVals(o).some(badUrl)) add('js_url');
      if (BIDI.test(o)) add('bidi');
    }
  }
  if (g.ok) {   // [C] 정상 URL(따옴표·& 포함 · http(s)·상대·#·mailto) = href 값 그대로
    const bad = R.ok[g.id] = [];
    const call = new Function('G', 'u', 'return ' + g.ok + ';');
    for (const u of IN.okUrls) { let hs; try { hs = hrefs(call(G, u)); } catch (err) { bad.push(JSON.stringify(u) + ' → ' + err.message); continue; }
      if (hs.length !== 1 || hs[0] !== u) bad.push(JSON.stringify(u) + ' → ' + JSON.stringify(hs)); }
  }
}
console.log(JSON.stringify(R));
'''

OK_URLS = ["https://example.test/a/b?c=1&d=2#e", "https://example.test/p?q=\"x\"&r='y'", "http://example.test/", "/v2/x?y=1&z=2", "./rel",
           "#settings/keys", "?q=1&b=2", "mailto:someone@example.test"]
OK_CALLS = {"search.actBtn": "G.actBtn({ ext: u, t: 'x' }, 'v', true)", "salelink.xl": "G.xl(u, 'x')"}

PAYLOADS = ["<img src=x onerror=alert(1)>", "\"><svg onload=alert(1)>", "'><script>alert(1)</script>", "\" onmouseover=\"alert(1)\" x=\"",
            "' onfocus='alert(1)' autofocus='", "javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>", "‮gnp.exe‬", "</textarea><img src=x onerror=alert(1)>",
            "&lt;img src=x onerror=alert(1)&gt;", "${alert(1)}", "<a href=\"javascript:alert(1)\">x</a>"]

NODE = L.require_node(T, "XSS 카나리아")
if NODE:
    esc_list = L.escaper_defs(T.ROOT)
    T.chk(len(esc_list) >= 7 and ("app.js", "esc") in [(u, n) for u, n, _t in esc_list], "이스케이프 도우미 정의 찾음(파일마다 사본)", [(u, n) for u, n, _t in esc_list])
    escapers = []
    app_esc = "const __appEsc = (() => { %s\n return esc; })();" % APP_ESC

    def calls_x(txt, tk=None):
        tk = L.js_tokens(txt)[0] if tk is None else tk
        return any((t.k == "name" and t.v == "X" and i + 1 < len(tk) and tk[i + 1].v == "(") or
                   (t.k == "tpl" and any(calls_x(txt, ex) for ex in t.x or ())) for i, t in enumerate(tk))

    deleg9 = re.compile(r"(?:const|let|var)\s+\w+\s*=\s*TJDOM\s*\.\s*esc\s*;")
    n_deleg9 = 0
    for unit, nm, txt in esc_list:
        base9 = nm.split("#", 1)[0]
        if unit != "tjdom.js" and deleg9.fullmatch(txt.strip()):
            n_deleg9 += 1
            continue
        others = "\n".join(t2 for u2, n2, t2 in esc_list if u2 == unit and n2.split("#", 1)[0] != base9 and "#" not in n2)
        for xv in (("const X = () => null;",) + (("%s\nconst X = () => ({ esc: __appEsc });" % app_esc,) if calls_x(txt) else ())):
            escapers.append({"id": "%s::%s" % (unit, nm), "name": base9, "src": txt, "prelude": FAKE_TJDOM + xv + "\n" + others})
    print("(TJDOM.esc 위임 %d곳 = tjdom.js 의 esc 하나로 실행)" % n_deleg9)
    renders = [{"id": i, "prelude": pre, "src": src, "ret": ret, "calls": calls, "ok": OK_CALLS.get(i)} for i, pre, src, ret, calls in RENDERS]
    r = subprocess.run([NODE, "-e", JS], input=json.dumps({"payloads": PAYLOADS, "escapers": escapers, "renders": renders, "okUrls": OK_URLS}),
                       capture_output=True, text=True, timeout=120)
    try:
        R = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        R = None
    T.chk(R is not None, "node 카나리아 실행", (r.stdout[-300:], r.stderr[-600:]))
    if R:
        known = set()
        print("[A] 이스케이프 도우미")
        for eid, res in sorted(R["esc"].items()):
            T.chk(not res["abs"], "%s: < > \" 그대로 0 · 큰따옴표 속성 탈출 0 · &lt; 재이스케이프" % eid, res["abs"][:6])
            for k in res["known"]:
                known.add("esc:%s:%s" % (eid, k))
        print("[B] 렌더 도우미")
        for rid, res in sorted(R["render"].items()):
            T.chk(not res["err"], "%s: 가짜 의존성으로 실행됨(예외 0)" % rid, res["err"][:4])
            for k in res["issues"]:
                known.add("render:%s:%s" % (rid, k))
            print("  %s → %s" % (rid, ", ".join(res["issues"]) or "구멍 없음"))
        print("[C] 정상 URL 그대로(8-2 esc(TJDOM.safeUrl(…)) 자리)")
        for rid in sorted(OK_CALLS):
            T.chk(rid in R["ok"] and not R["ok"][rid], "%s: 정상 URL %d개(따옴표·& 포함 · http(s)·상대·#·mailto) = href 값 그대로" % (rid, len(OK_URLS)),
                  R["ok"].get(rid, "실행 안 됨")[:4])
        L.known_list(T, "xss_canary", "known_hole", sorted(known),
                     "G1 XSS 카나리아 알려진 구멍 — esc:<단위::이름>:<sq|bidi|url_scheme> · render:<도우미>:<exec_markup|js_url|bidi>. "
                     "고쳐지면 --update-lower 로 빠짐(새 구멍 = FAIL)",
                     "새 XSS 구멍 — 그 도우미가 외부 값을 esc()·safeUrl 없이 내보냄(위 '→' 줄 참고)")
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()

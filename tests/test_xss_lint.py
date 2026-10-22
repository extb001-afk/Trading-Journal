#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402
import _sec_succession as S  # noqa: E402

import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

t0 = time.time()
NODE = L.require_node(T, "safeUrl 정상 URL 카나리아 · acorn 교차 검증")
counts, samples = L.js_census(T.ROOT, node=NODE)


NEXT_URL_DEF = ("function nextUrl() { var n = ''; try { n = new URLSearchParams(location.search).get('next') || ''; } catch (e) { n = ''; }"
                " if (typeof n !== 'string' || n.length > 512 || !/^\\/(?![\\/\\\\])/.test(n) || /[\\s\\\\\\u0000-\\u001f\\u007f]/.test(n)"
                " || /^\\/(login([?#\\/]|$)|api\\/)/.test(n)) return '/'; return n; }")


IDX_U_DEF = ("var u = '/login'+(nx&&nx!=='/'&&nx.charAt(0)==='/'&&nx.charAt(1)!=='/'?'?next='+encodeURIComponent(nx):'');")
WOW_BLOB = "const u = URL.createObjectURL(b), a = document.createElement('a'); a.href = u;"


ALLOW_NAME_N = {("login.js", "nextUrl"): 4, ("index.html", "u"): 9, ("wow.js", "u"): 14}


def pick(*cats):
    out = {}
    for c in cats:
        for k, v in counts.get(c, {}).items():
            out[k] = out.get(k, 0) + v
    return out


def smp(*cats):
    out = {}
    for c in cats:
        for k, v in samples.get(c, {}).items():
            out.setdefault(k, []).extend(v)
    return out


print("[1~5] 화면 자리 조사")
units = [u for u, _s in L.js_units(T.ROOT)]
T.chk(len(units) >= 10 and "index.html" in units and "app.js" in units, "화면 단위 = web/v2/*.js + index.html 인라인 스크립트", units)
T.chk(sum(pick("sink:static", "sink:esc", "sink:raw").values()) > 0, "HTML 싱크 조사가 자리를 찾음(조사기 고장 아님)")
html = {}
for name, txt in L.html_static(T.ROOT):
    n_h = len(re.findall(r"<[^>]*\son[a-z]{3,}\s*=", txt, re.I))
    n_j = len(re.findall(r"(?:href|src|action|formaction)\s*=\s*[\"']?\s*javascript:", txt, re.I))
    if n_h or n_j:
        html["%s::<html>" % name] = n_h + n_j
inline = pick("inline_handler")
for k, v in html.items():
    inline[k] = inline.get(k, 0) + v

metrics = {
    "sink_all": pick("sink:static", "sink:esc", "sink:raw"),
    "sink_esc_raw": pick("sink:esc", "sink:raw"),
    "sink_raw": pick("sink:raw"),
    "code_sink": pick("code_sink"),
    "url_unsafe": pick("url:raw", "url:esc_only"),
    "url_raw": pick("url:raw"),
    "ext_field": pick("ext"),
    "inline_handler": inline,
}
smps = {"sink_all": smp("sink:static", "sink:esc", "sink:raw"), "sink_esc_raw": smp("sink:esc", "sink:raw"), "sink_raw": smp("sink:raw"),
        "code_sink": smp("code_sink"), "url_unsafe": smp("url:raw", "url:esc_only"), "url_raw": smp("url:raw"), "ext_field": smp("ext"),
        "inline_handler": smp("inline_handler")}
hints = {
    "sink_all": "새 innerHTML·insertAdjacentHTML 자리 — textContent·DOM API 를 쓰거나(8막 setHTML 래퍼 전까지) 기존 자리를 다시 쓰세요",
    "sink_esc_raw": "글자 그대로가 아닌 값을 HTML 싱크에 넣음 — 동적 값은 esc() 로 감싸세요",
    "sink_raw": "원시 동적 HTML 싱크(esc 안 거친 값) — 값마다 esc() 로 감싸거나 DOM API(textContent)로",
    "code_sink": "eval·new Function·문자열 타이머·on* 문자열 = CSP 가 막는 코드 실행 꼴 — 함수 참조로 바꾸세요",
    "url_unsafe": "href·src 등에 동적 값 — esc 만으로는 javascript:·data: 를 못 막아요(글자 접두 '#'·'/'·'https://' 로 고정하거나 safeUrl 계열)",
    "url_raw": "href·src 등에 esc 도 안 거친 동적 값 — 최소 esc() + 스킴 고정",
    "ext_field": "외부 필드(.sym·.name·.memo·.title·.url …)를 HTML 글에 그대로 이어 붙임 — esc(x.sym) 처럼 감싸세요",
    "inline_handler": "인라인 이벤트 속성(on*=)·javascript: 주소 = CSP 가 막음 — data-a 위임 이벤트를 쓰세요",
}
doc = ("G1 test_xss_lint 기준선 — 화면 HTML 싱크·URL 속성·외부 필드 자리(파일::함수 → 수). 늘면 FAIL · 줄면 `--update-lower`. "
       "분류 규칙 = _sec_lint.classify_expr·_url_kind·_ext_hits(이름 기반 esc 판정 · 삼항 조건·비교 자리는 출력 아님)")
L.ratchet(T, "xss", metrics, doc, hints=hints, samples=smps, exists=lambda f: f.split("::")[0] in units or f.endswith("<html>"))

print("[6] esc 계열 이름 무결성")
app_esc_ok = set()
_tj6 = dict(L.js_units(T.ROOT)).get("tjdom.js")
_tjd6 = L.js_defs_all(_tj6, ["esc"]).get("esc", []) if _tj6 is not None else []
TJ_ESC_OK = len(_tjd6) == 1 and all(x in _tjd6[0] for x in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"))
T.chk(_tj6 is None or TJ_ESC_OK, "tjdom.js: esc 정의 하나 · & < > \" ' 다섯 글자를 바꿈(화면 파일 위임 대상)", _tjd6[:2])
DELEG6 = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*TJDOM\s*\.\s*esc\s*;")
for unit, src in sorted(L.js_units(T.ROOT), key=lambda u: u[0] != "app.js"):
    called = L.called_names(L.js_tokens(src)[0], L.ESC_NAMES)
    ENT = ("&amp;", "&lt;", "&gt;", "&quot;")
    unit_ok = {}
    for nm0 in ("esc0",):
        b0 = L.js_defs_all(src, [nm0]).get(nm0, [])
        unit_ok[nm0] = bool(b0) and all(all(x in d for x in ENT) for d in b0)
    borrowed = set()
    for mx in re.finditer(r"const \{([^{}]*)\} = X;", src):
        borrowed.update(x.strip() for x in mx.group(1).replace("\n", " ").split(","))
    defs9 = L.js_defs_all(src, called)
    for nm in sorted(called):
        bodies = defs9.get(nm, [])
        if nm in borrowed and not bodies:
            T.chk(nm in app_esc_ok, "%s: %s() = app.js 에서 빌린 이름(app.js 정의가 & < > \" 를 바꿈)" % (unit, nm), sorted(app_esc_ok))
            continue
        bad9 = []
        for body in bodies:
            ok_full = all(x in body for x in ENT)
            rhs9 = body.split("=", 1)[1] if "=" in body else ""
            deleg = nm != "esc0" and (("esc0(" in rhs9 and unit_ok.get("esc0")) or (".esc(" in rhs9 and "esc" in app_esc_ok))
            m6 = DELEG6.fullmatch(body.strip())
            deleg = deleg or bool(m6 and m6.group(1) == nm and TJ_ESC_OK and not L.js_defs_all(src, ["TJDOM"]).get("TJDOM"))
            if not (ok_full or deleg):
                bad9.append(body[:120])
        T.chk(bool(bodies) and not bad9, "%s: %s() 정의 %d개 전부 & < > \" 를 바꿈(또는 검증된 esc0·X().esc·TJDOM.esc 위임)" % (unit, nm, len(bodies)), bad9 or "정의 없음")
        unit_ok[nm] = bool(bodies) and not bad9
        if unit == "app.js" and bodies and not bad9:
            app_esc_ok.add(nm)

print("[7] CSP")
import email.message  # noqa: E402
import io  # noqa: E402

import http_assets  # noqa: E402
import web  # noqa: E402

idx = open(os.path.join(T.ROOT, "web", "v2", "index.html"), "rb").read()
csp, csp_ro = http_assets.v2_csp(idx, "g1-test")


csp_dirs = S.csp_dirs
fk9, fdup9 = csp_dirs("form-action *; Form-Action 'self'")
T.chk(fk9.get("form-action") == ["*"] and fdup9 == {"form-action"}, "CSP 해석 = 첫 지시어 적용 · 중복은 따로 잡음(브라우저와 같게)", [fk9, fdup9])
dirs, dup9 = csp_dirs(csp)


class _CspResp(web.Handler):

    def __init__(self, inm=None):   # noqa: D107
        self.headers = email.message.Message()
        if inm:
            self.headers["If-None-Match"] = inm
        self.client_address = ("127.0.0.1", 0)
        self.close_connection = True
        self.wfile = io.BytesIO()
        self.sent, self.status = [], None

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, name, value):
        self.sent.append((name.lower(), value))

    def end_headers(self):
        pass


asset9 = {"raw": idx, "gz": None, "hash": "g1-test", "etag": 'W/"g1-csp"'}
for inm9 in (None, asset9["etag"]):
    h9 = _CspResp(inm9)
    h9._send_v2_index(asset9)
    sent9 = [v for k, v in h9.sent if k == "content-security-policy"]
    ro9 = [v for k, v in h9.sent if k == "content-security-policy-report-only"]
    T.chk(web.BUILDER is None and h9.status == (304 if inm9 else 200) and sent9 == [csp] and ro9 == [] and csp_ro is None,
          "v2 HTML 실제 응답의 CSP = 위에서 검사한 강제 정책 한 벌 · Report-Only 없음(%d)" % (304 if inm9 else 200), (h9.status, sent9, ro9))
n_inline = len([m for m in re.finditer(rb"<script(?P<a>[^>]*)>", idx) if not re.search(rb"\bsrc\s*=", m.group("a"))
                and not re.search(rb"type\s*=\s*[\"']application/json", m.group("a"))])
rep9 = http_assets.v2_csp(idx, "g1-test", "report")
ro_dirs, ro_dup9 = csp_dirs(rep9[1] or "")
for nm9, dirs9, dup_9 in (("CSP", dirs, dup9), ("CSP 단계 report 의 Report-Only", ro_dirs, ro_dup9)):
    T.chk(not dup_9, "%s 중복 지시어 0(브라우저는 첫 지시어만 — 뒤 지시어로 고쳐도 안 먹음)" % nm9, sorted(dup_9))
    ss = dirs9.get("script-src", [])
    bad_ss = [x for x in ss if x != "'self'" and not re.fullmatch(r"'sha256-[A-Za-z0-9+/=]+'", x)]
    T.chk(bool(ss) and "'self'" in ss and not bad_ss, "%s script-src = 'self' + 인라인 해시만(그 밖 출처 0 — 'unsafe-inline'·'unsafe-eval'·*·data:·https:·바깥 호스트)" % nm9, bad_ss or ss)
    T.chk(len([x for x in ss if x.startswith("'sha256-")]) == n_inline, "%s 해시 수 = index.html 인라인 실행 스크립트 수" % nm9, (ss, n_inline))
    for d9 in ("object-src", "base-uri", "frame-ancestors"):
        T.chk(dirs9.get(d9) == ["'none'"], "%s %s 'none'" % (nm9, d9), dirs9.get(d9))
    T.chk(dirs9.get("default-src") == ["'self'"], "%s default-src 'self'" % nm9, dirs9.get("default-src"))
    T.chk(dirs9.get("form-action") == ["'self'"], "%s form-action 'self'(default-src 로 대체되지 않는 지시어 — 빠지거나 넓으면 아무 곳으로나 폼 전송)" % nm9,
          dirs9.get("form-action"))
STRICT_V2 = {"default-src": ["'self'"], "script-src": dirs.get("script-src"), "style-src": ["'self'"], "font-src": ["'self'", "data:"],
             "img-src": ["'self'", "data:", "blob:"], "connect-src": ["'self'"], "object-src": ["'none'"], "base-uri": ["'none'"], "form-action": ["'self'"],
             "frame-ancestors": ["'none'"], "require-trusted-types-for": ["'script'"], "trusted-types": ["tj-html"]}
T.chk(http_assets.CSP_STAGE == "enforce" and dirs == STRICT_V2, "CSP 단계 enforce = 강제 정책이 엄격안과 지시어·출처·차례까지 같음(script-src = 인라인 해시)",
      (http_assets.CSP_STAGE, [(k, dirs.get(k), v) for k, v in STRICT_V2.items() if dirs.get(k) != v] + sorted(set(dirs) - set(STRICT_V2))))
T.chk(list(dirs) == list(STRICT_V2), "CSP 강제 지시어 차례 = 엄격안 차례", list(dirs))
T.chk(rep9[1] == csp and rep9[0] != csp and http_assets.v2_csp(idx, "g1-test") == (csp, None), "CSP 단계 report = (8-4a 앞 강제, 엄격안 Report-Only = 지금 강제와 바이트 같음) · enforce 로 되돌리면 다시 (엄격안, 없음)",
      rep9)


class _LoginResp:

    def _send_bytes(self, code, raw, gz, ctype, extra=()):
        self.got = (code, ctype, list(extra))


import login_auth  # noqa: E402

STRICT_LOGIN = "default-src 'self'; style-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; require-trusted-types-for 'script'; trusted-types 'none'"
for nm9, ct9, want9 in (("login.html", "text/html; charset=utf-8", [("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", STRICT_LOGIN)]),
                        ("login.js", "application/javascript; charset=utf-8", [("Referrer-Policy", "no-referrer")])):
    lh9 = _LoginResp()
    login_auth._file(lh9, nm9, ct9)
    T.chk(lh9.got[2] == want9, "로그인 %s 응답 헤더 = %s" % (nm9, "강제 엄격안 · Report-Only 없음" if ct9.startswith("text/html") else "CSP 없음(HTML 만)"), lh9.got[2])
lg_dirs, lg_dup = csp_dirs(login_auth.LOGIN_CSP[0])
T.chk(not lg_dup and lg_dirs.get("default-src") == ["'self'"] and "script-src" not in lg_dirs and all(lg_dirs.get(d9) == ["'none'"] for d9 in ("frame-ancestors", "base-uri")),
      "로그인 강제 CSP = default-src 'self'(스크립트 = 같은 출처 login.js 만 · 인라인 0) · frame-ancestors·base-uri 'none'", lg_dirs)
L.ratchet(T, "xss_csp", S.csp_metrics(csp, csp_ro),
          "G1 CSP 알려진 약점(8막에서 고치면 목록에서 빠짐) · csp_source = 지시어·출처 전체(새 출처 = FAIL · 줄면 안내)",
          hints={"csp_weak": "CSP 에 새 약점 — script·style·img·connect 출처를 넓히지 마세요",
                 "csp_source": "CSP 에 새 출처 — 지시어마다 허용 출처를 넓히지 마세요(정말 필요하면 이유와 함께 기준선에 손으로)"},
          modes=S.CSP_MODES)
print("[8]~[11] 절대 검사(지금 값 고정 — 묶음마다 줄임)")
import _xss_abs as X  # noqa: E402

ABS_NOW = {
    "sink_out": {},
    "sink_tjdom": 1,
    "logo_src": {},
    "cdn": {},
    "dynstyle": {},
    "markup_style": {},
    "style_block": {},
    "policy_tjdom": 1,
}
ABS = X.census(T.ROOT)
TJD = "tjdom.js"
SYN = os.path.join(T.TMP, "xss_abs_syn")
os.makedirs(os.path.join(SYN, "web", "v2"))
for fn9, body9 in {
    "tjdom.js": "(function () {\n  const P = trustedTypes.createPolicy('tj-html', {});\n  const Q = trustedTypes.createPolicy('default', {});\n"
                "  function set(el, s) { ctx.innerHTML = P.createHTML(s); el['outerHTML'] = s; }\n  window.TJDOM = { set };\n  globalThis.leak = P;\n"
                "  window['pol'] = Q;\n  Object.defineProperty(self, 'dp', { value: P });\n  const R = P['createPolicy']('x');\n})();\n"
                "var topLeak = 1, other = 2;\nfunction topFn() { var inner = 1; }\nconst { a9, b9 } = {};\nif (true) { var blk = 1; function blkFn() {} }\n"
                "for (var k9 = 0; k9 < 1; k9++) {}\n(() => { var arrowLocal = 1; })();\nconst cp = trustedTypes.createPolicy;\ntrustedTypes.createPolicy?.('default', {});\n"
                "(function () { Object.defineProperties(window, { pol2: { value: 1 } }); Reflect.set(globalThis, 'z9', 1); Reflect.get(trustedTypes, 'createPolicy'); })();\n",
    "app.js": "function f(el, n) {\n  el.insertAdjacentHTML('beforeend', `<b style=\"x\">${n}</b>`);\n  el.setAttribute('style', 'color:red');\n"
              "  document.head.appendChild(document.createElement('style'));\n  img.src = 'https://cdn.jsdelivr.net/gh/x';\n  S.src = { mode: 1 };\n"
              "  const k = trustedTypes.createPolicy(name, {});\n  el[`innerHTML`] = n;\n  Reflect.set(el, 'outerHTML', n);\n  Object.assign(el, { innerHTML: n });\n}\n",
    "index.html": "<html><head><style>.a{}</style></head><body><div style=\"a\" id=x><i style='b'></i></div>"
                  "<script>document.write('<p>');</script></body></html>\n",
}.items():
    with open(os.path.join(SYN, "web", "v2", fn9), "w", encoding="utf-8") as f9:
        f9.write(body9)
SY = X.census(SYN)
want9 = {"sink": {"tjdom.js": 2, "app.js": 4, "index.html": 1}, "policy": {"tjdom.js": 6, "app.js": 1}, "setattr_style": {"app.js": 1},
         "dynstyle": {"app.js": 1}, "logo_src": {"app.js": 1}, "cdn": {"app.js": 1}, "markup_style": {"index.html": 2}, "style_block": {"index.html": 1}}
got9 = {k: X.by_file(SY[k]) for k in want9}
T.chk(got9 == {k: dict(sorted(v.items())) for k, v in want9.items()}, "[8]~[11] 조사기 자체 시험(합성 트리): 싱크·정책·style·로고·마크업을 모두 잡음", got9)
T.chk(sorted(x.detail for x in SY["policy"]) == ["<동적>"] * 5 + ["default", "tj-html"], "[8]~[11] 조사기 자체 시험: 정책 이름('default'·동적·계산 속성·?.(·별칭)",
      sorted(x.detail for x in SY["policy"]))
CLEAN9 = ("(function () {\n  'use strict';\n  const P = window.trustedTypes ? window.trustedTypes.createPolicy('tj-html', { createHTML: s => s }) : null;\n"
          "  const ctx = document.createElement('div');\n  function set(el, s) { ctx.innerHTML = P ? P.createHTML(s) : s; el.replaceChildren(...ctx.childNodes); }\n"
          "  window.TJDOM = { set };\n})();\n")
PROBES9 = [
    ("global", "globalThis.leak = 1;"), ("global", "window['pol'] = 1;"), ("global", "Object.defineProperty(self, 'dp', { value: 1 });"),
    ("global", "var topLeak = 1;"), ("global", "if (true) { var blk = 1; }"), ("global", "if (true) { function blkFn() {} }"),
    ("global", "for (var k9 of [1]) {}"), ("global", "async function aLeak() {}"), ("global", "function* gLeak() {}"),
    ("global", "f9()\nfunction asiLeak() {}"), ("global", "class CLeak {}"), ("global", "const cTop = 1;"),
    ("global", "(() => { this.arrowLeak = 1; })();"), ("global", "(function () { (window).paren = 1; })();"),
    ("global", "(function () { ({ v: window.dz } = { v: 1 }); })();"), ("global", "(function () { Object['assign'](window, { a: 1 }); })();"),
    ("global", "(function () { Object.assign?.(window, { a: 1 }); })();"), ("global", "(function () { Object.defineProperties(window, { a: { value: 1 } }); })();"),
    ("global", "(function () { Reflect.set(globalThis, 'z9', 1); })();"), ("global", "(function () { const w = [window]; })();"),
    ("policy", "trustedTypes.createPolicy('default', {});"), ("policy", "trustedTypes.createPolicy?.('tj-html', {});"),
    ("policy", "const cp = trustedTypes.createPolicy;"), ("policy", "trustedTypes['createPolicy']('x', {});"), ("policy", "Reflect.get(trustedTypes, 'createPolicy');"),
    ("policy", "trustedTypes.createPolicy(`tj-html`, {});"),
    ("sink", "document.body.innerHTML = 1;"), ("sink", "[document.body.innerHTML] = [1];"), ("sink", "({ v: document.body.outerHTML } = { v: 1 });"),
    ("sink", "for (document.body.innerHTML of [1]) {}"), ("sink", "document.body[`innerHTML`] = 1;"), ("sink", "Reflect.set(document.body, 'innerHTML', 1);"),
    ("sink", "Object.assign(document.body, { innerHTML: 1 });"), ("sink", "const ia = document.body.insertAdjacentHTML;"), ("sink", "document.body.setAttribute(`srcdoc`, 1);"),
    ("esc", "trustedTypes.createPolic\\u0079('default', {});"), ("esc", "const \\u0061b = 1;"),
]


def abs_viol(c):
    v = set()
    if {x.detail for x in c["global"] if x.file == TJD} - {"TJDOM"}:
        v.add("global")
    pol = [x for x in c["policy"]]
    if any(x.detail != "tj-html" for x in pol) or len([x for x in pol if x.file == TJD]) > 1:
        v.add("policy")
    if len([x for x in c["sink"] if x.file == TJD]) > 1:
        v.add("sink")
    if c["ident_escape"]:
        v.add("esc")
    if c["setattr_style"] or c["dynstyle"]:
        v.add("style")
    return v


def syn_tree(name, tjdom):
    d9 = os.path.join(T.TMP, "xss_probe", name)
    os.makedirs(os.path.join(d9, "web", "v2"))
    with open(os.path.join(d9, "web", "v2", TJD), "w", encoding="utf-8") as f9:
        f9.write(tjdom)
    return X.census(d9)


c0 = syn_tree("clean", CLEAN9)
T.chk(abs_viol(c0) == set() and [x.detail for x in c0["global"]] == ["TJDOM"] and [x.detail for x in c0["policy"]] == ["tj-html"]
      and len(c0["sink"]) == 1, "[8]~[11] 조사기 자체 시험: 깨끗한 tjdom.js 꼴 = 위반 0(전역 TJDOM · 정책 tj-html · 싱크 하나)",
      {k: [x.detail for x in c0[k]] for k in ("global", "policy", "sink")})
miss9 = []
for k9, (kind9, line9) in enumerate(PROBES9):
    v9 = abs_viol(syn_tree("p%d" % k9, CLEAN9 + line9 + "\n"))
    if kind9 not in v9:
        miss9.append((kind9, line9, sorted(v9)))
T.chk(not miss9, "[8]~[11] 조사기 자체 시험: 위반 꼴 %d개(전역 노출 · 정책 · 싱크 · 식별자 이스케이프)를 하나씩 더하면 전부 잡음" % len(PROBES9), miss9)


def site_list(sites, n=6):
    return ["%s:%d %s %s" % (x.file, x.line, x.fn, x.detail) for x in sites[:n]]


def now_eq(key, got, sites):
    want = ABS_NOW[key]
    if got == want:
        T.chk(True, "%s = 지금 값 %s" % (key, want))
        return
    tot = (lambda v: sum(v.values()) if isinstance(v, dict) else v)
    more = tot(got) > tot(want) or (isinstance(got, dict) and any(got.get(k, 0) > want.get(k, 0) for k in got))
    T.chk(False, "%s = 지금 값 표와 다름 — %s" % (key, "늘어남(금지 · 새 자리를 없애세요)" if more else "줄었음 → test_xss_lint.ABS_NOW['%s'] 를 지금 값으로 줄이세요" % key),
          {"표": want, "지금": got, "자리": site_list(sites)})


print("[8] HTML 싱크 = tjdom.js 안만 · 토큰 로고 바깥 요청")
sk_in = [x for x in ABS["sink"] if x.file == TJD]
sk_out = [x for x in ABS["sink"] if x.file != TJD]
now_eq("sink_out", X.by_file(sk_out), sk_out)
now_eq("sink_tjdom", len(sk_in), sk_in)
T.chk(len(sk_in) <= 1, "[8] tjdom.js 안 HTML 싱크 ≤ 1(절대 — 비활성 문서 문맥 요소 대입 하나)", site_list(sk_in))
n_g1 = sum(pick("sink:static", "sink:esc", "sink:raw").values())
T.chk(len(ABS["sink"]) == n_g1, "[8] 싱크 수 = [1] 분류 조사기 합계(두 조사기 같음 — 한쪽이 놓치면 실패)", {"절대 조사": len(ABS["sink"]), "[1] 분류": n_g1})
now_eq("logo_src", X.by_file(ABS["logo_src"]), ABS["logo_src"])
now_eq("cdn", X.by_file(ABS["cdn"]), ABS["cdn"])

print("[9] 동적 <style> · setAttribute('style')")
now_eq("dynstyle", X.by_file(ABS["dynstyle"]), ABS["dynstyle"])
T.chk(not ABS["setattr_style"], "[9] setAttribute('style') 0(절대 — style 은 CSSOM 길만)", site_list(ABS["setattr_style"]))

print("[10] index.html·login.html 마크업 style 속성 · <style> 블록")
now_eq("markup_style", X.by_file(ABS["markup_style"]), ABS["markup_style"])
now_eq("style_block", X.by_file(ABS["style_block"]), ABS["style_block"])

print("[11] Trusted Types 정책 · tjdom.js 전역")
pol = ABS["policy"]
T.chk(all(x.detail == "tj-html" for x in pol), "[11] 정책 이름 = 'tj-html' 만(절대 — 'default'·다른 이름·글자 아닌 이름 0)", site_list(pol))
T.chk(not [x for x in pol if x.file != TJD], "[11] createPolicy = tjdom.js 안만(절대 — 밖 0)", site_list([x for x in pol if x.file != TJD]))
now_eq("policy_tjdom", len([x for x in pol if x.file == TJD]), pol)
T.chk(len([x for x in pol if x.file == TJD]) <= 1, "[11] tjdom.js 정책 생성 ≤ 1(절대)", site_list(pol))
T.chk(not ABS["ident_escape"], "[11] 식별자 안 유니코드 이스케이프 0(절대 — 조사기가 이름을 못 읽는 꼴)", site_list(ABS["ident_escape"]))
gl = sorted({x.detail for x in ABS["global"] if x.file == TJD})
T.chk(set(gl) <= {"TJDOM"}, "[11] tjdom.js 전역 열쇠 = TJDOM 하나(절대 — 정책 객체·내부 함수가 전역에 안 나감)", gl)

print("[12] 토큰 분석기 교차 검증(node 내장 acorn — 있을 때만)")
if NODE:
    import json as _json  # noqa: E402
    import subprocess  # noqa: E402

    ACORN = r"""
    const fs = require('fs');
    let acorn;
    try { acorn = require('internal/deps/acorn/acorn/dist/acorn'); } catch (e) { console.log(JSON.stringify({ noacorn: String(e.message).slice(0, 120) })); process.exit(0); }
    const IN = JSON.parse(fs.readFileSync(0, 'utf8')), out = {};
    for (const u of IN) {
      const rx = [], st = []; let bq = 0;
      try {
        for (const t of acorn.tokenizer(u.text, { ecmaVersion: 'latest', sourceType: 'script', allowHashBang: true })) {
          if (t.type.label === 'regexp') rx.push(t.start); else if (t.type.label === 'string') st.push(t.start); else if (t.type.label === '`') bq++;
        }
        out[u.name] = { rx, st, tpl: bq / 2 };
      } catch (e) { out[u.name] = { err: String(e.message).slice(0, 160) }; }
    }
    console.log(JSON.stringify(out));
    """
    units9 = L.js_units(T.ROOT)
    r9 = subprocess.run([NODE, "--expose-internals", "-e", ACORN], input=_json.dumps([{"name": u, "text": s9} for u, s9 in units9]),
                        capture_output=True, text=True, timeout=120)
    try:
        A9 = _json.loads(r9.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        A9 = {"noacorn": (r9.stderr or r9.stdout)[-160:]}
    if "noacorn" in A9:
        T.chk(not T.node_required(L.REQUIRE_NODE), "node 내장 acorn 을 못 읽음(이 node 판에 internal 경로 없음)", A9["noacorn"])
        if not T.node_required(L.REQUIRE_NODE):
            print("SKIP 내장 acorn 없음 — 교차 검증 건너뜀: %s" % A9["noacorn"])
    else:
        def _flat(toks, rx, st, tp):
            for t9 in toks:
                if t9.k == "rx":
                    rx.append(t9.p)
                elif t9.k == "str":
                    st.append(t9.p)
                elif t9.k == "tpl":
                    tp[0] += 1
                    for e9 in t9.x:
                        _flat(e9, rx, st, tp)
        for u, s9 in units9:
            a9 = A9.get(u) or {"err": "결과 없음"}
            if "err" in a9:
                T.chk(False, "%s: acorn 이 못 읽음" % u, a9["err"])
                continue
            u16, acc = [], 0
            for ch in s9:
                u16.append(acc)
                acc += 2 if ord(ch) > 0xFFFF else 1
            u16.append(acc)
            rx, st, tp = [], [], [0]
            _flat(L.js_tokens(s9)[0], rx, st, tp)
            same = sorted(u16[p9] for p9 in rx) == sorted(a9["rx"]) and sorted(u16[p9] for p9 in st) == sorted(a9["st"]) and tp[0] == a9["tpl"]
            T.chk(same, "%s: 문자열·정규식·템플릿 토큰 = acorn 과 같음(분석기 정확도)" % u,
                  {"정규식": (len(rx), len(a9["rx"])), "문자열": (len(st), len(a9["st"])), "템플릿": (tp[0], a9["tpl"])})

print("[13] 8-2 TJDOM.safeUrl 인정 · 판정표 허용(닫힌 목록)")
import tempfile  # noqa: E402

su_ok, su_probs, su_ran = L.safe_url_check(T.ROOT, NODE)
if TJD in dict(L.js_units(T.ROOT)):
    T.chk(su_ok, "[13] tjdom.js URL 검사 정의 무결성(정의 6개 하나씩 · 스킴 닫힌 표 %s · 전역 TJDOM.safeUrl)%s"
          % ("·".join(L.SAFE_URL_SCHEMES), " + 정상 URL 카나리아 %d개(그대로 · 따옴표·& 든 URL 이 속성 값 그대로)"
             % (len(L.SAFE_URL_OK) + len(L.SAFE_URL_OK_IMG)) if su_ran else ""), su_probs)
    if not su_ran and su_ok:
        print("SKIP node 없음 — safeUrl 정상 URL 카나리아 건너뜀(정의 무결성만)")
login9 = dict(L.js_units(T.ROOT)).get("login.js")
if login9 is not None:
    nx9 = L.js_defs_all(login9, ["nextUrl"]).get("nextUrl", [])
    T.chk(len(nx9) == 1 and L._tok_sig(nx9[0]) == L._tok_sig(NEXT_URL_DEF), "[13] login.js nextUrl 정의 = 판정 때 글(URL_ALLOW 이유 그대로)",
          [x[:160] for x in nx9])
idx9 = dict(L.js_units(T.ROOT)).get("index.html")
if idx9 is not None:
    u9 = L.js_defs_all(idx9, ["u"]).get("u", [])
    T.chk(len(u9) == 1 and L._tok_sig(u9[0]) == L._tok_sig(IDX_U_DEF), "[13] index.html 401 감시 u 정의 = 판정 때 글(URL_ALLOW 이유 그대로)", [x[:160] for x in u9])
wow9 = dict(L.js_units(T.ROOT)).get("wow.js")
if wow9 is not None:
    sg9, pat9 = L._tok_sig(wow9), L._tok_sig(WOW_BLOB)
    T.chk(sum(sg9[i:i + len(pat9)] == pat9 for i in range(len(sg9))) == 1, "[13] wow.js 연말 결산 blob 생산자·소비자 글 = 판정 때 글(한 번)")


def allow_counts(cat, field_of):
    got = {}
    for k, v in samples.get(cat, {}).items():
        unit9, fn9 = k.split("::", 1)
        for ex in v:
            key = (unit9, fn9, field_of(ex.split(" ", 1)[1] if " " in ex else ""))
            got[key] = got.get(key, 0) + 1
    return got


U13 = dict(L.js_units(T.ROOT))
nn13 = {k: L._flat_names(L.js_tokens(U13[k[0]])[0]).count(k[1]) for k in ALLOW_NAME_N if k[0] in U13}
T.chk(nn13 == {k: v for k, v in ALLOW_NAME_N.items() if k[0] in U13}, "[13] 허용 대상 이름 쓰임 수 = 판정 때 수(ALLOW_NAME_N — 재대입·가리기 0)",
      {"지금": {"%s:%s" % k: v for k, v in nn13.items()}, "표": {"%s:%s" % k: v for k, v in ALLOW_NAME_N.items()}})
ext_got = allow_counts("ext:allow", lambda d: re.sub(r"^\$\{…|\}$", "", d.strip()))
ext_want = {k: n for k, (n, _why) in L.EXT_ALLOW.items()}
T.chk(ext_got == ext_want, "[13] 외부 필드 허용 표(EXT_ALLOW %d자리) = 조사 결과와 정확히 같음(새 자리·사라진 자리 = 표를 다시 판정)" % sum(ext_want.values()),
      {"조사": ext_got, "표": ext_want})
url_got = allow_counts("url:allow", lambda d: d.strip())
url_want = {}
for (u9, f9, d9, _k9), (n9, _why) in L.URL_ALLOW.items():
    url_want[(u9, f9, d9)] = url_want.get((u9, f9, d9), 0) + n9
T.chk(url_got == url_want, "[13] URL 허용 표(URL_ALLOW %d자리) = 조사 결과와 정확히 같음" % sum(url_want.values()), {"조사": url_got, "표": url_want})
T.chk(all(why for _n, why in list(L.EXT_ALLOW.values()) + list(L.URL_ALLOW.values())), "[13] 허용 표 줄마다 이유 있음")

tj9 = dict(L.js_units(T.ROOT)).get(TJD)


def syn_root(files):
    root9 = tempfile.mkdtemp(dir=T.TMP)
    os.makedirs(os.path.join(root9, "web", "v2"))
    for nm9, txt9 in files.items():
        with open(os.path.join(root9, "web", "v2", nm9), "w", encoding="utf-8") as f9:
            f9.write(txt9)
    return root9


if tj9 is not None and su_ok:
    T.chk(L.safe_url_check(syn_root({TJD: tj9}), None)[0], "[13] 합성: 같은 tjdom.js 사본 = 정의 무결성 통과")
    MUT9 = [("막힌 값도 그대로 돌려줌", "? String(u) : '#'", "? String(u) : String(u)"),
            ("스킴 표에서 tel 뺌", " || u.s === 'tel') return true;", ") return true;"),
            ("문자 참조 풀어 다시 보기 뺌", "return urlOk1(s, img) && urlOk1(deRef(s), img);", "return urlOk1(s, img);"),
            ("전역 safeUrl 이름 바꿔치기", "esc, safeUrl, report })", "esc, safeUrl: esc, report })"),
            ("safeUrl 다시 대입", "  function safeUrl(u, kind) {", "  safeUrl = u => u;\n  function safeUrl(u, kind) {"),
            ("내보내기 뒤쪽 같은 열쇠 덮어쓰기", "esc, safeUrl, report })", "esc, safeUrl, report, safeUrl: esc })"),
            ("window.TJDOM 두 번 대입", "  window.TJDOM = Object.freeze(", "  window.TJDOM = { safeUrl: esc };\n  window.TJDOM = Object.freeze("),
            ("구조 분해로 safeUrl 다시 대입", "  window.TJDOM = Object.freeze(", "  [safeUrl] = [esc];\n  window.TJDOM = Object.freeze("),
            ("내보내기를 매개변수 safeUrl 로 감쌈", "  window.TJDOM = Object.freeze({ set, insert, replace, clear, esc, safeUrl, report });",
             "  (safeUrl => { window.TJDOM = Object.freeze({ set, insert, replace, clear, esc, safeUrl, report }); })(esc);")]
    miss13 = []
    for why9, a9, b9 in MUT9:
        if tj9.count(a9) != 1:
            miss13.append("바꿀 글 못 찾음: " + why9)
        elif L.safe_url_check(syn_root({TJD: tj9.replace(a9, b9)}), None)[0]:
            miss13.append("못 잡음: " + why9)
    OTHER9 = (("다른 파일이 window.TJDOM 대입", "window.TJDOM = { safeUrl: u => u };"),
              ("다른 파일이 defineProperty 로 바꿔치기", "Object.defineProperty(window, 'TJDOM', { value: {} });"),
              ("다른 파일이 맨 이름으로 다시 대입", "TJDOM = Object.freeze({ esc: TJDOM.esc });"))
    for why9, extra9 in OTHER9:
        if L.safe_url_check(syn_root({TJD: tj9, "z.js": extra9}), None)[0]:
            miss13.append("못 잡음: " + why9)
    T.chk(not miss13, "[13] 합성: tjdom.js URL 검사 정의를 바꾼 꼴 %d개 + 다른 파일의 전역 바꿔치기 %d꼴 = 전부 안 믿음" % (len(MUT9), len(OTHER9)), miss13)
cur13 = L.safe_url_sites(T.ROOT)
T.chk(cur13 == L.SAFE_URL_SITES, "[13] 인정 자리 표 %d줄(자리 %d) = 지금 src 의 TJDOM.safeUrl 자리와 정확히 같음(새 자리·글 바뀐 자리 = 표를 다시 판정)"
      % (len(L.SAFE_URL_SITES), sum(L.SAFE_URL_SITES.values())),
      {"표에만": sorted(set(L.SAFE_URL_SITES) - set(cur13)), "src 에만": sorted(set(cur13) - set(L.SAFE_URL_SITES))})
if tj9 is not None and su_ok and cur13 == L.SAFE_URL_SITES:
    miss13 = []
    for unit9 in sorted({k[0] for k in L.SAFE_URL_SITES}):
        src9 = U13[unit9]
        want0 = {"%s::%s" % (unit9, k[1]): v for k, v in L.SAFE_URL_SITES.items() if k[0] == unit9}
        got0 = L.js_census(syn_root({TJD: tj9, unit9: src9}), node=None)[0].get("url:safe", {})
        if got0 != want0:
            miss13.append("%s 그대로인데 인정 %s ≠ 표 %s" % (unit9, got0, want0))
        n9 = src9.count("TJDOM.safeUrl(")
        for j9 in range(n9):
            k9 = -1
            for _ in range(j9 + 1):
                k9 = src9.index("TJDOM.safeUrl(", k9 + 1)
            mut9 = src9[:k9] + "TJDOM.safeUrl('' + " + src9[k9 + len("TJDOM.safeUrl("):]
            got9 = L.js_census(syn_root({TJD: tj9, unit9: mut9}), node=None)[0].get("url:safe", {})
            if sum(got9.values()) != sum(want0.values()) - 1:
                miss13.append("%s %d번째 자리 글 바꿈 → 인정 %s(하나 줄어야)" % (unit9, j9 + 1, got9))
        for why9, mut9 in (("esc 매개변수 함수 덧붙임", src9 + "\nfunction zz9(esc) { return esc; }\n"),
                           ("esc 기본값 매개변수 함수 덧붙임", src9 + "\nfunction zz9(v, esc = TJDOM.esc) { return esc(v); }\n"),
                           ("esc 정의를 let 으로", src9.replace("const esc = TJDOM.esc;", "let esc = TJDOM.esc;", 1))):
            if mut9 == src9:
                continue
            got9 = L.js_census(syn_root({TJD: tj9, unit9: mut9}), node=None)[0].get("url:safe", {})
            if got9:
                miss13.append("%s %s → 인정 %s(0 이어야)" % (unit9, why9, got9))
    T.chk(not miss13, "[13] 합성: 표 단위마다 그대로 = 표 수 · 자리 글 한 군데 바꿈 = 그 자리만 인정 빠짐 · esc 를 다시 묶음(매개변수·기본값·let) = 그 파일 인정 0", miss13)
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()

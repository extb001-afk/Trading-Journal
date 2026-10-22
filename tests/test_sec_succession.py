#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import os  # noqa: E402
import tempfile  # noqa: E402

import _arch_ratchet as R  # noqa: E402
import _sec_succession as S  # noqa: E402

SINKS = {"sink_all": ("sink:static", "sink:esc", "sink:raw"), "sink_esc_raw": ("sink:esc", "sink:raw"), "sink_raw": ("sink:raw",)}
ESC_SPEC = R.SPECS["js_esc"]


def sink_metrics(root):
    counts, _smp = L.js_census(root)
    out = {}
    for m, cats in SINKS.items():
        for c in cats:
            for k, v in counts.get(c, {}).items():
                out.setdefault(m, {})[k] = out.get(m, {}).get(k, 0) + v
    for c, d in counts.items():
        if not c.startswith("sink:"):
            out[c] = dict(d)
    return out


def tree(files):
    root = tempfile.mkdtemp(dir=T.TMP)
    os.makedirs(os.path.join(root, "web", "v2"))
    for nm, txt in files.items():
        with open(os.path.join(root, "web", "v2", nm), "w", encoding="utf-8") as f:
            f.write(txt)
    return root


def xss_flow(name, cur, base, modes=None):
    modes = modes or {}
    now, succ = [], {}
    for m in sorted(set(cur) | set(base)):
        viol, _dec, _mv, g = L.compare_succ(name, m, cur, base, modes.get(m, "site"), None, cur)
        now += ["%s · %s" % (m, v[0]) for v in viol]
        succ.update(g)
    return now, L.ref_violations(name, cur, base, modes, cur), succ


def esc_doc(root):
    return R.current_js(root)[0]["js_esc"]


def esc_flow(cur, base):
    bad, _stale, succ = R.judge_now(ESC_SPEC, cur, base)
    return bad, R.judge_ref(ESC_SPEC, R.lower(ESC_SPEC, cur, base), base, cur) + R.judge_ref(ESC_SPEC, cur, base, cur), succ


def failed(label, flow):
    now, ref, _s = flow
    T.chk(bool(now) and bool(ref), "반례 실패: %s (지금 값 비교·기준 커밋 비교 둘 다)" % label, {"지금": now[:4], "기준": ref[:4]})


def passed(label, flow, want=None):
    now, ref, succ = flow
    T.chk(not now and not ref and (want is None or sorted(succ) == sorted(want)), "정상 승계 통과: %s" % label,
          {"지금": now[:4], "기준": ref[:4], "승계": succ, "기대": want})


print("[1] 지금 트리 — 승계 규칙이 기존 판정을 안 바꿈(기준선에 이미 적힌 열쇠 = 승계 0)")
cur_x = sink_metrics(T.ROOT)
sk1 = cur_x.get("sink_all", {})
if S.TJDOM in dict(L.js_units(T.ROOT)):
    T.chk(sum(sk1.values()) == 1 and all(k.startswith(S.TJDOM + "::") for k in sk1), "지금 트리 싱크 조사(8-1 뒤) = tjdom.js 한 자리뿐", sk1)
else:
    T.chk(sum(sk1.values()) > 0, "지금 트리 싱크 조사 = 자리 있음 · tjdom.js 없음(승계 대상 0)", sum(sk1.values()))
for nm in ("xss", "xss_canary", "xss_csp"):
    bl = L.load_baseline(nm)
    if bl is None:
        print("SKIP 기준선 sec_%s 없음(공개 배치) — 대조 건너뜀" % nm)
        continue
    bm = bl["metrics"]
    sides = [("기준선", bm)] + ([("지금 값", cur_x)] if nm == "xss" else [])
    for what, side in sides:
        diff = []
        for m in sorted(set(side) | set(bm)):
            got = L.compare_succ(nm, m, side, bm, "exact" if nm != "xss" else "site", None, side)
            want = L.compare(side.get(m, {}), bm.get(m, {}), "exact" if nm != "xss" else "site")
            if tuple(got[:3]) != tuple(want) or got[3]:
                diff.append(m)
        T.chk(not diff, "sec_%s: %s ↔ 기준선 = compare 결과 그대로 · 승계 0" % (nm, what), diff)
    T.chk(not L.ref_violations(nm, bm, bm, S.CSP_MODES if nm == "xss_csp" else {}, bm), "sec_%s: 기준선 ↔ 같은 기준선 위반 0" % nm)
if R.repo_layout() and R.load("js_esc") is not None:
    jb, jc = R.load("js_esc"), R.current_js(T.ROOT)[0]["js_esc"]
    T.chk(R.judge_now(ESC_SPEC, jc, jb) == (R.compare(ESC_SPEC, jc, jb) + ({},)) and R.lower(ESC_SPEC, jc, jb) == R.tighten(ESC_SPEC, jc, jb),
          "js_esc: 지금 값 ↔ 기준선 = compare·tighten 그대로 · 승계 0")
    T.chk(R.judge_ref(ESC_SPEC, jb, jb, jc) == [], "js_esc: 기준선 ↔ 같은 기준선 변조 실패 0")
else:
    print("SKIP 기준선 js_esc 없음(공개 배치) — 대조 건너뜀")
tj_src = dict(L.js_units(T.ROOT)).get(S.TJDOM)
if tj_src is None:
    print("(web/v2/tjdom.js 없음 — esc 정의 무결성 검사 대상 없음 · 8-1 부터 적용)")
else:
    probs = S.tjdom_esc_problems(L.js_defs_all(tj_src, ["esc"]).get("esc", []), R.current_js(T.ROOT)[0]["js_esc"]["items"].get(S.TJDOM_PATH, {}).get("n", 0))
    T.chk(not probs, "tjdom.js esc 정의 무결성(정의 하나 · 엔티티 글자 그대로 · js_esc 1)", probs)

print("[2] 합성 트리 — 싱크·esc 승계")
ESC = ("String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')"
       ".replace(/\"/g, '&quot;').replace(/'/g, '&#39;')")
ESC38 = ("String(s).replace(/&/g, '&#38;').replace(/</g, '&#60;').replace(/>/g, '&#62;')"
         ".replace(/\"/g, '&#34;').replace(/'/g, '&#39;')")
A0 = ("(function () {\n  const esc = s => " + ESC + ";\n"
      "  function paint(el, x) { el.innerHTML = '<b>' + esc(x) + '</b>'; }\n"
      "  function show(el, h) { el.innerHTML = h; }\n  window.A = { paint, show };\n})();\n")
B0 = ("(function () {\n  function esc(s) { return " + ESC + "; }\n"
      "  function put(el, h) { el.insertAdjacentHTML('beforeend', h); }\n  function txt(el, x) { el.innerHTML = esc(x); }\n"
      "  window.B = { put, txt };\n})();\n")
IDX0 = ("<!doctype html><html><body><div id=\"v\"></div><script>(function () {\n  const es = s => " + ESC + ";\n"
        "  document.getElementById('v').innerHTML = '<i>' + es(location.hash) + '</i>';\n})();</script></body></html>\n")
A1 = ("(function () {\n  function paint(el, x) { TJDOM.set(el, '<b>' + TJDOM.esc(x) + '</b>'); }\n"
      "  function show(el, h) { TJDOM.set(el, h); }\n  window.A = { paint, show };\n})();\n")
B1 = ("(function () {\n  function put(el, h) { TJDOM.insert(el, 'beforeend', h); }\n  function txt(el, x) { TJDOM.set(el, TJDOM.esc(x)); }\n"
      "  window.B = { put, txt };\n})();\n")
IDX1 = ("<!doctype html><html><body><div id=\"v\"></div><script>(function () {\n"
        "  document.getElementById('v').textContent = location.hash;\n})();</script></body></html>\n")


def tj(sinks="  function parse(ctx, h) { ctx.innerHTML = h; return ctx; }\n", esc="  function esc(s) { return " + ESC + "; }\n"):
    return ("(function () {\n" + esc + sinks +
            "  function set(el, h) { el.replaceChildren(...parse(document.createElement('div'), h).childNodes); }\n"
            "  function insert(el, p, h) { el.append(...parse(document.createElement('div'), h).childNodes); }\n"
            "  window.TJDOM = { set, insert, esc };\n})();\n")


base_root = tree({"a.js": A0, "b.js": B0, "index.html": IDX0})
good_root = tree({"a.js": A1, "b.js": B1, "index.html": IDX1, "tjdom.js": tj()})
MB, MG = sink_metrics(base_root), sink_metrics(good_root)
T.chk(sum(MB["sink_all"].values()) == 5 and len(MB["sink_all"]) == 5 and MG["sink_all"] == {"tjdom.js::parse": 1},
      "합성 트리 싱크 조사 = 기준 5자리(3파일) · 작업 tjdom.js::parse 1", [MB.get("sink_all"), MG.get("sink_all")])
passed("싱크 5자리 → tjdom.js::parse 1", xss_flow("xss", MG, MB), ["tjdom.js::parse"])
EB, EG = esc_doc(base_root), esc_doc(good_root)
T.chk({k: v["n"] for k, v in EB["items"].items()} == {"web/v2/a.js": 1, "web/v2/b.js": 1, "web/v2/index.html": 1}
      and {k: v["n"] for k, v in EG["items"].items()} == {S.TJDOM_PATH: 1}, "합성 트리 js_esc = 기준 3벌 · 작업 tjdom.js 1", [EB, EG])
passed("esc 사본 3벌 → tjdom.js 1", esc_flow(EG, EB), [S.TJDOM_PATH])
T.chk(R.lower(ESC_SPEC, EG, EB)["items"] == {S.TJDOM_PATH: {"n": 1}}, "--update-lower 새 기준선 = 승계 열쇠 tjdom.js 1 만(옛 사본 줄 빠짐)",
      R.lower(ESC_SPEC, EG, EB))
named_root = tree({"a.js": A1, "b.js": B1, "index.html": IDX1,
                   "tjdom.js": tj("  function show(ctx, h) { ctx.innerHTML = h; return ctx; }\n  const parse = show;\n")})
passed("tjdom.js 파서 함수 이름이 옛 함수(a.js::show)와 같아도 승계 규칙으로만 판정", xss_flow("xss", sink_metrics(named_root), MB), ["tjdom.js::show"])
T.chk(("tjdom.js", "esc") in [(u, n) for u, n, _t in L.escaper_defs(good_root)],
      "카나리아 대상 = tjdom.js 의 esc(파일 안에서 안 불려도 — 화면 파일은 TJDOM.esc 로 부름)", [(u, n) for u, n, _t in L.escaper_defs(good_root)])
T.chk(not S.tjdom_esc_problems(L.js_defs_all(tj(), ["esc"])["esc"], 1), "tjdom.js esc 무결성: 정상 정의 = 문제 0")

failed("다른 파일(c.js)에 싱크 하나 더",
       xss_flow("xss", sink_metrics(tree({"a.js": A1, "b.js": B1, "index.html": IDX1, "tjdom.js": tj(),
                                          "c.js": "function more(el, h) { el.innerHTML = h; }\n"})), MB))
failed("index.html 인라인 싱크가 남음", xss_flow("xss", sink_metrics(tree({"a.js": A1, "b.js": B1, "index.html": IDX0, "tjdom.js": tj()})), MB))
failed("tjdom.js 한 함수에 싱크 둘",
       xss_flow("xss", sink_metrics(tree({"a.js": A1, "b.js": B1, "index.html": IDX1,
                                          "tjdom.js": tj("  function parse(ctx, h) { ctx.innerHTML = h; ctx.innerHTML += ''; return ctx; }\n")})), MB))
failed("tjdom.js 두 함수에 싱크 하나씩(하나는 옛 이름 put 을 빌림 — 기존 '옮김' 인정 못 받음)",
       xss_flow("xss", sink_metrics(tree({"a.js": A1, "b.js": B1, "index.html": IDX1,
                                          "tjdom.js": tj("  function parse(ctx, h) { ctx.innerHTML = h; return ctx; }\n"
                                                         "  function put(el, h) { el.insertAdjacentHTML('beforeend', h); }\n")})), MB))
failed("기준 합계 0(옮겨 올 싱크 없음 — sink_raw 0 인 기준)",
       xss_flow("xss", {"sink_raw": {"tjdom.js::parse": 1}, "sink_all": {"tjdom.js::parse": 1}}, {"sink_all": {"a.js::x": 1}}))
stale_bl = {m: dict(MB.get(m, {}), **MG.get(m, {})) for m in set(MB) | set(MG)}
stale_ref = L.ref_violations("xss", stale_bl, MB, {}, MG)
T.chk(any("tjdom.js::parse" in x for x in stale_ref), "반례 실패: 옛 줄을 안 낮춘 작업 기준선(+ tjdom.js) ↔ 기준 커밋", stale_ref[:4])
T.chk(bool(L.ref_violations("xss", {"sink_all": {"tjdom.js::parse": 2}}, MB, {}, MG)), "반례 실패: 작업 기준선을 손으로 tjdom.js 2 로 올림")
out_viol = L.compare_succ("xss", "sink_all", {"sink_all": {"a.js::parse": 1}}, {"sink_all": {"tjdom.js::parse": 1}}, "site", None,
                          {"sink_all": {"a.js::parse": 1}})[0]
plain = L.compare({"a.js::parse": 1}, {"tjdom.js::parse": 1}, "site")[0]
T.chk(bool(out_viol) and not plain, "반례 실패: tjdom.js 싱크를 다른 파일 같은 이름 함수로 옮김(기존 compare 는 '옮김' 으로 봄 — 승계 규칙은 막음)",
      [out_viol, plain])

failed("esc 사본을 안 줄이고 tjdom.js esc 추가", esc_flow(esc_doc(tree({"a.js": A0, "b.js": B0, "index.html": IDX0, "tjdom.js": tj()})), EB))
failed("tjdom.js esc 사본 둘",
       esc_flow(esc_doc(tree({"a.js": A1, "b.js": B1, "index.html": IDX1,
                              "tjdom.js": tj(esc="  function esc(s) { return " + ESC + "; }\n  const esc2 = s => " + ESC + ";\n")})), EB))
T.chk(bool(esc_flow({"items": {S.TJDOM_PATH: {"n": 1}, "web/index.html": {"n": 3}}},
                    {"items": {"web/v2/a.js": {"n": 1}, "web/index.html": {"n": 1}}})[0]), "반례 실패: esc 사본 합계 늘어남(다른 화면 사본 +2)")
r38 = tree({"a.js": A1, "b.js": B1, "index.html": IDX1, "tjdom.js": tj(esc="  function esc(s) { return " + ESC38 + "; }\n")})
e38 = esc_doc(r38)
p38 = S.tjdom_esc_problems(L.js_defs_all(dict(L.js_units(r38))["tjdom.js"], ["esc"]).get("esc", []), e38["items"].get(S.TJDOM_PATH, {}).get("n", 0))
T.chk(not esc_flow(e38, EB)[0] and bool(p38), "반례: '&#38;' 표기로 바꾼 tjdom.js esc = js_esc 셈 0(래칫은 통과) → 무결성 검사가 실패로 잡음", p38)
T.chk(bool(S.tjdom_esc_problems([], 1)) and bool(S.tjdom_esc_problems(["function esc(s){return s}", "let esc = s => s;"], 1)),
      "반례 실패: tjdom.js esc 정의 없음 · 둘")

print("[3] 카나리아 known_hole")
COPIES = ["app.js::esc", "health.js::esc", "index.html::es", "salelink.js::esc0", "salelink.js::esc", "search.js::esc", "setup.js::esc", "wow.js::esc"]
KB = {"esc:%s:%s" % (c, k): 1 for c in COPIES for k in S.ESC_KINDS}
KB.update({"esc:wow.js::xml:bidi": 1, "esc:wow.js::xml:sq": 1, "esc:wow.js::xml:url_scheme": 1, "render:app.icon:bidi": 1, "render:salelink.xl:js_url": 1})
KG = {k: 1 for k in KB if not k.startswith(tuple("esc:%s:" % c for c in COPIES))}
KG.update({"esc:tjdom.js::esc:bidi": 1, "esc:tjdom.js::esc:url_scheme": 1})


def can(cur, base=None):
    return xss_flow("xss_canary", {"known_hole": cur}, {"known_hole": KB if base is None else base}, {"known_hole": "exact"})


passed("esc 사본 8벌(bidi·url_scheme) → esc:tjdom.js::esc 2종", can(KG), ["esc:tjdom.js::esc:bidi", "esc:tjdom.js::esc:url_scheme"])
failed("tjdom.js esc 의 sq(대응 표 밖)", can(dict(KG, **{"esc:tjdom.js::esc:sq": 1})))
failed("tjdom.js 둘째 정의 esc#2", can(dict(KG, **{"esc:tjdom.js::esc#2:bidi": 1})))
failed("tjdom.js 다른 이름(es)", can(dict(KG, **{"esc:tjdom.js::es:bidi": 1})))
failed("지운 사본이 남은 채 tjdom.js 구멍 추가", can(dict(KB, **{"esc:tjdom.js::esc:bidi": 1})))
failed("기준에 없던 종류(url_scheme 사본 0 인 기준)",
       can({"esc:tjdom.js::esc:url_scheme": 1}, {"esc:app.js::esc:bidi": 1, "esc:wow.js::xml:bidi": 1}))
failed("tjdom.js 밖 새 구멍(render)", can(dict(KG, **{"render:tab_x.y:exec_markup": 1})))

print("[4] CSP 대응 표 · Report-Only 따로 셈")
import http_assets  # noqa: E402

NOW, NOW_RO = http_assets.v2_csp(b"<script>1</script>", "succession-test", "report")


def policy(dirs):
    return "; ".join(" ".join([d] + v) for d, v in dirs.items())


def strict(**over):
    d, _dup = S.csp_dirs(NOW)
    d["style-src"] = ["'self'"]
    d["img-src"] = ["'self'", "data:", "blob:"]
    d["require-trusted-types-for"] = ["'script'"]
    d["trusted-types"] = ["tj-html"]
    for k, v in over.items():
        if v is None:
            d.pop(k.replace("_", "-"), None)
        else:
            d[k.replace("_", "-")] = v
    return policy(d)


BASE_C = S.csp_metrics(NOW)
T.chk(sorted(BASE_C["csp_weak"]) == sorted(["style-src 'unsafe-inline'", "img-src https:(모든 https 이미지)", "Trusted Types 없음(require-trusted-types-for)"])
      and len(BASE_C["csp_source"]) == 16, "지금 정책 지표 = 약점 3 · 출처 16(기준선 sec_xss_csp 와 같은 정의)", BASE_C)
T.chk(S.csp_metrics(strict())["csp_weak"] == {} and sorted(S.csp_metrics(strict())["csp_source"]) == sorted(S.strict_sources(BASE_C["csp_source"])),
      "엄격안 = 약점 0 · 출처 = 지금 − img-src https: − style-src 'unsafe-inline' + TT 두 줄", S.csp_metrics(strict()))


def csp(cur, base=None):
    return xss_flow("xss_csp", cur, BASE_C if base is None else base, S.CSP_MODES)


P = S.csp_metrics(NOW, strict())
passed("배-P(강제 무변 + Report-Only 엄격안 · 기준 = 지금)", csp(P), sorted(S.csp_metrics(strict())["csp_source"]))
passed("배-P(Report-Only 에서 connect-src jsDelivr 도 뺌)", csp(S.csp_metrics(NOW, strict(connect_src=["'self'"]))))
T.chk(NOW_RO == strict(connect_src=["'self'"]), "8-4a 실제 Report-Only 정책(http_assets.v2_csp) = 엄격안(connect-src 'self' — jsDelivr 0)", NOW_RO)
passed("8-4a 실제 정책 쌍(http_assets.v2_csp — 강제 무변 + Report-Only 엄격안)", csp(S.csp_metrics(NOW, NOW_RO)), sorted(S.csp_metrics(NOW_RO)["csp_source"]))
Q = S.csp_metrics(strict())
passed("배-Q(강제 = 엄격안 · 기준 = 지금 — 배-P 를 안 합치고 함께 낼 때)", csp(Q), list(S.CSP_ADD))
passed("배-Q(기준 = 배-P 기준선)", csp(Q, P), list(S.CSP_ADD))
T.chk(http_assets.v2_csp(b"<script>1</script>", "succession-test") == (NOW_RO, None), "8-4b 실제 정책(http_assets.v2_csp 단계 enforce) = (8-4a Report-Only 엄격안 바이트 그대로, 없음)")
failed("강제 정책 img-src 에 https://cdn.jsdelivr.net", csp(S.csp_metrics(NOW.replace("img-src 'self' data: blob: https:",
                                                                                     "img-src 'self' data: blob: https://cdn.jsdelivr.net"))))
failed("엄격안 강제 + img-src https://cdn.jsdelivr.net", csp(S.csp_metrics(strict(img_src=["'self'", "data:", "blob:", "https://cdn.jsdelivr.net"]))))
failed("Report-Only 엄격안 + img-src https://cdn.jsdelivr.net",
       csp(S.csp_metrics(NOW, strict(img_src=["'self'", "data:", "blob:", "https://cdn.jsdelivr.net"]))))
failed("표 밖 출처 하나(connect-src https://evil.example)", csp(S.csp_metrics(strict(connect_src=["'self'", "https://evil.example"]))))
failed("Report-Only 에만 약화: 지금 정책 그대로", csp(S.csp_metrics(NOW, NOW)))
failed("Report-Only 에만 약화: style-src 'unsafe-inline'", csp(S.csp_metrics(NOW, strict(style_src=["'self'", "'unsafe-inline'"]))))
failed("Report-Only 에만 약화: img-src https:", csp(S.csp_metrics(NOW, strict(img_src=["'self'", "data:", "blob:", "https:"]))))
failed("Report-Only 지시어 누락: require-trusted-types-for", csp(S.csp_metrics(NOW, strict(require_trusted_types_for=None))))
failed("Report-Only 지시어 누락: object-src", csp(S.csp_metrics(NOW, strict(object_src=None))))
failed("Report-Only 다른 값: script-src 'unsafe-eval'", csp(S.csp_metrics(NOW, strict(script_src=["'self'", "'unsafe-eval'"]))))
failed("Report-Only 모르는 지시어(report-uri)", csp(S.csp_metrics(NOW, strict(report_uri=["/csp"]))))
failed("강제 TT 한 줄만(trusted-types 만)", csp(S.csp_metrics(strict(require_trusted_types_for=None))))
failed("강제 TT 다른 값(trusted-types tj-html default)", csp(S.csp_metrics(strict(trusted_types=["tj-html", "default"]))))
failed("강제 TT 다른 값(require-trusted-types-for 'script' 'x')", csp(S.csp_metrics(strict(require_trusted_types_for=["'script'", "'x'"]))))
failed("배-P 뒤(기준 = 배-P) Report-Only 에서 object-src 만 뺌(늘어난 줄 없음 · 빠짐만으로 약화)", csp(S.csp_metrics(NOW, strict(object_src=None)), P))
failed("배-Q 뒤(기준 = 배-Q) 강제 trusted-types 만 뺌(TT 한 줄만 남음)", csp(S.csp_metrics(strict(trusted_types=None)), Q))
passed("배-P 뒤(기준 = 배-P) Report-Only 통째 제거 = 줄어듦", csp(S.csp_metrics(NOW), P))
T.finish()

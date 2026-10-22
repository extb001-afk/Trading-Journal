#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import os  # noqa: E402
import re  # noqa: E402

TJD = os.path.join(T.ROOT, "web", "v2", "tjdom.js")
if not os.path.isfile(TJD):
    T.chk(True, "tjdom.js 없음(8-1 앞 트리) · 건너뜀")
    T.finish()
SRC = open(TJD, encoding="utf-8").read()
TOKS, _ = L.js_tokens(SRC)


def table(name):
    for i, t in enumerate(TOKS):
        if t.k == "name" and t.v == name and i + 3 < len(TOKS) and TOKS[i + 1].v == "=" and TOKS[i + 2].v == "words" and TOKS[i + 3].v == "(":
            parts, j = [], i + 4
            while j < len(TOKS) and TOKS[j].v != ")":
                if TOKS[j].k == "str":
                    parts.append(TOKS[j].v)
                elif not (TOKS[j].k == "pun" and TOKS[j].v == "+"):
                    return None
                j += 1
            return set("".join(parts).split())
    return None


NAMES = ("EL_HTML", "EL_SVG", "AT", "ST", "CP_EL_HTML", "CP_EL_SVG", "CP_AT", "CP_ST", "FORBID_EL", "FORBID_AT", "URL_AT")
TB = {n: table(n) for n in NAMES}
T.chk(all(v is not None for v in TB.values()), "tjdom.js 표 %d개를 글자 상수로 읽음" % len(NAMES), [n for n, v in TB.items() if v is None])
TB = {n: (v or set()) for n, v in TB.items()}


def pieces(toks):
    for t in toks:
        if t.k == "str":
            yield t.v
        elif t.k == "tpl":
            for q in t.q or ():
                yield q
            for ex in t.x or ():
                yield from pieces(ex)


TAG = re.compile(r"<([A-Za-z][A-Za-z0-9-]*)")
ATT = re.compile(r"(?<=[\s\"'])([A-Za-z_:][-A-Za-z0-9_:.]*)=(?=[\"']|$)")
BOOLS = ("allowfullscreen async autofocus autoplay checked controls default defer disabled formnovalidate hidden inert ismap itemscope loop"
         " multiple muted nomodule novalidate open playsinline readonly required reversed selected").split()
BOOL_IN_TAG = re.compile(r"<[A-Za-z][^<>]*?\s(%s)(?=[\s/>]|$)" % "|".join(BOOLS))
BOOL_TAIL = re.compile(r"(?<=[\s\"'])(%s)(?=\s*/?>)" % "|".join(BOOLS))
STY = re.compile(r"\bstyle=\"([^\"]*)")
DECL = re.compile(r"(?:^|;)\s*(--[a-z0-9-]+|-?[a-z][a-z-]*)\s*:")
tags, atts, bools, stys = {}, {}, {}, {}


def add(d, k, where):
    d.setdefault(k, where)


for unit, src in L.js_units(T.ROOT):
    if unit == "tjdom.js":
        continue
    toks, _ = L.js_tokens(src)
    for s in pieces(toks):
        for m in TAG.finditer(s):
            add(tags, m.group(1).lower(), unit)
        for m in ATT.finditer(s):
            add(atts, m.group(1).lower(), unit)
        if s.strip() in BOOLS and s != s.strip():
            add(bools, s.strip(), unit)
        for m in list(BOOL_IN_TAG.finditer(s)) + list(BOOL_TAIL.finditer(s)):
            add(bools, m.group(1), unit)
        for m in STY.finditer(s):
            for d in DECL.finditer(m.group(1)):
                add(stys, d.group(1), unit)

EL = TB["EL_HTML"] | TB["EL_SVG"]
miss_el = sorted(k for k in tags if k not in EL)
T.chk(not miss_el, "화면 글 태그 %d종 ⊆ tjdom.js 허용 요소(EL_HTML ∪ EL_SVG)" % len(tags), {k: tags[k] for k in miss_el})
DA = re.compile(r"^(data|aria)-[a-z0-9_.-]+$")
miss_at = sorted(k for k in atts if k not in TB["AT"] and not DA.match(k))
plain = sorted(k for k in atts if not DA.match(k))
T.chk(not miss_at, "화면 글 속성 %d종(data-*·aria-* 빼고 %d) ⊆ tjdom.js 허용 속성(AT · data-*·aria-* 이름 문법)" % (len(atts), len(plain)),
      {k: atts[k] for k in miss_at})
miss_b = sorted(k for k in bools if k not in TB["AT"])
T.chk(not miss_b, "화면 글 값 없는 불리언 속성 %s ⊆ AT" % sorted(bools), {k: bools[k] for k in miss_b})
miss_st = sorted(k for k in stys if k not in TB["ST"] and not k.startswith("--"))
T.chk(not miss_st, "화면 글 style 선언 이름 %d종 ⊆ tjdom.js ST(+ --이름)" % len(stys), {k: stys[k] for k in miss_st})
T.chk(len(tags) >= 57 and len(plain) >= 61, "실측 어휘 크기(요소 ≥ 57 · 속성 ≥ 61 — 설계 0-2) · 도구가 덜 뽑으면 실패", {"요소": len(tags), "속성": len(plain)})
unused = sorted((EL - set(tags)) - {"title"}) + sorted(TB["AT"] - set(atts) - set(bools))
T.chk(not unused, "허용 표에 화면 글에 없는 이름 0(허용 = 실측만 · 나머지는 호환 표로)", unused)

print("표 무결성")
F_EL, F_AT = TB["FORBID_EL"], TB["FORBID_AT"]
T.chk(not ((EL | TB["CP_EL_HTML"] | TB["CP_EL_SVG"]) & F_EL), "허용·호환 요소 ∩ 늘 금지 요소 = ∅", sorted((EL | TB["CP_EL_HTML"] | TB["CP_EL_SVG"]) & F_EL))
T.chk(not ((TB["AT"] | TB["CP_AT"]) & F_AT), "허용·호환 속성 ∩ 늘 금지 속성 = ∅", sorted((TB["AT"] | TB["CP_AT"]) & F_AT))
T.chk(not (TB["EL_HTML"] & TB["CP_EL_HTML"]) and not (TB["EL_SVG"] & TB["CP_EL_SVG"]) and not (TB["AT"] & TB["CP_AT"]) and not (TB["ST"] & TB["CP_ST"]),
      "허용 ∩ 호환 = ∅(요소·속성·style 이름)")
T.chk(not [k for k in TB["AT"] | TB["CP_AT"] if k.startswith("on")], "허용·호환 속성에 on* 0")
T.chk(TB["AT"] & TB["URL_AT"] == {"href"} and TB["CP_AT"] & TB["URL_AT"] == {"src"}, "URL 속성: 허용 = href · 호환 = src 만(둘 다 safeUrl 검사)",
      {"허용": sorted(TB["AT"] & TB["URL_AT"]), "호환": sorted(TB["CP_AT"] & TB["URL_AT"])})
T.chk({"name", "srcset", "contenteditable"}.isdisjoint(TB["AT"] | TB["CP_AT"]), "name·srcset·contenteditable 은 허용·호환 밖(문서 이름 덮어쓰기·바깥 자원)")
T.chk({"a", "filter", "clippath", "mask", "marker", "pattern", "use", "image", "foreignobject"}.isdisjoint(TB["EL_SVG"] | TB["CP_EL_SVG"]),
      "SVG a·filter·clipPath·mask·marker·pattern·use·image·foreignObject 은 허용·호환 밖")
need_forbid = set("script style link meta base iframe frame object embed form math foreignobject template noscript animate set animatemotion"
                  " animatetransform animatecolor mpath discard use image feimage".split())
T.chk(need_forbid <= F_EL, "늘 금지 요소 ⊇ 설계 4장 목록", sorted(need_forbid - F_EL))
need_fat = set("srcdoc formaction action xlink:href ping attributename values from to by".split())
T.chk(need_fat <= F_AT, "늘 금지 속성 ⊇ 설계 4장 목록", sorted(need_fat - F_AT))
T.chk(all(n == n.lower() for v in TB.values() for n in v), "표 이름 = 전부 소문자(정제기는 소문자로 대조 — 대문자 항목 = 죽은 항목)",
      sorted(n for v in TB.values() for n in v if n != n.lower()))
ST_FORBID = {"behavior", "-moz-binding"}
T.chk(not ((TB["ST"] | TB["CP_ST"]) & ST_FORBID), "style 허용·호환 ∩ 늘 금지 style 이름 = ∅", sorted((TB["ST"] | TB["CP_ST"]) & ST_FORBID))
URL_KNOWN = set(("href src srcset action formaction poster cite data background longdesc usemap manifest codebase archive icon profile lowsrc"
                 " dynsrc ping xlink:href xml:base classid imagesrcset itemid itemtype attributionsrc").split())
url_seen = (set(atts) | TB["AT"] | TB["CP_AT"]) & URL_KNOWN
T.chk(url_seen <= TB["URL_AT"] | TB["FORBID_AT"], "URL_AT ⊇ 화면 어휘·허용·호환 표의 URL 받는 속성 %s(늘 금지 속성은 따로 지움)" % sorted(url_seen),
      sorted(url_seen - TB["URL_AT"] - TB["FORBID_AT"]))
T.chk(set(atts) & URL_KNOWN <= TB["URL_AT"], "화면 글의 URL 받는 속성 %s 전부 URL_AT(safeUrl 검사 대상)" % sorted(set(atts) & URL_KNOWN),
      sorted(set(atts) & URL_KNOWN - TB["URL_AT"]))
T.chk((URL_KNOWN - TB["URL_AT"]) <= TB["FORBID_AT"] | (URL_KNOWN - TB["AT"] - TB["CP_AT"]), "URL_AT 밖 URL 속성은 허용·호환 표에도 없음(표 밖 = 두 판 모두 지움)",
      sorted((URL_KNOWN - TB["URL_AT"]) & (TB["AT"] | TB["CP_AT"])))
LOOSE = {}
for unit, src in L.js_units(T.ROOT):
    if unit == "tjdom.js":
        continue
    for s in pieces(L.js_tokens(src)[0]):
        for m in re.finditer(r"(?:^|[;\"'\s{])(-?[a-z][a-z-]*)\s*:", s):
            LOOSE.setdefault(m.group(1), unit)
st_unused = sorted(n for n in TB["ST"] if n not in stys and n not in LOOSE)
print("  style 허용 이름 중 style=\"…\" 정확 대조 밖(이어 붙인 조각에서만 보임): %s" % sorted(n for n in TB["ST"] if n not in stys))
T.chk(not st_unused, "허용 style 이름 %d개가 화면 글에 쓰임(안 쓰이는 이름 0)" % len(TB["ST"]), st_unused)
import _xss_abs as X  # noqa: E402
CEN = X.census(T.ROOT)
sk = [x for x in CEN["sink"] if x.file == "tjdom.js"]
pl = [x for x in CEN["policy"] if x.file == "tjdom.js"]
T.chk(len(sk) == 1 and sk[0].fn == "frag", "tjdom.js 안 HTML 싱크 = 1(frag 의 비활성 문맥 요소 대입 · _xss_abs)", [tuple(x) for x in sk])
T.chk(len(pl) == 1 and pl[0].detail == "tj-html", "tjdom.js 안 createPolicy = 1('tj-html' · _xss_abs)", [tuple(x) for x in pl])
nm_cnt = {k: sum(1 for t in TOKS if t.k == "name" and t.v == k) for k in ("innerHTML", "outerHTML", "insertAdjacentHTML", "createPolicy", "createHTML")}
T.chk(nm_cnt["innerHTML"] == 1 and nm_cnt["outerHTML"] == 0 and nm_cnt["insertAdjacentHTML"] == 0 and nm_cnt["createPolicy"] == 1,
      "tjdom.js 토큰 셈: innerHTML 1 · outerHTML·insertAdjacentHTML 0 · createPolicy 1", nm_cnt)
print("허용 표 크기: 요소 %d(HTML %d · SVG %d) · 속성 %d · style %d · 호환 요소 %d · 호환 속성 %d · 호환 style %d" % (
    len(EL), len(TB["EL_HTML"]), len(TB["EL_SVG"]), len(TB["AT"]), len(TB["ST"]), len(TB["CP_EL_HTML"]) + len(TB["CP_EL_SVG"]), len(TB["CP_AT"]),
    len(TB["CP_ST"])))
T.finish()

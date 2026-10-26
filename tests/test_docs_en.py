#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import collections  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

chk = T.chk
PUB = os.path.dirname(T.HERE)
DOCS = os.path.join(PUB, "docs")
PAIRS = (("INSTALL.md", "INSTALL_EN.md"), ("SECURITY_DATA.md", "SECURITY_DATA_EN.md"))
EN_INDEX = "README_EN.md"
MAP_HEAD = "Anchor map (Korean → English):"
_HEAD = re.compile(r"^(#{1,6}) +(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")
_CODE = re.compile(r"`([^`\n]+)`")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")
_COMMENT = re.compile(r"(?:^\s*|\s+)#(?:\s.*)?$")
_URL = re.compile(r"https?://[^\s)<>|`\]]+")
PLACEHOLDERS = (("<이 저장소 주소>", "<this repository URL>"), ("사용자@서버", "user@server"), ("https://도메인", "https://<domain>"),
                ("<체인>", "<chain>"), ("<유닛>", "<unit>"), ("<시각>", "<time>"), ("/내/디스크/경로", "/my/disk/path"),
                ("<이 폴더>", "<this folder>"))


def ko2en(code: str) -> str:
    for k, e in PLACEHOLDERS:
        code = code.replace(k, e)
    return code


def slug(title: str) -> str:
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", title)
    t = re.sub(r"<[^>]*>", "", t)
    return re.sub(r"[^\w\- ]", "", t.strip().lower()).replace(" ", "-")


def shape(text: str) -> dict:
    out = {"heads": [], "tables": 0, "items": 0, "fences": [], "codes": [], "links": [], "urls": [], "map": None}
    seen = collections.Counter()
    fence = None
    for ln in text.split("\n"):
        m = _FENCE.match(ln)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            else:
                out["fences"][-1].append(_COMMENT.sub("", ln).rstrip())
            continue
        if m:
            fence = m.group(1)
            out["fences"].append([])
            continue
        s = ln.strip()
        if s.startswith(MAP_HEAD):
            out["map"] = _LINK.findall(s)
            continue
        if s.startswith("←"):
            continue
        h = _HEAD.match(ln)
        if h:
            a = slug(h.group(2))
            out["heads"].append((len(h.group(1)), a + ("-%d" % seen[a] if seen[a] else "")))
            seen[a] += 1
        out["tables"] += s.startswith("|")
        out["items"] += bool(_ITEM.match(ln))
        out["codes"] += _CODE.findall(ln)
        out["links"] += _LINK.findall(ln)
        out["urls"] += _URL.findall(_CODE.sub("", ln))
    return out


def compare(ko_name: str, ko: str, en: str) -> dict:
    a, b = shape(ko), shape(en)
    bad = collections.defaultdict(list)
    if [lv for lv, _ in a["heads"]] != [lv for lv, _ in b["heads"]]:
        bad["E1"].append("절 머리 단계·수 다름 %s ↔ %s" % ([x for x in a["heads"]], [x for x in b["heads"]]))
    pairs = list(zip((b["map"] or [])[0::2], (b["map"] or [])[1::2]))
    ko_anc = [t.split("#", 1)[1] if t.startswith(ko_name + "#") else "?" + t for t, _ in pairs]
    en_anc = [t[1:] if t.startswith("#") else "?" + t for _, t in pairs]
    if b["map"] is None or len(b["map"]) % 2:
        bad["E1"].append("앵커 대응표 줄 없음·짝 안 맞음")
    if ko_anc != [x for _, x in a["heads"][1:]]:
        bad["E1"].append("대응표 원문 앵커 ≠ 원문 절 앵커 %s ↔ %s" % (ko_anc, [x for _, x in a["heads"][1:]]))
    if en_anc != [x for _, x in b["heads"][1:]]:
        bad["E1"].append("대응표 영어 앵커 ≠ 영어판 절 앵커 %s ↔ %s" % (en_anc, [x for _, x in b["heads"][1:]]))
    for k in ("tables", "items"):
        if a[k] != b[k]:
            bad["E2-" + k].append("수 다름 %d ↔ %d" % (a[k], b[k]))
    fa = [[ko2en(x) for x in blk] for blk in a["fences"]]
    if fa != b["fences"]:
        lines = [(x, y) for p, q in zip(fa, b["fences"]) for x, y in zip(p, q) if x != y]
        bad["E2-fences"].append("코드 블록 다름 — 줄 %s · 블록별 줄 수 %s ↔ %s" % (lines[:4], [len(p) for p in fa], [len(q) for q in b["fences"]]))
    ca, cb = collections.Counter(ko2en(c) for c in a["codes"]), collections.Counter(b["codes"])
    if ca != cb:
        bad["E2-codes"].append("인라인 코드 다름 원문만 %s · 영어판만 %s" % (sorted(ca - cb)[:6], sorted(cb - ca)[:6]))
    left = sorted({c for c in list(ca) + [x for blk in fa for x in blk] if _HANGUL.search(c)})
    if left:
        bad["E2-codes"].append("코드에 PLACEHOLDERS 표 밖 한글 %s" % left[:4])
    back = {"#" + e: "#" + k for k, e in zip(ko_anc, en_anc)}
    en_links = collections.Counter(back.get(t, t) for t in b["links"])
    ko_links = collections.Counter(a["links"])
    if en_links != ko_links:
        bad["E3"].append("링크 대상 다름 원문만 %s · 영어판만 %s" % (sorted(ko_links - en_links)[:6], sorted(en_links - ko_links)[:6]))
    ua, ub = collections.Counter(a["urls"]), collections.Counter(b["urls"])
    if ua != ub:
        bad["E3"].append("주소 다름 원문만 %s · 영어판만 %s" % (sorted(ua - ub)[:4], sorted(ub - ua)[:4]))
    return dict(bad)


def anchors(text: str) -> set:
    return {x for _, x in shape(text)["heads"]}


def broken(rel: str, text: str) -> list:
    bad = []
    for tg in _LINK.findall(text):
        if re.match(r"(?i)(?:https?|mailto):", tg):
            continue
        path, _, anc = tg.partition("#")
        dst = os.path.normpath(os.path.join(DOCS, path)) if path else os.path.join(DOCS, rel)
        if not os.path.isfile(dst):
            bad.append(rel + " 파일 없음 " + tg)
            continue
        if anc and dst.endswith(".md"):
            with open(dst, encoding="utf-8") as f:
                heads = anchors(f.read())
            if {anc} - heads:
                bad.append(rel + " 앵커 없음 " + tg)
    return bad


def read(name: str) -> str:
    with open(os.path.join(DOCS, name), encoding="utf-8") as f:
        return f.read()


for ko_n, en_n in PAIRS:
    ko_t, en_t = read(ko_n), read(en_n)
    diff = compare(ko_n, ko_t, en_t)
    chk(not diff, "E1~E3 %s 꼴 = 원문 %s 꼴(원문을 고쳤으면 영어판도 고칠 것)" % (en_n, ko_n), diff)
    sh = shape(en_t)
    chk(len(sh["heads"]) >= 2 and sh["map"] is not None, "E1 %s 절 머리·앵커 대응표 줄 있음" % en_n, sh["heads"])
    chk(not broken(en_n, en_t), "E3 %s 상대 링크·앵커 깨짐 0" % en_n, broken(en_n, en_t))

idx = read(EN_INDEX)
tg4 = {t.partition("#")[0] for t in shape(idx)["links"]}
chk({en for _, en in PAIRS} <= tg4, "E4 %s 가 영어판 둘을 링크" % EN_INDEX, sorted({en for _, en in PAIRS} - tg4))
chk(not broken(EN_INDEX, idx), "E4 %s 상대 링크·앵커 깨짐 0" % EN_INDEX, broken(EN_INDEX, idx))

ko_s, en_s = read(PAIRS[0][0]), read(PAIRS[0][1])
d1 = compare(PAIRS[0][0], ko_s + "\n### 8) 새 절\n\n새 글\n", en_s)
chk(bool(d1.get("E1")), "S 원문에 절 하나 더함 = E1 차이", d1)
d2 = compare(PAIRS[0][0], ko_s, en_s.replace("`pm2 logs tj-core`", "`pm2 logs tj-core2`", 1))
chk(bool(d2.get("E2-codes")) and not d2.get("E2-items"), "S 영어판 명령 하나 바꿈 = E2 차이", d2)
d5 = compare(PAIRS[0][0], ko_s.replace("unit_runner.py tron ", "unit_runner.py tron --x ", 1), en_s)
chk(bool(d5.get("E2-fences")), "S 원문 코드 블록 명령 하나 바꿈 = E2 차이", d5)
d6 = compare(PAIRS[0][0], ko_s.replace("runner_<유닛>.json", "runner_<유닛>.txt", 1), en_s)
chk(bool(d6.get("E2-codes")), "S 원문 한글 자리표시 든 경로 바꿈 = E2 차이", d6)
d7 = compare(PAIRS[0][0], ko_s.replace("사용자@서버", "사용자@새서버", 1), en_s)
chk(bool(d7.get("E2-codes")), "S 코드에 표 밖 한글 = E2 차이", d7)
d8 = compare(PAIRS[0][0], ko_s.replace("https://dashboard.helius.dev ", "https://dashboard.helius.dev/keys ", 1), en_s)
chk(bool(d8.get("E3")), "S 원문 맨 주소(링크 문법 없음) 바꿈 = E3 차이", d8)
d9 = compare(PAIRS[0][0], ko_s.replace("```bash\npm2 start", "```bash\n# 전체 시작\npm2 start", 1),
             en_s.replace("```bash\npm2 start", "```bash\n# start everything\npm2 start", 1))
chk(not d9, "S 코드 블록에 줄 전체 셸 주석을 양쪽에 번역해 더함 = 차이 없음", d9)
d3 = compare(PAIRS[0][0], ko_s, en_s.replace("\n  - Logs: ", "\n  Logs: ", 1))
chk(bool(d3.get("E2-items")) and not d3.get("E2-codes"), "S 영어판 목록 항목 하나 뺌 = E2 차이", d3)
d4 = compare(PAIRS[1][0], read(PAIRS[1][0]) + "\n- [새 링크](OPERATIONS.md#구조)\n", read(PAIRS[1][1]))
chk(bool(d4.get("E3")), "S 원문에 링크 하나 더함 = E3 차이", d4)
chk(broken("x.md", "[a](NO_SUCH.md) [b](INSTALL.md#없는-앵커) [c](https://h.invalid/x)") == ["x.md 파일 없음 NO_SUCH.md", "x.md 앵커 없음 INSTALL.md#없는-앵커"],
    "S 링크 검사 = 없는 파일·없는 앵커만 잡음(바깥 주소 뺌)")

T.finish()

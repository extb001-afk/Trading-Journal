#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "readme_split.py")):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/readme_split.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import readme_split as S  # noqa: E402

DOC = ("# 제목\n머리 글\n\n## 처음 시작하면\n시작 글\n```\n## 코드 안 머리\n```\n## 설치 자세히\n설치 글\n"
       "`config.json` 에서 알아 두면 좋은 키:\n\n| 키 | 기본 |\n|---|---|\n| a | 1 |\n\n뒤 글\n## 처음 보는 절\n모름\n"
       "## 보안 · 데이터\n보안 글 한국어\n## English\nEnglish text\n")

secs = S.sections(DOC)
chk([s["title"] for s in secs] == ["_head", "처음 시작하면", "설치 자세히", "처음 보는 절", "보안 · 데이터", "English"],
    "S1 절 머리(코드 블록 안 '## ' 은 절 아님)", [s["title"] for s in secs])
chk(sum(s["bytes"] for s in secs) == len(DOC.encode("utf-8")), "S1 절 바이트 합 = 원문 바이트(한글 포함)")
chk(secs[2]["start"] == 9 and secs[0]["lines"] == 3, "S1 줄 번호 · 줄 수", [(s["start"], s["lines"]) for s in secs])

p = S.section_map(DOC)
chk(p["unassigned"] == ["처음 보는 절"], "S2 표에 없는 절 = 미배정", p["unassigned"])
dests = {r["title"]: r["dest"] for r in p["sections"]}
chk(dests["처음 시작하면"] == S.KEEP and dests["설치 자세히"] == "docs/INSTALL.md" and dests["English"] == "docs/README_EN.md",
    "S2 닫힌 표 앞부분 일치", dests)
cv = p["carved"]
chk(len(cv) == 1 and cv[0]["dest"] == "docs/CONFIG.md" and cv[0]["lines"] == 5 and cv[0]["start"] == 11,
    "S2 덩어리 = 표식 줄 + 빈 줄 + 표 줄(뒤 글은 남음)", cv)
unb = next(s["bytes"] for s in secs if s["title"] == "처음 보는 절")
chk(sum(p["per_file"].values()) + unb == p["total_bytes"], "S2 새 파일별 바이트 합 + 미배정 = 원문 바이트", p["per_file"])

e = p["readme_est"]
chk(e["kept_sections"] == p["per_file"][S.KEEP] and e["stubs_est"] == sum(S.STUB_BYTES.values())
    and e["total_est"] == e["kept_sections"] + e["stubs_est"] + S.MAP_BYTES, "S3 새 README 예상 = 남는 절 + 한 단락 추정 + 문서 지도 추정", e)

RM = "줄 하나 알림 문구\n줄 둘째 `KEY_A` | 필수\n셋째 줄 끝\n넷째 시작\n"
SRC = '''"""독스트링 알림 문구"""
import re
import _harness as T
rd = open(T.README).read()
other = open("x.txt").read()
T.chk("알림 문구" in rd, "결과 줄 알림 문구")
T.chk(all(x in rd for x in ("셋째 줄", "넷째 시작")), "합")
T.chk("없는 글귀" not in rd, "부정")
T.chk("줄 하나" in other, "다른 파일")
T.chk(re.search(r"셋째 줄 끝\\n넷째", rd) is not None, "여러 줄")
T.chk(re.search(r"`KEY_A` \\| 필수", rd) is not None, "표")
for fn in ("a.txt", "README.md"):
    tx = open(fn).read()
    T.chk("줄 둘째" in tx, "반복")
'''
nd = S.test_needles(SRC, RM)
chk(nd["strings"] == sorted(["알림 문구", "셋째 줄", "넷째 시작", "줄 둘째"]), "S4 찾는 글 = README 글 이름을 따라간 비교만(라벨·독스트링·다른 파일 글 뺌)",
    nd["strings"])
chk(nd["neg"] == 1, "S4 없어야 할 글 수", nd["neg"])
chk([h for _p, h in nd["regex"]] == [[3], [2]], "S4 정규식 = 맞는 README 줄 번호(여러 줄 패턴 포함)", nd["regex"])
chk(S.where(DOC, "설치 글", secs) == ["설치 자세히"], "S4 글 → 절")

import readme_move as M  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

chk(M.slug("AI 기능 켜기 — `claude` CLI 로그인") == "ai-기능-켜기--claude-cli-로그인" and M.slug("금액 가리기(숨김 모드)") == "금액-가리기숨김-모드"
    and M.slug("3) 키 준비 — .env 와 config.json") == "3-키-준비--env-와-configjson", "S5 앵커 = 깃허브 규칙(글자·숫자·하이픈·공백만 · 공백 → -)")
chk(M.anchors("# 가\n## 가\n```\n## 나\n```\n### 다 #\n## [P2](../x.md) <b>굵게</b>\n") == {"가", "가-1", "다", "p2-굵게"},
    "S5 같은 머리 둘째 = -1 · 코드 블록 안 머리 아님 · 닫는 # 뺌 · 머리 안 링크·태그 = 보이는 글")
anc5 = {"README.md": {"업데이트"}, "docs/FEATURES.md": {"nft"}, "docs/INSTALL.md": {"설치"}}
chk(M.rewrite("#nft", "README.md", "docs/INSTALL.md", anc5) == "FEATURES.md#nft" and M.rewrite("#설치", "README.md", "docs/INSTALL.md", anc5) == "#설치"
    and M.rewrite("#업데이트", "README.md", "docs/INSTALL.md", anc5) == "../README.md#업데이트"
    and M.rewrite("docs/API_KEYS.md", "README.md", "docs/INSTALL.md", anc5) == "API_KEYS.md"
    and M.rewrite("CHANGELOG.md#v1", "README.md", "docs/INSTALL.md", anc5) == "../CHANGELOG.md#v1"
    and M.rewrite("https://x.example/a#b", "README.md", "docs/INSTALL.md", anc5) == "https://x.example/a#b"
    and M.rewrite("README.md#nft", "CHANGELOG.md", "CHANGELOG.md", anc5) == "docs/FEATURES.md#nft"
    and M.rewrite("README.md#업데이트", "CHANGELOG.md", "CHANGELOG.md", anc5) == "README.md#업데이트",
    "S5 링크 고침 = 옮긴 파일 기준 상대 경로 · 다른 문서로 간 앵커 · 남은 앵커 · 바깥 주소 그대로 · 다른 문서의 README 앵커")

chk(set(d for _p, d in S.SECTION_MAP) - {S.KEEP} == set(M.PARTS) == set(T.README_PARTS) and set(M.DOC_TITLES) == set(M.PARTS),
    "S5 새 문서 목록 = 지도 새 자리 = _harness.README_PARTS = 문서 제목 표")

RD6 = ("# 봇\n머리 [설치](#설치-자세히) · [백업](#백업--복구) · [둘 것](#알아-둘-것)\n\n## 처음 시작하면 이것부터\n시작 표\n\n---\n\n"
       "## 화면 미리보기\n<!--SHOT:a|사진-->\n\n## 설치 자세히\n설치 글 [API](docs/API_KEYS.md) · [백업 · 복구](#백업--복구)\n\n"
       "`config.json` 에서 알아 두면 좋은 키:\n\n| 키 | 기본 |\n|---|---|\n| `a.b` | 1 |\n\n설치 뒤 글\n\n"
       "## 지갑 주소 여러 개 한 번에\n지갑 글\n\n## 백업 · 복구\n백업 글\n\n## 업데이트\n업데이트 글\n\n"
       "## 보안 · 데이터\n\n- 첫 항목\n  이어지는 줄\n- 둘째 항목\n- 셋째 항목 보안만\n\n## 고급 설정\n고급 글\n\n## 알아 둘 것\n둘 것 글\n\n"
       "## English\n\nFirst para line one\nline two\n\nSecond para only in docs\n")
CL6 = "# 변경\n- [백업](README.md#백업--복구) · [업데이트](README.md#업데이트)\n- 그대로 줄\n"
W6 = tempfile.mkdtemp(prefix="tj_rs6_")


def put6(rel, txt):
    fp = os.path.join(W6, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(txt)


def get6(rel):
    with open(os.path.join(W6, rel), encoding="utf-8") as f:
        return f.read()


put6("public/README.md", RD6)
put6("public/CHANGELOG.md", CL6)
put6("public/docs/API_KEYS.md", "# 키\n")
put6("public/tests/_harness.py", "README_PARTS = " + repr(M.PARTS) + "\n")
OLD6 = {"CHANGELOG.md": CL6, "docs/API_KEYS.md": "# 키\n"}
res6 = M.apply(W6)
rd6 = get6("public/README.md")
chk(all(os.path.isfile(os.path.join(W6, "public", p)) for p in M.PARTS) and res6["links"] > 0, "S6 apply = 새 문서 7 · 고친 링크 > 0", res6)
chk("- 첫 항목\n  이어지는 줄\n- 둘째 항목\n\n→ [보안 · 데이터](docs/SECURITY_DATA.md#보안--데이터)" in rd6 and "셋째 항목 보안만" not in rd6
    and "First para line one\nline two\n\n→ [English](docs/README_EN.md#english)" in rd6 and "Second para" not in rd6,
    "S6 README 한 단락 = 앞 덩어리 n 개 옛 글 그대로 + 전문 링크 줄(목록 항목 2 · 문단 1)")
chk("[설치](docs/INSTALL.md#설치-자세히)" in rd6 and "[둘 것](#알아-둘-것)" in rd6 and "## 문서 지도" in rd6
    and "[docs/CONFIG.md](docs/CONFIG.md): [알아 두면 좋은 키](docs/CONFIG.md#알아-두면-좋은-키) · [고급 설정](docs/CONFIG.md#고급-설정)" in rd6,
    "S6 README 링크 = 옮긴 절은 docs 앵커 · 남은 절 그대로 · 문서 지도(덩어리 절 머리 포함)")
ins6, cfg6 = get6("public/docs/INSTALL.md"), get6("public/docs/CONFIG.md")
chk(ins6.startswith("# tj-bot 설치\n\n← [README.md](../README.md)\n") and "[API](API_KEYS.md) · [백업 · 복구](OPERATIONS.md#백업--복구)" in ins6
    and "→ [알아 두면 좋은 키](CONFIG.md#알아-두면-좋은-키)" in ins6 and "| `a.b` |" not in ins6 and "설치 뒤 글" in ins6,
    "S6 옮긴 문서 = 머리 · 상대 경로 · 다른 문서 앵커 · 덩어리 자리 = 링크 줄(뒤 글 남음)")
chk(cfg6.startswith("# tj-bot 설정\n\n← [README.md](../README.md)\n\n## 알아 두면 좋은 키\n\n`config.json` 에서 알아 두면 좋은 키:\n\n| 키 | 기본 |")
    and cfg6.index("## 알아 두면 좋은 키") < cfg6.index("## 고급 설정"), "S6 CONFIG = 덩어리(글 그대로 · 등록 머리 아래 · 옛 차례대로 앞) + 고급 설정 절")
chk(get6("public/CHANGELOG.md") == "# 변경\n- [백업](docs/OPERATIONS.md#백업--복구) · [업데이트](README.md#업데이트)\n- 그대로 줄\n",
    "S6 CHANGELOG = 옮긴 절 앵커만 새 자리로(남은 절 · 다른 줄 그대로)")
tbl6 = json.loads(get6(M.LINKS_REL))["links"]
chk(tbl6.get("CHANGELOG.md") == {"README.md#백업--복구": "docs/OPERATIONS.md#백업--복구"} and tbl6["docs/INSTALL.md"].get("docs/API_KEYS.md") == "API_KEYS.md",
    "S6 링크 고침 표 = 파일별 옛 대상 → 새 대상", tbl6.get("CHANGELOG.md"))
try:
    M.apply(W6)
    rej6 = False
except SystemExit:
    rej6 = True
chk(rej6, "S6 두 번째 apply = 거부(이미 나뉨 · 덮어쓰지 않음)")
v6 = M.verify_texts(W6, RD6, OLD6)
chk(v6["ok"] and v6["same_as_fresh_apply"], "S6 verify 통과(나눈 그대로)", v6["problems"])


def broken6(rel, fn, want, **kw):
    keep = get6(rel)
    put6(rel, fn(keep))
    try:
        v = M.verify_texts(W6, RD6, OLD6, kw.get("target"))
    finally:
        put6(rel, keep)
    return any(p.startswith(want) for p in v["problems"]), v["problems"]


cases6 = [
    ("① 줄 빠짐", "public/docs/FEATURES.md", lambda t: t.replace("지갑 글\n", ""), "①"),
    ("⑧ 줄 차례 바뀜", "public/docs/INSTALL.md", lambda t: t.replace("설치 뒤 글\n", "").replace("## 설치 자세히\n", "## 설치 자세히\n설치 뒤 글\n"), "⑧"),
    ("② 새 글", "public/docs/INSTALL.md", lambda t: t + "\n새로 쓴 설명 글\n", "②"),
    ("① 보이는 링크 글 바뀜", "public/docs/INSTALL.md", lambda t: t.replace("[API](API_KEYS.md)", "[키 문서](API_KEYS.md)"), "①"),
    ("③ 앵커 깨짐", "public/README.md", lambda t: t + "\n[설치 자세히](docs/INSTALL.md#없는-앵커)\n", "③"),
    ("③ 파일 없음", "public/docs/OPERATIONS.md", lambda t: t + "\n[백업 · 복구](NOPE.md)\n", "③"),
    ("④ 다른 문서 글", "public/CHANGELOG.md", lambda t: t.replace("그대로 줄", "바뀐 줄"), "④"),
    ("④ 다른 문서 링크 앞 NBSP", "public/CHANGELOG.md", lambda t: t.replace("(docs/OPERATIONS.md#", "(\u00a0docs/OPERATIONS.md#"), "④"),
    ("④ 다른 문서 링크 앞 공백", "public/CHANGELOG.md", lambda t: t.replace("(README.md#업데이트)", "( README.md#업데이트)"), "④"),
    ("⑤ 고침 표", M.LINKS_REL, lambda t: t.replace("API_KEYS.md\"", "API_KEYS.md#x\"", 1), "⑤"),
    ("⑦ _harness 목록", "public/tests/_harness.py", lambda t: t.replace(repr("docs/SCREENS.md") + ", ", ""), "⑦"),
    ("② 링크 글 = 등록 밖", "public/README.md", lambda t: t + "\n- [아무 말](docs/INSTALL.md)\n", "②"),
    ("② 링크만 줄 = 바깥 주소", "public/README.md", lambda t: t + "\n- [설치 자세히](https://x.example/a)\n", "②"),
    ("② 옛 글 사본 = 한 단락 밖", "public/docs/INSTALL.md", lambda t: t + "\n지갑 글\n", "②"),
    ("⑨ 블록 밖 손 편집(등록 꼴 줄 더함)", "public/README.md", lambda t: t + "\n- [설치 자세히](docs/INSTALL.md#설치-자세히)\n", "⑨"),
    ("⑨ 빈 줄 없앰(문단 합침)", "public/docs/INSTALL.md", lambda t: t.replace("(OPERATIONS.md#백업--복구)\n\n", "(OPERATIONS.md#백업--복구)\n", 1), "⑨"),
    ("gen:cfg = 만드는 도구 없음", "public/docs/CONFIG.md", lambda t: t + "\n<!-- gen:cfg -->\n| 생성 |\n<!-- /gen:cfg -->\n", "docs/CONFIG.md"),
    ("new:p2 = OPERATIONS 밖", "public/docs/INSTALL.md", lambda t: t + "\n<!-- new:p2 -->\n새 절\n<!-- /new:p2 -->\n", "docs/INSTALL.md"),
    ("블록 닫는 표식 없음", "public/docs/OPERATIONS.md", lambda t: t + "\n<!-- new:p2 -->\n새 절\n", "docs/OPERATIONS.md"),
    ("블록 짝 다름", "public/docs/OPERATIONS.md", lambda t: t + "\n<!-- new:p2 -->\n새 절\n<!-- /gen:p2 -->\n", "docs/OPERATIONS.md"),
    ("블록 종류 다름", "public/docs/OPERATIONS.md", lambda t: t + "\n<!-- gen:p2 -->\n새 절\n<!-- /gen:p2 -->\n", "docs/OPERATIONS.md"),
    ("③ 제목 붙은 링크 깨짐(블록 안)", "public/docs/OPERATIONS.md",
     lambda t: t + '\n<!-- new:p2 -->\n[백업 · 복구](NOPE.md "제목")\n<!-- /new:p2 -->\n', "③"),
    ("③ 인라인 코드 ```x``` 는 울타리 아님", "public/docs/OPERATIONS.md",
     lambda t: t + "\n<!-- new:p2 -->\n```x```\n[백업 · 복구](NOPE.md)\n```x```\n<!-- /new:p2 -->\n", "③"),
    ("③ 참조 링크 정의 깨짐", "public/docs/OPERATIONS.md", lambda t: t + "\n<!-- new:p2 -->\n[r]: NOPE.md\n<!-- /new:p2 -->\n", "③"),
    ("③ HTML 링크 깨짐", "public/docs/OPERATIONS.md", lambda t: t + '\n<!-- new:p2 -->\n<a href="NOPE.md">x</a>\n<!-- /new:p2 -->\n', "③"),
    ("③ 못 읽는 링크 꼴", "public/docs/OPERATIONS.md", lambda t: t + "\n<!-- new:p2 -->\n[x](NOPE.md foo)\n<!-- /new:p2 -->\n", "③"),
    ("③ 따옴표 없는 HTML 링크", "public/docs/OPERATIONS.md", lambda t: t + "\n<!-- new:p2 -->\n<a href=NOPE.md>x</a>\n<!-- /new:p2 -->\n", "③"),
    ("③ 대상이 다음 줄인 참조 정의", "public/docs/OPERATIONS.md",
     lambda t: t + "\n<!-- new:p2 -->\n[백업][r]\n\n[r]:\n  NOPE.md\n<!-- /new:p2 -->\n", "③"),
    ("③ HTML 주석 안 가짜 절", "public/docs/OPERATIONS.md",
     lambda t: t + "\n<!-- new:p2 -->\n<!--\n## phantom\n-->\n[백업 · 복구](#phantom)\n<!-- /new:p2 -->\n", "③"),
    ("③ 절 머리 안 링크 = 보이는 글로 앵커", "public/docs/OPERATIONS.md",
     lambda t: t + "\n<!-- new:p2 -->\n## [P2](../README.md)\n[백업 · 복구](#p2readmemd)\n<!-- /new:p2 -->\n", "③"),
    ("③ 절대 경로", "public/docs/INSTALL.md", lambda t: t + "\n- [README.md](/tmp/x/public/README.md)\n", "③"),
    ("③ HTML 블록 안 가짜 절", "public/docs/OPERATIONS.md", lambda t: t + "\n<pre>\n## phantom\n</pre>\n\n[백업 · 복구](#phantom)\n", "③"),
    ("③ 강조 든 절 머리", "public/docs/OPERATIONS.md", lambda t: t + "\n## _P2_\n[백업 · 복구](#_p2_)\n", "③"),
    ("③ 문자 참조 든 절 머리", "public/docs/OPERATIONS.md", lambda t: t + "\n## P&#50;\n[백업 · 복구](#p50)\n", "③"),
    ("③ 공개판 뿌리 밖 상대 경로", "public/docs/OPERATIONS.md", lambda t: t + "\n[백업 · 복구](../../..)\n", "③"),
    ("③ 허용 안 된 스킴", "public/docs/INSTALL.md", lambda t: t + "\n- [README.md](file:///tmp/README.md)\n", "③"),
]
for nm6, rel6, fn6, want6 in cases6:
    hit6, pr6 = broken6(rel6, fn6, want6)
    chk(hit6, f"S6 일부러 망가뜨림 — {nm6} = verify 실패", pr6)
put6("public/docs/EXTRA.md", "설명만 있는 새 문서\n")
pr6 = M.verify_texts(W6, RD6, OLD6)["problems"]
os.remove(os.path.join(W6, "public", "docs", "EXTRA.md"))
chk(any(x.startswith("④") for x in pr6), "S6 다른 공개 문서 새로 생김 = verify 실패", pr6)
os.rename(os.path.join(W6, "public", "docs", "API_KEYS.md"), os.path.join(W6, "ak.md"))
pr6 = M.verify_texts(W6, RD6, OLD6)["problems"]
os.rename(os.path.join(W6, "ak.md"), os.path.join(W6, "public", "docs", "API_KEYS.md"))
chk(any(x.startswith("④") for x in pr6), "S6 다른 공개 문서 지워짐 = verify 실패", pr6)
hit6, pr6 = broken6("public/README.md", lambda t: t, "⑥", target=100)
chk(hit6, "S6 README 크기 > 목표 = verify 실패", pr6)
ok6 = []
for rel6, fn6 in (("public/docs/OPERATIONS.md", lambda t: t + "\n<!-- new:p2 -->\n## 백업 암호화\n새 안내 글\n<!-- /new:p2 -->\n"),
                  ("public/README.md", lambda t: t + "\n- [설치 자세히](docs/INSTALL.md#설치-자세히) · [README.md](README.md)\n")):
    keep6 = get6(rel6)
    put6(rel6, fn6(keep6))
    ok6.append(M.verify_texts(W6, RD6, OLD6)["problems"])
    put6(rel6, keep6)
put6("tools/refactor/cfg_doc.py", "# 합성 자리\n")
keep6 = get6("public/docs/CONFIG.md")
put6("public/docs/CONFIG.md", keep6 + "\n<!-- gen:cfg -->\n| 생성 표 |\n<!-- /gen:cfg -->\n")
ok6.append(M.verify_texts(W6, RD6, OLD6)["problems"])
put6("public/docs/CONFIG.md", keep6)
chk(M.GEN_BLOCKS == {"cfg": ("gen", "docs/CONFIG.md", "tools/refactor/cfg_doc.py")}
    and any("등록 안 된 블록" in x for x in ok6[0]) and ok6[2] == []
    and [x[:1] for x in ok6[1]] == ["⑨"],
    "S6 단순안 = 등록 밖 블록 표식(new:p2)은 실패 · 등록된 gen:cfg(만드는 도구 있음)는 통과(10-2 합침) · 링크만 줄은 ①②③ 통과하나 블록 밖 손 편집 = ⑨", ok6)

B7 = os.path.join(W6, "public")
full7 = T.doc_text("README.md", B7)
want7 = "\n".join([rd6] + [get6("public/" + p7) for p7 in M.PARTS])
one7 = T.doc_text("docs/API_KEYS.md", B7)
os.rename(os.path.join(B7, "docs", "SCREENS.md"), os.path.join(W6, "s.md"))
try:
    T.doc_text("README.md", B7)
    part7 = False
except FileNotFoundError:
    part7 = True
os.rename(os.path.join(W6, "s.md"), os.path.join(B7, "docs", "SCREENS.md"))
for p7 in M.PARTS:
    os.rename(os.path.join(B7, p7), os.path.join(W6, p7.replace("/", "_")))
none7 = T.doc_text("README.md", B7)
chk(full7 == want7 and one7 == "# 키\n",
    "S7 doc_text('README.md') = README + 나눈 문서 · 다른 이름 = 그 파일만")
chk(part7 and none7 == rd6, "S7 나눈 문서 일부만 있음 = FileNotFoundError · 전부 없음 = README 만(나누기 전)")
shutil.rmtree(W6, ignore_errors=True)
import _arch_hyg as H  # noqa: E402

a7 = H.analyze_test('import _harness as T\nrd = T.doc_text("README.md")\nT.chk("x" in rd, "a")\nT.chk("y" not in T.doc_text(), "b")\n', "t.py")
chk(a7["str_checks"] == 2 and a7["str_neg"] == 1 and a7["reads_readme"], "S7 위생 분석기 = doc_text 읽기를 원문 검사로 셈 · README 읽기 목록",
    {k: a7[k] for k in ("str_checks", "str_neg", "reads_readme")})

pl = S.plan(T.ROOT)
chk(pl["unassigned"] == [], "P 지금 README 미배정 절 0", pl["unassigned"])
rt = pl["reader_tests"]
chk(sorted(rt["found"]) == sorted(rt["declared"]), "P README 를 읽는 시험 목록 = 다시 찾은 목록(새로 읽기 시작한 시험이면 목록에 더하라)",
    sorted(set(rt["found"]) ^ set(rt["declared"])))
chk(sum(r["bytes"] for r in pl["sections"]) == pl["total_bytes"], "P 절 바이트 합 = README 바이트")
with open(T.README, encoding="utf-8") as f8:
    txt8 = {"README.md": f8.read()}
txt8.update({p8: T.doc_text(p8) for p8 in T.README_PARTS})
chk(len(txt8["README.md"].encode("utf-8")) <= S.TARGET_BYTES, "P 나눈 README ≤ 목표 바이트", len(txt8["README.md"].encode("utf-8")))
linked8 = {tg.split("#")[0] for _t8, tg in M.links(txt8["README.md"])}
chk(set(T.README_PARTS) <= linked8, "P README 가 나눈 문서를 전부 링크(문서 지도)", sorted(set(T.README_PARTS) - linked8))
chk(M.check_links(T.ROOT, txt8) == [], "P README·나눈 문서 링크 깨짐 0(파일 · 절 앵커)", M.check_links(T.ROOT, txt8)[:5])

T.finish()

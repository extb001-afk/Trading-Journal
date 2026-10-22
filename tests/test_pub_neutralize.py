#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

chk = T.chk
PKG = os.path.join(T.ROOT, "tools", "package")
REF = os.path.join(T.ROOT, "tools", "refactor")
if not (os.path.isfile(os.path.join(PKG, "pub_neutralize.py")) and os.path.isfile(os.path.join(REF, "neutral_proof.py"))):
    public_layout = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(public_layout, "공개판 배치 — 비공개 도구(pub_neutralize · neutral_proof) 없음 · 건너뜀" if public_layout
        else "저장소 배치인데 tools/package/pub_neutralize.py 또는 tools/refactor/neutral_proof.py 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path[:0] = [PKG, REF]
import pub_neutralize as N  # noqa: E402
import neutral_proof as P  # noqa: E402

S = N.Rules(simple=True)


def nz(text, fixture=False):
    return N.neutralize(text, S, fixture)


cases = [
    ("값을 먼저 고친다(코덱스 ab12 #3: 순서가 바뀌면 틀림)", "값을 먼저 고친다(순서가 바뀌면 틀림)"),
    ("코덱스 78 #2: 채움 대기는 지운 뒤에", "채움 대기는 지운 뒤에"),
    ("새 칸 (2026-09-03) 추가", "새 칸 추가"),
    ("느린 노드 끊기(07-14 실측)", "느린 노드 끊기(실측)"),
    ("오너 결정 07-14: 기본은 켬", "기본은 켬"),
    ("창 계산(코덱스 67 H3 — 생략 = 기본 창)", "창 계산(생략 = 기본 창)"),
    ("규칙 설명 (DESIGN_X.md §3 참고)", "규칙 설명 (참고)"),
    ("자세한 기록 dev/20260903/notes.md 에", "자세한 기록 에"),
]
for src, want in cases:
    chk(nz(src) == want, "N1 단순안: %s" % src[:24], [nz(src), want])
keep = ["시각 꼴 '2026-09-03T09:00:00' 을 읽는다", "검색 예 after:2026-09-03 = 그 뒤", "무료 키는 2026-09-03 부터 한도",
        "첫 봉 = 2026-09-03(UTC) 기준", "오류 코드(-32005)는 거부", "다른 코드가 .value 를 넣어도", "옵션(--git-dir) 을 준다",
        "tool.py [--since 2026-09-03] 로 부름", "--days 2026-09-03,2026-09-04 = 그날들", "날짜 표기 2026-09-03 · 02-03 · 2/3 · 2월 3일 = 범위"]
keep += ["시각 하한 1420070400000 = 2015-01-01 이다", "먼 미래 9999-12-31 까지", "좁은 폭 1180 실측 = 62px",
         "상장 09-17 09:00 UTC 부터 1분봉", "눈금(08-30 · 09-07 · … · 오늘)", "10-01 에 6월분 소멸"]
for src in keep:
    out = nz("(코덱스 x1) " + src)
    chk(out == src, "N1 기술 날짜·다듬기 보호: %s" % src[:20], [out, src])
chk(nz("합성 2026-09-03 매수 · 첫 기록이 03-10 으로", fixture=True) == "합성 2026-09-03 매수 · 첫 기록이 03-10 으로", "N1 시험 파일 날짜 = 합성 값 보존")
chk(nz("값 확인 (07-14)", fixture=True) == "값 확인", "N1 시험 파일도 날짜만 든 괄호는 지움")
chk(nz("합성 하루(09-10) 의 기록", fixture=True) == "합성 하루(09-10) 의 기록" and nz("순서 맞춤(07-14)") == "순서 맞춤",
    "N1 낱말에 붙은 괄호 날짜 = 시험에서만 합성 값으로 보존")
chk(nz("합성 2026-09-03 매수") == "합성 매수", "N1 시험 밖 연-월-일 = 지움")
ln = N._Line(S, False, False)
chk(ln("──────── 구획 ────", "주석") == "──────── 구획 ────" and ln("값 , 그대로", "주석") == "값 , 그대로" and not ln.changes,
    "N1 규칙 안 걸린 줄 · 다듬기만 바뀔 줄 = 원래 글 그대로", ln.changes)
chk(ln("─── 07-14 ───", "주석") == "─── 07-14 ───" or ln.changes[-1][0].endswith("삭제"), "N1 꾸밈 + 날짜 줄은 지우거나 그대로(글자 남음 판정)")

rp = os.path.join(T.TMP, "rules.json")
with open(rp, "w", encoding="utf-8") as f:
    json.dump({"symbols": ["FOOX", "BARQ"], "aliases": [r"acct\d+"], "subs": {"mid": [[r"(?i)example\.org", "포털"]]}}, f)
R = N.load_rules(rp)
out = N.neutralize("FOOX 를 acct7 에서 팔고 example.org 로 보냄(07-14)", R)
chk(out == "토큰 를 지갑 에서 팔고 포털 로 보냄", "N2 full: 종목·별명·subs·날짜", out)
chk(N.neutralize("$5,000 남음", R) == "$N 남음" and N.neutralize("$10 기본", R) == "$10 기본", "N2 full: 금액 가림 · 허용 금액 보존")
for bad, why in (({"subs": {"zzz": []}}, "모르는 자리"), ([1], "객체 아님")):
    chk(isinstance(T.safe(N.Rules, bad), dict) and "_exc" in T.safe(N.Rules, bad), "N2 %s = 오류" % why)
chk("_exc" in T.safe(N.load_rules, os.path.join(T.TMP, "none.json")), "N2 규칙 파일 없음 = 오류")

PY = '''"""모듈 설명(코덱스 zz9: 근거) — 2026-09-03 바꿈."""
import os  # noqa: E402 — 순서 맞춤(07-14)


def f(x):  # type: (int) -> int
    """값을 돌려줌(audit 2026-09-03 [2], 순서)."""
    s = "문자열 안 07-14 · 코덱스 그대로"  # 끝 주석 (코덱스 q1)
    try:
        return x + len(s) + len(os.sep)
    except Exception:  # noqa: BLE001 [fallback] 기본값으로(07-14)
        return 0
'''
ln = N._Line(S, False, False)
new = N.scrub_py(PY, ln)
chk('"문자열 안 07-14 · 코덱스 그대로"' in new and "# type: (int) -> int" in new, "N3 문자열 값 · type: 주석 그대로", new)
chk("# noqa: E402 — 순서 맞춤" in new and "# noqa: BLE001 [fallback] 기본값으로" in new and "07-14" not in new.replace("문자열 안 07-14", ""),
    "N3 noqa 표식 보존 · 뒤 설명만 중립화", new)
chk('"""모듈 설명(근거) — 바꿈."""' in new and '"""값을 돌려줌(순서)."""' in new and "# 끝 주석" in new, "N3 독스트링·끝 주석 중립화", new)
chk(P.py_check(PY, new) == [], "N3 py_check 통과(AST 같음 · 바뀐 줄 = 주석·독스트링 · noqa 차례열 같음)", P.py_check(PY, new))
chk(P.py_check(PY, new.replace("return 0", "return 1")) != [], "N3 코드 한 글자 바뀜 = py_check 실패")
chk(P.py_check(PY, new.replace("[fallback]", "[isolate]")) != [], "N3 noqa 표식 바뀜 = py_check 실패")
chk(P.py_check(PY, new.replace('"""값을 돌려줌(순서)."""\n', "")) != [], "N3 독스트링 개수 바뀜 = py_check 실패")

ln = N._Line(S, True, False)
chk(ln("핫픽스 k(07-14): 값 고정", "주석") == "핫픽스 k(07-14): 값 고정" and ln.changes[-1][0] == "보류", "N4 src 이력 글 남음 = 보류", ln.changes)
chk(ln("(코덱스 ab1 · 2026-09-03). 다음 줄 이어서", "주석") == "(코덱스 ab1 · 2026-09-03). 다음 줄 이어서"
    and ln.changes[-1][0] == "보류-모양", "N4 새 구두점 머리 = 보류-모양", ln.changes)

JS = ('const u = "http://x//y"; // 끝 주석(코덱스 w1)\nconst r = /a\\/\\/b/g; /* 블록(07-14)\n * 둘째 줄 */\nreturn /* 07-14\n */ 1;\n'
      'const t = `${a}//안 주석 아님`;\n')
ln = N._Line(S, False, False)
nj = N.scrub_js(JS, ln)
chk('"http://x//y"' in nj and "/a\\/\\/b/g" in nj and "`${a}//안 주석 아님`" in nj, "N5 문자열·정규식·템플릿 안 '//' 그대로", nj)
chk("// 끝 주석" in nj and "/* 블록\n * 둘째 줄 */" in nj, "N5 JS 주석 중립화", nj)
chk(P._js_layout(JS) == P._js_layout(nj), "N5 줄바꿈 든 블록 주석(return 뒤) 줄바꿈 유지 = 줄바꿈 자리 같음", nj)
chk(P._js_layout("return /* a\n */ 1") != P._js_layout("return /* a */ 1"), "N5 줄바꿈 자리 검사가 ASI 차이를 잡음")
HT = '<!-- 머리(07-14) -->\n<!--MARK-->\n<!--  안 바뀜  -->\n<p>본문 07-14</p>\n<style>/* 색(코덱스 c1) */ a{color:red}</style>\n<script>let a = 1; // 끝(07-14)\n</script>\n'
nh = N.scrub_html(HT, N._Line(S, False, False))
chk("<!--MARK-->\n<!--  안 바뀜  -->" in nh, "N5 안 바뀐 HTML 주석 = 바이트 그대로(서버 표식 <!--MARK--> 꼴)", nh)
chk(P.text_check("a.html", HT, nh.replace("<!--MARK-->", "<!-- MARK -->")) != [] and P.text_check("a.html", HT, nh.replace("<!--  안 바뀜  -->", "<!-- 안 바뀜 -->")) != [],
    "N5 HTML 증명이 표식 주석·공백만 바뀐 주석을 잡음")
chk("<!-- 머리 -->" in nh and "<p>본문 07-14</p>" in nh and "/* 색 */" in nh and "// 끝" in nh, "N5 HTML 주석·style·script 만 · 본문 글 그대로", nh)
chk(P.text_check("a.html", HT, nh) == [] and P.text_check("a.html", HT, nh.replace("본문", "몸")) != [], "N5 HTML 증명(통과 · 본문 바뀜 = 실패)")
CSS = 'a::after{content:"x"} /* 진짜(07-14) */\n'
nc = N.scrub_css(CSS, N._Line(S, False, False))
chk(P.text_check("a.css", CSS, nc) == [] and P.text_check("a.css", CSS, nc.replace("after", "before")) != [], "N5 CSS 증명", nc)
CS2 = 'a::after{content:"/* 안(07-14) */"}\n'
chk(P.text_check("a.css", CS2, N.scrub_css(CS2, N._Line(S, False, False))) != [], "N5 CSS 문자열 안 '/*' 를 고치면 증명이 실패로 잡음")
SH = '#!/usr/bin/env bash\n# 준비(코덱스 s1 · 07-14)\necho "a # 07-14"  # 끝(07-14)\nx=1  # 끝 둘(07-14)\ncat <<EOF\n# 07-14 히어독\nEOF\n'
ns = N.scrub_sh(SH, N._Line(S, False, False))
chk("# 준비\n" in ns and 'echo "a # 07-14"  # 끝(07-14)' in ns and "x=1  # 끝 둘\n" in ns and "# 07-14 히어독" in ns,
    "N5 셸: 줄 전체·따옴표 없는 줄 끝 주석만 · 히어독 몸통 그대로", ns)
bash_ok = os.path.isfile("/bin/bash") or os.path.isfile("/usr/bin/bash")
if bash_ok:
    chk(P.text_check("a.sh", SH, ns) == [] and P.text_check("a.sh", SH, ns.replace("x=1", "x=2")) != [], "N5 셸 증명(bash -n)")
JSCMP = os.path.join(PKG, "jscmp.js")
node = T.node_bin("acorn 토큰 대조")
if node and os.path.isfile(JSCMP):
    chk(P.js_check(JS, nj, JSCMP) == [] and P.js_check(JS, nj.replace("const r", "let r"), JSCMP) != [], "N5 acorn 토큰 대조(통과 · 토큰 바뀜 = 실패)")
elif node:
    print("SKIP tools/package/jscmp.js 없음(빌드 도구 이전 묶음이 옮김) — acorn 대조 건너뜀 · 줄바꿈 자리 대조는 위에서 함", flush=True)

tg = N.targets(T.ROOT)
chk(len(tg) > 100 and all(f.endswith(N.EXTS) for f in tg), "P 대상 파일 %d · 확장자" % len(tg))
chk(not (set(tg) & N.MANUAL) and set(N.targets(T.ROOT, manual=True)) >= set(tg), "P 손 판정 파일은 대상 밖(증명 범위엔 들어감)")
one = next(f for f in tg if f.startswith("src/"))
a1, a2 = N.run_file(T.ROOT, one, S)[1], N.run_file(T.ROOT, one, S)[1]
chk(a1 == a2, "P 같은 입력 두 번 = 같은 결과(%s)" % one)
T.finish()

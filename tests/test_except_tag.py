#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "except_tag.py")):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/except_tag.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import except_tag as X  # noqa: E402

HIST = "코덱스 " + "지적(10-14 확인)"
MOD = (
    '"""합성 모듈."""\n'
    "import logging\n"
    "import threading\n"
    "try:\n"
    "    import fancy_opt\n"
    "except Exception:\n"
    "    fancy_opt = None\n"
    "log = logging.getLogger(__name__)\n"
    'SEP = "가\u2028나"\n'
    "\n\n"
    "def shut(f):\n"
    "    try:\n"
    "        f.close()\n"
    "    except Exception:  # noqa: BLE001\n"
    "        pass\n"
    "\n\n"
    "def is_alive(x):\n"
    "    try:\n"
    "        return x.ping()\n"
    "    except Exception:\n"
    "        return False\n"
    "\n\n"
    "def each(xs):\n"
    "    out = []\n"
    "    for x in xs:\n"
    "        try:\n"
    "            out.append(x.v())\n"
    "        except Exception:  # noqa: BLE001 — 한 항목 실패\n"
    "            continue\n"
    "    return out\n"
    "\n\n"
    "def quiet(x):\n"
    "    try:\n"
    "        x.go()\n"
    "    except Exception:  # 무시\n"
    "        pass\n"
    "\n\n"
    "def run(job):\n"
    "    try:\n"
    "        job()\n"
    "    except Exception as e:  # noqa: BLE001\n"
    "        log.warning('실패 %s', e)\n"
    "\n\n"
    "def pump(job):\n"
    "    try:\n"
    "        job()\n"
    "    except Exception as e:\n"
    "        log.warning('실패 %s', e)\n"
    "\n\n"
    "threading.Thread(target=pump, args=(None,))\n"
    "\n\n"
    "def value(x):\n"
    "    try:\n"
    "        return x.v()\n"
    "    except Exception:  # noqa: BLE001 — " + HIST + "\n"
    "        return 0\n"
    "\n\n"
    "def odd(x):\n"
    "    try:\n"
    "        x.go()\n"
    "    except Exception:\n"
    "        notify(x)\n"
    "\n\n"
    "def main(x):\n"
    "    try:\n"
    "        x.go()\n"
    "    except Exception as e:\n"
    "        log.error('x %s', e)\n"
    "        return 1\n"
    "\n\n"
    "def multi(x):\n"
    "    try:\n"
    "        return x.v()\n"
    "    except (ValueError,\n"
    "            Exception):\n"
    "        return None\n"
    "\n\n"
    "def done(x):\n"
    "    try:\n"
    "        x.go()\n"
    "    except Exception:  # noqa: BLE001 [probe] 이미 정함\n"
    "        pass\n"
    "\n\n"
    "def again(x):\n"
    "    try:\n"
    "        x.go()\n"
    "    except Exception:\n"
    "        log.info('x')\n"
    "        raise\n"
    "\n\n"
    "def narrow(x):\n"
    "    try:\n"
    "        x.go()\n"
    "    except ValueError:\n"
    "        pass\n"
    "\n\n"
    "def notify(x):\n"
    "    return x\n"
)
RULES = os.path.join(T.ROOT, "public", "tests", "arch_baseline", "py_rules.json")
with open(RULES, encoding="utf-8") as fh:
    rules = json.load(fh)
VALID = set(rules["except_reasons"])


def line_of(text, needle, start_from=None):
    lines = X.nl_lines(text)
    begin = 0
    if start_from:
        begin = next(i for i, ln in enumerate(lines) if start_from in ln)
    return next(i + 1 for i, ln in enumerate(lines) if i >= begin and needle in ln)


sites = X.analyze_text(MOD, "src/m.py", "m", VALID, set())
by_fn = {}
for s in sites:
    by_fn.setdefault(s.qual or "<module>", []).append(s)


def one(fn):
    return by_fn[fn][0]


chk(one("<module>").status == "auto" and one("<module>").decided == "optional", "R4 선택 import(모듈 수준 · 빈 값 대입) = optional")
chk(one("shut").decided == "cleanup", "R1 try 몸통이 닫기 호출뿐 = cleanup(pass 와의 겹침은 해소 표로 cleanup)", one("shut").why)
chk(one("is_alive").decided == "probe", "R2 확인 함수의 return False = probe(fallback 과 겹침 → probe)", one("is_alive").why)
chk(one("each").decided == "isolate", "R3 반복문 안 continue = isolate")
chk(one("quiet").decided == "optional", "R4 pass 하나 = optional")
chk(one("run").decided == "boundary", "R5 입구 이름 + 로그 = boundary", one("run").why)
chk(one("pump").decided == "boundary", "R5 Thread target 으로 넘긴 함수 + 로그 = boundary", one("pump").why)
chk(one("value").decided == "fallback" and one("value").hist, "R6 값 돌려줌 = fallback · 이력 글 설명 표시")
chk(one("odd").status == "manual" and one("odd").why.startswith("R7"), "R7 맞는 규칙 없음 = 손 판정", one("odd").why)
chk(one("main").status == "manual" and one("main").why.startswith("충돌"), "해소 표 밖 충돌(boundary·fallback) = 손 판정", one("main").why)
chk(one("multi").decided == "fallback" and one("multi").line == line_of(MOD, "except (ValueError,"),
    "여러 줄 except 머리 = except 키워드 줄")
chk(one("done").status == "has", "이미 유효 코드 = 대상 밖(has)")
chk(one("again").status == "out" and one("narrow").status == "out", "마지막 raise·좁은 except = 대상 밖")
chk(X.ratchet_count(MOD, "m", VALID) == sum(s.status in ("auto", "manual") for s in sites),
    "대상 수 = 래칫 정의(_arch_py_facts.facts)로 센 except.broad 자리 수")

new, n = X.tag_text(MOD, sites)
NL = X.nl_lines(new)
auto_n = sum(s.status == "auto" for s in sites)
chk(n == auto_n and len(NL) == len(X.nl_lines(MOD)), "자동 자리 수만큼 줄을 고치고 줄 수 그대로", (n, auto_n))
chk(NL[one("shut").line - 1].rstrip() == "    except Exception:  # noqa: BLE001 [cleanup]", "noqa 뒤 [코드] 삽입",
    NL[one("shut").line - 1])
chk(NL[one("each").line - 1].rstrip().endswith("# noqa: BLE001 [isolate] — 한 항목 실패"), "설명 글 그대로", NL[one("each").line - 1])
chk(NL[one("is_alive").line - 1].rstrip() == "    except Exception:  # noqa: BLE001 [probe]", "주석 없는 줄 끝에 표식")
chk(NL[one("quiet").line - 1].rstrip() == "    except Exception:  # noqa: BLE001 [optional] 무시", "noqa 아닌 주석 앞에 표식",
    NL[one("quiet").line - 1])
vline = NL[one("value").line - 1]
chk("[fallback]" in vline and not X.D.is_history(X.D.comment_norm(vline[vline.index("#"):])) and "지적" in vline,
    "이력 표지만 빼서 이력 글 아님(설명 낱말은 남김)", vline)
chk(NL[one("odd").line - 1] == X.nl_lines(MOD)[one("odd").line - 1], "손 판정 자리는 안 건드림")
chk(NL[one("multi").line - 1].rstrip().endswith("except (ValueError,  # noqa: BLE001 [fallback]"), "여러 줄 머리 첫 줄에 표식")
chk(compile(new, "m.py", "exec") is not None and X.ratchet_count(new, "m", VALID) == len(sites and [s for s in sites if s.status == "manual"]),
    "고친 글 = 컴파일됨 · 남은 except.broad = 손 판정 수")
chk(X.analyze_text(new, "src/m.py", "m", VALID, set()) and X.tag_text(new, X.analyze_text(new, "src/m.py", "m", VALID, set()))[1] == 0,
    "apply 두 번 = 바뀜 0(멱등)")

REPO = tempfile.mkdtemp(prefix="tj_except_tag_", dir=T.TMP)
GIT = ["git", "-C", REPO, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false",
       "-c", "init.defaultBranch=main", "-c", "core.hooksPath=/dev/null"]
OTHER = '"""다른 모듈."""\n\n\ndef g(x):\n    # 그냥 주석\n    try:\n        return x()\n    except Exception:\n        return None\n'


def write(rel, text):
    path = os.path.join(REPO, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8", newline="") as fh:
        return fh.read()


write("src/m.py", MOD)
write("src/other.py", OTHER)
write("public/tests/arch_baseline/py_rules.json", json.dumps(rules, ensure_ascii=False))
OTHER_ROW = json.dumps({"k": "file.bytes", "m": "zzz", "q": "<file>", "to": 9, "why": "남의 사유", "commit": "x"}, ensure_ascii=False)
write("public/tests/arch_baseline/py_size.jsonl",
      json.dumps({"k": "file.bytes", "m": "m", "q": "<file>", "v": len(MOD.encode("utf-8"))}) + "\n"
      + json.dumps({"k": "file.bytes", "m": "other", "q": "<file>", "v": 10 ** 6}) + "\n")
write("public/tests/arch_baseline/py_growth.jsonl", OTHER_ROW + "\n")
for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "기준"]):
    subprocess.run(GIT + cmd, check=True, capture_output=True)
SHA = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

summary, _rows, manual = X.plan(REPO)
chk(summary["같음"] and summary["대상"] == summary["래칫_except_broad"], "plan 대상 수 = 래칫 수(합성 트리)", summary)
chk({(s.rel, s.line) for s in manual} == {("src/m.py", one("odd").line), ("src/m.py", one("main").line)},
    "plan 손 판정 목록 = R7·충돌 두 자리", [(s.rel, s.line, s.why) for s in manual])
md = X.manual_md(summary, manual, REPO)
chk("src/m.py:%d" % one("odd").line in md and "R7" in md, "손 판정 마크다운에 파일:줄·이유")

changed = X.apply(REPO)
chk(changed == {"src/m.py": auto_n, "src/other.py": 1}, "apply 바꾼 파일·줄", changed)
ok, probs, summ = X.verify(REPO, SHA)
chk(not ok and probs and all(p.startswith("⑧") for p in probs), "growth 전 = ⑧ 실패만(기준선 넘은 m 의 표지 줄 없음)", probs)
chk(X.main(["growth", "--root", REPO, "--base", SHA, "--commit", "c1"]) == 0, "growth rc 0")
GROW = read("public/tests/arch_baseline/py_growth.jsonl")
grows = [json.loads(x) for x in GROW.splitlines() if x.strip()]
chk(GROW.splitlines()[0] == OTHER_ROW and len(grows) == 2 and grows[1]["m"] == "m"
    and grows[1]["to"] == len(read("src/m.py").encode("utf-8")) and grows[1]["why"] == X.GROWTH_WHY,
    "growth = 남의 줄 그대로 + 기준선 넘은 m 만 표지 줄(to = 지금 바이트 · other 는 기준선 밑)", grows)
X.main(["growth", "--root", REPO, "--base", SHA, "--commit", "c1"])
chk(read("public/tests/arch_baseline/py_growth.jsonl") == GROW, "growth 두 번 = 같은 표(멱등)")
ok, probs, summ = X.verify(REPO, SHA)
chk(ok and summ["새_코드_줄"] == auto_n + 1 == summ["래칫_감소"], "verify 통과(AST·토큰·코드·재현·래칫 수)", (probs, summ))
TAGGED = read("src/m.py")


def mutate(rel, old, new_text, count=1):
    text = read(rel)
    assert text.count(old) >= 1, old
    write(rel, text.replace(old, new_text, count))


def expect_fail(label, marker):
    ok2, probs2, _s = X.verify(REPO, SHA)
    chk(not ok2 and any(p.startswith(marker) for p in probs2), label, probs2)
    write("src/m.py", TAGGED)
    write("src/other.py", X.tag_text(OTHER, X.analyze_text(OTHER, "src/other.py", "other", VALID, set()))[0])


odd_ln = one("odd").line
lines = X.nl_lines(TAGGED)
lines[odd_ln - 1] = lines[odd_ln - 1].rstrip("\n") + "  # noqa: BLE001 [optional] 알림만 — 실패는 무시\n"
write("src/m.py", "".join(lines))
ok, probs, summ = X.verify(REPO, SHA)
chk(not ok and probs and all(p.startswith("⑧") for p in probs), "손 코드로 바이트가 늘고 growth 안 돌림 = ⑧ 실패", probs)
X.main(["growth", "--root", REPO, "--base", SHA, "--commit", "c1"])
ok, probs, summ = X.verify(REPO, SHA)
chk(ok and summ["새_코드_줄"] == auto_n + 2 == summ["래칫_감소"], "손 판정 자리에 손으로 코드 = 통과(④ 허용 · ⑤ 수 맞음)", (probs, summ))
write("src/m.py", TAGGED)
write("public/tests/arch_baseline/py_growth.jsonl", GROW)


def grow_fail(label, text):
    write("public/tests/arch_baseline/py_growth.jsonl", text)
    ok2, probs2, _s = X.verify(REPO, SHA)
    chk(not ok2 and any(p.startswith("⑧") for p in probs2), label, probs2)
    write("public/tests/arch_baseline/py_growth.jsonl", GROW)


grow_fail("표지 줄 to 를 1 크게 = ⑧ 실패", GROW.replace('"to": %d' % grows[1]["to"], '"to": %d' % (grows[1]["to"] + 1)))
grow_fail("남의 줄 지움 = ⑧ 실패", GROW.split("\n", 1)[1])
grow_fail("기준선 밑 파일(other)에 표지 줄 더함 = ⑧ 실패",
          GROW + json.dumps(dict(grows[1], m="other", to=10 ** 7), ensure_ascii=False) + "\n")
grow_fail("표지 줄 빠짐 = ⑧ 실패", OTHER_ROW + "\n")
ok, probs, _s = X.verify(REPO, SHA)
chk(ok, "표 되돌린 뒤 통과", probs)

mutate("src/m.py", "        notify(x)\n", "        notify(x + 1)\n")
expect_fail("코드 바뀜 = 실패(AST)", "①")
mutate("src/other.py", "# 그냥 주석", "# 바꾼 주석")
expect_fail("except 줄 밖 주석 바뀜 = 실패", "②")
mutate("src/m.py", "[probe] 이미 정함", "[optional] 이미 정함")
expect_fail("이미 있던 코드를 바꿈 = 실패", "③")
mutate("src/m.py", "  # noqa: BLE001 [cleanup]", "  # noqa: BLE001 [bogus]")
expect_fail("틀린 코드(닫힌 목록 밖) = 실패", "③")
mutate("src/m.py", "# noqa: BLE001 [isolate] — 한 항목 실패", "# noqa: BLE001 [fallback] — 한 항목 실패")
expect_fail("자동 자리를 다른 코드로 = 실패(apply 재현과 다름)", "④")
mutate("src/m.py", "# noqa: BLE001 [isolate] — 한 항목 실패", "# noqa: BLE001 [isolate] — 한 항목 실패(" + HIST + ")")
expect_fail("바뀐 except 줄 주석이 이력 글 = 실패", "⑥")
mutate("src/m.py", "def notify(x):\n", "def notify(x):\n\n")
expect_fail("줄 더함 = 실패", "②")
write("src/extra.py", "X = 1\n")
ok, probs, _s = X.verify(REPO, SHA)
chk(not ok and any(p.startswith("⑦") for p in probs), "src 파일 추가 = 실패", probs)
os.remove(os.path.join(REPO, "src", "extra.py"))
write("src/newpkg/__init__.py", "X = 1\n")
ok, probs, _s = X.verify(REPO, SHA)
chk(not ok and any(p.startswith("⑦") and "newpkg" in p for p in probs), "허용 패키지 밖 src 하위 폴더 파일 추가 = 실패", probs)
shutil.rmtree(os.path.join(REPO, "src", "newpkg"))
write("src/data.json", "{}\n")
subprocess.run(GIT + ["add", "src/data.json"], check=True, capture_output=True)
subprocess.run(GIT + ["commit", "-q", "-m", "자료"], check=True, capture_output=True)
SHA2 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
write("src/data.json", "{\"a\": 1}\n")
ok, probs, _s = X.verify(REPO, SHA2)
chk(not ok and any("분석 밖" in p for p in probs), "분석 밖 src 파일(비 .py) 내용 바뀜 = 실패", probs)
write("src/data.json", "{}\n")
OUTSIDE = os.path.join(T.TMP, "tj_except_tag_link_%d.py" % os.getpid())
with open(OUTSIDE, "w", encoding="utf-8") as fh:
    fh.write(read("src/other.py"))
os.remove(os.path.join(REPO, "src", "other.py"))
os.symlink(OUTSIDE, os.path.join(REPO, "src", "other.py"))
ok, probs, _s = X.verify(REPO, SHA2)
chk(not ok and any("심볼릭" in p for p in probs), "같은 내용의 바깥 파일 심볼릭 링크로 바꿈 = 실패", probs)
os.remove(os.path.join(REPO, "src", "other.py"))
os.remove(OUTSIDE)
write("src/other.py", X.tag_text(OTHER, X.analyze_text(OTHER, "src/other.py", "other", VALID, set()))[0])
ok, probs, _s = X.verify(REPO, SHA2)
chk(ok, "되돌린 뒤 다시 통과", probs)
with open(os.path.join(REPO, "src", "hmac.pyc"), "wb") as fh:
    fh.write(b"\x00" * 16)
ok, probs, _s = X.verify(REPO, SHA2)
chk(not ok and any("hmac.pyc" in p for p in probs), "소스 없는 .pyc 추가 = 실패", probs)
os.remove(os.path.join(REPO, "src", "hmac.pyc"))
SRC_REAL = os.path.join(REPO, "src_real")
os.rename(os.path.join(REPO, "src"), SRC_REAL)
os.symlink(SRC_REAL, os.path.join(REPO, "src"))
ok, probs, _s = X.verify(REPO, SHA2)
chk(not ok and any("src 폴더 자체" in p for p in probs), "src 폴더를 같은 내용 사본 링크로 바꿈 = 실패", probs)
os.remove(os.path.join(REPO, "src"))
os.rename(SRC_REAL, os.path.join(REPO, "src"))
write("src/m.py", TAGGED)
subprocess.run(GIT + ["add", "-A"], check=True, capture_output=True)
subprocess.run(GIT + ["commit", "-q", "-m", "기계적 1"], check=True, capture_output=True)
SHA3 = subprocess.run(GIT + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
ok, probs, _s = X.verify(REPO, SHA3)
chk(ok, "중간 커밋 기준 verify = 앞 커밋 표지 줄이 남아도 통과(안 바뀐 파일 줄 유지)", probs)
X.main(["growth", "--root", REPO, "--base", SHA3, "--commit", "c1"])
chk(read("public/tests/arch_baseline/py_growth.jsonl") == GROW, "중간 커밋 기준 growth = 표 그대로")
ok, probs, _s = X.verify(REPO, "0" * 40)
chk(not ok and probs and probs[0].startswith("기준 rev 없음"), "없는 기준 rev = 실패")
chk(X.main(["verify", "--root", REPO]) == 2, "verify 에 --base 없음 = rc 2")

shutil.rmtree(REPO, ignore_errors=True)

GBM = X.GB
rows6 = GBM.size_rows(T.ROOT, "시험용 없는 사유", "x")
chk(rows6 == [], "size_rows(없는 사유) = 래칫 size 통과 트리에서 새 줄 0", rows6[:3])
T.finish()

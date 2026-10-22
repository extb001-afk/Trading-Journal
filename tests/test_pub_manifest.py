#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import shutil  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
LIST = os.path.join(T.ROOT, "tools", "package", "pub_files.txt")
if not (os.path.isfile(os.path.join(TOOLS, "pub_census.py")) and os.path.isfile(LIST)):
    public_layout = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(public_layout, "공개판 배치 — 비공개 도구(tools/refactor/pub_census.py · tools/package/pub_files.txt) 없음 · 건너뜀" if public_layout
        else "저장소 배치인데 tools/refactor/pub_census.py 또는 tools/package/pub_files.txt 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import pub_census as C  # noqa: E402
import pub_list as L  # noqa: E402

KNOWN_MISSING = frozenset()


def put(root, rel, data=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(data)


RULES_TXT = "\n".join([
    "# 주석 줄", "", "src/*.py => src/   # 끝 주석", "!src/secret_x.py", "?web/v2/maybe.js", "web/v2/fonts/**",
    "public/CHANGELOG.md => CHANGELOG.md", "public/tests/*.py => tests/", "tools/none_here.py", "public/README.md => README.md",
    "public/docs/*.md => docs/", "@shots public/docs/shots => docs/shots/",
])
rules = L.parse_rules(RULES_TXT)
chk([r["op"] for r in rules] == ["+", "-", "?", "+", "+", "+", "+", "+", "+", "@"], "M1 규칙 종류(+ · ! · ? · @) · 주석·빈 줄 뺌", rules)
chk(rules[0]["pat"] == "src/*.py" and rules[0]["dest"] == "src/" and rules[0]["line"] == 3, "M1 줄 끝 주석 떼기 · 자리 · 줄 번호", rules[0])
chk(rules[4]["dest"] == "CHANGELOG.md" and rules[3]["dest"] is None, "M1 '=>' 자리 · 자리 없음 = 같은 경로", rules[3:5])
chk(L.md_refs('![a](docs/x.png) [b](../C.md#v1) [c](https://h.invalid/x) [d](#top) <img src="s/q.png?x"> [f](y.md "t") [g](mailto:a)')
    == ["docs/x.png", "../C.md", "s/q.png", "y.md"], "M1 문서 링크·그림 = 상대 자리만(조각·쿼리 뗌 · 바깥·앵커 뺌)")

R = os.path.join(T.TMP, "pubtree")
for rel in ("src/a.py", "src/b.py", "src/secret_x.py", "web/v2/fonts/plex.css", "web/v2/fonts/w/x.woff2",
            "public/tests/test_a.py", "public/CHANGELOG.md", "public/docs/shots/one.png", "public/docs/shots/two.jpg", "public/docs/shots/zzz.png"):
    put(R, rel)
put(R, "public/README.md", "머리\n![설명](docs/shots/one.png) ![없는 사진](docs/shots/none.png) [바뀐 이력](CHANGELOG.md#v1) [안내](docs/G.md)\n")
put(R, "public/docs/G.md", "<img src=\"shots/two.jpg\"> [처음](../README.md) [밖](../../x.md)\n")
ex = L.expand(R, rules)
fs = ex["files"]
chk(fs.get("src/a.py") == "src/a.py" and "src/secret_x.py" not in fs and ex["excluded"] == ["src/secret_x.py"],
    "M2 glob 펼침 · '!' 로 뺀 경로 = 목록 밖 · 기록", ex)
chk(fs.get("web/v2/fonts/w/x.woff2") == "web/v2/fonts/w/x.woff2" and fs.get("public/tests/test_a.py") == "tests/test_a.py"
    and fs.get("public/CHANGELOG.md") == "CHANGELOG.md", "M2 '**' 하위 폴더 · 폴더 자리 = 같은 파일 이름 · 파일 자리", fs)
chk(fs.get("public/docs/shots/one.png") == "docs/shots/one.png" and fs.get("public/docs/shots/two.jpg") == "docs/shots/two.jpg"
    and "public/docs/shots/zzz.png" not in fs, "M2 사진 = 목록 문서가 부르는 것만(README · docs 상대 경로 · 안 부르는 사진·없는 사진 뺌)",
    sorted(k for k in fs if "shots" in k))
chk(L.broken_links(R, fs) == [{"doc": "README.md", "ref": "docs/shots/none.png"}, {"doc": "docs/G.md", "ref": "../../x.md"}],
    "M2 깨진 링크 = 공개판 자리에 목록 파일 없음 · 공개판 뿌리 밖(../ 넘침)", L.broken_links(R, fs))
chk(ex["unmatched"] == [{"line": 9, "pat": "tools/none_here.py"}], "M2 맞는 파일 없는 필수 규칙 = 목록 · 있을 때만 규칙(?)은 조용히", ex["unmatched"])

put(R, "dev/secret_src.py", "x = 1\n")
os.makedirs(os.path.join(R, "dev", "fontdir"), exist_ok=True)
put(R, "dev/fontdir/f.woff2")
os.symlink(os.path.join(R, "dev", "secret_src.py"), os.path.join(R, "src", "linked.py"))
os.symlink(os.path.join(R, "dev", "fontdir"), os.path.join(R, "web", "v2", "fonts", "ld"))
ex2 = L.expand(R, rules)
chk("src/linked.py" not in ex2["files"] and not any(k.startswith("web/v2/fonts/ld") for k in ex2["files"])
    and {"src/linked.py", "web/v2/fonts/ld"} <= set(ex2["links"]), "M2 심볼릭 링크(파일·폴더) = 목록 밖 · links 로", ex2["links"])
os.remove(os.path.join(R, "src", "linked.py"))
os.remove(os.path.join(R, "web", "v2", "fonts", "ld"))
put(R, "web/v2/fonts/.env", "K=1\n")
put(R, "web/v2/fonts/.hid/secret.pem", "x")
ex3 = L.expand(R, rules)
chk({"web/v2/fonts/.env", "web/v2/fonts/.hid/secret.pem"} <= set(ex3["files"]) and len(L.private_hits(ex3["files"])) >= 2,
    "M2 폴더 통째(**) = 숨김 파일·폴더도 후보(비공개 꼴 검사가 봄)", sorted(ex3["files"]))
os.remove(os.path.join(R, "web", "v2", "fonts", ".env"))
shutil.rmtree(os.path.join(R, "web", "v2", "fonts", ".hid"))

bad = {"web/v2/fonts/.ssh/id_ed25519": "web/v2/fonts/.ssh/id_ed25519", "web/v2/fonts/id_rsa": "web/v2/fonts/id_rsa",
       "x/.gnupg/pubring.kbx": "x/.gnupg/pubring.kbx", "x/backup.gpg": "x/backup.gpg", "x/known_hosts": "x/known_hosts",
       "HANDOFF_X.md": "HANDOFF_X.md", "docs/DESIGN_Y.md": "docs/DESIGN_Y.md", "dev/a.py": "dev/a.py", "public/.env": ".env",
       "x/.env.local": "x/.env.local", "state/p.json": "state/p.json", "tools/package/scan_owner.py": "tools/scan_owner.py",
       "review/n.md": "review/n.md", "tools/refactor/t.py": "tools/t.py", "config.json": "config.json", "a/k.pem": "a/k.pem",
       "web/v2/fonts/ledger.db": "web/v2/fonts/ledger.db", "x/l.sqlite3": "x/l.sqlite3", "x/l.db-wal": "x/l.db-wal", "x/c.json.bak_s18": "x/c.json.bak_s18",
       "x/run.log": "x/run.log", "web/v2/fonts/000000001.jsonl": "web/v2/fonts/000000001.jsonl", "x/alerts_web.jsonl.gz": "x/alerts_web.jsonl.gz", "web/v2/fonts/tj-web.log.1": "web/v2/fonts/tj-web.log.1", "x/tj-web.log.2.gz": "x/tj-web.log.2.gz", "x/.git/config": "x/.git/config", "x/dump.pm2": "x/dump.pm2", "x/__pycache__/a.cpython-39.pyc": "x/__pycache__/a.cpython-39.pyc"}
good = {"public/.env.example": ".env.example", "config.example.json": "config.example.json", "src/runbook_view.py": "src/runbook_view.py",
        "src/a.py": "src/a.py"}
hits = L.private_hits(dict(bad, **good))
chk(sorted(h["src"] for h in hits) == sorted(bad), "M3 비공개 꼴 전부 잡음 · 공개 꼴(.env.example·config.example·소문자 이름)은 통과",
    sorted(h["src"] for h in hits))
chk(L.private_hits({"src/ok.py": "dev/ok.py"}) and L.private_hits({"src/ok.py": "src/ok.py"}) == [], "M3 공개판 자리 쪽 꼴도 봄")

put(R, "web/v2/index.html", '<link rel="stylesheet" href="/v2/app.css?v=1"><script src="/v2/app.js"></script><a href="#x"></a>'
                            '<img src="data:image/png;base64,AA"><script src="https://cdn.example/x.js"></script>')
put(R, "web/v2/login.html", '<script src="/v2/login.js#k"></script>')
chk(L.web_refs(R) == ["web/v2/app.css", "web/v2/app.js", "web/v2/login.js"], "M4 /v2/ 참조만 · 쿼리·조각 뗌 · 바깥·data·앵커 뺌", L.web_refs(R))
RW = os.path.join(T.TMP, "pubtree_web")
put(RW, "web/v2/index.html", '<link rel="stylesheet" href="/v2/app.css"><script src="/v2/app.js"></script>')
put(RW, "web/v2/login.html", '<script src="/v2/login.js"></script>')
LR = os.path.join(T.TMP, "pubtree_list.txt")
for body, want in (("web/v2/app.css\nweb/v2/app.js\nweb/v2/login.js\nweb/v2/index.html\nweb/v2/login.html\nsrc/version.py\n", []),
                   ("web/v2/app.css\nweb/v2/app.js => web/v2/renamed.js\nweb/v2/login.js\nweb/v2/index.html\nweb/v2/login.html\nsrc/version.py\n",
                    ["web/v2/app.js"])):
    for rel in ("web/v2/app.css", "web/v2/app.js", "web/v2/login.js", "src/version.py"):
        put(RW, rel)
    with open(LR, "w", encoding="utf-8") as f9:
        f9.write(body)
    chk(C.manifest(RW, LR)["web_missing"] == want, "M4 화면 파일 빠짐 = 공개판 자리 기준(다른 이름으로 가면 빠짐)", [body.split("\n")[1], want])
chk(C.changed_lines("a\nb\nc\n", "a\nB\nc\nd\n") == 2 and C.changed_lines("x\n", "x\n") == 0, "M4 바뀐 줄 수(덩어리마다 긴 쪽)")
chk(C.load_rules_module("") is None and C.load_rules_module(os.path.join(T.TMP, "none_dir")) is None, "M4 규칙 파일 없음 = None(빚 세기 건너뜀)")
RD = os.path.join(T.TMP, "rules_dir")
put(RD, "scrub.py", "def scrub_py(p, s):\n    return s.replace('# 이력', '# 설명')\n\n"
                    "def scrub_js(p, s):\n    raise ValueError('x')\n\n"
                    "def scrub_html(p, s):\n    return s\n")
put(R, "src/a.py", "x = 1  # 이력\ny = 2  # 이력\n")
put(R, "web/v2/app.js", "let a = 1;\n")
mod = C.load_rules_module(RD)
d = C.debt(R, mod)
chk(d["lines"] == {"src": 2} and d["files"] == {"src": 1} and d["total"] == 2 and d["top"] == [["src/a.py", 2]],
    "M4 중립화 빚 = 갈래별 바뀐 줄·파일 · 상위", d)
chk(d["errors"] == [("web/v2/app.js", "ValueError")], "M4 규칙이 한 파일에서 실패 = 오류 목록(이름만) · 나머지는 셈", d["errors"])
with open(os.path.join(R, "src", "a.py"), encoding="utf-8") as f9:
    chk(f9.read() == "x = 1  # 이력\ny = 2  # 이력\n", "M4 원본 무변(결과 글은 버림)")

m = C.manifest(T.ROOT)
chk(m["rules"] >= 50 and m["n_files"] > 500, "P 공개 목록 펼침", (m["rules"], m["n_files"]))
chk(m["unmatched"] == [], "P 필수 규칙마다 맞는 파일 있음(없으면 빌드가 멈춤)", m["unmatched"])
chk(m["private"] == [], "P 공개 목록 ∩ 비공개 꼴 = 0", m["private"])
chk(m["links"] == [], "P 공개 목록 후보 중 심볼릭 링크 0", m["links"])
chk(m["src_not_listed"] == [], "P src/*.py 전부 공개 목록(일부러 뺀 것은 '!' 규칙)", m["src_not_listed"])
miss = set(m["web_missing"])
chk(not (miss - KNOWN_MISSING), "P 화면이 부르는데 목록 밖 = 알려진 빠짐 표 밖의 새 빠짐 0", sorted(miss - KNOWN_MISSING))
chk(not (KNOWN_MISSING - miss), "P 알려진 빠짐 표에 있는데 이제 목록에 있음 = 0(있으면 표에서 지우라)", sorted(KNOWN_MISSING - miss))
chk(len(m["web_refs"]) >= 10, f"P 화면이 부르는 /v2/ 파일 {len(m['web_refs'])} · 알려진 빠짐 {len(miss & KNOWN_MISSING)}", m["web_refs"])
chk(L.broken_links(T.ROOT, m["files"]) == [], "P 공개판 문서의 상대 링크·그림 깨짐 0(공개판 자리 기준)", L.broken_links(T.ROOT, m["files"]))
shots = sorted(d for d in m["files"].values() if d.startswith("docs/screenshots/"))
chk(len(shots) >= 56, f"P 문서가 부르는 사진 {len(shots)}장 = 공개 목록", len(shots))
src_t = {d for s9, d in m["files"].items() if s9.startswith("public/tests/")}
chk(not any(s9.startswith(("tools/refactor/", "tools/package/", "review/", "dev/")) for s9 in m["files"]) and len(src_t) > 300,
    "P 내부 도구(tools/refactor·tools/package)·review/·dev/ = 목록 밖 · 공개 시험은 목록", len(src_t))

T.finish()

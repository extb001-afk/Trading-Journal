#!/usr/bin/env python3
import os
import sys

sys.dont_write_bytecode = True
OWNER_DIR = os.environ.get("TJ_PUB_OWNER_DIR", "")
import _harness as T  # noqa: E402

import json  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
PK = os.path.join(T.ROOT, "tools", "package")
TOOL = os.path.join(PK, "cmt_scan.py")
if not os.path.isfile(TOOL):
    public_layout = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(public_layout, "공개판 배치 — 비공개 도구(tools/package/cmt_scan.py) 없음 · 건너뜀" if public_layout
        else "저장소 배치인데 tools/package/cmt_scan.py 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, PK)
import cmt_scan as CS  # noqa: E402

SYM = "ZQXTOKEN"
W_OWN = "0x7e3a9c" + "51" * 16 + "a1"
SRE = CS.sym_regex([SYM, "USDC", "X"])


def kinds(text, frags=()):
    return sorted(k for k, _v in CS.line_hits(text, SRE, frags))


L = "실" + "측"
chk(kinds("# " + L + " 잔고 $12,345 가 남음") == ["실측 금액"], "1a 운영 낱말 + 금액(유효 3자리↑) = 실측 금액")
chk(kinds("# 라이브 손실 ₩45만") == ["실측 금액"], "1b 만·억 단위 금액도")
chk(kinds("# 예: A $3,000 → B") == [] and kinds("# " + L + " 한도 $5") == [], "1c 운영 낱말 없는 예시 금액 · 유효 1자리 금액 = 안 걸림")
chk(kinds("# 지갑 0x26ab51… 로 보냄") == ["주소 조각"] and kinds("# 끝자리 …9f3c2 일치") == ["주소 조각"], "1d 줄인 주소(0x+4자↑…) · …+16진 4자↑ = 주소 조각")
chk(kinds("# 시스템 주소 0x…800a 로그") == [] and kinds("# 꼴 'xpub…'") == [], "1e '0x…' 머리 공개 시스템 꼴 · 소문자만 낱말 = 안 걸림")
chk(kinds("# 솔라나 9NLw… 에서") == ["주소 조각"], "1f base58 머리 조각(숫자·대소문자 섞임) = 주소 조각")
chk(kinds("# 오너 " + "14" + "568 지시") == ["메시지 번호"] and kinds("# 블록 14568 부터") == [], "1g 운영자 + 5자리 = 메시지 번호 · 낱말 없는 수 = 안 걸림")
chk(kinds("# 잔고 " + SYM + " 0.0083 남음") == ["종목 수량"], "1h 원장 종목 + 소수 수량 = 종목 수량")
chk(kinds("# USDC 19,999.89 입금") == ["종목 수량"], "1i 천 단위 쉼표 수량")
chk(kinds("# USDC 6 자리") == [] and kinds("# " + SYM + " 500 블록") == [] and kinds("# USDC 2026 년") == [],
    "1j 둥근 작은 수 · 단위 붙은 수 · 연도 = 안 걸림")
chk(kinds("# 1.25 처럼 종목 없는 수") == [], "1k 종목 없는 수 = 안 걸림(일반 규칙 밖)")
chk(kinds("# 보낸 곳 " + W_OWN[:8] + " 확인", ["0x7e3a9c"]) == ["운영 주소"], "1l 운영 주소 앞 조각(0x+6자) = 운영 주소")
chk(kinds("# 종전 이름 'Uniswap V4 #" + "98" + "7654' 로 남음") == ["포지션 번호"] and kinds("# LP 묶음(#" + "9876xx 여러 장)") == ["포지션 번호"]
    and kinds("# 표 #12 참고") == [], "1m LP·V4 뒤 '#'+5자리↑(또는 xx) = 포지션 번호 · 짧은 번호 = 안 걸림")

D = os.path.join(T.TMP, "tree")
os.makedirs(os.path.join(D, "src"))
os.makedirs(os.path.join(D, "web", "v2"))
with open(os.path.join(D, "src", "a.py"), "w", encoding="utf-8") as f:
    f.write('"""모듈. ' + L + ' 잔고 $12,345."""\nX = "' + L + ' $99,999"  # 지갑 0x26ab51… 확인\n')
with open(os.path.join(D, "web", "v2", "b.js"), "w", encoding="utf-8") as f:
    f.write('const s = "' + SYM + ' 12.345";  // 라이브 ₩45만\n')
with open(os.path.join(D, "web", "c.html"), "w", encoding="utf-8") as f:
    f.write('<p>x</p>\n<script>\nconst t = 1;  // 라이브 ₩45만\n</script>\n')
r = CS.scan(D, SRE, (), frozenset())
got = sorted((h[0], h[1], h[2]) for h in r["hits"])
chk(got == [("src/a.py", 1, "실측 금액"), ("src/a.py", 2, "주소 조각"), ("web/c.html", 3, "실측 금액"), ("web/v2/b.js", 1, "실측 금액")],
    "2a 독스트링·주석만 셈(문자열 리터럴 안 값 = 안 봄) · HTML <script> 안 // 주석도", got)
rv = {("src/a.py", "주소 조각", CS.sha8("0x26ab51…")), ("*", "실측 금액", CS.sha8("₩45만"))}
r2 = CS.scan(D, SRE, (), frozenset(rv))
chk(sorted((h[0], h[2]) for h in r2["hits"]) == [("src/a.py", "실측 금액")] and r2["reviewed"] == 3, "2b 예외 = 경로·종류·sha8(경로 '*' = 전부)", r2)
rvp = os.path.join(T.TMP, "rv.txt")
with open(rvp, "w", encoding="utf-8") as f:
    f.write("# 설명\nsrc/a.py\t주소 조각\t" + CS.sha8("0x26ab51…") + "   # 꼬리 설명\n\n")
chk(CS.load_reviewed(rvp) == {("src/a.py", "주소 조각", CS.sha8("0x26ab51…"))}, "2c 예외 파일 꼴(탭 3칸 · # 꼬리 무시)")
with open(rvp, "w", encoding="utf-8") as f:
    f.write("src/a.py 주소 조각\n")
chk(isinstance(T.safe(CS.load_reviewed, rvp), dict) and "_exc" in T.safe(CS.load_reviewed, rvp), "2d 예외 파일 꼴 틀림 = 오류")


def run(*args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_PUB_")}
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-I", "-B", TOOL, *args], capture_output=True, text=True, env=env, timeout=300)
    return p.returncode, p.stdout


rc, out = run("scan", "--root", D)
chk(rc == 2 and "TJ_PUB_OWNER_DIR" in out, "3a 운영자 목록 없이 = rc 2(건너뛰지 않음)", out[-300:])
OD = os.path.join(T.TMP, "owner")
os.makedirs(OD)
with open(os.path.join(OD, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"wallets": [{"address": W_OWN, "label": "synthwallet"}]}, f)
with open(os.path.join(OD, ".env"), "w", encoding="utf-8") as f:
    f.write("TJ_SYNTH=synthetic-env-0042\n")
with open(os.path.join(OD, "owner_ids.json"), "w", encoding="utf-8") as f:
    json.dump({"addrs": ["0x" + "5c" * 19 + "c3"]}, f)
rc, out = run("scan", "--root", D, env_extra={"TJ_PUB_OWNER_DIR": OD})
chk(rc == 2 and "ledger_symbols.json" in out, "3b ledger_symbols.json 빠짐 = rc 2", out[-300:])
with open(os.path.join(OD, "ledger_symbols.json"), "w", encoding="utf-8") as f:
    json.dump({"symbols": []}, f)
rc, out = run("scan", "--root", D, env_extra={"TJ_PUB_OWNER_DIR": OD})
chk(rc == 2, "3c 빈 종목 목록 = rc 2", out[-300:])
with open(os.path.join(OD, "ledger_symbols.json"), "w", encoding="utf-8") as f:
    json.dump({"symbols": [SYM]}, f)
with open(os.path.join(D, "src", "c.py"), "w", encoding="utf-8") as f:
    f.write("Y = 2  # 보낸 곳 " + W_OWN[:10] + " · 남은 " + SYM + " 0.0421\n")
rc, out = run("scan", "--root", D, "--json", env_extra={"TJ_PUB_OWNER_DIR": OD})
j = json.loads(out) if out.strip().startswith("{") else {}
chk(rc == 1 and j.get("kinds", {}).get("종목 수량") == 1 and j.get("kinds", {}).get("운영 주소") == 1 and j.get("mode") == "owner",
    "3d 운영자 목록 = 종목 수량 · 운영 주소 규칙 켜짐", j)
rc, out = run("scan", "--root", D, "--no-owner")
chk(rc == 1 and SYM not in out and W_OWN[:10] not in out and "sha8=" in out, "3e --no-owner = 일반 규칙만 · 출력에 값 없음(sha8)", out[-400:])

with open(os.path.join(OD, "ledger_symbols.json"), "w", encoding="utf-8") as f:
    json.dump({"symbols": [""]}, f)
rc, out = run("scan", "--root", D, env_extra={"TJ_PUB_OWNER_DIR": OD})
chk(rc == 2, "3f 쓸 수 있는 종목 0(빈 글자뿐) = rc 2(빈 준비물로 통과 못 함)", out[-300:])
with open(os.path.join(OD, "ledger_symbols.json"), "w", encoding="utf-8") as f:
    json.dump({"symbols": [SYM]}, f)
rc, out = run("scan", "--root", os.path.join(T.TMP, "nope"), "--no-owner")
chk(rc == 2, "3g 없는 --root = rc 2(검사 0개를 통과로 치지 않음)", out[-300:])
with open(os.path.join(D, "src", "bad.py"), "wb") as f:
    f.write(b"X = 1  # \xff\xfe\n")
rc, out = run("scan", "--root", D, "--no-owner", "--json")
chk(rc == 1 and json.loads(out).get("kinds", {}).get("읽기 실패") == 1, "3h 못 읽은 원본(UTF-8 아님) = '읽기 실패'로 걸림", out[-300:])
os.remove(os.path.join(D, "src", "bad.py"))
LOCK = os.path.join(D, "src", "locked")
os.makedirs(LOCK)
os.chmod(LOCK, 0)
rc, out = run("scan", "--root", D, "--no-owner", "--json")
os.chmod(LOCK, 0o700)
j = json.loads(out) if out.strip().startswith("{") else {}
chk(os.geteuid() == 0 or (rc == 1 and j.get("kinds", {}).get("읽기 실패") == 1), "3i 못 연 폴더 = '읽기 실패'로 걸림(그 아래 검사 못 함)", out[-300:])

DB = os.path.join(T.TMP, "l.db")
con = sqlite3.connect(DB)
con.executescript("CREATE TABLE assets(asset_id INTEGER PRIMARY KEY, symbol TEXT);CREATE TABLE postings(posting_id INTEGER PRIMARY KEY, asset_id INTEGER);"
                  "INSERT INTO assets VALUES(1,'" + SYM + "'),(2,' QQQX '),(3,'NOPOST'),(4,NULL);INSERT INTO postings VALUES(1,1),(2,2),(3,4);")
con.commit()
con.close()
OUTJ = os.path.join(T.TMP, "sy.json")
rc, out = run("symbols", "--ledger", DB, "--out", OUTJ)
chk(rc == 0 and json.load(open(OUTJ, encoding="utf-8")) == {"symbols": ["QQQX", SYM]}, "4a 기장된 자산 심볼만(공백 뗌 · 기장 없는 자산·NULL 뺌)", out)
rc, out = run("symbols", "--ledger", DB, "--out", os.path.join(T.ROOT, "tools", "package", "sy_tmp.json"))
chk(rc == 2 and not os.path.exists(os.path.join(T.ROOT, "tools", "package", "sy_tmp.json")), "4b 저장소 안 출력 = rc 2(종목 목록 = 운영자 정보)", out)
sz = os.path.getsize(DB)
rc, out = run("symbols", "--ledger", DB, "--out", DB)
chk(rc == 2 and os.path.getsize(DB) == sz, "4c 출력 = 원장 자신 = rc 2(원장 안 덮음)", out)
DB2 = os.path.join(T.TMP, "l%2Edb")
with open(DB2, "wb") as f, open(DB, "rb") as g:
    f.write(g.read())
rc, out = run("symbols", "--ledger", DB2, "--out", DB)
with open(DB, encoding="utf-8") as f:
    got4 = f.read()
chk(rc == 0 and json.loads(got4) == {"symbols": ["QQQX", SYM]}, "4c2 원장 이름의 %2E 는 글자 그대로 읽음(출력 파일로 풀려 읽다 덮지 않음)", out)
with open(DB, "wb") as f, open(DB2, "rb") as g:
    f.write(g.read())
LNK = os.path.join(T.TMP, "lnk.json")
os.symlink(os.path.join(T.ROOT, "tools", "package", "sy_tmp2.json"), LNK)
rc, out = run("symbols", "--ledger", DB, "--out", LNK)
chk(rc == 2 and not os.path.exists(os.path.join(T.ROOT, "tools", "package", "sy_tmp2.json")), "4d 저장소 안을 가리키는 링크 출력 = rc 2", out)
ALT = os.path.join(T.TMP, "L.DB")
if os.path.exists(ALT) and os.path.samefile(ALT, DB):
    rc, out = run("symbols", "--ledger", DB, "--out", ALT)
    chk(rc == 2 and os.path.getsize(DB) == sz, "4f 대소문자만 다른 원장 별칭 출력 = rc 2(원장 안 덮음)", out)
    up = os.path.join(T.ROOT.upper() if os.path.exists(T.ROOT.upper()) else T.ROOT, "tools", "package", "sy_tmp3.json")
    rc, out = run("symbols", "--ledger", DB, "--out", up)
    chk(rc == 2 and not os.path.exists(os.path.join(T.ROOT, "tools", "package", "sy_tmp3.json")), "4g 대소문자 별칭 저장소 경로 출력 = rc 2", out)
WAL = DB + "-wal"
with open(WAL, "wb") as f:
    f.write(b"WALDATA")
rc, out = run("symbols", "--ledger", DB, "--out", WAL)
rc2, out2 = run("symbols", "--ledger", DB, "--out", DB + "-journal")
chk(rc == 2 and open(WAL, "rb").read() == b"WALDATA" and rc2 == 2 and not os.path.exists(DB + "-journal"),
    "4h 출력 = 원장 곁 파일(-wal·-journal) = rc 2(안 덮음·안 만듦)", [out, out2])
os.remove(WAL)
rc, out = run("symbols", "--ledger", DB, "--out", OUTJ)
chk(rc == 0 and not [x for x in os.listdir(T.TMP) if x.startswith(".ledger_symbols.")] and (os.stat(OUTJ).st_mode & 0o077) == 0,
    "4e 다시 써도 임시 파일 안 남음 · 권한 0600", sorted(os.listdir(T.TMP)))

E_OWN = "0x" + "4b7e" * 9 + "c0de"
B_OWN = "Syn" + "th7Wa11et" * 4 + "Q"
EV = {E_OWN[2:]}
chk([a for _l, a in CS.raw_hits('A = "' + E_OWN + '"\n', EV)] == [E_OWN], "6a 코드 글자 안 EVM 주소 전체 = 걸림")
chk([a for _l, a in CS.raw_hits('{"t": "0x' + "0" * 24 + E_OWN[2:].upper() + '"}', EV)] == [E_OWN], "6b 32바이트 패딩·대문자 = 걸림(16진 줄 안 어디든)")
chk([a for _l, a in CS.raw_hits("input 0xa9059cbb" + "0" * 24 + E_OWN[2:] + "f" * 64, EV)] == [E_OWN], "6c input 속(앞뒤 16진 붙음) = 걸림")
chk(CS.raw_hits("x " + E_OWN[:41] + " y", EV) == [] and CS.raw_hits("0x" + "4b7e" * 10, EV) == [], "6d 한 자 모자란 주소 · 다른 주소 = 안 걸림")
chk([(l, a) for l, a in CS.raw_hits("a\nb " + B_OWN + "\n", (), [B_OWN])] == [(2, B_OWN)] and CS.raw_hits(B_OWN.lower(), (), [B_OWN]) == [],
    "6e base58 = 글자 그대로(줄 번호) · 대소문자 다르면 안 걸림")
D6 = os.path.join(T.TMP, "tree6")
for sub in ("src", "tools", "dev/x", "public/tests"):
    os.makedirs(os.path.join(D6, sub))
files6 = {"src/k.py": 'K = "' + E_OWN + '"\n', "tools/fx.json": '{"topics": ["0x' + "0" * 24 + E_OWN[2:] + '"]}\n',
          "RUN.md": "지갑 " + B_OWN + "\n", "dev/x/n.md": E_OWN + " " + B_OWN + "\n", "public/tests/ok.py": "X = 1\n"}
for rel, body in files6.items():
    with open(os.path.join(D6, rel), "w", encoding="utf-8") as f:
        f.write(body)
r6 = CS.scan(D6, None, (), frozenset(), (EV, [B_OWN]))
got6 = sorted((h[0], h[1], h[2]) for h in r6["hits"])
chk(got6 == [("RUN.md", 1, "운영 주소 원문"), ("src/k.py", 1, "운영 주소 원문"), ("tools/fx.json", 1, "운영 주소 원문")] and r6["raw_files"] == 4,
    "6f 트리: 코드 글자(.py)·JSON 패딩·뿌리 문서 = 걸림 · dev/ = 대상 밖", (got6, r6.get("raw_files")))
chk(not CS.scan(D6, None, (), frozenset())["hits"], "6g 운영자 목록 없으면(owner_full 없음) 원문 규칙 안 봄")
rv6 = frozenset({("*", "운영 주소 원문", CS.sha8(E_OWN))})
chk(sorted(h[0] for h in CS.scan(D6, None, (), rv6, (EV, [B_OWN]))["hits"]) == ["RUN.md"], "6h 예외 = 종류 '운영 주소 원문' · sha8(주소)")
OD6 = os.path.join(T.TMP, "owner6")
os.makedirs(OD6)
with open(os.path.join(PK, "known_public_addresses.txt"), encoding="utf-8") as f:
    PUBA = next(ln.split("#", 1)[0].split()[0] for ln in f if ln.split("#", 1)[0].strip().lower().startswith("0x"))
with open(os.path.join(OD6, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"wallets": [{"address": E_OWN, "label": "synthwallet"}, {"address": B_OWN, "label": "synthsol", "type": "sol"}]}, f)
with open(os.path.join(OD6, ".env"), "w", encoding="utf-8") as f:
    f.write("TJ_SYNTH=synthetic-env-0042\n")
with open(os.path.join(OD6, "owner_ids.json"), "w", encoding="utf-8") as f:
    json.dump({"addrs": [PUBA]}, f)
with open(os.path.join(OD6, "ledger_symbols.json"), "w", encoding="utf-8") as f:
    json.dump({"symbols": [SYM]}, f)
evm6, oth6 = CS.load_owner_full(OD6)
chk(evm6 == EV and oth6 == [B_OWN], "6i 준비물 → EVM 몸통(소문자)·그 밖 주소 · 공개 목록 주소(known_public) 뺌", (sorted(evm6), oth6))
with open(os.path.join(D6, "src", "pub.py"), "w", encoding="utf-8") as f:
    f.write('P = "' + PUBA + '"\n')
rc, out = run("scan", "--root", D6, "--json", env_extra={"TJ_PUB_OWNER_DIR": OD6})
j6 = json.loads(out) if out.strip().startswith("{") else {}
chk(rc == 1 and j6.get("kinds", {}).get("운영 주소 원문") == 3 and E_OWN not in out and B_OWN not in out,
    "6j CLI(운영자 목록) = 원문 3건(공개 주소 0) · 출력에 값 없음", out[-400:])
rc, out = run("scan", "--root", D6, "--no-owner", "--json")
chk(rc == 0 and "운영 주소 원문" not in out, "6k --no-owner = 원문 규칙 안 봄", out[-300:])
with open(os.path.join(D6, "tools", "bin.json"), "wb") as f:
    f.write(b'{"x": "\xff\xfe", "a": "' + E_OWN.encode() + b'"}\n')
with open(os.path.join(D6, "tools", "w.mjs"), "w", encoding="utf-8") as f:
    f.write("export const A = '" + B_OWN + "';\n")
r6b = CS.scan(D6, None, (), frozenset(), (EV, [B_OWN]))
chk(sorted(h[0] for h in r6b["hits"] if h[2] == "운영 주소 원문") == ["RUN.md", "src/k.py", "tools/bin.json", "tools/fx.json", "tools/w.mjs"],
    "6l UTF-8 아닌 바이트 섞인 JSON · .mjs 도 원문 검사(건너뜀 0)", sorted((h[0], h[2]) for h in r6b["hits"]))
with open(os.path.join(OD6, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"wallets": [{"address": "0x" + "4b7e" * 3, "label": "synthwallet"}]}, f)
with open(os.path.join(OD6, "owner_ids.json"), "w", encoding="utf-8") as f:
    json.dump({"addrs": ["not-a-real-wallet"]}, f)
rc, out = run("scan", "--root", D6, "--json", env_extra={"TJ_PUB_OWNER_DIR": OD6})
chk(rc == 2, "6m 조각만 있고 원문 주소 0개인 준비물 = rc 2(빈 준비물로 통과 못 함)", out[-300:])

rc, out = run("scan", "--no-owner")
chk(rc == 0, "5a 저장소 원본 주석·독스트링 = 일반 규칙 0건", out[-1500:])
od = OWNER_DIR
if od and os.path.isfile(os.path.join(od, "ledger_symbols.json")):
    rc, out = run("scan", env_extra={"TJ_PUB_OWNER_DIR": od})
    chk(rc == 0, "5b 저장소 원본 = 원장 종목·운영 주소 규칙도 0건", out[-1500:])
else:
    print("SKIP 5b 운영자 목록(TJ_PUB_OWNER_DIR/ledger_symbols.json) 없음 — 전체 규칙은 공개판 드라이런(pub_dryrun) 단계에서", flush=True)
T.finish()

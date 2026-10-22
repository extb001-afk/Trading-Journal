#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
PK = os.path.join(T.ROOT, "tools", "package")
TOOL = os.path.join(PK, "pub_scan.py")
if not os.path.isfile(TOOL):
    public_layout = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(public_layout, "공개판 배치 — 비공개 도구(tools/package/pub_scan.py) 없음 · 건너뜀" if public_layout
        else "저장소 배치인데 tools/package/pub_scan.py 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, PK)
import pub_scan as PS  # noqa: E402

W_OWN = "0x" + "7e" * 19 + "a1"
W_DEP = "0x" + "6d" * 19 + "b2"
ENV_V = "synthetic-env-value-0042"
ID_ADDR = "0x" + "5c" * 19 + "c3"
SYM = "ZQXTOKEN"


def put(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb" if isinstance(data, bytes) else "w", **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
        f.write(data)


OD = os.path.join(T.TMP, "owner")
put(OD, "config.json", json.dumps({"wallets": [{"address": W_OWN, "label": "synthwallet"}],
                                   "exchange_addresses": [{"address": W_DEP, "memo": "memo-77881"}],
                                   "chains": {"x": {"rpcs": ["https://rpc.invalid/v2/" + "ab" * 16]}}}))
put(OD, ".env", "# 주석\nTJ_SYNTH_KEY=" + ENV_V + "\nSHORT=abc\n")
put(OD, "owner_ids.json", json.dumps({"addrs": [ID_ADDR], "labels": ["acctalias9"], "strings": ["owner-domain.invalid"],
                                      "patterns": [["내부 호스트", r"\bsynthhost\d+\b"]],
                                      "allow": [["docs/ok.md", "내부 호스트"], ["src/allow3.py", "내부 호스트", "synthhost7"]]}))
CW_BTC = "bc1q" + "zx8" * 12 + "w2"
CW_XPUB = "xpub" + "6Cs1nTh" * 15 + "Q"
CW_DESC = "wpkh([0a1b2c3d/84h/0h/0h]" + CW_XPUB + "/<0;1>/*)#synthck1"
CW_TON = "UQ" + "Sy_nTh-0" * 5 + "TonAddrSynthQQ"
cfg0 = json.loads(open(os.path.join(OD, "config.json"), encoding="utf-8").read())
cfg0["chain_wallets"] = [{"chain": "btc", "network": "mainnet", "mode": "address", "address": "  " + CW_BTC + " "},
                         {"chain": "btc", "network": "mainnet", "mode": "descriptor", "descriptor": CW_DESC[:30] + " \n " + CW_DESC[30:], "label": "synthcoldbtc"},
                         {"chain": "ton", "network": "mainnet", "address": CW_TON}]
put(OD, "config.json", json.dumps(cfg0))
RJ = os.path.join(T.TMP, "rules.json")
put(T.TMP, "rules.json", json.dumps({"symbols": [SYM], "aliases": [r"acct\d+"], "subs": {}}))


def run(out, env_extra, *extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_PUB_")}
    env.update(env_extra)
    p = subprocess.run([sys.executable, "-I", "-B", TOOL, out, *extra], capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stdout


OK_ENV = {"TJ_PUB_OWNER_DIR": OD, "TJ_PUB_RULES": RJ}
CLEAN = os.path.join(T.TMP, "clean")
put(CLEAN, "src/a.py", '"""모듈 설명."""\nX = 1  # 일반 설명\n')
put(CLEAN, "README.md", "# 제목\n설명 글.\n")

rc, out = run(CLEAN, OK_ENV)
chk(rc == 0 and "통과 — 0건" in out and "오너 실값" in out, "[1] 준비물 다 있음 + 깨끗한 산출물 = rc 0", out)
for name, env in (("오너 폴더 없음", {"TJ_PUB_RULES": RJ}), ("규칙 json 없음", {"TJ_PUB_OWNER_DIR": OD}),
                  ("없는 오너 폴더", {"TJ_PUB_OWNER_DIR": os.path.join(T.TMP, "none"), "TJ_PUB_RULES": RJ})):
    rc, out = run(CLEAN, env)
    chk(rc == 2 and "필수" in out, f"[1] {name} = rc 2(대조 없이 통과 못 함)", out)
OD2 = os.path.join(T.TMP, "owner_noids")
for fn in ("config.json", ".env"):
    put(OD2, fn, open(os.path.join(OD, fn), encoding="utf-8").read())
rc, out = run(CLEAN, {"TJ_PUB_OWNER_DIR": OD2, "TJ_PUB_RULES": RJ})
chk(rc == 2 and "owner_ids.json" in out, "[1] owner_ids.json 없음 = rc 2", out)
for name, fn9, body in (("규칙 json 빈 사전", "rules_empty.json", "{}"), ("규칙 json 종목 0", "rules_nosym.json", json.dumps({"symbols": [], "aliases": ["x"]}))):
    put(T.TMP, fn9, body)
    rc, out = run(CLEAN, {"TJ_PUB_OWNER_DIR": OD, "TJ_PUB_RULES": os.path.join(T.TMP, fn9)})
    chk(rc == 2 and "비었음" in out, f"[1] {name} = rc 2(빈 대조 목록으로 통과 못 함)", out)
for name, fn9, body in (("config 지갑 0", "config.json", "{}"), (".env 빈 파일", ".env", ""), ("owner_ids 빈 사전", "owner_ids.json", "{}")):
    OD3 = os.path.join(T.TMP, "owner_empty_" + fn9.strip("."))
    for f9 in ("config.json", ".env", "owner_ids.json"):
        put(OD3, f9, body if f9 == fn9 else open(os.path.join(OD, f9), encoding="utf-8").read())
    rc, out = run(CLEAN, {"TJ_PUB_OWNER_DIR": OD3, "TJ_PUB_RULES": RJ})
    chk(rc == 2 and "비었음" in out, f"[1] {name} = rc 2(빈 대조 목록으로 통과 못 함)", out)
put(T.TMP, "rules_str.json", json.dumps({"symbols": SYM, "aliases": []}))
rc, out = run(CLEAN, {"TJ_PUB_OWNER_DIR": OD, "TJ_PUB_RULES": os.path.join(T.TMP, "rules_str.json")})
chk(rc == 2, "[1] 규칙 symbols 가 목록 아님(글자 하나) = rc 2", out)
put(T.TMP, "rules_bad.json", "[1, 2]")
rc, out = run(CLEAN, {"TJ_PUB_OWNER_DIR": OD, "TJ_PUB_RULES": os.path.join(T.TMP, "rules_bad.json")})
chk(rc == 2, "[1] 규칙 json 꼴 틀림 = rc 2", out)
rc, out = run(CLEAN, {}, "--synthetic")
chk(rc == 0 and "합성 자료" in out, "[1] --synthetic = 오너 대조 없이(합성 녹화본 전용) · 그렇다고 출력에 적힘", out)

OD12 = os.path.join(T.TMP, "owner_chainonly")
for n12 in (".env", "owner_ids.json"):
    put(OD12, n12, open(os.path.join(OD, n12), encoding="utf-8").read())
put(OD12, "config.json", json.dumps(dict(cfg0, wallets=[])))
rc, out = run(CLEAN, {"TJ_PUB_OWNER_DIR": OD12, "TJ_PUB_RULES": RJ})
chk(rc == 0, "[1] 비EVM 지갑만 있는 오너 설정(wallets 빈 목록 + chain_wallets) = 준비물 통과", out[-300:])
for nm12, body12, kind12 in (("BTC 주소(대문자로 바꿔도)", CW_BTC.upper(), "오너 체인 지갑 주소"), ("확장 공개 키만", CW_XPUB, "오너 확장 공개 키"),
                             ("디스크립터 통째", CW_DESC, "오너 BTC 디스크립터"), ("TON 주소", CW_TON, "오너 체인 지갑 주소"),
                             ("디스크립터 원문(공백 든 채)", CW_DESC[:30] + " \n " + CW_DESC[30:], "오너 BTC 디스크립터"),
                             ("디스크립터 원문 JSON 글자(줄바꿈 이스케이프)", json.dumps(CW_DESC[:30] + " \n " + CW_DESC[30:])[1:-1], "오너 BTC 디스크립터"),
                             ("체인 지갑 별명", "synthcoldbtc", "오너 지갑 별명")):
    D12 = os.path.join(T.TMP, "cw12_" + kind12.replace(" ", "_") + str(len(body12)))
    put(D12, "src/a.py", 'X = "%s"\n' % body12)
    rc, out = run(D12, OK_ENV)
    chk(rc == 1 and "[" + kind12 + "]" in out and body12 not in out, f"[2] chain_wallets {nm12} = 잡음 · 값 안 찍음", out[-300:])
D2 = os.path.join(T.TMP, "d2")
put(D2, "src/w.py", "A = '" + W_OWN.upper().replace("0X", "0x") + "'\n")
put(D2, "docs/shot.png", b"\x89PNG\x00meta:" + W_DEP.encode() + b"\x00")
put(D2, "src/e.py", "K = '" + ENV_V + "'\n")
put(D2, "src/i.py", "Z = '" + ID_ADDR + "'  # owner-domain.invalid\nH = 'synthhost3'\n")
put(D2, "src/m.py", "M = 'memo-77881'\nR = 'https://rpc.invalid/v2/" + "ab" * 16 + "'\n")
put(D2, "web/x.js", "// acctalias9 의 설명\nlet q = 1;\n")
put(D2, "src/lab.py", "LABEL = 'synthwallet'\n")
rc, out = run(D2, OK_ENV)
kinds = {ln.split("[")[1].split("]")[0] for ln in out.splitlines() if "✗" in ln}
chk(rc == 1 and {"오너 지갑 주소", "오너 입금 주소", "오너 입금 메모", "오너 키 박힌 RPC", "오너 주소", "오너 글자", "내부 호스트", "오너 지갑 별명"} <= kinds
    and any(k.startswith("오너 .env 값") for k in kinds), "[2] 오너 실값 종류 전부 잡음(대소문자 무시 · 바이너리 사진 메타 포함)", sorted(kinds))
chk(any("src/lab.py" in ln and "[오너 지갑 별명]" in ln for ln in out.splitlines()), "[2] 별명 = 주석 밖 코드 글자도 잡음", out[-300:])
chk(all(v not in out and v.lower() not in out.lower() for v in (W_OWN, W_DEP, ENV_V, ID_ADDR, "memo-77881", "owner-domain.invalid", "acctalias9", "synthhost3", "synthwallet", "ab" * 16)),
    "[2] 출력에 오너 값 없음(sha8 만 · 키 박힌 RPC 의 키 조각 포함)")
D2c = os.path.join(T.TMP, "d2c")
put(D2c, "seed/x.json", json.dumps({"_note": "acctalias9 · " + ID_ADDR + " · 2026-01-07", "w": W_OWN}, ensure_ascii=True).replace("a", "\\u0061"))
rc, out = run(D2c, OK_ENV)
k2c = {ln.split("[")[1].split("]")[0] for ln in out.splitlines() if "✗" in ln}
chk(rc == 1 and {"오너 지갑 별명", "오너 지갑 주소", "날짜"} <= k2c and "acctalias9" not in out,
    "[2] JSON \\uXXXX 이스케이프로 감춘 오너 값·별명·날짜도 잡음(값 안 찍음)", sorted(k2c))
for name, body, want in (("오너 정규식", '{"host": "synth\\u0068ost3"}', "내부 호스트"),
                        ("중복 키 앞쪽 값", '{"v": "\\u006fwner-domain.invalid", "v": "ok"}', "오너 글자"),
                        ("별명 부분 글자 뒤 이스케이프", '{"a": "acctalias9x", "b": "\\u0061cctalias9"}', "오너 지갑 별명"),
                        ("이스케이프 따옴표 뒤 메모", '{"_note": "memo \\u0022' + SYM + '\\u0022"}', "보유 종목")):
    put(D2c, "seed/x.json", body + "\n")
    rc, out = run(D2c, OK_ENV)
    chk(rc == 1 and "[" + want + "]" in out and "synthhost3" not in out, f"[2] JSON 이스케이프 — {name} 도 잡음(낱말 단위로 풀어 글 검사 전부)", out[-300:])
put(D2c, "seed/x.json", "{}\n")
put(D2c, "web/v2/fonts/owner-domain.invalid.woff2", b"\x00")
MAILD = "@" + "gmail.com"
put(D2c, "src/n.py", "E = 'synthhost3" + MAILD + "'\n")
rc, out = run(D2c, OK_ENV)
chk(rc == 1 and "[파일 이름 속 오너 글자]" in out and "owner-domain" not in out, "[2] 파일 이름 속 오너 글자 = 잡음 · 이름은 안 찍음", out[-300:])
chk("synthhost3" not in out and "[이메일]  sha8=" in out, "[2] 일반 꼴(이메일) 조각에 오너 정규식 일치 글자 = 해시만", out[-300:])
OD5 = os.path.join(T.TMP, "owner_short")
for f9 in ("config.json", ".env"):
    put(OD5, f9, open(os.path.join(OD, f9), encoding="utf-8").read())
ids5 = json.loads(open(os.path.join(OD, "owner_ids.json"), encoding="utf-8").read())
ids5["strings"] = ids5["strings"] + ["zqal5"]
put(OD5, "owner_ids.json", json.dumps(ids5))
D2s = os.path.join(T.TMP, "d2s")
put(D2s, "src/h.py", "P = '/home/" + "zqal5/x'\n")
rc, out = run(D2s, {"TJ_PUB_OWNER_DIR": OD5, "TJ_PUB_RULES": RJ})
chk(rc == 1 and "[오너 글자]" in out and "[홈 경로]  sha8=" in out and "zqal5" not in out, "[2] 짧은(6자 미만) 오너 글자 = 일반 꼴(홈 경로) 조각에서도 해시만", out[-300:])
os.remove(os.path.join(D2c, "web", "v2", "fonts", "owner-domain.invalid.woff2"))
put(D2c, "web/v2/fonts/synthhost5.bak", "")
put(D2c, "src/q.py", "# acct42" + MAILD + "\n")
rc, out = run(D2c, OK_ENV)
chk(rc == 1 and "synthhost5" not in out and "acct42" not in out, "[2] 가린 파일 이름의 다른 걸림 조각·별명 규칙 일치 글자도 안 찍음", out[-400:])
os.remove(os.path.join(D2c, "web", "v2", "fonts", "synthhost5.bak"))
os.remove(os.path.join(D2c, "src", "q.py"))
os.remove(os.path.join(D2c, "src", "n.py"))
put(D2c, "src/m.py", "E = 'acctalias9" + MAILD + "'\n")
rc, out = run(D2c, OK_ENV)
chk(rc == 1 and "acctalias9" not in out and "[이메일]  sha8=" in out, "[2] 일반 꼴(이메일) 조각에 별명이 들면 해시만", out[-300:])
D2b = os.path.join(T.TMP, "d2b")
put(D2b, "src/k.py", "U = 'https://h.invalid/x?api_key=" + ENV_V + "'\n")
rc, out = run(D2b, OK_ENV)
chk(rc == 1 and "[키 박힌 URL]  sha8=" in out and ENV_V not in out, "[2] 일반 꼴 조각에 오너 값이 들면 해시만 출력", out[-300:])

D3 = os.path.join(T.TMP, "d3")
known = sorted(PS._addr_list())
k_evm = next(a for a in known if a.startswith("0x"))
HOME9, IP9 = "/Us" + "ers/someone/x", ".".join(("93", "184", "216", "34"))
put(D3, "src/g.py", "P = '" + HOME9 + "'\nIP = '" + IP9 + "'\nH = '" + "9f" * 32 + "'\nA = '0x" + "12" * 20 + "'\nB = '" + k_evm + "'\nL = '127.0.0.1'\n")
for rel in (".env", "config.json", "state/x.json", "q/inbox.jsonl", "tests/arch_baseline/ok.jsonl"):
    put(D3, rel, "{}\n")
r3 = PS.scan(D3, [], None, [], set())
k3 = sorted({(h[0], h[2]) for h in r3["hits"]})
chk({("src/g.py", "홈 경로"), ("src/g.py", "공인 IPv4"), ("src/g.py", "64hex(tx 해시·키?)"), ("src/g.py", "허용목록 밖 EVM 주소")} <= set(k3)
    and sum(1 for h in r3["hits"] if h[2] == "허용목록 밖 EVM 주소") == 1, "[3] 홈 경로 · 공인 IP(루프백 아님) · 64hex · 목록 밖 주소(목록 안 = 통과)", k3)
forb = sorted(h[0] for h in r3["hits"] if h[2] == "금지 파일")
chk(forb == [".env", "config.json", "q/inbox.jsonl", "state/x.json"], "[3] 금지 파일(.jsonl 래칫 기준선은 예외)", forb)

D4 = os.path.join(T.TMP, "d4")
put(D4, "src/c.py", '"""' + SYM + ' 이야기."""\nS = "' + SYM + '"  # 2026-01-02 코덱스 지적\n')
put(D4, "docs/g.md", SYM + " 를 예로 든 문서 · 2026-01-03\n")
put(D4, "web/v2/s.js", "const re = /a\\/\\/b/; const s = '/* 아님 */'; const t = `${'x' + `// 아님`}`; // " + SYM + "\n/* 2026-01-04 */\n"
    "let n = 4; const x = n++ / 2; // 2026-01-06\n"
    "const y = `${/}/.test('x') /* 2026-01-08 */}`;\n")
put(D4, "seed/n.json", '{"_note": "코덱스 메모", "v": "2026-01-05"}\n')
rules = PS.load_rules(RJ)
r4 = PS.scan(D4, [], None, rules, set())
got = sorted((h[0], h[1], h[2]) for h in r4["hits"])
chk(("src/c.py", 1, "보유 종목") in got and ("src/c.py", 2, "보유 종목") not in got and ("src/c.py", 2, "날짜") in got and ("src/c.py", 2, "검수 태그") in got,
    "[4] 파이썬: 독스트링·주석의 종목·날짜·검수 태그 잡음 · 코드 글자 종목은 아님", got)
chk(("docs/g.md", 1, "날짜") in got and ("docs/g.md", 1, "보유 종목") not in got, "[4] 문서(.md): 날짜는 봄 · 예시 종목은 사람 검토(규칙 밖)", got)
js = [g for g in got if g[0] == "web/v2/s.js"]
chk(js == [("web/v2/s.js", 1, "보유 종목"), ("web/v2/s.js", 2, "날짜"), ("web/v2/s.js", 3, "날짜"), ("web/v2/s.js", 4, "날짜")],
    "[4] JS 렉서: 정규식·문자열·템플릿 안 '//'·'/*' 는 주석 아님 · 증감 뒤 '/' = 나눗셈", js)
chk(("seed/n.json", 1, "검수 태그") in got and not any(g[0] == "seed/n.json" and g[2] == "날짜" for g in got), "[4] JSON = 메모 칸만", got)
chk(all(h[3].startswith("sha8=") for h in r4["hits"] if h[2] == "보유 종목"), "[4] 보유 종목 조각 = sha8 만")

D5 = os.path.join(T.TMP, "d5")
put(D5, "tests/test_ex_sign.py", "N = '" + "-".join(("00000000", "0000", "4000", "8000", "000000000001")) + "'\n")
put(D5, "docs/ok.md", "synthhost1 synthhost2\n")
put(D5, "src/allow3.py", "A = 'synthhost7'\nB = 'synthhost8'\n")
put(D5, "src/own.py", "O = '" + W_OWN + "'\n")
ids = PS.load_ids(os.path.join(OD, "owner_ids.json"))
ids["allow"].add(("src/own.py", "오너 지갑 주소"))
owner, labels = PS.load_owner(os.path.join(OD, "config.json"), os.path.join(OD, ".env"))
r5 = PS.scan(D5, owner, ids, [], labels)
g5 = sorted((h[0], h[2], h[3] if not h[3].startswith("sha8=") else "sha8") for h in r5["hits"])
chk(not any(h[0] == "tests/test_ex_sign.py" for h in r5["hits"]), "[5] REVIEWED(합성 nonce) 빠짐", g5)
chk(not any(h[0] == "docs/ok.md" for h in r5["hits"]) and [h[0] for h in r5["hits"] if h[2] == "내부 호스트"] == ["src/allow3.py"],
    "[5] allow 2칸 = 그 파일 그 종류 전부 · 3칸 = 그 글자만(다른 글자는 걸림)", g5)
chk(("src/own.py", "오너 지갑 주소", "sha8") in g5, "[5] 오너 실값은 allow 로 못 뺌", g5)
put(D5, "web/v2/h.js", "const A = 'synthwallet';\n")
put(D5, "web/v2/h2.js", "const A = 'synthwallet';\n")
ids["allow"] |= {("web/v2/h.js", "오너 지갑 별명", "sha8=" + PS.sha8("synthwallet")), ("web/v2/h2.js", "오너 지갑 별명")}
r5b = PS.scan(D5, owner, ids, [], labels)
lab5 = sorted(h[0] for h in r5b["hits"] if h[2] == "오너 지갑 별명")
chk(lab5 == ["web/v2/h2.js"], "[5] 별명 낱말 겹침 = 파일·sha8 3칸 예외만(2칸 통째 예외는 안 됨)", lab5)
gl = {x: bool(PS.GENERIC_LABEL.match(x)) for x in ("지갑 12", "Wallet7", "Solana 3", "지갑 NN", "my wallet 1", "synthwallet", "지갑-12", "acct9x",
                                                    "0x12", "acctalias9", "Kimchi 7", "지갑 12 메인")}
chk([x for x, v in gl.items() if v] == ["지갑 12", "Wallet7", "Solana 3"], "[6] 일반 번호 라벨 = 일반 낱말(지갑·체인 이름) + 숫자만(지어낸 낱말 + 숫자 = 고유 별명)", gl)
D6 = os.path.join(T.TMP, "d6")
put(D6, "web/v2/g.js", "// 예: '지갑 12' · 'Wallet7' 같은 이름\nconst a = 1;\n")
put(D6, "web/v2/u.js", "// 'synthwallet' 과 'acctalias9'\n")
ids6 = PS.load_ids(os.path.join(OD, "owner_ids.json"))
ids6["labels"] |= {"Wallet7"}
r6 = PS.scan(D6, owner, ids6, [], set(labels) | {"지갑 12"})
lab6 = sorted((h[0], h[3]) for h in r6["hits"] if h[2] == "오너 지갑 별명")
chk(lab6 == sorted([("web/v2/u.js", "sha8=" + PS.sha8("synthwallet")), ("web/v2/u.js", "sha8=" + PS.sha8("acctalias9"))]),
    "[6] 일반 번호 라벨(config·owner_ids 둘 다)은 별명 대조 밖 · 고유 별명은 그대로 걸림", lab6)
put(D6, "src/t.py", "# 터널(cloudflared) · Cloudflared 설명\n# synthproj 이야기\n")
ids6["patterns"].append(("다른 프로젝트", PS.re.compile(r"(?i)synthproj|cloudflared")))
r6b = PS.scan(D6, owner, ids6, [], labels)
p6 = sorted((h[0], h[1], h[3]) for h in r6b["hits"] if h[2] == "다른 프로젝트")
chk(p6 == [("src/t.py", 2, "sha8=" + PS.sha8("synthproj"))], "[6] 오너 정규식의 공개 기술 낱말(cloudflared · 대소문자 무관)만 빠짐 · 같은 규칙의 다른 낱말은 걸림", p6)
T.finish()

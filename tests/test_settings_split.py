#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
MOVED = {
    "address_codec": ["_RC", "_ROT", "_M64", "_keccak_f", "keccak256", "to_checksum", "SOL_NOT_WALLET", "validate_address", "ADDR_SPLIT",
                      "split_addresses", "_SECRET_HEX64", "_WORD", "secret_like", "b58decode"],
    "runner_fp": ["_h", "unit_inputs", "WEB_HOT_TOP", "WEB_HOT_WALLET_FIELDS", "web_restart_view", "RUNNER_UNITS", "_nonevm_units",
                  "_nonevm_core_view", "_nonevm_chain_fp", "_nonevm_unit_inputs", "runner_units", "runner_status"],
    "settings_wallets": ["_label_ok", "wallet_list", "add_wallet", "MAX_ADDRESSES", "cap_error", "MAX_BATCH", "addr_key", "_addr_key", "_auto_label",
                         "add_wallets", "remove_wallet", "rename_wallet", "chain_wallet_list", "validate_chain_wallet", "_btc_hd_scripts",
                         "_BTC_NO_MOVE", "_btc_overlap", "add_chain_wallet", "_chain_wallet_match", "remove_chain_wallet", "rename_chain_wallet",
                         "MAX_PERP", "perp_list", "add_perp", "remove_perp"],
}
GONE = {n for ns in MOVED.values() for n in ns} | {"ENV_PATH", "_B58", "_HEX64"}
HAVE = all(os.path.isfile(os.path.join(T.SRC, m + ".py")) for m in ("settings_wallets", "runner_fp", "address_codec"))


def child(code, extra_env=None, base=None):
    base = base or os.path.join(T.TMP, "base_%d" % len(os.listdir(T.TMP)))
    os.makedirs(base, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": T.TMP, "TJ_BASE": base, "LANG": "C.UTF-8", "TZ": "UTC"}
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1])\n" + code, T.SRC, base],
                       capture_output=True, text=True, env=env, cwd=T.TMP, timeout=120)
    if p.returncode:
        return {"_err": (p.stderr or p.stdout)[-800:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


LOADED = r'''
import importlib, json, os, sys
sys.path.insert(0, sys.argv[1])
src = os.path.realpath(sys.argv[1])
importlib.import_module(sys.argv[3])
print(json.dumps(sorted(n for n, m in list(sys.modules.items()) if getattr(m, "__file__", None)
                        and os.path.dirname(os.path.realpath(m.__file__)) == src)))
'''


def loaded(mod):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": T.TMP, "TJ_BASE": T.TMP, "LANG": "C.UTF-8"}
    p = subprocess.run([sys.executable, "-I", "-B", "-c", LOADED, T.SRC, T.TMP, mod], capture_output=True, text=True, env=env, cwd=T.TMP, timeout=120)
    return json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else ["실패: " + p.stderr[-300:]]


def via_store(text):
    tree = ast.parse(text)
    alias = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names if a.name == "settings_store"}
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias and n.attr in GONE:
            out.append((n.lineno, "%s.%s" % (n.value.id, n.attr)))
        elif isinstance(n, ast.ImportFrom) and n.module == "settings_store" and any(a.name in GONE for a in n.names):
            out.append((n.lineno, "from settings_store import"))
        elif isinstance(n, ast.Call):
            fn = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")
            args = n.args
            if fn in ("getattr", "hasattr", "setattr", "delattr") and len(args) >= 2 and isinstance(args[0], ast.Name) \
                    and args[0].id in alias and isinstance(args[1], ast.Constant) and args[1].value in GONE:
                out.append((n.lineno, "%s(%s, %r)" % (fn, args[0].id, args[1].value)))
            elif fn in ("patch", "object") and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str) \
                    and args[0].value.startswith("settings_store.") and args[0].value.split(".", 1)[1] in GONE:
                out.append((n.lineno, "patch(%r)" % args[0].value))
    return out


if not HAVE:
    chk(True, "공개판 배치·4-4 전 트리 — 건너뜀")
    T.finish()

l_ac, l_ss, l_rf, l_sw, l_pd = (loaded(m) for m in ("address_codec", "settings_store", "runner_fp", "settings_wallets", "perp_dex"))
chk(l_ac == ["address_codec", "token_tables"], "S1 address_codec 만 = src 모듈 address_codec · token_tables 뿐(settings_store 안 실림 · 표준 라이브러리 + 데이터 표)", l_ac)
up = {"settings_wallets", "runner_fp", "perp_dex", "btc_descriptor", "btc_watch", "rabby", "nodekeys", "address_codec", "common", "chain_registry"}
chk("settings_store" in l_ss and not (set(l_ss) & up), "S1 settings_store 만 = 지갑·지문·퍼프·BTC·rabby·노드 키·주소 코덱·common 안 실림(끊긴 간선)",
    sorted(set(l_ss) & up))
chk("settings_store" in l_rf and "settings_store" in l_sw and "runner_fp" not in l_sw and "settings_wallets" not in l_rf,
    "S1 runner_fp · settings_wallets 는 settings_store 를 실음(위층 → 기반) · 서로 안 실음", (len(l_rf), len(l_sw)))
chk("settings_store" not in l_pd and "address_codec" in l_pd, "S1 perp_dex = address_codec 만(settings_store 안 실음 — 옛 순환 간선 끊김)", l_pd)

ADDR = r'''
import json, sys
import address_codec as ac
import token_tables
def v(a):
    try:
        return list(ac.validate_address(a))
    except ValueError as e:
        return "거부:" + str(e)
r = {}
r["evm_low"] = v("0x" + "ab" * 20)
r["evm_ck"] = v("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed")
r["evm_bad_ck"] = v("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD")
r["evm_zero"] = v("0x" + "0" * 40)
r["sol"] = v("9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")
r["sol_short"] = v("9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGY")
r["tron"] = v("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
pk = "4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
r["pk"] = v(pk)
r["pk0x"] = v("0x" + pk)
r["sol_secret"] = v("5" * 88)
import hashlib
def b58c(body):
    return ac.b58encode(body + hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4])
k32 = bytes(range(7, 39))   # 합성 개인 키 바이트(실제 키 아님)
r["wif"] = {"c": v(b58c(b"\x80" + k32 + b"\x01")), "u": v(b58c(b"\x80" + k32)), "t": v(b58c(b"\xef" + k32 + b"\x01")),
            "xprv": v(b58c(bytes.fromhex("0488ade4") + bytes(9) + k32 + b"\x00" + k32))}
r["wif_raw"] = [b58c(b"\x80" + k32 + b"\x01"), b58c(b"\x80" + k32)]
seed = "abandon ability able about above absent absorb abstract absurd abuse access accident"
r["seed_like"] = ac.secret_like([seed])
r["pk_split"] = ac.secret_like(["0x" + pk[:40], pk[40:]])
r["two_addrs"] = ac.secret_like(["0x" + "ab" * 20, "0x" + "cd" * 20])
r["not_wallet"] = {a: v(a) for a in ["11111111111111111111111111111111", "So11111111111111111111111111111111111111112",
                                      "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"] + sorted(token_tables.STABLE_MINTS)}
r["split"] = ac.split_addresses("0xa, 0xb；0xc\n0xd 、0xe")
r["keccak"] = [ac.keccak256(b"").hex(), ac.keccak256(b"transfer(address,uint256)").hex()[:8]]
r["ck"] = ac.to_checksum("0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed")
r["b58"] = [len(ac.b58decode("9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")), ac.b58encode(b"\x00\x01")]
r["mods"] = sorted(m for m in ("settings_store", "settings_wallets", "runner_fp", "common") if m in sys.modules)
print(json.dumps(r, ensure_ascii=False))
'''
r = child(ADDR)
chk("_err" not in r, "S2 주소 검증 새 프로세스 실행", r.get("_err"))
if "_err" not in r:
    chk(r["mods"] == [], "S2 settings_store · settings_wallets · runner_fp · common 을 싣지 않은 프로세스", r["mods"])
    chk(r["evm_low"][:2] == ["evm", "0x" + "ab" * 20] and r["evm_ck"][:2] == ["evm", "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"]
        and r["evm_ck"][2] == "체크섬 확인됨" and r["sol"][0] == "sol",
        "S2 정상 주소 등록 형식(EVM 소문자 정규화 · 체크섬 확인 · Solana 그대로)", (r["evm_low"], r["evm_ck"], r["sol"]))
    chk(all(isinstance(r[k], str) and r[k].startswith("거부:") for k in ("evm_bad_ck", "evm_zero", "sol_short", "tron")),
        "S2 형식 오류 거부(체크섬 한 글자 · 0 주소 · 32바이트 아닌 Solana · 트론)", [r[k] for k in ("evm_bad_ck", "evm_zero", "sol_short", "tron")])
    sec = [r["pk"], r["pk0x"], r["sol_secret"]]
    chk(all(isinstance(x, str) and "개인 키" in x for x in sec) and not any("4c0883a6" in x for x in sec),
        "S2 개인 키(16진수 64자 · 0x 붙임 · Solana 비밀 키 88자) = 경고 문구로 거부 · 문구에 입력 값 없음", sec)
    wif9 = r["wif"]
    chk(all(isinstance(x, str) and x.startswith("거부:") and "개인 키" in x and "주소가 아닙니다" not in x for x in wif9.values())
        and not any(raw9 in x for raw9 in r["wif_raw"] for x in wif9.values()),
        "S2 EVM/SOL 칸에 비트코인 개인 키(WIF 압축·비압축·테스트넷 · xprv) = '주소 아님' 대신 개인 키 경고로 거부 · 문구에 입력 값 없음", wif9)
    chk("시드" in r["seed_like"] and "개인 키" in r["pk_split"] and r["two_addrs"] == "",
        "S2 secret_like: 시드 12단어 · 쪼갠 개인 키(묶음 전체) 잡음 · 정상 주소 둘은 통과", (r["seed_like"][:20], r["pk_split"][:20], r["two_addrs"]))
    chk(len(r["not_wallet"]) >= 5 and all(str(x).startswith("거부:지갑 주소가 아니에요") for x in r["not_wallet"].values()),
        "S2 SOL_NOT_WALLET: 프로그램 주소 · token_tables.STABLE_MINTS 전부 거부", r["not_wallet"])
    chk(r["split"] == ["0xa", "0xb", "0xc", "0xd", "0xe"], "S2 split_addresses(쉼표·전각 세미콜론·줄바꿈·、)", r["split"])
    chk(r["keccak"] == ["c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", "a9059cbb"]
        and r["ck"] == "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed" and r["b58"] == [32, "12"],
        "S2 keccak256 · to_checksum(EIP-55) · b58 알려진 값", (r["keccak"], r["ck"], r["b58"]))

PERP = r'''
import json, sys
import perp_dex
def v(d, a):
    try:
        return list(perp_dex.validate_address(d, a))
    except ValueError as e:
        return "거부:" + str(e)
pk = "4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
print(json.dumps({"evm": v("hyperliquid", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"), "evm_sol": v("hyperliquid", "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"),
                  "pk": v("hyperliquid", "0x" + pk), "nw": v("hyperliquid", "So11111111111111111111111111111111111111112"),
                  "ss": "settings_store" in sys.modules}, ensure_ascii=False))
'''
r = child(PERP)
chk("_err" not in r and r["evm"][0] == "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed" and "EVM 주소" in r["evm_sol"]
    and "개인 키" in r["pk"] and "지갑 주소가 아니에요" in r["nw"] and r["ss"] is False,
    "S2 perp_dex.validate_address = 지갑과 같은 검증(정상 · 종류 다름 · 개인 키 · 지갑 아닌 주소) · settings_store 안 실림", r)

MUT = [("import settings_store as ss\nss.add_wallet(1)\n", 1), ("def f():\n    import settings_store\n    return settings_store.unit_inputs('x')\n", 1),
       ("def g():\n    from settings_store import MAX_ADDRESSES\n", 1), ("import settings_store as S9\nhasattr(S9, 'unit_inputs')\n", 1),
       ("from unittest import mock\nmock.patch('settings_store.runner_status')\n", 1), ("import settings_store as ss\nss.ENV_PATH = 'x'\n", 1),
       ("import settings_store as ss\nss.read_env(), ss.LOCK\n", 0), ("import runner_fp\nrunner_fp.unit_inputs('x')\n", 0)]
chk(all(len(via_store(t)) == n for t, n in MUT), "S3 조사기 변이: 별칭·함수 안 import·from import·hasattr 글자·patch 글자·ENV_PATH 대입 = 잡음 · 남은 이름·새 모듈 = 안 잡음",
    [(t[:30], via_store(t)) for t, n in MUT if len(via_store(t)) != n])
LEFT = r'''
import json, sys
import settings_store
print(json.dumps(sorted(n for n in json.loads(sys.argv[3]) if hasattr(settings_store, n))))
'''
env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": T.TMP, "TJ_BASE": T.TMP, "LANG": "C.UTF-8"}
p = subprocess.run([sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1])\n" + LEFT, T.SRC, T.TMP, json.dumps(sorted(GONE))],
                   capture_output=True, text=True, env=env, cwd=T.TMP, timeout=120)
chk(p.returncode == 0 and p.stdout.strip().splitlines()[-1] == "[]", "S3 settings_store 에 옮긴 이름·ENV_PATH·옛 사본(_B58·_HEX64) 없음(대리 없음 — 옛 이름 = AttributeError)",
    (p.stdout[-300:], p.stderr[-300:]))
hits, me = [], os.path.abspath(__file__)
for top in ("src", "tools", os.path.join("public", "tests"), "tests"):
    d0 = os.path.join(T.ROOT, top)
    for dp, dns, fns in os.walk(d0):
        dns[:] = [x for x in dns if x not in ("__pycache__", "dev", "node_modules")]
        for fn in fns:
            fp = os.path.join(dp, fn)
            if fn.endswith(".py") and os.path.abspath(fp) != me:
                try:
                    with open(fp, encoding="utf-8") as f:
                        txt = f.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if "settings_store" in txt:
                    hits += ["%s:%d %s" % (os.path.relpath(fp, T.ROOT), ln, how) for ln, how in via_store(txt)]
chk(not hits, "S3 옮긴 이름·ENV_PATH 를 settings_store 경유로 부르는 곳 0(src·tools·tests 전수)", hits[:10])

FREE = r'''
import builtins, dis, importlib, json, sys, types
out = []
for name in ("settings_store", "address_codec", "settings_wallets", "runner_fp"):
    m = importlib.import_module(name)
    def codes(co):
        yield co
        for c in co.co_consts:
            if isinstance(c, types.CodeType):
                yield from codes(c)
    for k, v in list(vars(m).items()):
        if isinstance(v, types.FunctionType) and v.__module__ == name:
            for co in codes(v.__code__):
                for ins in dis.get_instructions(co):
                    if ins.opname == "LOAD_GLOBAL":
                        g = ins.argval if isinstance(ins.argval, str) else str(ins.argval)
                        g = g.split(" + ")[-1].replace("NULL + ", "")
                        if g not in vars(m) and not hasattr(builtins, g):
                            out.append("%s.%s → %s" % (name, k, g))
print(json.dumps(sorted(set(out))))
'''
r = child(FREE)
chk(r == [], "S4 settings_store · address_codec · settings_wallets · runner_fp 함수가 모듈에 없는 전역 이름을 읽는 곳 0(LOAD_GLOBAL)", r)

ENVC = r'''
import json, os, sys
base = sys.argv[2]
with open(os.path.join(base, ".env"), "w") as f:
    f.write("TJ_SPLIT_A=one\n")
import settings_store            # 먼저 싣는다(사본이 있으면 여기서 굳음)
import paths, chk_sources
r = {"first": settings_store.read_env().get("TJ_SPLIT_A"), "env_value": settings_store.env_value("TJ_SPLIT_A")}
other = os.path.join(base, "other.env")
with open(other, "w") as f:
    f.write("TJ_SPLIT_A=two\n")
orig = paths.ENV_PATH
paths.ENV_PATH = other
r["other"] = [settings_store.read_env().get("TJ_SPLIT_A"), settings_store.env_value("TJ_SPLIT_A")]
settings_store.write_env({"TJ_SPLIT_B": "w"})
r["wrote_other"] = "TJ_SPLIT_B=w" in open(other).read() and "TJ_SPLIT_B" not in open(orig).read()
d = os.path.join(base, "env_is_dir")
os.makedirs(d, exist_ok=True)
paths.ENV_PATH = d
r["dir_read"] = settings_store.read_env()
r["dir_upbit"] = chk_sources.upbit_connected()
try:
    settings_store.write_env({"TJ_SPLIT_C": "x"})
    r["dir_write"] = "썼음"
except OSError as e:
    r["dir_write"] = type(e).__name__
paths.ENV_PATH = other            # 다시 대입(4-6: 대리 common 지움 — 같은 대입을 정의 모듈에 직접)
r["proxy"] = [paths.ENV_PATH == other, settings_store.read_env().get("TJ_SPLIT_A")]
paths.ENV_PATH = orig
r["back"] = settings_store.read_env().get("TJ_SPLIT_A")
r["orig_text"] = open(orig).read()
print(json.dumps(r, ensure_ascii=False))
'''
r = child(ENVC)
chk("_err" not in r and r["first"] == "one" and r["env_value"] == "one" and r["other"] == ["two", "two"] and r["wrote_other"] is True,
    "S5 settings_store 를 먼저 실은 뒤 paths.ENV_PATH 대입 = read_env · env_value · write_env 가 새 경로(옛 .env 안 건드림)", r)
if "_err" not in r:
    chk(r["dir_read"] == {} and r["dir_upbit"] is True and r["dir_write"] == "IsADirectoryError",
        "S5 .env 자리가 디렉터리(못 읽음) = read_env 빈 값 · upbit_connected 모름 → 있음 · write_env 거부(OSError)", (r["dir_read"], r["dir_upbit"], r["dir_write"]))
    chk(r["proxy"] == [True, "two"] and r["back"] == "one" and r["orig_text"] == "TJ_SPLIT_A=one\n",
        "S5 paths.ENV_PATH 다시 대입도 settings_store 가 따라감 · 되돌리면 원래 .env · 원래 .env 글 그대로", (r["proxy"], r["back"], r["orig_text"]))

DEMO = r'''
import json, os, sys
base = sys.argv[2]
import settings_store, paths
settings_store.write_env({"TJ_SPLIT_DEMO": "d"})
st = os.environ.get("TJ_DEMO_STATE")
print(json.dumps({"isolated": paths.DEMO_ISOLATED, "decoy": settings_store.env_value("TJ_SPLIT_REAL"), "env_in_state": paths.ENV_PATH.startswith(st or "?"),
                  "demo_env": open(os.path.join(st, ".env")).read().strip().splitlines()[-1], "real": open(os.path.join(base, ".env")).read()}))
'''
db = os.path.join(T.TMP, "demo_base")
dst = os.path.join(T.TMP, "demo_state")
os.makedirs(db, exist_ok=True)
os.makedirs(dst, exist_ok=True)
with open(os.path.join(db, ".env"), "w", encoding="utf-8") as f:
    f.write("TJ_SPLIT_REAL=real\n")
r = child(DEMO, {"TJ_DEMO": "1", "TJ_DEMO_STATE": dst}, base=db)
chk("_err" not in r and r["isolated"] is True and r["decoy"] == "" and r["env_in_state"] is True and r["demo_env"] == "TJ_SPLIT_DEMO=d"
    and r["real"] == "TJ_SPLIT_REAL=real\n",
    "S6 데모 격리: 설치 뿌리 .env 키 안 읽음 · write_env = 데모 state 의 .env 에만(rebase 없이 paths.ENV_PATH 그대로)", r)
T.finish()

#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

os.environ["TJ_HEALTH"] = "0"
import paths  # noqa: E402
import settings_wallets as SW  # noqa: E402
import chainoff as CO  # noqa: E402

chk = T.chk
W1 = "0x" + "d1" * 20
W2 = "0x" + "d2" * 20
W3 = "0x" + "d3" * 20
NR = "https://bsc-mainnet.nodereal.io/v1/" + "k1" * 8
UNK = {
    "zz_top_first": {"keep": [1, 2, {"x": "가"}], "n": 1.5},
    "zz_top_last": "끝 글자",
    "chains.eth.zz_sub": {"deep": [True, None]},
    "chains.robinhood.zz_sub": 7,
    "web.zz_web": [3, "w"],
    "wallets.0.zz_wcell": {"c": 1},
}


def base_cfg():
    return {
        "zz_top_first": {"keep": [1, 2, {"x": "가"}], "n": 1.5},
        "chains": {"eth": {"blockscout": "https://eth.invalid", "rpcs": ["https://eth-rpc.invalid"], "zz_sub": {"deep": [True, None]}},
                   "scroll": {"blockscout": "https://scroll.invalid", "rpcs": ["https://scroll-rpc.invalid"], "enabled": False},
                   "robinhood": {"rpcs": ["https://rh-rpc.invalid"], "zz_sub": 7},
                   "base": {"rpcs": ["https://base-rpc.invalid"]}},
        "wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "가", "zz_wcell": {"c": 1}},
                    {"type": "evm", "chain": "scroll", "address": W1, "label": "가"}],
        "web": {"port": 8023, "zz_web": [3, "w"]},
        "bsc": {"logs_rpcs": ["https://bsc.invalid", NR]},
        "sol": {"rpc": "https://sol.invalid"},
        "native_symbol": {"eth": "ETH"},
        "zz_top_last": "끝 글자",
    }


def _get(d, dotted):
    cur = d
    for part in dotted.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)] if part.isdigit() and int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part, KeyError)
        else:
            return KeyError
        if cur is KeyError:
            return KeyError
    return cur


def write_cfg(path, cfg, indent=2):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=indent) + "\n")
    return open(path, "rb").read()


def verify(name, path, before_bytes, indent, keep_wallet0=True):
    after = open(path, "rb").read()
    chk(after != before_bytes, "[1] %s: 실제로 씀(바이트 바뀜)" % name)
    try:
        new = json.loads(after.decode("utf-8"))
    except ValueError as e:
        chk(False, "[1] %s: JSON 읽힘" % name, e)
        return
    old = json.loads(before_bytes.decode("utf-8"))
    lost = []
    for k, v in UNK.items():
        if k.startswith("wallets.") and not keep_wallet0:
            continue
        if _get(new, k) != v:
            lost.append(k)
    chk(not lost, "[1] %s: 모르는 키·칸 값 그대로" % name, lost)
    order = [k for k in new if k in old]
    chk(order == list(old), "[1] %s: 원래 최상위 키 차례 그대로" % name, (list(old), list(new)))
    lines = after.decode("utf-8").split("\n")
    got = len(lines[1]) - len(lines[1].lstrip(" ")) if len(lines) > 1 else -1
    chk(got == indent, "[1] %s: 들여쓰기 %d(지금 동작)" % (name, indent), got)


CP = paths.CONFIG_PATH
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
_pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))


def have(rel, name):
    if os.path.isfile(os.path.join(T.ROOT, rel)):
        return True
    chk(_pub, "[1] %s: 파일 없음(공개판 배치만 건너뜀)" % name)
    return False


chk(CP.startswith(T.TMP), "준비: 설정 경로 = 임시 폴더")

btc = None
cases = [
    ("settings_wallets.add_wallet", lambda: SW.add_wallet(W2, "나", ["eth"])),
    ("settings_wallets.add_wallets", lambda: SW.add_wallets([W3], ["eth"])),
    ("settings_wallets.rename_wallet", lambda: SW.rename_wallet(W1, "새 이름")),
    ("settings_wallets.add_chain_wallet", lambda: SW.add_chain_wallet("btc", N.BTC_ADDR, "비트")),
    ("settings_wallets.add_perp", lambda: SW.add_perp("hyperliquid", W2, "퍼프")),
]
for name, fn in cases:
    b0 = write_cfg(CP, base_cfg())
    try:
        r = fn()
        if name.endswith("add_chain_wallet"):
            btc = r
    except Exception as e:   # noqa: BLE001 [probe]
        chk(False, "[1] %s: 호출 성공" % name, repr(e))
        continue
    verify(name, CP, b0, 2)

for name, prep, fn in (
        ("settings_wallets.remove_wallet", lambda: SW.add_wallet(W2, "나", ["eth"]), lambda: SW.remove_wallet(W2)),
        ("settings_wallets.rename_chain_wallet", lambda: SW.add_chain_wallet("btc", N.BTC_ADDR, "비트"),
         lambda: SW.rename_chain_wallet("btc", btc["key"] if btc else N.BTC_ADDR, "비트 둘")),
        ("settings_wallets.remove_chain_wallet", lambda: SW.add_chain_wallet("btc", N.BTC_ADDR, "비트"),
         lambda: SW.remove_chain_wallet("btc", btc["key"] if btc else N.BTC_ADDR)),
        ("settings_wallets.remove_perp", lambda: SW.add_perp("hyperliquid", W2, "퍼프"), lambda: SW.remove_perp("hyperliquid", W2))):
    write_cfg(CP, base_cfg())
    try:
        prep()
        b0 = open(CP, "rb").read()
        n = fn()
        chk(n, "[1] %s: 대상 찾음" % name, n)
    except Exception as e:   # noqa: BLE001 [probe]
        chk(False, "[1] %s: 호출 성공" % name, repr(e))
        continue
    verify(name, CP, b0, 2)

b0 = write_cfg(CP, base_cfg())
try:
    res = CO.set_enabled("scroll", True)
    chk(res.get("changed") is True, "[1] chainoff.set_enabled: 꺼진 체인 켬 = 바뀜", res)
except Exception as e:   # noqa: BLE001 [probe]
    chk(False, "[1] chainoff.set_enabled: 호출 성공", repr(e))
verify("chainoff.set_enabled", CP, b0, 2)


def run_tool(rel, args, tmp, env_extra=None, cwd=None, stdin=None):
    env = dict(os.environ, TJ_BASE=tmp, TJ_CONFIG=os.path.join(tmp, "config.json"), TJ_HEALTH="0")
    env.pop("pm_id", None)
    env.update(env_extra or {})
    cmd = [sys.executable, "-I", "-B"] + ([os.path.join(T.ROOT, rel)] if rel else ["-"]) + list(args)
    p = subprocess.run(cmd, env=env, cwd=cwd or tmp, input=stdin, capture_output=True, text=True, timeout=180)
    return p


def fresh_dir(name):
    d = os.path.join(T.TMP, "w_" + name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(os.path.join(d, "state"))
    return d


TOOL_CASES = (
    ("tools/allchains_enable", "tools/allchains_enable.py", ["--apply"], (2, 4)),
    ("tools/robinhood_rpc_enable", "tools/robinhood_rpc_enable.py", ["--apply"], (2, 4)),
)
for name, rel, args, indents in TOOL_CASES:
    if not have(rel, name):
        continue
    for ind in indents:
        d = fresh_dir(name.split("/")[-1] + str(ind))
        cp = os.path.join(d, "config.json")
        b0 = write_cfg(cp, base_cfg(), ind)
        p = run_tool(rel, [cp] + args, d)
        chk(p.returncode == 0, "[1] %s(들여쓰기 %d): 종료 코드 0" % (name, ind), (p.stdout + p.stderr)[-500:])
        verify("%s(들여쓰기 %d)" % (name, ind), cp, b0, ind)
if have("tools/allchains_enable.py", "tools/allchains_enable(--seed-gate 무동작)"):
    d = fresh_dir("allchains_seedgate")
    cp = os.path.join(d, "config.json")
    b0 = write_cfg(cp, base_cfg())
    p = run_tool("tools/allchains_enable.py", [cp, "--apply", "--seed-gate", os.path.join(d, "state")], d)
    chk(p.returncode == 0 and "무동작" in p.stdout and not os.path.exists(os.path.join(d, "state", "chain_activity.json")),
        "[1] tools/allchains_enable --seed-gate = 무동작 안내 · 게이트 파일 안 만듦(운영 쌍 상수 없음)", (p.stdout + p.stderr)[-500:])
    verify("tools/allchains_enable(--seed-gate)", cp, b0, 2)
if have("tools/migrate_nodekeys_1008.py", "tools/migrate_nodekeys(노드 키 옮기기)"):
    d = fresh_dir("migrate_nodekeys")
    cp = os.path.join(d, "config.json")
    b0 = write_cfg(cp, base_cfg())
    p = run_tool("tools/migrate_nodekeys_1008.py", ["--apply"], d)
    chk(p.returncode == 0 and NR not in open(cp, encoding="utf-8").read(), "[1] tools/migrate_nodekeys(노드 키 옮기기): 종료 코드 0 · 노드 주소 빠짐",
        (p.stdout + p.stderr)[-500:])
    verify("tools/migrate_nodekeys(노드 키 옮기기)", cp, b0, 2)


CW = None
if os.path.isfile(os.path.join(TOOLS, "cfg_writers.py")):
    sys.path.insert(0, TOOLS)
    import cfg_writers as CW  # noqa: E402
else:
    chk(_pub, "공개판 배치 — 비공개 도구(cfg_writers) 없음 · 셸 조각·정적 탐지 건너뜀" if _pub else "저장소 배치인데 tools/refactor/cfg_writers.py 없음")


SH_CASES = (
    ("배포 셸 설정 병합 조각", "tools/deploy_final_20260926.sh", r"MODE_CM=.*CFG=.*<<'PY'", lambda cp: [],
     {"MODE_CM": "apply"}, (2, 4), True),
    ("발견 이중화 배포 조각", "tools/deploy_bprime_shadow.sh", r"^python3 - <<'EOF'", lambda cp: [], {}, (1,), True),
    ("발견 이중화 롤백 조각", "tools/rollback_bprime.sh", r"^python3 - <<'EOF'", lambda cp: [], {}, (1,), True),
)
for name, rel, head_re, argf, envx, indents, keep_w in (SH_CASES if CW else ()):
    if not have(rel, name):
        continue
    code = CW.heredoc(os.path.join(T.ROOT, rel), head_re)
    chk(code is not None, "[1] %s: 조각 하나 뽑음" % name)
    if code is None:
        continue
    for ind in indents:
        d = fresh_dir(re.sub(r"\W", "_", name) + str(ind))
        cp = os.path.join(d, "config.json")
        cfg = base_cfg()
        if name == "발견 이중화 롤백 조각":
            cfg["chains"]["base"].update(rpc_log_discovery="shadow", chain_id=8453)
        b0 = write_cfg(cp, cfg, 2 if ind == 1 else ind)
        p = run_tool(None, argf(cp), d, dict(envx, CFG=cp), cwd=d, stdin=code)
        chk(p.returncode == 0, "[1] %s: 종료 코드 0" % name, (p.stdout + p.stderr)[-500:])
        verify("%s(원래 %d)" % (name, 2 if ind == 1 else ind), cp, b0, ind, keep_w)

COVERED_PY = {
    "src/chainoff.py:set_enabled", "src/settings_store.py:write_config_raw",
    "src/settings_wallets.py:add_wallet", "src/settings_wallets.py:add_wallets", "src/settings_wallets.py:remove_wallet",
    "src/settings_wallets.py:rename_wallet", "src/settings_wallets.py:add_chain_wallet", "src/settings_wallets.py:remove_chain_wallet",
    "src/settings_wallets.py:rename_chain_wallet", "src/settings_wallets.py:add_perp", "src/settings_wallets.py:remove_perp",
    "tools/allchains_enable.py:main", "tools/migrate_nodekeys_1008.py:main",
    "tools/robinhood_rpc_enable.py:<module>",
}
NOT_WRITER_PY = {
    "src/health.py:_eval_feeds": "설정 글자는 안내 문구 · 쓰기는 상태 파일",
    "src/ledger_backup.py:backup_files": "설정 일부(지갑 목록)를 백업 폴더에 복사 — config.json 은 안 씀",
    "src/paths.py:<module>": "경로 정의만",
    "src/settings_store.py:update_settings": "설정 잠금 안에서 state/settings.json 을 씀",
    "src/settings_store.py:csrf_token": "설정 잠금 안에서 CSRF 토큰 상태 파일을 씀",
    "src/settings_store.py:rotate_csrf_token": "설정 잠금 안에서 CSRF 토큰 상태 파일을 씀",
    "src/settings_store.py:write_env": "설정 잠금 안에서 .env 를 씀(config.json 아님)",
    "src/wallet_register.py:_record_reload": "설정 잠금 안에서 state/wallet_reload.json 을 씀",
    "tools/repair_partial_legs.py:main": "설정은 읽기만 · 캐시·보고 파일을 씀",
}
COVERED_SH = {"tools/deploy_final_20260926.sh", "tools/deploy_bprime_shadow.sh", "tools/rollback_bprime.sh"}
NOT_WRITER_SH = {
    "tools/cutover_c.sh": "업비트 대사 조각 — 설정은 안 씀(원장·상태)",
    "tools/verify_audit_20260909.sh": "설정은 읽기만(API 주소 계산)",
}
if CW is None:
    T.finish()
found_py = CW.py_writers(T.ROOT)
new_py = sorted(found_py - COVERED_PY - set(NOT_WRITER_PY))
chk(not new_py, "[2] 새 config 작성자(파이썬) 0 — 보존 시험에 넣거나 '안 씀' 표에 이유", new_py)
stale_py = sorted((COVERED_PY | set(NOT_WRITER_PY)) - found_py)
chk(not stale_py, "[2] 표에 낡은 자리 없음(파이썬)", stale_py)
chk(not (COVERED_PY & set(NOT_WRITER_PY)), "[2] 표 겹침 0")

counts_sh = CW.sh_writer_counts(T.ROOT)
found_sh = set(counts_sh)
for rel, n in sorted(counts_sh.items()):
    expected = sum(1 for case in SH_CASES if case[1] == rel) + int(rel in NOT_WRITER_SH)
    chk(n == expected, "[2] 셸 파일의 작성자 후보 조각 수 = 덮음·안 씀 표(같은 파일에 새 조각이 늘어도 실패): %s" % rel, (n, expected))
new_sh = sorted(found_sh - COVERED_SH - set(NOT_WRITER_SH))
chk(not new_sh, "[2] 새 config 작성자(셸 안 파이썬) 0", new_sh)
stale_sh = sorted((COVERED_SH | set(NOT_WRITER_SH)) - found_sh)
chk("tools/deploy_hotfix_20260928t.sh" not in counts_sh,
    "[2] 배포 셸 t = config 쓰는 파이썬 조각 0(세션23 x27 지움 — 운영 지갑 주소 상수 든 1회 등록 단계가 되살아나면 실패)", counts_sh.get("tools/deploy_hotfix_20260928t.sh"))
chk(not stale_sh, "[2] 표에 낡은 자리 없음(셸)", stale_sh)
chk(len(found_py) >= 16 and len(found_sh) >= 4, "[2] 탐지가 실제로 돎(알려진 작성자 수 이상)", (len(found_py), len(found_sh)))
T.finish()

#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import config, paths, statefile  # noqa: E402

chk = T.chk
W1 = "0x" + "b1" * 20
W2 = "0x" + "b2" * 20
W3 = "0x" + "b3" * 20
SLOW = {"getLogsSpan": 1000, "blocksPerSec": 1.0, "windowCalls": 999999, "autoOk": False}
FAST = {"getLogsSpan": 1000, "blocksPerSec": 1.0, "windowCalls": 10, "autoOk": True}
CFG = {"chains": {"eth": {"blockscout": "https://eth.invalid", "rpcs": ["https://eth-rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "가"},
                   {"type": "evm", "chain": "eth", "address": W2, "label": "나"},
                   {"type": "evm", "chain": "eth", "address": W3, "label": "다"}],
       "chain_sweep": {"enabled": True, "auto_enable": True}}


def cur_path(c):
    return os.path.join(paths.STATE_DIR, f"cursor_evm_{c}.json")


def write_cur(c, body):
    with open(cur_path(c), "w", encoding="utf-8") as f:
        f.write(body if isinstance(body, str) else json.dumps(body))


def dec(gate, speed):
    return {(d["chain"], d["addr"]): d for d in config.gate_decisions(CFG, gate, speed)}


gate = {"version": 1, "pairs": {f"zerog:{W1}": {"active": True, "since_block": None},
                                f"zerog:{W2}": {"active": True, "since_block": None},
                                f"blast:{W1}": {"active": True, "since_block": None},
                                f"celo:{W3}": {"active": True, "since_block": None}}}
speed = {"version": 1, "chains": {"zerog": SLOW, "blast": SLOW, "celo": SLOW}}
write_cur("zerog", {"_rpc_v": 3, "_start": 100, W1.upper().replace("0X", "0x"): 120, "_bk:" + W2: {"from": 1, "to": 2, "done": 1}})
write_cur("blast", "{깨진")
write_cur("celo", {"_start": 100, "_synced_at": 1, "0x" + "c9" * 20: 150})
d = dec(gate, speed)
z1 = d[("zerog", W1)]
chk(z1["ok"] and isinstance(z1["block"], dict) and z1["block"].get("_auto") == "generic" and z1["reason"] == "이미 수집 중 — 켠 채로 유지",
    "A 커서에 그 지갑 키(대문자 키도) + autoOk 거짓 = 켬(범용 RPC 블록 · 짧은 사유)", (z1["ok"], z1["reason"]))
z2 = d[("zerog", W2)]
chk(not z2["ok"] and z2["block"] is None and z2["reason"].startswith("창 백필 비용 과다"),
    "A 같은 체인 다른 지갑 — 커서엔 '_' 접두 키(_bk:지갑)만 = 처음 켤 때 규칙 그대로 안 켬", z2["reason"])
b1 = d[("blast", W1)]
chk(b1["ok"] and b1["reason"] == "이미 수집 중 — 켠 채로 유지", "A 커서 파일 손상 = 수집한 것으로 = 켬", b1["reason"])
m3 = d[("celo", W3)]
chk(not m3["ok"] and m3["reason"].startswith("창 백필 비용 과다"), "A 커서에 다른 지갑 키만 = 안 켬(종전)", m3["reason"])
os.remove(cur_path("zerog"))
d = dec(gate, speed)
chk(not d[("zerog", W1)]["ok"] and d[("zerog", W1)]["reason"].startswith("창 백필 비용 과다"),
    "A 커서 파일 없음 + autoOk 거짓 = 종전 그대로 안 켬", d[("zerog", W1)]["reason"])

d = dec(gate, {"version": 1, "chains": {"zerog": FAST, "blast": SLOW, "celo": SLOW}})
chk(d[("zerog", W1)]["ok"] and d[("zerog", W1)]["reason"] == "generic", "B autoOk 참 = 커서 없어도 켬(사유 종전 generic)", d[("zerog", W1)]["reason"])
g2 = {"version": 1, "pairs": {f"zerog:{W1}": {"active": True, "since_block": 50, "since_state": [0, "0"]}}}
d = dec(g2, speed)
chk(d[("zerog", W1)]["ok"] and d[("zerog", W1)]["reason"] == "generic", "B since 앎 = autoOk 거짓이어도 켬(종전)", d[("zerog", W1)]["reason"])
write_cur("zerog", {"_start": 100, W1: 120})
d = dec(gate, {"version": 1, "chains": {"zerog": {"autoOk": False}}})
chk(not d[("zerog", W1)]["ok"] and d[("zerog", W1)]["reason"].startswith("실측 없음"),
    "B 실측 없음(구간·속도 없음) = 커서 있어도 안 켬(종전 · 이번 범위 밖)", d[("zerog", W1)]["reason"])

with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
statefile.atomic_write_json(paths.ACTIVITY_GATE_PATH, gate)
statefile.atomic_write_json(paths.BACKFILL_SPEED_PATH, speed)
write_cur("zerog", {"_rpc_v": 3, "_start": 100, W1: 120})
os.remove(cur_path("blast"))
c1 = config.load_config()
zw = sorted(w["address"] for w in c1["wallets"] if w.get("chain") == "zerog")
chk("zerog" in c1["chains"] and zw == [W1] and c1["chains"]["zerog"].get("discovery") == "rpc",
    "C load_config: 수집한 쌍만 지갑 행으로 합류(체인 블록 RPC 전용) · 처음 보는 쌍은 빠짐", (sorted(c1["chains"]), zw))
chk("blast" not in c1["chains"] and "celo" not in c1["chains"], "C 커서 없는·다른 지갑 커서 체인 = 안 켬(종전)", sorted(c1["chains"]))
CFG_OFF = dict(CFG, chains=dict(CFG["chains"], zerog={"enabled": False, "_chainoff": {"at": 1, "created": True}}))
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG_OFF, f)
c2 = config.load_config()
kept = sorted((w.get("chain"), w.get("address")) for w in c2.get("_disabled_wallets") or [])
chk("zerog" not in c2["chains"] and not [w for w in c2["wallets"] if w.get("chain") == "zerog"] and kept == [("zerog", W1)],
    "C 끈 체인 = 수집 안 함 · 수집한 쌍은 기장 관점(_disabled_wallets)에 남음", kept)

T.finish()

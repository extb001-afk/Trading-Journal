#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths, statefile  # noqa: E402
import health  # noqa: E402
import chain_registry as reg  # noqa: E402
import address_codec as ac  # noqa: E402

NOW = time.time()
S = paths.STATE_DIR
W = "0x" + "a1" * 20
A = N.OWN["tron"][0]
reg.FORCE_AVAILABLE.add("tron")
os.makedirs(os.path.join(T.TMP, "logs"), exist_ok=True)
PROBES = {"inbox": lambda: {}, "disk": lambda: {"free": 100 * 10 ** 9, "total": 200 * 10 ** 9}, "web": lambda: None, "tunnel": lambda: None}
OLD_UNITS = ["tj-evm", "tj-sol", "tj-bsc", "tj-core", "tj-web", "tj-alert", "tj-ex", "tj-exf"]


def write_cfg(tron=True, health_cfg=None):
    cfg = {"chains": {"eth": {"blockscout": "https://bs.invalid", "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W}]}
    if tron:
        cfg["chain_wallets"] = [{"chain": "tron", "network": "mainnet", "address": ac.tron_display(A), "label": "트론 1"}]
    if health_cfg:
        cfg["health"] = health_cfg
    json.dump(cfg, open(paths.CONFIG_PATH, "w"))
    statefile.atomic_write_json(os.path.join(S, "cursor_evm_eth.json"), {W: 100, "_synced_at": NOW - 30})


def run(pm2_units):
    c = config.load_config()
    h = health.settings(c)
    h["log_dir"] = os.path.join(T.TMP, "logs")
    pm2 = None if pm2_units is None else {u: {"status": "online", "restarts": 0, "pid": 100 + i, "uptime": NOW - 5000, "out": None, "err": None,
                                              "mem": 50 << 20} for i, u in enumerate(pm2_units)}
    m = health.Monitor(probes=dict(PROBES, pm2=lambda: pm2))
    obs = m.observe(c, h, NOW, False)
    return {x["id"]: x for x in health.evaluate(obs, h)}


write_cfg()
cs = run(OLD_UNITS)
p = cs.get("proc:tj-tron") or {}
T.chk(p.get("level") == "warn" and "pm2 save" in (p.get("action") or "") and "없" in (p.get("title") or ""),
      "CU1 Tron 지갑 있음 + pm2 목록에 tj-tron 없음 = proc:tj-tron 주의 · 조치에 pm2 save", p)
T.chk(p.get("unit") == "tj-tron" and p.get("kind") == "proc", "CU1 점검 단위·종류 = 그 유닛 프로세스 점검(종전 proc 규약)", p)
cs = run(OLD_UNITS + ["tj-tron"])
p = cs.get("proc:tj-tron") or {}
T.chk(p.get("level") == "ok", "CU2 pm2 목록에 tj-tron 있음 = 정상(종전 그대로)", p)
write_cfg(tron=False)
cs = run(OLD_UNITS)
T.chk("proc:tj-tron" not in cs and not any(k.endswith("tj-tron") for k in cs), "CU3 Tron 지갑 없음 = tj-tron 점검 없음(종전 그대로)",
      sorted(k for k in cs if "tron" in k))
write_cfg(tron=True, health_cfg={"tunnel": {"unit": "my-tunnel", "ready_url": "http://127.0.0.1:9/ready"}})
cs = run(OLD_UNITS)
T.chk("proc:my-tunnel" not in cs and (cs.get("proc:tj-tron") or {}).get("level") == "warn",
      "CU3 다른 선택 유닛(터널)은 pm2 에 없어도 조용(종전) · 체인 유닛만 주의", (cs.get("proc:my-tunnel"), cs.get("proc:tj-tron")))
write_cfg()
cs = run(None)
p = cs.get("proc:tj-tron") or {}
T.chk(p.get("level") == "warn", "CU4 pm2 없음 + 러너 기록 없음 + Tron 지갑 있음 = 주의(수집기를 안 켬)", p)
write_cfg(tron=True, health_cfg={"ignore_units": ["tj-tron"]})
cs = run(OLD_UNITS)
T.chk("proc:tj-tron" not in cs, "CU5 ignore_units 의 체인 유닛 = 점검 안 함(종전)", cs.get("proc:tj-tron"))
reg.FORCE_AVAILABLE.discard("tron")
T.finish()

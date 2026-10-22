#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import time  # noqa: E402

import config, paths, statefile  # noqa: E402
import chk_logs  # noqa: E402
import health  # noqa: E402

S = paths.STATE_DIR
NOW = time.time()
OTHER = os.path.join(T.TMP, "other_install")
os.makedirs(os.path.join(OTHER, "src"), exist_ok=True)
FAKE = os.path.join(T.TMP, "fakepm2.py")
JL = os.path.join(T.TMP, "jlist.json")
with open(FAKE, "w") as f:
    f.write("#!%s\nimport sys\nif sys.argv[1:2] == ['jlist']:\n    sys.stdout.write(open(%r).read())\n" % (sys.executable, JL))
os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IXUSR)


def ent(name, root, script="src/unit_runner.py", status="online"):
    e = {"status": status, "restart_time": 0, "pm_uptime": (NOW - 100) * 1000,
         "pm_out_log_path": os.path.join(T.TMP, "pm2home", "logs", name + "-out.log"),
         "pm_err_log_path": os.path.join(T.TMP, "pm2home", "logs", name + "-error.log")}
    if root is not None:
        e["pm_cwd"] = root
        e["pm_exec_path"] = script if os.path.isabs(script) else os.path.join(root, script)
    return {"name": name, "pid": 4242, "pm2_env": e, "monit": {"memory": 1 << 20}}


def jlist(items):
    json.dump(items, open(JL, "w"))


def run(items):
    jlist(items)
    h = {"pm2_bin": FAKE}
    return chk_logs.pm2_list(h), h


r, h = run([ent("tj-core", OTHER), ent("tj-evm", OTHER), ent("tj-web", OTHER)])
T.chk(r is None and h.get("pm2_foreign") is True, "[1] 다른 설치본 tj-* 만 = None · pm2_foreign 표식", (r, h))
r, h = run([ent("tj-core", OTHER), ent("tj-evm", OTHER), ent("tj-tunnel", "/opt", script="/usr/local/bin/cloudflared")])
T.chk(r is None and h.get("pm2_foreign") is True, "[1] 다른 설치본 tj-* + 터널(파이썬 아님)만 = None(터널만 남아도 pm2 없음으로)", (r, h))
r, h = run([])
T.chk(r is None and h.get("pm2_foreign") is True, "[1] pm2 목록 비었음(이 설치는 pm2 없이) = None", (r, h))
r, h = run([ent("tj-core", T.ROOT), ent("tj-evm", T.ROOT)])
T.chk(isinstance(r, dict) and set(r) == {"tj-core", "tj-evm"} and "pm2_foreign" not in h, "[1] 반대: 이 설치 유닛 = 종전 그대로", (r, h))

r, h = run([ent("tj-core", T.ROOT), ent("tj-evm", OTHER), ent("tj-tunnel", "/opt", script="/usr/local/bin/cloudflared"),
            ent("tj-sol", None)])
T.chk(isinstance(r, dict) and set(r) == {"tj-core", "tj-tunnel", "tj-sol"}, "[2] 섞임 = 이 설치 것만(터널·경로 없는 옛 항목은 그대로)", r)
LNK = os.path.join(T.TMP, "root_link")
os.symlink(T.ROOT, LNK)
r, h = run([ent("tj-core", LNK)])
T.chk(isinstance(r, dict) and set(r) == {"tj-core"}, "[2] 링크 경로로 띄운 이 설치 = 이 설치 것", r)

PM2HOME = os.path.join(T.TMP, "pm2home")
os.makedirs(os.path.join(PM2HOME, "logs"), exist_ok=True)
os.environ["PM2_HOME"] = PM2HOME
stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - 60))
for u in ("tj-core", "tj-evm", "tj-web"):
    with open(os.path.join(PM2HOME, "logs", u + "-error.log"), "w") as f:
        for k in range(30):
            f.write(f"{stamp},000 ERROR 다른 설치본 오류 {k}\n")
json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
           "wallets": [], "health": {"pm2_bin": FAKE}}, open(paths.CONFIG_PATH, "w"))
statefile.atomic_write_json(os.path.join(S, "runner_core.json"), {"unit": "core", "pid": os.getpid(), "ts": NOW - 10, "state": "running"})
PROBES = {"inbox": lambda: {}, "disk": lambda: {"free": 100 * 10 ** 9, "total": 200 * 10 ** 9}, "web": lambda: None, "tunnel": lambda: None}


def one(items):
    jlist(items)
    cfg = config.load_config()
    h = health.settings(cfg)
    m = health.Monitor(probes=dict(PROBES))
    obs = m.observe(cfg, h, NOW, False)
    return obs, health.evaluate(obs, h, open_ids={}), h


obs, cs, h = one([ent("tj-core", OTHER), ent("tj-evm", OTHER), ent("tj-web", OTHER)])
P = {c["id"]: c for c in cs if c["id"].startswith("proc:")}
lg = obs.get("logs") or {}
T.chk(obs.get("pm2") is None, "[3] 다른 설치본만 = pm2 없음으로 판정", obs.get("pm2"))
T.chk(all(not (lg.get(u) or {}).get("last_ts") and not (lg.get(u) or {}).get("n_err") for u in ("tj-core", "tj-evm", "tj-web")),
      "[3] 기본 ~/.pm2/logs(다른 설치본 로그)를 읽지 않음 — lastLog·오류 수 없음", {u: lg.get(u) for u in ("tj-core", "tj-web")})
T.chk(not any(c["level"] == "crit" and "pm2 상태" in str(c["detail"]) for c in P.values()), "[3] 전 유닛 'pm2 상태: 없음' 빨강 없음",
      [c for c in P.values() if c["level"] == "crit"])
T.chk(P["proc:tj-core"]["level"] == "ok", "[3] 러너 기록으로 판정(tj-core 초록)", P["proc:tj-core"])
st9 = health.build_status({}, obs, cs, NOW, h)
lastlog = {x["unit"]: x.get("lastLog") for x in st9["units"]}
T.chk(lastlog.get("tj-core") is None and lastlog.get("tj-web") is None, "[3] 상태 표 lastLog = 다른 설치본 시각 아님", lastlog)

obs, cs, h = one([ent("tj-core", T.ROOT), ent("tj-evm", T.ROOT), ent("tj-web", T.ROOT)])
lg = obs.get("logs") or {}
T.chk(isinstance(obs.get("pm2"), dict) and (lg.get("tj-core") or {}).get("n_err") == 30, "[3] 반대: 이 설치 유닛 = 종전대로 로그 읽음(오류 30)",
      (lg.get("tj-core") or {}).get("n_err"))
T.finish()

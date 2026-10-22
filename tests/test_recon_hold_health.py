#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import health  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import address_codec as ac  # noqa: E402

S = paths.STATE_DIR
NOW = time.time()
W = "0x" + "a1" * 20
A = N.OWN["tron"][0]
CID = "ledger:recon_hold:tron"
HOLD = os.path.join(S, "recon_hold.json")
CFG0 = {"chains": {"eth": {"blockscout": "https://bs.invalid", "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
        "wallets": [], "backfill_months": 5}
CFG_T = dict(CFG0, chain_wallets=[{"chain": "tron", "network": "mainnet", "address": ac.tron_display(A), "label": "트론 1"}])
reg.FORCE_AVAILABLE.add("tron")


def set_cfg(cfg):
    json.dump(cfg, open(paths.CONFIG_PATH, "w"))


def hold():
    try:
        return json.load(open(HOLD))
    except (OSError, ValueError):
        return None


os.makedirs(os.path.join(T.TMP, "logs"), exist_ok=True)
statefile.atomic_write_json(os.path.join(S, "cursor_evm_eth.json"), {W: 100, "_synced_at": NOW - 30})
PROBES = {"inbox": lambda: {}, "disk": lambda: {"free": 100 * 10 ** 9, "total": 200 * 10 ** 9}, "web": lambda: None, "tunnel": lambda: None}


def run_eval(open_ids=None, now=None):
    now = NOW if now is None else now
    cfg = config.load_config()
    h = health.settings(cfg)
    h["log_dir"] = os.path.join(T.TMP, "logs")
    pm2 = {u: {"status": "online", "restarts": 0, "pid": 100 + i, "uptime": now - 5000, "out": None, "err": None, "mem": 50 << 20}
           for i, u in enumerate(h["units"])}
    m = health.Monitor(probes=dict(PROBES, pm2=lambda: pm2))
    obs = m.observe(cfg, h, now, False)
    return {c["id"]: c for c in health.evaluate(obs, h, open_ids=open_ids or {})}


set_cfg(CFG_T)
st = cs.ChainState("tron")
st.set_status(A, requested_from=0, available_from=0, scanned_through=100, details_complete_through=100)
st.mark_synced()
c = core.Core(config.load_config())
c.conn.commit()


class BalAd(reg.ChainAdapter):
    chain = "tron"
    complete = False

    def fetch_balances(self, owners, boundary, tokens=None):
        return {"per_wallet": {A: {("native", None): 7_000_000}}, "_meta": {},
                "_boundary": {"kind": "height", "value": "200", "hash": None, "ts": int(NOW) - 3600},
                "_complete": BalAd.complete, "_why": [] if BalAd.complete else ["pending_details"],
                "_source": "fake", "_ownership_version": "x"}


c.svc_recon._nonevm_adapters = {"tron": BalAd({})}


def recon():
    cs.ChainState("tron").mark_synced()
    c.svc_recon._last_recon = 0
    c.svc_recon.recon_pass({"tron"})


def openings():
    return c.conn.execute("SELECT COUNT(*) FROM postings WHERE source_kind='opening'").fetchone()[0]


recon()
h1 = (hold() or {}).get("tron") or {}
check("RH1 대사 보류(부분 결과) = recon_hold.json 에 체인 사유 기록 · 짧은 코드 포함", "대사 결과 보류" in str(h1.get("why"))
      and "pending_details" in str(h1.get("why")) and isinstance(h1.get("since"), int) and h1.get("since") == h1.get("at"), hold())
check("RH1 원장 무변(기초잔고·완료 도장 없음)", openings() == 0 and not c._meta_get("recon_done_tron"))
statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 8 * 3600, at=int(NOW) - 600)})
recon()
h2 = (hold() or {}).get("tron") or {}
check("RH2 보류가 이어지면 since 유지 · at 갱신", h2.get("since") == int(NOW) - 8 * 3600 and h2.get("at", 0) >= int(NOW) - 5, h2)
statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 30 * 3600, at=int(NOW) - 20 * 3600)})
recon()
h2b = (hold() or {}).get("tron") or {}
check("RH2 오래 끊겼다(확인 간격 넘게) 다시 보류 = since 새로", h2b.get("since", 0) >= int(NOW) - 5, h2b)

statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 8 * 3600, at=int(NOW) - 300)})
cc = run_eval()
g = cc.get(CID) or {}
check("RH3 6시간 넘게 이어진 보류 = ledger:recon_hold:tron 주의 · 제목 체인 · 상세 사유", g.get("level") == "warn" and "Tron" in str(g.get("title"))
      and "pending_details" in str(g.get("detail")), g)
check("RH3 원장 계열 관례: unit tj-core · kind ledger · persist 0 · 리마인드 없음", g.get("unit") == "tj-core" and g.get("kind") == "ledger"
      and g.get("persist") == 0 and g.get("remind") is False, g)
statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 3600, at=int(NOW) - 60)})
check("RH4 짧은 보류(1시간) = 항목 없음(깜빡임 방지)", CID not in run_eval())
statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 30 * 3600, at=int(NOW) - 5 * 3600)})
check("RH4 오래 다시 확인 안 된 기록(5시간 전) = 항목 없음(지금 보류인지 모름 — 준비·gap 은 다른 점검)", CID not in run_eval())
g4 = run_eval(open_ids={CID: "tj-core"}).get(CID) or {}
check("RH4 열린 사건이 있으면 정상(ok)으로(풀림)", g4.get("level") == "ok", g4)

statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 8 * 3600, at=int(NOW) - 300), "sui": {"why": "x", "since": 1, "at": 1}})
BalAd.complete = True
recon()
check("RH5 대사 완료(recon_done_tron) = 그 체인 기록 지움(다른 체인 줄은 그대로)", bool(c._meta_get("recon_done_tron")) and "tron" not in (hold() or {})
      and "sui" in (hold() or {}), hold())
check("RH5 기록 지운 뒤 헬스 항목 없음", CID not in run_eval())
statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 8 * 3600, at=int(NOW) - 300)})
recon()
check("RH5 이미 대사 끝난 체인의 남은 기록 = 다음 대사 주기에 지움", "tron" not in (hold() or {}), hold())

statefile.atomic_write_json(HOLD, {"tron": dict(h1, since=int(NOW) - 8 * 3600, at=int(NOW) - 300)})
set_cfg(CFG0)
check("RH6 새 체인 지갑 없는 설치 = 기록이 있어도 항목 없음", not any(k.startswith("ledger:recon_hold") for k in run_eval()))
with open(HOLD, "w") as f:
    f.write("{깨진")
set_cfg(CFG_T)
c.conn.execute("DELETE FROM meta WHERE k='recon_done_tron'")
c.conn.execute("DELETE FROM postings WHERE source_kind='opening'")
c.conn.commit()
BalAd.complete = False
try:
    recon()
    ok6 = True
except BaseException as e:   # noqa: BLE001
    ok6 = f"예외:{type(e).__name__}"
check("RH6 손상 기록 = core 대사 경로 그대로(예외·종료 없음 · 원장 무변)", ok6 is True and openings() == 0 and not c._meta_get("recon_done_tron"), ok6)
check("RH6 손상 기록 = 헬스 판정 중단 없음", isinstance(run_eval(), dict))
c.conn.close()
reg.FORCE_AVAILABLE.discard("tron")
T.finish()

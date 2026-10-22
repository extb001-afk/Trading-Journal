#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import config, paths, statefile  # noqa: E402
import health  # noqa: E402
import health_ack  # noqa: E402
import chain_state as cs  # noqa: E402

S = paths.STATE_DIR
NOW = time.time()
W = "0x" + "a1" * 20
A, B = N.OWN["tron"]
CID = "ledger:gap:tron"
CFG0 = {"chains": {"eth": {"blockscout": "https://bs.invalid", "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
        "wallets": [{"type": "evm", "chain": "eth", "address": W}]}
CFG_T = dict(CFG0, chain_wallets=[{"chain": "tron", "network": "mainnet", "address": A, "label": "트론 1"}])


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def set_cfg(cfg):
    json.dump(cfg, open(paths.CONFIG_PATH, "w"))


def wj(name, obj):
    statefile.atomic_write_json(os.path.join(S, name), obj)


os.makedirs(os.path.join(T.TMP, "logs"), exist_ok=True)
wj("cursor_evm_eth.json", {W: 100, "_synced_at": NOW - 30})
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
    return health.evaluate(obs, h, open_ids=open_ids or {}), obs, h


def find(checks, cid=CID):
    return next((c for c in checks if c["id"] == cid), None)


def make_gap(st, sid, owner):
    st.pending_upsert([(sid, {"owner": owner, "lane": "history"})])
    for _i in range(cs.MAX_TRIES):
        if st.reschedule(sid, "일시 실패: HTTP 500 합성 오류") != "retry":
            break


set_cfg(CFG_T)
st = cs.ChainState("tron")
for o in (A, B):
    st.set_status(o, requested_from=100, available_from=100, scanned_through=200, details_complete_through=200)
make_gap(st, "txa" + "0" * 61, A)
make_gap(st, "txb" + "0" * 61, B)
st.mark_synced()
ck("전제: chain_state 미해소 gap 2건(A 1 · B 1) · A 는 대사 준비 아님(owner_done 거짓)",
   len(st.unresolved_gaps()) == 2 and not st.owner_done(A) and not st.ready({A}), st.unresolved_gaps())

c1, o1, h1 = run_eval()
ck("전제: Tron 지갑 + 수집기 있음 = 헬스 유닛에 tj-tron", "tj-tron" in h1["units"], h1["units"])
g1 = find(c1)
ck("G1 미해소 gap 1건 = 점검 ledger:gap:tron 주의(warn)", g1 is not None and g1["level"] == "warn", g1)
g1 = g1 or {}
ck("G1 제목·상세 = 체인·건수·영향(거래 기록 누락 · 기초잔고 대사 보류)·마지막 사유",
   "Tron" in str(g1.get("title")) and "1건" in str(g1.get("title")) and "보류" in str(g1.get("detail"))
   and "HTTP 500" in str(g1.get("detail")), g1)
ck("G1 원장 계열 관례: unit tj-tron · kind ledger · persist 0 · resolve 600 · 알림 대상 · 리마인드 없음",
   g1.get("unit") == "tj-tron" and g1.get("kind") == "ledger" and g1.get("persist") == 0 and g1.get("resolve") == 600
   and g1.get("notify") is True and g1.get("remind") is False and not g1.get("suppressed"), g1)
ck("G1 닫기 대상 아님(원장 계열 — ACKABLE 밖 · 닫기 지문 없음)", CID not in health_ack.ACKABLE and not g1.get("ack"), g1.get("ack"))
hst = {}
health.step(hst, c1, NOW, h1)
ev = health.step(hst, run_eval(now=NOW + 60)[0], NOW + 60, h1)
inc1 = (hst.get("incidents") or {}).get(CID)
ck("G1 두 판 뒤 사건 열림(주의)", inc1 is not None and inc1.get("level") == "warn" and any(t9 == "open" and i9.get("check") == CID for t9, i9 in ev),
   (inc1, [(t9, i9.get("check")) for t9, i9 in ev]))
d9 = datetime.fromtimestamp(NOW + 120, health.KST).replace(hour=9, minute=30, second=0, microsecond=0)
if d9.timestamp() <= NOW + 120:
    d9 = d9 + timedelta(days=1)
pst = json.loads(json.dumps(hst))
try:
    health.plan(pst, [], d9.timestamp(), h1, True)
    dg = [o9 for o9 in pst.get("outbox") or [] if o9.get("kind") == "digest"]
except Exception as e:   # noqa: BLE001
    dg = [f"예외:{type(e).__name__}: {e}"]
ck("G1 09시 요약(텔레그램)에 'Tron 거래 상세 누락'이 들어감", any("Tron" in str(o9.get("text") if isinstance(o9, dict) else o9) for o9 in dg), dg)

ck("G2 뺀 지갑(B)의 gap 은 세지 않음(1건 — 2건 아님) · 관측 = 그 체인 지갑만", "2건" not in str(g1.get("title")) and
   (o1.get("nonevm_gaps") or {}).get("tron", {}).get("n") == 1, o1.get("nonevm_gaps"))

st = cs.ChainState("tron")
st.mark_emitted("txa" + "0" * 61, "txa" + "0" * 61, owners=[A])
st.save()
ck("전제: A 의 gap 해소(발견 지갑 관점 방출) · A 대사 준비", st.owner_done(A), st.unresolved_gaps())
c3, _o3, _h3 = run_eval(open_ids={CID: "tj-tron"}, now=NOW + 120)
g3 = find(c3)
ck("G3 해소 뒤 열린 사건 있음 = 정상(ok) 관측", g3 is not None and g3["level"] == "ok", g3)
for k9 in range(1, 14):
    health.step(hst, run_eval(open_ids={CID: "tj-tron"}, now=NOW + 120 + 60 * k9)[0], NOW + 120 + 60 * k9, h1)
ck("G3 풀림 시간(600초) 뒤 사건 닫힘", CID not in (hst.get("incidents") or {}), (hst.get("incidents") or {}).get(CID))
ck("G3 열린 사건 없고 미해소 0 = 점검 항목 없음(상태 패널 초록 줄을 늘리지 않음)", find(run_eval(now=NOW + 1000)[0]) is None)

st = cs.ChainState("tron")
make_gap(st, "txd" + "0" * 61, A)
st.save()
set_cfg(CFG0)
c4, o4, h4 = run_eval()
ck("G4 새 체인 지갑 없음 = 점검 항목 없음(gap 이 든 상태 파일이 남아 있어도) · 유닛에 tj-tron 없음",
   not any(c["id"].startswith("ledger:gap") for c in c4) and "tj-tron" not in h4["units"], [c["id"] for c in c4 if "gap" in c["id"]])
ck("G4 관측에 새 체인 없음(빈 값 또는 칸 없음)", not o4.get("nonevm_gaps"), o4.get("nonevm_gaps"))
o4b = {k: v for k, v in o4.items() if k != "nonevm_gaps"}
ck("G4 판정 출력 = 관측 칸 없는 종전 판정과 바이트 동일",
   json.dumps(health.evaluate(o4, h4, open_ids={}), sort_keys=True, ensure_ascii=False, default=str)
   == json.dumps(health.evaluate(o4b, h4, open_ids={}), sort_keys=True, ensure_ascii=False, default=str))

set_cfg(CFG_T)
c5a = find(run_eval(now=NOW + 1100)[0])
ck("전제: 다시 지갑 등록 = 미해소 1건 주의", c5a is not None and c5a["level"] == "warn", c5a)
cur_p = os.path.join(S, "cursor_tron.json")
good = open(cur_p, "rb").read()
with open(cur_p, "w") as f:
    f.write("{손상")
c5, o5, _h5 = run_eval(open_ids={CID: "tj-tron"}, now=NOW + 1160)
g5 = find(c5)
ck("G5 수집 상태 파일 손상 = 0건(정상)으로 보지 않고 판단 보류(level None)", g5 is not None and g5["level"] is None and "보류" in str(g5.get("detail")), g5)
ck("G5 관측 = 읽기 실패 표시(None) — 0 아님", "tron" in (o5.get("nonevm_gaps") or {}) and (o5.get("nonevm_gaps") or {}).get("tron") is None, o5.get("nonevm_gaps"))
hst5 = {}
for k9 in range(3):
    health.step(hst5, [dict(c5a or {"id": CID, "unit": "tj-tron", "title": "t", "detail": "", "action": "", "persist": 0, "resolve": 600,
                                    "notify": True, "remind": False, "kind": "ledger"}, level="warn")], NOW + 1200 + 60 * k9, h1)
for k9 in range(1, 16):
    health.step(hst5, run_eval(open_ids={CID: "tj-tron"}, now=NOW + 1400 + 300 * k9)[0], NOW + 1400 + 300 * k9, h1)
ck("G5 읽기 실패가 1시간 넘게 이어져도 열린 사건은 닫히지 않고 유지(직전 판정 · '감시 대상에서 빠짐'으로 조용히 닫히지 않음)",
   CID in (hst5.get("incidents") or {}), [(x.get("check"), x.get("resolved_detail")) for x in hst5.get("history") or []])
with open(cur_p, "wb") as f:
    f.write(good)
em_p = os.path.join(S, "emitted_tron.json")
with open(em_p, "w") as f:
    f.write("[손상")
g5b = find(run_eval(open_ids={CID: "tj-tron"}, now=NOW + 2400)[0])
ck("G5 방출 기록 파일 손상 = 판단 보류(전부 미해소로 세지 않음)", g5b is not None and g5b["level"] is None, g5b)
os.remove(em_p)

T.finish()

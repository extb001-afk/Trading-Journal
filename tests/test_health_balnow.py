#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

os.environ["TJ_HEALTH"] = "0"
import chk_balance  # noqa: E402
import health as H  # noqa: E402
import paths  # noqa: E402

chk = T.chk
NOW = 1_800_000_000.0
UNITS = ["tj-core", "tj-web", "tj-sol", "tj-alert"]
HS = H.settings({"health": {"units": UNITS}})
HT = H.settings({"health": {"units": UNITS, "tg_min_age_sec": 0, "flap_hold_sec": 0}})
STK = "Stk" + "7" * 41
WA = "0x" + "ab" * 20


def stake_item(first=NOW - 600):
    return {"key": f"sol:{STK}:stake", "chain": "sol", "wallet": STK, "sym": "SOL(스테이킹 · 닫힌 계정 — 원장 칸 남음)", "ca": None,
            "diffUsd": 18000.0, "carried": False, "carriedN": 0, "seenAt": NOW, "firstSeen": first, "ledger": 200.0, "onchain": 0.0,
            "stakeClosed": True}


def plain_item(first=NOW - 600):
    return {"key": f"base:{WA}:native", "chain": "base", "wallet": WA, "sym": "ETH", "ca": None, "diffUsd": 900.0, "carried": False,
            "carriedN": 0, "seenAt": NOW, "firstSeen": first, "ledger": 1.0, "onchain": 0.5}


def obs(its, now=NOW, mem=None, bb=None):
    o = {"now": now, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {} if mem is None else mem,
         "prev_inc": {}, "sources": [], "balbusy": bb or {}, "bf": {}}
    o["balcheck"] = {"checkedAt": now, "confirmed": len(its), "watch": 0, "resolving": 0, "errors": 0, "top": "x", "items": its,
                     "unchecked": 0, "capped": False, "pairs": 10}
    return o


def bal(o):
    return {c["id"]: c for c in H.evaluate(o, HS)}.get("balcheck:mismatch") or {}


c1 = T.safe(bal, obs([stake_item()]))
chk(c1.get("level") == "crit" and c1.get("notify") is True and c1.get("keys") == [f"sol:{STK}:stake"]
    and (c1.get("tg_items") or [{}])[0].get("stakeClosed") is True, "N1 닫힌 스테이크 계정 = 처음 본 판에 빨강 · 알림 · 텔레그램 키", c1)
c2 = T.safe(bal, obs([plain_item()]))
chk(c2.get("level") == "crit" and c2.get("notify") is False and not c2.get("keys") and "24시간 지켜보는 중" in str(c2.get("detail")),
    "N2 일반 불일치 처음 본 판 = 빨강 · 알림 없음 · 24시간 지켜보는 중(종전)", c2)
c3 = T.safe(bal, obs([plain_item(first=NOW - 2 * 86400)], mem={f"base:{WA}:native": NOW - 86401}))
chk(c3.get("notify") is True and c3.get("keys") == [f"base:{WA}:native"], "N3 24시간 지난 일반 불일치 = 알림(종전)", c3)
c3b = T.safe(bal, obs([plain_item(), stake_item()]))
chk(c3b.get("notify") is True and c3b.get("keys") == [f"sol:{STK}:stake"], "N3 섞임 = 닫힌 계정만 바로 · 일반은 24시간 기다림", c3b)

st = {}
for k in range(4):
    t9 = NOW + k * 600
    o9 = obs([stake_item()], now=t9, mem=st.setdefault("bal_ready", {}))
    H.plan(st, H.step(st, H.evaluate(o9, HT), t9, HT), t9, HT, True)
opens = [o for o in st.get("outbox") or [] if o.get("kind") in ("open", "group") and any("balcheck" in str(x) for x in o.get("incs") or [])]
txt = opens[0].get("text") if opens else ""
chk(len(opens) == 1, "N4 같은 계정·같은 상태로 4판 = 생김 1통뿐", st.get("outbox"))
chk("하루 넘게" not in txt and "닫혔거나 출금 권한이 넘어갔는데" in txt and "SOL(스테이킹 · 닫힌 계정 — 원장 칸 남음)" in txt,
    "N4 문장 = '하루 넘게' 없음 · 짐작 = 닫힌 계정 · 이름 그대로", txt)
inc = (st.get("incidents") or {}).get("balcheck:mismatch") or {}
inc["announced"] = NOW + 1900
for k in range(4, 8):
    t9 = NOW + k * 600
    H.plan(st, H.step(st, H.evaluate(obs([stake_item()], now=t9, mem=st["bal_ready"]), HT), t9, HT), t9, HT, True)
more = [o for o in st.get("outbox") or [] if o.get("kind") in ("open", "group", "remind") and inc.get("id") in (o.get("incs") or [])]
chk(not more and inc.get("announced") == NOW + 1900, "N4 보낸 뒤 같은 상태 4판 더 = 새 안내·리마인드 0(보낸 표식 그대로)", [o.get("kind") for o in more])

c5 = T.safe(bal, obs([stake_item()], bb={"chains": {"sol": ["옛 기록을 반영하는 재계산 대기"]}}))
chk(c5.get("notify") is not True and not c5.get("keys"), "N5 진행 중 보류(재계산 대기) = 닫힌 계정도 보류(종전 규칙)", c5)

for k in range(9, 13):
    t6 = NOW + k * 600
    o6 = obs([], now=t6, mem=st["bal_ready"])
    o6["balcheck"]["confirmed"] = 0
    H.plan(st, H.step(st, H.evaluate(o6, HT), t6, HT), t6, HT, True)
res6 = [o for o in st.get("outbox") or [] if o.get("kind") == "resolve" and inc.get("id") in (o.get("incs") or [])]
chk("balcheck:mismatch" not in (st.get("incidents") or {}) and len(res6) == 1 and f"sol:{STK}:stake" not in st["bal_ready"],
    "N6 풀림 = 사건 닫힘 · '풀렸어요' 1통(종전 관례) · 키 시계 지움", [list(st.get("incidents") or {}), [o.get("kind") for o in st.get("outbox") or []]])

o9h = obs([stake_item()], mem={f"sol:{STK}:stake": NOW - 600})
o9h.update(unreadable={"fail_chains": ["sol"]}, prev_inc={"balcheck:mismatch": {"keys": [f"sol:{STK}:stake"]}})
c9h = T.safe(bal, o9h)
chk(c9h.get("notify") is not True and not c9h.get("keys"), "N9 상태 파일 못 읽은 체인의 직전 빨강(판단 보류) = 닫힌 계정이라도 새로 알리지 않음(종전 보류 규칙)", c9h)
t7 = T.safe(chk_balance.bal_text, [dict(plain_item(), stuck=[])])
chk(isinstance(t7, str) and t7.startswith("🔴 잔고가 장부와 하루 넘게 달라요 · 1곳"), "N7 일반 불일치만 = '하루 넘게' 그대로", t7)

json.dump({"checkedAt": NOW, "mismatches": [dict(stake_item(), confirmed=True), dict(plain_item(), confirmed=True)], "pending": {}},
          open(paths.state("onchain_check.json"), "w"))
bc8 = T.safe(chk_balance.collect_balcheck, {})
st8 = {x.get("key"): x.get("stakeClosed") for x in (bc8 or {}).get("items") or []}
chk(st8 == {f"sol:{STK}:stake": True, f"base:{WA}:native": False}, "N8 수집이 stakeClosed 를 실어 옴(일반 = False)", st8)
T.finish()

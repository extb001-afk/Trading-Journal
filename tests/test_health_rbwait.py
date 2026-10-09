#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os

os.environ["TJ_HEALTH"] = "0"
import health as H

NOW = 1_800_000_000.0
UNITS = ["tj-evm", "tj-bsc", "tj-core", "tj-web", "tj-alert"]
HS = H.settings({"health": {"units": UNITS}})
WA = "0x" + "ab" * 20
WB = "0x" + "cd" * 20
BF = {"evm": {"base:rpc": {"phase": "extend", "done": 42, "total": 100, "eta_sec": 2 * 86400 + 5 * 3600, "updated": NOW - 60}}}
RB = {"chains": {"base": ["옛 기록을 반영하는 재계산 대기", "과거 기록 범위를 넓히는 중"]}}
SENT = "Base 과거 기록 넓히기(지금 42% · 약 2일 5시간 남음)가 끝나면 원장 자동 재계산으로 사라져요 — 기다리면 됨"


def item(w=WA, chain="base", first=NOW - 3600):
    return {"key": f"{chain}:{w}:native", "chain": chain, "wallet": w, "sym": "ETH", "ca": None, "diffUsd": 100.0, "carried": False,
            "carriedN": 0, "seenAt": NOW, "firstSeen": first, "ledger": 1.0, "onchain": 0.5}


def ev(its=None, bb=None, bf=None, wd=None):
    obs = {"now": NOW, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {}, "sources": [],
           "balbusy": bb or {}, "bf": bf if bf is not None else BF}
    if its is not None:
        obs["balcheck"] = {"checkedAt": NOW, "confirmed": len(its), "watch": 0, "resolving": 0, "errors": 0, "top": "x", "items": its,
                           "unchecked": 0, "capped": False, "pairs": 10}
    if wd is not None:
        obs["webdiag"] = wd
    return {c["id"]: c for c in H.evaluate(obs, HS)}


c = T.safe(lambda: ev([item()], RB)["balcheck:mismatch"])
T.chk(isinstance(c, dict) and c.get("level") == "warn" and c.get("title") == "원장·온체인 잔고 불일치 1건 · 재계산 대기"
      and str(c.get("detail")).startswith(SENT + " / 재계산 대기: ") and str(c.get("action")).startswith(SENT) and c.get("notify") is False,
      "W1 전부 재계산 대기 = 주황 · 제목 '· 재계산 대기' · 상세·할 일 맨 앞 안내(진행률·남은 시간) · 알림 없음", c)
c = T.safe(lambda: ev([item(), item(w=WB, chain="bsc")], RB)["balcheck:mismatch"])
T.chk(isinstance(c, dict) and c.get("level") == "crit" and c.get("title") == "원장·온체인 잔고 불일치 2건"
      and str(c.get("detail")).endswith(" / 그중 1건은 재계산 대기 — " + SENT) and "그중 재계산 대기 1건은 기다리면 됨" in str(c.get("action")),
      "W2 섞임(보류 아닌 칸 있음) = 종전 빨강 · 제목 그대로 · '그중 1건은 재계산 대기 — …'", c)
c = T.safe(lambda: ev([item()], {})["balcheck:mismatch"])
T.chk(isinstance(c, dict) and c.get("level") == "crit" and c.get("title") == "원장·온체인 잔고 불일치 1건" and "재계산" not in str(c),
      "W3 보류 없음 = 종전 빨강 · '재계산' 문구 없음", c)
BF_STALL = {"evm": {"base:rpc": dict(BF["evm"]["base:rpc"], moved_at=NOW - 2 * 3600)}}
c2 = T.safe(lambda: ev([item(first=NOW - 3 * 86400 - 60)], RB, bf=BF_STALL)["balcheck:mismatch"])
T.chk(isinstance(c2, dict) and c2.get("level") == "warn" and c2.get("title") == "원장·온체인 잔고 불일치 1건 · 재계산 대기" and c2.get("notify") is False,
      "W3 재계산 대기가 3일 넘음 + 확장 멈춤(안 끝남) = 오너 규칙 '넓히기 끝날 때까지 주의' → 주황 유지(멈춤은 '가져오기 멈춤' 항목이 따로)", c2)
BF_DONE = {"evm": {"base:rpc": dict(BF["evm"]["base:rpc"], phase="done")}}
c9 = T.safe(lambda: ev([item(first=NOW - 3 * 86400 - 60)], RB, bf=BF_DONE)["balcheck:mismatch"])
T.chk(isinstance(c9, dict) and c9.get("level") == "crit" and "재계산 대기" not in str(c9.get("title")),
      "W9 넓히기가 끝났는데도 3일 넘게 남음 = 오류(빨강) · 오너 규칙", c9)
c3 = T.safe(lambda: ev([item(first=NOW - 3 * 86400 - 60)], RB)["balcheck:mismatch"])
T.chk(isinstance(c3, dict) and c3.get("level") == "warn" and c3.get("title") == "원장·온체인 잔고 불일치 1건 · 재계산 대기" and c3.get("notify") is False,
      "W7 재계산 대기가 3일 넘어도 확장이 멈추지 않고 진행 중 = 보류 유지(주황 · 알림 없음)", c3)
c8 = T.safe(lambda: ev([item(first=NOW - 7 * 86400 - 60)], RB)["balcheck:mismatch"])
T.chk(isinstance(c8, dict) and c8.get("level") == "warn" and c8.get("title") == "원장·온체인 잔고 불일치 1건 · 재계산 대기",
      "W8 7일 넘어도 그 체인 넓히기가 안 끝났으면 주의(주황) — 오너 10-09 규칙(끝나야 오류)", c8)
OLD_ES = {"phase": "extend", "done": 3, "total": 9, "updated": NOW - 5 * 86400, "moved_at": NOW - 5 * 86400}
BF_HAND = {"evm": {"base:extend": OLD_ES, "base:job": dict(OLD_ES), "base:rpc": dict(BF["evm"]["base:rpc"], phase="live", done=100)}}
c10 = T.safe(lambda: ev([item(first=NOW - 3 * 86400 - 60)], RB, bf=BF_HAND)["balcheck:mismatch"])
T.chk(isinstance(c10, dict) and c10.get("level") == "crit" and "재계산 대기" not in str(c10.get("title"))
      and T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_HAND}, "base") is False and T.safe(H.bf_ext_phrase, BF_HAND, NOW) == "",
      "W10 옛 탐색기 extend·job 표식 + 더 새로 갱신된 RPC live(인계분까지 끝남) = 넓히기 끝 → 3일 넘은 불일치 빨강 · 안내 진행률 없음", c10)
BF_HAND2 = {"evm": {"base:extend": OLD_ES, "base:rpc": dict(BF["evm"]["base:rpc"])}}
c11 = T.safe(lambda: ev([item(first=NOW - 3 * 86400 - 60)], RB, bf=BF_HAND2)["balcheck:mismatch"])
T.chk(isinstance(c11, dict) and c11.get("level") == "warn" and c11.get("title") == "원장·온체인 잔고 불일치 1건 · 재계산 대기"
      and str(c11.get("detail")).startswith(SENT + " / "),
      "W11 옛 탐색기 extend + RPC 가 인계분을 아직 넓히는 중(phase extend) = 안 끝남 → 주황 · 진행률은 RPC 것만", c11)
BF_BACK = {"evm": {"base:rpc": dict(BF["evm"]["base:rpc"], updated=NOW - 2 * 86400),
                   "base:extend": dict(OLD_ES, updated=NOW - 600, moved_at=NOW - 600)}}
T.chk(T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_BACK}, "base") is True and T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_BACK}, "bsc") is False,
      "W12 탐색기로 복귀 뒤 탐색기 extend 가 더 새로 갱신 = 그 표식 기준(안 끝남) · 다른 체인은 무관", BF_BACK)
BF_BACK2 = {"evm": {"base:rpc": dict(BF["evm"]["base:rpc"], updated=NOW - 2 * 86400),
                    "base:extend": dict(OLD_ES, phase="done", updated=NOW - 600)}}
T.chk(T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_BACK2}, "base") is False,
      "W13 탐색기 복귀 뒤 탐색기 확장 끝(done) = 남은 옛 RPC 'extend' 표식은 무시 → 끝남", BF_BACK2)
BF_3W = {"evm": {"base:job": dict(OLD_ES), "base:rpc": dict(BF["evm"]["base:rpc"], updated=NOW - 2 * 86400),
                  "base:extend": dict(OLD_ES, phase="done", updated=NOW - 600)}}
T.chk(T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_3W}, "base") is False,
      "W14 블록스카웃(:job) 확장 → RPC 인계 → 이더스캔(:extend) 복귀·완료 = 옛 :job·:rpc 표식 무시(세 경로 중 마지막 갱신만) → 끝남", BF_3W)
BF_BS = {"evm": {"base:extend": dict(OLD_ES), "base:job": dict(OLD_ES, updated=NOW - 600, moved_at=NOW - 600)}}
T.chk(T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_BS}, "base") is True,
      "W15 이더스캔 옛 표식 + 더 새로 갱신된 블록스카웃 확장(:job extend) = 안 끝남", BF_BS)
BF_ORPH = {"evm": {"base:job": dict(OLD_ES, phase="done", updated=NOW - 3 * 86400),
                    "base:rpc": dict(BF["evm"]["base:rpc"], updated=NOW - 25 * 3600)}}
c16 = T.safe(lambda: ev([item(first=NOW - 3 * 86400 - 60)], RB, bf=BF_ORPH)["balcheck:mismatch"])
T.chk(isinstance(c16, dict) and c16.get("level") == "crit" and T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_ORPH}, "base") is False,
      "W16 하루 넘게 아무도 안 쓴 '안 끝난' 표식(RPC 뒤 차선을 탐색기에 넘긴 뒤 남은 :rpc extend) = 남은 것 → 끝남 · 3일 넘은 불일치 빨강", c16)
BF_ORPH2 = {"evm": {"base:rpc": dict(BF["evm"]["base:rpc"], updated=NOW - 23 * 3600)}}
T.chk(T.safe(H.bf_ext_open, {"now": NOW, "bf": BF_ORPH2}, "base") is True,
      "W16 하루 안에 갱신된 표식 = 아직 안 끝남(멈춰도 살아 있는 워처는 매 사이클 갱신)", BF_ORPH2)
c = T.safe(lambda: ev([item()], RB, bf={})["balcheck:mismatch"])
T.chk(isinstance(c, dict) and c.get("level") == "warn" and str(c.get("detail")).startswith("원장 자동 재계산이 끝나면 사라져요 — 기다리면 됨 / ")
      and "%" not in str(c.get("action")), "W4 진행 정보 없음 = 진행률·남은 시간 빼고 '원장 자동 재계산이 끝나면 사라져요 — 기다리면 됨'", c)
WD = {"ts": NOW - 60, "neg": {"n": 1, "usd": -640.0, "top": [{"sym": "ETH", "loc": f"wallet:base:{WA}", "usd": -640.0, "pend": True}],
                              "pend": {"n": 1, "usd": -640.0}}}
c = T.safe(lambda: ev(None, None, wd=WD)["ledger:neg"])
T.chk(isinstance(c, dict) and c.get("title") == "원장 음수 보유 $640 · 재계산 대기"
      and str(c.get("detail")).endswith("Base 과거 기록 넓히기(지금 42% · 약 2일 5시간 남음)가 끝나면 원장 자동 재계산이 다시 맞춤 — 기다리면 됨")
      and "기다린 뒤에도 남으면" in str(c.get("action")), "W5 원장 음수 보유 재계산 대기 = 진행률·남은 시간 붙음 · '기다린 뒤에도 남으면 점검' 유지", c)
txt = T.safe(H.bal_text, [dict(item(), stuck=["옛 기록을 반영하는 재계산 대기"], rbw=SENT)])
T.chk(isinstance(txt, str) and txt.split("\n")[1].startswith("할 일: 기다리기 — ") and txt.split("\n")[2] == "  " + SENT,
      "W6 3일 넘은 재계산 대기 텔레그램 = '할 일: 기다리기' 다음 줄에 진행률·남은 시간 안내", txt)
txt = T.safe(H.bal_text, [dict(item(), stuck=["로그 없는 송금 4건 회수 중"])])
T.chk(isinstance(txt, str) and "자동 재계산" not in txt, "W6 재계산과 무관한 까닭 = 안내 줄 없음(종전 문장)", txt)

T.finish()

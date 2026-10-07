#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

from datetime import datetime

import wow2

chk = H.chk
T = datetime(2026, 10, 6, 12, 0, tzinfo=wow2.KST)
COINS = ["ETH", "BTC", "SOL", "ONDO"]

def R(q):
    return wow2.ask_rules(q, T, COINS, 1400.0)


r = R("작년 12월 ETH 매도")
chk(r["filters"].get("after") == "2025-12-01" and r["filters"].get("before") == "2025-12-31", "작년 12월 = 2025-12-01~12-31(작년 전체 아님)", r["filters"])
chk(r["filters"].get("type") == "sell" and r["filters"].get("coin") == "ETH", "작년 12월 ETH 매도: 종류 매도 · 코인 ETH", r["filters"])
chk(r["text"] == "", "작년 12월 ETH 매도: 글자 검색어 없음('12월'·'매' 안 남음)", r["text"])
r = R("작년 3월 BTC 손실")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2025-03-01", "2025-03-31") and r["filters"].get("pnl") == "<0" and r["filters"].get("coin") == "BTC",
    "작년 3월 BTC 손실 = 2025-03 · 손실 · BTC", r["filters"])
chk(r["text"] == "", "작년 3월 BTC 손실: 글자 검색어 없음", r["text"])
r = R("올해 5월 매수")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2026-05-01", "2026-05-31") and r["filters"].get("type") == "buy", "올해 5월 매수 = 2026-05 · 매수", r["filters"])
chk(r["text"] == "", "올해 5월 매수: 글자 검색어 없음", r["text"])
r = R("2025년 12월 SOL")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2025-12-01", "2025-12-31") and r["filters"].get("coin") == "SOL", "2025년 12월 SOL(종전 그대로)", r["filters"])
r = R("지난해 매도")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2025-01-01", "2025-12-31") and r["filters"].get("type") == "sell" and r["text"] == "",
    "지난해 매도 = 2025 전체 · 매도 · '매' 안 남음", (r["filters"], r["text"]))
r = R("12월 ETH 매도")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2025-12-01", "2025-12-31") and r["text"] == "", "연도 없는 12월 = 지난 12월(종전 규칙) · '매' 안 남음", (r["filters"], r["text"]))
r = R("재작년 매도")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2024-01-01", "2024-12-31") and r["text"] == "", "재작년 = 2024 전체(작년으로 잘못 읽지 않음)", (r["filters"], r["text"]))
r = R("올해 매도")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2026-01-01", "2026-10-06"), "올해 = 1/1~오늘(종전 그대로)", r["filters"])
r = R("작년 12월 3일 매도")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2025-12-03", "2025-12-03") and r["text"] == "", "작년 12월 3일 = 그날 하루", (r["filters"], r["text"]))
r = R("2025년 매수")
chk((r["filters"].get("after"), r["filters"].get("before")) == ("2025-01-01", "2025-12-31") and r["text"] == "", "2025년(달 없음) = 그해 전체", (r["filters"], r["text"]))
r = R("온도 매수")
chk(r["filters"].get("coin") == "ONDO" and r["text"] == "", "'온도'(코인 별칭)를 조사 '도' 로 자르지 않음", (r["filters"], r["text"]))
r = R("팔았던 ETH 도")
chk(r["filters"].get("type") == "sell" and r["filters"].get("coin") == "ETH", "팔았던 = 매도(종전 그대로)", r["filters"])
r = R("작년 12월 ETH 매도")
a = wow2.ask("작년 12월 ETH 매도", COINS, ["eth", "base"], 1400.0, T, llm_on=False)
chk(set(a["query"].split()) == {"after:2025-12-01", "before:2025-12-31", "type:sell", "coin:ETH"}, "ask: 검색 서버로 넘길 조건 = 연·월 함께 · 글자 없음", a["query"])

H.finish()

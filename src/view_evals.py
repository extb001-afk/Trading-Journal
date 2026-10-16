from __future__ import annotations
import sellchart
import day_memo

SELL_EVALS = sellchart.EvalStore()


BUY_EVALS = sellchart.EvalStore(kind="buy")


DAY_MEMOS = day_memo.Store()

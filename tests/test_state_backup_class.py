#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402

import paths  # noqa: E402
import ledger_backup as L  # noqa: E402

chk = T.chk

B, F, LG, TM, SC = "backup", "refetch", "ledger", "temp", "secret"
CLASS = {
    "addr_tier_*.json": F, "addr_tier_req.json": TM, "alert_hold.json": TM, "alert_stats.json": TM, "alert_watch.json": TM,
    "alerts_fast.jsonl": TM, "alerts_sent_web.json": TM, "alerts_web.jsonl": TM, "asset_decimals_issues.json": F,
    "att_frozen.json": B,
    "att_frozen_bfpx.json": B,
    "auth.json": SC, "auth_devices.json": SC, "auth_internal_token": SC, "auth_sessions.json": SC, "auth_setup_code": SC,
    "backfill_done": LG, "backfill_request.json": TM, "backfill_status.json": TM,
    "backups": TM,
    "bsc_balw.json": F, "bsc_balw_recheck.json": TM, "bsc_nonce.json": F, "bsc_token_meta.json": F, "bsc_xin.json": F,
    "candles": B,
    "cg_ca.json": F, "chain_activity.json": F, "chain_sweep.json": F,
    "chainoff_keep_on.json": B,
    "config.json.lock": TM, "coverage_limits.json": F,
    "cursor_bsc.json": LG, "cursor_btc.json": LG, "cursor_sol.json": LG, "cursor_ton.json": LG,
    "curve_hist.json": B, "curve_hist_px.json": B, "daily_cache.json": F, "daily_close_px.json": B, "daily_px.json": B,
    "daily_px_seed.json": TM,
    "day_memos.json": B, "decimals_resolve_request.json": TM, "decimals_resolve_result.json": TM, "decimals_wait.json": F, "depaddr_request.json": TM,
    "deposit_addresses.json": B,
    "dex_jump.json": F, "disc_open_request.json": TM, "emitted_bsc.json": LG, "emitted_sol.json": LG, "evm_route.json": F,
    "exf_active.json": F, "exf_balance_sources.json": F, "exf_balances_*.json": F, "exf_balances_hyperliquid.json": F,
    "exf_binance_symbols.json": F, "exf_bybit_symbols.json": F, "exf_clock.json": TM, "exf_cooldown.json": TM,
    "exf_debt_redate_t.json": B,
    "exf_fut_wait.json": TM,
    "exf_recon_revert.jsonl": B,
    "exf_redate_m.json": B,
    "exf_ident.json": B,
    "exf_snap_miss.json": TM, "exf_state.json": LG, "ext_rebuild_status.json": TM,
    "first_seen_px.json": B, "kr_deemed_px.json": B, "flow_px_cache.json": F, "flow_trace_cache.json": F, "genuine_tokens.json": B,
    "goplus_cache.json": F, "goplus_status.json": TM, "health": TM, "health_ack.json": TM, "health_eval.json": TM,
    "health_reload.json": TM, "health_status.json": TM, "hist_dirty.json": TM, "hl_cash_syms.json": F, "hl_late_stage.json": LG,
    "hl_neg_mark.json": F, "hl_spot_meta.json": F, "inflow_*.json": F, "intentional_restart.json": TM, "leverage.json": F,
    "liq_watch.json": TM, "lp_positions.json": F, "negabs_request.json": TM, "negabs_result.json": TM, "nft_budget.json": TM,
    "nft_fp.json": B, "nft_holdings.json": F, "nft_prefs.json": B, "onchain_check.json": F, "other_assets.json": B,
    "other_assets_px.json": B, "outflow_decisions.json": B, "pending_dm.jsonl": TM, "pending_poison.jsonl": LG, "poison.jsonl": LG,
    "poison_replay_request.json": TM, "poison_replayed.json": TM, "prov_bal.json": F, "px_cache_core.json": F, "px_cache_web.json": F,
    "rabby_bot_usd.json": F, "rabby_daily.json": B, "rabby_gap.json": F, "rabby_portfolio.json": F, "rebuild_pnl_approve.json": TM,
    "rebuild_pnl_gate.json": TM, "rebuild_rejected": TM, "recon_adj.json": F, "recon_hold.json": TM, "review_catchup_manual.lock": TM,
    "review_fill_request.json": TM, "review_old_budget.json": TM, "review_progress.json": TM, "reviews_llm.json": B,
    "reviews_llm_weekly.json": B, "rpc_fallback.json": TM, "runner_alert.json": TM, "runner_core.json": TM, "runner_evm.json": TM,
    "sale_bids.json": F, "sale_cand_alerts.json": TM, "search.db": F,
    "seed_local": B,
    "settings.json": B, "setup_token": SC, "sol_mint_meta.json": F, "sol_owner_unknown.jsonl": TM, "sol_stake.json": F, "spot.json": F,
    "tg_cursor.json": TM, "token_leg_skips.jsonl": TM, "ton_pace.lock": TM, "tx_origin_cache.json": F, "ui_prefs.json": B,
    "upbit_balances.json": F, "upbit_orders_state.json": LG, "upbit_sync.json": TM, "wallet_reload.json": TM,
    "wallet_reload_done.json": TM, "web_diag.json": TM, "web_snap_last.bin": TM, "wow_ask.json": TM, "xchain_px_cache.json": F,
    "addr_tier_{}.json": F, "bfspool_{}_{}.jsonl": LG, "cursor_evm_{}.json": LG, "cursor_rpc_{}.json": LG, "emitted_evm_{}.json": LG,
    "emitted_rpc_{}.json": LG, "enrich_{}.json": F, "exf_addrs_{}.json": F, "exf_balances_{}.json": F, "exf_balances_{}.json.view": F,
    "exf_balances_{}.json{}": F, "exf_fix_place_v{}.json": TM, "autofix_undo_{}_{}_{}_{}.json": TM, "exf_fut_place_v{}.json": TM,
    "futraw_{}_main.json": B, "futraw_{}_{}.json": B,
    "futures_px_{}.json": B,
    "futures_{}.json": B,
    "hq_left_{}.json": LG, "inflow_{}.json": F, "leaf_later_overflow_{}.jsonl": LG, "leaf_later_unresolved_{}.jsonl": LG,
    "pending_detail_{}.json": LG, "poison_tsfix_{}.json": TM, "rpc_token_meta_{}.json": F, "rpc_token_sym_{}.json": F, "runner_{}.json": TM,
    "solspool{}_{}.jsonl": LG, "token_nodec_{}.json": F, "trace_later_left_{}.json": LG, "trace_later_overflow_{}.jsonl": LG,
    "trace_later_unresolved_{}.jsonl": LG,
}
EXTRA = {
    "buy_evals.json": B, "sell_evals.json": B, "addr_ai.json": B,
    "buy_eval_budget.json": TM, "sell_eval_budget.json": TM, "addr_ai_budget.json": TM, "addr_ai_chain_budget.json": TM,
    "token_discovery.json": F, "web_rawtx_cache.json": F, "xchain_cache.json": F, "chain_backfill_speed.json": F, "ledger.db": LG, "inbox": LG,
}
ALL = dict(CLASS, **EXTRA)
DIR_BACKUP = {L.CANDLES, "seed_local"}


def sample(k: str) -> str:
    return k.replace("{}", "x").replace("*", "x")


reg = set(paths.REG) | set(paths.DYN)
chk(not (reg - set(CLASS)), "S1 등록부의 모든 state 이름 = 분류 있음(새 이름 = 이 표에 backup/refetch/ledger/temp/secret 중 하나 — 다시 못 받으면 backup)",
    sorted(reg - set(CLASS)))
chk(not (set(CLASS) - reg) and not (set(EXTRA) & reg), "S2 분류표 이름 = 등록부에 있음(등록부 밖은 EXTRA)", sorted((set(CLASS) - reg) | (set(EXTRA) & reg)))
chk(all(v in (B, F, LG, TM, SC) for v in ALL.values()), "S2b 분류 값 = 다섯 중 하나", sorted(set(ALL.values())))
prefs = set(L.PREFS_FILES)
bad = []
for k, v in sorted(ALL.items()):
    s = sample(k)
    got = s in DIR_BACKUP or s in prefs or L.backup_kind(s) is not None
    if got != (v == B):
        bad.append((k, v, got))
chk(not bad, "S3 표의 backup ⇔ 실제 백업 선택(ledger_backup.backup_kind · 봉/seed_local 폴더 · prefs 덤프)", bad)
names = set(L.FILES_STATE) | set(L.FILES_CACHE) | prefs
chk(all(ALL.get(n) == B for n in names), "S4 원장 밖 사본 목록 이름 = 전부 표에 backup", sorted(n for n in names if ALL.get(n) != B))
chk(L.backup_kind("futures_okx.json") == "cache" and L.backup_kind("futraw_okx_s1@u12.json") == "cache"
    and L.backup_kind("futures_okx.json.tmp") is None and L.backup_kind("futraw_okx_s1.json.bak") is None,
    "S5 선물 정본·원본 = 보관본(지금 없을 때만 · 정본은 합집합) · 임시·보존 꼬리 = 아님", None)
chk(os.path.isfile(os.path.join(T.ROOT, "src", "ledger_backup.py")), "S6 뿌리 확인", T.ROOT)
T.finish()

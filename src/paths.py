import os
import re
import stat
import tempfile
import urllib.parse

import logs

__all__ = ["BASE_DIR", "STATE_DIR", "INBOX_DIR", "CONFIG_PATH", "DB_PATH", "DEMO_ISOLATED", "ENV_PATH", "ACTIVITY_GATE_PATH",
           "BACKFILL_SPEED_PATH", "QUOTA_STATE_DIR", "quota_dir", "rebase_state", "ensure_dirs", "sqlite_ro_uri", "tighten_config_mode",
           "tool_ref", "REG", "DYN", "UnregisteredStateName", "registered", "state", "StatePath"]


BASE_DIR = os.environ.get("TJ_BASE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(BASE_DIR, "state")
INBOX_DIR = os.path.join(STATE_DIR, "inbox")
CONFIG_PATH = os.environ.get("TJ_CONFIG", os.path.join(BASE_DIR, "config.json"))
DB_PATH = os.path.join(STATE_DIR, "ledger.db")
DEMO_ISOLATED = False
if os.environ.get("TJ_DEMO") == "1":
    STATE_DIR = os.environ.get("TJ_DEMO_STATE") or ""
    if not STATE_DIR:
        import atexit as _atexit
        import shutil as _shutil
        STATE_DIR = tempfile.mkdtemp(prefix="tj_demo_state_")
        _demo_pid = os.getpid()
        _atexit.register(lambda d=STATE_DIR: _shutil.rmtree(d, ignore_errors=True) if os.getpid() == _demo_pid else None)
    os.environ["TJ_DEMO_STATE"] = STATE_DIR
    INBOX_DIR = os.path.join(STATE_DIR, "inbox")
    DB_PATH = os.path.join(STATE_DIR, "ledger.db")
    DEMO_ISOLATED = True
    if not os.environ.get("TJ_CONFIG"):
        CONFIG_PATH = os.path.join(STATE_DIR, "config.json")
ENV_PATH = os.path.join(STATE_DIR if DEMO_ISOLATED else BASE_DIR, ".env")


logs.set_sources(lambda: (ENV_PATH, CONFIG_PATH))


ACTIVITY_GATE_PATH = os.path.join(STATE_DIR, "chain_activity.json")
BACKFILL_SPEED_PATH = os.path.join(STATE_DIR, "chain_backfill_speed.json")


QUOTA_STATE_DIR = None


def quota_dir() -> str:
    return QUOTA_STATE_DIR or STATE_DIR


def rebase_state(state_dir: str, db_path: str = None) -> None:
    global STATE_DIR, INBOX_DIR, DB_PATH, ACTIVITY_GATE_PATH, BACKFILL_SPEED_PATH
    STATE_DIR = state_dir
    INBOX_DIR = os.path.join(state_dir, "inbox")
    DB_PATH = db_path or os.path.join(state_dir, "ledger.db")
    ACTIVITY_GATE_PATH = os.path.join(state_dir, "chain_activity.json")
    BACKFILL_SPEED_PATH = os.path.join(state_dir, "chain_backfill_speed.json")


def ensure_dirs() -> None:
    for d9 in (STATE_DIR, INBOX_DIR):
        os.makedirs(d9, mode=0o700, exist_ok=True)
        try:
            st9 = os.lstat(d9)
            if stat.S_ISDIR(st9.st_mode) and stat.S_IMODE(st9.st_mode) != 0o700 and (not hasattr(os, "getuid") or st9.st_uid == os.getuid()):
                os.chmod(d9, 0o700)
        except OSError:
            pass
    if not os.path.islink(ENV_PATH):
        tighten_config_mode(ENV_PATH)


def sqlite_ro_uri(path: str, immutable: bool = False) -> str:
    q = urllib.parse.quote(os.fspath(path), safe="/:\\")
    return "file:" + q + "?mode=ro" + ("&immutable=1" if immutable else "")


def tighten_config_mode(path: str = None) -> bool:
    p = path or CONFIG_PATH
    try:
        st = os.stat(p)
        if (st.st_mode & 0o170000) != 0o100000 or not (st.st_mode & 0o077) or (hasattr(os, "getuid") and st.st_uid != os.getuid()):
            return False
        os.chmod(p, st.st_mode & 0o700)
        return True
    except OSError:
        return False


def tool_ref(name: str, alt: str) -> str:
    return f"tools/{name}" if os.path.isfile(os.path.join(BASE_DIR, "tools", name)) else alt

REG = {
    "addr_tier_*.json": ("addr_tier_*.json", "addr_tier chk_balance", "glob", None),
    "addr_tier_req.json": ("addr_tier_req.json", "addr_tier", "json", None),
    "alert_hold.json": ("alert_hold.json", "alert_bot alert_prefs", "json", None),
    "alert_stats.json": ("alert_stats.json", "alert_bot alert_prefs", "json", None),
    "alert_watch.json": ("alert_watch.json", "alert_watch", "json", None),
    "alerts_fast.jsonl": ("alerts_fast.jsonl", "liq_watch", "jsonl", None),
    "alerts_sent_web.json": ("alerts_sent_web.json", "web", "json", None),
    "alerts_web.jsonl": ("alerts_web.jsonl", "view_alerts", "jsonl", None),
    "asset_decimals_issues.json": ("asset_decimals_issues.json", "core_dec health", "json", None),
    "auth.json": ("auth.json", "login_auth", "json", 0o600),
    "auth_devices.json": ("auth_devices.json", "login_auth", "json", 0o600),
    "auth_internal_token": ("auth_internal_token", "login_auth", "file", 0o600),
    "auth_sessions.json": ("auth_sessions.json", "login_auth", "json", 0o600),
    "auth_setup_code": ("auth_setup_code", "login_auth", "file", 0o600),
    "backfill_done": ("backfill_done", "core_recon health view_b_daily view_daily", "file", None),
    "backfill_request.json": ("backfill_request.json", "bf_engine view_builder", "json", None),
    "backfill_status.json": ("backfill_status.json", "bf_engine health", "json", None),
    "backups": ("backups", "chainoff chk_collect core_exf_fut health ledger_backup", "dir", 0o700),
    "bsc_balw.json": ("bsc_balw.json", "bsc_balw", "json", None),
    "bsc_balw_recheck.json": ("bsc_balw_recheck.json", "bsc_balw", "json", None),
    "bsc_nonce.json": ("bsc_nonce.json", "bsc_nonce chk_balance", "json", None),
    "bsc_token_meta.json": ("bsc_token_meta.json", "bsc_watch", "json", None),
    "bsc_xin.json": ("bsc_xin.json", "bsc_nonce", "json", None),
    "candles": ("candles", "candles review_daily sellchart", "dir", None),
    "cg_ca.json": ("cg_ca.json", "cgca", "json", None),
    "chain_activity.json": ("chain_activity.json", "chk_sources", "json", None),
    "chain_sweep.json": ("chain_sweep.json", "chainsweep chk_collect web", "json", None),
    "chainoff_keep_on.json": ("chainoff_keep_on.json", "chainoff", "json", None),
    "config.json.lock": ("config.json.lock", "settings_store", "lock", 0o600),
    "coverage_limits.json": ("coverage_limits.json", "coverage_limits recon_adj web", "json", None),
    "cursor_bsc.json": ("cursor_bsc.json", "bsc_watch chk_balance discopen", "json", None),
    "cursor_btc.json": ("cursor_btc.json", "settings_wallets", "json", None),
    "cursor_sol.json": ("cursor_sol.json", "sol_watch", "json", None),
    "cursor_ton.json": ("cursor_ton.json", "ton_watch", "json", None),
    "curve_hist.json": ("curve_hist.json", "histcurve", "json", None),
    "curve_hist_px.json": ("curve_hist_px.json", "histcurve web wow", "json", None),
    "daily_cache.json": ("daily_cache.json", "core core_exf_late core_post discopen view_builder view_daily view_pxfix", "json", None),
    "daily_close_px.json": ("daily_close_px.json", "histcurve wow", "json", None),
    "daily_px.json": ("daily_px.json", "recon_adj view_builder view_daily view_pxfix web", "json", None),
    "daily_px_seed.json": ("daily_px_seed.json", "view_builder", "json", None),
    "day_memos.json": ("day_memos.json", "day_memo", "json", 0o600),
    "decimals_resolve_request.json": ("decimals_resolve_request.json", "core_dec", "json", None),
    "decimals_resolve_result.json": ("decimals_resolve_result.json", "core_dec", "json", None),
    "depaddr_request.json": ("depaddr_request.json", "depaddr", "json", None),
    "deposit_addresses.json": ("deposit_addresses.json", "depaddr", "json", None),
    "dex_jump.json": ("dex_jump.json", "view_spot", "json", None),
    "disc_open_request.json": ("disc_open_request.json", "bsc_balw", "json", None),
    "emitted_bsc.json": ("emitted_bsc.json", "bsc_watch", "json", None),
    "emitted_sol.json": ("emitted_sol.json", "sol_watch", "json", None),
    "evm_route.json": ("evm_route.json", "evm_watch", "json", None),
    "exf_active.json": ("exf_active.json", "ex_foreign", "json", None),
    "exf_balance_sources.json": ("exf_balance_sources.json", "exf_net", "json", None),
    "exf_balances_*.json": ("exf_balances_*.json", "chk_collect", "glob", None),
    "exf_balances_hyperliquid.json": ("exf_balances_hyperliquid.json", "view_prov", "json", None),
    "exf_binance_symbols.json": ("exf_binance_symbols.json", "exf_binance", "json", None),
    "exf_bybit_symbols.json": ("exf_bybit_symbols.json", "exf_bybit", "json", None),
    "exf_clock.json": ("exf_clock.json", "ex_foreign exf_net", "json", None),
    "exf_cooldown.json": ("exf_cooldown.json", "exf_net", "json", None),
    "exf_debt_redate_t.json": ("exf_debt_redate_t.json", "core_exf_late view_daily", "json", None),
    "exf_fut_wait.json": ("exf_fut_wait.json", "chk_collect core_exf_fut", "json", None),
    "exf_recon_revert.jsonl": ("exf_recon_revert.jsonl", "core_exf", "jsonl", None),
    "exf_redate_m.json": ("exf_redate_m.json", "core_exf_late", "json", None),
    "exf_snap_miss.json": ("exf_snap_miss.json", "chk_collect ex_foreign", "json", None),
    "exf_state.json": ("exf_state.json", "core_exf ex_foreign exf_net hl_spot", "json", None),
    "ext_rebuild_status.json": ("ext_rebuild_status.json", "core_ext health view_builder", "json", None),
    "first_seen_px.json": ("first_seen_px.json", "recon_adj view_fspin", "json", None),
    "flow_px_cache.json": ("flow_px_cache.json", "view_workers", "json", None),
    "flow_trace_cache.json": ("flow_trace_cache.json", "view_outflows", "json", 0o644),
    "genuine_tokens.json": ("genuine_tokens.json", "spamguard", "json", None),
    "goplus_cache.json": ("goplus_cache.json", "view_b_cards view_b_replay web", "json", None),
    "goplus_status.json": ("goplus_status.json", "web", "json", None),
    "health": ("health", "addr_tier bf_engine chk_sources", "dir", None),
    "health_ack.json": ("health_ack.json", "health_ack", "json", None),
    "health_eval.json": ("health_eval.json", "health", "json", None),
    "health_reload.json": ("health_reload.json", "health", "json", None),
    "health_status.json": ("health_status.json", "health", "json", None),
    "hist_dirty.json": ("hist_dirty.json", "histcurve", "json", None),
    "hl_cash_syms.json": ("hl_cash_syms.json", "core_exf hl_spot view_common", "json", None),
    "hl_late_stage.json": ("hl_late_stage.json", "hl_spot", "json", None),
    "hl_neg_mark.json": ("hl_neg_mark.json", "view_outflows", "json", None),
    "hl_spot_meta.json": ("hl_spot_meta.json", "hl_spot", "json", None),
    "inflow_*.json": ("inflow_*.json", "inflow_probe", "glob", None),
    "intentional_restart.json": ("intentional_restart.json", "core_ext health", "json", None),
    "leverage.json": ("leverage.json", "leverage liq_watch", "json", None),
    "liq_watch.json": ("liq_watch.json", "health liq_watch web", "json", None),
    "lp_positions.json": ("lp_positions.json", "view_b_cards view_b_pendings view_workers", "json", None),
    "negabs_request.json": ("negabs_request.json", "discopen", "json", None),
    "negabs_result.json": ("negabs_result.json", "discopen", "json", None),
    "nft_budget.json": ("nft_budget.json", "nft", "json", None),
    "nft_fp.json": ("nft_fp.json", "nft", "json", None),
    "nft_holdings.json": ("nft_holdings.json", "nft", "json", None),
    "nft_prefs.json": ("nft_prefs.json", "nft", "json", None),
    "onchain_check.json": ("onchain_check.json", "balcheck bsc_balw chk_balance web", "json", None),
    "other_assets.json": ("other_assets.json", "other_assets", "json", None),
    "other_assets_px.json": ("other_assets_px.json", "other_assets", "json", None),
    "outflow_decisions.json": ("outflow_decisions.json", "core_outflow view_builder", "json", None),
    "pending_dm.jsonl": ("pending_dm.jsonl", "core_common evm_base view_index", "jsonl", None),
    "pending_poison.jsonl": ("pending_poison.jsonl", "bf_engine evm_bscout evm_es evm_logdisc", "jsonl", None),
    "poison.jsonl": ("poison.jsonl", "core_inbox tsfix", "jsonl", None),
    "poison_replay_request.json": ("poison_replay_request.json", "core_inbox", "json", None),
    "poison_replayed.json": ("poison_replayed.json", "core_inbox", "json", None),
    "prov_bal.json": ("prov_bal.json", "core_prov", "json", None),
    "px_cache_core.json": ("px_cache_core.json", "core view_b_replay view_fut", "json", None),
    "px_cache_web.json": ("px_cache_web.json", "view_builder", "json", None),
    "rabby_bot_usd.json": ("rabby_bot_usd.json", "view_b_pendings view_builder", "json", None),
    "rabby_daily.json": ("rabby_daily.json", "histcurve view_b_daily", "json", None),
    "rabby_gap.json": ("rabby_gap.json", "view_b_pendings", "json", None),
    "rabby_portfolio.json": ("rabby_portfolio.json", "token_discovery view_b_cards view_workers", "json", None),
    "rebuild_pnl_approve.json": ("rebuild_pnl_approve.json", "core_ext", "json", None),
    "rebuild_pnl_gate.json": ("rebuild_pnl_gate.json", "core_ext health", "json", None),
    "rebuild_rejected": ("rebuild_rejected", "ops_requests", "dir", None),
    "recon_adj.json": ("recon_adj.json", "health recon_adj view_b_tail", "json", None),
    "recon_hold.json": ("recon_hold.json", "chk_collect core_recon", "json", None),
    "review_catchup_manual.lock": ("review_catchup_manual.lock", "review_daily view_review", "lock", None),
    "review_fill_request.json": ("review_fill_request.json", "http_post review_daily view_review", "json", None),
    "review_old_budget.json": ("review_old_budget.json", "review_daily", "json", None),
    "review_progress.json": ("review_progress.json", "review_daily view_b_tail", "json", None),
    "reviews_llm.json": ("reviews_llm.json", "review_daily view_reviews", "json", None),
    "reviews_llm_weekly.json": ("reviews_llm_weekly.json", "review_daily view_reviews", "json", None),
    "rpc_fallback.json": ("rpc_fallback.json", "addr_tier evm_watch", "json", None),
    "runner_alert.json": ("runner_alert.json", "health", "json", None),
    "runner_core.json": ("runner_core.json", "health", "json", None),
    "runner_evm.json": ("runner_evm.json", "chk_sources", "json", None),
    "sale_bids.json": ("sale_bids.json", "view_b_replay view_b_tail view_workers", "json", None),
    "sale_cand_alerts.json": ("sale_cand_alerts.json", "view_builder", "json", None),
    "search.db": ("search.db", "search_index", "db", None),
    "seed_local": ("seed_local", "seeds", "dir", None),
    "settings.json": ("settings.json", "alert_prefs nodekeys settings_store", "json", 0o600),
    "setup_token": ("setup_token", "settings_store", "file", 0o600),
    "sol_mint_meta.json": ("sol_mint_meta.json", "sol_watch", "json", None),
    "sol_owner_unknown.jsonl": ("sol_owner_unknown.jsonl", "sol_watch", "jsonl", None),
    "sol_stake.json": ("sol_stake.json", "balcheck core_prov core_recon sol_watch view_misc", "json", None),
    "spot.json": ("spot.json", "spamguard view_spot wallet_register", "json", None),
    "tg_cursor.json": ("tg_cursor.json", "alert_bot chk_collect", "json", None),
    "token_leg_skips.jsonl": ("token_leg_skips.jsonl", "bf_engine", "jsonl", None),
    "ton_pace.lock": ("ton_pace.lock", "ton_watch", "lock", None),
    "tx_origin_cache.json": ("tx_origin_cache.json", "view_b_replay view_outflows view_workers", "json", None),
    "ui_prefs.json": ("ui_prefs.json", "alert_prefs chainoff discopen http_outflow http_post http_post_prefs liq_watch review_daily view_load web", "json", None),
    "upbit_balances.json": ("upbit_balances.json", "balcheck core_upbit_recon depaddr upbit_link view_b_cards view_b_replay", "json", None),
    "upbit_orders_state.json": ("upbit_orders_state.json", "balcheck core_ext core_upbit_recon upbit_link", "json", None),
    "upbit_sync.json": ("upbit_sync.json", "balcheck upbit_link", "json", None),
    "wallet_reload.json": ("wallet_reload.json", "wallet_register", "json", None),
    "wallet_reload_done.json": ("wallet_reload_done.json", "wallet_register", "json", None),
    "web_diag.json": ("web_diag.json", "health view_b_tail view_builder", "json", None),
    "web_snap_last.bin": ("web_snap_last.bin", "view_snapfile", "bin", None),
    "wow_ask.json": ("wow_ask.json", "wow2", "json", None),
    "xchain_px_cache.json": ("xchain_px_cache.json", "view_workers", "json", None),
}
DYN = {
    "addr_tier_{}.json": ("addr_tier_{}.json", "addr_tier chainoff", "json", None),
    "bfspool_{}_{}.jsonl": ("bfspool_{}_{}.jsonl", "evm_bscout", "jsonl", None),
    "cursor_evm_{}.json": ("cursor_evm_{}.json", "chainoff config core_recon discopen evm_bscout evm_es evm_rpcw evm_watch", "json", None),
    "cursor_rpc_{}.json": ("cursor_rpc_{}.json", "evm_logdisc", "json", None),
    "emitted_evm_{}.json": ("emitted_evm_{}.json", "evm_bscout evm_es evm_rpcw", "json", None),
    "emitted_rpc_{}.json": ("emitted_rpc_{}.json", "evm_logdisc", "json", None),
    "enrich_{}.json": ("enrich_{}.json", "evm_base evm_bscout evm_rpcw", "json", None),
    "exf_addrs_{}.json": ("exf_addrs_{}.json", "depaddr", "json", None),
    "exf_balances_{}.json": ("exf_balances_{}.json", "core_exf ex_foreign exf_net hl_spot view_b_pendings view_b_replay view_krw", "json", None),
    "exf_balances_{}.json.view": ("exf_balances_{}.json.view", "ex_foreign", "file", None),
    "exf_balances_{}.json{}": ("exf_balances_{}.json{}", "depaddr", "file", None),
    "exf_fix_place_v{}.json": ("exf_fix_place_v{}.json", "core_exf", "json", None),
    "exf_fut_place_v{}.json": ("exf_fut_place_v{}.json", "core_exf_fut", "json", None),
    "futraw_{}_main.json": ("futraw_{}_main.json", "ex_foreign", "json", None),
    "futraw_{}_{}.json": ("futraw_{}_{}.json", "ex_foreign exf_net", "json", None),
    "futures_px_{}.json": ("futures_px_{}.json", "fut_rcpt", "json", None),
    "futures_{}.json": ("futures_{}.json", "core_exf_fut ex_foreign exf_net liq_watch perp_dex view_index web", "json", None),
    "hq_left_{}.json": ("hq_left_{}.json", "evm_base evm_rpcw", "json", None),
    "inflow_{}.json": ("inflow_{}.json", "inflow_probe", "json", None),
    "leaf_later_overflow_{}.jsonl": ("leaf_later_overflow_{}.jsonl", "evm_base", "jsonl", None),
    "leaf_later_unresolved_{}.jsonl": ("leaf_later_unresolved_{}.jsonl", "evm_rpc_later", "jsonl", None),
    "pending_detail_{}.json": ("pending_detail_{}.json", "evm_base evm_bscout evm_es evm_rpcw", "json", None),
    "poison_tsfix_{}.json": ("poison_tsfix_{}.json", "tsfix", "json", None),
    "rpc_token_meta_{}.json": ("rpc_token_meta_{}.json", "evm_bscout evm_es evm_logdisc evm_rpcw", "json", None),
    "rpc_token_sym_{}.json": ("rpc_token_sym_{}.json", "evm_rpcw", "json", None),
    "runner_{}.json": ("runner_{}.json", "chk_sources health runner_fp unit_beat unit_runner", "json", None),
    "solspool{}_{}.jsonl": ("solspool{}_{}.jsonl", "sol_watch", "jsonl", None),
    "token_nodec_{}.json": ("token_nodec_{}.json", "bf_engine", "json", None),
    "trace_later_left_{}.json": ("trace_later_left_{}.json", "evm_base evm_rpcw", "json", None),
    "trace_later_overflow_{}.jsonl": ("trace_later_overflow_{}.jsonl", "evm_base evm_rpc_later", "jsonl", None),
    "trace_later_unresolved_{}.jsonl": ("trace_later_unresolved_{}.jsonl", "evm_rpc_later", "jsonl", None),
}


class UnregisteredStateName(AssertionError):
    pass


_DYN_RX = re.compile("|".join("(?:%s)" % re.escape(k).replace(r"\{\}", "[^/]*") for k in DYN))


def registered(name: object) -> bool:
    return isinstance(name, str) and (name in REG or _DYN_RX.fullmatch(name) is not None)


def state(name: str, *more: str) -> str:
    if os.environ.get("TJ_STRICT") == "1" and not registered(name):
        raise UnregisteredStateName("state 이름이 paths 등록부에 없음: %r" % (name,))
    return os.path.join(STATE_DIR, name, *more)


class StatePath:

    __slots__ = ("parts",)

    def __init__(self, name: str, *more: str) -> None:
        self.parts = (name,) + more

    def __get__(self, obj: object, owner: type = None) -> str:
        return state(*self.parts)

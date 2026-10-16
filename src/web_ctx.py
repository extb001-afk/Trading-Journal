_REG = {}


def register(**fns) -> None:
    for k9, f9 in fns.items():
        _REG.setdefault(k9, f9)


def builder():
    f9 = _REG.get("builder")
    return f9() if f9 else None


def bcall(name, *a):
    return _REG["bcall"](name, *a)


def day_memo():
    return _REG["day_memo"]()


def search_pool():
    return _REG["search_pool"]()


def nft_tracker(*a, **k):
    return _REG["nft_tracker"](*a, **k)


def oa_quoter(*a, **k):
    return _REG["oa_quoter"](*a, **k)


def oa_rate(*a, **k):
    return _REG["oa_rate"](*a, **k)


def memo_driven(*a, **k):
    return _REG["memo_driven"](*a, **k)


def v2_csp(*a, **k):
    return _REG["v2_csp"](*a, **k)


def alert_view(*a, **k):
    return _REG["alert_view"](*a, **k)


def tg_connected(*a, **k):
    return _REG["tg_connected"](*a, **k)


def _fwd(key):
    def f9(*a, **k):
        return _REG[key](*a, **k)
    f9.__name__ = key
    return f9


mats_ready = _fwd("mats_ready")
wallet_reload_view = _fwd("wallet_reload_view")
registered_wallet_keys = _fwd("registered_wallet_keys")
bench_series = _fwd("bench_series")
chain_auto_off_save = _fwd("chain_auto_off_save")
coverage_refresh = _fwd("coverage_refresh")
futures_api_payload = _fwd("futures_api_payload")
leverage_api_payload = _fwd("leverage_api_payload")
prefs_lock = _fwd("prefs_lock")
coverage_path = _fwd("coverage_path")
alias_max = _fwd("alias_max")
ignored_max = _fwd("ignored_max")
plans_max = _fwd("plans_max")
src_wl_max = _fwd("src_wl_max")
alias_addr_re = _fwd("alias_addr_re")

import sqlite3

from core_common import CLASSIFIER_VER
from core_exf import ExfMixin
from core_fills import FillsMixin
from core_pricing import PricingMixin
from core_prov import ProvMixin
from core_recon import ReconMixin
from core_upbit import UpbitMixin
from core_upbit_recon import UpbitReconMixin

__all__ = ["CLASSIFIER_VER", "EXF_PORT", "ExfService", "PRICE_PORT", "PriceService", "RECON_PORT", "ReconService", "attach", "exf_settle_planner"]

EXF_PORT = ("_post_leg", "_post_leg_strict", "_amend_leg", "_unpost_source", "_leg_sql", "_inval_daily", "_inval_seq", "_meta_get", "_win_t0",
            "asset_id", "conn", "cfg", "px", "recon_months", "_drain_at")
RECON_PORT = ("_inval_daily", "_meta_dec", "_meta_get", "_post_leg_strict", "_recon_view", "_recon_view_drop", "_win_t0", "asset_id", "_group_of",
              "cfg", "conn", "my_wallets", "sol_wallets", "chain_owners", "chain_readers", "native_sym", "wrapped", "reader", "sol_reader",
              "bsc_reader", "recon_months")
PRICE_PORT = ("_meta_get", "_norm", "_leg_sql", "cfg", "conn", "px", "native_sym", "wrapped", "svc_exf")


class ExfService(ExfMixin, FillsMixin, UpbitMixin, UpbitReconMixin):

    def __init__(self, core, wd_fee_since=None):
        self.core = core
        if wd_fee_since is not None:
            self.wd_fee_since = wd_fee_since

    conn = property(lambda self: self.core.conn)
    cfg = property(lambda self: self.core.cfg)
    px = property(lambda self: self.core.px)
    recon_months = property(lambda self: self.core.recon_months)
    _drain_at = property(lambda self: self.core._drain_at)

    def _post_leg(self, *a, **k):
        return self.core._post_leg(*a, **k)

    def _post_leg_strict(self, *a, **k):
        return self.core._post_leg_strict(*a, **k)

    def _amend_leg(self, *a, **k):
        return self.core._amend_leg(*a, **k)

    def _unpost_source(self, *a, **k):
        return self.core._unpost_source(*a, **k)

    def _leg_sql(self, *a, **k):
        return self.core._leg_sql(*a, **k)

    def _inval_daily(self, *a, **k):
        return self.core._inval_daily(*a, **k)

    def _inval_seq(self, *a, **k):
        return self.core._inval_seq(*a, **k)

    def _meta_get(self, *a, **k):
        return self.core._meta_get(*a, **k)

    def _win_t0(self, *a, **k):
        return self.core._win_t0(*a, **k)

    def asset_id(self, *a, **k):
        return self.core.asset_id(*a, **k)


class ReconService(ReconMixin, ProvMixin):

    def __init__(self, core):
        self.core = core
        self._last_recon = 0.0

    cfg = property(lambda self: self.core.cfg)
    conn = property(lambda self: self.core.conn)
    my_wallets = property(lambda self: self.core.my_wallets)
    sol_wallets = property(lambda self: self.core.sol_wallets)
    chain_owners = property(lambda self: self.core.chain_owners)
    chain_readers = property(lambda self: self.core.chain_readers)
    native_sym = property(lambda self: self.core.native_sym)
    wrapped = property(lambda self: self.core.wrapped)
    reader = property(lambda self: self.core.reader)
    sol_reader = property(lambda self: self.core.sol_reader)
    bsc_reader = property(lambda self: self.core.bsc_reader)
    recon_months = property(lambda self: self.core.recon_months)

    def _inval_daily(self, *a, **k):
        return self.core._inval_daily(*a, **k)

    def _meta_dec(self, *a, **k):
        return self.core._meta_dec(*a, **k)

    def _meta_get(self, *a, **k):
        return self.core._meta_get(*a, **k)

    def _post_leg_strict(self, *a, **k):
        return self.core._post_leg_strict(*a, **k)

    def _recon_view(self, *a, **k):
        return self.core._recon_view(*a, **k)

    def _recon_view_drop(self, *a, **k):
        return self.core._recon_view_drop(*a, **k)

    def _win_t0(self, *a, **k):
        return self.core._win_t0(*a, **k)

    def asset_id(self, *a, **k):
        return self.core.asset_id(*a, **k)

    def _group_of(self, *a, **k):
        return self.core._group_of(*a, **k)


class PriceService(PricingMixin):

    def __init__(self, core):
        self.core = core
        self._last_price_pass = 0.0
        self._px_skip = (None, "[]")

    cfg = property(lambda self: self.core.cfg)
    conn = property(lambda self: self.core.conn)
    px = property(lambda self: self.core.px)
    native_sym = property(lambda self: self.core.native_sym)
    wrapped = property(lambda self: self.core.wrapped)
    svc_exf = property(lambda self: self.core.svc_exf)

    def _meta_get(self, *a, **k):
        return self.core._meta_get(*a, **k)

    def _norm(self, *a, **k):
        return self.core._norm(*a, **k)

    def _leg_sql(self, *a, **k):
        return self.core._leg_sql(*a, **k)


def attach(c: object) -> object:
    c.svc_exf = ExfService(c)
    c.svc_recon = ReconService(c)
    c.svc_price = PriceService(c)
    return c


def exf_settle_planner(core_cls: type, cfg: dict, conn: sqlite3.Connection) -> ExfService:
    c = object.__new__(core_cls)
    c.cfg = cfg
    c.conn = conn
    c.recon_months = 0.0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 0)
    return ExfService(c)

import hashlib
import json
import os
import time
import urllib.request
import config, logs, paths, statefile
import bf_engine, evm_reorg
from evm_base import BisectBudget
from evm_base import ChainDisabled
from evm_base import HoldError
from evm_base import RETENTION_CONFIRM_N
from evm_base import RETENTION_CONFIRM_SEC
from evm_base import RETENTION_MIN_AGE_SEC
from evm_base import StateUnavailable
from evm_base import TRACE_DEPTH_MAX
from evm_base import TraceDeferred
from evm_base import TraceStaged
from evm_base import _RpcBudget
from evm_base import _SCAN_LOG
from evm_base import _TDLY
from evm_base import _TraceBudget
from evm_base import _WALK_END
from evm_base import _int_or
from evm_base import leaf_overflow_path
from evm_base import leaf_overflow_read
from evm_base import new_view_wallets
from evm_base import retention_summary
from evm_base import trace_fail_index
from evm_base import trace_path_failed
from evm_synth import RpcSynthMixin
from evm_es import EtherscanWatcher
import logging

log = logging.getLogger('tj-evm')

RPC_NODES = {
    "eth": {"logs": ["https://rpc.mevblocker.io", _TDLY + "mainnet", "https://eth.drpc.org"],
            "state": ["https://eth.drpc.org", "https://rpc.mevblocker.io", _TDLY + "mainnet"],
            "trace": ["https://eth.drpc.org"], "detail": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"],
            "caps": {"https://rpc.mevblocker.io": 10_000, "https://eth.drpc.org": 100}},
    "arbitrum": {"logs": ["https://arb1.arbitrum.io/rpc", _TDLY + "arbitrum", "https://arbitrum.drpc.org"],
                 "state": ["https://arb1.arbitrum.io/rpc", _TDLY + "arbitrum"],
                 "trace": ["https://arbitrum.drpc.org"], "caps": {"https://arb1.arbitrum.io/rpc": 30_000, "https://arbitrum.drpc.org": 100},
                 "mc_l1_block": True},
    "polygon": {"logs": [_TDLY + "polygon", "https://polygon.drpc.org"],
                "state": ["https://polygon.drpc.org", _TDLY + "polygon"], "trace": ["https://polygon.drpc.org"],
                "detail": ["https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"], "caps": {"https://polygon.drpc.org": 100}},
    "optimism": {"logs": ["https://mainnet.optimism.io", _TDLY + "optimism", "https://optimism.drpc.org"],
                 "state": ["https://mainnet.optimism.io", "https://optimism.drpc.org", _TDLY + "optimism"], "trace": ["https://optimism.drpc.org"],
                 "caps": {"https://mainnet.optimism.io": 10_000, "https://optimism.drpc.org": 100}},
    "scroll": {"logs": ["https://rpc.scroll.io", "https://scroll.drpc.org"],
               "state": ["https://rpc.scroll.io", "https://scroll-rpc.publicnode.com", "https://scroll.drpc.org"], "trace": [],
               "detail": ["https://rpc.scroll.io", "https://scroll-rpc.publicnode.com"], "caps": {"https://scroll.drpc.org": 100}},
    "zksync": {"logs": ["https://mainnet.era.zksync.io", "https://zksync.drpc.org"],
               "state": ["https://mainnet.era.zksync.io"], "trace": [],
               "caps": {"https://mainnet.era.zksync.io": 100_000, "https://zksync.drpc.org": 100},
               "multicall3": "0xf9cda624fbc7e059355ce98a31693d299facd963"},
    "gnosis": {"logs": ["https://rpc.gnosischain.com", "https://rpc.gnosis.gateway.fm", "https://gnosis.drpc.org"],
               "state": ["https://rpc.gnosischain.com", "https://rpc.gnosis.gateway.fm"],
               "trace": ["https://rpc.gnosischain.com", "https://rpc.gnosis.gateway.fm", "https://gnosis.drpc.org"], "caps": {"https://gnosis.drpc.org": 100}},
    "megaeth": {"logs": ["https://mainnet.megaeth.com/rpc", "https://megaeth.drpc.org"],
                "state": ["https://mainnet.megaeth.com/rpc", "https://megaeth.drpc.org"],
                "trace": ["https://mainnet.megaeth.com/rpc", "https://megaeth.drpc.org"], "caps": {"https://megaeth.drpc.org": 100}},
    "story": {"logs": ["https://mainnet.storyrpc.io"], "state": ["https://mainnet.storyrpc.io"], "trace": [],
              "caps": {"https://mainnet.storyrpc.io": 100_000}, "limited": "노드 1개·비아카이브 — 로그 없는 이동 정합은 최근 구간만",
              "handover": "rescan"},
    "base": {"logs": ["https://mainnet.base.org", _TDLY + "base", "https://base.drpc.org"],
             "state": ["https://mainnet.base.org", "https://base.drpc.org", _TDLY + "base"],
             "caps": {"https://mainnet.base.org": 500, _TDLY + "base": 1000, "https://base.drpc.org": 10}},
    "robinhood": {"logs": ["https://rpc.mainnet.chain.robinhood.com", "https://robinhood.drpc.org"],
                  "caps": {"https://rpc.mainnet.chain.robinhood.com": 30_000, "https://robinhood.drpc.org": 100},
                  "mc_l1_block": True},
    "arc": {"logs": ["https://rpc.mainnet.arc.io", "https://rpc.quicknode.mainnet.arc.io", "https://arc.drpc.org"],
            "state": ["https://rpc.mainnet.arc.io", "https://rpc.quicknode.mainnet.arc.io", "https://arc.drpc.org"], "caps": {"https://arc.drpc.org": 100}},
    "monad": {"logs": ["https://rpc1.monad.xyz", "https://rpc2.monad.xyz", "https://rpc.monad.xyz"], "state": ["https://rpc2.monad.xyz", "https://rpc1.monad.xyz"],
              "caps": {"https://rpc2.monad.xyz": 10_000, "https://rpc.monad.xyz": 100}, "fallback": {"https://rpc2.monad.xyz": 10_000}},
    "xlayer": {"logs": ["https://xlayerrpc.okx.com", "https://rpc.xlayer.tech", "https://xlayer.drpc.org"],
               "state": ["https://xlayerrpc.okx.com", "https://rpc.xlayer.tech", "https://xlayer.drpc.org"], "caps": {"https://xlayer.drpc.org": 100}},
    "kaia": {"logs": ["https://public-en.node.kaia.io", "https://kaia.drpc.org"], "state": ["https://public-en.node.kaia.io", "https://kaia.drpc.org"],
             "caps": {"https://public-en.node.kaia.io": 1_000_000, "https://kaia.drpc.org": 100}},
    "fraxtal": {"logs": ["https://rpc.frax.com", "https://fraxtal.drpc.org"], "state": ["https://rpc.frax.com", "https://fraxtal.drpc.org"], "caps": {"https://fraxtal.drpc.org": 100}},
    "bob": {"logs": ["https://rpc.gobob.xyz", "https://bob.drpc.org"], "state": ["https://rpc.gobob.xyz", "https://bob.drpc.org"], "caps": {"https://bob.drpc.org": 100}},
    "avalanche": {"logs": ["https://api.avax.network/ext/bc/C/rpc", "https://avalanche.drpc.org"],
                  "caps": {"https://api.avax.network/ext/bc/C/rpc": 100_000, "https://avalanche.drpc.org": 100}},
    "blast": {"logs": ["https://rpc.blast.io", "https://blast.drpc.org"], "caps": {"https://rpc.blast.io": 10_000, "https://blast.drpc.org": 100}},
    "linea": {"logs": ["https://rpc.linea.build", "https://linea.drpc.org"], "state": ["https://rpc.linea.build", "https://linea.drpc.org"],
              "caps": {"https://rpc.linea.build": 10_000, "https://linea.drpc.org": 100}},
    "berachain": {"logs": ["https://rpc.berachain.com", "https://berachain.drpc.org"], "state": ["https://rpc.berachain.com", "https://berachain.drpc.org"],
                  "caps": {"https://rpc.berachain.com": 10_000, "https://berachain.drpc.org": 100}},
    "zerog": {"logs": ["https://evmrpc.0g.ai", "https://0g.drpc.org"], "state": ["https://evmrpc.0g.ai", "https://0g.drpc.org"],
              "caps": {"https://evmrpc.0g.ai": 10_000, "https://0g.drpc.org": 100}, "addr_max": 32},
    "plasma": {"limited": "노드 1개(무키 백업 없음)"},
    "stable": {"limited": "노드 1개·비아카이브 — 로그 없는 이동 정합은 최근 구간만"},
    "abstract": {"limited": "노드 1개(무키 백업 없음)"},
}


def _cap_num(x):
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and int(x) > 0 else None


def logs_cap_host(url: str):
    sp = urllib.parse.urlsplit(str(url))
    h9 = (sp.hostname or "").lower()
    p9 = h9 + (sp.path or "").rstrip("/")
    tbl = RpcChainWatcher.LOGS_CAP_HOSTS
    return _cap_num(tbl.get(p9)) if p9 in tbl else _cap_num(tbl.get(h9))


def rpc_nodes(cfg: dict, chain: str) -> dict:
    cc = ((cfg or {}).get("chains") or {}).get(chain) or {}
    t = (RPC_NODES.get(chain) or {}) if cc.get("rpc_node_table", True) is not False else {}
    R = RpcChainWatcher
    cfgcaps = cc.get("rpc_log_span_caps") if isinstance(cc.get("rpc_log_span_caps"), dict) else {}
    tcaps = t.get("caps") or {}

    def cap_of(u):
        c9 = [x for x in (_cap_num(cfgcaps.get(u)), _cap_num(tcaps.get(u)), logs_cap_host(u)) if x]
        return min(c9) if c9 else None
    detail = list(cc.get("rpcs") or t.get("detail") or R.RPC_DEFAULT.get(chain) or [])
    if config.chain_discovery(chain, cc) == "rpc":
        logs = list(cc.get("rpc_logs") or detail)
        state = list(dict.fromkeys(list(cc.get("archive_rpcs") or []) + detail))
    else:
        logs = list(dict.fromkeys(list(cc.get("rpc_logs") or []) + list(t.get("logs") or []))) or list(detail)
        state = list(dict.fromkeys(list(cc.get("archive_rpcs") or []) + list(t.get("state") or []) + detail))
    if "trace_rpcs" in cc:
        trace = list(cc.get("trace_rpcs") or [])
    else:
        trace = list(t["trace"] if "trace" in t else (R.TRACE_DEFAULT.get(chain) or []))
    caps = {}
    for u in logs:
        c9 = cap_of(u)
        if c9:
            caps[u] = c9
    fb9 = cc.get("rpc_logs_fallback")
    if isinstance(fb9, dict):
        fallback = {u: int(c) for u, c in fb9.items() if _cap_num(c)}
    else:
        fallback = {u: c for u, c in caps.items() if c <= R.LOGS_FALLBACK_MAX_CAP}
        for u, c in (t.get("fallback") or {}).items():
            if u in logs and _cap_num(c):
                fallback.setdefault(u, int(caps.get(u) or c))
        if len(fallback) >= len(logs):
            fallback = {}
    mc9 = cc["multicall3"] if "multicall3" in cc else (t.get("multicall3") or R.MULTICALL3)
    try:
        amax = max(0, int(cc.get("getlogs_max_addrs") or t.get("addr_max") or 0))
    except (TypeError, ValueError):
        amax = 0
    hosts9 = {(urllib.parse.urlsplit(u).hostname or "").lower() for u in detail + logs + state}
    return {"detail": detail, "logs": logs, "state": state, "trace": trace, "caps": caps, "fallback": fallback, "addr_max": amax,
            "multicall3": mc9, "limited": t.get("limited") if len(hosts9) <= 1 else None, "handover": t.get("handover"),
            "mc_l1_block": bool(cc["multicall3_l1_block"] if "multicall3_l1_block" in cc else t.get("mc_l1_block"))}


from evm_rpc_trace import RpcTraceMixin  # noqa: E402


from evm_rpc_later import RpcLaterMixin  # noqa: E402


from evm_rpc_native import RpcNativeMixin  # noqa: E402


class RpcChainWatcher(RpcNativeMixin, RpcLaterMixin, RpcTraceMixin, RpcSynthMixin):

    TRANSFER = RpcSynthMixin.TRANSFER_TOPIC
    APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
    WETH_DEPOSIT = RpcSynthMixin.WETH_DEPOSIT
    WETH_WITHDRAWAL = RpcSynthMixin.WETH_WITHDRAWAL
    VERSION = 1
    TRACE_DEFAULT = {"robinhood": ["https://robinhood.drpc.org"], "base": ["https://base.drpc.org"]}
    HANDOVER_DEFAULT = {"robinhood": "rescan", "arc": "rescan"}
    LOGS_CAP_HOSTS = {"mainnet.base.org": 500, "gateway.tenderly.co/public/base": 1000, "base.drpc.org": 10}
    LOGS_FALLBACK_MAX_CAP = 100
    TRACE_SKIP_SELECTORS = ("0xa9059cbb", "0x095ea7b3", "0x23b872dd", "0x39509351", "0xa457c2d7", "0xd505accf")
    SELL_HINTS = True
    handover = "rescan"
    lanes_cfg = None
    addr_max = 0
    multicall = None
    bk_budget = None
    poll_sec = 45.0
    trace_mode = None
    bk_span = 200_000
    block_trace = True

    @classmethod
    def day_calls(cls, cfg: dict, chain: str, n_wallets: int, tx_per_day: float = 0, backfill_blocks: int = 0,
                  backfill_txs: int = 0, logless: int = 0, own_calls: int = 0) -> dict:
        cc = (cfg.get("chains") or {}).get(chain) or {}
        import math

        def host(u):
            return (urllib.parse.urlsplit(u).hostname or "?").lower()
        nd = rpc_nodes(cfg, chain)
        rpcs, logs, state = nd["detail"], nd["logs"], nd["state"]
        trace = [] if cls.NATIVE_EMITTER.get(chain) else nd["trace"]
        caps = {u: int(nd["caps"].get(u) or cc.get("getlogs_span", 5_000_000)) for u in logs}
        prim = [u for u in logs if u not in nd["fallback"]] or logs
        try:
            poll = min(max(float(cc.get("poll_sec") or cfg.get("evm_poll_sec") or 45), 5.0), 300.0)
        except (TypeError, ValueError):
            poll = 45.0
        cyc = 86400.0 / poll
        bpd = float(cc.get("blocks_per_day") or 43200)
        mx = nd["addr_max"] or max(1, n_wallets)
        bundles = max(1, math.ceil(max(1, n_wallets) / mx))
        mc = nd["multicall3"]
        st, bk = {}, {}

        def add(d, h, n):
            d[h] = d.get(h, 0) + n
        h0 = host(rpcs[0]) if rpcs else "?"
        hs = host(state[0]) if state else h0
        add(st, h0, 4 * cyc)
        nw9 = max(1, n_wallets)
        st_cost = (nw9 + math.ceil(nw9 / 150)) if mc else 2 * nw9
        add(st, hs, st_cost * cyc)
        per_cyc_blocks = bpd * poll / 86400.0
        for u in prim:
            add(st, host(u), 2 * bundles * math.ceil(per_cyc_blocks / max(1, caps[u])) * cyc / len(prim))
        add(st, hs, 3 * tx_per_day)
        if trace:
            add(st, host(trace[0]), 0.5 * tx_per_day)
        if backfill_blocks:
            avg = sum(caps[u] for u in prim) / len(prim)
            for u in prim:
                add(bk, host(u), 2 * bundles * backfill_blocks / avg / len(prim))
            add(bk, hs, 2.7 * backfill_txs + logless * (2 * math.log2(max(2, backfill_blocks / 60)) + 1)
                + (backfill_blocks / 200_000.0) * st_cost)
            if trace:
                add(bk, host(trace[0]), own_calls + logless * 0.2)
        return {"steady": {h: int(round(v)) for h, v in st.items()}, "backfill": {h: int(round(v)) for h, v in bk.items()}}

    def __init__(self, cfg: dict, chain: str, wallets: list, writer):
        cc = cfg["chains"][chain]
        self.chain = chain
        self.cfg = cfg
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.chain_id = int(cc["chain_id"]) if cc.get("chain_id") else None
        self.conf_depth = int(cc.get("conf_depth", 12))
        self.reorg_set = evm_reorg.settings(cc)
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.backfill_full = bool(cfg.get("backfill_full_history"))
        self.bpd = int(cc.get("blocks_per_day", 43200))
        self.wallets = [w.lower() for w in wallets]
        self.writer = writer
        nd9 = rpc_nodes(cfg, chain)
        self.cfg_rpcs = nd9["detail"]
        if not self.cfg_rpcs:
            raise SystemExit(f"{chain}: discovery=rpc 인데 rpcs 미구성")
        self.logs_rpcs = nd9["logs"]
        self.state_rpcs = nd9["state"]
        self.nodes_limited = nd9.get("limited")
        self.span = int(cc.get("getlogs_span", 5_000_000))
        self.min_span = int(cc.get("getlogs_min_span", 1))
        self.cycle_budget = float(cc.get("cycle_budget_sec", 240))
        self.detail_batch = max(1, int(cc.get("detail_batch", 10)))
        self.block_batch = max(1, int(cc.get("block_scan_batch", 50)))
        self.gap_scan_max = int(cc.get("gap_scan_max_blocks", 10_000))
        self.trace_rpcs = nd9["trace"]
        if self.NATIVE_EMITTER.get(chain) and self.trace_rpcs:
            log.warning("%s: 네이티브 시스템 이벤트 체인 — trace_rpcs 무시", chain)
            self.trace_rpcs = []
        try:
            import nodesel
            nodesel.register(chain, self.cfg_rpcs, self.logs_rpcs, self.state_rpcs, self.trace_rpcs)
        except Exception:   # noqa: BLE001 [optional]
            pass
        self.start_block = int(cc.get("start_block") or 0)
        if cc.get("rps"):
            for u9 in dict.fromkeys(self.cfg_rpcs + self.logs_rpcs + self.state_rpcs):
                bf_engine.set_call_rate(u9, cc.get("rps"))
        self._trace_fail = {}
        self.gap_budget = float(cc.get("gap_scan_budget_sec", 1800))
        self.handover = str(cc.get("rpc_handover") or self.HANDOVER_DEFAULT.get(chain) or nd9.get("handover") or "adopt").lower()
        self.lanes_cfg = cc.get("rpc_lanes")
        caps9 = dict(nd9["caps"])
        self.logs_fallback = dict(nd9["fallback"])
        self.logs_primary = [u for u in self.logs_rpcs if u not in self.logs_fallback]
        self._log_caps = dict(caps9)
        self._log_caps_static = dict(caps9)
        self._log_caps_at = time.time()
        self.addr_max = nd9["addr_max"]
        mc9 = nd9["multicall3"]
        self.mc_l1_block = bool(nd9.get("mc_l1_block"))
        self.multicall = str(mc9).lower() if (mc9 and str(mc9).lower().startswith("0x") and len(str(mc9)) == 42) else None
        bb9 = cc.get("rpc_backfill_budget_sec")
        self.bk_budget = float(bb9) if isinstance(bb9, (int, float)) and not isinstance(bb9, bool) else None
        try:
            self.poll_sec = min(max(float(cc.get("poll_sec") or cfg.get("evm_poll_sec") or 45), 5.0), 300.0)
        except (TypeError, ValueError):
            self.poll_sec = 45.0
        self.trace_mode = str(cc.get("rpc_trace") or "").lower() or None
        self.bk_span = max(1000, int(cc.get("rpc_backfill_span", 200_000)))
        self.block_trace = bool(cc.get("rpc_block_trace", True))
        self.cursor_path = paths.state(f"cursor_evm_{chain}.json")
        self.cursor = statefile.read_json(self.cursor_path, {})
        self.emitted_path = paths.state(f"emitted_evm_{chain}.json")
        self.emitted = set(statefile.read_json(self.emitted_path, []))
        new_view_wallets(self)
        self.since = {}
        for w9 in cfg.get("wallets") or []:
            a9 = str(w9.get("address") or "").lower()
            if w9.get("chain") == chain and a9 in self.wallets and w9.get("since_block") is not None:
                try:
                    st9 = w9.get("since_state") or [0, "0"]
                    self.since[a9] = (int(w9["since_block"]), int(st9[0]), str(int(st9[1])))
                except (TypeError, ValueError, IndexError):
                    continue
        self.pending_detail = {}
        self.rpc_meta_path = paths.state(f"rpc_token_meta_{chain}.json")
        self.rpc_meta = statefile.read_json(self.rpc_meta_path, {})
        self.sym_path = paths.state(f"rpc_token_sym_{chain}.json")
        self.sym = statefile.read_json(self.sym_path, {})
        self.progress = bf_engine.progress("evm")
        try:
            jobs9 = self._bk_jobs()
            if jobs9:
                dn9, tt9 = self._bk_lane(jobs9)
                self.progress.update(f"{chain}:rpc", phase="extend", unit="blocks", done=dn9, total=tt9,
                                     note="재기동 — 뒤 차선 이어서")
        except (TypeError, ValueError, KeyError) as e9:
            log.warning("%s 뒤 차선 진행률 기동 표시 실패(첫 사이클 뒤 표시): %s", chain, type(e9).__name__)
        self._pref = None
        self._txmeta = {}
        self._st_memo = {}
        self._bal_memo = {}
        self._snap_memo = {}
        self.last_scan_metrics = {}

    def _order(self, urls):
        ok = [u for u in urls if not bf_engine.gate(u).is_open()]
        ready = [u for u in ok if not bf_engine.gate(u).resting()]
        return (ready + [u for u in ok if u not in ready]) if ok else list(urls)

    def _node_order(self, urls):
        order = self._order(urls)
        if not self.__dict__.get("_key_ctx"):
            return self._sel_order(urls, order)
        try:
            import nodekeys
            key9 = [u for u in order if nodekeys.is_key_node(u) and not bf_engine.gate(u).is_open() and not bf_engine.gate(u).resting()]
        except Exception:   # noqa: BLE001 [fallback]
            return order
        if not key9 or len(key9) == len(order):
            return order
        return key9 + [u for u in order if u not in key9]

    def _sel_via(self) -> str:
        try:
            import nodesel
            return nodesel.via(self.chain)
        except Exception:   # noqa: BLE001 [fallback]
            return ""

    def _sel_lane(self, remaining):
        try:
            import nodesel
            it9 = self.progress.items.get(f"{self.chain}:rpc") or {}
            nodesel.lane_eta(self.chain, it9.get("eta_sec") if remaining else 0, remaining)
        except Exception:   # noqa: BLE001 [optional]
            pass

    def _sel_order(self, urls, order):
        try:
            import nodesel
            role9 = "state" if list(urls) == list(self.state_rpcs) and list(urls) != list(self.cfg_rpcs) else "detail"
            bf9 = bf_engine.burst_on()
            new9 = nodesel.order(self.chain, role9, urls, base=order, key_first=bf9 and nodesel.bf_key_first(self.chain))
            if not nodesel.enabled():
                nodesel.shadow(self.chain, role9, "bf" if bf9 else "rt", order, new9)
                return order
            return new9
        except Exception:   # noqa: BLE001 [fallback]
            return order

    def _rpc_call(self, method: str, params: list):
        if self._pref is not None:
            k = (method, json.dumps(params, sort_keys=True))
            if k in self._pref:
                return self._pref[k]
        last = None
        for url in self._order(self.cfg_rpcs):
            kw9 = self._rpc_kw(25)
            if kw9 is None:
                raise self._rpc_budget_err(last)
            try:
                r = bf_engine.rpc_call(url, method, params, allow_null=True, **kw9)
            except Exception as e:  # noqa: BLE001 [isolate]
                last = e
                continue
            if r is not None:
                return r
            last = RuntimeError(f"rpc {method}: result null")
        raise last if last else RuntimeError("rpc 미구성")

    RPC_MIN_LEFT = 1.0

    def _rpc_budget(self, dl):
        return _RpcBudget(self, dl)

    def _rpc_kw(self, cap: float):
        dl = self.__dict__.get("_rdl")
        if dl is None:
            return {"timeout": cap, "retries": 1}
        left = float(dl) - time.time()
        if left < self.RPC_MIN_LEFT:
            return None
        return {"timeout": min(float(cap), left), "retries": 1, "deadline": bf_engine.time.time() + left, "sem_timeout": left}

    @staticmethod
    def _rpc_budget_err(last=None):
        return bf_engine.NetError("budget: 상세 예산 소진 — 다음 사이클(마감 지나 다음 노드·조각 시작 안 함)"
                                  + (f" · 앞 노드: {logs.safe_err(last)[:60]}" if last is not None else ""), "budget")

    def _batch(self, calls: list, urls: list = None) -> list:
        last, all_bad = None, None
        for url in self._node_order(urls or self.cfg_rpcs):
            if self._rpc_kw(30) is None:
                raise self._rpc_budget_err(last)
            try:
                out = []
                cap = bf_engine.gate(url).batch_cap(40)
                for i in range(0, len(calls), cap):
                    kw9 = self._rpc_kw(30)
                    if kw9 is None:
                        raise self._rpc_budget_err(last)
                    out += bf_engine.rpc_batch(url, calls[i:i + cap], **kw9)
                if out and all(isinstance(r, Exception) for r in out):
                    all_bad = out
                    continue
                return out
            except Exception as e:  # noqa: BLE001 [fallback]
                last = e
        if all_bad is not None:
            return all_bad
        raise last if last else RuntimeError("rpc 미구성")

    def _head(self) -> int:
        h = int(self._rpc_call("eth_blockNumber", []), 16)
        self._log_head = h
        if self.chain_id is not None and not getattr(self, "_cid_ok", False):
            cid = int(self._rpc_call("eth_chainId", []), 16)
            if cid != self.chain_id:
                raise ChainDisabled(f"{self.chain}: RPC chainId 불일치 {cid} ≠ {self.chain_id} — 설정 확인")
            self._cid_ok = True
        return h

    def _states(self, pairs, strict: bool = False) -> dict:
        need = [p for p in dict.fromkeys(pairs) if p not in self._st_memo]
        if need:
            calls = []
            for w, b in need:
                calls += [("eth_getTransactionCount", [w, hex(b)]), ("eth_getBalance", [w, hex(b)])]
            got = {}
            last = None
            order9 = self._node_order(self.state_rpcs)
            transient9 = {}
            refused9 = self._key_resting(order9)
            for url in order9:
                todo = [p for p in need if p not in got]
                if not todo:
                    break
                cl = []
                for w, b in todo:
                    cl += [("eth_getTransactionCount", [w, hex(b)]), ("eth_getBalance", [w, hex(b)])]
                try:
                    res = []
                    cap = bf_engine.gate(url).batch_cap(40)
                    for i in range(0, len(cl), cap):
                        res += bf_engine.rpc_batch(url, cl[i:i + cap], timeout=30, retries=1)
                except Exception as e:  # noqa: BLE001 [isolate]
                    last = e
                    if refused9 is None and self._refused(e):
                        refused9 = e
                    if strict and getattr(e, "kind", None) != "pruned":
                        for p in todo:
                            transient9.setdefault(p, e)
                    continue
                for j, p in enumerate(todo):
                    n9, b9 = res[2 * j], res[2 * j + 1]
                    if isinstance(n9, Exception) or isinstance(b9, Exception):
                        last = n9 if isinstance(n9, Exception) else b9
                        if refused9 is None and self._refused(last):
                            refused9 = last
                        if strict:
                            for err9 in (n9, b9):
                                if isinstance(err9, Exception) and getattr(err9, "kind", None) != "pruned":
                                    transient9.setdefault(p, err9)
                                    break
                        continue
                    got[p] = (int(n9, 16), int(b9, 16))
            if strict:
                unchecked9 = [u for u in self.state_rpcs if u not in order9]
                for p in need:
                    if p not in got and p in transient9:
                        raise transient9[p]
                    if p not in got and unchecked9:
                        raise bf_engine.NetError(f"{self.chain} 블록 {p[1]} 상태 — 노드 {len(unchecked9)}곳 서킷으로 미확인(다음 사이클)", "circuit")
            for p in need:
                if p not in got:
                    kind = getattr(last, "kind", None)
                    if (kind == "pruned" or last is None) and refused9 is not None and self.__dict__.get("_e4_ctx") and not self._near_head(p[1]):
                        raise HoldError(f"{self.chain} 블록 {p[1]} 상태 — 아카이브(키) 노드가 한도·서킷으로 쉬는 중이라 미확인(커서 유지 · 다음 사이클): "
                                        f"{logs.safe_err(refused9)[:100]}")
                    if kind == "pruned" or last is None:
                        e9 = StateUnavailable(f"{self.chain} 블록 {p[1]} 상태 없음(비아카이브): {str(last)[:120]}")
                        e9.blk = int(p[1])
                        raise e9
                    raise last
            self._st_memo.update(got)
            if len(self._st_memo) > self.ST_MEMO_MAX:
                keep9 = set(pairs)
                for k9 in list(self._st_memo)[:len(self._st_memo) - self.ST_MEMO_KEEP]:
                    if k9 not in got and k9 not in keep9:
                        self._st_memo.pop(k9, None)
        return {p: self._st_memo[p] for p in pairs}

    ST_MEMO_MAX = 20000
    ST_MEMO_KEEP = 15000

    @staticmethod
    def _refused(e) -> bool:
        return bool(getattr(e, "local", False)) or getattr(e, "kind", None) in ("quota", "budget", "circuit")

    def _key_resting(self, order9: list):
        try:
            import nodekeys
            off9 = [u for u in self.state_rpcs if u not in order9 and nodekeys.is_key_node(u)]
        except Exception:   # noqa: BLE001 [fallback]
            return None
        if not off9:
            return None
        return bf_engine.NetError(f"키 노드 {len(off9)}곳 서킷으로 쉬는 중", "circuit")

    def _near_head(self, blk) -> bool:
        hd9 = self.__dict__.get("_log_head")
        if type(hd9) is not int:
            sf9 = self.__dict__.get("_st_safe")
            if type(sf9) is not int:
                return False
            hd9 = int(sf9) + int(self.conf_depth or 0)
        return int(hd9) - int(blk) <= max(64, self.STATE_LAG_NEAR * max(1, int(self.conf_depth or 0)))

    def _st_memo_trim(self) -> None:
        m9 = self.__dict__.get("_st_memo")
        s9 = self.__dict__.get("_st_safe")
        if not isinstance(m9, dict) or type(s9) is not int:
            self._st_memo = {}
            return
        self._st_memo = {k: v for k, v in m9.items() if isinstance(k, tuple) and len(k) == 2 and type(k[1]) is int and k[1] <= s9}

    @property
    def bk_mode(self) -> bool:
        return isinstance(self.cursor.get("_handover"), dict) and self.lanes_cfg is not False

    def _trace_want(self, h: str, snap: dict) -> bool:
        mode9 = self.trace_mode or ("own" if self.bk_mode else "all")
        if mode9 != "own":
            return True
        if h in (self.cursor.get("_hq") or {}):
            return True
        tx = snap.get("tx") or {}
        if self.trace_mode is None and tx.get("status") == "ok" and self._nobase_at(snap):
            return True
        if tx.get("status") != "ok" or (tx.get("from") or "").lower() not in set(self.wallets):
            return False
        inp = str(tx.get("raw_input") or "0x").lower()
        return len(inp) >= 10 and inp[:10] not in self.TRACE_SKIP_SELECTORS

    def _nobase_at(self, snap: dict) -> bool:
        try:
            blk = int((snap.get("tx") or {}).get("block_number") or 0)
        except (TypeError, ValueError):
            return False
        ns9, bk9 = self.cursor.get("_ns") or {}, self.cursor.get("_bkns") or {}
        for w in self.wallets:
            if not self._touches(snap, w):
                continue
            c9 = self.cursor.get(w)
            if type(c9) is int and blk > c9:
                b9 = ns9.get(w)
                if not isinstance(b9, list) or not b9 or int(b9[0]) != c9:
                    return True
            j9 = self.cursor.get("_bk:" + w)
            if isinstance(j9, dict) and type(j9.get("done")) is int and int(j9["done"]) < blk <= int(j9.get("to") or 0):
                b9 = bk9.get(w)
                if not isinstance(b9, list) or not b9 or int(b9[0]) != int(j9["done"]):
                    return True
        return False

    def _details(self, hashes, deadline: float = None, trace: bool = True, late: bool = False, pref_only: bool = False) -> dict:
        late = bool(late or self.__dict__.get("_late_ctx"))
        out = {}
        hs = [h for h in dict.fromkeys(hashes) if h]
        myset = set(self.wallets)
        rdl9 = self.__dict__.get("_rdl")
        edl9 = deadline if rdl9 is None else (rdl9 if deadline is None else min(float(deadline), float(rdl9)))
        rb9 = self._rpc_budget(deadline) if deadline is not None else None
        if rb9 is not None:
            rb9.__enter__()
        try:
            self._details_fetch(hs, out, edl9, myset, pref_only)
            self._fill_symbols([s for s in out.values() if isinstance(s, dict)])
        finally:
            if rb9 is not None:
                rb9.__exit__(None, None, None)
        self._details_trace(out, deadline, trace, late)
        return out

    def _details_fetch(self, hs: list, out: dict, edl9, myset: set, pref_only: bool = False) -> None:
        stop9 = False
        for i in range(0, len(hs), self.detail_batch):
            chunk = hs[i:i + self.detail_batch]
            if stop9 or (edl9 is not None and time.time() > edl9):
                for h in hs[i:]:
                    out[h] = RuntimeError("상세 예산 소진 — 다음 사이클")
                break
            pref = {}

            def put(m, p, r):
                if r is not None and not isinstance(r, Exception):
                    pref[(m, json.dumps(p, sort_keys=True))] = r
            bfail9 = False
            try:
                calls = []
                for h in chunk:
                    calls += [("eth_getTransactionByHash", [h]), ("eth_getTransactionReceipt", [h])]
                bfail9 = True
                res = self._batch(calls)
                bfail9 = bool(res) and all(isinstance(r, Exception) for r in res)
                for (m, p), r in zip(calls, res):
                    put(m, p, r)
                rcs = [r for (m, _p), r in zip(calls, res) if m == "eth_getTransactionReceipt" and isinstance(r, dict)]
                blks = sorted({r["blockNumber"] for r in rcs if r.get("blockNumber")})
                if blks:
                    bc = [("eth_getBlockByNumber", [b9, False]) for b9 in blks]
                    for (m, p), r in zip(bc, self._batch(bc)):
                        put(m, p, r)
                cas = set()
                skip9 = set(self.NATIVE_MIRROR.get(self.chain) or ()) | {self.NATIVE_EMITTER.get(self.chain)}
                for rc in rcs:
                    for lg in rc.get("logs") or []:
                        tps = lg.get("topics") or []
                        if len(tps) == 3 and (tps[0] or "").lower() == self.TRANSFER and (
                                ("0x" + tps[1][-40:]).lower() in myset or ("0x" + tps[2][-40:]).lower() in myset):
                            cas.add((lg.get("address") or "").lower())
                cas -= skip9
                nd9 = self._nodec_reg()
                dc = [("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"]) for ca in sorted(cas)
                      if ca and ca not in self.rpc_meta and not nd9.perm(ca)]
                if dc:
                    for (m, p), r in zip(dc, self._batch(dc)):
                        put(m, p, r)
            except Exception as e:  # noqa: BLE001 [isolate]
                log.info("%s 상세 배치 실패 → 단건 경로: %s", self.chain, str(e)[:100])
            self._pref = pref
            try:
                for k9, h in enumerate(chunk):
                    if pref_only and bfail9 and not self._pref_has(h):
                        continue
                    if edl9 is not None and time.time() > edl9 and not self._pref_has(h):
                        for h9 in chunk[k9:]:
                            out.setdefault(h9, RuntimeError("상세 예산 소진 — 다음 사이클"))
                        stop9 = True
                        break
                    try:
                        snap = self._rpc_synth_detail(h)
                        tx = self._rpc_call("eth_getTransactionByHash", [h]) or {}
                        self._txmeta[h] = {"nonce": int(tx.get("nonce") or "0x0", 16),
                                           "from": (tx.get("from") or "").lower(), "to": (tx.get("to") or "").lower(),
                                           "block": snap["tx"]["block_number"]}
                        out[h] = snap
                    except Exception as e:  # noqa: BLE001 [fallback]
                        out[h] = e
            finally:
                self._pref = None
            if pref_only and bfail9:
                break

    def _pref_has(self, h: str) -> bool:
        p9 = self._pref or {}
        return (("eth_getTransactionByHash", json.dumps([h], sort_keys=True)) in p9
                and ("eth_getTransactionReceipt", json.dumps([h], sort_keys=True)) in p9)

    def _details_trace(self, out: dict, deadline, trace: bool, late: bool) -> None:
        if self.trace_rpcs and trace:
            brk9, nbrk9 = None, 0
            tdl9 = deadline if deadline is not None else (self.__dict__.get("_tdl") or time.time() + self.TRACE_CALL_CAP_SEC)
            ctx9 = late or bool(self.__dict__.get("_peek_ctx"))
            nf9 = 0
            for h, snap in list(out.items()):
                if isinstance(snap, dict) and self._trace_want(h, snap):
                    if time.time() >= tdl9 or nf9 >= self.TRACE_SICK_N or (ctx9 and self._trace_sick()):
                        nbrk9 += 1
                        self._trace_late_add(h)
                        continue
                    try:
                        if brk9 is not None:
                            raise brk9
                        with self._trace_budget(tdl9):
                            self._trace_internal(h, snap)
                        nf9 = 0
                    except Exception as e:  # noqa: BLE001 [fallback]
                        if isinstance(e, TraceDeferred):
                            nbrk9 += 1
                            self._trace_late_add(h)
                            continue
                        if brk9 is None and late and not self._trace_gone(e):
                            brk9 = e
                        elif brk9 is not None and e is brk9:
                            nbrk9 += 1
                            self._trace_late_add(h)
                            continue
                        if self._trace_gone(e):
                            log.info("%s trace 불가(과거 상태 없음·미지원) — internal 없이 확정 %s: %s", self.chain, h[:12], logs.safe_err(e)[:80])
                            continue
                        nf9 += 1
                        n9 = self._trace_fail[h] = self._trace_fail.get(h, 0) + 1
                        if n9 < self.TRACE_RETRY and not late:
                            out[h] = RuntimeError(f"trace 실패 {n9}회(재시도): {logs.safe_err(e)[:100]}")
                        else:
                            self._trace_late_add(h)
                            getattr(log, "info" if late else "warning")("%s trace %d회 실패 — internal 없이 확정 · 나중에 다시(늦은 채움) %s: %s",
                                                                        self.chain, n9, h[:12], logs.safe_err(e)[:80])
            if nbrk9:
                log.info("%s trace 노드 일시 막힘 — 이 걸음 남은 %d건은 trace 없이 늦은 채움으로(다음 사이클부터 백오프 재시도)", self.chain, nbrk9)


    TRACE_SICK_N = 2
    TRACE_CALL_CAP_SEC = 120


    TRACE_RETRY = 3


    @staticmethod
    def _dec_symbol(r):
        try:
            b = bytes.fromhex((r or "0x")[2:])
            if len(b) == 32:
                return b.rstrip(b"\x00").decode("utf-8", "ignore").strip() or None
            if len(b) >= 64:
                ln = int.from_bytes(b[32:64], "big")
                return b[64:64 + ln].decode("utf-8", "ignore").strip() or None
        except (ValueError, TypeError):
            pass
        return None

    def _fill_symbols(self, snaps):
        need = sorted({(tt.get("token") or {}).get("address") for s in snaps for tt in s.get("token_transfers") or []}
                      - set(self.sym) - {None, ""})
        if need:
            try:
                calls = [("eth_call", [{"to": ca, "data": "0x95d89b41"}, "latest"]) for ca in need]
                for ca, r in zip(need, self._batch(calls)):
                    if not isinstance(r, Exception):
                        self.sym[ca] = (self._dec_symbol(r) or "")[:16]
                statefile.atomic_write_json(self.sym_path, self.sym)
            except Exception as e:  # noqa: BLE001 [optional]
                log.info("%s 토큰 심볼 조회 실패(무시): %s", self.chain, str(e)[:80])
        for s in snaps:
            for tt in s.get("token_transfers") or []:
                tok = tt.get("token") or {}
                if not tok.get("symbol") and self.sym.get(tok.get("address")):
                    tok["symbol"] = self.sym[tok["address"]]


    LANES_LEAF_QUIET_SEC = 600


    STATE_LAG_NEAR = 10


    def _window_start(self, safe: int) -> int:
        lo = min(max(0, self.start_block), int(safe))
        if self.backfill_full:
            return lo
        tgt = [time.time() - self.backfill_months * 30 * 86400] if self.backfill_months > 0 else []
        s9 = bf_engine.SINCE.target(self.chain)
        if s9:
            tgt.append(s9)
        if not tgt:
            return safe
        if lo and self._block_ts(lo) >= int(min(tgt)):
            return lo
        return max(lo, bf_engine.block_at_ts(self._block_ts, int(min(tgt)), 0, int(safe)))

    def _since_reinit(self, safe: int):
        if self.cursor.get("_rpc_v") != self.VERSION or self.backfill_full or isinstance(self.cursor.get("_since_ext"), dict):
            return
        s9 = bf_engine.SINCE.target(self.chain)
        if not s9 or self.cursor.get("_since_seen") == int(s9):
            return
        if self.bk_mode:
            self._since_reinit_bk(safe, int(s9))
            return
        if self.lanes_cfg is not False and not self.backfill_full:
            self._since_reinit_bk(safe, int(s9), promote=True)
            return
        old = int(self.cursor.get("_start") or 0)
        new = self._window_start(safe) if old > max(0, self.start_block) else old
        ws = [w for w in self.wallets if isinstance(self.cursor.get(w), int)]
        if new >= old or not ws:
            self.cursor["_since_seen"] = int(s9)
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            return
        sk9 = self.cursor.get("_since_skip")
        if isinstance(sk9, dict) and sk9.get("target") == int(s9) and time.time() - float(sk9.get("at") or 0) < 6 * 3600:
            return
        try:
            st0 = self._states([(w, new) for w in ws])
        except StateUnavailable as e:
            st0, err9 = {}, logs.safe_err(e)[:120]
        else:
            err9 = None if all((w, new) in st0 for w in ws) else "일부 지갑 상태 누락"
        if err9:
            self.cursor["_since_skip"] = {"target": int(s9), "at": int(time.time()), "err": err9}
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.warning("%s 과거 창 확장 보류(시작 블록 %d 상태 조회 불가 — 아카이브 노드 필요, 6시간 뒤 재시도): %s", self.chain, new, err9)
            return
        self.cursor.pop("_since_skip", None)
        ts9 = time.strftime("%Y%m%d_%H%M%S")
        statefile.atomic_write_json(self.cursor_path + f".pre_since_{ts9}", self.cursor)
        ns = self.cursor.setdefault("_ns", {})
        self.cursor["_since_ext"] = {"from": int(new), "to": old, "at": int(time.time()),
                                     "live": {w: int(self.cursor[w]) for w in ws}, "ns": {w: ns.get(w) for w in ws}}
        for w in ws:
            self.cursor[w] = int(new)
            if (w, new) in st0:
                n9, b9 = st0[(w, new)]
                ns[w] = [int(new), n9, str(b9), 0, "0"]
            else:
                ns.pop(w, None)
        self.cursor.pop("_scan", None)
        self.cursor["_start"] = int(new)
        self.cursor["_since_seen"] = int(s9)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        log.warning("★%s 과거 창 확장(backfill_since %s): 앞 구간 블록 %d → %d 만 훑음(지갑 %d · 보존본 .pre_since_%s)★",
                    self.chain, time.strftime("%Y-%m-%d", time.gmtime(s9)), new, old, len(ws), ts9)

    def _since_reinit_bk(self, safe: int, s9: int, promote: bool = False):
        if self._bk_jobs():
            return
        old = int(self.cursor.get("_start") or 0)
        new = self._window_start(safe) if old > max(0, self.start_block) else old
        ws = [w for w in self.wallets if isinstance(self.cursor.get(w), int)]
        if new >= old or not ws:
            self.cursor["_since_seen"] = int(s9)
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            return
        sk9 = self.cursor.get("_since_skip")
        if isinstance(sk9, dict) and sk9.get("target") == int(s9) and time.time() - float(sk9.get("at") or 0) < 6 * 3600:
            return
        try:
            b0 = self._baselines(ws, new)
            err9 = None if all(w in b0 for w in ws) else "일부 지갑 상태 누락"
        except StateUnavailable as e:
            b0, err9 = {}, logs.safe_err(e)[:120]
        if err9:
            self.cursor["_since_skip"] = {"target": int(s9), "at": int(time.time()), "err": err9}
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.warning("%s 과거 창 확장 보류(시작 블록 %d 상태 조회 불가, 6시간 뒤 재시도): %s", self.chain, new, err9)
            return
        self.cursor.pop("_since_skip", None)
        if promote and not isinstance(self.cursor.get("_handover"), dict):
            self.cursor["_handover"] = {"from": "extend", "at": int(time.time()), "live": min(int(self.cursor[w]) for w in ws), "start": int(old),
                                        "bk_from": int(new), "overlap": 0, "adopted": 0, "new": 0, "internal": 0, "extend": len(ws), "hq": 0,
                                        "src_min": None, "src_max": None, "curs": {}}
        bkns = self.cursor.setdefault("_bkns", {})
        for w in ws:
            self.cursor["_bk:" + w] = {"from": int(new), "to": int(old), "done": int(new), "why": "extend"}
            bkns[w] = b0[w]
        self.cursor["_start"] = int(new)
        self.cursor["_since_seen"] = int(s9)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        log.warning("★%s 과거 창 확장(backfill_since %s): 앞 구간 블록 %d → %d 를 뒤 차선으로(지갑 %d · 라이브 꼬리는 계속)★",
                    self.chain, time.strftime("%Y-%m-%d", time.gmtime(s9)), new, old, len(ws))

    def _since_ext_done(self):
        ext9 = self.cursor.get("_since_ext")
        ns = self.cursor.setdefault("_ns", {})
        for w, v in (ext9.get("live") or {}).items():
            self.cursor[w] = int(v)
            b9 = (ext9.get("ns") or {}).get(w)
            if b9 is None:
                ns.pop(w, None)
            else:
                ns[w] = b9
        self.cursor.pop("_since_ext", None)
        self.cursor.pop("_scan", None)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        log.info("%s 과거 창 확장(앞 구간 %d → %d) 완주 — 지갑 커서 복원", self.chain, int(ext9.get("from") or 0), int(ext9.get("to") or 0))


    def _es_late_overlap(self, cc: dict) -> int:
        if not cc.get("etherscan_chainid"):
            return 0
        try:
            sec = max(60, int(((self.cfg.get("etherscan") or {}).get("int_lag_sec")) or EtherscanWatcher.INT_LAG_SEC))
        except (TypeError, ValueError):
            sec = EtherscanWatcher.INT_LAG_SEC
        if not cc.get("trace_rpcs"):
            sec = min(sec, self.ES_OVERLAP_NOARCH_SEC)
        return max(int(self.conf_depth or 12), -(-int(self.bpd or 7200) * sec // 86400))

    ES_OVERLAP_NOARCH_SEC = 3600

    LANES_RECENT_SEC = 48 * 3600

    def _lanes_recent_blocks(self) -> int:
        cc = (self.cfg.get("chains") or {}).get(self.chain) or {}
        try:
            sec = float(cc.get("rpc_lanes_recent_hours")) * 3600 if cc.get("rpc_lanes_recent_hours") is not None else float(self.LANES_RECENT_SEC)
        except (TypeError, ValueError):
            sec = float(self.LANES_RECENT_SEC)
        return max(int(self.conf_depth or 12), -(-int(self.bpd or 7200) * int(max(0.0, sec)) // 86400))

    def _lanes_baselines(self, ws, live: int, safe: int) -> tuple:
        ns = self._baselines(list(ws), int(live))
        miss = [w for w in ws if w not in ns]
        if not miss or int(live) >= int(safe):
            return int(live), ns
        w0 = miss[0]

        def has(b):
            try:
                self._states([(w0, int(b))])
                return True
            except StateUnavailable:
                return False
        if not has(safe):
            return int(live), ns
        lo, hi = int(live), int(safe)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if has(mid):
                hi = mid
            else:
                lo = mid
        f9 = min(int(safe), hi + max(2, int(self.conf_depth or 12)))
        ns2 = self._baselines(list(ws), f9)
        log.warning("%s 라이브 시작 기준점 — 블록 %d 상태 없음(비아카이브) → 상태 보관 구간 %d 부터 라이브(정합) · 그 앞 %d블록은 로그만 먼저 + 뒤 차선",
                    self.chain, int(live), f9, f9 - int(live))
        return f9, ns2

    def _sweep_add(self, frm: int, to: int):
        if int(to) <= int(frm):
            return
        sw = self.cursor.get("_sweep") if isinstance(self.cursor.get("_sweep"), dict) else None
        if sw and type(sw.get("from")) is int and type(sw.get("to")) is int:
            frm, to = min(int(frm), int(sw["from"])), max(int(to), int(sw["to"]))
        self.cursor["_sweep"] = {"from": int(frm), "to": int(to), "n": 0}

    def _adopt_explorer(self, safe: int, fresh: bool = False):
        old = dict(self.cursor)
        cc = self.cfg["chains"][self.chain]
        start = self._window_start(safe)
        ov = max(0, min(int(cc.get("rescan_overlap_blocks") or 0), 5000))
        ov = max(ov, self._es_late_overlap(cc))
        curs = {w: int(old[w]) for w in self.wallets if isinstance(old.get(w), int) and not isinstance(old.get(w), bool)}
        xcurs9 = {k: v for k, v in old.items() if not str(k).startswith("_") and isinstance(v, int) and not isinstance(v, bool)} if fresh else None
        if fresh:
            curs = {}
        live = max(int(start), min(min(curs.values()) - ov, int(safe))) if curs else \
            (max(int(start), int(safe) - self._lanes_recent_blocks()) if fresh else int(safe))
        ipm = old.get("_ext_internal_pending") if isinstance(old.get("_ext_internal_pending"), dict) else {}
        rr0 = [r for r in (ipm.get("ranges") or []) if isinstance(r, dict) and not r.get("done")]
        leaf9 = [r for r in rr0 if r.get("kind") == "leaf" and isinstance(r.get("wallet"), str) and type(r.get("to_block")) is int]
        rr = [r for r in rr0 if r.get("kind") != "leaf"]
        any_w = any(not isinstance(r.get("wallet"), str) or not r.get("wallet") for r in rr)
        int_ws = {w for w in curs if any_w or any(str(r.get("wallet") or "").lower() == w for r in rr)}
        fr9 = [int(r["from_block"]) for r in rr if isinstance(r.get("from_block"), int)]
        bk_from = min([int(start)] + fr9)
        if bk_from >= live:
            int_ws = set()
        jobs = {}
        for w in self.wallets:
            bj9 = old.get("_bfjob") if isinstance(old.get("_bfjob"), dict) else {}
            first9 = (w not in curs or ("_bfes:" + w) in old or ("_bf:" + w) in old
                      or (bj9.get("kind") != "extend" and w in [str(x).lower() for x in (bj9.get("wallets") or [])]))
            why = "new" if first9 else ("internal" if w in int_ws else None)
            to9 = live
            if why is None:
                cv9 = old.get("_cov:" + w)
                if isinstance(cv9, int) and not isinstance(cv9, bool) and cv9 > bk_from + 1:
                    why, to9 = "extend", min(int(cv9), live)
            if why and bk_from < to9:
                jobs[w] = {"from": bk_from, "to": int(to9), "done": bk_from, "why": why}
        hq = {}
        hqp9 = paths.state(f"hq_left_{self.chain}.json")
        for k9 in list((statefile.read_json(hqp9, {}) or {}).keys()) \
                + list((statefile.read_json(paths.state(f"enrich_{self.chain}.json"), {}) or {}).keys()) \
                + list((statefile.read_json(paths.state(f"pending_detail_{self.chain}.json"), {}) or {}).keys()) \
                + [h for h in (ipm.get("hashes") or []) if isinstance(h, str)] + list((ipm.get("items") or {}).keys()):
            if isinstance(k9, str) and k9.startswith("0x"):
                hq[k9.lower()] = 0
        if fresh:
            live0 = live
            live, ns = self._lanes_baselines(list(self.wallets), live, safe)
            if live > live0:
                for w9 in self.wallets:
                    if w9 in jobs:
                        jobs[w9]["to"] = int(live)
                    else:
                        jobs[w9] = {"from": int(live0), "to": int(live), "done": int(live0), "why": "new"}
                bk_from = min(int(bk_from), int(live0))
        else:
            ns = self._baselines(list(self.wallets), live)
        bkns = self._baselines(sorted(jobs), bk_from) if jobs else {}
        nobase9 = (len(set(self.wallets) - set(ns)), len(set(jobs) - set(bkns)))
        if fresh and any(nobase9):
            log.warning("%s 새 차선 초기화 — 기준점 없음 라이브 %d · 뒤 차선 %d(비아카이브 노드: 첫 확인 지점이 기준점 · 옛 구간 로그 없는 이동은 대사 흡수)",
                        self.chain, nobase9[0], nobase9[1])
        elif set(ns) != set(self.wallets) or set(bkns) != set(jobs):
            miss9 = len(set(self.wallets) - set(ns)) + len(set(jobs) - set(bkns))
            raise StateUnavailable(f"{self.chain} 인계 기준점 {miss9}건 없음(블록 {live}·{bk_from} 상태) — 탐색기 커서 유지, 아카이브 상태 노드 필요")
        bp = self.cursor_path + ".explorer_legacy"
        if os.path.exists(bp):
            bp += time.strftime("_%Y%m%d_%H%M%S")
        statefile.atomic_write_json(bp, old)
        if self.emitted:
            self.emitted.clear()
            statefile.atomic_write_json(self.emitted_path, [])
        cur = {"_rpc_v": self.VERSION, "_start": int(start), "_ns": ns, "_bkns": bkns,
               "_handover": {"from": "explorer" if curs else ("rescan" if xcurs9 else "fresh"), "at": int(time.time()), "live": int(live), "start": int(start),
                             "bk_from": int(bk_from), "overlap": ov, "adopted": len(curs), "new": sum(1 for j in jobs.values() if j["why"] == "new"),
                             "internal": sum(1 for j in jobs.values() if j["why"] == "internal"),
                             "extend": sum(1 for j in jobs.values() if j["why"] == "extend"), "hq": len(hq),
                             "src_min": min(curs.values()) if curs else None, "src_max": max(curs.values()) if curs else None,
                             "curs": dict(curs),
                             "backup": os.path.basename(bp)}}
        if fresh:
            cur["_handover"]["nobase"] = list(nobase9)
            cur["_xcurs"] = dict(xcurs9 or {})
            if live > live0:
                self.cursor = cur
                self._sweep_add(live0, live)
        for k9, v9 in old.items():
            if str(k9).startswith("_cov:") or k9 in ("_quarantine", "_detail_fail", "_q_released", "_wallets", "_reorg"):
                cur[k9] = v9
        if isinstance(old.get("_quarantine_left"), dict):
            q9 = cur["_quarantine"] if isinstance(cur.get("_quarantine"), dict) else cur.setdefault("_quarantine", {})
            for h9, v9 in old["_quarantine_left"].items():
                q9.setdefault(h9, v9)
        for w in self.wallets:
            cur[w] = int(live)
        for w, j in jobs.items():
            cur["_bk:" + w] = j
        if hq:
            cur["_hq"] = hq
        lln9 = {}
        for k9, v9 in (old.get("_leaf_later_left") or {}).items():
            if isinstance(v9, dict) and isinstance(v9.get("w"), str) and type(v9.get("blk")) is int and v9["w"].lower() in self.wallets:
                lln9[k9] = dict(v9, next=0)
        for r9 in leaf9:
            w9 = r9["wallet"].lower()
            if w9 in self.wallets:
                lln9.setdefault(f"{w9[:12]}:{int(r9['to_block'])}", {"w": w9, "blk": int(r9["to_block"]), "at": int(time.time()), "n": 0, "next": 0})
        if lln9:
            cur["_leaf_later"] = lln9
        if bf_engine.SINCE.target(self.chain):
            cur["_since_seen"] = int(bf_engine.SINCE.target(self.chain))
        self.cursor = cur
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        if hq:
            statefile.atomic_write_json(paths.state(f"enrich_{self.chain}.json"), {})
            if os.path.exists(hqp9):
                statefile.atomic_write_json(hqp9, {})
        if fresh:
            log.warning("★%s RPC 차선 모드로 시작(%s) — 라이브 = 블록 %d 부터(최근 창 · safe %d) · 옛 구간 %d → %d 는 뒤 차선(지갑 %d)★", self.chain,
                        cur["_handover"]["from"], live, safe, bk_from, live, len(jobs))
            return
        log.warning("★%s 탐색기 → RPC 전용 인계: 지갑 커서 %d개 이어받음(%s~%s → 라이브 %d, 겹침 %d) · 새 지갑 첫 백필 %d · internal 재훑기 %d"
                    "(블록 %d → %d, 뒤 차선) · 인계 큐 %d건 · 원본 %s★", self.chain, len(curs), cur["_handover"]["src_min"],
                    cur["_handover"]["src_max"], live, ov, cur["_handover"]["new"], cur["_handover"]["internal"], bk_from, live, len(hq),
                    os.path.basename(bp))

    PEEK_SEC = 900

    def _head_peek(self, head: int, safe: int, deadline: float) -> int:
        ws = [w for w in self.wallets if type(self.cursor.get(w)) is int]
        if not ws:
            return 0
        cmin = min(int(self.cursor[w]) for w in ws)
        p0 = self.cursor.get("_peek_to")
        dirty = False
        if type(p0) is int and cmin >= int(p0):
            self.cursor.pop("_peek_to", None)
            p0, dirty = None, True
        wd9 = self.cursor.get("_peek_wdone")
        if isinstance(wd9, dict) and wd9 and all(type(v) is int and cmin >= v for v in wd9.values()):
            self.cursor.pop("_peek_wdone", None)
            dirty = True
        dl = min(deadline, time.time() + max(5.0, min(30.0, self.cycle_budget / 4.0)))
        win = max(1, -(-int(self.bpd or 7200) * self.PEEK_SEC // 86400))
        lh9 = self.cursor.get("_leaf_hold") if isinstance(self.cursor.get("_leaf_hold"), dict) else {}
        held9 = bool(lh9.get("held")) and time.time() - int(lh9.get("last") or 0) < self.LANES_LEAF_QUIET_SEC
        n = 0
        frm = max(cmin, int(safe) - win, int(p0) if type(p0) is int else 0)
        if (int(safe) - cmin > win or held9) and frm < int(safe):
            n9, last, bad9, dets = self._peek_logs(frm, int(safe), dl, head)
            n, dirty = n + n9, True
            if last > frm:
                nat9 = self._peek_native(ws, frm, last, dets, head, dl)
                n += nat9[1]
                adv = last if bad9 is None else max(frm, min(last, bad9 - 1))
                if nat9[0] == "fail":
                    adv = frm
                if adv > frm:
                    self.cursor["_peek_to"] = int(adv)
                if n:
                    log.info("%s 최신 블록 엿보기 — 블록 %d → %d 에서 %d건 먼저 방출(라이브 차선 커서 %d 따라잡는 중 · 네이티브 %s%s)", self.chain, frm, last, n, cmin,
                             nat9[0], f" · 상세 실패 재시도 블록 {bad9}" if bad9 is not None else "")
        sw = self.cursor.get("_sweep") if isinstance(self.cursor.get("_sweep"), dict) else None
        if sw and type(sw.get("from")) is int and type(sw.get("to")) is int and time.time() < dl:
            f9, t9 = int(sw["from"]), int(sw["to"])
            if f9 < t9:
                n9, last, bad9, _d9 = self._peek_logs(f9, t9, dl, head)
                n, dirty = n + n9, True
                if last > f9:
                    if bad9 is not None and int(sw.get("n") or 0) < 5:
                        sw["n"] = int(sw.get("n") or 0) + 1
                        last = max(f9, min(last, bad9 - 1))
                    else:
                        sw["n"] = 0
                    sw["from"] = int(last)
            if int(sw["from"]) >= t9:
                self.cursor.pop("_sweep", None)
                dirty = True
                log.info("%s 최근 창 앞부분 로그 입금 먼저 받기 끝(블록 → %d)", self.chain, t9)
        if dirty:
            statefile.atomic_write_json(self.cursor_path, self.cursor)
        return n

    def _peek_logs(self, frm: int, to: int, dl: float, head: int) -> tuple:
        found, last, _f9 = self._scan_logs(list(self.wallets), int(frm), int(to), dl)
        self._scan_floor = None
        if last <= frm:
            return 0, int(frm), None, {}
        q9 = bf_engine.quarantine_map(self.cursor)
        hs = sorted((h for h in found if h not in self.emitted and h not in q9), key=lambda x: (found[x], x))
        dets = self._details(hs, deadline=dl + 30) if hs else {}
        n, bad = 0, None
        self._trace_later_pre([h for h in hs if isinstance(dets.get(h), dict)], dets)
        for h in hs:
            s9 = dets.get(h)
            if isinstance(s9, dict):
                if any(self._touches(s9, w) for w in self.wallets):
                    self._emit(h, s9, head)
                    n += 1
            else:
                bad = int(found[h]) if bad is None else min(bad, int(found[h]))
        if n:
            statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        self._trace_late_settle([h for h in hs if isinstance(dets.get(h), dict)])
        return n, int(last), bad, dets

    def _peek_native(self, ws: list, frm: int, last: int, dets: dict, head: int, dl: float) -> tuple:
        wd = self.cursor.get("_peek_wdone") if isinstance(self.cursor.get("_peek_wdone"), dict) else {}
        starts = {}
        for w in ws:
            s9 = wd.get(w)
            starts[w] = int(s9) if (type(s9) is int and int(frm) < int(s9) < int(last)) else int(frm)
            if type(s9) is int and int(s9) >= int(last):
                starts[w] = None
        base = {}
        try:
            for st9 in sorted({v for v in starts.values() if v is not None}):
                base.update(self._baselines([w for w in ws if starts[w] == st9], st9))
        except Exception as e:  # noqa: BLE001 [fallback]
            log.info("%s 엿보기 네이티브 기준점 실패(다음 사이클): %s", self.chain, logs.safe_err(e)[:100])
            return "fail", 0
        todo = [w for w in ws if starts[w] is not None and w in base]
        nostate = [w for w in ws if starts[w] is not None and w not in base]
        if not todo:
            return ("nostate" if nostate else "ok"), 0
        try:
            self._states([(w, int(last)) for w in todo])
        except StateUnavailable:
            return "fail", 0
        saved_ns, saved_re = self.cursor.get("_peek_ns"), self.__dict__.get("_reemit")
        pool0 = [json.loads(json.dumps(s9)) for s9 in dets.values() if isinstance(s9, dict)]
        union = {s9["tx"]["hash"].lower(): s9 for s9 in pool0}
        failed, n = [], 0
        try:
            self.cursor["_peek_ns"] = base
            self._reemit = set()
            self._peek_fail_ws = set()
            for w in todo:
                pw = [s9 for s9 in union.values() if int((s9.get("tx") or {}).get("block_number") or 0) > int(starts[w])]
                try:
                    self._native(w, int(starts[w]), int(last), pw, dl + 30, nk="_peek_ns", head=head)
                except Exception as e:  # noqa: BLE001 [isolate]
                    failed.append(w)
                    log.info("%s 엿보기 네이티브 정합 %s… 보류(다음 사이클 · 다른 지갑은 계속): %s", self.chain, w[:10],
                             logs.redact_urls(logs.safe_err(e))[:100])
                    self._peek_union(union, pw)
                    continue
                self._peek_union(union, pw)
                if w in self._peek_fail_ws:
                    failed.append(w)
                    log.info("%s 엿보기 네이티브 정합 %s… 잎 일부 실패(다음 사이클 다시 · 찾은 입금은 방출)", self.chain, w[:10])
                    continue
                wd[w] = int(last)
            re9 = set(self._reemit or ())
            self._trace_later_pre(list(union), union)
            for s9 in sorted(union.values(), key=lambda x: (x["tx"]["block_number"], x["tx"]["hash"])):
                h = s9["tx"]["hash"].lower()
                if (h not in self.emitted or h in re9) and any(self._touches(s9, w) for w in self.wallets):
                    self._emit(h, s9, head)
                    n += 1
        finally:
            if saved_ns is None:
                self.cursor.pop("_peek_ns", None)
            else:
                self.cursor["_peek_ns"] = saved_ns
            if saved_re is None:
                self.__dict__.pop("_reemit", None)
            else:
                self._reemit = saved_re
        for w in failed:
            wd.pop(w, None)
        if wd:
            self.cursor["_peek_wdone"] = wd
        if n:
            statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        self._trace_late_settle(list(union))
        return ("fail" if failed else ("nostate" if nostate else "ok")), n

    @staticmethod
    def _snap_merge(a: dict, b: dict) -> dict:
        if a is b:
            return a
        ta, tb = a.get("internal_note") == "trace", b.get("internal_note") == "trace"
        base, other = (b, a) if (tb and not ta) else (a, b)
        if ta or tb:
            return base
        seen = {(str(i.get("from") or "").lower(), str(i.get("to") or "").lower(), str(i.get("value")), i.get("attr")) for i in base.get("internal") or []}
        add = [i for i in other.get("internal") or []
               if (str(i.get("from") or "").lower(), str(i.get("to") or "").lower(), str(i.get("value")), i.get("attr")) not in seen]
        if add:
            base.setdefault("internal", []).extend(add)
            if other.get("internal_note") and not base.get("internal_note"):
                base["internal_note"] = other["internal_note"]
        return base

    def _peek_union(self, union: dict, pw: list) -> None:
        for s9 in pw:
            h9 = s9["tx"]["hash"].lower()
            cur9 = union.get(h9)
            union[h9] = s9 if cur9 is None else self._snap_merge(cur9, s9)

    def _lanes_unstall(self, safe: int):
        if self.lanes_cfg is False or self.cursor.get("_rpc_v") != self.VERSION or isinstance(self.cursor.get("_handover"), dict) \
                or isinstance(self.cursor.get("_since_ext"), dict):
            return
        live = int(safe) - self._lanes_recent_blocks()
        start = int(self.cursor.get("_start") or 0)
        if live <= start:
            return
        behind = [w for w in self.wallets if type(self.cursor.get(w)) is int and int(self.cursor[w]) < live]
        if not behind:
            return
        live0 = live
        live, b0 = self._lanes_baselines(behind, live, safe)
        behind = [w for w in behind if int(self.cursor[w]) < live]
        if not behind:
            return
        ts9 = time.strftime("%Y%m%d_%H%M%S")
        bp = self.cursor_path + f".pre_lanes_{ts9}"
        statefile.atomic_write_json(bp, self.cursor)
        cur = self.cursor
        ns = cur.setdefault("_ns", {})
        bkns = cur.setdefault("_bkns", {})
        c0s = []
        for w in behind:
            c0 = int(cur[w])
            c0s.append(c0)
            cur["_bk:" + w] = {"from": c0, "to": int(live), "done": c0, "why": "new"}
            if isinstance(ns.get(w), list):
                bkns[w] = ns[w]
            else:
                bkns.pop(w, None)
            if w in b0:
                ns[w] = b0[w]
            else:
                ns.pop(w, None)
            cur[w] = int(live)
        sc9 = cur.pop("_scan", None)
        if isinstance(sc9, dict) and set(sc9.get("ws") or []) <= set(behind):
            cur["_bkscan"] = sc9
        if live > live0:
            self._sweep_add(max(live0, min(c0s)), live)
        cur["_handover"] = {"from": "stall", "at": int(time.time()), "live": int(live), "start": start, "bk_from": min(c0s), "overlap": 0,
                            "adopted": 0, "new": len(behind), "internal": 0, "extend": 0, "hq": 0, "src_min": None, "src_max": None, "curs": {},
                            "nobase": [len(set(behind) - set(b0)), 0], "backup": os.path.basename(bp)}
        statefile.atomic_write_json(self.cursor_path, cur)
        log.warning("★%s 단일 차선 → 차선 모드 전환: 지갑 %d개(커서 %d~%d)가 최근 창보다 뒤 — 라이브 = 블록 %d 부터 · 옛 구간은 뒤 차선(보존본 %s)★",
                    self.chain, len(behind), min(c0s), max(c0s), live, os.path.basename(bp))

    def _init(self, safe: int):
        self._since_reinit(safe)
        if self.cursor.get("_rpc_v") != self.VERSION:
            has9 = any(not str(k).startswith("_") and isinstance(v, int) and not isinstance(v, bool) for k, v in self.cursor.items())
            back9 = isinstance(self.cursor.get("_handback"), dict) and self.cursor["_handback"].get("from") == "rpc"
            if self.handover == "adopt" and (has9 or back9) and self.lanes_cfg is not False:
                self._adopt_explorer(safe)
            elif self.lanes_cfg is not False:
                self._adopt_explorer(safe, fresh=True)
            else:
                old = {k: v for k, v in self.cursor.items()}
                if old:
                    statefile.atomic_write_json(self.cursor_path + ".explorer_legacy", old)
                start = self._window_start(safe)
                self.cursor = {"_rpc_v": self.VERSION, "_start": int(start), **({"_reorg": old["_reorg"]} if evm_reorg.held(old) else {})}
                xc9 = {k: v for k, v in old.items() if not str(k).startswith("_") and isinstance(v, int) and not isinstance(v, bool)}
                self.cursor["_xcurs"] = xc9
                if bf_engine.SINCE.target(self.chain):
                    self.cursor["_since_seen"] = int(bf_engine.SINCE.target(self.chain))
                statefile.atomic_write_json(self.cursor_path, self.cursor)
                log.info("★%s RPC 전용 추적 초기화 — 창 시작 블록 %d (safe %d, 종전 커서는 .explorer_legacy)★",
                         self.chain, start, safe)
        else:
            self._lanes_unstall(safe)
        if "_xcurs" not in self.cursor and not isinstance(self.cursor.get("_handover"), dict):
            lg9 = statefile.read_json(self.cursor_path + ".explorer_legacy", {})
            self.cursor["_xcurs"] = {k: v for k, v in (lg9.items() if isinstance(lg9, dict) else ())
                                     if not str(k).startswith("_") and isinstance(v, int) and not isinstance(v, bool)}
        start = int(self.cursor["_start"])
        ns = self.cursor.setdefault("_ns", {})
        new_ws = []
        for w in self.wallets:
            if not isinstance(self.cursor.get(w), int):
                sb = self.since.get(w)
                if sb is not None and sb[0] > start and sb[0] < int(safe):
                    self.cursor[w] = sb[0]
                    ns[w] = [sb[0], sb[1], sb[2], 0, "0"]
                    continue
                new_ws.append(w)
        if new_ws and self.bk_mode:
            lv = [int(self.cursor[w]) for w in self.wallets if isinstance(self.cursor.get(w), int)]
            live0 = max(int(start), min(min(lv) if lv else int(safe), int(safe)) - self._lanes_recent_blocks())
            live, b0 = self._lanes_baselines(new_ws, live0, safe)
            if live > live0:
                self._sweep_add(live0, live)
            bb = self._baselines(new_ws, start) if start < live else {}
            if set(b0) != set(new_ws) or (start < live and set(bb) != set(new_ws)):
                log.warning("%s 새 지갑 합류 — 기준점 없음 라이브 %d · 뒤 차선 %d(비아카이브 노드: 첫 확인 지점이 기준점)", self.chain,
                            len(set(new_ws) - set(b0)), len(set(new_ws) - set(bb)) if start < live else 0)
            bkns = self.cursor.setdefault("_bkns", {})
            for w in new_ws:
                self.cursor[w] = live
                if w in b0:
                    ns[w] = b0[w]
                if start < live:
                    self.cursor["_bk:" + w] = {"from": start, "to": live, "done": start, "why": "new"}
                    if w in bb:
                        bkns[w] = bb[w]
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.warning("★%s 새 지갑 %d개 합류 — 라이브 %d 부터 · 옛 구간 %d → %d 는 뒤 차선★", self.chain, len(new_ws), live, start, live)
            new_ws = []
        st0 = {}
        if new_ws and start > 0:
            for w9 in new_ws:
                try:
                    st0.update(self._states([(w9, start)]))
                except StateUnavailable:
                    pass
        for w in new_ws:
            self.cursor[w] = start
            if start == 0:
                ns[w] = [0, 0, "0", 0, "0"]
            elif (w, start) in st0:
                n9, b9 = st0[(w, start)]
                ns[w] = [start, n9, str(b9), 0, "0"]
        self._legacy_queues()

    def _legacy_queues(self):
        pp = paths.state(f"pending_detail_{self.chain}.json")
        ep = paths.state(f"enrich_{self.chain}.json")
        pend = statefile.read_json(pp, {})
        if pend:
            dets = self._details(sorted(h.lower() for h in pend))
            self._trace_later_pre([h for h in sorted(dets) if isinstance(dets[h], dict)], dets)
            for h in sorted(dets):
                if isinstance(dets[h], dict) and h not in self.emitted:
                    self._emit(h, dets[h], 0)
            self._trace_late_settle(list(dets))
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            left = {h: v for h, v in pend.items() if not isinstance(dets.get(h.lower()), dict)}
            statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
            if self.bk_mode:
                statefile.atomic_write_json(self.cursor_path, self.cursor)
            statefile.atomic_write_json(pp, left)
        enr = statefile.read_json(ep, {})
        if enr:
            if self.bk_mode:
                hq = self.cursor.setdefault("_hq", {})
                for h in enr:
                    if isinstance(h, str) and h.startswith("0x"):
                        hq.setdefault(h.lower(), 0)
                statefile.atomic_write_json(self.cursor_path, self.cursor)
                log.warning("%s 탐색기 enrich 큐 %d건 → 인계 큐(_hq — RPC trace 로 internal 채움)로 옮기고 비움", self.chain, len(enr))
            else:
                log.warning("%s 탐색기 enrich 큐 잔존 — RPC 경로는 네이티브 정합으로 대체, 큐 비움", self.chain)
            statefile.atomic_write_json(ep, {})
        tp9 = paths.state(f"trace_later_left_{self.chain}.json")
        tll = statefile.read_json(tp9, {})
        if isinstance(tll, dict) and tll:
            hq9 = self.cursor.get("_hq") if isinstance(self.cursor.get("_hq"), dict) else {}
            tl9 = self.cursor.get("_trace_later") if isinstance(self.cursor.get("_trace_later"), dict) else {}
            got9 = []
            for h9, e9 in tll.items():
                h9 = str(h9).lower()
                if h9.startswith("0x") and isinstance(e9, dict) and h9 not in hq9:
                    tl9.setdefault(h9, dict(e9, sent=True))
                    got9.append(h9)
            if tl9:
                self.cursor["_trace_later"] = tl9
                self._trace_later_trim()
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            hp9 = paths.state(f"hq_left_{self.chain}.json")
            held9 = statefile.read_json(hp9, {})
            if isinstance(held9, dict) and any(h in held9 for h in got9):
                statefile.atomic_write_json(hp9, {h: v for h, v in held9.items() if h not in got9})
            statefile.atomic_write_json(tp9, {})
            log.warning("%s 되돌림 전 늦은 채움 trace %d건 되살림(_trace_later · 인계 큐에 든 %d건은 _hq 몫)", self.chain, len(got9), len(tll) - len(got9))


    def _detail_fail_note(self, bad: list, dets: dict, blocks: dict = None) -> list:
        return bf_engine.detail_fail_note(self.cursor, bad, dets, self.chain, "rpc_detail", log, self.__dict__.setdefault("_df_seen", set()),
                                          blocks=blocks)

    def _held_block(self, blk: int, pool_hashes: set, got=()) -> list:
        out = [h for h, v in bf_engine.quarantine_map(self.cursor).items()
               if isinstance(v, dict) and v.get("blk") is not None and int(v["blk"]) == int(blk)]
        out += [h for h, b in (self.cursor.get("_q_released") or {}).items() if int(b) == int(blk) and h not in pool_hashes]
        out += [h for h in got if h not in pool_hashes]
        return sorted(set(out))

    def _detail_fail_clear(self, ok_hashes):
        bf_engine.detail_fail_clear(self.cursor, ok_hashes)

    def _quarantine_retry(self, head: int):
        due = bf_engine.quarantine_due(self.cursor)
        if not due:
            return 0
        try:
            dets = self._details(due)
        except Exception as e:  # noqa: BLE001 [fallback]
            dets = {h: e for h in due}
        n = 0
        self._trace_later_pre([h for h in due if isinstance(dets.get(h), dict)], dets)
        for h in due:
            snap = dets.get(h)
            if isinstance(snap, dict):
                if h not in self.emitted and any(self._touches(snap, w) for w in self.wallets):
                    self._emit(h, snap, head)
                    n += 1
                bf_engine.quarantine_result(self.cursor, h, True, self.chain, "rpc_detail", log)
            else:
                bf_engine.quarantine_result(self.cursor, h, False, self.chain, "rpc_detail", log, err=snap)
        self._trace_late_settle(list(due))
        statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        return n

    def _retention_check(self, ws: list, c: int, target: int, f9: int) -> int:
        now = time.time()
        cands = self.cursor.get("_retention_cand") if isinstance(self.cursor.get("_retention_cand"), dict) else {}
        cands = {k: v for k, v in cands.items() if isinstance(v, dict) and now - float(v.get("last") or 0) < 86400}
        k = str(int(c) + 1)
        cd = cands.get(k) if isinstance(cands.get(k), dict) else {"n": 0, "first": int(now)}
        cd["floor"] = min(int(cd.get("floor") or f9), int(f9))
        cd["n"] = int(cd.get("n") or 0) + 1
        cd["last"] = int(now)
        cands[k] = cd
        self.cursor["_retention_cand"] = cands
        why = None
        ts9 = None
        if cd["n"] < RETENTION_CONFIRM_N or now - float(cd.get("first") or now) < RETENTION_CONFIRM_SEC:
            why = f"확인 중 {cd['n']}/{RETENTION_CONFIRM_N}회"
        else:
            try:
                ts9 = int(self._block_ts(int(cd["floor"])))
            except Exception as e:  # noqa: BLE001 [fallback]
                why = f"보관 시작 블록 시각 조회 실패({logs.safe_err(e)[:60]}) — 다음 사이클"
            if ts9 is not None and now - ts9 < RETENTION_MIN_AGE_SEC:
                why = (f"보관 시작이 {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts9))}로 너무 최근 — 노드 이상일 수 있어 자동으로 "
                       "건너뛰지 않음(사람 확인)")
        if why:
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            msg9 = f"노드 보관 범위 밖(블록 {int(c) + 1}~{int(cd['floor']) - 1}, 첫 보관 블록 {cd['floor']}) — {why}"
            if isinstance(self.last_scan_metrics, dict):
                self.last_scan_metrics["stop"] = msg9
            log.warning("%s %s", self.chain, msg9)
            return c
        to9 = min(int(cd["floor"]) - 1, int(target))
        return self._retention_skip(ws, c, to9, ts9 if to9 == int(cd["floor"]) - 1 else None, int(cd["n"]), cand_key=k)

    def _bk_retention(self):
        ws9, c9, fl9 = self.__dict__.pop("_scan_floor")
        jobs = self._bk_jobs()
        ws = [w for w in ws9 if w in jobs and int(jobs[w].get("done") or 0) == c9]
        if not ws or fl9 <= c9 + 1:
            return
        now = time.time()
        cands = self.cursor.get("_bk_retention_cand") if isinstance(self.cursor.get("_bk_retention_cand"), dict) else {}
        cands = {k: v for k, v in cands.items() if isinstance(v, dict) and now - float(v.get("last") or 0) < 86400}
        k = str(c9 + 1)
        cd = cands.get(k) if isinstance(cands.get(k), dict) else {"n": 0, "first": int(now)}
        cd["floor"] = min(int(cd.get("floor") or fl9), int(fl9))
        cd["n"] = int(cd.get("n") or 0) + 1
        cd["last"] = int(now)
        cands[k] = cd
        self.cursor["_bk_retention_cand"] = cands
        if cd["n"] < RETENTION_CONFIRM_N or now - float(cd.get("first") or now) < RETENTION_CONFIRM_SEC:
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            return
        ts9 = int(self._block_ts(int(cd["floor"])))
        if now - ts9 < RETENTION_MIN_AGE_SEC:
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.warning("%s 뒤 차선 노드 보관 밖(블록 %d~) — 보관 시작이 너무 최근이라 자동으로 넘기지 않음(사람 확인)", self.chain, int(cd["floor"]))
            return
        st0 = {}
        bkns = self.cursor.setdefault("_bkns", {})
        gaps = self.cursor.setdefault("_retention_gaps", [])
        fin = []
        for w in ws:
            j = jobs[w]
            to9 = min(int(cd["floor"]) - 1, int(j["to"]))
            if to9 <= c9:
                continue
            try:
                st0.update(self._states([(w, to9)], strict=True))
            except StateUnavailable:
                pass
            j["done"] = int(to9)
            if (w, to9) in st0:
                n9, b9 = st0[(w, to9)]
                bkns[w] = [int(to9), n9, str(b9), 0, "0"]
            else:
                bkns.pop(w, None)
            if int(to9) >= int(j["to"]):
                fin.append(w)
        gaps.append({"kind": "node_retention", "lane": "bk", "from": c9 + 1, "to": min(int(cd["floor"]) - 1, max(int(jobs[w]["to"]) for w in ws)),
                     "floor_ts": ts9, "ws": [w[:10] for w in ws], "at": int(now), "n_obs": int(cd["n"])})
        del gaps[:-20]
        for w in fin:
            self.cursor.pop("_bk:" + w, None)
            bkns.pop(w, None)
        cands.pop(k, None)
        if not cands:
            self.cursor.pop("_bk_retention_cand", None)
        self.cursor.pop("_bkscan", None)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        log.warning("★%s 뒤 차선 — 로그 노드 보관 밖 옛 구간 = 미수집 범위로 기록하고 넘어감: 블록 %d~%d · 지갑 %d(완주 %d) — 그 앞 보유는 기초 잔고 대조★",
                    self.chain, c9 + 1, int(cd["floor"]) - 1, len(ws), len(fin))

    def _retention_skip(self, ws: list, c: int, to: int, floor_ts=None, n_obs: int = 0, cand_key=None) -> int:
        def _ts(b):
            try:
                return int(self._block_ts(int(b)))
            except Exception:  # noqa: BLE001 [fallback]
                return None
        if floor_ts is None:
            floor_ts = _ts(to + 1)
        from_ts = _ts(c + 1)
        st0 = {}
        for w in ws:
            try:
                st0.update(self._states([(w, int(to))], strict=True))
            except StateUnavailable:
                pass
        if cand_key is not None:
            cands9 = self.cursor.get("_retention_cand") if isinstance(self.cursor.get("_retention_cand"), dict) else {}
            cands9.pop(str(cand_key), None)
            if not cands9:
                self.cursor.pop("_retention_cand", None)
        gaps = self.cursor.setdefault("_retention_gaps", [])
        gaps.append({"kind": "node_retention", "from": int(c) + 1, "to": int(to), "from_ts": from_ts, "floor_ts": floor_ts,
                     "ws": [w[:10] for w in ws], "at": int(time.time()), "n_obs": int(n_obs),
                     "host": urllib.parse.urlsplit(self.logs_rpcs[0]).hostname if self.logs_rpcs else None})
        del gaps[:-20]
        ns = self.cursor.setdefault("_ns", {})
        nb = 0
        for w in ws:
            self.cursor[w] = int(to)
            if (w, int(to)) in st0:
                n9, b9 = st0[(w, int(to))]
                ns[w] = [int(to), n9, str(b9), 0, "0"]
                nb += 1
            else:
                ns.pop(w, None)
        self.cursor.pop("_scan", None)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        log.warning("★%s 로그 노드 보관 밖 옛 구간 = 미수집 범위로 기록하고 넘어감: 블록 %d~%d%s · 지갑 %d(네이티브 새 기준점 %d) — "
                    "그 앞 보유는 잔고 대조(기초 잔고)로 맞춤★", self.chain, c + 1, to,
                    f"(~{time.strftime('%Y-%m-%d', time.localtime(floor_ts))} 이전)" if floor_ts else "", len(ws), nb)
        return int(to)

    LOG_CAPS_RESET_SEC = 1800

    def _scan_logs(self, ws: list, c: int, target: int, deadline: float) -> tuple:
        mx = self.addr_max or max(1, len(ws))
        found, last, floor9, stop9, mets = {}, int(target), None, None, {}
        caps0 = self.__dict__.setdefault("_log_caps", {})
        st9 = self.__dict__.get("_log_caps_static")
        if isinstance(st9, dict) and time.time() - float(self.__dict__.get("_log_caps_at") or 0) >= self.LOG_CAPS_RESET_SEC:
            caps0.clear()
            caps0.update(st9)
            self._log_caps_at = time.time()
        fb0 = getattr(self, "logs_fallback", None) or {}
        prim0 = getattr(self, "logs_primary", None) or self.logs_rpcs
        head9 = self.__dict__.get("_log_head")
        if isinstance(head9, int) and c >= head9 - bf_engine.RPC_NEAR_HEAD:
            try:
                import nodekeys
                key9 = [u for u in prim0 if nodekeys.is_key_node(u)]
            except Exception:   # noqa: BLE001 [fallback]
                key9 = []
            if key9 and len(key9) < len(prim0):
                prim0 = [u for u in prim0 if u not in key9]
                fb0 = dict(fb0)
                for u9 in key9:
                    fb0.setdefault(u9, int(caps0.get(u9) or self.span))
        for i in range(0, len(ws), mx):
            pads = ["0x" + w[2:].rjust(64, "0") for w in ws[i:i + mx]]
            scanner = bf_engine.LogScanner(
                prim0, self.TRANSFER, pads, span=self.span, min_span=self.min_span, timeout=25, log=_SCAN_LOG,
                caps=dict(caps0), fallback={u: int(caps0.get(u) or cap9) for u, cap9 in fb0.items()},
                name=f"{self.chain} getLogs",
                positions={1: [self.TRANSFER, self.APPROVAL, self.WETH_DEPOSIT, self.WETH_WITHDRAWAL], 2: self.TRANSFER},
                head_guard=(self.cfg["chains"][self.chain].get("logs_head_guard") is not False),
                soft=self.__dict__.setdefault("_log_soft", {}))
            f9, l9 = scanner.scan(c + 1, last, deadline=deadline)
            for u9, cap9 in (getattr(scanner, "caps", None) or {}).items():
                if isinstance(cap9, int) and cap9 > 0:
                    caps0[u9] = min(int(caps0.get(u9) or cap9), cap9)
            for k9, v9 in (getattr(scanner, "metrics", None) or {}).items():
                if isinstance(v9, (int, float)):
                    mets[k9] = mets.get(k9, 0) + v9
            stop9 = getattr(scanner, "last_stop", None) or stop9
            found.update(f9)
            if l9 < last:
                last = l9
            if l9 <= c:
                fl9 = getattr(scanner, "retention_floor", None)
                floor9 = fl9 if (isinstance(fl9, int) and not isinstance(fl9, bool)) else None
                break
        self.last_scan_metrics = dict(mets, stop=stop9)
        self._scan_floor = (tuple(sorted(ws)), int(c), int(floor9)) if (isinstance(floor9, int) and last <= c) else None
        return {h: b for h, b in found.items() if b <= last}, last, floor9

    def _emit(self, h: str, snap: dict, head: int):
        rec = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h, "snapshot": snap,
               "wallets": self.wallets, "observed_head": head, "ts": int(time.time())}
        if self.bk_mode:
            rec["wallets"] = [w for w in self.wallets if self._touches(snap, w)] or self.wallets
            if snap.get("internal_note") in ("trace", "balance_delta") and snap.get("internal"):
                rec["repair"] = "int_fill"
        self.writer.append(rec)
        self.emitted.add(h)
        hq = self.cursor.get("_hq")
        if isinstance(hq, dict) and snap.get("internal_note") == "trace":
            hq.pop(h, None)
        self._trace_later_mark(h, snap)

    TRACE_LATER_TAIL_PER = 20


    def _advance(self, ws: list, c: int, target: int, head: int, deadline: float, bk: bool = False) -> int:
        sk, nk = ("_bkscan", "_bkns") if bk else ("_scan", "_ns")
        self._reemit = set()
        self._bis_prog = 0
        self._det_prog = 0
        sc = self.cursor.get(sk)
        rest9 = None
        if isinstance(sc, dict) and sc.get("frm") == c + 1 and sorted(sc.get("ws") or []) == sorted(ws) \
                and int(sc.get("to") or 0) > c:
            found, last = dict(sc.get("found") or {}), int(sc["to"])
            if last > int(target) > c:
                rest9 = {"frm": int(target) + 1, "to": last, "ws": sorted(ws), "found": {h: b for h, b in found.items() if int(b) > int(target)}}
                found = {h: b for h, b in found.items() if int(b) <= int(target)}
                last = int(target)
        else:
            found, last, f9 = self._scan_logs(ws, c, target, deadline)
            if last <= c:
                if not bk and isinstance(f9, int) and f9 > c + 1:
                    return self._retention_check(ws, c, target, f9)
                return c
            self.cursor[sk] = {"frm": c + 1, "to": last, "ws": sorted(ws),
                               "found": {h: b for h, b in found.items() if h not in self.emitted}}
            statefile.atomic_write_json(self.cursor_path, self.cursor)
        qset = bf_engine.quarantine_map(self.cursor)
        todo = [h for h in found if h not in self.emitted and h not in qset]
        memo9 = self.__dict__.setdefault("_snap_memo", {})
        need = [h for h in todo if h not in memo9]
        ov9 = self.BK_NATIVE_OVERRUN_SEC if bk else 120
        dets = self._details(need, deadline=deadline + ov9, late=bk) if need else {}
        for h in need:
            if isinstance(dets.get(h), dict):
                memo9[h] = json.loads(json.dumps(dets[h]))
                self._det_prog += 1
        for h in todo:
            if h not in dets and h in memo9:
                dets[h] = json.loads(json.dumps(memo9[h]))
        if len(memo9) > 20000:
            memo9.clear()
        bad = [h for h in todo if not isinstance(dets.get(h), dict)]
        self._detail_fail_clear([h for h in todo if isinstance(dets.get(h), dict)])
        if bad:
            left = self._detail_fail_note(bad, dets, blocks=found)
            if left:
                log.warning("%s 상세 %d건 실패 — 커서 유지(스캔 체크포인트로 재시도): %s", self.chain, len(left),
                            str(dets.get(left[0]))[:120])
                return c
            todo = [h for h in todo if isinstance(dets.get(h), dict)]
        pool = [dets[h] for h in todo]
        self._mc_rate = None
        t_st9 = time.time()
        n_mc = self._mc_balances(ws, last) if self.multicall else 0
        if n_mc < len(ws) and self._mc_rate is not None:
            raise self._mc_rate
        if n_mc < len(ws):
            try:
                self._states([(w, last) for w in ws if (w, last) not in self.__dict__.setdefault("_st_memo", {})])
            except StateUnavailable:
                pass
        if bk:
            self._bk_fixed = time.time() - t_st9
        new_ns = {}
        sv9 = self.__dict__.setdefault("_nat_starve", {})
        first9 = [x for x in (sv9.get(nk) or []) if x in ws]
        ws_o = first9 + [x for x in ws if x not in first9]
        for i9, w in enumerate(ws_o):
            try:
                new_ns[w] = (self._native(w, c, last, pool, deadline + ov9, nk) if bk else self._native(w, c, last, pool, deadline + ov9, head=head))["ns"]
            except Exception:
                sv9[nk] = ws_o[i9:] + [x for x in (sv9.get(nk) or []) if x not in ws_o[i9:]][:200]
                raise
        if sv9.get(nk):
            sv9[nk] = [x for x in sv9[nk] if x not in ws]
        if not bk and all(isinstance(new_ns.get(w), list) and int(new_ns[w][0]) == int(last) for w in ws):
            sl9 = self._st_lag_map(self.cursor.get("_st_lag"))
            sl9.pop(str(c), None)
            sl9.pop("*", None)
            if sl9:
                self.cursor["_st_lag"] = sl9
            else:
                self.cursor.pop("_st_lag", None)
        n_emit = 0
        ph9 = {s["tx"]["hash"].lower(): s for s in pool}
        self._trace_later_pre(list(ph9), ph9)
        for s in sorted(pool, key=lambda s: (s["tx"]["block_number"], s["tx"]["hash"])):
            h = s["tx"]["hash"].lower()
            re9 = self.__dict__.get("_reemit") or set()
            if (h in self.emitted and h not in re9) or not any(self._touches(s, w) for w in self.wallets):
                continue
            self._emit(h, s, head)
            re9.discard(h)
            n_emit += 1
        statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        nm = self.cursor.setdefault("_nonces", {})
        for s in pool:
            m9 = self._txmeta.get(s["tx"]["hash"].lower())
            if m9 and m9["from"] in ws:
                nm.setdefault(m9["from"], {})[str(m9["nonce"])] = m9["block"]
                fo = self.cursor.setdefault("_first_own", {}).get(m9["from"])
                if not fo or m9["block"] < int(fo[0]):
                    self.cursor["_first_own"][m9["from"]] = [m9["block"], s["tx"]["hash"]]
        ns = self.cursor.setdefault(nk, {})
        fin = []
        for w in ws:
            if bk:
                job = self.cursor.get("_bk:" + w)
                if isinstance(job, dict):
                    job["done"] = int(last)
                    if int(last) >= int(job.get("to") or 0):
                        fin.append(w)
            else:
                self.cursor[w] = last
            if new_ns.get(w) is not None:
                ns[w] = new_ns[w]
        for w in fin:
            j9 = self.cursor.pop("_bk:" + w, None) or {}
            ns.pop(w, None)
            log.info("★%s 뒤 차선 완주 %s(%s) — 블록 %s → %s★", self.chain, w[:10], j9.get("why"), j9.get("from"), j9.get("to"))
        self.cursor.pop(sk, None)
        lf9 = self.cursor.get("_leaf_fail")
        if isinstance(lf9, dict):
            lf9.pop(self._leaf_rng_key(nk, c), None)
        if rest9 is not None:
            self.cursor[sk] = rest9
        for h in todo:
            memo9.pop(h, None)
        self._trace_late_settle(list(ph9) + list(todo))
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        if n_emit:
            log.info("%s rpc 발견 %d tx 방출 (%s블록 %d→%d, 지갑 %d)", self.chain, n_emit, "옛 구간 " if bk else "", c, last, len(ws))
        return last

    def _bk_jobs(self) -> dict:
        return {w: self.cursor["_bk:" + w] for w in self.wallets if isinstance(self.cursor.get("_bk:" + w), dict)}

    def _bk_base_fill(self, ws: list, d: int, jobs: dict) -> None:
        bns9 = self.cursor.get("_bkns") if isinstance(self.cursor.get("_bkns"), dict) else {}
        tried9 = self.__dict__.setdefault("_bk_base_tried", set())
        miss9 = [w for w in ws if bns9.get(w) is None and (w, int(d)) not in tried9 and isinstance(jobs.get(w), dict)
                 and int(jobs[w].get("done") or 0) == int(jobs[w].get("from") or -1) == int(d)]
        if not miss9:
            return
        got9 = self._baselines(miss9, int(d))
        if got9:
            self.cursor.setdefault("_bkns", {}).update(got9)
        for w in miss9:
            if w not in got9:
                tried9.add((w, int(d)))
        if len(tried9) > 5000:
            tried9.clear()

    @staticmethod
    def _bk_lane(jobs: dict) -> tuple:
        def _union(iv):
            n, s0, e0 = 0, None, None
            for s, e in sorted(iv):
                if e <= s:
                    continue
                if e0 is None or s > e0:
                    if e0 is not None:
                        n += e0 - s0
                    s0, e0 = s, e
                elif e > e0:
                    e0 = e
            return n + ((e0 - s0) if e0 is not None else 0)
        rows = [(int(j["from"]), max(int(j["from"]), int(j["done"])), int(j["to"])) for j in jobs.values()]
        tot = _union([(f, t) for f, _d, t in rows])
        left = _union([(d, t) for _f, d, t in rows])
        return max(0, tot - left), max(1, tot)

    def _bk_step(self, head: int, deadline: float) -> tuple:
        adv, stalled = 0, False
        bud9 = max(1.0, deadline - time.time())
        span = max(2000, min(self.bk_span, int(self.cursor.get("_bkspan") or self.bk_span)))
        while time.time() < deadline:
            jobs = self._bk_jobs()
            if not jobs:
                break
            groups = {}
            for w, j in jobs.items():
                groups.setdefault(int(j.get("done") or 0), []).append(w)
            d = min(groups)
            ws = groups[d]
            to = min(int(jobs[w].get("to") or 0) for w in ws)
            nxt = min((g for g in groups if g > d), default=None)
            tgt = min(to, d + span)
            clip = nxt is not None and nxt < tgt
            if clip:
                tgt = nxt
            if tgt <= d:
                break
            t0 = time.time()
            self._bk_fixed = 0.0
            self._late_ctx = True
            self._e4_ctx = True
            try:
                self._bk_base_fill(ws, d, jobs)
                got = self._advance(ws, d, tgt, head, deadline, bk=True)
            except StateUnavailable as e:
                got = d
                log.info("%s 뒤 차선 상태 조회 불가(다음 사이클): %s", self.chain, e)
            except Exception as e9:
                if self._span_keep(e9):
                    log.info("%s 뒤 차선 걸음 유지(%d블록 — %s): %s", self.chain, span, type(e9).__name__, logs.redact_urls(logs.safe_err(e9))[:100])
                else:
                    self._bkspan_persist(max(2000, span // 2))
                    self._bk_cut_t = time.time()
                raise
            finally:
                self._late_ctx = False
                self._e4_ctx = False
            el = time.time() - t0
            el_var = max(0.0, el - min(el, max(0.0, float(self.__dict__.get("_bk_fixed") or 0.0))))
            if got <= d:
                stalled = True
                if int(self.__dict__.get("_det_prog") or 0) == 0:
                    span = max(2000, span // 2)
                    self._bk_cut_t = time.time()
                self.cursor["_bkspan"] = int(span)
                break
            adv += got - d
            if got >= tgt and el_var < bud9 / 3 and not clip \
                    and time.time() - float(self.__dict__.get("_bk_cut_t") or 0) >= self.BK_GROW_HOLD_SEC:
                span = min(self.bk_span, span * 2)
            self.cursor["_bkspan"] = int(span)
        if not self._bk_jobs() and self.cursor.get("_hq") and time.time() < deadline:
            self._hq_step(head, deadline)
        return adv, stalled

    BK_NATIVE_OVERRUN_SEC = 60
    BK_GROW_HOLD_SEC = 600

    def _span_keep(self, e) -> bool:
        return isinstance(e, HoldError) or self._rate_err(e) or (isinstance(e, BisectBudget) and int(self.__dict__.get("_bis_prog") or 0) > 0)

    LATE_TAIL_SEC = 600
    LIVE_SPAN0 = 5000
    LIVE_SPAN_MIN = 500

    def _lv_span(self) -> int:
        try:
            v = int(self.cursor.get("_lvspan") or self.LIVE_SPAN0)
        except (TypeError, ValueError):
            v = self.LIVE_SPAN0
        return max(self.LIVE_SPAN_MIN, min(int(self.bk_span), v))

    def _lv_span_persist(self, span: int) -> None:
        try:
            cur9 = statefile.read_json(self.cursor_path, None)
            if isinstance(cur9, dict):
                cur9["_lvspan"] = int(span)
                tl9 = self.cursor.get("_trace_later")
                if isinstance(tl9, dict) and tl9:
                    dtl9 = cur9.get("_trace_later") if isinstance(cur9.get("_trace_later"), dict) else {}
                    add9 = {h: v for h, v in tl9.items() if h not in dtl9}
                    if add9:
                        cur9["_trace_later"] = dict(dtl9, **add9)
                if int(self.cursor.get("_trace_later_overflow") or 0) > int(cur9.get("_trace_later_overflow") or 0):
                    cur9["_trace_later_overflow"] = int(self.cursor["_trace_later_overflow"])
                statefile.atomic_write_json(self.cursor_path, cur9)
                cur9.pop("_synced_at", None)
                self.cursor = cur9
                return
        except Exception as e:  # noqa: BLE001 [optional]
            log.info("%s 라이브 걸음 저장 실패(무시): %s", self.chain, logs.safe_err(e)[:80])
        self.cursor["_lvspan"] = int(span)

    def _bkspan_persist(self, span: int) -> None:
        self.cursor["_bkspan"] = int(span)
        try:
            cur9 = statefile.read_json(self.cursor_path, None)
            if isinstance(cur9, dict):
                cur9["_bkspan"] = int(span)
                statefile.atomic_write_json(self.cursor_path, cur9)
        except Exception as e:  # noqa: BLE001 [optional]
            log.info("%s 뒤 차선 구간 저장 실패(무시): %s", self.chain, logs.safe_err(e)[:80])

    HQ_BATCH = 20


    def cycle(self):
        tc0 = time.time()
        if self.cursor.pop("_synced_at", None) is not None:
            statefile.atomic_write_json(self.cursor_path, self.cursor)
        self._st_memo_trim()
        self._bal_memo = {}
        self._df_seen = set()
        head = self._head()
        safe = head - self.conf_depth
        self._st_safe = int(safe)
        self._init(safe)
        safe = evm_reorg.cycle_check(self, safe)
        try:
            self._quarantine_retry(head)
        except Exception as e:  # noqa: BLE001 [boundary]
            log.info("%s 격리 tx 재시도 실패(다음 사이클): %s", self.chain, str(e)[:120])
        t0 = time.time()
        deadline = t0 + self.cycle_budget
        complete = True
        groups = {}
        for w in self.wallets:
            groups.setdefault(int(self.cursor[w]), []).append(w)
        advanced, stalled = 0, False
        ext9 = self.cursor.get("_since_ext") if isinstance(self.cursor.get("_since_ext"), dict) else None
        tgt = min(safe, int(ext9["to"])) if ext9 else safe
        if self.bk_mode and not ext9:
            try:
                self._peek_ctx = True
                self._head_peek(head, safe, deadline)
            except Exception as e:  # noqa: BLE001 [boundary]
                log.info("%s 최신 블록 엿보기 실패(라이브 차선이 이어서): %s", self.chain, logs.redact_urls(logs.safe_err(e))[:120])
                try:
                    statefile.atomic_write_json(self.cursor_path, {k: v for k, v in self.cursor.items() if k != "_peek_ns"})
                except Exception:   # noqa: BLE001 [optional]
                    pass
            finally:
                self._peek_ctx = False
        lspan = self._lv_span()
        lspan0 = lspan
        live_err = None
        live_dl = deadline - (min(max(10.0, self.cycle_budget * 0.25), self.cycle_budget * 0.5) if (self.bk_mode and self._bk_jobs()) else 0.0)
        for c0 in sorted(groups, reverse=self.bk_mode):
            c = c0
            ws9 = groups[c0]
            while c < tgt:
                if time.time() >= live_dl:
                    complete = False
                    break
                t_step = min(int(tgt), int(c) + int(lspan))
                t1 = time.time()
                self._late_ctx = t_step < int(tgt) or int(t_step) - int(c) > max(64, int(self.bpd or 43200) * self.LATE_TAIL_SEC // 86400)
                self._key_ctx = bool(self._late_ctx)
                try:
                    got = self._advance(ws9, c, t_step, head, live_dl)
                except StateUnavailable as e:
                    got = c
                    log.info("%s 상태 조회 불가(다음 사이클): %s", self.chain, e)
                except RuntimeError as e:
                    got = c
                    live_err = e
                    keep9 = self._span_keep(e)
                    if not keep9:
                        lspan = max(self.LIVE_SPAN_MIN, int(lspan) // 2)
                    self._lv_span_persist(lspan)
                    log.warning("%s 라이브 걸음 실패(블록 %d → %d) — 걸음 %d블록%s 다음에(다른 묶음·뒤 차선은 계속): %s", self.chain, c, t_step, lspan,
                                " 그대로(보류·한도·진행 중)" if keep9 else "으로 줄여", logs.redact_urls(logs.safe_err(e))[:140])
                finally:
                    self._late_ctx = False
                    self._key_ctx = False
                if got > c:
                    advanced += got - c
                    if got >= t_step and t_step < tgt and time.time() - t1 < max(5.0, self.cycle_budget / 6.0):
                        lspan = min(int(self.bk_span), int(lspan) * 2)
                    c = got
                else:
                    if c == c0:
                        stalled = True
                    break
            if c < tgt:
                complete = False
        if lspan != lspan0:
            self.cursor["_lvspan"] = int(lspan)
        if ext9:
            complete = False
            if tgt == int(ext9["to"]) and all(int(self.cursor[w]) >= tgt for w in self.wallets if isinstance(self.cursor.get(w), int)):
                self._since_ext_done()
        if self.cursor.get("_leaf_later") or self.cursor.get("_leaf_overflow"):
            try:
                self._leaf_later_step(head)
            except Exception as e:  # noqa: BLE001 [boundary]
                log.info("%s 나중에 다시 잎 블록 재시도 실패(다음 사이클): %s", self.chain, logs.safe_err(e)[:120])
        if self.cursor.get("_trace_later") or self.cursor.get("_trace_later_overflow"):
            try:
                self._trace_later_step(head, per=self.TRACE_LATER_TAIL_PER if complete else None)
            except Exception as e:  # noqa: BLE001 [boundary]
                log.info("%s 늦은 채움 trace 재시도 실패(다음 사이클): %s", self.chain, logs.safe_err(e)[:120])
        bk9 = None
        if self.bk_mode and (self._bk_jobs() or self.cursor.get("_hq")):
            bud9 = self.bk_budget if self.bk_budget is not None else max(10.0, self.poll_sec - (time.time() - tc0) - 5.0)
            bk_dl = min(deadline, time.time() + bud9)
            bk_adv, bk_stall = 0, False
            if time.time() < bk_dl:
                self._scan_floor = None
                try:
                    with bf_engine.ledger_burst():
                        bk_adv, bk_stall = self._bk_step(head, bk_dl)
                except Exception as e:  # noqa: BLE001 [fallback]
                    bk_stall = True
                    log.warning("%s 뒤 차선 실패(다음 사이클 이어서): %s", self.chain, logs.redact_urls(logs.safe_err(e))[:160])
                    try:
                        cur9 = statefile.read_json(self.cursor_path, {})
                        for k9 in [k for k in self.cursor if k.startswith("_bk:") or k in ("_bkns", "_bkscan", "_hq", "_bkspan")]:
                            if k9 in cur9:
                                self.cursor[k9] = cur9[k9]
                            else:
                                self.cursor.pop(k9, None)
                    except Exception:  # noqa: BLE001 [optional]
                        pass
            if bk_stall and isinstance(self.__dict__.get("_scan_floor"), tuple):
                try:
                    self._bk_retention()
                except Exception as e:  # noqa: BLE001 [boundary]
                    log.info("%s 뒤 차선 보관 밖 판정 실패(다음 사이클): %s", self.chain, logs.safe_err(e)[:120])
            jobs9 = self._bk_jobs()
            if jobs9 or self.cursor.get("_hq"):
                dn9, tot9 = self._bk_lane(jobs9) if jobs9 else (0, 0)
                left9 = tot9 - dn9
                bk9 = {"wallets": len(jobs9), "new": sum(1 for j in jobs9.values() if j.get("why") == "new"),
                       "internal": sum(1 for j in jobs9.values() if j.get("why") == "internal"),
                       "extend": sum(1 for j in jobs9.values() if j.get("why") == "extend"),
                       "done_min": min((int(j["done"]) for j in jobs9.values()), default=None),
                       "to": max((int(j["to"]) for j in jobs9.values()), default=None),
                       "pct": round(100.0 * (tot9 - left9) / tot9, 1) if tot9 else 100.0, "advanced": bk_adv, "stalled": bk_stall,
                       "hq": len(self.cursor.get("_hq") or {}),
                       "ids": sorted(w[:6] for w, j in jobs9.items() if j.get("why") == "new")[:3]}
        start = int(self.cursor.get("_start") or 0)
        cmin = min(int(self.cursor[w]) for w in self.wallets) if self.wallets else safe
        new_left = bool(bk9 and bk9["new"])
        if complete and cmin >= safe and not new_left:
            self.cursor["_synced_at"] = int(time.time())
        if len(self._txmeta) > 50000:
            self._txmeta.clear()
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        statefile.atomic_write_json(self.rpc_meta_path, self.rpc_meta)
        if bk9 is not None and self._bk_jobs():
            dn9, tt9 = self._bk_lane(self._bk_jobs())
            self.progress.update(f"{self.chain}:rpc", phase="extend", unit="blocks", done=dn9, total=tt9,
                                 note=(self.last_scan_metrics or {}).get("stop"), via=self._sel_via())
            self._sel_lane(tt9 - dn9)
        else:
            self._sel_lane(0)
            nt9 = (self.last_scan_metrics or {}).get("stop")
            if nt9 is None and ((self.progress.items.get(f"{self.chain}:rpc") or {}).get("note") or "").startswith("재기동 — 뒤 차선"):
                nt9 = ""
            self.progress.update(f"{self.chain}:rpc", phase="live" if complete else ("extend" if self.cursor.get("_since_ext") else "scan"),
                                 unit="blocks",
                                 done=max(0, cmin - start), total=max(1, safe - start),
                                 note=nt9, via=self._sel_via())
        gaps = self.cursor.get("_native_gaps") or []
        progressing = (not complete) and advanced > 0 and not stalled
        self._rpc_cycle_failed = not (complete or progressing)
        self._health_cycle("rpc", head, safe, ok=complete or progressing,
                           err=None if (complete or progressing) else (live_err if (live_err is not None and advanced == 0) else RuntimeError("부분 진행(예산·노드)")),
                           rpc_backfill=({"from": start, "cursor": cmin, "safe": safe, "advanced": advanced,
                                          "pct": round(100.0 * max(0, cmin - start) / max(1, safe - start), 1)}
                                         if progressing else None),
                           current_source=urllib.parse.urlsplit(self.cfg_rpcs[0]).hostname,
                           emitted=len(self.emitted), scan=self.last_scan_metrics or None,
                           native_verified=sorted(w[:10] for w, v in (self.cursor.get("_ns") or {}).items()
                                                  if v and int(v[0]) >= cmin),
                           native_gaps=gaps[-5:] or None,
                           retention=retention_summary(self.cursor),
                           native_unexplained=[r for r in (self.cursor.get("_native_notes") or [])
                                               if r.get("kind") == "unexplained"][-5:] or None,
                           rpc_bk=bk9)
        if not complete:
            log.info("%s rpc 사이클 부분 진행: 커서 %d / safe %d (%.0fs)", self.chain, cmin, safe, time.time() - t0)
        if live_err is not None and advanced == 0:
            try:
                live_err._tj_health_counted = True
            except Exception:   # noqa: BLE001 [optional]
                pass
            raise live_err

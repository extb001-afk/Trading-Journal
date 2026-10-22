from dataclasses import MISSING, dataclass, field, fields
from typing import Any, ClassVar, Dict, Optional, Tuple

import chain_event

__all__ = ["EVM_TX", "SOL_TX", "CHAIN_DELTA", "EX_SNAPSHOT", "EX_FILLS", "EX_ORDER_TRADES", "EXF_FILL_RETIME", "EXF_FILLS",
           "EXF_LATE_CYCLE", "CORRUPT", "EvmTx", "SolTx", "ChainDeltaTx", "ExSnapshot", "ExFills", "ExOrderTrades", "ExfFillRetime",
           "ExfFills", "ExfLateCycle", "Corrupt", "KINDS", "from_dict", "contract_keys", "required_keys"]

EVM_TX = "evm_tx"
SOL_TX = "sol_tx"
CHAIN_DELTA = chain_event.KIND
EX_SNAPSHOT = "ex_snapshot"
EX_FILLS = "ex_fills"
EX_ORDER_TRADES = "ex_order_trades"
EXF_FILL_RETIME = "exf_fill_retime"
EXF_FILLS = "exf_fills"
EXF_LATE_CYCLE = "exf_late_cycle"
CORRUPT = "_corrupt"

_META = ("extra", "_order")
_DC = dict(frozen=True, eq=False, repr=False)


class _Rec:

    KIND: ClassVar[str] = ""
    REQUIRED: ClassVar[Tuple[str, ...]] = ()

    @classmethod
    def keys(cls) -> Tuple[str, ...]:
        return tuple(f.name for f in fields(cls) if f.name not in _META)

    @classmethod
    def from_dict(cls, d: dict) -> "_Rec":
        if not isinstance(d, dict):
            raise TypeError("inbox 레코드는 dict 여야 해요: %s" % type(d).__name__)
        if "kind" not in d:
            raise KeyError("kind")
        if d.get("kind") != cls.KIND:
            raise ValueError("종류가 달라요: %r ≠ %r" % (d.get("kind"), cls.KIND))
        for k in cls.REQUIRED:
            if k not in d:
                raise KeyError(k)
        known = set(cls.keys())
        kw = {k: v for k, v in d.items() if k in known}
        extra = {k: v for k, v in d.items() if k not in known}
        return cls(extra=extra, _order=tuple(d), **kw)

    def to_dict(self) -> dict:
        known = set(self.keys())
        order = self._order
        if not order:
            dflt = {f.name: f for f in fields(self)}
            order = tuple(k for k in self.keys() if k in self.REQUIRED or getattr(self, k) != _default(dflt[k]))
        out = {}
        for k in order:
            out[k] = getattr(self, k) if k in known else self.extra[k]
        for k, v in self.extra.items():
            if k not in out:
                out[k] = v
        return out


def _default(f: Any) -> Any:
    return f.default_factory() if f.default_factory is not MISSING else f.default


@dataclass(**_DC)
class EvmTx(_Rec):
    KIND: ClassVar[str] = EVM_TX
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind", "chain", "txhash", "snapshot")
    kind: str
    chain: Any
    txhash: Any
    snapshot: Any
    v: Optional[int] = None
    ts: Any = None
    wallets: Any = field(default_factory=list)
    observed_head: Any = None
    repair: Any = None
    via: Any = None
    ts_fix: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class SolTx(_Rec):
    KIND: ClassVar[str] = SOL_TX
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind", "txhash")
    kind: str
    txhash: Any
    v: Optional[int] = None
    chain: Any = None
    slot: Any = None
    ts: Any = None
    wallets: Any = field(default_factory=list)
    deltas: Any = field(default_factory=list)
    counterparties: Any = None
    err: Any = None
    fee_lamports: Any = None
    fee_payer: Any = None
    fee_payer_mine: Any = None
    has_program: Any = None
    stake_open: Any = None
    stake_reward: Any = None
    stake_pre: Any = None
    stake_new: Any = None
    lp: Any = None
    repersp: Any = None
    ts_fix: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class ChainDeltaTx(_Rec):
    KIND: ClassVar[str] = CHAIN_DELTA
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind", "chain", "tx_uid", "ts")
    kind: str
    chain: Any
    tx_uid: Any
    ts: Any
    v: Optional[int] = None
    network: Any = "mainnet"
    txhash: Any = None
    order: Any = None
    finality: Any = None
    execution: Any = None
    owners: Any = None
    ownership_version: Any = None
    deltas: Any = field(default_factory=list)
    fees: Any = field(default_factory=list)
    movements: Any = None
    classification: Any = None
    completeness: Any = None
    source: Any = None
    tron: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class ExSnapshot(_Rec):
    KIND: ClassVar[str] = EX_SNAPSHOT
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind",)
    kind: str
    v: Optional[int] = None
    exchange: Any = "upbit"
    ts: Any = None
    deposits: Any = None
    withdraws: Any = None
    ext: Any = None
    lb: Any = None
    lbi: Any = None
    lbn: Any = None
    lc: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class ExFills(_Rec):
    KIND: ClassVar[str] = EX_FILLS
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind",)
    kind: str
    v: Optional[int] = None
    exchange: Any = None
    ts: Any = None
    orders: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class ExOrderTrades(_Rec):
    KIND: ClassVar[str] = EX_ORDER_TRADES
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind",)
    kind: str
    v: Optional[int] = None
    exchange: Any = None
    ts: Any = None
    src: Any = None
    orders: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class ExfFillRetime(_Rec):
    KIND: ClassVar[str] = EXF_FILL_RETIME
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind",)
    kind: str
    v: Optional[int] = None
    exchange: Any = None
    ts: Any = None
    src: Any = None
    fills: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class ExfFills(_Rec):
    KIND: ClassVar[str] = EXF_FILLS
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind",)
    kind: str
    v: Optional[int] = None
    exchange: Any = None
    ts: Any = None
    fills: Any = None
    ext: Any = None
    lb: Any = None
    lbi: Any = None
    lbn: Any = None
    lc: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class ExfLateCycle(_Rec):
    KIND: ClassVar[str] = EXF_LATE_CYCLE
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind",)
    kind: str
    v: Optional[int] = None
    exchange: Any = None
    ts: Any = None
    lc: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


@dataclass(**_DC)
class Corrupt(_Rec):
    KIND: ClassVar[str] = CORRUPT
    REQUIRED: ClassVar[Tuple[str, ...]] = ("kind",)
    kind: str
    raw: Any = None
    raw_hex: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _order: Tuple[str, ...] = ()


KINDS = {EVM_TX: EvmTx, SOL_TX: SolTx, CHAIN_DELTA: ChainDeltaTx, EX_SNAPSHOT: ExSnapshot, EX_FILLS: ExFills, EX_ORDER_TRADES: ExOrderTrades,
         EXF_FILL_RETIME: ExfFillRetime, EXF_FILLS: ExfFills, EXF_LATE_CYCLE: ExfLateCycle, CORRUPT: Corrupt}


def from_dict(d: dict) -> _Rec:
    if not isinstance(d, dict):
        raise TypeError("inbox 레코드는 dict 여야 해요: %s" % type(d).__name__)
    if "kind" not in d:
        raise KeyError("kind")
    k = d["kind"]
    cls = KINDS.get(k) if isinstance(k, str) else None
    if cls is None:
        raise ValueError("모르는 inbox 종류: %r" % (k,))
    return cls.from_dict(d)


def contract_keys(kind: str) -> Tuple[str, ...]:
    return KINDS[kind].keys()


def required_keys(kind: str) -> Tuple[str, ...]:
    return KINDS[kind].REQUIRED

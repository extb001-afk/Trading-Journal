from __future__ import annotations

import json
import os
import urllib.parse
from decimal import Decimal
from typing import Any, Callable, Optional

import acct_norm
import chain_registry
import paths
import rawtx_cache
import statefile
from view_common import CHAIN_NAME


def norm_addr(x: Any) -> str:
    text = str(x or "").strip()
    return text.lower() if text.startswith(("0x", "0X")) else text


def _addr(x: Any) -> str:
    if isinstance(x, dict):
        x = x.get("hash")
    return norm_addr(x)


def _chain_key(chain: str, addr: Any) -> str:
    text = str(addr or "").strip()
    if text and chain_registry.is_nonevm(chain):
        try:
            return chain_registry.owner_key(chain, text)
        except (ValueError, TypeError):
            return text
    return norm_addr(text)


__all__ = ["HarvestBook", "board", "api", "norm_addr", "pool_observer", "INFLOW_EVENTS", "DUST_USD"]

INFLOW_EVENTS = ("TRANSFER_IN", "PROGRAM_IN")
DUST_USD = Decimal("0.01")
KIND_CLAIM, KIND_PUSH, KIND_NATIVE = "claim", "push", "native"
CLS_OK, CLS_PUSH, CLS_SUSPECT, CLS_SCAM, CLS_NATIVE = "ok", "push", "suspect", "scam", "native"
FOLDS = (CLS_PUSH, CLS_SUSPECT, CLS_SCAM, CLS_NATIVE)
ROW_CAP = {CLS_OK: 400, CLS_PUSH: 200, CLS_SUSPECT: 300, CLS_SCAM: 120, CLS_NATIVE: 60}
WALLET_CAP = 12
_ZERO, _ONE = Decimal(0), Decimal(1)


def _f(v: Any, nd: int = 6) -> float:
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return 0.0


def _dec(v: Any) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def _scaled(parts: dict, frac: Decimal) -> dict:
    out = {}
    for origin, amt in parts.items():
        take = amt * frac
        if take > 0:
            out[origin] = take
    return out


class HarvestBook:

    def __init__(self, store: dict, px: Any = None, fs_on: bool = True, native: Any = None) -> None:
        self.store = store
        self.groups: dict = store.setdefault("g", {})
        self.ledgers: dict = store.setdefault("l", {})
        self.gas_by_tx: dict = store.setdefault("gas", {})
        self.px = px
        self.fs_on = bool(fs_on)
        self.off = os.environ.get("TJ_HARVEST_OFF") == "1"
        self.native: set = set(native or ())
        self.own: set = set()
        self.own_wallets: set = set()
        self._own_cache: dict = {}
        self.last_out: list = []
        self.last_burn: dict = {}
        self.by_ent: dict = {}
        self.pending: dict = {}
        self.sale_key: dict = {}

    def set_own(self, by_dest: Any, wallets: Any = None) -> None:
        for keys in (by_dest or {}).values():
            for key in keys or ():
                if isinstance(key, (tuple, list)) and len(key) >= 2:
                    self.own.add((str(key[0]), str(key[1])))
        self.own_wallets.clear()
        self.own_wallets.update(norm_addr(w) for w in (wallets or ()) if w)

    def _ent(self, g: dict) -> dict:
        ent = self.groups.get(g["gid"])
        if ent is None:
            ent = self.groups[g["gid"]] = {"sym": g.get("sym") or "?", "free": {}, "native": g["gid"] in self.native}
        return ent

    def _ledger(self, origin: tuple, sym: Any) -> dict:
        led = self.ledgers.get(origin)
        if led is None:
            led = self.ledgers[origin] = {"gid": origin[0], "kind": origin[1], "sym": sym or "?", "rx": [], "recv": _ZERO, "sold": _ZERO,
                                          "usd": _ZERO, "sales": [], "nopx": 0, "est": False, "retUnk": 0, "conv": 0, "brhist": 0, "brUnk": 0, "xcArr": 0}
        return led

    def _own_keys(self, chain: str) -> set:
        keys = self._own_cache.get(chain)
        if keys is None:
            keys = {_chain_key(chain, addr) for addr in self.own_wallets} | set(self.own_wallets)
            self._own_cache[chain] = keys
        return keys

    def _senders(self, chain: str, tx: str) -> set:
        row = self.px.ctx.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, tx)).fetchone()
        snap = json.loads(row["snapshot"]) if row and row["snapshot"] else None
        if not isinstance(snap, dict):
            return set()
        if snap.get("kind") == "chain_delta_tx":
            owners = {str(o) for o in (snap.get("owners") or [])}
            return {str(mv.get("from") or "") for mv in (snap.get("movements") or []) if isinstance(mv, dict) and str(mv.get("to") or "") in owners}
        if chain == "sol" or snap.get("kind") == "sol_tx":
            return {a for a in (snap.get("counterparties") or []) if isinstance(a, str)}
        mine = rawtx_cache.mine_wallets(getattr(self.px.sb, "cfg", None) or {})
        legs = [t for k in ("token_transfers", "internal") if isinstance(snap.get(k), list) for t in snap[k] if isinstance(t, dict)]
        return {_addr(t.get("from")) for t in legs if _addr(t.get("to")) in mine}

    def _from_own(self, signed: bool, chain: str, tx: str) -> bool:
        if (chain, tx) in self.own:
            return True
        if not self.own_wallets or self.px is None or (not signed and not chain_registry.is_nonevm(chain)):
            return False
        try:
            senders = self._senders(chain, tx)
        except Exception:  # noqa: BLE001 [fallback]
            return False
        keys = self._own_keys(chain)
        return any(s in keys or _chain_key(chain, s) in keys for s in senders if s)

    def recv(self, g: dict, r: Any, q: Decimal, ts: Any, signed: bool, fsa: Any, brhist: Any = False) -> None:
        if self.off or q is None or q <= 0 or g.get("is_stable") or g.get("is_fiat"):
            return
        if r["event"] not in INFLOW_EVENTS or r["leg_kind"] != "acq":
            return
        if fsa and len(fsa) >= 3 and fsa[2] == "ov":
            return
        self._flush_last_out()
        chain, tx = str(r["source_ns"] or ""), str(r["source_id"] or "")
        if self._from_own(bool(signed), chain, tx):
            return
        ent = self._ent(g)
        ret_unk = not ent["native"] and not self.fs_on and any(cell[1] > 0 for cell in self.pending.get(g["gid"], ()))
        xc = brhist == "xc"
        br_unk = signed and not ent["native"] and (xc or (bool(brhist) and (self._transit_open(g.get("sym")) or self._dest_open(brhist, ts))))
        kind = KIND_NATIVE if ent["native"] else (KIND_CLAIM if signed and not (ret_unk or br_unk) else KIND_PUSH)
        origin = (g["gid"], kind)
        led = self._ledger(origin, g.get("sym"))
        unit: Optional[Decimal] = None
        src = ""
        if fsa and len(fsa) >= 2 and fsa[1]:
            unit = _dec(fsa[1]) or None
            src = str(fsa[2]) if len(fsa) >= 3 and fsa[2] else ""
        led["rx"].append((int(ts or 0), q, str(r["location"] or ""), kind, unit, chain, tx, src))
        led["recv"] += q
        if brhist:
            led["brhist"] += 1
        if xc:
            led["xcArr"] += 1
        if ent["native"]:
            return
        ent["free"][origin] = ent["free"].get(origin, _ZERO) + q
        if ret_unk:
            led["retUnk"] += 1
            led["est"] = True
        if br_unk:
            led["brUnk"] += 1

    @staticmethod
    def _dest_open(td: Any, ts: Any) -> bool:
        if not isinstance(td, dict):
            return False
        tls = [t for t in (td.get("ts_list") or []) if t]
        return bool(td.get("no_ts")) or not tls or any(int(t) <= int(ts or 0) for t in tls)

    def _transit_open(self, sym: Any) -> bool:
        return any(len(cell) == 3 and cell[2] > 0 and (cell[0].get("sym") or "?") == (sym or "?") for cell in self.by_ent.values())

    def _take(self, g: dict, qty: Decimal) -> tuple:
        ent = self.groups.get(g["gid"])
        if self.off or ent is None or ent["native"] or qty is None or qty <= 0:
            return {}, _ZERO
        total_free = sum(ent["free"].values(), _ZERO)
        if total_free <= 0:
            return {}, _ZERO
        holding = g["qty_known"] + g["qty_unknown"]
        if holding <= 0:
            return {}, _ZERO
        share = min(_ONE, total_free / holding)
        take = min(total_free, qty * share)
        if take <= 0:
            return {}, _ZERO
        parts = _scaled(ent["free"], take / total_free)
        for origin, amt in parts.items():
            left = ent["free"][origin] - amt
            if left > 0:
                ent["free"][origin] = left
            else:
                del ent["free"][origin]
        return parts, share

    def sell(self, g: dict, qty: Decimal, cost: Optional[Decimal], dkey: str, key: Any = None) -> None:
        parts, share = self._take(g, qty)
        if not parts:
            return
        links = []
        for origin, part in parts.items():
            led = self._ledger(origin, g.get("sym"))
            led["sold"] += part
            if share < _ONE:
                led["est"] = True
            if cost is None:
                led["nopx"] += 1
                led["sales"].append([str(dkey), part, None])
                continue
            usd = cost * part / qty
            led["usd"] += usd
            led["sales"].append([str(dkey), part, usd])
            links.append((origin, len(led["sales"]) - 1, part / qty))
        if key is not None and links:
            self.sale_key[key] = links

    def fee(self, key: Any, usd: Any) -> None:
        links = self.sale_key.get(key) if usd else None
        for origin, idx, share in links or ():
            led = self.ledgers.get(origin)
            if led is None:
                continue
            part = _dec(usd) * share
            led["usd"] -= part
            sale = led["sales"][idx]
            if sale[2] is not None:
                sale[2] = sale[2] - part

    def burn(self, g: dict, qty: Decimal) -> None:
        parts, _share = self._take(g, qty)
        self.last_burn.clear()
        self.last_burn.update(parts)

    def _mark_est(self, origins: Any, conv: bool = False) -> None:
        for origin in origins:
            led = self.ledgers.get(origin)
            if led is not None:
                led["est"] = True
                if conv:
                    led["conv"] += 1

    def conv(self, g: dict) -> None:
        self._mark_est(list(self.last_burn), conv=True)
        self.last_burn.clear()

    def _flush_last_out(self) -> None:
        if self.last_out:
            gid, parts, qty = self.last_out
            if qty > 0:
                self.pending.setdefault(gid, []).append([parts, qty])
            self.last_out.clear()

    def move_out(self, g: dict, qty: Decimal) -> None:
        self._flush_last_out()
        if self.off or qty is None or qty <= 0:
            return
        parts, _share = self._take(g, qty)
        self.last_out[:] = [g["gid"], parts, qty]

    @staticmethod
    def _basis(ent: dict, fallback: Decimal) -> Decimal:
        try:
            basis = _dec(ent.get("qty"))
        except (TypeError, ValueError, ArithmeticError):
            basis = _ZERO
        return basis if basis > 0 else fallback

    def attach(self, ent: Any) -> None:
        if self.off or not isinstance(ent, dict):
            return
        cell = self.by_ent.get(id(ent))
        if cell is None or cell[0] is not ent:
            cell = self.by_ent[id(ent)] = [ent, {}, _ZERO]
        if not self.last_out:
            cell[2] = self._basis(ent, cell[2])
            return
        gid, parts, qty = self.last_out
        frac = _ONE
        basis = self._basis(ent, _ZERO)
        if not ent.get("_cv") and qty > 0 and 0 < basis < qty:
            frac = basis / qty
        for origin, amt in _scaled(parts, frac).items():
            cell[1][origin] = cell[1].get(origin, _ZERO) + amt
            parts[origin] = parts[origin] - amt
        cell[2] = self._basis(ent, cell[2] + qty * frac)
        if frac < _ONE and ent.get("split"):
            self.last_out[:] = [gid, {o: a for o, a in parts.items() if a > 0}, qty - qty * frac]
        else:
            self.last_out.clear()

    @staticmethod
    def _merge_cell(cell: list, parts: dict, qty: Decimal) -> None:
        for origin, amt in parts.items():
            if amt > 0:
                cell[1][origin] = cell[1].get(origin, _ZERO) + amt
        cell[2] += qty

    def _source_for(self, ent: dict, src_gid: Any) -> Optional[list]:
        cell = self.by_ent.get(id(ent))
        if cell is not None and cell[0] is ent and len(cell) == 3:
            return cell
        if cell is None or cell[0] is not ent:
            cell = self.by_ent[id(ent)] = [ent, {}, _ZERO, "bound"]
        n_in = 1 if cell[2] > 0 else 0
        if self.last_out and self.last_out[0] == src_gid:
            self._merge_cell(cell, self.last_out[1], self.last_out[2])
            self.last_out.clear()
            n_in += 1
        for parts_q, qty_q in self.pending.pop(src_gid, None) or []:
            if qty_q > 0:
                self._merge_cell(cell, parts_q, qty_q)
                n_in += 1
        if cell[1] and (n_in > 1 or sum(cell[1].values(), _ZERO) < cell[2]):
            self._mark_est(list(cell[1]))
        return cell if cell[2] > 0 and any(v > 0 for v in cell[1].values()) else None

    def move_in(self, g: dict, ent: Any, scale: Any, ratio: Any = None) -> None:
        if self.off or not isinstance(ent, dict) or g["gid"] in self.native:
            return
        src_gid = ent.get("gid", g["gid"])
        try:
            qin = (_dec(ent.get("known")) + _dec(ent.get("unknown"))) * _dec(scale)
            mult = _dec(ratio) if ratio is not None else _ONE
        except (TypeError, ValueError, ArithmeticError):
            return
        if qin <= 0 or mult <= 0:
            return
        cell = self._source_for(ent, src_gid)
        if cell is None:
            return
        parts, basis = cell[1], cell[2]
        frac = min(_ONE, qin / basis) if basis > 0 else _ONE
        dest = self._ent(g)
        taken = _scaled(parts, frac)
        for origin, amt in taken.items():
            parts[origin] = parts[origin] - amt
            dest["free"][origin] = dest["free"].get(origin, _ZERO) + amt * mult
        if mult != _ONE:
            self._mark_est(list(taken))
        cell[2] = max(_ZERO, basis - qin)
        if cell[2] <= 0 and not any(v > 0 for v in parts.values()):
            self.by_ent.pop(id(ent), None)

    def gas(self, evk: Any, chain: Any, tx: Any, usd: Any) -> None:
        if self.off or evk not in INFLOW_EVENTS or not usd or usd <= 0:
            return
        key = (str(chain or ""), str(tx or ""))
        cell = self.gas_by_tx.get(key)
        if cell is None:
            self.gas_by_tx[key] = [_dec(usd), 1]
        else:
            cell[0] += _dec(usd)
            cell[1] += 1


def pool_observer(book: HarvestBook) -> Callable[[dict], None]:
    return book.attach


def _short(addr: str) -> str:
    text = str(addr or "")
    return text if len(text) <= 14 else text[:6] + "…" + text[-4:]


def _loc_label(loc: str, wallet_label: Any) -> tuple:
    parts = str(loc or "").split(":")
    if len(parts) >= 3 and parts[0] == "wallet":
        chain, addr = parts[1], parts[2]
        name = (wallet_label or {}).get(addr.lower()) if isinstance(wallet_label, dict) else None
        return (f"{name or _short(addr)} · {CHAIN_NAME.get(chain, chain)}", chain)
    if len(parts) >= 2 and parts[0] == "exchange":
        return (parts[1], "")
    return (str(loc or "—"), "")


def _bucket(buckets: dict, day: str, qty: Decimal, usd: Optional[Decimal], n: int = 1) -> None:
    cell = buckets.get(day)
    if cell is None:
        buckets[day] = [qty, usd or _ZERO, n]
    else:
        cell[0] += qty
        cell[1] += usd or _ZERO
        cell[2] += n


def _goplus_strong(conn: Any, gids: set) -> dict:
    if not gids or conn is None:
        return {}
    path = paths.state("goplus_cache.json")
    if not os.path.exists(path):
        return {}
    cache = statefile.read_json(path, {}) or {}
    if not isinstance(cache, dict) or not cache:
        return {}
    out: dict = {}
    try:
        rows = conn.execute("SELECT group_id, chain, address FROM assets WHERE kind='token' AND address IS NOT NULL AND group_id IS NOT NULL").fetchall()
    except Exception:  # noqa: BLE001 [fallback]
        return {}
    for row in rows:
        gid = row["group_id"]
        if gid not in gids or gid in out:
            continue
        risk = (cache.get(f"{row['chain']}:{(row['address'] or '').lower()}") or {}).get("risk")
        if isinstance(risk, dict) and risk.get("strong"):
            out[gid] = str(risk.get("label") or "스캠 확증")
    return out


def _left_by_origin(groups: dict, G: dict, px_of: Any, hidden: set) -> dict:
    out: dict = {}
    for gid, ent in groups.items():
        if not ent["free"]:
            continue
        group = G.get(gid) or {}
        holding = (group.get("qty_known") or _ZERO) + (group.get("qty_unknown") or _ZERO)
        total = sum(ent["free"].values(), _ZERO)
        cap = min(_ONE, holding / total) if total > 0 and holding >= 0 else _ZERO
        price = _ZERO if gid in hidden else _dec(px_of(gid))
        for origin, amt in ent["free"].items():
            cell = out.setdefault(origin, [_ZERO, _ZERO, False, _ZERO])
            cell[0] += amt * cap
            cell[1] += amt * cap * price
            cell[2] = cell[2] or cap < _ONE
            if gid in hidden:
                cell[3] += amt * cap
    return out


def _classify(origin: tuple, led: dict, kit: dict) -> tuple:
    gid, kind = origin
    if gid in kit["quar"]:
        return (CLS_SUSPECT if gid in kit["ad_only"] else CLS_SCAM), str(kit["reasons"].get(gid) or "")
    if gid in kit["strong"]:
        return CLS_SCAM, f"고플러스 {kit['strong'][gid]} — 자동 허용(자기전송·거래소 이력)보다 먼저(보드만 · 보유표는 종전 규칙)"
    if kind == KIND_NATIVE:
        return CLS_NATIVE, "네이티브 코인 그룹의 프로그램 수령(환불·리워드 등 — 원가 없음 · 처분·합계 밖)"
    px = kit["px"]
    visible = kit["ov"].get(f"g{gid}") == "visible"
    if kind == KIND_PUSH:
        values = [(rx[4] if rx[4] is not None else px) * rx[1] if (rx[4] is not None or px > 0) else None for rx in led["rx"]]
        if led["rx"] and all(v is not None and v < DUST_USD for v in values):
            return CLS_SCAM, "주소 오염 의심 초소액 수령(남이 보낸 $0.01 미만 — 최초 인식 단가 또는 지금 시세)"
        if not visible:
            return CLS_PUSH, _push_reason(led)
        return CLS_OK, ""
    if not (visible or px > 0 or kit["sold_usd"] > 0):
        return CLS_SUSPECT, "유동성 있는 시세·실제 매도·사용자 정상 지정이 없음"
    return CLS_OK, ""


def _push_reason(led: dict) -> str:
    out = []
    if led.get("xcArr"):
        out.append("브릿지 도착으로 확인된 수령(출발이 미등록 체인·수집 기간 밖) — 내 코인을 옮긴 것일 수 있어요")
    if led["retUnk"]:
        out.append("보냈던 코인이 돌아온 것일 수 있어요(최초 인식 시가 끔 → 반환 판정 없음)")
    if led.get("brUnk"):
        out.append("브릿지·송금 출발이 아직 짝을 못 찾았거나 확인할 수 없는 코인 — 시간창 밖 브릿지 도착일 수 있어요")
    if len(led["rx"]) > led["retUnk"] + int(led.get("brUnk") or 0):
        out.append("남이 보낸 수령 — 미연동 거래소 출금·OTC·개인 이체일 수 있어요")
    return " · ".join(out) + "(미매칭 탭에서 원가 지정 · 발신 지갑 등록 · 에어드랍이 맞으면 정상으로)"


def _receipts(led: dict, gas_by_tx: dict, seen_tx: set, wallet_label: Any) -> dict:
    out = {"rd": {}, "gd": {}, "pq": {}, "wal": {}, "srcs": {}, "recv_usd": _ZERO, "px_qty": _ZERO, "px_n": 0, "chains": set(), "gas": _ZERO, "gas_n": 0}
    for ts, qty, loc, _kind, unit, chain, tx, src in led["rx"]:
        day = acct_norm.iso_day(ts)
        value = (unit * qty) if unit is not None else None
        if value is not None:
            out["recv_usd"] += value
            out["px_qty"] += qty
            out["px_n"] += 1
            out["srcs"][src or "?"] = out["srcs"].get(src or "?", 0) + 1
        _bucket(out["rd"], day, qty, value)
        _bucket(out["pq"], day, qty if value is not None else _ZERO, None, 1 if value is not None else 0)
        wal = out["wal"].get(loc)
        if wal is None:
            label, wchain = _loc_label(loc, wallet_label)
            wal = out["wal"][loc] = {"loc": label, "chain": wchain, "n": 0, "qty": _ZERO, "usd": _ZERO}
        wal["n"] += 1
        wal["qty"] += qty
        wal["usd"] += value or _ZERO
        if chain:
            out["chains"].add(chain)
        gkey = (chain, tx)
        if gkey in gas_by_tx and gkey not in seen_tx:
            seen_tx.add(gkey)
            out["gas"] += gas_by_tx[gkey][0]
            out["gas_n"] += int(gas_by_tx[gkey][1])
            _bucket(out["gd"], day, _ZERO, gas_by_tx[gkey][0], int(gas_by_tx[gkey][1]))
    return out


def _row(origin: tuple, led: dict, group: dict, kit: dict) -> dict:
    gid, kind = origin
    rx = led["rx"]
    left, left_usd, capped, left_hid = kit["left"].get(origin) or (_ZERO, _ZERO, False, _ZERO)
    px = _dec(kit["px_of"](gid))
    cls, reason = _classify(origin, led, dict(kit, px=px, sold_usd=led["usd"]))
    if cls != CLS_OK:
        left_usd = _ZERO
    rc = _receipts(led, kit["gas_by_tx"], kit["seen_tx"], kit["wallet_label"])
    sd: dict = {}
    for day, qty, usd in led["sales"]:
        _bucket(sd, day, qty, usd, 1 if usd else 0)
    wallets = sorted(rc["wal"].values(), key=lambda w: -w["qty"])[:WALLET_CAP]
    for wal in wallets:
        wal["qty"], wal["usd"] = _f(wal["qty"]), _f(wal["usd"], 2)
    return {"key": f"g{gid}" + ("p" if kind == KIND_PUSH else ""), "gkey": f"g{gid}", "sym": str(led.get("sym") or group.get("sym") or "?"),
            "chains": sorted(CHAIN_NAME.get(c, c) for c in rc["chains"]),
            "cls": cls, "kind": kind, "n": len(rx), "recv": _f(led["recv"]), "recvUsd": _f(rc["recv_usd"], 2), "pxQty": _f(rc["px_qty"]), "pxN": rc["px_n"],
            "pxSrc": max(rc["srcs"], key=rc["srcs"].get) if rc["srcs"] else "",
            "sold": _f(led["sold"]), "soldUsd": _f(led["usd"], 2), "soldN": sum(1 for s in led["sales"] if s[2]), "nopx": int(led["nopx"]),
            "left": _f(left), "leftUsd": _f(left_usd, 2), "leftHid": _f(left_hid), "px": _f(px, 10), "est": bool(led["est"] or capped),
            "retUnk": int(led["retUnk"]), "conv": int(led["conv"]), "brhist": int(led["brhist"]), "brUnk": int(led.get("brUnk") or 0), "xcArr": int(led.get("xcArr") or 0),
            "gas": _f(rc["gas"], 2), "gasN": rc["gas_n"], "reason": reason, "ov": kit["ov"].get(f"g{gid}"),
            "first": acct_norm.iso_day(min(x[0] for x in rx)), "last": acct_norm.iso_day(max(x[0] for x in rx)),
            "w": wallets, "_rd": rc["rd"], "_sd": sd, "_gd": rc["gd"], "_pq": rc["pq"]}


def board(sb: Any, store: dict, G: dict, prefs: Any, aux: Optional[dict] = None) -> dict:
    aux = aux or {}
    ov_all = (prefs or {}).get("risk_overrides") if isinstance(prefs, dict) else None
    groups: dict = store.get("g") or {}
    ledgers: dict = store.get("l") or {}
    quar = set(getattr(sb, "_risk_quarantined", None) or ())
    live_px = getattr(sb, "_live_px", None) or {}
    want = {origin[0] for origin, led in ledgers.items() if led["rx"]} | {gid for gid, ent in groups.items() if ent["free"]}
    strong = _goplus_strong(aux.get("conn"), {gid for gid in want if gid not in quar})
    hidden = quar | set(strong)
    px_of = lambda gid: (live_px.get(gid) or 0) if gid not in hidden else 0   # noqa: E731
    kit = {"quar": quar, "ad_only": set(getattr(sb, "_risk_airdrop_only", None) or ()), "reasons": getattr(sb, "_risk_reasons", None) or {},
           "px_of": px_of, "ov": ov_all if isinstance(ov_all, dict) else {}, "gas_by_tx": store.get("gas") or {},
           "seen_tx": set(), "wallet_label": aux.get("wallet_label"), "left": _left_by_origin(groups, G, px_of, hidden), "strong": strong}
    rank = {KIND_CLAIM: 0, KIND_PUSH: 1, KIND_NATIVE: 2}
    order = sorted(((o, led) for o, led in ledgers.items() if led["rx"]), key=lambda kv: (rank.get(kv[0][1], 9), kv[0][0] in hidden))
    rows = [_row(origin, led, G.get(origin[0]) or {}, kit) for origin, led in order]
    stake_n, stake_usd = 0, _ZERO
    for day in (aux.get("stake_inc") or {}).values():
        for cell in (day or {}).values():
            try:
                stake_n += int(cell[2])
                stake_usd += _dec(cell[0])
            except (TypeError, ValueError, IndexError, ArithmeticError):
                continue
    return {"rows": rows, "ref": {"stakeN": stake_n, "stakeUsd": _f(stake_usd, 2), "fsOn": bool(aux.get("fs_on", True)), "gasOn": bool(aux.get("gas_on", True))}}


def _iso_ok(text: Any) -> Optional[str]:
    text = str(text or "").strip()
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" and text[:4].isdigit() else None


def _sum_days(buckets: dict, lo: Optional[str], hi: Optional[str]) -> tuple:
    qty, usd, n = _ZERO, _ZERO, 0
    for day, cell in buckets.items():
        if (lo and day < lo) or (hi and day > hi):
            continue
        qty += cell[0]
        usd += cell[1]
        n += cell[2]
    return qty, usd, n


def _period_row(row: dict, lo: Optional[str], hi: Optional[str]) -> Optional[dict]:
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if not (lo or hi):
        return out
    rq, rusd, rn = _sum_days(row.get("_rd") or {}, lo, hi)
    sq, susd, sn = _sum_days(row.get("_sd") or {}, lo, hi)
    _gq, gusd, gn = _sum_days(row.get("_gd") or {}, lo, hi)
    if rn == 0 and sq == 0:
        return None
    pq, _pu, pn = _sum_days(row.get("_pq") or {}, lo, hi)
    out.update(recv=_f(rq), recvUsd=_f(rusd, 2), n=rn, pxQty=_f(pq), pxN=pn, sold=_f(sq), soldUsd=_f(susd, 2), soldN=sn, gas=_f(gusd, 2), gasN=gn)
    return out


def api(idx: Any, query: Any) -> dict:
    board_out = (idx or {}).get("harvest") if isinstance(idx, dict) else None
    if not isinstance(board_out, dict):
        return {"ok": False, "error": "아직 빌드 전이에요 — 잠시 뒤 다시"}
    try:
        qs = urllib.parse.parse_qs(str(query or ""))
    except Exception:  # noqa: BLE001 [fallback]
        qs = {}
    lo, hi = _iso_ok((qs.get("since") or [""])[0]), _iso_ok((qs.get("until") or [""])[0])
    out: dict = {"ok": True, "builtAt": idx.get("builtAt"), "since": lo, "until": hi, "ref": board_out.get("ref") or {},
                 "rows": [], "fold": {cls: [] for cls in FOLDS}, "n": {cls: 0 for cls in (CLS_OK,) + FOLDS},
                 "tot": {"recvUsd": 0.0, "soldUsd": 0.0, "soldN": 0, "soldHidUsd": 0.0, "soldHidN": 0, "leftUsd": 0.0, "gasUsd": 0.0, "gasN": 0, "recvN": 0, "est": False}}
    tot = out["tot"]
    for raw in board_out.get("rows") or ():
        row = _period_row(raw, lo, hi)
        if row is None:
            continue
        cls = row["cls"]
        out["n"][cls] += 1
        if cls == CLS_OK:
            tot["recvUsd"] += row["recvUsd"]
            tot["recvN"] += row["n"]
            tot["soldUsd"] += row["soldUsd"]
            tot["soldN"] += row["soldN"]
            tot["leftUsd"] += row["leftUsd"]
            tot["gasUsd"] += row["gas"]
            tot["gasN"] += row["gasN"]
            tot["est"] = tot["est"] or bool(row["est"])
        else:
            tot["soldHidUsd"] += row["soldUsd"]
            tot["soldHidN"] += row["soldN"]
        (out["rows"] if cls == CLS_OK else out["fold"][cls]).append(row)
    order = lambda row: (-(row["soldUsd"] + row["leftUsd"] + row["recvUsd"]), -row["recv"], row["sym"])   # noqa: E731
    out["rows"].sort(key=order)
    out["rows"] = out["rows"][:ROW_CAP[CLS_OK]]
    for cls, rows in out["fold"].items():
        rows.sort(key=order)
        out["fold"][cls] = rows[:ROW_CAP[cls]]
    for name in ("recvUsd", "soldUsd", "soldHidUsd", "leftUsd", "gasUsd"):
        tot[name] = _f(tot[name], 2)
    return out

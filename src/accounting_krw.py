from __future__ import annotations

from decimal import Decimal
from typing import Any

import acct_norm
import calcguard
import histcurve
from view_common import DAYCLOSE_ON
from view_common import EPS
from view_fspin import kd_conf
from view_fspin import kd_pin_load
from view_fspin import kd_ts
from view_misc import fx_candle_near

POOL_DUST_USD = Decimal("0.000001")


class KrwPools:

    def __init__(kpx, px, *, fxb, krw_mkt, up_mkt, fx_name):
        kpx.px = px
        kpx.fxb = fxb
        kpx.krw_mkt = krw_mkt
        kpx.up_mkt = up_mkt
        kpx.fx_name = fx_name
        kpx.fs_last = [Decimal(0)]
        kpx.krw_mix = [Decimal(0)]
        kpx.krw_stl = [None]
        kpx.krw_last = [None]
        kpx.kd_last = [Decimal(0)]
        kpx.kd_for = [None]
        kpx.kd_lost = {}
        kpx.STL_TOP = 8

    def krw_of(kpx, usd, ts9, row9=None):
        try:
            usd = Decimal(usd)
        except Exception as _cg9:  # noqa: BLE001 [fallback]
            calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.krw_of[usd]", _cg9)
            return Decimal(0)
        if row9 is not None and row9["cost_krw"] is not None and row9["cost_usd"] is not None:
            try:
                cu9 = Decimal(row9["cost_usd"])
                if cu9 > 0:
                    return usd * Decimal(row9["cost_krw"]) / cu9
            except Exception as _cg9:  # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_replay:ReplayMixin._build_replay.krw_of[cu9]", _cg9, expected=isinstance(_cg9, ArithmeticError))
                calcguard.row_err("view_b_replay:ReplayMixin._build_replay.krw_of[cu9]", row9)
        return usd * Decimal(str(kpx.fxb.rate_at(ts9)))

    def consume_krw(kpx, g, cost):
        kpx.krw_mix[0] = Decimal(0)
        kpx.fs_last[0] = Decimal(0)
        kpx.krw_stl[0] = None
        kpx.kd_reset()
        flow = g.get("cur")
        if flow is None or cost <= 0:
            return None
        used = flow.get("_cost_used", Decimal(0))
        left = flow["cost"] - used
        if left <= EPS:
            return None
        dust_res = g["cost"] - left
        if not g["is_stable"] and not flow.get("_krw_stale") and EPS < dust_res <= POOL_DUST_USD:
            used_krw = flow.get("_cost_krw_used", Decimal(0))
            flow["_cost_krw_used"] = used_krw - (flow["cost_krw"] - used_krw) * dust_res / left
            flow["_cost_used"] = used = used - dust_res
            left = flow["cost"] - used
        if abs(left - g["cost"]) > EPS:
            if not (g["is_stable"] and g["cost"] > left + EPS):
                flow["_krw_stale"] = True
                return None
            take9 = cost * left / g["cost"]
            kpx.krw_mix[0] = cost - take9
            cost = take9
        used_krw = flow.get("_cost_krw_used", Decimal(0))
        taken = (flow["cost_krw"] - used_krw) * cost / left
        flow["_cost_used"] = used + cost
        flow["_cost_krw_used"] = used_krw + taken
        if flow.get("fs_kc"):
            kpx.fs_last[0] = flow["fs_kc"] * cost / left
            flow["fs_kc"] -= kpx.fs_last[0]
        if flow.get("kd"):
            kpx.kd_last[0] = flow["kd"] * cost / left
            flow["kd"] -= kpx.kd_last[0]
            kpx.kd_for[0] = taken
        if flow.get("_stl"):
            kpx.stl_take(flow, float(cost) / float(left), float(left))
        return taken

    def kd_reset(kpx: KrwPools) -> None:
        if kpx.kd_last[0]:
            kpx.kd_lose("left", kpx.kd_last[0])
            kpx.kd_last[0] = Decimal(0)
        kpx.kd_for[0] = None

    def kd_lose(kpx: KrwPools, why: str, val: Decimal | None) -> None:
        if val:
            ent = kpx.kd_lost.setdefault(why, [Decimal(0), 0])
            ent[0] += Decimal(val)
            ent[1] += 1

    def kd_take(kpx: KrwPools, cck: Decimal | None) -> Decimal:
        if cck is None or cck is not kpx.kd_for[0] or not kpx.kd_last[0]:
            return Decimal(0)
        val = kpx.kd_last[0]
        kpx.kd_last[0] = Decimal(0)
        kpx.kd_for[0] = None
        return val

    def kd_cut(kpx: KrwPools, ratio: Decimal) -> Decimal:
        val = kpx.kd_last[0] * ratio
        kpx.kd_last[0] -= val
        return val

    def kd_put(kpx: KrwPools, entry: dict, val: Decimal) -> None:
        kpx.kd_last[0] = Decimal(0)
        kpx.kd_for[0] = None
        if val:
            entry["kd"] = entry.get("kd", Decimal(0)) + val

    def kd_move(kpx: KrwPools, flow: dict, entry: dict, share: Decimal) -> None:
        amt = entry.get("kd")
        if amt:
            kpx.kd_in(flow, entry, share)
            entry["kd"] = amt - amt * min(Decimal(1), share)

    def kd_in(kpx: KrwPools, flow: dict | None, entry: dict, share: Decimal) -> None:
        amt = entry.get("kd")
        if amt and flow is not None and share > 0:
            flow["kd"] = flow.get("kd", Decimal(0)) + amt * share

    def krw_took(kpx, mc9, ts9):
        if kpx.krw_last[0] is None:
            return kpx.krw_of(mc9, ts9)
        return kpx.krw_last[0] + (kpx.krw_of(kpx.krw_mix[0], ts9) if kpx.krw_mix[0] > 0 else Decimal(0))

    def krw_rec(kpx, mc9):
        if kpx.krw_last[0] is None:
            return Decimal(0), Decimal(0)
        return mc9 - kpx.krw_mix[0], kpx.krw_last[0]

    def krw_inh(kpx, e9, part9, ts9):
        k9, c9 = e9.get("krw"), e9.get("cost")
        if k9 is not None and c9 is not None and c9 > 0:
            return k9 * part9 / c9
        return kpx.krw_of(part9, ts9)

    def stl_krw_mkt(kpx, r9):
        return (r9["source_ns"], r9["source_id"]) in kpx.krw_mkt or (r9["source_ns"] == "upbit:order" and kpx.up_mkt.get(r9["source_id"], "KRW") == "KRW")

    def stl_ex(kpx, r9):
        l9 = str(r9["location"] or "")
        return kpx.fx_name.get(l9.split(":")[-1], l9.split(":")[-1]) if l9.startswith("exchange:") else "온체인"

    def stl_src(kpx, r9, evk9):
        if kpx.stl_krw_mkt(r9):
            return f"{kpx.stl_ex(r9)} 원화 매수"
        d9 = [(s9, k9) for s9, k9 in (kpx.px.tx_legsym.get((r9["source_ns"], r9["source_id"])) or {}).get("disp", ()) if k9 != "fiat"]
        tok9 = [s9 for s9, k9 in d9 if k9 in ("tok", "nat")]
        if tok9:
            return f"{tok9[0]} 매도 대금"
        if d9:
            return f"{d9[0][0]} 교환"
        return {"EX_DEPOSIT": "입금", "EXF_DEPOSIT": "입금", "TRANSFER_IN": "입금"}.get(evk9, "취득")

    def stl_use(kpx, r9, krw_sale9):
        if krw_sale9:
            return "원화 매도"
        a9 = [(s9, k9) for s9, k9 in (kpx.px.tx_legsym.get((r9["source_ns"], r9["source_id"])) or {}).get("acq", ()) if k9 != "fiat"]
        tok9 = [s9 for s9, k9 in a9 if k9 in ("tok", "nat")]
        if tok9:
            return f"{tok9[0]} 매수 대금"
        if a9:
            return f"{a9[0][0]} 교환"
        return "처분"

    def stl_add(kpx, fl9, day9, lab9, usd9, krw9, qty9=None):
        if fl9 is None or usd9 <= 0:
            return
        d9 = fl9.get("_stl")
        if d9 is None:
            d9 = fl9["_stl"] = {}
            fl9["_stlt"] = []
            fl9["_stlm"] = 1.0
        m9 = fl9["_stlm"]
        if m9 < 1e-9:
            for a9 in d9.values():
                a9[0] *= m9
                a9[1] *= m9
                a9[2] *= m9
            m9 = fl9["_stlm"] = 1.0
        k9 = (day9, lab9)
        a9 = d9.get(k9)
        if a9 is None:
            a9 = d9[k9] = [0.0, 0.0, 0.0]
        a9[0] += float(usd9) / m9
        a9[1] += float(krw9) / m9
        a9[2] += float(usd9 if qty9 is None else qty9) / m9
        t9 = fl9["_stlt"]
        if k9 in t9 or len(t9) < kpx.STL_TOP or a9[0] > d9[t9[-1]][0]:
            if k9 not in t9:
                t9.append(k9)
            t9.sort(key=lambda x9: -d9[x9][0])
            del t9[kpx.STL_TOP:]

    def stl_take(kpx, fl9, f9, left9):
        d9, m9 = fl9["_stl"], fl9["_stlm"]
        top9 = []
        for k9 in fl9["_stlt"][:5]:
            u9, w9, n9 = d9[k9][0] * m9, d9[k9][1] * m9, d9[k9][2] * m9
            top9.append((k9[0], k9[1], u9 * f9, w9 * f9, min(1.0, u9 / left9) if left9 > 0 else 0.0, n9 * f9))
        kpx.krw_stl[0] = {"l": top9, "o": max(0.0, 1.0 - sum(x9[4] for x9 in top9[:3]))}
        fl9["_stlm"] = m9 * max(0.0, 1.0 - f9)

    def stl_out(kpx, kc9):
        if kc9 <= 0 or not kpx.krw_stl[0]:
            return []
        return [[d9, l9, u9, w9, n9] for d9, l9, u9, w9, _x9, n9 in kpx.krw_stl[0]["l"]]

    def stl_carry(kpx, e9, kc9):
        e9.setdefault("_stl", []).extend(kpx.stl_out(kc9))

    def stl_in(kpx, fl9, e9, sc9):
        if fl9 is None or sc9 <= 0:
            return
        f9 = float(sc9)
        for x9 in e9.get("_stl") or ():
            kpx.stl_add(fl9, x9[0], x9[1], x9[2] * f9, x9[3] * f9, (x9[4] if len(x9) > 4 else x9[2]) * f9)


KD_MIN_UP = Decimal("0.5")
KD_FX_OK = ("minute", "close", "near36h")


class KrDeemed:

    def __init__(self, fsx: Any) -> None:
        self.fsx = fsx
        self.at = None
        self.pin = {}
        self.miss: list[Any] = []
        day = kd_conf(fsx.px.ctx.prefs)
        if day is None:
            return
        t_at = kd_ts(day)
        fsx.px.unx.fs_sum["kd"] = {"at": day, "state": "before" if fsx.now < t_at else "applied", "n": 0, "keep": 0, "wait": 0, "none": 0,
                                   "skip": 0, "unk": 0, "tr": 0, "up": 0.0, "rows": 0, "add": 0.0, "lost": 0.0, "miss": 0.0,
                                   "lostBy": {}, "pin_new": {}}
        if fsx.now >= t_at:
            self.at = t_at
            self.pin = kd_pin_load(day)

    def apply(self, groups: dict, pools: tuple = (), brs: Any = ()) -> None:
        t_at, self.at = self.at, None
        if t_at is None:
            return
        summ = self.fsx.px.unx.fs_sum["kd"]
        for grp in groups.values():
            if grp.get("is_fiat"):
                continue
            if grp["qty_unknown"] > EPS and not grp["is_stable"]:
                summ["unk"] += 1
            if grp["qty_known"] <= EPS:
                continue
            share = self._share(grp)
            if share is None:
                summ["skip"] += 1
                continue
            unit, src = self.price(grp, t_at)
            if unit is None:
                summ["wait" if src == "wait" else "none"] += 1
                continue
            flow = grp["cur"]
            qty = grp["qty_known"] * share
            book = flow["cost_krw"] - flow.get("_cost_krw_used", Decimal(0))
            up = Decimal(str(unit)) * qty - book
            grp["_kd"] = {"u": unit, "q": float(qty), "book": float(book), "src": src}
            if up > KD_MIN_UP:
                flow["kd"] = flow.get("kd", Decimal(0)) + up
                summ["n"] += 1
                summ["up"] += float(up)
            else:
                summ["keep"] += 1
        for ent in self.live(pools):
            self._transit_up(groups.get(ent.get("gid")), ent, t_at, summ)
        px = self.fsx.px
        self.snap(groups, (("br", brs), ("rt", px.omx.rt_transit), ("ret", self.fsx.ret_pool), ("offc", px.ofx.offc_pool)), t_at)
        if summ["wait"]:
            summ["state"] = "waiting"

    def _share(self, grp: dict) -> Decimal | None:
        flow, cost = grp.get("cur"), grp["cost"]
        if flow is None or flow.get("_krw_stale") or cost <= EPS:
            return None
        left = flow["cost"] - flow.get("_cost_used", Decimal(0))
        if left <= EPS:
            return None
        if grp["is_stable"]:
            return None if left > cost + EPS else min(Decimal(1), left / cost)
        return Decimal(1) if -EPS <= cost - left <= POOL_DUST_USD else None

    def _transit_up(self, grp: dict | None, ent: dict, t_at: int, summ: dict) -> None:
        if grp is None or grp.get("is_fiat") or not ent.get("qty"):
            return
        unit, src = self.price(grp, t_at)
        if unit is None:
            summ["wait" if src == "wait" else "none"] += 1
            return
        up = self._up(grp, ent, unit, ent.get("krw") or Decimal(0))
        if up > KD_MIN_UP:
            ent["kd"] = ent.get("kd", Decimal(0)) + up
            summ["tr"] += 1
            summ["up"] += float(up * (ent["left"] / ent["qty"] if "left" in ent else 1))

    @staticmethod
    def _up(grp: dict, ent: dict, unit: float, book: Decimal) -> Decimal:
        qty = ent.get("known") or Decimal(0)
        if ent.get("_cv"):
            ratio = Decimal(str(ent["_cv"].get("ratio") or 0))
            qty = qty / ratio if ratio > 0 else Decimal(0)
        if grp["is_stable"]:
            qty = qty * (ent.get("kc") or Decimal(0)) / ent["cost"] if ent.get("cost") else Decimal(0)
            book = ent.get("kk") or Decimal(0)
        return Decimal(str(unit)) * qty - book

    def snap(self, groups: dict, miss: tuple, t_at: int) -> None:
        kpx = self.fsx.px.kpx
        for why, pool in miss:
            for gid, ent in self._ents(pool):
                grp, left = groups.get(gid), ent.get("left") or Decimal(0)
                if grp is None or grp.get("is_fiat") or left <= EPS or not ent.get("qty") or not ent.get("known"):
                    continue
                unit = self.price(grp, t_at, peek=True)[0]
                book = next((ent[k] for k in ("krw", "cost_krw") if ent.get(k) is not None), None)
                book = kpx.krw_of(ent.get("cost") or 0, t_at) if book is None else book
                self.miss.append((why, ent, left, ent["qty"], None if unit is None else self._up(grp, ent, unit, book)))

    @staticmethod
    def _ents(pool: Any) -> list:
        out = []
        for key, val in (pool.items() if isinstance(pool, dict) else enumerate(pool)):
            if isinstance(val, list):
                out += [(e.get("gid"), e) for e in val if isinstance(e, dict)]
            elif isinstance(val, dict) and "left" in val:
                out.append((val["gid"] if "gid" in val else key[-1] if isinstance(key, tuple) else None, val))
            elif isinstance(val, dict):
                out += [(key, e) for e in val.values() if isinstance(e, dict)]
        return out

    @staticmethod
    def live(pools: tuple) -> list:
        out = []
        for pool in pools:
            for val in (pool.values() if isinstance(pool, dict) else pool):
                for ent in (val if isinstance(val, list) else (val,)):
                    if isinstance(ent, dict) and (ent.get("left", Decimal(0)) > EPS if "left" in ent else not ent.get("used", True)):
                        out.append(ent)
        return out

    def price(self, grp: dict, t_at: int, peek: bool = False) -> tuple:
        fsx = self.fsx
        new = fsx.px.unx.fs_sum["kd"]["pin_new"]
        pin = dict(new, **self.pin) if peek else self.pin
        new = {} if peek else new
        if grp["is_stable"]:
            if "fx" in pin:
                return pin["fx"][0], "pin"
            rate, rsrc = fsx.fxb.rate_src(t_at)
            if rsrc not in KD_FX_OK or not rate:
                return None, "wait"
            new["fx"] = [float(rate), "fx-" + rsrc, int(fsx.now)]
            return float(rate), "fx-" + rsrc
        spec = fsx.fs_spec(grp)
        if not spec or spec in ("stable", "ov") or (spec.startswith("ca:") and not fsx.fs_ok_ca(grp)):
            return None, "none"
        if spec in pin:
            return pin[spec][0], "pin"
        usd, src = self._usd(spec, t_at, not peek)
        if usd is None:
            return None, src
        rate, rsrc = fsx.fxb.rate_src(t_at)
        if rsrc not in KD_FX_OK or not rate:
            return None, "wait"
        unit = usd * float(rate)
        new[spec] = [unit, src, int(fsx.now)]
        return unit, src

    def _usd(self, spec: str, t_at: int, ask: bool = True) -> tuple:
        fsx = self.fsx
        if spec.startswith("sym:"):
            minute = fx_candle_near(fsx.fxb, spec[4:], t_at, 3600)
            if minute:
                return float(minute), "minute"
        if not DAYCLOSE_ON:
            return None, "wait"
        try:
            close, state = histcurve.DAYCLOSE.lookup(spec, acct_norm.iso_day(t_at), fsx.now, 0.0, ask=ask, old=True)
        except Exception as exc:   # noqa: BLE001 [fallback]
            calcguard.swallowed("accounting_krw:KrDeemed._usd", exc)
            return None, "wait"
        if close and close > 0:
            return float(close), "close"
        return None, "none" if state == "none" else "wait"

    def row(self, tax: dict, grp: dict, kd: Decimal | None) -> None:
        if not kd:
            return
        summ = self.fsx.px.unx.fs_sum.get("kd")
        if summ is None:
            return
        if tax.get("_akr") is None:
            self.fsx.px.kpx.kd_lose("akr", kd)
            return
        tax["_akr"] += float(kd)
        tax["akr"] = round(tax["_akr"])
        tax["_kd"] = float(kd)
        tax["kd"] = round(float(kd))
        if grp.get("_kd"):
            tax["kdu"] = round(grp["_kd"]["u"], 2)
        summ["rows"] += 1
        summ["add"] += float(kd)

    def end(self) -> None:
        summ = self.fsx.px.unx.fs_sum.get("kd")
        if summ is None:
            return
        kpx = self.fsx.px.kpx
        kpx.kd_reset()
        by = {why: [float(v[0]), v[1]] for why, v in kpx.kd_lost.items()}
        summ["lost"] = round(summ["lost"] + sum(v[0] for v in by.values()))
        for why, ent, left, qty, up in self.miss:
            got = left - max(Decimal(0), ent.get("left") or Decimal(0))
            if got > EPS and (up is None or up > KD_MIN_UP):
                val = float(up * min(Decimal(1), got / qty)) if up is not None else 0.0
                cnt = by.setdefault("tr_" + why, [0.0, 0])
                cnt[0] += val
                cnt[1] += 1
                summ["miss"] += val
        summ["lostBy"] = {why: [round(v[0]), v[1]] for why, v in sorted(by.items())}
        summ["up"], summ["add"], summ["miss"] = round(summ["up"]), round(summ["add"]), round(summ["miss"])

from __future__ import annotations

from decimal import Decimal
from decimal import InvalidOperation

import buychart
import lpdec
import lpsol
import spamguard
from view_common import EPS


def be_cap_of(v9):
    if not isinstance(v9, dict) or "qty" not in v9:
        return None
    try:
        q9 = Decimal(str(v9.get("qty"))) if v9.get("qty") is not None else Decimal(0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)
    return q9 if (q9.is_finite() and q9 >= 0) else Decimal(0)


def _un(qn, usd):
    try:
        qd = qn if type(qn) is Decimal else Decimal(str(qn))
        ud = usd if type(usd) is Decimal else Decimal(str(usd))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not qd.is_finite() or not ud.is_finite() or qd == 0 or ud == 0:
        return None
    return float(f"{abs(ud / qd):.10g}")


def stable_fx_mark(tax9, cc9, krw_sale, stl9=None, cck9=None, mix9=None, use9=None):
    ak9 = tax9.get("_akr")
    tax9["tk"] = "st"
    tax9["_sfx"] = (float(cc9) * float(tax9.get("rate") or 0) - float(ak9)) if ak9 is not None else None
    if krw_sale:
        tax9["_sfk"] = 1
    q9 = float(tax9.get("_qty") or tax9.get("qty") or 0)
    rt9 = float(tax9.get("rate") or 0)
    fx9 = {"u": use9 or ("원화 매도" if krw_sale else "처분")}
    if q9 > 0 and rt9 > 0:
        fx9["d"] = round(float(tax9.get("_disp", tax9.get("disp")) or 0) * rt9 / q9, 2)
    if ak9 is not None and cck9 is not None and cc9 > 0 and q9 > 0:
        kq9 = q9 * float(cc9 - (mix9 or Decimal(0))) / float(cc9)
        if kq9 > 0:
            fx9["a"] = round(float(cck9) / kq9, 2)
            fx9["kq"] = round(kq9, 6)
    top9 = (stl9 or {}).get("l") if ak9 is not None else None
    if top9:
        fx9["l"] = [[d9, l9, round(n9, 2), round(k9 / n9, 2) if n9 > 0 else None, round(w9 * 100, 1)] for d9, l9, u9, k9, w9, n9 in top9[:3]]
        fx9["o"] = round(float(stl9.get("o") or 0) * 100, 1)
    tax9["fx"] = fx9


def oa_take(g9, take9):
    a9 = g9.get("oa") or Decimal(0)
    if a9 <= 0 or take9 <= 0:
        return Decimal(0)
    k9 = g9["qty_known"]
    p9 = a9 if take9 >= k9 else a9 * take9 / k9
    g9["oa"] = a9 - p9
    return p9


def cp_pool(g):
    if g.get("is_stable"):
        return None
    p9 = g.get("_cp")
    if p9 is None:
        p9 = g["_cp"] = buychart.CpPool()
    return p9


def cp_merge(dst9, mp9, s9=1.0):
    if not mp9:
        return dst9
    for k9, (q9, c9) in mp9.items():
        a9 = dst9.setdefault(k9, [0.0, 0.0])
        a9[0] += q9 * s9
        a9[1] += c9 * s9
    return dst9


def fs_in(fl9, e9, sc9):
    fk9 = (e9.get("fk") or Decimal(0)) * sc9
    if fk9 > EPS:
        fl9["fs_kc"] = fl9.get("fs_kc", Decimal(0)) + fk9


def _qfmt(v):
    v = float(v)
    return f"{v:,.4f}".rstrip("0").rstrip(".") if abs(v) >= 1 else f"{v:.6g}"


def mv_note(fl, label, q, own=True):
    if fl is None or not label or q <= 0:
        return
    a = fl.setdefault("mv_to", {}).setdefault(label, [Decimal(0), own])
    a[0] += q


def nopx_px_ok(r9):
    return r9["kind"] in ("native", "exchange_currency") or spamguard.is_genuine(r9["chain"], r9["address"])


def lp_label(b9):
    t9 = lpdec.lp_tid(b9["id"])
    if isinstance(t9, int):
        return f"{b9['name']} #{b9['id']}"
    if t9 is not None:
        return f"{b9['name']} #{lpsol.short(str(t9)) if not str(t9).startswith('0x') else str(t9)[:6] + '…' + str(t9)[-4:]}"
    return f"{b9['name']} (포지션 번호 미상)"


class Invariants:
    KINDS = ("known_gt_held", "cost_neg", "cost_no_qty")
    MAX_EX = 12

    def __init__(self):
        self.n = {k: 0 for k in self.KINDS}
        self.ex = []

    def check(self, gid, sym, held, k_all, c_all):
        try:
            tol = Decimal("1e-6") * max(abs(held), Decimal(1))
            if k_all > held + tol and k_all > EPS:
                self._hit("known_gt_held", gid, sym, held, k_all, c_all)
            if c_all < Decimal("-0.01"):
                self._hit("cost_neg", gid, sym, held, k_all, c_all)
            if k_all <= EPS and c_all > Decimal("0.01"):
                self._hit("cost_no_qty", gid, sym, held, k_all, c_all)
        except (TypeError, ArithmeticError):
            pass

    def _hit(self, kind, gid, sym, held, k_all, c_all):
        self.n[kind] += 1
        self.ex.append({"k": kind, "gid": gid, "sym": str(sym)[:24], "held": float(held), "known": float(k_all), "cost": round(float(c_all), 2)})

    def to_diag(self, diag):
        for k in self.KINDS:
            diag["inv_" + k] = self.n[k]
        self.ex.sort(key=lambda e: -abs(e["known"] - e["held"]))
        diag["inv_ex"] = self.ex[:self.MAX_EX]

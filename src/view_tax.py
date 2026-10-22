from __future__ import annotations
import acct_norm
from view_common import _f

FEE_TAX_EX = "수수료로 쓴 코인(처분)"


def _tax_fee_key(r):
    ex9 = str(r.get("ex") or "")
    if r.get("tk") == "st" or not (ex9 == FEE_TAX_EX or ex9.startswith(FEE_TAX_EX + " · ")):
        return None
    return (str(r.get("sold") or ""), r.get("sym") or "?", ex9, r.get("tk") or "")


def _tax_fee_merge(rows):
    grp, out = {}, []
    for r in rows:
        k9 = _tax_fee_key(r)
        if k9 is None:
            out.append(r)
            continue
        g9 = grp.get(k9)
        if g9 is None:
            grp[k9] = g9 = [len(out), []]
            out.append(None)
        g9[1].append(r)
    for pos9, rs9 in grp.values():
        if len(rs9) == 1:
            out[pos9] = rs9[0]
            continue
        v9 = lambda r, k: float(r.get("_" + k, r.get(k)) or 0)
        qa, aa, da, fa = (sum(v9(r, k) for r in rs9) for k in ("qty", "acq", "disp", "fee"))
        dk9 = sum(v9(r, "disp") * float(r.get("rate") or 0) for r in rs9)
        rt9 = dk9 / da if da > 0 else float(rs9[0].get("rate") or 0)
        m9 = {k: rs9[0][k] for k in ("sold", "sym", "ticker", "ex", "tk") if k in rs9[0]}
        srcs9 = {r.get("rateSrc") for r in rs9}
        m9.update({"qty": round(qa, 4), "acq": round(aa, 2), "disp": round(da, 2), "fee": round(fa, 2), "rate": round(rt9, 6),
                   "rateSrc": srcs9.pop() if len(srcs9) == 1 else "mix", "n": len(rs9), "_qty": qa, "_acq": aa, "_disp": da, "_fee": fa})
        ak9 = sum(float(r.get("_akr", r.get("akr"))) if r.get("_akr", r.get("akr")) is not None else v9(r, "acq") * float(r.get("rate") or 0) for r in rs9)
        m9["_akr"], m9["akr"] = ak9, round(ak9)
        out[pos9] = m9
    return out


def _tax_summary(rows, today):
    acc, fee_days = {}, set()
    for r in rows:
        ym = acct_norm.month_of(r.get("sold"), today)
        if not ym:
            continue
        key = (ym, r.get("sym") or "?", r.get("ex") or "", r.get("tk") or "")
        a = acc.setdefault(key, [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0])
        fk9 = _tax_fee_key(r)
        if fk9 is None or fk9 not in fee_days:
            a[0] += 1
            if fk9 is not None:
                fee_days.add(fk9)
        acq9, disp9, fee9 = (float(r.get("_" + k9, r.get(k9)) or 0) for k9 in ("acq", "disp", "fee"))
        a[1] += float(r.get("_qty", r.get("qty")) or 0); a[2] += acq9
        a[3] += disp9; a[4] += fee9
        rt = float(r.get("rate") or 0)
        ak9 = r.get("_akr", r.get("akr"))
        if r.get("_akm") and ak9 is not None:
            a[5] += disp9 * rt - float(ak9) - fee9 * rt
            a[6] += float(ak9)
        else:
            a[5] += (disp9 - acq9 - fee9) * rt
            a[6] += acq9 * rt
        a[7] += disp9 * rt
        a[8] += int(r.get("tx") or 0)
        if ak9 is None:
            ak9 = acq9 * rt
            a[11] += 1 if acq9 else 0
        a[9] += float(ak9)
        a[10] += disp9 * rt - float(ak9) - fee9 * rt
    return [[k[0], k[1], k[2], v[0], round(v[1], 6), round(v[2], 4), round(v[3], 4), round(v[4], 4), round(v[5], 2), round(v[6], 2), round(v[7], 2), v[8],
             round(v[9], 2), round(v[10], 2), v[11], k[3]]
            for k, v in sorted(acc.items())]


def _tax_stable_fx(rows, today):
    acc = {}
    for r in rows:
        if "_sfx" not in r:
            continue
        ym = acct_norm.month_of(r.get("sold"), today)
        if not ym:
            continue
        a = acc.setdefault(ym, [0, 0, 0.0, 0, 0.0])
        v = r.get("_sfx")
        a[0] += 1
        if v is not None:
            a[1] += 1
            a[2] += float(v)
        if r.get("_sfk"):
            a[3] += 1
            if v is not None:
                a[4] += float(v)
    return {k: [v[0], v[1], round(v[2]), v[3], round(v[4])] for k, v in sorted(acc.items())}


def _tax_add(t, k, v):
    t["_" + k] = float(t.get("_" + k, t.get(k) or 0)) + float(v)
    t[k] = _f(t["_" + k], 2)

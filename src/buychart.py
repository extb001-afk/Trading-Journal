"""Buy/sell timing chart and score for trade receipts."""
from __future__ import annotations

import bisect
import heapq
import math
import re
from datetime import datetime, timedelta, timezone

import sellchart

KST = timezone(timedelta(hours=9))
CLUSTER_GAP_S = 3 * 3600
PRE_B = 3600
POST_B = 3600
MAX_SEGS = 3
MATCH_WIN_S = 72 * 3600
TRIM_MULT = 1.5
CHASE_S = 3600
KIND_SHORT = {"온체인 매수": "스왑", "LP 전환 매수": "LP 전환", "거래소 매수": "거래소", "브릿지 전환": "브릿지 전환"}
_f = sellchart._f
_r = sellchart._r
_pct = sellchart._pct


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if math.isfinite(v) else None
    return _f(str(v).replace("$", "").replace("₩", "").strip())


def kst_day(ts) -> str:
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d")


def is_buy(e) -> bool:
    k = str(e.get("k") or "")
    return "매수" in k and "매도" not in k


def is_pay_leg(e) -> bool:
    d = str(e.get("d") or "")
    return bool(e.get("_pay")) or "스왑 지불" in d or "대금 지불" in d


def is_sell(e) -> bool:
    return "매도" in str(e.get("k") or "") and not is_pay_leg(e)


def is_inflow(e) -> bool:
    k, d = str(e.get("k") or ""), str(e.get("d") or "")
    if k == "입금 확인":
        return "승계" in d or "이관" in d
    return k in ("전송", "외부 전송") and "도착" in d and "승계" in d


def is_outflow(e) -> bool:
    k, d = str(e.get("k") or ""), str(e.get("d") or "")
    return k in ("전송", "외부 전송") and "→" in d and "내 지갑 간 이동" not in d and "도착" not in d


def _sym_norm(s) -> str:
    return str(s or "").split("#", 1)[0].strip().upper()


def keep_leg_row(kind, card_gid, row_gid, row_sym, coin_syms) -> bool:
    if card_gid is None or row_gid is None or int(row_gid) == int(card_gid):
        return True
    if kind != "LP 전환 매수":
        return True
    return _sym_norm(row_sym) in {_sym_norm(x) for x in (coin_syms or ())}


def in_dest(e):
    k, d = str(e.get("k") or ""), str(e.get("d") or "")
    if k == "입금 확인":
        m = re.match(r"\s*(\S+) 입금 완료", d)
        return m.group(1) if m else None
    m = re.search(r"출금 도착 · ([^·(]+?)\s*(?:·|$)", d)
    return m.group(1).strip() if m else None


def out_dest(e):
    d = str(e.get("d") or "")
    if "→" not in d:
        return None
    t = d.rsplit("→", 1)[1].strip()
    m = re.match(r"내 지갑 \(([^)]+)\)", t)
    if m:
        return m.group(1).strip()
    m = re.match(r"(\S+) 입금", t)
    return m.group(1) if m else None


def _tx_ok(t) -> bool:
    return bool(t) and t not in ("—", "-", "–")


WAC_REBASE = 1e-150
LINEAGE_DEPTH = 8


_U = 1.12e-16


class _TopK:
    __slots__ = ("mk", "K", "seq", "nseq", "top", "th", "rh", "rq", "rc", "rq_err", "rc_err", "dirty", "amin")

    @classmethod
    def build(cls, it, mk, K):
        fx = cls()
        fx.mk, fx.K = mk, K
        fx.seq = {k: i for i, k in enumerate(it)}
        fx.nseq = len(fx.seq)
        sq9 = fx.seq
        order = sorted((k for k in it if k != mk), key=lambda k: (-it[k][0], sq9[k]))
        top, rest = order[:K], order[K:]
        fx.top = set(top)
        fx.th = [(it[k][0], -sq9[k], k) for k in top]
        heapq.heapify(fx.th)
        fx.rh = [(-it[k][0], sq9[k], k) for k in rest]
        heapq.heapify(fx.rh)
        fx._resum(it)
        fx.dirty = set()
        fx.amin = min(a[0] for a in it.values())
        return fx

    def _resum(self, it):
        top, mk = self.top, self.mk
        rest = [it[k] for k in it if k != mk and k not in top]
        self.rq = sum(a[0] for a in rest)
        self.rc = sum(a[1] for a in rest)
        self.rq_err = (len(rest) + 1) * _U * self.rq
        self.rc_err = (len(rest) + 1) * _U * self.rc

    def rest_add(self, dq, dc):
        self.rq += dq
        self.rc += dc
        self.rq_err += _U * self.rq
        self.rc_err += _U * self.rc

    def _top_min(self, it):
        th, top = self.th, self.top
        while th:
            a0, ns, k = th[0]
            if k in top and it[k][0] == a0:
                return a0, -ns, k
            heapq.heappop(th)
        return None

    def _rest_max(self, it):
        rh, top, mk = self.rh, self.top, self.mk
        while rh:
            na0, s9, k = rh[0]
            if k != mk and k not in top and it[k][0] == -na0:
                return -na0, s9, k
            heapq.heappop(rh)
        return None

    def settle(self, it):
        seq, top, th, rh = self.seq, self.top, self.th, self.rh
        for k in self.dirty:
            a0 = it[k][0]
            if k in top:
                heapq.heappush(th, (a0, -seq[k], k))
            else:
                heapq.heappush(rh, (-a0, seq[k], k))
        self.dirty.clear()
        while True:
            R = self._rest_max(it)
            if R is None:
                break
            T = self._top_min(it) if len(top) >= self.K else None
            if T is not None and not (R[0] > T[0] or (R[0] == T[0] and R[1] < T[1])):
                break
            ar = it[R[2]]
            top.add(R[2])
            heapq.heappush(th, (ar[0], -R[1], R[2]))
            self.rq -= ar[0]
            self.rc -= ar[1]
            self.rq_err += _U * abs(self.rq)
            self.rc_err += _U * abs(self.rc)
            if T is not None:
                at = it[T[2]]
                top.discard(T[2])
                heapq.heappush(rh, (-at[0], T[1], T[2]))
                self.rest_add(at[0], at[1])
        if len(rh) > 2 * (len(it) - len(top)) + 64:
            self.rh = [(-it[k][0], seq[k], k) for k in it if k != self.mk and k not in top]
            heapq.heapify(self.rh)
        if len(th) > 4 * len(top) + 64:
            self.th = [(it[k][0], -seq[k], k) for k in top]
            heapq.heapify(self.th)
        if self.rq_err > 1e-12 * self.rq or self.rc_err > 1e-12 * self.rc:
            self._resum(it)


class CpPool:
    __slots__ = ("m", "it", "sq", "sc", "_fx")
    STATS = {"fast": 0, "slow_small": 0, "slow_thr": 0, "slow_tie": 0, "build": 0}

    def __init__(self):
        self.m = 1.0
        self.it = {}
        self.sq = 0.0
        self.sc = 0.0
        self._fx = None

    def _clear(self):
        self.it.clear()
        self.m = 1.0
        self.sq = 0.0
        self.sc = 0.0
        self._fx = None

    def add(self, key, q, c):
        q, c = float(q), float(c)
        if q <= 0:
            return
        dq, dc = q / self.m, max(0.0, c) / self.m
        a = self.it.get(key)
        fx = self._fx
        if a is None:
            self.it[key] = [dq, dc]
            if fx is not None:
                fx.seq[key] = fx.nseq
                fx.nseq += 1
                if dq < fx.amin:
                    fx.amin = dq
                if key != fx.mk:
                    fx.rest_add(dq, dc)
                    fx.dirty.add(key)
        else:
            a[0] += dq
            a[1] += dc
            if fx is not None and key != fx.mk:
                if key not in fx.top:
                    fx.rest_add(dq, dc)
                fx.dirty.add(key)
        self.sq += dq
        self.sc += dc

    def add_map(self, mp, s=1.0):
        for k, (q, c) in (mp or {}).items():
            self.add(k, q * float(s), c * float(s))

    def total(self):
        return (self.sq * self.m, self.sc * self.m)

    def sync(self, kn, cost, gap_key):
        kn, cost = float(kn), float(cost)
        sq, sc = self.total()
        if kn > sq + max(1e-12, 1e-9 * kn):
            self.add(gap_key, kn - sq, max(0.0, cost - sc))
        elif sq > kn + max(1e-12, 1e-9 * max(kn, 1e-12)) and sq > 0:
            if kn <= 1e-15:
                self._clear()
            else:
                self.m *= kn / sq

    def take(self, kn, take, cost, merge_key, max_n=64):
        kn, take, cost = float(kn), float(take), float(cost)
        if take <= 0 or kn <= 0 or not self.it:
            return None
        f = min(1.0, take / kn)
        m = self.m
        out = self._take_fast(m, f, cost, merge_key, max_n) if len(self.it) > max_n else None
        if out is None:
            if len(self.it) <= max_n:
                CpPool.STATS["slow_small"] += 1
            out = {k: [a[0] * m * f, a[1] * m * f] for k, a in self.it.items() if a[0] * m * f > 1e-15}
            tc = sum(v[1] for v in out.values())
            tq = sum(v[0] for v in out.values()) or 1.0
            for v in out.values():
                v[1] = (v[1] * cost / tc) if tc > 0 else cost * v[0] / tq
            out = compress(out, merge_key, max_n)
        self.m = m * (1.0 - f)
        if f >= 1.0 - 1e-12 or self.m < 1e-12:
            self._clear()
        return out

    def _take_fast(self, m, f, cost, merge_key, max_n):
        it = self.it
        K = max_n - 1
        fx = self._fx
        if fx is None or fx.mk != merge_key or fx.K != K:
            fx = self._fx = _TopK.build(it, merge_key, K)
            CpPool.STATS["build"] += 1
        if not (fx.amin * m * f > 1e-15):
            fx.amin = min(a[0] for a in it.values())
            if not (fx.amin * m * f > 1e-15):
                CpPool.STATS["slow_thr"] += 1
                return None
        fx.settle(it)
        T = fx._top_min(it)
        R = fx._rest_max(it)
        if T is None or R is None or len(fx.top) != K or T[0] * m * f == R[0] * m * f:
            CpPool.STATS["slow_tie"] += 1
            return None
        tc = self.sc * m * f
        tq = self.sq * m * f or 1.0
        res = {}
        for k in sorted(fx.top, key=fx.seq.__getitem__):
            a = it[k]
            q = a[0] * m * f
            c = a[1] * m * f
            res[k] = [q, (c * cost / tc) if tc > 0 else cost * q / tq]
        mq = mc = 0.0
        a = it.get(merge_key)
        if a is not None:
            q = a[0] * m * f
            c = a[1] * m * f
            mq += q
            mc += (c * cost / tc) if tc > 0 else cost * q / tq
        rq = fx.rq * m * f
        rc = fx.rc * m * f
        mq += rq
        mc += (rc * cost / tc) if tc > 0 else cost * rq / tq
        res[merge_key] = [mq, mc]
        CpPool.STATS["fast"] += 1
        return res


def compress(out, merge_key, max_n):
    if len(out) <= max_n:
        return out
    mg = [0.0, 0.0]
    if merge_key in out:
        a = out.pop(merge_key)
        mg[0] += a[0]
        mg[1] += a[1]
    keep = set(heapq.nlargest(max_n - 1, out, key=lambda k: out[k][0]))
    for k in [k for k in out if k not in keep]:
        mg[0] += out[k][0]
        mg[1] += out[k][1]
        del out[k]
    out[merge_key] = mg
    return out


def legs_from_engine(cards, real_keys, iso):
    order = [pk for pk in real_keys if pk in cards]
    sells = [(pk, e) for pk in order for ts, e in cards[pk]["ev"] if is_sell(e) and kst_day(ts) == iso]
    if not sells or all("_cmp" not in e for _pk, e in sells):
        return None
    miss = [e for _pk, e in sells if "_cmp" not in e]
    sells = [(pk, e) for pk, e in sells if "_cmp" in e]
    where = {id(e): pk for pk, c in cards.items() for _ts, e in c["ev"]}
    acc, fee, other, unk, src = {}, {}, [0.0, 0.0], 0.0, []
    cvs = {}
    need = {}
    for pk, e in sells:
        cm = e["_cmp"] or {}
        unk += float(cm.get("unk") or 0)
        nd = need.setdefault(pk, [0, 0.0])
        nd[1] += num(e.get("q")) or 0.0
        for ev0, _key, q9, c9 in cm.get("o") or ():
            if ev0 is not None and ev0.get("_cv"):
                a9 = cvs.setdefault(id(ev0), [ev0, 0.0, 0.0])
            elif ev0 is not None and is_buy(ev0):
                a9 = acc.setdefault(id(ev0), [ev0, 0.0, 0.0])
            elif ev0 is not None and str(ev0.get("k") or "") == "LP 수수료 수령":
                a9 = fee.setdefault(id(ev0), [ev0, 0.0, 0.0])
            else:
                other[0] += q9
                other[1] += c9
                continue
            a9[1] += q9
            a9[2] += c9
    sim9 = None
    if miss:
        sim9 = _extract_legs_sim(cards, real_keys, iso, only={id(e) for e in miss})
        for e, q9, c9 in sim9.pop("_acc"):
            a9 = acc.setdefault(id(e), [e, 0.0, 0.0])
            a9[1] += q9
            a9[2] += c9
        for e, q9, c9 in sim9.pop("_fee"):
            a9 = fee.setdefault(id(e), [e, 0.0, 0.0])
            a9[1] += q9
            a9[2] += c9
        for pk, (t9, q9) in sim9["need"].items():
            nd = need.setdefault(pk, [0, 0.0])
            nd[0] = max(nd[0], t9)
        for pk in sim9["srcCards"]:
            if pk not in src:
                src.append(pk)
    legs = []
    for i9, (e, q9, c9) in acc.items():
        pk = where.get(i9)
        if pk is not None and pk not in order and pk not in src:
            src.append(pk)
        q0 = num(e.get("q")) or 0.0
        un = num(e.get("un"))
        krw = num(e.get("aK"))
        f9 = q9 / q0 if q0 > 0 else 0.0
        legs.append({"ts": int(e.get("_ts") or 0), "q": q9, "usd": c9 if c9 > 0 else None, "un": un if un and un > 0 else ((c9 / q9) if q9 else None),
                     "krw": (krw * f9) if krw and krw > 0 else None, "pid": e.get("_pid"), "pkey": pk,
                     "chain": (cards.get(pk) or {}).get("chain"), "k": str(e.get("k") or ""), "d": str(e.get("d") or ""), "src": e.get("src"),
                     "share": round(f9, 6)})
    for i9, (e, q9, c9) in cvs.items():
        pk = where.get(i9)
        if pk is not None and pk not in order and pk not in src:
            src.append(pk)
        fr9 = str((e.get("_cv") or {}).get("from") or "?")
        legs.append({"ts": int(e.get("_ts") or 0), "q": q9, "usd": c9 if c9 > 0 else None, "un": (c9 / q9) if (q9 > 0 and c9 > 0) else None,
                     "krw": None, "pid": e.get("_pid"), "pkey": pk, "chain": (cards.get(pk) or {}).get("chain"), "k": "브릿지 전환",
                     "d": f"{fr9} → 브릿지 전환 · " + str(e.get("d") or ""), "src": e.get("src"), "from": fr9, "share": 1.0})
    legs.sort(key=lambda x: (x["ts"], str(x["pkey"])))
    lpf = {"n": len(fee), "qty": sum(v[1] for v in fee.values()), "usd": sum(v[2] for v in fee.values())}
    return {"legs": legs, "lpFee": {"n": lpf["n"], "qty": _r(lpf["qty"]), "usd": round(lpf["usd"], 2)},
            "cards": list(order), "srcCards": src, "unmatched": sim9["unmatched"] if sim9 else 0, "fallback": sim9["fallback"] if sim9 else 0,
            "trimmed": {"n": 0, "qty": 0}, "simSells": len(miss),
            "other": {"qty": _r(other[0]), "usd": round(other[1], 2)}, "unknownQty": _r(unk), "source": "mixed" if miss else "engine",
            "need": {k: [v[0], _r(v[1])] for k, v in need.items()}}


def sell_cards(cards, iso):
    return [pk for pk, c in cards.items() if any(is_sell(e) and kst_day(ts) == iso for ts, e in c["ev"])]


def extract_legs(cards, real_keys, iso):
    out = legs_from_engine(cards, real_keys, iso)
    if out is not None:
        return out
    out = _extract_legs_sim(cards, real_keys, iso)
    out["source"] = "sim"
    return out


def _extract_legs_sim(cards, real_keys, iso, only=None):
    order = [pk for pk in real_keys if pk in cards]

    def is_disp(e):
        return "매도" in str(e.get("k") or "") or is_outflow(e)

    def qty(e):
        return num(e.get("q")) or 0.0

    pid_out = {}
    for pk, ev9 in cards.items():
        for ts, e in ev9["ev"]:
            p9 = e.get("_pid")
            if p9 is not None and (is_outflow(e) or str(e.get("k") or "") in ("전송", "외부 전송")) and not e.get("_mv"):
                pid_out.setdefault(p9, pk)
    evs = {pk: [] for pk in cards}
    for pk, c in cards.items():
        for ts, e in c["ev"]:
            dst9 = pid_out.get(e.get("_mv")) if e.get("_mv") is not None else None
            evs[dst9 if (dst9 is not None and dst9 in evs) else pk].append((ts, e))
    for pk in evs:
        evs[pk].sort(key=lambda x: x[0])
    pid_ix = {}
    for pk, ev9 in evs.items():
        for i, (ts, e) in enumerate(ev9):
            p9 = e.get("_pid")
            if p9 is not None and (is_outflow(e) or str(e.get("k") or "") in ("전송", "외부 전송")) and p9 not in pid_ix:
                pid_ix[p9] = (pk, i)
    linked_send = {pid_ix[sp] for ev9 in evs.values() for ts, e in ev9 for sp, _w in (e.get("_lnk") or ()) if sp in pid_ix}
    internal = set()

    outs = sorted((int(ts), pk2, i2, qty(e), str(e.get("tx") or "").strip(), out_dest(e))
                  for pk2, ev9 in evs.items() for i2, (ts, e) in enumerate(ev9) if is_outflow(e) and (pk2, i2) not in linked_send)
    out_ts = [o[0] for o in outs]
    groups = {}
    for pk, ev9 in evs.items():
        for i_in, (ts_in, e_in) in enumerate(ev9):
            if e_in.get("_lnk") or not is_inflow(e_in) or qty(e_in) <= 0:
                continue
            tx_in = str(e_in.get("tx") or "").strip()
            gk = (tx_in, in_dest(e_in)) if _tx_ok(tx_in) else ("#", pk, i_in)
            g9 = groups.setdefault(gk, {"ts": int(ts_in), "q": 0.0, "mem": [], "tx": tx_in, "dst": in_dest(e_in)})
            g9["ts"] = max(g9["ts"], int(ts_in))
            g9["q"] += qty(e_in)
            g9["mem"].append((pk, i_in))
    used, match = set(), {}
    for gk, g9 in sorted(groups.items(), key=lambda kv: kv[1]["ts"]):
        ts_in, q_in, tx_in, dst_in = g9["ts"], g9["q"], g9["tx"], g9["dst"]
        pks = {m[0] for m in g9["mem"]}
        best = None
        for j in range(bisect.bisect_left(out_ts, int(ts_in) - MATCH_WIN_S), bisect.bisect_right(out_ts, int(ts_in))):
            ts_o, pk2, i2, q_o, tx_o, dst_o = outs[j]
            if dst_in and dst_o and dst_in != dst_o:
                continue
            if pk2 in pks or (pk2, i2) in used:
                continue
            same = _tx_ok(tx_in) and tx_in == tx_o
            if not same and _tx_ok(tx_in) and _tx_ok(tx_o) and tx_in.startswith("0x") and tx_o.startswith("0x"):
                continue
            if not (q_in * (1 - 1e-3) - 1e-9 <= q_o <= q_in * 1.03 + 1e-9):
                continue
            key9 = (0 if same else 1, int(ts_in) - ts_o, abs(q_o - q_in))
            if best is None or key9 < best[0]:
                best = (key9, pk2, i2, q_o)
        if best is None:
            continue
        used.add((best[1], best[2]))
        for m in g9["mem"]:
            match[m] = (best[1], best[2], q_in, min(1.0, q_in / best[3]) if best[3] > 0 else 1.0)
    sims = {}
    day0 = int(datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=KST).timestamp())

    def sim(pk):
        if pk in sims:
            return sims[pk]
        items, rec, m, tot, ep = [], {}, 1.0, 0.0, 0
        ev9 = evs[pk]
        for i, (ts, e) in enumerate(ev9):
            if (pk, i) in internal:
                continue
            q = qty(e)
            if q <= 0:
                continue
            k = str(e.get("k") or "")
            if is_buy(e):
                kind = "buy"
            elif k == "LP 수수료 수령":
                kind = "fee"
            elif e.get("_lnk") or is_inflow(e):
                kind = "in"
            elif k == "입금 확인":
                kind = "unk"
            elif is_disp(e) or (pk, i) in linked_send:
                if tot <= 1e-12:
                    rec[i] = None
                    continue
                qd = min(q, tot)
                frac = qd / tot
                rec[i] = (m, frac, len(items), ep)
                m *= (1.0 - frac)
                tot -= qd
                if m < WAC_REBASE:
                    ep, m = ep + 1, 1.0
                    if tot < 1e-9:
                        tot = 0.0
                continue
            else:
                continue
            items.append((kind, i, q / m, ep))
            tot += q
        sims[pk] = (items, rec, m, tot)
        return sims[pk]

    legs_acc, fee_acc, unmatched, fallback, src_cards = {}, {}, set(), set(), []
    need = {}

    def take(pk, i, share, depth):
        items, rec, _m, _t = sim(pk)
        r = rec.get(i)
        if r is None or share <= 0:
            return
        m0, frac, n, ep0 = r
        ts_i = int(evs[pk][i][0])
        nd = need.setdefault(pk, [ts_i, 0.0])
        nd[0] = max(nd[0], ts_i)
        nd[1] += qty(evs[pk][i][1]) * share
        for kind, idx, base, epi in items[:n]:
            if epi != ep0:
                continue
            c = base * m0 * frac * share
            if c <= 1e-12:
                continue
            if kind == "buy":
                legs_acc[(pk, idx)] = legs_acc.get((pk, idx), 0.0) + c
            elif kind == "fee":
                fee_acc[(pk, idx)] = fee_acc.get((pk, idx), 0.0) + c
            elif kind == "in":
                e_in = evs[pk][idx][1]
                q_dep = qty(e_in)
                if depth >= LINEAGE_DEPTH or q_dep <= 0:
                    unmatched.add((pk, idx))
                    continue
                lnk = e_in.get("_lnk")
                if lnk:
                    hit = False
                    for sp, w in lnk:
                        tg = pid_ix.get(sp)
                        if tg is None:
                            continue
                        hit = True
                        if tg[0] not in src_cards and tg[0] not in order:
                            src_cards.append(tg[0])
                        take(tg[0], tg[1], (c / q_dep) * float(w), depth + 1)
                    if not hit:
                        unmatched.add((pk, idx))
                    continue
                mt = match.get((pk, idx))
                if mt is None:
                    unmatched.add((pk, idx))
                    continue
                pk2, i2, q_ref, w9 = mt
                fallback.add((pk, idx))
                if pk2 not in src_cards and pk2 not in order:
                    src_cards.append(pk2)
                take(pk2, i2, (c / q_ref) * w9 if q_ref > 0 else 0.0, depth + 1)

    for pk in order:
        sells = [i for i, (ts, e) in enumerate(evs[pk]) if is_sell(e) and kst_day(ts) == iso and (pk, i) not in internal]
        if only is not None:
            for i in sells:
                if id(evs[pk][i][1]) in only:
                    take(pk, i, 1.0, 0)
            continue
        if sells:
            for i in sells:
                take(pk, i, 1.0, 0)
        else:
            items, rec, m, tot = sim(pk)
            cut = day0 + 86400 - 1
            ep_last = items[-1][3] if items else 0
            for kind, idx, base, epi in items:
                if evs[pk][idx][0] > cut or epi != ep_last:
                    continue
                c = base * m
                if kind == "buy":
                    legs_acc[(pk, idx)] = legs_acc.get((pk, idx), 0.0) + c
                elif kind == "fee":
                    fee_acc[(pk, idx)] = fee_acc.get((pk, idx), 0.0) + c
            need.setdefault(pk, [cut, 0.0])

    def rec_usd(e):
        q0, un, usd = qty(e), num(e.get("un")), num(e.get("a"))
        if un and un > 0:
            usd9 = un * q0
            usd = usd9 if (usd is None or abs(usd9 - usd) <= max(0.01, 0.005 * abs(usd))) else usd
        return usd

    if only is not None:
        def part(e, c):
            q0, usd = qty(e), rec_usd(e)
            return (e, c, (usd * c / q0) if (usd and usd > 0 and q0 > 0) else 0.0)
        return {"_acc": [part(evs[pk][idx][1], c) for (pk, idx), c in legs_acc.items()],
                "_fee": [(evs[pk][idx][1], c, (num(evs[pk][idx][1].get("a")) or 0.0) * (c / qty(evs[pk][idx][1]) if qty(evs[pk][idx][1]) > 0 else 0.0))
                         for (pk, idx), c in fee_acc.items()],
                "srcCards": src_cards, "unmatched": len(unmatched), "fallback": len(fallback),
                "need": {k: [v[0], _r(v[1])] for k, v in need.items()}}
    legs = []
    for (pk, idx), c in legs_acc.items():
        ts, e = evs[pk][idx]
        q0 = qty(e)
        un = num(e.get("un"))
        usd = rec_usd(e)
        krw = num(e.get("aK"))
        f9 = c / q0 if q0 > 0 else 0.0
        legs.append({"ts": int(ts), "q": c, "usd": (usd * f9) if usd and usd > 0 else None,
                     "un": un if un and un > 0 else ((usd / q0) if usd and q0 else None),
                     "krw": (krw * f9) if krw and krw > 0 else None, "pid": e.get("_pid"), "pkey": pk, "chain": cards[pk].get("chain"),
                     "k": str(e.get("k") or ""), "d": str(e.get("d") or ""), "src": e.get("src"), "share": round(f9, 6)})
    lpf = {"n": 0, "qty": 0.0, "usd": 0.0}
    for (pk, idx), c in fee_acc.items():
        e = evs[pk][idx][1]
        q0 = qty(e)
        lpf["n"] += 1
        lpf["qty"] += c
        lpf["usd"] += (num(e.get("a")) or 0.0) * (c / q0 if q0 > 0 else 0.0)
    legs.sort(key=lambda x: (x["ts"], x["pkey"]))
    return {"legs": legs, "lpFee": {"n": lpf["n"], "qty": _r(lpf["qty"]), "usd": round(lpf["usd"], 2)},
            "cards": list(order), "srcCards": src_cards, "unmatched": len(unmatched), "fallback": len(fallback), "trimmed": {"n": 0, "qty": 0},
            "need": {k: [v[0], _r(v[1])] for k, v in need.items()}}


def segments(fills, sell_from=None, max_segs=MAX_SEGS, gap=CLUSTER_GAP_S):
    ix = sorted(range(len(fills)), key=lambda i: int(fills[i]["ts"]))
    groups = []
    for i in ix:
        t = int(fills[i]["ts"])
        if groups and t - groups[-1]["buyTo"] <= gap:
            g = groups[-1]
            g["buyTo"] = t
            g["ix"].append(i)
            g["amt"] += float(fills[i].get("amt") or 0)
        else:
            groups.append({"buyFrom": t, "buyTo": t, "ix": [i], "amt": float(fills[i].get("amt") or 0)})
    keep = sorted(sorted(groups, key=lambda g: -g["amt"])[:max_segs], key=lambda g: g["buyFrom"])
    outside = set()
    for g in groups:
        if g not in keep:
            outside.update(g["ix"])
    segs = []
    for g in keep:
        s = {"from": g["buyFrom"] - PRE_B, "to": g["buyTo"] + POST_B, "buyFrom": g["buyFrom"], "buyTo": g["buyTo"],
             "n": len(g["ix"]), "amt": _r(g["amt"])}
        if segs and s["from"] <= segs[-1]["to"]:
            p = segs[-1]
            p.update(to=max(p["to"], s["to"]), buyTo=max(p["buyTo"], s["buyTo"]), n=p["n"] + s["n"], amt=_r(float(p["amt"] or 0) + float(s["amt"] or 0)))
        else:
            segs.append(s)
    if segs and sell_from:
        last = segs[-1]
        if 0 < int(sell_from) - last["to"] <= gap:
            last["to"] = int(sell_from)
    return segs, outside


COVER_GAP_MIN_S = 1800


def covers(pool, t0, t1) -> bool:
    seg = sorted((int(c[0]), int(c[0]) + int(iv)) for c, iv in pool)
    if not seg:
        return False
    cur, prev_iv = int(t0), seg[0][1] - seg[0][0]
    for a, b in seg:
        iv = b - a
        if a - cur > max(3 * max(iv, prev_iv), COVER_GAP_MIN_S):
            return False
        cur, prev_iv = max(cur, b), iv
    return int(t1) - cur <= max(3 * prev_iv, COVER_GAP_MIN_S)


def windows_cover(wins, t0, t1, tol=60) -> bool:
    ws = sorted((int(a), int(b)) for a, b in (wins or ()) if b > a)
    if not ws:
        return False
    cur = int(t0)
    for a, b in ws:
        if a > cur + tol:
            if a >= int(t1):
                break
            return False
        cur = max(cur, b)
        if cur >= int(t1) - tol:
            return True
    return cur >= int(t1) - tol


FFILL_MAX = 3000


def ffill(cs, iv_s, t0=None, t1=None):
    rows = sorted((list(c[:6]) for c in (cs or ())), key=lambda c: c[0])
    if not rows or iv_s <= 0:
        return rows
    out, n = [], 0
    for i, c in enumerate(rows):
        if out:
            t = out[-1][0] + iv_s
            px = out[-1][4]
            while t < c[0] and n < FFILL_MAX:
                out.append([t, px, px, px, px, 0.0, 1])
                t += iv_s
                n += 1
        out.append(c)
    if t1 is not None:
        t = out[-1][0] + iv_s
        px = out[-1][4]
        while t < int(t1) and n < FFILL_MAX:
            out.append([t, px, px, px, px, 0.0, 1])
            t += iv_s
            n += 1
    return out


GAP_BRIDGE_S = 6 * 3600
SHORT_SPAN_S = 6 * 3600


def gap_plan(seg_spans, s_first, w_from=None, open_ts=None, s_iv=300, short=False, max_gap=GAP_BRIDGE_S):
    sp = sorted(seg_spans or (), key=lambda s: s[0])
    out = []
    if short:
        for i in range(len(sp) - 1):
            a, b, iv = int(sp[i][1]), int(sp[i + 1][0]), int(sp[i][2])
            if s_first is not None and b > int(s_first):
                continue
            if iv <= b - a <= max_gap:
                out.append({"from": a, "to": b, "kind": "idle", "seg": i})
    if sp and s_first is not None:
        a, b, iv = int(sp[-1][1]), int(s_first), int(sp[-1][2])
        if iv <= b - a <= max_gap:
            live = open_ts is None and w_from is not None and b <= int(w_from) + int(s_iv)
            out.append({"from": a, "to": b, "kind": "wait" if live else "pre", "seg": len(sp) - 1})
    return out


def bridge_rows(cs, iv_s, a, b, seed=None):
    iv_s, a, b = int(iv_s), int(a), int(b)
    if iv_s <= 0 or b <= a:
        return []
    t0 = -(-a // iv_s) * iv_s
    src = sorted((c for c in (cs or ()) if isinstance(c, (list, tuple)) and len(c) >= 6 and t0 <= int(c[0]) < b), key=lambda c: c[0])
    prev = float(seed) if seed and float(seed) > 0 else None
    out, t = [], t0
    for c in src:
        while prev is not None and t < int(c[0]) and len(out) < FFILL_MAX:
            out.append([t, prev, prev, prev, prev, 0.0, 1])
            t += iv_s
        if len(out) >= FFILL_MAX:
            break
        out.append([int(c[0])] + [float(x) for x in c[1:6]] + [0])
        prev, t = float(c[4]), int(c[0]) + iv_s
    while prev is not None and t < b and len(out) < FFILL_MAX:
        out.append([t, prev, prev, prev, prev, 0.0, 1])
        t += iv_s
    return out


def bridge_label(kind, sell_name, buy_name, opened=False):
    s9, b9 = sellchart.clean_label(sell_name, 20) or "매도 장소", sellchart.clean_label(buy_name, 20) or "매수 장소"
    if kind == "wait":
        return "입금 대기 중", f"입금 대기 중 · {s9} 시세"
    if kind == "idle":
        return "매수 사이", f"매수 사이 · {b9} 시세"
    return "이동 중", f"이동 중 · {s9} {'개장' if (kind == 'pre' and opened) else '거래'} 전 · {b9} 시세"


def _typ(c):
    return (c[2] + c[3] + c[4]) / 3.0


def buy_score(sm):
    if not isinstance(sm, dict):
        return None
    cl = sellchart._clamp
    comps = []
    bp = sm.get("botPct")
    comps.append({"k": "pos", "label": "평균 매수가 위치", "max": 40, "in": bp,
                  "pts": round(cl(40 * (1 - float(bp) / 100), 0, 40), 1) if bp is not None else None,
                  "why": "40 × (1 − 저가에서 올라간 % / 100)" if bp is not None else "구간 봉 없음 — 빼고 환산"})
    vw = sm.get("vsMarketPct")
    comps.append({"k": "mkt", "label": "체결 시각 시세 대비", "max": 20, "in": vw,
                  "pts": round(cl(10 - float(vw), 0, 20), 1) if vw is not None else None,
                  "why": "10 − 체결 시각 봉 중간가 대비 %(금액 가중)" if vw is not None else "체결 시각 봉 없음 — 빼고 환산"})
    us = sm.get("untilSell") if isinstance(sm.get("untilSell"), dict) else None
    if us and us.get("covered") is False:
        comps.append({"k": "after", "label": "매수 뒤 첫 매도까지", "max": 25, "in": None, "pts": None,
                      "why": "구간 시세 부족(첫 매도까지 봉이 다 있지 않음) — 빼고 환산"})
    elif us and us.get("hiPct") is not None and us.get("loPct") is not None:
        gain = max(0.0, float(us["hiPct"]))
        dd = max(0.0, -float(us["loPct"]))
        comps.append({"k": "after", "label": "매수 뒤 첫 매도까지", "max": 25, "in": {"gainPct": round(gain, 2), "ddPct": round(dd, 2)},
                      "pts": round(cl(25 * min(1.0, gain / 30) - min(10.0, dd / 2), 0, 25), 1),
                      "why": "25 × min(1, 최고 상승 % / 30) − min(10, 최대 하락 % / 2)"})
    else:
        comps.append({"k": "after", "label": "매수 뒤 첫 매도까지", "max": 25, "in": None, "pts": None,
                      "why": "첫 매도까지 봉 없음 — 빼고 환산"})
    ch = sm.get("chasePct")
    comps.append({"k": "chase", "label": "추격 매수", "max": 15, "in": ch,
                  "pts": round(15 * (1 - cl(float(ch), 0, 20) / 20), 1) if ch is not None else None,
                  "why": "15 × (1 − 직전 1시간 평균 대비 %(0~20) / 20)" if ch is not None else "직전 1시간 봉 없음 — 빼고 환산"})
    tot, scaled = sellchart._score_total(comps)
    if tot is None:
        return None
    return {"total": tot, "verdict": sellchart.verdict_of(tot, "buy"), "scaled": scaled, "components": comps}


def summarize_buy(candles, fills, iv_s, segs, cur="KRW", sell=None, bridge=None, bridge_iv=3600, fetched=None):
    out = _summarize_buy(candles, fills, iv_s, segs, cur=cur, sell=sell, bridge=bridge, bridge_iv=bridge_iv, fetched=fetched)
    sc = buy_score(out)
    if sc is not None:
        out["score"] = sc
    return out


def _summarize_buy(candles, fills, iv_s, segs, cur="KRW", sell=None, bridge=None, bridge_iv=3600, fetched=None):
    fl = [f for f in fills if f.get("px") and f.get("q")]
    q = sum(float(f["q"]) for f in fl)
    amt = sum(float(f["px"]) * float(f["q"]) for f in fl)
    out = {"cur": cur, "curSym": sellchart.CUR_SYM.get(cur, ""), "n": len(fl), "qty": _r(q), "amt": _r(amt),
           "avgPx": _r(amt / q) if q else None, "clusters": len(segs or ())}
    if not fl:
        return out
    avg = amt / q
    t_first, t_last = min(int(f["ts"]) for f in fl), max(int(f["ts"]) for f in fl)
    big = max(fl, key=lambda f: float(f["px"]) * float(f["q"]))
    out.update(firstTs=t_first, lastTs=t_last, buySpanMin=round((t_last - t_first) / 60, 1), pxMin=_r(min(f["px"] for f in fl)),
               pxMax=_r(max(f["px"] for f in fl)), maxSharePct=round(100.0 * float(big["px"]) * float(big["q"]) / amt, 1) if amt else None)
    sell = sell or {}
    if sell.get("avgPx"):
        out["sell"] = {"avgPx": _r(sell["avgPx"]), "premiumPct": _pct(float(sell["avgPx"]), avg)}
        if sell.get("costPx"):
            out["sell"]["costPx"] = _r(sell["costPx"])
        if sell.get("firstTs"):
            out["sell"]["firstTs"] = int(sell["firstTs"])
    if sell.get("openTs"):
        out["openTs"] = int(sell["openTs"])
        out["firstBuyToOpenMin"] = round((int(sell["openTs"]) - t_first) / 60, 1)
    cs = sorted(candles or (), key=lambda c: c[0])
    if not cs:
        return out
    civ = lambda c: int(c[7]) if len(c) > 7 and c[7] else iv_s
    ins = lambda c: any(s["from"] - civ(c) < c[0] < s["to"] for s in (segs or ())) if segs else True
    win = [c for c in cs if ins(c)]
    if not win:
        return out
    hi_c = max(win, key=lambda c: c[2])
    lo_c = min(win, key=lambda c: c[3])
    hi, lo = hi_c[2], lo_c[3]
    out.update(hi=_r(hi), hiTs=hi_c[0], lo=_r(lo), loTs=lo_c[0], nCandles=len(win))
    rng = hi - lo
    pos = max(0.0, min(100.0, (avg - lo) / rng * 100)) if rng > 0 else 50.0
    out["botPct"] = round(pos, 1)
    out["fromLowPct"] = _pct(avg, lo)
    out["fromHighPct"] = _pct(avg, hi)
    vt = sum(c[5] for c in win)
    if vt > 0:
        out["volAbovePct"] = round(100.0 * sum(c[5] for c in win if _typ(c) >= avg) / vt, 1)
    m_sum, m_w, m_n = 0.0, 0.0, 0
    for f in fl:
        t = int(f["ts"])
        c9 = next((c for c in reversed(cs) if c[0] <= t < c[0] + civ(c)), None)
        if c9 is None:
            continue
        mid = (c9[2] + c9[3]) / 2.0
        if mid <= 0:
            continue
        a9 = float(f["px"]) * float(f["q"])
        m_sum += a9 * (float(f["px"]) / mid - 1)
        m_w += a9
        m_n += 1
    if m_w > 0:
        out["vsMarketPct"] = round(m_sum / m_w * 100, 2)
        out["mktN"] = m_n
    w_sum, ch_sum, n_ch = 0.0, 0.0, 0
    for f in fl:
        t = int(f["ts"])
        pr = [c for c in cs if t - CHASE_S < c[0] + civ(c) <= t]
        if not pr:
            continue
        pv = sum(c[5] for c in pr)
        ref = (sum(_typ(c) * c[5] for c in pr) / pv) if pv > 0 else sum(_typ(c) for c in pr) / len(pr)
        if ref <= 0:
            continue
        a9 = float(f["px"]) * float(f["q"])
        ch_sum += a9 * (float(f["px"]) / ref - 1)
        w_sum += a9
        n_ch += 1
    if w_sum > 0:
        out["chasePct"] = round(ch_sum / w_sum * 100, 2)
        out["chaseN"] = n_ch
    c_at = next((c for c in reversed(cs) if c[0] <= t_first), None)
    c_pre = next((c for c in reversed(cs) if c[0] <= t_first - CHASE_S), None)
    if c_at and c_pre and c_pre[4] > 0 and c_at is not c_pre:
        out["pre1hPct"] = _pct(c_at[4], c_pre[4])
    fs = int(sell.get("firstTs") or 0)
    if fs and fs > t_first:
        pool = [(c, civ(c)) for c in cs if t_first < c[0] + civ(c) and c[0] < fs]
        pool += [(c, bridge_iv) for c in (bridge or ()) if t_first < c[0] + bridge_iv and c[0] < fs
                 and not any(c[0] < p[0][0] + p[1] and p[0][0] < c[0] + bridge_iv for p in pool)]
        if pool:
            h9 = max(pool, key=lambda p: p[0][2])[0]
            l9 = min(pool, key=lambda p: p[0][3])[0]
            out["untilSell"] = {"hi": _r(h9[2]), "hiTs": h9[0], "hiPct": _pct(h9[2], avg), "lo": _r(l9[3]), "loTs": l9[0], "loPct": _pct(l9[3], avg),
                                "horizonMin": round((fs - t_first) / 60, 1), "covered": windows_cover(fetched, t_first, fs) if fetched is not None else covers(pool, t_first, fs),
                                "bridge": bool(bridge)}
    return out


def _hm(ts, date):
    d = datetime.fromtimestamp(int(ts), KST)
    return d.strftime("%H:%M") if d.strftime("%Y-%m-%d") == date else d.strftime("%m-%d %H:%M")


def buy_eval_input(date, sym, venue_labels, src, summary, fills, candles, extra=None, fills_max=30):
    cur = summary.get("cur") or "USD"
    ts_keys = ("firstTs", "lastTs", "hiTs", "loTs", "openTs")
    sm = {k: v for k, v in summary.items() if k not in ts_keys}
    for k in ts_keys:
        if summary.get(k):
            sm[k.replace("Ts", "_t")] = _hm(summary[k], date)
    if isinstance(sm.get("untilSell"), dict):
        sm["untilSell"] = {k: (_hm(v, date) if k.endswith("Ts") else v) for k, v in sm["untilSell"].items()}
    if isinstance(sm.get("sell"), dict):
        sm["sell"] = {k: (_hm(v, date) if k.endswith("Ts") else v) for k, v in sm["sell"].items()}
    fl = sorted(fills, key=lambda f: -float(f.get("amt") or 0))[:fills_max]
    fl = sorted(fl, key=lambda f: f["ts"])
    out = {"date": date, "sym": sellchart.clean_sym(sym), "venues": [sellchart.clean_label(v) for v in (venue_labels or ())][:6], "cur": cur,
           "cur_sym": sellchart.CUR_SYM.get(cur, ""), "chart_src": sellchart.clean_label((src or {}).get("label")) or None,
           "chart_fallback": bool((src or {}).get("fallback")), "chart_iv": (src or {}).get("iv"), "fx_converted": bool((src or {}).get("fx")),
           "summary": sm,
           "fills": [{"t": _hm(f["ts"], date), "kind": sellchart.clean_label(f.get("kind"), 12), "px": _r(f["px"]), "q": _r(f["q"]), "amt": _r(f.get("amt"))} for f in fl],
           "fills_total": len(fills),
           "candles": [[_hm(c[0], date), _r(c[1]), _r(c[2]), _r(c[3]), _r(c[4]), _r(c[5])] for c in sellchart.downsample(candles, 48)]}
    for k, v in (extra or {}).items():
        out[k] = v
    return out

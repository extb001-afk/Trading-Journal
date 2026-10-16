from __future__ import annotations
from decimal import Decimal
from view_common import STABLE_GROUPS
from view_common import _ex_stable_sym

ORD_GAP_SEC = 3600

ORD_RUN_MAX = 64

ORD_DFS_MAX = 12

ORD_DFS_NODES = 20000

NOPX_LEGS_MAX = 6

_ORD_HOLD = ("wallet:", "exchange:", "lp:")


def _ord_cash(r) -> bool:
    if (r["gname"] or "") in STABLE_GROUPS:
        return True
    if r["kind"] == "exchange_currency":
        s9 = str(r["symbol"] or "").upper()
        return s9 == "KRW" or _ex_stable_sym(s9)
    return False


def _ord_flow(rows, s, e) -> dict:
    out = {}
    for k in range(s, e):
        r = rows[k]
        if r["leg_kind"] in ("gas", "fee", "opening") or not str(r["location"] or "").startswith(_ORD_HOLD) or _ord_cash(r):
            continue
        g = r["group_id"] or -r["asset_id"]
        d9 = r["decimals"] if r["decimals"] is not None else 18
        out[g] = out.get(g, Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** int(d9))
    return out


def _ord_auth_before(a, b) -> bool:
    if not a or not b or a[0] != b[0] or a[1] != b[1]:
        return False
    if a[0] == "c":
        if a[2] is None or b[2] is None:
            return False
        if a[2] != b[2]:
            return a[2] < b[2]
        for k9 in (3, 4):
            if len(a) > k9 and len(b) > k9 and a[k9] is not None and b[k9] is not None and a[k9] != b[k9]:
                return a[k9] < b[k9]
        return False
    if a[2] is not None and b[2] is not None and a[2] != b[2]:
        return a[2] < b[2]
    return bool(a[3]) and a[3] == b[3] and a[4] is not None and b[4] is not None and a[4] < b[4]


def _ord_feasible(flows, bal, pred):
    m = len(flows)
    full = (1 << m) - 1
    dead = set()
    left = [ORD_DFS_NODES]

    def short(b, bal9):
        return {g for g, v in flows[b].items() if v < 0 and bal9.get(g, Decimal(0)) + v < -max(Decimal("1e-12"), -v * Decimal("1e-9"))}

    def go(done, bal9, path):
        if done == full:
            return path
        if done in dead or left[0] <= 0:
            return None
        left[0] -= 1
        cand = [b for b in range(m) if not (done >> b) & 1 and not (pred[b] & ~done)]
        sh9 = {b: short(b, bal9) for b in cand}
        need = sh9[cand[0]] if cand else set()
        ok = [b for b in cand if not sh9[b]]
        if need:
            need2 = set().union(*sh9.values())
            ok.sort(key=lambda b: 0 if any(flows[b].get(g, 0) > 0 for g in need) else (1 if any(flows[b].get(g, 0) > 0 for g in need2) else 2))
        for b in ok:
            nb = dict(bal9)
            for g, v in flows[b].items():
                nb[g] = nb.get(g, Decimal(0)) + v
            r9 = go(done | (1 << b), nb, path + [b])
            if r9 is not None:
                return r9
        dead.add(done)
        return None
    return go(0, bal, [])


def _ord_tie(flows, bal, keys=None) -> list:
    m = len(flows)
    keys = keys or [None] * m
    if 2 <= m <= ORD_DFS_MAX:
        pred = [sum(1 << o for o in range(m) if o != b and _ord_auth_before(keys[o], keys[b])) for b in range(m)]
        p9 = _ord_feasible(flows, dict(bal), pred)
        if p9 is not None:
            for b in p9:
                for g, v in flows[b].items():
                    bal[g] = bal.get(g, Decimal(0)) + v
            return p9
    rem = list(range(m))
    out = []

    def short(b):
        return {g for g, v in flows[b].items() if v < 0 and bal.get(g, Decimal(0)) + v < -max(Decimal("1e-12"), -v * Decimal("1e-9"))}
    while rem:
        cand = [b for b in rem if not any(o != b and _ord_auth_before(keys[o], keys[b]) for o in rem)] or rem[:1]
        pick = cand[0]
        need = short(pick)
        if need:
            pick = next((b for b in cand[1:] if not short(b) and any(flows[b].get(g, 0) > 0 for g in need)), pick)
        out.append(pick)
        rem.remove(pick)
        for g, v in flows[pick].items():
            bal[g] = bal.get(g, Decimal(0)) + v
    return out


def _ord_splice(rows, moves) -> list:
    ins, skip = {}, {}
    for p9, (s9, e9) in moves:
        ins.setdefault(p9, []).append((s9, e9))
        skip[s9] = e9
    out, k = [], 0
    for c in sorted(set(ins) | set(skip)):
        if c > k:
            out.extend(rows[k:c])
            k = c
        for s9, e9 in ins.get(c, ()):
            out.extend(rows[s9:e9])
        if c in skip and c >= k:
            k = skip[c]
    out.extend(rows[k:])
    return out


def _ord_pair_moves(rows, pairs):
    def key(k):
        r = rows[k]
        return r["source_ns"], r["source_id"], r["event_ts"]

    def blk(k):
        s, e, k9 = k, k + 1, key(k)
        while s > 0 and key(s - 1) == k9:
            s -= 1
        while e < len(rows) and key(e) == k9:
            e += 1
        return s, e

    def gids(s, e):
        return {rows[k]["group_id"] or -rows[k]["asset_id"] for k in range(s, e)}
    moves, used, kept = [], set(), 0
    for ia, idp in sorted(pairs):
        a9, d9 = blk(ia), blk(idp)
        if a9[1] > d9[0] or a9[0] in used or d9[0] in used:
            kept += 1
            continue
        gd9, ga9 = gids(*d9), gids(*a9)
        if not any((rows[k]["group_id"] or -rows[k]["asset_id"]) in gd9 for k in range(a9[1], d9[0])):
            moves.append((a9[0], d9))
        elif not any((rows[k]["group_id"] or -rows[k]["asset_id"]) in ga9 for k in range(a9[1], d9[0])):
            moves.append((d9[1], a9))
        else:
            kept += 1
            continue
        used.update((a9[0], d9[0]))
    return moves, kept

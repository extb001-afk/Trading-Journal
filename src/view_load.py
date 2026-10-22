from __future__ import annotations
import bisect
import logs, paths, statefile
import json
import os
import re
from decimal import Decimal
from view_common import CHAIN_NAME
from view_common import STABLE_GROUPS
from view_common import SUB_SID_RE
from view_common import _GSYM_MEMO
from view_offc import _offc_tx
from view_order import ORD_GAP_SEC
from view_order import ORD_RUN_MAX
from view_order import _ORD_HOLD
from view_order import _ord_flow
from view_order import _ord_splice
from view_order import _ord_tie
from view_txkey import _ton_hash_uids
from view_txkey import _txk
from view_txkey import _wd_txk
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


class LoadMixin:

    def prefs(self):
        return statefile.read_json(paths.state("ui_prefs.json"), {"plans": {}, "ignored": []}) \
            if os.path.exists(paths.state("ui_prefs.json")) else {"plans": {}, "ignored": []}

    def _load(self, conn):
        rows = conn.execute(
            "SELECT p.posting_id, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.asset_id,"
            " p.location, p.qty_base, p.cost_usd, p.cost_krw, p.leg_kind, p.event,"
            " a.symbol, a.kind, a.chain, a.address, a.decimals, a.group_id, g.name AS gname"
            " FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
            " LEFT JOIN asset_groups g ON g.group_id = a.group_id"
            " ORDER BY p.event_ts, p.source_ns, p.source_id,"
            " CASE p.leg_kind WHEN 'disp' THEN 0 WHEN 'acq' THEN 1 ELSE 2 END, p.leg_seq, p.posting_id").fetchall()
        return rows

    def _drop_cancelled_openings(self, rows):
        pos, neg, by_loc = {}, {}, {}
        for r in rows:
            k = (r["asset_id"], r["location"] or "")
            by_loc.setdefault(k, []).append(r)
            if r["leg_kind"] != "opening" or r["event"] != "OPENING":
                continue
            q = int(r["qty_base"])
            sid = str(r["source_id"] or "")
            if q > 0 and sid.startswith("recon:"):
                pos.setdefault(k, []).append(r)
            elif q < 0 and sid.startswith("rebal"):
                neg.setdefault(k, []).append(r)
        drop = set()
        for k, ps in pos.items():
            ns = neg.get(k) or []
            pairs = [(p, n) for p in ps for n in ns if n["event_ts"] >= p["event_ts"]
                     and abs(int(p["qty_base"]) + int(n["qty_base"])) <= max(1, int(p["qty_base"]) // 10 ** 6)]
            if len(pairs) != 1:
                continue
            p, n = pairs[0]
            if (p["gname"] or "") in STABLE_GROUPS:
                continue
            pid = {p["posting_id"], n["posting_id"]}
            mid = [r for r in by_loc[k] if r["posting_id"] not in pid and p["event_ts"] <= r["event_ts"] <= n["event_ts"]]
            if not mid:
                continue
            run, lo = 0, 0
            for r in by_loc[k]:
                if r["event_ts"] > n["event_ts"]:
                    break
                if r["posting_id"] in pid:
                    continue
                run += int(r["qty_base"])
                lo = min(lo, run)
            if lo < -max(1, int(p["qty_base"]) // 10 ** 6):
                continue
            drop |= pid
        self._open_cancel_n = len(drop) // 2
        return [r for r in rows if r["posting_id"] not in drop] if drop else rows

    @staticmethod
    def _ord_key(conn, r):
        ns, sid = str(r["source_ns"] or ""), str(r["source_id"] or "")
        try:
            if ":" not in ns and r["leg_kind"] != "opening":
                b9 = conn.execute("SELECT block, CASE WHEN json_valid(snapshot) THEN json_extract(snapshot, '$.tx.position') END,"
                                  " CASE WHEN json_valid(snapshot) AND json_type(snapshot, '$.token_transfers') = 'array' THEN (SELECT min(json_extract(t.value, '$.log_index'))"
                                  " FROM json_each(snapshot, '$.token_transfers') t WHERE t.type = 'object') END FROM raw_txs WHERE chain=? AND txhash=?", (ns, sid)).fetchone()
                if b9 is None or b9[0] is None:
                    return None

                def _i(v):
                    try:
                        return int(v) if v is not None and str(v).strip().lstrip("-").isdigit() else None
                    except (TypeError, ValueError):
                        return None
                return ("c", ns, int(b9[0]), _i(b9[1]), _i(b9[2]))
            if ns.endswith(":trade"):
                ex9 = ns[:-6]
                p9 = conn.execute("SELECT payload FROM raw_ex WHERE exchange=? AND kind='trade' AND uuid=? ORDER BY revision DESC LIMIT 1",
                                  (ex9, sid)).fetchone()
                if p9 is None:
                    return None
                ms9 = int((json.loads(p9[0]) or {}).get("ts") or 0) or None
                pt9 = sid.split(":")
                if len(pt9) == 4 and SUB_SID_RE.match(sid):
                    pt9 = [pt9[0]] + pt9[2:]
                mk9, no9 = (pt9[1], int(pt9[2])) if len(pt9) == 3 and pt9[2].isdigit() else ("", None)
                return ("x", ex9, ms9, mk9, no9)
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_load:LoadMixin._ord_key", _cg9)
            return None
        return None

    def _replay_order(self, conn, rows):
        diag = {"tieRuns": 0, "tieMoved": 0, "wdMoved": 0, "arrMoved": 0, "wdKept": 0}
        self._ord_diag = diag
        self._ord_far = []
        n = len(rows)
        if n < 2:
            return rows
        K = (lambda c9: c9) if isinstance(rows[0], dict) else list(rows[0].keys()).index
        iTS, iNS, iSID, iLK, iLOC, iQ, iG, iA, iD = (K(c9) for c9 in ("event_ts", "source_ns", "source_id", "leg_kind", "location", "qty_base",
                                                                    "group_id", "asset_id", "decimals"))
        ts = [r[iTS] for r in rows]
        ns = [r[iNS] for r in rows]
        sid = [r[iSID] for r in rows]
        sec9 = sorted({t9 for t9, t0, s9, s0, a9, a0 in zip(ts[1:], ts, sid[1:], sid, ns[1:], ns) if t9 == t0 and (s9 != s0 or a9 != a0)})
        hot = []
        mv9 = ("acq", "disp", "move_in", "move_out")
        for t9 in sec9:
            i, j = bisect.bisect_left(ts, t9), bisect.bisect_right(ts, t9)
            blk, s9 = [], i
            for k in range(i + 1, j + 1):
                if k == j or sid[k] != sid[k - 1] or ns[k] != ns[k - 1]:
                    blk.append((s9, k))
                    s9 = k
            if not 2 <= len(blk) <= ORD_RUN_MAX:
                continue
            sg9 = {}
            for b9, (s0, e0) in enumerate(blk):
                for r in rows[s0:e0]:
                    if r[iLK] in mv9:
                        sg9.setdefault(r[iG] or -r[iA], (set(), set()))[0 if str(r[iQ]).startswith("-") else 1].add(b9)
            if not any(ng and pg and len(ng | pg) > 1 for ng, pg in sg9.values()):
                continue
            fl = [_ord_flow(rows, s0, e0) for s0, e0 in blk]
            hg = {g for b9, f in enumerate(fl) for g, v in f.items()
                  if v > 0 and any(b2 != b9 and fl[b2].get(g, 0) < 0 for b2 in range(len(fl)))}
            if hg:
                hot.append((i, j, blk, [{g: v for g, v in f.items() if g in hg} for f in fl], hg))
        if hot:
            bal = {g: Decimal(0) for g in set().union(*(h[4] for h in hot))}
            snaps, k0 = {}, 0
            for h9 in hot:
                for k in range(k0, h9[0]):
                    r = rows[k]
                    g = r[iG] or -r[iA]
                    if g in bal and str(r[iLOC] or "").startswith(_ORD_HOLD):
                        bal[g] += Decimal(int(r[iQ])) / (Decimal(10) ** int(18 if r[iD] is None else r[iD]))
                k0 = h9[0]
                snaps[h9[0]] = {g: bal[g] for g in h9[4]}
            seg = []
            for i0, j0, blk, fl, hg in hot:
                diag["tieRuns"] += 1
                perm = _ord_tie(fl, snaps[i0], [self._ord_key(conn, rows[s0]) for s0, _e0 in blk])
                if perm != list(range(len(blk))):
                    diag["tieMoved"] += 1
                    seg.append((i0, j0, [rows[k] for b9 in perm for k in range(*blk[b9])]))
            if seg:
                out, k = [], 0
                for i0, j0, part in seg:
                    out.extend(rows[k:i0])
                    out.extend(part)
                    k = j0
                out.extend(rows[k:])
                rows = out
        return self._ord_wd_first(conn, rows, ts, diag)

    def _ord_wd_first(self, conn, rows, ts, diag):
        wd, dep = {}, {}
        ton9 = _ton_hash_uids(conn)
        try:
            for ex9, k9, u9, t9, st9, n9 in conn.execute(
                    "SELECT exchange, kind, uuid, json_extract(payload, '$.txid'), json_extract(payload, '$.state'),"
                    " COALESCE(json_extract(payload, '$.network'), json_extract(payload, '$.net_type')) FROM raw_ex"
                    " WHERE kind IN ('withdraw', 'deposit') AND json_valid(payload)"
                    " GROUP BY exchange, kind, uuid HAVING revision = MAX(revision)").fetchall():
                t9 = (_wd_txk(t9, n9 if isinstance(n9, str) else None, ton9) if k9 == "withdraw" else _txk(t9)) if isinstance(t9, str) else ""
                if not t9 or t9.startswith("swap_") or _offc_tx(t9):
                    continue
                if k9 == "withdraw" and str(st9 or "").upper() == "DONE":
                    wd[(f"{ex9}:withdraw", u9)] = (ex9, t9)
                elif k9 == "deposit" and str(st9 or "").upper() == "ACCEPTED":
                    dep[(f"{ex9}:deposit", u9)] = (ex9, t9)
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_load:LoadMixin._ord_wd_first[ex9]", e9)
            log.warning("출금·도착 순서 색인 실패(이번 빌드 종전 순서): %s", logs.safe_err(e9)[:160])
            return rows
        if not wd:
            return rows
        wd_tx = {}
        for (ns9, u9), (ex9, t9) in wd.items():
            wd_tx.setdefault(t9, []).append((ns9, u9, ex9))
        exns9 = sorted({k9[0] for k9 in wd} | {k9[0] for k9 in dep})
        try:
            cand = conn.execute("SELECT source_ns, source_id, event_ts FROM postings WHERE source_kind = 'exchange' AND leg_seq = 0"
                                " AND source_ns IN (%s)" % ",".join("?" * len(exns9)), exns9).fetchall()
            cand_c = conn.execute("SELECT source_ns, source_id, event_ts FROM postings WHERE source_kind = 'chain_tx' AND leg_kind = 'acq'"
                                  " AND event IN ('TRANSFER_IN', 'PROGRAM_IN')").fetchall()
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_load:LoadMixin._ord_wd_first[cand]", e9)
            log.warning("출금·도착 순서 후보 조회 실패(이번 빌드 종전 순서): %s", logs.safe_err(e9)[:160])
            return rows
        wts = {}
        arr = []
        for ns9, sid9, t9 in cand:
            if ns9.endswith(":withdraw"):
                if (ns9, sid9) in wd:
                    wts[(ns9, sid9)] = int(t9)
            else:
                d9 = dep.get((ns9, sid9))
                if d9 and d9[1] in wd_tx:
                    arr.append((ns9, sid9, int(t9), d9[1], d9[0]))
        seen9 = set()
        for ns9, sid9, t9 in cand_c:
            tk9 = _txk(sid9)
            if tk9 in wd_tx and (ns9, sid9) not in seen9:
                seen9.add((ns9, sid9))
                arr.append((ns9, sid9, int(t9), tk9, None))
        pairs = []
        far = []
        for ns9, sid9, at9, t9, aex9 in arr:
            for wns9, wu9, wex9 in wd_tx[t9]:
                wt9 = wts.get((wns9, wu9))
                if wt9 is not None and wex9 != aex9 and at9 + ORD_GAP_SEC < wt9 <= at9 + 30 * 86400:
                    far.append((ns9, sid9, at9, wex9, wt9, t9))
                if wt9 is None or wex9 == aex9 or not (at9 <= wt9 <= at9 + ORD_GAP_SEC):
                    continue
                pairs.append(((ns9, sid9, at9), (wns9, wu9, wt9)))
        self._ord_far = far
        if not pairs:
            return rows

        def where(key):
            ns9, sid9, t9 = key
            k = bisect.bisect_left(ts, t9)
            while k < len(rows) and ts[k] == t9:
                if rows[k]["source_ns"] == ns9 and rows[k]["source_id"] == sid9:
                    e = k + 1
                    while e < len(rows) and rows[e]["source_ns"] == ns9 and rows[e]["source_id"] == sid9 and ts[e] == t9:
                        e += 1
                    return k, e
                k += 1
            return None

        def gids(s, e):
            return {rows[k]["group_id"] or -rows[k]["asset_id"] for k in range(s, e)}
        moves, used = [], set()
        for akey, wkey in pairs:
            a9, w9 = where(akey), where(wkey)
            if a9 is None or w9 is None or a9[1] > w9[0] or a9[0] in used or w9[0] in used:
                continue
            gw9, ga9 = gids(*w9), gids(*a9)
            if not any((rows[k]["group_id"] or -rows[k]["asset_id"]) in gw9 for k in range(a9[0], w9[0])):
                moves.append((a9[0], w9))
                diag["wdMoved"] += 1
            elif not any((rows[k]["group_id"] or -rows[k]["asset_id"]) in ga9 for k in range(a9[1], w9[1])):
                moves.append((w9[1], a9))
                diag["arrMoved"] += 1
            else:
                diag["wdKept"] += 1
                continue
            used.update((a9[0], w9[0]))
        return _ord_splice(rows, moves) if moves else rows

    def _norm(self, row) -> Decimal:
        dec = row["decimals"] if row["decimals"] is not None else 18
        return Decimal(int(row["qty_base"])) / (Decimal(10) ** int(dec))

    @staticmethod
    def _flow_chain(fl) -> str:
        chl = fl.get("chl") or {}
        if not chl:
            return CHAIN_NAME.get(fl["chain"], fl["chain"])
        labs = [k for k, _ in sorted(chl.items(), key=lambda kv: (-kv[1], kv[0]))]
        return " · ".join(labs) if len(labs) <= 2 else " · ".join(labs[:2]) + f" 외 {len(labs) - 2}"

    PREWIN_MAX = 20000

    @staticmethod
    def _prewin_pairs(conn, cap: int = None) -> set:
        cap = LoadMixin.PREWIN_MAX if cap is None else cap
        out = set()
        try:
            ks = conn.execute("SELECT k FROM meta WHERE k >= 'ext_prewindow_tx:' AND k < 'ext_prewindow_tx;' LIMIT ?", (int(cap),)).fetchall()
            for (k9,) in ks:
                parts = str(k9).split(":", 2)
                if len(parts) != 3:
                    continue
                for g9, loc9 in conn.execute(
                        "SELECT DISTINCT a.group_id, p.location FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                        " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=?", (parts[1], parts[2])).fetchall():
                    if g9 is not None:
                        out.add((int(g9), loc9))
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_load:LoadMixin._prewin_pairs", e9)
            log.warning("재계산 대기 표식 읽기 실패(원장 음수 보유 문구 구분 없이): %s", type(e9).__name__)
            return set()
        return out

    @staticmethod
    def _gsym(row) -> str:
        k9 = (row["gname"], row["symbol"])
        v9 = _GSYM_MEMO.get(k9)
        if v9 is not None:
            return v9
        v9 = LoadMixin._gsym_calc(row)
        if len(_GSYM_MEMO) < 200000:
            _GSYM_MEMO[k9] = v9
        return v9

    @staticmethod
    def _gsym_calc(row) -> str:
        name = row["gname"] or (row["symbol"] or "?")
        if row["symbol"] and re.fullmatch(r"TOKEN#\d+", name or ""):
            return str(row["symbol"]).strip() or "TOKEN"
        return re.sub(r"#\d+$", "", name)

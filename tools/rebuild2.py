"""Shadow ledger rebuild with verification gates."""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from decimal import Decimal, localcontext, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
import common

LIVE_STATE = common.STATE_DIR
LIVE_DB = common.DB_PATH
DERIVED_TABLES = ("postings", "tx_class", "transfers", "positions")
ANCHOR_SQL = ("SELECT source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location,"
              " qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver"
              " FROM postings WHERE leg_kind='opening' ORDER BY posting_id")


DECIMAL_PREC = 100


def _qty_norm(qb, dec) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        return Decimal(int(qb)) / (Decimal(10) ** int(dec))


def _paths_overlap(a: str, b: str) -> bool:
    a, b = os.path.realpath(a), os.path.realpath(b)
    try:
        cp = os.path.commonpath((a, b))
    except ValueError:
        return False
    return cp in (a, b)


def _make_private_dir(d: str):
    new = not os.path.exists(d)
    os.makedirs(d, mode=0o700, exist_ok=True)
    if new or os.path.basename(os.path.normpath(d)).startswith("tj_shadow"):
        os.chmod(d, 0o700)


def _write_private_json(path: str, obj):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass
    with os.fdopen(fd, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=1)


def _ro(path, immutable: bool = False):
    q = "mode=ro&immutable=1" if immutable else "mode=ro"
    return sqlite3.connect(f"file:{path}?{q}", uri=True, timeout=10)


def snapshot_from(baseline_dir: str, shadow_dir: str) -> tuple:
    if _paths_overlap(shadow_dir, LIVE_STATE) or _paths_overlap(shadow_dir, ROOT) \
            or _paths_overlap(shadow_dir, baseline_dir):
        raise SystemExit("shadow-dir 가 라이브/저장소/기준선 디렉터리와 겹친다 — 중단")
    _make_private_dir(shadow_dir)
    for sub in ("inbox/evm", "inbox/sol", "inbox/bsc", "inbox/ex"):
        os.makedirs(os.path.join(shadow_dir, sub), exist_ok=True)
    src_base = os.path.join(baseline_dir, "live_snapshot.db")
    if not os.path.exists(src_base):
        raise SystemExit(f"기준선 없음: {src_base}")
    dst = os.path.join(shadow_dir, "ledger.db")
    baseline = os.path.join(shadow_dir, "live_snapshot.db")
    for base in (dst, baseline):
        for p in (base, base + "-wal", base + "-shm"):
            if os.path.exists(p):
                os.remove(p)
    shutil.copy2(src_base, baseline)
    os.chmod(baseline, 0o400)
    shutil.copy2(src_base, dst)
    os.chmod(dst, 0o600)
    for f in os.listdir(shadow_dir):
        if (f.endswith((".json", ".jsonl")) or f == "backfill_done") and not os.path.exists(os.path.join(baseline_dir, f)):
            os.remove(os.path.join(shadow_dir, f))
    for f in os.listdir(baseline_dir):
        if (f.endswith(".json") or f.endswith(".jsonl") or f == "backfill_done") and f != "rebuild2_report.json":
            shutil.copy2(os.path.join(baseline_dir, f), os.path.join(shadow_dir, f))
    _copy_seed_local(baseline_dir, shadow_dir)
    return dst, baseline


def _copy_seed_local(src_state: str, shadow_dir: str) -> None:
    dst9 = os.path.join(shadow_dir, "seed_local")
    if os.path.isdir(dst9):
        shutil.rmtree(dst9)
    src9 = os.path.join(src_state, "seed_local")
    if os.path.isdir(src9):
        shutil.copytree(src9, dst9)


def snapshot_live(shadow_dir: str) -> tuple:
    if _paths_overlap(shadow_dir, LIVE_STATE) or _paths_overlap(shadow_dir, ROOT):
        raise SystemExit("shadow-dir 가 라이브 state/저장소와 겹친다 — 중단")
    _make_private_dir(shadow_dir)
    for sub in ("inbox/evm", "inbox/sol", "inbox/bsc", "inbox/ex"):
        os.makedirs(os.path.join(shadow_dir, sub), exist_ok=True)
    dst = os.path.join(shadow_dir, "ledger.db")
    baseline = os.path.join(shadow_dir, "live_snapshot.db")
    for base in (dst, baseline):
        for p in (base, base + "-wal", base + "-shm"):
            if os.path.exists(p):
                os.remove(p)
    src = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True, timeout=30)
    tgt = sqlite3.connect(baseline)
    try:
        src.backup(tgt)
    finally:
        tgt.close()
        src.close()
    shutil.copy2(baseline, dst)
    os.chmod(dst, 0o600)
    os.chmod(baseline, 0o400)
    n = 0
    for f in os.listdir(shadow_dir):
        if (f.endswith((".json", ".jsonl")) or f == "backfill_done") and not os.path.exists(os.path.join(LIVE_STATE, f)):
            os.remove(os.path.join(shadow_dir, f))
    for f in os.listdir(LIVE_STATE):
        if f.endswith(".json") or f.endswith(".jsonl"):
            shutil.copy2(os.path.join(LIVE_STATE, f), os.path.join(shadow_dir, f))
            n += 1
    for f in ("backfill_done",):
        p = os.path.join(LIVE_STATE, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(shadow_dir, f))
    _copy_seed_local(LIVE_STATE, shadow_dir)
    return dst, baseline


def offline_patch(pricing):
    stats = {"candle_hit": 0, "candle_miss": 0, "fx_hit": 0, "fx_miss": 0}

    def candle_usd(self, sym, ts_ms):
        sym = sym.upper()
        m = (ts_ms // 60_000) * 60_000
        key = f"{sym}:{m}"
        v = self.d["candle"].get(key)
        if v:
            stats["candle_hit"] += 1
            return v
        if sym in ("USDT", "USDC", "DAI"):
            stats["candle_hit"] += 1
            return 1.0
        stats["candle_miss"] += 1
        return None

    def fx_at(self, ts_ms):
        m = (ts_ms // 60_000) * 60_000
        v = self.d["fx"].get(str(m))
        if v:
            stats["fx_hit"] += 1
            return v
        stats["fx_miss"] += 1
        return None

    def maybe_save(self):
        return None

    pricing.PxCache.candle_usd = candle_usd
    pricing.PxCache.fx_at = fx_at
    pricing.PxCache.maybe_save = maybe_save
    pricing.PxCache.flush = maybe_save

    def _deny(*a, **k):
        raise RuntimeError("offline rebuild: 네트워크 호출 금지")
    for name in ("_gj", "upbit_krw_markets", "upbit_spot_krw", "_fx_candle_krw_per_usdt"):
        if hasattr(pricing, name):
            setattr(pricing, name, _deny)
    return stats


def sums_by_asset_loc(conn):
    out = {}
    for r in conn.execute("SELECT asset_id, location, qty_base FROM postings"):
        k = (r[0], r[1])
        out[k] = out.get(k, 0) + int(r[2])
    return out


def positions_map(conn):
    return {(r[0], r[1]): Decimal(r[2]) for r in conn.execute(
        "SELECT group_id, location, qty_norm FROM positions")}


def asset_label(conn, aid, alt=None):
    r = conn.execute("SELECT symbol, chain, kind FROM assets WHERE asset_id=?", (aid,)).fetchone()
    if not r and alt is not None:
        r = alt.execute("SELECT symbol, chain, kind FROM assets WHERE asset_id=?", (aid,)).fetchone()
    return f"{r[0] or '?'}({r[1]}/{r[2]})" if r else f"aid{aid}"

def anchor_time(source_id: str, obs: dict, meta: dict):
    if source_id.startswith("recon:"):
        return obs.get(source_id)
    if source_id.startswith("rebal"):
        return obs.get(source_id.split(":")[0])
    if source_id.startswith("exrecon:"):
        return meta.get("recon_done_upbit")
    if source_id.startswith("exfrecon:"):
        try:
            return int(source_id.rsplit(":", 1)[1])
        except ValueError:
            return None
    return None


class KnownIndex:

    @staticmethod
    def _ex_key(ns: str, sid: str):
        ex, _, kind = (ns or "").partition(":")
        if kind == "recon_comp":
            kind = "deposit"
        return (ex, kind, sid)

    def __init__(self, conn, obs, meta, tx_at_override=None):
        self.tx_at = {(r[0], r[1]): r[2] for r in conn.execute("SELECT chain, txhash, ingested_at FROM raw_txs")}
        if tx_at_override:
            self.tx_at.update(tx_at_override)
        self.ex_at = {}
        for r in conn.execute(
                "SELECT r.exchange, r.kind, r.uuid, r.observed_at FROM raw_ex r JOIN"
                " (SELECT exchange, kind, uuid, max(revision) AS revision FROM raw_ex"
                "  GROUP BY exchange, kind, uuid) x"
                " ON x.exchange=r.exchange AND x.kind=r.kind AND x.uuid=r.uuid AND x.revision=r.revision"):
            self.ex_at[(r[0], r[1], r[2])] = r[3]
        self.meta_dec = {}
        self.sym_of = {}
        for r in conn.execute("SELECT asset_id, symbol, decimals FROM assets"):
            self.sym_of[r[0]] = (r[1] or "").upper()
            self.meta_dec[r[0]] = int(r[2]) if r[2] is not None else 18
        self.items = {}
        self.unknown_t = 0
        for r in conn.execute("SELECT source_kind, source_ns, source_id, leg_kind, asset_id, location,"
                              " qty_base FROM postings"):
            sk, ns, sid, lk, aid, loc, qb = r
            anchor = lk == "opening"
            if anchor:
                t = anchor_time(sid, obs, meta)
                if t is None and ns == "upbit:recon_comp":
                    t = self.ex_at.get(self._ex_key(ns, sid))
            elif sk == "chain_tx":
                t = self.tx_at.get((ns, sid))
            elif sk == "exchange":
                t = self.ex_at.get(self._ex_key(ns, sid))
            else:
                t = None
            if t is None:
                self.unknown_t += 1
                t = 0
            self.add(aid, loc, t, anchor, _qty_norm(qb, self.meta_dec[aid]))
        for k in self.items:
            self.items[k].sort(key=lambda x: (x[0], x[1]))

    def add(self, aid, loc, t, anchor, q):
        for key in (("aid", aid, loc), ("sym", self.sym_of.get(aid, ""), loc)):
            self.items.setdefault(key, []).append((t, anchor, q))

    def add_sorted(self, aid, loc, t, anchor, q, sym=None):
        if sym is None:
            sym = self.sym_of.get(aid, "")
        self.sym_of.setdefault(aid, sym)
        for key in (("aid", aid, loc), ("sym", sym, loc)):
            lst = self.items.setdefault(key, [])
            lst.append((t, anchor, q))
            lst.sort(key=lambda x: (x[0], x[1]))

    def sum_before(self, key, T) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = DECIMAL_PREC
            tot = Decimal(0)
            for t, anchor, q in self.items.get(key, []):
                if t > T:
                    break
                if anchor and t >= T:
                    continue
                tot += q
            return tot


def core_mod_ver(core) -> int:
    return int(getattr(sys.modules.get(type(core).__module__), "CLASSIFIER_VER", 3))


def recompute_anchors(live_db, conn, core, anchors, obs, meta):
    live = _ro(live_db, immutable=True)
    try:
        live_idx = KnownIndex(live, obs, meta)
    finally:
        live.close()
    ov = {}
    lv = _ro(live_db, immutable=True)
    try:
        for k9, v9 in lv.execute("SELECT k, v FROM meta WHERE k LIKE 'ext\\_prewindow\\_tx:%' ESCAPE '\\'").fetchall():
            try:
                _, ch9, h9 = k9.split(":", 2)
                ov[(ch9, h9)] = int(float(v9))
            except ValueError:
                continue
    finally:
        lv.close()
    sh_idx = KnownIndex(conn, obs, meta, tx_at_override=ov)
    ov_chains = {ch for ch, _h in ov}
    rows = []
    rounding = []
    verbatim = changed = zeroed = dropped_comp = remapped = 0
    added_new = skipped_unobs = 0
    synth = []
    if ov:
        have = {(a[5], a[6], str(a[2])) for a in anchors if str(a[2]).startswith("recon:")}
        touched = set()
        for (ch9, h9) in ov:
            for aid9, loc9 in conn.execute("SELECT DISTINCT asset_id, location FROM postings WHERE source_kind='chain_tx'"
                                           " AND source_ns=? AND source_id=? AND location LIKE 'wallet:%'", (ch9, h9)).fetchall():
                touched.add((ch9, aid9, loc9))
        pay_cache = {}
        scope_cache = {}
        unobs_cache = {}
        q_cache = {}

        def observed(oid9, ch9, aid9, loc9):
            if oid9 not in pay_cache:
                r9 = conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (oid9,)).fetchone()
                try:
                    d9 = json.loads(r9[0]) if r9 and r9[0] else {}
                except (TypeError, ValueError):
                    d9 = {}
                pay_cache[oid9] = {str(w).lower(): {str(k).lower() for k in (v or {})} for w, v in (d9 or {}).items()
                                   if isinstance(v, dict)} if isinstance(d9, dict) else {}
                scope_cache[oid9] = d9.get("_scope") if isinstance(d9, dict) else None
                u9 = d9.get("_unobs") if isinstance(d9, dict) else None
                unobs_cache[oid9] = {str(x).lower() for x in u9} if isinstance(u9, list) else set()
                q9 = d9.get("_q") if isinstance(d9, dict) else None
                q_cache[oid9] = {str(x).lower() for x in q9} if isinstance(q9, list) else None
            w9 = loc9.split(":", 2)[2].lower() if loc9.count(":") >= 2 else None
            if not w9 or w9 not in pay_cache[oid9]:
                return False
            if unobs_cache.get(oid9) or q_cache.get(oid9) is not None:
                a9 = conn.execute("SELECT kind, address FROM assets WHERE asset_id=?", (aid9,)).fetchone()
                k9 = f"{w9}:{str((a9 or [None, ''])[1] or '').lower()}"
                if a9 and a9[0] == "token" and (k9 in unobs_cache[oid9] or (q_cache[oid9] is not None and k9 not in q_cache[oid9])):
                    return False
            if scope_cache.get(oid9) in ("token", "native"):
                a9 = conn.execute("SELECT kind FROM assets WHERE asset_id=?", (aid9,)).fetchone()
                if bool(a9 and a9[0] == "native") != (scope_cache[oid9] == "native"):
                    return False
            if ch9 == "bsc":
                a9 = conn.execute("SELECT kind, address FROM assets WHERE asset_id=?", (aid9,)).fetchone()
                k9 = "native:none" if (a9 and a9[0] == "native") else f"token:{str((a9 or [None, ''])[1] or '').lower()}"
                return k9 in pay_cache[oid9][w9]
            return True

        for ch9, aid9, loc9 in sorted(touched):
            cands = [f"recon:{ch9}"]
            if loc9.count(":") == 2:
                cands.append(f"recon:{ch9}:{loc9.split(':', 2)[2]}")
                cands.append(f"recon:{ch9}:{loc9.split(':', 2)[2]}:native")
            for oid9 in cands:
                T9 = obs.get(oid9)
                if T9 is None or (aid9, loc9, oid9) in have:
                    continue
                if not observed(oid9, ch9, aid9, loc9):
                    skipped_unobs += 1
                    continue
                synth.append((int(T9), oid9, ch9, aid9, loc9))
    seq_next = {}

    def _next_seq(ch9, oid9):
        if (ch9, oid9) not in seq_next:
            m9 = conn.execute("SELECT coalesce(max(leg_seq), -1) FROM postings WHERE source_kind='opening' AND source_ns=?"
                              " AND source_id=?", (ch9, oid9)).fetchone()[0]
            for a in anchors:
                if a[0] == "opening" and a[1] == ch9 and a[2] == oid9:
                    m9 = max(m9, int(a[3]))
            seq_next[(ch9, oid9)] = int(m9) + 1
        s9 = seq_next[(ch9, oid9)]
        seq_next[(ch9, oid9)] = s9 + 1
        return s9

    order = []
    for a in anchors:
        sid, ns, aid, loc, qb = a[2], a[1], a[5], a[6], int(a[7])
        T = anchor_time(sid, obs, meta)
        order.append((T if T is not None else -1, a, False))
    for T9, oid9, ch9, aid9, loc9 in synth:
        order.append((T9, ("opening", ch9, oid9, _next_seq(ch9, oid9), T9, aid9, loc9, "0", None, None, "opening", "OPENING",
                           core_mod_ver(core)), True))
    order.sort(key=lambda x: x[0])
    seen_leg = set()
    for T, a, is_new in order:
        sk, ns, sid, seq, ets, aid, loc, qb = a[0], a[1], a[2], a[3], a[4], a[5], a[6], int(a[7])
        dec = sh_idx.meta_dec.get(aid, 18)
        q_live = _qty_norm(qb, dec)
        if ns in ("upbit:recon_comp", "upbit:recon"):
            dropped_comp += 1
            continue
        if T < 0:
            cur9 = conn.execute("INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
                                " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", a)
            if cur9.rowcount:
                core._bump_position(aid, qb, loc)
                sh_idx.add_sorted(aid, loc, 0, True, q_live, sym=sh_idx.sym_of.get(aid, ""))
            verbatim += 1
            continue
        sym9 = sh_idx.sym_of.get(aid, "")
        key = ("aid", aid, loc) if sk == "opening" else ("sym", sym9, loc)
        ldec9 = live_idx.meta_dec.get(aid, 18) if key[0] == "aid" else dec
        rescale9 = (Decimal(10) ** int(ldec9)) / (Decimal(10) ** int(dec)) if ldec9 != dec else None
        tgt_aid, tgt_dec = aid, dec
        if loc == "exchange:upbit":
            tgt_aid, tgt_dec = core._upbit_asset(sym9), 8
            remapped += (1 if tgt_aid != aid else 0)
        live_then = live_idx.sum_before(key, T)
        sh_then = sh_idx.sum_before(key, T)
        dup_leg = (key, T, sid) in seen_leg
        seen_leg.add((key, T, sid))
        with localcontext() as ctx:
            ctx.prec = DECIMAL_PREC
            if rescale9 is not None:
                actual = (live_then + _qty_norm(qb, ldec9)) * rescale9
            else:
                actual = live_then + q_live
            new_q = q_live if dup_leg else actual - sh_then
            scaled = new_q * (Decimal(10) ** tgt_dec)
            new_qb = int(scaled.to_integral_value())
            if scaled != new_qb:
                rounding.append({"sid": sid, "asset": tgt_aid, "residual": str(scaled - new_qb)})
        new_q = _qty_norm(new_qb, tgt_dec)
        rows.append({"ns": ns, "sid": sid, "asset": f"{sym9}#{aid}", "tgt_asset": tgt_aid, "loc": loc,
                     "T": T, "live_then": str(live_then), "shadow_then": str(sh_then),
                     "diff_live": str(q_live), "diff_new": str(new_q), "delta": str(new_q - q_live)}
                    | ({"new_anchor": True} if is_new else {}))
        if is_new:
            if new_qb == 0:
                continue
            ets9 = int(T)
            if new_qb > 0:
                ets9 = core._win_t0(T, ns)
                if sid != f"recon:{ns}":
                    f9 = conn.execute("SELECT min(event_ts) FROM postings WHERE location=? AND source_kind='chain_tx'",
                                      (loc,)).fetchone()[0]
                    if f9 is not None:
                        ets9 = min(ets9, int(f9) - 1)
            conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                         " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('opening',?,?,?,?,?,?,?,NULL,NULL,'opening',"
                         "'OPENING',?)", (ns, sid, seq, ets9, aid, loc, str(new_qb), a[12]))
            core._bump_position(aid, new_qb, loc)
            sh_idx.add_sorted(aid, loc, T, True, new_q, sym=sym9)
            added_new += 1
            continue
        if new_qb == 0:
            zeroed += 1
            continue
        if new_qb != qb:
            changed += 1
        if ov and new_qb > 0 and ns in ov_chains and sid.startswith("recon:"):
            ets = min(int(ets), core._win_t0(T, ns))
        if (new_qb > 0) != (qb > 0):
            ets = (T - int(core.recon_months * 30 * 86400)) if (new_qb > 0 and core.recon_months > 0) else T
        cur9 = conn.execute("INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
                            " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sk, ns, sid, seq, ets, tgt_aid, loc, str(new_qb), a[8], a[9], a[10], a[11], a[12]))
        if not cur9.rowcount:
            continue
        core._bump_position(tgt_aid, new_qb, loc)
        sh_idx.add_sorted(tgt_aid, loc, T, True, new_q, sym=sym9)
    conn.commit()
    return {"total": len(anchors), "verbatim": verbatim, "changed": changed, "zeroed": zeroed, "added_prewindow": added_new,
            "prewindow_unobserved": skipped_unobs,
            "dropped_comp": dropped_comp, "remapped_canonical": remapped,
            "unknown_t_live": live_idx.unknown_t, "unknown_t_shadow": sh_idx.unknown_t, "prewindow_override": len(ov),
            "rounding_residuals": len(rounding), "rounding": rounding[:50], "rows": rows}


def gates(b, t0: int = 0, iso=None) -> dict:
    g = {}
    _before_window = set()
    def _ts(p, keys):
        for k in keys:
            v = p.get(k)
            if v and iso:
                t = iso(v)
                if t:
                    return t
        return None
    missing, mismatch, total, unlinked_sum = [], [], 0, {}
    linked = {r[0] for r in b.execute("SELECT ex_uuid FROM transfers WHERE ex_uuid IS NOT NULL")}
    post = {}
    for r in b.execute("SELECT source_id, qty_base FROM postings WHERE source_ns='upbit:deposit'"):
        post[r[0]] = post.get(r[0], 0) + int(r[1])
    for r in b.execute("SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='deposit'"
                       " GROUP BY uuid HAVING revision = MAX(revision)"):
        try:
            p = json.loads(r[1])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        if str(p.get("state") or "").upper() != "ACCEPTED":
            continue
        cur = str(p.get("currency") or "").upper()
        if not cur or cur == "KRW":
            continue
        try:
            if Decimal(str(p.get("amount"))) <= 0:
                continue
        except Exception:
            pass
        dts = _ts(p, ("done_at", "created_at"))
        if t0 and dts is not None and dts < t0:
            _before_window.add(r[0])
            continue
        if dts is None and iso:
            g.setdefault("_held_no_time", []).append(r[0])
            continue
        total += 1
        try:
            q8 = int(Decimal(str(p.get("amount"))) * (Decimal(10) ** 8))
        except Exception:
            q8 = None
        got = post.get(r[0])
        if got is None:
            missing.append((r[0], cur, str(p.get("amount"))))
        elif q8 is not None and got != q8:
            mismatch.append((r[0], cur, str(p.get("amount")), got))
        if r[0] not in linked and got:
            unlinked_sum[cur] = unlinked_sum.get(cur, 0) + got
    eligible = set()
    for r in b.execute("SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='deposit'"
                       " GROUP BY uuid HAVING revision = MAX(revision)"):
        try:
            p = json.loads(r[1])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        cur = str(p.get("currency") or "").upper()
        if str(p.get("state") or "").upper() == "ACCEPTED" and cur and cur != "KRW" and r[0] not in _before_window:
            eligible.add(r[0])
    extra = sorted(set(post) - eligible)
    g["G0_deposits"] = {"total": total, "missing": len(missing), "mismatch": len(mismatch),
                        "posted_not_eligible": len(extra), "posted_not_eligible_sample": extra[:10],
                        "before_window_skipped": len(_before_window),
                        "missing_sample": missing[:10], "mismatch_sample": mismatch[:10],
                        "unlinked_sum_q8": {k: str(v) for k, v in sorted(unlinked_sum.items())}}
    import core as _core9
    elig_ord, elig_q, n_nonkrw = set(), {}, 0
    for r in b.execute("SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='order'"
                       " GROUP BY uuid HAVING revision = MAX(revision)"):
        try:
            o = json.loads(r[1])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        mk = str(o.get("market") or "")
        if not mk.startswith("KRW-"):
            n_nonkrw += 1
            p9 = _core9.Core._upbit_quote_fill_legs(_core9.Core, o)
            if p9 is not None:
                elig_q[r[0]] = p9
            continue
        try:
            vol = Decimal(str(o.get("executed_volume") or "0"))
            funds = o.get("executed_funds")
            krw = Decimal(str(funds)) if funds is not None else Decimal(str(o.get("price") or "0")) * vol
            fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
            side = str(o.get("side") or "").lower()
            if not (vol.is_finite() and krw.is_finite() and fee.is_finite()):
                continue
            if side in ("bid", "ask") and vol > 0 and krw > 0 and fee >= 0 \
                    and (vol * (Decimal(10) ** 8)) == (vol * (Decimal(10) ** 8)).to_integral_value():
                elig_ord.add(r[0])
        except (InvalidOperation, ValueError, TypeError):
            continue
    post_ord = {}
    for r in b.execute("SELECT source_id, leg_seq, qty_base, event, cost_krw FROM postings WHERE source_ns='upbit:order'"):
        post_ord[(r[0], int(r[1]))] = (int(r[2]), r[3], r[4])
    ord_mismatch = []
    for r in b.execute("SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='order'"
                       " GROUP BY uuid HAVING revision = MAX(revision)"):
        if r[0] in elig_q:
            _b9, _q9, bqb, qqb, _t9, _s9 = elig_q[r[0]]
            for seq9, exp9 in ((0, bqb), (1, qqb)):
                got9 = post_ord.get((r[0], seq9))
                if got9 is None:
                    continue
                if got9[0] != exp9 or got9[1] != ("EX_BUY" if exp9 > 0 else "EX_SELL"):
                    ord_mismatch.append((r[0], f"nonkrw_leg{seq9}"))
            continue
        if r[0] not in elig_ord or (r[0], 0) not in post_ord:
            continue
        try:
            o = json.loads(r[1])
            vol = Decimal(str(o.get("executed_volume") or "0")); side = str(o.get("side") or "").lower()
            fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
            funds = o.get("executed_funds")
            krw = Decimal(str(funds)) if funds is not None else Decimal(str(o.get("price") or "0")) * vol
            net = (krw - fee) if side == "ask" else (krw + fee)
            exp_qb = int(vol * (Decimal(10) ** 8)) * (-1 if side == "ask" else 1)
            exp_ev = "EX_SELL" if side == "ask" else "EX_BUY"
        except Exception:
            ord_mismatch.append((r[0], "parse")); continue
        qb, ev, ck = post_ord[(r[0], 0)]
        try:
            ck_ok = ck is not None and abs(Decimal(str(ck)) - net) <= Decimal("0.000001")
        except Exception:
            ck_ok = False
        if qb != exp_qb or ev != exp_ev or not ck_ok:
            ord_mismatch.append((r[0], "qty" if qb != exp_qb else ("event" if ev != exp_ev else "cost_krw")))
        if (r[0], 1) in post_ord:
            ord_mismatch.append((r[0], "krw_extra_leg"))
    posted_ord = {r[0] for r in b.execute("SELECT DISTINCT source_id FROM postings WHERE source_ns='upbit:order'")}
    nonkrw_legs = {}
    for (sid9, _seq9) in post_ord:
        if sid9 in elig_q:
            nonkrw_legs[sid9] = nonkrw_legs.get(sid9, 0) + 1
    dup_ord = b.execute("SELECT count(*) FROM (SELECT source_id, leg_seq FROM postings WHERE source_ns='upbit:order'"
                        " GROUP BY source_id, leg_seq HAVING count(*) > 1)").fetchone()[0]
    all_elig = elig_ord | set(elig_q)
    g["G0_orders"] = {"krw_orders": len(elig_ord), "nonkrw_orders": len(elig_q), "posted": len(posted_ord),
                      "missing": len(all_elig - posted_ord), "extra": len(posted_ord - all_elig),
                      "nonkrw_incomplete_legs": sum(1 for u in elig_q if nonkrw_legs.get(u, 0) != 2),
                      "duplicate_uuid": dup_ord, "mismatch": len(ord_mismatch), "mismatch_sample": ord_mismatch[:10],
                      "non_krw_orders_ineligible": n_nonkrw - len(elig_q)}
    wd_post = {}
    for r in b.execute("SELECT source_id, qty_base FROM postings WHERE source_ns='upbit:withdraw'"):
        wd_post[r[0]] = wd_post.get(r[0], 0) + int(r[1])
    wd_total, wd_missing, wd_mismatch, wd_before = 0, [], [], 0
    for r in b.execute("SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='withdraw'"
                       " GROUP BY uuid HAVING revision = MAX(revision)"):
        try:
            p = json.loads(r[1])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        if str(p.get("state") or "").upper() != "DONE":
            continue
        cur = str(p.get("currency") or "").upper()
        if not cur or cur == "KRW":
            continue
        try:
            amt = Decimal(str(p.get("amount")))
            fee = Decimal(str(p.get("fee") if p.get("fee") not in (None, "") else "0"))
            if amt <= 0:
                continue
            exp = -int((amt + fee) * (Decimal(10) ** 8))
        except Exception:
            exp = None
        wts = _ts(p, ("created_at", "done_at"))
        if t0 and wts is not None and wts < t0:
            wd_before += 1
            continue
        if wts is None and iso:
            continue
        wd_total += 1
        got = wd_post.get(r[0])
        if got is None:
            wd_missing.append((r[0], cur, str(p.get("amount")), str(p.get("fee"))))
        elif exp is not None and got != exp:
            wd_mismatch.append((r[0], cur, exp, got))
    wd_elig = set()
    for r in b.execute("SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='withdraw'"
                       " GROUP BY uuid HAVING revision = MAX(revision)"):
        try:
            p = json.loads(r[1])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        cur = str(p.get("currency") or "").upper()
        if str(p.get("state") or "").upper() != "DONE" or not cur or cur == "KRW":
            continue
        try:
            if Decimal(str(p.get("amount"))) <= 0:
                continue
        except Exception:
            continue
        wts = _ts(p, ("created_at", "done_at"))
        if t0 and wts is not None and wts < t0:
            continue
        if wts is None and iso:
            continue
        wd_elig.add(r[0])
    wd_extra = sorted(set(wd_post) - wd_elig)
    wd_dup = b.execute("SELECT count(*) FROM (SELECT source_id FROM postings WHERE source_ns='upbit:withdraw'"
                       " GROUP BY source_id HAVING count(*) > 1)").fetchone()[0]
    g["G0_withdraws"] = {"total": wd_total, "before_window_skipped": wd_before,
                         "missing": len(wd_missing), "mismatch": len(wd_mismatch),
                         "posted_not_eligible": len(wd_extra), "duplicate_uuid": wd_dup,
                         "missing_sample": wd_missing[:10], "mismatch_sample": wd_mismatch[:10]}
    bad = b.execute("SELECT count(*) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                    " WHERE p.location='exchange:upbit' AND (a.kind != 'exchange_currency'"
                    " OR a.address IS NULL OR a.address NOT LIKE 'upbit:_%' OR a.decimals IS NULL OR a.decimals != 8"
                    " OR a.symbol IS NULL OR trim(a.symbol) = ''"
                    " OR upper(a.address) != 'UPBIT:' || upper(a.symbol))").fetchone()[0]
    bad_anchor = b.execute("SELECT count(*) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                           " WHERE p.location='exchange:upbit' AND p.leg_kind='opening'"
                           " AND a.kind != 'exchange_currency'").fetchone()[0]
    bad_rev = b.execute("SELECT count(*) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                        " WHERE a.kind='exchange_currency' AND a.address LIKE 'upbit:%'"
                        " AND p.location != 'exchange:upbit'").fetchone()[0]
    shape_bad = b.execute(
        "SELECT count(*) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
        " WHERE p.source_ns IN ('upbit:deposit','upbit:withdraw','upbit:order') AND ("
        "  p.location != 'exchange:upbit' OR a.kind != 'exchange_currency' OR a.decimals != 8"
        "  OR (p.source_ns='upbit:deposit' AND NOT (p.leg_kind='move_in' AND p.event='EX_DEPOSIT' AND cast(p.qty_base as integer) > 0))"
        "  OR (p.source_ns='upbit:withdraw' AND NOT (p.leg_kind='move_out' AND p.event='EX_WITHDRAW' AND cast(p.qty_base as integer) < 0))"
        "  OR (p.source_ns='upbit:order' AND NOT ((p.leg_kind='acq' AND p.event='EX_BUY' AND cast(p.qty_base as integer) > 0)"
        "                                        OR (p.leg_kind='disp' AND p.event='EX_SELL' AND cast(p.qty_base as integer) < 0))))").fetchone()[0]
    g["G2_canonical"] = {"non_canonical_postings": bad, "non_canonical_anchors": bad_anchor,
                         "canonical_outside_upbit": bad_rev, "upbit_posting_shape_bad": shape_bad}
    g3_n, g3_bad = 0, []
    dep_amt = {}
    for r in b.execute("SELECT source_id, qty_base FROM postings WHERE source_ns='upbit:deposit'"):
        dep_amt[r[0]] = dep_amt.get(r[0], Decimal(0)) + Decimal(int(r[1])) / Decimal(10) ** 8
    srcs = {}
    dep_sym = {}
    for r in b.execute("SELECT p.source_id, upper(a.symbol) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                       " WHERE p.source_ns='upbit:deposit'"):
        dep_sym[r[0]] = r[1]
    for r in b.execute("SELECT t.ex_uuid, t.qty_base, a.decimals, upper(a.symbol) FROM transfers t"
                       " JOIN assets a ON a.asset_id=t.asset_id WHERE t.state='credited' AND t.ex_uuid IS NOT NULL"
                       " AND t.ex_uuid IN (SELECT uuid FROM raw_ex WHERE exchange='upbit' AND kind='deposit')"):
        d = int(r[2]) if r[2] is not None else 18
        srcs.setdefault((r[0], r[3]), Decimal(0))
        srcs[(r[0], r[3])] += Decimal(int(r[1])) / Decimal(10) ** d
    multi = {r[0]: r[1] for r in b.execute(
        "SELECT t1.ex_uuid, count(DISTINCT coalesce(upper(a2.symbol), '')) FROM transfers t1"
        " JOIN transfers t2 ON t2.chain_txhash = t1.chain_txhash JOIN assets a2 ON a2.asset_id = t2.asset_id"
        " WHERE t1.state='credited' AND t1.ex_uuid IS NOT NULL AND t1.chain_txhash IS NOT NULL GROUP BY t1.ex_uuid")}
    for (uid, sym), src_q in srcs.items():
        g3_n += 1
        if dep_sym.get(uid) not in (None, sym) and multi.get(uid, 0) > 1:
            g3_bad.append(("symbol_mismatch_multi", uid, sym, dep_sym.get(uid)))
            continue
        dst = dep_amt.get(uid)
        if dst is None:
            g3_bad.append(("no_dep_posting", uid, sym))
        elif dst > src_q * Decimal("1.0001"):
            g3_bad.append(("dst>src", uid, sym, str(src_q), str(dst)))
        elif src_q - dst > src_q * Decimal("0.01"):
            g3_bad.append(("gap>1%", uid, sym, str(src_q), str(dst)))
    g["G3_linked_deposits"] = {"total": g3_n, "violations": len(g3_bad), "sample": g3_bad[:10]}
    try:
        bal = json.load(open(os.path.join(common.STATE_DIR, "upbit_balances.json"), encoding="utf-8"))
    except Exception:
        bal = {}
    actual = {}
    for a9 in bal.get("accounts") or []:
        cur = str(a9.get("currency") or "").upper()
        if cur and cur != "KRW":
            try:
                actual[cur] = Decimal(str(a9.get("balance") or 0)) + Decimal(str(a9.get("locked") or 0))
            except Exception:
                pass
    anchored = {r[0] for r in b.execute("SELECT DISTINCT upper(a.symbol) FROM postings p JOIN assets a"
                                        " ON a.asset_id=p.asset_id WHERE p.source_ns='upbit:recon'")}
    ledger = {}
    raw_led = {}
    for r in b.execute("SELECT upper(a.symbol), a.decimals, p.qty_base FROM postings p"
                       " JOIN assets a ON a.asset_id=p.asset_id WHERE p.location='exchange:upbit'"):
        d = int(r[1]) if r[1] is not None else 8
        raw_led[(r[0], d)] = raw_led.get((r[0], d), 0) + int(r[2])
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        for (sym, d), v in raw_led.items():
            ledger[sym] = ledger.get(sym, Decimal(0)) + Decimal(v) / (Decimal(10) ** d)
    ok, bad9, unanch = 0, [], []
    TOL_U = Decimal("0.000001")
    for sym, v in sorted(ledger.items()):
        tgt = actual.get(sym, Decimal(0))
        if sym in anchored:
            if abs(v - tgt) <= TOL_U:
                ok += 1
            else:
                bad9.append((sym, str(v), str(tgt)))
        elif abs(v - tgt) > TOL_U:
            unanch.append((sym, str(v), str(tgt)))
    g["G1u_upbit_vs_balance"] = {"anchored_ok": ok, "anchored_mismatch": len(bad9), "mismatch_sample": bad9[:10],
                                 "unanchored_diff": len(unanch), "unanchored_sample": unanch[:15],
                                 "balance_ts": bal.get("ts")}
    return g


def cost_lost(a, b, top: int = 10) -> dict:
    lost = {}
    nul = {(r[0], r[1], r[2], int(r[3])): (r[4], r[5]) for r in b.execute(
        "SELECT source_kind, source_ns, source_id, leg_seq, leg_kind, event FROM postings WHERE cost_usd IS NULL")}
    if nul:
        for r in a.execute("SELECT source_kind, source_ns, source_id, leg_seq, cost_usd, asset_id FROM postings WHERE cost_usd IS NOT NULL"):
            k = (r[0], r[1], r[2], int(r[3]))
            if k in nul:
                try:
                    cu = float(r[4])
                except (TypeError, ValueError):
                    cu = 0.0
                lost[k] = (cu, r[5], nul[k])
    rows = sorted(lost.items(), key=lambda kv: -abs(kv[1][0]))
    syms = {}
    for k, (cu, aid, lk) in rows[:top]:
        if aid not in syms:
            s9 = a.execute("SELECT symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
            syms[aid] = (s9[0] if s9 else None) or f"#{aid}"
    return {"n": len(lost), "usd": round(sum(abs(v[0]) for v in lost.values()), 2),
            "top": [{"key": list(k), "sym": syms.get(aid), "leg": lk[0], "event": lk[1], "cost_baseline": round(cu, 2)} for k, (cu, aid, lk) in rows[:top]]}


def carry_costs(baseline_db: str, conn) -> dict:
    base = _ro(baseline_db, immutable=True)
    try:
        bdec = {int(r[0]): r[1] for r in base.execute("SELECT asset_id, decimals FROM assets")}
        bmap = {(r[0], r[1], r[2], int(r[3])): r[4:] for r in base.execute(
            "SELECT source_kind, source_ns, source_id, leg_seq, asset_id, qty_base, leg_kind, event, cost_usd, cost_krw"
            " FROM postings WHERE cost_usd IS NOT NULL AND leg_kind != 'opening'")}
    finally:
        base.close()
    sdec = {int(r[0]): r[1] for r in conn.execute("SELECT asset_id, decimals FROM assets")}
    n = skip_dec = 0
    usd = 0.0
    for r in conn.execute("SELECT posting_id, source_kind, source_ns, source_id, leg_seq, asset_id, qty_base, leg_kind, event FROM postings"
                          " WHERE cost_usd IS NULL AND leg_kind != 'opening'").fetchall():
        b9 = bmap.get((r[1], r[2], r[3], int(r[4])))
        if not b9 or int(b9[0]) != int(r[5]) or str(b9[1]) != str(r[6]) or b9[2] != r[7] or b9[3] != r[8]:
            continue
        if bdec.get(int(r[5])) != sdec.get(int(r[5])):
            skip_dec += 1
            continue
        conn.execute("UPDATE postings SET cost_usd=?, cost_krw=? WHERE posting_id=?", (b9[4], b9[5], r[0]))
        n += 1
        try:
            usd += abs(float(b9[4]))
        except (TypeError, ValueError):
            pass
    conn.commit()
    return {"n": n, "usd": round(usd, 2), "skipped_decimals_changed": skip_dec}


def apply_dec_pending(conn, state_dir: str) -> dict:
    dec_pend = {}
    for k9, it9 in ((common.read_json(os.path.join(state_dir, "asset_decimals_issues.json"), {}) or {}).get("items") or {}).items():
        if isinstance(it9, dict) and it9.get("kind") == "pending" and isinstance(it9.get("seen"), int) and not isinstance(it9.get("seen"), bool):
            try:
                dec_pend[int(k9)] = int(it9["seen"])
            except (TypeError, ValueError):
                continue
    for aid9, dv9 in sorted(dec_pend.items()):
        conn.execute("UPDATE assets SET decimals=? WHERE asset_id=? AND decimals IS NULL", (dv9, aid9))
    conn.commit()
    return dec_pend


def dec_unresolved(conn, dec_pend: dict) -> list:
    return sorted(a9 for a9 in dec_pend
                  if (conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (a9,)).fetchone() or [0])[0] is None)


def _unv_all(fields: dict, rows: list, money) -> dict:
    u9 = ((fields or {}).get("_diag") or {}).get("unv_all")
    if isinstance(u9, dict) and u9.get("proceeds") is not None:
        return {"rows": int(u9.get("rows") or 0), "sum": round(float(u9["proceeds"]), 2), "src": "diag"}
    return {"rows": len(rows), "sum": round(sum(money(p.get("onchain")) for p in rows), 2), "src": "pendings"}


def keep_upbit_anchor_names(baseline_db: str, conn) -> int:
    base = _ro(baseline_db, immutable=True)
    try:
        bl = {}
        for r in base.execute("SELECT source_id, event_ts, asset_id, qty_base, leg_kind, event FROM postings"
                              " WHERE source_kind='exchange' AND source_ns='upbit:recon' AND location='exchange:upbit'"):
            sym9 = str(r[0]).split(":")[1] if str(r[0]).count(":") >= 2 else ""
            bl.setdefault((sym9, int(r[2])), []).append(r)
    finally:
        base.close()
    new = {}
    for r in conn.execute("SELECT posting_id, source_id, asset_id, qty_base, classifier_ver FROM postings"
                          " WHERE source_kind='exchange' AND source_ns='upbit:recon' AND location='exchange:upbit'").fetchall():
        sym9 = str(r[1]).split(":")[1] if str(r[1]).count(":") >= 2 else ""
        new.setdefault((sym9, int(r[2])), []).append(r)
    kept = 0
    for k, rows in new.items():
        old = bl.get(k)
        if not old or sum(int(x[3]) for x in rows) != sum(int(x[3]) for x in old):
            continue
        if sorted(str(x[1]) for x in rows) == sorted(str(x[0]) for x in old):
            continue
        cv9 = rows[0][4]
        for x in rows:
            conn.execute("DELETE FROM postings WHERE posting_id=?", (x[0],))
        for o in old:
            conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                         " cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange', 'upbit:recon', ?, 0, ?, ?, 'exchange:upbit', ?, NULL, NULL,"
                         " ?, ?, ?)", (o[0], o[1], o[2], o[3], o[4], o[5], cv9))
        kept += 1
    conn.commit()
    return kept


def compare(live_db: str, shadow_db: str, t0: int = 0, iso=None) -> dict:
    a, b = _ro(live_db, immutable=True), _ro(shadow_db)
    try:
        rep = {"postings": {}, "tx_class": {}, "positions": {}, "cost_null": {}, "events": {}}
        rep["postings"]["live"] = a.execute("SELECT count(*) FROM postings").fetchone()[0]
        rep["postings"]["shadow"] = b.execute("SELECT count(*) FROM postings").fetchone()[0]
        sa, sb = sums_by_asset_loc(a), sums_by_asset_loc(b)
        diffs = []
        for k in sorted(set(sa) | set(sb)):
            va, vb = sa.get(k, 0), sb.get(k, 0)
            if va != vb:
                dec = (b.execute("SELECT decimals FROM assets WHERE asset_id=?", (k[0],)).fetchone()
                       or a.execute("SELECT decimals FROM assets WHERE asset_id=?", (k[0],)).fetchone())
                d = int(dec[0]) if dec and dec[0] is not None else 18
                diffs.append({"asset": asset_label(b, k[0], a), "asset_id": k[0], "location": k[1],
                              "live": str(Decimal(va) / Decimal(10) ** d),
                              "shadow": str(Decimal(vb) / Decimal(10) ** d),
                              "delta": str(Decimal(vb - va) / Decimal(10) ** d)})
        rep["postings"]["pair_diffs"] = diffs
        def symsum(conn):
            raw = {}
            for r in conn.execute("SELECT a.asset_id, upper(a.symbol), p.location, a.decimals, p.qty_base"
                                  " FROM postings p JOIN assets a ON a.asset_id=p.asset_id"):
                d = int(r[3]) if r[3] is not None else 18
                k = (r[1] or "?", r[2], d)
                raw[k] = raw.get(k, 0) + int(r[4])
            out = {}
            with localcontext() as ctx:
                ctx.prec = DECIMAL_PREC
                for (sym, loc, d), v in raw.items():
                    out[(sym, loc)] = out.get((sym, loc), Decimal(0)) + Decimal(v) / (Decimal(10) ** d)
            return out
        ssa, ssb = symsum(a), symsum(b)
        tol = Decimal("0.00000001")
        rep["G1_symbol_loc"] = [{"sym": k[0], "loc": k[1], "live": str(ssa.get(k, Decimal(0))),
                                 "shadow": str(ssb.get(k, Decimal(0))),
                                 "delta": str(ssb.get(k, Decimal(0)) - ssa.get(k, Decimal(0)))}
                                for k in sorted(set(ssa) | set(ssb))
                                if abs(ssb.get(k, Decimal(0)) - ssa.get(k, Decimal(0))) > tol]
        rep["postings"]["pairs_live"] = len(sa)
        rep["postings"]["pairs_shadow"] = len(sb)
        pa, pb = positions_map(a), positions_map(b)
        pdiff = [{"group_id": k[0], "location": k[1], "live": str(pa.get(k, 0)), "shadow": str(pb.get(k, 0))}
                 for k in sorted(set(pa) | set(pb)) if pa.get(k, Decimal(0)) != pb.get(k, Decimal(0))]
        rep["positions"] = {"live": len(pa), "shadow": len(pb), "diffs": pdiff}
        ev_a = dict(a.execute("SELECT event, count(*) FROM tx_class GROUP BY event").fetchall())
        ev_b = dict(b.execute("SELECT event, count(*) FROM tx_class GROUP BY event").fetchall())
        rep["tx_class"] = {"live": ev_a, "shadow": ev_b,
                           "diff": {k: (ev_a.get(k, 0), ev_b.get(k, 0))
                                    for k in sorted(set(ev_a) | set(ev_b)) if ev_a.get(k, 0) != ev_b.get(k, 0)}}
        pe_a = dict(a.execute("SELECT event, count(*) FROM postings GROUP BY event").fetchall())
        pe_b = dict(b.execute("SELECT event, count(*) FROM postings GROUP BY event").fetchall())
        rep["events"] = {k: (pe_a.get(k, 0), pe_b.get(k, 0))
                         for k in sorted(set(pe_a) | set(pe_b)) if pe_a.get(k, 0) != pe_b.get(k, 0)}
        for name, c in (("live", a), ("shadow", b)):
            rep["cost_null"][name] = c.execute(
                "SELECT count(*) FROM postings WHERE cost_usd IS NULL"
                " AND leg_kind IN ('acq','disp','gas')").fetchone()[0]
        rep["cost_lost"] = cost_lost(a, b)
        tr_a = dict(a.execute("SELECT state, count(*) FROM transfers GROUP BY state").fetchall())
        tr_b = dict(b.execute("SELECT state, count(*) FROM transfers GROUP BY state").fetchall())
        rep["transfers"] = {"live": tr_a, "shadow": tr_b}
        rep["gates"] = gates(b, t0, iso)
        return rep
    finally:
        a.close()
        b.close()


OBS_GATE_TOL_USD = 1.0


def _obs_ledger_index(conn, exclude=None):
    arrived = {}
    if exclude and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='raw_txs'").fetchone():
        for ch9, h9 in exclude:
            r9 = conn.execute("SELECT ingested_at FROM raw_txs WHERE chain=? AND txhash=?", (ch9, h9)).fetchone()
            if r9 and r9[0] is not None:
                arrived[(ch9, h9)] = int(r9[0])
    raw = {}
    for aid, loc, ts, qb, sk, ns, sid in conn.execute(
            "SELECT asset_id, location, event_ts, qty_base, source_kind, source_ns, source_id FROM postings WHERE location LIKE 'wallet:%'"):
        if loc.count(":") != 2:
            continue
        if exclude and sk == "chain_tx" and (ns, sid) in exclude:
            t_arr = arrived.get((ns, sid))
            if t_arr is None:
                continue
            ts = max(int(ts), t_arr)
        raw.setdefault((aid, loc), []).append((int(ts), int(qb)))
    out = {}
    for k, lst in raw.items():
        lst.sort(key=lambda x: x[0])
        ts9, cum9, s9 = [], [], 0
        for t, q in lst:
            s9 += q
            ts9.append(t)
            cum9.append(s9)
        out[k] = (ts9, cum9)
    return out


def _obs_led_at(idx, key, T) -> int:
    import bisect
    v = idx.get(key)
    if not v:
        return 0
    i = bisect.bisect_right(v[0], int(T))
    return v[1][i - 1] if i else 0


def _obs_price_fn(assets, spot_path):
    try:
        sp = json.load(open(spot_path, encoding="utf-8")) if spot_path and os.path.exists(spot_path) else {}
    except (OSError, ValueError):
        sp = {}
    usd, dex, guarded = sp.get("usd") or {}, sp.get("dex_usd") or {}, set((sp.get("guarded") or {}).keys())
    try:
        import pricing as _pr
        stab = {(ch, str(ca).lower()) for ch, m in (getattr(_pr, "STABLE_CAS", {}) or {}).items() for ca in m}
        stab |= {("sol", m) for m in (getattr(_pr, "STABLE_MINTS", {}) or {})}
    except Exception:
        stab = set()

    def px(aid):
        a = assets.get(aid)
        if not a:
            return None
        kind, chain, addr, sym = a[0], a[1], a[2], a[3]
        if kind == "native":
            v = usd.get(str(sym or "").upper())
            return float(v) if v else None
        if kind != "token" or not addr:
            return None
        ca = addr if chain == "sol" else str(addr).lower()
        if (chain, ca) in stab:
            return 1.0
        k9 = f"{chain}:{ca}"
        if k9 in guarded:
            return None
        v = dex.get(k9)
        return float(v) if v else None
    return px


def obs_replay_gate(live_db: str, shadow_db: str, spot_path: str, tol_usd: float = OBS_GATE_TOL_USD,
                    live_immutable: bool = True) -> dict:
    a = _ro(live_db, immutable=live_immutable)
    b = _ro(shadow_db)
    try:
        assets = {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in b.execute(
            "SELECT asset_id, kind, chain, address, symbol, decimals FROM assets")}
        for r in a.execute("SELECT asset_id, kind, chain, address, symbol, decimals FROM assets"):
            assets.setdefault(r[0], (r[1], r[2], r[3], r[4], r[5]))
        byaddr = {}
        for aid, (kind, chain, addr, _sym, _dec) in sorted(assets.items()):
            if kind == "native":
                byaddr.setdefault((chain, "native:none"), aid)
            elif kind == "token" and addr:
                byaddr.setdefault((chain, "token:" + (addr if chain == "sol" else str(addr).lower())), aid)
        pend = set()
        for (k9,) in a.execute("SELECT k FROM meta WHERE k LIKE 'ext\\_prewindow\\_tx:%' ESCAPE '\\'").fetchall():
            try:
                _, ch9, h9 = k9.split(":", 2)
            except ValueError:
                continue
            pend.add((ch9, h9))
        ia, ib = _obs_ledger_index(a, exclude=pend), _obs_ledger_index(b)
        cells_by_loc = {}
        for k in set(ia) | set(ib):
            cells_by_loc.setdefault(k[1], set()).add(k[0])
        obs_rows = b.execute("SELECT obs_id, kind, payload, observed_at FROM raw_observations"
                             " WHERE (kind='opening_balance' AND obs_id LIKE 'recon:%') OR kind='rebalance'").fetchall()
    finally:
        a.close()
        b.close()
    px = _obs_price_fn(assets, spot_path)
    items = []
    cnt = {"no_asset": 0, "bsc_unlisted_skipped": 0, "bad_payload": 0, "scope_skipped": 0, "unobs_skipped": 0, "unqueried_skipped": 0}
    for oid, kind, pl, T in obs_rows:
        try:
            d = json.loads(pl)
        except (TypeError, ValueError):
            cnt["bad_payload"] += 1
            continue
        if kind == "rebalance":
            for x in d if isinstance(d, list) else []:
                try:
                    loc9, aid9, real9 = str(x["loc"]), int(x["aid"]), int(x["real"])
                except (KeyError, TypeError, ValueError):
                    cnt["bad_payload"] += 1
                    continue
                if loc9.startswith("wallet:") and loc9.count(":") == 2:
                    items.append((oid, int(T), loc9, aid9, real9, True))
            continue
        parts = oid.split(":")
        if len(parts) < 2 or ":stake:" in oid or not isinstance(d, dict):
            continue
        chain = parts[1]
        scope9 = d.get("_scope") if d.get("_scope") in ("token", "native") else None
        unobs9 = {str(x).lower() for x in d.get("_unobs")} if isinstance(d.get("_unobs"), list) else set()
        qq9 = {str(x).lower() for x in d.get("_q")} if isinstance(d.get("_q"), list) else None
        for w, wb in d.items():
            if not isinstance(wb, dict):
                continue
            wl = w if chain == "sol" else str(w).lower()
            loc9 = f"wallet:{chain}:{wl}"
            seen = set()
            for k, v in wb.items():
                kind9, _, addr9 = str(k).partition(":")
                kind9 = kind9.lower()
                kk = "native:none" if kind9 == "native" else f"{kind9}:{addr9 if chain == 'sol' else addr9.lower()}"
                aid9 = byaddr.get((chain, kk))
                try:
                    v9 = int(v)
                except (TypeError, ValueError):
                    cnt["bad_payload"] += 1
                    continue
                if aid9 is None:
                    cnt["no_asset"] += 1
                    continue
                seen.add(aid9)
                items.append((oid, int(T), loc9, aid9, v9, True))
            for aid9 in sorted(cells_by_loc.get(loc9, ())):
                if aid9 in seen:
                    continue
                if unobs9 and (assets.get(aid9) or ("?",))[0] == "token" \
                        and f"{str(w).lower()}:{str((assets.get(aid9) or (None, None, None))[2] or '').lower()}" in unobs9:
                    cnt["unobs_skipped"] += 1
                    continue
                if qq9 is not None and (assets.get(aid9) or ("?",))[0] == "token" \
                        and f"{str(w).lower()}:{str((assets.get(aid9) or (None, None, None))[2] or '').lower()}" not in qq9:
                    cnt["unqueried_skipped"] += 1
                    continue
                if scope9 and ((assets.get(aid9) or ("?",))[0] == "native") != (scope9 == "native"):
                    cnt["scope_skipped"] += 1
                    continue
                if chain == "bsc":
                    cnt["bsc_unlisted_skipped"] += 1
                    continue
                items.append((oid, int(T), loc9, aid9, 0, False))
    worse, improved, no_price, checked = [], 0, 0, 0
    for oid, T, loc9, aid9, v9, listed in items:
        la, lb = _obs_led_at(ia, (aid9, loc9), T), _obs_led_at(ib, (aid9, loc9), T)
        if la == lb:
            checked += 1
            continue
        p9 = px(aid9)
        if not p9:
            no_price += 1
            continue
        checked += 1
        a9 = assets.get(aid9) or ("?", "?", None, "?", 18)
        dec = int(a9[4]) if a9[4] is not None else 18
        with localcontext() as ctx:
            ctx.prec = DECIMAL_PREC
            sc = Decimal(10) ** dec
            dev_l, dev_s = Decimal(la - v9) / sc, Decimal(lb - v9) / sc
            d_usd = (abs(dev_s) - abs(dev_l)) * Decimal(str(p9))
        if d_usd >= Decimal(str(tol_usd)):
            worse.append({"obs": oid, "T": T, "loc": loc9, "asset_id": aid9, "sym": a9[3], "listed": listed,
                          "obs_qty": str(Decimal(v9) / sc), "dev_live": str(dev_l), "dev_shadow": str(dev_s),
                          "px": p9, "worse_usd": round(float(d_usd), 2)})
        elif d_usd <= -Decimal(str(tol_usd)):
            improved += 1
    worse.sort(key=lambda x: -x["worse_usd"])
    return {"ok": not worse, "tol_usd": tol_usd, "observations": len(obs_rows), "cells": len(items), "checked": checked,
            "no_price": no_price, "improved": improved, "live_pending_excluded": len(pend), "worse_n": len(worse), "worse": worse[:100],
            **cnt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shadow-dir", default=os.path.join(os.path.expanduser("~"), "tj_shadow_rebuild"),
                    help="라이브 state/저장소 밖이어야 한다(겹치면 중단)")
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--anchors", choices=("recompute", "verbatim"), default="recompute",
                    help="앵커 이월 방식: recompute(절대관측 역산, 기본) / verbatim(diff 그대로)")
    ap.add_argument("--from-baseline", default=None,
                    help="라이브 대신 이 shadow 디렉터리의 live_snapshot.db+json 을 입력으로(G5 결정성 검증)")
    ap.add_argument("--price-online-lp", action="store_true",
                    help="LP 레그·업비트 비KRW 체결만 네트워크로 캔들 조회(나머지는 오프라인 캐시) — fix-c 컷오버용")
    ap.add_argument("--allow-locked", action="store_true",
                    help="업비트 재대사 미완 사유가 정확히 'locked'(미체결 주문 통화)이고 미대사 심볼 ⊆ locked 집합이면 완료로 인정 —"
                         " recon_done_upbit 은 비워 두고 라이브 core 가 미체결 주문 동봉 스냅샷으로 완성(cutover_c --allow-locked 와 같은 규약)")
    ap.add_argument("--web-compare", action="store_true",
                    help="shadow DB 위에서 web.StateBuilder 를 돌려 실현·미확인 총계를 라이브와 대조")
    args = ap.parse_args()

    input_db = (os.path.join(os.path.abspath(args.from_baseline), "live_snapshot.db")
                if args.from_baseline else LIVE_DB)
    if args.from_baseline and not os.path.exists(input_db):
        raise SystemExit(f"기준선 없음: {input_db}")
    ro = _ro(input_db, immutable=bool(args.from_baseline))
    n_raw = ro.execute("SELECT count(*) FROM raw_txs").fetchone()[0]
    n_anchor = ro.execute("SELECT count(*) FROM postings WHERE leg_kind='opening'").fetchone()[0]
    n_post = ro.execute("SELECT count(*) FROM postings").fetchone()[0]
    ro.close()
    print(f"{'기준선' if args.from_baseline else '라이브'}: raw_txs {n_raw} /"
          f" postings {n_post} / 앵커(opening) {n_anchor}")
    if args.dry_run:
        print("--dry-run: 종료 (아무것도 안 씀)")
        return

    t0 = time.time()
    shadow_dir = os.path.abspath(args.shadow_dir)
    if args.report and args.from_baseline and _paths_overlap(args.report, args.from_baseline):
        raise SystemExit("--report 가 입력 기준선 디렉터리와 겹친다 — 중단")
    if args.report and (_paths_overlap(args.report, LIVE_STATE) or _paths_overlap(args.report, ROOT)):
        raise SystemExit("--report 가 라이브 state/저장소 안을 가리킨다 — 중단")
    if args.report and os.path.realpath(args.report) in {
            os.path.realpath(os.path.join(shadow_dir, name + suffix))
            for name in ("ledger.db", "live_snapshot.db") for suffix in ("", "-wal", "-shm")}:
        raise SystemExit("--report 가 shadow DB/기준선과 겹친다 — 중단")
    if args.from_baseline:
        shadow_db, baseline_db = snapshot_from(os.path.abspath(args.from_baseline), shadow_dir)
    else:
        shadow_db, baseline_db = snapshot_live(shadow_dir)
    print(f"[0] 스냅샷 완료 → 작업 {shadow_db} / 기준선 {baseline_db} ({time.time() - t0:.1f}s)")

    _live_state = common.STATE_DIR
    common.rebase_state(shadow_dir, shadow_db)
    assert common.ACTIVITY_GATE_PATH.startswith(shadow_dir), "활동 게이트 경로가 shadow 밖"
    common.QUOTA_STATE_DIR = _live_state
    import nft as _nft9
    _nft9.BUDGET_PATH = os.path.join(_live_state, "nft_budget.json")
    import pricing
    _px_orig = {k: getattr(pricing.PxCache, k) for k in ("candle_usd", "fx_at", "maybe_save", "flush")}
    _px_mod_orig = {k: getattr(pricing, k) for k in ("_gj", "upbit_krw_markets", "upbit_spot_krw", "_fx_candle_krw_per_usdt")
                    if hasattr(pricing, k)}
    px_stats = offline_patch(pricing)
    import core as core_mod
    import db as dbm
    assert dbm

    cfg = common.load_config()
    bal_p = os.path.join(common.STATE_DIR, "upbit_balances.json")
    try:
        bal_ts = int((json.load(open(bal_p, encoding="utf-8")) or {}).get("ts") or 0)
    except Exception:
        bal_ts = 0
    real_time = core_mod.time.time
    real_sleep = core_mod.time.sleep
    core_mod.time.sleep = lambda *_a, **_k: None
    GEN_NOW = float(bal_ts + 1) if bal_ts else real_time()
    core_mod.time.time = lambda: GEN_NOW
    _nft9._now = real_time
    _nft9._SHARED.clear()
    _cb = _ro(baseline_db, immutable=True)
    _bv = _cb.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone(); _cb.close()
    _bv = int(_bv[0]) if _bv else 0
    if _bv not in (dbm.SCHEMA_VERSION - 1, dbm.SCHEMA_VERSION):
        raise SystemExit(f"★기준선 DB 세대 {_bv} — 허용 {dbm.SCHEMA_VERSION - 1}/{dbm.SCHEMA_VERSION} 만 (중단)★")
    _c0 = sqlite3.connect(shadow_db)
    _c0.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('schema_version', ?)", (str(dbm.SCHEMA_VERSION),))
    _c0.commit(); _c0.close()
    c = core_mod.Core(cfg)
    conn = c.conn
    if not c.lp_mgrs:
        raise SystemExit("★LP 관리자 목록 비어 있음(seed/lp_managers.json + state/seed_local) — 재구축 중단★")
    GEN_T0 = c._upbit_window_t0()
    _cb0 = _ro(baseline_db, immutable=True)
    _t0_live = _cb0.execute("SELECT min(event_ts) FROM postings WHERE source_ns IN ('upbit:deposit', 'upbit:withdraw')").fetchone()[0]
    _cb0.close()
    if _t0_live and c.recon_months > 0 and int(_t0_live) < GEN_T0:
        print(f"[0b] 업비트 기장 창 시작 {GEN_T0} → 기준선 최초 기장 {int(_t0_live)} 로 고정(재파생이 라이브 기장분을 잃지 않게)")
        GEN_T0 = int(_t0_live)
        c._upbit_window_t0 = (lambda t9=GEN_T0: t9)
    assert os.path.abspath(conn.execute("PRAGMA database_list").fetchone()[2]) == shadow_db, "shadow 아님"

    anchors = [tuple(r) for r in conn.execute(ANCHOR_SQL).fetchall()]
    print(f"[1] 앵커 보존 {len(anchors)}건 (legacy_exact_adjustment)")

    conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rebuild_incomplete', ?)",
                 (str(int(time.time())),))
    for t in DERIVED_TABLES:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    print("[2] 파생 삭제")
    dec_pend = apply_dec_pending(conn, common.STATE_DIR)
    if dec_pend:
        print(f"[2c] decimals 채움 대기 {len(dec_pend)}개 자산에 먼저 반영")

    _oc9 = c.outflow_sync_exchange_rows()
    conn.commit()
    if _oc9:
        print(f"[2b] 보낸 내역 거래소 입금 주소 판정 {len(_oc9)}건 반영")

    ok = err = 0
    errs = []
    rows = conn.execute("SELECT chain, txhash, snapshot FROM raw_txs"
                        " ORDER BY ingested_at, chain, txhash").fetchall()
    for r in rows:
        try:
            conn.execute("BEGIN")
            snap = json.loads(r["snapshot"])
            if r["chain"] == "sol" and snap.get("kind") == "sol_tx":
                c.apply_sol(snap)
            else:
                c.apply(r["chain"], r["txhash"], "", snap)
            conn.commit()
            ok += 1
        except Exception as e:
            conn.rollback()
            err += 1
            errs.append((r["chain"], r["txhash"], repr(e)[:120]))
    print(f"[3] 온체인 재파생 {ok} 성공 / {err} 실패 ({time.time() - t0:.1f}s)")

    now = int(time.time())
    m = 0
    for d in conn.execute("SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
                          " GROUP BY uuid HAVING revision = MAX(revision)"
                          " ORDER BY observed_at, uuid").fetchall():
        try:
            p = json.loads(d["payload"])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        if str(p.get("state") or "").upper() != "ACCEPTED":
            continue
        txid = str(p.get("txid") or "")
        if not txid:
            continue
        m += c._link_transfers(d["uuid"], txid, p.get("currency"), now)
    dep_n = 0
    for d in conn.execute("SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
                          " GROUP BY uuid HAVING revision = MAX(revision)"
                          " ORDER BY observed_at, uuid").fetchall():
        try:
            p = json.loads(d["payload"])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        dep_ts = c._iso_ts(p.get("done_at") or p.get("created_at")) or now
        if c._post_ex_deposit(d["uuid"], p, dep_ts):
            dep_n += 1
    wd_n = 0
    for d in conn.execute("SELECT uuid, payload FROM raw_ex WHERE kind='withdraw' AND exchange='upbit'"
                          " GROUP BY uuid HAVING revision = MAX(revision)"
                          " ORDER BY observed_at, uuid").fetchall():
        try:
            p = json.loads(d["payload"])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        if c._post_ex_withdraw(d["uuid"], p):
            wd_n += 1
    conn.commit()
    print(f"[4a] 업비트 입금 canonical 기장 {dep_n}건 (링크 매칭 {m}건) / [4b] 출금 기장 {wd_n}건")
    nf = 0
    for t in conn.execute("SELECT exchange, payload FROM raw_ex WHERE kind='trade'"
                          " AND exchange != 'upbit' ORDER BY observed_at, exchange, uuid, revision").fetchall():
        try:
            if c._post_exf_fill(t["exchange"], json.loads(t["payload"])):
                nf += 1
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
    for t in conn.execute("SELECT exchange, uuid, payload FROM raw_ex WHERE kind='withdraw'"
                          " AND exchange != 'upbit' GROUP BY exchange, uuid"
                          " HAVING revision = MAX(revision) ORDER BY observed_at, exchange, uuid").fetchall():
        try:
            d9 = json.loads(t["payload"])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        if str(d9.get("state") or "").upper() != "DONE":
            continue
        c._post_exf_withdraw(t["exchange"], t["uuid"], d9)
    for t in conn.execute("SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit'"
                          " AND exchange != 'upbit' GROUP BY exchange, uuid"
                          " HAVING revision = MAX(revision) ORDER BY observed_at, exchange, uuid").fetchall():
        try:
            d9 = json.loads(t["payload"])
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
        if str(d9.get("state") or "").upper() != "ACCEPTED":
            continue
        txid9 = str(d9.get("txid") or "")
        if txid9:
            c._link_transfers(t["uuid"], txid9, d9.get("currency"), now)
        c._post_exf_deposit_in(t["exchange"], t["uuid"], d9)
    conn.commit()
    orders = []
    for o in conn.execute("SELECT payload FROM raw_ex WHERE kind='order'"
                          " GROUP BY uuid HAVING revision = MAX(revision) ORDER BY observed_at, uuid").fetchall():
        try:
            orders.append(json.loads(o["payload"]))
        except json.JSONDecodeError as e9:
            raise SystemExit(f"★raw_ex 원본 JSON 손상({e9}) — 재파생·게이트 신뢰 불가, shadow 사용 금지★")
    if orders:
        c._consume_fills({"orders": orders})
        conn.commit()
    print(f"[4] 업비트 입금 대사 {m} / 해외 체결 {nf} / 업비트 주문 {len(orders)} ({time.time() - t0:.1f}s)")
    if err:
        conn.commit()
        conn.close()
        for e9 in errs[:20]:
            print("   재파생 실패:", e9)
        raise SystemExit(f"★재파생 실패 {err}건 — rebuild_incomplete 마커 유지, shadow 사용 금지★")

    core_mod.PRICE_BATCH = max(core_mod.PRICE_BATCH,
                               conn.execute("SELECT count(*) FROM postings").fetchone()[0])
    _cached_fx_at = c.px.fx_at

    def _offline_fx_scan(ts_ms):
        v = _cached_fx_at(ts_ms)
        return 0.0 if v is None else v
    c.px.fx_at = _offline_fx_scan
    passes = 0
    prev = None
    while passes < 400:
        c._last_price_pass = 0.0
        c.price_pass()
        passes += 1
        left = conn.execute("SELECT count(*) FROM postings WHERE cost_usd IS NULL"
                            " AND (leg_kind='gas' OR (event='SWAP' AND leg_kind IN ('disp','acq'))"
                            "      OR (event LIKE 'LP\\_%' ESCAPE '\\' AND leg_kind IN ('disp','acq')))").fetchone()[0]
        if left == prev:
            break
        prev = left
    conn.commit()
    print(f"[5] 가격패스 {passes}회 → 미산정 잔여 {prev} (캐시 hit {px_stats['candle_hit']}"
          f"/miss {px_stats['candle_miss']}, fx hit {px_stats['fx_hit']}/miss {px_stats['fx_miss']})")
    if args.price_online_lp:
        fixed_time9, fixed_sleep9 = core_mod.time.time, core_mod.time.sleep
        core_mod.time.time = real_time
        core_mod.time.sleep = real_sleep
        for k9, f9 in _px_orig.items():
            setattr(pricing.PxCache, k9, f9)
        for k9, f9 in _px_mod_orig.items():
            setattr(pricing, k9, f9)
        if "fx_at" in c.px.__dict__:
            del c.px.__dict__["fx_at"]
        n_lp9 = 0
        for r9 in conn.execute("SELECT DISTINCT source_ns, source_id FROM postings WHERE source_kind='chain_tx'"
                               " AND event LIKE 'LP\\_%' ESCAPE '\\' AND leg_kind IN ('disp','acq') AND cost_usd IS NULL"
                               " ORDER BY source_ns, source_id").fetchall():
            c._price_tx(r9[0], r9[1])
            n_lp9 += 1
        n_uq9 = c._price_upbit_quote_fills(10 ** 6)
        conn.commit()
        try:
            fx_calls9 = int(os.environ.get("TJ_REBUILD_FX_CALLS") or 3000)
        except ValueError:
            fx_calls9 = 3000
        if fx_calls9 > 0:
            ms9 = [int(r9[0]) * 1000 for r9 in conn.execute(
                "SELECT DISTINCT (event_ts / 60) * 60 FROM postings WHERE cost_usd IS NOT NULL AND cost_krw IS NULL").fetchall()]
            if ms9:
                t9 = time.time()
                st9 = c.px.prefetch_fx(ms9, max_calls=fx_calls9, deadline=time.time() + 1800)
                print(f"[5b] 환율 선조회: 분 {len(ms9)} → {st9['calls']}콜 · {st9['filled']}분 채움 ({time.time() - t9:.0f}s)")
        c.px.flush()
        core_mod.time.time = fixed_time9
        core_mod.time.sleep = fixed_sleep9
        offline_patch(pricing)
        c.px.fx_at = _offline_fx_scan
        left9 = conn.execute("SELECT count(*) FROM postings WHERE cost_usd IS NULL AND event LIKE 'LP\\_%' ESCAPE '\\'"
                             " AND leg_kind IN ('disp','acq')").fetchone()[0]
        print(f"[5b] 온라인 가격: LP tx {n_lp9} · 업비트 비KRW 체결 {n_uq9} → LP 레그 미산정 잔여 {left9}(시세 없는 토큰)")
        prev9 = None
        for _i9 in range(400):
            c._last_price_pass = 0.0
            c.price_pass()
            n9 = conn.execute("SELECT count(*) FROM postings WHERE cost_usd IS NULL"
                              " AND (leg_kind='gas' OR (event='SWAP' AND leg_kind IN ('disp','acq'))"
                              "      OR (event LIKE 'LP\\_%' ESCAPE '\\' AND leg_kind IN ('disp','acq')))").fetchone()[0]
            if n9 == prev9:
                break
            prev9 = n9
        n_krw9 = 0
        for pid9, ets9, cu9 in conn.execute("SELECT posting_id, event_ts, cost_usd FROM postings"
                                            " WHERE cost_usd IS NOT NULL AND cost_krw IS NULL").fetchall():
            fx9 = _cached_fx_at(int(ets9) * 1000)
            if fx9:
                conn.execute("UPDATE postings SET cost_krw=? WHERE posting_id=?", (repr(float(cu9) * fx9), pid9))
                n_krw9 += 1
        conn.commit()
        print(f"[5b] 오프라인 재수렴 → 미산정 {prev9} · cost_krw 캐시 보충 {n_krw9}행")

    carry9 = carry_costs(baseline_db, conn)
    print(f"[5c] 기준선 원가 이월 {carry9['n']}칸 (${carry9['usd']:,.2f}) · 자리수 바뀐 자산이라 건너뜀 {carry9['skipped_decimals_changed']}")

    obs = {r[0]: r[1] for r in conn.execute("SELECT obs_id, observed_at FROM raw_observations")}
    meta = {r[0]: int(r[1]) for r in conn.execute("SELECT k, v FROM meta WHERE k LIKE 'recon_done_%'")}
    if args.anchors == "verbatim":
        ins = 0
        for a in anchors:
            cur9 = conn.execute("INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
                                " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", a)
            if cur9.rowcount:
                c._bump_position(a[5], int(a[7]), a[6])
                ins += 1
        anc = {"mode": "verbatim", "total": ins}
    else:
        anc = recompute_anchors(baseline_db, conn, c, anchors, obs, meta)
        anc["mode"] = "recompute"
    conn.execute("DELETE FROM meta WHERE k='recon_done_upbit'")
    conn.commit()
    c._last_exrecon = 0.0
    before6 = conn.execute("SELECT count(*) FROM postings WHERE source_ns='upbit:recon'").fetchone()[0]
    c.exchange_recon_pass(drained={"ex"})
    core_mod.time.time = real_time
    core_mod.time.sleep = real_sleep
    kept6 = keep_upbit_anchor_names(baseline_db, conn)
    after6 = conn.execute("SELECT count(*) FROM postings WHERE source_ns='upbit:recon'").fetchone()[0]
    done6 = conn.execute("SELECT v FROM meta WHERE k='recon_done_upbit'").fetchone()
    try:
        bal9 = json.load(open(bal_p, encoding="utf-8")) or {}
    except Exception:
        bal9 = {}
    try:
        ost9 = json.load(open(os.path.join(common.STATE_DIR, "upbit_orders_state.json"), encoding="utf-8")) or {}
    except Exception:
        ost9 = {}
    locked9 = sorted({str(a9.get("currency") or "").upper() for a9 in (bal9.get("accounts") or [])
                      if str(a9.get("currency") or "").upper() not in ("", "KRW")
                      and float(a9.get("locked") or 0) > 0})
    if done6:
        reason6 = "none"
    elif not ost9.get("complete"):
        reason6 = "orders_incomplete"
    elif GEN_NOW - float(ost9.get("backfilled_until") or 0) > 8 * 86400:
        reason6 = "orders_stale"
    elif GEN_NOW - (bal9.get("ts") or 0) > 600:
        reason6 = "balance_stale"
    elif locked9:
        reason6 = "locked"
    else:
        reason6 = "unknown"
    anc["upbit_reanchor"] = {"anchors": after6 - before6, "marker": bool(done6), "reason": reason6, "kept_original": kept6,
                             "locked": locked9, "gen_now": GEN_NOW, "gen_t0": GEN_T0}
    diagnostic_only = args.anchors == "verbatim"
    locked_ok = bool(args.allow_locked and not done6 and reason6 == "locked")
    incomplete = ((not done6) and not locked_ok) or diagnostic_only
    if incomplete:
        print("★[6b] 업비트 재대사 미완(잔고 스냅샷 신선도/주문 스윕/미체결 통화) — rebuild_incomplete 유지, "
              "이 shadow 는 컷오버 후보 아님(진단 리포트만 생성)★")
    conn.commit()
    c.px.flush = lambda: None
    conn.close()
    print(f"[6] 앵커 {anc['mode']}: " + ", ".join(f"{k}={v}" for k, v in anc.items() if k != "rows")
          + f" ({time.time() - t0:.1f}s)")

    rep = compare(baseline_db, shadow_db, GEN_T0, core_mod.Core._iso_ts)
    _cu = _ro(shadow_db)
    try:
        rep["decimals_unresolved"] = dec_unresolved(_cu, dec_pend)
    finally:
        _cu.close()
    rep["anchors"] = anc
    try:
        rep["G_obs_replay"] = obs_replay_gate(baseline_db, shadow_db, os.path.join(shadow_dir, "spot.json"))
    except Exception as e9:
        rep["G_obs_replay"] = {"ok": False, "error": repr(e9)[:300], "worse_n": 0, "worse": []}
    _og = rep["G_obs_replay"]
    print(f"[7b] G_obs_replay: 관측 칸 {_og.get('cells', '?')} · 판정 {_og.get('checked', '?')} · 가격 없음 제외 {_og.get('no_price', '?')}"
          f" · BSC 미등재 제외 {_og.get('bsc_unlisted_skipped', '?')} · 나아짐 {_og.get('improved', '?')} · ★나빠짐 {_og.get('worse_n', '?')}★"
          + (f" · 오류 {_og['error']}" if _og.get("error") else ""))
    if locked_ok:
        un9 = {x[0] for x in (rep["gates"].get("G1u_upbit_vs_balance") or {}).get("unanchored_sample") or []}
        n_un9 = (rep["gates"].get("G1u_upbit_vs_balance") or {}).get("unanchored_diff", 0)
        if n_un9 > len(un9) or not un9 <= set(locked9):
            incomplete = True
            print(f"★--allow-locked 거부: 미대사 심볼 {sorted(un9)} ⊄ locked {locked9} (또는 표본 초과 {n_un9})★")
        else:
            print(f"[6b] --allow-locked: 미대사 {sorted(un9)} ⊆ locked — recon_done_upbit 미설정으로 완료 처리(라이브 core 가 완성)")
    rep["meta"] = {"incomplete": incomplete,
                   "took_s": round(time.time() - t0, 1), "apply_ok": ok, "apply_err": err,
                   "apply_errors": errs[:50], "price_passes": passes, "price_left": prev,
                   "px": px_stats, "anchors": len(anchors), "shadow_db": shadow_db,
                   "baseline_db": baseline_db}
    web_error = False
    if args.web_compare:
        try:
            import web
            b = web.StateBuilder()
            conn2 = dbm.open_db(shadow_db, readonly=True)
            try:
                out = b._build(conn2)
            finally:
                conn2.close()
            f = out["fields"]
            unv = [p for p in f["pendings"] if p.get("kind") == "원가미상 매도 검토"]
            dg = f.get("_diag") or {}
            resid = (float(dg.get("ex_out_cost", 0)) - float(dg.get("ex_dep_inh_cost", 0))
                     - float(dg.get("ex_dep_fee_resid_cost", 0)) - float(dg.get("ex_transit_unused_cost", 0)))
            coins = f.get("coins") or []
            unloc = [c.get("sym") for c in coins if (c.get("qty") or 0) > 0
                     and sum((x.get("qty") or 0) for x in (c.get("locs") or [])) < (c.get("qty") or 0) * 0.999]
            rep["web_shadow"] = {"realized_total": round(sum(f["realizedByDate"].values()), 2),
                                 "unverified_rows": len(unv), "positions": len(f["positions"]),
                                 "coins": len(coins), "unlocated": len(unloc),
                                 "risk_rows": len([p for p in f["pendings"] if p.get("kind") == "스팸·에어드랍 의심"]),
                                 "diag": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in dg.items()},
                                 "cost_conservation_residual": round(resid, 4)}
            import re as _re
            connb = _ro(baseline_db, immutable=True)
            connb.row_factory = sqlite3.Row
            try:
                bb = web.StateBuilder()
                bb.skip_gen_check = True
                fb = bb._build(connb)["fields"]
            finally:
                connb.close()
            def _val(ff):
                o = {}
                for c9 in (ff.get("coins") or []) + (ff.get("stables") or []):
                    o[c9.get("sym")] = o.get(c9.get("sym"), 0.0) + (c9.get("qty") or 0) * (c9.get("price") or 0)
                return o
            vb, vs = _val(fb), _val(f)
            vdiff = sorted(((sy, round(vb.get(sy, 0)), round(vs.get(sy, 0))) for sy in set(vb) | set(vs)
                            if abs(vb.get(sy, 0) - vs.get(sy, 0)) > max(50.0, 0.01 * max(vb.get(sy, 0), vs.get(sy, 0)))),
                           key=lambda x: -abs(x[1] - x[2]))
            def _money(sx):
                mm = _re.search(r"정산 \$([0-9,\.]+)", sx or "")
                return float(mm.group(1).replace(",", "")) if mm else 0.0
            unv_b = [p for p in fb["pendings"] if p.get("kind") == "원가미상 매도 검토"]
            def _qset(builder, ff):
                q = getattr(builder, "_risk_quarantined", None)
                if isinstance(q, (set, dict, list, frozenset)):
                    return {str(x) for x in q}
                return {p.get("sym") for p in ff["pendings"] if p.get("kind") == "스팸·에어드랍 의심"}
            risk_b, risk_s = _qset(bb, fb), _qset(b, f)
            rep["G4_vs_baseline"] = {
                "realized_baseline": round(sum(fb["realizedByDate"].values()), 2),
                "unverified_baseline": _unv_all(fb, unv_b, _money),
                "unverified_shadow": _unv_all(f, unv, _money),
                "coins_baseline": len(fb.get("coins") or []), "stables_value_baseline": round(sum((c9.get("qty") or 0) * (c9.get("price") or 0) for c9 in fb.get("stables") or []), 2),
                "stables_value_shadow": round(sum((c9.get("qty") or 0) * (c9.get("price") or 0) for c9 in f.get("stables") or []), 2),
                "value_diffs_n": len(vdiff), "value_diffs": vdiff[:20],
                "value_diff_max_abs": max([abs(x[1] - x[2]) for x in vdiff] or [0]),
                "risk_set_equal": risk_b == risk_s, "risk_only_baseline": sorted(risk_b - risk_s)[:10],
                "risk_only_shadow": sorted(risk_s - risk_b)[:10]}

            def _by_month(rbd):
                o = {}
                for k9, v9 in (rbd or {}).items():
                    m9 = str(k9)[:7] if len(str(k9)) >= 10 else "?"
                    o[m9] = round(o.get(m9, 0.0) + float(v9 or 0), 2)
                return o
            rep["G4_vs_baseline"]["realized_by_month_baseline"] = _by_month(fb.get("realizedByDate"))
            rep["G4_vs_baseline"]["realized_by_month_shadow"] = _by_month(f.get("realizedByDate"))
        except Exception as e:
            web_error = True
            rep["web_shadow"] = {"error": repr(e)[:300]}
    rep["meta"]["web_error"] = web_error
    path = args.report or os.path.join(shadow_dir, "rebuild2_report.json")
    _write_private_json(path, rep)
    pd = rep["postings"]["pair_diffs"]
    print(f"[7] 비교: postings {rep['postings']['live']}→{rep['postings']['shadow']} /"
          f" (asset,location) 쌍 차이 {len(pd)}건 / positions 차이 {len(rep['positions']['diffs'])}건 /"
          f" tx_class 차이 {rep['tx_class']['diff']} / cost NULL {rep['cost_null']}")
    for d in pd[:15]:
        print("   ", d)
    print("리포트:", path)
    if web_error:
        print("★web 리플레이 실패 — shadow 사용 금지★")
        raise SystemExit(3)
    if not _og.get("ok"):
        for w9 in _og.get("worse", [])[:30]:
            print(f"   관측 재현 악화: {w9['obs']} {w9['loc']} {w9['sym']}#{w9['asset_id']} 관측 {w9['obs_qty']}"
                  f" 편차 라이브 {w9['dev_live']} → shadow {w9['dev_shadow']} (≈${w9['worse_usd']:,.2f})")
        head9 = " · ".join(f"{w9['sym']}@{w9['loc'].split(':')[1]}:{w9['loc'].split(':')[2][:6]} +${w9['worse_usd']:,.0f}"
                           for w9 in _og.get("worse", [])[:4])
        print(f"★G_obs_replay 실패 — 관측 재현 악화 {_og.get('worse_n', 0)}칸, 컷오버 금지: {head9 or _og.get('error', '?')}★",
              file=sys.stderr, flush=True)
        raise SystemExit(4)
    if incomplete:
        raise SystemExit(2)
    finished = sqlite3.connect(shadow_db)
    try:
        finished.execute("DELETE FROM meta WHERE k='rebuild_incomplete'")
        finished.commit()
    finally:
        finished.close()


if __name__ == "__main__":
    main()

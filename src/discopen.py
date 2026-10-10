import json
import os
import sys
import threading
import time

import common
import spamguard

SID_TAG = ":disc:"
CAND = "negabs_cand:"
REQ_NAME = "negabs_request.json"
RECHK_REQ_NAME = "disc_open_request.json"
RES_NAME = "negabs_result.json"
SWAPLIKE = ("SWAP", "CONVERT")
STATE_ERR = ("missing trie node", "historical state", "header not found", "not supported", "pruned", "state not available",
             "state is not available", "unknown block", "state histories", "is not available", "old data not available",
             "required historical state", "block not found")
MAX_TRIES = 8
BACKOFF0 = 600
BACKOFF_MAX = 6 * 3600
WAIT_RETRY = 600
PASS_GAP = 60.0
MAX_JOBS = 2
DEFER_MAX = 900
FINAL = ("done", "none", "skip", "fail", "gone")
LANE_FAIL_WHY = "과거 블록 상태 없음(대체 조건 미충족)"


def _lanes_chain(chain: str) -> bool:
    try:
        if chain == "bsc":
            cur = common.read_json(os.path.join(common.STATE_DIR, "cursor_bsc.json"), {}) or {}
            return isinstance(cur.get("_live"), dict) or bool(cur.get("_lanes_seen"))
        cur = common.read_json(os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json"), {}) or {}
        return isinstance(cur, dict) and isinstance(cur.get("_handover"), dict)
    except (SystemExit, TypeError, ValueError):
        return False


def is_disc(sid) -> bool:
    s = str(sid or "")
    return s.startswith("recon:") and SID_TAG in s


def sid_of(chain: str, w: str, ca, blk: int) -> str:
    return f"recon:{chain}:{w}:disc:{(str(ca).lower() if ca else 'native')}@{int(blk)}"


def cand_key(chain: str, w: str, aid: int) -> str:
    return f"{CAND}{chain}:{w}:{int(aid)}"


def _ver(core) -> int:
    return int(getattr(sys.modules.get(type(core).__module__), "CLASSIFIER_VER", 3))


def _meta(conn, k):
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else None


def _jload(s, default=None):
    try:
        v = json.loads(s) if s else default
    except (TypeError, ValueError):
        return default
    return v


def cell_rows(conn, loc: str, aid: int) -> list:
    return [tuple(r) for r in conn.execute(
        "SELECT p.posting_id, p.source_kind, p.source_ns, p.source_id, p.event_ts, p.qty_base, r.block FROM postings p"
        " LEFT JOIN raw_txs r ON p.source_kind='chain_tx' AND r.chain=p.source_ns AND r.txhash=p.source_id"
        " WHERE p.location=? AND p.asset_id=?", (loc, int(aid))).fetchall()]


def cell_fp(rows) -> tuple:
    return (len(rows), max((int(r[0]) for r in rows), default=0), sum(int(r[5]) for r in rows))


def first_neg(rows):
    total = sum(int(r[5]) for r in rows)
    if total >= 0:
        return None
    by_ts = {}
    for r in rows:
        by_ts.setdefault(int(r[4]), []).append(r)
    run = 0
    for ts in sorted(by_ts):
        g = by_ts[ts]
        run += sum(int(r[5]) for r in g)
        if run < 0:
            negs = [r for r in g if r[1] == "chain_tx" and int(r[5]) < 0]
            if not negs:
                return "음수 원인이 체인 거래가 아님(대사 정정 등)"
            if any(r[6] is None for r in negs):
                return "블록 모르는 거래"
            r0 = min(negs, key=lambda r: (int(r[6]), str(r[3])))
            return {"tx": str(r0[3]), "block": int(r0[6]), "ts": ts, "total": total}
    return "음수 시점 못 찾음"


def posted_le(rows, blk: int, t_cut: int):
    s = 0
    for r in rows:
        if r[1] == "chain_tx":
            if r[6] is None:
                return None
            if int(r[6]) <= int(blk):
                s += int(r[5])
        elif int(r[4]) < int(t_cut):
            s += int(r[5])
    return s


def moved_after(rows, blk: int) -> bool:
    return any(r[1] == "chain_tx" and (r[6] is None or int(r[6]) > int(blk)) for r in rows)


def recon_done(conn, chain: str, w: str, native: bool) -> bool:
    wl = str(w).lower()
    if _meta(conn, f"wrecon_done:{chain}:{wl}") or (not native and _meta(conn, f"wrecon_tok:{chain}:{wl}")):
        return True
    if not _meta(conn, f"recon_done_{chain}"):
        return False
    r = conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:{chain}",)).fetchone()
    d = _jload(r[0] if r else None, {})
    return isinstance(d, dict) and any(str(k).lower() == wl and isinstance(v, dict) for k, v in d.items())


def lane_hold(chain: str, w: str, upto: int):
    sd = common.STATE_DIR
    upto = int(upto)
    try:
        if chain == "bsc":
            cur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {}) or {}
            fb = int(cur.get("from_block") or 0)
            if fb >= upto:
                return None
            if isinstance(cur.get("_live"), dict):
                return f"BSC 옛 기록 차선이 그 블록 아래를 아직 다 못 받음(블록 {fb} 까지 — 그 아래 안 받은 입금이 원장에 빠져 있을 수 있음 · 지나가면 다시)"
            return f"BSC 수집기가 그 블록까지 빈틈없이 아직 안 옴(커서 {fb})"
        cur = common.read_json(os.path.join(sd, f"cursor_evm_{chain}.json"), {}) or {}
    except (SystemExit, TypeError, ValueError):
        return "수집기 커서를 못 읽음"
    if not isinstance(cur, dict) or cur.get("_rpc_v") is None:
        return None
    wl = str(w).lower()
    j = cur.get("_bk:" + wl)
    if isinstance(j, dict):
        try:
            d9, t9 = int(j.get("done") or 0), int(j.get("to") or 0)
        except (TypeError, ValueError):
            d9, t9 = 0, 1
        if d9 < t9 and d9 < upto:
            return f"그 지갑 옛 기록 뒤 차선 진행 중(블록 {d9} 까지 — 그 블록 아래 아직 안 받은 거래가 있을 수 있음 · 차선이 지나가면 다시)"
    lc = cur.get(wl)
    if type(lc) is int and lc < upto:
        return f"수집기 라이브 차선이 그 블록까지 아직 안 옴(커서 {lc})"
    return None


def lane_busy(chain: str):
    try:
        if chain == "bsc":
            cur = common.read_json(os.path.join(common.STATE_DIR, "cursor_bsc.json"), {}) or {}
            return "BSC 옛 기록 차선 진행 중" if isinstance(cur.get("_live"), dict) else None
        cur = common.read_json(os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json"), {}) or {}
    except (SystemExit, TypeError, ValueError):
        return None
    if not isinstance(cur, dict) or cur.get("_rpc_v") is None:
        return None
    for k9, j9 in cur.items():
        if str(k9).startswith("_bk:") and isinstance(j9, dict) and j9.get("why") == "new":
            try:
                if int(j9.get("done") or 0) < int(j9.get("to") or 0):
                    return "새 지갑 옛 기록 뒤 차선 진행 중(동기화 도장 전 — 끝나면 다시)"
            except (TypeError, ValueError):
                continue
    return None


def prewin_pending(conn, chain: str, rows) -> bool:
    for r in rows:
        if r[1] == "chain_tx" and _meta(conn, f"ext_prewindow_tx:{chain}:{r[3]}"):
            return True
    return False


def observed_after(conn, chain: str, w: str, ca, blk: int, ts: int) -> str:
    wl = str(w).lower()
    kk = "native:none" if not ca else f"token:{str(ca).lower()}"
    oids = [f"recon:{chain}", f"recon:{chain}:{w}", f"recon:{chain}:{w}:native"]
    oids += [r[0] for r in conn.execute("SELECT obs_id FROM raw_observations WHERE obs_id >= ? AND obs_id < ? AND obs_id LIKE ?",
                                        (f"recon:{chain}:{w}:disc:", f"recon:{chain}:{w}:disc;", "%:disc:%")).fetchall()]
    for oid in oids:
        r = conn.execute("SELECT payload, observed_at FROM raw_observations WHERE obs_id=?", (oid,)).fetchone()
        d = _jload(r[0] if r else None, None)
        if not isinstance(d, dict):
            continue
        wb = next((v for k, v in d.items() if isinstance(v, dict) and str(k).lower() == wl), None)
        if wb is None:
            continue
        sc = d.get("_scope")
        if sc in ("token", "native") and (sc == "native") != (not ca):
            continue
        q = d.get("_q")
        un = d.get("_unobs")
        if ca:
            k9 = f"{wl}:{str(ca).lower()}"
            if isinstance(un, list) and k9 in {str(x).lower() for x in un}:
                continue
            if isinstance(q, list):
                if k9 not in {str(x).lower() for x in q}:
                    continue
            elif chain == "bsc" and kk not in {str(x).lower() for x in wb}:
                continue
        b = d.get("_block")
        after = (int(b) >= int(blk)) if isinstance(b, int) and not isinstance(b, bool) else int(r[1]) > int(ts)
        if after:
            return oid
    return ""


def asset_row(conn, aid: int):
    r = conn.execute("SELECT kind, chain, address, symbol, decimals, hidden, group_id FROM assets WHERE asset_id=?", (int(aid),)).fetchone()
    return tuple(r) if r else None


def asset_guard(conn, aid: int, prefs=None):
    a = asset_row(conn, aid)
    if not a:
        return "자산 없음"
    kind, chain, ca, sym, _dec, hidden, gid = a
    if kind not in ("native", "token"):
        return "체인 자산 아님"
    if hidden:
        return "숨김 자산"
    if kind == "token":
        if not ca:
            return "토큰 주소 없음"
        ca = str(ca).lower()
        if any(x and str(x[0]).lower() == ca for x in (common.NATIVE_MIRROR.get(chain), common.ZK_STACK.get(chain))):
            return "네이티브 거울·시스템 CA"
        if not spamguard.is_genuine(chain, ca) and (spamguard.impostor_of(sym) or spamguard.odd_symbol(sym)):
            return "사칭·혼용 심볼"
    ov = ((prefs or {}).get("risk_overrides") or {}).get(f"g{gid}") if gid is not None else None
    if ov == "spam":
        return "사용자 스팸 확정"
    return ""


def trusted_asset(conn, aid) -> bool:
    a = conn.execute("SELECT kind, chain, address FROM assets WHERE asset_id=?", (int(aid),)).fetchone() if aid is not None else None
    if not a:
        return False
    return a[0] == "native" or (a[0] == "token" and bool(a[2]) and spamguard.is_genuine(a[1], a[2]))


def signed_ok(conn, chain: str, txh: str, w: str, aid=None) -> bool:
    sg = conn.execute("SELECT COALESCE(json_extract(snapshot, '$.tx.from.hash'), json_extract(snapshot, '$.tx.from')),"
                      " json_extract(snapshot, '$.tx.fee.value'), json_extract(snapshot, '$.tx.raw_input')"
                      " FROM raw_txs WHERE chain=? AND txhash=? AND json_valid(snapshot)", (chain, txh)).fetchone()
    if sg and spamguard.signer_mine(sg[0], sg[1], sg[2], {str(w).lower()}):
        return True
    ev = conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?", (chain, txh)).fetchone()
    ev = str(ev[0] if ev else "")
    return (ev in SWAPLIKE or ev.startswith("LP_")) and trusted_asset(conn, aid)


def _multi_groups(conn) -> set:
    return {(int(g), c) for g, c in conn.execute("SELECT group_id, chain FROM assets WHERE group_id IS NOT NULL AND chain IS NOT NULL"
                                                 " GROUP BY group_id, chain HAVING count(*) > 1").fetchall()}


def cell_negative(conn, chain: str, loc: str, aid: int, gid=None) -> bool:
    if gid is not None:
        n = conn.execute("SELECT count(*) FROM assets WHERE group_id=? AND chain=?", (int(gid), chain)).fetchone()[0]
        if n == 1:
            r = conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (int(gid), loc)).fetchone()
            try:
                return r is not None and str(r[0]).strip().startswith("-") and float(r[0]) < 0
            except (TypeError, ValueError):
                pass
    return sum(int(r[0]) for r in conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (loc, int(aid))).fetchall()) < 0


def neg_cells(conn, chains) -> list:
    from decimal import Decimal, InvalidOperation
    out = []
    multi = _multi_groups(conn)
    for gid, loc, q in conn.execute("SELECT group_id, location, qty_norm FROM positions WHERE location LIKE 'wallet:%'").fetchall():
        p = str(loc).split(":")
        if len(p) != 3 or p[1] not in chains:
            continue
        try:
            if Decimal(str(q)) >= 0 and (int(gid), p[1]) not in multi:
                continue
        except (InvalidOperation, ValueError):
            continue
        for (aid,) in conn.execute("SELECT asset_id FROM assets WHERE group_id=? AND chain=?", (gid, p[1])).fetchall():
            s = sum(int(r[0]) for r in conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (loc, aid)).fetchall())
            if s < 0:
                out.append((p[1], p[2], int(aid)))
    return out


def plan_cell(conn, chain: str, w: str, aid: int, prefs=None, my=None) -> dict:
    loc = f"wallet:{chain}:{w}"
    why = asset_guard(conn, aid, prefs)
    if why:
        return {"st": "skip", "why": why}
    a = asset_row(conn, aid)
    native = a[0] == "native"
    if my is not None and str(w).lower() not in my:
        return {"st": "skip", "why": "등록 지갑 아님"}
    rows = cell_rows(conn, loc, aid)
    fn = first_neg(rows)
    if fn is None:
        return {"st": "gone", "why": "음수 아님"}
    if prewin_pending(conn, chain, rows):
        return {"st": "wait", "why": "재계산 대기(늦게 온 옛 거래 — 자동 재구축이 고침)"}
    if isinstance(fn, str):
        return {"st": "skip" if "체인 거래가 아님" in fn else "wait", "why": fn}
    if not recon_done(conn, chain, w, native):
        return {"st": "wait", "why": "그 지갑 기초 잔고 대사 미완료"}
    hold9 = lane_hold(chain, w, int(fn["block"]) - 1)
    if hold9:
        return {"st": "wait", "why": hold9}
    oa = observed_after(conn, chain, w, None if native else a[2], fn["block"], fn["ts"])
    if oa:
        return {"st": "skip", "why": ("발견 시점" if SID_TAG in oa else "기초 잔고 대사") + " 관측이 이 거래 뒤 잔고를 이미 봄 — 옛 보유 누락 아님(확인 필요)"}
    if not signed_ok(conn, chain, fn["tx"], w, aid):
        return {"st": "skip", "why": "내가 서명하지 않은 유출(주소 오염 가짜 전송 의심)"}
    return {"st": "go", "tx": fn["tx"], "block": fn["block"], "ts": fn["ts"], "total": fn["total"], "ca": None if native else str(a[2]).lower(),
            "native": native, "loc": loc, "rows": rows, "fp": cell_fp(rows), "sym": a[3], "dec": a[4]}


def _state_err(e) -> bool:
    s = str(e).lower()
    return any(x in s for x in STATE_ERR)


def fetch_at(urls: list, w: str, ca, blk: int, tries: int = 2) -> tuple:
    import recon
    bh = hex(int(blk))
    if ca:
        rd = recon._rpc_any(urls, "eth_call", [{"to": ca, "data": recon._SEL_BAL + str(w).lower().replace("0x", "").rjust(64, "0")}, bh], tries=tries)
        if not isinstance(rd, str) or not rd.startswith("0x") or len(rd) != 66:
            raise ValueError(f"balanceOf 응답 형식(관측 불가): {str(rd)[:20]}")
        bal = int(rd, 16)
    else:
        bal = recon._rpc_any(urls, "eth_getBalance", [str(w).lower(), bh], check=recon._hex_int, tries=tries)

    def _blk(r):
        if not isinstance(r, dict) or recon._hex_int(r.get("number")) != int(blk):
            raise ValueError("eth_getBlockByNumber 응답 블록 불일치")
        return recon._hex_int(r.get("timestamp"))
    bts = recon._rpc_any(urls, "eth_getBlockByNumber", [bh, False], check=_blk, tries=tries)
    return int(bal), int(bts)


def write_anchor(core, chain: str, w: str, aid: int, ca, diff: int, obs_block: int, obs_ts: int, at_ts: int, bal: int,
                 basis: str, extra=None) -> str:
    conn = core.conn
    sid = sid_of(chain, w, ca, obs_block)
    if conn.execute("SELECT 1 FROM raw_observations WHERE obs_id=?", (sid,)).fetchone() or conn.execute(
            "SELECT 1 FROM postings WHERE source_kind='opening' AND source_ns=? AND source_id=? LIMIT 1", (chain, sid)).fetchone():
        return ""
    loc = f"wallet:{chain}:{w}"
    pay = {w: {("native:None" if not ca else f"token:{str(ca).lower()}"): int(bal)},
           "_source": "rpc", "_block": int(obs_block), "_block_ts": int(obs_ts), "_scope": "native" if not ca else "token",
           "_basis": basis, "_at": int(at_ts)}
    if ca:
        pay["_q"] = [f"{str(w).lower()}:{str(ca).lower()}"]
    for k, v in (extra or {}).items():
        if not isinstance(v, dict):
            pay[k] = v
    conn.execute("INSERT INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
                 (sid, "opening_balance", chain, json.dumps(pay, ensure_ascii=False), int(obs_ts) + 1))
    conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                 " leg_kind, event, classifier_ver) VALUES ('opening', ?, ?, 0, ?, ?, ?, ?, NULL, NULL, 'opening', 'OPENING', ?)",
                 (chain, sid, int(at_ts), int(aid), loc, str(int(diff)), _ver(core)))
    core._bump_position(int(aid), int(diff), loc)
    core.__dict__.pop("_disc_t_cache", None)
    return sid


def after_write(at_ts: int, log=None) -> None:
    try:
        os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
    except FileNotFoundError:
        pass
    except OSError:
        pass
    try:
        common.mark_hist_dirty(int(at_ts))
    except Exception as e:
        if log:
            log.warning("발견 시점 기초 잔고: 장기 곡선 표식 실패: %s", e)


def disc_anchors(conn, chain: str, loc: str, aid: int) -> list:
    p = str(loc).split(":")
    if len(p) != 3:
        return []
    a = conn.execute("SELECT kind, address FROM assets WHERE asset_id=?", (int(aid),)).fetchone()
    if not a:
        return []
    pre = f"recon:{chain}:{p[2]}:disc:{(str(a[1]).lower() if a[0] != 'native' and a[1] else 'native')}@"
    out = []
    for sid, pl, t in conn.execute("SELECT obs_id, payload, observed_at FROM raw_observations WHERE obs_id >= ? AND obs_id < ?",
                                   (pre, pre[:-1] + "A")).fetchall():
        d = _jload(pl, {})
        b = d.get("_block") if isinstance(d, dict) else None
        if isinstance(b, int) and not isinstance(b, bool):
            out.append((sid, int(b), int(t)))
    out.sort(key=lambda x: -x[1])
    return out


def disc_obs(conn) -> dict:
    out = {}
    for sid, kind, venue, pl, t in conn.execute("SELECT obs_id, kind, venue, payload, observed_at FROM raw_observations"
                                                " WHERE kind='opening_balance' AND obs_id LIKE 'recon:%:disc:%'").fetchall():
        d = _jload(pl, None)
        if not is_disc(sid) or not isinstance(d, dict):
            continue
        b, at = d.get("_block"), d.get("_at")
        wl = [(k, v) for k, v in d.items() if isinstance(v, dict)]
        if not (isinstance(b, int) and isinstance(at, int)) or len(wl) != 1 or len(wl[0][1]) != 1:
            continue
        w, cell = wl[0]
        key, bal = next(iter(cell.items()))
        kind9, _, ca = str(key).partition(":")
        r = conn.execute("SELECT asset_id FROM assets WHERE kind='native' AND chain=?", (venue,)).fetchone() if kind9 == "native" else \
            conn.execute("SELECT asset_id FROM assets WHERE kind='token' AND chain=? AND address=?", (venue, ca.lower())).fetchone()
        try:
            bal = int(bal)
        except (TypeError, ValueError):
            continue
        if r:
            out[sid] = {"chain": venue, "loc": f"wallet:{venue}:{w}", "aid": int(r[0]), "bal": bal, "blk": int(b), "T": int(t), "at": int(at)}
    return out


def base_at(conn, loc: str, aid: int, blk: int, T: int, exclude_sid=None):
    rows = [r for r in cell_rows(conn, loc, aid) if not (r[1] == "opening" and exclude_sid and r[3] == exclude_sid)]
    return posted_le(rows, blk, T)


def absorbed_by(conn, chain: str, loc: str, aid: int, blk, ts=None) -> tuple:
    if blk is None and ts is None:
        return None, None
    hit = [x for x in disc_anchors(conn, chain, loc, aid) if (x[1] >= int(blk) if blk is not None else int(ts) < x[2])]
    if not hit:
        return None, None
    x = min(hit, key=lambda t: (t[1], t[0]))
    return x[0], x[2]


def anchor_at(conn, sid: str):
    r = conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
    d = _jload(r[0] if r else None, {})
    a = d.get("_at") if isinstance(d, dict) else None
    return int(a) if isinstance(a, int) and not isinstance(a, bool) else None


def max_t(conn, chain: str) -> int:
    r = conn.execute("SELECT max(observed_at) FROM raw_observations WHERE obs_id >= ? AND obs_id < ? AND obs_id LIKE ?",
                     (f"recon:{chain}:", f"recon:{chain};", "%:disc:%")).fetchone()
    return int(r[0]) if r and r[0] is not None else 0


class Runner:

    def __init__(self, core, log):
        self.core = core
        self.log = log
        self.jobs = {}
        self.last = 0.0

    def _get(self, k):
        return _jload(_meta(self.core.conn, k), None)

    def _put(self, k, d):
        self.core.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, json.dumps(d, ensure_ascii=False, sort_keys=True)))

    def _res(self, kind: str, key: str, d: dict):
        p = os.path.join(common.STATE_DIR, RES_NAME)
        try:
            cur = common.read_json(p, {}) or {}
        except SystemExit:
            cur = {}
        cur = cur if isinstance(cur, dict) else {}
        sec = cur.setdefault(kind, {})
        sec[key] = dict(d, ts=int(time.time()))
        if len(sec) > 500:
            for k9 in sorted(sec, key=lambda x: (sec[x] or {}).get("ts", 0))[:len(sec) - 500]:
                sec.pop(k9, None)
        cur["ts"] = int(time.time())
        try:
            common.atomic_write_json(p, cur)
        except OSError:
            pass

    def _chains(self) -> set:
        c = self.core
        out = {ch for ch in (c.cfg.get("chains") or {}) if c.my_wallets.get(ch)}
        if any(w.get("type") == "bsc_rpc" for w in c.cfg.get("wallets") or []) or c.my_wallets.get("bsc"):
            out.add("bsc")
        out.discard("sol")
        return out

    def _my(self, chain: str) -> set:
        c = self.core
        m = {str(x).lower() for x in (c.my_wallets.get(chain) or ())}
        if chain == "bsc":
            m |= {str(w.get("address") or "").lower() for w in c.cfg.get("wallets") or [] if w.get("type") == "bsc_rpc"}
        return m

    def _urls(self, chain: str) -> list:
        c = self.core
        if chain == "bsc":
            b = c.cfg.get("bsc") or {}
            return [u for u in list(b.get("detail_rpcs") or []) + list(b.get("logs_rpcs") or []) if u]
        cc = (c.cfg.get("chains") or {}).get(chain) or {}
        from evm_watch import RpcSynthMixin as _RS
        return list(cc.get("rpcs") or _RS.RPC_DEFAULT.get(chain) or [])

    def _cursor(self, chain: str, w: str):
        sd = common.STATE_DIR
        try:
            if chain == "bsc":
                cur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {}) or {}
                return int(cur.get("from_block") or 0) or None
            cur = common.read_json(os.path.join(sd, f"cursor_evm_{chain}.json"), {}) or {}
            v = cur.get(w, cur.get(str(w).lower()))
            return int(v) if v is not None else None
        except (SystemExit, TypeError, ValueError):
            return None

    def _lane_hold(self, chain: str, upto: int):
        return lane_hold(chain, "", upto) if chain == "bsc" else None

    def _prefs(self) -> dict:
        try:
            d = common.read_json(os.path.join(common.STATE_DIR, "ui_prefs.json"), {}) or {}
        except SystemExit:
            d = {}
        return d if isinstance(d, dict) else {}

    def note(self, chain: str, txhash: str) -> int:
        if chain == "sol" or chain not in self._chains():
            return 0
        conn = self.core.conn
        n = 0
        for aid, loc in conn.execute("SELECT DISTINCT asset_id, location FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?"
                                     " AND location LIKE 'wallet:%' AND CAST(qty_base AS TEXT) LIKE '-%'", (chain, txhash)).fetchall():
            p = str(loc).split(":")
            if len(p) != 3:
                continue
            k = cand_key(chain, p[2], aid)
            old = self._get(k)
            if isinstance(old, dict) and old.get("st") not in ("gone",):
                continue
            if not cell_negative(conn, chain, loc, int(aid), self.core._group_of(int(aid))):
                continue
            self._put(k, {"st": "new", "tx": txhash, "at": int(time.time()), "n": 0, "next": 0, "src": "net"})
            n += 1
        return n

    def run(self, drained=frozenset()) -> int:
        n = 0
        n += self._harvest()
        now = time.time()
        if now - self.last < PASS_GAP:
            return n
        self.last = now
        self._take_request()
        n += self._recheck_request()
        self._start_jobs()
        n += self._harvest()
        return n

    def _req_take(self, name: str, key: str) -> tuple:
        p = os.path.join(common.STATE_DIR, name)
        pp, tk = p + ".processing", p + ".taking"
        cur = common.read_control_json(pp, None)
        items = list(cur.get(key) or []) if isinstance(cur, dict) and isinstance(cur.get(key), list) else []
        by = str((cur or {}).get("by") or "")[:40] if isinstance(cur, dict) else ""
        if not os.path.exists(tk) and os.path.exists(p):
            try:
                os.replace(p, tk)
            except OSError:
                pass
        if os.path.exists(tk):
            new = common.read_control_json(tk, None)
            if isinstance(new, dict) and isinstance(new.get(key), list):
                items += new[key]
                by = str(new.get("by") or by)[:40]
            common.atomic_write_json(pp, {key: items, "by": by, "ts": int(time.time())})
            try:
                os.remove(tk)
            except OSError:
                pass
        return items, by

    def _req_keep(self, name: str, key: str, left: list, by: str) -> None:
        pp = os.path.join(common.STATE_DIR, name) + ".processing"
        if left:
            common.atomic_write_json(pp, {key: left, "by": by, "ts": int(time.time())})
        else:
            try:
                os.remove(pp)
            except OSError:
                pass

    def _take_request(self):
        cells, by = self._req_take(REQ_NAME, "cells")
        if not cells:
            self._req_keep(REQ_NAME, "cells", [], by)
            return
        req = {"by": by}
        conn = self.core.conn
        took = 0
        for x in cells[:500]:
            if not isinstance(x, dict):
                continue
            ch, w = str(x.get("chain") or ""), str(x.get("wallet") or "").lower()
            if ch not in self._chains() or w not in self._my(ch):
                continue
            ca = x.get("ca")
            if ca in (None, "", "native"):
                r = conn.execute("SELECT asset_id FROM assets WHERE kind='native' AND chain=?", (ch,)).fetchone()
            else:
                r = conn.execute("SELECT asset_id FROM assets WHERE kind='token' AND chain=? AND address=?", (ch, str(ca).lower())).fetchone()
            if not r:
                continue
            k = cand_key(ch, w, r[0])
            old = self._get(k)
            if isinstance(old, dict) and old.get("st") in FINAL and old.get("st") != "gone" and not x.get("retry"):
                continue
            self._put(k, {"st": "new", "tx": None, "at": int(time.time()), "n": 0, "next": 0, "src": "req", "by": str(req.get("by") or "")[:40]})
            took += 1
        conn.commit()
        self._req_keep(REQ_NAME, "cells", cells[500:], by)
        if took:
            self.log.warning("발견 시점 기초 잔고 요청 %d칸 접수 — 가드 통과분만 직전 블록 잔고 확인 뒤 기장", took)

    def _start_jobs(self):
        c = self.core
        conn = c.conn
        live = sum(1 for j in self.jobs.values() if not j["ev"].is_set())
        now = int(time.time())
        prefs = None
        rows = conn.execute("SELECT k, v FROM meta WHERE k >= ? AND k < ?", (CAND, CAND[:-1] + ";")).fetchall()
        changed = False
        for k, v in rows:
            if live >= MAX_JOBS:
                break
            d = _jload(v, None)
            if isinstance(d, dict) and d.get("st") == "fail" and not d.get("reopened") and str(d.get("why") or "").startswith(LANE_FAIL_WHY) \
                    and k not in self.jobs:
                try:
                    ch9, w9 = k.split(":", 3)[1:3]
                except ValueError:
                    ch9 = w9 = None
                if ch9 and _lanes_chain(ch9) and not lane_busy(ch9) and not lane_hold(ch9, w9, int(self._cursor(ch9, w9) or 0)):
                    d.update(st="retry", n=0, next=0, reopened=now, why="차선 끝 — 다시 확인")
                    self._put(k, d)
                    changed = True
                    self.log.info("발견 시점 기초 잔고 %s — 차선 때문에 실패로 굳었던 칸 다시 엶", k[len(CAND):])
            if not isinstance(d, dict) or d.get("st") in FINAL or k in self.jobs or int(d.get("next") or 0) > now:
                continue
            try:
                _, ch, w, aid = k.split(":", 3)
                aid = int(aid)
            except ValueError:
                continue
            if ch not in self._chains():
                continue
            if prefs is None:
                prefs = self._prefs()
            pl = plan_cell(conn, ch, w, aid, prefs, self._my(ch))
            if pl["st"] != "go":
                d.update(st=pl["st"] if pl["st"] in ("skip", "gone") else "wait", why=pl["why"], next=now + WAIT_RETRY)
                self._put(k, d)
                changed = True
                if pl["st"] in ("skip",):
                    self.log.info("발견 시점 기초 잔고 건너뜀 %s:%s… #%s — %s", ch, w[:10], aid, pl["why"])
                    self._res("cells", k, {"st": "skip", "why": pl["why"]})
                continue
            if d.get("tx") and d["tx"] != pl["tx"]:
                d["tx0"] = d["tx"]
            d["tx"] = pl["tx"]
            hold9 = self._lane_hold(ch, int(pl["block"]) - 1)
            if hold9:
                d.update(st="wait", why=hold9, next=now + WAIT_RETRY)
                self._put(k, d)
                changed = True
                continue
            urls = self._urls(ch)
            if not urls:
                d.update(st="wait", why="RPC 없음", next=now + WAIT_RETRY)
                self._put(k, d)
                changed = True
                continue
            cur = self._cursor(ch, w)
            fb_ok = bool(cur and cur >= pl["block"] and not moved_after(pl["rows"], pl["block"]) and c._scope_ready(ch))
            fb_hold = (lane_hold(ch, w, cur) if cur else None) or (lane_busy(ch) if not c._scope_ready(ch) else None)
            job = {"k": k, "ch": ch, "w": w, "aid": aid, "pl": pl, "ev": threading.Event(), "t1": None, "res": None, "err": None,
                   "fb": cur if (fb_ok and not fb_hold) else None, "fb_hold": fb_hold}

            def _run(job=job, urls=urls):
                try:
                    b1 = int(job["pl"]["block"]) - 1
                    try:
                        job["res"] = ("arch", b1) + fetch_at(urls, job["w"], job["pl"]["ca"], b1)
                    except Exception as e:
                        if not (_state_err(e) and job["fb"]):
                            raise
                        job["res"] = ("now", int(job["fb"])) + fetch_at(urls, job["w"], job["pl"]["ca"], int(job["fb"]))
                except BaseException as e:
                    job["err"] = e
                finally:
                    job["t1"] = time.time()
                    job["ev"].set()
            self.jobs[k] = job
            d.update(st="run", why="", at_run=now)
            self._put(k, d)
            changed = True
            try:
                threading.Thread(target=_run, name=f"tj-negabs-{ch}", daemon=True).start()
            except Exception:
                self.jobs.pop(k, None)
                raise
            live += 1
        if changed:
            conn.commit()

    def _harvest(self) -> int:
        c = self.core
        conn = c.conn
        done = 0
        for k, job in list(self.jobs.items()):
            if not job["ev"].is_set():
                continue
            d = self._get(k) or {}
            now = int(time.time())
            if job["err"] is not None:
                self.jobs.pop(k, None)
                e = job["err"]
                if _state_err(e) and job.get("fb_hold"):
                    d.update(st="wait", why=str(job["fb_hold"]), next=now + WAIT_RETRY)
                    self._put(k, d)
                    conn.commit()
                    continue
                n9 = int(d.get("n") or 0) + 1
                fin = n9 >= MAX_TRIES
                d.update(st="fail" if fin else "retry", n=n9, why=(LANE_FAIL_WHY if _state_err(e) else "조회 실패: ")
                         + ("" if _state_err(e) else common.safe_err(str(e))[:120]),
                         next=now + min(BACKOFF_MAX, BACKOFF0 * (2 ** (n9 - 1))))
                self._put(k, d)
                conn.commit()
                self.log.warning("발견 시점 기초 잔고 조회 실패 %s (%d/%d)%s — 종전 음수 유지: %s", k[len(CAND):], n9, MAX_TRIES,
                                 " · 재시도 끝" if fin else "", d["why"])
                if fin:
                    self._res("cells", k, {"st": "fail", "why": d["why"]})
                continue
            if now - job["t1"] > DEFER_MAX:
                self.jobs.pop(k, None)
                d.update(st="retry", next=0)
                self._put(k, d)
                conn.commit()
                continue
            hold9 = lane_hold(job["ch"], job["w"], int(job["res"][1]) if job.get("res") else int(job["pl"]["block"]) - 1)
            if hold9:
                self.jobs.pop(k, None)
                d.update(st="retry", why=hold9, next=now + WAIT_RETRY)
                self._put(k, d)
                conn.commit()
                continue
            if c._recon_pending(job["ch"]):
                continue
            self.jobs.pop(k, None)
            pl = job["pl"]
            rows = cell_rows(conn, pl["loc"], job["aid"])
            if cell_fp(rows) != pl["fp"]:
                d.update(st="retry", why="조회 중 그 칸 원장 변경", next=0)
                self._put(k, d)
                conn.commit()
                continue
            mode, oblk, bal, bts = job["res"]
            hold9 = self._lane_hold(job["ch"], int(pl["block"]) - 1)
            if hold9:
                d.update(st="retry", why=hold9, next=now + WAIT_RETRY)
                self._put(k, d)
                conn.commit()
                continue
            if mode != "arch" and (moved_after(rows, pl["block"]) or not c._scope_ready(job["ch"])):
                d.update(st="retry", why="대체 조건 해제(B 뒤 이동·수집기 준비)", next=now + WAIT_RETRY)
                self._put(k, d)
                conn.commit()
                continue
            base = posted_le(rows, oblk, int(bts) + 1)
            if base is None:
                d.update(st="wait", why="블록 모르는 거래", next=now + WAIT_RETRY)
                self._put(k, d)
                conn.commit()
                continue
            diff = int(bal) - int(base)
            if diff <= 0:
                d.update(st="none", why=f"직전 잔고로 확인되는 옛 보유 없음(잔고 {bal} · 원장 {base})", bal=str(bal), blk=oblk)
                self._put(k, d)
                conn.commit()
                self.log.info("발견 시점 기초 잔고 없음 %s — %s", k[len(CAND):], d["why"])
                self._res("cells", k, {"st": "none", "why": d["why"]})
                continue
            at_ts = min(int(pl["ts"]) - 1, int(bts)) if mode == "arch" else int(pl["ts"]) - 1
            try:
                sid = write_anchor(c, job["ch"], job["w"], job["aid"], pl["ca"], diff, oblk, bts, at_ts, bal,
                                   "neg_tx" if mode == "arch" else "neg_tx_now_minus_flows", {"_tx": pl["tx"]})
                d.update(st="done", why="", sid=sid, qty=str(diff), blk=oblk, mode=mode)
                self._put(k, d)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            if sid:
                done += 1
                after_write(at_ts, self.log)
                self.log.warning("★발견 시점 기초 잔고 %s %s %s… +%s(원시 단위 · 관측 블록 %s · %s) — 원가 미상, 발견 시각 시세로 추정★",
                                 job["ch"], pl.get("sym") or "", job["w"][:10], diff, oblk, "직전 블록" if mode == "arch" else "수집기 커서 블록 − 이후 원장")
                self._res("cells", k, {"st": "done", "sid": sid, "qty": str(diff), "blk": oblk})
        return done

    def _recheck_request(self) -> int:
        items, by = self._req_take(RECHK_REQ_NAME, "items")
        if not items:
            self._req_keep(RECHK_REQ_NAME, "items", [], by)
            return 0
        n = 0
        prefs = self._prefs()
        left = list(items[2000:])
        for it in items[:2000]:
            try:
                st, why, sid = self._recheck_one(it, prefs)
            except Exception as e:
                self.core.conn.rollback()
                st, why, sid = "err", common.safe_err(str(e))[:160], ""
            key = f"{(it or {}).get('chain')}:{str((it or {}).get('wallet') or '').lower()}:{str((it or {}).get('ca') or 'native').lower()}@{(it or {}).get('block')}" \
                if isinstance(it, dict) else "?"
            self._res("recheck", key, {"st": st, "why": why, "sid": sid})
            if st == "done":
                n += 1
            elif st == "wait":
                left.append(it)
            elif st not in ("list",):
                self.log.info("재점검 결과 적용 %s — %s: %s", key[:60], st, why)
        self._req_keep(RECHK_REQ_NAME, "items", left, by)
        if n:
            self.log.warning("★재점검 결과로 발견 시점 기초 잔고 %d칸 기장★", n)
        return n

    def _recheck_one(self, it, prefs) -> tuple:
        c = self.core
        conn = c.conn
        if not isinstance(it, dict):
            return "err", "형식 오류", ""
        ch = str(it.get("chain") or "")
        w = str(it.get("wallet") or "").lower()
        ca = it.get("ca")
        ca = None if ca in (None, "", "native") else str(ca).lower()
        try:
            blk, cbal, bts = int(it["block"]), int(str(it["chain_bal_raw"])), int(it.get("block_ts") or 0)
        except (KeyError, TypeError, ValueError):
            return "err", "형식 오류(block·chain_bal_raw)", ""
        if it.get("spam") is not False:
            return "skip", "스팸 표시(또는 판정 없음) 줄", ""
        try:
            dr = int(str(it.get("diff_raw")))
        except (TypeError, ValueError):
            return "err", "형식 오류(diff_raw)", ""
        if dr <= 0:
            return "list", "원장이 더 많거나 같음 — 넣지 않음(목록만)", ""
        if ch not in self._chains() or w not in self._my(ch):
            return "skip", "추적 중인 등록 지갑·체인 아님", ""
        if bts <= 0 or bts > time.time() + 600:
            return "err", "블록 시각 없음(도구가 채움)", ""
        if ca is None:
            aid = c.asset_id("native", ch, None, symbol=c.native_sym.get(ch, ch.upper()), decimals=18)
        else:
            dec = it.get("decimals")
            if isinstance(dec, bool) or not isinstance(dec, int) or not 0 <= dec <= 77:
                dec = None
            aid = c.asset_id("token", ch, ca, symbol=str(it.get("symbol") or "")[:40] or None, decimals=dec)
        why = asset_guard(conn, aid, prefs)
        if why:
            conn.rollback()
            return "skip", why, ""
        if not recon_done(conn, ch, w, ca is None):
            conn.rollback()
            return "wait", "그 지갑 기초 잔고 대사 미완료", ""
        cur = self._cursor(ch, w)
        if not cur or cur < blk:
            conn.rollback()
            return "wait", f"수집기가 그 블록까지 아직 안 옴(커서 {cur})", ""
        hold9 = lane_hold(ch, w, blk)
        if hold9:
            conn.rollback()
            return "wait", hold9, ""
        if not (c._scope_ready(ch) or (ca is not None and c._scope_ready_tok(ch))) or c._recon_pending(ch):
            conn.rollback()
            return "wait", "수집기 상세 대기·미소비 거래 있음", ""
        loc = f"wallet:{ch}:{w}"
        if any(x[1] > blk for x in disc_anchors(conn, ch, loc, aid)):
            conn.rollback()
            return "list", "같은 칸에 더 늦은 블록의 발견 시점 기초 잔고가 이미 있음 — 넣지 않음(목록만)", ""
        rows = cell_rows(conn, loc, aid)
        if prewin_pending(conn, ch, rows):
            conn.rollback()
            return "wait", "재계산 대기(늦게 온 옛 거래)", ""
        base = posted_le(rows, blk, bts + 1)
        if base is None:
            conn.rollback()
            return "wait", "블록 모르는 거래", ""
        if base < 0:
            conn.rollback()
            return "list", "그 블록에서 원장 음수 — 안전망(나간 거래 직전 블록) 경로 대상(tools/negabs_1010.py)", ""
        diff = cbal - base
        if diff <= 0:
            conn.rollback()
            return "list", f"원장이 이미 따라잡음(체인 {cbal} · 원장 {base})", ""
        try:
            sid = write_anchor(c, ch, w, aid, ca, diff, blk, bts, bts, cbal, "token_recheck",
                               {"_sources": [str(s)[:40] for s in (it.get("sources") or [])][:6] if isinstance(it.get("sources"), list) else [],
                                "_diff_raw": str(dr)})
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if not sid:
            return "list", "이미 기장됨(같은 관측)", ""
        after_write(bts, self.log)
        return "done", f"+{diff}(원시 단위)" + ("" if diff == dr else f" — 점검 때 차이 {dr} 에서 원장 변화 반영"), sid

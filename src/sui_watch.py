from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, logs, paths  # noqa: E402
import address_codec as ac  # noqa: E402
import bf_engine  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state  # noqa: E402
import chain_watch  # noqa: E402

CHAIN = "sui"
PROVIDER = "sui_graphql"
QV = 1
MAINNET_ID = "4btiuiMPvEENsttpZC7CZ53DruC3MAgfznDbASZ7DR6S"
DEFAULT_URL = "https://graphql.mainnet.sui.io/graphql"
PAGE_MAX = 50
LATEST_OVERLAP = 600
EXTEND_MIN_SEC = 86400
PREFLIGHT_TTL = 3600
MISMATCH_HOLD = 300
NESTED_MAX_PAGES = 200
BAL_MAX_PAGES = 200
META_BATCH = 8
CACHE_MAX = 3000
META_NONE_TTL = 3600

_BC = "pageInfo { hasNextPage endCursor } nodes { owner { address } coinType { repr } amount }"
TX_FIELDS = ("digest sender { address } gasInput { gasSponsor { address } } "
             "effects { status timestamp checkpoint { sequenceNumber } "
             "gasEffects { gasSummary { computationCost storageCost storageRebate } } "
             "balanceChanges(first: 50) { " + _BC + " } }")
Q_PREFLIGHT = ('query SuiPreflight { chainIdentifier checkpoint { sequenceNumber timestamp } '
               'serviceConfig { maxPageSize(type: "Query", field: "transactions") '
               'r: availableRange(type: "Query", field: "transactions", filters: ["affectedAddress"]) '
               '{ first { sequenceNumber timestamp } last { sequenceNumber timestamp } } } }')
Q_FWD = ("query SuiTxFwd($a: SuiAddress!, $n: Int!, $after: String, $ack: UInt53) { checkpoint { sequenceNumber } "
         "transactions(first: $n, after: $after, filter: { affectedAddress: $a, afterCheckpoint: $ack }) "
         "{ pageInfo { hasNextPage endCursor } nodes { " + TX_FIELDS + " } } }")
Q_BACK = ("query SuiTxBack($a: SuiAddress!, $n: Int!, $before: String, $bck: UInt53) { checkpoint { sequenceNumber } "
          "transactions(last: $n, before: $before, filter: { affectedAddress: $a, beforeCheckpoint: $bck }) "
          "{ pageInfo { hasPreviousPage startCursor } nodes { " + TX_FIELDS + " } } }")
Q_TX = "query SuiTx($d: String!) { transaction(digest: $d) { " + TX_FIELDS + " } }"
Q_BC = ("query SuiTxBc($d: String!, $after: String) { transaction(digest: $d) { digest effects { "
        "balanceChanges(first: 50, after: $after) { " + _BC + " } } } }")
Q_CK = "query SuiCk { checkpoint { sequenceNumber timestamp } }"
Q_CK_AT = "query SuiCkAt($c: UInt53!) { checkpoint(sequenceNumber: $c) { sequenceNumber timestamp } }"
Q_BAL = ("query SuiBal($a: SuiAddress!, $c: UInt53!, $after: String) { address(address: $a, atCheckpoint: $c) { "
         "balances(first: 50, after: $after) { pageInfo { hasNextPage endCursor } "
         "nodes { coinType { repr } totalBalance coinBalance addressBalance } } } }")

_DIGEST = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,64}")
_BIGINT = re.compile(r"-?\d{1,80}")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|\+00:00)")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class GqlError(chain_watch.Transient):
    pass


class StaleRange(GqlError):
    pass


class ProviderMismatch(chain_watch.Transient):
    pass


def _iso_ts(s):
    m = _ISO.fullmatch(str(s or ""))
    if not m:
        return None
    y, mo, d, h, mi, se = (int(x) for x in m.groups())
    return calendar.timegm((y, mo, d, h, mi, se, 0, 0, 0))


def _uint(v, what):
    if isinstance(v, bool):
        raise chain_watch.Transient(f"{what} 형식 오류")
    if isinstance(v, int) and v >= 0:
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    raise chain_watch.Transient(f"{what} 없음·형식 오류")


def _big(v, what):
    if isinstance(v, bool) or not isinstance(v, (str, int)) or not _BIGINT.fullmatch(str(v)):
        raise chain_watch.Transient(f"{what} 형식 오류(정수 아님)")
    return int(v)


def _seq(ck, what="checkpoint"):
    if not isinstance(ck, dict):
        raise chain_watch.Transient(f"{what} 없음")
    return _uint(ck.get("sequenceNumber"), what)


def _addr(node):
    a = (node or {}).get("address") if isinstance(node, dict) else None
    if not isinstance(a, str):
        return None
    try:
        return ac.sui_key(a)
    except ValueError:
        return None


def _struct_name(t):
    head = t.split("<", 1)[0]
    return head.rsplit("::", 1)[-1][:32]


def _clean_sym(s):
    if not isinstance(s, str):
        return None
    s = _CTRL.sub("", s).strip()[:32]
    return s or None


def _owners_version(owners):
    return hashlib.sha256(("|".join(sorted(owners))).encode()).hexdigest()[:16]


class SuiAdapter(reg.ChainAdapter):
    chain = CHAIN

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        sc = ((self.cfg.get(reg.CFG_CHAIN_KEY) or {}).get(CHAIN) or {}) if isinstance(self.cfg.get(reg.CFG_CHAIN_KEY), dict) else {}
        sc = sc if isinstance(sc, dict) else {}
        url = str(sc.get("graphql_url") or DEFAULT_URL)
        u = urllib.parse.urlsplit(url)
        loop = u.hostname in ("127.0.0.1", "localhost")
        if not (u.scheme == "https" or (u.scheme == "http" and loop)) or not u.hostname:
            raise ValueError("nonevm.sui.graphql_url 은 https 주소여야 해요")
        self.url = url
        self.host = (u.hostname or "").lower()
        self.timeout = float(sc.get("timeout_sec", 25))
        self.retries = max(1, int(sc.get("retries", 2)))
        self.overlap = max(0, int(sc.get("latest_overlap", LATEST_OVERLAP)))
        self._pf = None
        self._pf_at = 0.0
        self._mm_at = 0.0
        self._cache = {}
        self._meta = {}
        self._nometa = {}
        self._lock = threading.Lock()

    def _post(self, op, query, variables=None, prio="fg"):
        body = json.dumps({"query": query, "variables": variables or {}, "operationName": op}).encode()
        try:
            d, _h = bf_engine.http_request(self.url, data=body, timeout=self.timeout, retries=self.retries, prio=prio)
        except bf_engine.NetError as e:
            raise chain_watch.Transient(f"{op}: {logs.safe_err(e)[:160]}") from e
        except (OSError, ValueError) as e:
            raise chain_watch.Transient(f"{op}: {logs.safe_err(e)[:160]}") from e
        if not isinstance(d, dict):
            raise chain_watch.Transient(f"{op}: 응답 형식 오류")
        errs = d.get("errors")
        if errs:
            msg = "; ".join(str((e or {}).get("message") if isinstance(e, dict) else e)[:120] for e in (errs if isinstance(errs, list) else [errs]))[:240]
            low9 = msg.lower()
            if "consistent range" in low9 or ("outside" in low9 and "range" in low9):
                raise StaleRange(f"{op}: {logs.safe_err(msg)}")
            raise GqlError(f"{op}: {logs.safe_err(msg)}")
        data = d.get("data")
        if not isinstance(data, dict):
            raise GqlError(f"{op}: data 없음")
        return data

    def preflight(self, force=False) -> dict:
        now = time.time()
        if not force and self._pf is not None and now - self._pf_at < PREFLIGHT_TTL:
            return self._pf
        if not force and now - self._mm_at < MISMATCH_HOLD:
            raise ProviderMismatch("설정한 Sui GraphQL 이 메인넷이 아니에요(chainIdentifier 불일치) — 수집 안 함")
        data = self._post("SuiPreflight", Q_PREFLIGHT, {}, "fg")
        if data.get("chainIdentifier") != MAINNET_ID:
            self._pf, self._mm_at = None, now
            raise ProviderMismatch("설정한 Sui GraphQL 이 메인넷이 아니에요(chainIdentifier 불일치) — 수집 안 함")
        ck = data.get("checkpoint")
        tip = _seq(ck)
        sc = data.get("serviceConfig") or {}
        r = sc.get("r") if isinstance(sc, dict) else None
        first = (r or {}).get("first") if isinstance(r, dict) else None
        try:
            mps = int(sc.get("maxPageSize")) if sc.get("maxPageSize") is not None else PAGE_MAX
        except (TypeError, ValueError):
            mps = PAGE_MAX
        self._pf = {"tip": tip, "tip_ts": _iso_ts((ck or {}).get("timestamp")),
                    "avail_ck": _seq(first) if isinstance(first, dict) else None,
                    "avail_ts": _iso_ts(first.get("timestamp")) if isinstance(first, dict) else None,
                    "page": max(1, min(PAGE_MAX, mps))}
        self._pf_at = now
        return self._pf

    def coverage_from(self, t0):
        pf = self._pf
        if not pf:
            return None
        if pf.get("avail_ck") is None or pf.get("avail_ts") is None:
            return pf.get("tip_ts")
        if pf["avail_ck"] == 0:
            return None
        return pf["avail_ts"] if pf["avail_ts"] > int(t0 or 0) else None

    def window_t0(self, now=None) -> int:
        now = time.time() if now is None else now
        months = 0.0 if self.cfg.get("backfill_full_history") else float(self.cfg.get("backfill_months") or 0)
        t = int(now - months * 30 * 86400) if months > 0 else 0
        if t <= 0:
            return 0
        s = bf_engine.SINCE.target(None)
        return int(min(t, s)) if s else t

    def lane_fp(self, lane) -> str:
        return f"sui-gql-v{QV}|{self.host}|{lane}"

    def discovery_query(self, owner, lane):
        return {"owner": owner, "lane": lane}, self.lane_fp(lane)

    def _take_nodes(self, nodes):
        if not isinstance(nodes, list):
            raise chain_watch.Transient("transactions.nodes 없음")
        out = []
        for n in nodes:
            if not isinstance(n, dict) or not isinstance(n.get("digest"), str) or not _DIGEST.fullmatch(n["digest"]):
                raise chain_watch.Transient("거래 digest 없음·형식 오류")
            eff = n.get("effects") if isinstance(n.get("effects"), dict) else {}
            ck = _seq(eff.get("checkpoint"), "거래 체크포인트")
            out.append((n, ck, _iso_ts(eff.get("timestamp"))))
        with self._lock:
            for n, _c, _t in out:
                self._cache.pop(n["digest"], None)
                self._cache[n["digest"]] = n
            while len(self._cache) > CACHE_MAX:
                self._cache.pop(next(iter(self._cache)))
        return out

    @staticmethod
    def _item(n, ck, ts):
        return {"stable_id": n["digest"], "ck": ck, "ts": ts}

    def latest_page(self, owner, safe, cur):
        pf = self.preflight()
        s0 = int(safe["ck"])
        ack = max(0, s0 - self.overlap)
        c = cur if isinstance(cur, dict) and cur.get("c") and cur.get("a") == ack else None
        data = self._post("SuiTxFwd", Q_FWD, {"a": owner, "n": pf["page"], "after": c["c"] if c else None, "ack": ack}, "fg")
        conn = data.get("transactions")
        if not isinstance(conn, dict) or not isinstance(conn.get("pageInfo"), dict):
            raise chain_watch.Transient("transactions 없음")
        l0 = int(c["L"]) if c else _seq(data.get("checkpoint"))
        rows = self._take_nodes(conn.get("nodes"))
        items = [self._item(n, ck, ts) for n, ck, ts in rows]
        pi = conn["pageInfo"]
        if pi.get("hasNextPage") is True:
            if not isinstance(pi.get("endCursor"), str):
                raise chain_watch.Transient("다음 쪽 커서 없음")
            return items, {"c": pi["endCursor"], "a": ack, "L": l0}, None
        if pi.get("hasNextPage") is not False:
            raise chain_watch.Transient("hasNextPage 없음")
        return items, None, {"ck": max(s0, l0)}

    def history_page(self, owner, safe, cur):
        pf = self.preflight()
        t0 = int(safe.get("t0") or 0)
        c = dict(cur) if isinstance(cur, dict) else {}
        if c.get("c"):
            bck, before = int(c["b0"]), c["c"]
        else:
            bck, before = (int(c["m"]) + 1 if c.get("m") is not None else int(safe["from_b"])), None
        data = self._post("SuiTxBack", Q_BACK, {"a": owner, "n": pf["page"], "before": before, "bck": bck}, "bg")
        conn = data.get("transactions")
        if not isinstance(conn, dict) or not isinstance(conn.get("pageInfo"), dict):
            raise chain_watch.Transient("transactions 없음")
        rows = self._take_nodes(conn.get("nodes"))
        crossed = False
        items = []
        m, lo = c.get("m"), c.get("lo")
        for n, ck, ts in rows:
            if ts is None:
                raise chain_watch.Transient("거래 시각 없음")
            m = ck if m is None else min(m, ck)
            if ts < t0:
                crossed = True
                continue
            items.append(self._item(n, ck, ts))
            lo = ck if lo is None else min(lo, ck)
        pi = conn["pageInfo"]
        more = pi.get("hasPreviousPage")
        if more not in (True, False):
            raise chain_watch.Transient("hasPreviousPage 없음")
        if crossed or more is False:
            lo9 = lo if lo is not None else safe.get("lo")
            return items, None, dict(safe, done=True, lo=lo9)
        if not isinstance(pi.get("startCursor"), str):
            raise chain_watch.Transient("이전 쪽 커서 없음")
        return items, {"c": pi["startCursor"], "b0": bck, "m": m, "lo": lo}, None

    @staticmethod
    def rebase_cursor(lane, cur):
        if lane == "history" and isinstance(cur, dict) and (cur.get("m") is not None or cur.get("lo") is not None):
            return {"c": None, "b0": None, "m": cur.get("m"), "lo": cur.get("lo")}
        return None

    def discover_page(self, owner, query, cursor):
        raise NotImplementedError("Sui 는 SuiCollector(체크포인트 lane)로 돌린다")

    def _cache_pop(self, d):
        with self._lock:
            return self._cache.pop(d, None)

    def fetch_and_normalize(self, ref, owners):
        d = str((ref or {}).get("stable_id") or "")
        if not _DIGEST.fullmatch(d):
            raise chain_watch.Transient("digest 형식 오류")
        self.preflight()
        node = self._cache_pop(d)
        if node is None:
            data = self._post("SuiTx", Q_TX, {"d": d}, "fg" if (ref or {}).get("lane") == "latest" else "bg")
            node = data.get("transaction")
            if node is None:
                return None
        if not isinstance(node, dict) or node.get("digest") != d:
            raise chain_watch.Transient("상세 응답 digest 불일치")
        eff = node.get("effects")
        if not isinstance(eff, dict):
            return None
        bc = eff.get("balanceChanges")
        if not isinstance(bc, dict) or not isinstance(bc.get("pageInfo"), dict) or not isinstance(bc.get("nodes"), list):
            raise chain_watch.Transient("balanceChanges 없음")
        changes = list(bc["nodes"])
        pi = bc["pageInfo"]
        for _i in range(NESTED_MAX_PAGES):
            if pi.get("hasNextPage") is False:
                break
            if pi.get("hasNextPage") is not True or not isinstance(pi.get("endCursor"), str):
                raise chain_watch.Transient("balanceChanges 쪽 정보 없음")
            data = self._post("SuiTxBc", Q_BC, {"d": d, "after": pi["endCursor"]}, "bg")
            t9 = data.get("transaction")
            b9 = ((t9 or {}).get("effects") or {}).get("balanceChanges") if isinstance(t9, dict) else None
            if not isinstance(b9, dict) or not isinstance(b9.get("nodes"), list) or not isinstance(b9.get("pageInfo"), dict):
                raise chain_watch.Transient("balanceChanges 다음 쪽 없음")
            changes += b9["nodes"]
            pi = b9["pageInfo"]
        else:
            raise chain_watch.Transient("balanceChanges 쪽이 너무 많음(상세 미완)")
        return self.normalize(node, changes, set(owners), (ref or {}).get("owner"))

    def normalize(self, node, changes, owners, ref_owner=None):
        eff = node.get("effects") or {}
        st9 = eff.get("status")
        if st9 not in ("SUCCESS", "FAILURE"):
            return None
        ts = _iso_ts(eff.get("timestamp"))
        if not ts:
            return None
        ck = _seq(eff.get("checkpoint"), "거래 체크포인트")
        failed = st9 == "FAILURE"
        sender = _addr(node.get("sender"))
        payer = _addr(((node.get("gasInput") or {}).get("gasSponsor")) if isinstance(node.get("gasInput"), dict) else None) or sender
        gs = ((eff.get("gasEffects") or {}).get("gasSummary")) if isinstance(eff.get("gasEffects"), dict) else None
        if not isinstance(gs, dict):
            raise chain_watch.Transient("gasSummary 없음(수수료 모름 — 보류)")
        fee = (_uint(gs.get("computationCost"), "computationCost") + _uint(gs.get("storageCost"), "storageCost")
               - _uint(gs.get("storageRebate"), "storageRebate"))
        gi9 = node.get("gasInput")
        if fee and (not isinstance(gi9, dict) or "gasSponsor" not in gi9
                    or (gi9["gasSponsor"] is not None and _addr(gi9["gasSponsor"]) is None)):
            raise chain_watch.Transient("gasInput·gasSponsor 정보 없음(가스 낸 쪽 모름 — 보류)")
        if fee and payer is None:
            raise chain_watch.Transient("가스 낸 쪽 모름(보류)")
        allc = {}
        for x in changes:
            if not isinstance(x, dict):
                raise chain_watch.Transient("balanceChange 형식 오류")
            rp = (x.get("coinType") or {}).get("repr") if isinstance(x.get("coinType"), dict) else None
            try:
                t = ac.sui_type_canonical(rp)
            except (ValueError, TypeError) as e:
                raise chain_watch.Transient(f"코인 타입 해석 불가: {str(rp)[:60]}") from e
            o9 = _addr(x.get("owner"))
            if o9 is None:
                raise chain_watch.Transient("balanceChange.owner 없음·형식 오류(보류)")
            k = (o9, t)
            allc[k] = allc.get(k, 0) + _big(x.get("amount"), "balanceChange.amount")
        mine_ch = {k: v for k, v in allc.items() if k[0] in owners and v}
        involved = {o for o, _t in mine_ch} | ({sender} & owners) | ({payer} & owners)
        if ref_owner in owners:
            involved.add(ref_owner)
        if not involved:
            return None
        tok_types = sorted({t for (_o, t) in mine_ch if t != ac.SUI_NATIVE_TYPE})
        meta = self.coin_meta(tok_types) if tok_types else {}
        nodec = [t for t in tok_types if meta.get(t, (None, None))[1] is None]
        nometa_types = {t for t in nodec if self.dec_invalid(t)}
        extra_reasons = []
        if nometa_types:
            mine_ch = {k: v for k, v in mine_ch.items() if k[1] not in nometa_types}
            allc = {k: v for k, v in allc.items() if k[1] not in nometa_types}
            nodec = [t for t in nodec if t not in nometa_types]
            extra_reasons.append("token_decimals_invalid_skipped")
        if nodec:
            raise chain_watch.Transient(f"내 토큰 자릿수(coinMetadata) 없음 — 보류: {_struct_name(nodec[0])}")

        def asset(t):
            if t == ac.SUI_NATIVE_TYPE:
                return {"kind": "native", "symbol": "SUI", "decimals": 9}
            sym, dec = meta.get(t, (None, None))
            return {"kind": "token", "id": t, "symbol": sym or _struct_name(t), "decimals": dec}
        deltas = [{"owner": o, "asset": asset(t), "delta_base": str(v)} for (o, t), v in sorted(mine_ch.items())]
        fees = []
        if fee and payer in owners:
            fees.append({"payer": payer, "asset": {"kind": "native"}, "amount_base": str(fee), "component": "gas",
                         "included_in_deltas": True})
        elif fee and sender in owners:
            fees.append({"payer": chain_event.EXTERNAL, "asset": {"kind": "native"}, "amount_base": str(fee), "component": "gas_sponsored",
                         "included_in_deltas": True})
        tot = {}
        for (o, t), v in allc.items():
            tot[t] = tot.get(t, 0) + v
        conserved = all(
            v == (-fee if t == ac.SUI_NATIVE_TYPE else 0) for t, v in tot.items()) and (fee == 0 or ac.SUI_NATIVE_TYPE in tot)
        hint = "" if failed else ("transfer" if conserved and mine_ch else "unknown")
        econ = dict(allc)
        if fee and payer is not None:
            k9 = (payer, ac.SUI_NATIVE_TYPE)
            econ[k9] = econ.get(k9, 0) + fee
        moves = []
        for t in sorted({t for (_o, t) in econ}):
            neg = sorted((o, -v) for (o, t2), v in econ.items() if t2 == t and v < 0 and o is not None)
            pos = sorted((o, v) for (o, t2), v in econ.items() if t2 == t and v > 0 and o is not None)
            pairs = []
            if len(neg) == 1:
                pairs = [(neg[0][0], o, v) for o, v in pos]
            elif len(pos) == 1:
                pairs = [(o, pos[0][0], v) for o, v in neg]
            for f, to, v in pairs:
                if f in owners or to in owners:
                    moves.append({"id": f"{len(moves)}", "asset": asset(t), "from": f, "to": to, "amount_base": str(v)})
        own_list = sorted(involved)
        return {"v": chain_event.VERSION, "kind": chain_event.KIND, "chain": CHAIN, "network": "mainnet",
                "tx_uid": node["digest"], "txhash": node["digest"], "ts": int(ts),
                "order": {"height": None, "checkpoint": ck, "lt": None, "index": 0},
                "finality": {"state": "finalized", "blockhash": None, "evidence": "checkpoint"},
                "execution": {"state": "failed" if failed else "success", "trace_complete": True},
                "owners": own_list, "ownership_version": _owners_version(owners),
                "deltas": deltas, "fees": fees, "movements": moves,
                "classification": {"hint": hint, "trusted": False,
                                   "evidence": "balance_changes_conserved" if conserved else "balance_changes_not_conserved"},
                "completeness": {"history": True, "details": True, "balances": True, "reasons": extra_reasons},
                "source": {"provider": PROVIDER, "parser_version": QV, "observed_at": int(time.time()),
                           "payload_digest": chain_event.payload_digest({"n": node.get("digest"), "c": changes, "g": gs})}}

    def coin_meta(self, types) -> dict:
        now = time.time()
        out, need = {}, []
        with self._lock:
            for t in types:
                m = self._meta.get(t)
                if m is not None and (m[1] is not None or now - m[2] < META_NONE_TTL):
                    out[t] = (m[0], m[1])
                else:
                    need.append(t)
        for i in range(0, len(need), META_BATCH):
            part = need[i:i + META_BATCH]
            decl = ", ".join(f"$t{j}: String!" for j in range(len(part)))
            body = " ".join(f"m{j}: coinMetadata(coinType: $t{j}) {{ decimals symbol }}" for j in range(len(part)))
            data = self._post("SuiMeta", f"query SuiMeta({decl}) {{ {body} }}", {f"t{j}": t for j, t in enumerate(part)}, "bg")
            for j, t in enumerate(part):
                if f"m{j}" not in data:
                    raise chain_watch.Transient("coinMetadata 응답 칸 없음")
                m = data[f"m{j}"]
                dec = None
                sym = None
                with self._lock:
                    if m is None:
                        self._nometa[t] = self._nometa.get(t, 0) + 1
                    else:
                        self._nometa.pop(t, None)
                if isinstance(m, dict):
                    d9 = m.get("decimals")
                    dec = d9 if isinstance(d9, int) and not isinstance(d9, bool) and 0 <= d9 <= 77 else None
                    sym = _clean_sym(m.get("symbol"))
                with self._lock:
                    self._meta[t] = (sym, dec, now)
                out[t] = (sym, dec)
        return out

    def dec_invalid(self, t: str) -> bool:
        with self._lock:
            m = self._meta.get(t)
            return self._nometa.get(t, 0) >= 2 and (m is None or m[1] is None)

    def fetch_balances(self, owners, boundary, tokens=None):
        owners = sorted(set(owners or ()))
        tokens = tokens or {}
        self.preflight()
        last = None
        for _attempt in range(3):
            try:
                if boundary is not None and _attempt == 0:
                    data = self._post("SuiCkAt", Q_CK_AT, {"c": int(boundary)}, "bg")
                else:
                    data = self._post("SuiCk", Q_CK, {}, "bg")
                ck = data.get("checkpoint")
                L = _seq(ck)
                lts = _iso_ts((ck or {}).get("timestamp"))
                rows = {o: self._balances_at(o, L) for o in owners}
                break
            except StaleRange as e:
                last = e
                continue
        else:
            raise chain_watch.Transient(f"잔고 스냅숏 경계가 계속 보존 범위 밖으로 밀림: {last}")
        per, unobs, types, sum_un, sum_all = {}, {}, set(), {}, {}
        for o in owners:
            wb, un = {("native", None): 0}, []
            for t, (tot, cb, ab) in rows[o].items():
                if cb is not None and ab is not None and cb + ab != tot:
                    if t == ac.SUI_NATIVE_TYPE:
                        raise chain_watch.Transient("SUI 코인 + 주소 잔고 ≠ 합계 — 대사 보류")
                    un.append(ac.sui_asset_key(t))
                    sum_all.setdefault(o, []).append(ac.sui_asset_key(t))
                    if ac.sui_asset_key(t) not in set(map(str, tokens.get(o) or ())):
                        sum_un.setdefault(o, []).append(ac.sui_asset_key(t))
                if t == ac.SUI_NATIVE_TYPE:
                    wb[("native", None)] = tot
                else:
                    wb[("token", ac.sui_asset_key(t))] = tot
                    types.add(t)
            for k9 in tokens.get(o) or ():
                wb.setdefault(("token", str(k9)), 0)
            per[o] = wb
            if un:
                unobs[o] = un
        meta, dec_un = {}, {}
        if types:
            cm = self.coin_meta(sorted(types))
            for t in sorted(types):
                sym, dec = cm.get(t, (None, None))
                k = ac.sui_asset_key(t)
                if dec is None:
                    for o in owners:
                        if ("token", k) in per[o] and k not in set(map(str, tokens.get(o) or ())):
                            unobs.setdefault(o, []).append(k)
                            if per[o][("token", k)] > 0 and not self.dec_invalid(t):
                                dec_un.setdefault(o, []).append(k)
                    continue
                meta[k] = (sym or _struct_name(t), dec)
        why = ([chain_event.WHY_DEC_UNKNOWN] if dec_un else []) + ([chain_event.WHY_SUM_MISMATCH] if sum_un else [])
        hold = {o: sorted(set(dec_un.get(o, [])) | set(sum_un.get(o, []))) for o in set(dec_un) | set(sum_un)}
        return {"per_wallet": per, "_meta": meta,
                "_boundary": {"kind": "checkpoint", "value": str(L), "hash": None, "ts": lts},
                "_complete": not hold, "_why": why, "_dec_unknown": hold,
                "_unobserved": unobs, "_sum_mismatch": sum_all, "_source": PROVIDER, "_ownership_version": _owners_version(owners)}

    def _balances_at(self, owner, L):
        out = {}
        after = None
        for _i in range(BAL_MAX_PAGES):
            data = self._post("SuiBal", Q_BAL, {"a": owner, "c": L, "after": after}, "bg")
            a9 = data.get("address")
            conn = a9.get("balances") if isinstance(a9, dict) else None
            if not isinstance(conn, dict) or not isinstance(conn.get("nodes"), list) or not isinstance(conn.get("pageInfo"), dict):
                raise chain_watch.Transient("balances 없음(0 으로 보지 않음)")
            for n in conn["nodes"]:
                rp = ((n or {}).get("coinType") or {}).get("repr") if isinstance(n, dict) else None
                try:
                    t = ac.sui_type_canonical(rp)
                except (ValueError, TypeError) as e:
                    raise chain_watch.Transient(f"잔고 코인 타입 해석 불가: {str(rp)[:60]}") from e
                if t in out:
                    raise chain_watch.Transient("잔고 목록에 같은 코인 타입이 두 번")
                tot = _big(n.get("totalBalance"), "totalBalance")
                if tot < 0:
                    raise chain_watch.Transient("음수 잔고")
                cb = _big(n["coinBalance"], "coinBalance") if n.get("coinBalance") is not None else None
                ab = _big(n["addressBalance"], "addressBalance") if n.get("addressBalance") is not None else None
                out[t] = (tot, cb, ab)
            pi = conn["pageInfo"]
            if pi.get("hasNextPage") is False:
                return out
            if pi.get("hasNextPage") is not True or not isinstance(pi.get("endCursor"), str):
                raise chain_watch.Transient("balances 쪽 정보 없음")
            after = pi["endCursor"]
        raise chain_watch.Transient("잔고 쪽이 너무 많음(부분 결과로 대사 안 함)")

    def get_capabilities(self, provider=None):
        out = []
        for c in super().get_capabilities(provider):
            c2 = reg.ProviderCapability(**{k: v for k, v in c.as_dict().items()})
            if c2.provider == "sui_graphql" and self.host == "graphql.mainnet.sui.io":
                c2.verified, c2.verified_at = True, "2026-10-11"
                c2.history_from = 0 if c2.role == "address_history" else c2.history_from
            out.append(c2)
        return out


def make_adapter(cfg):
    return SuiAdapter(cfg)


class SuiCollector(chain_watch.Collector):

    def _init_owner(self, o):
        lk, hk = "latest:" + o, "history:" + o
        ls, hs = self.st.lane(lk).get("safe"), self.st.lane(hk).get("safe")
        if isinstance(ls, dict) and isinstance(hs, dict):
            return
        pf = self.ad.preflight()
        if not isinstance(hs, dict):
            u = int(ls["ck"]) if isinstance(ls, dict) else int(pf["tip"])
            hs = {"upper": u, "from_b": u + 1, "t0": self.ad.window_t0(), "done": False, "lo": None}
            self.st.mark_safe(hk, hs)
        if not isinstance(ls, dict):
            self.st.mark_safe(lk, {"ck": int(hs["upper"])})

    def discover(self, lane: str) -> int:
        added = 0
        try:
            self.ad.preflight()
        except chain_watch.Transient as e:
            self.errors += 1
            self._say("[sui] 사전 점검 실패(다음 주기): %s", logs.safe_err(e)[:160])
            return 0
        fp = self.ad.lane_fp(lane)
        for o in sorted(self.owners):
            key = f"{lane}:{o}"
            try:
                self._init_owner(o)
            except chain_watch.Transient as e:
                self.errors += 1
                self._say("[sui] %s 시작 경계 못 잡음: %s", key, logs.safe_err(e)[:120])
                continue
            ln = self.st.lane(key)
            if ln.get("fp") and ln.get("fp") != fp:
                keep = self.ad.rebase_cursor(lane, ln.get("cursor"))
                self.st.reset_lane(key, "제공자·질의 바뀜")
                if keep is not None:
                    self.st.save_cursor(key, keep, fp)
                ln = self.st.lane(key)
            safe = ln.get("safe") or {}
            if lane == "history":
                t0n = self.ad.window_t0()
                if safe.get("done"):
                    if t0n >= int(safe.get("t0") or 0) - EXTEND_MIN_SEC:
                        continue
                    lo = safe.get("lo")
                    safe = dict(safe, done=False, t0=t0n, from_b=(int(lo) + 1) if lo is not None else int(safe["from_b"]))
                    self.st.reset_lane(key, "창 확장")
                    self.st.mark_safe(key, safe)
            cur = self.st.lane(key).get("cursor")
            for _i in range(max(0, int(self.page_budget.get(lane, 1)))):
                try:
                    if lane == "latest":
                        items, nxt, done = self.ad.latest_page(o, safe, cur)
                    else:
                        items, nxt, done = self.ad.history_page(o, safe, cur)
                except chain_watch.Transient as e:
                    self.errors += 1
                    self._say("[sui] %s 발견 일시 실패(다음 주기): %s", key, logs.safe_err(e)[:160])
                    if isinstance(e, GqlError) and cur is not None:
                        self.st.save_cursor(key, self.ad.rebase_cursor(lane, cur), fp)
                    break
                n9 = self.st.pending_upsert([(it["stable_id"], dict(it, owner=o, lane=lane)) for it in items])
                added += n9
                if n9:
                    self.st.save()
                self.st.save_cursor(key, nxt, fp)
                if done is not None:
                    self.st.mark_safe(key, done)
                    break
                cur = nxt
        return added

    def update_status(self):
        pend = {}
        for p in self.st.d["pending"].values():
            o = (p.get("ref") or {}).get("owner")
            pend[o] = pend.get(o, 0) + 1
        gapped = set()
        for g in self.st.d["gaps"]:
            o, em = (g.get("ref") or {}).get("owner"), self.st.em["uids"].get(str(g.get("id")))
            if em is None or (isinstance(em, dict) and o not in (em.get("o") or ())):
                gapped.add(o)
        for o in sorted(self.owners):
            hs = self.st.lane("history:" + o).get("safe") or {}
            ls = self.st.lane("latest:" + o).get("safe") or {}
            if not hs or not ls:
                continue
            t0 = int(hs.get("t0") or 0)
            old = (self.st.d["status"].get(o) or {}).get("details_complete_through")
            dct = ls.get("ck") if hs.get("done") and not pend.get(o) else (old if hs.get("done") else None)
            if o in gapped:
                dct = None
            av = self.ad.coverage_from(t0) if self.ad._pf is not None else (self.st.d["status"].get(o) or {}).get("available_from")
            self.st.set_status(o, requested_from=t0, available_from=av, scanned_through=ls.get("ck"), details_complete_through=dct)

    def cycle(self) -> dict:
        r = super().cycle()
        self.update_status()
        self.st.save()
        return r


def _budgets(cfg):
    sc = ((cfg.get(reg.CFG_CHAIN_KEY) or {}).get(CHAIN) or {}) if isinstance(cfg.get(reg.CFG_CHAIN_KEY), dict) else {}
    sc = sc if isinstance(sc, dict) else {}

    def n(k, d):
        try:
            return max(1, int(sc.get(k, d)))
        except (TypeError, ValueError):
            return d
    return ({"latest": n("latest_pages", 5), "history": n("history_pages", 10)},
            {"latest": n("latest_details", 100), "history": n("history_details", 500)})


def main(poll_default: int = 60):
    from inbox import SegmentWriter
    log = logs.setup_logging("tj-" + CHAIN)
    paths.ensure_dirs()
    cfg = config.load_config()
    bf_engine.configure(cfg)
    owners = reg.owners(cfg, CHAIN)
    if not owners:
        raise SystemExit("추적할 Sui 지갑이 없음 — config chain_wallets 확인")
    sp = reg.spec(CHAIN)
    st = chain_state.ChainState(CHAIN)
    st.drop_owner(owners)
    st.save()
    pb, db = _budgets(cfg)
    try:
        ad = make_adapter(cfg)
    except ValueError as e:
        raise SystemExit(f"Sui 설정 오류: {logs.safe_err(e)[:160]}") from e
    col = SuiCollector(ad, SegmentWriter(os.path.join(paths.INBOX_DIR, sp.stream)), st, owners, log=log,
                       page_budget=pb, detail_budget=db)
    sc = (cfg.get(reg.CFG_CHAIN_KEY) or {}).get(CHAIN) if isinstance(cfg.get(reg.CFG_CHAIN_KEY), dict) else None
    try:
        poll = max(10, int((sc or {}).get("poll_sec", poll_default))) if isinstance(sc, dict) else poll_default
    except (TypeError, ValueError):
        poll = poll_default
    log.info("가동: Sui %d지갑, %d초 주기", len(owners), poll)
    try:
        while True:
            t0 = time.time()
            try:
                r = col.cycle()
                log.info("[sui] 주기: %s", r)
            except Exception as e:   # noqa: BLE001 [boundary]
                log.warning("[sui] 주기 실패(다음 주기): %s", logs.safe_err(e)[:200])
            time.sleep(max(5.0, poll - (time.time() - t0)))
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

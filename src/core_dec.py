import common
import os
import sqlite3
import time
import logging

log = logging.getLogger('tj-core')


class DecMixin:

    DEC_ISSUES_PATH = os.path.join(common.STATE_DIR, "asset_decimals_issues.json")

    def _meta_dec(self, chain, ca):
        if not chain or not ca:
            return None
        name = "bsc_token_meta.json" if chain == "bsc" else f"rpc_token_meta_{chain}.json"
        p = os.path.join(common.STATE_DIR, name)
        cache = self.__dict__.setdefault("_meta_dec_cache", {})
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return None
        ent = cache.get(name)
        if not ent or ent[0] != mt:
            raw = common.read_json(p, {}) or {}
            m9 = {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    v = v[1] if isinstance(v, (list, tuple)) and len(v) >= 2 else v
                    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 77:
                        m9[str(k).lower()] = v
            ent = cache[name] = (mt, m9)
        return ent[1].get(str(ca).lower())

    def _dec_issue(self, aid: int, kind: str, stored, seen) -> None:
        seen_k = (int(aid), kind, seen)
        logged = self.__dict__.setdefault("_dec_issue_seen", set())
        if kind == "pending":
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
        if seen_k in logged:
            return
        logged.add(seen_k)
        r = self.conn.execute("SELECT chain, address, symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        log.warning("자산 decimals %s: #%s %s %s 저장=%s 관측=%s%s", kind, aid, (r["chain"] if r else "?"), (r["symbol"] if r else "?"), stored, seen,
                    " — 이미 기장된 자산이라 다음 재구축에서 채움" if kind == "pending" else " — 덮지 않음(확인 필요)")
        try:
            d = common.read_json(self.DEC_ISSUES_PATH, {}) or {}
            it = d.setdefault("items", {})
            prev9 = it.get(str(aid)) if isinstance(it.get(str(aid)), dict) else {}
            if kind == "conflict" and prev9.get("kind") == "resolve" and prev9.get("stored") == stored and prev9.get("seen") == seen:
                return
            it[str(aid)] = {"kind": kind, "chain": r["chain"] if r else None, "address": r["address"] if r else None,
                            "symbol": r["symbol"] if r else None, "stored": stored, "seen": seen, "ts": int(time.time())}
            d["ts"] = int(time.time())
            common.atomic_write_json(self.DEC_ISSUES_PATH, d)
        except (OSError, ValueError, TypeError):
            pass


    def _dec_startup(self) -> None:
        self._dec_issues_prune()
        try:
            rows = self.conn.execute("SELECT asset_id, chain, address, decimals FROM assets WHERE kind='token' AND address IS NOT NULL").fetchall()
        except sqlite3.Error:
            return
        cand = {}
        for r in rows:
            m9 = self._meta_dec(r["chain"], r["address"])
            if m9 is None:
                continue
            if r["decimals"] is None:
                cand[int(r["asset_id"])] = m9
            elif int(r["decimals"]) != m9:
                self._dec_issue(int(r["asset_id"]), "conflict", int(r["decimals"]), m9)
        if not cand:
            return
        posted = set()
        ids = list(cand)
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            posted |= {int(x[0]) for x in self.conn.execute(
                "SELECT DISTINCT asset_id FROM postings WHERE asset_id IN (%s)" % ",".join("?" * len(ch)), ch).fetchall()}
        for aid, m9 in sorted(cand.items()):
            if aid in posted and m9 != 18:
                self._dec_issue(aid, "pending", None, m9)
            else:
                self.conn.execute("UPDATE assets SET decimals=? WHERE asset_id=?", (m9, aid))

    def _dec_issues_prune(self) -> None:
        try:
            d = common.read_json(self.DEC_ISSUES_PATH, None)
            if not isinstance(d, dict) or not isinstance(d.get("items"), dict):
                return
            keep = {}
            for k, it in d["items"].items():
                r = self.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (int(k),)).fetchone()
                if r is None or (r["decimals"] is not None and it.get("seen") is not None and int(r["decimals"]) == int(it["seen"])):
                    continue
                keep[k] = it
            if len(keep) != len(d["items"]):
                d["items"], d["ts"] = keep, int(time.time())
                common.atomic_write_json(self.DEC_ISSUES_PATH, d)
            if not any((it or {}).get("kind") in ("pending", "resolve") for it in keep.values()):
                self.conn.execute("DELETE FROM meta WHERE k='ext_prewindow:decimals_fix'")
            else:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
        except (OSError, ValueError, TypeError, sqlite3.Error):
            pass

    def _dec_pending_pairs(self) -> set:
        out = set()
        d = common.read_json(self.DEC_ISSUES_PATH, None)
        if not isinstance(d, dict):
            return out
        for k, it in (d.get("items") or {}).items():
            if (it or {}).get("kind") not in ("pending", "resolve"):
                continue
            try:
                for g, loc in self.conn.execute("SELECT DISTINCT a.group_id, p.location FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                                " WHERE p.asset_id=?", (int(k),)).fetchall():
                    if g is not None:
                        out.add((int(g), loc))
            except (sqlite3.Error, ValueError):
                continue
        return out

    DEC_REQ_PATH = os.path.join(common.STATE_DIR, "decimals_resolve_request.json")

    DEC_RES_PATH = os.path.join(common.STATE_DIR, "decimals_resolve_result.json")

    def decimals_resolve_pass(self) -> int:
        req = common.read_control_json(self.DEC_REQ_PATH, None)
        if req is None:
            return 0
        try:
            os.remove(self.DEC_REQ_PATH)
        except OSError:
            pass
        items = req.get("items") if isinstance(req, dict) and isinstance(req.get("items"), dict) else {}
        res = common.read_json(self.DEC_RES_PATH, {}) or {}
        res = res if isinstance(res, dict) else {}
        d = common.read_json(self.DEC_ISSUES_PATH, {}) or {}
        its = d.setdefault("items", {}) if isinstance(d, dict) else {}
        n = 0
        for k, v in items.items():
            try:
                aid, stored, seen = int(k), (v or {}).get("stored"), (v or {}).get("seen")
            except (TypeError, ValueError, AttributeError):
                continue
            err = ""
            it = its.get(str(aid)) if isinstance(its.get(str(aid)), dict) else None
            if any(isinstance(x, bool) or not isinstance(x, int) for x in (stored, seen)) or not 0 <= seen <= 77:
                err = "형식 오류"
            elif not it or it.get("kind") != "conflict" or it.get("stored") != stored or it.get("seen") != seen:
                err = "지금 '자리수 다름' 항목과 다름"
            else:
                r = self.conn.execute("SELECT decimals, chain, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
                m9 = self._meta_dec(r["chain"], r["address"]) if r else None
                if r is None or r["decimals"] is None or int(r["decimals"]) != stored:
                    err = "원장 저장값이 요청과 다름"
                elif m9 is not None and m9 != seen:
                    err = f"수집기 관측값이 바뀜({m9})"
            if err:
                res[str(aid)] = {"ok": False, "err": err, "ts": int(time.time())}
                log.warning("자리수 해결 요청 거절 #%s: %s", aid, err)
                continue
            it.update(kind="resolve", req_at=int(time.time()), by=str((v or {}).get("by") or "")[:40])
            res[str(aid)] = {"ok": True, "ts": int(time.time())}
            n += 1
        if n:
            d["ts"] = int(time.time())
            common.atomic_write_json(self.DEC_ISSUES_PATH, d)
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
            self.conn.commit()
            log.warning("자리수 해결 요청 %d건 접수 — 다음 자동 재구축에서 관측값으로 다시 기장(손익 게이트 그대로)", n)
        try:
            common.atomic_write_json(self.DEC_RES_PATH, res)
        except OSError:
            pass
        return n

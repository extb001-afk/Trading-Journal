import paths, statefile
import fsio
import json
import os
import sqlite3
import time
import logging

log = logging.getLogger('tj-core')


def _read_soft(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log.warning("캐시·표시 파일 손상 — 없는 것으로 보고 계속: %s: %s", os.path.basename(path), str(e)[:120])
        return default


class DecMixin:

    DEC_ISSUES_PATH = paths.StatePath("asset_decimals_issues.json")

    def _meta_dec(self, chain, ca):
        if not chain or not ca:
            return None
        name = "bsc_token_meta.json" if chain == "bsc" else f"rpc_token_meta_{chain}.json"
        p = paths.state(name)
        cache = self.__dict__.setdefault("_meta_dec_cache", {})
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return None
        ent = cache.get(name)
        if not ent or ent[0] != mt:
            raw = _read_soft(p, {}) or {}
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
            d = _read_soft(self.DEC_ISSUES_PATH, {}) or {}
            d = d if isinstance(d, dict) else {}
            it = d.setdefault("items", {})
            prev9 = it.get(str(aid)) if isinstance(it.get(str(aid)), dict) else {}
            if kind == "conflict" and prev9.get("kind") == "resolve" and prev9.get("stored") == stored and prev9.get("seen") == seen:
                return
            it[str(aid)] = {"kind": kind, "chain": r["chain"] if r else None, "address": r["address"] if r else None,
                            "symbol": r["symbol"] if r else None, "stored": stored, "seen": seen, "ts": int(time.time())}
            d["ts"] = int(time.time())
            statefile.atomic_write_json(self.DEC_ISSUES_PATH, d)
        except (OSError, ValueError, TypeError):
            pass


    def _dec_startup(self) -> None:
        n_re = 0
        for aid, sv in sorted(self._dec_pending_seen().items()):
            cur = self.conn.execute("UPDATE assets SET decimals=? WHERE asset_id=? AND decimals IS NULL AND kind='token'", (sv, aid))
            if cur.rowcount and self._renorm_asset(aid):
                n_re += 1
        self._dec_issues_prune()
        try:
            rows = self.conn.execute("SELECT asset_id, chain, address, decimals FROM assets WHERE kind='token' AND address IS NOT NULL").fetchall()
        except sqlite3.Error:
            self._renorm_done(n_re)
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
            self._renorm_done(n_re)
            return
        posted = set()
        ids = list(cand)
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            posted |= {int(x[0]) for x in self.conn.execute(
                "SELECT DISTINCT asset_id FROM postings WHERE asset_id IN (%s)" % ",".join("?" * len(ch)), ch).fetchall()}
        for aid, m9 in sorted(cand.items()):
            self.conn.execute("UPDATE assets SET decimals=? WHERE asset_id=?", (m9, aid))
            if aid in posted and self._renorm_asset(aid):
                n_re += 1
        self._renorm_done(n_re)

    def _dec_pending_seen(self) -> dict:
        d = _read_soft(self.DEC_ISSUES_PATH, None)
        its = d.get("items") if isinstance(d, dict) and isinstance(d.get("items"), dict) else {}
        out = {}
        for k, it in its.items():
            sv = it.get("seen") if isinstance(it, dict) else None
            if not isinstance(it, dict) or it.get("kind") != "pending" or isinstance(sv, bool) or not isinstance(sv, int) or not 0 <= sv <= 77:
                continue
            try:
                out[int(k)] = sv
            except (TypeError, ValueError):
                continue
        return out

    def _renorm_done(self, n: int) -> None:
        if n:
            log.warning("자릿수 채움 재정규화 %d개 자산 — 표시 수량 정정(원장 무변 · 재구축 불필요)", n)
            self._renorm_info = {"n": int(n), "ts": int(time.time())}

    def _dec_issues_prune(self) -> None:
        try:
            d = _read_soft(self.DEC_ISSUES_PATH, None)
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
                statefile.atomic_write_json(self.DEC_ISSUES_PATH, d)
            if not any((it or {}).get("kind") in ("pending", "resolve") for it in keep.values()):
                self.conn.execute("DELETE FROM meta WHERE k='ext_prewindow:decimals_fix'")
            else:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
        except (OSError, ValueError, TypeError, sqlite3.Error):
            pass

    def _dec_pending_pairs(self) -> set:
        out = set()
        d = _read_soft(self.DEC_ISSUES_PATH, None)
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

    DEC_WAIT_PATH = paths.StatePath("decimals_wait.json")
    DEC_WAIT_EVERY = 300

    def _dec_wait_scan(self, force: bool = False) -> int:
        now = time.time()
        if not force and now - float(self.__dict__.get("_dec_wait_at") or 0) < self.DEC_WAIT_EVERY:
            return -1
        self._dec_wait_at = now
        rows = self.conn.execute("SELECT a.asset_id, a.chain, a.address, a.symbol FROM assets a WHERE a.kind='token' AND a.decimals IS NULL"
                                 " AND EXISTS (SELECT 1 FROM postings p WHERE p.asset_id=a.asset_id)").fetchall()
        iss = _read_soft(self.DEC_ISSUES_PATH, {}) or {}
        its = iss.get("items") if isinstance(iss, dict) and isinstance(iss.get("items"), dict) else {}
        prev0 = _read_soft(self.DEC_WAIT_PATH, {}) or {}
        prev = prev0.get("items") if isinstance(prev0, dict) and isinstance(prev0.get("items"), dict) else {}
        ren = self.__dict__.get("_renorm_info") or (prev0.get("renorm") if isinstance(prev0, dict) and isinstance(prev0.get("renorm"), dict) else None)
        nodec = {}
        items = {}
        for r in rows:
            k = str(r["asset_id"])
            if isinstance(its.get(k), dict) and its[k].get("kind") in ("pending", "resolve"):
                continue
            ch = r["chain"]
            if ch not in nodec:
                reg = _read_soft(paths.state(f"token_nodec_{ch}.json"), {}) if ch else {}
                nodec[ch] = reg if isinstance(reg, dict) else {}
            ent = nodec[ch].get(str(r["address"] or "").lower())
            old = prev.get(k) if isinstance(prev.get(k), dict) else {}
            since = old.get("since") if isinstance(old.get("since"), (int, float)) and not isinstance(old.get("since"), bool) else int(now)
            items[k] = {"chain": ch, "address": r["address"], "symbol": r["symbol"], "since": int(since),
                        "est": bool(isinstance(ent, dict) and ent.get("perm"))}
        doc = {"ts": int(now), "items": items}
        if ren:
            doc["renorm"] = ren
        if items != prev or ren != (prev0.get("renorm") if isinstance(prev0, dict) else None) or not os.path.exists(self.DEC_WAIT_PATH):
            statefile.atomic_write_json(self.DEC_WAIT_PATH, doc)
        return len(items)

    DEC_REQ_PATH = paths.StatePath("decimals_resolve_request.json")

    DEC_RES_PATH = paths.StatePath("decimals_resolve_result.json")

    def decimals_pass(self) -> int:
        try:
            return self.decimals_resolve_pass()
        finally:
            self._dec_wait_scan()

    def decimals_resolve_pass(self) -> int:
        req = statefile.read_control_json(self.DEC_REQ_PATH, None)
        if req is None:
            return 0
        claimed = fsio.claim(self.DEC_REQ_PATH)
        taken = statefile.read_control_json(claimed, None) if claimed else None
        if claimed:
            try:
                os.remove(claimed)
            except OSError:
                pass
        if taken is not None:
            req = taken
        items = req.get("items") if isinstance(req, dict) and isinstance(req.get("items"), dict) else {}
        res = statefile.read_json(self.DEC_RES_PATH, {}) or {}
        res = res if isinstance(res, dict) else {}
        d = _read_soft(self.DEC_ISSUES_PATH, {}) or {}
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
            statefile.atomic_write_json(self.DEC_ISSUES_PATH, d)
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
            self.conn.commit()
            log.warning("자리수 해결 요청 %d건 접수 — 다음 자동 재구축에서 관측값으로 다시 기장(손익 게이트 그대로)", n)
        try:
            statefile.atomic_write_json(self.DEC_RES_PATH, res)
        except OSError:
            pass
        return n

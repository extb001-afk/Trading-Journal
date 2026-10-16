import bf_engine
import common
import json
import ledger_backup
import ops_requests
import os
import spamguard
import sqlite3
import sys
import time
from decimal import Decimal
from decimal import localcontext
import logging
import calcguard

log = logging.getLogger('tj-core')


class ExtMixin:

    EXT_STREAMS = frozenset(("evm", "sol", "bsc", "ex"))

    EXT_STALL_SEC = 3600

    EXT_RETRY_MAX = 24 * 3600

    EXT_FAIL_LABEL = ops_requests.REBUILD_FAIL_LABEL

    EXT_DISK_RETRY_SEC = 300

    EXT_DISK_BORN_SEC = 900

    def _ext_items(self, now: float):
        bcfg = self.cfg.get("backfill") or {}
        stall = float(bcfg.get("stall_sec") or self.EXT_STALL_SEC)
        running, stalled, ex_done = [], [], []
        for unit, items in bf_engine.read_status().items():
            if not isinstance(items, dict) or unit.startswith("_"):
                continue
            for key, it in items.items():
                if not isinstance(it, dict) or not (key.endswith(":extend") or it.get("phase") == "extend"):
                    continue
                name = f"{unit}/{key}"
                upd = float(it.get("updated") or 0)
                if it.get("phase") != "done":
                    moved = float(it.get("moved_at") or it.get("started") or upd or 0)
                    if now - upd >= 3 * 3600:
                        continue
                    (stalled if now - moved > stall else running).append(name)
                elif unit in ("ex", "exf") and int(it.get("emitted", 1) or 0) > 0:
                    ex_done.append((name, float(it.get("done_at") or upd)))
        return running, stalled, ex_done

    def ext_rebuild_pass(self, drained: set):
        bcfg = self.cfg.get("backfill") or {}
        if bcfg.get("auto_rebuild") is False or os.environ.get("TJ_EXT_REBUILD") == "0":
            if self._meta_get("ext_rebuild_started_at"):
                self.conn.execute("DELETE FROM meta WHERE k='ext_rebuild_started_at'")
                self.conn.commit()
                self._ext_status()
            return
        now = time.time()
        if now - self._last_ext_check < float(bcfg.get("rebuild_check_sec") or 60):
            return
        self._last_ext_check = now
        need = {}
        for r in self.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'ext_prewindow:%'").fetchall():
            try:
                if int(r["v"]) > 0:
                    need[r["k"][len("ext_prewindow:"):]] = int(r["v"])
            except (TypeError, ValueError):
                continue
        running, stalled, ex_all = self._ext_items(now)
        last_rb = float(self._meta_get("ext_rebuilt_at") or 0)
        ex_done = [n for n, t in ex_all if t >= last_rb]
        if not need and not ex_done:
            return
        try:
            gap = float(bcfg.get("rebuild_min_gap_sec") or 1800)
        except (TypeError, ValueError, OverflowError):
            gap = 1800.0
        gap = min(6 * 3600.0, max(0.0, gap)) if gap == gap else 1800.0
        if not ex_done and last_rb and now - last_rb < gap and not self._meta_get("ext_rebuild_started_at"):
            return
        if running:
            if not getattr(self, "_ext_wait_logged", False):
                log.info("과거 창 확장 진행 중(%s) — 끝난 뒤 원장 재구축", ", ".join(running[:4]))
                self._ext_wait_logged = True
            return
        if stalled and not getattr(self, "_ext_stall_logged", False):
            log.warning("과거 창 확장 멈춤(%s) — 기다리지 않고 원장 재구축 진행", ", ".join(stalled[:4]))
            self._ext_stall_logged = True
        if not self.EXT_STREAMS <= set(drained):
            return
        nb = float(self._meta_get("rebuild_not_before") or 0)
        if now < nb:
            return
        if self._meta_get("ext_rebuild_started_at"):
            self._ext_record_fail("중단됨(재구축 도중 프로세스 종료)", "interrupted")
            return
        fail = float(self._meta_get("ext_rebuild_fail_at") or 0)
        nfail = int(self._meta_get("ext_rebuild_fails") or 0)
        wait = min(self.EXT_RETRY_MAX, float(bcfg.get("rebuild_retry_sec") or 6 * 3600) * (2 ** max(0, nfail - 1)))
        if fail and now - fail < wait and not self._ext_disk_retry_now(now, fail):
            ap9 = common.read_control_json(self.PNL_APPROVE_PATH, None)
            at9 = ops_requests._fin(ap9.get("at")) if isinstance(ap9, dict) else None
            un9 = ops_requests._fin(ap9.get("until")) if isinstance(ap9, dict) else None
            fresh9 = (at9 is not None and un9 is not None and fail < at9 <= now + 60 and now < un9 <= now + ops_requests.APPROVE_TTL + 600
                      and ap9.get("report_sha") == (ops_requests.gate_record() or {}).get("report_sha"))
            if not fresh9 or now - fail < 600:
                return
            log.warning("재구축: 보류된 결과를 승인함 — 백오프를 기다리지 않고 다시 재계산(승인한 결과와 같을 때만 교체)")
        self._ext_rebuild(need, ex_done)

    def _ext_touched(self, ex_done: list):
        pairs = set()
        for r in self.conn.execute("SELECT k FROM meta WHERE k LIKE 'ext\\_prewindow\\_tx:%' ESCAPE '\\'").fetchall():
            _, ch, h = r[0].split(":", 2)
            for g, loc in self.conn.execute(
                    "SELECT DISTINCT a.group_id, p.location FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                    " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=?", (ch, h)).fetchall():
                if g is None:
                    continue
                pairs.add((int(g), loc))
        pairs |= self._dec_pending_pairs()
        prefixes = set()
        for name in ex_done:
            unit, key = name.split("/", 1)
            ex = key.split(":", 1)[0]
            prefixes.add(f"exchange:{'upbit' if unit == 'ex' else ex}")
        return pairs, prefixes

    @staticmethod
    def _positions(conn) -> dict:
        return {(int(r[0]), r[1]): tuple(r[2:]) for r in conn.execute(
            "SELECT group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd FROM positions")}

    QTY_TOL = Decimal("1e-8")

    def _ext_position_gate(self, new_db: str, pairs: set, prefixes: set, locked=()):
        live = self._positions(self.conn)
        c = sqlite3.connect(common.sqlite_ro_uri(new_db, immutable=True), uri=True)
        try:
            new = self._positions(c)
            return self._ext_position_gate_cmp(live, new, c, pairs, prefixes, locked)
        finally:
            c.close()

    def _ext_persp_exempt(self, c, k, qa: Decimal, qb: Decimal):
        loc = str(k[1] or "")
        if loc.count(":") != 2 or not loc.startswith("wallet:"):
            return 0
        ch, w = loc.split(":", 2)[1], loc.split(":", 2)[2]
        sql = ("SELECT p.source_kind, p.source_ns, p.source_id, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
               " WHERE p.location=? AND a.group_id=?")

        def sums(conn9):
            out9 = {}
            with localcontext() as ctx:
                ctx.prec = 100
                for sk, ns, sid, qb9, dec in conn9.execute(sql, (loc, int(k[0]))).fetchall():
                    kk = (sk, ns, sid)
                    out9[kk] = out9.get(kk, Decimal(0)) + Decimal(int(qb9)) / (Decimal(10) ** int(18 if dec is None else dec))
            return out9
        sl, sn = sums(self.conn), sums(c)
        diff = {kk: sn.get(kk, Decimal(0)) - sl.get(kk, Decimal(0)) for kk in set(sl) | set(sn)}
        diff = {kk: d for kk, d in diff.items() if d != 0}
        if not diff:
            return 0
        tol = self.QTY_TOL + abs(qa) * Decimal("1e-12")
        if abs(sum(diff.values(), Decimal(0)) - (qb - qa)) > tol:
            return 0
        r9 = self.conn.execute("SELECT added_at FROM wallets WHERE chain=? AND address=?", (ch, w)).fetchone() or \
            self.conn.execute("SELECT added_at FROM wallets WHERE chain=? AND lower(address)=lower(?)", (ch, w)).fetchone()
        if not r9 or r9[0] is None:
            return 0
        added = int(r9[0])
        for sk, ns, sid in diff:
            if sk != "chain_tx" or ns != ch:
                return 0
            if self.conn.execute("SELECT 1 FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=? AND location=? LIMIT 1",
                                 (ns, sid, loc)).fetchone():
                return 0
            if not c.execute("SELECT 1 FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=? AND location=? LIMIT 1",
                             (ns, sid, loc)).fetchone():
                return 0
            ing = self.conn.execute("SELECT ingested_at FROM raw_txs WHERE chain=? AND txhash=?", (ns, sid)).fetchone()
            if not ing or ing[0] is None or int(ing[0]) >= added:
                return 0
        return len(diff)

    def _ext_position_gate_cmp(self, live: dict, new: dict, c, pairs: set, prefixes: set, locked=()):
        lk_groups = set()
        if locked:
            for r in self.conn.execute("SELECT DISTINCT group_id FROM assets WHERE upper(symbol) IN (%s)"
                                       % ",".join("?" * len(locked)), [str(x).upper() for x in locked]).fetchall():
                if r[0] is None:
                    continue
                lk_groups.add(int(r[0]))
        spam_groups = self._ext_spam_groups()
        bad, cost_diff, skipped = [], 0, 0
        exempt, exempt_tx = [], 0
        for k in set(live) | set(new):
            a, b = live.get(k), new.get(k)
            if k[0] in lk_groups and k[1] == "exchange:upbit":
                continue
            if str(k[1] or "").startswith("out:") or k[0] in spam_groups:
                skipped += 1
                continue
            touched = k in pairs or k[1] in prefixes
            qa = Decimal(a[0]) if a else Decimal(0)
            qb = Decimal(b[0]) if b else Decimal(0)
            tol = self.QTY_TOL + abs(qa) * Decimal("1e-12")
            if k[1] == "exchange:upbit":
                tol = max(tol, self.EX_RECON_TOL)
            if not touched and abs(qa - qb) > tol:
                n9 = self._ext_persp_exempt(c, k, qa, qb)
                if n9:
                    touched = True
                    exempt.append(f"{k} {qa}→{qb}")
                    exempt_tx += n9
            if touched:
                if qb < -tol and qb < qa - tol:
                    bad.append(f"{k} 음수 {qa}→{qb}")
            elif abs(qa - qb) > tol:
                bad.append(f"{k} 수량 {qa}→{qb}")
            elif (a or ("0", "0", "0"))[1:] != (b or ("0", "0", "0"))[1:]:
                cost_diff += 1
        if cost_diff:
            log.info("재구축 포지션 게이트: 수량 동일, 원가/미상 수량만 다른 칸 %d개(허용)", cost_diff)
        if skipped:
            log.info("재구축 포지션 게이트: 판정 제외 %d칸(out:* 외부 주머니 · 사칭 토큰 그룹)", skipped)
        if exempt:
            log.warning("★재구축 포지션 게이트: 등록 뒤 관점 변화 면제 %d칸(근거 tx %d건 — 등록 전에 저장된 tx 의 새 지갑 레그 · 새 음수만 검사): %s★",
                        len(exempt), exempt_tx, " · ".join(exempt[:5]))
        self._ext_gate_exempt = exempt
        return bad

    def _ext_spam_groups(self) -> set:
        per = {}
        for r in self.conn.execute("SELECT group_id, kind, chain, address, symbol FROM assets WHERE group_id IS NOT NULL").fetchall():
            g = int(r[0])
            s9 = r[4] or ""
            fake = r[1] == "token" and bool(r[3]) and bool(s9) and bool(spamguard.impostor_of(s9))
            per[g] = per.get(g, True) and fake
        return {g for g, f in per.items() if f}

    @staticmethod
    def _ext_wal_settle(path: str) -> bool:
        wal = path + "-wal"
        if not (os.path.exists(wal) and os.path.getsize(wal) > 0):
            return True
        c9 = None
        try:
            c9 = sqlite3.connect(path, timeout=10)
            busy, nlog, ncp = c9.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy or (nlog >= 0 and ncp != nlog):
                log.warning("재구축 shadow WAL 체크포인트 미완(busy=%s log=%s done=%s)", busy, nlog, ncp)
                return False
        except sqlite3.Error as e:
            log.warning("재구축 shadow WAL 정리 실패: %s", common.safe_err(e))
            return False
        finally:
            if c9 is not None:
                c9.close()
        ok = not (os.path.exists(wal) and os.path.getsize(wal) > 0)
        if ok:
            log.info("재구축 shadow WAL 을 본문에 합침(단일 파일)")
        return ok

    def _ext_rebuild(self, need: dict, ex_done: list):
        import shutil
        import subprocess
        bcfg = self.cfg.get("backfill") or {}
        ts = time.strftime("%Y%m%d_%H%M%S")
        home = os.path.expanduser(str(bcfg.get("rebuild_dir") or "~"))
        shadow = os.path.join(home, f"tj_shadow_extrebuild_{ts}")
        root = common.BASE_DIR
        live = common.DB_PATH
        tmp = live + f".extnew_{ts}"
        why = ", ".join([("토큰 자리수(decimals) 채움" if c == "decimals_fix" else f"{c} 창 밖 {n}건") for c, n in sorted(need.items())] + ex_done) or "?"
        if self.conn.in_transaction:
            self.conn.commit()
        t_start = int(time.time())
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_started_at', ?)", (str(t_start),))
        self.conn.commit()
        self._ext_status(running=True)

        def fail(msg, code="error", stage="run"):
            n9 = self._ext_record_fail(msg, code, stage)
            log.error("★과거 창 확장 재구축 실패 %d회째(원인 %s · 원장 무변, %s): %s★", n9, self.EXT_FAIL_LABEL.get(code, code),
                      "디스크 여유가 생기면 곧바로 다시" if (code, stage) == ("resource_disk", "precheck") else "백오프 뒤 재시도", msg)
            self._ext_merge_px(os.path.join(shadow, "px_cache_core.json"))
            shutil.rmtree(shadow, ignore_errors=True)
            for p9 in (shadow + ".report.json", tmp):
                try:
                    os.remove(p9)
                except OSError:
                    pass

        try:
            os.makedirs(home, exist_ok=True)
            ok9, msg9 = self._ext_disk_check(home, live)
            if not ok9:
                return fail(msg9, "resource_disk", "precheck")
            os.makedirs(shadow, mode=0o700, exist_ok=True)
            os.chmod(shadow, 0o700)
            log.warning("★과거 창 확장 반영 — 원장 재구축 시작(core 소비 일시 정지 ≈4분): %s★", why)
            pairs, prefixes = self._ext_touched(ex_done)
            self._ext_wait_upbit_complete()
            py = sys.executable or "/usr/bin/python3"
            args = [py, os.path.join(root, "tools", "rebuild2.py"), "--shadow-dir", shadow, "--report", shadow + ".report.json",
                    "--price-online-lp"] + ([] if bcfg.get("rebuild_allow_locked") is False else ["--allow-locked"]) \
                + ([] if bcfg.get("rebuild_pnl_gate") is False else ["--web-compare"])
            try:
                r = subprocess.run(args, env=dict(os.environ, TJ_BASE=root), cwd=root, capture_output=True, text=True,
                                   timeout=float(bcfg.get("rebuild_timeout_sec") or 5400))
            except subprocess.TimeoutExpired:
                return fail("rebuild2 시간 초과", "timeout")
            if r.returncode:
                return fail("rebuild2 rc=%d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:]),
                            self._ext_rc_code(r.returncode, (r.stderr or "") + (r.stdout or "")))
            new_db = os.path.join(shadow, "ledger.db")
            try:
                g = subprocess.run([py, os.path.join(root, "tools", "verify_fixc.py"), "gates", new_db,
                                    "--balances", os.path.join(shadow, "upbit_balances.json"), "--live", live], capture_output=True, text=True,
                                   timeout=float(bcfg.get("verify_timeout_sec") or self.EXT_VERIFY_TIMEOUT_SEC))
            except subprocess.TimeoutExpired:
                return fail("verify_fixc 게이트 시간 초과", "timeout")
            if g.returncode:
                return fail("게이트 b·c: " + g.stdout.strip()[-300:], "integrity")
            self._ext_wal_settle(new_db)
            if os.path.exists(new_db + "-wal") and os.path.getsize(new_db + "-wal") > 0:
                return fail("shadow WAL 미체크포인트", "integrity")
            locked = []
            try:
                rep9 = json.load(open(shadow + ".report.json", encoding="utf-8"))
                locked = list(((rep9.get("anchors") or {}).get("upbit_reanchor") or {}).get("locked") or [])
            except (OSError, ValueError):
                pass
            bad = self._ext_position_gate(new_db, pairs, prefixes, locked=locked)
            if bad:
                return fail(f"포지션 게이트 {len(bad)}칸: " + " · ".join(bad[:5]), "position_gate")
            if bcfg.get("rebuild_pnl_gate") is not False:
                pg9 = self._ext_pnl_gate(shadow + ".report.json", bcfg, why)
                if not pg9["ok"] and not pg9.get("approved"):
                    return fail("손익 게이트: " + pg9["reason"], "pnl_approval")
            c2 = sqlite3.connect(new_db)
            try:
                if c2.execute("PRAGMA quick_check").fetchone()[0] != "ok" or \
                        c2.execute("SELECT 1 FROM meta WHERE k='rebuild_incomplete'").fetchone():
                    return fail("새 원장 무결성/마커", "integrity")
                c2.execute("DELETE FROM meta WHERE k LIKE 'ext_prewindow:%' OR k LIKE 'ext\\_prewindow\\_tx:%' ESCAPE '\\'"
                           " OR k IN ('ext_rebuild_fail_at', 'ext_rebuild_fails', 'ext_rebuild_last_error', 'ext_rebuild_started_at',"
                           " 'ext_rebuild_fail_code', 'ext_rebuild_fail_stage', 'ext_rebuild_fail_code_at')")
                c2.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuilt_at', ?)", (str(t_start),))
                c2.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuilt_why', ?)", (why[:500],))
                c2.commit()
            finally:
                c2.close()
            self._ext_merge_px(os.path.join(shadow, "px_cache_core.json"))
            shutil.copyfile(new_db, tmp)
            c3 = sqlite3.connect(common.sqlite_ro_uri(tmp, immutable=True), uri=True)
            try:
                ok3 = c3.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            finally:
                c3.close()
            if not ok3:
                return fail("복사본 무결성", "integrity")
        except Exception as e:
            calcguard.swallowed("core_ext:ExtMixin._ext_rebuild", e)
            import errno
            full9 = (isinstance(e, OSError) and getattr(e, "errno", None) == errno.ENOSPC) or \
                (isinstance(e, sqlite3.OperationalError) and "disk is full" in str(e).lower())
            return fail(f"예외 {type(e).__name__}: {common.safe_err(e)}", "resource_disk" if full9 else "error")
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.conn.close()
        try:
            kr9, ko9 = self._ext_keep_cfg(bcfg, self.cfg.get("backup"))
            self._ext_swap(live, tmp, ts, keep_recent=kr9, keep_oldest=ko9)
        except Exception as e:
            log.critical("★재구축 원장 교체 중 오류 — core 재기동(원장 파일 확인: %s*): %s★", live, e)
            raise SystemExit(1)
        shutil.rmtree(shadow, ignore_errors=True)
        self._ext_prune_reports(home)
        try:
            os.remove(self.PNL_APPROVE_PATH)
        except OSError:
            pass
        log.warning("★과거 창 확장 반영 완료 — 원장 교체(이전 원장 %s), core 재기동★", os.path.basename(live) + f".pre_extrebuild_{ts}")
        self._ext_status(rebuilt_at=t_start)
        try:
            common.atomic_write_json(os.path.join(common.STATE_DIR, "intentional_restart.json"),
                                     {"unit": "tj-core", "ts": int(time.time()), "reason": "ext_rebuild"})
        except OSError:
            pass
        import logging
        try:
            keep = sqlite3.connect(live)
            keep.execute("SELECT count(*) FROM meta").fetchone()
        except sqlite3.Error:
            pass
        logging.shutdown()
        os._exit(0)

    def _ext_merge_px(self, path: str) -> int:
        d9 = common.read_json(path, None)
        if not isinstance(d9, dict):
            return 0
        n = 0
        try:
            with self.px.lock:
                for sect in ("candle", "fx", "cven", "cgday"):
                    src9 = d9.get(sect)
                    if not isinstance(src9, dict):
                        continue
                    dst9 = self.px.d.setdefault(sect, {})
                    for k9, v9 in src9.items():
                        if k9 not in dst9 and v9 not in (None, 0, 0.0, "", [], {}):
                            dst9[k9] = v9
                            n += 1
                if n:
                    self.px._dirty = int(getattr(self.px, "_dirty", 0) or 0) + n
            if n:
                self.px.flush()
                log.info("재구축 shadow 시세 %d개를 라이브 원가 캐시에 합침(px_cache_core.json)", n)
        except Exception as e:
            calcguard.swallowed("core_ext:ExtMixin._ext_merge_px", e)
            log.warning("재구축 shadow 시세 합치기 실패: %s", common.safe_err(e))
        return n

    PNL_GATE_PATH = os.path.join(common.STATE_DIR, "rebuild_pnl_gate.json")

    PNL_APPROVE_PATH = os.path.join(common.STATE_DIR, "rebuild_pnl_approve.json")

    def _ext_pnl_gate(self, report_path: str, bcfg: dict, why: str) -> dict:
        tol_usd, tol_pct = ops_requests.tol_of(bcfg)
        try:
            rep9 = json.load(open(report_path, encoding="utf-8"))
        except (OSError, ValueError):
            rep9 = {}
        ev = ops_requests.gate_eval(rep9, tol_usd, tol_pct)
        out = {"ok": ev["ok"], "approved": False, "reason": ev["reason"], "months": ev["months"][:5], "n_months": len(ev["months"]),
               "unv": ev["unv"], "cost_lost": ev["cost_lost"], "decimals_unresolved": ev["decimals_unresolved"],
               "open_cost": ev["open_cost"][:5], "n_open_cost": len(ev["open_cost"]), "missing": ev["missing"],
               "why": why[:200], "ts": int(time.time()),
               "tol": [tol_usd, tol_pct]}
        if not out["ok"]:
            try:
                sha9, name9 = ops_requests.preserve_report(report_path)
            except OSError as e:
                sha9, name9 = None, None
                log.warning("재구축 손익 게이트: 거부 보고서 보존 실패(승인 불가 — 다음 재계산에서 다시): %s", common.safe_err(e))
            out["report_sha"], out["report_file"] = sha9, name9
            if sha9:
                ok9, note9, asha9 = ops_requests.approval_check(ev, tol_usd, tol_pct)
                if ok9:
                    out["approved"], out["approved_sha"] = True, asha9
                    log.warning("재구축 손익 게이트: 차이 있음(%s) — 승인한 보고서(%s…)와 같은 결과라 통과", out["reason"], str(asha9)[:12])
                elif note9:
                    out["approve_note"] = note9
                    log.warning("재구축 손익 게이트: 승인이 있지만 이번 결과에 맞지 않음 — %s", note9)
            else:
                out["approve_note"] = "보고서가 없어 승인할 수 없어요 — 다음 재계산 결과로"
        elif out["months"] == [] and not out["reason"]:
            log.info("재구축 손익 게이트 통과 — 월별 실현·원가미상·열린 원가 차이 임계 이내")
        try:
            common.atomic_write_json(self.PNL_GATE_PATH, out)
        except OSError:
            pass
        return out

    EXT_VERIFY_TIMEOUT_SEC = 1800

    EXT_UPBIT_WAIT_SEC = 120

    EXT_UPBIT_FRESH_SEC = 30

    def _ext_wait_upbit_complete(self):
        p = os.path.join(common.STATE_DIR, "upbit_orders_state.json")
        if not os.path.exists(p):
            return
        t0 = time.time()
        while time.time() - t0 < self.EXT_UPBIT_WAIT_SEC:
            try:
                fresh = time.time() - os.path.getmtime(p) <= self.EXT_UPBIT_FRESH_SEC
                if fresh and (common.read_json(p, {}) or {}).get("complete"):
                    return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        log.info("재구축: 업비트 체결 완주 도장을 %d초 안에 못 봄 — 그대로 진행(rebuild2 가 판정)", self.EXT_UPBIT_WAIT_SEC)

    EXT_STATUS_PATH = os.path.join(common.STATE_DIR, "ext_rebuild_status.json")

    def _ext_record_fail(self, msg: str, code: str = "error", stage: str = "run") -> int:
        code = code if code in self.EXT_FAIL_LABEL else "error"
        n9 = int(self._meta_get("ext_rebuild_fails") or 0) + 1
        at9 = str(int(time.time()))
        for k9, v9 in (("ext_rebuild_fail_at", at9), ("ext_rebuild_fails", str(n9)),
                       ("ext_rebuild_last_error", str(msg)[:500]), ("ext_rebuild_fail_code", code),
                       ("ext_rebuild_fail_stage", "precheck" if stage == "precheck" else "run"), ("ext_rebuild_fail_code_at", at9)):
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k9, v9))
        self.conn.execute("DELETE FROM meta WHERE k='ext_rebuild_started_at'")
        self.conn.commit()
        self._ext_status()
        return n9

    def _ext_fail_code(self):
        fa9 = self._meta_get("ext_rebuild_fail_at")
        if not self._meta_get("ext_rebuild_fails") or not fa9 or self._meta_get("ext_rebuild_fail_code_at") != fa9:
            return None, None
        return self._meta_get("ext_rebuild_fail_code"), self._meta_get("ext_rebuild_fail_stage")

    @staticmethod
    def _ext_rc_code(rc: int, out: str) -> str:
        if rc == 2:
            return "transient_rpc"
        if rc == 4:
            return "integrity"
        t = (out or "").lower()
        if "no space left on device" in t or "database or disk is full" in t or "[errno 28]" in t:
            return "resource_disk"
        return "error"

    EXT_DISK_WHAT = {"same": "작업 폴더·원장 같은 디스크", "work": "재구축 작업 폴더 디스크", "ledger": "원장 디스크"}

    def _ext_disk_plan(self, home: str, live: str) -> dict:
        import shutil
        size = os.path.getsize(live) + (os.path.getsize(live + "-wal") if os.path.exists(live + "-wal") else 0)
        sd = os.path.dirname(os.path.abspath(live))
        dh, ds = ledger_backup.dev_of(home), ledger_backup.dev_of(sd)
        need_home = 3 * size + (2 << 30)
        if dh == ds:
            rows = [{"dev": dh, "what": "same", "free": int(shutil.disk_usage(home).free), "need": int(need_home + size)}]
        else:
            rows = [{"dev": dh, "what": "work", "free": int(shutil.disk_usage(home).free), "need": int(need_home)},
                    {"dev": ds, "what": "ledger", "free": int(shutil.disk_usage(sd).free), "need": int(1.5 * size)}]
        return {"size": int(size), "same": dh == ds, "rows": rows, "at": int(time.time())}

    def _ext_disk_check(self, home: str, live: str):
        def short():
            p9 = self._ext_disk_plan(home, live)
            self._ext_disk = p9
            return {r9["dev"]: r9["need"] - r9["free"] for r9 in p9["rows"] if r9["free"] < r9["need"]}
        need9 = short()
        if need9:
            self._ext_relief = ledger_backup.relieve(live, short, home=home, log=log)
            need9 = short()
        if not need9:
            return True, ""
        p9 = self._ext_disk
        r9 = next(x for x in p9["rows"] if x["dev"] in need9)
        return False, "디스크 부족(자동 정리 뒤에도): 여유 %dGB / 필요 ≈%dGB (%s · 원장 %dMB)" % (
            r9["free"] >> 30, r9["need"] >> 30, self.EXT_DISK_WHAT.get(r9["what"], r9["what"]), p9["size"] >> 20)

    def _ext_disk_retry_now(self, now: float, fail: float) -> bool:
        if self._ext_fail_code() != ("resource_disk", "precheck"):
            return False
        if now - fail < self.EXT_DISK_RETRY_SEC or now - float(getattr(self, "_ext_born", None) or now) < self.EXT_DISK_BORN_SEC:
            return False
        bcfg = self.cfg.get("backfill") or {}
        home = os.path.expanduser(str(bcfg.get("rebuild_dir") or "~"))
        try:
            os.makedirs(home, exist_ok=True)
            ok9, _msg9 = self._ext_disk_check(home, common.DB_PATH)
        except Exception as e:
            calcguard.swallowed("core_ext:ExtMixin._ext_disk_retry_now", e)
            log.warning("재구축 디스크 재검사 실패(종전 백오프): %s", common.safe_err(e))
            return False
        self._ext_status()
        if ok9:
            log.warning("재구축: 지난 실패 = 디스크 부족 → 지금 두 디스크 여유 충분 — 백오프를 기다리지 않고 다시")
        return ok9

    def _ext_disk_view(self):
        p9 = getattr(self, "_ext_disk", None)
        if not isinstance(p9, dict):
            return None
        return {"at": p9.get("at"), "same": p9.get("same"), "ledger_mb": int(p9.get("size") or 0) >> 20,
                "rows": [{"what": r9["what"], "label": self.EXT_DISK_WHAT.get(r9["what"], r9["what"]),
                          "free_gb": round(r9["free"] / 1024 ** 3, 1), "need_gb": round(r9["need"] / 1024 ** 3, 1)} for r9 in p9.get("rows") or []]}

    def _ext_status(self, running: bool = False, rebuilt_at: int = None):
        try:
            rl9, dk9 = getattr(self, "_ext_relief", None), self._ext_disk_view()
            if rebuilt_at:
                common.atomic_write_json(self.EXT_STATUS_PATH, {"running": False, "started_at": None, "fails": 0, "fail_at": None,
                                                                "last_error": None, "fail_code": None, "fail_label": None, "fail_stage": None,
                                                                "rebuilt_at": int(rebuilt_at), "relief": rl9, "disk": dk9, "ts": int(time.time())})
                return
            fc9, fs9 = self._ext_fail_code()
            d = {"running": bool(running), "started_at": int(float(self._meta_get("ext_rebuild_started_at") or 0)) or None,
                 "fails": int(self._meta_get("ext_rebuild_fails") or 0),
                 "fail_at": int(float(self._meta_get("ext_rebuild_fail_at") or 0)) or None,
                 "last_error": self._meta_get("ext_rebuild_last_error"),
                 "fail_code": fc9, "fail_label": self.EXT_FAIL_LABEL.get(fc9) if fc9 else None,
                 "fail_stage": fs9 if fc9 else None,
                 "rebuilt_at": int(float(self._meta_get("ext_rebuilt_at") or 0)) or None,
                 "relief": rl9, "disk": dk9,
                 "ts": int(time.time())}
            common.atomic_write_json(self.EXT_STATUS_PATH, d)
        except Exception as _cg9:
            calcguard.swallowed("core_ext:ExtMixin._ext_status", _cg9)
            pass

    EXT_KEEP_RECENT = 0

    EXT_KEEP_REPORTS = 3

    @classmethod
    def _ext_keep_cfg(cls, bcfg: dict, kcfg: dict = None):
        kp = kcfg.get("keep_pre_rebuild") if isinstance(kcfg, dict) else None
        if isinstance(kp, int) and not isinstance(kp, bool) and 1 <= kp <= 5:
            return kp - 1, False
        kr = bcfg.get("rebuild_keep_recent") if isinstance(bcfg, dict) else None
        ko = bcfg.get("rebuild_keep_oldest") if isinstance(bcfg, dict) else None
        kr = kr if isinstance(kr, int) and not isinstance(kr, bool) and kr >= 0 else cls.EXT_KEEP_RECENT
        ko = ko if isinstance(ko, bool) else False
        return kr, ko

    @classmethod
    def _ext_prune_reports(cls, home: str, keep: int = None):
        keep = cls.EXT_KEEP_REPORTS if keep is None else keep
        try:
            rs = sorted(f9 for f9 in os.listdir(home) if f9.startswith("tj_shadow_extrebuild_") and f9.endswith(".report.json"))
        except OSError:
            return []
        gone = []
        for f9 in rs[:max(0, len(rs) - keep)]:
            try:
                os.remove(os.path.join(home, f9))
                gone.append(f9)
            except OSError:
                pass
        return gone

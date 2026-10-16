from __future__ import annotations
import common
import coverage_limits
import db as dbm
import health
import json
import login_auth
import onboarding
import ops_requests
import os
import re
import spamguard
import time
import urllib.request
import web_ctx
import wow
import xfer_match
from decimal import Decimal
from decimal import InvalidOperation
from http_assets import WEB_DIR
from http_assets import _ui_route
from view_common import PREFS_PATH
from view_offc import OFFC_EXCHANGES
from view_review import REVIEW_LEN_KEYS
from view_review import review_len_eff
from view_review import review_pause_eff
from view_review import review_progress
import logging

log = logging.getLogger('tj-web')


class RouteMixin:

    def do_GET(self):
        path, _, query = self.path.partition("?")
        login_auth.mark_conn(self)
        if self._body_on_bodyless():
            return
        try:
            if login_auth.handle(self, "GET", path, query):
                return
            if onboarding.handle_get(self, path):
                return
            if not web_ctx.mats_ready(path):
                return self._send(503, {"ok": False, "error": "계산 재료를 만드는 중 — 잠시 뒤 다시 시도하세요"})
            ui9 = _ui_route(path)
            if ui9:
                return self._send_asset(ui9[0], ui9[1], query)
            if path == "/" or path == "/index.html":
                self._send_asset(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            elif path == "/classic":
                self._send_bytes(302, b"", None, "text/plain; charset=utf-8", extra=(("Location", "/"),))
            elif path == "/support.js":
                self._send_optional("support.js", "application/javascript; charset=utf-8")
            elif path == "/api/state":
                ma9 = self._max_age(query)
                if ma9 is not None and not onboarding.origin_ok(self, required=False):
                    return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
                snap = web_ctx.builder().snapshot() if ma9 is None else web_ctx.builder().snapshot(max_age=ma9)
                self._send_bytes(200, snap.raw, snap.gz, etag=f'W/"{snap.ver}"', extra=(("X-TJ-Ver", snap.ver),))
            elif path == "/api/v2/state":
                self._send_state_v2(query)
            elif path == "/api/v2/part":
                self._send_part(query)
            elif path == "/api/day_events":
                self._send_day_events(query)
            elif path == "/api/tax_rows":
                self._send_tax_rows(query)
            elif path == "/api/bench":
                b9 = web_ctx.bench_series()
                try:
                    sn9 = (urllib.parse.parse_qs(query).get("since") or [""])[0].strip()
                    b9.update(wow.bench(getattr(web_ctx.builder(), "_day_idx", None), since=sn9 if re.fullmatch(r"\d{4}-\d{2}-\d{2}", sn9) else None))
                except Exception as e9:
                    log.warning("비교선(안 팔았다면) 계산 실패: %s", common.safe_err(e9)[:120])
                self._send(200, b9)
            elif path == "/api/habits":
                self._send(200, wow.habits(getattr(web_ctx.builder(), "_day_idx", None)))
            elif path == "/api/curve_hist":
                self._send_curve_hist(query)
            elif path == "/api/receipt":
                self._send_receipt(query)
            elif path == "/api/fut_receipt":
                self._send_fut_receipt(query)
            elif path == "/api/att_detail":
                self._send_att_detail(query)
            elif path == "/api/receipt_chart":
                self._send_receipt_chart(query)
            elif path == "/api/receipt_eval":
                self._send_receipt_eval(query)
            elif path == "/api/receipt_list":
                self._send_receipt_list(query)
            elif path == "/api/other_assets":
                self._send_other_assets(query)
            elif path == "/api/other_assets/quote":
                self._send_oa_quote(query)
            elif path in ("/api/wow/tm", "/api/wow/flows", "/api/search/ask"):
                self._send_wow(path, query)
            elif path == "/api/search":
                self._send_search(query)
            elif path == "/api/nft":
                self._send_nft(query)
            elif path == "/api/alert_prefs":
                self._send(200, web_ctx.alert_view(web_ctx.builder().prefs()))
            elif path == "/api/wallet_reload":
                self._send(200, web_ctx.wallet_reload_view())
            elif path == "/api/outflow_candidates":
                self._send_outflow_cands(query)
            elif path == "/futures":
                if os.path.isfile(os.path.join(WEB_DIR, "futures.html")):
                    self._send_optional("futures.html", "text/html; charset=utf-8")
                else:
                    self._send_bytes(302, b"", None, "text/plain; charset=utf-8", extra=(("Location", "/"),))
            elif path == "/api/futures":
                self._send(200, web_ctx.futures_api_payload())
            elif path == "/api/leverage":
                self._send(200, web_ctx.leverage_api_payload())
            elif path == "/api/coverage_limits":
                if not os.path.exists(web_ctx.coverage_path()):
                    web_ctx.coverage_refresh()
                d9 = coverage_limits._rj(web_ctx.coverage_path(), None)
                if isinstance(d9, dict) and "api_limits" not in d9:
                    d9["api_limits"] = coverage_limits.api_limits_table()
                if isinstance(d9, dict):
                    d9 = common.scrub_secrets(d9)[0]
                self._send(200, {"ok": True, "data": d9} if isinstance(d9, dict) else {"ok": False, "error": "수집 한계를 아직 만들지 못했어요"})
            elif path == "/api/health":
                try:
                    import version as version9
                    ver9 = version9.app_version()
                except Exception:
                    ver9 = "알 수 없음"
                self._send(200, {"ok": True, "spot_updated": web_ctx.builder().spot.updated,
                                 "last_scan": web_ctx.builder()._last_scan_str(), "health": health.web_view(),
                                 "version": ver9, "dataRev": getattr(dbm, "DATA_REV", None)})
            elif path == "/api/ops":
                self._send(200, ops_requests.status())
            else:
                self._send(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
            self._gone_or_500("GET", path, e)
        except (Exception, SystemExit) as e:
            log.warning("GET %s 실패: %s", path, e, exc_info=True)
            try:
                self._send(500, self._err500_body(e))
            except Exception:
                pass

    def _send_optional(self, name, ctype):
        fp = os.path.join(WEB_DIR, name)
        if not os.path.isfile(fp):
            return self._send(404, {"error": "not found"})
        with open(fp, "rb") as f:
            return self._send(200, f.read(), ctype)

    def _gone_or_500(self, method, path, e):
        try:
            self._send(500, self._err500_body(e))
        except Exception:
            log.debug("%s %s 상대가 끊음: %s", method, path, type(e).__name__)
            return
        log.warning("%s %s 실패: %s", method, path, e, exc_info=(type(e), e, e.__traceback__))

    def _err500_body(self, e):
        return {"error": f"처리 중 오류({type(e).__name__}) — tj-web 로그를 확인하세요"}

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        login_auth.mark_conn(self)
        self.close_connection = True
        locked = False
        try:
            if login_auth.handle(self, "POST", path):
                return
            if onboarding.handle_post(self, path):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "Content-Length 형식 오류"})
            if n < 0 or n > 1024 * 1024:
                return self._send(413 if n > 0 else 400, {"error": "본문은 0~1 MiB"})
            self.connection.settimeout(10)
            try:
                body = json.loads(self.rfile.read(n).decode() or "{}") if n else {}
            except (ValueError, RecursionError):
                return self._send(400, {"error": "JSON 형식 오류"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "JSON 객체 필요"})
            if not web_ctx.mats_ready(path):
                return self._send(503, {"ok": False, "error": "계산 재료를 만드는 중 — 잠시 뒤 다시 시도하세요"})
            if path == "/api/flow_register":
                return self._flow_register(body)
            if path in ("/api/other_assets/save", "/api/other_assets/delete"):
                return self._oa_post(path, body)
            if path == "/api/nft/prefs":
                return self._nft_post(body)
            if path == "/api/receipt_eval":
                if body.get("auto") is True and review_pause_eff(web_ctx.builder().prefs() if web_ctx.builder() is not None else {}).get("on"):
                    return self._send(409, {"ok": False, "paused": True, "error": "AI 자동 생성 멈춤 중 — 버튼으로 직접 만들 수 있어요"})
                return self._receipt_eval_post(body)
            if path == "/api/day_memo":
                return self._day_memo_post(body)
            if path == "/api/alert_test":
                return self._alert_test_post(body)
            if path == "/api/wd_dest_register":
                return self._wd_dest_register(body)
            if path in ("/api/health/ack", "/api/health/restore"):
                return self._health_ack_post(path, body)
            if path == "/api/review/fill":
                return self._review_fill_post(body)
            if path.startswith("/api/ops/"):
                return self._ops_post(path, body)
            web_ctx.prefs_lock().acquire()
            locked = True
            prefs = web_ctx.builder().prefs()
            if path == "/api/alert_prefs":
                return self._alert_prefs_post(prefs, body)
            if path == "/api/outflow_resolve":
                return self._outflow_resolve(body)
            if path == "/api/backfill_request":
                return self._backfill_request(body)
            if path == "/api/sale_link":
                lot9 = str(body.get("lot") or "")
                off_now9 = [str(x) for x in (prefs.get("sale_link_off") or [])]
                if not lot9 or len(lot9) > 160 or lot9 not in (set(getattr(web_ctx.builder(), "_sale_lot_ids", None) or ()) | set(off_now9)):
                    return self._send(400, {"ok": False, "error": "세일 연결 목록에 없는 로트"})
                off9 = body.get("off")
                if not isinstance(off9, bool):
                    return self._send(400, {"ok": False, "error": "off 는 true/false"})
                prefs["sale_link_off"] = [x for x in off_now9 if x != lot9] + ([lot9] if off9 else [])
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                return self._send(200, {"ok": True, "lot": lot9, "off": off9})
            if path == "/api/xfer_link":
                dep9 = str(body.get("dep") or "")
                off_now9 = [str(x) for x in (prefs.get("xfer_link_off") or [])]
                known9 = set(getattr(web_ctx.builder(), "_xfer_links_all", None) or {}) | set(off_now9)
                if not dep9 or len(dep9) > 160 or dep9 not in known9:
                    return self._send(400, {"ok": False, "error": "연결 목록에 없는 입금"})
                off9 = body.get("off")
                if not isinstance(off9, bool):
                    return self._send(400, {"ok": False, "error": "off 는 true/false"})
                lst9 = [x for x in off_now9 if x != dep9] + ([dep9] if off9 else [])
                prefs["xfer_link_off"] = lst9
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                return self._send(200, {"ok": True, "dep": dep9, "off": off9})
            if path == "/api/plan":
                key = str(body.get("key") or "")
                if not key:
                    return self._send(400, {"error": "key 필요"})
                for f9 in ("target", "stop"):
                    v9 = body.get(f9)
                    if v9 in (None, ""):
                        continue
                    try:
                        v9 = float(v9)
                    except (TypeError, ValueError):
                        return self._send(400, {"error": f"{f9} 숫자 필요"})
                    if not (-float("inf") < v9 < float("inf")):
                        return self._send(400, {"error": f"{f9} 유한수 필요"})
                    body[f9] = v9
                if len(key) > 120:
                    return self._send(400, {"error": "key 는 120자 이하"})
                for f9, lim9 in (("memo", 2000), ("src", 40), ("venue", 120)):
                    v9 = body.get(f9)
                    if v9 is not None and (not isinstance(v9, str) or len(v9) > lim9):
                        return self._send(400, {"error": f"{f9} 는 {lim9}자 이하 문자열"})
                if "tags" in body and body["tags"] is not None and (
                        not isinstance(body["tags"], list) or len(body["tags"]) > 20
                        or any(not isinstance(t9, str) or len(t9) > 40 for t9 in body["tags"])):
                    return self._send(400, {"error": "tags 는 40자 이하 문자열 배열(≤20)"})
                old9 = (prefs.get("plans") or {}).get(key) if isinstance(prefs.get("plans"), dict) else None
                old9 = old9 if isinstance(old9, dict) else {}
                tg9 = body["target"] if "target" in body else old9.get("target")
                sp9 = body["stop"] if "stop" in body else old9.get("stop")
                tg9 = None if tg9 in (None, "") else tg9
                sp9 = None if sp9 in (None, "") else sp9
                for f9, v9 in (("목표가", tg9), ("손절선", sp9)):
                    if v9 is not None and (not isinstance(v9, (int, float)) or isinstance(v9, bool) or v9 <= 0):
                        return self._send(400, {"error": f"{f9}는 0보다 커야 해요"})
                if tg9 is not None and sp9 is not None and not sp9 < tg9:
                    return self._send(400, {"error": "손절선은 목표가보다 낮아야 해요(0 < 손절 < 목표)"})
                plans = prefs.setdefault("plans", {})
                if key not in plans and len(plans) >= web_ctx.plans_max():
                    return self._send(413, {"error": f"계획(목표가·메모)은 {web_ctx.plans_max():,}개까지예요 — 안 쓰는 계획을 지운 뒤 다시"})
                ent = plans.setdefault(key, {})
                for f in ("target", "stop", "memo", "src", "venue", "tags"):
                    if f in body:
                        ent[f] = body[f]
                common.atomic_write_json(PREFS_PATH, prefs)
                if not web_ctx.bcall("mpatch", {"plan"}):
                    with web_ctx.builder().lock:
                        web_ctx.builder().cache = None
                self._send(200, {"ok": True})
            elif path in ("/api/ignore", "/api/ignore_bulk"):
                keys = body.get("keys") if path.endswith("_bulk") else [body.get("key")]
                if not isinstance(keys, list) or len(keys) > 1000:
                    return self._send(400, {"error": "keys 는 배열(≤1000)"})
                if any((not isinstance(k, str)) or len(k) > 120 for k in keys):
                    return self._send(400, {"error": "key 는 120자 이하 문자열"})
                ig = prefs.setdefault("ignored", [])
                new9 = {k for k in keys if k} - set(ig)
                if len(ig) + len(new9) > web_ctx.ignored_max():
                    return self._send(413, {"error": f"무시 목록은 {web_ctx.ignored_max():,}개까지예요(지금 {len(ig):,}개) — 저장하지 않았어요"})
                added = 0
                for k in keys:
                    if k and k not in ig:
                        ig.append(k); added += 1
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "added": added, "total": len(ig)})
            elif path == "/api/wallet_alias":
                a_in, n_in = body.get("address"), body.get("alias")
                if not isinstance(a_in, str) or (n_in is not None and not isinstance(n_in, str)):
                    return self._send(400, {"error": "address·alias 는 문자열"})
                addr = a_in.strip()
                alias = (n_in or "").strip()[:40]
                if not addr or len(addr) > 128:
                    self._send(400, {"error": "address 필요"})
                    return
                if any(ord(c) < 32 or ord(c) == 127 for c in alias):
                    return self._send(400, {"error": "지갑 이름은 한 줄(제어문자 없음)"})
                key9 = addr.lower() if addr.startswith("0x") else addr
                al = prefs.get("aliases") if isinstance(prefs.get("aliases"), dict) else {}
                prefs["aliases"] = al
                if alias:
                    import chain_registry as _cr9
                    if key9 not in web_ctx.registered_wallet_keys(web_ctx.builder().cfg) and not web_ctx.alias_addr_re().fullmatch(key9) and not _cr9.key_chain(key9):
                        return self._send(400, {"error": "등록된 지갑이거나 지갑 주소 형식(0x… 40자리 · Solana)이어야 해요"})
                    if key9 not in al and len(al) >= web_ctx.alias_max():
                        return self._send(400, {"error": f"지갑 이름은 {web_ctx.alias_max()}개까지예요 — 안 쓰는 이름을 지운 뒤 다시"})
                    al[key9] = alias
                else:
                    al.pop(key9, None)
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "address": key9, "alias": alias})
            elif path == "/api/cost_override":
                key = str(body.get("key") or ""); mode = str(body.get("mode") or "")
                if not re.fullmatch(r"g\d{1,12}", key) or mode not in ("unit", "market", "clear", "breakeven", "breakeven_clear"):
                    return self._send(400, {"error": "key=g<gid> + mode(unit|market|clear|breakeven|breakeven_clear) 필요"})
                if mode in ("breakeven", "breakeven_clear"):
                    be = prefs.get("cost_breakeven") if isinstance(prefs.get("cost_breakeven"), dict) else {}
                    if mode == "breakeven":
                        last9 = getattr(web_ctx.builder(), "_last_out", None) or {}
                        last9 = last9.get("fields") if isinstance(last9.get("fields"), dict) else last9
                        row9 = next((p9 for p9 in (last9.get("pendings") or ())
                                     if isinstance(p9, dict) and p9.get("gkey") == key and "원가미상 매도" in str(p9.get("kind") or "")), None)
                        def _dq(r9):
                            try:
                                v9 = Decimal(str(r9.get("qtyExact") if r9.get("qtyExact") is not None else r9.get("qty")))
                            except (InvalidOperation, TypeError, ValueError, AttributeError):
                                return None
                            return v9 if v9.is_finite() and v9 >= 0 else None
                        q9 = _dq(row9) if row9 else None
                        if q9 is None or q9 <= 0:
                            return self._send(409, {"error": "이 항목의 원가 미상 매도를 지금 화면에서 찾지 못했습니다 — 새로고침 뒤 다시 눌러 주세요"})
                        done9 = next((d9 for d9 in (last9.get("costDecidedRows") or ()) if isinstance(d9, dict) and d9.get("gkey") == key), None)
                        p9 = (_dq(done9) or Decimal(0)) if done9 else Decimal(0)
                        be[key] = {"until": int(time.time()), "qty": str(p9 + q9)}
                    else:
                        be.pop(key, None)
                    prefs["cost_breakeven"] = be
                    common.atomic_write_json(PREFS_PATH, prefs)
                    with web_ctx.builder().lock:
                        web_ctx.builder().cache = None
                    return self._send(200, {"ok": True, "key": key, "breakeven": be.get(key)})
                ov = prefs.setdefault("cost_overrides", {})
                if mode == "clear":
                    ov.pop(key, None)
                elif mode == "market":
                    ov[key] = {"mode": "market"}
                else:
                    try:
                        unit = float(body.get("value"))
                    except (TypeError, ValueError):
                        return self._send(400, {"error": "value(개당 $) 숫자 필요"})
                    if not (unit > 0) or unit > 1e9:
                        return self._send(400, {"error": "value 범위 오류"})
                    ov[key] = {"mode": "unit", "unit": unit}
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "key": key, "override": ov.get(key)})
            elif path == "/api/fallback_avg":
                if not isinstance(body.get("on"), bool):
                    return self._send(400, {"ok": False, "error": "on 은 true/false"})
                prefs["fallback_avg"] = body["on"]
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "on": prefs["fallback_avg"]})
            elif path == "/api/offchain_self":
                ex9 = body.get("ex")
                if not isinstance(ex9, str) or ex9 not in OFFC_EXCHANGES:
                    return self._send(400, {"ok": False, "error": "ex(" + "|".join(OFFC_EXCHANGES) + ") 필요"})
                if "addr" in body:
                    a9, x9 = body.get("addr"), body.get("excl")
                    if not isinstance(a9, str) or not a9.strip() or len(a9) > 128 or not isinstance(x9, bool):
                        return self._send(400, {"ok": False, "error": "addr(문자열 ≤128) + excl(true/false) 필요"})
                    a9 = xfer_match.norm_addr(a9)
                    ex0 = prefs.get("offchain_self_excl") if isinstance(prefs.get("offchain_self_excl"), dict) else {}
                    cur9 = [str(x) for x in (ex0.get(ex9) if isinstance(ex0.get(ex9), list) else [])]
                    known9 = set(((getattr(web_ctx.builder(), "_offc_addrs", None) or {}).get(ex9)) or ()) if x9 else set(cur9)
                    if a9 not in known9:
                        return self._send(400, {"ok": False, "error": ("이 거래소의 오프체인 출금 받는 주소 목록에 없는 주소" if x9
                                                                       else "제외 목록에 없는 주소")})
                    lst9 = [x for x in cur9 if x != a9] + ([a9] if x9 else [])
                    ex0 = {k9: v9 for k9, v9 in ex0.items() if k9 in OFFC_EXCHANGES and isinstance(v9, list) and k9 != ex9}
                    if lst9:
                        ex0[ex9] = lst9
                    prefs["offchain_self_excl"] = ex0
                    common.atomic_write_json(PREFS_PATH, prefs)
                    with web_ctx.builder().lock:
                        web_ctx.builder().cache = None
                    return self._send(200, {"ok": True, "ex": ex9, "addr": a9, "excl": x9})
                on9 = body.get("on")
                if not isinstance(on9, bool):
                    return self._send(400, {"ok": False, "error": "on(true/false) 필요"})
                oc9 = prefs.get("offchain_self") if isinstance(prefs.get("offchain_self"), dict) else {}
                oc9 = {k9: v9 for k9, v9 in oc9.items() if k9 in OFFC_EXCHANGES and isinstance(v9, bool)}
                oc9[ex9] = on9
                prefs["offchain_self"] = oc9
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "ex": ex9, "on": on9})
            elif path == "/api/first_seen_px":
                if "note" in body:
                    if body.get("note") is not True:
                        return self._send(400, {"ok": False, "error": "note 는 true"})
                    prefs["first_seen_note"] = int(time.time())
                    common.atomic_write_json(PREFS_PATH, prefs)
                    if not web_ctx.bcall("mpatch", {"fsnote"}):
                        with web_ctx.builder().lock:
                            web_ctx.builder().cache = None
                    return self._send(200, {"ok": True, "note": True})
                if not isinstance(body.get("on"), bool):
                    return self._send(400, {"ok": False, "error": "on 은 true/false"})
                prefs["first_seen_px"] = body["on"]
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "on": prefs["first_seen_px"]})
            elif path == "/api/gas_in_cost":
                if not isinstance(body.get("on"), bool):
                    return self._send(400, {"ok": False, "error": "on 은 true/false"})
                prefs["gas_in_cost"] = body["on"]
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "on": prefs["gas_in_cost"]})
            elif path == "/api/review_len":
                kind9, len9 = body.get("kind"), body.get("len")
                if kind9 not in ("daily", "weekly") or len9 not in REVIEW_LEN_KEYS:
                    return self._send(400, {"ok": False, "error": "kind(daily|weekly) + len(short|normal|long) 필요"})
                rl9 = prefs.get("review_len") if isinstance(prefs.get("review_len"), dict) else {}
                prefs["review_len"] = dict(rl9, **{kind9: len9})
                common.atomic_write_json(PREFS_PATH, prefs)
                if not web_ctx.bcall("mpatch", {"review"}):
                    with web_ctx.builder().lock:
                        web_ctx.builder().cache = None
                self._send(200, {"ok": True, "kind": kind9, "len": len9, "reviewLen": review_len_eff(prefs)})
            elif path == "/api/review_pause":
                if not isinstance(body.get("on"), bool):
                    return self._send(400, {"ok": False, "error": "on 은 true/false"})
                prefs["review_pause"] = {"on": body["on"], "at": int(time.time())}
                common.atomic_write_json(PREFS_PATH, prefs)
                if not web_ctx.bcall("mpatch", {"review"}):
                    with web_ctx.builder().lock:
                        web_ctx.builder().cache = None
                self._send(200, {"ok": True, "reviewPause": review_pause_eff(prefs)})
            elif path == "/api/review_fill":
                ord9, par9 = body.get("order"), body.get("parallel")
                if review_progress is None or ord9 not in review_progress.FILL_ORDERS or isinstance(par9, bool) \
                        or not isinstance(par9, int) or par9 not in review_progress.FILL_PARALLEL:
                    return self._send(400, {"ok": False, "error": "order(recent|oldest) + parallel(1|3) 필요"})
                prefs["review_fill"] = {"order": ord9, "parallel": par9}
                common.atomic_write_json(PREFS_PATH, prefs)
                if not web_ctx.bcall("mpatch", {"review"}):
                    with web_ctx.builder().lock:
                        web_ctx.builder().cache = None
                self._send(200, {"ok": True, "reviewFill": review_progress.fill_eff(prefs["review_fill"])})
            elif path == "/api/chain_auto_off":
                code9, out9 = web_ctx.chain_auto_off_save(prefs, body)
                self._send(code9, out9)
            elif path == "/api/dust_threshold":
                try:
                    v9 = float(body.get("usd"))
                except (TypeError, ValueError):
                    self._send(400, {"error": "usd 숫자 필요"})
                    return
                prefs["dust_usd"] = max(0.0, min(v9, 1e6))
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "usd": prefs["dust_usd"]})
            elif path == "/api/risk_override":
                key = str(body.get("key") or "")
                verdict = str(body.get("verdict") or "")
                if not re.fullmatch(r"g\d{1,12}", key) or \
                        verdict not in ("visible", "spam", "clear"):
                    return self._send(400, {"error": "key=g<gid> + verdict(visible|spam|clear) 필요"})
                ro = prefs.setdefault("risk_overrides", {})
                if verdict == "clear":
                    ro.pop(key, None)
                else:
                    ro[key] = verdict
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "key": key, "verdict": verdict})
            elif path == "/api/genuine_token":
                ch15 = str(body.get("chain") or "").strip().lower()
                ca15 = str(body.get("ca") or "").strip()
                on15 = body.get("on", True)
                if not isinstance(on15, bool) or not re.fullmatch(r"[a-z0-9_-]{1,32}", ch15) or not (
                        (ch15 != "sol" and re.fullmatch(r"0[xX][0-9a-fA-F]{40}", ca15))
                        or (ch15 == "sol" and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", ca15))):
                    return self._send(400, {"error": "chain + ca(컨트랙트 주소) + on(true|false) 필요"})
                ca15 = ca15 if ch15 == "sol" else ca15.lower()
                sym15 = (getattr(web_ctx.builder(), "_unv_pairs", None) or {}).get((ch15, ca15))
                if on15 and sym15 is None:
                    return self._send(400, {"error": "지금 '확인 필요'로 보이는 토큰 컨트랙트만 등록할 수 있어요"})
                try:
                    changed15 = spamguard.set_user_genuine(ch15, ca15, sym15 or "", on15)
                except ValueError as e15:
                    return self._send(409, {"error": str(e15)})
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "chain": ch15, "ca": ca15, "on": on15, "changed": changed15})
            elif path == "/api/src_whitelist":
                raw15 = str(body.get("address") or "").strip()
                if re.fullmatch(r"0[xX][0-9a-fA-F]{40}", raw15):
                    addr = raw15.lower()
                elif re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", raw15):
                    addr = raw15
                else:
                    return self._send(400, {"error": "address 형식 오류 (0x40hex/base58)"})
                rm9 = body.get("remove", False)
                if not isinstance(rm9, bool):
                    return self._send(400, {"error": "remove 는 true/false"})
                wl = prefs.setdefault("src_whitelist", [])
                if rm9:
                    prefs["src_whitelist"] = [a for a in wl if a != addr]
                elif addr not in wl:
                    if len(wl) >= web_ctx.src_wl_max():
                        return self._send(413, {"error": f"발신 화이트리스트는 {web_ctx.src_wl_max():,}개까지예요 — 안 쓰는 주소를 지운 뒤 다시"})
                    wl.append(addr)
                common.atomic_write_json(PREFS_PATH, prefs)
                with web_ctx.builder().lock:
                    web_ctx.builder().cache = None
                self._send(200, {"ok": True, "whitelist": prefs["src_whitelist"]})
            else:
                self._send(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
            self._gone_or_500("POST", path, e)
        except (Exception, SystemExit) as e:
            log.warning("POST %s 실패: %s", path, e, exc_info=True)
            try:
                self._send(500, self._err500_body(e))
            except Exception:
                pass
        finally:
            if locked:
                web_ctx.prefs_lock().release()

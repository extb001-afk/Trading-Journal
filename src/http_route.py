from __future__ import annotations
import logs
import coverage_limits
import db as dbm
import health
import http_post_prefs
import json
import login_auth
import onboarding
import ops_requests
import os
import re
import reqclass
import urllib.request
import web_ctx
import wow
from http_assets import WEB_DIR
from http_assets import _ui_route
import logging

log = logging.getLogger('tj-web')


OPS_PREFIX = "/api/ops/"


def post_routes():
    nolock = {
        "/api/flow_register": http_post_prefs.post_flow_register,
        "/api/other_assets/save": http_post_prefs.post_other_assets,
        "/api/other_assets/delete": http_post_prefs.post_other_assets,
        "/api/nft/prefs": http_post_prefs.post_nft_prefs,
        "/api/receipt_eval": http_post_prefs.post_receipt_eval,
        "/api/day_memo": http_post_prefs.post_day_memo,
        "/api/alert_test": http_post_prefs.post_alert_test,
        "/api/wd_dest_register": http_post_prefs.post_wd_dest_register,
        "/api/health/ack": http_post_prefs.post_health_ack,
        "/api/health/restore": http_post_prefs.post_health_ack,
        "/api/review/fill": http_post_prefs.post_review_fill_run,
    }
    locked = {
        "/api/alert_prefs": http_post_prefs.post_alert_prefs,
        "/api/outflow_resolve": http_post_prefs.post_outflow_resolve,
        "/api/backfill_request": http_post_prefs.post_backfill_request,
        "/api/sale_link": http_post_prefs.post_sale_link,
        "/api/xfer_link": http_post_prefs.post_xfer_link,
        "/api/plan": http_post_prefs.post_plan,
        "/api/ignore": http_post_prefs.post_ignore,
        "/api/ignore_bulk": http_post_prefs.post_ignore,
        "/api/wallet_alias": http_post_prefs.post_wallet_alias,
        "/api/cost_override": http_post_prefs.post_cost_override,
        "/api/fallback_avg": http_post_prefs.post_fallback_avg,
        "/api/offchain_self": http_post_prefs.post_offchain_self,
        "/api/first_seen_px": http_post_prefs.post_first_seen_px,
        "/api/kr_deemed": http_post_prefs.post_kr_deemed,
        "/api/gas_in_cost": http_post_prefs.post_gas_in_cost,
        "/api/review_len": http_post_prefs.post_review_len,
        "/api/review_pause": http_post_prefs.post_review_pause,
        "/api/review_fill": http_post_prefs.post_review_fill,
        "/api/chain_auto_off": http_post_prefs.post_chain_auto_off,
        "/api/dust_threshold": http_post_prefs.post_dust_threshold,
        "/api/risk_override": http_post_prefs.post_risk_override,
        "/api/genuine_token": http_post_prefs.post_genuine_token,
        "/api/src_whitelist": http_post_prefs.post_src_whitelist,
    }
    return nolock, locked


_NOLOCK, _LOCKED = post_routes()


class RouteMixin:

    def do_GET(self):
        path, _, query = self.path.partition("?")
        reqclass.mark_conn(self)
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
                except Exception as e9:   # noqa: BLE001 [boundary]
                    log.warning("비교선(안 팔았다면) 계산 실패: %s", logs.safe_err(e9)[:120])
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
                    d9 = logs.scrub_secrets(d9)[0]
                self._send(200, {"ok": True, "data": d9} if isinstance(d9, dict) else {"ok": False, "error": "수집 한계를 아직 만들지 못했어요"})
            elif path == "/api/health":
                try:
                    import version as version9
                    ver9 = version9.app_version()
                except Exception:   # noqa: BLE001 [fallback]
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
        except (Exception, SystemExit) as e:   # noqa: BLE001 [boundary]
            log.warning("GET %s 실패: %s", path, e, exc_info=True)
            try:
                self._send(500, self._err500_body(e))
            except Exception:  # noqa: BLE001 [optional]
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
        except Exception:   # noqa: BLE001 [cleanup]
            log.debug("%s %s 상대가 끊음: %s", method, path, type(e).__name__)
            return
        log.warning("%s %s 실패: %s", method, path, e, exc_info=(type(e), e, e.__traceback__))

    def _err500_body(self, e):
        return {"error": f"처리 중 오류({type(e).__name__}) — tj-web 로그를 확인하세요"}

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        reqclass.mark_conn(self)
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
            fn = _NOLOCK.get(path)
            if fn is not None:
                return fn(self, path, body)
            if path.startswith(OPS_PREFIX):
                return self._ops_post(path, body)
            web_ctx.prefs_lock().acquire()
            locked = True
            prefs = web_ctx.builder().prefs()
            fn = _LOCKED.get(path)
            if fn is None:
                return self._send(404, {"error": "not found"})
            return fn(self, path, body, prefs)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
            self._gone_or_500("POST", path, e)
        except (Exception, SystemExit) as e:  # noqa: BLE001 [boundary]
            log.warning("POST %s 실패: %s", path, e, exc_info=True)
            try:
                self._send(500, self._err500_body(e))
            except Exception:  # noqa: BLE001 [optional]
                pass
        finally:
            if locked:
                web_ctx.prefs_lock().release()

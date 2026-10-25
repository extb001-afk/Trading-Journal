from __future__ import annotations
import logs
import acct_norm
import day_memo
import demo_data
import gzip
import histcurve
import json
import login_auth
import onboarding
import os
import other_assets
import re
import reqclass
import search_index
import sellchart
import time
import urllib.request
import web_ctx
import websnap
import wow2
from datetime import datetime
from http_assets import V2_DIR
from http_assets import _asset
from http_assets import CSP_HEADERS, v2_csp
from view_builder import StateBuilder
from view_common import CHAIN_NAME
from timeutil import KST
from view_evals import BUY_EVALS
from view_evals import SELL_EVALS
from view_hero import _HERO_HTML
from view_hero import _HERO_HTML_LOCK
from view_hero import _hero_ok
import logging

log = logging.getLogger('tj-web')


V2_INDEX_CACHE = "private, no-store"


class GetMixin:

    def _send_asset(self, fpath, ctype, query=""):
        if ctype == "font/woff2":
            with open(fpath, "rb") as f:
                raw = f.read()
            return self._send_bytes(200, raw, None, ctype, etag='W/"' + os.path.basename(fpath)[:-6] + '"', cache="private, max-age=31536000, immutable")
        a = _asset(fpath)
        if os.path.normpath(fpath) == os.path.normpath(os.path.join(V2_DIR, "index.html")):
            return self._send_v2_index(a)
        v = urllib.parse.parse_qs(query).get("v", [""])[0]
        cache = "private, max-age=31536000, immutable" if (v and v == a["hash"]) else "private, no-cache"
        self._send_bytes(200, a["raw"], a["gz"], ctype, etag=a["etag"], cache=cache)

    def _send_v2_index(self, a):
        b = web_ctx.builder()
        snap = getattr(getattr(b, "snaps", None), "cur", None) if b is not None else None
        hero = getattr(snap, "hero", None) if snap is not None else None
        csp = tuple((name, value) for name, value in zip(CSP_HEADERS, v2_csp(a["raw"], a["hash"])) if value)
        if hero and any(c.strip() == "tj_v2_rand=1" for raw9 in (self.headers.get_all("Cookie") or []) for c in raw9.split(";")):
            hero = None
        if not hero or not _hero_ok(b, snap) or b"<!--HERO-->" not in a["raw"]:
            return self._send_bytes(200, a["raw"], a["gz"], "text/html; charset=utf-8", etag=a["etag"], cache=V2_INDEX_CACHE, extra=csp)
        k9 = (a["hash"], snap.ver)
        with _HERO_HTML_LOCK:
            m9 = _HERO_HTML.get(k9)
        if m9 is None:
            js = json.dumps(hero, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").encode()
            raw = a["raw"].replace(b"<!--HERO-->", b'<script id="tjHero" type="application/json">' + js + b"</script>", 1)
            m9 = (raw, websnap.gz(raw), f'W/"{a["hash"]}-{snap.ver[:8]}"')
            with _HERO_HTML_LOCK:
                _HERO_HTML.clear()
                _HERO_HTML[k9] = m9
        self._send_bytes(200, m9[0], m9[1], "text/html; charset=utf-8", etag=m9[2], cache=V2_INDEX_CACHE, extra=csp)

    def _send_state_v2(self, query):
        qs9 = urllib.parse.parse_qs(query)
        since = qs9.get("since", [""])[0][:64]
        if since and not self._VER_RE.fullmatch(since):
            since = ""
        slim9 = qs9.get("slim", [""])[0] == "1"
        nd9 = slim9 and qs9.get("nd", [""])[0] == "1"
        snap = web_ctx.builder().snapshot()
        snaps9 = web_ctx.builder().snaps
        if since and hasattr(snaps9, "hold"):
            snaps9.hold(since)
        if since and since == snap.ver:
            web_ctx.builder().snaps.note_served(snap.ver)
            body = websnap.dumps({"v": snap.ver, "b": since, "same": 1})
            return self._send_bytes(200, body, None, extra=(("X-TJ-Kind", "same"), ("X-TJ-Ver", snap.ver)))
        if since and not nd9:
            dg = web_ctx.builder().snaps.delta_gz(since, target=snap)
            if dg:
                web_ctx.builder().snaps.note_served(snap.ver)
                hdr = (("X-TJ-Kind", "delta"), ("X-TJ-Ver", snap.ver))
                if self._gzip_ok():
                    return self._send_bytes(200, b"", dg, extra=hdr)
                return self._send_bytes(200, gzip.decompress(dg), None, extra=hdr)
        web_ctx.builder().snaps.note_served(snap.ver)
        if hasattr(snaps9, "pin"):
            snaps9.pin(snap.ver)
        if slim9 and snap.slim_gz is not None and snap.parts_gz:
            hdr = (("X-TJ-Kind", "slim"), ("X-TJ-Ver", snap.ver), ("X-TJ-Parts", ",".join(websnap.PARTS)))
            if self._gzip_ok():
                return self._send_bytes(200, b"", snap.slim_gz, extra=hdr)
            return self._send_bytes(200, gzip.decompress(snap.slim_gz), None, extra=hdr)
        self._send_bytes(200, snap.raw, snap.gz, etag=f'W/"{snap.ver}"',
                         extra=(("X-TJ-Kind", "full"), ("X-TJ-Ver", snap.ver)))

    _VER_RE = re.compile(r"[0-9a-f]{16}")

    def _send_part(self, query):
        qs9 = urllib.parse.parse_qs(query)
        name = qs9.get("name", [""])[0]
        ver = qs9.get("v", [""])[0]
        if name not in websnap.PARTS or not self._VER_RE.fullmatch(ver):
            return self._send(400, {"ok": False, "error": "name(ev|oft)·v(버전) 필요"})
        web_ctx.builder()._last_client = time.time()
        g9 = web_ctx.builder().snaps.part_gz(ver, name)
        if g9 is None:
            return self._send(410, {"ok": False, "stale": 1, "error": "그 버전 조각이 없어요 — 상태를 다시 받으세요"})
        etag = f'W/"{ver}-{name}"'
        if self._gzip_ok():
            return self._send_bytes(200, b"", g9, etag=etag, cache="private, no-store", extra=(("X-TJ-Ver", ver),))
        return self._send_bytes(200, gzip.decompress(g9), None, etag=etag, cache="private, no-store", extra=(("X-TJ-Ver", ver),))

    _DAY_RE = re.compile(r"20\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")

    @staticmethod
    def _max_age(query):
        v = urllib.parse.parse_qs(query or "").get("max_age", [""])[0]
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return min(86400.0, max(5.0, f)) if f == f else None

    def _send_day_events(self, query):
        qs = urllib.parse.parse_qs(query)
        one = (qs.get("date") or [""])[0].strip()
        d_from = one or (qs.get("from") or [""])[0].strip() or "2000-01-01"
        d_to = one or (qs.get("to") or [""])[0].strip() or "2099-12-31"
        if not (self._DAY_RE.fullmatch(d_from) and self._DAY_RE.fullmatch(d_to)) or d_from > d_to:
            return self._send(400, {"ok": False, "error": "date(또는 from·to)는 YYYY-MM-DD"})
        lim9, off9 = (qs.get("limit") or [""])[0].strip(), (qs.get("offset") or [""])[0].strip()
        if (lim9 and not lim9.isdigit()) or (off9 and not off9.isdigit()) or len(lim9) > 7 or len(off9) > 9:
            return self._send(400, {"ok": False, "error": "limit·offset 은 0 이상의 정수"})
        if not lim9 and not any((qs.get(k) or [""])[0].strip() for k in ("date", "from", "to")):
            lim9 = str(StateBuilder.DAY_EV_LIMIT_DEFAULT)
        ma9 = self._max_age(query)
        if ma9 is not None and not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        web_ctx.builder().snapshot() if ma9 is None else web_ctx.builder().snapshot(max_age=ma9)
        body = (web_ctx.builder().day_events(d_from, d_to) if not lim9 else
                web_ctx.builder().day_events(d_from, d_to, limit=int(lim9), offset=int(off9) if off9 else 0))
        if body is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        if one:
            body["date"] = one
        self._send(200, body)

    _YM_RE = re.compile(r"20\d\d-(0[1-9]|1[0-2])")

    def _send_tax_rows(self, query):
        qs = urllib.parse.parse_qs(query)
        ym = (qs.get("ym") or [""])[0].strip()
        sym = (qs.get("sym") or [""])[0].strip()
        off = (qs.get("offset") or ["0"])[0].strip()
        if not self._YM_RE.fullmatch(ym) or len(sym) > 120 or not off.isdigit() or len(off) > 7:
            return self._send(400, {"ok": False, "error": "ym(YYYY-MM) 필요 · sym(선택) · offset(0 이상 정수)"})
        web_ctx.builder().snapshot()
        body = web_ctx.builder().tax_rows(ym, sym, int(off))
        if body is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "명세 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    def _send_curve_hist(self, query):
        qs = urllib.parse.parse_qs(query)
        r9 = (qs.get("range") or ["all"])[0].strip()
        if r9 not in ("90", "180", "365", "all"):
            return self._send(400, {"ok": False, "error": "range = 90 | 180 | 365 | all"})
        code9, body9 = histcurve.HIST.view(None if r9 == "all" else int(r9))
        self._send(code9, body9)

    def _send_receipt(self, query):
        qs = urllib.parse.parse_qs(query)
        d9 = (qs.get("date") or [""])[0].strip()
        sym = (qs.get("sym") or [""])[0].strip()
        if not self._DAY_RE.fullmatch(d9) or not sym or len(sym) > 120:
            return self._send(400, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"})
        try:
            datetime.strptime(d9, "%Y-%m-%d")
        except ValueError:
            return self._send(400, {"ok": False, "error": "date는 유효한 YYYY-MM-DD 날짜여야 합니다"})
        web_ctx.builder().snapshot()
        body = web_ctx.builder().receipt(d9, sym)
        if body is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    def _send_fut_receipt(self, query):
        qs = urllib.parse.parse_qs(query)
        d9 = (qs.get("date") or [""])[0].strip()
        if not self._DAY_RE.fullmatch(d9):
            return self._send(400, {"ok": False, "error": "date(YYYY-MM-DD) 필요"})
        try:
            datetime.strptime(d9, "%Y-%m-%d")
        except ValueError:
            return self._send(400, {"ok": False, "error": "date는 유효한 YYYY-MM-DD 날짜여야 합니다"})
        fn9 = getattr(web_ctx.builder(), "fut_receipt", None)
        if fn9 is None:
            return self._send(200, {"ok": True, "empty": True, "date": d9})
        web_ctx.builder().snapshot()
        body = fn9(d9)
        if body is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    def _send_att_detail(self, query):
        qs = urllib.parse.parse_qs(query)
        g9 = lambda k: (qs.get(k) or [""])[0].strip()   # noqa: E731
        lo9, hi9 = g9("from") or g9("date"), g9("to") or g9("date")
        if not self._DAY_RE.fullmatch(lo9) or not self._DAY_RE.fullmatch(hi9):
            return self._send(400, {"ok": False, "error": "from·to(또는 date) = YYYY-MM-DD 필요"})
        try:
            a9, b9 = datetime.strptime(lo9, "%Y-%m-%d"), datetime.strptime(hi9, "%Y-%m-%d")
        except ValueError:
            return self._send(400, {"ok": False, "error": "날짜는 유효한 YYYY-MM-DD 여야 합니다"})
        if b9 < a9 or (b9 - a9).days > 40:
            return self._send(400, {"ok": False, "error": "기간은 하루~41일"})
        fn9 = getattr(web_ctx.builder(), "att_detail", None)
        if fn9 is None:
            return self._send(200, {"ok": True, "days": {}})
        web_ctx.builder().snapshot()
        body = fn9(lo9, hi9, lite=g9("lite") == "1")
        body = {k: v for k, v in body.items() if k != "days"} if g9("frz") == "1" and isinstance(body, dict) else body
        if body is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "분해 재료를 만드는 중 — 잠시 뒤 다시 시도하세요"})
        data9 = json.dumps(body, ensure_ascii=False).encode()
        if len(data9) > getattr(StateBuilder, "ATT_DET_BYTES", 6_000_000):
            return self._send(413, {"ok": False, "error": "상세가 너무 커요 — 기간을 줄여 주세요"})
        self._send(200, data9)

    _IV_OK = ("1m", "5m")

    _AFTER_OK = ("1h", "6h", "24h")

    def _chart_args(self, src, fut_ok=False):
        if not isinstance(src, dict):
            return None, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"}
        g = lambda k, d="": (src.get(k) if isinstance(src.get(k), str) else d)
        d9, sym = (g("date") or "").strip(), (g("sym") or "").strip()
        iv, after, venue = g("iv", "5m") or "5m", g("after", "1h") or "1h", (g("venue") or "").strip() or None
        side, bvenue = g("side", "sell") or "sell", (g("bvenue") or "").strip() or None
        if side not in (("sell", "buy", "fut") if fut_ok else ("sell", "buy")) or (src.get("side") is not None and not isinstance(src.get("side"), str)) \
                or (bvenue is not None and len(bvenue) > 200):
            return None, {"ok": False, "error": "side = sell|buy" + ("|fut" if fut_ok else "") + " · bvenue ≤ 200자"}
        if not self._DAY_RE.fullmatch(d9) or not sym or len(sym) > 120:
            return None, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"}
        try:
            datetime.strptime(d9, "%Y-%m-%d")
        except ValueError:
            return None, {"ok": False, "error": "date는 유효한 YYYY-MM-DD 날짜여야 합니다"}
        if iv not in self._IV_OK or after not in self._AFTER_OK or (venue is not None and len(venue) > 200):
            return None, {"ok": False, "error": "iv = 1m|5m · after = 1h|6h|24h · venue ≤ 200자"}
        return {"date": d9, "sym": sym, "iv": iv, "after": after, "venue": venue, "side": side, "bvenue": bvenue, "bg": g("bg") == "1"}, None

    def _send_receipt_chart(self, query):
        if not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        qs = urllib.parse.parse_qs(query)
        a9, err = self._chart_args({k: v[0] for k, v in qs.items() if v}, fut_ok=True)
        if err:
            return self._send(400, err)
        if a9.get("bg") and a9["side"] in ("sell", "buy") and not onboarding.DEMO and not (
                login_auth._internal_ok(self) or (not login_auth.S.enabled and reqclass.direct_loopback(self))):
            return self._send(403, {"ok": False, "error": "봉 미리 받기는 내부 요청만 허용합니다"})
        web_ctx.builder().snapshot()
        body, st9 = web_ctx.builder().chart_request(a9["date"], a9["sym"], a9["iv"], a9["after"], a9["venue"], side=a9["side"], bvenue=a9["bvenue"],
                                          bg=bool(a9.get("bg")) and a9["side"] in ("sell", "buy"))
        if st9 != "ok":
            return self._send(202, {"ok": True, "status": st9, "retryAfter": 3,
                                    "message": "차트를 준비하는 중이에요" if st9 == "preparing" else "다른 차트를 받는 중이에요 — 잠시 뒤 다시"})
        if body is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        if (qs.get("inp") or [""])[0] == "1" and body.get("evalFp"):
            ik9 = (("buy",) if a9["side"] == "buy" else ()) + (a9["date"], body.get("sym"), body["evalFp"])
            inp9 = (getattr(web_ctx.builder(), "_eval_inputs", None) or {}).get(ik9)
            msym9 = web_ctx.memo_driven(a9["date"], body.get("sym"), inp9, a9["side"]) if inp9 is not None else None
            if msym9:
                inp9 = None
            if inp9 is not None:
                body = dict(body, evalInput=inp9)
        self._send(200, body)

    def _send_receipt_list(self, query):
        qs = urllib.parse.parse_qs(query)
        a9, b9 = (qs.get("from") or [""])[0].strip(), (qs.get("to") or ["2099-12-31"])[0].strip()
        if not (self._DAY_RE.fullmatch(a9) and self._DAY_RE.fullmatch(b9)) or a9 > b9:
            return self._send(400, {"ok": False, "error": "from·to 는 YYYY-MM-DD"})
        web_ctx.builder().snapshot()
        body = web_ctx.builder().receipt_list(a9, b9)
        if body is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        self._send(200, body)

    def _send_receipt_eval(self, query):
        qs = urllib.parse.parse_qs(query)
        d9 = (qs.get("date") or [""])[0].strip()
        sym = (qs.get("sym") or [""])[0].strip()
        side = (qs.get("side") or ["sell"])[0].strip() or "sell"
        if not self._DAY_RE.fullmatch(d9) or not sym or len(sym) > 120:
            return self._send(400, {"ok": False, "error": "date(YYYY-MM-DD)·sym 필요"})
        if side not in ("sell", "buy"):
            return self._send(400, {"ok": False, "error": "side = sell|buy"})
        st = BUY_EVALS if side == "buy" else SELL_EVALS
        recs = st.get(d9, sym)
        k9 = f"{d9}|{sym}"
        memo9 = web_ctx.day_memo().pending(d9, day_memo.norm_sym(sym) or sym)
        st9 = "running" if (k9 in st.running or memo9) else ("error" if k9 in st.errors else ("done" if recs else "none"))
        day9 = datetime.now(KST).strftime("%Y-%m-%d")
        body = {"ok": True, "date": d9, "sym": sym, "status": st9, "eval": StateBuilder._eval_rec(recs[0], side) if recs else None,
                "history": [{"fp": r.get("fp"), "at": r.get("at"), "score": r.get("score"), "verdict": r.get("verdict")} for r in recs[:10]],
                "budget": st.budget(day9, sellchart.daily_max(web_ctx.builder().cfg, side))}
        if side == "buy":
            body["side"] = "buy"
        if st9 == "error":
            body["error"] = st.errors[k9].get("error")
        self._send(200, body)

    def _oa_view(self):
        q9 = web_ctx.oa_quoter()
        try:
            with other_assets.STORE_LOCK:
                d9 = other_assets.load_store()
        except other_assets.StoreError as e9:
            return {"ok": False, "error": logs.safe_err(e9)}
        bc9 = (getattr(web_ctx.builder(), "cfg", None) or {}).get("brokers")
        return other_assets.view(d9, q9, web_ctx.oa_rate(), bc9 if isinstance(bc9, dict) else {})

    def _send_wow(self, path, query):
        if not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        qs9 = urllib.parse.parse_qs(query or "")
        g9 = lambda k: (qs9.get(k) or [""])[0]   # noqa: E731
        last9 = getattr(web_ctx.builder(), "_last_out", None) or {}
        f9 = last9.get("fields") if isinstance(last9, dict) else None
        bt9 = last9.get("builtAt") if isinstance(last9, dict) and isinstance(f9, dict) else None
        if not isinstance(f9, dict) and onboarding.DEMO:
            try:
                b9 = web_ctx.builder().build() or {}
                f9, bt9 = b9.get("fields"), b9.get("builtAt")
            except Exception:   # noqa: BLE001 [fallback]
                f9 = None
        f9 = f9 if isinstance(f9, dict) else {}
        if not f9:
            bt9 = None
        conn9 = None
        try:
            if path == "/api/search/ask":
                cfg9 = (getattr(web_ctx.builder(), "cfg", None) or {}).get("wow") or {}
                coins9 = sorted({str(c.get("sym") or "").upper() for c in (f9.get("coins") or ()) if isinstance(c, dict) and c.get("sym")})[:800]
                body = wow2.ask(g9("q"), coins=coins9, chains=sorted(CHAIN_NAME), rate=float(f9.get("rate") or acct_norm.DEFAULT_KRW_USD),
                               llm_on=(cfg9.get("ask_llm") is True) and not onboarding.DEMO, llm_cap=int(cfg9.get("ask_llm_daily_max") or 40))
                return self._send(200 if body.get("ok") else 400, body)
            conn9 = demo_data.ledger() if onboarding.DEMO else wow2._ro()
            hist9 = demo_data.DemoHist() if onboarding.DEMO else histcurve.HIST
            if path == "/api/wow/tm":
                kit9 = getattr(hist9, "kit", None) or {}
                now9 = {str(k): float(g.get("lp") or g.get("ov") or 0) for k, g in (kit9.get("groups") or {}).items()}
                body = wow2.tm(g9("date"), hist=None if onboarding.DEMO else hist9, daily=getattr(web_ctx.builder(), "daily", None), dpx=getattr(web_ctx.builder(), "daily_px", None), fields=f9, conn=conn9,
                              chain_names=CHAIN_NAME, now_px=now9)
                if body.get("ok"):
                    body["builtAt"] = bt9
            else:
                body = wow2.flows(f9, conn=conn9, chain_names=CHAIN_NAME, since=g9("since") or None, hist=hist9)
            self._send(200 if body.get("ok") else 400, body)
        except Exception as e9:   # noqa: BLE001 [optional]
            log.warning("감탄 기능 %s 실패: %s", path, type(e9).__name__, exc_info=True)
            self._send(503, {"ok": False, "error": "지금은 만들지 못했어요 — 잠시 뒤 다시"})
        finally:
            if conn9 is not None:
                try:
                    conn9.close()
                except Exception:   # noqa: BLE001 [cleanup]
                    pass

    def _send_search(self, query):
        qs9 = urllib.parse.parse_qs(query or "")
        g9 = lambda k: (qs9.get(k) or [""])[0]   # noqa: E731
        kinds9 = [k for k in g9("kinds").split(",") if k] or None
        req9 = {"q": g9("q")[:search_index.Q_MAX], "kinds": kinds9, "limit": g9("limit") or None,
                "after": g9("after") or None, "before": g9("before") or None, "offset": g9("offset") or None,
                "krw": search_index.krw_rate(g9("krw"))}
        try:
            body = web_ctx.search_pool().run(req9)
            if body is None:
                body = search_index.search(req9["q"], kinds=kinds9, limit=req9["limit"], after=req9["after"], before=req9["before"], offset=req9["offset"], krw=req9["krw"])
        except Exception as e9:   # noqa: BLE001 [fallback]
            log.warning("검색 실패: %s", type(e9).__name__)
            return self._send(503, {"ok": False, "error": "검색하지 못했어요 — 잠시 뒤 다시"})
        self._send(200, body)

    def _send_nft(self, query):
        try:
            v9 = web_ctx.nft_tracker().view()
        except Exception as e9:   # noqa: BLE001 [fallback]
            log.warning("NFT 보기 실패: %s", type(e9).__name__)
            return self._send(503, {"ok": False, "error": "NFT 목록을 만들지 못했어요"})
        self._send(200, v9)

    def _send_other_assets(self, query):
        v9 = self._oa_view()
        self._send(200 if v9.get("ok") else 503, v9)

    def _send_oa_quote(self, query):
        if not onboarding.origin_ok(self, required=False):
            return self._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        t9 =urllib.parse.parse_qs(query or "").get("t", [""])[0]
        if not t9 or len(t9) > 16:
            return self._send(400, {"ok": False, "error": "t(종목 코드) 필요"})
        out9, st9 = web_ctx.oa_quoter().lookup(t9)
        self._send(st9, out9)

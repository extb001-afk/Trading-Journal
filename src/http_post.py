from __future__ import annotations
import alert_prefs
import alert_watch
import logs, paths, statefile
import csrf_gate
import day_memo
import health
import health_ack
import onboarding
import ops_requests
import os
import other_assets
import re
import sellchart
import threading
import time
import web_ctx
from datetime import datetime
from http_state import ALERT_TEST_HOURLY
from http_state import MemoHourly
from http_state import _ALERT_TEST_LOCK
from http_state import _ALERT_TEST_T
from http_state import _OPS_RL
from http_state import _OPS_RL_LOCK
from http_state import _eval_budget_msg
from view_alerts import _append_alert
from view_builder import StateBuilder
from timeutil import KST
from view_evals import BUY_EVALS
from view_evals import DAY_MEMOS
from view_evals import SELL_EVALS
from view_review import review_fill_req_view
from view_review import review_manual_busy
from view_review import review_pause_eff
from view_snapfile import _snapfile_drop
import logging

log = logging.getLogger('tj-web')


class PostMixin:

    def _ops_post(self, path: str, body: dict):
        if not self._write_guard():
            return None
        now9 = time.time()
        with _OPS_RL_LOCK:
            while _OPS_RL and now9 - _OPS_RL[0] > 60:
                _OPS_RL.popleft()
            if len(_OPS_RL) >= 30:
                return self._send(429, {"ok": False, "error": "요청이 너무 많아요 — 잠시 뒤 다시"})
            _OPS_RL.append(now9)
        act = path[len("/api/ops/"):]
        if act == "rebuild_approve":
            sha9 = body.get("report_sha")
            ok9, msg9 = ops_requests.approve(sha9 if isinstance(sha9, str) else "", "web")
        elif act == "rebuild_cancel":
            ok9 = ops_requests.cancel_approve()
            msg9 = "승인 취소" if ok9 else "취소할 승인이 없어요"
        elif act == "poison_replay":
            ids9 = body.get("ids")
            ok9, msg9 = ops_requests.poison_request(ids=ids9 if isinstance(ids9, list) else None, all_=False, by="web")
        elif act == "decimals_resolve":
            ok9, msg9 = ops_requests.decimals_request(body.get("asset_id"), body.get("stored"), body.get("seen"), "web")
        else:
            return self._send(404, {"ok": False, "error": "없는 요청"})
        log.warning("정리 요청(%s): %s — %s", act, "접수" if ok9 else "거절", str(msg9)[:160])
        return self._send(200 if ok9 else 409, {"ok": bool(ok9), ("msg" if ok9 else "error"): msg9, "ops": ops_requests.status()})

    def _review_fill_post(self, body: dict):
        if not self._write_guard():
            return None
        now9 = time.time()
        with _OPS_RL_LOCK:
            while _OPS_RL and now9 - _OPS_RL[0] > 60:
                _OPS_RL.popleft()
            if len(_OPS_RL) >= 30:
                return self._send(429, {"ok": False, "error": "요청이 너무 많아요 — 잠시 뒤 다시"})
            _OPS_RL.append(now9)
        if review_pause_eff(web_ctx.bcall("prefs") or {}).get("on"):
            return self._send(409, {"ok": False, "error": "AI 리뷰 자동 생성 멈춤 중이에요 — 멈춤을 풀고 다시 눌러 주세요"})
        if review_manual_busy():
            return self._send(409, {"ok": False, "error": "지난 리뷰를 이미 쓰는 중이에요 — 끝난 뒤 다시 눌러 주세요"})
        if review_fill_req_view() is not None:
            return self._send(200, {"ok": True, "msg": "이미 요청했어요 — 1분 안에 시작해요"})
        try:
            since9 = (web_ctx.bcall("_backfill_since_view") or {}).get("windowStart")
        except Exception:   # noqa: BLE001 [fallback]
            since9 = None
        if not (isinstance(since9, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", since9)):
            m9 = float(((getattr(web_ctx.builder(), "cfg", None) or {}).get("backfill_months")) or 5)
            since9 = datetime.fromtimestamp(now9 - m9 * 30 * 86400, KST).strftime("%Y-%m-%d")
        try:
            statefile.atomic_write_json(paths.state("review_fill_request.json"), {"since": since9, "weekly": True, "at": int(now9), "by": "web"})
            os.chmod(paths.state("review_fill_request.json"), 0o600)
        except OSError as e:
            return self._send(500, {"ok": False, "error": "요청 파일을 쓰지 못했어요 · " + logs.safe_err(str(e))[:120]})
        log.warning("AI 리뷰 전체 채우기 요청 — %s 부터(tj-review 가 처리)", since9)
        if not web_ctx.bcall("mpatch", {"review"}) and hasattr(web_ctx.builder(), "lock"):
            with web_ctx.builder().lock:
                web_ctx.builder().cache = None
        return self._send(200, {"ok": True, "msg": "요청했어요 — 1분 안에 쓰기 시작해요", "since": since9})

    def _health_ack_post(self, path: str, body: dict):
        if not self._write_guard():
            return None
        now9 = time.time()
        with _OPS_RL_LOCK:
            while _OPS_RL and now9 - _OPS_RL[0] > 60:
                _OPS_RL.popleft()
            if len(_OPS_RL) >= 30:
                return self._send(429, {"ok": False, "error": "요청이 너무 많아요 — 잠시 뒤 다시"})
            _OPS_RL.append(now9)
        chk9, fp9 = body.get("check"), body.get("fp")
        if not isinstance(chk9, str) or not chk9 or len(chk9) > 80 or (path.endswith("/ack") and (not isinstance(fp9, str) or len(fp9) > 64)):
            return self._send(400, {"ok": False, "error": "check(문자열)·fp(문자열) 필요"})
        try:
            ok9, msg9 = health.ack_apply(chk9, fp9, now9) if path.endswith("/ack") else health_ack.restore(chk9)
        except OSError as e9:
            ok9, msg9 = False, f"저장 실패: {type(e9).__name__}"
        log.info("상태 주의 %s(%s): %s — %s", "닫기" if path.endswith("/ack") else "되살리기", chk9[:40], "접수" if ok9 else "거절", str(msg9)[:120])
        return self._send(200 if ok9 else 409, {"ok": bool(ok9), ("msg" if ok9 else "error"): msg9, "health": health.web_view()})

    def _write_guard(self, need_json: bool = True, origin_err: str = "출처(Origin) 확인 실패 — 같은 화면에서만 요청할 수 있습니다") -> bool:
        if not onboarding.origin_ok(self, required=True):
            self._send(403, {"ok": False, "error": origin_err})
            return False
        try:
            good = csrf_gate.check(self)
        except Exception:  # noqa: BLE001 [fallback]
            good = False
        if not good:
            self._send(403, {"ok": False, "error": "CSRF 토큰 불일치 — 페이지를 새로고침하세요"})
            return False
        if need_json and "application/json" not in (self.headers.get("Content-Type") or ""):
            self._send(415, {"ok": False, "error": "JSON 요청만 받습니다"})
            return False
        return True

    def _alert_prefs_post(self, prefs, body):
        if not self._write_guard():
            return
        old9 = prefs.get(alert_prefs.PREF_KEY)
        doc9, err9 = alert_prefs.apply_post(old9, body)
        if err9:
            return self._send(400, {"ok": False, "error": err9})
        if isinstance(old9, dict) and old9.get("v") != alert_prefs.SCHEMA and "alert_prefs_v1" not in prefs:
            prefs["alert_prefs_v1"] = old9
        prefs[alert_prefs.PREF_KEY] = doc9
        statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
        log.info("알림 설정 저장: %s", alert_prefs.match_preset(doc9))
        self._send(200, web_ctx.alert_view(prefs))

    def _alert_test_post(self, body):
        if not self._write_guard():
            return
        cat9 = body.get("cat")
        if not isinstance(cat9, str) or cat9 not in alert_prefs.CAT:
            return self._send(400, {"ok": False, "error": "cat(알림 카테고리) 필요"})
        if not web_ctx.tg_connected():
            return self._send(409, {"ok": False, "error": "텔레그램이 연결돼 있지 않아요 — 설정 › 연결 · 키에서 먼저 연결하세요"})
        now9 = time.time()
        with _ALERT_TEST_LOCK:
            _ALERT_TEST_T[:] = [x for x in _ALERT_TEST_T if now9 - x[0] < 3600]
            if any(c9 == cat9 and now9 - t9 < 60 for t9, c9 in _ALERT_TEST_T):
                return self._send(429, {"ok": False, "error": "같은 종류 테스트는 1분에 한 번이에요 — 잠시 뒤 다시"})
            if len(_ALERT_TEST_T) >= ALERT_TEST_HOURLY:
                left9 = max(1, int((3600 - (now9 - min(t9 for t9, _c in _ALERT_TEST_T))) // 60) + 1)
                return self._send(429, {"ok": False, "error": f"테스트는 시간당 {ALERT_TEST_HOURLY}통까지예요 — 약 {left9}분 뒤 다시"})
            _ALERT_TEST_T.append((now9, cat9))
        _append_alert(alert_watch.test_line(cat9))
        self._send(200, {"ok": True, "cat": cat9, "queued": True})

    def _nft_post(self, body):
        if not self._write_guard():
            return
        v9, err9 = web_ctx.nft_tracker().apply_prefs(body)
        if err9:
            return self._send(err9[0], {"ok": False, "error": err9[1]})
        self._send(200, v9)

    def _oa_post(self, path, body):
        if not self._write_guard():
            return
        q9 = web_ctx.oa_quoter()
        with other_assets.STORE_LOCK:
            try:
                d9 = other_assets.load_store()
            except other_assets.StoreError as e9:
                return self._send(503, {"ok": False, "error": logs.safe_err(e9)})
            if path.endswith("/delete"):
                ok9, err9 = other_assets.apply_delete(d9, body.get("id"))
                if not ok9:
                    return self._send(err9[0], {"ok": False, "error": err9[1]})
                other_assets.save_store(d9)
                return self._send(200, {"ok": True, "id": body.get("id")})
            it9, err9 = other_assets.apply_save(d9, body)
            if err9:
                return self._send(err9[0], {"ok": False, "error": err9[1]})
            other_assets.save_store(d9)
        try:
            q9.apply_quotes()
        except Exception as e9:   # noqa: BLE001 [optional]
            log.warning("기타 자산 평가 반영 실패: %s", type(e9).__name__)
        if it9.get("auto"):
            q9.wake.set()
        self._send(200, {"ok": True, "id": it9["id"]})

    def _receipt_eval_post(self, body):
        if not self._write_guard():
            return
        a9, err = self._chart_args(body)
        if err:
            return self._send(400, err)
        force = body.get("force", False)
        if not isinstance(force, bool):
            return self._send(400, {"ok": False, "error": "force 는 true/false"})
        buy9 = a9["side"] == "buy"
        ST, side_ko = (BUY_EVALS, "매수") if buy9 else (SELL_EVALS, "매도")
        cap9 = sellchart.daily_max(web_ctx.builder().cfg, a9["side"])
        day9 = datetime.now(KST).strftime("%Y-%m-%d")
        with ST.mu:
            busy9 = bool(ST.running)
            bud9 = ST._budget_read(day9)
        if busy9:
            return self._send(409, {"ok": False, "status": "running", "error": f"다른 {side_ko} 평가가 진행 중이에요 — 끝나면 다시 눌러 주세요"})
        if bud9.get("_bad") or bud9["used"] >= cap9:
            return self._send(429, {"ok": False, "error": _eval_budget_msg(cap9, a9["side"], side_ko)})
        web_ctx.builder().snapshot()
        ch, st9 = web_ctx.builder().chart_request(a9["date"], a9["sym"], a9["iv"], a9["after"], a9["venue"], side=a9["side"], bvenue=a9["bvenue"])
        if st9 != "ok":
            return self._send(202, {"ok": True, "status": "preparing", "retryAfter": 3, "message": "차트를 준비하는 중이에요 — 잠시 뒤 다시 눌러 주세요"})
        if ch is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
        fp9 = ch.get("evalFp")
        ik9 = (("buy",) if buy9 else ()) + (a9["date"], ch.get("sym"), fp9)
        inp = (getattr(web_ctx.builder(), "_eval_inputs", None) or {}).get(ik9) if fp9 else None
        if not inp:
            return self._send(422, {"ok": False, "error": "차트(봉)가 없어 평가할 수 없어요 — " + str(((ch.get("chart") or {}).get("why")) or ch.get("why") or "")})
        sym9 = ch["sym"]
        k9 = f"{a9['date']}|{sym9}"
        old = ST.find(a9["date"], sym9, fp9)
        if old and not force:
            return self._send(200, {"ok": True, "status": "done", "cached": True, "eval": StateBuilder._eval_rec(old, a9["side"])})
        if body.get("auto") is True and (ch.get("autoEval") is False or ch.get("dexLater")):
            return self._send(409, {"ok": False, "auto": False, "error": "이 차트는 자동 평가를 하지 않아요 — 버튼으로 직접 만들 수 있어요"})
        runner9 = None
        msym9 = web_ctx.memo_driven(a9["date"], sym9, inp, a9["side"])
        if msym9:
            if a9["iv"] == "5m" and a9["after"] == "1h" and not a9["venue"] and not a9["bvenue"]:
                if not web_ctx.day_memo().schedule(a9["date"], msym9, reset=False, force=force, side=a9["side"], manual=body.get("auto") is not True):
                    return self._send(429, {"ok": False, "error": "근거 메모 평가 대기 줄이 가득 찼어요 — 잠시 뒤 다시"})
                return self._send(202, {"ok": True, "status": "running", "queued": True, "fp": fp9})
            if web_ctx.day_memo().hour_left() <= 0:
                return self._send(429, {"ok": False, "error": web_ctx.day_memo().HOURLY_MSG.format(n=web_ctx.day_memo().HOURLY_MAX)})
            runner9 = web_ctx.day_memo().runner(f"{side_ko}평가(근거·보기) {a9['date']}|{sym9}")
        with ST.mu:
            if k9 in ST.running or ST.running:
                return self._send(409, {"ok": False, "status": "running", "error": f"다른 {side_ko} 평가가 진행 중이에요 — 끝나면 다시 눌러 주세요"})
            bud9 = ST._budget_read(day9)
            if bud9.get("_bad") or bud9["used"] >= cap9:
                return self._send(429, {"ok": False, "error": _eval_budget_msg(cap9, a9["side"], side_ko)})
            ST.running[k9] = {"since": int(time.time()), "fp": fp9}
            ST.errors.pop(k9, None)
        cfg9 = web_ctx.builder().cfg

        def work():
            try:
                rec, e9 = sellchart.run_eval(ST, cfg9, a9["date"], sym9, fp9, inp, skip_if_fresh=not force, runner=runner9)
                if e9:
                    ST.errors[k9] = {"at": int(time.time()), "error": e9}
            except MemoHourly:
                ST.errors[k9] = {"at": int(time.time()), "error": web_ctx.day_memo().HOURLY_MSG.format(n=web_ctx.day_memo().HOURLY_MAX)}
            except Exception as e9:   # noqa: BLE001 [boundary]
                log.warning("%s 평가 실패(%s): %s", side_ko, k9, e9)
                ST.errors[k9] = {"at": int(time.time()), "error": "평가 중 오류"}
            finally:
                with ST.mu:
                    ST.running.pop(k9, None)
        threading.Thread(target=work, name=f"{'buy' if buy9 else 'sell'}-eval {k9}", daemon=True).start()
        self._send(202, {"ok": True, "status": "running", "fp": fp9})

    def _day_traded(self, d9, s9):
        idx = getattr(web_ctx.builder(), "_day_idx", None)
        if not idx or idx.get("ix") is None:
            return None
        syms = set()
        for _ts, kind, e, meta in (idx["ix"].get(d9) or ()):
            if kind == "hidden" or not isinstance(e, dict):
                continue
            k9 = str(e.get("k") or "")
            if ("매수" in k9 or "매도" in k9) and "평단" not in k9:
                sy = meta[1] if meta is not None else e.get("sym")
                if sy:
                    syms.add(str(sy))
        canon = day_memo.canon_map(syms)
        return any(day_memo.norm_sym(canon.get(x, x)) == s9 or day_memo.norm_sym(x) == s9 for x in syms)

    def _day_memo_post(self, body):
        if not self._write_guard():
            return
        extra9 = set(body) - {"date", "sym", "memo"}
        if extra9:
            return self._send(400, {"ok": False, "error": "모르는 필드: " + ", ".join(sorted(str(x)[:20] for x in extra9))[:120]})
        d9 = day_memo.norm_date(body.get("date"))
        if not d9:
            return self._send(400, {"ok": False, "error": "date 는 유효한 YYYY-MM-DD"})
        if d9 > datetime.now(KST).strftime("%Y-%m-%d"):
            return self._send(400, {"ok": False, "error": "앞날에는 메모를 쓸 수 없어요"})
        s9 = day_memo.norm_sym(body.get("sym"))
        if not s9:
            return self._send(400, {"ok": False, "error": f"sym 은 1~{day_memo.SYM_MAX}자 심볼(공백·특수 구분자 없음)"})
        m9, e9 = day_memo.norm_memo(body.get("memo"))
        if e9:
            return self._send(400, {"ok": False, "error": e9})
        if not onboarding.RL.hit("day_memo", self.DAY_MEMO_RL_N, 60):
            return self._send(429, {"ok": False, "error": "너무 자주 저장했어요 — 잠시 뒤 다시"})
        mm9, err9 = DAY_MEMOS.read()
        if err9:
            return self._send(503, {"ok": False, "error": "근거 메모 파일을 읽지 못해 저장하지 않았어요(" + err9 + ") — 파일을 고친 뒤 다시"})
        k9 = day_memo.key(d9, s9)
        old9 = mm9.get(k9)
        if old9 is None and not m9:
            return self._send(200, {"ok": True, "date": d9, "sym": s9, "memo": "", "at": int(time.time()), "deleted": False, "changed": False})
        if old9 is not None and old9["memo"] == m9:
            return self._send(200, {"ok": True, "date": d9, "sym": s9, "memo": m9, "at": old9["at"], "deleted": False, "changed": False})
        if old9 is None:
            tr9 = self._day_traded(d9, s9)
            if tr9 is None:
                web_ctx.builder().kick_refresh()
                return self._send(503, {"ok": False, "error": "기록 색인을 만드는 중 — 잠시 뒤 다시 시도하세요"})
            if not tr9:
                return self._send(400, {"ok": False, "error": f"{d9} 에 {s9} 매수·매도 기록이 없어요"})
        try:
            rec9 = DAY_MEMOS.put(d9, s9, m9)
        except day_memo.Corrupt as e:
            return self._send(503, {"ok": False, "error": f"근거 메모 파일을 읽지 못해 저장하지 않았어요({logs.safe_err(e)})"})
        except day_memo.TooBig as e:
            return self._send(413, {"ok": False, "error": logs.safe_err(e)})
        except day_memo.Full as e:
            return self._send(409, {"ok": False, "error": logs.safe_err(e)})
        web_ctx.builder().purge_memo_charts(d9, s9)
        if not web_ctx.bcall("mpatch", {"day_memo"}):
            if web_ctx.builder().__dict__.get("_snapfile_on"):
                _snapfile_drop()
            web_ctx.builder().soft_invalidate()
        q9 = False if review_pause_eff(web_ctx.builder().prefs() if web_ctx.builder() is not None else {}).get("on") else web_ctx.day_memo().schedule(d9, s9)
        self._send(200, {"ok": True, "date": d9, "sym": s9, "memo": m9, "at": rec9["at"] if rec9 else int(time.time()),
                         "deleted": not m9, "changed": True, "reeval": bool(q9)})

    DAY_MEMO_RL_N = 30

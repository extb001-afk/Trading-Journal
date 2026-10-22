from __future__ import annotations
import paths
import re
import spamguard
import statefile
import time
import web_ctx
import xfer_match
from decimal import Decimal
from decimal import InvalidOperation
from view_offc import OFFC_EXCHANGES
from view_review import REVIEW_LEN_KEYS
from view_review import review_len_eff
from view_review import review_pause_eff
from view_review import review_progress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

__all__ = ["post_sale_link", "post_xfer_link", "post_plan", "post_ignore", "post_wallet_alias", "post_cost_override", "post_fallback_avg",
           "post_offchain_self", "post_first_seen_px", "post_gas_in_cost", "post_review_len", "post_review_pause", "post_review_fill",
           "post_chain_auto_off", "post_dust_threshold", "post_risk_override", "post_genuine_token", "post_src_whitelist",
           "post_flow_register", "post_other_assets", "post_nft_prefs", "post_receipt_eval", "post_day_memo", "post_alert_test",
           "post_wd_dest_register", "post_health_ack", "post_review_fill_run", "post_alert_prefs", "post_outflow_resolve",
           "post_backfill_request"]


def post_sale_link(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    lot = str(body.get("lot") or "")
    off_now = [str(x) for x in (prefs.get("sale_link_off") or [])]
    if not lot or len(lot) > 160 or lot not in (set(getattr(web_ctx.builder(), "_sale_lot_ids", None) or ()) | set(off_now)):
        return h._send(400, {"ok": False, "error": "세일 연결 목록에 없는 로트"})
    off = body.get("off")
    if not isinstance(off, bool):
        return h._send(400, {"ok": False, "error": "off 는 true/false"})
    prefs["sale_link_off"] = [x for x in off_now if x != lot] + ([lot] if off else [])
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    return h._send(200, {"ok": True, "lot": lot, "off": off})


def post_xfer_link(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    dep = str(body.get("dep") or "")
    off_now = [str(x) for x in (prefs.get("xfer_link_off") or [])]
    known = set(getattr(web_ctx.builder(), "_xfer_links_all", None) or {}) | set(off_now)
    if not dep or len(dep) > 160 or dep not in known:
        return h._send(400, {"ok": False, "error": "연결 목록에 없는 입금"})
    off = body.get("off")
    if not isinstance(off, bool):
        return h._send(400, {"ok": False, "error": "off 는 true/false"})
    lst = [x for x in off_now if x != dep] + ([dep] if off else [])
    prefs["xfer_link_off"] = lst
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    return h._send(200, {"ok": True, "dep": dep, "off": off})


def post_plan(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    key = str(body.get("key") or "")
    if not key:
        return h._send(400, {"error": "key 필요"})
    for field in ("target", "stop"):
        v = body.get(field)
        if v in (None, ""):
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            return h._send(400, {"error": f"{field} 숫자 필요"})
        if not (-float("inf") < v < float("inf")):
            return h._send(400, {"error": f"{field} 유한수 필요"})
        body[field] = v
    if len(key) > 120:
        return h._send(400, {"error": "key 는 120자 이하"})
    for field, lim in (("memo", 2000), ("src", 40), ("venue", 120)):
        v = body.get(field)
        if v is not None and (not isinstance(v, str) or len(v) > lim):
            return h._send(400, {"error": f"{field} 는 {lim}자 이하 문자열"})
    if "tags" in body and body["tags"] is not None and (
            not isinstance(body["tags"], list) or len(body["tags"]) > 20
            or any(not isinstance(t, str) or len(t) > 40 for t in body["tags"])):
        return h._send(400, {"error": "tags 는 40자 이하 문자열 배열(≤20)"})
    old = (prefs.get("plans") or {}).get(key) if isinstance(prefs.get("plans"), dict) else None
    old = old if isinstance(old, dict) else {}
    tg = body["target"] if "target" in body else old.get("target")
    sp = body["stop"] if "stop" in body else old.get("stop")
    tg = None if tg in (None, "") else tg
    sp = None if sp in (None, "") else sp
    for field, v in (("목표가", tg), ("손절선", sp)):
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0):
            return h._send(400, {"error": f"{field}는 0보다 커야 해요"})
    if tg is not None and sp is not None and not sp < tg:
        return h._send(400, {"error": "손절선은 목표가보다 낮아야 해요(0 < 손절 < 목표)"})
    plans = prefs.setdefault("plans", {})
    if key not in plans and len(plans) >= web_ctx.plans_max():
        return h._send(413, {"error": f"계획(목표가·메모)은 {web_ctx.plans_max():,}개까지예요 — 안 쓰는 계획을 지운 뒤 다시"})
    ent = plans.setdefault(key, {})
    for f in ("target", "stop", "memo", "src", "venue", "tags"):
        if f in body:
            ent[f] = body[f]
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    if not web_ctx.bcall("mpatch", {"plan"}):
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
    h._send(200, {"ok": True})


def post_ignore(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    keys = body.get("keys") if path.endswith("_bulk") else [body.get("key")]
    if not isinstance(keys, list) or len(keys) > 1000:
        return h._send(400, {"error": "keys 는 배열(≤1000)"})
    if any((not isinstance(k, str)) or len(k) > 120 for k in keys):
        return h._send(400, {"error": "key 는 120자 이하 문자열"})
    ig = prefs.setdefault("ignored", [])
    new = {k for k in keys if k} - set(ig)
    if len(ig) + len(new) > web_ctx.ignored_max():
        return h._send(413, {"error": f"무시 목록은 {web_ctx.ignored_max():,}개까지예요(지금 {len(ig):,}개) — 저장하지 않았어요"})
    added = 0
    for k in keys:
        if k and k not in ig:
            ig.append(k); added += 1
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "added": added, "total": len(ig)})


def post_wallet_alias(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    a_in, n_in = body.get("address"), body.get("alias")
    if not isinstance(a_in, str) or (n_in is not None and not isinstance(n_in, str)):
        return h._send(400, {"error": "address·alias 는 문자열"})
    addr = a_in.strip()
    alias = (n_in or "").strip()[:40]
    if not addr or len(addr) > 128:
        h._send(400, {"error": "address 필요"})
        return
    if any(ord(c) < 32 or ord(c) == 127 for c in alias):
        return h._send(400, {"error": "지갑 이름은 한 줄(제어문자 없음)"})
    key = addr.lower() if addr.startswith("0x") else addr
    al = prefs.get("aliases") if isinstance(prefs.get("aliases"), dict) else {}
    prefs["aliases"] = al
    if alias:
        import chain_registry as _cr
        if key not in web_ctx.registered_wallet_keys(web_ctx.builder().cfg) and not web_ctx.alias_addr_re().fullmatch(key) and not _cr.key_chain(key):
            return h._send(400, {"error": "등록된 지갑이거나 지갑 주소 형식(0x… 40자리 · Solana)이어야 해요"})
        if key not in al and len(al) >= web_ctx.alias_max():
            return h._send(400, {"error": f"지갑 이름은 {web_ctx.alias_max()}개까지예요 — 안 쓰는 이름을 지운 뒤 다시"})
        al[key] = alias
    else:
        al.pop(key, None)
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "address": key, "alias": alias})


def post_cost_override(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    key = str(body.get("key") or ""); mode = str(body.get("mode") or "")
    if not re.fullmatch(r"g\d{1,12}", key) or mode not in ("unit", "market", "clear", "breakeven", "breakeven_clear"):
        return h._send(400, {"error": "key=g<gid> + mode(unit|market|clear|breakeven|breakeven_clear) 필요"})
    if mode in ("breakeven", "breakeven_clear"):
        be = prefs.get("cost_breakeven") if isinstance(prefs.get("cost_breakeven"), dict) else {}
        if mode == "breakeven":
            last = getattr(web_ctx.builder(), "_last_out", None) or {}
            last = last.get("fields") if isinstance(last.get("fields"), dict) else last
            row = next((p for p in (last.get("pendings") or ())
                         if isinstance(p, dict) and p.get("gkey") == key and "원가미상 매도" in str(p.get("kind") or "")), None)
            def _dq(r):
                try:
                    v = Decimal(str(r.get("qtyExact") if r.get("qtyExact") is not None else r.get("qty")))
                except (InvalidOperation, TypeError, ValueError, AttributeError):
                    return None
                return v if v.is_finite() and v >= 0 else None
            q = _dq(row) if row else None
            if q is None or q <= 0:
                return h._send(409, {"error": "이 항목의 원가 미상 매도를 지금 화면에서 찾지 못했습니다 — 새로고침 뒤 다시 눌러 주세요"})
            done = next((d for d in (last.get("costDecidedRows") or ()) if isinstance(d, dict) and d.get("gkey") == key), None)
            p = (_dq(done) or Decimal(0)) if done else Decimal(0)
            be[key] = {"until": int(time.time()), "qty": str(p + q)}
        else:
            be.pop(key, None)
        prefs["cost_breakeven"] = be
        statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
        return h._send(200, {"ok": True, "key": key, "breakeven": be.get(key)})
    ov = prefs.setdefault("cost_overrides", {})
    if mode == "clear":
        ov.pop(key, None)
    elif mode == "market":
        ov[key] = {"mode": "market"}
    else:
        try:
            unit = float(body.get("value"))
        except (TypeError, ValueError):
            return h._send(400, {"error": "value(개당 $) 숫자 필요"})
        if not (unit > 0) or unit > 1e9:
            return h._send(400, {"error": "value 범위 오류"})
        ov[key] = {"mode": "unit", "unit": unit}
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "key": key, "override": ov.get(key)})


def post_fallback_avg(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    if not isinstance(body.get("on"), bool):
        return h._send(400, {"ok": False, "error": "on 은 true/false"})
    prefs["fallback_avg"] = body["on"]
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "on": prefs["fallback_avg"]})


def post_offchain_self(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    ex = body.get("ex")
    if not isinstance(ex, str) or ex not in OFFC_EXCHANGES:
        return h._send(400, {"ok": False, "error": "ex(" + "|".join(OFFC_EXCHANGES) + ") 필요"})
    if "addr" in body:
        a, excl = body.get("addr"), body.get("excl")
        if not isinstance(a, str) or not a.strip() or len(a) > 128 or not isinstance(excl, bool):
            return h._send(400, {"ok": False, "error": "addr(문자열 ≤128) + excl(true/false) 필요"})
        a = xfer_match.norm_addr(a)
        ex0 = prefs.get("offchain_self_excl") if isinstance(prefs.get("offchain_self_excl"), dict) else {}
        cur = [str(x) for x in (ex0.get(ex) if isinstance(ex0.get(ex), list) else [])]
        known = set(((getattr(web_ctx.builder(), "_offc_addrs", None) or {}).get(ex)) or ()) if excl else set(cur)
        if a not in known:
            return h._send(400, {"ok": False, "error": ("이 거래소의 오프체인 출금 받는 주소 목록에 없는 주소" if excl
                                                           else "제외 목록에 없는 주소")})
        lst = [x for x in cur if x != a] + ([a] if excl else [])
        ex0 = {k: v for k, v in ex0.items() if k in OFFC_EXCHANGES and isinstance(v, list) and k != ex}
        if lst:
            ex0[ex] = lst
        prefs["offchain_self_excl"] = ex0
        statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
        return h._send(200, {"ok": True, "ex": ex, "addr": a, "excl": excl})
    on = body.get("on")
    if not isinstance(on, bool):
        return h._send(400, {"ok": False, "error": "on(true/false) 필요"})
    oc = prefs.get("offchain_self") if isinstance(prefs.get("offchain_self"), dict) else {}
    oc = {k: v for k, v in oc.items() if k in OFFC_EXCHANGES and isinstance(v, bool)}
    oc[ex] = on
    prefs["offchain_self"] = oc
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "ex": ex, "on": on})


def post_first_seen_px(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    if "note" in body:
        if body.get("note") is not True:
            return h._send(400, {"ok": False, "error": "note 는 true"})
        prefs["first_seen_note"] = int(time.time())
        statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
        if not web_ctx.bcall("mpatch", {"fsnote"}):
            with web_ctx.builder().lock:
                web_ctx.builder().cache = None
        return h._send(200, {"ok": True, "note": True})
    if not isinstance(body.get("on"), bool):
        return h._send(400, {"ok": False, "error": "on 은 true/false"})
    prefs["first_seen_px"] = body["on"]
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "on": prefs["first_seen_px"]})


def post_gas_in_cost(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    if not isinstance(body.get("on"), bool):
        return h._send(400, {"ok": False, "error": "on 은 true/false"})
    prefs["gas_in_cost"] = body["on"]
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "on": prefs["gas_in_cost"]})


def post_review_len(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    kind, length = body.get("kind"), body.get("len")
    if kind not in ("daily", "weekly") or length not in REVIEW_LEN_KEYS:
        return h._send(400, {"ok": False, "error": "kind(daily|weekly) + len(short|normal|long) 필요"})
    rl = prefs.get("review_len") if isinstance(prefs.get("review_len"), dict) else {}
    prefs["review_len"] = dict(rl, **{kind: length})
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    if not web_ctx.bcall("mpatch", {"review"}):
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
    h._send(200, {"ok": True, "kind": kind, "len": length, "reviewLen": review_len_eff(prefs)})


def post_review_pause(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    if not isinstance(body.get("on"), bool):
        return h._send(400, {"ok": False, "error": "on 은 true/false"})
    prefs["review_pause"] = {"on": body["on"], "at": int(time.time())}
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    if not web_ctx.bcall("mpatch", {"review"}):
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
    h._send(200, {"ok": True, "reviewPause": review_pause_eff(prefs)})


def post_review_fill(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    order, par = body.get("order"), body.get("parallel")
    if review_progress is None or order not in review_progress.FILL_ORDERS or isinstance(par, bool) \
            or not isinstance(par, int) or par not in review_progress.FILL_PARALLEL:
        return h._send(400, {"ok": False, "error": "order(recent|oldest) + parallel(1|3) 필요"})
    prefs["review_fill"] = {"order": order, "parallel": par}
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    if not web_ctx.bcall("mpatch", {"review"}):
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
    h._send(200, {"ok": True, "reviewFill": review_progress.fill_eff(prefs["review_fill"])})


def post_chain_auto_off(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    code, out = web_ctx.chain_auto_off_save(prefs, body)
    h._send(code, out)


def post_dust_threshold(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    try:
        v = float(body.get("usd"))
    except (TypeError, ValueError):
        h._send(400, {"error": "usd 숫자 필요"})
        return
    prefs["dust_usd"] = max(0.0, min(v, 1e6))
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "usd": prefs["dust_usd"]})


def post_risk_override(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    key = str(body.get("key") or "")
    verdict = str(body.get("verdict") or "")
    if not re.fullmatch(r"g\d{1,12}", key) or \
            verdict not in ("visible", "spam", "clear"):
        return h._send(400, {"error": "key=g<gid> + verdict(visible|spam|clear) 필요"})
    ro = prefs.setdefault("risk_overrides", {})
    if verdict == "clear":
        ro.pop(key, None)
    else:
        ro[key] = verdict
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "key": key, "verdict": verdict})


def post_genuine_token(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    ch15 = str(body.get("chain") or "").strip().lower()
    ca15 = str(body.get("ca") or "").strip()
    on15 = body.get("on", True)
    if not isinstance(on15, bool) or not re.fullmatch(r"[a-z0-9_-]{1,32}", ch15) or not (
            (ch15 != "sol" and re.fullmatch(r"0[xX][0-9a-fA-F]{40}", ca15))
            or (ch15 == "sol" and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", ca15))):
        return h._send(400, {"error": "chain + ca(컨트랙트 주소) + on(true|false) 필요"})
    ca15 = ca15 if ch15 == "sol" else ca15.lower()
    sym15 = (getattr(web_ctx.builder(), "_unv_pairs", None) or {}).get((ch15, ca15))
    if on15 and sym15 is None:
        return h._send(400, {"error": "지금 '확인 필요'로 보이는 토큰 컨트랙트만 등록할 수 있어요"})
    try:
        changed15 = spamguard.set_user_genuine(ch15, ca15, sym15 or "", on15)
    except ValueError as e15:
        return h._send(409, {"error": str(e15)})
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "chain": ch15, "ca": ca15, "on": on15, "changed": changed15})


def post_src_whitelist(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    raw15 = str(body.get("address") or "").strip()
    if re.fullmatch(r"0[xX][0-9a-fA-F]{40}", raw15):
        addr = raw15.lower()
    elif re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", raw15):
        addr = raw15
    else:
        return h._send(400, {"error": "address 형식 오류 (0x40hex/base58)"})
    rm = body.get("remove", False)
    if not isinstance(rm, bool):
        return h._send(400, {"error": "remove 는 true/false"})
    wl = prefs.setdefault("src_whitelist", [])
    if rm:
        prefs["src_whitelist"] = [a for a in wl if a != addr]
    elif addr not in wl:
        if len(wl) >= web_ctx.src_wl_max():
            return h._send(413, {"error": f"발신 화이트리스트는 {web_ctx.src_wl_max():,}개까지예요 — 안 쓰는 주소를 지운 뒤 다시"})
        wl.append(addr)
    statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
    with web_ctx.builder().lock:
        web_ctx.builder().cache = None
    h._send(200, {"ok": True, "whitelist": prefs["src_whitelist"]})


def post_flow_register(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._flow_register(body)


def post_other_assets(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._oa_post(path, body)


def post_nft_prefs(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._nft_post(body)


def post_receipt_eval(h: BaseHTTPRequestHandler, path: str, body: dict):
    if body.get("auto") is True and review_pause_eff(web_ctx.builder().prefs() if web_ctx.builder() is not None else {}).get("on"):
        return h._send(409, {"ok": False, "paused": True, "error": "AI 자동 생성 멈춤 중 — 버튼으로 직접 만들 수 있어요"})
    return h._receipt_eval_post(body)


def post_day_memo(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._day_memo_post(body)


def post_alert_test(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._alert_test_post(body)


def post_wd_dest_register(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._wd_dest_register(body)


def post_health_ack(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._health_ack_post(path, body)


def post_review_fill_run(h: BaseHTTPRequestHandler, path: str, body: dict):
    return h._review_fill_post(body)


def post_alert_prefs(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    return h._alert_prefs_post(prefs, body)


def post_outflow_resolve(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    return h._outflow_resolve(body)


def post_backfill_request(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):
    return h._backfill_request(body)

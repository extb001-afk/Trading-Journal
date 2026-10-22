from __future__ import annotations
import acct_norm
import config, logs, paths, statefile
import copy
import depaddr
import json
import lpchain
import lpdec
import lpsol
import os
import token_tables
import rabby
import re
import spamguard
import time
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
from view_common import CHAIN_NAME
from view_common import EPS
from timeutil import KST
from view_common import STABLE_GROUPS
from view_common import TRANSIT_ASK_DAYS
from view_common import _ex_stable_sym
from view_common import _f
from view_evals import DAY_MEMOS
from view_fspin import FS_HOLD_KO
from view_hero import _ago_ko
from view_pending import _classify_pendings
from view_pending import _of_linked_txs
from view_pending import _tx_norm
from view_text import _scam_name
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _unk_cands(gid, sym, px, *, G, resolve_origin, wallet_label):
    srcs = list((G.get(gid) or {}).get("unk_src") or [])
    if not srcs:
        return []
    srcs.sort(key=lambda x: -x["qty"])
    tot = sum(x["qty"] for x in srcs) or 1.0
    expanded = []
    for x in srcs[:6]:
        expanded.append((x, 0))
        ug = G.get(x.get("up_gid")) if x.get("up_gid") is not None else None
        for y in sorted((ug or {}).get("unk_src") or [], key=lambda z: -z["qty"])[:2]:
            expanded.append((y, 1))
            ug2 = G.get(y.get("up_gid")) if y.get("up_gid") is not None else None
            for z in sorted((ug2 or {}).get("unk_src") or [], key=lambda w: -w["qty"])[:1]:
                expanded.append((z, 2))
    out = []
    seen = set()
    for x, lvl in expanded:
        x = x if x.get("via") else resolve_origin(x)
        key_x = (lvl > 0, x.get("ref"), x.get("kind"))
        if key_x in seen:
            continue
        seen.add(key_x)
        if len(out) >= 12:
            break
        ref = x.get("ref") or ""; frm = x.get("from"); dt = datetime.fromtimestamp(x["ts"], KST).strftime("%m-%d %H:%M")
        short = (ref[:8] + "…" + ref[-4:]) if len(ref) > 14 else ref
        if x.get("via"):
            who = f" ← {x['via']}"; copy = ref; btn = "참조 복사" if ref else "—"
        elif frm and frm in wallet_label:
            who = f" ← 내 지갑 {wallet_label[frm]} ({frm[:6]}…{frm[-4:]})"; copy = frm; btn = "주소 복사"
        elif frm:
            who = f" ← 외부 지갑 {frm[:6]}…{frm[-4:]} (미등록 · 내 지갑이면 설정에 등록)"; copy = frm; btn = "주소 복사"
        elif ref.startswith("0x") and len(ref) == 66 and x.get("oc_na"):
            who = (" ← 발신 조회 불가 (추적 체인에서 찾지 못함 · txid 로 직접 확인)" if x["oc_na"] == "notfound"
                   else f" ← 발신 조회 불가 (네트워크 미지원: {x['oc_na']} · txid 로 직접 확인)")
            copy = ref; btn = "txid 복사"
        elif ref.startswith("0x") and len(ref) == 66 and x.get("oc_fail"):
            who = f" ← 발신 조회 실패(재시도 {datetime.fromtimestamp(x['oc_fail'], KST).strftime('%m-%d')})"; copy = ref; btn = "txid 복사"
        elif ref.startswith("0x") and len(ref) == 66:
            who = " ← 발신 지갑 조회 중"; copy = ref; btn = "txid 복사"
        else:
            who = ""; copy = ref; btn = "참조 복사" if ref else "—"
        val = x["qty"] * float(px or 0)
        sym_x = (G.get(x.get("up_gid")) or {}).get("sym") if lvl and x.get("up_gid") is not None else sym
        ov_txt = ""
        if x.get("ov"):
            ov_txt = (f" · ★원가 지정 ${x['ov']['unit']:,.6g}/개 적용★" if x["ov"].get("mode") == "unit"
                      else f" · ★당시 시세 ${x['ov']['unit']:,.6g}/개 적용★")
        out.append({"kind": "src", "label": ("↳ " * lvl) + (f"상류({sym_x or sym}) " if lvl else "") + f"{dt} {x['kind']} {x['qty']:,.4f}" + (f" · {short}" if short else "") + who
                     + (f" · 지금 평가 ${val:,.0f}" if (val >= 1 and not lvl) else "") + ov_txt,
                     "score": (x.get("chain") or x.get("ex") or "—"),
                     "pct": (0 if lvl else min(100, int(round(100.0 * x["qty"] / tot)))),
                     "copy": copy, "btn": btn})
    return out


def _leg_scam(r, *, quarantined, spoof_keys):
    return ((r["group_id"] or -r["asset_id"]) in quarantined
            or (r["source_ns"], r["source_id"], r["asset_id"]) in spoof_keys or int(r["qty_base"]) == 0)


def _grp_weak(r, *, quarantined, spoof_keys, G):
    gid = r["group_id"] or -r["asset_id"]
    if gid not in quarantined or (r["source_ns"], r["source_id"], r["asset_id"]) in spoof_keys or int(r["qty_base"]) == 0:
        return None
    rr = str((G.get(gid) or {}).get("risk_reason") or "")
    if rr.startswith(("가짜 ", "사칭 ", "확인 필요")) or "유저 확정" in rr or "스캠 확증" in rr \
            or _scam_name((G.get(gid) or {}).get("sym") or r["symbol"]):
        return None
    return rr or "실매수 이력 없는 유입"


def _dep_net(a, ch=None, *, cr):
    c = ch if cr.is_nonevm(ch) else cr.key_chain(a)
    return cr.display_name(c) if c else None


def _lp_tok_px(ch, addr, sym, *, lpa, tok_gid, live_px, sb):
    a = lpa(ch, addr)
    if token_tables.STABLE_CAS.get(ch, {}).get(a) or (ch == "sol" and token_tables.STABLE_MINTS.get(a)):
        return 1.0
    if ch == "sol" and a == lpsol.WSOL:
        a = lpchain.ZERO
    gid = tok_gid.get((ch, a.lower()))
    if gid is not None and live_px.get(gid):
        return float(live_px[gid])
    if a and a != lpchain.ZERO:
        dp = sb.spot.dex_price(ch, a)
        return float(dp) if dp else None
    p = sb.spot.price(sym or "") if sym else None
    return float(p) if p else None


def _qnow(x, *, qfmt):
    if x is None:
        return "구성 미확인"
    return "<0.0001" if 0 < abs(float(x)) < 0.00005 else qfmt(x)


def _lp_extra(b, loc, tid, *, lp_v2_units, lp_meta_by):
    ex = {"proto": b.get("proto")}
    if b.get("proto") == "v2":
        ex["units"] = str(max(0, lp_v2_units.get(loc, 0)))
        ex["wallet"] = str(tid)
    stk = ((lp_meta_by.get((b["chain"], b["mgr"])) or {}).get("stake") or {}).get(str(b["id"]))
    if stk:
        ex["stake"] = stk
        ex.setdefault("wallet", ((lp_meta_by.get((b["chain"], b["mgr"])) or {}).get("who") or {}).get(str(b["id"])))
    return ex


def _lp_value(oc, ch, *, lpa, tok_gid, live_px, sb):
    p0 = _lp_tok_px(ch, oc.get("token0"), oc.get("sym0"), lpa=lpa, tok_gid=tok_gid, live_px=live_px, sb=sb)
    p1 = _lp_tok_px(ch, oc.get("token1"), oc.get("sym1"), lpa=lpa, tok_gid=tok_gid, live_px=live_px, sb=sb)
    pr = float(oc.get("price") or 0)
    if p0 is None and p1 is not None and pr:
        p0 = p1 * pr
    if p1 is None and p0 is not None and pr:
        p1 = p0 / pr
    if p0 is None or p1 is None:
        return None
    a0, a1 = float(oc.get("amount0") or 0), float(oc.get("amount1") or 0)
    f0, f1 = float(oc.get("fees0") or 0), float(oc.get("fees1") or 0)
    rw = float(oc.get("rewardAmount") or 0)
    rp = _lp_tok_px(ch, oc.get("rewardToken"), oc.get("rewardSym"), lpa=lpa, tok_gid=tok_gid, live_px=live_px, sb=sb) if rw > 0 else None
    return {"value": a0 * p0 + a1 * p1, "fees": f0 * p0 + f1 * p1, "p0": p0, "p1": p1,
            "rewards": rw * rp if rp else 0.0}


def _pend_upbit_only(coins, ignored_u, pendings, now):
    for c in sorted((c for c in coins if str(c.get("key", "")).startswith("ub:") and not (c.get("avg") or 0)
                      and float(c.get("qty") or 0) * float(c.get("price") or 0) >= 50.0),
                     key=lambda c: -(float(c["qty"]) * float(c.get("price") or 0))):
        key = f"unkh:{c['key']}"
        if key in ignored_u:
            continue
        pendings.insert(0, {
            "key": key, "t": datetime.fromtimestamp(now, KST).strftime("%m-%d"),
            "kind": "원가미상 보유 (업비트 단독 · 손익 제외(평가 포함))",
            "sym": c["sym"], "chain": "업비트",
            "onchain": f"{float(c['qty']):,.4f} {c['sym']} 업비트 잔고 · 원장 매수·입금 기록과 매칭 안 됨",
            "ex": "업비트",
            "gap": "원장에 이 코인의 업비트 유입(매수 체결·입금)이 없음 — 수집 창(백필) 이전부터 보유했거나 체결·입금 미수집",
            "why": "업비트 실잔고로만 보이는 보유분이라 원가를 모릅니다 — 평가손익에서 빠져 있어요. 업비트 체결·입금이 원장에 잡히면 자동으로 원가가 붙습니다.",
            "fbAvg": 0, "fbCost": 0, "gkey": "", "ckey": c["key"], "costOv": None, "cands": [], "candsHint": "",
            "qty": _f(float(c["qty"]), 6) or 0, "usd": _f(float(c["qty"]) * float(c.get("price") or 0), 2) or 0,
        })


def _pend_gas_nopx(gas_nopx, ignored_u, pendings):
    for gid_g, gn in sorted(gas_nopx.items(), key=lambda kv: -float(kv[1]["cost"])):
        key_g = f"gasnopx:{gid_g}"
        if key_g in ignored_u or gn["cost"] < 1:
            continue
        pendings.insert(0, {
            "key": key_g, "t": acct_norm.mmdd(gn["last"]),
            "kind": "시세 없는 가스 · 원가만 소진",
            "sym": gn["sym"], "chain": "/".join(sorted(CHAIN_NAME.get(c, c) for c in gn["chains"])) or "—",
            "onchain": f"{float(gn['qty']):,.6f}".rstrip("0").rstrip(".") + f" {gn['sym']} 가스 {gn['n']}건 · 소진한 원가 ${float(gn['cost']):,.2f}",
            "ex": "—",
            "gap": f"{gn['n']}건 · 그 시각 달러 시세가 없어 가스 비용·실현에 안 잡히고 원가만 빠짐",
            "why": "가스로 나간 수량의 원가가 손익 없이 사라졌어요(가스 비용 칸에도 없음). 그 시각 시세를 받으면(가격 채움·재구축) 가스 비용으로 들어가요 — "
                   "금액이 작으면 무시해도 돼요.",
            "gkey": f"g{gid_g}", "costOv": None, "cands": [], "candsHint": "",
            "qty": _f(float(gn["qty"]), 6) or 0, "usd": _f(float(gn["cost"]), 2) or 0})


def _pend_noproc(noproc, ignored_u, pendings):
    for gid_n, np in sorted(noproc.items(), key=lambda kv: -float(kv[1]["cost"])):
        key_n = f"noproc:{gid_n}"
        if key_n in ignored_u or not np["old"] or (np["cost"] < 1 and np["unk"] <= 0):
            continue
        wh = " · ".join(sorted(np["where"])) or "—"
        pendings.insert(0, {
            "key": key_n, "t": acct_norm.mmdd(np["last"]),
            "kind": "대금 미상 매도 (정산액 산정 전)",
            "sym": np["sym"], "chain": "—",
            "onchain": f"{float(np['qty']):,.4f} {np['sym']} 매도 {np['n']}건 · 정산액 없음"
                       + (f" · 소진한 원가 ${float(np['cost']):,.2f}" if np["cost"] > 0 else ""),
            "ex": wh,
            "gap": f"{np['n']}건 · {np['first'][5:] if len(np['first']) >= 10 else np['first']}"
                   + (f"~{np['last'][5:] if len(np['last']) >= 10 else np['last']}" if np["last"] != np["first"] else "")
                   + " · 그 시각 시세(받은 쪽 코인·마켓 쿼트)를 못 받아 정산액이 비어 있음",
            "why": "판 대금을 몰라 이 매도의 원가가 실현손익에도 원가미상 매도에도 들어가지 않았어요. 시세를 받으면(가격 채움·재구축) 자동으로 실현에 들어갑니다.",
            "gkey": f"g{gid_n}", "costOv": None, "cands": [], "candsHint": "", "tx": np["tx"],
            "qty": _f(float(np["qty"]), 6) or 0, "usd": _f(float(np["cost"]), 2) or 0})


def _pend_ord_far(far, rows, fx_name, ignored_u, pendings):
    if not far:
        return
    want = {(f[0], f[1]) for f in far}
    arrival = {}
    for row in rows:
        k = (row["source_ns"], row["source_id"])
        if k in want and row["leg_kind"] in ("acq", "move_in") and k not in arrival:
            arrival[k] = row
    seen = set()
    for ns, sid, at_ts, wd_ex, wd_ts, txid in far:
        key = f"ordgap:{txid}"
        row = arrival.get((ns, sid))
        if key in ignored_u or key in seen or row is None:
            continue
        seen.add(key)
        dec = row["decimals"] if row["decimals"] is not None else 18
        qty = float(int(row["qty_base"])) / (10 ** int(dec))
        sym = row["symbol"] or "?"
        wd_name = fx_name.get(wd_ex, wd_ex)
        pendings.insert(0, {
            "key": key, "t": datetime.fromtimestamp(at_ts, KST).strftime("%m-%d"),
            "kind": "출금보다 먼저 찍힌 도착 · 원가 연결 안 됨",
            "sym": sym, "chain": CHAIN_NAME.get(row["chain"], row["chain"]) if row["chain"] else fx_name.get(ns.split(":")[0], ns.split(":")[0]),
            "onchain": f"{qty:,.4f} {sym} 도착 {datetime.fromtimestamp(at_ts, KST).strftime('%m-%d %H:%M')} · "
                       f"{wd_name} 출금 기록 {datetime.fromtimestamp(wd_ts, KST).strftime('%m-%d %H:%M')} (같은 txid)",
            "ex": wd_name,
            "gap": f"도착이 출금 기록보다 {(wd_ts - at_ts) / 3600.0:,.1f}시간 먼저 — 거래소 시계·기록 지연 허용(1시간)을 넘어 출금 원가를 이어받지 못함",
            "why": "도착은 원가 미상(최초 인식 시가를 켰으면 그 시가)으로 잡혔고, 출금 쪽 원가는 이동 중으로 남았을 수 있어요. 같은 코인이면 아래에서 출금 때 평단으로 원가를 지정하세요.",
            "gkey": f"g{row['group_id'] or -row['asset_id']}", "costOv": None, "cands": [], "candsHint": "", "tx": txid,
            "qty": _f(qty, 6) or 0, "usd": 0})


def _pend_unv_lost(G, ignored_u, pendings, backfill_t0, cost_ov, UNK_HINT):
    for gid_l, g_l in sorted(G.items(), key=lambda kv: float((kv[1].get("unv_lost") or (0, 0, 0))[1])):
        lost = g_l.get("unv_lost")
        if not lost:
            continue
        k_l, c_l, ts_l = lost
        key_l = f"unvlost:{gid_l}"
        if key_l in ignored_u or float(c_l) < 1.0:
            continue
        pendings.insert(0, {
            "key": key_l, "t": datetime.fromtimestamp(ts_l or backfill_t0, KST).strftime("%m-%d"),
            "kind": f"창 밖 처분 · 원가 ${float(c_l):,.2f}",
            "sym": g_l["sym"], "chain": "/".join(sorted(CHAIN_NAME.get(c, c) for c in g_l["chains"])) or "—",
            "onchain": f"{float(k_l):,.4f} {g_l['sym']} 실매수분 · 원가 ${float(c_l):,.2f} 가 손익에 안 잡힘",
            "ex": "—",
            "gap": "백필 창(5개월) 시작 직후 창 이전 보유분을 처분 — 원장 순액이 0 밑으로 파여 리플레이가 그 처분을 버리고, 뒤 매수분 원가가 대응 없이 남음",
            "why": "창 이전 보유분은 원가를 모르고 처분은 창 안에 있어 실현손익으로도 미확인 매도로도 못 잡습니다. "
                   "표시용 보정(원장 무변경)이라 무시해도 되고, 창 이전 매수 이력을 등록하면 원가가 연결됩니다.",
            "gkey": f"g{gid_l}", "costOv": cost_ov.get(f"g{gid_l}"), "cands": [], "candsHint": UNK_HINT,
            "qty": _f(float(k_l), 6) or 0, "usd": _f(float(c_l), 2) or 0})


def _pend_spam(spam_sorted, pendings, today_kst):
    for gid13, g13, qty13, px13 in spam_sorted:
        key13 = f"risk:g{gid13}"
        val13 = qty13 * (px13 or 0)
        ch13 = "/".join(sorted(CHAIN_NAME.get(c, c) for c in g13["chains"])) or "—"
        pendings.insert(0, {
            "key": key13, "t": today_kst.strftime("%m-%d %H:%M"),
            "kind": "스팸·에어드랍 의심", "sym": g13["sym"], "chain": ch13,
            "onchain": f"{qty13:,.4f} {g13['sym']} · 평가 ${val13:,.2f} — 스팸 의심이라 평가에서 뺐어요",
            "ex": "—",
            "gap": g13.get("risk_reason") or "실매수 이력 없는 유입",
            "why": "실매수·스왑·내 지갑 이동 이력이 없는 유입이라 메인 목록과 일별 기록에서 뺐습니다."
                   " 실제 보유가 맞으면 [정상으로 복원]을 누르거나, 보낸 주소를 설정 › 발신 주소 화이트리스트에 추가하세요.",
            "gkey": f"g{gid13}", "risk": g13.get("risk_reason") or "",
            "qty": _f(qty13, 6) or 0, "usd": _f(val13, 2) or 0,
            "cands": []})


def _collect_upbit_withdrawals(conn, ub_wd_shown, wd_rows):
    for r8 in conn.execute(
            "SELECT uuid, payload FROM raw_ex WHERE kind='withdraw' AND exchange='upbit'"
            " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
        try:
            wd = json.loads(r8["payload"])
        except json.JSONDecodeError:
            continue
        if str(wd.get("state") or "").upper() not in ("DONE", "ACCEPTED"):
            continue
        if r8["uuid"] in ub_wd_shown:
            continue
        try:
            wts = int(datetime.fromisoformat(str(wd.get("done_at")
                                                 or wd.get("created_at"))).timestamp())
        except (ValueError, TypeError):
            continue
        wd_rows.append((wts, wd))


class PendingsMixin:

    def _build_pendings(self, _bs9):
        (G, _ak, _qfmt, aliases, backfill_t0, be_done, be_until, coins, conn, cost_be, cost_ov, cur_src, debt_over9, disp9, ev_hide, ev_usd, ex_fee, exb9, extra_ev, extra_events, fb_cov9, fb_on, fs_on, fx_dep_tx, fx_name, fx_wd, gas_applied, gas_by_chain, gas_expense, gas_nopx, gas_on, gid_pairs_all, hl_neg, led_by_gid, live_px, locs_by_gid, lp_by_tx, lp_events, lp_meta_by, lp_mgrs, lpb, my_all9, noproc, now, of_applied, of_cands, of_dec9, overrides9, pos_hid9, pos_rows, prefs, pv_led9, quarantined, rb_view, realized_by_date, resolve_origin, rows, sale_lot_by, signer9, spam_view, spoof_keys, stables, syms9, today_kst, ub2, ub_path2, ub_wd_shown, ub_wd_tx, uncred_gid, unv9, unverified, wallet_label, wd_fee, wl9,) = (_bs9["G"], _bs9["_ak"], _bs9["_qfmt"], _bs9["aliases"], _bs9["backfill_t0"], _bs9["be_done"], _bs9["be_until"], _bs9["coins"], _bs9["ctx"].conn, _bs9["cost_be"], _bs9["cost_ov"], _bs9["cur_src"], _bs9["debt_over9"], _bs9["disp9"], _bs9["ev_hide"], _bs9["ev_usd"], _bs9["ex_fee"], _bs9["exb9"], _bs9["extra_ev"], _bs9["extra_events"], _bs9["fb_cov9"], _bs9["ctx"].fb_on, _bs9["ctx"].fs_on, _bs9["fx_dep_tx"], _bs9["fx_name"], _bs9["fx_wd"], _bs9["gas_applied"], _bs9["gas_by_chain"], _bs9["gas_expense"], _bs9["gas_nopx"], _bs9["ctx"].gas_on, _bs9["gid_pairs_all"], _bs9["hl_neg"], _bs9["led_by_gid"], _bs9["live_px"], _bs9["locs_by_gid"], _bs9["lp_by_tx"], _bs9["lp_events"], _bs9["lp_meta_by"], _bs9["lp_mgrs"], _bs9["lpb"], _bs9["my_all9"], _bs9["noproc"], _bs9["ctx"].now, _bs9["of_applied"], _bs9["of_cands"], _bs9["of_dec9"], _bs9["overrides9"], _bs9["pos_hid9"], _bs9["pos_rows"], _bs9["ctx"].prefs, _bs9["pv_led9"], _bs9["quarantined"], _bs9["rb_view"], _bs9["realized_by_date"], _bs9["resolve_origin"], _bs9["rows"], _bs9["sale_lot_by"], _bs9["signer9"], _bs9["spam_view"], _bs9["spoof_keys"], _bs9["stables"], _bs9["syms9"], _bs9["ctx"].today_kst, _bs9["ub2"], _bs9["ub_path2"], _bs9["ub_wd_shown"], _bs9["ub_wd_tx"], _bs9["uncred_gid"], _bs9["unv9"], _bs9["unverified"], _bs9["wallet_label"], _bs9["wd_fee"], _bs9["wl9"],)
        pendings = self._pendings(conn, prefs)
        ignored_u = set(prefs.get("ignored", []))
        UNK_HINT = ("내 지갑에서 보낸 거라면 설정 › 연결 · 키에서 그 지갑을 추가해 주세요 — 다음 재구축 때 원가가 자동으로 붙습니다. "
                    "에어드랍·타인 송금·LP 인출이라면 아래에서 개당 원가를 입력하거나 '당시 시세로 추정'을 누르세요.")
        _unk_rows = [c9 for c9 in coins if (c9.get("fbQty") or 0) > 0 and str(c9.get("key", "")).startswith("g")
                     and ((c9.get("fbCost") or 0) >= 50.0 or float(c9["fbQty"]) * float(c9.get("price") or 0) >= 50.0)]
        _unk_rows.sort(key=lambda c9: -(float(c9["fbQty"]) * float(c9.get("price") or 0)))
        for c9 in _unk_rows:
            gid9 = int(c9["key"][1:]) if c9["key"][1:].isdigit() else None
            key9 = f"unkh:{gid9 if gid9 is not None else c9['sym']}"
            if key9 in ignored_u:
                continue
            fb_ok = fb_on and (c9.get("fbCost") or 0) > 0
            pendings.insert(0, {
                "key": key9, "t": datetime.fromtimestamp(now, KST).strftime("%m-%d"),
                "kind": ("원가미상 보유 · 평균가 폴백 적용" if fb_ok else
                         ("원가미상 보유 (평균가 없음)" if fb_on else "원가미상 보유 (폴백 OFF · 손익 제외(평가 포함))")),
                "sym": c9["sym"], "chain": "—",
                "onchain": f"{float(c9['fbQty']):,.4f} {c9['sym']} 원가미상 보유"
                           + (f" · 평균 매수가 ${float(c9['avg']):,.6g} → 원가 ${float(c9['fbCost']):,.2f} 적용" if fb_ok else ""),
                "ex": "—",
                "gap": "실매수 기록 없는 유입분(미등록 지갑·OTC·에어드랍·미수집 체결)",
                "why": ("평가·손익에는 이 종목 평균 매수가로 원가를 잡아 반영했습니다. 실제 취득 경로(지갑 등록·체결 연동)가 확인되면 자동으로 정정됩니다."
                        if fb_ok else ("이 종목은 실매수 기록이 없어 평균가로 대체할 수도 없어요 — 평가·손익에서 빠져 있습니다." if fb_on else
                                       "원가 추적(지갑 등록·체결 연동)이 우선입니다. 설정의 '원가 미확인 → 평균가 대체'를 켜면 이 종목 평균 매수가로 원가를 잡아 평가·손익에 반영합니다.")),
                "fbAvg": _f(float(c9["avg"]), 6) or 0, "fbCost": c9.get("fbCost") or 0,
                "gkey": f"g{gid9}" if gid9 is not None else "", "costOv": cost_ov.get(f"g{gid9}") if gid9 is not None else None,
                "cands": _unk_cands(gid9, c9["sym"], c9.get("price") or 0, G=G, resolve_origin=resolve_origin, wallet_label=wallet_label),
                "candsHint": UNK_HINT,
                "qty": _f(float(c9["fbQty"]), 6) or 0, "usd": _f(float(c9["fbQty"]) * float(c9.get("price") or 0), 2) or 0,
            })
        _pend_upbit_only(coins, ignored_u, pendings, now)
        _pend_gas_nopx(gas_nopx, ignored_u, pendings)
        _pend_noproc(noproc, ignored_u, pendings)
        _pend_ord_far(getattr(self, "_ord_far", None) or (), rows, fx_name, ignored_u, pendings)
        for gid_u, u in sorted(unverified.items(), key=lambda kv: float(kv[1]["proceeds"])):
            key_u = f"unv:{gid_u}"
            if key_u in ignored_u:
                continue
            if float(u["proceeds"]) < 1.0:
                continue
            org = ", ".join(sorted(G.get(gid_u, {}).get("origin_ex") or []))
            fc9u = fb_cov9.get(gid_u) if fb_on else None
            fb_avg_u = (fc9u[1] / fc9u[0]) if (fc9u and fc9u[0] > 0) else 0.0
            fh9u = ((G.get(gid_u) or {}).get("_fsh") or {}) if fs_on else {}
            fhk9u = max(sorted(fh9u), key=lambda k9: fh9u[k9]) if fh9u else None
            pendings.insert(0, {
                "key": key_u, "t": acct_norm.mmdd(u["last"]),
                "kind": "원가미상 매도 · 평균가 폴백 적용" if fb_avg_u else "원가미상 매도 검토",
                "fbAvg": _f(fb_avg_u, 6) or 0,
                "fbRealized": _f(fc9u[2], 2) if fb_avg_u else 0,
                "sym": u["sym"], "chain": "—",
                "onchain": f"{float(u['qty']):,.4f} {u['sym']} 매도 · 정산 ${float(u['proceeds']):,.2f}",
                "ex": org or "—",
                "gap": f"{u['n']}건 · " + (f"★{org} 출금 유입 확인★ (원가 연결 대기)" if org
                                           else "실매수 기록 없는 유입분") + FS_HOLD_KO.get(fhk9u, ""),
                **({"fsHold": fhk9u} if fhk9u else {}),
                "why": (f"{org} 출금과 txid 가 일치하는 유입입니다. 해당 거래소 매수내역 연동(2단계)"
                        " 시 원가가 자동 연결됩니다." if org else
                        "매수 기록이 없는 유입분의 매도라 실현손익에서 제외했습니다. "
                        "원가 지정 또는 이체·에어드랍 확인이 필요합니다."),
                "gkey": f"g{gid_u}", "costOv": cost_ov.get(f"g{gid_u}"),
                **({"costBe": cost_be.get(f"g{gid_u}")} if be_until(gid_u) is not None else {}),
                "qty": _f(float(u["qty"]), 6) or 0, "usd": _f(float(u["proceeds"]), 2) or 0,
                "qtyExact": str(u["qty"]),
                "cands": _unk_cands(gid_u, u["sym"], live_px.get(gid_u) or 0, G=G, resolve_origin=resolve_origin, wallet_label=wallet_label), "candsHint": UNK_HINT})
        cost_decided_rows = []
        for gid_b, bd in sorted(be_done.items(), key=lambda kv: -float(kv[1]["proceeds"])):
            g_b = G.get(gid_b) or {}
            ut9 = be_until(gid_b)
            cost_decided_rows.append({
                "key": f"be:{gid_b}", "gkey": f"g{gid_b}", "mode": "breakeven", "sym": disp9.get(gid_b) or bd["sym"],
                "chain": "/".join(sorted(CHAIN_NAME.get(c, c) for c in (g_b.get("chains") or ()))) or "—",
                "qty": _f(float(bd["qty"]), 6) or 0, "usd": _f(float(bd["proceeds"]), 2) or 0, "n": bd["n"],
                "qtyExact": str(bd["qty"]),
                "first": bd["first"], "last": bd["last"],
                "until": int(ut9) if ut9 is not None else None,
                "untilT": datetime.fromtimestamp(ut9, KST).strftime("%m-%d %H:%M") if ut9 is not None else ""})
        _pend_unv_lost(G, ignored_u, pendings, backfill_t0, cost_ov, UNK_HINT)
        spam_all = [x for x in sorted(spam_view, key=lambda x: -(x[2] * (x[3] or 0)))
                    if f"risk:g{x[0]}" not in ignored_u]
        pin_gids13 = {x[0] for x in spam_all
                      if "유저 확정" in (x[1].get("risk_reason") or "")
                      or "재정렬" in (x[1].get("risk_reason") or "")}
        pinned13 = [x for x in spam_all if x[0] in pin_gids13]
        rest13 = [x for x in spam_all if x[0] not in pin_gids13]
        spam_sorted = pinned13 + rest13[:30]
        if len(rest13) > 30 and "risk:summary" not in ignored_u:
            more13 = rest13[30:]
            pendings.insert(0, {
                "key": "risk:summary", "t": today_kst.strftime("%m-%d %H:%M"),
                "kind": "스팸·에어드랍 의심", "sym": f"외 {len(more13)}종", "chain": "—",
                "onchain": "저평가 격리분 일괄 — 메인·일일기록에서 제외됨",
                "ex": "—", "gap": "개별 행 생략(평가액 상위 30건만 표시)",
                "why": "격리는 이 종목들 전부에 적용돼 있습니다(평가액이 작은 순서라 개별 행은 생략). "
                       "특정 종목을 되살리려면 그 종목 행에서 [정상으로 복원]을 누르세요.", "cands": [],
                "n": len(more13), "usd": _f(sum(x[2] * (x[3] or 0) for x in more13), 2) or 0})
        _pend_spam(spam_sorted, pendings, today_kst)
        tx_legs9 = {}
        for r9 in rows:
            if r9["leg_kind"] in ("acq", "disp", "move_in", "move_out") and (r9["location"] or "").startswith("wallet:"):
                tx_legs9.setdefault((r9["source_ns"], r9["source_id"]), []).append(r9)
        fold9 = {}
        of_linked9 = _of_linked_txs(of_dec9)
        for p9 in pendings:
            k9 = str(p9.get("key") or "").split(":", 1)[0]
            tx9 = str(p9.get("tx") or "")
            if k9 not in ("PROGRAM_IN", "UNKNOWN", "NEW_ASSET") or not tx9 or not p9.get("chainKey"):
                continue
            ol9 = of_linked9.get((p9["chainKey"], _tx_norm(tx9)))
            if ol9:
                p9["autoDone"] = f"보낸 내역에 연결됨({ol9}) — 받은 것과 연결로 설명됨"
                continue
            if k9 == "PROGRAM_IN" and (tx9 in fx_wd or tx9.lower() in fx_wd or tx9 in ub_wd_tx or tx9.lower() in ub_wd_tx):
                p9["autoDone"] = "거래소 출금 도착(txid 일치) — 출금 기록으로 설명됨"
                continue
            legs9 = tx_legs9.get((p9["chainKey"], tx9.lower() if tx9.startswith("0x") else tx9)) or []
            if not legs9:
                continue
            syms9 = sorted({(G.get(r9["group_id"] or -r9["asset_id"]) or {}).get("sym") or (r9["symbol"] or "?") for r9 in legs9})
            if p9.get("sym") in (None, "", "—"):
                p9["sym"] = "/".join(syms9)[:40]
            if all(_leg_scam(r9, quarantined=quarantined, spoof_keys=spoof_keys) for r9 in legs9):
                wk9 = [w9 for w9 in (_grp_weak(r9, quarantined=quarantined, spoof_keys=spoof_keys, G=G) for r9 in legs9) if w9]
                if wk9:
                    p9["riskOf"] = wk9[0]
                else:
                    p9["scamWhy"] = ("확인 필요 토큰(정품 목록 밖 대표 심볼 — 보유 › 값 없는 토큰에서 확인) "
                                     if all((r9["group_id"] or -r9["asset_id"]) in unv9 for r9 in legs9)
                                     else "스캠 토큰(가짜·사칭·주소 오염) ") + ("수령" if k9 == "PROGRAM_IN" else "기록")
                if k9 == "PROGRAM_IN":
                    fold9.setdefault((frozenset(r9["group_id"] or -r9["asset_id"] for r9 in legs9), "r" if wk9 else "s"), []).append(p9)
                continue
            if k9 == "NEW_ASSET" and all(r9["event"] == "SWAP" and r9["leg_kind"] in ("acq", "disp") and r9["cost_usd"] is not None
                                         for r9 in legs9) and any(r9["leg_kind"] == "disp" for r9 in legs9):
                s9n = self._tx_signer(conn, legs9[0]["source_ns"], legs9[0]["source_id"])
                if s9n and spamguard.signer_mine(*s9n, my_all9):
                    p9["autoDone"] = "원가 있는 내 스왑 체결 — 새 자산 자동 기록 확인됨"
                    continue
            if any(r9["leg_kind"] in ("disp", "move_out") and not _leg_scam(r9, quarantined=quarantined, spoof_keys=spoof_keys) for r9 in legs9):
                continue
            ins9 = [r9 for r9 in legs9 if not _leg_scam(r9, quarantined=quarantined, spoof_keys=spoof_keys)]
            vals9 = [ev_usd(r9, G.get(r9["group_id"] or -r9["asset_id"]) or {"gid": None, "sym": ""}) for r9 in ins9]
            if ins9 and all(v9 is not None for v9 in vals9):
                p9["usdIn"] = round(sum(vals9), 6)
                s9 = signer9.get((legs9[0]["source_ns"], legs9[0]["source_id"]))
                if p9["usdIn"] < 0.01 and not (s9 and spamguard.signer_mine(*s9, my_all9)):
                    p9["scamWhy"] = f"주소 오염 의심 초소액 수령 (${p9['usdIn']:.4f})"
            if not p9.get("scamWhy") and k9 in ("PROGRAM_IN", "UNKNOWN") and len(legs9) == 1 and legs9[0]["leg_kind"] == "acq" \
                    and legs9[0]["event"] in ("TRANSFER_IN", "PROGRAM_IN") and legs9[0]["kind"] == "token" \
                    and (G.get(legs9[0]["group_id"] or -legs9[0]["asset_id"]) or {}).get("is_stable") \
                    and spamguard.is_genuine(legs9[0]["chain"] or legs9[0]["source_ns"], legs9[0]["address"]):
                p9["kind"] = "외부 유입(액면)"
                p9["gap"] = "정품 스테이블 입금 · 액면 원가"
                p9["why"] = ("정품 스테이블(컨트랙트 확인)이 한 줄로 들어온 입금이라 액면 $1 원가로 기록했어요. 내 다른 지갑·거래소에서 보낸 것이면"
                             " 설정 › 연결에서 그 주소를 등록하고, 남에게 받은 것이면 무시해도 돼요.")
        for (gs9, _k9), lst9 in fold9.items():
            if len(lst9) < 2:
                continue
            keep9 = lst9[0]
            keep9["foldN"] = len(lst9)
            keep9["foldTx"] = [str(x9.get("tx") or "") for x9 in lst9[1:21]]
            keep9["why"] = (keep9.get("why") or "") + f" · 같은 코인 수령 {len(lst9)}건을 한 행으로 묶었어요(나머지 {len(lst9) - 1}건 tx 는 foldTx)"
            for x9 in lst9[1:]:
                x9["_fold"] = True
        if fold9:
            pendings[:] = [p9 for p9 in pendings if not p9.pop("_fold", False)]
        _classify_pendings(pendings, prefs)
        wallets_cfg = self._hist_wallets()
        by_addr = {}
        for w in wallets_cfg:
            k9 = w["address"] if w.get("type") == "sol" else w["address"].lower()
            by_addr.setdefault(k9, []).append(w)
        wallet_rows = []
        last_scan9 = self._last_scan_str() if by_addr else None
        for k9, ws in by_addr.items():
            addr = ws[0]["address"]
            chains = sorted({CHAIN_NAME.get(w["chain"], w["chain"]) for w in ws})
            wallet_rows.append({"alias": (aliases.get(k9) or ws[0].get("label")
                                          or addr[:8]),
                                "addr": addr, "key": k9,
                                "chains": " · ".join(chains),
                                "last": last_scan9})
        chain_wallet_rows = [{"alias": aliases.get(cw["key"]) or cw["label"] or (cw["disp"] or cw["key"])[:8], "addr": cw["key"], "key": cw["key"],
                              "disp": cw["disp"], "chain": cw["chain"], "network": cw["network"], "chains": cw["name"]}
                             for cw in self._chain_disp_wallets(self.cfg)]
        deposit_rows = []
        seen_dep = set()
        import chain_registry as _cr9
        for e in self.cfg.get("exchange_addresses", []):
            net = _dep_net(e["address"], e["chain"], cr=_cr9) or ("SOL" if e["chain"] == "sol" else "EVM")
            k = (e["exchange"], net, e["address"])
            if k in seen_dep:
                continue
            seen_dep.add(k)
            deposit_rows.append({"ex": "업비트" if e["exchange"] == "upbit" else e["exchange"],
                                 "net": net, "addr": e["address"], "memo": "—", "ok": True})
        try:
            man9 = {depaddr.norm_addr(k9[2]) for k9 in seen_dep}
            for r9 in depaddr.deposit_rows():
                if depaddr.norm_addr(r9["addr"]) not in man9:
                    deposit_rows.append(r9)
        except Exception as _cg9:  # noqa: BLE001 [optional]
            calcguard.swallowed("view_b_pendings:PendingsMixin._build_pendings[man9]", _cg9)
            pass
        dec_dep9 = self.outflow_decisions()
        for a9, v9 in dec_dep9.items():
            if isinstance(v9, dict) and v9.get("verdict") == "exchange":
                deposit_rows.append({"ex": v9.get("exchange") or "?", "net": _dep_net(a9, cr=_cr9) or ("SOL" if not a9.startswith("0x") else "EVM"),
                                     "addr": a9, "memo": "보낸 내역 판정" + (f" · {v9['memo']}" if v9.get("memo") else ""),
                                     "ok": True})
        for a9, (ex9, how9) in sorted(((getattr(self, "_of_auto", None) or {}).get("proven") or {}).items()):
            if ex9 and how9 == "txid" and a9 not in dec_dep9 and a9 not in ("multi", "?") and \
                    not any(str(d9.get("addr") or "").lower() == a9.lower() for d9 in deposit_rows):
                deposit_rows.append({"ex": ex9, "net": _dep_net(a9, cr=_cr9) or ("SOL" if not a9.startswith("0x") else "EVM"), "addr": a9,
                                     "memo": "보낸 내역 자동 입증(txid 일치)", "ok": True})
        ch9 = {n: c for n, c in (self.cfg.get("chains") or {}).items() if isinstance(c, dict) and not str(n).startswith("_")}
        n_rpc9 = sum(1 for n, c in ch9.items() if config.chain_discovery(n, c) == "rpc")
        wl9 = [w for w in (self.cfg.get("wallets") or []) if isinstance(w, dict) and w.get("address")]
        n_evm9 = len({str(w["address"]).lower() for w in wl9 if w.get("type", "evm") == "evm"})
        n_sol9 = len({str(w["address"]) for w in wl9 if w.get("type") == "sol"})
        n_bsc9 = len({str(w["address"]).lower() for w in wl9 if w.get("type") == "bsc_rpc"})
        sol_src9 = "Helius" if str((self.cfg.get("sol") or {}).get("rpc") or "") == "helius" else "RPC"
        src_chips = [
            {"label": f"EVM {len(ch9)}체인 · " + (f"blockscout {len(ch9) - n_rpc9} + RPC {n_rpc9}" if n_rpc9 else "blockscout"),
             "short": f"EVM {n_evm9}지갑",
             "addr": f"{self._backfill_pct('evm')} · {self._last_scan_str('evm')}"},
            {"label": f"Solana · {sol_src9}", "short": f"SOL {n_sol9}지갑",
             "addr": f"{self._backfill_pct('sol')} · {self._last_scan_str('sol')}"},
            {"label": "BSC · 공개 RPC", "short": f"BSC {n_bsc9}지갑",
             "addr": f"{self._backfill_pct('bsc')} · {self._last_scan_str('bsc')}"},
        ]
        nx_src9 = {"tron": "TronGrid", "sui": "Sui GraphQL", "ton": "toncenter", "btc": "Esplora"}
        for c9 in _cr9.configured_chains(self.cfg):
            if _cr9.available(c9):
                n9 = len(_cr9.wallets(self.cfg, c9))
                src_chips.append({"label": f"{_cr9.display_name(c9)} · {nx_src9.get(c9, 'API')}", "short": f"{_cr9.display_name(c9)} {n9}지갑",
                                  "addr": self._last_scan_str(c9)})
        wd_rows = []
        _collect_upbit_withdrawals(conn, ub_wd_shown, wd_rows)
        wd_rows.sort(key=lambda x: -x[0])
        n_ev_before_wd = len(extra_events)
        cur_src[0] = "ex:upbit"
        ctx_ns9 = [r9[0] for r9 in conn.execute(
            "SELECT DISTINCT source_ns FROM postings WHERE source_kind='chain_tx'").fetchall()]
        for wts, wd in wd_rows:
            txid = str(wd.get("txid") or "")
            cand = txid.lower() if txid.startswith("0x") else txid
            dest = "외부/미매칭"
            if txid and ctx_ns9:
                hit = conn.execute(
                    "SELECT p.location FROM postings p WHERE p.source_kind='chain_tx'"
                    " AND p.source_ns IN (" + ",".join("?" * len(ctx_ns9)) + ")"
                    " AND p.source_id IN (?, ?) AND p.leg_kind='acq'"
                    " ORDER BY p.source_ns, p.source_id, p.leg_seq LIMIT 1",
                    (*ctx_ns9, cand, txid)).fetchone()
                if hit:
                    pl = (hit["location"] or "").split(":")
                    wa2 = pl[2] if len(pl) >= 3 else None
                    lbl = (aliases.get(wa2) or self.addr_label.get(wa2)) if wa2 else None
                    dest = f"내 지갑 {lbl or (wa2[:8] if wa2 else '?')}" \
                           + (f" ({CHAIN_NAME.get(pl[1], pl[1])})" if len(pl) >= 2 else "")
            if dest == "외부/미매칭":
                if str(wd.get("currency") or "").upper() == "KRW":
                    dest = "은행 (원화 출금)"
                elif txid.startswith("swap_"):
                    dest = "토큰 전환 (업비트 내부)"
                elif cand in fx_dep_tx:
                    dest = f"{fx_name.get(fx_dep_tx[cand], fx_dep_tx[cand])} 입금 (txid 일치)"
            amt = wd.get("amount") or "?"
            extra_ev(wts, str(wd.get("currency") or "?"), "전송",
                     f"업비트 출금 → {dest}", str(amt), "—", txid or "—")
        cur_src[0] = None
        _k9 = lambda e9: e9.get("_ts", 0)
        ev_main9, ev_wd9, ev_hid9 = [], [], []
        n_wd_hid9 = 0
        tdk9 = today_kst.strftime("%Y-%m-%d")
        for e9 in extra_events:
            vq9 = e9.pop("_vq", None)
            if vq9 is None or e9.get("a") not in (None, "", "—"):
                continue
            g9 = G.get(e9.get("_gid"))
            if not g9:
                continue
            try:
                aq9 = abs(Decimal(str(vq9)))
            except (InvalidOperation, ValueError, TypeError):
                continue
            if aq9 <= 0:
                continue
            if g9.get("is_fiat"):
                e9["a"] = f"₩{float(aq9):,.0f}"
                continue
            d9 = datetime.fromtimestamp(e9.get("_ts") or 0, KST).strftime("%Y-%m-%d")
            if g9.get("is_stable"):
                p9 = 1.0
            elif d9 >= tdk9:
                p9 = float(live_px.get(g9["gid"]) or 0)
            else:
                p9 = float((((self.daily_px or {}).get(d9) or {}).get("p") or {}).get(str(g9["gid"])) or 0)
            if p9 > 0:
                e9["a"] = f"${float(aq9) * p9:,.2f}"
                e9["un"] = float(f"{p9:.10g}")
                ak9 = _ak(e9["a"], e9.get("_ts") or 0)
                if ak9 is not None:
                    e9["aK"] = ak9
        for i9, e9 in enumerate(extra_events):
            why9 = None if overrides9.get(f"g{e9.get('_gid')}") == "visible" else self._event_hide_reason(e9, G, quarantined, gid_pairs_all)
            kind9 = "scam" if why9 else None
            if not why9:
                h9 = ev_hide(e9)
                if h9:
                    kind9, why9 = h9
            if why9:
                ev_hid9.append(dict(e9, hide=why9, hideKind=kind9))
                n_wd_hid9 += i9 >= n_ev_before_wd
            else:
                (ev_main9 if i9 < n_ev_before_wd else ev_wd9).append(e9)
        ev_hid9 += pos_hid9
        for e9 in ev_main9 + ev_wd9 + ev_hid9:
            if e9.get("sym") == "TOKEN" and e9.get("_gid") in disp9:
                e9["sym"] = disp9[e9["_gid"]]
        for p9 in pendings:
            m9 = re.match(r"^g(\d+)$", str(p9.get("gkey") or "")) or re.match(r"^(?:unv|unkh|risk):g?(\d+)$", str(p9.get("key") or ""))
            if m9 and p9.get("sym") == "TOKEN" and int(m9.group(1)) in disp9:
                p9["sym"] = disp9[int(m9.group(1))]
        _nopid9 = lambda e9: {k9: v9 for k9, v9 in e9.items() if k9 not in ("_pid", "_lnk", "_mv", "_src", "_cmp", "_cv", "_tax", "_vq", "_ccapay")}
        extra_events_out = [_nopid9(e9) for e9 in sorted(sorted(ev_main9, key=_k9)[-150:] + sorted(ev_wd9, key=_k9)[-150:], key=_k9)]
        extra_events_hidden = [_nopid9(e9) for e9 in sorted(ev_hid9, key=_k9)[-150:]]
        hid_kind_n9 = {"scam": 0, "dust": 0}
        for e9 in ev_hid9:
            hid_kind_n9[e9.get("hideKind") or "scam"] = hid_kind_n9.get(e9.get("hideKind") or "scam", 0) + 1
        realized_month = sum(v for k, v in realized_by_date.items()
                             if k.startswith(today_kst.strftime("%Y-%m-")))
        gas_list = [{"chain": CHAIN_NAME.get(c, c), "spot": _f(v["usd"], 2) or 0,
                     "lp": 0, "tx": v["tx"], **({"br": _f(v["br"], 2)} if v.get("br") else {})}
                    for c, v in sorted(gas_by_chain.items(), key=lambda kv: -kv[1]["usd"])]
        exfee_lab = lambda e9: f"{fx_name.get(e9, e9)} 체결 수수료"
        gas_list += [{"chain": exfee_lab(e9), "spot": _f(v9["usd"], 2) or 0, "lp": 0, "tx": v9["tx"], "kind": "exfee", "ex": e9}
                     for e9, v9 in sorted(ex_fee.items(), key=lambda kv: -kv[1]["usd"])]
        wdfee_lab = lambda e9: f"{fx_name.get(e9, e9)} 출금 수수료"
        gas_list += [{"chain": wdfee_lab(e9), "spot": _f(v9["usd"], 2) or 0, "lp": 0, "tx": v9["tx"], "kind": "exfee", "ex": e9}
                     for e9, v9 in sorted(wd_fee.items(), key=lambda kv: -kv[1]["usd"])]
        gas_chain_usd = sum((v9["usd"] for v9 in gas_by_chain.values()), Decimal(0))
        tax_gas = {"on": gas_on, "total": _f(gas_chain_usd, 2) or 0,
                   "inCost": _f(gas_applied["buy"], 2) or 0, "inRealized": _f(gas_applied["sell"], 2) or 0,
                   "separate": _f(gas_chain_usd - (gas_applied["buy"] + gas_applied["sell"] if gas_on else 0), 2) or 0,
                   "expense": _f(sum((v9[0] - (v9[3].get("EXF_WD_FEE") or (Decimal(0),))[0] - (v9[3].get("LOAN_INT") or (Decimal(0),))[0]
                                      for v9 in gas_expense.values()), Decimal(0)), 2) or 0,
                   "wdFee": _f(sum((v9["usd"] for v9 in wd_fee.values()), Decimal(0)), 2) or 0,
                   "swapTx": gas_applied["n"],
                   "exFee": _f(sum((v9["usd"] for v9 in ex_fee.values()), Decimal(0)), 2) or 0}
        day_memos9, day_memos_err9 = DAY_MEMOS.read()
        if day_memos_err9:
            log.warning("그날 매매 근거 메모 파일 이상(%s) — 화면엔 빈 것 · 저장 거부", day_memos_err9)
        plans_out, plan_memos = self._plans_view(prefs)
        fiats = []
        xv_up_krw9 = None
        xv_up_krw_st9 = False
        if ub2:
            ub = ub2
            age_u9 = time.time() - float(ub.get("ts") or 0)
            if age_u9 < self.UB_KRW_KEEP_SEC:
                xv_up_krw9 = float(ub.get("ts") or 0)
                xv_up_krw_st9 = age_u9 >= config.upbit_fresh_sec(self.cfg)
                for acc in ub.get("accounts") or []:
                    if acc.get("currency") == "KRW":
                        try:
                            krw = float(acc.get("balance") or 0) + float(acc.get("locked") or 0)
                        except (TypeError, ValueError):
                            krw = 0
                        if krw > 0:
                            fu9 = {"ex": "업비트", "krw": krw, "note": "거래소 예수금"}
                            if xv_up_krw_st9:
                                fu9.update(age=int(age_u9), stale=True, note=f"거래소 예수금 · 업비트 잔고 {_ago_ko(age_u9)} 전")
                            fiats.append(fu9)
        fx_name9 = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX",
                    "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "coinbase": "코인베이스"}
        ex_debts = []
        bal_src9 = {}
        xv_krw9 = {}
        for ex9, kn9 in fx_name9.items():
            bp9, bd9 = exb9.get(ex9) or (None, {})
            if bp9 is None:
                continue
            bal_src9[ex9] = (bp9, float(bd9.get("ts") or 0))
            age9 = time.time() - float(bd9.get("ts") or 0)
            bal9 = bd9.get("balances")
            if not isinstance(bal9, dict):
                continue
            try:
                krw9 = float(bal9.get("KRW") or 0)
            except (TypeError, ValueError):
                continue
            kts9 = float(bd9.get("ts") or 0)
            if ex9 == "bithumb" and kts9 > 0:
                try:
                    r9, t9 = type(self)._krw_roll(self._bithumb_krw_timeline(conn), kts9)
                except Exception as e9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_b_pendings:PendingsMixin._build_pendings[r9]", e9)
                    r9, t9 = 0.0, kts9
                    log.warning("빗썸 원화 예수금 굴림 실패(스냅숏 그대로): %s", logs.safe_err(e9)[:120])
                if r9:
                    krw9 = max(0.0, krw9 + r9)
                    kts9 = max(kts9, t9)
            xv_krw9[ex9] = (max(krw9, 0.0), kts9,
                            age9 > (config.exf_fresh_sec(self.cfg) if bp9.endswith(".json") else max(21600, config.exf_fresh_sec(self.cfg))))
            if krw9 > 0:
                f9 = {"ex": kn9, "krw": krw9, "note": "거래소 예수금"}
                if age9 > config.exf_fresh_sec(self.cfg):
                    f9["age"] = int(age9)
                    f9["stale"] = True
                    f9["note"] = f"거래소 예수금 · {kn9} 잔고 {_ago_ko(age9)} 전"
                fiats.append(f9)
            loan_d9, loan_c9 = {}, {}
            for ln9 in (bd9.get("loans") if isinstance(bd9.get("loans"), list) else ()):
                if not isinstance(ln9, dict):
                    continue
                for s9, v9 in ((ln9.get("debt") or {}) if isinstance(ln9.get("debt"), dict) else {}).items():
                    try:
                        su9 = str(s9).upper()
                        loan_d9[su9] = (loan_d9.get(su9, (0.0, ln9.get("label")))[0] + float(v9), str(ln9.get("label") or "담보대출"))
                    except (TypeError, ValueError):
                        continue
                    for c9, cv9 in ((ln9.get("collateral") or {}) if isinstance(ln9.get("collateral"), dict) else {}).items():
                        try:
                            loan_c9.setdefault(su9, []).append(f"{str(c9).upper()} {float(cv9):,.6g}")
                        except (TypeError, ValueError):
                            pass
            for s9, v9 in ((bd9.get("debts") or {}) if isinstance(bd9.get("debts"), dict) else {}).items():
                try:
                    fv9 = float(v9)
                except (TypeError, ValueError):
                    continue
                if fv9 < 0:
                    su9 = str(s9).upper()
                    px9 = 1.0 if su9 in STABLE_GROUPS or _ex_stable_sym(su9) else (
                        self.spot.ex_price(ex9, su9) or self.spot.price(su9))
                    lq9, ll9 = loan_d9.get(su9, (0.0, None))
                    parts9 = []
                    if lq9 > 0:
                        lq9 = min(lq9, -fv9)
                        parts9.append((-lq9, "loan", f"{ll9} 차입(총자산에서 차감 반영 · 담보 {', '.join(loan_c9.get(su9) or []) or '—'} = 내 자산으로 계산)"))
                    if fv9 + lq9 < -1e-12:
                        parts9.append((fv9 + lq9, "margin", "마진 차입(총자산에서 차감 반영)"))
                    for q9, k9, n9 in parts9:
                        d9 = {"ex": kn9, "sym": su9, "qty": q9, "note": n9, "kind": k9}
                        if px9:
                            d9["price"] = float(px9)
                            d9["usd"] = round(q9 * float(px9), 2)
                        ex_debts.append(d9)
        for gid9, q9 in sorted(hl_neg.items()):
            if q9 < -EPS:
                sym9 = str((G.get(gid9) or {}).get("sym") or "USDC").upper()
                px9 = 1.0 if (G.get(gid9) or {}).get("is_stable") else float(live_px.get(gid9) or self.spot.ex_price("hyperliquid", sym9) or 0)
                d9 = {"ex": fx_name.get("hyperliquid", "Hyperliquid"), "sym": sym9, "qty": float(q9), "kind": "margin",
                      "note": "Hyperliquid 무기한 현금 음수(미실현 이익 인출 — 포지션 청산 때 메워짐 · 총자산에서 차감 반영)"}
                if px9:
                    d9.update(price=px9, usd=round(float(q9) * px9, 2))
                ex_debts.append(d9)
        debt_sym9 = {(d9["ex"], d9["sym"]) for d9 in ex_debts}
        neg_hold = []
        for r9 in pos_rows:
            if r9["qty"] >= -EPS or r9["gid"] in quarantined:
                continue
            g9 = G.get(r9["gid"])
            if not g9 or g9.get("is_fiat"):
                continue
            px9 = 1.0 if g9.get("is_stable") else float(live_px.get(r9["gid"]) or 0)
            usd9 = float(r9["qty"]) * px9
            if usd9 > -0.01:
                continue
            loc9 = r9["location"]
            ex9 = fx_name.get(loc9.split(":")[1], loc9.split(":")[1]) if loc9.startswith("exchange:") else None
            neg_hold.append({"key": f"g{r9['gid']}", "sym": g9["sym"], "loc": loc9, "qty": float(r9["qty"]),
                             "usd": round(usd9, 2), "debt": bool(ex9 and (ex9, (g9["sym"] or "").upper()) in debt_sym9)})
            ov9 = debt_over9.pop((loc9, (g9["sym"] or "").upper()), None)
            if ov9:
                neg_hold.append({"key": f"g{r9['gid']}", "sym": g9["sym"], "loc": loc9, "qty": -float(ov9),
                                 "usd": round(-float(ov9) * px9, 2), "debt": False, "over": True})
        neg_hold.sort(key=lambda d9: d9["usd"])
        if neg_hold:
            pend9 = self._prewin_pairs(conn)
            for n9 in neg_hold:
                if (int(n9["key"][1:]), n9["loc"]) in pend9:
                    n9["pend"] = True
        rate_fx = self.spot.rate or acct_norm.DEFAULT_KRW_USD
        hold_qty = {gid9: led_by_gid.get(gid9, Decimal(0)) + uncred_gid.get(gid9, Decimal(0)) - pv_led9.get(gid9, Decimal(0))
                    for gid9 in G if not G[gid9].get("is_fiat")}
        x_ub = sum(c["qty"] * (c.get("price") or 0) for c in coins + stables if str(c.get("key", "")).startswith("ub:"))
        x_ubs = {}
        for c in coins + stables:
            if str(c.get("key", "")).startswith("ub:"):
                a9 = x_ubs.setdefault(str(c["key"])[3:].upper(), [0.0, 0.0])
                a9[0] += float(c["qty"])
                a9[1] += float(c["qty"]) * float(c.get("price") or 0)
        x_fiat = sum(f5["krw"] / rate_fx for f5 in fiats)
        up_fresh9 = bool(ub2) and time.time() - float((ub2 or {}).get("ts") or 0) < config.upbit_fresh_sec(self.cfg)
        x_ok = True
        for p9, lim9 in ([(ub_path2, config.upbit_fresh_sec(self.cfg))] + [(paths.state(f"exf_balances_{e9}.json"), config.exf_fresh_sec(self.cfg))
                                               for e9 in fx_name9 if e9 not in bal_src9]):
            if os.path.exists(p9):
                age9 = time.time() - float((statefile.read_json(p9, {}) or {}).get("ts") or 0)
                if lim9 < age9 < 86400:
                    x_ok = False
        for e9, (p9, ts9) in bal_src9.items():
            age9 = time.time() - ts9
            lim9 = config.exf_fresh_sec(self.cfg) if p9.endswith(".json") else max(21600, config.exf_fresh_sec(self.cfg))
            if lim9 < age9 < 86400:
                x_ok = False
        lp_onchain = (statefile.read_json(paths.state("lp_positions.json"), {}) or {}).get("positions") or {}
        tok_gid = {}
        self._lp_solmeta = {r7["address"]: {"symbol": r7["symbol"], "decimals": r7["decimals"]} for r7 in conn.execute(
            "SELECT address, symbol, decimals FROM assets WHERE chain='sol' AND kind='token' AND address IS NOT NULL"
            " AND decimals IS NOT NULL").fetchall()}
        for r7 in conn.execute("SELECT kind, chain, address, group_id FROM assets"
                               " WHERE group_id IS NOT NULL AND kind IN ('token', 'native')").fetchall():
            a7 = (r7["address"] or "").lower() if r7["kind"] == "token" else lpchain.ZERO
            tok_gid.setdefault((r7["chain"], a7), r7["group_id"])
        _lpa = lambda ch9, a9: (str(a9 or "") if ch9 == "sol" else str(a9 or "").lower())
        lp_want = sorted({(oc9.get("chain") or loc9.split(":")[1], _lpa(oc9.get("chain") or loc9.split(":")[1], oc9.get(k9)))
                          for loc9, oc9 in lp_onchain.items() for k9 in ("token0", "token1", "rewardToken")
                          if str(oc9.get(k9) or "").lower() not in ("", lpchain.ZERO)})
        self.spot.want_tokens([p9 for p9 in lp_want if not token_tables.STABLE_CAS.get(p9[0], {}).get(p9[1])
                               and not (p9[0] == "sol" and token_tables.STABLE_MINTS.get(p9[1]))], slot="lp")
        def _qfmt(x):
            return f"{float(x):,.4f}".rstrip("0").rstrip(".") if x else "0"
        lps_out, lps_pending, lps_closed = [], [], []
        lp_targets9 = []
        lp_v2_units = {}
        for (ch9, _h9), d9 in lp_by_tx.items():
            if d9.get("proto") != "v2" or not d9.get("mgr"):
                continue
            for act9, t9, l9 in d9.get("liq") or []:
                if t9 is None or l9 is None:
                    continue
                k9 = f"lp:{ch9}:{d9['mgr']}:{t9}"
                lp_v2_units[k9] = lp_v2_units.get(k9, 0) + (int(l9) if act9 in ("MINT", "INCREASE") else -int(l9))
        seen_lp = set()
        for loc9, b9 in sorted(lpb.items(), key=lambda kv: -kv[1]["last"]):
            seen_lp.add(loc9)
            oc9 = lp_onchain.get(loc9) or {}
            units9 = {k: v for k, v in b9["units"].items() if v > Decimal("0.000001")}
            prin9 = sum((v for k, v in b9["ucost"].items() if k in units9), Decimal(0))
            liq9 = int(oc9.get("liquidity") or 0) if oc9 else None
            is_open = (liq9 > 0) if liq9 is not None else bool(units9)
            tid9 = lpdec.lp_tid(b9["id"])
            if tid9 is not None and (is_open or units9):
                lp_targets9.append((b9["chain"], b9["mgr"], tid9, loc9, _lp_extra(b9, loc9, tid9, lp_v2_units=lp_v2_units, lp_meta_by=lp_meta_by)))
            base9 = {"key": loc9, "id": b9["id"], "chainKey": b9["chain"], "chain": CHAIN_NAME.get(b9["chain"], b9["chain"]),
                     "mgr": b9["mgr"], "proto": b9["proto"], "dex": b9["name"],
                     "opened": datetime.fromtimestamp(b9["opened"], KST).strftime("%m-%d"),
                     "lastTs": int(b9["last"]), "openedTs": int(b9["opened"]),
                     "deposited": _f(float(b9["deposited"]), 2) or 0,
                     "principalUnits": {k: _f(float(v), 6) for k, v in units9.items()},
                     "returned": {k: _f(float(v), 6) for k, v in b9["returned"].items()},
                     "converted": {k: _f(float(v), 6) for k, v in b9["converted"].items()},
                     "acquired": {k: _f(float(v), 6) for k, v in b9["acq"].items()},
                     "realized": _f(float(b9["realized"]), 2) or 0, "income": _f(float(b9["income"]), 2) or 0,
                     "realizedByDay": {d9: round(float(v9), 2) for d9, v9 in sorted(b9["rbd"].items())},
                     "realizedKrwByDay": {d9: round(float(v9)) for d9, v9 in sorted(b9["rbdk"].items())},
                     "liquidity": str(liq9) if liq9 is not None else None}
            if not isinstance(tid9, int) and tid9 is not None:
                base9["idShort"] = (lpsol.short(str(tid9)) if not str(tid9).startswith("0x")
                                    else str(tid9)[:6] + "…" + str(tid9)[-4:])
            stk9 = ((lp_meta_by.get((b9["chain"], b9["mgr"])) or {}).get("stake") or {}).get(str(b9["id"]))
            if stk9:
                base9["staked"] = stk9
            mm9 = ((lp_meta_by.get((b9["chain"], b9["mgr"])) or {}).get("mints") or {}).get(str(b9["id"]))
            if mm9 and b9["chain"] == "sol":
                s9 = [("SOL" if m == lpsol.WSOL else ((self._lp_solmeta.get(m) or {}).get("symbol") or m[:4])) for m in mm9]
                base9["pair"] = s9
                base9["pool"] = f"{s9[0]} / {s9[1]}"
            if oc9.get("sym0") and oc9.get("sym1"):
                base9["pair"] = [oc9.get("sym0"), oc9.get("sym1")]
            if not is_open:
                base9["closed"] = True
                base9["residualUnits"] = base9["principalUnits"]
                lps_closed.append(base9)
                continue
            val9 = _lp_value(oc9, b9["chain"], lpa=_lpa, tok_gid=tok_gid, live_px=live_px, sb=self) if oc9 else None
            if val9 is None:
                base9["closed"] = False
                base9["pendingReason"] = ("온체인 평가 대기" if not oc9 else
                                          "지정가 주문 — 온체인 평가 미지원" if oc9.get("limitOrder") else "토큰 시세 없음")
                lps_pending.append(base9)
                continue
            s0, s1 = oc9.get("sym0") or "?", oc9.get("sym1") or "?"
            fee9 = oc9.get("fee")
            if oc9.get("proto") == "meteora_dlmm":
                tier9 = f"bin {oc9.get('binStep')}bp"
            elif oc9.get("proto") == "v2":
                tier9 = "stable" if oc9.get("stable") else ("volatile" if oc9.get("stable") is False else "v2")
            elif oc9.get("proto") == "slipstream" or fee9 is None:
                tier9 = f"틱간격 {oc9.get('tickSpacing')}"
            elif int(fee9) & 0x800000:
                tier9 = "동적 수수료"
            else:
                tier9 = f"{int(fee9) / 10000:.2f}%".replace(".00%", "%")
            hold9 = None
            if all(k in (s0, s1) for k in units9):
                hold9 = sum(float(v) * (val9["p0"] if k == s0 else val9["p1"]) for k, v in units9.items())
            days9 = max(1.0, (now - b9["opened"]) / 86400)
            row9 = dict(base9)
            row9.update({
                "pool": f"{s0} / {s1}", "tier": tier9, "closed": False,
                "status": "범위 내" if oc9.get("inRange") else "범위 이탈",
                "range": (f"전 구간(v2) · 현재 {float(oc9.get('price') or 0):,.6g} ({s1}/{s0})" if oc9.get("proto") == "v2" else
                          f"{float(oc9.get('priceLower') or 0):,.6g} – {float(oc9.get('priceUpper') or 0):,.6g} ({s1}/{s0})"),
                "deposit": round(float(prin9), 2), "value": round(val9["value"], 2), "fees": round(val9["fees"], 2),
                "rewards": round(val9.get("rewards") or 0, 2), "il": round(val9["value"] - hold9, 2) if hold9 is not None else 0,
                "apr": (f"{(val9['fees'] + (val9.get('rewards') or 0)) / float(prin9) * 365 / days9 * 100:.1f}%" if prin9 > 0 else "—"),
                "comp": [{"sym": s0, "then": _qfmt(units9.get(s0)), "now": _qnow(oc9.get("amount0"), qfmt=_qfmt)},
                         {"sym": s1, "then": _qfmt(units9.get(s1)), "now": _qnow(oc9.get("amount1"), qfmt=_qfmt)}],
                "feesStale": bool(oc9.get("feesStale"))})
            b9["pool"] = row9["pool"]
            lps_out.append(row9)
        for loc9, oc9 in lp_onchain.items():
            if loc9 in seen_lp or int(oc9.get("liquidity") or 0) <= 0:
                continue
            parts9 = loc9.split(":")
            if len(parts9) < 4:
                continue
            mg9 = (lp_mgrs.get(parts9[1]) or {}).get(parts9[2]) or {}
            val9 = _lp_value(oc9, parts9[1], lpa=_lpa, tok_gid=tok_gid, live_px=live_px, sb=self)
            s0, s1 = oc9.get("sym0") or "?", oc9.get("sym1") or "?"
            ent9 = {"key": loc9, "id": parts9[3], "chainKey": parts9[1], "chain": CHAIN_NAME.get(parts9[1], parts9[1]),
                    "mgr": parts9[2], "proto": mg9.get("proto"), "dex": mg9.get("name") or "LP", "noLedger": True,
                    "liquidity": str(oc9.get("liquidity")), "closed": False}
            lp_targets9.append((parts9[1], parts9[2], int(parts9[3]), loc9, {})) if parts9[3].isdigit() else None
            if val9 is None:
                ent9["pendingReason"] = "토큰 시세 없음"
                lps_pending.append(ent9)
                continue
            ent9.update({"pool": f"{s0} / {s1}", "tier": "—", "opened": "—",
                         "status": "범위 내" if oc9.get("inRange") else "범위 이탈",
                         "range": f"{float(oc9.get('priceLower') or 0):,.6g} – {float(oc9.get('priceUpper') or 0):,.6g} ({s1}/{s0})",
                         "deposit": 0, "value": round(val9["value"], 2), "fees": round(val9["fees"], 2),
                         "rewards": round(val9.get("rewards") or 0, 2),
                         "il": 0, "apr": "—",
                         "comp": [{"sym": s0, "then": "—", "now": _qnow(oc9.get("amount0"), qfmt=_qfmt)},
                                  {"sym": s1, "then": "—", "now": _qnow(oc9.get("amount1"), qfmt=_qfmt)}]})
            lps_out.append(ent9)
        with self._lp_lock:
            self._lp_targets = lp_targets9
        lp_ev_by9 = {}
        for e9 in sorted(lp_events, key=lambda e9: e9["_ts"]):
            lp_ev_by9.setdefault(e9.get("lp"), []).append(e9)
        lp_events_out = sorted((e9 for l9 in lp_ev_by9.values() for e9 in l9[-300:]), key=lambda e9: e9["_ts"])
        lp_total = sum((l9["value"] + l9["fees"] + (l9.get("rewards") or 0)) for l9 in lps_out)
        rb_recon = []
        bot_w9 = {}
        row_px_b9 = {c9["key"]: float(c9.get("price") or 0) for c9 in coins + stables}
        for gid9, lr9 in locs_by_gid.items():
            px9 = row_px_b9.get(f"g{gid9}", 0.0)
            if px9 <= 0:
                continue
            for l9 in lr9:
                p9 = str(l9["location"] or "").split(":")
                if p9[0] != "wallet" or len(p9) < 3 or not p9[2]:
                    continue
                u9 = float(Decimal(l9["qty_norm"])) * px9
                if u9 > 0:
                    bot_w9[p9[2].lower()] = bot_w9.get(p9[2].lower(), 0.0) + u9
        for l9 in lps_out:
            ow9 = str((lp_onchain.get(l9.get("key")) or {}).get("owner") or "").lower()
            if ow9:
                bot_w9[ow9] = bot_w9.get(ow9, 0.0) + float(l9.get("value") or 0) + float(l9.get("fees") or 0) \
                    + float(l9.get("rewards") or 0)
        self._bot_wallet_usd = dict(bot_w9)
        if self.__dict__.get("_bot_usd_saved") != bot_w9:
            try:
                statefile.atomic_write_json(paths.state(rabby.BOTUSD_NAME), {"v": 1, "t": int(now), "w": {a9: round(v9, 2) for a9, v9 in bot_w9.items()}})
                self._bot_usd_saved = dict(bot_w9)
            except OSError as e9:
                log.warning("지갑별 봇 평가 저장 실패(다음 빌드에 다시): %s", e9)
        if rb_view:
            for a9, wv9 in sorted(rb_view["wallets"].items(), key=lambda kv: -kv[1]["rabby"]):
                b9 = round(bot_w9.get(a9, 0.0), 2)
                rb_recon.append({"addr": a9, "label": rb_view["labels"].get(a9) or a9[:8], "bot": b9, "rabby": wv9["rabby"],
                                 "diff": round(wv9["rabby"] - b9, 2), "only": wv9["only"], "onlyDebt": wv9["onlyDebt"],
                                 "rest": round(wv9["rabby"] - b9 - wv9["only"] - wv9["onlyDebt"], 2),
                                 "fetchedAt": wv9["fetchedAt"], "top": wv9["top"],
                                 "skipped": {k9: v9 for k9, v9 in wv9["skipped"].items() if v9 >= 1}, "err": wv9.get("err")})
            try:
                gs9 = rabby.gap_track(paths.state(rabby.GAP_NAME), rb_recon, now)
                for r9 in rb_recon:
                    if r9["addr"] in gs9:
                        r9["gapSince"] = gs9[r9["addr"]]
            except Exception as e9:   # noqa: BLE001 [optional]
                calcguard.swallowed("view_b_pendings:PendingsMixin._build_pendings[gs9]", e9)
                log.warning("Rabby 차이 추적 실패: %s", e9)
        tc9 = self.cfg.get("transit") if isinstance(self.cfg.get("transit"), dict) else {}
        ask9 = now - float(tc9.get("ask_days", TRANSIT_ASK_DAYS)) * 86400
        for a9m, st9 in (getattr(self, "_of_man_state", None) or {}).items():
            fin9 = (sale_lot_by.get("of:" + a9m) or {}).get("fin")
            if fin9:
                st9["paidUsd"] = fin9[1]
                if fin9[0] == "ok":
                    st9["costUsd"] = fin9[2]
            lm9 = sale_lot_by.get("of:" + a9m) or {}
            st9["payHold"] = lm9.get("pay_hold")
            st9["pay"] = {k9: float(lm9["_pay"][k9]) for k9 in ("q", "usd", "rz", "n")} if lm9.get("_pay") else None
            for l9 in st9["links"].values():
                if l9.get("st") == "pending":
                    ap9 = of_applied.get(l9.get("pid"))
                    l9["st"] = "applied" if ap9 else (fin9[0] if fin9 and fin9[0] != "ok" else "other_path")
                    if ap9:
                        l9["cost"] = ap9[1]
        self._of_cands = of_cands
        cl_legs9 = {}
        dec_cl9 = self.outflow_decisions()
        for a9c, st9c in (getattr(self, "_of_man_state", None) or {}).items():
            for l9c in ((dec_cl9.get(a9c) or {}).get("links") or []):
                if not isinstance(l9c, dict):
                    continue
                s9c = (st9c.get("links") or {}).get(str(l9c.get("key") or "")) or {}
                cl_legs9.setdefault(a9c, []).append({"kind": l9c.get("kind"), "st": s9c.get("st"), "tx": l9c.get("tx"), "sym": l9c.get("sym"),
                                                     "qty": l9c.get("qty"), "where": l9c.get("where"), "key": self._of_key_cur(a9c, l9c)})
        self._of_claim_legs = cl_legs9
        self._ph("pendings")
        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")

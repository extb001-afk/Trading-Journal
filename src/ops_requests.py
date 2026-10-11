from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import time

import common

GATE_NAME = "rebuild_pnl_gate.json"
APPROVE_NAME = "rebuild_pnl_approve.json"
REJ_DIR_NAME = "rebuild_rejected"
REJ_KEEP = 20
APPROVE_TTL = 48 * 3600
REBUILD_FAIL_LABEL = {"resource_disk": "디스크 공간", "transient_rpc": "일시 오류(업비트 대사·수집 미완)", "integrity": "무결성 검사",
                      "position_gate": "포지션 게이트", "pnl_approval": "손익 승인 대기", "interrupted": "도중 중단", "timeout": "시간 초과",
                      "error": "그 밖 오류"}
UNV_GROUP_EPS = 1.0
POISON_NAME = "poison.jsonl"
POISON_REQ_NAME = "poison_replay_request.json"
POISON_DONE_NAME = "poison_replayed.json"
DEC_ISSUES_NAME = "asset_decimals_issues.json"
DEC_REQ_NAME = "decimals_resolve_request.json"
DEC_RES_NAME = "decimals_resolve_result.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _p(name: str) -> str:
    return os.path.join(common.STATE_DIR, name)


def _safe_read(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def tol_of(bcfg) -> tuple:
    bcfg = bcfg if isinstance(bcfg, dict) else {}
    tu9, tp9 = _fin(bcfg.get("rebuild_pnl_tol_usd")), _fin(bcfg.get("rebuild_pnl_tol_pct"))
    tol_usd = tu9 if tu9 is not None and tu9 >= 0 else 50.0
    tol_pct = tp9 if tp9 is not None and tp9 >= 0 else 0.01
    return tol_usd, tol_pct


def _tol(tol_usd, tol_pct, a, b) -> float:
    return max(tol_usd, tol_pct * max(abs(a), abs(b)))


def _same_as_appr(new_d, appr_d, tol_usd, tol_pct) -> bool:
    n9, a9 = _fin(new_d), _fin(appr_d)
    if n9 is None or a9 is None:
        return False
    return abs(n9 - a9) <= max(tol_usd, tol_pct * abs(a9))


def appr_tol(ap, tol_usd: float, tol_pct: float) -> tuple:
    t9 = ap.get("tol") if isinstance(ap, dict) else None
    if isinstance(t9, list) and len(t9) == 2:
        u9, p9 = _fin(t9[0]), _fin(t9[1])
        if u9 is not None and u9 >= 0:
            tol_usd = min(tol_usd, u9)
        if p9 is not None and p9 >= 0:
            tol_pct = min(tol_pct, p9)
    return tol_usd, tol_pct


def _fin(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _num_map(d) -> dict | None:
    if not isinstance(d, dict):
        return None
    out = {}
    for k, v in d.items():
        f = _fin(v)
        if f is None:
            return None
        out[str(k)] = f
    return out


def gate_eval(rep: dict, tol_usd: float, tol_pct: float) -> dict:
    rep = rep if isinstance(rep, dict) else {}
    g4 = rep.get("G4_vs_baseline") if isinstance(rep.get("G4_vs_baseline"), dict) else {}
    missing, parts = [], []
    months = []
    mb, ms = _num_map(g4.get("realized_by_month_baseline")), _num_map(g4.get("realized_by_month_shadow"))
    if mb is None or ms is None:
        missing.append("months")
    else:
        for m9 in sorted(set(mb) | set(ms)):
            a9, b9 = mb.get(m9, 0.0), ms.get(m9, 0.0)
            if abs(b9 - a9) > _tol(tol_usd, tol_pct, a9, b9):
                months.append({"month": m9, "before": round(a9, 2), "after": round(b9, 2), "diff": round(b9 - a9, 2)})
        months.sort(key=lambda x: -abs(x["diff"]))
    ub = g4.get("unverified_baseline") if isinstance(g4.get("unverified_baseline"), dict) else {}
    us = g4.get("unverified_shadow") if isinstance(g4.get("unverified_shadow"), dict) else {}
    ua, ub9 = _fin(ub.get("sum")), _fin(us.get("sum"))
    if ua is None or ub9 is None:
        ua, ub9 = 0.0, 0.0
        missing.append("unv")
    unv_up = ub9 - ua > _tol(tol_usd, tol_pct, ua, ub9)
    bb9, bs9 = _num_map(ub.get("by")), _num_map(us.get("by"))
    unv_groups = (sorted(k9 for k9 in set(bb9) | set(bs9) if bs9.get(k9, 0.0) - bb9.get(k9, 0.0) > UNV_GROUP_EPS)
                  if bb9 is not None and bs9 is not None else None)
    unv_deltas = {k9: round(bs9.get(k9, 0.0) - bb9.get(k9, 0.0), 2) for k9 in unv_groups} if unv_groups is not None else None
    cl9 = rep.get("cost_lost") if isinstance(rep.get("cost_lost"), dict) else None
    n9 = cl9.get("n") if cl9 is not None else None
    lost_usd = _fin(cl9.get("usd")) if cl9 is not None else None
    if isinstance(n9, int) and not isinstance(n9, bool) and n9 >= 0 and lost_usd is not None and lost_usd >= 0:
        lost_n = n9
    else:
        lost_n, lost_usd = -1, 0.0
    if lost_n < 0:
        missing.append("cost_lost")
    dun9 = rep.get("decimals_unresolved")
    if isinstance(dun9, list) and all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in dun9):
        dun = sorted(dun9)
    else:
        dun = []
        missing.append("decimals_unresolved")
    ocb, ocs = _num_map(g4.get("open_cost_baseline")), _num_map(g4.get("open_cost_shadow"))
    hc = g4.get("open_cost_held_cards")
    hm = g4.get("open_cost_missing_groups")
    open_cost = []
    hc_ok = isinstance(hc, list) and len(hc) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in hc)
    hm_ok = isinstance(hm, list) and len(hm) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in hm)
    if (ocb is None or ocs is None or not hc_ok or not hm_ok or (hc[0] > 0 and not ocb) or (hc[1] > 0 and not ocs)
            or hm[0] > 0 or hm[1] > 0):
        missing.append("open_cost")
    else:
        for k9 in sorted(set(ocb) | set(ocs)):
            a9, b9 = ocb.get(k9, 0.0), ocs.get(k9, 0.0)
            if abs(b9 - a9) > _tol(tol_usd, tol_pct, a9, b9):
                open_cost.append({"group": k9, "sym": ((g4.get("open_cost_sym") or {}) if isinstance(g4.get("open_cost_sym"), dict) else {}).get(k9),
                                  "before": round(a9, 2), "after": round(b9, 2), "diff": round(b9 - a9, 2)})
        open_cost.sort(key=lambda x: -abs(x["diff"]))
    if "months" in missing:
        parts.append("리포트에 월별 실현 없음(web 비교 실패) — fail-closed")
    if months:
        parts.append("월별 실현 차이 %d달: " % len(months) + " · ".join(f"{x['month']} {x['diff']:+,.2f}" for x in months[:3]))
    if unv_up:
        parts.append(f"원가미상 매도 ${ua:,.0f} → ${ub9:,.0f}")
    if lost_n > 0:
        parts.append(f"원가 사라진 칸 {lost_n}개(${lost_usd:,.0f}): "
                     + " · ".join(f"{x.get('sym')} {x.get('event')} ${float(x.get('cost_baseline') or 0):,.0f}" for x in (cl9.get("top") or [])[:3] if isinstance(x, dict)))
    elif lost_n < 0:
        parts.append("리포트에 원가 소실 집계 없음 — fail-closed")
    if "unv" in missing:
        parts.append("리포트에 원가미상 매도 집계 없음 — fail-closed")
    if "decimals_unresolved" in missing:
        parts.append("리포트에 자리수 미해결 집계 없음 — fail-closed")
    if dun:
        parts.append(f"토큰 자리수 채움 대기 {len(dun)}개가 재구축 뒤에도 비어 있음(#{', #'.join(str(x) for x in dun[:5])})")
    if open_cost:
        parts.append("안 판 포지션 원가 차이 %d개: " % len(open_cost)
                     + " · ".join(f"{x.get('sym') or ('그룹 ' + x['group'])} {x['diff']:+,.2f}" for x in open_cost[:3]))
    elif "open_cost" in missing:
        parts.append("리포트에 안 판 포지션 원가 없음 — fail-closed")
    ok = not (missing or months or unv_up or lost_n != 0 or dun or open_cost)
    return {"ok": ok, "reason": " · ".join(parts), "months": months, "unv": {"before": round(ua, 2), "after": round(ub9, 2),
            "rows_before": ub.get("rows"), "rows_after": us.get("rows")}, "unv_up": unv_up,
            "cost_lost": cl9 or {"n": None}, "lost_n": lost_n, "lost_usd": round(lost_usd, 2), "decimals_unresolved": dun,
            "open_cost": open_cost, "missing": missing, "unv_groups": unv_groups, "unv_deltas": unv_deltas}


def covers(appr: dict, new: dict, tol_usd: float, tol_pct: float) -> str:
    if not isinstance(appr, dict) or not isinstance(new, dict):
        return "승인 비교 재료 없음"
    for nm9, x9 in (("승인한", appr), ("새", new)):
        m9 = x9.get("missing")
        if not isinstance(m9, list) or m9:
            return f"{nm9} 결과에 빠진 재료가 있어 승인한 결과와 같은지 확인할 수 없음(" + (", ".join(str(v) for v in m9) if isinstance(m9, list) else "?") + ")"
    for k9, kk9 in (("months", "month"), ("open_cost", "group"), ("decimals_unresolved", None)):
        for nm9, x9 in (("승인한", appr), ("새", new)):
            l9 = x9.get(k9)
            if not isinstance(l9, list) or (kk9 and not all(isinstance(e9, dict) and isinstance(e9.get(kk9), str) for e9 in l9)):
                return f"{nm9} 결과의 비교 재료({k9}) 형식 이상 — 승인한 결과와 같은지 확인할 수 없음"
    am = {x["month"]: x for x in appr["months"]}
    for x in new["months"]:
        y = am.get(x["month"])
        if y is None:
            return f"새 달 차이 {x['month']} {x['diff']:+,.2f}"
        if not _same_as_appr(x.get("diff"), y.get("diff"), tol_usd, tol_pct):
            return f"{x['month']} 차이 {_fmt(y.get('diff'))} → {_fmt(x.get('diff'))}"
    if new.get("unv_up") or new.get("unv_groups"):
        if new.get("unv_up"):
            if not appr.get("unv_up"):
                return "원가미상 매도 증가(승인 때 없음)"
            au9 = appr.get("unv") if isinstance(appr.get("unv"), dict) else {}
            nu9 = new.get("unv") if isinstance(new.get("unv"), dict) else {}
            aa9, ab9, na9, nb9 = _fin(au9.get("after")), _fin(au9.get("before")), _fin(nu9.get("after")), _fin(nu9.get("before"))
            if None in (aa9, ab9, na9, nb9):
                return "원가미상 매도 증가분 재료 없음 — 승인한 결과와 같은지 확인할 수 없음"
            ad9, bd9 = aa9 - ab9, na9 - nb9
            if bd9 > ad9 and not _same_as_appr(bd9, ad9, tol_usd, tol_pct):
                return f"원가미상 매도 증가분 ${ad9:,.0f} → ${bd9:,.0f}"
        ag9, ng9 = appr.get("unv_groups"), new.get("unv_groups")
        if not isinstance(ag9, list) or not isinstance(ng9, list):
            return "원가미상 매도 그룹 재료 없음 — 승인한 결과와 같은지 확인할 수 없음"
        if not set(ng9) <= set(ag9):
            return "원가미상 매도가 승인 때와 다른 포지션에서 늘어남(" + ", ".join(sorted(set(ng9) - set(ag9)))[:80] + ")"
        adg9, ndg9 = _num_map(appr.get("unv_deltas")), _num_map(new.get("unv_deltas"))
        if adg9 is None or ndg9 is None or set(adg9) != set(ag9) or set(ndg9) != set(ng9):
            return "원가미상 매도 그룹별 증가분 재료 없음 — 승인한 결과와 같은지 확인할 수 없음"
        for k9 in ng9:
            if ndg9[k9] > adg9[k9] and not _same_as_appr(ndg9[k9], adg9[k9], tol_usd, tol_pct):
                return f"원가미상 매도 그룹 {k9} 증가분 ${adg9[k9]:,.0f} → ${ndg9[k9]:,.0f}"
    an9, nn9 = appr.get("lost_n"), new.get("lost_n")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (an9, nn9)):
        return "원가 소실 집계 재료 없음 — 승인한 결과와 같은지 확인할 수 없음"
    if nn9 < 0 or an9 < 0:
        return "원가 소실 집계 없음"
    if nn9 > an9:
        return f"원가 사라진 칸 {an9} → {nn9}"
    au9, nu9 = _fin(appr.get("lost_usd")), _fin(new.get("lost_usd"))
    if au9 is None or nu9 is None:
        return "원가 사라진 금액 재료 없음 — 승인한 결과와 같은지 확인할 수 없음"
    if nu9 > au9 + tol_usd:
        return "원가 사라진 금액 증가"
    if nn9 > 0:
        why9 = _lost_cover(appr.get("cost_lost"), new.get("cost_lost"), tol_usd)
        if why9:
            return why9
    if not set(new["decimals_unresolved"]) <= set(appr["decimals_unresolved"]):
        return "자리수 미해결 자산 증가"
    ao = {x["group"]: x for x in appr["open_cost"]}
    for x in new["open_cost"]:
        y = ao.get(x["group"])
        if y is None:
            return f"새 포지션 원가 차이 {x.get('sym') or x['group']} {x['diff']:+,.2f}"
        if not _same_as_appr(x.get("diff"), y.get("diff"), tol_usd, tol_pct):
            return f"{x.get('sym') or x['group']} 원가 차이 {_fmt(y.get('diff'))} → {_fmt(x.get('diff'))}"
    if not set(new.get("missing") or []) <= set(appr.get("missing") or []):
        return "빠진 재료(" + ", ".join(sorted(set(new.get("missing") or []) - set(appr.get("missing") or []))) + ")"
    return ""


def _fmt(v) -> str:
    f9 = _fin(v)
    return f"{f9:+,.2f}" if f9 is not None else "?"


def _lost_keys(cl) -> dict | None:
    if not isinstance(cl, dict) or not isinstance(cl.get("top"), list) or cl.get("n") != len(cl["top"]):
        return None
    out = {}
    for x in cl["top"]:
        k9 = x.get("key") if isinstance(x, dict) else None
        if not isinstance(k9, list) or not k9:
            return None
        c9 = _fin(x.get("cost_baseline"))
        if c9 is None:
            return None
        out[json.dumps(k9, ensure_ascii=False, sort_keys=True)] = abs(c9)
    return out


def _lost_cover(acl, ncl, tol_usd: float = 0.0) -> str:
    ak9, nk9 = _lost_keys(acl), _lost_keys(ncl)
    if ak9 is not None and nk9 is not None:
        if not set(nk9) <= set(ak9):
            return "원가 사라진 칸이 승인 때와 다름"
        for k9, v9 in nk9.items():
            if v9 > ak9[k9] + tol_usd:
                return f"원가 사라진 칸 금액 ${ak9[k9]:,.0f} → ${v9:,.0f}"
        return ""
    ah9 = acl.get("keys_sha") if isinstance(acl, dict) else None
    nh9 = ncl.get("keys_sha") if isinstance(ncl, dict) else None
    ac9 = acl.get("costs_sha") if isinstance(acl, dict) else None
    nc9 = ncl.get("costs_sha") if isinstance(ncl, dict) else None
    if isinstance(nh9, str) and _HEX64.match(nh9) and nh9 == ah9:
        if isinstance(nc9, str) and _HEX64.match(nc9) and nc9 == ac9:
            return ""
        return "원가 사라진 칸별 금액이 승인 때와 다르거나 재료 없음 — 다시 확인"
    return "원가 사라진 칸 목록 재료 없음 — 승인한 결과와 같은 칸인지 확인할 수 없음"


def file_sha(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None


def rej_dir() -> str:
    return _p(REJ_DIR_NAME)


def find_rejected(sha: str) -> str | None:
    if not isinstance(sha, str) or not _HEX64.match(sha):
        return None
    d = rej_dir()
    try:
        names = sorted(os.listdir(d), reverse=True)
    except OSError:
        return None
    for n in names:
        if sha[:16] in n and n.endswith(".report.json"):
            p = os.path.join(d, n)
            if file_sha(p) == sha:
                return p
    return None


def preserve_report(report_path: str) -> tuple:
    sha = file_sha(report_path)
    if not sha:
        return None, None
    d = rej_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    have = find_rejected(sha)
    if have:
        return sha, os.path.basename(have)
    name = time.strftime("%Y%m%d_%H%M%S") + f"_{sha[:16]}.report.json"
    dst = os.path.join(d, name)
    tmp = dst + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f, open(report_path, "rb") as src:
            shutil.copyfileobj(src, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if file_sha(dst) != sha:
        try:
            os.remove(dst)
        except OSError:
            pass
        return None, None
    _prune_rejected(keep_name=name)
    return sha, name


def _prune_rejected(keep_name: str = ""):
    d = rej_dir()
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".report.json"))
    except OSError:
        return
    ap = _safe_read(_p(APPROVE_NAME), None)
    keep_sha = ap.get("report_sha") if isinstance(ap, dict) and isinstance(ap.get("report_sha"), str) else ""
    extra = len(names) - REJ_KEEP
    for n in names:
        if extra <= 0:
            break
        if (keep_sha and keep_sha[:16] in n) or n == keep_name:
            continue
        try:
            os.remove(os.path.join(d, n))
            extra -= 1
        except OSError:
            pass


def approval_check(new_ev: dict, tol_usd: float, tol_pct: float, now: float = None) -> tuple:
    now = time.time() if now is None else now
    ap = common.read_control_json(_p(APPROVE_NAME), None)
    if not isinstance(ap, dict):
        return False, "", None
    until = _fin(ap.get("until"))
    if until is None or until > now + APPROVE_TTL + 600:
        return False, "승인 기한이 이상해요 — 다시 승인하세요", None
    if until <= now:
        return False, "승인 기한 지남 — 다시 승인하세요", None
    sha = ap.get("report_sha")
    if not isinstance(sha, str) or not _HEX64.match(sha):
        return False, "승인에 보고서 해시가 없어요(옛 형식) — 보고서를 확인하고 다시 승인하세요", None
    p = find_rejected(sha)
    if not p:
        return False, "승인한 보고서 보존본이 없어요 — 새 결과를 확인하고 다시 승인하세요", sha
    try:
        appr_rep = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return False, "승인한 보고서를 읽지 못했어요 — 다시 승인하세요", sha
    tu9, tp9 = appr_tol(ap, tol_usd, tol_pct)
    diff = covers(gate_eval(appr_rep, tu9, tp9), new_ev, tu9, tp9)
    if diff:
        return False, "승인한 결과와 달라요(" + diff + ") — 새 결과를 확인하고 다시 승인하세요", sha
    return True, "", sha


def gate_record() -> dict | None:
    g = _safe_read(_p(GATE_NAME), None)
    return g if isinstance(g, dict) else None


def report_missing(path: str) -> list | None:
    try:
        with open(path, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None
    return list(gate_eval(rep, 50.0, 0.01).get("missing") or [])


def pending_gate() -> dict | None:
    g = gate_record()
    if not g or g.get("ok") or g.get("approved"):
        return None
    return g


def approve(report_sha: str, by: str, now: float = None) -> tuple:
    now = time.time() if now is None else now
    g = pending_gate()
    if not g:
        return False, "승인할 보류 결과가 없어요(마지막 재계산이 통과했거나 아직 안 돌았음)"
    want = g.get("report_sha")
    if not isinstance(want, str) or not _HEX64.match(want):
        return False, "보류 기록에 보고서가 없어요(옛 기록 · 보고서 없음) — 다음 재계산 결과로 승인하세요"
    if report_sha != want:
        return False, "화면의 결과가 마지막 보류 결과와 달라요 — 새로 고친 뒤 다시"
    rp9 = find_rejected(want)
    if not rp9:
        return False, "보류된 보고서 보존본이 없어요 — 다음 재계산 결과로 승인하세요"
    miss9 = report_missing(rp9)
    if miss9 is None or miss9:
        return False, ("보류된 보고서에 빠진 재료가 있어 승인할 수 없어요(" + ", ".join(miss9 or ["읽기 실패"]) + ") — 재계산 보고서가 온전해야 승인할 수 있어요")
    common.atomic_write_json(_p(APPROVE_NAME), {"report_sha": want, "until": int(now) + APPROVE_TTL, "at": int(now), "by": str(by)[:40],
                                                "gate_ts": g.get("ts"), "tol": g.get("tol") if isinstance(g.get("tol"), list) else None})
    return True, "승인함 — 이 결과와 같은 다음 재계산 1회(48시간 안)를 교체합니다"


def cancel_approve() -> bool:
    try:
        os.remove(_p(APPROVE_NAME))
        return True
    except OSError:
        return False


def poison_id(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry.get("rec"), ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def poison_entries(limit: int = 200) -> list:
    done = _safe_read(_p(POISON_DONE_NAME), {}) or {}
    done = done if isinstance(done, dict) else {}
    by = {}
    try:
        with open(_p(POISON_NAME), encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if not isinstance(e, dict):
                    continue
                rec = e.get("rec") if isinstance(e.get("rec"), dict) else {}
                pid = poison_id(e)
                st = done.get(pid) if isinstance(done.get(pid), dict) else {}
                ref = rec.get("txhash") or rec.get("hash") or ((rec.get("tx") or {}).get("hash") if isinstance(rec.get("tx"), dict) else None) \
                    or rec.get("exchange") or rec.get("chain") or ""
                by[pid] = {"id": pid, "ts": int(e.get("ts") or 0), "kind": str(rec.get("kind") or "?")[:24], "chain": str(rec.get("chain") or "")[:16],
                           "ref": str(ref)[:20], "err": common.safe_err(str(e.get("err") or ""))[:160],
                           "corrupt": rec.get("kind") == "_corrupt",
                           "state": "성공" if st.get("ok") else ("실패" if st else "대기"), "rerr": common.safe_err(str(st.get("err") or ""))[:120]}
    except OSError:
        pass
    out = sorted(by.values(), key=lambda x: -x["ts"])
    return out[:limit]


def poison_request(ids=None, all_=False, by: str = "") -> tuple:
    ents = {e["id"]: e for e in poison_entries(limit=10 ** 6)}
    if all_:
        todo = [i for i, e in ents.items() if e["state"] != "성공" and not e["corrupt"]]
        if not todo:
            return False, "다시 처리할 격리 기록이 없어요"
        _poison_req_write(True, [], by)
        return True, f"요청함 — 격리 기록 {len(todo)}건을 tj-core 가 다음 주기에 다시 처리합니다"
    ids = [str(x) for x in (ids or []) if isinstance(x, str)]
    if not ids or len(ids) > 500:
        return False, "다시 처리할 기록을 고르세요(최대 500)"
    bad = [i for i in ids if i not in ents or ents[i]["state"] == "성공" or ents[i]["corrupt"]]
    if bad:
        return False, f"지금 목록에 없거나 이미 처리된 기록 {len(bad)}건 — 새로 고친 뒤 다시"
    n9 = _poison_req_write(False, ids, by)
    return True, f"요청함 — {len(ids)}건을 tj-core 가 다음 주기에 다시 처리합니다" + (f"(아직 처리 전인 앞 요청과 합쳐 {n9}건)" if n9 > len(ids) else "")


def _poison_req_write(all_: bool, ids: list, by: str) -> int:
    import fcntl
    path = _p(POISON_REQ_NAME)
    with open(path + ".lock", "a+") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            prev = _safe_read(path, None)
            if isinstance(prev, dict):
                if prev.get("all") is True:
                    all_ = True
                elif not all_:
                    ids = list(dict.fromkeys([str(x) for x in (prev.get("ids") or []) if isinstance(x, str)] + list(ids)))[:5000]
            common.atomic_write_json(path, {"all": bool(all_), "ids": [] if all_ else ids, "ts": int(time.time()), "by": str(by)[:40]})
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    return 0 if all_ else len(ids)


def _meta_dec_cache(chain: str, ca: str):
    if not chain or not ca:
        return None
    name = "bsc_token_meta.json" if chain == "bsc" else f"rpc_token_meta_{chain}.json"
    raw = _safe_read(_p(name), {}) or {}
    v = raw.get(str(ca).lower()) if isinstance(raw, dict) else None
    if v is None and isinstance(raw, dict):
        v = next((vv for kk, vv in raw.items() if str(kk).lower() == str(ca).lower()), None)
    v = v[1] if isinstance(v, (list, tuple)) and len(v) >= 2 else v
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 77 else None


def decimals_items() -> list:
    d = _safe_read(_p(DEC_ISSUES_NAME), {}) or {}
    out = []
    for k, it in ((d.get("items") or {}) if isinstance(d, dict) else {}).items():
        if not isinstance(it, dict):
            continue
        try:
            aid = int(k)
        except (TypeError, ValueError):
            continue
        out.append({"aid": aid, "kind": str(it.get("kind") or ""), "chain": it.get("chain"), "symbol": it.get("symbol"), "address": it.get("address"),
                    "stored": it.get("stored"), "seen": it.get("seen"), "ts": it.get("ts")})
    return sorted(out, key=lambda x: (x["kind"] != "conflict", x["aid"]))


def _ledger_decimals(aid: int):
    if not os.path.exists(common.DB_PATH):
        return "nodb"
    c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
    try:
        r = c.execute("SELECT decimals, chain, address FROM assets WHERE asset_id=?", (int(aid),)).fetchone()
    finally:
        c.close()
    return r


def decimals_check(aid, stored, seen) -> str:
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (aid, stored, seen)) or not (0 <= seen <= 77):
        return "형식 오류(asset_id·stored·seen 정수)"
    it = next((x for x in decimals_items() if x["aid"] == aid), None)
    if not it or it["kind"] != "conflict":
        return "지금 '자리수 다름' 목록에 없는 자산"
    if it.get("stored") != stored or it.get("seen") != seen:
        return "목록 값이 바뀌었어요 — 새로 고친 뒤 다시"
    r = _ledger_decimals(aid)
    if r == "nodb" or r is None:
        return "원장에 그 자산이 없어요"
    if r[0] is None or int(r[0]) != stored:
        return "원장 저장값이 요청과 달라요 — 새로 고친 뒤 다시"
    m9 = _meta_dec_cache(r[1], r[2])
    if m9 is not None and m9 != seen:
        return f"수집기 관측값이 바뀌었어요({m9}) — 새로 고친 뒤 다시"
    return ""


def decimals_request(aid, stored, seen, by: str = "") -> tuple:
    why = decimals_check(aid, stored, seen)
    if why:
        return False, why
    cur = _safe_read(_p(DEC_REQ_NAME), None)
    items = cur.get("items") if isinstance(cur, dict) and isinstance(cur.get("items"), dict) else {}
    items[str(aid)] = {"stored": stored, "seen": seen, "at": int(time.time()), "by": str(by)[:40]}
    common.atomic_write_json(_p(DEC_REQ_NAME), {"items": items, "ts": int(time.time())})
    return True, "요청함 — tj-core 가 확인 뒤 다음 자동 재계산에서 관측값으로 다시 기장합니다(손익이 바뀌면 승인 필요)"


def status() -> dict:
    g = gate_record() or {}
    ap = _safe_read(_p(APPROVE_NAME), None)
    ap = ap if isinstance(ap, dict) else None
    pend = pending_gate()
    rs = (pend or {}).get("report_sha")
    pnl = None
    if g:
        pnl = {"ts": g.get("ts"), "ok": bool(g.get("ok")), "approved": bool(g.get("approved")), "reason": str(g.get("reason") or "")[:400],
               "why": str(g.get("why") or "")[:200], "months": (g.get("months") or [])[:5], "n_months": g.get("n_months"),
               "open_cost": (g.get("open_cost") or [])[:5], "n_open_cost": g.get("n_open_cost"), "unv": g.get("unv"),
               "approve_note": g.get("approve_note") or "", "report_sha": rs if isinstance(rs, str) else None,
               "report_ok": bool(isinstance(rs, str) and find_rejected(rs)), "pending": bool(pend)}
        rp9 = find_rejected(rs) if isinstance(rs, str) else None
        miss9 = report_missing(rp9) if rp9 else None
        pnl["missing"] = miss9 if miss9 is not None else (g.get("missing") if isinstance(g.get("missing"), list) else None)
        pnl["approvable"] = bool(pnl["report_ok"] and miss9 is not None and not miss9)
    apv = None
    if ap:
        u9 = _fin(ap.get("until"))
        until = int(u9) if u9 is not None and abs(u9) < 1e12 else 0
        apv = {"until": until, "at": ap.get("at"), "by": str(ap.get("by") or "")[:40], "report_sha": ap.get("report_sha") if isinstance(ap.get("report_sha"), str) else None,
               "live": time.time() < until <= time.time() + APPROVE_TTL + 600}
    pe = poison_entries()
    dec = decimals_items()
    req_p = _safe_read(_p(POISON_REQ_NAME), None)
    req_d = _safe_read(_p(DEC_REQ_NAME), None)
    res_d = _safe_read(_p(DEC_RES_NAME), {}) or {}
    return {"ok": True, "pnl": pnl, "approve": apv,
            "poison": {"n": len(pe), "waiting": sum(1 for e in pe if e["state"] == "대기" and not e["corrupt"]),
                       "failed": sum(1 for e in pe if e["state"] == "실패"), "done": sum(1 for e in pe if e["state"] == "성공"),
                       "items": pe[:30], "requested": isinstance(req_p, dict)},
            "decimals": {"items": dec[:30], "conflicts": sum(1 for x in dec if x["kind"] == "conflict"),
                         "requested": sorted(int(k) for k in ((req_d or {}).get("items") or {}) if str(k).isdigit()) if isinstance(req_d, dict) else [],
                         "results": res_d if isinstance(res_d, dict) else {}}}

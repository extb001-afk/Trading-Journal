from __future__ import annotations
import os
import time
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
import histcurve
import paths
from view_common import DC_SMALL_USD
from view_common import _f
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


def _pxfix_backup(ts) -> list:
    import shutil
    out = []
    for src9 in (paths.state("daily_px.json"), paths.state("daily_cache.json")):
        if os.path.exists(src9):
            dst9 = f"{src9}.bak_pxfix_{int(ts)}"
            shutil.copy2(src9, dst9)
            out.append(dst9)
    return out


PXB_KEYS = ("p", "k", "fp", "lp", "dcn", "dcw", "rdo")


def _bind_px_blocks(daily, dpx, lo=None):
    n, legacy = 0, []
    for ck, c in (daily or {}).items():
        if str(ck).startswith("_") or not isinstance(c, dict) or "val" not in c or (lo and str(ck) < lo):
            continue
        b = c.get("px")
        if not isinstance(b, dict):
            legacy.append(ck)
            continue
        e = dpx.get(ck)
        if not isinstance(e, dict):
            e = dpx[ck] = {}
        hit = False
        for key in PXB_KEYS:
            if key in b:
                if e.get(key) is not b[key]:
                    hit = hit or e.get(key) != b[key]
                    e[key] = b[key]
            elif key in e:
                e.pop(key)
                hit = True
        if hit:
            n += 1
            log.info("일별 %s: daily_px 를 동결 항목 가격 블록으로 맞춤(저장 사이 중단·저장 실패 복구)", ck)
    return n, legacy


def _migrate_px_blocks(daily, dpx, days) -> int:
    n = 0
    for ck in days:
        c = daily[ck]
        e = dpx.get(ck)
        if not isinstance(e, dict):
            e = dpx[ck] = {"p": {}, "k": {}}
        for key, kind in (("dcp", "d"), ("native_c", "c")):
            m = c.get(key)
            if not isinstance(m, dict):
                continue
            for sid, v in m.items():
                k = e.setdefault("k", {})
                if k.get(sid) or not v:
                    continue
                p = e.setdefault("p", {})
                if kind == "d" and p.get(sid):
                    e.setdefault("fp", {}).setdefault(sid, float(p[sid]))
                p[sid] = float(v)
                k[sid] = kind
                log.info("일별 %s: 교정 표식(%s) 복구 — g%s 고정가 %s · 종류 %s(옛 저장 사이 중단)", ck, key, sid, v, kind)
        e.setdefault("p", {})
        e.setdefault("k", {})
        dcp0 = c.get("dcp") if isinstance(c.get("dcp"), dict) else {}
        for sid, fpv in list((e.get("fp") or {}).items()):
            if e["k"].get(sid) == "d" and sid not in dcp0 and fpv:
                e["p"][sid] = float(fpv)
                e["k"].pop(sid, None)
                e["fp"].pop(sid, None)
                log.warning("일별 %s: g%s 옛 형식 동결 항목 + daily_px 교정 흔적 — 교정 전 가격으로 되돌려 다시 교정", ck, sid)
        c["px"] = {key: e[key] for key in PXB_KEYS if key in e}
        n += 1
    return n


def _capture_px_blocks(daily, dpx, lo=None) -> int:
    n = 0
    for ck, c in (daily or {}).items():
        if str(ck).startswith("_") or not isinstance(c, dict) or "val" not in c or (lo and str(ck) < lo):
            continue
        e = dpx.get(ck)
        if not isinstance(e, dict):
            continue
        b = {key: e[key] for key in PXB_KEYS if key in e}
        old = c.get("px")
        if not isinstance(old, dict) or set(old) != set(b) or any(old[k] is not b[k] for k in b):
            c["px"] = b
            n += 1
    return n


def _reprice_now_days(daily, dpx, G, today_iso, now_ts, day_close, skip_gids=None, backup=_pxfix_backup) -> dict:
    out = {"rep": 0, "fin": 0, "pend": 0, "dv": 0.0, "days": {}, "changed": False, "px_changed": False, "bak": None}
    if day_close is None or not isinstance(dpx, dict):
        return out
    skip9 = set(skip_gids or ())
    lo9 = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
    plan9, fin9, pend9, unfin = [], {}, {}, []
    for ck9 in sorted(k9 for k9 in dpx if not str(k9).startswith("_")):
        if not (lo9 <= ck9 < today_iso):
            continue
        e9, c9 = dpx.get(ck9), (daily or {}).get(ck9)
        if not isinstance(e9, dict) or not isinstance(c9, dict) or not isinstance(c9.get("g"), dict):
            continue
        p9, k9, dn9 = e9.get("p") or {}, e9.get("k") or {}, set(e9.get("dcn") or ())
        done9 = c9.get("dcp") if isinstance(c9.get("dcp"), dict) else {}
        for sid9, op9 in p9.items():
            if sid9 in k9 or not op9:
                continue
            if done9.get(sid9) is not None:
                plan9.append((ck9, sid9, float(op9), float(done9[sid9]), True))
                continue
            try:
                gv9 = float(c9["g"].get(sid9) or 0)
                gid9 = int(sid9)
            except (TypeError, ValueError):
                continue
            if abs(gv9) < DC_SMALL_USD or gid9 not in G:
                continue
            np9, st9 = day_close(gid9, ck9, abs(gv9), ref=op9, **({"ask": False} if sid9 in dn9 else {}))
            if np9:
                plan9.append((ck9, sid9, float(op9), float(np9), False))
            elif st9 == "suspect":
                unfin += [(ck9, sid9)] if sid9 in dn9 else []
            elif st9 == "none" and sid9 not in dn9:
                fin9.setdefault(ck9, []).append(sid9)
            elif sid9 not in dn9:
                pend9.setdefault(ck9, []).append(sid9)
    stamp9 = {}
    for ck9 in pend9:
        if not dpx[ck9].get("dcw"):
            stamp9[ck9] = int(now_ts)
    for ck9, e9 in dpx.items():
        if isinstance(e9, dict) and e9.get("dcw") and ck9 not in pend9:
            stamp9.setdefault(ck9, None)
    out["pend"] = sum(len(v9) for v9 in pend9.values())
    if not plan9 and not fin9 and not stamp9 and not unfin:
        return out
    if not isinstance(dpx.get("_pxfix"), dict):
        ts9 = int(now_ts)
        try:
            out["bak"] = backup(ts9) if backup else []
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_pxfix:_reprice_now_days", e9)
            log.warning("pxfix: 이관 전 백업 실패 — 이번 빌드는 재평가 안 함: %s", e9)
            return out
        dpx["_pxfix"] = {"v": 1, "bak": ts9, "at": ts9}
        log.info("pxfix: 근사(now) 고정가 → 그날 마감가 1회 이관 시작 — 백업 %s", out["bak"])
    out["px_changed"] = True
    for ck9, w9 in stamp9.items():
        if w9:
            dpx[ck9]["dcw"] = w9
        else:
            dpx[ck9].pop("dcw", None)
    for ck9, sids9 in fin9.items():
        e9 = dpx[ck9]
        e9["dcn"] = sorted(set(e9.get("dcn") or ()) | set(sids9), key=lambda x9: (len(x9), x9))
        out["fin"] += len(sids9)
    for ck9, sid9 in unfin + [tuple(row[:2]) for row in plan9 if row[1] in (dpx[row[0]].get("dcn") or ())]:
        left = [x for x in dpx[ck9]["dcn"] if x != sid9]
        dpx[ck9].update(dcn=left) if left else dpx[ck9].pop("dcn")
    for ck9, sid9, op9, np9, rec9 in plan9:
        e9, c9 = dpx[ck9], daily[ck9]
        d9 = out["days"].setdefault(ck9, [0, 0.0, float(c9.get("est") or 0), None])
        if not rec9:
            ov9 = Decimal(str(c9["g"][sid9]))
            nv9 = ov9 * Decimal(str(np9)) / Decimal(str(op9))
            c9["g"][sid9] = round(float(nv9), 4)
            if int(sid9) not in skip9:
                c9["val"] = _f(Decimal(str(c9["val"])) + nv9 - ov9, 2) or 0
                if c9.get("est"):
                    e9s = float(c9["est"]) - abs(float(ov9))
                    if e9s >= 1:
                        c9["est"] = round(e9s, 2)
                    else:
                        c9.pop("est", None)
                d9[1] += float(nv9 - ov9)
                out["dv"] += float(nv9 - ov9)
            c9.setdefault("dcp", {})[sid9] = float(np9)
            c9["src9"] = "dayclose"
            out["changed"] = True
        e9.setdefault("fp", {}).setdefault(sid9, float(op9))
        e9.setdefault("p", {})[sid9] = float(np9)
        e9.setdefault("k", {})[sid9] = "d"
        rd9 = e9.get("rdo") if isinstance(e9.get("rdo"), dict) else {}
        rd9[sid9] = max(int(rd9.get(sid9) or 0), int(now_ts))
        e9["rdo"] = rd9
        d9[0] += 1
        d9[3] = float(c9.get("est") or 0)
        out["rep"] += 1
    for ck9, (n9, dv9, est0, est1) in sorted(out["days"].items()):
        log.info("일별 %s: 근사(now) %d그룹 → 그날 마감가 재평가 %+.2f (근사분 %.2f → %.2f)", ck9, n9, dv9, est0, est1 or 0)
    return out


def _px1004_backup(ts) -> list:
    import shutil
    out = []
    for src9 in (paths.state("daily_px.json"), paths.state("daily_cache.json")):
        if os.path.exists(src9):
            dst9 = f"{src9}.bak_px1004_{int(ts)}"
            shutil.copy2(src9, dst9)
            out.append(dst9)
    return out


def _px1004_reset(daily, dpx, G, today_iso, day_close, live_px=None, skip_gids=None, now_ts=None, backup=_px1004_backup) -> dict:
    out = {"n": 0, "days": {}, "dv": 0.0, "changed": False, "px_changed": False, "bak": None}
    chg_of, spec9 = getattr(day_close, "chg", None), getattr(day_close, "spec", None)
    if chg_of is None or spec9 is None or not isinstance(dpx, dict):
        return out
    skip9 = set(skip_gids or ())
    lo9 = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
    plan9 = []
    for ck9 in sorted(k9 for k9 in dpx if not str(k9).startswith("_")):
        if not (lo9 <= ck9 < today_iso):
            continue
        e9, c9 = dpx.get(ck9), (daily or {}).get(ck9)
        if not isinstance(e9, dict):
            continue
        frozen9 = isinstance(c9, dict) and isinstance(c9.get("g"), dict)
        k9, p9 = e9.get("k") or {}, e9.get("p") or {}
        rdo9 = e9.get("rdo") if isinstance(e9.get("rdo"), dict) else {}
        hit9 = []
        for sid9, kd9 in k9.items():
            if kd9 != "d" or not p9.get(sid9):
                continue
            try:
                gid9 = int(sid9)
            except (TypeError, ValueError):
                continue
            if gid9 not in G:
                continue
            c9g = chg_of(spec9(gid9))
            if not c9g:
                continue
            t9 = int(c9g.get(ck9) or 0)
            st9 = int(c9g.get("*") or 0)
            if st9 and histcurve.settle_ts(ck9) <= st9:
                t9 = max(t9, st9)
            if t9 and t9 > int(rdo9.get(sid9) or 0):
                hit9.append((sid9, gid9, t9))
        if hit9:
            plan9.append((ck9, e9, c9, frozen9, k9, p9, hit9))
    if not plan9:
        return out
    if not isinstance(dpx.get("_px1004"), dict):
        ts9 = int(time.time() if now_ts is None else now_ts)
        try:
            out["bak"] = backup(ts9) if backup else []
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_pxfix:_px1004_reset", e9)
            log.warning("px1004: 되돌리기 전 백업 실패 — 이번 빌드는 안 바꿈: %s", e9)
            return out
        dpx["_px1004"] = {"v": 1, "bak": ts9, "at": ts9}
        log.info("px1004: 업비트·빗썸 USDT·BTC 마켓 그날 마감가 되돌리기 시작 — 백업 %s", out["bak"])
    for ck9, e9, c9, frozen9, k9, p9, hit9 in plan9:
        d9 = out["days"].setdefault(ck9, [0, 0.0])
        for sid9, gid9, t9 in hit9:
            pb9 = float(p9[sid9])
            fp9 = (e9.get("fp") or {}).get(sid9)
            prov9 = float(fp9) if fp9 else (float((live_px or {}).get(gid9) or 0) or pb9)
            if frozen9 and sid9 in c9["g"]:
                ov9 = Decimal(str(c9["g"][sid9]))
                nv9 = ov9 * Decimal(str(prov9)) / Decimal(str(pb9))
                c9["g"][sid9] = round(float(nv9), 4)
                if gid9 not in skip9:
                    c9["val"] = _f(Decimal(str(c9["val"])) + nv9 - ov9, 2) or 0
                    c9["est"] = round(float(c9.get("est") or 0) + abs(float(nv9)), 2)
                    d9[1] += float(nv9 - ov9)
                    out["dv"] += float(nv9 - ov9)
                if isinstance(c9.get("dcp"), dict):
                    c9["dcp"].pop(sid9, None)
            p9[sid9] = prov9
            k9.pop(sid9, None)
            if isinstance(e9.get("dcn"), list) and sid9 in e9["dcn"]:
                e9["dcn"].remove(sid9)
            d9[0] += 1
            out["n"] += 1
        e9.pop("dcw", None)
        rd9 = e9.get("rdo") if isinstance(e9.get("rdo"), dict) else {}
        rd9.update({sid9: t9 for sid9, _g9, t9 in hit9})
        e9["rdo"] = rd9
        out["changed"] = out["changed"] or frozen9
        out["px_changed"] = True
        log.warning("일별 %s: px1004 업비트·빗썸 USDT·BTC 마켓 그날 마감가 %d그룹 근사로 되돌림(다시 받기) %+.2f", ck9, d9[0], d9[1])
    return out


def _pin_frozen_x(daily, dpx, lo=None) -> int:
    n = 0
    for ck, c in list((daily or {}).items()):
        if str(ck).startswith("_") or not isinstance(c, dict) or c.get("x") is None or (lo and str(ck) < lo):
            continue
        e = dpx.setdefault(ck, {"p": {}, "k": {}})
        if not isinstance(e, dict) or e.get("x") is not None:
            continue
        try:
            e["x"] = round(float(c["x0"] if c.get("x0") is not None else c["x"]), 2)
        except (TypeError, ValueError):
            continue
        e["xk"] = "live" if c.get("src") in ("live", "partial") else "calc"
        if c.get("xc"):
            e["xc"] = c["xc"]
        xu9 = c.get("xu0") if c.get("x0") is not None else c.get("xu")
        if isinstance(xu9, dict) and xu9:
            e["xu"] = xu9
        n += 1
    return n

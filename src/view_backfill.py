from __future__ import annotations
import bf_engine
import common
import os
import time
from datetime import datetime
from view_common import CHAIN_NAME
from view_common import KST
import calcguard


class BackfillMixin:

    EX_NAME_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트", "hyperliquid": "Hyperliquid"}

    BF_DONE_FRAC = 0.999

    BF_STALL_SEC = 1800

    BF_UNIT_KO = {"tx": "건", "blocks": "블록", "sigs": "개", "tasks": "개"}

    @staticmethod
    def _bf_jobs():
        out = []
        st = bf_engine.read_status()
        now = time.time()
        for unit, items in st.items():
            if not isinstance(items, dict) or unit.startswith("_"):
                continue
            for key, it in items.items():
                if not isinstance(it, dict) or it.get("phase") in ("done", "live", None):
                    continue
                if now - float(it.get("updated") or 0) > 3 * 3600:
                    continue
                tot, done = it.get("total"), it.get("done")
                frac = None
                try:
                    if tot:
                        frac = max(0.0, min(1.0, float(done or 0) / float(tot)))
                except (TypeError, ValueError):
                    frac = None
                if frac is not None and frac >= BackfillMixin.BF_DONE_FRAC:
                    continue
                info = {k9: it.get(k9) for k9 in ("done", "total", "unit", "moved_at", "updated", "note", "via")}
                out.append((key if ":" in key else unit, frac, it.get("eta_sec"),
                            sum(int(v) for v in (it.get("errors") or {}).values()), it.get("phase"), info))
        return out

    @staticmethod
    def _bf_job_text(name, frac, eta, ne, ph, info=None, now=None) -> dict:
        info = info or {}
        now = time.time() if now is None else now
        parts = str(name).split(":")
        ck, kind = parts[0], (parts[1] if len(parts) > 1 else "")
        chain = CHAIN_NAME.get(ck) or BackfillMixin.EX_NAME_KO.get(ck) or ck
        sub = ""
        if ck == "sol" and kind and kind not in ("extend",):
            sub = f" 지갑 {kind[:4]}…"
            kind = parts[2] if len(parts) > 2 else "sigs"
        if ck == "bsc" and kind == "newwallet":
            sub, kind = " 새 지갑", "extend"
        note = str(info.get("note") or "")
        mv0 = info.get("moved_at") or info.get("updated")
        try:
            idle9 = now - float(mv0) if mv0 else 0.0
        except (TypeError, ValueError):
            idle9 = 0.0
        if ("circuit" in note or "서킷" in note) and idle9 >= 300:
            what = "외부 탐색기 장애로 대기"
        elif kind == "rpc" or ph == "scan":
            what = "과거 창 넓히는 중" if ph == "extend" else "과거 블록 훑는 중"
        elif kind == "job":
            what = {"collect": "과거 거래 조회 중", "extend": "과거 창 넓히는 중", "emit": "찾은 거래 기록에 반영 중"}.get(ph, "과거 거래 불러오는 중")
        elif kind == "extend" or ph == "extend":
            what = "과거 창 넓히는 중"
        elif ph == "wait":
            what = "옛 기록 차례 대기(오늘 몫을 다 써서 UTC 0시 · 한국 오전 9시에 이어 받음)"
        elif ph == "sigs" or kind == "sigs":
            what = "거래 서명 모으는 중"
        elif ph == "parse":
            what = "거래 내용 읽는 중"
        else:
            what = "과거 거래 불러오는 중"
        prog = None
        u9 = BackfillMixin.BF_UNIT_KO.get(str(info.get("unit") or ""))
        try:
            if info.get("total") and u9 and float(info["total"]) < 1e6:
                prog = f"{int(float(info.get('done') or 0)):,}/{int(float(info['total'])):,}{u9}"
            elif frac is not None:
                prog = f"{int(frac * 100)}%"
            elif info.get("done") is not None and u9:
                prog = f"{int(float(info['done'])):,}{u9} 처리"
        except (TypeError, ValueError):
            prog = None
        mv = info.get("moved_at") or info.get("updated")
        try:
            mv = float(mv) if mv else None
        except (TypeError, ValueError):
            mv = None
        last = datetime.fromtimestamp(mv, KST).strftime("%H:%M") if mv else None
        if last and mv and now - mv >= 86400:
            last = datetime.fromtimestamp(mv, KST).strftime("%m-%d %H:%M")
        stalled = bool(mv) and now - mv >= BackfillMixin.BF_STALL_SEC and ph != "wait"
        eta_s = None
        if not stalled and eta is not None and float(eta) > 0:
            eta_s = "약 " + BackfillMixin._eta_ko(float(eta)) + " 남음"
        tail = []
        if prog:
            tail.append(prog)
        if stalled:
            tail.append(f"멈춤(마지막 진행 {last})")
        elif eta_s:
            tail.append(eta_s)
        if ne and not stalled:
            tail.append(f"재시도 {ne}회")
        via9 = str(info.get("via") or "").strip()[:40]
        via_s = f"{via9}로 받는 중" if via9 and not stalled else None
        if via_s:
            tail.insert(len(tail) - (1 if (ne and not stalled) else 0), via_s)
        text = f"{chain}{sub} · {what}" + (" — " + " · ".join(tail) if tail else "")
        return {"chain": chain + sub, "what": what, "prog": prog, "eta": eta_s, "stalled": stalled, "last": last,
                "pct": int(frac * 100) if frac is not None else None, "errors": int(ne or 0), "text": text, "via": via_s}

    @staticmethod
    def _eta_ko(sec: float) -> str:
        sec = int(sec)
        if sec < 90:
            return "1분"
        if sec < 3600:
            return f"{sec // 60}분"
        h9, m9 = divmod(sec // 60, 60)
        if h9 >= 24:
            return f"{h9 // 24}일 {h9 % 24}시간" if h9 % 24 else f"{h9 // 24}일"
        return f"{h9}시간" + (f" {m9}분" if m9 and h9 < 10 else "")

    def _backfill_progress(self, conn):
        sd = common.STATE_DIR
        jobs = []
        try:
            jobs = self._bf_jobs()
        except Exception as _cg9:
            calcguard.swallowed("view_backfill:BackfillMixin._backfill_progress", _cg9)
            jobs = []
        eta_txt = None
        now9 = time.time()
        jtx = [type(self)._bf_job_text(*j, now=now9) for j in jobs]
        etas = [j[2] for j, t9 in zip(jobs, jtx) if j[2] is not None and not t9["stalled"]]
        if etas:
            eta_txt = bf_engine.fmt_eta(max(etas))
        job_txt = " · ".join(t9["text"] for t9 in jtx[:4]) or None
        jobs_out = [{k9: t9[k9] for k9 in ("chain", "what", "prog", "eta", "stalled", "last", "pct", "errors", "text", "via")} for t9 in jtx[:6]]
        if os.path.exists(os.path.join(sd, "backfill_done")):
            if not jobs:
                return None
            fr = [j[1] for j in jobs if j[1] is not None]
            stl = sum(1 for t9 in jtx if t9["stalled"])
            return {"pct": int(round(100.0 * sum(fr) / len(fr))) if fr else 0,
                    "detail": f"추가로 과거 거래 불러오는 중 {len(jobs)}건" + (f" · 멈춤 {stl}" if stl else ""),
                    "active": job_txt, "remain": None, "eta": eta_txt, "jobs": jobs_out, "stalled": stl}
        try:
            units, total = 0.0, 0
            done_pairs, tot_pairs = 0, 0
            active = []
            curs = {}
            ch_done, ch_tot = {}, {}
            for w in self.cfg.get("wallets", []):
                wtype = w.get("type", "evm")
                if wtype == "evm":
                    total += 1
                    tot_pairs += 1
                    ch = w["chain"]
                    ch_tot[ch] = ch_tot.get(ch, 0) + 1
                    if ch not in curs:
                        curs[ch] = common.read_json(
                            os.path.join(sd, f"cursor_evm_{ch}.json"), {})
                    a = w["address"].lower()
                    bk9 = curs[ch].get("_bk:" + a)
                    if isinstance(bk9, dict) and bk9.get("why") == "new" and type(bk9.get("done")) is int and type(bk9.get("to")) is int \
                            and type(bk9.get("from")) is int and bk9["done"] < bk9["to"]:
                        units += min(1.0, max(0.0, (bk9["done"] - bk9["from"]) / max(1, bk9["to"] - bk9["from"])))
                    elif a in curs[ch]:
                        units += 1.0
                        done_pairs += 1
                        ch_done[ch] = ch_done.get(ch, 0) + 1
                    else:
                        ck = curs[ch].get("_bf:" + a)
                        if isinstance(ck, dict) and ck.get("v2"):
                            jf = next((j[1] for j in jobs if j[0] == f"{ch}:job" and j[1] is not None), 0.0)
                            ph = next((j[4] for j in jobs if j[0] == f"{ch}:job"), "collect")
                            units += min(1.0, 0.5 * jf if ph == "collect" else 0.5 + 0.5 * jf)
                            active.append(f"{ch} {w.get('label') or a[:8]} v2")
                        elif isinstance(ck, dict):
                            units += min(1.0, (int(ck.get("ep") or 0)) / 3.0)
                            active.append(f"{ch} {w.get('label') or a[:8]}"
                                          f" {int(ck.get('pages') or 0)}p")
            sol_cur = common.read_json(os.path.join(sd, "cursor_sol.json"), {})
            for w in self.cfg.get("wallets", []):
                if w.get("type") == "sol":
                    total += 1
                    units += 1.0 if w["address"] in sol_cur else 0.0
            bcur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {})
            head, frm = int(bcur.get("head") or 0), int(bcur.get("from_block") or 0)
            has_bsc9 = any(w.get("type") == "bsc_rpc" for w in self.cfg.get("wallets", []))
            total += 1 if has_bsc9 else 0
            bstat = (bf_engine.read_status().get("bsc") or {}).get("bsc") or {}
            if not has_bsc9:
                pass
            elif bstat.get("total") and isinstance(bcur.get("_bf_start"), int):
                units += min(1.0, max(0.0, float(bstat.get("done") or 0) / float(bstat["total"])))
            elif head and frm:
                days = bf_engine.bsc_backfill_days(self.cfg)
                start = head - days * 28800
                units += min(1.0, max(0.0, (frm - start) / max(1, head - start)))
            rc_have = {r[0].replace("recon_done_", "") for r in conn.execute(
                "SELECT k FROM meta WHERE k LIKE 'recon_done_%'")}
            ws9 = self.cfg.get("wallets") or []
            rc_expect = {w.get("chain") for w in ws9 if w.get("type", "evm") == "evm"} & set(self.cfg.get("chains") or {})
            rc_expect |= {"bsc"} if any(w.get("type") == "bsc_rpc" for w in ws9) else set()
            rc_expect |= {"sol"} if any(w.get("type") == "sol" for w in ws9) else set()
            e9 = common.read_env_file()
            rc_expect |= {"upbit"} if (e9.get("UPBIT_ACCESS") and e9.get("UPBIT_SECRET")) else set()
            rc, rc_total = len(rc_have & rc_expect), len(rc_expect)
            pct = int(round(units * 100.0 / total)) if total else 0
            if pct >= 100 and rc < rc_total:
                pct = 99
            remain_c = [f"{c} {ch_done.get(c, 0)}/{t}" for c, t in sorted(ch_tot.items())
                        if ch_done.get(c, 0) < t]
            remain_r = []
            for c in sorted(rc_expect - rc_have):
                np9 = len(common.read_json(
                    os.path.join(sd, f"pending_detail_{c}.json"), {})) \
                    if c not in ("bsc", "sol", "upbit") else 0
                remain_r.append(f"{c} (잔여상세 {np9}건)" if np9 else c)
            remain = []
            if remain_c:
                remain.append("수집 남음: " + " · ".join(remain_c))
            if remain_r:
                remain.append("대사 대기: " + " · ".join(remain_r))
            act = " · ".join(active[:3]) if active else None
            if job_txt:
                act = job_txt if not act else act + " · " + job_txt
            return {"pct": pct,
                    "detail": f"체인쌍 {done_pairs}/{tot_pairs} · 대사 {rc}/{rc_total}",
                    "active": act,
                    "remain": " / ".join(remain) if remain else None,
                    "eta": eta_txt, "jobs": jobs_out, "stalled": sum(1 for t9 in jtx if t9["stalled"])}
        except Exception as _cg9:
            calcguard.swallowed("view_backfill:BackfillMixin._backfill_progress", _cg9)
            return None

    def _backfill_pct(self, which: str) -> str:
        sd = common.STATE_DIR
        try:
            if which == "evm":
                total = done = 0
                for w in self.cfg.get("wallets", []):
                    if w.get("type", "evm") != "evm":
                        continue
                    total += 1
                    cur = common.read_json(
                        os.path.join(sd, f"cursor_evm_{w['chain']}.json"), {})
                    bk9 = cur.get("_bk:" + w["address"].lower())
                    if w["address"].lower() in cur and not (isinstance(bk9, dict) and bk9.get("why") == "new"):
                        done += 1
                if total and done >= total:
                    return "증분 감시"
                return f"백필 {done}/{total}쌍"
            if which == "sol":
                owners = [w["address"] for w in self.cfg.get("wallets", [])
                          if w.get("type") == "sol"]
                cur = common.read_json(os.path.join(sd, "cursor_sol.json"), {})
                done = sum(1 for o in owners if o in cur)
                if owners and done >= len(owners):
                    return "증분 감시"
                return f"백필 {done}/{len(owners)}지갑"
            if which == "bsc":
                cur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {})
                head = int(cur.get("head") or 0)
                frm = int(cur.get("from_block") or 0)
                if head and frm:
                    days = bf_engine.bsc_backfill_days(self.cfg)
                    start = head - days * 28800
                    span = max(1, head - start)
                    pct = min(100, max(0, int((frm - start) * 100 / span)))
                    return "증분 감시" if head - frm < 3000 else f"백필 {pct}%"
                return "백필 시작 대기"
        except Exception as _cg9:
            calcguard.swallowed("view_backfill:BackfillMixin._backfill_pct", _cg9)
            pass
        return "상태 미상"

    def _last_scan_str(self, which=None) -> str:
        newest = 0
        pats = {"evm": "cursor_evm_", "sol": "cursor_sol", "bsc": "cursor_bsc",
                "tron": "cursor_tron.", "sui": "cursor_sui.", "ton": "cursor_ton.", "btc": "cursor_btc."}
        off9 = {f"cursor_evm_{c}.json" for c in (self.cfg.get("_disabled_chains") or [])}
        try:
            for fn in os.listdir(common.STATE_DIR):
                if which and not fn.startswith(pats[which]):
                    continue
                if not which and not fn.startswith("cursor"):
                    continue
                if fn in off9:
                    continue
                newest = max(newest, os.path.getmtime(os.path.join(common.STATE_DIR, fn)))
        except OSError:
            pass
        if not newest:
            return "수집 대기"
        ago = int(time.time() - newest)
        if ago < 90:
            return f"{ago}초 전 스캔"
        return f"{ago // 60}분 전 스캔"

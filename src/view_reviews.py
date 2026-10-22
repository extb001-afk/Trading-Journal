from __future__ import annotations
import paths, statefile
import os
import re
from datetime import datetime
from datetime import timedelta
from view_review import REVIEW_PV
from view_review import REVIEW_WPV


class ReviewsMixin:

    @staticmethod
    def _review_stale_why(iso, fp, day_ix, rbd, fbd, rbdk=None, fbdk=None):
        why = []
        if REVIEW_PV and fp.get("pv") != REVIEW_PV:
            why.append("리뷰 방식 변경")
        mm = iso[5:]
        for k9, src9 in (("rs", rbd), ("rf", fbd)):
            cur9 = float((src9.get(iso) if iso in src9 else src9.get(mm)) or 0)
            old9 = float(fp.get(k9) or 0)
            if abs(cur9 - old9) > max(1.0, 0.01 * max(abs(cur9), abs(old9))):
                why.append("실현손익 변경")
                break
        else:
            fu9 = float((fbd.get(iso) if iso in fbd else fbd.get(mm)) or 0)
            if fp.get("rk") is not None and rbdk is not None and (iso in rbdk or mm in rbdk) \
                    and (abs(fu9) < 0.005 or iso in (fbdk or {})):
                cur9 = float((rbdk.get(iso) if iso in rbdk else rbdk.get(mm)) or 0) + float((fbdk or {}).get(iso) or 0)
                old9 = float(fp.get("rk") or 0)
                if abs(cur9 - old9) > max(1500.0, 0.005 * max(abs(cur9), abs(old9))):
                    why.append("원화 실현 변경")
        ent9 = day_ix.get(iso) or []
        n9 = sum(1 for x9 in ent9 if x9[1] != "hidden")
        if fp.get("n") is not None and int(fp.get("n") or 0) != n9:
            why.append(f"기록 {int(fp.get('n') or 0)}→{n9}건")
        return " · ".join(why) or None

    def _merge_llm_reviews(self, reviews, day_ix, rbd, fbd, today_iso, rbdk=None, fbdk=None):
        llm_path = paths.state("reviews_llm.json")
        llm = (statefile.read_json(llm_path, {}) or {}) if os.path.exists(llm_path) else {}
        items = []
        for key, rv in llm.items():
            if not isinstance(rv, dict) or not rv.get("s") or not isinstance(rv.get("fp"), dict):
                continue
            k9 = str(key)
            if len(k9) == 10 and k9[4] == "-":
                items.append((1, k9, k9[5:], rv))
            elif len(k9) == 5 and k9[2] == "-":
                items.append((0, today_iso[:4] + "-" + k9, k9, rv))
        items.sort(key=lambda x9: (x9[0], x9[1]))
        for pri9, iso9, mm9, rv in items:
            why9 = self._review_stale_why(iso9, rv["fp"], day_ix, rbd, fbd, rbdk, fbdk)
            out9 = dict(rv)
            out9.update(iso=iso9, stale=bool(why9))
            if why9:
                out9["staleWhy"] = why9
            reviews[mm9] = out9
        return self._merge_weekly_reviews(rbd, fbd)

    @staticmethod
    def _wk_seg_sum(frm, to, rbd, fbd):
        tot, d9 = 0.0, frm
        try:
            dt9, end9 = datetime.strptime(frm, "%Y-%m-%d"), datetime.strptime(to, "%Y-%m-%d")
        except (TypeError, ValueError):
            return None
        while dt9 <= end9:
            d9 = dt9.strftime("%Y-%m-%d")
            for src9 in (rbd, fbd):
                tot += float((src9.get(d9) if d9 in src9 else src9.get(d9[5:])) or 0)
            dt9 += timedelta(days=1)
        return round(tot, 2)

    def _merge_weekly_reviews(self, rbd, fbd):
        wk_path = paths.state("reviews_llm_weekly.json")
        wk = (statefile.read_json(wk_path, {}) or {}) if os.path.exists(wk_path) else {}
        weekly = {}
        keys = sorted((k9 for k9, v9 in wk.items() if isinstance(v9, dict) and isinstance(v9.get("fp"), dict)))
        kset = set(keys)
        for key in keys:
            out9 = dict(wk[key])
            fp9 = out9["fp"]
            why = []
            if REVIEW_WPV and fp9.get("pv") != REVIEW_WPV:
                why.append("리뷰 방식 변경")
            frm, to = str(out9.get("from") or ""), str(out9.get("to") or "")
            cur9 = self._wk_seg_sum(frm, to, rbd, fbd) if frm and to else None
            if cur9 is not None and fp9.get("rs") is not None:
                old9 = float(fp9.get("rs") or 0)
                if abs(cur9 - old9) > max(5.0, 0.01 * max(abs(cur9), abs(old9))):
                    why.append("실현손익 변경")
                    out9["rsNow"] = cur9
            m9 = re.match(r"^(\d{4}-W\d{2})([ab]?)$", key)
            if m9 and not m9.group(2) and frm and to and frm[:7] != to[:7]:
                if (key + "a") in kset or (key + "b") in kset:
                    out9["superseded"] = True
                else:
                    out9["legacy"] = True
            out9["stale"] = bool(why)
            if why:
                out9["staleWhy"] = " · ".join(why)
            weekly[key] = out9
        return weekly

    def _auto_reviews(self, daily, realized_by_date, acts=None) -> dict:
        out = {}
        prev = None
        acts = acts or {}
        for d in daily:
            r = realized_by_date.get(d["date"])
            a = acts.get(d["date"]) or {}
            nb, ns = int(a.get("b") or 0), int(a.get("s") or 0)
            act_txt = " · ".join(x for x in ((f"매수 {nb}건" if nb else ""), (f"매도 {ns}건" if ns else "")) if x)
            n_txt = f"실현 {'+' if r > 0 else ''}{r:,.0f}$" if r else (act_txt or "체결 없음")
            delta = (d["val"] - prev) if prev is not None else 0
            s = "관망"
            out[d["date"]] = {
                "s": s, "auto": True, "note": n_txt,
                "sum": f"총자산 ${d['val']:,.0f}" + (f" · 전일대비 {'+' if delta >= 0 else ''}{delta:,.0f}$" if prev is not None else "")
                       + (f" · 당일 실현손익 ${r:,.0f}" if r else (f" · 실현 없음 · {act_txt}" if act_txt else " · 매매 없음"))
                       + ". 이 날은 AI 리뷰가 아직 없어 숫자 요약만 보여요.",
                "obs": [], "next": "—",
            }
            prev = d["val"]
        return out

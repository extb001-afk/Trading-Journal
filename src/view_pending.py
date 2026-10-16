from __future__ import annotations
import re
from view_text import _GP_KO
from view_text import _scam_name
from view_text import _usd_txt

NEG_DIAG_MIN_USD = 0.5


_PEND_GAP = {"TRANSFER_OUT": "미등록 외부 주소로 전송", "PROGRAM_IN": "컨트랙트 경유 수령", "UNKNOWN": "거래 종류 판정 보류"}


_PEND_WHY_UNKNOWN = ("보낸 코인과 받은 코인이 한 거래에 함께 있는데 스왑·예치·브릿지 중 무엇인지 정하지 못했어요. 잔고 변화는 그대로 기록했고,"
                     " 원가는 보낸 코인에서 받은 코인으로 넘겼어요(손익 없음). 거래를 확인해 맞으면 무시해도 돼요.")


def dust_usd_eff(prefs) -> float:
    d9 = (prefs or {}).get("dust_usd")
    try:
        return 50.0 if d9 is None else max(0.0, float(d9 or 0))
    except (TypeError, ValueError):
        return 50.0


def _tx_norm(tx) -> str:
    tx = str(tx or "")
    return tx.lower() if tx.startswith("0x") else tx


def _of_linked_txs(of_dec) -> dict:
    out = {}
    for ent in (of_dec or {}).values():
        if not isinstance(ent, dict):
            continue
        for l in (ent.get("links") or ()):
            if not isinstance(l, dict):
                continue
            kp = str(l.get("key") or "").split("|")
            if len(kp) < 3 or kp[0] != "chain_tx" or not kp[1] or not kp[2]:
                continue
            out[(kp[1], _tx_norm(kp[2]))] = "세일 토큰" if l.get("kind") == "tokens" else "환불"
    return out


def _classify_pendings(pendings, prefs):
    dust = dust_usd_eff(prefs)
    for p in pendings:
        key = str(p.get("key") or "")
        usd = p.get("usd")
        hide = why = None
        if key == "risk:summary":
            hide, why = "dust", f"저평가 격리분 {p.get('n') or ''}종 일괄".replace("  ", " ")
        elif key.startswith("risk:"):
            rr = str(p.get("risk") or "")
            m9 = re.search(r"고플러스 (스캠 확증|주의) ([\w·]+)", rr)
            flags9 = [_GP_KO.get(x, x) for x in (m9.group(2).split("·") if m9 else [])]
            name9 = _scam_name(p.get("sym"))
            if "유저 확정" in rr:
                hide, why = "scam", "직접 스팸으로 지정함"
            elif rr.startswith(("가짜 ", "사칭 ")):
                hide, why = "scam", rr
            elif "재정렬" in rr:
                hide, why = "info", "잔고 대사 잔여분(실측 잔고로 소거됨)"
            elif m9 and m9.group(1) == "스캠 확증":
                hide, why = "scam", "에어드랍 스캠 · " + " · ".join(flags9)
            elif name9:
                hide, why = "scam", "에어드랍 스캠 · " + name9
            elif usd is not None and float(usd) < dust:
                hide, why = "dust", "소액 " + _usd_txt(usd)
        elif p.get("scamWhy"):
            hide, why = "scam", p["scamWhy"]
        elif p.get("autoDone"):
            hide, why = "info", str(p["autoDone"])
        elif p.get("riskOf"):
            hide, why = "info", "코인 검토 행에서 판정 · " + str(p["riskOf"])[:120]
        elif p.get("usdIn") is not None and float(p["usdIn"]) < dust:
            hide, why = "dust", "소액 수령 " + _usd_txt(p["usdIn"])
        elif usd is not None and float(usd) < dust and not key.startswith(("unv:", "unvlost:")):
            hide, why = "dust", "소액 " + _usd_txt(usd)
        elif key.startswith("unvlost:"):
            hide, why = "info", "백필 창 이전 보유분 정리 · 표시용 보정(할 일 없음)"
        p["hide"], p["hideReason"] = hide, why


UNPRICED_FACTS_MAX = 1000


def unpriced_ent(pairs, ex, sym) -> str:
    prs = sorted(((str(c), str(a)) for c, a in (pairs or ()) if c and a), key=lambda p: (p[0], p[1]))
    if prs:
        return f"{prs[0][0]}:{prs[0][1]}"
    return f"ex:{ex}:{sym}" if ex else f"sym:{sym}"


def unpriced_facts(unpriced_w, cap: int = UNPRICED_FACTS_MAX) -> list:
    return [{"sym": w9["sym"], "where": w9["where"], "qty": w9["qty"], "cost": round(w9["cost"], 2), "ref": round(w9["ref"], 2)}
            | ({"ent": w9["ent"]} if w9.get("ent") else {})
            for w9 in sorted(unpriced_w, key=lambda w9: -max(w9["cost"], w9["ref"]))[:max(0, int(cap))]
            if max(w9["cost"], w9["ref"]) >= 1]

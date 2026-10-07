from __future__ import annotations

SALE_CAT = "세일 참가금"

CODE_KO = {"sale": "세일 참가", "sale_auto": "토큰 세일 입찰", "ext": "외부 유출", "own": "내 지갑", "exchange": "거래소 입금주소",
           "ret": "되돌려 받음", "pending": "확인 필요", "system": "시스템 주소", "spam": "사칭·스팸 로그", "bridge": "브릿지 → 내 지갑"}


def short(a: str) -> str:
    a = str(a or "")
    return a[:6] + "…" + a[-4:] if len(a) > 12 else a


def dest_name(a: str, dec: dict | None) -> str:
    d = dec if isinstance(dec, dict) else {}
    al = str(d.get("alias") or "").strip()
    if al and al != short(a):
        return al[:40]
    mo = str(d.get("memo") or "").strip()
    if mo:
        return mo[:40]
    return {"multi": "여러 수령처", "?": "수령처 미상"}.get(a) or short(a)


def name_addr(a: str, dec: dict | None) -> str:
    nm, sa = dest_name(a, dec), short(a)
    return f"{nm}({sa})" if nm != sa and a not in ("multi", "?") else nm


def classify(a: str, dec: dict | None, *, system: bool = False) -> str:
    d = dec if isinstance(dec, dict) else {}
    v = d.get("verdict")
    if v == "external":
        return "sale" if d.get("category") == SALE_CAT else "ext"
    if v == "own":
        return "own"
    if v == "exchange":
        return "exchange"
    if d.get("ret") is True:
        return "ret"
    if system:
        return "system"
    return "pending"


def label(chain_ko: str, a: str, dec: dict | None, cost_txt: str, *, system: bool = False, roundtrip: bool = False) -> dict:
    d = dec if isinstance(dec, dict) else {}
    c = classify(a, d, system=system)
    if c == "pending" and roundtrip:
        c = "ret"
    nm = dest_name(a, d)
    links = [x for x in (d.get("links") or []) if isinstance(x, dict)] if c == "sale" else []
    if c == "sale":
        st = f"받은 것 연결 {len(links)}건" if links else "회수 대기"
        lab = f"{chain_ko} → {nm} (세일 참가금 · {st})"
    elif c == "ext":
        lab = f"{chain_ko} → 외부 {nm} (보낸 내역 · {d.get('category') or '외부'} · {cost_txt} 유출)"
    elif c == "own":
        lab = f"{chain_ko} → 내 지갑 {nm} (보낸 내역에서 내 지갑으로 정함 · 다시 분류되는 중)"
    elif c == "exchange":
        lab = f"{chain_ko} → 거래소 입금주소 {nm} (보낸 내역에서 정함 · 다시 분류되는 중)"
    elif c == "ret":
        lab = f"{chain_ko} → {nm} (되돌려 받음 · 상쇄)"
    elif c == "system":
        lab = f"{chain_ko} → 시스템 주소 {nm} (수수료 성격)"
    else:
        lab = f"{chain_ko} → {nm} (확인 필요 · 눌러서 분류 · {cost_txt})"
    out = {"c": c, "lab": lab, "nm": nm}
    if d.get("category"):
        out["cat"] = str(d["category"])
    if c == "sale":
        out["ln"] = len(links)
    return out


STATUS_CODE = {"spam": "spam", "returned": "ret", "system": "system", "own": "own", "own_restart_needed": "own",
               "exchange": "exchange", "exchange_applying": "exchange", "exchange_matched": "exchange", "bridge_matched": "bridge"}


def relabel(of: dict, status: str, chain_ko: str) -> bool:
    if not isinstance(of, dict) or of.get("c") != "pending":
        return False
    c = STATUS_CODE.get(str(status or ""))
    if not c:
        return False
    nm = of.get("nm") or short(of.get("a"))
    lab = {"spam": f"{chain_ko} → {nm} (사칭·스팸 로그 · 실제로 나간 돈 아님)",
           "ret": f"{chain_ko} → {nm} (되돌려 받음 · 상쇄)",
           "system": f"{chain_ko} → 시스템 주소 {nm} (수수료 성격)",
           "own": f"{chain_ko} → 내 지갑 {nm} (다시 분류되는 중)",
           "exchange": f"{chain_ko} → 거래소 입금주소 {nm} (다시 분류되는 중)",
           "bridge": f"{chain_ko} → {nm} (브릿지 → 내 지갑 · 자동 매칭)"}[c]
    of.update(c=c, lab=lab)
    return True


def review_notes(events) -> list:
    out, seen = [], set()
    for e in events or ():
        of = e.get("of") if isinstance(e, dict) else None
        if not isinstance(of, dict) or of.get("c") not in ("sale", "sale_auto"):
            continue
        k = (str(e.get("sym") or "?"), str(of.get("a") or ""))
        if k in seen:
            continue
        seen.add(k)
        out.append({"sym": k[0], "to": short(k[1]), "kind": "세일 참가금 — 유출·손실 아님(나중에 받은 코인·환불로 회수, 받은 코인 원가 = 넣은 돈 − 환불)"})
        if len(out) >= 20:
            break
    return out

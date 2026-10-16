from __future__ import annotations
import re
import spamguard

_GP_KO = {"is_airdrop_scam": "에어드랍 스캠 확증", "is_honeypot": "팔 수 없는 토큰(허니팟)", "cannot_sell_all": "전량 매도 불가",
          "is_fake_token": "가짜 토큰", "is_mintable": "민트 가능 토큰", "is_proxy": "변경 가능 컨트랙트",
          "is_blacklisted": "블랙리스트 기능", "transfer_pausable": "전송 정지 기능"}

_SCAM_NAME = re.compile(r"(https?:|www\.|\.(com|io|org|net|xyz|top|mom|site|app|live|pro|claim|gift|click|vip)\b|t\.me|"
                        r"visit|claim|reward|airdrop|voucher|✅|🎁|\$\s?\d|"
                        r"@\w{3,}bot\b|telegram)", re.I)

_SCAM_DOMAIN = re.compile(r"(?<![\w.])[a-z0-9][a-z0-9-]{1,62}\.(?:" + spamguard.LURE_TLD + r")(?![\w-])", re.I)

_SCAM_SOFT = re.compile(r"zero[\s_-]?fees?|返佣|空投|免费", re.I)

_SCAM_FREE = re.compile(r"(?<![a-z])free(?![a-z])", re.I)

_INVISIBLE = re.compile("[\u200b-\u200f\u2060-\u206f\ufeff\u00ad]")


def _short_addr(a):
    a = str(a or "")
    return (a[:6] + "…" + a[-4:]) if len(a) > 14 else (a or "—")


def _human_dm(t):
    t = re.sub(r"^\[[\w-]+\]\s*[A-Z_]+\s*[—-]\s*", "", str(t or ""))
    t = re.sub(r"\s*·?\s*검토 후 /confirm 처리 예정", "", t)
    return t.strip()


def _usd_txt(v):
    v = float(v or 0)
    return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"


def _scam_name(sym):
    s = str(sym or "")
    if _INVISIBLE.search(s):
        return "사칭 문자(보이지 않는 글자)"
    if _SCAM_NAME.search(s) or _SCAM_DOMAIN.search(s):
        return "링크·보상 유도 이름"
    if _SCAM_SOFT.search(s) or (re.search(r"\s", s.strip()) and _SCAM_FREE.search(s)):
        return "보상 유도 문구"
    if spamguard.impostor_of(s) or spamguard.odd_symbol(s):
        return "사칭 문자(유사 글자)"
    return None

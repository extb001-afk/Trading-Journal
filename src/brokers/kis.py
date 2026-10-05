"""Korea Investment & Securities holdings adapter (read-only, UNVERIFIED)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import Adapter as _Base, BrokerError, fnum, ERR_BODY

KST = timezone(timedelta(hours=9))


def _exchange_list(v) -> list:
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip().upper() for x in v if str(x).strip()]


class Adapter(_Base):
    KEY = "kis"
    NAME = "한국투자증권"
    DOCS = ("https://apiportal.koreainvestment.com/apiservice", "https://github.com/koreainvestment/open-trading-api")
    REQUIRED = ("app_key", "app_secret", "account")
    OPTIONAL = ("paper", "overseas", "overseas_exchanges")
    MAX_PAGES = 10

    def base(self):
        return "https://openapivts.koreainvestment.com:29443" if self.cfg.get("paper") is True else "https://openapi.koreainvestment.com:9443"

    def acct(self):
        a = "".join(ch for ch in str(self.cfg.get("account") or "") if ch.isdigit())
        if len(a) != 10:
            raise BrokerError("account 는 계좌번호 8자리 + 상품코드 2자리(예: 12345678-01)")
        return a[:8], a[8:]

    def token(self):
        ck = self.token_cache_key(self.base(), self.cfg.get("app_key"))
        t = self.cached_token(ck)
        if t:
            return t
        j, _ = self.req("POST", self.base() + "/oauth2/tokenP", {"content-type": "application/json"},
                        {"grant_type": "client_credentials", "appkey": self.cfg["app_key"], "appsecret": self.cfg["app_secret"]})
        tok = j.get("access_token")
        if not tok:
            raise BrokerError("토큰 응답에 access_token 없음")
        ttl = fnum(j.get("expires_in")) or 0
        exp = j.get("access_token_token_expired")
        if exp:
            try:
                ttl = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST).timestamp() - self.now()
            except ValueError:
                pass
        self.keep_token(ck, tok, ttl or 3600)
        return tok

    def hd(self, tr_id, cont=""):
        paper = self.cfg.get("paper") is True
        if paper and tr_id[:1] in "TJC":
            tr_id = "V" + tr_id[1:]
        return {"content-type": "application/json; charset=utf-8", "authorization": "Bearer " + self.token(),
                "appkey": self.cfg["app_key"], "appsecret": self.cfg["app_secret"], "tr_id": tr_id, "custtype": "P", "tr_cont": cont}

    def _paged(self, path, tr_id, params, fk, nk):
        import urllib.parse
        out1, out2, cont = [], [], ""
        for _ in range(self.MAX_PAGES):
            url = self.base() + path + "?" + urllib.parse.urlencode(params)
            j, rh = self.req("GET", url, self.hd(tr_id, cont))
            if str(j.get("rt_cd", "0")) != "0":
                raise BrokerError("조회 실패(%s)" % ERR_BODY)
            out1 += self.need_list(j, "output1", "보유")
            out2 += self.need_list(j, "output2", "예수금·요약")
            if str(rh.get("tr_cont") or "") not in ("M", "F"):
                break
            params[fk.upper()] = j.get(fk, "")
            params[nk.upper()] = j.get(nk, "")
            cont = "N"
        else:
            self.incomplete()
        return out1, out2

    def fetch(self):
        cano, prdt = self.acct()
        pos, cash = [], []
        o1, o2 = self._paged("/uapi/domestic-stock/v1/trading/inquire-balance", "TTTC8434R",
                             {"CANO": cano, "ACNT_PRDT_CD": prdt, "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
                              "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""},
                             "ctx_area_fk100", "ctx_area_nk100")
        for r in o1:
            q = fnum(r.get("hldg_qty"))
            if q and q > 0:
                pos.append({"sym": str(r.get("pdno") or "").strip(), "name": r.get("prdt_name"), "qty": q,
                            "avg": fnum(r.get("pchs_avg_pric")), "px": fnum(r.get("prpr")), "cur": "KRW"})
        if o2:
            c = fnum(o2[0].get("dnca_tot_amt"))
            if c is not None:
                cash.append({"cur": "KRW", "amount": c})
        if self.cfg.get("overseas", True) is not False:
            exs = _exchange_list(self.cfg.get("overseas_exchanges")) or (["NASD", "NYSE", "AMEX"] if self.cfg.get("paper") is True else ["NASD"])
            seen = set()
            for ex in exs[:6]:
                o1, _ = self._paged("/uapi/overseas-stock/v1/trading/inquire-balance", "TTTS3012R",
                                    {"CANO": cano, "ACNT_PRDT_CD": prdt, "OVRS_EXCG_CD": str(ex), "TR_CRCY_CD": "USD",
                                     "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "ctx_area_fk200", "ctx_area_nk200")
                for r in o1:
                    s = str(r.get("ovrs_pdno") or "").strip()
                    q = fnum(r.get("ovrs_cblc_qty"))
                    if not s or s in seen or not q or q <= 0:
                        continue
                    seen.add(s)
                    pos.append({"sym": s, "name": r.get("ovrs_item_name") or s, "qty": q, "avg": fnum(r.get("pchs_avg_pric")),
                                "px": fnum(r.get("now_pric2")), "cur": str(r.get("tr_crcy_cd") or "USD").upper()})
        return {"positions": pos, "cash": cash, "acct": cano + prdt}

import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import _harness as T  # noqa: F401
from brokers import base as bb

NOW = 1_790_000_000.0
KST = 9 * 3600


def kr(p):
    return "9%05d" % (p + 1)


def us(p):
    return "TKJ" + chr(65 + p % 26)


def _key(p):
    return "K%d" % p


def _idx(k):
    k = str(k or "")
    return int(k[1:]) if k[:1] == "K" and k[1:].isdigit() else 0


class Fake:
    def __init__(self, broker, pages=1, endless=False):
        self.broker, self.pages, self.endless = broker, pages, endless
        self.now = NOW
        self.log, self.hosts, self.issued, self.valid = [], [], [], set()
        self.reject_new = False
        self.n401 = 0
        self.ib_auth = True
        self.served = set()
        self.app = getattr(self, "_" + broker)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def http(self, method, url, headers=None, body=None, timeout=15.0, verify=True):
        u = urllib.parse.urlsplit(url)
        self.hosts.append(u.scheme + "://" + u.netloc)
        loop = urllib.parse.urlunsplit(("http", "127.0.0.1:%d" % self.port, u.path, u.query, ""))
        return bb.default_http(method, loop, headers, body, timeout, True)

    def issue(self):
        t = "SYN-TOK-%s-%d-zq" % (self.broker, len(self.issued) + 1)
        self.issued.append(t)
        if not self.reject_new:
            self.valid.add(t)
        return t

    def revoke(self):
        self.valid.clear()

    def bearer(self, rq):
        a = rq["h"].get("authorization", "")
        return a[7:] if a[:7].lower() == "bearer " else ""

    def deny(self, rq):
        t = self.bearer(rq)
        if t in self.valid:
            return None
        self.n401 += 1
        return 401, {"error": "invalid_token", "error_description": "token rejected: " + t}, {}

    def data(self, sub=""):
        return [x for x in self.log if sub in x["path"] and "oauth" not in x["path"]]

    def more(self, p):
        return self.endless or p + 1 < self.pages

    def kr_row(self, p):
        self.served.add(kr(p))
        return kr(p)

    def us_row(self, p):
        self.served.add(us(p))
        return us(p)

    def _kis(self, rq):
        if rq["path"] == "/oauth2/tokenP":
            b = rq["b"] if isinstance(rq["b"], dict) else {}
            if b.get("grant_type") != "client_credentials" or not b.get("appkey") or not b.get("appsecret"):
                return 403, {"error_code": "EGW00103"}, {}
            exp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(self.now + 86400 + KST))
            return 200, {"access_token": self.issue(), "access_token_token_expired": exp, "token_type": "Bearer", "expires_in": 86400}, {}
        d = self.deny(rq)
        if d:
            return d
        ovs = "overseas" in rq["path"]
        fk = "CTX_AREA_FK200" if ovs else "CTX_AREA_FK100"
        p = _idx(rq["q"].get(fk))
        if p and rq["h"].get("tr_cont") != "N":
            return 400, {"rt_cd": "1"}, {}
        nx = _key(p + 1) if self.more(p) else ""
        if ovs:
            j = {"rt_cd": "0", "msg_cd": "MCA00000", "ctx_area_fk200": nx, "ctx_area_nk200": nx, "output2": {"tot_evlu_pfls_amt": "0"},
                 "output1": [{"ovrs_pdno": self.us_row(p), "ovrs_item_name": "합성", "ovrs_cblc_qty": "10", "pchs_avg_pric": "10.5", "now_pric2": "11.25", "tr_crcy_cd": "USD"}]}
        else:
            j = {"rt_cd": "0", "msg_cd": "MCA00000", "ctx_area_fk100": nx, "ctx_area_nk100": nx, "output2": [{"dnca_tot_amt": "1000000"}],
                 "output1": [{"pdno": self.kr_row(p), "prdt_name": "합성", "hldg_qty": str(100 + p), "pchs_avg_pric": "1000.0000", "prpr": "1100"}]}
        return 200, j, {"tr_cont": "M" if nx else "D"}

    def _kiwoom(self, rq):
        b = rq["b"] if isinstance(rq["b"], dict) else {}
        if rq["path"] == "/oauth2/token":
            if b.get("grant_type") != "client_credentials" or not b.get("appkey") or not b.get("secretkey"):
                return 400, {"return_code": 2}, {}
            exp = time.strftime("%Y%m%d%H%M%S", time.gmtime(self.now + 86400 + KST))
            return 200, {"token": self.issue(), "token_type": "bearer", "expires_dt": exp, "return_code": 0, "return_msg": "정상"}, {}
        d = self.deny(rq)
        if d:
            return d
        api = rq["h"].get("api-id")
        if api == "kt00001":
            return 200, {"return_code": 0, "return_msg": "정상", "entr": "000000001000000"}, {"api-id": api}
        p = _idx(rq["h"].get("next-key"))
        if p and rq["h"].get("cont-yn") != "Y":
            return 400, {"return_code": 1}, {}
        nx = _key(p + 1) if self.more(p) else ""
        hd = {"api-id": api, "cont-yn": "Y" if nx else "N", "next-key": nx}
        if api == "ust21070":
            rows = [{"stk_cd": self.us_row(p), "frgn_stk_nm": "합성", "poss_qty": "10", "frgn_stk_book_uv": "10.5", "now_pric": "11.25", "crnc_code": "USD"}] \
                if b.get("stex_tp") == "ND" else []
            if b.get("stex_tp") != "ND":
                hd = {"api-id": api, "cont-yn": "N", "next-key": ""}
            return 200, {"return_code": 0, "result_list": rows}, hd
        row = {"stk_cd": "A" + self.kr_row(p), "stk_nm": "합성", "rmnd_qty": "%012d" % (100 + p), "pur_pric": "000000001000", "cur_prc": "-000000001100"}
        return 200, {"return_code": 0, "return_msg": "정상", "acnt_evlt_remn_indv_tot": [row]}, hd

    def _ls(self, rq):
        b = rq["b"] if isinstance(rq["b"], dict) else {}
        if rq["path"] == "/oauth2/token":
            if b.get("grant_type") != "client_credentials" or not b.get("appsecretkey") or b.get("scope") != "oob":
                return 401, {"rsp_cd": "IGW00121"}, {}
            return 200, {"access_token": self.issue(), "scope": "oob", "token_type": "Bearer", "expires_in": 86400}, {}
        d = self.deny(rq)
        if d:
            return d
        if rq["path"] == "/overseas-stock/accno":
            return 200, {"rsp_cd": "00000", "COSOQ00201OutBlock3": [{"CrcyCode": "USD", "FcurrDps": "100.5"}],
                         "COSOQ00201OutBlock4": [{"ShtnIsuNo": self.us_row(0), "JpnMktHanglIsuNm": "합성", "AstkBalQty": "10", "FcstckUprc": "10.5",
                                                  "OvrsScrtsCurpri": "11.25", "CrcyCode": "USD"}]}, {}
        p = _idx(((b.get("t0424InBlock") or {}).get("cts_expcode")))
        if p and rq["h"].get("tr_cont") != "Y":
            return 400, {"rsp_cd": "1"}, {}
        nx = _key(p + 1) if self.more(p) else ""
        return 200, {"rsp_cd": "00000", "rsp_msg": "조회완료", "t0424OutBlock": {"sunamt1": "1000000", "cts_expcode": nx},
                     "t0424OutBlock1": [{"expcode": self.kr_row(p), "hname": "합성", "janqty": 100 + p, "pamt": 1000, "price": 1100}]}, {"tr_cont": "Y" if nx else "N"}

    def _dbsec(self, rq):
        b = rq["b"] if isinstance(rq["b"], dict) else {}
        if rq["path"] == "/oauth2/token":
            if b.get("grant_type") != "client_credentials" or not b.get("appsecretkey"):
                return 401, {"rsp_cd": "1"}, {}
            return 200, {"access_token": self.issue(), "token_type": "Bearer", "expires_in": 86400}, {}
        d = self.deny(rq)
        if d:
            return d
        if rq["path"].endswith("/acnt-deposit"):
            return 200, {"rsp_cd": "00000", "Out1": {"DpsBalAmt": "1000000"}}, {}
        p = _idx(rq["h"].get("cont_key"))
        if p and rq["h"].get("cont_yn") != "Y":
            return 400, {"rsp_cd": "1"}, {}
        nx = _key(p + 1) if self.more(p) else ""
        hd = {"cont_yn": "Y" if nx else "N", "cont_key": nx}
        if "overseas" in rq["path"]:
            return 200, {"rsp_cd": "00000", "Out2": [{"SymCode": self.us_row(p), "AstkHanglIsuNm": "합성", "AstkExecBaseQty": "10", "AstkAvrPchsPrc": "10.5",
                                                     "AstkNowPrc": "11.25", "CrcyCode": "USD"}]}, hd
        return 200, {"rsp_cd": "00000", "Out1": [{"IsuNo": "A" + self.kr_row(p), "IsuNm": "합성", "BalQty0": str(100 + p), "NowPrc": "1100", "BookUprc": "1000"}]}, hd

    def _toss(self, rq):
        b = rq["b"] if isinstance(rq["b"], dict) else {}
        if rq["path"] == "/oauth2/token":
            if b.get("grant_type") != "client_credentials" or not b.get("client_secret"):
                return 401, {"error": "invalid_client"}, {}
            return 200, {"access_token": self.issue(), "token_type": "Bearer", "expires_in": 3600}, {}
        d = self.deny(rq)
        if d:
            return d
        if rq["path"] == "/api/v1/accounts":
            return 200, {"result": [{"accountNo": "SYN-0000-01", "accountSeq": 1, "accountType": "BROKERAGE"}]}, {}
        if rq["h"].get("x-tossinvest-account") != "1":
            return 400, {"error": "account"}, {}
        if rq["path"] == "/api/v1/holdings":
            return 200, {"result": {"items": [
                {"symbol": self.kr_row(0), "name": "합성", "marketCountry": "KR", "currency": "KRW", "quantity": "100", "averagePurchasePrice": "1000", "lastPrice": "1100"},
                {"symbol": self.us_row(0), "name": "합성", "marketCountry": "US", "currency": "USD", "quantity": "1.5", "averagePurchasePrice": "10.5", "lastPrice": "11.25"}]}}, {}
        if rq["path"] == "/api/v1/buying-power":
            return 200, {"result": {"cashBuyingPower": "1000000" if rq["q"].get("currency") == "KRW" else "100.5"}}, {}
        return 404, {}, {}

    def _alpaca(self, rq):
        if not rq["h"].get("apca-api-key-id") or not rq["h"].get("apca-api-secret-key") or self.reject_new:
            self.n401 += 1
            return 401, {"code": 40110000, "message": "request is not authorized"}, {}
        if rq["path"] == "/v2/positions":
            return 200, [{"symbol": self.us_row(0), "qty": "10", "avg_entry_price": "10.5", "current_price": "11.25", "side": "long", "asset_class": "us_equity"},
                         {"symbol": "TKJS", "qty": "-1", "avg_entry_price": "1", "current_price": "1", "side": "short", "asset_class": "us_equity"}], {}
        return 200, {"cash": "100.5", "currency": "USD", "account_number": "SYN000001"}, {}

    def _ibkr(self, rq):
        pa = rq["path"]
        if pa.endswith("/iserver/auth/status"):
            return 200, {"authenticated": self.ib_auth, "competing": False, "connected": True}, {}
        if pa.endswith("/portfolio/accounts"):
            return 200, [{"id": "U0000001", "accountId": "U0000001"}], {}
        if pa.endswith("/ledger"):
            return 200, {"USD": {"cashbalance": 100.5, "currency": "USD"}, "BASE": {"cashbalance": 1.0, "currency": "BASE"}}, {}
        p = int(pa.rsplit("/", 1)[1])
        n = 100 if self.more(p) else 1
        rows = [{"ticker": self.us_row(p * 100 + i) if i == 0 else "TKX%d_%d" % (p, i), "name": "합성", "position": 10, "avgPrice": 10.5, "mktPrice": 11.25,
                 "currency": "USD", "assetClass": "STK"} for i in range(n)]
        return 200, rows, {}

    def _schwab(self, rq):
        if rq["path"] == "/v1/oauth/token":
            b = rq["b"] if isinstance(rq["b"], dict) else {}
            if not rq["h"].get("authorization", "").startswith("Basic ") or b.get("grant_type") != "refresh_token" or not b.get("refresh_token"):
                return 401, {"error": "invalid_client"}, {}
            return 200, {"access_token": self.issue(), "token_type": "Bearer", "expires_in": 1800, "scope": "api"}, {}
        d = self.deny(rq)
        if d:
            return d
        return 200, [{"securitiesAccount": {"accountNumber": "SYN000001", "type": "MARGIN", "currentBalances": {"cashBalance": 100.5},
                      "positions": [{"longQuantity": 10.0, "shortQuantity": 0.0, "averagePrice": 10.5, "marketValue": 112.5,
                                     "instrument": {"symbol": self.us_row(0), "assetType": "EQUITY", "description": "합성"}}]}}], {}


def _handler(fk):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _do(self):
            u = urllib.parse.urlsplit(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode("utf-8") if n else ""
            ct = (self.headers.get("Content-Type") or "").lower()
            body = (json.loads(raw) if "json" in ct else dict(urllib.parse.parse_qsl(raw))) if raw else None
            rq = {"m": self.command, "path": u.path, "q": dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True)),
                  "h": {k.lower(): v for k, v in self.headers.items()}, "b": body}
            fk.log.append(rq)
            try:
                st, j, hd = fk.app(rq)
            except Exception as e:   # noqa: BLE001
                st, j, hd = 500, {"fake_error": type(e).__name__}, {}
            out = json.dumps(j).encode()
            self.send_response(st)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            for k, v in hd.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = _do
    return H

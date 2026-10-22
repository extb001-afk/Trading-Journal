#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

import base64  # noqa: E402
import hashlib  # noqa: E402
import http.server  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import urllib.parse  # noqa: E402

PORT = 9989
os.environ["TJ_TEST_BASE_COINBASE"] = f"http://127.0.0.1:{PORT}"
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import ex_sign  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402

chk = T.chk
NAME = "organizations/test-org-0001/apiKeys/test-key-0001"
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
D = int.from_bytes(hashlib.sha256(b"tj onboarding coinbase synthetic key").digest(), "big") % _N
PUB = ex_sign.ec_p256_pub(D)


def _tlv(tag, body):
    n = len(body)
    return bytes([tag]) + (bytes([n]) if n < 128 else bytes([0x81, n])) + body


SEC1 = _tlv(0x30, _tlv(0x02, b"\x01") + _tlv(0x04, D.to_bytes(32, "big")) + _tlv(0xA0, bytes.fromhex("06082a8648ce3d030107"))
            + _tlv(0xA1, _tlv(0x03, b"\x00\x04" + PUB[0].to_bytes(32, "big") + PUB[1].to_bytes(32, "big"))))
BODY = base64.b64encode(SEC1).decode()
PEM = "-----BEGIN EC PRIVATE KEY-----\n" + "\n".join(BODY[i:i + 64] for i in range(0, len(BODY), 64)) + "\n-----END EC PRIVATE KEY-----\n"
ED = "-----BEGIN PRIVATE KEY-----\n" + base64.b64encode(_tlv(0x30, _tlv(0x02, b"\x00") + _tlv(0x30, bytes.fromhex("06032b6570"))
                                                             + _tlv(0x04, _tlv(0x04, b"\x22" * 32)))).decode() + "\n-----END PRIVATE KEY-----\n"
MODE = {"perm": {"can_view": True, "can_trade": False, "can_transfer": False, "portfolio_uuid": "p-0001", "portfolio_type": "DEFAULT"}}
SEEN = []


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        sp = urllib.parse.urlsplit(self.path)
        tok = str(self.headers.get("Authorization") or "")[7:]
        ok = False
        try:
            h64, p64, s64 = tok.split(".")
            pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
            hd, cl = json.loads(base64.urlsafe_b64decode(pad(h64))), json.loads(base64.urlsafe_b64decode(pad(p64)))
            ok = (hd.get("alg") == "ES256" and hd.get("kid") == cl.get("sub") == NAME and cl.get("iss") == "cdp"
                  and cl.get("uri") == "GET api.coinbase.com" + sp.path and cl["exp"] - cl["nbf"] == 120
                  and ex_sign.es256_verify((h64 + "." + p64).encode(), base64.urlsafe_b64decode(pad(s64)), PUB))
        except (ValueError, KeyError, TypeError):
            ok = False
        SEEN.append((sp.path, ok))
        if not ok:
            body, code = {"error": "unauthorized"}, 401
        elif sp.path == "/api/v3/brokerage/accounts":
            body, code = {"accounts": [{"currency": "USDC", "available_balance": {"value": "5", "currency": "USDC"}}], "has_next": False}, 200
        elif sp.path == "/api/v3/brokerage/key_permissions":
            body, code = MODE["perm"], 200
        else:
            body, code = {"error": "not found"}, 404
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
th = threading.Thread(target=srv.serve_forever, daemon=True)
th.start()
try:
    with C.real_loopback():
        r = onboarding._dispatch("keys/save", {"group": "coinbase", "values": {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": PEM}})
        env = ss.read_env()
        chk(r.get("ok") is True and env.get("TJ_COINBASE_SECRET") == BODY and env.get("TJ_COINBASE_KEY_NAME") == NAME,
            "K1 View 만 키 = 저장 · 비밀키 = base64 본문 한 줄 · 키 이름 그대로", (r, sorted(env)))
        chk(SEEN and all(ok for _p, ok in SEEN) and {p for p, _ok in SEEN} == {"/api/v3/brokerage/accounts", "/api/v3/brokerage/key_permissions"},
            "K1 서버가 받은 JWT = ES256 · kid=sub · uri 쿼리 없음 · 공개점으로 검증 참(잔고·권한 2콜)", SEEN)
        chk(PEM not in json.dumps(r, ensure_ascii=False) and BODY not in json.dumps(r, ensure_ascii=False), "K1 응답에 비밀키 없음")
        r2 = onboarding._dispatch("keys/save", {"group": "coinbase", "values": {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": PEM.replace("\n", "\\n")}})
        chk(r2.get("ok") is True and ss.read_env().get("TJ_COINBASE_SECRET") == BODY, "K1 JSON 다운로드의 '\\n' 꼴도 같은 본문으로 저장", r2)
        ss.write_env({"TJ_COINBASE_KEY_NAME": None, "TJ_COINBASE_SECRET": None})
        MODE["perm"] = {"can_view": True, "can_trade": True, "can_transfer": True, "portfolio_uuid": "p-0001", "portfolio_type": "DEFAULT"}
        r = onboarding._dispatch("keys/save", {"group": "coinbase", "values": {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": PEM}})
        kinds = sorted(x.get("kind") for x in ((r.get("permBlock") or {}).get("danger") or []))
        chk(r.get("ok") is False and kinds == ["trade", "withdraw"] and not ss.read_env().get("TJ_COINBASE_SECRET"),
            "K2 Trade·Transfer 켠 키 = 저장 거부(permBlock 위험 2) · .env 안 바뀜", (r.get("error"), kinds))
        n0 = len(SEEN)
        ra = onboarding._dispatch("keys/save", {"group": "coinbase", "values": {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": ED}})
        rb = onboarding._dispatch("keys/save", {"group": "coinbase", "values": {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": PEM[:90]}})
        chk(ra.get("ok") is False and "ECDSA" in str(ra.get("error")) and rb.get("ok") is False and len(SEEN) == n0 and not ss.read_env().get("TJ_COINBASE_SECRET"),
            "K3 Ed25519·잘린 PEM = 형식 거부 · 서버 호출 0", (ra.get("error"), rb.get("error")))
        MODE["perm"] = {"can_view": "true", "can_trade": False}
        r = onboarding._dispatch("keys/save", {"group": "coinbase", "values": {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": PEM}})
        chk(r.get("ok") is False and r.get("permRetry") and not ss.read_env().get("TJ_COINBASE_SECRET"), "K4 권한 응답 모양 이상 = 판정 불가 → 저장 거부(permRetry)", r)
        MODE["perm"] = {"can_view": True, "can_trade": False, "can_transfer": False, "portfolio_uuid": "p-0001", "portfolio_type": "DEFAULT"}
        r = onboarding._dispatch("keys/test", {"group": "coinbase", "values": {"TJ_COINBASE_KEY_NAME": NAME, "TJ_COINBASE_SECRET": PEM}})
        t9 = r.get("test") or {}
        chk(r.get("ok") is True and t9.get("ok") is True and (t9.get("perm") or {}).get("checked") is True and not (t9.get("perm") or {}).get("danger"),
            "K5 연결 테스트 = 잔고 성공 · 권한 확인됨(위험 0)", r)
finally:
    srv.shutdown()
    srv.server_close()
T.finish()

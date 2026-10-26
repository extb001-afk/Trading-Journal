#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import base64  # noqa: E402
import gzip  # noqa: E402
import http.client  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import tarfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

t0 = time.time()
TG_TOK = "7712345678:" + "AAGqkzvwpJdLmNbXcVf" + "RtYhUoPgWsEaZx3"
CONF = {
    "tg_token": ("TJ_TG_TOKEN", TG_TOK.split(":", 1)[1], "발송 실패 https://api.telegram.org/bot%s/sendMessage" % TG_TOK),
    "path_key": ("TJ_ALCHEMY_KEY", "hYt5RmQw8ZxKpLs3NvBc6DjFg", "RPC 실패 https://eth-mainnet.g.alchemy.com/v2/" + "hYt5RmQw8ZxKpLs3NvBc6DjFg"),
    "query_key": ("TJ_ETHERSCAN_KEY", "UQ7VW2XE9RT4YZ6PO1MN3KL8J", "조회 실패 https://api.etherscan.io/v2/api?chainid=1&apikey=" + "UQ7VW2XE9RT4YZ6PO1MN3KL8J"),
    "ex_secret": ("TJ_BINANCE_SECRET", "vB9nM2qW4eR6tY8uI1oP3aS5dF7gH0jK", "서명 문자열 vB9nM2qW4eR6tY8uI1oP3aS5dF7gH0jK 로 계산"),
    "privkey": ("TJ_WALLET_PRIVATE_KEY", "0x" + "9e1d5b3a7c2f4e6d8b0a" * 3 + "7c5e", "개인키 0x" + "9e1d5b3a7c2f4e6d8b0a" * 3 + "7c5e"),
    "broker_secret": (None, "ZpXo3IcU7VyT1BrN5MeQ9WaS2LdK", "증권사 오류 ZpXo3IcU7VyT1BrN5MeQ9WaS2LdK"),
    "rpc_url": (None, "gF4hJ6kL8zX0cV2bN4mQ6wE8rT", "노드 오류 https://bsc-node.example.invalid/rpc/gF4hJ6kL8zX0cV2bN4mQ6wE8rT"),
}
UNCONF = {
    "tg_token_url": ("AAHkTxRvBnWqZpMlYsJdGfHc8Ue2", "발송 실패 https://api.telegram.org/bot8823456789:AAHkTxRvBnWqZpMlYsJdGfHc8Ue2/sendMessage"),
    "bearer": ("tYp8Ws2Df4Gh6Jk8Lz0Xc2Vb4Nm6Qw", "헤더 Authorization: Bearer tYp8Ws2Df4Gh6Jk8Lz0Xc2Vb4Nm6Qw"),
    "path_key": ("Kd3Fh5Jl7Zn9Xb1Cv3Mq5Wr7Ey9Tu", "RPC 실패 https://base-mainnet.g.alchemy.com/v2/" + "Kd3Fh5Jl7Zn9Xb1Cv3Mq5Wr7Ey9Tu"),
    "query_key": ("Rg6Th8Yj0Uk2Il4Om6Pn8Qb0Sa2Dc", "조회 실패 https://api.example.invalid/x?apikey=" + "Rg6Th8Yj0Uk2Il4Om6Pn8Qb0Sa2Dc"),
    "privkey": ("0x" + "4b8f2d6a0e3c5a7b9d1f" * 3 + "2e6a", "키 0x" + "4b8f2d6a0e3c5a7b9d1f" * 3 + "2e6a"),
    "secret_hex": ("0x" + "e2a4c6e8a0c2e4a6c8e0" * 3 + "a2c4", "서명 실패 secret=0x" + "e2a4c6e8a0c2e4a6c8e0" * 3 + "a2c4"),
    "privkey_colon": ("0x" + "d7b9f1d3b5f7d9b1f3d5" * 3 + "b7f9", "설정 private_key: 0x" + "d7b9f1d3b5f7d9b1f3d5" * 3 + "b7f9"),
    "infura_v3": ("9fa3c8e1d64b27f05ac39e8d1b7f42a6", "RPC 실패 https://mainnet.infura.io/v3/" + "9fa3c8e1d64b27f05ac39e8d1b7f42a6"),
}
NEW_CAN = {"unconf:secret_hex", "unconf:privkey_colon", "unconf:infura_v3"}
NEW_EXITS = {"web_error"}
CONTROLS = {
    "tx_hash": "tx 0x" + "5d1f3b7a9c0e2d4f6b8a" * 3 + "1c3e",
    "address": "주소 0x" + "a1b2c3d4e5f6a7b8c9d0" * 2,
    "solscan": "https://solscan.io/tx/4hVqZ7mN2pK9rT5wX8yB3cD6fG1jL4nQ7sU2vW5zA8bE3gH6kM9pR2tY5uX8wC1dF4",
    "etherscan": "https://etherscan.io/tx/0x" + "7e9a1c3e5b7d9f0a2c4e" * 3 + "6b8d",
    "blockscout": "https://base.blockscout.com/address/0x" + "b4d6f8a0c2e4b6d8f0a2" * 2,
    "token_addr": "token 0x" + "13579bdf02468ace1357" * 2,
    "token_sym": "token: USDT",
}
CTRL_MSG = " ‖ ".join(CONTROLS.values())
CTRL_SEEN = {}


def ctrl_check(exit_name, text):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    lost = sorted(k for k, v in CONTROLS.items() if v not in text)
    CTRL_SEEN[exit_name] = lost
    T.chk(not lost, "대조군 %s: 공개 값(tx 해시·주소·탐색기 링크·token 표기) 가리지 않음" % exit_name, lost)
ALLMSG = " ‖ ".join(sorted([v[2] for v in CONF.values()] + [v[1] for v in UNCONF.values()],
                           key=lambda m9: "authorization" in m9.lower()))


def grams(s):
    return {s[i:i + 8] for i in range(len(s) - 7) if not s[i:i + 8].isdigit()}


CAN = {("conf:" + k): grams(v[1]) for k, v in CONF.items()}
CAN.update({("unconf:" + k): grams(v[0]) for k, v in UNCONF.items()})
INTERNAL_TOK = "itokQz8vR3mK7pLw2Xn9cnry"
CAN["file:auth_internal_token"] = grams(INTERNAL_TOK)
SECRET_FILES = (".env", "auth_internal_token", "auth.json", "auth_sessions.json", "auth_devices.json", "setup_token", "auth_setup_code")
for a in CAN:
    for b in CAN:
        if a < b and CAN[a] & CAN[b]:
            raise SystemExit("카나리아 조각 겹침: %s %s" % (a, b))
for c9, g9 in CAN.items():
    if any(x in CTRL_MSG for x in g9):
        raise SystemExit("대조군에 카나리아 조각: %s" % c9)
LEAKS = set()
MATRIX = {}


def scan(exit_name, text):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    got = sorted(c for c, g in CAN.items() if any(x in text for x in g))
    for c in got:
        LEAKS.add("%s:%s" % (exit_name, c))
    MATRIX.setdefault(exit_name, set()).update(got)
    return got


with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback"}
CFG.setdefault("balance_check", {})["enabled"] = False
CFG["brokers"] = {"kis": {"enabled": False, "app_key": "PSkis-canary-appkey", "app_secret": CONF["broker_secret"][1]}}
CFG.setdefault("bsc", {})["logs_rpcs"] = ["https://bsc-node.example.invalid/rpc/" + CONF["rpc_url"][1]]
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
with open(os.path.join(T.TMP, ".env"), "w", encoding="utf-8") as f:
    f.write("".join("%s=%s\n" % (env, (TG_TOK if k == "tg_token" else sec)) for k, (env, sec, _m) in CONF.items() if env))
    f.write("TJ_TG_CHAT=123456789\n")

import logs, paths, statefile  # noqa: E402

assert T.TMP in paths.ENV_PATH and T.TMP in paths.CONFIG_PATH

print("[1] 로그 필터(SecretLogFilter)")
buf = io.StringIO()
hd = logging.StreamHandler(buf)
lg = logging.getLogger("tj-canary")
lg.handlers, lg.propagate = [hd], False
lg.setLevel(logging.INFO)
logs.add_secret_filter([hd])
for k, (_e, _s, m) in CONF.items():
    lg.warning("%s", m)
for k, (_s, m) in UNCONF.items():
    lg.warning(m)
lg.warning("대조군 %s", CTRL_MSG)
try:
    raise RuntimeError("예외 안 " + CONF["path_key"][2] + " · " + UNCONF["bearer"][1])
except RuntimeError:
    lg.warning("처리 실패", exc_info=True)
scan("log", buf.getvalue())
ctrl_check("log", buf.getvalue())
T.chk("conf:path_key" not in MATRIX["log"] and "conf:ex_secret" not in MATRIX["log"], "로그: 설정된 경로형 키·거래소 secret 은 가림(필터 동작 확인)", sorted(MATRIX["log"]))

print("[2] 잡히지 않은 예외(sys.excepthook · threading.excepthook)")
CHILD = r'''
import os, sys, threading
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import logs, paths  # paths = .env·config 출처 등록(옛 import common 이 싣던 것)
logs.setup_logging("tj-canary")
msg = " ".join(sys.argv[3:])
if sys.argv[2] == "thread":
    t = threading.Thread(target=lambda: (_ for _ in ()).throw(RuntimeError("스레드 " + msg)))
    t.start(); t.join()
else:
    raise RuntimeError("잡히지 않은 예외 " + msg)
'''
env9 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
env9.update(TJ_BASE=T.TMP, PYTHONDONTWRITEBYTECODE="1")
for mode9 in ("thread", "main"):
    r9 = subprocess.run([sys.executable, "-c", CHILD, T.SRC, mode9, CONF["path_key"][2], "‖", CTRL_MSG], capture_output=True, text=True,
                        timeout=60, env=env9)
    lab9 = "스레드" if mode9 == "thread" else "잡히지 않은 예외"
    T.chk((r9.returncode == 0 if mode9 == "thread" else r9.returncode != 0) and lab9 in r9.stderr,
          "자식 프로세스 %s 예외 훅이 stderr 로 냄(시험 대역 동작)" % mode9, r9.stderr[-300:])
    scan("excepthook", r9.stderr + r9.stdout)
    ctrl_check("excepthook_" + mode9, r9.stderr)

print("[2b] tj-web 요청 처리 예외(QuietHTTPServer.handle_error → socketserver 기본 = stderr 트레이스백)")
import contextlib  # noqa: E402
import web  # noqa: E402

srv_e = web.QuietHTTPServer(("127.0.0.1", 0), web.Handler)
buf_e = io.StringIO()
try:
    try:
        raise RuntimeError("요청 처리 실패 " + CTRL_MSG + " ‖ " + ALLMSG)
    except RuntimeError:
        with contextlib.redirect_stderr(buf_e):
            srv_e.handle_error(None, ("127.0.0.1", 50000))
finally:
    srv_e.server_close()
T.chk("Traceback" in buf_e.getvalue() and "RuntimeError" in buf_e.getvalue(), "handle_error 가 트레이스백을 stderr 로 냄(시험 대역 동작 · 모양 = 계약)",
      buf_e.getvalue()[-300:])
scan("web_error", buf_e.getvalue())
ctrl_check("web_error", buf_e.getvalue())

print("[3] 상태 파일 쓰기(safe_err · scrub_secrets · scrub_secret_file · health.note_send)")
scan("state_safe_err", logs.safe_err(ALLMSG))
scan("state_scrub", json.dumps(logs.scrub_secrets({"err": ALLMSG, "detail": [ALLMSG], "note": {"x": ALLMSG}})[0], ensure_ascii=False))
sp = os.path.join(paths.STATE_DIR, "canary_state.json")
statefile.atomic_write_json(sp, {"last_error": ALLMSG, "errors": [ALLMSG], "rows": [{"msg": ALLMSG}]})
logs.scrub_secret_file(sp)
scan("state_file", open(sp, encoding="utf-8").read())
import health  # noqa: E402

health.note_send(False, ALLMSG)
scan("state_health", json.dumps(health.TG_STATS, ensure_ascii=False, default=str))

print("[4] /api 응답(로그인 켬 · 세션)")
import login_auth as LA  # noqa: E402
import login_limits as LL  # noqa: E402
import onboarding  # noqa: E402
import web  # noqa: E402
import web_ctx  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

LA.init(CFG)
LL.LIM = LL.Limiter()
rec = LA.set_password("Synthetic-Canary-7731", iters=200_000)
tok = LA.new_session(rec)
web.BUILDER = onboarding.DemoBuilder()
cov = {"api_limits": {}, "collector_error": ALLMSG, "chains": {"eth": {"collector_error": ALLMSG, "partial_sample": ALLMSG}}}
os.makedirs(os.path.dirname(web_ctx.coverage_path()), exist_ok=True)
statefile.atomic_write_json(web_ctx.coverage_path(), cov)
HC_MARK = "hcCanaryMarkQ4"
statefile.atomic_write_json(paths.state("health_status.json"), {
    "v": 1, "updatedAt": time.time(), "interval": 60, "overall": "warn", "note": HC_MARK, "resolved": [], "watching": [], "units": [],
    "open": [{"id": "canary", "check": "canary", "unit": "tj-alert", "title": "카나리아", "level": "warn", "peak": "warn",
              "detail": " ‖ ".join(v[2] for v in CONF.values()), "action": "-", "notified": False, "telegram": False}]})
SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-secret-canary").start()


def get(path):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    c.request("GET", path, headers={"Host": "127.0.0.1:%d" % PORT, "Cookie": "%s=%s" % (LA.COOKIE, tok)})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


for p9 in ("/api/setup/status", "/api/coverage_limits", "/api/health"):
    st9, b9 = get(p9)
    T.chk(st9 == 200, "GET %s = 200(세션)" % p9, (st9, b9[:200]))
    if p9 == "/api/health":
        try:
            note9 = (json.loads(b9).get("health") or {}).get("note")
        except ValueError:
            note9 = None
        T.chk(note9 == HC_MARK, "/api/health 가 카나리아 심은 상태 파일을 읽음(가림 경로를 실제로 지남)", b9[:200])
    scan("api" + p9.replace("/api", "").replace("/", "_"), b9)
SRV.shutdown()
SRV.server_close()

print("[5] 텔레그램 발송(alert_bot.send_message · 가짜 전송기)")
import alert_bot  # noqa: E402

SENT = []


class _Resp:
    length = None

    def __init__(self, raw):
        self._b = io.BytesIO(raw)

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, *a, **k):
    SENT.append((getattr(req, "full_url", str(req)), getattr(req, "data", None)))
    return _Resp(b'{"ok": true, "result": {"message_id": 7}}')


_fake_urlopen._tj_test_mock = True
_guard = alert_bot.urllib.request.urlopen
alert_bot.urllib.request.urlopen = _fake_urlopen
try:
    ok9 = alert_bot.send_message(TG_TOK, "123456789", "알림 " + ALLMSG)
    alert_bot.send_message(TG_TOK, "123456789", "대조군 " + CTRL_MSG)
finally:
    alert_bot.urllib.request.urlopen = _guard
T.chk(SENT and ok9[0], "가짜 전송기로 1통 보냄", (len(SENT), ok9))
if SENT:
    body9 = urllib.parse.parse_qs((SENT[0][1] or b"").decode("utf-8")).get("text", [""])[0]
    scan("tg_body", body9)
T.chk(len(SENT) == 2, "대조군 알림도 보냄(2통)", len(SENT))
if len(SENT) == 2:
    ctrl_check("tg_body", urllib.parse.parse_qs((SENT[1][1] or b"").decode("utf-8")).get("text", [""])[0])

print("[6] AI 리뷰 입력(review_daily.payload · CLI 환경)")
import ai_cli  # noqa: E402
import review_daily  # noqa: E402

data9 = {"day": "2026-10-01", "memos": [{"text": ALLMSG}], "trades": [{"sym": "ETH", "note": ALLMSG}], "health": ALLMSG, "_fp": ALLMSG}
scan("ai_payload", review_daily.payload(data9))
envc = {"PATH": "/usr/bin", "HOME": "/tmp", "ANTHROPIC_API_KEY": "sk-ant-cnry", "LANG": "C.UTF-8"}
envc.update({env: sec for _k, (env, sec, _m) in CONF.items() if env})
scan("ai_cli_env", json.dumps(ai_cli._cli_env(envc), ensure_ascii=False))

print("[7] 백업(ledger_backup.backup_files · tools/offsite_backup.build)")
import ledger_backup  # noqa: E402

st_dir = paths.STATE_DIR
statefile.atomic_write_json(os.path.join(st_dir, "settings.json"), {"telegram": {"bot": "canary_bot", "chat_name": "합성"}, "currency": "KRW"})
statefile.atomic_write_json(os.path.join(st_dir, "day_memos.json"), {"2026-10-01": {"text": "메모"}})
with open(os.path.join(st_dir, "auth_internal_token"), "w") as f9:
    f9.write(INTERNAL_TOK + "\n")
for fn9 in ("auth.json", "auth_sessions.json", "auth_devices.json", "setup_token", "auth_setup_code"):
    if not os.path.exists(os.path.join(st_dir, fn9)):
        with open(os.path.join(st_dir, fn9), "w") as f9:
            f9.write("{}\n" if fn9.endswith(".json") else "x\n")


def scan_name(exit_name, name):
    b9 = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if b9 in SECRET_FILES:
        LEAKS.add("%s:file:%s" % (exit_name, b9))
        MATRIX.setdefault(exit_name, set()).add("file:" + b9)
day9 = time.strftime("%Y%m%d", time.gmtime(time.time() + 9 * 3600))
ledger_backup.backup_files(day9, st_dir, paths.CONFIG_PATH)
for dp, _dn, fns in os.walk(os.path.join(st_dir, "backups")):
    for fn in fns:
        scan("backup_files", open(os.path.join(dp, fn), "rb").read() + fn.encode())
        scan_name("backup_files", fn)
db9 = sqlite3.connect(paths.DB_PATH)
db9.executescript("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT); INSERT INTO meta VALUES('schema_version','1');"
                  "CREATE TABLE raw_txs(ingested_at INTEGER); INSERT INTO raw_txs VALUES(1790000000);"
                  "CREATE TABLE raw_ex(observed_at INTEGER); INSERT INTO raw_ex VALUES(1790000000);")
db9.commit()
db9.close()
off_path = os.path.join(T.ROOT, "tools", "offsite_backup.py")
if os.path.isfile(off_path):
    import importlib.util  # noqa: E402

    spec = importlib.util.spec_from_file_location("offsite_backup_canary", off_path)
    ob = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ob)
    man = ob.build(check=True, log=lambda *a: None)
    T.chk(isinstance(man, dict) and man.get("files"), "offsite 묶음 만듦(원장 압축본 · 원장 밖 사본 · manifest)", man)
    for fn in sorted(os.listdir(ob.OUT_DIR)):
        p9 = os.path.join(ob.OUT_DIR, fn)
        if fn.endswith(".manifest.json"):
            scan("backup_offsite_manifest", open(p9, "rb").read())
        elif fn.endswith(".files.tar.gz"):
            with tarfile.open(p9, "r:gz") as tf:
                for mem in tf.getmembers():
                    scan("backup_offsite_files", mem.name)
                    scan_name("backup_offsite_files", mem.name)
                    if mem.isfile():
                        scan("backup_offsite_files", tf.extractfile(mem).read())
        elif fn.endswith(".db.gz"):
            raw9 = gzip.open(p9).read()
            scan("backup_offsite_db", raw9)
            if raw9.startswith(b"SQLite format 3"):
                LEAKS.add("backup:offsite_plaintext")

    man_disk = json.load(open(os.path.join(ob.OUT_DIR, man["stamp"] + ".manifest.json"), encoding="utf-8"))
    key9 = ob.seal.load_key(ob.AUTH_KEY)

    def _sealed(m):
        try:
            ob.seal.verify(m, key9)
            return True
        except ob.seal.AuthError:
            return False
    if not (key9 and _sealed(man_disk)) or _sealed(dict(man_disk, created=int(man_disk.get("created") or 0) + 1)):
        LEAKS.add("backup:manifest_no_sender_auth")
    blob9 = base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(32))).decode()
    c9 = {"port": 22, "host": "backup.invalid", "host_key_fpr": [ob.seal.key_fpr(blob9)]}
    with open(ob.KNOWN_HOSTS, "w", encoding="utf-8") as f9:
        f9.write("backup.invalid ssh-ed25519 %s\n" % blob9)
    for pin9 in (ob.ssh_cmd(c9), ob.scp_cmd(c9)):
        if any("accept-new" in x for x in pin9) or not {"StrictHostKeyChecking=yes", "UserKnownHostsFile=" + ob.KNOWN_HOSTS,
                                                        "GlobalKnownHostsFile=/dev/null", "VerifyHostKeyDNS=no"} <= set(pin9):
            LEAKS.add("backup:ssh_accept_new_hostkey")
else:
    print("(tools/offsite_backup.py 없음 — offsite 묶음 건너뜀)")

print("\n출구별 누출(카나리아):")
for ex in sorted(MATRIX):
    print("  %-26s %s" % (ex, ", ".join(sorted(MATRIX[ex])) or "없음"))
for must in ("state_safe_err", "api_setup_status", "backup_files", "ai_cli_env"):
    if must in MATRIX:
        T.chk(not any(c.startswith("conf:") for c in MATRIX[must]), "%s: 설정된 비밀값 누출 0" % must, sorted(MATRIX[must]))
print("대조군(가려진 것):", {k: v for k, v in sorted(CTRL_SEEN.items())})


def _p1(k):
    ex9, _, can9 = k.partition(":")
    return ex9 in NEW_EXITS or can9 in NEW_CAN


L.known_list(T, "secret_p1", "leak", sorted(k for k in LEAKS if _p1(k)),
             "3막 A0 비밀값 카나리아 보강 알려진 누출 — '출구:unconf|conf:카나리아' · 출구 web_error(tj-web handle_error stderr) · "
             "변형 secret=0x64·private_key: 0x64·infura /v3/<키>. 3막 P1b(로그 필터·excepthook·handle_error 가림)에서 고치면 --update-lower 로 빠짐",
             "새 비밀값 누출(3막 A0 출구·변형) — 그 출구가 값을 그대로 내보냄: 로그 필터·handle_error·excepthook 가림(3막 P1b)")
L.known_list(T, "secret", "leak", sorted(k for k in LEAKS if not _p1(k)),
             "G1 비밀값 카나리아 알려진 구멍 — '출구:conf|unconf:카나리아'(누출) · 'backup:…'(백업 무결성·기밀: 평문·manifest 송신자 인증 없음·ssh accept-new). "
             "설정에 없는 꼴(봇 토큰 URL·Bearer·경로형 키)·잡히지 않은 예외는 3막 P1, 백업은 10막 P2 에서 고치면 --update-lower 로 빠짐",
             "새 비밀값 누출 — 그 출구가 값을 그대로 내보냄: 로그는 logs.SecretLogFilter, 상태·API 는 logs.safe_err/scrub_secrets 를 거치게")
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()

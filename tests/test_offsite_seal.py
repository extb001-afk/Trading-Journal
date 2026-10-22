#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import base64  # noqa: E402
import gzip  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools")
sys.path.insert(0, TOOLS)
import offsite_seal as S  # noqa: E402

W = os.path.join(T.TMP, "seal")
os.makedirs(W, mode=0o700, exist_ok=True)


def raises(fn, exc=Exception):
    try:
        fn()
    except exc as e:   # noqa: BLE001
        return str(e) or type(e).__name__
    return None


K1, K2 = bytes(range(32)), bytes(range(1, 33))
MAN = {"v": 1, "stamp": "tjoff_20260101_0930", "created": 1767228600, "source": "snapshot",
       "db": {"name": "tjoff_20260101_0930.db.gz", "sha256": "a" * 64, "size": 10, "raw_sha256": "b" * 64, "raw_size": 20,
              "quick_check": "ok", "schema_version": "7", "data_until": None},
       "files": {}, "메모": "합성 값"}
chk(S.canon(MAN) == json.dumps(MAN, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    and "메모".encode() in S.canon(MAN), "[A] 정규 JSON = sort_keys · 빈칸 없음 · 한글 그대로(UTF-8)")
m1 = S.seal(json.loads(json.dumps(MAN)), K1)
chk(set(m1["auth"]) == {"alg", "kid", "mac"} and m1["auth"]["alg"] == "hmac-sha256" and m1["auth"]["kid"] == hashlib.sha256(K1).hexdigest()[:8]
    and len(m1["auth"]["mac"]) == 64, "[A] auth 칸 = alg·kid(열쇠 sha256 앞 8)·mac(64 hex)", m1["auth"])
chk(S.canon(m1) == S.canon(MAN), "[A] HMAC 이 덮는 바이트 = auth 칸 뺀 manifest(봉인 전과 같음)")
re_ordered = json.loads(json.dumps(m1, indent=3, sort_keys=False))
chk(raises(lambda: S.verify(re_ordered, K1)) is None, "[A] 열쇠 차례·들여쓰기 다른 같은 manifest = 통과")
for path, val in ((("created",), 1767228601), (("db", "sha256"), "c" * 64), (("db", "raw_sha256"), "d" * 64), (("files",), {"x": 1}),
                  (("메모",), "합성 값 "), (("db", "data_until"), 0)):
    m = json.loads(json.dumps(m1))
    tgt = m
    for p in path[:-1]:
        tgt = tgt[p]
    tgt[path[-1]] = val
    chk(raises(lambda: S.verify(m, K1), S.AuthError), "[A] 값 바뀜 = 거부: %s" % ".".join(path))
m = json.loads(json.dumps(m1))
m["새칸"] = 1
chk(raises(lambda: S.verify(m, K1), S.AuthError), "[A] 칸 추가 = 거부")
chk("다른 열쇠" in (raises(lambda: S.verify(m1, K2), S.AuthError) or ""), "[A] 다른 열쇠 = 거부(kid 다름)")
m = json.loads(json.dumps(m1))
m["auth"]["kid"] = S.kid(K2)
chk(raises(lambda: S.verify(m, K2), S.AuthError), "[A] kid 만 맞춘 다른 열쇠 = 거부(mac 다름)")
for bad in (None, "x", {"alg": "hmac-sha1", "kid": S.kid(K1), "mac": m1["auth"]["mac"]}, {"alg": "hmac-sha256", "kid": S.kid(K1), "mac": 5}):
    m = dict(m1, auth=bad)
    chk(raises(lambda: S.verify(m, K1), S.AuthError), "[A] auth 꼴 틀림 = 거부: %r" % (bad if not isinstance(bad, dict) else bad["alg"],))
chk(raises(lambda: S.verify(dict(MAN), K1), S.AuthError), "[A] auth 칸 없음 = verify 거부")
for why, auth in (("mac 비ASCII", dict(m1["auth"], mac="가" * 64)), ("mac 대문자", dict(m1["auth"], mac=m1["auth"]["mac"].upper())),
                  ("kid 숫자", dict(m1["auth"], kid=12345678)), ("mac 목록", dict(m1["auth"], mac=[m1["auth"]["mac"]]))):
    chk("꼴" in (raises(lambda: S.verify(dict(m1, auth=auth), K1), S.AuthError) or ""), "[A] auth 꼴 틀림 = AuthError(다른 예외로 새지 않음): " + why)
chk(raises(lambda: S.verify(dict(m1, 메모="\ud800"), K1), S.AuthError), "[A] 정규화 불가(고립 서로게이트) = AuthError")
HM = []
for fn in sorted(os.listdir(TOOLS)):
    if fn.endswith(".py"):
        tree = ast.parse(open(os.path.join(TOOLS, fn), encoding="utf-8").read())
        HM += [fn for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "hmac"
               and n.attr in ("new", "digest", "HMAC")]
chk(sorted(set(HM)) == ["offsite_seal.py"], "[A] tools 의 HMAC 계산 자리 = offsite_seal.py 하나", sorted(set(HM)))

kp = os.path.join(W, "auth.key")
chk(S.load_key(kp) is None and not os.path.exists(kp), "[B] 없음 = None(받는 쪽은 만들지 않음)")
k = S.load_key(kp, create=True)
chk(isinstance(k, bytes) and len(k) == 32 and (os.stat(kp).st_mode & 0o777) == 0o600, "[B] 만들기 = 32바이트 · 0600",
    oct(os.stat(kp).st_mode & 0o777))
chk(S.load_key(kp, create=True) == k and S.load_key(kp) == k, "[B] 이미 있으면 그대로(다시 만들지 않음)")
chk(not [n for n in os.listdir(W) if n.startswith(".tmp_")], "[B] 만들기 임시 파일 안 남음", os.listdir(W))
short = os.path.join(W, "short.key")
with open(short, "wb") as f:
    f.write(b"x" * 31)
chk("길이" in (raises(lambda: S.load_key(short), S.AuthError) or ""), "[B] 31바이트 = 거부(묶음 안 만듦)")
with open(short, "wb") as f:
    f.write(b"x" * 33)
chk(raises(lambda: S.load_key(short, create=True), S.AuthError), "[B] 33바이트 = 거부 · create 여도 덮지 않음")
chk(open(short, "rb").read() == b"x" * 33, "[B] 손상 열쇠는 그대로 둠(덮어쓰기 0)")
ln = os.path.join(W, "link.key")
os.symlink(kp, ln)
chk(raises(lambda: S.load_key(ln), S.AuthError), "[B] 링크 열쇠 = 거부")
cp = os.path.join(W, "copy.key")
chk(S.export_key(k, cp) == S.kid(k) and open(cp, "rb").read() == k and (os.stat(cp).st_mode & 0o777) == 0o600, "[B] 사본 = 같은 바이트 · 0600 · kid")
chk(raises(lambda: S.export_key(K2, cp), FileExistsError) and open(cp, "rb").read() == k, "[B] 사본 자리에 파일 있음 = 덮지 않음")
chk(S.read_key_file(cp) == k and raises(lambda: S.read_key_file(os.path.join(W, "none.key")), S.AuthError), "[B] --auth-key 읽기 · 없음 = 거부")
OUT = []
chk(S.key_cli(os.path.join(W, "cli.key"), None, out=OUT.append) == 0 and OUT and S.kid(S.load_key(os.path.join(W, "cli.key"))) in OUT[-1],
    "[B] auth-key = 열쇠 만들고 kid 출력", OUT)
chk(S.key_cli(os.path.join(W, "cli.key"), cp, out=OUT.append) == 1 and open(cp, "rb").read() == k, "[B] auth-key --export 있는 파일 = rc 1 · 그대로")

ST = MAN["stamp"]
chk(S.manifest_parts(MAN, ST) == [(ST + ".db.gz", "a" * 64)], "[C] 원장 밖 사본 없음(files={}) = db 만")
chk(S.manifest_parts(dict(MAN, files={"name": ST + ".files.tar.gz", "sha256": "e" * 64}), ST)[1] == (ST + ".files.tar.gz", "e" * 64),
    "[C] 원장 밖 사본 있으면 둘 다")
for bad in ({"db": dict(MAN["db"], name="../" + ST + ".db.gz")}, {"db": dict(MAN["db"], name="tjoff_20260101_0931.db.gz")},
            {"db": dict(MAN["db"], name=ST + ".db.gz.gpg")}, {"db": dict(MAN["db"], sha256="A" * 64)}, {"db": {}},
            {"files": {"name": "/etc/" + ST + ".files.tar.gz", "sha256": "e" * 64}}, {"files": "x"}, {"files": {"name": ST + ".files.tar.gz"}}):
    chk(raises(lambda: S.manifest_parts(dict(MAN, **bad), ST), RuntimeError), "[C] 거부: %s" % json.dumps(bad, ensure_ascii=False)[:70])

SRC_D, OUT_D = os.path.join(W, "box"), os.path.join(W, "out")
os.makedirs(SRC_D)
RAW = b"SQLite format 3\x00" + os.urandom(5000)


def bundle(stamp=ST, raw=RAW, key=K1, files=True):
    gz = os.path.join(SRC_D, stamp + ".db.gz")
    with gzip.open(gz, "wb") as g:
        g.write(raw)
    man = {"v": 1, "stamp": stamp, "created": 1, "source": "snapshot",
           "db": {"name": stamp + ".db.gz", "sha256": hashlib.sha256(open(gz, "rb").read()).hexdigest(), "size": os.path.getsize(gz),
                  "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_size": len(raw)}, "files": {}}
    if files:
        fz = os.path.join(SRC_D, stamp + ".files.tar.gz")
        with open(fz, "wb") as f:
            f.write(b"tar-ish")
        man["files"] = {"name": stamp + ".files.tar.gz", "sha256": hashlib.sha256(b"tar-ish").hexdigest(), "size": 7, "includes": []}
    if key:
        S.seal(man, key)
    with open(os.path.join(SRC_D, stamp + ".manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f)
    return man


bundle()
LOG = []
p = S.open_bundle(SRC_D, ST, OUT_D, K1, log=LOG.append)
chk(p == os.path.join(OUT_D, "ledger_20260101_0930.db") and open(p, "rb").read() == RAW and (os.stat(p).st_mode & 0o777) == 0o600 and not LOG,
    "[D] 열기 = 원본 바이트 · 0600 · 경고 없음", LOG)
os.remove(p)
chk("열쇠가 없음" in (raises(lambda: S.open_bundle(SRC_D, ST, OUT_D, None), S.AuthError) or "") and not os.path.exists(p),
    "[D] 봉인 묶음 + 열쇠 없음 = 거부 · 풀지 않음")
chk(raises(lambda: S.open_bundle(SRC_D, ST, OUT_D, K2), S.AuthError) and not os.path.exists(p), "[D] 다른 열쇠 = 거부")
bundle(files=False)
chk(S.open_bundle(SRC_D, ST, OUT_D, K1) == p, "[D] 원장 밖 사본 없는 묶음 = 열림")
os.remove(p)
bundle()
os.remove(os.path.join(SRC_D, ST + ".files.tar.gz"))
chk("묶음 파일 없음" in (raises(lambda: S.open_bundle(SRC_D, ST, OUT_D, K1), RuntimeError) or "") and not os.path.exists(p),
    "[D] manifest 가 적은 원장 밖 사본이 없음 = 실패")
bundle()
with open(os.path.join(SRC_D, ST + ".files.tar.gz"), "ab") as f:
    f.write(b"!")
chk("원장 밖 사본 sha256" in (raises(lambda: S.open_bundle(SRC_D, ST, OUT_D, K1), RuntimeError) or ""), "[D] 원장 밖 사본 sha256 다름 = 실패")
m = bundle(key=None)
m["db"]["raw_sha256"] = "0" * 64
S.seal(m, K1)
with open(os.path.join(SRC_D, ST + ".manifest.json"), "w", encoding="utf-8") as f:
    json.dump(m, f)
chk("풀린 원장 sha256" in (raises(lambda: S.open_bundle(SRC_D, ST, OUT_D, K1), RuntimeError) or "") and not os.path.exists(p)
    and not [n for n in os.listdir(OUT_D) if n.startswith(".tmp_")], "[D] raw_sha256 다름 = 실패 · 제자리 파일·임시 파일 없음", os.listdir(OUT_D))
bundle(key=None)
chk("서명 없는" in (raises(lambda: S.open_bundle(SRC_D, ST, OUT_D, K1), S.AuthError) or ""), "[D] 서명 없는 옛 묶음 = 스위치 없이 거부")
LOG = []
chk(S.open_bundle(SRC_D, ST, OUT_D, None, allow_unsigned=True, log=LOG.append) == p and any("경고" in x for x in LOG),
    "[D] 서명 없는 옛 묶음 + allow_unsigned = 열림 · 경고 한 줄", LOG)
chk(raises(lambda: S.open_bundle(SRC_D, "../" + ST, OUT_D, K1), RuntimeError) and raises(lambda: S.open_bundle(SRC_D, ST + "x", OUT_D, K1)),
    "[D] 묶음 이름 꼴 아님 = 거부")
m = bundle()
m2 = dict(m, stamp="tjoff_20260101_0931")
S.seal(m2, K1)
with open(os.path.join(SRC_D, ST + ".manifest.json"), "w", encoding="utf-8") as f:
    json.dump(m2, f)
chk("묶음 이름이 다름" in (raises(lambda: S.open_bundle(SRC_D, ST, OUT_D, K1), RuntimeError) or ""), "[D] manifest 안 묶음 이름 다름 = 거부")

BIN = os.path.join(T.TMP, "scanbin")
os.makedirs(BIN)
SCAN_OUT, SCAN_LOG = os.path.join(W, "scan_out.txt"), os.path.join(W, "scan_log.txt")
with open(os.path.join(BIN, "ssh-keyscan"), "w", encoding="utf-8") as f:
    f.write("#!%s\nimport sys\nopen(%r, 'a').write(' '.join(sys.argv[1:]) + '\\n')\nsys.stdout.write(open(%r).read())\n"
            % (sys.executable, SCAN_LOG, SCAN_OUT))
os.chmod(os.path.join(BIN, "ssh-keyscan"), 0o755)
os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")


def blob(n):
    return base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([n]) * 32).decode()


B1, B2, B3 = blob(1), blob(2), blob(3)
F1, F2, F3 = S.key_fpr(B1), S.key_fpr(B2), S.key_fpr(B3)
chk(all(S.FPR_RX.fullmatch(x) for x in (F1, F2, F3)) and len({F1, F2, F3}) == 3 and S.key_fpr("!!") == "", "[E] 지문 = 'SHA256:' + 43자 · 꼴 아님 = ''")
chk(S.parse_fprs(" %s , %s=,,%s" % (F1, F2, F1)) == [F1, F2] and S.parse_fprs([F3]) == [F3] and S.parse_fprs(None) == [] and S.parse_fprs("") == [],
    "[E] 설정 지문 읽기 = 쉼표·목록 · 끝 '=' 뗌 · 중복 뺌 · 없음·빈 글자 = 미고정")
for bad in (5, True, {"a": F1}, "=", [5], "MD5:aa"):
    got = S.parse_fprs(bad)
    chk(got and not all(S.FPR_RX.fullmatch(x) for x in got), "[E] 꼴 아닌 지문 설정 = 빈 목록(미고정)으로 내려앉지 않음: %r" % (bad,), got)
kg = shutil.which("ssh-keygen")
if kg:
    kf = os.path.join(W, "hk")
    subprocess.run([kg, "-q", "-t", "ed25519", "-N", "", "-C", "합성", "-f", kf], check=True, capture_output=True, timeout=60)
    want = subprocess.run([kg, "-l", "-E", "sha256", "-f", kf + ".pub"], capture_output=True, text=True, timeout=60).stdout.split()[1]
    chk(S.key_fpr(open(kf + ".pub").read().split()[1]) == want, "[E] 지문 계산 = ssh-keygen -l -E sha256", want)
else:
    chk(True, "[E] ssh-keygen 없음 — 지문 대조 건너뜀")
KH = os.path.join(W, "known_hosts_offsite")
C0 = {"host": "box.invalid", "port": 22, "host_key_fpr": []}
chk(S.host_opts(C0, KH) == ["-o", "StrictHostKeyChecking=accept-new"] and not os.path.exists(KH), "[E] 지문 칸 없음 = accept-new(종전) · 파일 안 만듦")
chk("형식" in (raises(lambda: S.host_opts(dict(C0, host_key_fpr=["MD5:aa"]), KH), RuntimeError) or "") and not os.path.exists(KH),
    "[E] 꼴 아닌 지문이 host_opts 까지 와도 접속 전 실패")
for odd in ("sp ace", 'q"uote', "q'uote", "pct%h", "hash#x", "back\\slash", "env${HOME}", "env$HOME", "한글"):
    chk("밖 글자" in (raises(lambda: S.host_opts(dict(C0, host_key_fpr=["SHA256:" + "A" * 43]), os.path.join(W, odd, "kh")), RuntimeError) or ""),
        "[E] known_hosts 경로에 ssh 가 다시 나누거나 펼치는 글자(%r) = 접속 전 실패" % odd)
chk(raises(lambda: S.host_opts(dict(C0, host_key_fpr=["SHA256:" + "A" * 43]), "~/kh"), RuntimeError), "[E] known_hosts 경로 '~' 시작 = 접속 전 실패")


def scan(*blobs, host="box.invalid"):
    with open(SCAN_OUT, "w") as f:
        f.write("# box.invalid:22 SSH-2.0\n" + "".join("%s ssh-ed25519 %s\n" % (host, b) for b in blobs))


def scans():
    return len(open(SCAN_LOG).read().splitlines()) if os.path.exists(SCAN_LOG) else 0


scan(B2)
C1 = dict(C0, host_key_fpr=[F1])
chk("다름" in (raises(lambda: S.host_opts(C1, KH), RuntimeError) or "") and not os.path.exists(KH), "[E] 원격 키 지문 다름 = 접속 전 실패 · 파일 안 씀")
scan(B2, B1)
o = S.host_opts(C1, KH)
chk(o[:2] == ["-o", "StrictHostKeyChecking=yes"] and "UserKnownHostsFile=" + KH in o and "GlobalKnownHostsFile=/dev/null" in o
    and "KnownHostsCommand=none" in o and "UpdateHostKeys=no" in o and "ControlPath=none" in o and not any("accept-new" in x for x in o)
    and "VerifyHostKeyDNS=no" in o and "NoHostAuthenticationForLocalhost=no" in o
    and "ProxyCommand=none" in o and "ProxyJump=none" in o and "GSSAPIKeyExchange=no" in o and "NoHostAuthenticationForProxyCommand=no" in o
    and o.index("IgnoreUnknown=GSSAPIKeyExchange,NoHostAuthenticationForProxyCommand") < o.index("GSSAPIKeyExchange=no"),
    "[E] 지문 칸 있음 = yes + 전용 known_hosts · 전역·명령·DNS SSHFP·localhost 생략·프록시·공유 연결 끔", o)
chk(open(KH).read() == "box.invalid ssh-ed25519 %s\n" % B1 and (os.stat(KH).st_mode & 0o777) == 0o600, "[E] 전용 파일 = 설정 지문 키만 · 0600",
    open(KH).read())
SSH = shutil.which("ssh")
if SSH:
    HOSTILE = os.path.join(W, "hostile_config")
    with open(HOSTILE, "w") as f:
        f.write("IgnoreUnknown NoHostAuthenticationForProxyCommand,GSSAPIKeyExchange\nHost *\n  StrictHostKeyChecking no\n"
                "  GSSAPIKeyExchange yes\n  UserKnownHostsFile /tmp/evil_kh\n"
                "  GlobalKnownHostsFile /tmp/evil_kh2\n  KnownHostsCommand /bin/echo\n  VerifyHostKeyDNS yes\n"
                "  NoHostAuthenticationForLocalhost yes\n  NoHostAuthenticationForProxyCommand yes\n  ProxyCommand /bin/cat\n"
                "  UpdateHostKeys yes\n  CheckHostIP yes\n  ControlMaster auto\n  ControlPath /tmp/evil_cm\n")
    r = subprocess.run([SSH, "-F", HOSTILE, "-G"] + o + ["-p", "22", "box.invalid"], capture_output=True, text=True, timeout=60)
    G = {}
    for ln in r.stdout.splitlines():
        k, _, v = ln.partition(" ")
        G[k] = v
    want = {"stricthostkeychecking": "true", "userknownhostsfile": KH, "globalknownhostsfile": "/dev/null", "verifyhostkeydns": "false",
            "nohostauthenticationforlocalhost": "no", "updatehostkeys": "false", "checkhostip": "no", "controlmaster": "false",
            "controlpath": None, "proxycommand": None, "knownhostscommand": None}
    got = {k: G.get(k) for k in want}
    for k9, v9 in (("nohostauthenticationforproxycommand", "no"), ("gssapikeyexchange", "no")):
        if k9 in G:
            got[k9], want[k9] = G[k9], v9
    chk(r.returncode == 0 and got == want, "[E] 실제 ssh -G(적대 설정 파일): 고정 옵션이 이김 — yes · 전용 파일만 · DNS·localhost·프록시·공유 연결 끔",
        [r.returncode, r.stderr[-200:], got])
else:
    chk(True, "[E] ssh 없음 — 실제 해석 대조 건너뜀")
n0 = scans()
S.host_opts(C1, KH)
chk(scans() == n0, "[E] 파일이 설정과 같으면 다시 훑지 않음")
with open(KH, "a") as f:
    f.write("box.invalid ssh-ed25519 %s\n" % B2)
S.host_opts(C1, KH)
chk(scans() == n0 + 1 and open(KH).read() == "box.invalid ssh-ed25519 %s\n" % B1, "[E] 파일에 설정 밖 키가 끼면 버리고 다시 씀")
C2 = dict(C0, host_key_fpr=[F2])
S.host_opts(C2, KH)
chk(open(KH).read() == "box.invalid ssh-ed25519 %s\n" % B2, "[E] 설정 지문을 바꾸면 다음 부름이 따름")
C3 = dict(C0, port=2222, host_key_fpr=[F2])
S.host_opts(C3, KH)
chk(open(KH).read() == "[box.invalid]:2222 ssh-ed25519 %s\n" % B2 and "-p 2222" in open(SCAN_LOG).read().splitlines()[-1],
    "[E] 포트 바뀜 = '[호스트]:포트' 무늬로 다시 씀(포트 실어 훑음)", open(KH).read())
C4 = dict(C3, host="other.invalid")
scan(B2, host="other.invalid")
S.host_opts(C4, KH)
chk(open(KH).read() == "[other.invalid]:2222 ssh-ed25519 %s\n" % B2, "[E] 호스트 바뀜 = 다시 씀(무늬는 설정 호스트 — 훑은 줄의 이름 안 믿음)")
C5 = dict(C0, host_key_fpr=[F1, F3])
scan(B1)
S.host_opts(C5, KH)
n1 = scans()
S.host_opts(C5, KH)
chk(open(KH).read() == "box.invalid ssh-ed25519 %s\n" % B1 and scans() == n1, "[E] 서버가 설정 지문 일부만 냄 = 그 키만 · 같은 프로세스에선 다시 훑지 않음")
os.remove(KH)
with open(os.path.join(BIN, "ssh-keyscan"), "w") as f:
    f.write("")
os.chmod(os.path.join(BIN, "ssh-keyscan"), 0o644)
os.environ["PATH"] = BIN
chk(raises(lambda: S.host_opts(C1, KH), RuntimeError) and not os.path.exists(KH), "[E] ssh-keyscan 없음 = 실패(접속 안 함)")
T.finish()

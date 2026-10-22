#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
NEED = ("web_golden.mjs", "web_golden_diff.py", "web_golden_env.py", "web_golden.sh", "web_scenes.json", "web_probe.mjs")
if not all(os.path.isfile(os.path.join(TOOLS, n)) for n in NEED):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/web_golden*) 없음 · 건너뜀")
    T.finish()
ENV = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
node = T.node_path()

if node:
    r = subprocess.run([node, "--expose-internals", os.path.join(TOOLS, "web_golden.mjs"), "selftest"], capture_output=True, text=True, timeout=120, env=ENV)
    chk(r.returncode == 0 and "SELFTEST OK" in r.stdout, "G1 web_golden.mjs selftest(엄격안·모드·TT off·로고 분류·캐시 열쇠·커버리지 표)", (r.stdout + r.stderr)[-600:])
else:
    chk(not T.node_required(), "G1 node 없음 — 건너뜀(TJ_TEST_REQUIRE_NODE=1 이면 실패)")

r = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "web_golden_diff.py"), "--selftest"], capture_output=True, text=True, timeout=120, env=ENV)
chk(r.returncode == 0 and "SELFTEST OK" in r.stdout, "G2 web_golden_diff.py selftest(같음 0 · 줄 단위 의도된 변경 · 실패·누락 장면 = 실패)", (r.stdout + r.stderr)[-600:])

with open(os.path.join(TOOLS, "web_scenes.json"), encoding="utf-8") as f:
    SC = json.load(f)["scenes"]
ids = [s["id"] for s in SC]
chk(len(SC) >= 95, "G3 장면 수 ≥ 95(%d)" % len(SC))
chk(len(ids) == len(set(ids)), "G3 장면 id 겹침 0", sorted({i for i in ids if ids.count(i) > 1}))
chk(all(s.get("cfg") in ("s1", "s2", "s3") for s in SC), "G3 구성 = s1·s2·s3", [s["id"] for s in SC if s.get("cfg") not in ("s1", "s2", "s3")])
chk(all(s.get("pre") for s in SC), "G3 모든 장면에 선행 조건(pre)", [s["id"] for s in SC if not s.get("pre")])
by = lambda pred: [s["id"] for s in SC if pred(s)]  # noqa: E731
F = lambda s, p: any(f.get("path") == p for f in s.get("faults") or [])  # noqa: E731
need = {
    "R1 app.js 500": by(lambda s: F(s, "/v2/app.js") and any(f.get("status") == 500 for f in s["faults"])),
    "R1 tjdom.js 500": by(lambda s: F(s, "/v2/tjdom.js") and any(f.get("status") == 500 for f in s["faults"])),
    "R1 무기한 지연(s1·s3)": by(lambda s: F(s, "/v2/tjdom.js") and any(f.get("hang") for f in s["faults"])),
    "R2 그리기 예외": by(lambda s: s.get("r2")),
    "R3 401 → /login": by(lambda s: any(r[1] == "xlogin" for r in s.get("req") or [])),
    "R4 503": by(lambda s: any(f.get("status") == 503 for f in s.get("faults") or [])),
    "동작 상태(메모 입력·다시 그리기)": by(lambda s: "memo_state" in s["id"]),
    "로고 계측": by(lambda s: s.get("logo")),
    "s3 델타": by(lambda s: s["cfg"] == "s3" and any(r[1:] == ["s3", "delta"] for r in s.get("req") or [])),
    "s3 조각 늦게": by(lambda s: s["cfg"] == "s3" and s.get("partDelay")),
    "s3 첫 페인트(app.js 막음)": by(lambda s: s["cfg"] == "s3" and F(s, "/v2/app.js")),
    "첫 페인트 시간(차가운·따뜻한)": by(lambda s: s.get("fcp")),
    "연말 결산 이미지 저장": by(lambda s: s.get("download")),
    "검색": by(lambda s: "search" in s["id"]),
    "감탄": by(lambda s: "wow" in s["id"]),
    "상태 패널": by(lambda s: "health" in s["id"]),
    "금액 숨김·랜덤값": by(lambda s: (s.get("ls") or {}).get("tj_v2_hide") == "1" or (s.get("ls") or {}).get("tj_v2_rand") == "1"),
    "폰 390": by(lambda s: s.get("vp") == "m"),
    "s2 로그인 화면": by(lambda s: s["cfg"] == "s2" and s.get("url") == "/login"),
}
chk(all(need.values()), "G3 필수 장면 꼴 %d가지 전부 있음" % len(need), [k for k, v in need.items() if not v])
s2 = [s for s in SC if s["cfg"] == "s2"]
chk(len(s2) >= 2 and all(s.get("url") == "/login" and not s.get("pre_login") for s in s2[:2]) and not any(s.get("acts") for s in s2[:2]),
    "G3 s2 첫 두 장면 = 비밀번호 만들기 전 첫 비밀번호 화면(차례 의존)", [s["id"] for s in s2[:2]])
chk(any("login.css" in str(p) for s in s2[:1] for p in s.get("pre") or []), "G3 s2 첫 장면 = 비로그인 /v2/login.css 도입 전·뒤 선행 조건")

base2, base3 = os.path.join(T.TMP, "wg_s2"), os.path.join(T.TMP, "wg_s3")
envpy = os.path.join(TOOLS, "web_golden_env.py")
r2 = subprocess.run([sys.executable, "-I", "-B", envpy, "mkbase", "s2", base2, T.ROOT, "9899"], capture_output=True, text=True, timeout=120, env=ENV)
cfg2 = json.load(open(os.path.join(base2, "config.json"), encoding="utf-8")) if r2.returncode == 0 else {}
sc2 = os.path.join(base2, "state", "auth_setup_code")
chk(r2.returncode == 0 and (cfg2.get("web") or {}).get("login", {}).get("enabled") is True and cfg2["web"].get("port") == 9899
    and os.path.isfile(sc2) and (os.stat(sc2).st_mode & 0o777) == 0o600 and len(open(sc2).read().replace("-", "").strip()) == 16,
    "G4 s2 설치 폴더 = 로그인 켬 · 포트 · 고정 설정 코드(16글자 · 0600)", (r2.stdout + r2.stderr)[-400:])
r3 = subprocess.run([sys.executable, "-I", "-B", envpy, "mkbase", "s3", base3, T.ROOT, "9898"], capture_output=True, text=True, timeout=120, env=ENV)
led = os.path.join(base3, "state", "ledger.db")
n0 = sqlite3.connect(led).execute("SELECT COUNT(*) FROM postings").fetchone()[0] if r3.returncode == 0 and os.path.isfile(led) else -1
cfg3 = json.load(open(os.path.join(base3, "config.json"), encoding="utf-8")) if r3.returncode == 0 else {}
chk(n0 == 9 and (cfg3.get("web") or {}).get("login", {}).get("enabled") is False and cfg3["web"].get("token_logos") is True and len(cfg3.get("wallets") or []) == 1,
    "G4 s3 합성 원장(트리 스키마 · 행 9) · 로그인 끔 · 서버 로고 켬 · 합성 지갑 1", {"rows": n0, "err": (r3.stdout + r3.stderr)[-300:]})
ra = subprocess.run([sys.executable, "-I", "-B", envpy, "addrow", base3, T.ROOT], capture_output=True, text=True, timeout=120, env=ENV)
con = sqlite3.connect(led) if os.path.isfile(led) else None
n1 = con.execute("SELECT COUNT(*) FROM postings").fetchone()[0] if con else -1
newc = con.execute("SELECT COUNT(*) FROM assets WHERE symbol='NEWC'").fetchone()[0] if con else -1
chk(ra.returncode == 0 and n1 == n0 + 1 and newc == 1, "G4 addrow = 행 +1 · NEWC 자산 1(V1 표시 칸)", {"n1": n1, "newc": newc})

rx = subprocess.run([sys.executable, "-I", "-B", envpy, "mkbase", "s3", base3, T.ROOT, "9898"], capture_output=True, text=True, timeout=120, env=ENV)
nomark = os.path.join(T.TMP, "wg_nomark")
os.makedirs(os.path.join(nomark, "state"))
ry = subprocess.run([sys.executable, "-I", "-B", envpy, "addrow", nomark, T.ROOT], capture_output=True, text=True, timeout=120, env=ENV)
rz = subprocess.run([sys.executable, "-I", "-B", envpy, "serve", os.path.join(T.TMP, "n.log"), os.path.join(T.SRC, "web.py")], capture_output=True, text=True, timeout=60,
                    env=dict(ENV, TJ_BASE=nomark))
chk(rx.returncode != 0 and "거부" in (rx.stdout + rx.stderr) and ry.returncode != 0 and "거부" in (ry.stdout + ry.stderr) and rz.returncode != 0 and "거부" in (rz.stdout + rz.stderr)
    and not os.path.exists(os.path.join(nomark, "state", "ledger.db")),
    "G4 표식 없는 폴더 = 거부(이미 있는 폴더에 mkbase · 표식 없는 addrow · 표식 없는 TJ_BASE 로 serve)", [x.returncode for x in (rx, ry, rz)])

if node:
    r = subprocess.run([node, "--expose-internals", os.path.join(TOOLS, "web_golden.mjs"), "run", "--tree", T.ROOT, "--out", os.path.join(T.TMP, "wg_o"),
                        "--cache", os.path.join(T.TMP, "wg_c"), "--cfg", "s1", "--only", "no_such_scene", "--port", "9897"], capture_output=True, text=True, timeout=60, env=ENV)
    chk(r.returncode != 0 and "없는 장면" in r.stdout and "CHROME_PID" not in r.stdout, "G6 없는 장면 id = 실패(장면 0 통과 없음)", r.stdout[-300:])
    r = subprocess.run([node, "--expose-internals", os.path.join(TOOLS, "web_golden.mjs"), "run", "--tree", T.ROOT, "--out", os.path.join(T.TMP, "wg_o"),
                        "--cache", os.path.join(T.TMP, "wg_c"), "--cfg", "s2", "--only", "pc_dash", "--port", "9897"], capture_output=True, text=True, timeout=60, env=ENV)
    chk(r.returncode != 0 and "CHROME_PID" not in r.stdout, "G6 구성과 안 맞는 장면 = 실패", r.stdout[-300:])

if node:
    r = subprocess.run([node, "--check", os.path.join(TOOLS, "web_probe.mjs")], capture_output=True, text=True, timeout=60)
    chk(r.returncode == 0, "G5 web_probe.mjs 문법(node --check)", r.stderr[-300:])
else:
    chk(not T.node_required(), "G5 node 없음 — 건너뜀")
r = subprocess.run(["bash", "-n", os.path.join(TOOLS, "web_golden.sh")], capture_output=True, text=True, timeout=60)
chk(r.returncode == 0, "G5 web_golden.sh 문법(bash -n)", r.stderr[-300:])
T.finish()

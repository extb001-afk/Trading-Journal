#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402

TOOL = os.path.join(T.ROOT, "tools", "rollback_check.py")
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import rollback_check as RC  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5, "backfill_since": "2026-01-01"}, open(os.path.join(T.TMP, "config.json"), "w"))
import config  # noqa: E402
import core  # noqa: E402

c = core.Core(config.load_config())


def raw(kind, uid, ccy, state):
    pay = {"uuid": uid, "currency": ccy, "amount": "10", "fee": "0", "txid": "0x" + uid[-2:] * 32, "state": state,
           "created_at": "2026-02-01T00:00:00+00:00", "done_at": "2026-02-01T00:00:00+00:00"}
    c.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('okx',?,?,0,?,?)", (kind, uid, json.dumps(pay), 1769904000))
    return pay


def n_post(uid):
    return c.conn.execute("SELECT count(*) FROM postings WHERE source_id=?", (uid,)).fetchone()[0]


for kind, uid in (("deposit", "okx:kd1"), ("withdraw", "okx:kw1")):
    c.conn.execute("INSERT INTO meta (k, v) VALUES (?, 'okx_prewin')", ("exf_rawskip:okx:%s:%s" % (kind, uid),))
P = {"okx:kd1": raw("deposit", "okx:kd1", "TKJ", "ACCEPTED"), "okx:kd2": raw("deposit", "okx:kd2", "TKJ", "ACCEPTED"),
     "okx:kw1": raw("withdraw", "okx:kw1", "TKJ", "DONE"), "okx:kw2": raw("withdraw", "okx:kw2", "TKJ", "DONE")}
r_d1 = c.svc_exf._post_exf_deposit_in("okx", "okx:kd1", P["okx:kd1"])
r_w1 = c.svc_exf._post_exf_withdraw("okx", "okx:kw1", P["okx:kw1"])
c.svc_exf._post_exf_deposit_in("okx", "okx:kd2", P["okx:kd2"])
c.svc_exf._post_exf_withdraw("okx", "okx:kw2", P["okx:kw2"])
T.chk(not r_d1 and not r_w1 and n_post("okx:kd1") == 0 and n_post("okx:kw1") == 0 and n_post("okx:kd2") > 0 and n_post("okx:kw2") > 0,
      "K1 실제 reader: 표식 원본(입금·출금) = 기장 안 함 · 표식 없는 원본 = 기장", (r_d1, r_w1, [n_post(u) for u in P]))
c.conn.rollback()
c.conn.close()
SRCS = {f: open(os.path.join(T.SRC, f), encoding="utf-8").read() for f in sorted(os.listdir(T.SRC)) if RC.CORE_RE.fullmatch(f)}
ALL = set()
for t9 in SRCS.values():
    ALL |= RC.rawskip_readers(t9)
T.chk(ALL == {"deposit", "withdraw"}, "K1 이 트리 core 판정 = 입금·출금 둘 다 읽음(위 실제 reader 와 같음)", sorted(ALL))
host = [f for f, t9 in SRCS.items() if RC.rawskip_readers(t9)]
T.chk(len(host) == 1, "K1 (전제) 읽는 곳 = core 파일 하나", host)
HT = SRCS[host[0]] if host else ""
KD, KW = 'f"exf_rawskip:{ex}:deposit:{uid}"', 'f"exf_rawskip:{ex}:withdraw:{uid}"'
no_w = HT.replace(KW, 'f"exf_unread:{ex}:withdraw:{uid}"')
no_d = HT.replace(KD, 'f"exf_unread:{ex}:deposit:{uid}"')
T.chk(no_w != HT and no_d != HT, "K1 (전제) 원문에 입금·출금 열쇠 꼴이 있어 변이가 듦")
cmt = (no_w.replace(KD, 'f"exf_unread:{ex}:deposit:{uid}"')
       + '\n\n# 표식 exf_rawskip:{ex}:deposit:{uid} · exf_rawskip:{ex}:withdraw:{uid} 을 읽던 자리(주석만)\n'
       + 'def _gone(ex, uid, log):\n    """f"exf_rawskip:{ex}:withdraw:{uid}" 독스트링"""\n    f"exf_rawskip:{ex}:deposit:{uid}"\n'
       + '    log.info(f"exf_rawskip:{ex}:withdraw:{uid}")\n    return None\n')
T.chk(RC.rawskip_readers(no_w) == {"deposit"} and RC.rawskip_readers(no_d) == {"withdraw"} and RC.rawskip_readers(cmt) == set(),
      "K1 부분 되돌림 = 출금만 뺌 → 입금만 · 입금만 뺌 → 출금만 · 주석·독스트링·홀로 선 글자열·로그 호출만 → 없음",
      (RC.rawskip_readers(no_w), RC.rawskip_readers(no_d), RC.rawskip_readers(cmt)))
T.chk(RC.rawskip_readers("def broken(:\n") == set(), "K1 문법 오류 파일 = 읽는 곳 없음(통과 근거 안 됨)")
QW = 'self.conn.execute("SELECT 1 FROM meta WHERE k=?", (' + KW + ',)).fetchone()'
v_col = HT.replace(QW, QW.replace("WHERE k=?", "WHERE v=?"))
v_and = HT.replace(QW, "False and " + QW)
T.chk(v_col != HT and v_and != HT, "K1 (전제) 출금 조회 원문 꼴이 있어 변이가 듦")
SYN = "class M:\n    def a(self, ex, uid):\n%s\n"
dead_if = SYN % ('        if False:\n            return self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_rawskip:{ex}:withdraw:{uid}",)).fetchone()')
bare = SYN % ('        self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_rawskip:{ex}:withdraw:{uid}",)).fetchone()')
live = SYN % ('        return self.conn.execute("SELECT 1 FROM meta WHERE k = ? LIMIT 1", (f"exf_rawskip:{ex}:withdraw:{uid}",)).fetchone()')
T.chk(RC.rawskip_readers(v_col) == {"deposit"} and RC.rawskip_readers(v_and) == {"deposit"} and RC.rawskip_readers(dead_if) == set()
      and RC.rawskip_readers(bare) == set() and RC.rawskip_readers(live) == {"withdraw"},
      "K1 출금 조회 WHERE v=? · 'False and' · if False 가지 · 결과 안 쓰는 문장 = 못 읽음 · (대조) 바른 조회(공백·LIMIT 1) = 읽음",
      [sorted(RC.rawskip_readers(x)) for x in (v_col, v_and, dead_if, bare, live)])

G = os.path.join(T.TMP, "inst")
os.makedirs(os.path.join(G, "tools"))
os.makedirs(os.path.join(G, "state"))
shutil.copy2(TOOL, os.path.join(G, "tools", "rollback_check.py"))
ENV = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
ENV.update(GIT_CONFIG_NOSYSTEM="1", HOME=os.path.join(T.TMP, "home"))
os.makedirs(ENV["HOME"])


def git(*a):
    return subprocess.run(["git", "-C", G] + list(a), capture_output=True, text=True, check=True, env=ENV).stdout.strip()


def put(rel, s):
    p = os.path.join(G, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


READ = ('    def _post_{k}(self, ex, uid):\n'
        '        if self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_rawskip:{{ex}}:{k}:{{uid}}",)).fetchone():\n'
        '            return False\n'
        '        return True\n')
git("init", "-q")
git("config", "user.email", "t@t")
git("config", "user.name", "t")
DB1 = "SCHEMA_VERSION = 2\nDATA_REV = 1\n"
VERS = {
    "old": {"core.py": "X = 1\n", "core_exf.py": "class M:\n    def _post(self, ex, uid):\n        return True\n", "db.py": DB1},
    "dep": {"core.py": "X = 1\n", "core_exf.py": "class M:\n" + READ.format(k="deposit"), "db.py": DB1},
    "wd": {"core.py": "X = 1\n", "core_exf.py": "class M:\n" + READ.format(k="withdraw"), "db.py": DB1},
    "cmt": {"core.py": "X = 1\n", "core_exf.py": cmt, "db.py": DB1},
    "both": {"core.py": "X = 1\n", "core_exf.py": "class M:\n" + READ.format(k="deposit") + READ.format(k="withdraw"), "db.py": DB1},
    "split": {"core.py": "X = 1\n", "core_exf.py": "class M:\n" + READ.format(k="deposit"), "core_exf_wd.py": "class W:\n" + READ.format(k="withdraw"), "db.py": DB1},
    "nocore": {"core_exf.py": "class M:\n" + READ.format(k="deposit") + READ.format(k="withdraw"), "db.py": DB1},
    "rev2": {"core.py": "X = 1\n", "core_exf.py": "class M:\n" + READ.format(k="deposit") + READ.format(k="withdraw"), "db.py": "DATA_REV = 2\n"},
    "nodb": {"core.py": "X = 1\n", "core_exf.py": "class M:\n" + READ.format(k="deposit") + READ.format(k="withdraw")},
}
SHA = {}
for name, files in VERS.items():
    for f9 in os.listdir(os.path.join(G, "src")) if os.path.isdir(os.path.join(G, "src")) else []:
        os.remove(os.path.join(G, "src", f9))
    for f9, s in files.items():
        put("src/" + f9, s)
    git("add", "-A")
    git("commit", "-qm", name)
    git("tag", "v_" + name)
    SHA[name] = git("rev-parse", "HEAD")
put("src/core.py", "X = 'now'\n")
put("src/core_exf.py", "class M:\n" + READ.format(k="deposit") + READ.format(k="withdraw"))
put("src/db.py", "DATA_REV = 2\n")
git("add", "-A")
git("commit", "-qm", "now")
NOW = git("rev-parse", "HEAD")
DB = os.path.join(G, "state", "ledger.db")


def ledger(keys, rev="1"):
    if os.path.exists(DB):
        os.remove(DB)
    cx = sqlite3.connect(DB)
    cx.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
    if rev is not None:
        cx.execute("INSERT INTO meta VALUES('data_rev', ?)", (rev,))
    cx.execute("INSERT INTO meta VALUES('exf_rawskiq', 'x')")
    for k in keys:
        cx.execute("INSERT INTO meta VALUES(?, 'okx_prewin')", (k,))
    cx.commit()
    cx.close()


def run(*a, cwd=None):
    p = subprocess.run([sys.executable, "-B", os.path.join(G, "tools", "rollback_check.py")] + list(a), capture_output=True, text=True, env=ENV,
                       cwd=cwd, timeout=120)
    return p.returncode, p.stdout + p.stderr


WD2 = ["exf_rawskip:okx:withdraw:okx:a%d" % i for i in range(2)]
DEP1 = ["exf_rawskip:okx:deposit:okx:b1"]
rc, out = run("v_old")
T.chk(rc == 0 and "원장 없음" in out, "K2 원장 없음 = 통과", out)
rc, out = run("v_nosuch")
T.chk(rc == 2, "K2 원장 없음이어도 모르는 커밋·태그 = 확인 불가(rc 2 · 대상 먼저)", out)
ledger([])
rc, out = run("v_old")
T.chk(rc == 0 and "표식 없음" in out, "K2 표식 없는 원장 + 옛 판 = 통과(과잉 거부 없음)", out)
ledger(WD2)
with open(os.path.join(G, "state", "ledger_rowfix_undo_okx_prewin_20260101_000000_ab12cd34.json"), "w") as f:
    f.write("{}")
before = open(DB, "rb").read()
rc, out = run("v_old")
T.chk(rc == 1 and "거부" in out and "출금 2개" in out and "ledger_rowfix.py --undo" in out and "ledger_rowfix_undo_okx_prewin_20260101_000000_ab12cd34.json" in out,
      "K2 출금 표식 2 + 읽기 없는 옛 판 = 거부(rc 1 · 개수 · undo 안내 · undo 파일 이름)", out)
for nm, want in (("dep", 1), ("cmt", 1), ("wd", 0), ("both", 0), ("split", 0)):
    rc, out = run("v_" + nm)
    T.chk(rc == want, "K2 출금 표식만 + %s 판 = %s" % (nm, "거부" if want else "통과"), (rc, out))
rc, out = run(SHA["dep"])
T.chk(rc == 1, "K2 커밋 해시로도 같은 판정(입금만 읽는 판 = 거부)", out)
ledger(WD2 + DEP1)
for nm, want in (("wd", 1), ("dep", 1), ("both", 0), ("split", 0)):
    rc, out = run("v_" + nm)
    T.chk(rc == want, "K2 입금·출금 표식 + %s 판 = %s" % (nm, "거부" if want else "통과"), (rc, out))
ledger(["exf_rawskip:okx:transfer:okx:z1"])
rc, out = run("v_both")
T.chk(rc == 1 and "모르는 꼴" in out, "K2 모르는 꼴 표식 = 거부", out)
ledger(WD2)
TREE = os.path.join(T.TMP, "tree_old")
os.makedirs(os.path.join(TREE, "src"))
for f9, s in VERS["old"].items():
    with open(os.path.join(TREE, "src", f9), "w") as f:
        f.write(s)
rc, out = run("--tree", TREE)
T.chk(rc == 1, "K2 --tree 옛 판 = 거부", out)
with open(os.path.join(TREE, "src", "core_exf.py"), "w") as f:
    f.write(VERS["both"]["core_exf.py"])
rc, out = run("--tree", TREE)
T.chk(rc == 0, "K2 --tree 읽는 판 = 통과", out)
rc, out = run("v_nosuch")
T.chk(rc == 2 and "확인 불가" in out, "K2 모르는 커밋·태그 = 확인 불가(rc 2)", out)
rc, out = run("v_nocore")
T.chk(rc == 2 and "core.py" in out, "K2 core.py 없는 판 = 확인 불가(rc 2)", out)
rc, out = run("v_old", "--tree", TREE)
rc2, out2 = run()
T.chk(rc == 2 and rc2 == 2, "K2 인자 둘 다·없음 = rc 2", (out, out2))
T.chk(open(DB, "rb").read() == before, "K2 원장 무변(읽기 전용)")
with open(os.path.join(T.TMP, "broken.db"), "wb") as f:
    f.write(b"SQLite format 3\x00" + b"\xff" * 200)
rc, out = run("v_old", "--ledger", os.path.join(T.TMP, "broken.db"))
T.chk(rc == 2 and "확인 불가" in out, "K2 깨진 원장 = 확인 불가(rc 2)", out)
T.chk(git("rev-parse", "HEAD") == NOW, "K2 점검은 checkout 안 함(HEAD 무변)")

ledger([], rev="2")
rc, out = run("v_both")
T.chk(rc == 1 and "데이터 개정" in out and "2 > " in out and "DATA_REV 1" in out and "--undo-autofix" in out and "--data-rev-down 1" in out and "ledger_restore" in out,
      "K4 원장 개정 2 + DATA_REV 1 판(표식 없음) = 거부(rc 1 · 되돌리기 순서·백업 안내)", out)
rc, out = run("v_rev2")
T.chk(rc == 0 and "표식 없음" in out, "K4 원장 개정 2 + DATA_REV 2 판 = 통과", out)
rc, out = run("v_nodb")
T.chk(rc == 1 and "DATA_REV 0" in out, "K4 db.py 없는 판 = 개정 0 = 거부", out)
rc, out = run("v_old")
T.chk(rc == 1 and "데이터 개정" in out, "K4 옛 판(DATA_REV 1) = 거부(표식보다 먼저 판정)", out)
ledger(WD2, rev="2")
rc, out = run("v_rev2")
T.chk(rc == 0, "K4 개정 2 + 출금 표식 + 둘 다 읽는 DATA_REV 2 판 = 통과", out)
rc, out = run("v_dep")
T.chk(rc == 1 and "데이터 개정" in out, "K4 개정 2 + 표식 + 입금만 읽는 DATA_REV 1 판 = 거부(개정 사유가 먼저)", out)
ledger([], rev=None)
rc, out = run("v_old")
T.chk(rc == 0 and "표식 없음" in out, "K4 data_rev 칸 없는 원장(개정 0) + 옛 판 = 통과(과잉 거부 없음)", out)
ledger([], rev="x")
rc, out = run("v_both")
T.chk(rc == 2 and "확인 불가" in out and "data_rev" in out, "K4 개정 번호가 숫자 아님 = 확인 불가(rc 2)", out)
ledger([], rev="2")
with open(os.path.join(TREE, "src", "db.py"), "w") as f:
    f.write("DATA_REV = 1\n")
rc, out = run("--tree", TREE)
T.chk(rc == 1 and "DATA_REV 1" in out, "K4 --tree DATA_REV 1 + 개정 2 = 거부", out)
with open(os.path.join(TREE, "src", "db.py"), "w") as f:
    f.write("# DATA_REV = 9 주석\nDATA_REV = 2\n")
rc, out = run("--tree", TREE)
T.chk(rc == 0, "K4 --tree DATA_REV 2(줄 머리 정규식 · 주석 무시) = 통과", out)
T.chk(RC.target_data_rev(None, TREE) == 2 and RC.ledger_data_rev(DB) == 2 and RC.ledger_data_rev(os.path.join(T.TMP, "none.db")) == 0,
      "K4 함수: 판 DATA_REV · 원장 개정 · 원장 없음 = 0")
ledger(WD2)
T.chk(RC.ledger_data_rev(DB) == 1, "K4 (전제) K3 용 원장 = 개정 1 + 출금 표식")

CMD = "python3 tools/rollback_check.py <예전 버전의 커밋·태그> && git checkout <예전 버전의 커밋·태그>"
SH = shutil.which("bash") or "/bin/bash"
PYDIR = os.path.join(T.TMP, "pybin")
os.makedirs(PYDIR)
os.symlink(sys.executable, os.path.join(PYDIR, "python3"))
ENV3 = dict(ENV, PATH=PYDIR + os.pathsep + ENV.get("PATH", ""))


def readme_cmd(tag):
    p = subprocess.run([SH, "-c", CMD.replace("<예전 버전의 커밋·태그>", tag)], cwd=G, capture_output=True, text=True, env=ENV3, timeout=120)
    return p.returncode, p.stdout + p.stderr


rc, out = readme_cmd("v_old")
T.chk(rc == 1 and git("rev-parse", "HEAD") == NOW, "K3 표식 원장 + 옛 판 = README 명령이 checkout 전에 멈춤(HEAD 무변)", out)
cx = sqlite3.connect(DB)
cx.execute("DELETE FROM meta WHERE k >= 'exf_rawskip:' AND k < 'exf_rawskip;'")
cx.commit()
cx.close()
rc, out = readme_cmd("v_old")
T.chk(rc == 0 and git("rev-parse", "HEAD") == SHA["old"], "K3 undo 뒤(표식 없음) = 통과 + checkout", out)
T.finish()

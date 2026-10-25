#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import paths  # noqa: E402
import db as dbm  # noqa: E402
import core_inbox  # noqa: E402
import inbox  # noqa: E402
import ledger_restore as LR  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
os.makedirs(S, exist_ok=True)
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": []}, f)
os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
IB = os.path.join(S, "inbox")
SEGD = os.path.join(IB, "ex")
SEGP = os.path.join(SEGD, "000000001.jsonl")
LIVE = paths.DB_PATH


def line(ident, pad=120):
    return (json.dumps({"kind": "tkj-gen", "id": ident, "pad": "x" * pad}, separators=(",", ":")) + "\n").encode()


A, B, C = line("A"), line("B"), line("C")


class Drain(core_inbox.InboxMixin):

    def __init__(self, conn):
        self.conn = conn

    def _consume_record(self, rec):
        return None


def put(data: bytes):
    os.makedirs(SEGD, exist_ok=True)
    with open(SEGP, "wb") as f:
        f.write(data)


def fresh_live(tag):
    for p9 in (LIVE, LIVE + "-wal", LIVE + "-shm"):
        if os.path.exists(p9):
            os.remove(p9)
    c = dbm.open_db(LIVE)
    c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('tkj_tag', ?)", (tag,))
    c.commit()
    return c


def make_backup(name, anchor=True):
    if os.path.isdir(IB):
        shutil.rmtree(IB)
    put(A)
    c = fresh_live("backup")
    seg9, off9, n9 = Drain(c)._drain_stream("ex", inbox.SegmentReader(SEGD), 1, 0)
    if not anchor:
        c.execute("DELETE FROM meta WHERE k=?", (inbox.ANCHOR_META + "ex",))
        c.commit()
    bk = os.path.join(S, name)
    if os.path.exists(bk):
        os.remove(bk)
    b9 = sqlite3.connect(bk)
    c.backup(b9)
    b9.execute("PRAGMA journal_mode=DELETE").fetchone()
    b9.close()
    c.execute("UPDATE meta SET v='live' WHERE k='tkj_tag'")
    c.commit()
    c.close()
    return bk, (seg9, off9, n9)


def tag():
    with sqlite3.connect(LIVE) as c9:
        return c9.execute("SELECT v FROM meta WHERE k='tkj_tag'").fetchone()[0]


def restore(bk, unverified=None):
    p = LR.plan(bk, unverified=unverified)
    try:
        LR.apply(p, proc_check=False, log=lambda *a: None)
        err = None
    except SystemExit as e:
        err = str(e)
    return p, err


def read_from_restored():
    with sqlite3.connect(LIVE) as c9:
        row = c9.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ex'").fetchone()
    seg9, off9 = row if row else (1, 0)
    recs, _s, _o = inbox.SegmentReader(SEGD).read_batch(seg9, off9)
    return [r[0].get("id") for r in recs], row


BK, (s1, o1, n1) = make_backup("bk_anchor.db")
with sqlite3.connect(BK) as c9:
    off_b = c9.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ex'").fetchone()
    anc_b = json.loads(c9.execute("SELECT v FROM meta WHERE k=?", (inbox.ANCHOR_META + "ex",)).fetchone()[0])
chk(n1 == 1 and off_b == (1, len(A)) and anc_b == inbox.anchor(SEGD, 1, len(A)) and anc_b["n"] == len(A),
    "G1 tj-core 소비 = 위치(1, A 끝)와 같은 커밋으로 내용 앵커 · 백업이 그대로 지님", (off_b, anc_b))

put(A + C)
p, err = restore(BK)
got, row = read_from_restored()
chk(err is None and p["coverage"]["ex"]["state"] == "replay" and not p["rewind"] and got == ["C"] and row == (1, len(A)),
    "G2 같은 세대(이어 쓴 인박스) = 이어읽기 · 미처리 C 한 번", (p["coverage"]["ex"], err, got, row))
p, err = restore(BK)
got, row = read_from_restored()
chk(err is None and p["coverage"]["ex"]["state"] == "replay" and got == ["C"], "G2 반복 복원 = 같은 결과(C 한 번)", (p["coverage"]["ex"], err, got))
put(A + C[:40])
p, err = restore(BK)
got, row = read_from_restored()
put(A + C)
got2, _r = read_from_restored()
chk(err is None and p["coverage"]["ex"]["state"] == "replay" and got == [] and got2 == ["C"],
    "G2 줄 쓰는 중(부분 줄) = 이어읽기 · 완성되면 C 한 번", (p["coverage"]["ex"], err, got, got2))

for name, data, want in (("같은 길이", B + C, ["B", "C"]), ("더 긴", line("B", pad=400) + C, ["B", "C"])):
    put(data)
    p, err = restore(BK)
    got, row = read_from_restored()
    chk(err is None and p["coverage"]["ex"]["state"] == "gap" and "ex" in p["rewind"] and "다름" in p["coverage"]["ex"].get("why", "")
        and row is None and got == want,
        f"G3 같은 번호·{name} 다른 세대 = gap(처음부터) · B·C 각 한 번(종전 = B 조용히 건너뜀)", (p["coverage"]["ex"], err, got, row))
with sqlite3.connect(LIVE) as c9:
    anc_after = c9.execute("SELECT count(*) FROM meta WHERE k=?", (inbox.ANCHOR_META + "ex",)).fetchone()[0]
chk(anc_after == 0, "G3 처음부터 다시 읽는 스트림 = 복원 원장의 옛 앵커도 지움(위치와 같이)", anc_after)

put(line("B", pad=0))
p, err = restore(BK)
got, row = read_from_restored()
chk(err is None and p["coverage"]["ex"]["state"] == "gap" and got == ["B"] and row is None, "G4 더 짧은 파일 = gap(종전대로)", (p["coverage"]["ex"], got))

BK0, _x = make_backup("bk_noanchor.db", anchor=False)
put(B + C)
p, err = restore(BK0)
chk(p["coverage"]["ex"]["state"] == "unverified" and err and "--inbox-unverified" in err and tag() == "live",
    "G5 앵커 없는 백업 = 확인 불가 → 적용 거부(원장 그대로 · 안내)", (p["coverage"]["ex"], err))
p, err = restore(BK0, unverified="rewind")
got, row = read_from_restored()
chk(err is None and p["coverage"]["ex"]["state"] == "gap" and "ex" in p["rewind"] and got == ["B", "C"] and tag() == "backup",
    "G5 --inbox-unverified rewind = gap(처음부터 + 수집기 되감기) · B·C 각 한 번", (p["coverage"]["ex"], err, got))
put(A + C)
p, err = restore(BK0, unverified="trust")
got, row = read_from_restored()
chk(err is None and p["coverage"]["ex"]["state"] == "replay" and got == ["C"], "G5 --inbox-unverified trust = 이어읽기(원래 인박스를 확인한 명시 선택)", (p["coverage"]["ex"], err, got))
OUTSIDE = os.path.join(T.TMP, "outside.jsonl")
with open(OUTSIDE, "wb") as f:
    f.write(A + C)
os.remove(SEGP)
os.symlink(OUTSIDE, SEGP)
p, err = restore(BK)
chk(p["coverage"]["ex"]["state"] == "unverified" and err and "링크" in p["coverage"]["ex"].get("why", ""), "G5 세그먼트가 인박스 밖을 가리키는 링크 = 확인 불가(밖 파일 내용으로 판정 안 함)", p["coverage"]["ex"])
os.remove(SEGP)
put(B + C)
cli9 = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", "ledger_restore.py"), "restore", BK0], capture_output=True, text=True, timeout=120,
                      env=dict({k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}, TJ_BASE=T.TMP))
chk(cli9.returncode == 0 and "적용 거부" in cli9.stdout and "--inbox-unverified" in cli9.stdout, "G5 미리보기(CLI) = 확인 불가 · 고르는 법 안내", cli9.stdout[-600:] + cli9.stderr[-400:])

chk(not T.NET_TRIES, "바깥 연결 0", T.NET_TRIES)
T.finish()

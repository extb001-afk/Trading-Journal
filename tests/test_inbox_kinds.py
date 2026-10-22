#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "inbox_kinds.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/inbox_kinds.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import inbox_kinds as K  # noqa: E402

cur = K.table(T.ROOT)
base = K.load_baseline(T.ROOT)
d = K.diff(cur, base)
chk(not d, "K1 inbox 계약 표 = 기준선(바뀌면 freeze + 사유 커밋)", [x[0] for x in d][:10])
chk(len(cur["kinds"]) == 10 and cur["kinds"][-1] == "_corrupt" and len(set(cur["kinds"])) == 10, "K2 종류 10 · 분기 끝 _corrupt", cur["kinds"])
chk(all(cur["producers"][k] for k in cur["kinds"]), "K2 종류마다 생산 자리 1 이상", {k: len(v) for k, v in cur["producers"].items()})
chk(all(cur["consumers"][k]["handler"] for k in cur["kinds"]), "K2 종류마다 소비 처리기", sorted(cur["consumers"]))

CORE_INBOX = '''import ev
from consts import BK


class InboxMixin:
    def _consume_record(self, rec):
        if rec.get("kind") == "a_tx":
            x = rec["ax"]
            self._apply_a(x, rec)
        elif rec.get("kind") == BK:
            self._consume_b(rec)
        elif rec.get("kind") == ev.KIND:
            self._consume_c(rec)
        elif rec.get("kind") == "_corrupt":
            print(rec.get("raw"))
'''
CORE_B = '''class BMixin:
    def _consume_b(self, r):
        n = r["bx"]
        return self._b_inner(n, r)

    def _b_inner(self, n, q):
        return q.get("by"), "bz" in q

    def _apply_a(self, x, rr):
        return rr["aa"]

    def _consume_c(self, rec):
        return rec["cx"]
'''
PROD = '''from consts import BK
import ev

LOCAL = "a_tx"


def emit_a():
    return {"v": 1, "kind": LOCAL, "ax": 1}


def emit_b():
    rec = {"v": 1, "kind": BK, "bx": 2}
    rec["repair"] = True
    return rec


class W:
    def emit_c(self):
        return {"v": ev.VERSION, "kind": ev.KIND, "cx": 3}
'''
FILES = {"src/core_inbox.py": CORE_INBOX, "src/core_b.py": CORE_B, "src/prod.py": PROD,
         "src/ev.py": 'KIND = "c_tx"\nVERSION = 1\n', "src/consts.py": 'BK = "b_tx"\n',
         "src/inbox.py": 'def read_batch():\n    return {"kind": "_corrupt", "raw": "", "raw_hex": ""}\n'}


def mk(name, edits=None):
    root = os.path.join(T.TMP, name)
    for rel, body in FILES.items():
        body = (edits or {}).get(rel, body)
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
    os.makedirs(os.path.join(root, "tools"), exist_ok=True)
    return root


b0 = K.table(mk("k0"))
chk(b0["kinds"] == ["a_tx", "b_tx", "c_tx", "_corrupt"], "K3 분기 차례 · 글자·from 상수·모듈 상수 풀이", b0["kinds"])
chk(b0["consumers"]["b_tx"]["reads"] == ["bx", "by", "bz"] and b0["consumers"]["b_tx"]["handler"] == "core_b.py:BMixin._consume_b",
    "K3 처리기 + 위임 메서드 따라감(get · in)", b0["consumers"]["b_tx"])
chk(b0["consumers"]["a_tx"]["reads"] == ["aa", "ax"], "K3 분기 몸통에서 넘긴 레코드도 따라감", b0["consumers"]["a_tx"])
chk([(p["file"], p["func"], p["keys"]) for p in b0["producers"]["c_tx"]] == [("src/prod.py", "W.emit_c", ["cx", "kind", "v"])],
    "K3 생산 자리 = 파일·qualname·열쇠", b0["producers"]["c_tx"])
chk(b0["appended"] == [{"key": "repair", "file": "src/prod.py", "func": "emit_b", "n": 1}], "K3 덧붙이는 열쇠 자리", b0["appended"])
chk(b0["v"]["c_tx"] == ["ev.VERSION"] and b0["v"]["a_tx"] == ["1"], "K3 판 번호 식", b0["v"])
chk(K.diff(K.table(mk("k0b")), b0) == [], "K3 그대로 = 차이 0")

cases = {
    "새 생산 자리": {"src/prod.py": PROD + '\n\ndef emit_a2():\n    return {"v": 1, "kind": "a_tx", "ax": 9}\n'},
    "기존 dict 에 새 열쇠": {"src/prod.py": PROD.replace('"cx": 3}', '"cx": 3, "cy": 4}')},
    "처리기가 새 열쇠 읽음": {"src/core_b.py": CORE_B.replace('return rec["cx"]', 'return rec["cx"], rec.get("cnew")')},
    "분기 차례 바뀜": {"src/core_inbox.py": CORE_INBOX.replace('== "a_tx"', '== "@@"').replace("== BK", '== "a_tx"').replace('== "@@"', "== BK")},
    "덧붙이는 열쇠 자리": {"src/prod.py": PROD.replace('    return {"v": ev.VERSION', '    r = {}\n        r["ts_fix"] = 1\n        return {"v": ev.VERSION')},
    "처리기 바뀜": {"src/core_inbox.py": CORE_INBOX.replace("self._consume_c(rec)", "self._consume_b(rec)")},
    "판 번호 바뀜": {"src/prod.py": PROD.replace('{"v": 1, "kind": LOCAL', '{"v": 2, "kind": LOCAL')},
    "dict() 꼴 새 생산 자리": {"src/prod.py": PROD + '\n\ndef emit_a3():\n    return dict(v=1, kind="a_tx", ax=7)\n'},
    "처리기가 레코드를 통째로 넘김": {"src/core_b.py": CORE_B.replace('return rec["cx"]', 'return rec["cx"], helper.use(rec)')},
}
for i, (why, ed) in enumerate(sorted(cases.items())):
    dd = K.diff(K.table(mk("kc%d" % i, ed)), b0)
    chk(bool(dd), "K3 %s = 차이로 잡힘" % why, [x[0] for x in dd])

T.finish()

#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

chk = T.chk
TOOL = os.path.join(T.ROOT, "tools", "seed_local_split.py")
if not os.path.isfile(TOOL):
    public_layout = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(public_layout, "공개판 배치 — 비공개 도구(tools/seed_local_split.py) 없음 · 건너뜀" if public_layout
        else "저장소 배치인데 tools/seed_local_split.py 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, os.path.dirname(TOOL))
import seed_local_split as SL  # noqa: E402
import paths  # noqa: E402
import seeds  # noqa: E402

A1, A2, A3, A4 = ("0x" + c * 40 for c in "abcd")


def put(root, rel, obj):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def tree(root):
    out = {}
    for dp, _d, fs in os.walk(root):
        for fn in fs:
            p = os.path.join(dp, fn)
            with open(p, encoding="utf-8") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


def run(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SL.main(list(args))
    return rc, buf.getvalue()


def case(name, old, new, cur):
    base = os.path.join(T.TMP, name)
    d = {"old": os.path.join(base, "old", "seed"), "new": os.path.join(base, "new", "seed"), "st": os.path.join(base, "state")}
    for k, files in (("old", old), ("new", new)):
        os.makedirs(d[k], exist_ok=True)
        for rel, o in files.items():
            put(d[k], rel, o)
    if cur is not None:
        os.makedirs(os.path.join(d["st"], "seed_local"), exist_ok=True)
        for rel, o in cur.items():
            put(os.path.join(d["st"], "seed_local"), rel, o)
    d["out"] = os.path.join(d["st"], "seed_local")
    return d


def reads(seed_dir, ov_dir, rels):
    return {r: SL._canon(v, r) for r, v in SL.real_reads(seed_dir, ov_dir, rels).items()}


OLD = {
    "ticker_aliases.json": {"_note": "옛 설명", "exchange": {"upbit": {"XA": "XB"}}, "evidence": {"upbit:XA=XB": ["옛 근거"]}},
    "bridge_contracts.json": [A1, A2],
    "sale_contracts.json": {"auctions": {"base:" + A3: {"sym": "SALEX"}}, "cca_factories": [A1]},
}
NEW = {
    "ticker_aliases.json": {"_note": "새 설명", "exchange": {}, "evidence": {}, "_format": {"exchange": {}}},
    "bridge_contracts.json": [A1],
    "sale_contracts.json": {"auctions": {}, "cca_factories": [A1]},
}
CUR = {
    "ticker_aliases.json": {"exchange": {"bithumb": {"YA": "YB"}}},
    "bridge_contracts.json": [A4],
    "sale_contracts.json": {"auctions": {"arb:" + A2: {"sym": "SALEY"}}},
    "coverage/only_local.json": {"measured": {"x": 1}},
}
c1 = case("c1", OLD, NEW, CUR)
rels = sorted(set(OLD) | set(CUR))
now = reads(c1["old"], c1["out"], rels)
chk(now["ticker_aliases.json"]["exchange"] == {"upbit": {"XA": "XB"}, "bithumb": {"YA": "YB"}} and now["bridge_contracts.json"] == sorted([A1, A2, A4]),
    "[1] 지금 실효값 = 옛 seed + 이미 있는 덮어쓰기(실제 읽기)", now)
lost = {}
for rel in OLD:
    ov_old, _g = SL.overlay(NEW[rel], OLD[rel], rel)
    merged = seeds.seed_merge(NEW[rel], ov_old, rel) if ov_old is not None else NEW[rel]
    if SL._canon(merged, rel) != now[rel]:
        lost[rel] = True
chk(sorted(lost) == ["bridge_contracts.json", "sale_contracts.json", "ticker_aliases.json"], "[1] 옛 판 계산이면 잃는 값이 실제로 있음(고친 이유 재현)", lost)
todo, bad, fresh = SL.plan(SL.read_tree(c1["old"], "o"), SL.read_tree(c1["new"], "n"), SL.read_tree(c1["out"], "c"))
chk(bad == [] and fresh == [] and "coverage/only_local.json" not in todo, "[1] 계획 = 어긋남 0 · 덮어쓰기에만 있는 파일은 손대지 않음", (bad, sorted(todo)))
ta = (todo.get("ticker_aliases.json") or {}).get("exchange") or {}
chk(ta.get("bithumb") == {"YA": "YB"} and ta.get("upbit") == {"XA": "XB"} and list(ta)[:1] == ["bithumb"],
    "[1] 이미 있는 칸 그대로 · 모자란 칸만 뒤에 더함", ta)
chk(todo.get("bridge_contracts.json") == [A4, A2], "[1] 집합 목록 = 이미 있는 차례 뒤에 새 값", todo.get("bridge_contracts.json"))

before = tree(c1["st"])
rc, out = run("--old", c1["old"], "--new", c1["new"], "--out", c1["out"])
chk(rc == 0 and "(계획)" in out and tree(c1["st"]) == before and not os.path.exists(os.path.join(c1["st"], "backups")),
    "[2] --apply 없음 = 쓰기 0 · 백업 0", (rc, out))

rc, out = run("--old", c1["old"], "--new", c1["new"], "--out", c1["out"], "--apply")
bks = os.listdir(os.path.join(c1["st"], "backups"))
chk(rc == 0 and len(bks) == 1 and bks[0].startswith("seed_local_"), "[3] 적용 rc 0 · 기본 백업 자리 = <state>/backups/seed_local_<시각>", (rc, out, bks))
chk(tree(os.path.join(c1["st"], "backups", bks[0])) == {k[len("seed_local/"):]: v for k, v in before.items()},
    "[3] 백업 = 쓰기 전 덮어쓰기 폴더 통째(내용 같음)")
chk(reads(c1["new"], c1["out"], rels) == now and reads(c1["old"], c1["out"], rels) == now,
    "[3] 쓴 뒤 실제 읽기 = 지금(새 seed · 옛 seed 둘 다 — 배포 차례 사이에도 같음)")
chk(oct(os.stat(os.path.join(c1["out"], "ticker_aliases.json")).st_mode & 0o777) == "0o600", "[3] 쓴 파일 0600")
chk(tree(c1["out"])["coverage/only_local.json".replace("/", os.sep)] == before[os.path.join("seed_local", "coverage", "only_local.json")],
    "[3] 덮어쓰기에만 있는 파일 바이트 그대로")
rc, out = run("--old", c1["old"], "--new", c1["new"], "--out", c1["out"], "--apply")
chk(rc == 0 and "바꿀 덮어쓰기 없음" in out and len(os.listdir(os.path.join(c1["st"], "backups"))) == 1, "[3] 다시 돌리면 바꿀 것 없음(백업도 안 늘어남)", out)

c4 = case("c4", OLD, NEW, CUR)
put(c4["out"], "ticker_aliases.json", "{깨진")
before = tree(c4["st"])
rc, out = run("--old", c4["old"], "--new", c4["new"], "--out", c4["out"], "--apply")
chk(rc == 2 and "손상" in out and tree(c4["st"]) == before, "[4] 이미 있는 덮어쓰기 손상 = rc 2 · 쓰기 0", (rc, out))
c5 = case("c5", {"bridge_contracts.json": [A1, A2]}, {"bridge_contracts.json": [A1, A3]}, {})
rc, out = run("--old", c5["old"], "--new", c5["new"], "--out", c5["out"], "--apply")
chk(rc == 2 and "bridge_contracts.json" in out and os.listdir(c5["out"]) == [], "[4] 새 seed 가 집합에 값을 더함(지울 수 없음) = rc 2 · 쓰기 0", (rc, out))
c6 = case("c6", {"lp_managers.json": {"a": 1}}, {"lp_managers.json": {"a": 1, "b": 2}}, {"lp_managers.json": {"c": 3}})
before = tree(c6["st"])
rc, out = run("--old", c6["old"], "--new", c6["new"], "--out", c6["out"], "--apply")
chk(rc == 2 and "지울 칸" in out and tree(c6["st"]) == before, "[4] 새 seed 에만 있는 칸 = rc 2 · 쓰기 0", (rc, out))
c7 = case("c7", OLD, NEW, CUR)
os.makedirs(os.path.join(c7["st"], "bk_here"))
before = tree(c7["st"])
rc, out = run("--old", c7["old"], "--new", c7["new"], "--out", c7["out"], "--apply", "--backup", os.path.join(c7["st"], "bk_here"))
chk(rc == 2 and "백업 자리가 이미 있음" in out and tree(c7["st"]) == before, "[4] 백업 자리가 이미 있음 = rc 2 · 쓰기 0", (rc, out))

AP_OLD = {"exchanges": [{"id": "ex1", "lim": 5}, {"id": "ex2", "lim": 7}]}
AP_NEW = {"exchanges": [{"id": "ex1", "lim": 5}, {"id": "ex2", "lim": 9}]}
c8 = case("c8", {"coverage/api_limits.json": AP_OLD, "debt_first_seen_t.json": {"bin": {"Z": {"ts": 1}}}},
          {"coverage/api_limits.json": AP_NEW, "debt_first_seen_t.json": {"_note": "형식"}, "new_only.json": {"k": 1}}, None)
rc, out = run("--old", c8["old"], "--new", c8["new"], "--out", c8["out"], "--apply")
r8 = ["coverage/api_limits.json", "debt_first_seen_t.json"]
chk(rc == 0 and reads(c8["new"], c8["out"], r8) == reads(c8["old"], None, r8), "[5] id 레코드 목록 · 덮어쓰기 폴더 없음(처음) → 실제 읽기 같음", (rc, out))
chk("new_only.json" in out and "참고" in out and not os.path.exists(os.path.join(c8["out"], "new_only.json")), "[5] 새 seed 에만 있는 파일 = 참고 줄만(덮어쓰기 안 만듦)", out)
c9 = case("c9", {"coverage/evm_chains.json": {"chains": {"x": {"a": 1, "note": "옛"}}}},
          {"coverage/evm_chains.json": {"chains": {"x": {"note": "새"}}}, "bridge_contracts.json": [A1, A2]},
          {"bridge_contracts.json": [A3]})
r9 = ["coverage/evm_chains.json", "bridge_contracts.json"]
full_old = os.path.join(T.TMP, "c9", "full_old", "seed")
os.makedirs(os.path.join(full_old, "coverage"))
put(full_old, "coverage/evm_chains.json", {"chains": {"x": {"a": 1, "note": "옛"}}})
put(full_old, "bridge_contracts.json", [A1, A2])
before9 = reads(full_old, c9["out"], r9)
rc, out = run("--old", c9["old"], "--new", c9["new"], "--out", c9["out"], "--apply")
chk(rc == 0 and reads(c9["new"], c9["out"], r9) == before9 and json.load(open(os.path.join(c9["out"], "bridge_contracts.json"))) == [A3],
    "[5] --old = 바뀐 파일만(배포 백업 꼴) → 안 바뀐 파일 = 새 seed 와 같다고 봄 · 그 덮어쓰기 그대로 · 실제 읽기 같음", (rc, out))
chk(not os.path.exists(os.path.join(c8["st"], "backups")), "[5] 처음(덮어쓰기 폴더 없음)이면 백업할 것 없음")
chk(paths.STATE_DIR != c8["st"] and "seed_local" not in str(paths.STATE_DIR), "[5] 실제 읽기 뒤 paths.STATE_DIR 원래대로")

shutil.rmtree(os.path.join(T.TMP, "c1"), ignore_errors=True)
T.finish()

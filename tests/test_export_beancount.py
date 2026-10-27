#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
from decimal import Decimal  # noqa: E402

chk = T.chk
TOOL = os.path.join(T.ROOT, "tools", "export_beancount.py")
_sp = importlib.util.spec_from_file_location("export_beancount", TOOL)
X = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(X)
SD = os.path.join(T.TMP, "bean")
os.makedirs(SD, exist_ok=True)
CM_RE = re.compile(r"^[A-Z][A-Z0-9'._-]{0,22}[A-Z0-9]$")
AC_RE = re.compile(r"^(Assets|Liabilities|Equity|Income|Expenses)(:[A-Z0-9][A-Za-z0-9-]*)+$")

ld = X.demo_ledger()
text, st, acct, cm = X.export(ld)
r = X.check_text(text)
chk(not r["bad"], "B1 거래마다 분개 합 0(금액 빈 줄 ≤ 1)", r["bad"][:5])
chk(r["tx"] == st["tx"] == len({(p[1], p[2], p[3]) for p in ld["postings"]}), "B1 거래 수 = 원장 출처 수", (r["tx"], st["tx"]))
diff = X.positions_diff(ld, r["units"], acct, cm)
chk(not diff, "B1 계정별 최종 수량 == positions.qty_norm", diff[:5])
chk(r["balance"] == r["balance_days"] == 0 and " balance " not in text, "B1 balance 줄 0 = 대조 성공 칸 기록 0(검사 안 한 칸을 단언하지 않음)", r["balance"])
chk('option "booking_method" "NONE"' in text, "B1 로트를 모든 줄에 적고 booking NONE(이동평균 booking 없음 — 맞춰 보기만)")
chk(re.search(r"  Assets:Wallet:Eth:\S+  1 ETH \{0 USD, \d{4}-\d\d-\d\d\}\n    cost: \"unknown\"", text) is not None,
    "B1 기초 잔고(원가 모름) = {0 USD} + cost \"unknown\" — 숫자를 지어내지 않음")
chk(re.search(r"-50 TKJ \{0 USD, [\d-]+\} @ 0\.5 USD\n    cost: \"unknown\"\n    shortfall: TRUE", text) is not None and st["shortfall"] == 1,
    "B1 가진 로트보다 많이 나감 = {0 USD} 음수 로트 + shortfall 메타(수량은 원장 그대로)")
chk(all(not re.match(r"^  Income:PnL:Realized\s+\S", ln) for ln in text.split("\n")) and text.count("  Income:PnL:Realized\n") == 4,
    "B1 실현 손익 금액은 안 적음(금액 빈 줄 — Beancount 가 채움)")
chk("  Expenses:Fee:Withdraw  4 USD" in text and "  Expenses:Fee:Gas  3 USD" in text and "  Expenses:Fee:Transfer  1 USD" in text,
    "B1 수수료 = 시가 있으면 시가 · 없으면 로트 원가 · 같은 출처 이동 수량 차이 = Transfer")
chk("  Equity:Transfer-Out  0.8 ETH-5 {2000 USD," in text and re.search(r"  Assets:Wallet:Eth:\S+  0\.8 ETH \{0 USD, [\d-]+\}\n    cost: \"unknown\"", text) is not None
    and st["unknown_in"] == 1 and "Transit" not in text,
    "B1 출처가 다른 출금 → 도착 = 짝 안 지음(나간 로트 Equity:Transfer-Out · 도착 = 원가 모름 · 자산 계정에 중간 잔고 없음)")
chk("why: \"EX_ADJUST\"" in text and "  Equity:Reconciliation\n" in text, "B1 대사 조정 = Equity:Reconciliation + why")
chk(all(AC_RE.match(a) for a in re.findall(r"^\S+ open (\S+)$", text, re.M)), "B1 계정 이름 = Beancount 규칙")
chk(text.count(" price ") == 2, "B1 price = snapshots.px_usd 날·그룹별")

import db as dbm  # noqa: E402

dbp = os.path.join(SD, "ledger.db")
c = sqlite3.connect(dbp)
for s in dbm.DDL:
    c.execute(s)
c.executemany("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,?)", [(g, n, d) for g, (n, d) in ld["groups"].items()])
c.executemany("INSERT INTO assets (asset_id, group_id, decimals, kind, chain, address, symbol) VALUES (?,?,?,?,?,?,?)", [(k,) + v for k, v in ld["assets"].items()])
c.executemany("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, leg_kind, event,"
              " classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)", ld["postings"])
c.executemany("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", [(g, loc, format(q, "f")) for (g, loc), q in ld["positions"].items()])
c.executemany("INSERT INTO snapshots (day, group_id, location, qty_norm, px_usd) VALUES (?,?,'x','0',?)", [(d, g, px) for (d, g), px in ld["prices"].items()])
c.commit()
c.close()
def _fp():
    return [hashlib.sha256(open(f, "rb").read()).hexdigest() if os.path.exists(f) and (f == dbp or os.path.getsize(f) > 0) else None
            for f in (dbp, dbp + "-wal")]


h0 = _fp()
outp = os.path.join(SD, "o.beancount")
p = subprocess.run([sys.executable, "-I", TOOL, "--ledger", dbp, "--check", "--out", outp], capture_output=True, text=True, timeout=120)
chk(p.returncode == 0 and "check_bad 0" in p.stderr and "positions_diff 0" in p.stderr, "B2 sqlite 원장 → 종료 0 · --check 통과", (p.returncode, p.stderr[-400:]))
chk(_fp() == h0, "B2 원장 파일·-wal 바이트 무변(읽기 전용 연결)")
c2 = X.open_ro(dbp)
ld2 = X.load_ledger(c2)
c2.close()
t2 = X.export(ld2)[0]
chk(open(outp, encoding="utf-8").read() == t2 and t2 == X.export(ld)[0], "B2 같은 원장 = 같은 글(sqlite 읽기 = 합성 dict)")
lnk = os.path.join(SD, "lnk.db")
os.symlink(dbp, lnk)
rcs = [subprocess.run([sys.executable, "-I", TOOL, "--ledger", dbp, "--out", o], capture_output=True, text=True, timeout=60).returncode
       for o in (dbp, dbp + "-wal", lnk)]
rcs += [subprocess.run([sys.executable, "-I", TOOL, "--demo", "--ledger", dbp, "--out", dbp], capture_output=True, text=True, timeout=60).returncode,
        subprocess.run([sys.executable, "-I", TOOL, "--ledger", lnk, "--out", dbp + "-wal"], capture_output=True, text=True, timeout=60).returncode]
chk(rcs == [2, 2, 2, 2, 2] and _fp() == h0, "B2 --out 이 원장·-wal·심볼릭 링크(--demo 여도 · 원장 경로가 링크여도) = 거부(종료 2 · 원장 무변)", rcs)
p = subprocess.run([sys.executable, "-I", TOOL, "--ledger", os.path.join(SD, "없음.db")], capture_output=True, text=True, timeout=60)
chk(p.returncode == 2 and not os.path.exists(os.path.join(SD, "없음.db")), "B2 원장 없음 = 종료 2 · 파일 만들지 않음", (p.returncode, p.stderr[-200:]))
st_dir = os.path.join(os.environ["TJ_BASE"], "state")
os.makedirs(os.path.join(st_dir, "sub"), exist_ok=True)
auth = os.path.join(st_dir, "auth.json")
with open(auth, "w", encoding="utf-8") as f:
    f.write('{"k": "v"}')
rcs = [subprocess.run([sys.executable, "-I", TOOL] + args, capture_output=True, text=True, timeout=60).returncode
       for args in (["--demo", "--out", auth], ["--ledger", dbp, "--out", os.path.join(st_dir, "ledger.db")],
                    ["--demo", "--out", os.path.join(st_dir, "sub", "x.beancount")])]
chk(rcs == [2, 2, 2] and open(auth, encoding="utf-8").read() == '{"k": "v"}' and not os.path.exists(os.path.join(st_dir, "ledger.db"))
    and not os.path.exists(os.path.join(st_dir, "sub", "x.beancount")), "B2 --out 이 기본 state 폴더 안(--demo·다른 --ledger 여도 · 하위 폴더) = 거부 · 파일 무변", rcs)
alt = os.path.join(os.environ["TJ_BASE"], "STATE")
if os.path.isdir(alt):
    p = subprocess.run([sys.executable, "-I", TOOL, "--demo", "--out", os.path.join(alt, "auth.json")], capture_output=True, text=True, timeout=60)
    chk(p.returncode == 2 and open(auth, encoding="utf-8").read() == '{"k": "v"}', "B2 --out 이 글자 꼴만 다른 state 폴더(대소문자 무시) = 거부", p.returncode)
o600 = os.path.join(SD, "mode.beancount")
p = subprocess.run([sys.executable, "-I", TOOL, "--demo", "--out", o600], capture_output=True, text=True, timeout=60)
chk(p.returncode == 0 and (os.name != "posix" or os.stat(o600).st_mode & 0o777 == 0o600), "B2 새 출력 파일 = 0600(본인만)",
    (p.returncode, oct(os.stat(o600).st_mode) if os.path.exists(o600) else None))

gs = {1: ("USDT#eth:0xa", 18), 2: ("USDT", 18), 3: ("ＵＳＤＴ#bsc:0xb", 18), 4: ("1INCH#eth:0xc", 18), 5: ("", 18), 6: ("💲#x", 18), 7: ("USD", 18),
      8: ("A" * 40 + "#y", 18), 9: ("ETH.", 18), 10: ("usdt#sol:z", 18)}
nm = X.commodity_names(gs)
chk(all(CM_RE.match(v) for v in nm.values()) and len(set(nm.values())) == len(nm), "B3 상품 이름 = 규칙 · 서로 다름", nm)
chk(nm[2] == "USDT" and nm[1] == "USDT-1" and nm[3] == "USDT-3" and nm[10] == "USDT-10", "B3 겹치면 -<group_id> · '#' 없는 이름이 맨 이름", nm)
chk(X.commodity_names({1: ("TRUE#x", 18), 2: ("NULL", 18)}) == {1: "TRUE-1", 2: "NULL-2"}, "B3 Beancount 예약 낱말(TRUE·FALSE·NULL) 피함")
chk(nm[4] == "X1INCH" and nm[5] == "G5" and nm[6] == "G6" and nm[7] == "USD-7" and nm[9] == "ETH", "B3 숫자 시작 = X · 빈 이름 = G<id> · 원가 통화 USD 피함", nm)
locs = ["wallet:eth:0x1234567890aa", "wallet:eth:0x1234567890bb", "wallet:sol:abcDEF", "exchange:upbit", "lp:arbitrum:0xmgr:?who", "out:base:0x99"]
am = X.account_names(locs)
chk(len(set(am.values())) == len(locs) and all(AC_RE.match(a) for a in am.values()), "B3 주소 앞 8자가 겹쳐도 서로 다른 계정 · 규칙", am)
chk(am["wallet:sol:abcDEF"] == "Assets:Wallet:Sol:XabcDEF" and am["exchange:upbit"] == "Assets:Exchange:Upbit" and am["out:base:0x99"].startswith("Equity:External:Base:"),
    "B3 소문자 시작 주소 = X 접두 · 거래소 · 바깥 전송", am)

bad1 = text.replace("  Expenses:Fee:Withdraw  4 USD", "  Expenses:Fee:Withdraw  5 USD", 1)
chk(any("분개 합" in b for b in X.check_text(bad1)["bad"]), "B5 숫자 하나 바꿈 = 분개 합 ≠ 0")
bad2 = text.replace("  Expenses:Fee:Gas  3 USD", "  Expenses:Fee:Gas", 1)
chk(any("분개 합" in b for b in X.check_text(bad2)["bad"]), "B5 금액 빈 줄 둘 = 실패")
bad3 = text.replace("open Expenses:Fee:Gas\n", "open Expenses:Fee:GasX\n", 1)
chk(any("open 앞 사용" in b for b in X.check_text(bad3)["bad"]), "B5 open 없는 계정 = 실패")
ld5 = dict(ld, positions={**ld["positions"], (2, "exchange:upbit"): Decimal("9")})
chk(len(X.positions_diff(ld5, r["units"], acct, cm)) == 1, "B5 positions 와 다르면 잡음")

E = 10 ** 18
lb = {"groups": {1: ("BTC", 18), 2: ("USDT", 18)}, "assets": {1: (1, 18, "exchange_currency", None, None, "BTC"), 2: (2, 18, "exchange_currency", None, None, "USDT")},
      "positions": {}, "prices": {}, "postings": [
          (1, "exchange", "x:trade", "a", 0, 1767225600, 1, "exchange:x", str(E), "10000", "acq", "EXF_BUY"),
          (2, "exchange", "x:trade", "b", 0, 1767312000, 1, "exchange:x", str(E), "20000", "acq", "EXF_BUY"),
          (3, "exchange", "x:trade", "c", 0, 1767398400, 1, "exchange:x", str(-E), "30000", "disp", "EXF_SELL"),
          (4, "exchange", "x:trade", "c", 1, 1767398400, 2, "exchange:x", str(30000 * E), "30000", "acq", "EXF_SELL")]}
lb["positions"] = {(1, "exchange:x"): Decimal(1), (2, "exchange:x"): Decimal(30000)}
tb, sb, ab, cb = X.export(lb)
chk(re.search(r"Assets:Exchange:X  -1 BTC \{10000 USD, [\d-]+\} @ 30000 USD", tb) is not None and not X.check_text(tb)["bad"]
    and not X.positions_diff(lb, X.check_text(tb)["units"], ab, cb), "B6 선입선출 = 먼저 산 10,000 로트 · 분개 합 0 · positions 같음")

lr = {"groups": {1: ("KRW#x", 18)}, "assets": {1: (1, 0, "exchange_currency", None, None, "KRW")}, "prices": {}, "postings": [
          (1, "exchange", "x:recon", "r", 0, 1767398400, 1, "exchange:x", "100", None, "opening", "EXF_ADJUST"),
          (2, "exchange", "x:recon", "r", 1, 1767225600, 1, "exchange:x", "50", None, "opening", "EXF_ADJUST"),
          (3, "exchange", "x:trade", "s", 0, 1767312000, 1, "exchange:x", "-10", "7", "disp", "EXF_SELL")]}
lr["postings"].sort(key=lambda p: (p[5], p[0]))
lr["positions"] = {(1, "exchange:x"): Decimal(140)}
tr = X.export(lr)[0]
cr = X.check_text(tr)
chk(not cr["bad"] and re.search(r"^%s open " % X.day_of(1767225600), tr, re.M) and re.search(r"^%s \* \"EXF_ADJUST\"" % X.day_of(1767225600), tr, re.M),
    "B8 소급 보정(순번 1 이 더 이름) = 거래 날짜·open 이 가장 이른 레그 · open 앞 사용 0", cr["bad"][:3])

lp9 = {"groups": {1: ("TKJ#x", 18)}, "assets": {1: (1, 8, "token", "eth", "0xt", "TKJ")}, "prices": {}, "postings": [
          (1, "chain_tx", "eth", "a", 0, 1767225600, 1, "wallet:eth:0xa1", str(1000 * 10 ** 8), "1000", "acq", "TRANSFER_IN"),
          (2, "chain_tx", "eth", "b", 0, 1767225660, 1, "wallet:eth:0xa1", "100000001", "1.2345678901234567", "acq", "TRANSFER_IN"),
          (3, "chain_tx", "eth", "c", 0, 1767312000, 1, "wallet:eth:0xa1", str(-(1000 * 10 ** 8 + 100000001)), None, "move_out", "TRANSFER_SELF"),
          (4, "chain_tx", "eth", "c", 1, 1767312000, 1, "wallet:eth:0xb2", str(1000 * 10 ** 8 + 100000001), None, "move_in", "TRANSFER_SELF")]}
lp9["positions"] = {(1, "wallet:eth:0xb2"): Decimal("1001.00000001")}
t9 = X.export(lp9)[0]
c9 = X.check_text(t9)
chk(not c9["bad"] and 'option "inferred_tolerance_default" "USD:0.0000001"' in t9, "B9 28자리 합 찌꺼기 = USD 허용오차 option 안(자체 검사도 28자리로 셈)", c9["bad"][:3])
_tol, X.USD_TOL = X.USD_TOL, Decimal(0)
c9z = X.check_text(t9)
X.USD_TOL = _tol
chk(any("28자리" in b for b in c9z["bad"]), "B9 RED: 허용오차 0 이면 28자리 합 찌꺼기를 잡음(이 꼴이 실제로 남는다는 증거)", c9z["bad"][:2])

bc = shutil.which("bean-check")
if bc:
    dp = os.path.join(SD, "demo.beancount")
    with open(dp, "w", encoding="utf-8") as f:
        f.write(text)
    p = subprocess.run([bc, dp], capture_output=True, text=True, timeout=300)
    chk(p.returncode == 0, "B7 bean-check 합성 원장 = 종료 0", p.stdout[-800:] + p.stderr[-800:])
else:
    print("  (B7 건너뜀 — bean-check 없음 · 설치하지 않음)")

T.finish()

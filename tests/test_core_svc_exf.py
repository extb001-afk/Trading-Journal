#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import core_svc  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
SV = core_svc.ExfService
SVD = vars(SV)
EXF6 = ("ExfMixin", "ExfLateMixin", "ExfFutMixin", "FillsMixin", "UpbitMixin", "UpbitReconMixin")

C = core.Core(config.load_config())
S = C.svc_exf

ro_err = "대입됨"
try:
    S.conn = None
except AttributeError:
    ro_err = "AttributeError"
PROPS = ("conn", "cfg", "px", "recon_months", "_drain_at")
chk(ro_err == "AttributeError" and all(isinstance(SVD[n], property) and SVD[n].fset is None and SVD[n].fdel is None for n in PROPS),
    "S1 포트 속성 5 = 읽기 전용(setter 없음 · 서비스 몸통이 포트에 대입하면 AttributeError)", ro_err)
chk(S.conn is C.conn and S.cfg is C.cfg and S.px is C.px and S.recon_months == C.recon_months,
    "S1 포트 속성 = core 의 같은 객체(늦게 읽음)")
aid = C.asset_id("native", "eth", None, "ETH", 18)
chk(S._meta_get("exf_wd_fee_since") == C._meta_get("exf_wd_fee_since") and S.asset_id("native", "eth", None, "ETH", 18) == aid
    and S._win_t0() == C._win_t0(), "S1 위임 메서드 = core 쪽과 같은 값(_meta_get · asset_id · _win_t0)")
with open(os.path.join(T.HERE, "arch_baseline", "core_bounds.json"), encoding="utf-8") as fh:
    tab = json.load(fh)
chk(sorted(core_svc.EXF_PORT) == sorted(tab["ports"].get("ExfService", [])) and len(core_svc.EXF_PORT) == 15
    and all(n in SVD for n in core_svc.EXF_PORT),
    "S1 EXF_PORT(메서드 10 + 속성 5) = core_bounds 표 ports · 이름마다 ExfService 몸통에 명시", sorted(core_svc.EXF_PORT))

mro = [k.__name__ for k in core.Core.__mro__]
chk(not set(EXF6) & set(mro) and all(n in [k.__name__ for k in SV.mro()] for n in EXF6),
    "S2 Core 바탕에 EXF 6클래스 없음 · ExfService 바탕에 6 모두", mro)
_names = {"_consume_ex", "exf_recon_pass", "EX_RECON_TOL", "_quote_usd"}
chk(not (set(dir(core.Core)) & (_names | {"settle_planner"})) and _names <= set(dir(SV)),
    "S2 EXF 이름 = Core 에 없음(옛 이름 대입은 효과 없이 지나가므로 svc_names 가 0 강제) · 서비스 클래스에 있음")
since = int(C.conn.execute("SELECT v FROM meta WHERE k='exf_wd_fee_since'").fetchone()["v"])
chk(isinstance(S, SV) and vars(S)["core"] is C and S.wd_fee_since == since and "wd_fee_since" not in vars(C),
    "S2 c.svc_exf = ExfService(core = c) · wd_fee_since = 원장 meta 값 · 소유 = 서비스(Core __dict__ 에 없음)")

import ast  # noqa: E402
with open(os.path.join(T.SRC, "core.py"), encoding="utf-8") as fh:
    _ct = ast.parse(fh.read())
_init = [f for n in _ct.body if isinstance(n, ast.ClassDef) and n.name == "Core" for f in n.body
         if isinstance(f, ast.FunctionDef) and f.name == "__init__"][0]
_exf = {n for k in SV.mro()[1:] if k.__name__ in EXF6 for n in vars(k)}
_use = [(x.lineno, x.attr) for x in ast.walk(_init) if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
        and x.value.id == "self" and (x.attr in _exf or x.attr == "svc_exf")]
chk(len(_use) == 1 and _use[0][1] == "svc_exf", "S2 Core.__init__ = 서비스 생성 줄 하나만(그 앞뒤 EXF 이름 부르기 0)", _use)

with open(os.path.join(T.SRC, "core_pricing.py"), encoding="utf-8") as fh:
    _pt = ast.parse(fh.read())
_sv = [(x.lineno, x.attr) for x in ast.walk(_pt) if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Attribute)
       and x.value.attr == "svc_exf" and isinstance(x.value.value, ast.Name) and x.value.value.id == "self"]
chk(len(_sv) == 3 and all(n in dir(SV) for _l, n in _sv), "S6 core_pricing 의 self.svc_exf.N 3자리 = 서비스 이름", _sv)
t6 = int(time.time()) - 3600
C.px.d["fx"][str((t6 * 1000 // 60_000) * 60_000)] = 1380.0
o6 = {"uuid": "u-s6", "market": "USDT-ETH", "side": "bid", "state": "done", "executed_volume": "1", "executed_funds": "3000",
      "paid_fee": "0", "price": "3000", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t6)), "trades_count": 1}
S._consume_fills({"orders": [o6]})
C.conn.execute("UPDATE postings SET cost_usd=NULL, cost_krw=NULL WHERE source_ns='upbit:order'")
C.conn.commit()
n6 = C.svc_price._price_upbit_quote_fills(10)
r6 = [tuple(r) for r in C.conn.execute("SELECT leg_seq, cost_usd, cost_krw FROM postings WHERE source_ns='upbit:order' ORDER BY leg_seq")]
chk(n6 == 1 and r6 == [(0, "3000.0", repr(3000.0 * 1380.0)), (1, "3000.0", repr(3000.0 * 1380.0))],
    "S6 PricingMixin._price_upbit_quote_fills = svc_exf._upbit_quote_fill_legs·_quote_usd 로 두 레그 원가 소급(USDT 액면 · 합성 환율)", (n6, r6))
C.conn.execute("DELETE FROM postings WHERE source_ns='upbit:order'")
C.conn.commit()

b = object.__new__(core.Core)
sb = core_svc.attach(b).svc_exf
chk(isinstance(sb, SV) and vars(sb) == {"core": b}
    and getattr(sb, "_drain_at", 0) == 0 and set(vars(b)) == {"svc_exf", "svc_recon", "svc_price"},
    "S3 attach = 서비스만 붙임 · wd_fee_since·_drain_at 없음 → getattr 기본 0(지금과 같음)", sorted(vars(b)))
b._drain_at = 123.0
chk(getattr(sb, "_drain_at", 0) == 123.0, "S3 _drain_at = core 에 생기면 그 값(포트가 늦게 읽음)")

C.conn.commit()
DB = paths.DB_PATH


def ledger_sig():
    with open(DB, "rb") as fh:
        h = hashlib.sha256(fh.read()).hexdigest()
    k = sqlite3.connect(DB)
    try:
        ddl = sorted(tuple(r) for r in k.execute("SELECT type, name, sql FROM sqlite_master"))
        rows = {t: k.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0] for (t,) in k.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        k.close()
    return h, ddl, rows


C.conn.close()
sig0 = ledger_sig()
ro = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
ro.row_factory = sqlite3.Row
cfg = config.load_config()
P = core_svc.exf_settle_planner(core.Core, cfg, ro)
res = (P._exf_ext_done(None), P._exf_ext_settle_plan("binance", {since}))
chk(isinstance(P, SV) and type(vars(P)["core"]) is core.Core and set(vars(vars(P)["core"])) == {"cfg", "conn", "recon_months"}
    and P.recon_months == 5.0 and P.conn is ro, "S4 계획기 = ExfService · 맨 core 의 __dict__ = cfg·conn·recon_months(옛 settle_planner 와 같은 식)",
    sorted(vars(vars(P)["core"])))
C2 = object.__new__(core.Core)
C2.cfg, C2.recon_months = cfg, 5.0
chk(P._win_t0() == core.Core._win_t0(C2), "S4 계획 메서드의 _win_t0 = 포트로 맨 Core 의 메서드(같은 값)")
chk(ro.total_changes == 0 and res[1] == [], "S4 계획 = 읽기 전용 연결 쓰기 0 · 빈 원장 = 계획 0", (ro.total_changes, res))
ro.close()
chk(ledger_sig() == sig0, "S4 계획기 = 원장 바이트·DDL·행 수 무변")

FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
with open(os.path.join(FAKE, "pm2"), "w") as fh:
    fh.write("#!/bin/sh\necho '[]'\n")
os.chmod(os.path.join(FAKE, "pm2"), 0o755)


def tool(name, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, "pm2"), PATH=FAKE + os.pathsep + env.get("PATH", ""), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", name)] + list(args), env=env, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


for name, args in (("repair_own_overlap.py", ["--force"]),):
    if not os.path.isfile(os.path.join(T.ROOT, "tools", name)):
        print("SKIP %s 없음(공개판 배치)" % name)
        continue
    rc, out = tool(name, *args)
    chk(rc == 0 and "Traceback" not in out and "AttributeError" not in out, f"S5 {name} 점검 = 정상 끝(맨 Core + attach)", (rc, out[-500:]))
    chk(ledger_sig() == sig0, f"S5 {name} 점검 = 원장 DDL·내용 무변(Core() 안 씀)")

T.finish()

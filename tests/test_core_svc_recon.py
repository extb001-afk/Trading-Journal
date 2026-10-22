#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config  # noqa: E402
import core  # noqa: E402
import core_common  # noqa: E402
import core_svc  # noqa: E402
import discopen  # noqa: E402

chk = T.chk
SV = core_svc.ReconService
SVD = vars(SV)
RECON2 = ("ReconMixin", "ProvMixin")

C = core.Core(config.load_config())
C.conn.commit()
S = C.svc_recon

ro_err = "대입됨"
try:
    S.conn = None
except AttributeError:
    ro_err = "AttributeError"
PROPS = ("cfg", "conn", "my_wallets", "sol_wallets", "chain_owners", "chain_readers", "native_sym", "wrapped", "reader", "sol_reader",
         "bsc_reader", "recon_months")
METHS = ("_inval_daily", "_meta_dec", "_meta_get", "_post_leg_strict", "_recon_view", "_recon_view_drop", "_win_t0", "asset_id", "_group_of")
chk(ro_err == "AttributeError" and all(isinstance(SVD[n], property) and SVD[n].fset is None and SVD[n].fdel is None for n in PROPS),
    "R1 포트 속성 12 = 읽기 전용(setter 없음 · 서비스 몸통이 포트에 대입하면 AttributeError)", ro_err)
chk(all(getattr(S, n) is getattr(C, n) for n in PROPS), "R1 포트 속성 = core 의 같은 객체(늦게 읽음 · _gate_reload 더하기가 core 에 닿음)")
aid = C.asset_id("native", "eth", None, "ETH", 18)
chk(S.asset_id("native", "eth", None, "ETH", 18) == aid and S._group_of(aid) == C._group_of(aid) and S._win_t0() == C._win_t0()
    and S._recon_view("eth") == C._recon_view("eth") and S._meta_get("schema_version") == C._meta_get("schema_version"),
    "R1 위임 메서드 = core 쪽과 같은 값(asset_id · _group_of · _win_t0 · _recon_view · _meta_get)")
_seen = []
C._inval_daily = lambda: _seen.append("inval")
S._inval_daily()
del C._inval_daily
chk(_seen == ["inval"], "R1 위임 = 부를 때 core 의 이름을 찾음(core 에 갈아 끼운 가짜가 먹음)", _seen)
with open(os.path.join(T.HERE, "arch_baseline", "core_bounds.json"), encoding="utf-8") as fh:
    tab = json.load(fh)
chk(sorted(core_svc.RECON_PORT) == sorted(tab["ports"].get("ReconService", [])) == sorted(PROPS + METHS) and len(core_svc.RECON_PORT) == 21
    and all(n in SVD for n in core_svc.RECON_PORT),
    "R1 RECON_PORT(메서드 9 + 속성 12) = core_bounds 표 ports · 이름마다 ReconService 몸통에 명시", sorted(core_svc.RECON_PORT))
cl = C.chain_readers
del C.chain_readers
chk(getattr(S, "chain_readers", None) is None and "chain_readers" not in vars(S),
    "R1 core 에 없는 포트 이름 = AttributeError → getattr(서비스, 이름, 기본값) 은 기본값(옛 __dict__.get 뜻)")
C.chain_readers = cl

mro = [k.__name__ for k in core.Core.__mro__]
chk(not set(RECON2) & set(mro) and all(n in [k.__name__ for k in SV.mro()] for n in RECON2),
    "R2 Core 바탕에 ReconMixin·ProvMixin 없음 · ReconService 바탕에 둘 다", mro)
_names = {"recon_pass", "prov_pass", "negabs_pass", "_scope_ready", "_disc_max_t", "PROV_PAR", "RECON_WAIT_SEC", "_prov_pack"}
chk(not (set(dir(core.Core)) & _names) and _names <= set(dir(SV)),
    "R2 RECON 이름 = Core 에 없음(옛 이름 대입은 효과 없이 지나가므로 svc_names 가 0 강제) · 서비스 클래스에 있음")
chk(isinstance(S, SV) and vars(S)["core"] is C and vars(S)["_last_recon"] == 0.0 and "_last_recon" not in vars(C),
    "R2 c.svc_recon = ReconService(core = c) · _last_recon = 0.0 소유 = 서비스(Core __dict__ 에 없음)", sorted(vars(S)))
with open(os.path.join(T.SRC, "core.py"), encoding="utf-8") as fh:
    _ct = ast.parse(fh.read())
_init = [f for n in _ct.body if isinstance(n, ast.ClassDef) and n.name == "Core" for f in n.body
         if isinstance(f, ast.FunctionDef) and f.name == "__init__"][0]
_rec = {n for k in SV.mro()[1:] if k.__name__ in RECON2 for n in vars(k)}
_use = [(x.lineno, x.attr) for x in ast.walk(_init) if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
        and x.value.id == "self" and (x.attr in _rec or x.attr == "svc_recon")]
chk(len(_use) == 1 and _use[0][1] == "svc_recon", "R2 Core.__init__ = 서비스 생성 줄 하나만(그 앞뒤 RECON 이름 부르기 0)", _use)

b = object.__new__(core.Core)
sb = core_svc.attach(b).svc_recon
chk(isinstance(sb, SV) and vars(sb) == {"core": b, "_last_recon": 0.0} and set(vars(b)) == {"svc_exf", "svc_recon", "svc_price"},
    "R3 attach = svc_recon 도 붙임 · _last_recon 0.0 · core 상태 안 읽음", sorted(vars(sb)))
try:
    sb.conn
    r3 = "읽힘"
except AttributeError:
    r3 = "AttributeError"
b.conn = C.conn
chk(r3 == "AttributeError" and sb.conn is C.conn, "R3 맨 Core 의 포트 = core 에 생기면 그 값(늦게 읽음 · 생성 때 안 읽음)", r3)

import importlib.util  # noqa: E402
_sp = importlib.util.spec_from_file_location("rb2", os.path.join(T.ROOT, "tools", "rebuild2.py"))
rebuild2 = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(rebuild2)
CV = core_common.CLASSIFIER_VER
chk(core_svc.CLASSIFIER_VER == CV != 3 and discopen._ver(S) == CV and discopen._ver(C.svc_exf) == CV,
    "R4 discopen._ver(서비스 2 — ExfService·ReconService) = core_common.CLASSIFIER_VER(type(x).__module__ = core_svc)", discopen._ver(S))
chk(rebuild2.core_mod_ver(C) == CV and type(C).__module__ == "core", "R4 rebuild2.core_mod_ver(Core 인스턴스) = 같은 값(무변 · 모듈 core)")

T.finish()

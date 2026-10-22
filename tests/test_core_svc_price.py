#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config  # noqa: E402
import core  # noqa: E402
import core_pricing  # noqa: E402
import core_svc  # noqa: E402

chk = T.chk
SV = core_svc.PriceService
SVD = vars(SV)

C = core.Core(config.load_config())
C.conn.commit()
S = C.svc_price

PROPS = ("cfg", "conn", "px", "native_sym", "wrapped", "svc_exf")
METHS = ("_meta_get", "_norm", "_leg_sql")
errs = []
for _fn in (lambda: S.__setattr__("conn", None), lambda: S.__setattr__("px", None), lambda: S.__setattr__("svc_exf", None)):
    try:
        _fn()
        errs.append("대입됨")
    except AttributeError:
        errs.append("AttributeError")
chk(errs == ["AttributeError"] * 3 and all(isinstance(SVD[n], property) and SVD[n].fset is None and SVD[n].fdel is None for n in PROPS),
    "P1 포트 속성 6 = 읽기 전용(setter 없음 · 서비스 몸통이 포트에 대입하면 AttributeError)", errs)
chk(all(getattr(S, n) is getattr(C, n) for n in PROPS), "P1 포트 속성 = core 의 같은 객체(늦게 읽음 · svc_exf = core 의 ExfService)")
aid = C.asset_id("native", "eth", None, "ETH", 18)
chk(S._norm(aid, 10 ** 18) == C._norm(aid, 10 ** 18) and S._meta_get("schema_version") == C._meta_get("schema_version"),
    "P1 위임 메서드 = core 쪽과 같은 값(_norm · _meta_get)", S._norm(aid, 10 ** 18))
_seen = []
C._norm = lambda a, v: _seen.append((a, v)) or "7"
_r = S._norm(aid, 3)
del C._norm
chk(_seen == [(aid, 3)] and _r == "7", "P1 위임 = 부를 때 core 의 이름을 찾음(core 에 갈아 끼운 가짜가 먹음)", _seen)
with open(os.path.join(T.HERE, "arch_baseline", "core_bounds.json"), encoding="utf-8") as fh:
    tab = json.load(fh)
chk(sorted(core_svc.PRICE_PORT) == sorted(tab["ports"].get("PriceService", [])) == sorted(PROPS + METHS) and len(core_svc.PRICE_PORT) == 9
    and all(n in SVD for n in core_svc.PRICE_PORT) and tab["runtime"].get("PRICING") == "PriceService",
    "P1 PRICE_PORT(메서드 3 + 속성 6) = core_bounds 표 ports · 이름마다 PriceService 몸통에 명시 · runtime PRICING = PriceService",
    sorted(core_svc.PRICE_PORT))

mro = [k.__name__ for k in core.Core.__mro__]
chk("PricingMixin" not in mro and "PricingMixin" in [k.__name__ for k in SV.mro()], "P2 Core 바탕에 PricingMixin 없음 · PriceService 바탕에 있음", mro)
_names = {"price_pass", "_price_tx", "krw_fill_pass", "_out_px_band_fix_once", "_leg_px", "_is_stable_aid", "OUT_PX_BAND", "SYM_PX_BAND",
          "_price_upbit_quote_fills", "_px_skip_json"}
chk(not (set(dir(core.Core)) & _names) and _names <= set(dir(SV)),
    "P2 PRICING 이름 = Core 에 없음(옛 이름 대입은 효과 없이 지나가므로 svc_names 가 0 강제) · 서비스 클래스에 있음", sorted(set(dir(core.Core)) & _names))
chk(isinstance(S, SV) and vars(S)["core"] is C and vars(S)["_last_price_pass"] == 0.0 and vars(S)["_px_skip"] == (None, "[]")
    and not {"_last_price_pass", "_px_skip"} & set(vars(C)),
    "P2 c.svc_price = PriceService(core = c) · _last_price_pass 0.0 · _px_skip (None, \"[]\") 소유 = 서비스(Core __dict__ 에 없음)", sorted(vars(S)))
with open(os.path.join(T.SRC, "core.py"), encoding="utf-8") as fh:
    _ct = ast.parse(fh.read())
_init = [f for n in _ct.body if isinstance(n, ast.ClassDef) and n.name == "Core" for f in n.body
         if isinstance(f, ast.FunctionDef) and f.name == "__init__"][0]
_pr = set(vars(core_pricing.PricingMixin)) | {"_last_price_pass", "_px_skip"}
_use = [(x.lineno, x.attr) for x in ast.walk(_init) if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
        and x.value.id == "self" and (x.attr in _pr or x.attr == "svc_price")]
chk(len(_use) == 1 and _use[0][1] == "svc_price", "P2 Core.__init__ = 서비스 생성 줄 하나만(그 앞뒤 PRICING 이름·상태 0)", _use)

b = object.__new__(core.Core)
sb = core_svc.attach(b).svc_price
chk(isinstance(sb, SV) and vars(sb) == {"core": b, "_last_price_pass": 0.0, "_px_skip": (None, "[]")}
    and set(vars(b)) == {"svc_exf", "svc_recon", "svc_price"},
    "P3 attach = svc_price 도 붙임 · 옛 Core.__init__ 초기값 · core 상태 안 읽음", sorted(vars(sb)))
try:
    sb.px
    r3 = "읽힘"
except AttributeError:
    r3 = "AttributeError"
b.px = C.px
chk(r3 == "AttributeError" and sb.px is C.px and sb.svc_exf is b.svc_exf, "P3 맨 Core 의 포트 = core 에 생기면 그 값(늦게 읽음 · 생성 때 안 읽음)", r3)

E = C.svc_exf
t6 = int(time.time()) - 3600
C.px.d["fx"][str((t6 * 1000 // 60_000) * 60_000)] = 1380.0
o6 = {"uuid": "u-p4", "market": "USDT-ETH", "side": "bid", "state": "done", "executed_volume": "1", "executed_funds": "3000",
      "paid_fee": "0", "price": "3000", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t6)), "trades_count": 1}
E._consume_fills({"orders": [o6]})
C.conn.execute("UPDATE postings SET cost_usd=NULL, cost_krw=NULL WHERE source_ns='upbit:order'")
C.conn.commit()
seen4 = []
_legs0, _qu0 = E._upbit_quote_fill_legs, E._quote_usd
E._upbit_quote_fill_legs = lambda o: (seen4.append("legs"), _legs0(o))[1]
E._quote_usd = lambda q, ts: (seen4.append("qu"), _qu0(q, ts))[1]
n4 = S._price_upbit_quote_fills(10)
r4 = [tuple(r) for r in C.conn.execute("SELECT leg_seq, cost_usd, cost_krw FROM postings WHERE source_ns='upbit:order' ORDER BY leg_seq")]
del E._upbit_quote_fill_legs, E._quote_usd
chk(seen4 == ["legs", "qu"] and n4 == 1 and r4 == [(0, "3000.0", repr(3000.0 * 1380.0)), (1, "3000.0", repr(3000.0 * 1380.0))],
    "P4 PriceService._price_upbit_quote_fills → core.svc_exf._upbit_quote_fill_legs·_quote_usd(갈아 끼운 래퍼가 먹음) · 두 레그 원가 = 9-1 S6 과 같음",
    (seen4, n4, r4))
C.conn.execute("DELETE FROM postings WHERE source_ns='upbit:order'")
C.conn.commit()

NTX = 50
for i9 in range(NTX):
    C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                   " cost_krw, leg_kind, event, classifier_ver) VALUES ('chain_tx','eth',?,0,?,?,'wallet:eth:0xsyn','-1',NULL,NULL,'gas','GAS',3)",
                   ("0xp5%04d" % i9, t6 + i9, aid))
C.conn.commit()
calls5 = []
S._price_tx = lambda ch, h: calls5.append((ch, h)) and False


def one_pass(last):
    del calls5[:]
    S.__dict__.pop("_px_backoff", None)
    S._last_price_pass = last
    S.price_pass()
    return len(calls5)


B0 = core_pricing.PRICE_BATCH
chk(one_pass(time.time()) == 0, "P5 _last_price_pass = 지금 → 가격 패스 건너뜀(주기 = 서비스 소유 상태)")
chk(one_pass(0.0) == B0 == 40 and S._last_price_pass > 0, "P5 _last_price_pass = 0.0(rebuild2 덮기 꼴) → 돎 · 덮기 전 = PRICE_BATCH 40 개", len(calls5))
with open(os.path.join(T.ROOT, "tools", "rebuild2.py"), encoding="utf-8") as fh:
    _rb = ast.parse(fh.read())
_main = [f for f in _rb.body if isinstance(f, ast.FunctionDef) and f.name == "main"][0]
_body = list(_main.body)
_i = [k for k, st in enumerate(_body) if isinstance(st, ast.Assign) and ast.unparse(st.targets[0]) == "core_mod.PRICE_BATCH"]
chk(len(_i) == 1 and isinstance(_body[_i[0] + 1], ast.For) and "PRICE_BATCH" in ast.unparse(_body[_i[0] + 1]),
    "P5 rebuild2.main 의 PRICE_BATCH 덮기 두 문장(core_mod 대입 + core_ 접두어 모듈 반복) 찾음", _i)
_snip = ast.Module(body=_body[_i[0]:_i[0] + 2], type_ignores=[])
exec(compile(_snip, "rebuild2.py", "exec"), {"core_mod": core, "conn": C.conn, "sys": sys})
nrow = C.conn.execute("SELECT count(*) FROM postings").fetchone()[0]
chk(core.PRICE_BATCH == core_pricing.PRICE_BATCH == nrow >= NTX and "PRICE_BATCH" not in vars(core_svc),
    "P5 rebuild2 덮기 뒤 core_pricing.PRICE_BATCH = 덮은 값(원장 행 수) · core_svc 에 PRICE_BATCH 없음(몸통 = core_pricing 모듈 이름)",
    (core.PRICE_BATCH, core_pricing.PRICE_BATCH, nrow))
chk(SV.price_pass.__globals__ is vars(core_pricing) and one_pass(0.0) == NTX,
    "P5 PriceService.price_pass 가 읽는 PRICE_BATCH = core_pricing 모듈 이름 → 덮은 뒤 후보 전부(재생 결정성)", len(calls5))

T.finish()

#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

W = "0x" + "e1" * 20
TOK = "0x" + "e2" * 20
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
CFG_PATH = os.path.join(T.TMP, "config.json")
json.dump({"wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}], "backfill_months": 3, "chains": {"eth": {}}},
          open(CFG_PATH, "w"))
os.environ["TJ_CONFIG"] = CFG_PATH
import config, paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import rabby  # noqa: E402
import token_discovery as td  # noqa: E402

chk = T.chk
ON = {"rabby": {"enabled": True}}

chk(rabby.settings({})["enabled"] is False and rabby.settings(None)["enabled"] is False and rabby.enabled({}) is False,
    "V1a 설정 없음 = Rabby 꺼짐(기본)", rabby.settings({}))
chk(rabby.settings({"rabby": ["x"]})["enabled"] is False and rabby.settings({"rabby": "on"})["enabled"] is False,
    "V1b rabby 칸이 dict 아님 = 기본(꺼짐) · 예외 없음", None)
chk(rabby.settings(ON)["enabled"] is True and rabby.settings({"rabby": {"enabled": "true"}})["enabled"] is True
    and rabby.settings({"rabby": {"enabled": 1}})["enabled"] is True and rabby.enabled(ON) is True,
    "V1c 명시 true = 켜짐(기존 사용자 그대로)", None)
chk(rabby.settings({"rabby": {"enabled": "false"}})["enabled"] is False and rabby.settings({"rabby": {"enabled": False}})["enabled"] is False
    and rabby.settings({"rabby": {"enabled": "0"}})["enabled"] is False,
    "V1d 명시 false · 문자열 'false'·'0' = 꺼짐(bool('false') 함정 없음)", None)
chk(rabby.settings({"rabby": {"min_wallet_usd": "250"}})["min_wallet_usd"] == 250.0, "V1e 다른 칸 형 변환은 종전 그대로", None)

calls = []


def fake_get(u):
    calls.append(u)
    return {"total_usd_value": 0.0, "chain_list": []}


rp = os.path.join(paths.STATE_DIR, "rabby_test_v2.json")
cfg_w = {"wallets": [{"type": "evm", "chain": "eth", "address": W}]}
r0 = T.safe(rabby.refresh_once, cfg_w, rp, get=fake_get, sleep=lambda s: None)
chk(r0 == "off" and calls == [], "V2a 기본 설정 = 워커 'off' · Rabby 외부 조회 0번", (r0, calls))
r1 = T.safe(rabby.refresh_once, dict(cfg_w, rabby={"enabled": True, "min_wallet_usd": 0}), rp, get=fake_get, sleep=lambda s: None)
chk(r1 != "off" and len(calls) >= 1 and all(u.startswith(rabby.API) for u in calls), "V2b 명시 true = 조회함(가짜 get 으로 확인)", (r1, calls))

p_def = td.plan("eth", {"chains": {"eth": {}}}, {})
p_on = td.plan("eth", dict({"chains": {"eth": {}}}, **ON), {})
chk("rabby" not in p_def and "rabby" not in td.plan("eth", None, {}), "V3a 발견 출처 기본 = Rabby 없음", p_def)
chk("rabby" in p_on, "V3b rabby.enabled true = 발견 출처에 Rabby", p_on)

json.dump({"wallets": {W: {"total": 50.0, "chains": [{"id": "eth", "cid": 1, "usd": 50.0}],
                           "tokens": [{"id": TOK, "chain": "eth", "sym": "SYN", "v": True, "px": 1.0, "amt": 50.0}], "protocols": []}}},
          open(os.path.join(paths.STATE_DIR, rabby.STATE_NAME), "w"))
o0, m0 = {}, {}
td.src_rabby("eth", W, {"chains": {"eth": {}}}, o0, m0)
o1, m1 = {}, {}
td.src_rabby("eth", W, dict({"chains": {"eth": {}}}, **ON), o1, m1)
chk(o0 == {} and m0 == {}, "V4a 기본 = 스냅샷 파일이 있어도 Rabby 후보 0", (o0, m0))
chk(TOK in o1, "V4b 명시 true = 같은 파일에서 후보(종전 동작)", (o1, m1))
rd = T.safe(td.discover, "eth", W, cfg={"chains": {"eth": {}}}, env={}, sources=["rabby"])
rd1 = T.safe(td.discover, "eth", W, cfg=dict({"chains": {"eth": {}}}, **ON), env={}, sources=["rabby"])
chk(isinstance(rd, dict) and "_exc" not in rd and TOK not in (rd.get("cas") or {}) and isinstance(rd1, dict) and TOK in (rd1.get("cas") or {}),
    "V4c discover(출처 rabby 지정) = 끈 설정이면 후보 0 · 켠 설정이면 후보", (rd, rd1))

import db as dbm  # noqa: E402

con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
seen = []


def fake_disc(chain, w, **k):
    seen.append(list(k.get("sources") or []))
    return {"cas": {}, "meta": {}, "ok": {}, "fail": {}, "calls": {}}


for tag, cfg5, want in (("기본", {"chains": {"eth": {}}}, False), ("켬", dict({"chains": {"eth": {}}}, **ON), True)):
    seen.clear()
    prep = T.safe(td.recon_prep, con, cfg5, "eth", [W])
    rb5 = isinstance(prep, dict) and rabby.enabled(prep.get("cfg") or {})
    chk(rb5 is want, f"V5a 대사 재료({tag}) = 설정의 rabby 켬/끔이 실림", prep if isinstance(prep, dict) and "_exc" in prep else (prep or {}).get("cfg"))
    td.update_state(lambda cur: {"v": 1, "pairs": {}})
    ex5 = T.safe(td.recon_extra, prep, discover_fn=fake_disc, sleep=lambda s: None)
    chk(isinstance(ex5, dict) and "_exc" not in ex5 and len(seen) == 1 and (("rabby" in seen[0]) is want),
        f"V5b 대사 백그라운드 발견({tag}) = Rabby 출처 {'있음' if want else '없음'}", (seen, ex5 if isinstance(ex5, dict) and "_exc" in ex5 else None))
con.close()

chk(config.token_logos_on({}) is False and config.token_logos_on(None) is False and config.token_logos_on({"web": {}}) is False
    and config.token_logos_on({"web": {"token_logos": False}}) is False and config.token_logos_on({"web": "x"}) is False,
    "V6a 서버 로고 기본값 = 꺼짐", None)
chk(config.token_logos_on({"web": {"token_logos": True}}) is True and config.token_logos_on({"web": {"token_logos": "true"}}) is False,
    "V6b web.token_logos true(JSON 참) 일 때만 켜짐", None)

import acct_norm  # noqa: E402
import netpace  # noqa: E402
import pricing  # noqa: E402
import web  # noqa: E402

pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
acct_norm.FxBook.candle = lambda self, sym, ts: None
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False

for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker", "_rabby_worker", "_addr_ai_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None


def build_fields(cfg):
    json.dump(cfg, open(CFG_PATH, "w"))
    b = web.StateBuilder()
    web.BUILDER = b
    st = T.safe(b.build)
    return (st or {}).get("fields") if isinstance(st, dict) else None, st


base6 = {"wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}], "backfill_months": 3, "chains": {"eth": {}}}
f0, st0 = build_fields(base6)
chk(isinstance(f0, dict) and f0.get("tokenLogos") is False, "V6c 전체 빌드 fields.tokenLogos 기본 = false",
    st0 if not isinstance(f0, dict) else {"tokenLogos": f0.get("tokenLogos")})
f1, st1 = build_fields(dict(base6, web={"token_logos": True}))
chk(isinstance(f1, dict) and f1.get("tokenLogos") is True, "V6d config web.token_logos true = fields.tokenLogos true",
    st1 if not isinstance(f1, dict) else {"tokenLogos": f1.get("tokenLogos")})

import re  # noqa: E402

import _sec_lint as L7  # noqa: E402
APP = T.app_js()
V2 = os.path.join(T.ROOT, "web", "v2")
LOGO_RE = re.compile(r"cdn\.jsdelivr\.net|tokenlist|logosOff|logoDev|logoSrvOn|logoToggle|getItem\('tj_v2_nologo'\)|LS\.get\('tj_v2_nologo'\)")
bad7 = sorted(n + ":" + w for n in sorted(os.listdir(V2)) if n.endswith((".js", ".html"))
              for w in LOGO_RE.findall(open(os.path.join(V2, n), encoding="utf-8").read()))
chk(not bad7, "V7a web/v2 에 jsDelivr 주소·tokenlist·로고 켬 판정·켬 스위치·기기 로고 값 읽기 0", bad7)
D7 = L7.js_defs(APP, ["TW", "CHAIN_KEY", "symColor", "letter", "chainBadge", "icon", "hydrateLogos", "KEEP_LS"])
NODE = T.node_bin("화면 함수 동작 시험")
chk(len(D7) == 8, "V7b 아바타·hydrateLogos(호환 입구)·KEEP_LS 정의 찾음", sorted(D7))
if NODE and len(D7) == 8:
    js = ("const hits = []; const trap = n => new Proxy(function () {}, { get(t, k) { hits.push(n + '.' + String(k)); return trap(n + '.' + String(k)); },\n"
          "  apply() { hits.push(n + '()'); return trap(n + '()'); }, set(t, k) { hits.push(n + '.' + String(k) + '='); return true; } });\n"
          "globalThis.document = trap('document'); globalThis.fetch = trap('fetch'); globalThis.Image = trap('Image');\n"
          "globalThis.requestAnimationFrame = trap('raf');\n"
          "const store = { tj_v2_nologo: '0' }; const LS = { get: k => store[k] ?? null, set: (k, v) => { hits.push('LS.set ' + k); } };\n"
          "const S = { data: { fields: { tokenLogos: true } } };\n"
          "const esc = v => String(v).replace(/[&<>\"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;' }[c]));\n"
          + "\n".join(D7[k] for k in ("TW", "CHAIN_KEY", "symColor", "letter", "chainBadge", "icon", "hydrateLogos", "KEEP_LS")) + "\n"
          "const html = icon('ETH', 'sm', { chain: 'Base', ck: 'base', ca: '0x' + 'ab'.repeat(20) }) + chainBadge('Ethereum');\n"
          "const r = hydrateLogos();\n"
          "const tags = [...html.matchAll(/<img ([^>]*)>/g)].map(m => m[1].split(' ').map(a => a.split('=')[0]).sort().join(','));\n"
          "console.log(JSON.stringify({ hits, tags, r: r === undefined ? 'u' : String(r), keep: KEEP_LS }));\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    p = subprocess.run([NODE, "-"], input=js, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=60)
    try:
        r7 = json.loads((p.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        r7 = {"_err": (p.stderr or "")[-400:]}
    chk(r7.get("hits") == [] and r7.get("r") == "u",
        "V7c (node) hydrateLogos — 서버 켬 + 기기 '0'(구값)이어도 document·fetch·Image·저장소 접근 0(외부 요청 0)", r7)
    chk(r7.get("tags") == ["alt,class,data-lg,decoding,loading", "alt,data-cbk,decoding,loading", "alt,data-cbk,decoding,loading"],
        "V7d 아바타 마크업 = img.lg·체인 배지 img 그대로 · src 속성 없음(레이아웃 그대로 · 글자 아이콘)", r7.get("tags"))
    chk((r7.get("keep") or {}).get("tj_v2_nologo") == 1, "V7e 기기 키 이름 보존 — 초기화가 남기는 값에 tj_v2_nologo 그대로", r7.get("keep"))
else:
    chk(not T.node_required(), "node 없음 — V7c~V7e 건너뜀(TJ_TEST_REQUIRE_NODE=1 이면 실패)")

import runner_fp  # noqa: E402
base9 = {"wallets": [{"type": "evm", "chain": "base", "address": "0x" + "1" * 40}]}
f_off = runner_fp.unit_inputs("core", dict(base9))[2] if hasattr(runner_fp, "unit_inputs") else None
f_def = runner_fp.unit_inputs("core", dict(base9, rabby={"enabled": False}))[2] if f_off else None
f_on = runner_fp.unit_inputs("core", dict(base9, rabby={"enabled": True}))[2] if f_off else None
chk(f_off is not None and f_off == f_def and f_on != f_off, "V9 core 지문: 끔·칸 없음 = 종전 그대로 · 켜면 바뀜(core 도 다시 시작)", (f_off, f_def, f_on))

SET = open(os.path.join(T.ROOT, "web", "v2", "tab_set.js"), encoding="utf-8").read()
chk(not re.findall(r"sx-display-logo|logoToggle|'토큰 로고'", SET), "V8a 설정 › 화면 · 표시 = 토큰 로고 켬 스위치·검색 항목 없음(8-1 · 받기 제거)")
EX = json.load(open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8"))
chk((EX.get("rabby") or {}).get("enabled") is False and (EX.get("web") or {}).get("token_logos") is False,
    "V8b 예시 설정 = rabby.enabled false · web.token_logos false 명시", {"rabby": EX.get("rabby"), "token_logos": (EX.get("web") or {}).get("token_logos")})
chk(rabby.settings(EX)["enabled"] is False and config.token_logos_on(EX) is False, "V8c 예시 설정 그대로 = 둘 다 꺼짐", None)
RD = T.doc_text("README.md")
row = next((l for l in RD.split("\n") if l.startswith("| `rabby.enabled`")), "")
chk("꺼짐" in row and "켜짐 · 1000" not in row and "`web.token_logos`" in RD and "기본 꺼짐" in RD,
    "V8d README 설정 표 = Rabby 기본 꺼짐 · web.token_logos 행", row)


import token_discovery as TD10  # noqa: E402
import time as _t10  # noqa: E402
ent10 = {"at": _t10.time(), "sig": {}, "ok": {"blockscout": 3}, "fail": {}}
r_on = TD10.need_refresh(ent10, {}, srcs=["blockscout", "rabby"]) if "srcs" in TD10.need_refresh.__code__.co_varnames else None
ent10b = dict(ent10, ok={"blockscout": 3, "rabby": 0})
r_done = TD10.need_refresh(ent10b, {}, srcs=["blockscout", "rabby"]) if r_on is not None else None
chk(r_on is not None and r_on[0] is True and r_on[1] == "new:rabby" and r_done == (False, "cache"),
    "V10a Rabby 새로 켬 = 한 번 다시 발견(new:rabby) · 한 번 돈 뒤 = 캐시", (r_on, r_done))
chk(not re.findall(r"LS\.set\('tj_logo_fail'|addEventListener\('(?:load|error)', ev =>", APP),
    "V10b 로고 실패 기억(tj_logo_fail 덮어쓰기)·문서 위임 load/error 로고 리스너 없음(8-1 · 기존 값은 그대로)")


T.finish()

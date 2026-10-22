#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import config  # noqa: E402
import chain_registry as reg  # noqa: E402
import token_tables  # noqa: E402
import candles  # noqa: E402
import spamguard  # noqa: E402

chk = T.chk

chk(all(candles.KNOWN_CG_ID.get(reg.spec(c).native_symbol) == reg.spec(c).cg_native for c in reg.CHAINS),
    "P1 네이티브 코인게코 id = 레지스트리 cg_native(TRX tron · SUI sui · TON the-open-network · BTC bitcoin)",
    {c: (reg.spec(c).native_symbol, candles.KNOWN_CG_ID.get(reg.spec(c).native_symbol)) for c in reg.CHAINS})
OFF = {("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"): "USDT", ("ton", "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"): "USDT",
       ("sui", "0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC"): "USDC"}
got = {(c, i): token_tables.STABLE_CAS.get(c, {}).get(reg.asset_key(c, "token", i)) for (c, i) in OFF}
chk(got == OFF, "P1 공식 스테이블 키 = 레지스트리 원장 키(Tron Base58·TON friendly·Sui Move 타입 → asset_key)", got)
chk(all(spamguard.is_genuine(c, reg.asset_key(c, "token", i)) for (c, i) in OFF), "P1 공식 스테이블 = 정품(spamguard)")
chk(set(token_tables.STABLE_CAS["tron"]) == {reg.asset_key("tron", "token", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")} and len(token_tables.STABLE_CAS["ton"]) == 1
    and len(token_tables.STABLE_CAS["sui"]) == 1, "P1 새 체인 화이트리스트 = 공식 1개씩(검증 안 된 계약 없음)")
FAKE_T = N.TOK["tron"]
chk(spamguard.fake_major("USDT", [("tron", FAKE_T)]) == "USDT" and spamguard.fake_major("USD₮", [("ton", "0_" + "77" * 32)]) == "USDT",
    "P1 기호만 USDT 인 다른 계약 = 정품 아님(가짜 대표 심볼 — 시세·총자산 격리)")
chk(token_tables.STABLE_CAS["eth"].get("0xdac17f958d2ee523a2206206994597c13d831ec7") == "USDT", "P1 기존 EVM 표 무변(이더리움 USDT)")

import core  # noqa: E402
c = core.Core(config.load_config())
k_t = reg.asset_key("tron", "token", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
a1 = c.asset_id("token", "tron", k_t, symbol="USDT", decimals=6)
a2 = c.asset_id("token", "tron", FAKE_T, symbol="USDT", decimals=6)
k_s = reg.asset_key("sui", "token", "0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC")
a3 = c.asset_id("token", "sui", k_s, symbol="USDC", decimals=6)
g = {a: c.conn.execute("SELECT name FROM asset_groups WHERE group_id=?", (c._group_of(a),)).fetchone()["name"] for a in (a1, a2, a3)}
chk(g[a1] == "USDT" and g[a3] == "USDC" and g[a2] == f"USDT#{a2}", "P2 공식 = USDT/USDC 그룹 · 가짜 = 인스턴스 그룹", g)
c.conn.rollback()

import subprocess  # noqa: E402
SJ = os.path.join(T.ROOT, "web", "v2", "setup.js")
src = open(SJ, encoding="utf-8").read()
blk = src[src.index("  const NX = ['tron', 'sui', 'ton', 'btc'];"):src.index("  function nxMsgHTML(an)")]
chk("<select" not in blk and "su-chip" in src[src.index("function nxPickHTML"):src.index("async function nxAdd")]
    and "api('chain_wallets/add'" in src and "script_type: x.xpub ? U.wfmt : undefined" in src,
    "S1 정적: 칩 꼴(select 없음) · chain_wallets/add · xpub 형식 칩 값을 script_type 으로")
chk("if (nxOn()) return nxAnalyze(raw);" in src and "if (nxOn()) return nxAdd();" in src and "if (an.nx) return nxMsgHTML(an);" in src,
    "S1 정적: 새 체인 칩을 골랐을 때만 새 흐름(그 밖 = 종전 wAnalyze·wadd)")
node = T.node_bin("S1 실행 시험(정적 검사만)")
if node:
    JS = """
const U = { wnet: '', wbtc: 'address', st: { nonevm: [] } };
const wSecret = raw => /[0-9a-fA-F]{64}/.test(String(raw).replace(/[\\s,;]+/g, '')) ? 'key' : '';
const esc = t => String(t);
""" + blk + """
const R = [];
const ck = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const T = (ch, hd, v) => { U.wnet = ch; U.wbtc = hd ? 'hd' : 'address'; return nxAnalyze(v); };
const xpub = 'xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8';
ck(T('tron', 0, 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t').nx.ok && !T('tron', 0, '0x' + 'ab'.repeat(20)).nx.ok, 'tron T… 통과 · EVM 0x 거부');
ck(T('sui', 0, '0x' + 'ab'.repeat(32)).nx.ok && !T('sui', 0, '0x' + 'ab'.repeat(32)).secret && !T('sui', 0, '0x' + 'ab'.repeat(20)).nx.ok, 'sui 0x64 통과(개인 키로 안 봄) · 0x40 거부');
ck(T('ton', 0, '0:' + 'ab'.repeat(32)).nx.ok && !T('ton', 0, '0:' + 'ab'.repeat(32)).secret && T('ton', 0, 'UQ' + 'A'.repeat(46)).nx.ok, 'ton raw·friendly 통과');
ck(T('sui', 0, 'ab'.repeat(32)).secret === 'key' && T('tron', 0, 'ab'.repeat(32)).secret === 'key', '16진수 64자만(주소 꼴 아님) = 개인 키 거부');
ck(!T('tron', 0, 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t, TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t').nx.ok, '여러 개 = 하나씩');
ck(T('btc', 0, 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4').nx.ok && !T('btc', 0, xpub).nx.ok, 'btc 주소 하나 · xpub 은 HD 로');
const z = T('btc', 1, 'z' + xpub.slice(1)), x = T('btc', 1, xpub);
ck(z.nx.ok && !z.nx.xpub && x.nx.ok && x.nx.xpub, 'HD: zpub = 형식 자동 · xpub = 형식 칩 필요');
ck(!T('btc', 1, 'xprv' + xpub.slice(4)).nx.ok && T('btc', 1, 'wpkh(' + xpub + '/<0;1>/*)#abcdefgh').nx.ok, 'HD: xprv 거부 · 디스크립터(<0;1> 의 ; 허용)');
ck(T('btc', 1, '').toks.length === 0 && T('btc', 1, '').save.length === 0, '빈 칸 = 안내만');
console.log(JSON.stringify(R));
"""
    pr = subprocess.run([node, "--input-type=module", "-e", JS], capture_output=True, text=True, timeout=60)
    try:
        res = json.loads(pr.stdout.strip().splitlines()[-1])
    except Exception:   # noqa: BLE001
        res = [[False, "node 실행 실패", pr.stderr[-400:]]]
    for ok9, msg9, d9 in res:
        chk(ok9, "S1 " + msg9, d9)
T.finish()

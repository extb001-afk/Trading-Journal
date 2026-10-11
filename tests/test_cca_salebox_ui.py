#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import re
import shutil
import subprocess

chk = T.chk
APP = os.path.join(T.ROOT, "web", "v2", "app.js")
src = open(APP, encoding="utf-8").read() if os.path.exists(APP) else ""
chk(bool(src), "app.js 있음", APP)
blk = src.split("  function saleBox(p) {", 1)[1].split("\n  }\n", 1)[0] if "  function saleBox(p) {" in src else ""
chk("x.payN" in blk and "m(num(x.payCost))" in blk and "m(num(x.payProceeds))" in blk and "m(num(x.payRealized))" in blk and "q(num(x.payQty))" in blk,
    "S0 saleBox = 사용분 처분 줄(금액 m() · 수량 q() — 숨김·랜덤값 규칙)", blk[:200])

JS = r'''
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const i = APP.indexOf('  function saleBox(p) {'), j = APP.indexOf('\n  }\n', i);
if (i < 0 || j < 0) throw new Error('saleBox 못 찾음');
const B = APP.slice(i, j) + '\n  }\n';
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const S = { D: { saleLinks: [] }, hide: false };
const deps = { S, esc, num: x => (isFinite(+x) ? +x : 0), arr: x => (Array.isArray(x) ? x : []),
  m: v => (S.hide ? '$•••' : '$' + Number(v).toLocaleString('en-US')), q: v => (S.hide ? '•••' : Number(v).toLocaleString('en-US')),
  short: a => String(a || '').slice(0, 6), pvW: () => '•••', PVM: { px: 1 }, rw: t => t };
const names = Object.keys(deps);
const F = new Function(...names, B + '\nreturn { saleBox };')(...names.map(k => deps[k]));
const base = { lot: 'eth:a:b', sym: 'TKN', label: '토큰 세일', cur: 'ETH', paidUsd: 20000, refundUsd: 18000, unit: 2, qty: 1000, usedQty: 1000, usedCost: 2000, bidder: '0xb4b4', bidderMine: true, off: false };
const pay = { payQty: 1, payCost: 1000, payProceeds: 2000, payRealized: 1000, payUnkQty: 0, payN: 1 };
const out = {};
const run = (k, x, hide) => { S.D.saleLinks = [x]; S.hide = !!hide; out[k] = F.saleBox({ sym: 'TKN' }).replace(/<[^>]+>/g, ' '); };
run('with', Object.assign({}, base, pay));
run('none', base);
run('off', Object.assign({}, base, pay, { off: true }));
run('hide', Object.assign({}, base, pay), true);
run('unk', Object.assign({}, base, pay, { payUnkQty: 0.5 }));
process.stdout.write(JSON.stringify(out));
'''
node = shutil.which("node")
if not node or not src:
    print("SKIP node 없음 — 화면 함수 실행 시험 건너뜀(정적 S0 만)")
else:
    r = subprocess.run([node, "--input-type=module", "-"], input=JS, capture_output=True, text=True, timeout=60, env=dict(os.environ, TJ_TEST_APP=APP))
    try:
        o = json.loads(r.stdout)
    except ValueError:
        o = None
    chk(o is not None, "node 함수 실행", (r.stdout[-300:], r.stderr[-600:]))
    if o:
        chk("결제 코인 사용 1 ETH" in o["with"] and "원래 원가 $1,000" in o["with"] and "대가 $2,000" in o["with"] and "실현 $1,000" in o["with"]
            and "원가 미상" not in o["with"], "S1 처분 있음 = '결제 코인 사용 1 ETH · 원래 원가 $1,000 · 대가 $2,000 · 실현 $1,000'", o["with"])
        chk("결제 코인 사용" not in o["none"], "S2 처분 없음(옛 서버 · 원가 미확인 로트) = 줄 없음", o["none"])
        chk("결제 코인 사용" not in o["off"], "S3 연결 끊음 = 줄 없음(일반 경로로 계산 중)", o["off"])
        chk("결제 코인 사용" in o["hide"] and not re.search(r"\d", o["hide"].split("결제 코인 사용", 1)[1].split("입찰 지갑")[0]),
            "S4 금액 숨김 = 처분 줄에 숫자 없음(가린 글자만)", o["hide"])
        chk("원가 미상 0.5" in o["unk"], "S5 원가 미상 몫 = '원가 미상 0.5'", o["unk"])
T.finish()

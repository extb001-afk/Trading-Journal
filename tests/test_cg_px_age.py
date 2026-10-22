#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import cgca  # noqa: E402

chk = T.chk
cgca.reset_for_tests()
now = time.time()
CA = "0x" + "cd" * 20
with cgca._LOCK:
    cgca._entries()[cgca.key_of("eth", CA)] = [now - 15 * 3600, 2.5]
chk(cgca.price_at("eth", CA, now=now) == (2.5, now - 15 * 3600) and cgca.price("eth", CA, now=now) == 2.5, "G1 price_at = (값, 받은 시각) · price 종전 값")
chk(cgca.price_at("eth", CA, now=now + 10 * 3600) is None and cgca.price("eth", CA, now=now + 10 * 3600) is None, "G1 24시간 넘으면 없음")

JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const line = a => { const i = APP.indexOf(a); if (i < 0) throw new Error('줄을 못 찾음: ' + a); return APP.slice(i, APP.indexOf('\n', i)); };
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a); return APP.slice(i, j); };
const B = [cut('  const PX_STALE = 1800,', '  const rbChip = g =>')].join('\n');
const F = new Function(B + '\nreturn { pxSrcTxt, pxStaleOf };')();
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? '' : JSON.stringify(d)]);
const t1 = F.pxSrcTxt({ pxSrc: 'coingecko', pxAge: 15 * 3600 });
chk(t1.startsWith('코인게코') && t1.indexOf('15시간 전') >= 0, 'G3 코인게코 15시간 = 출처 코인게코 · ≈ 15시간 전', t1);
const t2 = F.pxSrcTxt({ pxSrc: 'coingecko', pxAge: 3600 });
chk(t2 === '코인게코', 'G3 코인게코 1시간(갱신 주기 안) = 나이 글 없음', t2);
const t3 = F.pxSrcTxt({ pxSrc: 'dex:gecko', pxAge: 2400 });
chk(t3 === 'DEX(게코) · ≈ 40분 전', 'G3 반대: DEX 30분 기준 종전', t3);
chk(F.pxStaleOf({ pxSrc: 'coingecko', pxAge: 15 * 3600 }) && !F.pxStaleOf({ pxSrc: 'coingecko', pxAge: 3600 }), 'G4 묵은 칩 대상 = 코인게코(2시간 넘음)');
chk(F.pxStaleOf({ pxSrc: 'dex:okx', pxAge: 2400 }) && !F.pxStaleOf({ pxSrc: 'cex:바이낸스', pxAge: 99999 }) && !F.pxStaleOf({ pxSrc: 'coingecko', pxAge: null }),
  'G4 반대: DEX = 종전 · 거래소 시세·나이 없음 = 대상 아님');
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok ? '' : '  — ' + d));
console.log('RESULT ' + R.filter(r => r[0]).length + '/' + R.length);
'''
NODE = T.node_bin("화면 시세 출처·나이 시험")
if NODE:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = T.app_js_path()
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        chk(ln.startswith("PASS "), ln[5:])
    chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 시험이 끝까지 돌았음", (p.stderr or "")[-900:])
T.finish()

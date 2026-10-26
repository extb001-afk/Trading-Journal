#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import subprocess  # noqa: E402

APP = T.app_js_path()
app = open(APP, encoding="utf-8").read()

print("[1] 정적")
T.chk("  const BENCH_K = ['btc'];\n" in app and "BENCH_K = ['btc', 'hold']" not in app, "켜는 키 = btc 만('안 팔았다면' 숨김)")
i9 = app.find("  function benchLeg() {")
leg = app[i9:app.find("\n  }\n", i9)] if i9 >= 0 else ""
T.chk(leg and "chip('hold'" not in leg and "안 팔았다면'" not in leg, "범례 칩에 '안 팔았다면' 없음", leg[-300:])
T.chk("chip('btc', 'BTC 만 들고 있었다면'" in leg, "BTC 칩은 그대로", leg[-300:])
T.chk("benchOn('hold') && bv ? bv.hold : null" in app, "계산 경로는 남김(benchOn('hold') 로만 막힘 — 다시 켤 때 그대로)")

print("[2] 켜 둔 기기(node)")
a9 = app.find("  const BENCH_K = ['btc'];")
b9 = app.find("  const benchOn = k =>", a9)
blk = app[a9:app.find("\n", b9)] if a9 >= 0 and b9 >= 0 else ""
JS = r'''
let STORE = '';
const LS = { get: k => (k === 'tj_v2_bench' ? STORE : null) };
''' + blk + r'''
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, d]);
STORE = 'btc,hold'; chk(benchOn('btc') && !benchOn('hold') && benchOn(), "저장 'btc,hold' = BTC 만 켜짐", [...benchSet()]);
STORE = 'hold'; chk(!benchOn('hold') && !benchOn(), "저장 'hold' 만 = 비교선 전부 꺼짐(빈 칩 상태 아님)", [...benchSet()]);
STORE = ''; chk(!benchOn(), '저장 없음 = 꺼짐');
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok || d === undefined ? '' : '  — ' + JSON.stringify(d)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''
NODE = T.node_bin("켜 둔 기기 시험")
if NODE:
    T.chk(bool(blk), "BENCH_K·benchSet·benchOn 블록 찾음")
    p = subprocess.run([NODE, "-"], input=JS, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=60)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()

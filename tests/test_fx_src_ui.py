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
chk("D.rateSrc =" in src and re.search(r"D\.rateLive = D\.rateSrc === 'live'", src) is not None,
    "F0a derive: D.rateSrc 보관 · rateLive = rateSrc === 'live' 일 때만(종전 fallback 아니면 참 — stale 도 실제 값 취급)",
    re.findall(r"D\.rateLive = [^;]+;", src))
m9 = re.search(r"const fx = '<div class=\"sx-it\" id=\"sx-data-fx\">.*\n", src)
chk(m9 is not None and "fxNote(D)" in m9.group(0) and "rateSrc === 'fallback'" in m9.group(0),
    "F0b 설정 환율 줄 = fxNote(D) · fallback 이면 김프 숨김 · 점 색 rateSrc", m9.group(0)[:300] if m9 else None)

JS = r'''
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const B = [cut('  function fxNote(D) {', '\n  }\n') + '\n  }\n', cut('  function statusHTML(short) {', '  function tabBadge(k) {'), cut('  function derive(d) {', '    const stables = arr(f.stables)') + ' return D; }'].join('\n');
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const S = { D: null, lastOk: Date.now(), err: null, cached: false };
const deps = { S, esc, POLL_MS: 30000, num: x => (isFinite(+x) ? +x : 0), arr: x => (Array.isArray(x) ? x : []), todayISO: () => '2026-10-10', kstISOAt: () => '2026-10-10',
  fmtTs: () => '10-10 09:00', scanText: () => '방금', optWaiting: () => false, nf: () => ({ format: v => Number(v).toLocaleString('en-US') }),
  kimpCol: () => 'var(--text)', pctS: (v, d) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + '%', kimpChip: () => '' };
const names = Object.keys(deps);
const F = new Function(...names, B + '\nreturn { fxNote, statusHTML, derive };')(...names.map(k => deps[k]));
const out = {};
for (const [k, f] of Object.entries({ live: { rate: 1450, fxRate: 1400, rateSrc: 'live', rateAt: 1 }, stale: { rate: 1450, fxRate: 1400, rateSrc: 'stale', rateAt: 1760054400 },
  fallback: { rate: 1384, fxRate: 1384, rateSrc: 'fallback' }, old: { rate: 1450, fxRate: 1400 } })) {
  const D = F.derive({ fields: f, todayKey: '10-10' });
  D.wallets = []; D.exN = 0; D.lastScan = 0;
  S.D = D;
  out[k] = { html: F.statusHTML(false), live: D.rateLive, src: D.rateSrc };
}
process.stdout.write(JSON.stringify(out));
'''
node = shutil.which("node")
if not node or not src:
    print("SKIP node 없음 — 화면 블록 실행 시험 건너뜀(정적 F0 만)")
else:
    r = subprocess.run([node, "--input-type=module", "-"], input=JS, capture_output=True, text=True, timeout=60, env=dict(os.environ, TJ_TEST_APP=APP))
    try:
        o = json.loads(r.stdout)
    except ValueError:
        o = None
    chk(o is not None, "node 블록 실행", (r.stdout[-300:], r.stderr[-600:]))
    if o:
        for v9 in o.values():
            v9["html"] = re.sub(r'\s[\w-]+="[^"]*"', "", v9["html"])
        lv, st, fb, od = o["live"], o["stale"], o["fallback"], o["old"]
        chk(lv["live"] is True and "김프" in lv["html"] and "환율 대체값" not in lv["html"] and "환율 오래됨" not in lv["html"],
            "F1 live = 김프 표시 · 경고 글자 없음 · rateLive 참", lv)
        chk(st["live"] is False and "김프" in st["html"] and "환율 오래됨" in st["html"] and 'class="wtxt"' in src.split("function fxNote(D)")[1][:900],
            "F2 stale = 김프 표시 + '환율 오래됨'(작은 경고 글자) · rateLive 거짓(종전 참)", st)
        chk(fb["live"] is False and "김프" not in fb["html"] and "환율 대체값" in fb["html"],
            "F3 fallback = 김프 숨김 + '환율 대체값'", fb)
        chk(od["live"] is True and od["src"] == "live" and "환율" not in od["html"].split("USDT")[1],
            "F4 옛 서버(rateSrc 없음) = 종전처럼 live 취급(경고 없음)", od)
T.finish()

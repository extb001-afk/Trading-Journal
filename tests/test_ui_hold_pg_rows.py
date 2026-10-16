#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import shutil
import subprocess

APP = T.app_js_path()
app = open(APP, encoding="utf-8").read()

print("[1] 정적")
i9 = app.find("  function holdingsHTML() {")
hb = app[i9:app.find("\n  }\n", i9)] if i9 >= 0 else ""
T.chk("uiPgSlice('hold', rows)" in hb and "uiPgBar('hold', rows.length," in hb and "uiPgUnits(" not in hb,
      "rev1012: 보유표 쪽 넘김 = 줄 단위(하위 행도 한 줄 · 종전 ui17 묶음 단위 = 하위 행 있는 쪽이 길어져 쪽 바 위치가 바뀜)", hb[:120])
T.chk("uiPgUnits" not in app, "묶음 쪽 도우미(uiPgUnits — 보유표만 썼음) 없음")

print("[2] 화면 함수(node)")
JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const line = a => { const i = APP.indexOf(a); if (i < 0) throw new Error('줄을 못 찾음: ' + a); return APP.slice(i, APP.indexOf('\n', i)); };
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
try {
  // 자르는 표식 = 코드 줄만(공개 빌드는 주석 문구를 바꾼다)
  const B = [cut('  const uiWrapBtn = (b, o) =>', '  const uiHidChip = '), line('  const rbChip = g =>'),
    ...['  const gRb = g =>', '  let twinVis = ', '  const twinChip = g =>', '  const gName = g =>', '  const gTip = g =>', '  const gSub = (g, t) =>'].map(line),
    cut('  const holdPgHit = ', '  function debtFootHTML() {'), cut('  const holdTh = ', '  function stakeUnk(g) {')].join('\n');
  const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  let ROWS = [];
  const S = { uiPg: {}, pgSz: 10, hold: { mode: 'all', sort: 'value', dir: -1, open: new Set(), dense: false, showDust: false }, D: { groups: [1] }, dust: 0, mobile: false, hide: false, rand: false };
  const deps = { S, esc, nf: () => ({ format: v => Number(v).toLocaleString('en-US') }), IC: { chev: '<svg class="c"></svg>', coin: '', right: '' }, UI_CHEV: '<span class="uchev"></span>',
    uiHas: (o, k) => Object.prototype.hasOwnProperty.call(o, k), LS: { get: () => null }, holdRows: () => ({ rows: ROWS, hidden: [] }),
    m: v => '$' + v, q: v => String(v), ago: () => '1분 전', clps: (k, h) => h, TODAY_TIP: 't', TODAY_NONE: 'n', todayOf: () => null, sparkOf: () => null,
    document: { querySelectorAll: () => [] }, window: {} };
  // 그 밖 화면 조각(아이콘·칩·셀·펼침 …) = 빈 글자 — 줄 수·순서·이름만 본다
  const P = new Proxy(deps, { has: (t, k) => typeof k === 'string' && (k in t || !(k in globalThis)), get: (t, k) => (k in t ? t[k] : typeof k === 'string' ? () => '' : undefined) });
  const F = new Function('P', 'with (P) {\n' + B + '\nreturn { holdingsHTML, holdPgHit, uiPgReveal };\n}')(P);
  // 25코인 + Rabby 기준 하위 행 3줄(C2 · C8 · C20 바로 뒤) = 28줄 — C8 = 10번째 줄 · 그 하위 행 = 11번째 줄(쪽 크기 10 의 경계)
  const g = (k, sub) => ({ key: sub ? '#rb:' + k : k, sym: k, chainLabel: 'X Layer', qty: 1, rabby: sub ? 1700000000 : 0, rbKind: sub ? '스테이킹' : undefined, logo: {} });
  const mk = subs => { const a = []; for (let i = 0; i < 25; i++) { a.push({ g: g('C' + i), value: 1000 - i, frac: 1 }); if (subs && [2, 8, 20].indexOf(i) >= 0) a.push({ g: g('C' + i, true), value: 5, frac: 1, sub: true }); } return a; };
  const keys = h => Array.from(h.matchAll(/data-a="holdTog" data-k="([^"]*)"/g), x => x[1]);
  const MODES = [['모바일', () => { S.mobile = true; S.hold.dense = false; }], ['기본 표', () => { S.mobile = false; S.hold.dense = false; }], ['촘촘히', () => { S.mobile = false; S.hold.dense = true; }]];
  for (const [mn, setM] of MODES) for (const sz of [10, 20]) {
    setM(); S.pgSz = sz; S.uiPg = {}; ROWS = mk(true);
    const all = ROWS.map(r => r.g.key), N = all.length, last = Math.ceil(N / sz) - 1, got = [], lens = [];
    let bars = true, head = true;
    for (let p = 0; p <= last; p++) {
      S.uiPg.hold = p; const h = F.holdingsHTML(), k = keys(h); lens.push(k.length); got.push(...k);
      const a = p * sz + 1, b = Math.min(N, a + sz - 1);
      if (!(h.indexOf(a + '–' + b + ' <span class="mut">/ ' + N + '<span class="upgu">줄</span>') >= 0)) bars = false;
      if (!/<span class="cap num">25종 · /.test(h)) head = false;
    }
    chk(lens.slice(0, -1).every(n => n === sz) && lens[lens.length - 1] === N - sz * last, mn + ' · 쪽 크기 ' + sz + ': 하위 행 섞인 ' + N + '줄 = 모든 쪽 정확히 ' + sz + '줄(마지막 쪽만 짧음 — 다음 단추 위치 고정)', lens);
    chk(got.join() === all.join(), mn + ' · 쪽 크기 ' + sz + ': 쪽을 이어 붙이면 전체 줄 그대로(빠짐·겹침·순서 바뀜 없음)', got);
    chk(bars && head, mn + ' · 쪽 크기 ' + sz + ": 쪽 바 'a–b / " + N + "줄'(줄 수 기준) · 머리 '25종'(코인 수 그대로)", { bars, head });
  }
  // 하위 행 없으면 줄 수 = 코인 수 → 쪽 바 단위 '종'(종전 그대로)
  S.mobile = false; S.hold.dense = false; S.pgSz = 10; S.uiPg = {}; ROWS = mk(false);
  { const h = F.holdingsHTML(); chk(keys(h).length === 10 && /1–10 <span class="mut">\/ 25<span class="upgu">종<\/span>/.test(h), "하위 행 없음 = 쪽 바 '1–10 / 25종'(종전 그대로)", keys(h).length); }
  // 찾아가기(⌘K 보유) — 줄 단위 그 쪽
  for (const [mn, setM] of MODES) {
    setM(); ROWS = mk(true);
    S.pgSz = 10; S.uiPg = {}; F.uiPgReveal('hold', F.holdPgHit('#rb:C8')); let h = F.holdingsHTML(), k = keys(h);
    const i9 = Math.max(0, h.indexOf('data-k="#rb:C8"')), top = h.slice(i9, i9 + 1200);
    chk(S.uiPg.hold === 1 && k[0] === '#rb:C8' && k.length === 10 && !(S.uiPgFind && S.uiPgFind.hold), mn + ' · 쪽 크기 10: 하위 행(11번째 줄) 찾아가기 = 둘째 쪽 맨 위', { p: S.uiPg.hold, k: k.slice(0, 2) });
    chk(/C8<span class="rbnm"> · 스테이킹<\/span>/.test(top) && /Rabby/.test(top), mn + ": 다음 쪽 맨 위로 간 하위 행 = 이름 'C8 · 스테이킹' + 'Rabby 기준'(본행 없이도 스스로 설명)", top.slice(0, 300));
    S.pgSz = 20; S.uiPg = { hold: 1 }; F.uiPgReveal('hold', F.holdPgHit('#rb:C8')); k = keys(F.holdingsHTML());
    chk(S.uiPg.hold === 0 && k.indexOf('#rb:C8') === 10, mn + ' · 쪽 크기 20: 하위 행 찾아가기 = 첫 쪽(다른 쪽 보던 중이어도)', S.uiPg.hold);
    S.pgSz = 10; S.uiPg = {}; F.uiPgReveal('hold', F.holdPgHit('C24')); k = keys(F.holdingsHTML());
    chk(S.uiPg.hold === 2 && k[k.length - 1] === 'C24' && k.length === 8, mn + ' · 쪽 크기 10: 마지막 본행(28번째 줄) 찾아가기 = 셋째 쪽', { p: S.uiPg.hold, n: k.length });
    S.pgSz = 10; S.uiPg = {}; F.uiPgReveal('hold', F.holdPgHit('C8')); k = keys(F.holdingsHTML());
    chk(S.uiPg.hold === 0 && k[k.length - 1] === 'C8', mn + ' · 쪽 크기 10: 경계 본행(C8 · 10번째 줄) 찾아가기 = 첫 쪽 끝', { p: S.uiPg.hold, k: k.slice(-1) });
  }
} catch (e) { chk(false, '실행 오류', String(e && e.stack || e)); }
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok ? '' : ' — ' + JSON.stringify(d).slice(0, 600)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''
NODE = shutil.which("node")
if not NODE:
    print("SKIP node 없음 — 화면 함수 동작 시험 건너뜀")
else:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = APP
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()

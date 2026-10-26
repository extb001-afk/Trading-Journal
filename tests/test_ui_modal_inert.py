#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

JS = r'''
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8'), HJ = fs.readFileSync(process.env.TJ_TEST_HEALTH, 'utf8');
const cutOf = SRC => (a, b) => { const i = SRC.indexOf(a), j = i < 0 ? -1 : SRC.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return SRC.slice(i, j); };
const lineOf = SRC => a => { const i = SRC.indexOf(a); if (i < 0) throw new Error('줄을 못 찾음: ' + a); return SRC.slice(i, SRC.indexOf('\n', i)); };
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const sec = (n, f) => { try { f(); } catch (e) { chk(false, '묶음 ' + n + ' 실행 오류', String((e && e.stack) || e).slice(0, 300)); } };
const SELS = ['header.top', '#mtop', '#banners', '#view', '#tabbar', '#bf'];

function world() {
  const BG = {}; SELS.forEach(s => { BG[s] = { inert: false }; });
  const ids = {}, OV = { __h: '' }, focusLog = [];
  const btn = { offsetParent: {}, focus: () => focusLog.push(SELS.map(s => BG[s].inert)) };
  BG['header.top'].btn = btn;
  const document = {
    getElementById: id => ids[id] || null,
    createElement: () => { const el = { id: '', querySelector: () => null, remove: () => { if (ids[el.id] === el) delete ids[el.id]; } }; return el; },
    body: { appendChild: el => { ids[el.id] = el; } },
    documentElement: { classList: { toggle: () => {}, remove: () => {} } },
    querySelector: s => (s === '.tjh-btn' ? btn : null),
  };
  const $ = s => (s === '#overlay' ? OV : BG[s] || null);
  const bgInert = new Function('$', 'document', cutOf(APP)('  function bgInert(ov) {', '  function ovAfter(h) {') + '\nreturn bgInert;')($, document);
  const TJ = new Function('bgInert', '$', 'return {\n' + lineOf(APP)('    bgInert: () => bgInert(') + '\n};')(bgInert, $);
  const window = { TJ };
  const H = { open: false, pop: false, locked: false }, OPS = { scrollTo: '', det: new Set(), d: null, inflight: false };
  const deps = { H, OPS, window, document, chrome: () => {}, paintPop: () => {}, panelHTML: () => '<div class="tjh-panel"></div>', TJDOM: { set: () => {} },
    load: () => {}, loadOps: () => {}, isLocked: () => false };
  const cutH = cutOf(HJ);
  const api = new Function(...Object.keys(deps), cutH('  function paint() {', '  function paintPop() {') + cutH('  function lock() {', '  const syn = ')
    + cutH('  function openPanel() {', "  document.addEventListener('click'") + '\nreturn { paint, lock, openPanel, closePanel };')(...Object.values(deps));
  const inert = () => SELS.map(s => BG[s].inert);
  return { BG, OV, H, api, bgInert, inert, focusLog, ids };
}
const all = (a, v) => a.every(x => x === v);

sec('A 열기·닫기', () => {
  const w = world();
  w.bgInert(''); chk(all(w.inert(), false), 'A 아무 창도 없으면 뒤 화면 inert 아님', w.inert());
  w.H.open = true; w.api.paint();
  chk(!!w.ids.tjhOverlay && all(w.inert(), true), 'A 상태 패널(aria-modal)을 열면 뒤 화면(상단·배너·본문·탭바) inert', w.inert());
  w.H.open = false; w.api.paint();
  chk(!w.ids.tjhOverlay && all(w.inert(), false), 'A 패널을 닫으면 inert 풂', w.inert());
});
sec('B 겹침', () => {
  const w = world();
  w.H.open = true; w.api.paint();
  w.bgInert(w.OV.__h);   // 폴링 → renderOverlay → ovAfter('') (빈 앱 덮개)
  chk(all(w.inert(), true), 'B 패널이 열린 채 빈 앱 덮개를 다시 그려도 inert 유지', w.inert());
  w.H.open = false; w.api.paint();
  w.OV.__h = '<aside class="drawer"></aside>'; w.bgInert(w.OV.__h);
  chk(all(w.inert(), true), 'B 앱 서랍 열림 = inert', w.inert());
  w.H.open = true; w.api.paint(); w.H.open = false; w.api.paint();
  chk(all(w.inert(), true), 'B 앱 서랍이 열린 채 패널을 열고 닫아도 inert 유지(둘 다 닫혀야 풂)', w.inert());
  w.OV.__h = ''; w.bgInert(w.OV.__h);
  chk(all(w.inert(), false), 'B 서랍까지 닫히면 풂', w.inert());
});
sec('C 닫기·잠금', () => {
  const w = world();
  w.api.openPanel();
  chk(all(w.inert(), true), 'C 열기 단추(openPanel) = inert', w.inert());
  w.api.closePanel();
  chk(w.focusLog.length === 1 && all(w.focusLog[0], false), 'C 닫기(Esc·바깥·닫기 단추) 뒤 칩 초점 = inert 가 이미 풀린 뒤', w.focusLog);
  w.H.open = true; w.api.paint(); w.api.lock();
  chk(!w.ids.tjhOverlay && all(w.inert(), false), 'C 앱 잠금(lock) = 패널 닫고 inert 풂', w.inert());
});
console.log(JSON.stringify(R));
'''


def run_js(js):
    node = T.node_bin("모달 inert 시험")
    if not node:
        return None
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path(), TJ_TEST_HEALTH=os.path.join(T.ROOT, "web", "v2", "health.js"))
    p = subprocess.run([node, "--input-type=module", "-"], input=js, capture_output=True, text=True, timeout=60, env=env)
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        T.chk(False, "node 실행", (p.stderr or "")[-1500:])
        return None
    return json.loads(out[-1])


R = run_js(JS)
for ok, msg, *d in (R or []):
    T.chk(ok, msg, d[0] if d else None)
T.chk(R is None or len(R) >= 10, "검사 줄 수(묶음이 실행 오류로 빠지지 않음)", len(R or []))
T.finish()

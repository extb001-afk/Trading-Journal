#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const B = cut('  function dayFrz(k, load) {', '  function evSkel(rows, heads) {');
const R = [], chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const S = { D: { todayKey: '10-22', builtAt: 7 }, tab: 'daily' };
const num = x => (isFinite(+x) ? +x : 0);
let SENT = 0, RENDER = 0, PEND = [];
// 응답을 손으로 풀어 준다(받는 사이 화면 세대 바꾸기)
const fetch = () => { SENT++; return new Promise(res => PEND.push(res)); };
const reply = (built, frz, ok = true, status = 200) => { const r = PEND.shift(); if (!r) return; r({ ok: status < 400, status, json: () => Promise.resolve(ok ? { ok: true, builtAt: built, days: {}, ...(frz ? { frz } : {}) } : null) }); };
const tick = async () => { for (let i = 0; i < 4; i++) await new Promise(r => setTimeout(r, 0)); };
const F = new Function('S', 'num', 'isoDay', 'fetch', 'onUnauthorized', 'render', B + '\nreturn { dayFrz, frzRow };')(S, num, k => '2026-' + k, fetch, () => {}, () => { RENDER++; });
const rec = (val, st) => ({ '2026-09-20': { r: { date: '09-20', val, att: { v: 2, mk: 1 } }, p: { date: '09-19', val: 90 }, at: 55, ...(st ? { st } : {}) } });
const C = () => S.dayFrz['2026-09-20'];

// B1 화면 7 · 응답 8
chk(F.dayFrz('09-20', true) === null && SENT === 1, 'B1 첫 호출 = 받는 중 · 한 번', SENT);
reply(8, rec(100, 's')); await tick();
chk(C().st !== 'ok' && F.dayFrz('09-20') === null && RENDER === 0, 'B1 화면 7 · 응답 8 = 정상 캐시 아님 · 값 안 붙임 · 다시 그리기 안 부름', [C(), RENDER]);
F.dayFrz('09-20', true);
chk(SENT === 2, 'B1 같은 화면 세대 다음 그리기 = 다시 받음(불일치는 캐시 안 함)', SENT);
reply(8, rec(100, 's')); await tick();
S.D.builtAt = 8;
F.dayFrz('09-20', true);
chk(SENT === 3, 'B1 화면이 8 이 되면 = 다시 받음', SENT);
reply(8, rec(100, 's')); await tick();
const x8 = F.dayFrz('09-20', true);
chk(C().st === 'ok' && C().at === 8 && x8 && x8.val === 100 && x8.delta === 10 && x8._frz.st === 's' && RENDER === 1 && SENT === 3,
  'B1 화면 8 + 응답 8 = 정상 캐시(값·표식) · 다시 그림 1번 · 같은 세대 = 다시 안 받음', [C(), RENDER, SENT]);

// B2 요청 8 → 받는 사이 화면 9 → 응답 8
S.D.builtAt = 9;
F.dayFrz('09-20', true);
chk(SENT === 4 && F.dayFrz('09-20', true) === x8 && SENT === 4, 'B2 새 세대 = 다시 받음(받는 중 = 한 번 · 그동안 직전 값)', SENT);
S.D.builtAt = 10;
reply(9, rec(120)); await tick();
chk(C().st !== 'ok' && F.dayFrz('09-20') === x8 && RENDER === 2, 'B2 요청 9 → 화면 10 → 응답 9 = 정상 캐시 아님(직전 값 유지) · 다시 그림(새 세대로 다시 받게)', [C(), RENDER]);
F.dayFrz('09-20', true);
chk(SENT === 5, 'B2 다시 그리기 = 새 세대로 다시 받음', SENT);
reply(10, rec(130)); await tick();
const x10 = F.dayFrz('09-20');
chk(C().st === 'ok' && C().at === 10 && x10.val === 130 && x10._frz.st === '', 'B2/B4 새 세대 응답 = 정상 · 표식 없는 기록은 표식 없이(옛 세대 s 안 섞임)', [C()]);

// B3 화면 11 · 응답 10(옛 세대)
S.D.builtAt = 11;
F.dayFrz('09-20', true);
reply(10, rec(130)); await tick();
chk(C().st !== 'ok' && SENT === 6, 'B3 화면 11 · 늦게 온 옛 세대 응답 10 = 정상 캐시 아님', [C(), SENT]);
F.dayFrz('09-20', true);
reply(11, rec(140, 's')); await tick();
chk(C().st === 'ok' && F.dayFrz('09-20').val === 140 && F.dayFrz('09-20')._frz.st === 's', 'B3/B4 맞는 세대에서만 새 값·새 표식', C());

// B5 오류 뒤 다시
const r0 = RENDER;
F.dayFrz('09-21', true);
reply(11, null, false, 500); await tick();
chk(S.dayFrz['2026-09-21'].st === 'err' && F.dayFrz('09-21') === null && RENDER === r0, 'B5 실패 = 값 없음 · 다시 그리기 안 부름', S.dayFrz['2026-09-21']);
const s0 = SENT;
F.dayFrz('09-21', true);
chk(SENT === s0 + 1, 'B5 같은 세대여도 오류 뒤 다음 그리기 = 다시 받음', SENT - s0);
reply(11, { '2026-09-21': rec(150)['2026-09-20'] }); await tick();
chk(S.dayFrz['2026-09-21'].st === 'ok' && F.dayFrz('09-21').val === 150, 'B5 다시 받아 성공 = 정상', S.dayFrz['2026-09-21']);
F.dayFrz('09-22', true);
{ const r = PEND.shift(); if (r) r(Promise.reject(new Error('net'))); } await tick();
chk(S.dayFrz['2026-09-22'].st === 'err', 'B5 전송 오류 = err', S.dayFrz['2026-09-22']);

// B6 잠금 뒤 도착 · 날짜마다 따로 · 정상 = 다시 안 받음
F.dayFrz('09-23', true);
S.dayFrz = null;
reply(11, { '2026-09-23': rec(1)['2026-09-20'] }); await tick();
chk(S.dayFrz === null, 'B6 잠금(캐시 비움) 뒤 도착 = 버림', S.dayFrz);
F.dayFrz('09-20', true);
reply(11, rec(140)); await tick();
const s1 = SENT;
F.dayFrz('09-20', true); F.dayFrz('09-20', true);
chk(SENT === s1 && F.dayFrz('10-22', true) === null && SENT === s1, 'B6 같은 세대 정상 = 다시 안 받음 · 오늘 = 안 받음', SENT - s1);
console.log(JSON.stringify(R));
'''
node = T.node_bin("동결 분해 받기 세대 확인")
if node:
    env = dict(os.environ, TJ_TEST_APP=T.app_js_path())
    p = subprocess.run([node, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=60)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        res = None
    chk(res is not None, "node 화면 함수 시험이 끝까지 돌았음", (p.stdout[-400:], p.stderr[-800:]))
    for ok, msg, dd in res or []:
        chk(ok, msg, dd)

T.finish()

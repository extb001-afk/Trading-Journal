#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

JS = r'''
import fs from 'node:fs';
import path from 'node:path';
const DIR = process.env.TJ_TEST_V2, FILES = ['app.css', 'mods.css', 'wow.css'];
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
// CSS → 규칙 목록 {file, sel, depth, line, decls:[[이름, 값]]} — 주석·따옴표 안 괄호는 건너뜀(선언 블록만 · @규칙 안 규칙은 depth 1+)
function rules(file) {
  const s = fs.readFileSync(path.join(DIR, file), 'utf8'), out = [], stack = [];
  let i = 0, start = 0, line = 1, startLine = 1;
  while (i < s.length) {
    const c = s[i];
    if (c === '/' && s[i + 1] === '*') { const j = s.indexOf('*/', i + 2); const e = j < 0 ? s.length : j + 2; for (let k = i; k < e; k++) if (s[k] === '\n') line++; i = e; continue; }
    if (c === '"' || c === "'") { let j = i + 1; while (j < s.length && s[j] !== c) { if (s[j] === '\\') j++; j++; } i = j + 1; continue; }
    if (c === '\n') line++;
    if (c === '{') { const sel = s.slice(start, i).replace(/\/\*[\s\S]*?\*\//g, '').split(';').pop().trim(); stack.push({ sel, at: i, line: startLine }); start = i + 1; startLine = line; }
    else if (c === '}') {
      const b = stack.pop(); if (!b) throw new Error(file + ' 닫는 괄호 짝 없음 ' + line);
      const body = s.slice(b.at + 1, i);
      if (!/[{]/.test(body.replace(/\/\*[\s\S]*?\*\//g, ''))) {
        const decls = body.replace(/\/\*[\s\S]*?\*\//g, '').split(';').map(x => x.trim()).filter(x => x.startsWith('--')).map(x => { const k = x.indexOf(':'); return [x.slice(0, k).trim(), x.slice(k + 1).trim()]; });
        out.push({ file, sel: b.sel, depth: stack.length, line: b.line, decls });
      }
      start = i + 1; startLine = line;
    } else if (c === ';' && !stack.length) { start = i + 1; startLine = line; }
    else if (/\s/.test(c) && start === i) { start = i + 1; startLine = line + (c === '\n' ? 0 : 0); }
    i++;
  }
  if (stack.length) throw new Error(file + ' 괄호가 안 닫힘');
  return out;
}
try {
  const all = FILES.flatMap(rules);
  const ROOT = ':root', LIGHT = 'html[data-theme="light"]';
  const root = all.filter(r => r.sel === ROOT), light = all.filter(r => r.sel === LIGHT);
  chk(root.length === 1 && root[0].file === 'app.css' && root[0].depth === 0 && root[0].line <= 100,
    '[1] 어두운 기본 토큰(:root) = app.css 맨 위 최상위 블록 하나', root.map(r => [r.file, r.line, r.depth]));
  chk(light.length === 1 && light[0].file === 'app.css' && light[0].depth === 0 && light[0].line <= 100,
    '[1] 밝은 테마 토큰(html[data-theme="light"]) = app.css 맨 위 최상위 블록 하나', light.map(r => [r.file, r.line, r.depth]));
  for (const [nm, rs] of [['어두운 기본', root], ['밝은 테마', light]]) {
    const seen = new Map(), dup = [];
    rs.forEach(r => r.decls.forEach(([k]) => { if (seen.has(k)) dup.push(k); seen.set(k, 1); }));
    chk(!dup.length && seen.size > 30, '[2] ' + nm + ' 토큰 블록 안 같은 변수 두 번 없음(충돌 = 버그)', { dup, n: seen.size });
  }
  const val = (rs, k) => { for (const r of rs) for (const [a, b] of r.decls) if (a === k) return b; return null; };
  const want = [['--c6', '#FF9E66', '#E8590C'], ['--c7', '#5DD3E8', '#0C8599'], ['--lvSafe', '#7C9CFF', '#3D63DD'], ['--lvTrack', null, '#E5E8ED'], ['--lvWarn', 'var(--warn)', null]];
  const got = want.map(([k]) => [k, val(root, k), val(light, k)]);
  chk(got.every(([k, d, l], i) => (want[i][1] == null || d === want[i][1]) && (want[i][2] == null || l === want[i][2]) && d != null),
    '[2] 합친 변수(구분색 c6·c7 · 레버리지 lv*) 값이 두 테마에 그대로', got);
} catch (e) { chk(false, 'CSS 읽기 실행 오류', String((e && e.stack) || e).slice(0, 300)); }
console.log(JSON.stringify(R));
'''


def run_js(js):
    node = T.node_bin("CSS 토큰 자리 시험")
    if not node:
        return None
    env = dict(os.environ, TJ_TEST_V2=os.path.join(T.ROOT, "web", "v2"))
    p = subprocess.run([node, "--input-type=module", "-"], input=js, capture_output=True, text=True, timeout=60, env=env)
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        T.chk(False, "node 실행", (p.stderr or "")[-1500:])
        return None
    return json.loads(out[-1])


R = run_js(JS)
for ok, msg, *d in (R or []):
    T.chk(ok, msg, d[0] if d else None)
T.chk(R is None or len(R) >= 5, "검사 줄 수(실행 오류로 빠지지 않음)", len(R or []))
T.finish()

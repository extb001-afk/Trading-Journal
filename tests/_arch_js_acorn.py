from __future__ import annotations

import json
import shutil
import subprocess

from _arch_js import Unit, js_units, unit_metrics

_ACORN_JS = r"""
const acorn = require('internal/deps/acorn/acorn/dist/acorn');
const walk = require('internal/deps/acorn/acorn-walk/dist/walk');
let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { buf += d; });
process.stdin.on('end', () => {
  const out = [];
  for (const text of JSON.parse(buf)) {
    const r = { fns: [], n1384: 0, esc: 0, err: null };
    try {
      const opt = t => ({ ecmaVersion: 'latest', sourceType: t, locations: true, allowHashBang: true });
      let ast;
      try { ast = acorn.parse(text, opt('script')); } catch (e) { ast = acorn.parse(text, opt('module')); }   // type="module" 블록
      const head = new Map(), spans = [];
      walk.full(ast, n => {
        const method = (n.type === 'Property' && (n.method || n.kind !== 'init')) || n.type === 'MethodDefinition';
        if (method) head.set(n.value, { line: n.loc.start.line, off: n.start });
      });
      walk.full(ast, n => {
        const fn = n.type === 'FunctionDeclaration' || n.type === 'FunctionExpression' || n.type === 'ArrowFunctionExpression';
        const kind = head.has(n) ? 'method' : n.type === 'FunctionDeclaration' ? 'decl'
          : n.type === 'ArrowFunctionExpression' ? 'arrow' : 'expr';
        if (fn && n.body.type === 'BlockStatement') {
          const h = head.get(n);
          spans.push({ s: h ? h.off : n.start, e: n.end, row: [h ? h.line : n.loc.start.line, n.loc.end.line, kind] });
        }
        if (n.type === 'Literal' && typeof n.value === 'number' && n.value === 1384) r.n1384++;
        if (n.type === 'Literal' && n.value === '&amp;') r.esc++;
        if (n.type === 'TemplateLiteral' && n.expressions.length === 0 && n.quasis[0].value.cooked === '&amp;') r.esc++;
      });
      spans.sort((a, b) => a.s - b.s || b.e - a.e);   // 부모 = 품는 가장 안쪽 함수(파이썬 _parents 와 같은 규칙)
      const st = [];
      for (const sp of spans) {
        while (st.length && st[st.length - 1].e < sp.s) st.pop();
        const p = st.length ? st[st.length - 1].row : [0, 0];
        r.fns.push(sp.row.concat([p[0], p[1]]));
        st.push(sp);
      }
    } catch (e) { r.err = String(e && e.message); }
    out.push(r);
  }
  process.stdout.write(JSON.stringify({ node: process.version, acorn: acorn.version, units: out }));
});
"""


def node_bin() -> str | None:
    return shutil.which("node")


def _node_run(payload: str, timeout: float):
    nb = node_bin()
    if not nb:
        return None, None
    try:
        p = subprocess.run([nb, "--expose-internals", "-e", _ACORN_JS], input=payload, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"node 실행 실패: {e}"
    if p.returncode != 0:
        return None, "node 내장 acorn 을 못 부름(internal 경로 — node 판에 따라 사라질 수 있음): " + (p.stderr or p.stdout)[-300:]
    try:
        return json.loads(p.stdout), None
    except ValueError:
        return None, "node 출력이 JSON 아님: " + p.stdout[-200:]


def acorn_report(units: list[Unit], timeout: float = 120.0):
    out, why = _node_run(json.dumps([u.text for u in units]), timeout)
    if out is None:
        return None if why is None else (None, why)
    return out


def acorn_diff(units: list[Unit], res: list[dict], report_units: list[dict]) -> list[dict]:
    from collections import Counter
    diff = []
    for u, r, a in zip(units, res, report_units):
        def par(f, fns=r["fns"], off=u.offset):
            p = f["parent"]
            return (fns[p]["start"] - off, fns[p]["end"] - off) if p >= 0 else (0, 0)
        py = Counter((f["start"] - u.offset, f["end"] - u.offset, f["kind"]) + par(f) for f in r["fns"])
        an = Counter(tuple(x) for x in a["fns"])
        if a["err"] or py != an or (r["esc"], r["n1384"]) != (a["esc"], a["n1384"]):
            diff.append({"원본": f"{u.path}+{u.offset}", "acorn 오류": a["err"], "파이썬만": sorted((py - an).elements())[:5],
                         "acorn 만": sorted((an - py).elements())[:5], "esc·1384(파이썬)": (r["esc"], r["n1384"]),
                         "esc·1384(acorn)": (a["esc"], a["n1384"])})
    return diff


def verify(root: str) -> tuple[str, list[dict]]:
    units = js_units(root)
    rep = acorn_report(units)
    if rep is None or isinstance(rep, tuple):
        return "파이썬 토크나이저 측정 · acorn 대조 못 함(" + ("node 없음" if rep is None else "내장 acorn 없음") + ")", []
    diff = acorn_diff(units, [unit_metrics(u) for u in units], rep["units"])
    return (f"파이썬 토크나이저 측정 · acorn {rep.get('acorn')} · node {rep.get('node')} 대조 " + ("일치" if not diff else "불일치")), diff

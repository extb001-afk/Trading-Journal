(function () {
  'use strict';
  const POLL_MS = 30000;
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = v => (window.__tj && typeof window.__tj.moneyTxt === 'function') ? window.__tj.moneyTxt(v) : String(v == null ? '' : v);
  const H = { data: null, err: null, at: 0, open: false, pop: false, inflight: false, showAllResolved: false, knownOpen: false, incOpen: new Set(), unitsAll: false };
  const bfInfo = () => { try { const f = window.TJ && window.TJ.bfInfo; return typeof f === 'function' ? f() : null; } catch (e) { return null; } };
  const bfRing = b => { const r = 5.5, c = 2 * Math.PI * r, p = Math.max(0, Math.min(100, b.pct)) / 100;
    return '<svg class="tjh-ring' + (b.stalled ? ' st' : '') + '" viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="' + r + '" fill="none" stroke-width="2" class="bg"/><circle cx="7" cy="7" r="' + r + '" fill="none" stroke-width="2" class="fg" stroke-dasharray="' + (c * Math.max(p, 0.04)).toFixed(2) + ' ' + c.toFixed(2) + '" transform="rotate(-90 7 7)"/></svg>'; };
  const isKnown = x => !!(x && x.known && x.level !== 'crit');
  const openNew = () => ((H.data && H.data.open) || []).filter(x => !isKnown(x));
  const openKnown = () => ((H.data && H.data.open) || []).filter(isKnown);
  const actTxt = t => String(t == null ? '' : t)
    .replace(/pm2 logs (tj-[a-z]+)(?:\s+--(?:err|lines\s+\d+))*/g, (a, u) => (UNIT_KO[u] || u) + ' 로그')
    .replace(/pm2 restart (tj-[a-z]+)/g, (a, u) => (UNIT_KO[u] || u) + ' 재시작')
    .replace(/pm2 monit/g, '메모리 추이');
  const LV = { ok: 0, warn: 1, crit: 2 };
  const LBL = { ok: '정상', warn: '주의', crit: '오류', unknown: '확인 불가' };
  const UNIT_KO = {
    'tj-evm': 'EVM 수집', 'tj-sol': 'Solana 수집', 'tj-bsc': 'BSC 수집', 'tj-core': '원장 처리', 'tj-web': '대시보드·시세',
    'tj-alert': '알림·감시', 'tj-review': '하루 리뷰', 'tj-ex': '업비트', 'tj-exf': '해외 거래소', system: '시스템'
  };

  const css = `
.tjh-btn{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 12px;border-radius:10px;border:1px solid var(--line2);background:var(--surface);color:var(--text2);font-size:13px;font-weight:700;white-space:nowrap;flex:none}
.tjh-btn:hover{color:var(--text);border-color:var(--text2)}
.tjh-btn[aria-expanded="true"]{border-color:var(--text2);background:var(--surface2)}
/* 디자인 d1(② 상태 칩 After): 오류·주의를 따로 — 색 점 + 글자, 사이 세로선(읽기 문자열은 ' · ') · 주황 = 외부 서비스 원인 */
.tjh-part{display:inline-flex;align-items:center;gap:6px}
.tjh-part i{width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.tjh-part.crit{color:var(--danger)} .tjh-part.warn{color:var(--warn)} .tjh-part.ext{color:var(--ext)} .tjh-part.known{color:var(--muted);font-weight:600}
.tjh-kn{display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;border-radius:10px;font-size:13px;font-weight:650;color:var(--muted);text-align:left}
.tjh-kn:hover{background:var(--surface2);color:var(--text2)} .tjh-kn .sp{flex:1}
.tjh-row.kn>i{background:var(--faint)} .tjh-row.kn .r1 b{color:var(--text2);font-weight:650}
.tjh-tgn{display:flex;align-items:center;gap:8px;padding:6px 10px 2px;font-size:12.5px;color:var(--muted)} .tjh-tgn button{color:var(--accent);font-weight:700;font-size:12.5px;white-space:nowrap;margin-left:auto}
.tjh-inc.kn{border-left-color:var(--line2)}
.tjh-sep{display:inline-block;width:1px;height:14px;background:var(--line2);font-size:0;color:transparent;overflow:hidden;flex:none}
.tjh-pop{position:fixed;z-index:72;width:470px;max-width:calc(100vw - 24px);box-sizing:border-box;background:var(--surface);border:1px solid var(--line2);border-radius:14px;box-shadow:var(--pop);padding:12px 8px 8px;display:flex;flex-direction:column;animation:tjhin .16s cubic-bezier(.2,.8,.2,1)}
@keyframes tjhin{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
.tjh-pop .ph{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding:0 10px 8px;font-size:12px;color:var(--faint)}
.tjh-pop .ph .lg{display:flex;align-items:center;gap:6px}
.tjh-pop .ph .lg i{width:8px;height:8px;border-radius:50%;background:var(--ext)}
.tjh-row{display:flex;gap:10px;padding:9px 10px;border-radius:10px}
.tjh-row.hi{background:var(--dangerBg)} .tjh-row.hi.ext{background:var(--extBg)}
.tjh-row.sep{border-top:1px solid var(--line);border-radius:0 0 10px 10px}
.tjh-row>i{width:8px;height:8px;border-radius:50%;margin-top:7px;flex:none;background:var(--warn)}
.tjh-row.crit>i{background:var(--danger)} .tjh-row.ext>i{background:var(--ext)}
.tjh-row .rb{display:flex;flex-direction:column;gap:1px;flex:1;min-width:0}
.tjh-row .r1{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.tjh-row .r1 b{font-size:14px;font-weight:700;color:var(--text)}
.tjh-row .r1 span{font-size:11.5px;font-weight:700;white-space:nowrap;color:var(--muted)}
.tjh-row .r1 span.ext{color:var(--ext)} .tjh-row .r1 span.own{color:var(--accent)}   /* 핫픽스 f5ui(A12): '내 계정'(마진 부채 등)은 외부 원인이 아니다 — 범례의 주황과 겹치지 않게 파랑 */
.tjh-pop .ph .lg i.w{background:var(--warn)}
.tjh-row .r2{font-size:12.5px;color:var(--muted);line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}
.tjh-pop .pf{display:flex;justify-content:flex-end;padding:8px 10px 2px;border-top:1px solid var(--line);margin-top:4px}
.tjh-pop .pf button{font-size:13px;font-weight:700;color:var(--accent)}
.tjh-pop .pf button:hover{text-decoration:underline}
.tjh-pop .ok{display:flex;align-items:center;gap:8px;padding:10px;color:var(--ok);font-weight:650;font-size:14px}
.tjh-btn .tjh-n{font-variant-numeric:tabular-nums}
.tjh-dot{width:9px;height:9px;border-radius:50%;flex:none;background:var(--ok);box-shadow:0 0 0 3px var(--okBg)}
.tjh-dot.warn{background:var(--warn);box-shadow:0 0 0 3px var(--warnBg)}
.tjh-dot.crit{background:var(--danger);box-shadow:0 0 0 3px var(--dangerBg)}
.tjh-dot.unknown,.tjh-dot.off{background:var(--faint);box-shadow:0 0 0 3px var(--surface3)}
.tjh-dot.sm{width:7px;height:7px;box-shadow:none}
.m-top .tjh-btn{height:32px;padding:0 9px;gap:6px}
.tjh-long{display:inline-flex;align-items:center;gap:8px}.tjh-short{display:none;align-items:center;gap:6px}
.top .tjh-btn .tjh-long{display:none}.top .tjh-btn .tjh-short{display:inline-flex}   /* search1006: 머리 줄(최대 1320px)에 '검색' 칸 자리 — 데스크톱도 '● 4·2'(누르면 펼침) */
.tjh-bg{position:fixed;inset:0;background:var(--dim);z-index:70}
.tjh-panel{position:fixed;top:0;right:0;bottom:0;width:500px;max-width:100%;background:var(--bg);border-left:1px solid var(--line);z-index:71;overflow-y:auto;padding:22px 24px 40px;box-shadow:var(--pop)}
.tjh-hd{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.tjh-hd h3{font-size:19px;font-weight:750;letter-spacing:-.02em}
.tjh-sub{font-size:13px;color:var(--muted);margin-bottom:18px}
.tjh-sec{margin-top:22px}
.tjh-sec>.tt{font-size:13px;font-weight:700;color:var(--text2);margin-bottom:10px;display:flex;align-items:center;gap:8px}
.tjh-sec>.tt .n{color:var(--muted);font-weight:600}
.tjh-inc{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px;border-left:4px solid var(--warn)}
.tjh-inc.crit{border-left-color:var(--danger)}
.tjh-inc .t1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tjh-inc .t1 b{font-size:15px;font-weight:700}
.tjh-inc .d{font-size:13.5px;color:var(--text2);margin-top:6px;line-height:1.55;word-break:break-word}
.tjh-inc .m{font-size:12.5px;color:var(--muted);margin-top:6px;display:flex;gap:6px 12px;flex-wrap:wrap}
.tjh-inc .act{font-size:13px;margin-top:8px;padding:8px 10px;border-radius:9px;background:var(--surface2);color:var(--text2);line-height:1.5;word-break:break-word}
.tjh-inc .act b{color:var(--text);font-weight:650}
.tjh-empty{display:flex;align-items:center;gap:10px;padding:14px 16px;border-radius:14px;background:var(--okBg);color:var(--ok);font-weight:650;font-size:14px}
.tjh-bnr{padding:12px 14px;border-radius:12px;background:var(--dangerBg);color:var(--danger);font-size:13.5px;margin-bottom:12px;line-height:1.5}
.tjh-bnr.g{background:var(--surface2);color:var(--text2)}
.tjh-watch{font-size:13px;color:var(--text2);display:flex;gap:8px;align-items:baseline;padding:6px 0;border-bottom:1px solid var(--line)}
.tjh-watch:last-child{border-bottom:0}
.tjh-tbl{width:100%;border-collapse:collapse;font-size:13.5px}
.tjh-tbl th{font-size:12px;color:var(--muted);font-weight:600;text-align:left;padding:0 8px 8px 0;border:0;border-bottom:1px solid var(--line);white-space:nowrap}
.tjh-tbl td{padding:10px 8px 10px 0;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}
.tjh-tbl tr:last-child td{border-bottom:0}
.tjh-u{display:flex;align-items:center;gap:8px;white-space:nowrap}
.tjh-u b{font-weight:700;font-size:13.5px}
.tjh-k{font-size:12px;color:var(--muted);padding-left:15px;margin-top:1px}
.tjh-srcs{display:flex;flex-wrap:wrap;gap:5px}
.tjh-src{display:inline-flex;align-items:center;gap:5px;font-size:12px;padding:2px 8px;border-radius:99px;background:var(--surface2);color:var(--text2);white-space:nowrap;font-variant-numeric:tabular-nums}
.tjh-src.warn{background:var(--warnBg);color:var(--warn)} .tjh-src.crit{background:var(--dangerBg);color:var(--danger)} .tjh-src.off{color:var(--faint)}
.tjh-res{display:flex;gap:10px;align-items:baseline;font-size:13px;padding:7px 0;border-bottom:1px solid var(--line);color:var(--text2)}
.tjh-res:last-child{border-bottom:0}
.tjh-res .w{margin-left:auto;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.tjh-tg{display:flex;align-items:center;gap:10px;font-size:13.5px;padding:12px 14px;border-radius:12px;background:var(--surface);border:1px solid var(--line)}
.tjh-pill{display:inline-block;font-size:12px;font-weight:700;padding:2px 8px;border-radius:6px;white-space:nowrap}
.tjh-pill.ok{background:var(--okBg);color:var(--ok)} .tjh-pill.warn{background:var(--warnBg);color:var(--warn)} .tjh-pill.crit{background:var(--dangerBg);color:var(--danger)} .tjh-pill.unknown,.tjh-pill.g{background:var(--surface2);color:var(--muted)}
/* ★screens1005★ 문제 = 한 줄(수준 점 · 제목 · 배지 하나) + 누르면 상세 · 정상 유닛 접기 · 과거 거래 불러오기(칩 고리 · 펼침 줄 · 패널 칸) */
.tjh-inc{padding:0;border-left-width:4px;overflow:hidden}
.tjh-ih{display:flex;align-items:center;gap:10px;width:100%;min-height:48px;padding:10px 14px;text-align:left;font-size:14px;color:var(--text)}
.tjh-ih b{font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tjh-ih .sp{flex:1}
.tjh-ih .tjh-pill{flex:none}
.tjh-lv{width:8px;height:8px;border-radius:50%;flex:none;background:var(--warn)}
.tjh-inc.crit .tjh-lv{background:var(--danger)} .tjh-inc.kn .tjh-lv{background:var(--faint)}
.tjh-cv{flex:none;color:var(--faint);transition:transform .2s cubic-bezier(.2,.8,.2,1)}
.tjh-inc.open .tjh-cv{transform:rotate(180deg)}
.tjh-ib{padding:0 14px 14px 32px;animation:tjhin .18s cubic-bezier(.2,.8,.2,1)}
.tjh-ib .d{margin-top:0}
.tjh-pill.ext{background:var(--extBg);color:var(--ext)} .tjh-pill.own{background:var(--accentBg);color:var(--accent)}
.tjh-okall{display:flex;align-items:center;gap:8px;width:100%;min-height:44px;margin-top:8px;padding:10px 12px;border-radius:12px;background:var(--surface);border:1px solid var(--line);text-align:left;font-size:13.5px;color:var(--text2)}
.tjh-okall:hover{border-color:var(--line2)}
.tjh-okall .cap{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;color:var(--muted)}
.tjh-okall .sp{flex:1}
.tjh-ring{flex:none;display:inline-block;vertical-align:-2px}
.tjh-ring .bg{stroke:var(--line2)} .tjh-ring .fg{stroke:var(--warn)} .tjh-ring.st .fg{stroke:var(--muted)}
.tjh-part.bf{color:var(--text2);font-weight:650} .tjh-part.bf.st{color:var(--muted)}
@media (max-width:1499px){ .tjh-part.bf .bfw{display:none} }   /* 좁은 머리 줄 = 고리 + % (전체 문장은 칩 title·펼침) */
.tjh-okall b{white-space:nowrap}
.tjh-bfl{display:flex;align-items:center;gap:8px;width:100%;padding:9px 10px;margin:0 0 4px;border-radius:10px;background:var(--surface2);font-size:13px;color:var(--text2);text-align:left}
.tjh-bfl:hover{color:var(--text)} .tjh-bfl .sp{flex:1}
.tjh-bf .tt{gap:6px}
.tjh-bfb{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 14px;font-size:13px;color:var(--text2);line-height:1.55}
.tjh-bfb .bar{height:6px;border-radius:99px;background:var(--surface3);overflow:hidden;margin:2px 0 8px}
.tjh-bfb .bar i{display:block;height:100%;border-radius:99px;background:var(--warn)}
.tjh-bfb .bar.st i{background:var(--muted)}
.tjh-bfb .j b{color:var(--text)}
@media (max-width:640px){
  .tjh-pop{left:0!important;right:0!important;top:auto!important;bottom:0;width:100%;max-width:none;max-height:80vh;overflow:auto;border-radius:20px 20px 0 0;border-width:1px 0 0;padding:14px 10px calc(14px + env(safe-area-inset-bottom))}
  .tjh-pbg{position:fixed;inset:0;background:var(--dim);z-index:71}
  .tjh-panel{top:auto;left:0;right:0;width:100%;max-height:88vh;border-left:0;border-top:1px solid var(--line);border-radius:20px 20px 0 0;padding:18px 16px calc(28px + env(safe-area-inset-bottom))}
  .tjh-tbl thead{display:none}
  .tjh-tbl tr{display:block;padding:10px 0;border-bottom:1px solid var(--line)}
  .tjh-tbl tr:last-child{border-bottom:0}
  .tjh-tbl td{display:block;padding:2px 0;border:0}
  .tjh-tbl td.lg{font-size:12px;color:var(--muted);width:auto!important}
  .tjh-tbl td{width:auto!important}
  .tjh-k{display:inline;padding-left:6px}
  .tjh-tbl td:first-child{display:flex;align-items:baseline}
}`;

  const nowS = () => Date.now() / 1000;
  function ago(sec) {
    if (sec == null || !isFinite(sec)) return '—';
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return sec + '초';
    if (sec < 5400) return Math.floor(sec / 60) + '분';
    if (sec < 172800) { const mins = Math.floor(sec / 60), h = Math.floor(mins / 60), m = mins % 60; return h + '시간' + (m && h < 10 ? ' ' + m + '분' : ''); }
    return Math.floor(sec / 86400) + '일';
  }
  function hm(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000), p = n => (n < 10 ? '0' : '') + n;
    return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  const LVW = (v, dflt) => (v === 'ok' || v === 'warn' || v === 'crit' || v === 'off' || v === 'unknown') ? v : dflt;
  function overall() {
    if (H.err && !H.data) return 'unknown';
    const d = H.data;
    if (!d) return 'unknown';
    return LVW(d.overall, 'unknown');
  }
  const isLocked = () => !!(H.locked || (window.TJ && typeof window.TJ.isLocked === 'function' && window.TJ.isLocked()));
  function lock() {
    H.locked = true; H.data = null; H.err = null; H.at = 0; H.pop = false; H.open = false; H.knownOpen = false; H.showAllResolved = false;
    const ov = document.getElementById('tjhOverlay'); if (ov) ov.remove();
    const pp = document.getElementById('tjhPop'); if (pp) pp.remove();
    try { chrome(); } catch (e) {  }
  }
  async function load() {
    if (H.inflight || isLocked()) return;
    H.inflight = true;
    try {
      const r = await fetch('/api/health', { cache: 'no-store' });
      if (r.status === 401 && typeof window.__tjLoginCheck === 'function' && window.__tjLoginCheck(r)) return;
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      if (isLocked()) { H.data = null; return; }
      H.data = j.health || null;
      H.err = null;
      H.at = Date.now();
    } catch (e) {
      H.err = (e && e.message) || String(e);
    } finally {
      H.inflight = false;
    }
    if (isLocked()) return;
    paint();
  }

  function counts() {
    const op = openNew();
    return { crit: op.filter(x => x.level === 'crit').length, warn: op.filter(x => x.level !== 'crit').length, known: openKnown().length };
  }
  function splitLabel(c) {
    return [c.crit ? LBL.crit + ' ' + c.crit : '', c.warn ? LBL.warn + ' ' + c.warn : ''].filter(Boolean).join(' · ');
  }
  function extOf(x) {
    const c = String(x.check || x.id || ''), t = String(x.title || '') + ' ' + String(x.detail || '');
    if (!/^quota:/.test(c) && !/\(외부\)/.test(t)) return null;
    return { src: /helius/i.test(c + ' ' + t) ? 'Helius' : /블록스카웃|blockscout/i.test(t) ? 'blockscout' : '' };
  }
  function partTone(lv) {
    const op = openNew().filter(x => (x.level === 'crit') === (lv === 'crit'));
    return op.length && op.every(x => extOf(x)) ? 'ext' : lv;
  }
  function btnHTML(mobile) {
    const b9 = bfInfo(), bfP = b9 ? (mobile ? bfRing(b9) : '<span class="tjh-sep" aria-hidden="true"> · </span><span class="tjh-part bf' + (b9.stalled ? ' st' : '') + '">' + bfRing(b9) + '<span class="tjh-n"><span class="bfw">과거 </span>' + b9.pct + '%' + (b9.stalled ? '<span class="bfw"> 멈춤</span>' : '') + '</span></span>') : '';
    return btnCore(mobile) + bfP;
  }
  function btnCore(mobile) {
    const o = overall(), c = counts();
    const n = c.crit + c.warn;
    const col = k => 'var(--' + ({ crit: 'danger', warn: 'warn', ext: 'ext' }[partTone(k)]) + ')';
    const dotC = n ? o : 'off';
    const shortH = () => { const part = (k, v) => '<span style="color:' + col(k) + '">' + v + '</span>';
      return '<span class="tjh-dot ' + dotC + '"></span><span class="tjh-n">' + [c.crit ? part('crit', c.crit) : '', c.warn ? part('warn', c.warn) : '', c.known ? '<span style="color:var(--muted)" title="알려진 사항">' + c.known + '</span>' : ''].filter(Boolean).join('<span style="color:var(--muted);margin:0 2px">·</span>') + '</span>'; };
    if (mobile && o !== 'unknown' && (n || c.known)) return shortH();
    if (o !== 'unknown' && (n || c.known)) {
      const part = (k, v) => '<span class="tjh-part ' + partTone(k) + '"><i></i><span class="tjh-n">' + LBL[k] + ' ' + v + '</span></span>';
      return '<span class="tjh-long">' + [c.crit ? part('crit', c.crit) : '', c.warn ? part('warn', c.warn) : '', c.known ? '<span class="tjh-part known"><i></i><span class="tjh-n">알려진 사항 ' + c.known + '</span></span>' : ''].filter(Boolean).join('<span class="tjh-sep" aria-hidden="true"> · </span>') + '</span><span class="tjh-short" aria-hidden="true">' + shortH() + '</span>';
    }
    const label = o === 'unknown' ? (mobile ? '' : '확인 불가') : (mobile ? '' : '정상');
    return '<span class="tjh-dot ' + o + '"></span>' + (label ? '<span class="tjh-n">' + esc(label) + '</span>' : '');
  }
  function btnTitle() {
    const o = overall(), c = counts();
    const ex = lv => partTone(lv) === 'ext' ? '(외부 원인)' : '';
    const b9 = bfInfo();
    return '시스템 상태: ' + (c.crit + c.warn ? LBL[o] : c.known ? '새 문제 없음' : LBL[o]) + (c.crit ? ' · 오류 ' + c.crit + '건' + ex('crit') : '') + (c.warn ? ' · 주의 ' + c.warn + '건' + ex('warn') : '') + (c.known ? ' · 알려진 사항 ' + c.known + '건(오래 지속 · 판정은 그대로)' : '')
      + (b9 ? ' · 과거 거래 불러오는 중 ' + b9.pct + '%' + (b9.stalled ? '(멈춤)' : '') : '');
  }
  function popHTML() {
    const d = H.data;
    if (!d) return '<div class="ph"><span>' + (H.err ? '상태를 불러오지 못했습니다 · ' + esc(H.err) : '불러오는 중…') + '</span></div>' + popFoot();
    const op = openNew().slice().sort((a, b) => ((b.level === 'crit') - (a.level === 'crit')) || ((extOf(b) ? 1 : 0) - (extOf(a) ? 1 : 0)));
    const kn = openKnown();
    const anyExt = op.some(x => extOf(x));
    const age = d.updatedAt ? nowS() - d.updatedAt : null;
    const head = '<div class="ph"><span>' + (d.interval || 60) + '초마다 판정 · ' + (age == null ? '—' : age < 60 ? '방금 전' : esc(ago(age)) + ' 전') + '</span>'
      + (anyExt ? '<span class="lg"><i></i>주황 = 외부 서비스 원인' + (op.some(x => !extOf(x) && x.level !== 'crit') ? ' <i class="w"></i>노랑 = 주의(내 계정·데이터)' : '(내 데이터 문제 아님)') + '</span>' : '') + '</div>';
    let prevExt = null;
    const rows = op.map((x, i) => {
      const e = extOf(x), lv = x.level === 'crit' ? 'crit' : 'warn';
      const own = /^debt:/.test(String(x.check || ''));
      const tag = e ? '<span class="ext">외부' + (e.src ? ' · ' + esc(e.src) : '') + '</span>' : own ? '<span class="own">내 계정</span>' : '<span>' + esc(UNIT_KO[x.unit] || x.unit || '') + '</span>';
      const sep = i > 0 && prevExt && !e; prevExt = !!e;
      return '<div class="tjh-row ' + lv + (e ? ' ext' : '') + (lv === 'crit' ? ' hi' : '') + (sep ? ' sep' : '') + '"><i></i><div class="rb"><div class="r1"><b>' + LBL[lv] + ' · ' + esc(money(x.title)) + '</b>' + tag + '</div>'
        + '<span class="r2" title="' + esc(money(x.detail)) + '">' + esc(money(x.detail)) + '</span></div></div>';
    }).join('');
    const knH = kn.length ? '<button class="tjh-kn" data-h="known" aria-expanded="' + H.knownOpen + '"><span class="pvx">알려진 사항 ' + kn.length + '</span><span class="sp"></span><span>' + (H.knownOpen ? '접기' : '오래 지속 · 판정은 그대로 ›') + '</span></button>'
      + (H.knownOpen ? kn.map(x => '<div class="tjh-row kn"><i></i><div class="rb"><div class="r1"><b>' + esc(money(x.title)) + '</b><span>' + esc(x.known) + '</span></div><span class="r2" title="' + esc(money(x.detail)) + '">' + esc(money(x.detail)) + '</span></div></div>').join('') : '') : '';
    const b9 = bfInfo();
    const bfH = b9 ? '<button class="tjh-bfl" data-h="full" title="과거 거래 불러오기 — 작업별 진행은 전체 상태에서">' + bfRing(b9) + '<span>과거 거래 불러오는 중 <b class="pvx">' + b9.pct + '%' + (b9.stalled ? ' · 멈춤' : '') + '</b></span><span class="sp"></span><span class="pvx">' + (b9.n ? '작업 ' + b9.n + '개 ›' : '자세히 ›') + '</span></button>' : '';
    return head + bfH + (rows || '<div class="ok"><span class="tjh-dot"></span>' + (kn.length ? '새 문제가 없습니다' : '열린 문제가 없습니다') + '</div>') + knH + tgNote() + popFoot();
  }
  function tgNote() {
    const t = (H.data && H.data.telegram) || null;
    return t && !t.configured ? '<div class="tjh-tgn"><span>알림 봇 미연결 — 오류가 떠도 알림이 안 가요</span><button data-h="tg">설정에서 연결 ›</button></div>' : '';
  }
  function popFoot() { return '<div class="pf"><button data-h="full">유닛별 상태 · 최근 복구 · 알림 ›</button></div>'; }
  function incHTML(x, compact, known) {
    const lv = x.level === 'crit' ? 'crit' : 'warn';
    const id = String(x.id || x.check || x.title || ''), open = (lv === 'crit' && !known) !== H.incOpen.has(id);
    const since = x.since || x.opened;
    const tgOn = !!(H.data && H.data.telegram && H.data.telegram.configured);
    const tg = x.telegram === false ? '대시보드 표시만' : x.notified ? '텔레그램 알림 보냄' : (lv === 'crit' && tgOn ? '텔레그램 대기' : '대시보드 표시만');
    const e = extOf(x), own = /^debt:/.test(String(x.check || ''));
    const badge = known ? '<span class="tjh-pill g">' + esc(x.known || '알려진 사항') + '</span>' : e ? '<span class="tjh-pill ext">외부' + (e.src ? ' · ' + esc(e.src) : '') + '</span>' : own ? '<span class="tjh-pill own">내 계정</span>' : '<span class="tjh-pill g" title="' + esc(x.unit) + '">' + esc(UNIT_KO[x.unit] || x.unit || '') + '</span>';
    const chev = '<svg class="tjh-cv" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
    return '<div class="tjh-inc ' + lv + (known ? ' kn' : '') + (open ? ' open' : '') + '"><button class="tjh-ih" data-h="inc" data-v="' + esc(id) + '" aria-expanded="' + open + '"><i class="tjh-lv"></i><b>' + (known ? '' : LBL[lv] + ' · ') + esc(money(x.title)) + '</b><span class="sp"></span>' + badge + chev + '</button>'
      + (open ? '<div class="tjh-ib"><div class="d">' + esc(money(x.detail)) + '</div>'
        + '<div class="m"><span>' + esc(x.unit) + '</span><span>시작 ' + esc(hm(since)) + ' · ' + esc(ago(nowS() - since)) + '째</span><span>' + esc(tg) + '</span></div>'
        + (compact ? '' : (x.action ? '<div class="act" title="' + esc(x.action) + '"><b>조치</b> · ' + esc(actTxt(x.action)) + '</div>' : '')) + '</div>' : '') + '</div>';
  }
  function unitsHTML() {
    const us = (H.data && H.data.units) || [];
    if (!us.length) return '<div class="tjh-bnr g">유닛 정보 없음</div>';
    const pvc = t => /[$₩]/.test(String(t || '')) ? '' : ' class="pvx"';
    const srcLv = s0 => s0.level === 'crit' ? 'crit' : s0.level === 'warn' ? 'warn' : s0.level == null ? 'off' : '';
    const othLv = o => o.level === 'off' || o.level == null ? 'off' : o.level === 'ok' ? '' : LVW(o.level, 'off');
    const bad = u => { const lvl = u.ignored ? 'off' : LVW(u.level || 'ok', 'off'); return (lvl !== 'ok' && lvl !== 'off') || (u.sources || []).some(x => srcLv(x) === 'crit' || srcLv(x) === 'warn') || (u.other || []).some(o => othLv(o) === 'crit' || othLv(o) === 'warn'); };
    const row = (u, all) => {
      const p = u.proc;
      const ps = !p ? '—' : (p.status === 'online' ? '실행 중' : (p.status || '—'));
      const sub = [p && p.restarts ? '재시작 ' + p.restarts : '', u.lastLog ? '로그 ' + ago(nowS() - u.lastLog) + ' 전' : '', u.errors60 ? '오류 ' + u.errors60 + '/시' : ''].filter(Boolean).join(' · ');
      const lvl = u.ignored ? 'off' : LVW(u.level || 'ok', 'off');
      let okN = 0;
      const srcs = (u.sources || []).map(s0 => {
        const l = srcLv(s0);
        if (!all && !l) { okN++; return ''; }
        const st9 = s0.label + ' ' + (s0.age != null ? ago(s0.age) : String(s0.id || '').indexOf('inbox:') === 0 ? (s0.level === 'ok' ? '밀림 없음' : '밀림') : '—');
        return '<span class="tjh-src ' + l + '" title="' + esc(money(s0.detail)) + '"><span class="tjh-dot sm ' + (l || 'ok') + '"></span><span' + pvc(st9) + '>' + esc(st9) + '</span></span>';
      }).join('') + (u.other || []).map(o => { const l = othLv(o); if (!all && !l) { okN++; return ''; } const ct9 = money(o.chip || o.title); return '<span class="tjh-src ' + l + '" title="' + esc(money(o.detail)) + '"><span class="tjh-dot sm ' + (l || 'ok') + '"></span><span' + pvc(ct9) + '>' + esc(ct9) + '</span></span>'; }).join('')
        + (okN ? '<span class="tjh-src pvx"><span class="tjh-dot sm ok"></span>정상 ' + okN + '</span>' : '');
      return '<tr data-anc="unit:' + esc(u.unit) + '"><td style="width:118px"><div class="tjh-u"><span class="tjh-dot sm ' + lvl + '"></span><b>' + esc(u.unit) + '</b></div><div class="tjh-k">' + esc(UNIT_KO[u.unit] || '') + '</div></td>'
        + '<td class="lg pvx" style="width:112px">' + esc(ps) + (sub ? '<div class="cap" style="font-size:12px">' + esc(sub) + '</div>' : '') + '</td>'
        + '<td><div class="tjh-srcs">' + (srcs || '<span class="tjh-src off">추적 소스 없음</span>') + '</div></td></tr>';
    };
    const badU = us.filter(bad), okU = us.filter(u => !bad(u));
    const list = H.unitsAll ? us.map(u => row(u, true)) : badU.map(u => row(u, false));
    const okBtn = okU.length ? '<button class="tjh-okall" data-h="units" aria-expanded="' + H.unitsAll + '"><span class="tjh-dot sm ok"></span><b class="pvx">' + (H.unitsAll ? '정상만 접기' : '정상 ' + okU.length + '개') + '</b><span class="cap ell">' + (H.unitsAll ? '문제 있는 유닛만 보기' : esc(okU.map(u => UNIT_KO[u.unit] || u.unit).join(' · '))) + '</span><span class="sp"></span><span class="pvx">' + (H.unitsAll ? '‹' : '›') + '</span></button>' : '';
    return (list.length ? '<table class="tjh-tbl"><thead><tr><th>유닛</th><th>프로세스</th><th>데이터 신선도</th></tr></thead><tbody>' + list.join('') + '</tbody></table>' : '') + okBtn;
  }
  function tgHTML() {
    const t = (H.data && H.data.telegram) || {};
    if (!t.configured) return '<div class="tjh-tg"><span class="tjh-dot off"></span><div><b>텔레그램 미연결</b><div class="cap">연결하면 오류(빨강)만 알림으로 받습니다 · 주의(주황)는 이 화면에만</div></div></div>';
    const bad = t.consecFail > 0;
    return '<div class="tjh-tg"><span class="tjh-dot ' + (bad ? 'crit' : 'ok') + '"></span><div><b>텔레그램 연결됨</b><div class="cap">'
      + (bad ? '최근 발송 실패 ' + t.consecFail + '회' + (t.lastError ? ' · ' + esc(t.lastError) : '') : (t.lastOk ? '마지막 발송 ' + esc(ago(nowS() - t.lastOk)) + ' 전' : '아직 발송 없음'))
      + ' · 오류(빨강)만 알림, 6시간마다 리마인드, 09시 요약' + (t.queued ? ' · 대기 ' + t.queued + '통' : '') + '</div></div></div>';
  }
  function resolvedHTML(limit) {
    const rs = (H.data && H.data.resolved) || [];
    if (!rs.length) return '<div class="cap">최근 7일 복구 기록 없음</div>';
    const shown = rs.slice(0, limit);
    return shown.map(x => '<div class="tjh-res"><span class="tjh-dot sm ' + (x.peak === 'crit' ? 'crit' : 'warn') + '"></span><span><b>' + esc(x.unit) + '</b> · ' + esc(money(x.title)) + '</span><span class="w">' + esc(hm(x.resolved)) + ' 복구 · ' + esc(ago((x.resolved || 0) - (x.since || x.opened || 0))) + '</span></div>').join('')
      + (rs.length > limit ? '<div style="margin-top:8px"><button class="link" data-h="moreRes">' + (rs.length - limit) + '건 더 보기</button></div>' : '');
  }
  function headerLine() {
    const d = H.data;
    if (!d) return H.err ? '상태를 불러오지 못했습니다 · ' + esc(H.err) : '불러오는 중…';
    return '마지막 점검 ' + (d.updatedAt ? esc(ago(nowS() - d.updatedAt)) + ' 전' : '—') + ' · 60초마다 점검';
  }
  function bodyHTML(inSettings) {
    const d = H.data;
    let h = '';
    if (!d) return '<div class="tjh-bnr g">' + (H.err ? '상태를 불러오지 못했습니다 — ' + esc(H.err) : '불러오는 중…') + '</div>';
    if (d.note) h += '<div class="tjh-bnr g">' + esc(d.note) + '</div>';
    const op = openNew(), kn = openKnown();
    const crit = op.filter(x => x.level === 'crit'), warn = op.filter(x => x.level !== 'crit');
    h += '<div class="tjh-sec"><div class="tt">열린 문제 <span class="n pvx">' + op.length + '</span>' + (op.length ? '<span class="n">· 누르면 설명·조치</span>' : '') + '</div>'
      + (op.length ? crit.concat(warn).map(x => incHTML(x, false)).join('') : '<div class="tjh-empty"><span class="tjh-dot"></span>' + (kn.length ? '새 문제가 없습니다' : '열린 문제가 없습니다') + '</div>') + '</div>';
    if (kn.length) h += '<div class="tjh-sec"><button class="tt tjh-kn" style="padding:0;margin-bottom:10px" data-h="known" aria-expanded="' + H.knownOpen + '">알려진 사항 <span class="n pvx">' + kn.length + ' · 오래 지속 · 판정은 그대로</span><span class="sp"></span><span class="n pvx">' + (H.knownOpen ? '접기' : '펼치기') + '</span></button>'
      + (H.knownOpen ? kn.map(x => incHTML(x, false, true)).join('') : '') + '</div>';
    const b9 = bfInfo();
    if (b9) h += '<div class="tjh-sec tjh-bf"><div class="tt">' + bfRing(b9) + '과거 거래 불러오기 <span class="n pvx">' + b9.pct + '%' + (b9.stalled ? ' · 멈춤' : '') + '</span></div>' + b9.html + '</div>';
    const wt = (d.watching || []).filter(x => !x.suppressed);
    const sup = (d.watching || []).filter(x => x.suppressed);
    if (wt.length || sup.length) {
      h += '<div class="tjh-sec"><div class="tt">관찰 중 <span class="n pvx">아직 지속 조건 전 · 알림 없음</span></div>'
        + wt.concat(sup).map(x => '<div class="tjh-watch"><span class="tjh-dot sm ' + (x.suppressed ? 'off' : LVW(x.level, 'off')) + '"></span><span><b>' + esc(x.unit) + '</b> · ' + esc(money(x.title)) + ' <span class="cap">' + esc(x.suppressed ? '(' + x.suppressed + ' — 원인 쪽에서 추적)' : x.detail) + '</span></span></div>').join('') + '</div>';
    }
    h += '<div class="tjh-sec"><div class="tt">유닛별 상태·신선도</div>' + unitsHTML() + '</div>';
    h += '<div class="tjh-sec"><div class="tt">최근 복구</div>' + resolvedHTML(H.showAllResolved ? 20 : (inSettings ? 5 : 8)) + '</div>';
    h += '<div class="tjh-sec"><div class="tt">알림</div>' + tgHTML() + '</div>';
    return h;
  }
  function panelHTML() {
    const o = overall();
    return '<div class="tjh-bg" data-h="close"></div><div class="tjh-panel" role="dialog" aria-modal="true" aria-labelledby="tjhTitle">'
      + '<div class="tjh-hd"><h3 id="tjhTitle">시스템 상태</h3><span class="tjh-pill ' + (counts().crit + counts().warn || !counts().known ? o : 'g') + '">' + (counts().crit + counts().warn || !counts().known ? LBL[o] : '새 문제 없음') + '</span><span class="sp" style="flex:1"></span>'
      + '<button class="iconbtn" data-h="refresh" aria-label="다시 점검 결과 불러오기" title="새로고침"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg></button>'
      + '<button class="iconbtn" data-h="close" id="tjhClose" aria-label="닫기"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>'
      + '<div class="tjh-sub">' + headerLine() + '</div>' + bodyHTML(false) + '</div>';
  }
  function summary() {
    const c = counts(), o = overall();
    return { loaded: !!H.data, err: H.err || '', overall: o, crit: c.crit, warn: c.warn, known: c.known, label: c.crit + c.warn ? splitLabel(c) : c.known ? '알려진 사항 ' + c.known : LBL[o],
      ext: (c.crit + c.warn) > 0 && openNew().every(x => extOf(x)), tg: !!(H.data && H.data.telegram && H.data.telegram.configured) };
  }

  function ensureStyle() {
    if (document.getElementById('tjh-css')) return;
    const s = document.createElement('style');
    s.id = 'tjh-css';
    s.textContent = css;
    document.head.appendChild(s);
  }
  function ensureBtn(host, before, mobile) {
    if (!host) return null;
    let b = host.querySelector(':scope > .tjh-btn');
    if (!b) {
      b = document.createElement('button');
      b.className = 'tjh-btn pvx';
      b.setAttribute('data-h', 'pop');
      b.setAttribute('aria-haspopup', 'dialog');
      host.insertBefore(b, before && before.parentNode === host ? before : null);
    }
    b.innerHTML = btnHTML(mobile);
    b.title = btnTitle();
    b.setAttribute('aria-label', btnTitle());
    b.setAttribute('aria-expanded', H.pop || H.open ? 'true' : 'false');
    b.setAttribute('data-h', 'pop');
    return b;
  }
  function chrome() {
    ensureStyle();
    const top = document.querySelector('.top .in');
    ensureBtn(top, document.getElementById('themeBtn'), false);
    const mt = document.getElementById('mtop');
    if (mt) ensureBtn(mt, mt.querySelector('.curb') || mt.querySelector('.iconbtn[data-a="theme"]'), true);
  }
  function view(tab, el) { void tab; void el; }
  function paint() {
    chrome();
    try { window.dispatchEvent(new Event('tj:health')); } catch (e) {  }
    const ov = document.getElementById('tjhOverlay');
    if (H.open) {
      const scrollTop = ov && ov.querySelector('.tjh-panel') ? ov.querySelector('.tjh-panel').scrollTop : 0;
      let host = ov;
      if (!host) { host = document.createElement('div'); host.id = 'tjhOverlay'; document.body.appendChild(host); }
      host.innerHTML = panelHTML();
      const p = host.querySelector('.tjh-panel');
      if (p) p.scrollTop = scrollTop;
    } else if (ov) {
      ov.remove();
    }
    paintPop();
  }
  function paintPop() {
    let host = document.getElementById('tjhPop');
    if (!H.pop || H.open) { if (host) host.remove(); return; }
    const btn = Array.from(document.querySelectorAll('.tjh-btn')).find(b => b.offsetParent);
    if (!host) { host = document.createElement('div'); host.id = 'tjhPop'; document.body.appendChild(host); }
    const mob = window.matchMedia && window.matchMedia('(max-width:640px)').matches;
    host.innerHTML = (mob ? '<div class="tjh-pbg" data-h="popClose"></div>' : '') + '<div class="tjh-pop" role="dialog" aria-label="상태 상세">' + popHTML() + '</div>';
    const p = host.querySelector('.tjh-pop');
    if (btn && p && !mob) { const r = btn.getBoundingClientRect(); p.style.top = Math.round(r.bottom + 6) + 'px'; p.style.right = Math.max(12, Math.round(window.innerWidth - r.right)) + 'px'; }
  }
  function togglePop(force) {
    if (isLocked()) { H.pop = false; paintPop(); return; }
    H.pop = force != null ? !!force : !H.pop;
    paint();
    if (H.pop) load();
  }
  function openPanel() {
    if (isLocked()) return;
    H.open = true;
    paint();
    const c = document.getElementById('tjhClose');
    if (c) c.focus();
    load();
  }
  function closePanel() {
    H.open = false;
    paint();
    const b = document.querySelector('.tjh-btn');
    if (b && b.offsetParent) b.focus();
  }

  document.addEventListener('click', ev => {
    const el = ev.target.closest('[data-h]');
    if (!el) return;
    const a = el.getAttribute('data-h');
    if (a === 'open') { ev.preventDefault(); H.pop = false; openPanel(); }
    else if (a === 'pop') { ev.preventDefault(); togglePop(); }
    else if (a === 'popClose') togglePop(false);
    else if (a === 'full') { H.pop = false; openPanel(); }
    else if (a === 'close') closePanel();
    else if (a === 'refresh') load();
    else if (a === 'moreRes') { H.showAllResolved = true; paint(); }
    else if (a === 'known') { ev.preventDefault(); H.knownOpen = !H.knownOpen; paint(); }
    else if (a === 'inc') { ev.preventDefault(); const v = el.getAttribute('data-v') || ''; if (H.incOpen.has(v)) H.incOpen.delete(v); else H.incOpen.add(v); paint(); refocus('[data-h="inc"]', v); }
    else if (a === 'units') { ev.preventDefault(); H.unitsAll = !H.unitsAll; paint(); refocus('[data-h="units"]', null); }
    else if (a === 'tg') {
      ev.preventDefault(); H.pop = false; H.open = false; paint();
      try {
        const su = window.__tjSetup;
        if (su && su.U) { su.U.panelOpen = true; su.U.where = 'telegram'; }
        location.hash = 'settings/keys/telegram';
      } catch (e) {  }
    }
  });
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && H.open) { ev.stopPropagation(); closePanel(); }
    else if (ev.key === 'Escape' && H.pop) { ev.stopPropagation(); togglePop(false); const b = Array.from(document.querySelectorAll('.tjh-btn')).find(x => x.offsetParent); if (b) b.focus(); }
  }, true);
  document.addEventListener('pointerdown', ev => { if (H.pop && !ev.target.closest('.tjh-pop') && !ev.target.closest('.tjh-btn')) togglePop(false); }, true);
  window.addEventListener('resize', () => { if (H.pop) paintPop(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - H.at > POLL_MS) load(); });
  setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
  setInterval(() => { const s = document.querySelector('#tjhOverlay .tjh-sub'); if (s && !document.hidden) s.innerHTML = headerLine(); }, 15000);

  function refocus(sel, v) { const b = Array.from(document.querySelectorAll('#tjhOverlay ' + sel + ', #tjhCard ' + sel + ', #tjhPop ' + sel)).find(x => v == null || x.getAttribute('data-v') === v); if (b) { try { b.focus({ preventScroll: true }); } catch (e) {  } } }
  window.TJHealth = { chrome: chrome, view: view, summary: summary, open: openPanel, close: closePanel, pop: togglePop, reload: load, lock: lock, _state: H };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { chrome(); load(); });
  else { chrome(); load(); }
})();

(function () {
  'use strict';
  const X = () => (window.TJ && window.TJ.ext) || null;
  const locSumH = g => {
    const wNmH = t => { const a9 = typeof window !== 'undefined' ? window.__tjSearchApi : null, t9 = String(t == null ? '' : t); return '<span class="pvl" data-pk="w">' + esc(a9 && typeof a9.ownNm === 'function' ? a9.ownNm(t9, 'w') : t9) + '</span>'; };
    const L = arr(g && g.locList), n = L.length;
    if (!n) return g && g.locSummary && g.locSummary !== '—' ? String(g.locSummary).split(' · ').map(x => / ?지갑$/.test(x) && !/^지갑 \d/.test(x) ? wNmH(x) : '<span class="pvl">' + esc(x) + '</span>').join(' · ') : '—';
    if (n >= 3 && L.every(l => l && l.wallet)) return '지갑 ' + n + '곳';
    return L.slice(0, 2).map(l => (l && l.wallet ? wNmH(l.w) : '<span class="pvl">' + esc(l && l.w) + '</span>')).join(' · ') + (n > 2 ? ' 외 ' + (n - 2) + '곳' : '');
  };
  const $ = (s, r) => (r || document).querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const num = v => { const n = Number(v); return isFinite(n) ? n : 0; };
  const arr = v => (Array.isArray(v) ? v : []);
  const KST = 9 * 3600 * 1000;
  const todayISO = () => new Date(Date.now() + KST).toISOString().slice(0, 10);
  const isoShift = (iso, d) => new Date(Date.parse(iso + 'T00:00:00Z') + d * 864e5).toISOString().slice(0, 10);
  const DOWS = ['일', '월', '화', '수', '목', '금', '토'];
  const dlabel = iso => { const d = new Date(iso + 'T00:00:00Z'); return d.getUTCFullYear() + '년 ' + (d.getUTCMonth() + 1) + '월 ' + d.getUTCDate() + '일 (' + DOWS[d.getUTCDay()] + ')'; };
  const md = iso => { const d = new Date(iso + 'T00:00:00Z'); return (d.getUTCMonth() + 1) + '/' + d.getUTCDate(); };
  const reduce = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const M = (usd, o) => { const x = X(); return x ? x.m(usd, o) : '—'; };
  const P = (v, d, sign) => (v == null || !isFinite(v) ? '—' : '<span class="pvx">' + (sign && v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d == null ? 1 : d) + '%</span>');
  const cls = v => (v > 0 ? 'up' : v < 0 ? 'down' : '');
  const ICO = {
    tm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M12 7v5l3 2"/></svg>',
    flow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M3 6c6 0 6 6 12 6h6"/><path d="M3 18c6 0 6-6 12-6"/><path d="M3 12h4"/></svg>',
    star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.6 5.5 6 .8-4.4 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.3l6-.8z"/></svg>',
    target: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
    sell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 17l6-6 4 4 6-7"/><path d="M14 8h6v6"/></svg>',
    x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    l: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>',
    r: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
    dl: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/></svg>'
  };

  const CSS = `
.wowbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.wowchip{display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 13px;border-radius:999px;border:1px solid var(--line2);background:var(--surface2);color:var(--text2);font:500 13px var(--sans);cursor:pointer;transition:background .15s var(--ease),border-color .15s var(--ease),color .15s;white-space:nowrap}
.wowchip svg{width:16px;height:16px;opacity:.85;flex:none}
.wowchip:hover{color:var(--text);border-color:var(--rule);background:var(--surface3)}
.wowchip:focus-visible,.wbtn:focus-visible,.wpill:focus-visible,.wchipb:focus-visible,.wst-x:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wowchip b{font-family:var(--mono);font-weight:600;color:var(--text)}
.wowchip.hl{border-color:color-mix(in srgb,var(--accent) 45%,transparent);color:var(--text)}
@media (pointer:coarse){.wowchip{height:40px}}
html.wow-lock,html.wow-lock body{overflow:hidden}
.wsr{position:absolute!important;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;margin:0;padding:0}
.wst{position:fixed;inset:0;z-index:70;display:flex;align-items:center;justify-content:center}
.wst-bg{position:absolute;inset:0;background:var(--dim);backdrop-filter:blur(3px)}
.wst-box{position:relative;width:min(1200px,calc(100vw - 48px));max-height:calc(100vh - 48px);display:flex;flex-direction:column;background:var(--bg);border:1px solid var(--line2);border-radius:24px;box-shadow:var(--pop);overflow:hidden;animation:wstIn .2s var(--ease)}
.wst.sm .wst-box{width:min(460px,calc(100vw - 32px));background:var(--surface)}
@keyframes wstIn{from{opacity:0;transform:translateY(12px) scale(.985)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.wst-box{animation:none}}
.wst-h{display:flex;align-items:flex-end;gap:10px;padding:22px 26px 14px;border-bottom:1px solid var(--line)}
.wst-h>div:first-child{flex:1 1 auto}
.wst-h.slim{align-items:center;padding:14px 18px 10px;border-bottom:0}
.wst-k{font-size:12.5px;color:var(--accent);font-weight:600;letter-spacing:.04em}
.wst-h.slim .wst-k{color:var(--muted);font-weight:500;letter-spacing:0;font-size:13px}
.wst-h h3{margin:4px 0 0;font-size:26px;font-weight:700;letter-spacing:-.01em;color:var(--text);line-height:1.25}
.wst-h .sp{display:none}
.wst-x{flex:none;width:40px;height:40px;border-radius:12px;border:1px solid var(--line2);background:var(--surface);color:var(--text2);display:inline-flex;align-items:center;justify-content:center;cursor:pointer}
.wst-x svg{width:18px;height:18px}
.wst-b{padding:20px 26px 26px;overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain}
.wst-grab{display:block;align-self:center;width:40px;height:4px;border-radius:2px;background:var(--line2);margin:10px auto 0;flex:none}
@media (min-width:641px){.wst-grab{display:none}}   /* design1008 P3-6: 손잡이는 폰 아래 시트에만(PC = 가운데 모달) */
.wst-box.bare .wst-b{padding-top:14px}
.wst-dk{display:inline-flex;gap:8px;align-items:center}
.wst-mb{display:none}
@media (max-width:720px){.wst{align-items:stretch}.wst-box{width:100vw;max-height:none;height:100%;border-radius:0;border:0}
  .wst-h{flex-wrap:wrap;align-items:center;padding:14px 16px 12px}.wst-h h3{font-size:20px}.wst-b{padding:16px}
  .wst-h>.wseg{order:3;flex:1 1 100%;display:flex}.wst-h>.wseg button{flex:1}
  .wst-dk{display:none}.wst-mb{display:block}
  .wst.sm{align-items:flex-end}.wst.sm .wst-box{width:100vw;height:auto;max-height:94vh;border-radius:24px 24px 0 0;border-top:1px solid var(--line2)}}
.wcard{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:18px 20px;min-width:0}
.wgrid{display:grid;gap:14px;align-content:start}
.wmet{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:14px}
.wmet>div{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:14px 16px;display:flex;flex-direction:column;gap:5px;min-width:0}
.wmet .l{font-size:12.5px;color:var(--muted)}
.wmet .v{font-family:var(--mono);font-size:22px;font-weight:600;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wmet .s{font-size:12px;color:var(--faint);line-height:1.45}
@media (max-width:560px){.wmet{grid-template-columns:1fr 1fr;gap:8px}.wmet>div{padding:12px}.wmet .v{font-size:17px}.wmet.wcmp>div:first-child{grid-column:1/-1}}
.wmet .up,.wtbl .up,.wps .up,.wfl-sel .up{color:var(--up)}.wmet .down,.wtbl .down,.wps .down,.wfl-sel .down{color:var(--down)}
.wseg{display:inline-flex;gap:4px;background:var(--seg);border:1px solid var(--line);border-radius:12px;padding:3px}
.wseg button{height:34px;padding:0 13px;border:0;border-radius:9px;background:transparent;color:var(--muted);font:500 13px var(--sans);cursor:pointer;white-space:nowrap}
.wseg button.on{background:var(--segOn);color:var(--text);font-weight:600}
@media (pointer:coarse){.wseg button{height:40px}}
.wbtn{height:42px;padding:0 16px;border-radius:12px;border:1px solid var(--line2);background:var(--surface);color:var(--text);font:500 14px var(--sans);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:7px;white-space:nowrap}
.wbtn.pri{border:0;background:var(--accent);color:var(--onAccent);font-weight:600}
.wbtn svg{width:17px;height:17px}
.wbtn:disabled{opacity:.5;cursor:default}
.wpill{height:32px;padding:0 13px;border-radius:999px;border:1px solid var(--line2);background:transparent;color:var(--text2);font:500 12.5px var(--sans);cursor:pointer;white-space:nowrap}
.wpill[aria-pressed="true"]{background:var(--segOn);color:var(--text)}
.wchipb{height:34px;padding:0 13px;border-radius:999px;border:1px solid var(--line2);background:var(--surface);color:var(--text2);font:500 13px var(--sans);cursor:pointer}
.wchipb[aria-pressed="true"]{background:var(--segOn);color:var(--text);font-weight:600}
.wnote{font-size:12.5px;color:var(--faint);line-height:1.55}
.wnd summary{cursor:pointer;list-style:none;padding:4px 0;min-height:32px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}.wnd summary::-webkit-details-marker{display:none}
.wnd .wndm{color:var(--accent);font-weight:600}.wnd[open] .wndm{display:none}.wnd .wndb{padding-top:4px}
.wempty{padding:28px 10px;text-align:center;color:var(--muted);font-size:14px;line-height:1.6}
/* ④ 타임머신 */
.wtm-scr{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:14px 18px 8px;margin-bottom:14px;user-select:none;-webkit-user-select:none}
.wtm-scr:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wtm-plot{position:relative;height:84px;touch-action:none;cursor:ew-resize}
.wtm-plot svg{display:block;width:100%;height:84px}
.wtm-ln{position:absolute;top:2px;bottom:2px;width:1.5px;margin-left:-.75px;background:var(--accent);pointer-events:none}
.wtm-dot{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px var(--surface);pointer-events:none}
.wtm-ax{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;color:var(--faint);margin-top:6px}
.wtm-ax .sp{flex:1;text-align:center;font-family:var(--sans)}
.wtm-ax .wst-mb{font:600 13px var(--mono);color:var(--text)}
.wtm-ib{width:30px;height:30px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--text2);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;flex:none}
.wtm-ib svg{width:15px;height:15px}
@media (pointer:coarse){.wtm-ib{width:40px;height:40px}}
.wtm-scr+.wst-mb{margin:-4px 0 12px}
.wtm-body{display:grid;grid-template-columns:340px minmax(0,1fr);gap:14px;align-items:start}
@media (max-width:860px){.wtm-body{grid-template-columns:1fr}}
.wdon{display:flex;flex-direction:column;align-items:center;gap:14px}
.wdon-c{position:relative;width:220px;height:220px}
.wdon-c svg{width:220px;height:220px;display:block}
.wdon-t{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;text-align:center}
.wdon-t span{font-size:13px;color:var(--muted)}
.wdon-t b{font:600 20px var(--mono);color:var(--text);max-width:150px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wleg{display:flex;flex-wrap:wrap;gap:6px 12px;justify-content:center;font-size:12.5px;color:var(--text2)}
.wleg i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:0}
.wtbl{display:flex;flex-direction:column}
.wtbl .hd,.wtbl .rw{display:grid;grid-template-columns:minmax(0,1.4fr) 84px 120px 120px;gap:10px;align-items:center}
.wtbl .hd{font-size:12px;color:var(--muted);padding:0 4px 8px;border-bottom:1px solid var(--line)}
.wtbl .rw{padding:11px 4px;border-bottom:1px solid var(--line);font-size:14px}
.wtbl .rw:last-child{border-bottom:0}
.wtbl .n{display:flex;align-items:center;gap:10px;min-width:0}
.wtbl .av{flex:none;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;color:var(--onAccent)}
.wtbl .n b{display:block}
.wtbl .n small{display:block;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wtbl .r{text-align:right;font-family:var(--mono)}
@media (max-width:560px){.wtbl .hd,.wtbl .rw{grid-template-columns:minmax(0,1fr) 62px 76px}.wtbl .c3{display:none}.wcard{padding:14px}}
.wapx{font-size:11px;color:var(--warn);margin-left:4px}
.wskel{height:14px;border-radius:7px;background:linear-gradient(90deg,var(--surface2),var(--surface3),var(--surface2));background-size:200% 100%;animation:wsk 1.2s linear infinite}
@keyframes wsk{to{background-position:-200% 0}}
@media (prefers-reduced-motion:reduce){.wskel{animation:none}}
.wtm-dat{position:relative}
.wtm-dat.wtm-stale>*{visibility:hidden}
.wtm-dat.wtm-stale::after{content:attr(data-wait);position:absolute;inset:0;display:flex;align-items:flex-start;justify-content:center;padding-top:48px;border-radius:16px;font-size:13px;color:var(--muted);background:linear-gradient(90deg,var(--surface2),var(--surface3),var(--surface2));background-size:200% 100%;animation:wsk 1.2s linear infinite}
@media (prefers-reduced-motion:reduce){.wtm-dat.wtm-stale::after{animation:none}}
/* ⑤ 자금 흐름 지도 */
.wfl-tot{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--muted);margin:0 2px 12px}
.wfl-tot b{font-family:var(--mono);font-weight:600;color:var(--text);margin-left:4px}
.wfl-wrap{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:16px 20px 18px}
.wfl-cols{position:relative;height:18px;margin-bottom:8px;font-size:12px;color:var(--muted)}
.wfl-cols span{position:absolute;top:0;white-space:nowrap}
#wflMap svg{display:block;overflow:visible}
.wfl-band{cursor:pointer;transition:opacity .15s}
.wfl-band:focus{outline:none}
.wfl-band:focus-visible{stroke:var(--text);stroke-width:1.5}
.wfl-dim .wfl-band{opacity:.12}
html:not([data-theme="light"]) .wfl-band{fill-opacity:.58}html:not([data-theme="light"]) .wfl-band.est{fill-opacity:.24}
.wfl-lb.thin{font-size:11.5px;line-height:1.2;padding:0 5px}
.wfl-lb.wrap b{white-space:normal;word-break:keep-all;line-height:1.15}
.wfl-dim .wfl-band.on{opacity:1}
.wfl-lb{position:absolute;transform:translateY(-50%);pointer-events:none;font-size:13px;line-height:1.3;color:var(--text);padding:2px 6px;border-radius:7px;background:color-mix(in srgb,var(--surface) 78%,transparent);min-width:0}
.wfl-lb b{display:block;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wfl-lb>span{display:block;font:500 11.5px var(--mono);color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wfl-lb.r{background:transparent;padding-left:2px}
@media (max-width:640px){.wfl-wrap{padding:12px 10px 14px}.wfl-lb{font-size:11.5px;padding:1px 4px}.wfl-lb>span{font-size:10.5px}.wfl-cols{font-size:11px}}
/* exte1006(외부 검토 5장 '자금 흐름 지도가 읽기 어려움' — 배치·대비·글자만): ① 이름은 두 줄까지 감싸기(낱말 안 끊음 · 넘치면 아래 범례로)
   ② 얇은 마디도 한 줄 이름(자리 없으면 범례) ③ 어두운 테마 띠 진하게(종전 .34·추정 .16 이 어두운 배경에서 거의 안 보임) · 5번째 팔레트 회색 밝게 */
.wfl-lb b{white-space:normal;word-break:keep-all;overflow-wrap:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;line-height:1.25}
.wfl-lb.thin{padding-top:0;padding-bottom:0;line-height:1.2}
.wfl-lb.thin b{display:block;white-space:nowrap;font-size:12px}
.wfl-band{fill-opacity:.34}.wfl-band.est{fill-opacity:.16}
html:not([data-theme="light"]) .wfl-band{fill-opacity:.5}
html:not([data-theme="light"]) .wfl-band.est{fill-opacity:.3}
html{--wfl5:var(--c5)} html:not([data-theme="light"]){--wfl5:#8C94A8}
.wfl-legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line);font-size:12.5px;color:var(--text2)}
.wfl-legend:empty{display:none}
.wfl-legend .k{color:var(--muted)}
.wfl-legend [data-n]{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.wfl-legend [data-n] i{width:9px;height:9px;border-radius:3px;flex:none}
.wfl-legend [data-n] span{font:500 11.5px var(--mono);color:var(--muted)}
.wfl-sel{margin-top:12px;background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:14px 16px;display:flex;flex-direction:column;gap:8px;margin-bottom:10px}
.wfl-hint{font-size:13.5px;color:var(--muted)}
.wfl-sh{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.wfl-sh .sw{width:10px;height:10px;border-radius:3px;flex:none}
.wfl-sh b{font-size:15px}
.wfl-sh .amt{font:600 15px var(--mono)}
.wfl-sh .sp{flex:1}
.wfl-sh .wbtn{height:34px;font-size:13px;padding:0 12px}
.wfl-rows{display:flex;flex-direction:column;max-height:300px;overflow:auto;border-top:1px solid var(--line)}
.wfl-r{display:grid;grid-template-columns:72px minmax(0,1fr) auto;gap:10px;align-items:center;padding:8px 2px;border-bottom:1px solid var(--line);font-size:13.5px}
.wfl-r .d{font-family:var(--mono);font-size:12px;color:var(--faint)}
.wfl-r .n{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wfl-r .n small{color:var(--muted);font-size:12px;margin-left:4px}
.wfl-r .v{font-family:var(--mono);text-align:right}
/* ⑥ 계획 점수 */
.wps{display:grid;grid-template-columns:340px minmax(0,1fr);gap:14px;align-items:start}
@media (max-width:860px){.wps{grid-template-columns:1fr}}
.wps-ring{display:flex;flex-direction:column;align-items:center;gap:12px;text-align:center}
.wps-ring svg{width:190px;height:190px}
.wps-bars{display:flex;align-items:flex-end;gap:8px;height:92px}
.wps-bars span{flex:1;border-radius:6px;background:var(--line2);min-height:4px}
.wps-bars span.on{background:var(--ok)}
.wps-ax{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;color:var(--faint);margin-top:6px}
.wchips{display:flex;gap:8px;flex-wrap:wrap;padding-bottom:10px;border-bottom:1px solid var(--line)}
.wchips button{height:34px;padding:0 13px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text2);font:500 13px var(--sans);cursor:pointer}
.wchips button.on{background:var(--segOn);color:var(--text);font-weight:600;border-color:var(--line2)}
@media (pointer:coarse){.wchips button{height:40px}}
.wps-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr) 128px 76px;gap:12px;align-items:center;padding:11px 6px;border-bottom:1px solid var(--line);cursor:pointer;border-radius:10px}
.wps-row:hover{background:var(--surface2)}
.wps-row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.wps-row:last-child{border-bottom:0}
.wps-row b{display:block;font-size:14.5px}
.wps-row small{display:block;font-size:12px;color:var(--muted)}
.wps-row .pl{font-size:13px;color:var(--text2)}
.wps-row .r{text-align:right;font-family:var(--mono);font-weight:600}
@media (max-width:560px){.wps-row{grid-template-columns:minmax(0,1fr) auto 64px}.wps-row .pl{display:none}}
.wv{justify-self:start;height:26px;padding:0 10px;border-radius:999px;display:inline-flex;align-items:center;font-size:12.5px;font-weight:600;white-space:nowrap}
.wv.plan{color:var(--ok);background:var(--okBg)}.wv.early{color:var(--warn);background:var(--warnBg)}.wv.late{color:var(--ext);background:var(--extBg)}.wv.cut{color:var(--accent);background:var(--accentBg)}
.wrule{display:flex;flex-direction:column;gap:8px}
.wrule .lb{font-size:12.5px;color:var(--muted)}
.wrule .wseg{display:flex}.wrule .wseg button{flex:1;padding:0 6px}
/* ⑧ 팔기 전 미리보기 */
.wsl-h{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.wsl-h .av{flex:none;width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--onAccent);background:var(--accent)}
.wsl-h b{font-size:18px;display:block}
.wsl-h small{font-size:12.5px;color:var(--muted)}
.wsl-tr{position:relative;height:40px;touch-action:none;cursor:pointer;margin:2px 13px 0}
.wsl-tr .tk{position:absolute;left:0;right:0;top:18px;height:4px;border-radius:2px;background:var(--surface3)}
.wsl-tr .fi{position:absolute;left:0;top:18px;height:4px;border-radius:2px;background:var(--accent)}
.wsl-tr .th{position:absolute;top:7px;width:26px;height:26px;margin-left:-13px;border-radius:50%;background:var(--text);box-shadow:0 2px 8px rgba(0,0,0,.35)}
.wsl-tr:focus{outline:none}.wsl-tr:focus-visible .th{outline:2px solid var(--accent);outline-offset:2px}
.wsl-q{display:flex;gap:6px;margin-top:6px}.wsl-q button{flex:1;height:36px;font-size:13px}
.wsl-q button.on{background:var(--segOn);border-color:transparent;font-weight:600}
.wsl-res{background:var(--surface2);border-radius:16px;padding:16px;display:flex;flex-direction:column;gap:11px;margin-top:16px}
.wsl-res .big{font-family:var(--mono);font-size:30px;font-weight:600;letter-spacing:-.01em;line-height:1.2}
.wsl-res .up{color:var(--up)}.wsl-res .down{color:var(--down)}
.wsl-kv{display:flex;justify-content:space-between;gap:12px;font-size:13.5px;color:var(--text2)}
.wsl-kv>span:last-child{font-family:var(--mono);text-align:right}
.wsl-pl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;margin-top:14px}
.wsl-pl label{display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--muted);min-width:0}
.wsl-pl input{width:100%;min-width:0;box-sizing:border-box;height:44px;border-radius:12px;border:1px solid var(--line2);background:var(--bg);color:var(--text);font:500 15px var(--mono);padding:0 12px;outline:none}
.wsl-pl input:focus{border-color:var(--accent)}
.wsl-act{display:flex;gap:8px;margin-top:14px}.wsl-act .wbtn{height:48px;border-radius:14px;font-size:14.5px}
/* ⑨ 올해 결산 */
.wye{display:flex;flex-direction:column;align-items:center;gap:14px}
.wye-prog{display:flex;gap:4px;width:min(420px,100%)}
.wye-prog span{flex:1;height:3px;border-radius:2px;background:var(--rule)}
.wye-prog span.on{background:var(--text)}
.wye-card{position:relative;width:min(420px,100%);min-height:min(520px,calc(100vh - 230px));border-radius:28px;background:var(--surface);border:1px solid var(--line);padding:28px 24px;display:flex;flex-direction:column;gap:16px;overflow:hidden;box-sizing:border-box}
.wye-card .ey{font-size:13px;font-weight:600;letter-spacing:.04em;position:relative}
.wye-card .t1{font-size:42px;font-weight:700;line-height:1.05;letter-spacing:-.01em;color:var(--text);position:relative;word-break:keep-all}
.wye-card .t2{font-family:var(--mono);font-size:52px;font-weight:600;letter-spacing:-.02em;line-height:1.05;position:relative;word-break:break-all}
.wye-card .tx{font-size:15px;color:var(--text2);line-height:1.6;position:relative}
.wye-card .sp{flex:1}
.wye-card .g4{display:grid;grid-template-columns:1fr 1fr;gap:10px;position:relative}
.wye-card .g4>div{background:var(--surface2);border-radius:16px;padding:12px 14px;min-width:0}
.wye-card .g4 .l{font-size:11.5px;color:var(--muted)}
.wye-card .g4 b{display:block;font-size:17px;line-height:1.3;overflow-wrap:anywhere}   /* 폰: '코인 · 거래 횟수' 가 말줄임으로 잘리던 것 → 줄바꿈 */
.wye-card .orb{position:absolute;right:-70px;top:-50px;width:260px;height:260px;border-radius:50%;border:1px dashed currentColor;opacity:.45;pointer-events:none}
.wye-card .orb::after{content:'';position:absolute;inset:40px;border-radius:50%;border:1px dashed currentColor}
.wye-card .up{color:var(--up)}.wye-card .down{color:var(--down)}
.wye-tap{position:absolute;top:0;bottom:0;width:38%;border:0;background:transparent;cursor:pointer;z-index:1;padding:0}
.wye-tap.l{left:0}.wye-tap.r{right:0;width:62%}
.wye-tap:disabled{cursor:default}
.wye-tap:focus-visible{outline:2px solid var(--accent);outline-offset:-4px;border-radius:28px}
.wye-nav{display:flex;gap:8px;width:min(420px,100%)}
.wye-nav .wbtn{flex:1;height:48px;border-radius:14px}
`;
  function css() { if ($('#wowCss')) return; const s = document.createElement('style'); s.id = 'wowCss'; s.textContent = CSS; document.head.appendChild(s); }

  const st = { view: null, sm: false, hist: false,
    tm: { series: null, sErr: '', date: '', cache: {}, re: {}, busy: false, err: '', t: 0, cmp: false },
    fl: { cache: {}, per: 'all', err: '', busy: '', sel: -1, L: null },
    ps: { f: 'all' },
    sell: { key: '', f: 0.5, saveMsg: '' },
    ye: { i: 0, ratio: false, year: 0 } };
  const LSget = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } };
  const LSset = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {  } };

  const VIEWS = {};
  function open(view, o) {
    const x = X(); if (!x || !x.S.D || x.lockedNow()) return;
    css();
    const first = !st.view;
    st.view = view; st.sm = !!(o && o.sm); Object.assign(st, { opener: (o && o.opener) || st.opener || null });
    if (first) { try { history.pushState(Object.assign({}, history.state || {}, { tjWow: 1 }), ''); st.hist = true; } catch (e) { st.hist = false; } }
    paint();
    if (VIEWS[view] && VIEWS[view].load) VIEWS[view].load();
    setTimeout(() => { const b = $('#wowStage .wst-x') || $('#wowStage [role="slider"]') || $('#wowStage button'); if (b && first) { try { b.focus({ preventScroll: true }); } catch (e) {  } } }, 30);
  }
  function close(fromPop) {
    if (!st.view) return;
    st.view = null;
    const el = $('#wowStage'); if (el) el.remove();
    document.documentElement.classList.remove('wow-lock');
    if (!fromPop && st.hist && history.state && history.state.tjWow) { try { history.back(); } catch (e) {  } }
    st.hist = false;
    const op = st.opener; st.opener = null;
    if (op && op.isConnected && op.focus) { try { op.focus({ preventScroll: true }); } catch (e) {  } }
  }
  function closeAndGo(go) {
    const wait = !!(st.view && st.hist && history.state && history.state.tjWow);
    if (!wait) { close(); go(); return; }
    let done = false, timer = null;
    const run = () => {
      if (done) return;
      done = true; clearTimeout(timer);
      window.removeEventListener('popstate', onPop);
      go();
    };
    const onPop = () => setTimeout(run, 0);
    window.addEventListener('popstate', onPop);
    timer = setTimeout(run, 600);
    close();
  }
  const focusKey = el => (el && el.getAttribute ? { id: el.id || '', w: el.getAttribute('data-w') || '', v: el.getAttribute('data-v') || '', k: el.getAttribute('data-k') || '', i: el.getAttribute('data-i') || '' } : null);
  function focusBack(k) {
    if (!k) return;
    const box = $('#wowStage'); if (!box) return;
    let el = k.id ? document.getElementById(k.id) : null;
    if (!el && k.w) el = Array.from(box.querySelectorAll('[data-w]')).find(e => e.getAttribute('data-w') === k.w && (e.getAttribute('data-v') || '') === k.v && (e.getAttribute('data-k') || '') === k.k && (e.getAttribute('data-i') || '') === k.i) || null;
    if (el && !el.disabled && box.contains(el)) { try { el.focus({ preventScroll: true }); } catch (e) {  } }
  }
  function paint() {
    const v = VIEWS[st.view]; if (!v) return;
    let el = $('#wowStage');
    const ae0 = document.activeElement, fk0 = el && ae0 && el.contains(ae0) && ae0 !== document.body ? focusKey(ae0) : null;
    const keepY = el ? ($('.wst-b', el) || {}).scrollTop || 0 : 0;
    if (!el) { el = document.createElement('div'); el.id = 'wowStage'; document.body.appendChild(el); }
    const h = v.head();
    el.className = 'wst' + (st.sm ? ' sm' : '');
    el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-labelledby', 'wowT');
    const hd = h.bare ? '<span class="wst-grab" aria-hidden="true"></span><h3 id="wowT" class="wsr">' + h.t + '</h3>'
      : '<div class="wst-h' + (h.slim ? ' slim' : '') + '"><div style="min-width:0"><div class="wst-k pvx">' + esc(h.k) + '</div><h3 id="wowT"' + (h.slim ? ' class="wsr"' : '') + '>' + h.t + '</h3></div><span class="sp"></span>'
        + (h.act || '') + '<button type="button" class="wst-x" data-w="close" aria-label="닫기">' + ICO.x + '</button></div>';
    el.innerHTML = '<div class="wst-bg" data-w="close"></div><div class="wst-box' + (h.bare ? ' bare' : '') + '">' + hd + '<div class="wst-b">' + v.body() + '</div></div>';
    { const x9 = X(); if (x9 && typeof x9.hydrateLogos === 'function') x9.hydrateLogos(); }
    document.documentElement.classList.add('wow-lock');
    const b = $('.wst-b', el); if (b && keepY) b.scrollTop = keepY;
    if (v.after) v.after(el);
    focusBack(fk0);
  }
  window.addEventListener('popstate', ev => { if (st.view && !(ev.state && ev.state.tjWow)) close(true); });
  function lock() {
    close(true);
    st.tm.cache = {}; st.tm.re = {}; st.tm.series = null; st.tm.err = ''; st.fl.cache = {}; st.sell.dT = null; st.sell.dS = null;
  }
  function onPv() {
    if (!st.view) return;
    const ae = document.activeElement, id = ae && ae.id && ae.tagName === 'INPUT' && $('#wowStage') && $('#wowStage').contains(ae) ? ae.id : '';
    const sel = id && typeof ae.selectionStart === 'number' ? [ae.selectionStart, ae.selectionEnd] : null;
    paint();
    if (id) { const el = document.getElementById(id); if (el && !el.disabled) { try { el.focus({ preventScroll: true }); if (sel && el.setSelectionRange) el.setSelectionRange(sel[0], sel[1]); } catch (e) {  } } }
  }
  document.addEventListener('keydown', ev => {
    if (!st.view) return;
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); close(); return; }
    if (ev.key === 'Tab') {
      const box = $('#wowStage .wst-box'); if (!box) return;
      const f = Array.from(box.querySelectorAll('button:not([disabled]),[href],input:not([disabled]),[tabindex]:not([tabindex="-1"])')).filter(e => e.offsetParent !== null || e === document.activeElement);
      if (!f.length) { ev.preventDefault(); return; }
      const i = f.indexOf(document.activeElement);
      if (ev.shiftKey && (i <= 0)) { ev.preventDefault(); f[f.length - 1].focus(); return; }
      if (!ev.shiftKey && (i < 0 || i === f.length - 1)) { ev.preventDefault(); f[0].focus(); return; }
      return;
    }
    const v = VIEWS[st.view]; if (v && v.key) v.key(ev);
  }, true);
  document.addEventListener('click', ev => {
    const t = ev.target && ev.target.closest ? ev.target.closest('[data-w]') : null;
    if (!t) return;
    const a = t.getAttribute('data-w');
    if (A[a]) { ev.preventDefault(); ev.stopPropagation(); A[a](t, ev); }
  }, true);
  const A = {
    close: () => close(),
    open: el => open(el.getAttribute('data-v'), { opener: el }),
    sell: el => { st.sell.key = el.getAttribute('data-k') || ''; st.sell.f = 0.5; st.sell.saveMsg = ''; st.sell.dT = null; st.sell.dS = null; open('sell', { sm: true, opener: el }); }
  };

  function slot(k, g) {
    const x = X(); if (!x || !x.S.D) return '';
    css();
    if (k === 'dash.total') {
      return '<div class="wowbar"><button type="button" class="wowchip" data-w="open" data-v="tm">' + ICO.tm + '타임머신</button>'
        + '<button type="button" class="wowchip" data-w="open" data-v="fl">' + ICO.flow + '자금 흐름 지도</button>'
        + '<button type="button" class="wowchip" data-w="open" data-v="ye">' + ICO.star + yearLabel() + '</button></div>';
    }
    if (k === 'journal.head') {
      const sc = planScore();
      return '<div class="wowbar" style="margin:0 0 12px"><button type="button" class="wowchip' + (sc.n ? ' hl' : '') + '" data-w="open" data-v="ps">' + ICO.target + '계획 지키기 점수' + (sc.n ? ' <b class="pvx">' + sc.score + '</b>' : '') + '</button>'
        + '<button type="button" class="wowchip" data-w="open" data-v="ye">' + ICO.star + yearLabel() + '</button></div>';
    }
    if (k === 'hold.open' && g && num(g.qty) > 0 && num(g.value) > 0) {
      return '<div class="wowbar" style="margin:0 0 10px"><button type="button" class="wowchip" data-w="sell" data-k="' + esc(g.key) + '">' + ICO.sell + '지금 팔면?</button></div>';
    }
    return '';
  }
  const yeDefault = () => { const d = new Date(Date.now() + KST); return String(d.getUTCMonth() === 0 ? d.getUTCFullYear() - 1 : d.getUTCFullYear()); };
  const yeYear = () => String(st.ye.year || yeDefault());
  const yearLabel = yr => { const d = new Date(Date.now() + KST), y = String(yr || yeDefault()); return y + '년 결산' + (y === String(d.getUTCFullYear()) && d.getUTCMonth() < 11 ? ' 미리 보기' : ''); };

  const PAL = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c6)', 'var(--c7)'];
  const LOC_PAL = { '거래소': 'var(--c1)', '원화·기타': 'var(--c5)', '기록 없음': 'var(--line2)' };
  VIEWS.tm = {
    head: () => ({ k: '타임머신', t: st.tm.date ? esc(dlabel(st.tm.date)) + '의 내 지갑' : '지난날의 내 지갑',
      act: st.tm.date ? '<span class="wst-dk"><button type="button" class="wbtn" data-w="tmCmp" aria-pressed="' + !!st.tm.cmp + '"' + (st.tm.cmp ? ' style="background:var(--segOn)"' : '') + '>오늘과 비교</button>'
        + '<button type="button" class="wbtn pri" data-w="close">오늘로 돌아가기</button></span>' : '' }),
    load: () => {
      if (st.tm.series) { if (st.tm.date) tmFetch(st.tm.date); return; }
      fetch('/api/curve_hist?range=all', { cache: 'no-store', credentials: 'same-origin' }).then(r => r.json().then(j => ({ r, j }))).then(({ r, j }) => {
        let days = arr(j && j.days).filter(d => Array.isArray(d) && /^\d{4}-\d{2}-\d{2}$/.test(d[0]) && num(d[1]) > 0).map(d => [d[0], num(d[1])]);
        const x = X(), today = todayISO();
        const ds = arr(x && x.S.D && x.S.D.f && x.S.D.f.dailySeries);
        const have = new Set(days.map(d => d[0]));
        ds.forEach(r0 => { const iso = /^\d{4}-\d{2}-\d{2}$/.test(r0.iso || '') ? r0.iso : (r0.date && x.isoDay(r0.date)) || ''; if (iso && iso < today && !have.has(iso) && num(r0.val) > 0) days.push([iso, num(r0.val)]); });
        days = days.filter(d => d[0] < today).sort((a, b) => (a[0] < b[0] ? -1 : 1));
        st.tm.series = days; st.tm.sErr = days.length ? '' : (r.status === 404 ? '이 서버는 장기 곡선을 지원하지 않아요' : '아직 지난날 곡선이 없어요');
        if (!st.tm.date && days.length) st.tm.date = days[Math.max(0, days.length - 31)][0];
        if (st.view === 'tm') { paint(); if (st.tm.date) tmFetch(st.tm.date); }
      }).catch(() => { st.tm.series = []; st.tm.sErr = '곡선을 불러오지 못했어요'; if (st.view === 'tm') paint(); });
    },
    body: () => {
      const T = st.tm, x = X();
      if (!T.series) return '<div class="wtm-scr"><div class="wskel" style="height:90px;border-radius:12px"></div></div>' + skelRows(5);
      if (!T.series.length) return '<div class="wempty">' + esc(T.sErr || '지난날 기록이 아직 없어요') + '</div>';
      const d = T.cache[T.date];
      const scr = tmScrubber() + '<div class="wst-mb"><button type="button" class="wchipb" data-w="tmCmp" aria-pressed="' + !!T.cmp + '">' + (T.cmp ? '비교 닫기' : '오늘과 비교') + '</button></div>';
      if (!d) return scr + (T.err ? '<div class="wempty">' + esc(T.err) + '</div>' : skelRows(6));
      const bNow = x.S.D ? x.S.D.builtAt : null, sameB = d.builtAt != null && bNow != null && d.builtAt === bNow;
      if (!sameB && bNow != null && T.re[T.date] !== bNow) { T.re[T.date] = bNow; tmFetch(T.date, true); }
      const noFx = x.S.cur !== 'USD' && !(d.totalKrw != null && num(d.fx) > 0);
      const DV = usd => (!noFx && typeof x.KV === 'function' && num(d.fx) > 0 ? x.KV(num(usd), num(usd) * num(d.fx)) : num(usd));
      const thenV = !noFx && d.totalKrw != null && typeof x.KV === 'function' ? x.KV(num(d.total), num(d.totalKrw)) : num(d.total);
      const items = arr(d.items), chg = d.nowTotal && thenV ? num(d.nowTotal) / thenV * 100 - 100 : null;
      const fl = d.flows && typeof d.flows === 'object' ? d.flows : null, flV = fl ? (!noFx && typeof x.KV === 'function' ? x.KV(num(fl.usd), num(fl.krw)) : num(fl.usd)) : 0;
      const ret = typeof x.retPct === 'function' ? x.retPct : (a, b, c) => (a ? (b - a - num(c)) / a * 100 : null);
      const nowAct = num(x.S.D && x.S.D.total), flMiss = fl ? num(fl.miss) + num(fl.nofx) : 0, actChg = sameB && fl && !flMiss && thenV && nowAct > 0 ? ret(thenV, nowAct, flV) : null;
      const cmp = T.cmp ? '<div class="wmet wcmp"><div><span class="l">그날 총자산</span><span class="v">' + M(thenV, { compact: true }) + '</span><span class="s">' + esc(md(d.date)) + ' 마감' + (noFx ? ' · 그날 환율 없음(지금 환율로 환산)' : d.totalKrw != null ? ' · 그날 환율' : '') + '</span></div>'
        + '<div><span class="l">그 보유를 그대로 뒀다면</span><span class="v ' + cls(chg) + '">' + (d.nowTotal ? M(d.nowTotal, { compact: true }) : '—') + '</span><span class="s">' + (chg != null ? '그날보다 ' + P(chg, 1, true) + (num(d.nowMiss) ? ' · 시세 없는 <span class="pvx">' + num(d.nowMiss) + '종</span>은 그날 값' : '') : '지금 시세를 모르는 코인뿐이에요') + '</span></div>'
        + '<div><span class="l">실제 지금</span><span class="v ' + cls(actChg) + '">' + (nowAct > 0 ? M(nowAct, { compact: true }) : '—') + '</span><span class="s">' + (actChg != null ? (noFx ? '달러 기준 입출금 뺀 수익률 ' : '입출금 뺀 수익률 ') + P(actChg, 1, true)
          + (fl && Math.abs(flV) >= 0.005 ? ' · 그 뒤 입출금 ' + M(flV, { sign: true, compact: true }) + ' 뺌' : '') + (flMiss ? ' · 입출금 모르는 날 <span class="pvx">' + flMiss + '일</span>' : '')
          + (chg != null ? ' · 그대로 뒀을 때와 ' + P(actChg - chg, 1, true) + 'p' : '')
          : nowAct > 0 && thenV ? (!sameB ? '최신 기록으로 다시 세는 중 — 잠시 뒤 입출금 뺀 수익률을 보여 드려요' : !fl ? '입출금 기록을 받으면 입출금 뺀 수익률을 보여 드려요' : flMiss ? '입출금·환율 모르는 날 <span class="pvx">' + flMiss + '일</span> — 수익률은 생략했어요' : '') : '') + '</span></div></div>' : '';
      const bl = arr(d.byLoc), blTot = bl.reduce((a, b) => a + num(b[1]), 0) || 1;
      let segs = bl.slice(0, 5).map(b => [b[0], num(b[1]) / blTot * 100, LOC_PAL[b[0]] || '']);
      const usedC = new Set(segs.map(s0 => s0[2]).filter(Boolean));
      segs.forEach(s0 => { if (!s0[2]) { s0[2] = PAL.find(c => !usedC.has(c)) || 'var(--c5)'; usedC.add(s0[2]); } });
      const restS = 100 - segs.reduce((a, s0) => a + s0[1], 0);
      if (restS > 0.3) segs.push(['그 밖', restS, usedC.has('var(--c5)') ? 'var(--line2)' : 'var(--c5)']);
      if (!segs.length) segs = items.slice(0, 5).map((it, i) => [it.sym, num(it.share), PAL[i]]);
      const R0 = 82, C = 2 * Math.PI * R0; let off = 0;
      const ring = segs.map(s0 => { const len = Math.max(0, s0[1] / 100 * C - 2.5); const c = '<circle cx="110" cy="110" r="' + R0 + '" fill="none" stroke="' + s0[2] + '" stroke-width="28" stroke-dasharray="' + len.toFixed(1) + ' ' + C.toFixed(1) + '" stroke-dashoffset="' + (-off).toFixed(1) + '" transform="rotate(-90 110 110)"/>'; off += s0[1] / 100 * C; return c; }).join('');
      const don = '<div class="wcard wdon"><div class="wdon-c"><svg viewBox="0 0 220 220" role="img" aria-label="그날 보관처 비중"><circle cx="110" cy="110" r="' + R0 + '" fill="none" stroke="var(--surface3)" stroke-width="28"/>' + ring + '</svg>'
        + '<div class="wdon-t"><span>그날 총자산</span><b>' + M(thenV, { compact: true }) + '</b></div></div>'
        + '<div class="wleg">' + segs.map(s0 => '<span><i style="background:' + s0[2] + '"></i>' + esc(s0[0]) + ' ' + P(s0[1], 0) + '</span>').join('') + '</div>'
        + '<div class="wnote" style="text-align:center">' + (d.src === 'hist' ? '장기 곡선과 같은 그날 마감가 · 그날 시세가 없는 코인은 합계에서 빼요' : '최근 30일 = 그날 마감 직전 화면 값 그대로') + ' · 보관처 = 그날까지 원장 기록'
          + tmConf(d) + '</div></div>';
      const locNmH = v9 => { const t9 = String(v9 || ''), i9 = t9.indexOf(' · '), a9 = window.__tjSearchApi;
        if (i9 < 0) return '<span class="pvl">' + esc(t9) + '</span>';
        const nm9 = t9.slice(i9 + 3);
        return '<span class="pvl">' + esc(t9.slice(0, i9 + 3)) + '</span><span class="pvl" data-pk="w">' + esc(a9 && typeof a9.ownNm === 'function' ? a9.ownNm(nm9, 'w') : nm9) + '</span>'; };
      const rows = items.map((it, i) => { const cg9 = it.chg != null && DV(it.usd) > 0 ? num(it.nowUsd) / DV(it.usd) * 100 - 100 : null, lc = arr(it.locs), lt = lc.length ? lc.slice(0, 2).map(l => locNmH(l[0])).join(' · ') + (num(it.nLocs) > 2 ? ' 외 ' + (num(it.nLocs) - 2) + '곳' : '') : '보관처 기록 없음';
        const lg9 = x.S.D && x.S.D.symLogo && x.S.D.symLogo[it.sym];
        return '<div class="rw"><span class="n">' + (typeof x.icon === 'function' ? x.icon(it.sym, 'sm', lg9 ? { ck: lg9.ck, ca: lg9.ca } : {}) : '<span class="av" style="background:' + PAL[i % 5] + '">' + esc(String(it.sym).slice(0, 1)) + '</span>') + '<span style="min-width:0"><b>' + esc(it.sym) + (it.approx ? '<span class="wapx" aria-label="어림">≈</span>' : '') + '</b><small>' + lt + '</small></span></span>'
          + '<span class="r">' + P(it.share, 1) + '</span><span class="r c3">' + M(DV(it.usd), { compact: true }) + '</span><span class="r ' + cls(cg9) + '">' + (cg9 != null ? P(cg9, 1, true) : '<span class="pvx" style="color:var(--faint)">시세 없음</span>') + '</span></div>'; }).join('');
      const tbl = '<div class="wcard"><div class="wtbl"><div class="hd"><span>코인 · 보관처</span><span class="r">비중</span><span class="r c3">그날 평가</span><span class="r">지금 그대로면</span></div>' + rows
        + (d.rest ? '<div class="rw"><span class="n"><span class="av" style="background:var(--c5)">+</span><span><b>그 밖 <span class="pvx">' + d.rest.n + '종</span></b><small>작은 보유 합</small></span></span><span class="r">' + P(d.rest.usd / d.total * 100, 1) + '</span><span class="r c3">' + M(DV(d.rest.usd), { compact: true }) + '</span><span class="r ' + cls(d.rest.usd ? d.rest.nowUsd / DV(d.rest.usd) - 1 : 0) + '">' + (d.rest.usd && d.rest.nowUsd ? P((d.rest.nowUsd / DV(d.rest.usd) - 1) * 100, 1, true) : '') + '</span></div>' : '')
        + (d.noPx && num(d.noPx.n) ? '<div class="rw"><span class="n"><span class="av" style="background:var(--line2)">?</span><span><b>그날 시세 없음 <span class="pvx">' + num(d.noPx.n) + '종</span></b><small>합계에서 뺐어요</small></span></span><span class="r">—</span><span class="r c3">—</span><span class="r">' + (num(d.noPx.nowUsd) > 0 ? '<span class="wapx" aria-label="지금 시세로 치면">≈</span>' + M(d.noPx.nowUsd, { compact: true }) : '') + '</span></div>' : '') + '</div></div>';
      const cu = num(d.curveUsd), cuN = cu > 0 && d.total && Math.abs(d.total / cu - 1) > 0.005
        ? '<div class="wnote" style="margin:-4px 0 12px">위 곡선의 그날 값(' + M(DV(cu), { compact: true }) + ')과 다른 건 그 뒤 들어온 기록까지 반영해 다시 셌기 때문이에요</div>' : '';
      return scr + '<div class="wtm-dat" data-d="' + esc(T.date) + '">' + cuN + cmp + '<div class="wtm-body">' + don + tbl + '</div></div>';
    },
    after: el => tmBind(el),
    key: ev => { if (ev.target && /^(INPUT|TEXTAREA)$/.test(ev.target.tagName)) return; if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') { ev.preventDefault(); tmStep(ev.key === 'ArrowLeft' ? -1 : 1, ev.shiftKey ? 7 : 1); } }
  };
  function tmConf(d) {
    const it = arr(d.items), tot = it.reduce((a, z) => a + Math.max(0, num(z.usd)), 0), ok = it.filter(z => !z.approx).reduce((a, z) => a + Math.max(0, num(z.usd)), 0);
    const nm = d.noPx ? num(d.noPx.n) : 0;
    return tot > 0 ? '<br>시세 기준 = <span class="pvx">' + esc(md(d.date)) + '</span> 마감 · 가격 확인 ' + P(ok / tot * 100, 0) + (nm ? ' · 그날 시세 없는 코인 <span class="pvx">' + nm + '종</span>' : '') : '';
  }
  function skelRows(n) { let h = '<div class="wcard" style="margin-top:14px;display:flex;flex-direction:column;gap:14px">'; for (let i = 0; i < n; i++) h += '<div class="wskel" style="width:' + (92 - i * 7) + '%"></div>'; return h + '</div>'; }
  function tmScrubber() {
    const T = st.tm, S9 = T.series, n = S9.length, W = 1000, H = 84;
    const vs = S9.map(d => d[1]), lo = Math.min(...vs), hi = Math.max(...vs), sp = hi - lo || 1;
    const xy = (i, v) => [(n > 1 ? i / (n - 1) : 0) * W, H - 8 - (v - lo) / sp * (H - 18)];
    const idx = Math.max(0, S9.findIndex(d => d[0] === T.date));
    const pth = a => a.map((d, i) => { const p = xy(i, d[1]); return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
    const hp = xy(idx, S9[idx][1]), fx = n > 1 ? idx / (n - 1) : 0;
    return '<div class="wtm-scr" id="wtmScr" tabindex="0" role="slider" aria-label="날짜 — 끌거나 ← → 로 옮겨요" aria-valuemin="0" aria-valuemax="' + (n - 1) + '" aria-valuenow="' + idx + '" aria-valuetext="' + esc(T.date) + '">'
      + '<div class="wtm-plot"><svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">'
      + '<path d="' + pth(S9) + '" fill="none" stroke="var(--rule)" stroke-width="2" vector-effect="non-scaling-stroke"/><path id="wtmPast" d="' + pth(S9.slice(0, idx + 1)) + '" fill="none" stroke="var(--accent)" stroke-width="2.6" vector-effect="non-scaling-stroke"/></svg>'
      + '<span class="wtm-ln" id="wtmLn" style="left:' + (fx * 100).toFixed(3) + '%"></span><span class="wtm-dot" id="wtmDot" style="left:' + (fx * 100).toFixed(3) + '%;top:' + (hp[1] / H * 100).toFixed(2) + '%"></span></div>'
      + '<div class="wtm-ax"><span>' + esc(S9[0][0].slice(0, 7)) + '</span><button type="button" class="wtm-ib" data-w="tmPrev" aria-label="하루 전">' + ICO.l + '</button><span class="sp"><span class="wst-dk">끌어서 날짜 이동 · ← → 하루씩</span><span class="wst-mb" id="wtmD">' + esc(md(T.date)) + '</span></span>'
      + '<button type="button" class="wtm-ib" data-w="tmNext" aria-label="하루 뒤">' + ICO.r + '</button><span>어제</span></div></div>';
  }
  function tmBind(el) {
    const s = $('#wtmScr', el); if (!s) return;
    let drag = false;
    const plot = $('.wtm-plot', s);
    const pick = ev => { const r = plot.getBoundingClientRect(), n = st.tm.series.length; const f = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)); return st.tm.series[Math.round(f * (n - 1))][0]; };
    plot.addEventListener('pointerdown', ev => { drag = true; try { plot.setPointerCapture(ev.pointerId); } catch (e) {  } tmSet(pick(ev), true); });
    plot.addEventListener('pointermove', ev => { if (drag) tmSet(pick(ev), true); });
    const up = ev => { if (!drag) return; drag = false; tmSet(pick(ev), false); };
    plot.addEventListener('pointerup', up); plot.addEventListener('pointercancel', () => { drag = false; });
  }
  function tmSet(iso, live) {
    if (!iso) return;
    const ch = iso !== st.tm.date;
    st.tm.date = iso;
    if (live) {
      const S9 = st.tm.series, n = S9.length, i = S9.findIndex(d => d[0] === iso);
      if (i >= 0) {
        const vs = S9.map(d => d[1]), lo = Math.min(...vs), hi = Math.max(...vs), sp = hi - lo || 1, fx = n > 1 ? i / (n - 1) : 0, y = 84 - 8 - (S9[i][1] - lo) / sp * (84 - 18);
        const dEl = $('#wtmDot'), ln = $('#wtmLn'), pp = $('#wtmPast');
        if (dEl) { dEl.style.left = (fx * 100).toFixed(3) + '%'; dEl.style.top = (y / 84 * 100).toFixed(2) + '%'; }
        if (ln) ln.style.left = (fx * 100).toFixed(3) + '%';
        if (pp) pp.setAttribute('d', S9.slice(0, i + 1).map((d, k) => (k ? 'L' : 'M') + ((n > 1 ? k / (n - 1) : 0) * 1000).toFixed(1) + ' ' + (84 - 8 - (d[1] - lo) / sp * (84 - 18)).toFixed(1)).join(' '));
      }
      const t = $('#wowT'), md9 = $('#wtmD'), s = $('#wtmScr');
      const dat = $('.wtm-dat');
      if (dat) { const off = dat.getAttribute('data-d') !== iso; dat.classList.toggle('wtm-stale', off); if (off) dat.setAttribute('data-wait', md(iso) + ' 지갑 — 놓으면 받아요'); }
      if (t) t.textContent = dlabel(iso) + '의 내 지갑';
      if (md9) md9.textContent = md(iso);
      if (s) { s.setAttribute('aria-valuenow', String(i)); s.setAttribute('aria-valuetext', iso); }
      return;
    }
    paint();
    if (!st.tm.cache[iso]) tmFetch(iso);
    void ch;
  }
  function tmStep(dir, k) { const S9 = st.tm.series || [], i = S9.findIndex(d => d[0] === st.tm.date); const j = Math.max(0, Math.min(S9.length - 1, i + dir * (k || 1))); if (S9[j]) tmSet(S9[j][0], false); }
  function tmFetch(iso, force) {
    const T = st.tm;
    if (T.cache[iso] && !force) { if (st.view === 'tm') paint(); return; }
    T.err = ''; const tk = ++T.t;
    clearTimeout(T.timer);
    T.timer = setTimeout(() => {
      fetch('/api/wow/tm?date=' + encodeURIComponent(iso), { cache: 'no-store', credentials: 'same-origin' }).then(r => r.json()).then(j => {
        if (tk !== T.t) return;
        if (j && j.ok) { T.cache[iso] = j; const ks = Object.keys(T.cache); if (ks.length > 40) delete T.cache[ks[0]]; } else T.err = (j && j.error) || '그날 보유를 만들지 못했어요';
        if (st.view === 'tm') paint();
      }).catch(() => { if (tk === T.t) { T.err = '불러오지 못했어요 — 잠시 뒤 다시'; if (st.view === 'tm') paint(); } });
    }, 180);
  }
  Object.assign(A, {
    tmPrev: () => tmStep(-1), tmNext: () => tmStep(1),
    tmCmp: () => { st.tm.cmp = !st.tm.cmp; paint(); }
  });

  const FL_DST = { 'now:coin_ex': 'var(--c3)', 'now:coin_w': 'var(--c3)', 'now:stable': 'var(--c2)', 'now:lp': 'var(--c1)', 'now:cash': 'var(--c4)', 'now:krw_out': 'var(--c5)', 'now:sent': 'var(--ext)', 'now:toex': 'var(--line2)', 'now:fee': 'var(--danger)', 'now:loss': 'var(--down)',
    'now:bridge': 'var(--c4)', 'now:unexpl': 'var(--warn)' };
  const FL_CYC = { ex: ['var(--c1)', 'var(--c2)', 'var(--c4)', 'var(--c3)', 'var(--wfl5)'], ch: ['var(--c1)', 'var(--c4)', 'var(--c2)', 'var(--c3)', 'var(--wfl5)'] };
  const FL_WHY = { krw: '은행 → 거래소 원화 입금', coin_in: '밖에서 받은 코인(전송·보상·에어드랍 · 받은 날 가격)', open: '수집 시작 때 있던 코인 · 거래소 대사 보정(그날 가격)',
    route: '거래소 출금 → 내 지갑 도착(출금 날 가격 · 오간 것 상계)', back: '내 지갑 → 거래소 입금(상계하고 남은 몫)', hold: '지금 보유(지금 시세)', cash: '거래소 원화 예수금(지금 환율)',
    krw_out: '거래소 → 은행 원화 출금', sent: '밖으로 보낸 돈(보낸 날 값 · 거래소 외부 출금 포함)', fee: '체인에 낸 가스',
    gain: '들어온 것보다 지금·나간 것이 많은 만큼(시세·매매 + 짝 못 찾은 기록 — 추정)', loss: '들어온 것보다 지금·나간 것이 적은 만큼(시세·매매 + 짝 못 찾은 기록 — 추정)',
    bridge_in: '다른 체인·내 지갑에서 브릿지로 옮겨 온 코인(출발과 짝지은 것 — 밖에서 받은 돈 아님 · 도착 날 가격)', bridge_out: '브릿지로 다른 체인에 옮긴 코인(도착과 짝지은 것 · 도착 쪽 금액 — 차이는 수수료)',
    unexpl: '브릿지·내 다른 지갑으로 보냈는데 도착을 못 찾은 것 — 손실이 아니라 아직 설명 안 된 이동(보낸 날 가격)' };
  const FL_PER = [['all', '전체'], ['year', '올해'], ['month', '이번 달']];
  const FL_SHORT_SRC = { 'in:krw': '원화', 'in:coin': '코인', 'in:open': '시작 보유', 'in:back': '되돌림', 'in:bridge': '옮겨 옴', 'in:gain': '늘어남' };
  const FL_SHORT = { Ethereum: '이더리움', Arbitrum: '아비트럼', Optimism: '옵티미즘', Polygon: '폴리곤', Avalanche: '아발란체', 'BNB Chain': 'BNB', 'BNB Smart Chain': 'BNB',
    Hyperliquid: '하이퍼', HyperEVM: '하이퍼', Berachain: '베라', Unichain: '유니체인', Abstract: '앱스트랙', Scroll: '스크롤', Linea: '리니아', Solana: '솔라나', Mantle: '맨틀', Monad: '모나드', Sonic: '소닉', zkSync: 'zkSync', 'zkSync Era': 'zkSync', Blast: 'Blast', Kaia: '카이아' };
  const flSince = p => (p === 'year' ? todayISO().slice(0, 4) + '-01-01' : p === 'month' ? todayISO().slice(0, 8) + '01' : '');
  VIEWS.fl = {
    head: () => ({ k: '자금 흐름 지도 · ' + (st.fl.per === 'year' ? '올해' : st.fl.per === 'month' ? '이번 달' : '처음부터 지금까지'), t: '넣은 돈이 지금 어디에 얼마나 있나',
      act: '<span class="wseg" role="group" aria-label="기간">' + FL_PER.map(o => '<button type="button" class="' + (st.fl.per === o[0] ? 'on' : '') + '" aria-pressed="' + (st.fl.per === o[0]) + '" data-w="flPer" data-v="' + o[0] + '">' + o[1] + '</button>').join('') + '</span>' }),
    load: () => {
      const F = st.fl, per = F.per;
      if (F.cache[per] || F.busy === per) return;
      F.busy = per; F.err = '';
      const q = flSince(per);
      fetch('/api/wow/flows' + (q ? '?since=' + q : ''), { cache: 'no-store', credentials: 'same-origin' }).then(r => r.json()).then(j => {
        if (F.busy === per) F.busy = '';
        if (j && j.ok) F.cache[per] = j; else F.err = (j && j.error) || '만들지 못했어요';
        if (st.view === 'fl' && F.per === per) paint();
      }).catch(() => { if (F.busy === per) F.busy = ''; F.err = '불러오지 못했어요 — 잠시 뒤 다시'; if (st.view === 'fl') paint(); });
    },
    body: () => {
      const F = st.fl, d = F.cache[F.per];
      if (!d) return F.err ? '<div class="wempty">' + esc(F.err) + '</div>' : '<div class="wcard"><div class="wskel" style="height:440px;border-radius:14px"></div></div>';
      const t = d.totals || {};
      if (!arr(d.links).length) return '<div class="wempty">이 기간엔 그릴 흐름이 없어요 — 입출금·보유가 쌓이면 보여요</div>';
      const tot = '<div class="wfl-tot"><span>원화로 넣은 돈 <b>' + M(t.in_krw, { compact: true }) + '</b></span><span>코인으로 받은 몫 <b>' + M(t.in_coin, { compact: true }) + '</b></span>'
        + (num(t.in_open) ? '<span>시작 보유 · 대사 보정 <b>' + M(t.in_open, { compact: true }) + '</b></span>' : '')
        + (num(t.bridge) ? '<span>체인끼리 옮긴 몫 <b>' + M(t.bridge, { compact: true }) + '</b></span>' : '') + (num(t.unexpl) ? '<span>설명 안 됨 <b>' + M(t.unexpl, { compact: true }) + '</b></span>' : '')
        + '<span>지금 있는 돈 <b>' + M(t.now, { compact: true }) + '</b></span><span>원화로 돌아온 돈 <b>' + M(t.out_krw, { compact: true }) + '</b></span></div>';
      return tot + '<div class="wfl-wrap" id="wflWrap"><div class="wfl-cols" id="wflCols"></div><div id="wflMap" style="position:relative"></div></div>'
        + '<div class="wfl-sel" id="wflSel" aria-live="polite">' + flSelHTML() + '</div>'
        + '<details class="wnote wnd"><summary>띠 굵기 = 금액 · 띠를 누르면 그 길의 전송 목록 · 늘어난·줄어든 몫은 추정(손익 아님) <span class="wndm">자세히</span></summary>'
        + '<div class="wndb">띠 굵기 = 금액(그날 가격) · 띠를 누르면 그 길의 전송 목록 · 거래소 ↔ 지갑 = 출금과 도착을 짝지은 것(<span class="pvx">' + num(t.routes) + '건</span> · 내 거래소끼리 옮긴 <span class="pvx">' + num(t.internal) + '건</span>은 뺐어요) · 체인끼리 옮긴 것 = 브릿지 출발과 도착 짝(<span class="pvx">' + num(t.bridgeN) + '건</span> · 못 찾은 것 = 설명 안 됨) · 지금 있는 곳 = 지금 시세 · '
        + (t.pxDay != null ? '이동 금액 중 그날 가격 ' + P(num(t.pxDay) * 100, 0) + (num(t.pxDay) < 0.995 ? '(나머지는 그날 가격이 없어 지금 시세)' : '') + (num(t.pxNone) ? ' · 가격 없어 뺀 기록 <span class="pvx">' + num(t.pxNone) + '건</span>' : '') + ' · ' : '')
        + '<b style="color:var(--up)">' + (F.per === 'all' ? '늘어난 몫' : '그 전부터 있던 돈 · 늘어난 몫') + '</b> / <b style="color:var(--down)">줄어든 몫</b> = 들어온 것과 지금·나간 것의 차이 — 시세·매매 손익에 원장에서 짝을 못 찾은 이동·거래소 대사 보정이 섞인 추정이라 손익으로 읽지 마세요(손익은 매매일지·대시보드)</div></details>';
    },
    after: el => {
      const w = $('#wflWrap', el); if (!w) return;
      flDraw();
      w.addEventListener('mouseover', ev => { const b = ev.target.closest && ev.target.closest('.wfl-band'); if (b) flHi(+b.getAttribute('data-i'), false); });
      w.addEventListener('mouseleave', () => flHi(-1, false));
      w.addEventListener('keydown', ev => { const b = ev.target.closest && ev.target.closest('.wfl-band'); if (b && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); flHi(+b.getAttribute('data-i'), true); } });
    }
  };
  let flRsz = 0;
  window.addEventListener('resize', () => { if (st.view !== 'fl') return; clearTimeout(flRsz); flRsz = setTimeout(flDraw, 120); });
  function flLayout(d, W, H, mob) {
    const nodes = arr(d.nodes).map(n => Object.assign({}, n, { inV: 0, outV: 0 })), byId = {};
    nodes.forEach(n => { byId[n.id] = n; });
    const links = arr(d.links).filter(l => byId[l.s] && byId[l.t] && num(l.usd) > 0).map((l, i) => Object.assign({ i }, l));
    links.forEach(l => { byId[l.s].outV += l.usd; byId[l.t].inV += l.usd; });
    nodes.forEach(n => { n.v = Math.max(n.inV, n.outV); });
    const cols = [[], [], [], []];
    nodes.forEach(n => cols[Math.max(0, Math.min(3, n.col))].push(n));
    cols.forEach(c => c.sort((a, b) => (a.kind === 'gain' || a.id === 'now:loss') - (b.kind === 'gain' || b.id === 'now:loss') || b.v - a.v));
    const pad = 14, maxN = Math.max(...cols.map(c => c.length)), avail = H - pad * Math.max(0, maxN - 1) - 20;
    const maxSum = Math.max(...cols.map(c => c.reduce((a, n) => a + n.v, 0))) || 1;
    let k = avail / maxSum;
    const sizeUp = () => {
      links.forEach(l => { l.h = Math.max(1, l.usd * k); });
      nodes.forEach(n => { let hi = 0, ho = 0; links.forEach(l => { if (l.t === n.id) hi += l.h; if (l.s === n.id) ho += l.h; }); n.h = Math.max(2, hi, ho); });
      return Math.max(...cols.map(c => c.reduce((a, n) => a + n.h, 0)));
    };
    for (let t = 0; t < 3; t++) { const top = sizeUp(); if (top <= avail + 0.5) break; k *= Math.max(0.2, (avail - (top - maxSum * k)) / (maxSum * k)); }
    const nw = W < 400 ? 8 : 12, f9 = W < 400 ? [0.3, 0.6] : [0.34, 0.67], colX = [0, (W - nw) * f9[0], (W - nw) * f9[1], W - nw];
    cols.forEach((c, ci) => { const tot = c.reduce((a, n) => a + n.h, 0) + pad * Math.max(0, c.length - 1); let y = Math.max(0, (H - tot) / 2); c.forEach(n => { n.x = colX[ci]; n.y = y; y += n.h + pad; n.oy = n.y; n.iy = n.y; }); });
    links.sort((a, b) => byId[a.t].y - byId[b.t].y);
    links.forEach(l => { const s = byId[l.s]; l.y0 = s.oy; s.oy += l.h; });
    links.slice().sort((a, b) => byId[a.s].y - byId[b.s].y).forEach(l => { const t = byId[l.t]; l.y1 = t.iy; t.iy += l.h; });
    const ci = { ex: 0, ch: 0 };
    cols.forEach(c => c.forEach(n => { n.color = n.kind === 'src' ? (n.id === 'in:krw' ? 'var(--text)' : n.id === 'in:open' ? 'var(--c2)' : n.id === 'in:back' ? 'var(--line2)' : n.id === 'in:bridge' ? 'var(--c1)' : 'var(--c4)') : n.kind === 'gain' ? 'var(--up)' : n.kind === 'dst' ? (FL_DST[n.id] || 'var(--c5)') : FL_CYC[n.kind] ? FL_CYC[n.kind][ci[n.kind]++ % 5] : 'var(--c5)'; }));
    return { nodes, links, byId, nw, k, colX };
  }
  function flDraw() {
    const F = st.fl, d = F.cache[F.per], map = $('#wflMap'), colsEl = $('#wflCols'); if (!d || !map) return;
    const r = flMap(d, Math.max(300, map.clientWidth));
    map.style.height = r.H + 'px'; map.innerHTML = r.map;
    if (colsEl) colsEl.innerHTML = r.cols;
    flFit(map);
  }
  function flFit(map) {
    const F = st.fl, L = F.L, leg = []; if (!L) return;
    const last = {};
    Array.from(map.querySelectorAll('.wfl-lb')).map(e => ({ e, r: e.getBoundingClientRect(), c: e.getAttribute('data-c') })).sort((a, b) => a.c - b.c || a.r.top - b.r.top).forEach(x => {
      const b = x.e.querySelector('b'), over = b && (b.scrollWidth > b.clientWidth || b.scrollHeight > b.clientHeight + 1);
      if (over || (last[x.c] != null && x.r.top < last[x.c] + 2)) { const n = L.byId[x.e.getAttribute('data-id')]; if (n) leg.push(n); x.e.remove(); return; }
      last[x.c] = x.r.bottom;
    });
    let lg = map.parentNode && map.parentNode.querySelector('.wfl-legend');
    if (!lg && map.parentNode) { lg = document.createElement('div'); lg.className = 'wfl-legend'; map.parentNode.appendChild(lg); }
    if (!lg) return;
    const tot = F.tot || 1;
    lg.innerHTML = leg.length ? '<span class="k">작은 칸</span>' + leg.sort((a, b) => a.col - b.col || a.y - b.y).map(n => { const sh = n.v / tot * 100;
      return '<span data-n="' + esc(n.id) + '"><i style="background:' + n.color + '"></i>' + esc(n.label) + ' <span class="pvx">' + sh.toFixed(sh < 10 ? 1 : 0) + '%</span></span>'; }).join('') : '';
  }
  function flMap(d, cw) {
    const F = st.fl, mob = cw < 640, Rm = mob ? 78 : Math.min(230, Math.round(cw * 0.2)), H = mob ? 600 : 520;
    const L = flLayout(d, cw - Rm, H); F.L = L;
    const tot = L.nodes.filter(n => n.col === 0).reduce((a, n) => a + n.outV, 0) || 1;
    const bands = L.links.map(l => { const s = L.byId[l.s], t = L.byId[l.t], x0 = s.x + L.nw, x1 = t.x, xm = (x0 + x1) / 2, est = l.kind === 'gain' || l.kind === 'loss';
      return '<path class="wfl-band' + (est ? ' est' : '') + (F.sel === l.i ? ' on' : '') + '" data-w="flSel" data-i="' + l.i + '" tabindex="0" role="button" aria-label="' + esc(s.label + ' → ' + t.label) + '" d="M' + x0.toFixed(1) + ' ' + l.y0.toFixed(1) + ' C' + xm.toFixed(1) + ' ' + l.y0.toFixed(1) + ' ' + xm.toFixed(1) + ' ' + l.y1.toFixed(1) + ' ' + x1.toFixed(1) + ' ' + l.y1.toFixed(1)
        + ' L' + x1.toFixed(1) + ' ' + (l.y1 + l.h).toFixed(1) + ' C' + xm.toFixed(1) + ' ' + (l.y1 + l.h).toFixed(1) + ' ' + xm.toFixed(1) + ' ' + (l.y0 + l.h).toFixed(1) + ' ' + x0.toFixed(1) + ' ' + (l.y0 + l.h).toFixed(1) + 'Z" fill="' + (est ? L.byId[l.kind === 'gain' ? l.s : l.t].color : s.color) + '" fill-opacity="' + (est ? '.16' : '.34') + '"'
        + (est ? ' stroke="' + L.byId[l.kind === 'gain' ? l.s : l.t].color + '" stroke-opacity=".55" stroke-dasharray="3 4"' : '') + '/>'; }).join('');
    const rects = L.nodes.map(n => '<rect x="' + n.x.toFixed(1) + '" y="' + n.y.toFixed(1) + '" width="' + L.nw + '" height="' + n.h.toFixed(1) + '" rx="4" fill="' + n.color + '"/>').join('');
    const labs = L.nodes.map(n => {
      const thin = n.h < (mob ? 13 : 11);
      const gx = mob ? 4 : 6, right = n.col === 3, maxW = right ? Rm - 8 : (L.colX[n.col + 1] - n.x - L.nw - gx - (mob ? 2 : 4)), sh = n.v / tot * 100;
      const two = !thin && n.h >= (right ? 30 : 34);
      return '<div class="wfl-lb' + (right ? ' r' : '') + (thin ? ' thin' : '') + '" data-c="' + n.col + '" data-id="' + esc(n.id) + '" style="left:' + (n.x + L.nw + gx).toFixed(1) + 'px;top:' + (n.y + n.h / 2).toFixed(1) + 'px;max-width:' + Math.max(40, maxW).toFixed(0) + 'px">'
        + '<b>' + esc(mob && n.kind === 'ch' ? n.label.replace(/ 지갑$/, '') : n.label) + '</b>' + (two ? '<span>' + (right && !mob ? M(n.v, { compact: true }) + ' · ' : '') + '<span class="pvx">' + sh.toFixed(sh < 10 ? 1 : 0) + '%</span></span>' : '') + '</div>';
    }).join('');
    F.tot = tot;
    return { H, map: '<svg width="' + cw + '" height="' + H + '" viewBox="0 0 ' + cw + ' ' + H + '" role="img" aria-label="자금 흐름 지도"><g id="wflBands"' + (F.sel >= 0 ? ' class="wfl-dim"' : '') + '>' + bands + '</g>' + rects + '</svg>' + labs,
      cols: [['넣은 돈', 0], ['거래소', 1], ['체인 · 지갑', 2], ['지금 있는 곳', 3]].map(c => '<span style="left:' + (L.colX[c[1]]).toFixed(1) + 'px">' + c[0] + '</span>').join('') };
  }
  const fdate = ts => { if (!ts) return ''; const d = new Date(num(ts) * 1000 + KST); return String(d.getUTCFullYear()).slice(2) + '.' + (d.getUTCMonth() + 1) + '.' + d.getUTCDate(); };
  function flSelHTML() {
    const L = st.fl.L, i = st.fl.sel;
    if (!L || i < 0) return '<div class="wfl-hint">띠를 누르면 그 길로 간 돈과 전송 목록을 보여 줘요</div>';
    const l = L.links.find(z => z.i === i); if (!l) return '';
    const s = L.byId[l.s], t = L.byId[l.t], rows = arr(l.rows), n = num(l.n) || rows.length;
    const x9 = X(), Q = v => (x9 && typeof x9.q === 'function' ? x9.q(v) : '');
    const rowOf = r => (Array.isArray(r) ? { t: r[0], sym: r[1], usd: null, qty: null, note: '' } : r || {});
    const sentNameH = v => {
      const a0 = window.__tjSearchApi, s0 = String(v || '').trim(), D9 = a0 && a0.S && a0.S.D;
      const named = !!D9 && arr(D9.of).some(o => o && String(o.alias || o.label || '').trim().slice(0, 40) === s0);
      const pk = named || /^(?:0x[0-9a-fA-F]{6,64}|[A-Za-z0-9]{3,12}…[A-Za-z0-9]{3,10}|[1-9A-HJ-NP-Za-km-z]{32,44})$/.test(s0) ? 'w' : 'm';
      return '<span class="pvl" data-pk="' + pk + '">' + esc(a0 && typeof a0.ownNm === 'function' ? a0.ownNm(s0, pk) : s0) + '</span>';
    };
    const sentCh = l.kind === 'sent' && s && s.kind === 'ch';
    const list = rows.length ? '<div class="wfl-rows">' + rows.map(rowOf).map(r => '<div class="wfl-r"><span class="d pvx">' + esc(fdate(r.t)) + '</span><span class="n' + (l.kind === 'sent' && !sentCh ? ' pvl' : '') + '">' + (sentCh ? sentNameH(r.sym) : esc(r.sym || ''))
        + (r.qty != null && num(r.qty) ? ' <small class="num">' + Q(num(r.qty)) + '</small>' : '') + (r.note ? ' <small>' + esc(r.note) + '</small>' : '') + '</span><span class="v">' + (r.usd != null ? M(num(r.usd), { compact: true }) : '—') + '</span></div>').join('')
      + (n > rows.length ? '<div class="wnote">최근·큰 순 <span class="pvx">' + rows.length + '건</span>만 · 전체 <span class="pvx">' + n + '건</span></div>' : '') + '</div>' : '';
    return '<div class="wfl-sh"><span class="sw" style="background:' + s.color + '"></span><b>' + esc(s.label) + ' → ' + esc(t.label) + '</b><span class="amt">' + M(l.usd) + '</span><span class="sp"></span>'
      + (l.kind === 'sent' ? '<button type="button" class="wbtn" data-w="flGo" data-v="outflows">보낸 내역</button>' : '') + '<button type="button" class="wbtn" data-w="flSel" data-i="-1">전체 보기</button></div>'
      + '<div class="wnote">' + esc(FL_WHY[l.kind] || '') + (n ? ' · <span class="pvx">' + n + '건</span>' : '') + '</div>' + list;
  }
  function flHi(i, sticky) {
    if (sticky) st.fl.sel = i;
    const g = $('#wflBands'); if (!g) return;
    const on = i >= 0 ? i : st.fl.sel;
    g.classList.toggle('wfl-dim', on >= 0);
    g.querySelectorAll('.wfl-band').forEach(b => b.classList.toggle('on', +b.getAttribute('data-i') === on));
    if (sticky) { const s = $('#wflSel'); if (s) { s.innerHTML = flSelHTML(); if (i >= 0 && X() && X().S.mobile) { try { s.scrollIntoView({ block: 'nearest', behavior: reduce() ? 'auto' : 'smooth' }); } catch (e) {  } } } }
  }
  Object.assign(A, {
    flSel: el => flHi(+el.getAttribute('data-i'), true),
    flPer: el => { st.fl.per = el.getAttribute('data-v') || 'all'; st.fl.sel = -1; paint(); VIEWS.fl.load(); },
    flGo: el => { const v = el.getAttribute('data-v'); closeAndGo(() => { location.hash = '#' + v; }); }
  });

  const RULE_STOP = [-5, -10, -15, -20], RULE_TGT = [10, 25, 50, 100];
  const rule = () => { let r = null; try { r = JSON.parse(LSget('tj_v2_planrule', 'null')); } catch (e) { r = null; } return { stop: r && RULE_STOP.indexOf(r.stop) >= 0 ? r.stop : -10, tgt: r && RULE_TGT.indexOf(r.tgt) >= 0 ? r.tgt : 25 }; };
  const isoOfKey = k => { const x = X(); return /^\d{4}-\d{2}-\d{2}$/.test(k) ? k : (x && x.isoDay(k)) || ''; };
  function planRows() {
    const x = X(), D = x && x.S.D; if (!D) return [];
    const R = rule(), out = [];
    const cardOf = {}, cardLast = {};
    arr(D.merged).forEach(m9 => { arr(m9 && m9._legs).forEach(k9 => { cardOf[k9] = m9.key; if (m9._last) cardLast[k9] = String(m9._last).slice(0, 10); }); });
    const src9 = arr(D.positions).length ? arr(D.positions) : arr(D.merged);
    src9.forEach(p => {
      if (!p || p.kind === 'gas' || p._lp || p.dust || num(p.soldQty) <= 0 || num(p.avg) <= 0 || num(p.avgSell) <= 0) return;
      if (/^(USDT|USDC|DAI|FDUSD|USDE|PYUSD|USD1)$/i.test(String(p.sym))) return;
      const days = Object.keys(p.realizedByDay || {}).map(isoOfKey).filter(Boolean).sort();
      const last = p._last && /^\d{4}-\d{2}-\d{2}/.test(p._last) ? String(p._last).slice(0, 10) : days[days.length - 1] || (/^\d{4}-\d{2}-\d{2}/.test(cardLast[p.key] || '') ? cardLast[p.key] : '');
      if (!last) return;
      const pnl = (num(p.avgSell) / num(p.avg) - 1) * 100, pl = D.plans && (D.plans[p.key] || (cardOf[p.key] && D.plans[cardOf[p.key]]));
      const sg = v9 => (v9 > 0 ? '+' : v9 < 0 ? '−' : '') + Math.abs(v9).toFixed(1) + '%';
      const T = pl && num(pl.target) > 0 ? num(pl.target) : null, Sx = pl && num(pl.stop) > 0 ? num(pl.stop) : null, own = T != null || Sx != null, avg = num(p.avg);
      const judge = s => {
        const pc = (s / avg - 1) * 100;
        if (own) {
          if (T != null && s >= T * 0.98) return ['plan', '직접 건 목표가에서 매도'];
          if (Sx != null) { if (s <= Sx * 0.97) return ['late', '직접 건 손절선 아래까지 버팀']; if (s <= Sx * 1.03) return ['plan', '직접 건 손절선에서 정리']; }
          if (s < avg) {
            if (Sx != null) return ['cut', '손절선 전에 정리'];
            return pc <= R.stop - 3 ? ['late', '손절 −' + Math.abs(R.stop) + '%(기본) · 실제 ' + sg(pc)] : pc <= R.stop + 1.5 ? ['plan', '손절 −' + Math.abs(R.stop) + '%(기본) · 실제 ' + sg(pc)] : ['cut', '손절 −' + Math.abs(R.stop) + '%(기본) 전에 정리'];
          }
          if (T != null) return ['early', '직접 건 목표가 도달 전 매도'];
          return pc >= R.tgt * 0.98 ? ['plan', '목표 +' + R.tgt + '%(기본) · 실제 ' + sg(pc)] : ['early', '목표 +' + R.tgt + '%(기본) 도달 전 매도'];
        }
        if (pc >= R.tgt * 0.98) return ['plan', '목표 +' + R.tgt + '% · 실제 ' + sg(pc)];
        if (pc <= R.stop - 3) return ['late', '손절 −' + Math.abs(R.stop) + '% · 실제 ' + sg(pc)];
        if (pc <= R.stop + 1.5) return ['plan', '손절 −' + Math.abs(R.stop) + '% · 실제 ' + sg(pc)];
        return pc >= 0 ? ['early', '목표 +' + R.tgt + '% 도달 전 매도'] : ['cut', '손절 −' + Math.abs(R.stop) + '% 전에 정리'];
      };
      const sales = planSales(p);
      const vq = {};
      sales.forEach(z => { const j = judge(z.px); z.v = j[0]; z.t = j[1]; vq[z.v] = (vq[z.v] || 0) + z.q; });
      const qT = sales.reduce((a, z) => a + z.q, 0) || 1;
      const v = Object.keys(VW).reduce((b, k) => (num(vq[k]) > num(vq[b]) + 1e-12 ? k : b), Object.keys(VW).find(k => vq[k] > 0) || 'early');
      const sc = sales.reduce((a, z) => a + z.q * VW[z.v][1], 0) / qT;
      const nReal = sales.filter(z => !z.rest).length, nPlan = sales.filter(z => !z.rest && z.v === 'plan').length;
      const main = (sales.filter(z => z.v === v).sort((a, b) => b.q - a.q)[0] || { t: '' }).t;
      const plan = { own, t: nReal >= 2 ? '나눠 판 ' + nReal + '건 중 ' + nPlan + '건 계획대로 · ' + main : main, n: nReal, nPlan };
      out.push({ key: cardOf[p.key] || p.key, ckey: p.key, sym: p.sym, last, pnl, v, sc, plan, real: num(p.realized) });
    });
    return out.sort((a, b) => (a.last < b.last ? 1 : -1));
  }
  const sigDig = t => { const d = String(t == null ? '' : t).replace(/[^0-9.]/g, '').replace('.', '').replace(/^0+/, ''); return d.length; };
  const pMoney = s => { const n = parseFloat(String(s == null ? '' : s).replace(/[^0-9.\-]/g, '')); return isFinite(n) ? n : 0; };
  function planSales(p) {
    const out = [];
    arr(p.events).forEach(e => {
      const k = String((e && e.k) || ''); if (!/매도/.test(k) || /^LP/.test(k)) return;
      if (e._pay || /대금 지불|스왑 지불/.test(String(e.d || ''))) return;
      let px = num(e.un) > 0 ? num(e.un) : 0;
      const usd9 = String(e.a || '').indexOf('₩') < 0 && sigDig(e.a) >= 3 ? Math.abs(pMoney(e.a)) : 0;
      const q = px > 0 && usd9 > 0 && sigDig(e.q) < 3 ? usd9 / px : Math.abs(pMoney(e.q)); if (!(q > 0)) return;
      if (!px) { const a = pMoney(e.a); if (String(e.a || '').indexOf('₩') < 0 && a && sigDig(e.q) >= 3 && sigDig(e.a) >= 3) px = Math.abs(a / q); }
      if (px > 0) out.push({ px, q });
    });
    const sold = num(p.soldQty), avgS = num(p.avgSell);
    if (!out.length) return [{ px: avgS, q: 1 }];
    const sq = out.reduce((a, z) => a + z.q, 0);
    if (sold > sq * 1.02 && avgS > 0) {
      const rq = sold - sq, rp = avgS * sold - out.reduce((a, z) => a + z.px * z.q, 0);
      if (rq > 0 && rp > 0) out.push({ px: rp / rq, q: rq, rest: true });
    }
    return out;
  }
  const VW = { plan: ['계획대로', 1], cut: ['빨리 정리', 0.75], early: ['일찍 팔았다', 0.4], late: ['손절을 미뤘다', 0] };
  const VCOL = { plan: 'var(--ok)', cut: 'var(--accent)', early: 'var(--warn)', late: 'var(--ext)' };
  const scoreOf = rows => (rows.length ? Math.round(rows.reduce((a, r) => a + (r.sc != null && isFinite(r.sc) ? r.sc : VW[r.v][1]), 0) / rows.length * 100) : 0);
  function planScore() { const rows = planRows(), ym = todayISO().slice(0, 7), cur = rows.filter(r => r.last.slice(0, 7) === ym); const base = cur.length >= 3 ? cur : rows.slice(0, 20); return { n: base.length, score: scoreOf(base) }; }
  VIEWS.ps = {
    head: () => ({ k: '계획 지키기 · ' + (+todayISO().slice(5, 7)) + '월', t: '수익률보다 규율' }),
    key: ev => { const t = ev.target; if (!t || !t.matches || !t.matches('.wps-row[data-w="psGo"]') || ev.repeat || ev.isComposing || ev.altKey || ev.ctrlKey || ev.metaKey) return;
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') { ev.preventDefault(); A.psGo(t); } },
    body: () => {
      const rows = planRows(), R = rule();
      if (!rows.length) return '<div class="wempty">판 기록이 쌓이면 점수가 생겨요 — 목표가·손절선을 걸어 두면 그 계획으로, 아니면 아래 기본 규칙으로 판정해요</div>';
      const ym = todayISO().slice(0, 7), months = [];
      for (let i = 5; i >= 0; i--) { const d = new Date(Date.parse(ym + '-15T00:00:00Z')); d.setUTCMonth(d.getUTCMonth() - i); months.push(d.toISOString().slice(0, 7)); }
      const mrows = mm => rows.filter(r => r.last.slice(0, 7) === mm);
      const cur = mrows(ym), base = cur.length >= 3 ? cur : rows.slice(0, 20), sc = scoreOf(base), prevM = months[4], prev = mrows(prevM);
      const cnt = k => base.filter(r => r.v === k).length;
      const C = 2 * Math.PI * 78, arc = Math.max(0.001, sc / 100) * C;
      const ring = '<div class="wcard wps-ring"><svg viewBox="0 0 190 190" role="img" aria-label="점수 ' + sc + '점"><circle cx="95" cy="95" r="78" fill="none" stroke="var(--surface3)" stroke-width="15"/><circle cx="95" cy="95" r="78" fill="none" stroke="' + (sc >= 70 ? 'var(--ok)' : sc >= 45 ? 'var(--warn)' : 'var(--ext)') + '" stroke-width="15" stroke-linecap="round" stroke-dasharray="' + arc.toFixed(1) + ' ' + C.toFixed(1) + '" transform="rotate(-90 95 95)"/>'
        + '<text x="95" y="96" text-anchor="middle" font-size="44" font-weight="600" fill="var(--text)" font-family="var(--mono)" class="pvx">' + sc + '</text><text x="95" y="122" text-anchor="middle" font-size="12.5" fill="var(--muted)" font-family="var(--sans)" class="pvx">/ 100' + (prev.length >= 3 ? ' · 지난달 ' + scoreOf(prev) : '') + '</text></svg>'
        + '<div style="font-size:14px;color:var(--text2);line-height:1.6" class="pvx">' + (cur.length >= 3 ? '이번 달' : '최근') + ' 판 ' + base.length + '건 중 <b style="color:var(--ok)">' + cnt('plan') + '건</b>을 계획대로 팔았어요</div></div>';
      const bars = '<div class="wcard"><b style="font-size:14px">월별 준수율</b><div class="wps-bars" style="margin-top:12px">' + months.map(mm => { const r = mrows(mm), s9 = r.length ? scoreOf(r) : 0; return '<span class="' + (mm === ym ? 'on' : '') + '" style="height:' + Math.max(4, s9) + '%" aria-label="' + mm + ' ' + (r.length ? s9 + '점' : '판 기록 없음') + '"></span>'; }).join('')
        + '</div><div class="wps-ax">' + months.map(mm => '<span>' + (+mm.slice(5)) + '월</span>').join('') + '</div></div>';
      const ruleH = '<div class="wcard wrule"><b style="font-size:14px">기본 규칙</b><span class="wnote">목표가·손절선을 안 걸어 둔 매도는 이 규칙으로 판정해요(이 기기에 저장)</span><span class="lb">손절</span><span class="wseg">' + RULE_STOP.map(v => '<button type="button" class="' + (R.stop === v ? 'on' : '') + '" aria-pressed="' + (R.stop === v) + '" data-w="psRule" data-k="stop" data-v="' + v + '">−' + Math.abs(v) + '%</button>').join('') + '</span>'
        + '<span class="lb">목표</span><span class="wseg">' + RULE_TGT.map(v => '<button type="button" class="' + (R.tgt === v ? 'on' : '') + '" aria-pressed="' + (R.tgt === v) + '" data-w="psRule" data-k="tgt" data-v="' + v + '">+' + v + '%</button>').join('') + '</span></div>';
      const f = st.ps.f, shown = (f === 'all' ? rows : rows.filter(r => r.v === f)).slice(0, 60);
      const chips = '<div class="wchips">' + [['all', '전체', rows.length]].concat(Object.keys(VW).map(k => [k, VW[k][0], rows.filter(r => r.v === k).length])).map(c => '<button type="button" class="' + (f === c[0] ? 'on' : '') + '" aria-pressed="' + (f === c[0]) + '" data-w="psF" data-v="' + c[0] + '"' + (c[0] !== 'all' && f !== c[0] ? ' style="color:' + VCOL[c[0]] + '"' : '') + '>' + esc(c[1]) + ' <span class="pvx">' + c[2] + '</span></button>').join('') + '</div>';
      const list = '<div class="wcard" style="padding-top:14px">' + chips + shown.map(r => '<div class="wps-row" data-w="psGo" data-k="' + esc(r.key) + '" role="button" tabindex="0"><span style="min-width:0"><b>' + esc(r.sym) + '</b><small class="pvx">' + esc(md(r.last)) + ' 판</small></span><span class="pl">' + esc(r.plan.t) + '</span><span class="wv ' + r.v + '">' + VW[r.v][0] + '</span><span class="r ' + cls(r.pnl) + '">' + P(r.pnl, 1, true) + '</span></div>').join('')
        + (rows.length > shown.length && f === 'all' ? '<div class="wnote" style="padding-top:10px">최근 60건만 · 거르기로 좁혀 보세요</div>' : '') + '</div>';
      return '<div class="wps"><div class="wgrid">' + ring + bars + ruleH + '</div>' + list + '</div>';
    }
  };
  Object.assign(A, {
    psF: el => { st.ps.f = el.getAttribute('data-v') || 'all'; paint(); },
    psRule: el => { const R = rule(); R[el.getAttribute('data-k')] = num(el.getAttribute('data-v')); LSset('tj_v2_planrule', JSON.stringify(R)); paint(); const x = X(); if (x) x.render(); },
    psGo: el => { const k = el.getAttribute('data-k'), x = X(); if (x && k) closeAndGo(() => x.revealAndHighlight('cycle:' + k)); else close(); }
  });

  function taxYtd(yr) {
    const x = X(), D = x && x.S.D; if (!D) return 0;
    let s = 0;
    const KV = typeof x.KV === 'function' ? x.KV : (u => u);
    if (D.taxFull) arr(D.taxSum).forEach(r => { if (String(r.ym || '').slice(0, 4) === yr) s += KV(num(r.disp) - num(r.acq) - num(r.fee), r.pk2 != null ? r.pk2 : r.pk); });
    else arr(D.tax).forEach(r => { const iso = isoOfKey(String(r.sold || '').slice(0, 10)) || isoOfKey(String(r.sold || '').slice(0, 5)); if (iso.slice(0, 4) !== yr) return;
      const u = num(r.disp) - num(r.acq) - num(r.fee), rk = num(r.rate) > 0 ? num(r.rate) : null;
      s += KV(u, rk ? (r.akr != null ? (num(r.disp) - num(r.fee)) * rk - num(r.akr) : u * rk) : null); });
    return s;
  }
  function feeRate(sym) {
    const x = X(), D = x && x.S.D; if (!D) return { r: 0.001, src: 'def' };
    const spot = r => !r.fut && !r.futFee && !/ 무기한$/.test(String(r.sym || '')) && !/^(기타 비용|스테이킹 보상|유동성)/.test(String(r.ex || ''));
    const rows = arr(D.taxSum).filter(spot), sy = String(sym || '').toUpperCase();
    const agg = rs => rs.reduce((a, r) => [a[0] + num(r.fee), a[1] + num(r.disp)], [0, 0]);
    const mine = agg(rows.filter(r => String(r.sym || '').toUpperCase() === sy)), all = agg(rows);
    if (mine[1] > 0 && mine[0] >= 0) return { r: mine[0] / mine[1], src: 'sym' };
    if (all[1] > 0 && all[0] >= 0) return { r: all[0] / all[1], src: 'all' };
    return { r: 0.001, src: 'def' };
  }
  function sellCalc() {
    const x = X(), D = x && x.S.D; if (!D) return null;
    const g = arr(D.groups).find(z => z.key === st.sell.key); if (!g || num(g.qty) <= 0 || num(g.value) <= 0) return null;
    const f = st.sell.f, price = g.value / g.qty, unk = Math.min(num(g.unkQty), g.qty), kq = Math.max(0, g.qty - unk), sq = f * g.qty;
    const useK = Math.min(sq, kq), unkSell = Math.max(0, sq - useK), uc = kq > 0 ? num(g.cost) / kq : 0;
    const fr = feeRate(g.sym), sell = f * g.value, fee = sell * fr.r, costPart = useK * uc;
    const est = useK * (price - uc) - fee;
    const ytd = taxYtd(todayISO().slice(0, 4));
    const pog = x.planOfGroup(g), cyc = arr(D.merged).find(p => num(p.held) > 0 && x.gMatch(g, p.sym, p.key));
    const pkey = pog ? pog.key : cyc ? cyc.key : '';
    return { g, f, price, est, pct: costPart > 0 ? est / costPart * 100 : null, unkSell, ytd, pkey, plan: pog ? pog.plan : (pkey && D.plans[pkey]) || null, sell, fee, fr };
  }
  VIEWS.sell = {
    head: () => { const c = sellCalc(); return { bare: true, k: '팔기 전 미리보기', t: c ? esc(c.g.sym) + ' 지금 팔면' : '지금 팔면' }; },
    body: () => {
      const c = sellCalc(), x = X();
      if (!c) return '<div class="wempty">이 코인의 보유·시세를 찾지 못했어요</div>';
      const g = c.g, pcv = Math.round(c.f * 100), plan = c.plan;
      const tgt = plan && num(plan.target) > 0 ? plan.target : null, stp = plan && num(plan.stop) > 0 ? plan.stop : null, pv = x.pvOn();
      return '<div class="wsl-h"><span class="av">' + esc(String(g.sym).slice(0, 1)) + '</span><span style="min-width:0"><b>' + esc(g.sym) + ' 지금 팔면</b><small>보유 ' + x.q(num(g.qty)) + ' · ' + locSumH(g) + ' · <span class="pvx">원가 확인 ' + Math.round((1 - Math.min(1, num(g.unkPct))) * 100) + '%</span></small></span></div>'
        + '<div class="wsl-kv"><span>팔 양</span><span class="pvx"><b id="wslPct">' + pcv + '%</b></span></div>'
        + '<div class="wsl-tr" id="wslTr" tabindex="0" role="slider" aria-label="팔 양" aria-valuemin="1" aria-valuemax="100" aria-valuenow="' + pcv + '" aria-valuetext="' + pcv + '%"><span class="tk"></span><span class="fi" style="width:' + pcv + '%"></span><span class="th" style="left:' + pcv + '%"></span></div>'
        + '<div class="wsl-q">' + [[0.25, '25%'], [0.5, '50%'], [1, '전부']].map(o => '<button type="button" class="wbtn' + (Math.abs(c.f - o[0]) < 0.001 ? ' on' : '') + '" aria-pressed="' + (Math.abs(c.f - o[0]) < 0.001) + '" data-w="slQ" data-v="' + o[0] + '">' + o[1] + '</button>').join('') + '</div>'
        + '<div class="wsl-res"><div><div style="font-size:12.5px;color:var(--muted)">예상 실현손익</div><div class="big ' + cls(c.est) + '" id="wslBig">' + M(c.est, { sign: true }) + '</div><div class="wnote" id="wslSub">' + sellSub(c) + '</div></div>'
        + '<div style="height:1px;background:var(--line2)"></div><div class="wsl-kv"><span>올해 누적 양도차익</span><span id="wslYtd">' + sellYtd(c) + '</span></div>'
        + (num(g.unkQty) > 0 ? '<div class="wsl-kv"><span>원가 모르는 수량</span><span style="color:var(--ext)" id="wslUnk">' + x.q(c.unkSell) + ' ' + esc(g.sym) + ' 포함</span></div><div class="wnote">장부처럼 원가 아는 수량부터 판다고 계산했어요 — 원가 모르는 몫(아는 몫을 다 판 뒤)은 손익 0 · 미매칭에서 원가를 정하면 더 정확해져요</div>' : '') + '</div>'
        + (c.pkey ? '<div class="wsl-pl"><label>목표가 (USD)<input inputmode="decimal" id="wslT" data-pv value="' + (pv ? '' : esc(String(st.sell.dT != null ? st.sell.dT : tgt != null ? tgt : ''))) + '" placeholder="' + (pv ? '숨김 중' : esc(sigf(c.price * 1.25))) + '" autocomplete="off"' + (pv ? ' disabled' : '') + '></label><label>손절선 (USD · 선택)<input inputmode="decimal" id="wslS" data-pv value="' + (pv ? '' : esc(String(st.sell.dS != null ? st.sell.dS : stp != null ? stp : ''))) + '" placeholder="' + (pv ? '숨김 중' : esc(sigf(c.price * 0.9))) + '" autocomplete="off"' + (pv ? ' disabled' : '') + '></label></div>'
          + '<div class="wsl-act"><button type="button" class="wbtn" style="flex:1" data-w="close">닫기</button><button type="button" class="wbtn pri" style="flex:1.4" data-w="slSave"' + (pv ? ' disabled title="숨김 중엔 저장할 수 없어요"' : '') + '>목표가로 저장</button></div>' : '<div class="wsl-act"><button type="button" class="wbtn" style="flex:1" data-w="close">닫기</button></div>')
        + (st.sell.saveMsg ? '<div class="wnote" style="margin-top:8px">' + esc(st.sell.saveMsg) + '</div>' : '')
        + '<div class="wnote" style="text-align:center;margin-top:10px">이 봇은 주문을 넣지 않아요 · 계산만 해요</div>';
    },
    after: el => {
      [['#wslT', 'dT'], ['#wslS', 'dS']].forEach(([id9, k9]) => { const i9 = $(id9, el); if (i9 && !i9.disabled) i9.addEventListener('input', () => { st.sell[k9] = i9.value; }); });
      const tr = $('#wslTr', el); if (!tr) return;
      let drag = false;
      const pick = ev => { const r = tr.getBoundingClientRect(); return Math.max(0.01, Math.min(1, (ev.clientX - r.left) / r.width)); };
      const live = f => { const pc = Math.round(f * 100); const fi = $('.fi', tr), th = $('.th', tr); if (fi) fi.style.width = pc + '%'; if (th) th.style.left = pc + '%';
        st.sell.f = Math.round(f * 100) / 100; const c = sellCalc(); if (!c) return; const x = X();
        const set = (id, h) => { const e = $(id); if (e) e.innerHTML = h; };
        set('#wslPct', pc + '%'); set('#wslBig', M(c.est, { sign: true })); set('#wslSub', sellSub(c)); set('#wslYtd', sellYtd(c)); if (x) set('#wslUnk', x.q(c.unkSell) + ' ' + esc(c.g.sym) + ' 포함');
        const b = $('#wslBig'); if (b) b.className = 'big ' + cls(c.est); tr.setAttribute('aria-valuenow', String(pc)); tr.setAttribute('aria-valuetext', pc + '%'); };
      tr.addEventListener('pointerdown', ev => { drag = true; try { tr.setPointerCapture(ev.pointerId); } catch (e) {  } live(pick(ev)); });
      tr.addEventListener('pointermove', ev => { if (drag) live(pick(ev)); });
      tr.addEventListener('pointerup', ev => { if (!drag) return; drag = false; st.sell.f = Math.round(pick(ev) * 100) / 100; paint(); const t = $('#wslTr'); if (t) t.focus({ preventScroll: true }); });
      tr.addEventListener('keydown', ev => { if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') { ev.preventDefault(); st.sell.f = Math.max(0.01, Math.min(1, Math.round((st.sell.f + (ev.key === 'ArrowRight' ? 0.05 : -0.05)) * 100) / 100)); paint(); const t = $('#wslTr'); if (t) t.focus({ preventScroll: true }); } });
    }
  };
  const sellSub = c => (c.pct != null ? '평균 매수가 대비 ' + P(c.pct, 1, true) + ' · ' : '') + '지금 시세 기준 · 받을 돈 ' + M(c.sell, { compact: true })
    + ' · 수수료 ≈ ' + M(-num(c.fee), { compact: true }) + ' (' + (c.fr && c.fr.src === 'sym' ? '이 코인 지난 매도 평균 ' : c.fr && c.fr.src === 'all' ? '지난 매도 평균 ' : '기본 ') + P(num(c.fr && c.fr.r) * 100, 2) + ')';
  const sellYtd = c => M(c.ytd, { compact: true, sign: true }) + ' → <b style="color:var(--warn)">' + M(c.ytd + c.est, { compact: true, sign: true }) + '</b>';
  const sigf = v => { if (!(v > 0)) return ''; const d = v >= 100 ? 2 : v >= 1 ? 4 : 8; return String(+v.toFixed(d)); };
  Object.assign(A, {
    slQ: el => { st.sell.f = num(el.getAttribute('data-v')) || 0.5; paint(); },
    slSave: () => {
      const c = sellCalc(), x = X(); if (!c || !c.pkey || !x || x.pvOn()) return;
      const rd = id => { const v = String(($(id) || {}).value || '').replace(/[,\s$]/g, ''); return v === '' ? null : parseFloat(v); };
      const t = rd('#wslT'), s = rd('#wslS');
      if (!(t != null && isFinite(t) && t > 0)) { st.sell.saveMsg = '목표가를 숫자로 넣어 주세요'; paint(); return; }
      if (s != null && !(isFinite(s) && s > 0 && s < t)) { st.sell.saveMsg = '손절선은 0보다 크고 목표가보다 낮아야 해요'; paint(); return; }
      const body = { key: c.pkey, target: t }; if (s != null) body.stop = s;
      const cur = (x.S.D.plans || {})[c.pkey] || {}, both = s != null || num(cur.stop) > 0;
      x.post('/api/plan', body, both ? '목표가·손절선을 저장했어요 — 닿으면 알려 드려요' : '목표가를 저장했어요 · 손절선까지 채우면 감시해요').then(d => { st.sell.saveMsg = d ? '저장했어요' : ''; if (st.view === 'sell') paint(); });
    }
  });

  function yearData(yr) {
    const x = X(), D = x && x.S.D; if (!D) return null;
    const ys = String(yr), cyc = [];
    arr(D.merged).forEach(p => {
      if (!p || p.kind === 'gas' || p.kind === 'quarantined' || p.kind === 'stable' || p.kind === 'stake' || /^(USDT|USDC|DAI|FDUSD)$/i.test(String(p.sym))) return;
      let r = 0, n = 0, outYr = false; Object.keys(p.realizedByDay || {}).forEach(k => { const iso = isoOfKey(k); if (iso && iso.slice(0, 4) === ys) { r += num(p.realizedByDay[k]); n++; } else if (Math.abs(num(p.realizedByDay[k])) > 0.005) outYr = true; });
      if (!Object.keys(p.realizedByDay || {}).length && num(p.soldQty) > 0 && Math.abs(num(p.realized)) > 0 && String(p._last || '').slice(0, 4) === ys) { r = num(p.realized); n = 1; }
      let act = 0; Object.keys(p.actByDay || {}).forEach(k => { const iso = isoOfKey(k); const v = p.actByDay[k]; if (iso && iso.slice(0, 4) === ys) act += Array.isArray(v) ? v.reduce((a, z) => a + num(z), 0) : num(v); });
      const pct = !outYr && num(p.avg) > 0 && num(p.avgSell) > 0 ? (num(p.avgSell) / num(p.avg) - 1) * 100 : null;
      const o = num(p._ots) * 1000, endIso = p._last ? String(p._last).slice(0, 10) : '', end0 = p._st === '종료' && endIso ? Date.parse(endIso + 'T00:00:00Z') : Date.now();
      const yEnd = Date.parse((+ys + 1) + '-01-01T00:00:00Z') - KST, end = Math.min(end0, yEnd);
      const oYr = o ? new Date(o + KST).getUTCFullYear() : null;
      const held = o && o < yEnd ? Math.max(0, Math.round((end - o) / 864e5)) : 0;
      const live9 = p._st !== '종료';
      cyc.push({ key: p.key, sym: p.sym, r, n, act: act || n, pct, held, open: o ? new Date(o + KST).toISOString().slice(0, 10) : '', end: endIso,
        inYr: (act || n) > 0 || (live9 && num(p.held) > 0 && oYr != null && oYr <= +ys) || (endIso && endIso.slice(0, 4) === ys) });
    });
    const sold = cyc.filter(c => c.n > 0);
    const best = sold.slice().sort((a, b) => b.r - a.r)[0] || null, worst = sold.slice().sort((a, b) => a.r - b.r)[0] || null;
    const most = cyc.slice().sort((a, b) => b.act - a.act)[0] || null, longest = cyc.filter(c => c.held > 0 && c.inYr).sort((a, b) => b.held - a.held)[0] || null;
    const dd = yearDays(D, ys);
    let pos = 0, neg = 0, tot = 0;
    Object.keys(dd.v).forEach(iso => { const v = dd.v[iso]; tot += v; if (Math.abs(v) >= 0.005) { if (v > 0) pos++; else neg++; } });
    let gas = 0; const gbm = D.gasByMonth || {};
    Object.keys(gbm).forEach(ym => { if (ym.slice(0, 4) === ys) arr(gbm[ym]).forEach(g => { if (g && g.kind !== 'exfee') gas += num(g.spot) + num(g.lp); }); });
    return { yr: ys, best, worst, most, longest, pos, neg, tot, gas, nSold: sold.length, fut: dd.fut };
  }
  function yearDays(D, ys) {
    const x = X(), f = (D && D.f) || {}, fu = (D && D.fut) || {}, R0 = x && typeof x.rate === 'function' ? num(x.rate()) : 0;
    const hasK = !!f.realizedKrwByDate, u = {}, k = {};
    let fut = false;
    const add = (mp, mk, isF) => Object.keys(mp || {}).forEach(key => {
      const iso = isoOfKey(key); if (!iso || iso.slice(0, 4) !== ys) return;
      const v = num(mp[key]); u[iso] = num(u[iso]) + v;
      k[iso] = num(k[iso]) + (mk && mk[key] != null ? num(mk[key]) : v * R0);
      if (isF && Math.abs(v) >= 0.005) fut = true;
    });
    add(f.realizedByDate, f.realizedKrwByDate, false);
    add(fu.realizedByDate, fu.realizedKrwByDate, true);
    const out = {};
    Object.keys(u).forEach(iso => { out[iso] = hasK && R0 > 0 && x && typeof x.KV === 'function' ? num(x.KV(u[iso], k[iso])) : u[iso]; });
    return { v: out, fut };
  }
  function yeYears() {
    const x = X(), D = x && x.S.D; const ys = new Set([yeDefault(), todayISO().slice(0, 4)]);
    if (D) [(D.f || {}).realizedByDate, (D.fut || {}).realizedByDate].forEach(mp => Object.keys(mp || {}).forEach(key => { const iso = isoOfKey(key); if (iso) ys.add(iso.slice(0, 4)); }));
    return Array.from(ys).filter(y => /^\d{4}$/.test(y)).sort().reverse();
  }
  const YE_N = 5;
  VIEWS.ye = {
    head: () => { const yr = yeYear(), ys = yeYears();
      return { slim: true, k: yearLabel(yr) + ' · ' + (st.ye.i + 1) + ' / ' + YE_N, t: esc(yr) + '년 결산 카드',
        act: (ys.length > 1 ? '<span class="wseg" role="group" aria-label="연도">' + ys.map(y => '<button type="button" class="pvx' + (y === yr ? ' on' : '') + '" aria-pressed="' + (y === yr) + '" data-w="yeYear" data-v="' + esc(y) + '">' + esc(y) + '년</button>').join('') + '</span>' : '')
          + '<button type="button" class="wpill" data-w="yeRatio" aria-pressed="' + st.ye.ratio + '">' + (st.ye.ratio ? '금액도 보기' : '비율만 보기') + '</button>' }; },
    body: () => {
      const yd = yearData(yeYear());
      if (!yd || (!yd.nSold && !yd.tot)) return '<div class="wempty">' + esc(yeYear() === todayISO().slice(0, 4) ? '올해' : yeYear() + '년') + ' 판 기록이 아직 없어요</div>';
      const i = st.ye.i, prog = '<div class="wye-prog" aria-hidden="true">' + Array.from({ length: YE_N }, (_, k) => '<span class="' + (k <= i ? 'on' : '') + '"></span>').join('') + '</div>';
      return '<div class="wye">' + prog + '<div class="wye-card" id="wyeCard">' + yeCard(yd, i)
        + '<button type="button" class="wye-tap l" data-w="yePrev" aria-label="이전 카드"' + (i === 0 ? ' disabled' : '') + '></button><button type="button" class="wye-tap r" data-w="yeNext" aria-label="다음 카드"></button></div>'
        + '<div class="wye-nav"><button type="button" class="wbtn" data-w="yeSave">' + ICO.dl + '이미지로 저장</button><button type="button" class="wbtn pri" data-w="yeNext">' + (i >= YE_N - 1 ? '처음으로' : '다음 카드') + '</button></div>'
        + '<div class="wnote" style="text-align:center">' + (st.ye.ratio ? '비율만 보기 — 금액은 카드·이미지 어디에도 없어요(공유용)' : '카드 왼쪽·오른쪽을 눌러 넘겨요 · 금액은 화면 설정(원화·달러·가리기)을 따라요') + '</div></div>';
    },
    key: ev => { if (ev.key === 'ArrowRight') { ev.preventDefault(); A.yeNext(); } else if (ev.key === 'ArrowLeft') { ev.preventDefault(); A.yePrev(); } }
  };
  function yeAmt(usd, o) { return st.ye.ratio ? '' : M(usd, o); }
  function yeModel(yd, i) {
    const days = yd.pos + yd.neg, wr = days ? yd.pos / days * 100 : null, R = st.ye.ratio, PV = v => '<span class="pvx">' + v + '</span>';
    const gasTxt = R ? (yd.tot ? P(Math.abs(yd.gas / (Math.abs(yd.tot) || 1)) * 100, 1) : '—') : M(yd.gas, { compact: true });
    const YW = yd.yr === todayISO().slice(0, 4) ? '올해' : esc(yd.yr) + '년';
    if (i === 0) return { c: 'var(--accent)', ey: esc(yd.yr) + '년 결산', t1: YW === '올해' ? '올해의 나' : YW + '의 나', t2: R ? (wr != null ? P(wr, 0) : '—') : M(yd.tot, { sign: true, compact: true }), t2c: R ? 'var(--text)' : yd.tot >= 0 ? 'var(--up)' : 'var(--down)',
      tx: [R ? '수익 난 날의 비율이에요' + (yd.fut ? '(선물 포함).' : '.') : YW + ' 판 것으로 생긴 실현손익이에요' + (yd.fut ? '(선물 정산 포함).' : '.'), PV('매도한 코인 ' + yd.nSold + '종 · 매매한 날 ' + days + '일')],
      g4: [['가장 많이 거래', yd.most ? esc(yd.most.sym) + ' · ' + PV(yd.most.act + '번') : '—'], [R ? '가스 ÷ 실현' : '낸 가스비', gasTxt],
        ['가장 오래 버틴', yd.longest ? esc(yd.longest.sym) + ' · ' + PV(yd.longest.held + '일') : '—'], ['수익 난 날', wr != null ? PV(wr.toFixed(0) + '%') : '—']] };
    if (i === 1) { const b = yd.best; if (!b) return { c: 'var(--muted)', ey: YW + ' 최고의 거래', t1: '아직 없음', tx: [YW + ' 판 기록이 쌓이면 보여요.'], g4: [] };
      return { c: 'var(--up)', ey: YW + ' 최고의 거래', t1: esc(b.sym), t2: b.pct != null ? P(b.pct, 0, true) : (R ? '—' : M(b.r, { sign: true, compact: true })), t2c: 'var(--up)',
        tx: [(b.open ? PV(esc(md(b.open))) + '에 사서 ' : '') + (b.end ? PV(esc(md(b.end))) + '에 팔았어요.' : '아직 들고 있어요.')].concat(R ? [] : ['이 거래로 ' + yeAmt(b.r, { sign: true, compact: true }) + '.']),
        g4: [['버틴 기간', PV(b.held + '일')], ['매매한 날', PV(b.n + '일')]] }; }
    if (i === 2) { const w = yd.worst; if (!w || w.r >= 0) return { c: 'var(--ok)', ey: YW + ' 가장 아팠던 거래', t1: '없음', tx: [YW + ' 판 거래가 모두 이익이었어요.'], g4: [] };
      return { c: 'var(--down)', ey: YW + ' 가장 아팠던 거래', t1: esc(w.sym), t2: w.pct != null ? P(w.pct, 0, true) : (R ? '—' : M(w.r, { sign: true, compact: true })), t2c: 'var(--down)',
        tx: [(R ? '' : yeAmt(w.r, { sign: true, compact: true }) + ' — ') + '다음엔 손절선을 먼저 걸어 두기.'], g4: [['버틴 기간', PV(w.held + '일')], ['매매한 날', PV(w.n + '일')]] }; }
    if (i === 3) { const mo = yd.most, lg = yd.longest;
      return { c: 'var(--c2)', ey: '가장 많이 · 가장 오래', t1: esc(mo ? mo.sym : '—'), t2: mo ? PV(mo.act + '번') : '', t2c: 'var(--c2)', tx: [YW + ' 가장 자주 거래한 코인이에요.'],
        g4: [['가장 오래 버틴', esc(lg ? lg.sym : '—')], ['버틴 기간', lg ? PV(lg.held + '일') : '—']] }; }
    return { c: 'var(--c3)', ey: '숨은 비용', t1: '가스 · 수수료', t2: gasTxt, t2c: 'var(--c3)', tx: [R ? '실현손익 대비 가스 비율이에요.' : YW + ' 체인에 낸 가스예요.', '거래 수수료는 양도차익 명세에 따로 있어요.'], g4: [] };
  }
  function yeCard(yd, i) {
    const m = yeModel(yd, i);
    return '<span class="orb" style="color:' + m.c + '"></span><span class="ey" style="color:' + m.c + '">' + m.ey + '</span><div class="t1">' + m.t1 + '</div>'
      + (m.t2 ? '<div class="t2" style="color:' + m.t2c + '">' + m.t2 + '</div>' : '') + '<div class="tx">' + m.tx.filter(Boolean).join('<br>') + '</div><span class="sp"></span>'
      + (m.g4.length ? '<div class="g4">' + m.g4.map(g => '<div><div class="l">' + g[0] + '</div><b>' + g[1] + '</b></div>').join('') + '</div>' : '');
  }
  function yeSvg(yd, i) {
    const m = yeModel(yd, i), cs = getComputedStyle(document.documentElement);
    const col = v => { const k = String(v).replace(/^var\((--[\w-]+)\)$/, '$1'); return (k.startsWith('--') ? cs.getPropertyValue(k).trim() : k) || '#888'; };
    const txt = h => { const d = document.createElement('div'); d.innerHTML = String(h || ''); return (d.textContent || '').replace(/[\uE000-\uE0FF]/g, '').replace(/\s+/g, ' ').trim(); };
    const xml = s => String(s).replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]);
    const SANS = "'Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif", MONO = "'SF Mono',Menlo,Consolas,monospace";
    const W = 1080, H = 1350, X0 = 88, c = col(m.c);
    const wrap = (s, n) => { const out = []; let cur = ''; s.split(' ').forEach(w => { if ((cur + ' ' + w).trim().length > n && cur) { out.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); }); if (cur) out.push(cur); return out; };
    let svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">'
      + '<rect width="' + W + '" height="' + H + '" rx="72" fill="' + xml(col('--surface')) + '"/>'
      + '<g fill="none" stroke="' + xml(c) + '" stroke-opacity=".5" stroke-dasharray="3 12" stroke-width="2"><circle cx="900" cy="170" r="330"/><circle cx="900" cy="170" r="220"/></g>'
      + '<text x="' + X0 + '" y="170" font-family="' + SANS + '" font-size="34" font-weight="700" letter-spacing="1.5" fill="' + xml(c) + '">' + xml(txt(m.ey)) + '</text>';
    const t1 = txt(m.t1), t1s = t1.length > 9 ? 92 : 118;
    svg += '<text x="' + X0 + '" y="' + (170 + 40 + t1s) + '" font-family="' + SANS + '" font-size="' + t1s + '" font-weight="800" fill="' + xml(col('--text')) + '">' + xml(t1) + '</text>';
    let y = 170 + 40 + t1s;
    if (m.t2) { const t2 = txt(m.t2), t2s = t2.length > 9 ? 108 : 150; y += 40 + t2s; svg += '<text x="' + (X0 - 6) + '" y="' + y + '" font-family="' + MONO + '" font-size="' + t2s + '" font-weight="700" letter-spacing="-4" fill="' + xml(col(m.t2c)) + '">' + xml(t2) + '</text>'; }
    y += 96;
    m.tx.filter(Boolean).forEach(l => wrap(txt(l), 26).forEach(line => { svg += '<text x="' + X0 + '" y="' + y + '" font-family="' + SANS + '" font-size="40" fill="' + xml(col('--text2')) + '">' + xml(line) + '</text>'; y += 60; }));
    if (m.g4.length) {
      const rows = Math.ceil(m.g4.length / 2), cw = (W - X0 * 2 - 24) / 2, ch = 150, top = H - 170 - rows * ch - (rows - 1) * 24;
      m.g4.forEach((g, k) => { const gx = X0 + (k % 2) * (cw + 24), gy = top + Math.floor(k / 2) * (ch + 24);
        svg += '<rect x="' + gx + '" y="' + gy + '" width="' + cw + '" height="' + ch + '" rx="36" fill="' + xml(col('--surface2')) + '"/>'
          + '<text x="' + (gx + 36) + '" y="' + (gy + 58) + '" font-family="' + SANS + '" font-size="28" fill="' + xml(col('--muted')) + '">' + xml(txt(g[0])) + '</text>'
          + '<text x="' + (gx + 36) + '" y="' + (gy + 112) + '" font-family="' + SANS + '" font-size="42" font-weight="700" fill="' + xml(col('--text')) + '">' + xml(txt(g[1]).slice(0, 18)) + '</text>'; });
    }
    svg += '<text x="' + X0 + '" y="' + (H - 72) + '" font-family="' + SANS + '" font-size="28" fill="' + xml(col('--faint')) + '">' + xml(yd.yr + '년 결산 · ' + (i + 1) + ' / ' + YE_N + ' · tj-bot 온체인 매매일지' + (X() && X().S.rand ? ' · 금액 = 랜덤값(예시)' : '')) + '</text></svg>';
    return svg;
  }
  function yeSave() {
    const yd = yearData(yeYear()); if (!yd) return;
    const W = 1080, H = 1350, svg = yeSvg(yd, st.ye.i), x = X();
    const img = new Image();
    img.onload = () => { const cv = document.createElement('canvas'); cv.width = W; cv.height = H; const g = cv.getContext('2d'); g.drawImage(img, 0, 0);
      cv.toBlob(b => { if (!b) { if (x) x.toast('이미지를 만들지 못했어요', true); return; } const u = URL.createObjectURL(b), a = document.createElement('a'); a.href = u; a.download = 'tj-' + yd.yr + '-card' + (st.ye.i + 1) + (st.ye.ratio ? '-ratio' : '') + '.png'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 4000); if (x) x.toast('카드 이미지를 저장했어요'); }, 'image/png'); };
    img.onerror = () => { if (x) x.toast('이미지를 만들지 못했어요', true); };
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }
  Object.assign(A, {
    yeNext: () => { st.ye.i = st.ye.i < YE_N - 1 ? st.ye.i + 1 : 0; paint(); },
    yePrev: () => { if (st.ye.i > 0) { st.ye.i--; paint(); } },
    yeRatio: () => { st.ye.ratio = !st.ye.ratio; paint(); },
    yeYear: el => { const y = String(el.getAttribute('data-v') || ''); if (/^\d{4}$/.test(y)) { st.ye.year = y; st.ye.i = 0; paint(); } },
    yeSave: () => yeSave()
  });

  const askCache = new Map();
  function askParse(q) {
    let s = String(q || '').trim().slice(0, 200);
    const x0 = X(); if (x0 && x0.pvOn()) s = typeof x0.pvStripAmt === 'function' ? x0.pvStripAmt(s) : '';
    if (!s) return Promise.resolve(null);
    if (askCache.has(s)) return Promise.resolve(askCache.get(s));
    return fetch('/api/search/ask?q=' + encodeURIComponent(s), { cache: 'no-store', credentials: 'same-origin' }).then(r => (r.ok ? r.json() : null)).then(j => {
      const v = j && j.ok ? { ok: true, filters: j.filters || {}, text: String(j.text || ''), via: j.via || 'rules', echo: String(j.echo || ''), query: String(j.query || '') } : null;
      if (v) { if (askCache.size > 100) askCache.clear(); askCache.set(s, v); }
      return v;
    }).catch(() => null);
  }

  window.TJWow = { slot, open, close, askParse, lock, onPv, _tmSet: tmSet, _st: st, _views: VIEWS, _taxYtd: taxYtd, _planRows: planRows, _yearData: yearData, _sellCalc: sellCalc, _flLayout: flLayout, _flMap: flMap, _flSelHTML: flSelHTML, _yeModel: yeModel };
  const hook = () => { if (window.TJ) { window.TJ.askParse = askParse; window.TJ.wow = window.TJWow; } };
  hook();
  const x0 = X(), had0 = !!(x0 && x0.S && x0.S.D);
  const kick = () => { const x = X(); if (x && x.S.D && !x.lockedNow()) { try { x.render(); } catch (e) {  } } };
  if (had0) setTimeout(kick, 0);
})();

(function () {
  'use strict';
  var H = document.documentElement;
  try { var t = localStorage.getItem('tj_v2_theme'); if (t === 'light' || t === 'dark') H.setAttribute('data-theme', t); } catch (e) {  }
  try { if (H.getAttribute('data-theme') === 'light') { var m = document.querySelector('meta[name=theme-color]'); if (m) m.setAttribute('content', '#F3F4F7'); } } catch (e) {  }

  function nextUrl() {
    var n = '';
    try { n = new URLSearchParams(location.search).get('next') || ''; } catch (e) { n = ''; }
    if (typeof n !== 'string' || n.length > 512 || !/^\/(?![\/\\])/.test(n) || /[\s\\\u0000-\u001f\u007f]/.test(n) || /^\/(login([?#\/]|$)|api\/)/.test(n)) return '/';
    return n;
  }
  function $(id) { return document.getElementById(id); }
  function show(el, on) { if (el) el.classList.toggle('hidden', !on); }
  function msg(text, kind) { var m = $('msg'); if (!m) return; m.textContent = text || ''; m.className = 'msg ' + (kind || 'e'); show(m, !!text); }
  function mins(s) { s = Math.max(0, Math.round(+s || 0)); var m = Math.floor(s / 60), r = s % 60; return m >= 60 ? Math.floor(m / 60) + '시간 ' + (m % 60) + '분' : m ? m + '분 ' + (r < 10 ? '0' : '') + r + '초' : r + '초'; }
  function port() { return location.port || (location.protocol === 'https:' ? '443' : '80'); }

  function plainHttp() {
    if (location.protocol !== 'http:') return false;
    var h = String(location.hostname || '').toLowerCase().replace(/^\[|\]$/g, '');
    if (h === 'localhost' || h === '::1' || /^127\./.test(h) || /\.ts\.net$/.test(h)) return false;
    var m = /^100\.(\d{1,3})\.\d{1,3}\.\d{1,3}$/.exec(h);
    if (m && +m[1] >= 64 && +m[1] <= 127) return false;
    return true;
  }
  function plainWarn() {
    var w = $('plain');
    if (!w || !plainHttp()) return;
    w.textContent = '주의: 암호화되지 않은 주소(http)예요 — 비밀번호와 로그인 쿠키가 이 네트워크에 그대로 오가요. 테일넷(테일스케일)이나 HTTPS 주소로 여는 걸 권해요.';
    show(w, true);
  }
  var WIPE_LS = ['tj_v2_ver', 'tj_v2_full', 'tj_logo_fail', 'tj_v2_todo_hist', 'tj_v2_srch_recent', 'tj_v2_srch_saved'], wiped = false;
  function wipeCache() {
    if (wiped) return;
    wiped = true;
    WIPE_LS.forEach(function (k) { try { localStorage.removeItem(k); } catch (e) {  } });
    try {
      var ks = [];
      for (var i = 0; i < sessionStorage.length; i++) { var k = sessionStorage.key(i); if (k && k.indexOf('tj_') === 0) ks.push(k); }
      ks.forEach(function (k) { try { sessionStorage.removeItem(k); } catch (e) {  } });
    } catch (e) {  }
    try { indexedDB.deleteDatabase('tj_v2'); } catch (e) {  }
  }

  var lockT = null, lockUntil = 0, busy = false, ST = null;
  function lockFor(sec) {
    lockUntil = Date.now() + Math.max(1, +sec || 1) * 1000;
    if (lockT) clearInterval(lockT);
    var tick = function () {
      var left = Math.ceil((lockUntil - Date.now()) / 1000);
      if (left <= 0) { clearInterval(lockT); lockT = null; msg(''); setDisabled(false); var p = $('pw'); if (p) p.focus(); return; }
      msg('로그인 시도가 너무 많아요 — ' + mins(left) + ' 뒤에 다시 할 수 있어요', 'w');
      setDisabled(true);
    };
    tick(); lockT = setInterval(tick, 1000);
  }
  function setDisabled(on) {
    ['pw', 'bLogin', 'np', 'np2', 'bSetup'].forEach(function (id) { var el = $(id); if (el) el.disabled = !!on; });
  }

  function post(path, body) {
    return fetch(path, { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return null; }).then(function (d) { return { st: r.status, d: d || {} }; }); });
  }

  function modeLogin() {
    wipeCache(); plainWarn();
    $('ttl').textContent = '로그인';
    $('desc').textContent = '비밀번호를 넣으면 이 기기에서 ' + ((ST && ST.sessionDays) || 30) + '일 동안 로그인이 유지돼요 (' + ((ST && ST.idleDays) || 7) + '일 동안 쓰지 않으면 다시 물어요).';
    show($('fLogin'), true); show($('fSetup'), false); show($('step'), false);
    $('foot').textContent = '비밀번호를 잊었으면 tj-bot 이 도는 컴퓨터에서 python3 tools/reset_password.py 를 실행하세요.';
    if (ST && ST.retryAfter) lockFor(ST.retryAfter);
    else { var p = $('pw'); if (p) p.focus(); }
  }
  function modeSetup() {
    wipeCache();
    $('ttl').textContent = '비밀번호 만들기';
    $('desc').textContent = '이 대시보드를 여는 비밀번호예요. 다른 기기(같은 와이파이·테일넷·휴대폰)에서 열 때도 이 비밀번호를 물어요. 계정은 하나라 아이디는 없어요.';
    show($('step'), true); show($('fSetup'), true); show($('fLogin'), false);
    $('foot').textContent = '나중에 바꾸기 = 설정 › 로그인 · 잊었을 때 = 이 컴퓨터에서 python3 tools/reset_password.py';
    rules(); var n = $('np'); if (n) n.focus();
  }
  function modeSetupElsewhere() {
    wipeCache();
    $('ttl').textContent = '아직 비밀번호가 없어요';
    $('desc').textContent = '보안을 위해 첫 비밀번호는 tj-bot 이 도는 그 컴퓨터에서만 만들 수 있어요.';
    show($('fLogin'), false); show($('fSetup'), false); show($('step'), true);
    msg('그 컴퓨터의 브라우저에서 http://127.0.0.1:' + port() + '/login 을 여세요. 브라우저를 쓸 수 없는 서버라면 거기서 python3 tools/reset_password.py --set 으로 만들 수 있어요.', 'i');
    $('foot').textContent = '';
  }
  function modeDamaged() {
    wipeCache();
    $('ttl').textContent = '로그인할 수 없어요';
    $('desc').textContent = '';
    show($('fLogin'), false); show($('fSetup'), false); show($('step'), false);
    msg('비밀번호 파일(state/auth.json)이 손상됐어요. tj-bot 이 도는 컴퓨터에서 python3 tools/reset_password.py 로 지운 뒤 새로 만드세요.', 'e');
  }

  function rules() {
    var a = ($('np') || {}).value || '', b = ($('np2') || {}).value || '', min = (ST && ST.pwMin) || 10;
    var same = a.length > 0 && !(new Set(a.split('')).size === 1) && !(/^\d+$/.test(a) && a.length < 12);
    var st = { len: a.length >= min, same: same, match: a.length > 0 && a === b };
    Array.prototype.forEach.call(document.querySelectorAll('#rules li'), function (li) { li.classList.toggle('ok', !!st[li.getAttribute('data-r')]); });
    return st;
  }

  function onLogin(ev) {
    ev.preventDefault();
    if (busy || lockT) return;
    var pw = ($('pw') || {}).value || '';
    if (!pw) { msg('비밀번호를 넣어 주세요'); return; }
    busy = true; setDisabled(true); msg('');
    post('/api/login', { password: pw }).then(function (x) {
      busy = false;
      if (x.st === 200 && x.d.ok) { $('pw').value = ''; location.replace(nextUrl()); return; }
      setDisabled(false);
      if (x.st === 429) { lockFor(x.d.retryAfter || 60); return; }
      if (x.st === 409 && x.d.setup) { boot(); return; }
      var t = String(x.d.error || ('로그인하지 못했어요 (HTTP ' + x.st + ')'));
      if (x.st === 401 && typeof x.d.left === 'number' && x.d.left > 0 && x.d.left <= 3) t += ' · ' + x.d.left + '번 더 틀리면 잠시 잠겨요';
      msg(t);
      var p = $('pw'); if (p) { p.select(); p.focus(); }
    }, function () { busy = false; setDisabled(false); msg('서버에 연결하지 못했어요 — tj-web 이 켜져 있는지 확인하세요'); });
  }
  function onSetup(ev) {
    ev.preventDefault();
    if (busy) return;
    var st = rules(), a = $('np').value;
    if (!st.len) { msg(((ST && ST.pwMin) || 10) + '자 이상으로 만들어 주세요'); return; }
    if (!st.same) { msg('같은 글자만 반복하거나 짧은 숫자만으로는 만들 수 없어요'); return; }
    if (!st.match) { msg('두 칸의 비밀번호가 달라요'); return; }
    busy = true; setDisabled(true); msg('');
    post('/api/auth/setup', { password: a }).then(function (x) {
      busy = false;
      if (x.st === 200 && x.d.ok) { $('np').value = ''; $('np2').value = ''; location.replace(nextUrl()); return; }
      setDisabled(false);
      if (x.st === 409) { boot(); return; }
      msg(String(x.d.error || ('만들지 못했어요 (HTTP ' + x.st + ')')));
    }, function () { busy = false; setDisabled(false); msg('서버에 연결하지 못했어요 — tj-web 이 켜져 있는지 확인하세요'); });
  }

  function boot() {
    msg('');
    fetch('/api/auth/status', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)); })
      .then(function (d) {
        ST = d || {};
        if (!ST.enabled) { location.replace('/'); return; }
        if (ST.authed) { location.replace(nextUrl()); return; }
        if (ST.damaged) { modeDamaged(); return; }
        if (!ST.passwordSet) { if (ST.canSetup) modeSetup(); else modeSetupElsewhere(); return; }
        modeLogin();
      })
      .catch(function () { $('desc').textContent = ''; msg('서버 상태를 확인하지 못했어요 — 잠시 뒤 새로 고쳐 주세요'); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('fLogin').addEventListener('submit', onLogin);
    $('fSetup').addEventListener('submit', onSetup);
    ['np', 'np2'].forEach(function (id) { $(id).addEventListener('input', rules); });
    Array.prototype.forEach.call(document.querySelectorAll('[data-eye]'), function (b) {
      b.addEventListener('click', function () {
        var f = $(b.getAttribute('data-eye')); if (!f) return;
        var on = f.type === 'password'; f.type = on ? 'text' : 'password';
        b.textContent = on ? '숨기기' : '보기'; b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    });
    boot();
  });
})();

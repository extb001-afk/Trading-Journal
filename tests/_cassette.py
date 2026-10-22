from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse

import _harness as T
from _cassette_clock import CLOCK, FROZEN, MONO_BASE, MONO_OFF, NOW, Fn, freeze  # noqa: F401
from _cassette_codec import PID_FILES, SNAP_SKIP, canon, dec, diff, enc, read_any, scrub, snap_tree  # noqa: F401
from _cassette_wire import CassetteMiss, Reply, Request, StopCycle, Transport, as_reply, parse_request, planned, resp_raw, resp_store  # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
CAS_DIR = os.path.join(HERE, "cassettes")
REPO_LAYOUT = os.path.realpath(HERE) == os.path.realpath(os.path.join(T.ROOT, "public", "tests"))
RECORD = {x.strip() for x in os.environ.get("TJ_TEST_RECORD", "").split(",") if x.strip()}
MAX_REQUESTS = 5000

_AUTH_HDR = re.compile(r"authorization|key|sign|secret|token|passphrase|nonce|timestamp", re.I)
_VOL_PARAMS = {"timestamp", "ts", "nonce", "signature", "sign", "sig"}
_TIMEISH = re.compile(r"time|nonce|(^|[-_])ts$", re.I)
_PYUA = re.compile(r"Python-urllib/\d+\.\d+")
_SKIP_HDR = {"content-length", "connection"}


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _origin_of(sp) -> str:
    dflt = 443 if sp.scheme == "https" else 80
    try:
        port = sp.port or dflt
    except ValueError:
        port = dflt
    host = (sp.hostname or "").lower()
    host = f"[{host}]" if ":" in host else host
    return f"{sp.scheme}://" + (host if port == dflt else f"{host}:{port}")


class _Norm:
    __slots__ = ("key", "req", "hdr", "auth")


class Cassette:

    def __init__(self, name: str, secrets: dict = None, responder=None, tick: float = None, dirpath: str = None, record: bool = None,
                 dns: dict = None, conn_events: dict = None, preserve: bool = None):
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError("카세트 이름 = 소문자·숫자·밑줄")
        self.name = name
        self.dir = dirpath or CAS_DIR
        self.path = os.path.join(self.dir, name + ".json")
        self.gpath = os.path.join(self.dir, name + ".golden.json")
        self.record = (name in RECORD) if record is None else bool(record)
        self.secrets = dict(secrets or {})
        self.responder = responder
        self.tick = tick
        self.entries, self.queues = [], {}
        self.misses, self.diffs = [], []
        self.served = 0
        self.n_recorded = 0
        self.missing = False
        self.failed = None
        self.nonce_reuse = 0
        self._nonces = set()
        self._socks = []
        self._dns = {}
        self._golden_new = None
        self._t0 = CLOCK.now
        self._lock = threading.RLock()
        self._want = {"addr_mode": None if preserve is None else ("preserve" if preserve else "plain"), "dns": dns, "conn_events": conn_events}
        self.preserve, self.dns = bool(preserve), json.loads(json.dumps(dns or {}))
        self.conn_events = json.loads(json.dumps(conn_events or {}))
        self.conn_log, self.lookups = [], {"name": {}, "numeric": {}}
        self._conn_at, self._rdns, self._file_net = {}, {}, None
        if self.record:
            if not callable(responder):
                raise ValueError("녹화에는 responder 가 필요")
        elif not (os.path.isfile(self.path) and os.path.isfile(self.gpath)):
            self.missing = True
        else:
            self._load()

    def _load(self):
        doc = json.load(open(self.path, encoding="utf-8"))
        if doc.get("version") != 1:
            raise ValueError(f"카세트 판 모름: {doc.get('version')}")
        if self.tick is None:
            self.tick = float((doc.get("clock") or {}).get("tick") or 0.0)
        self._file_net = {"addr_mode": doc.get("addr_mode") or "plain", "dns": doc.get("dns") or {}, "conn_events": doc.get("conn_events") or {},
                          "conn_log": doc.get("conn_log") or [], "used": any(k in doc for k in ("addr_mode", "dns", "conn_events", "conn_log"))}
        self.preserve = self._file_net["addr_mode"] == "preserve"
        self.dns, self.conn_events = self._file_net["dns"], self._file_net["conn_events"]
        for e in doc["interactions"]:
            e = dict(e, resp=dec(e["resp"]))
            self.queues.setdefault(e["key"], []).append(e)
            self.n_recorded += 1

    def ready(self, T_) -> bool:
        if not self.missing:
            return True
        rel = os.path.relpath(self.path, HERE)
        if REPO_LAYOUT:
            T_.chk(False, f"[{self.name}] 카세트·골든 파일 있음({rel})", "TJ_TEST_RECORD=%s 로 녹화" % self.name)
        else:
            print(f"카세트 파일 없음({rel}) — 공개 패키지 배치라 건너뜀", flush=True)
        return False

    def _sec(self, s: str) -> str:
        for nm, v in sorted(self.secrets.items(), key=lambda kv: -len(kv[1])):
            if v:
                s = s.replace(v, f"<secret:{nm}>")
                q = urllib.parse.quote(v, safe="")
                if q != v:
                    s = s.replace(q, f"<secret:{nm}>")
        return s

    def _sec_out(self, s: str) -> str:
        spans = []
        for nm, v in self.secrets.items():
            if not v:
                continue
            for f in {v, urllib.parse.quote(v, safe=""), repr(v)[1:-1], json.dumps(v, ensure_ascii=False)[1:-1], json.dumps(v)[1:-1]}:
                i = s.find(f)
                while f and i >= 0:
                    spans.append((i, i + len(f), nm))
                    i = s.find(f, i + 1)
        if not spans:
            return s
        merged = []
        for a, b, nm in sorted(spans):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
                merged[-1][2].add(nm)
            else:
                merged.append([a, b, {nm}])
        out, at = [], 0
        for a, b, nms in merged:
            out += [s[at:a], "<secret:%s>" % ",".join(sorted(nms))]
            at = b
        s = "".join(out) + s[at:]
        return s

    def _auth_val(self, name: str, v: str):
        v2 = self._sec(str(v))
        m = re.fullmatch(r"(?i)bearer\s+([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]*)", v2.strip())
        if m:
            j = self._jwt(*m.groups())
            if j is not None:
                return j
        if re.fullmatch(r"(<secret:[a-z0-9_]+>)+", v2) or _TIMEISH.search(name):
            return v2
        return "h:" + hashlib.sha256(v2.encode("utf-8")).hexdigest()[:16]

    def _jwt(self, h64: str, p64: str, s64: str):
        try:
            hdr, pl = json.loads(_b64u(h64)), json.loads(_b64u(p64))
            sig = _b64u(s64)
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(hdr, dict) or not isinstance(pl, dict):
            return None
        fn = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}.get(str(hdr.get("alg")))
        by = None
        if fn is not None:
            for nm, v in sorted(self.secrets.items()):
                if v and hmac.compare_digest(sig, hmac.new(v.encode(), f"{h64}.{p64}".encode(), fn).digest()):
                    by = nm
                    break
        elif str(hdr.get("alg")) == "ES256":
            by = self._es256_by(f"{h64}.{p64}".encode(), sig)
            hdr = {k: (self._sec(x) if isinstance(x, str) else x) for k, x in hdr.items()}
            if "nonce" in hdr:
                hdr["nonce"] = self._nonce_mark(hdr["nonce"])
        claims = {k: (self._sec(x) if isinstance(x, str) else x) for k, x in sorted(pl.items())}
        if "nonce" in claims:
            claims["nonce"] = self._nonce_mark(pl["nonce"])
        return {"jwt": {"hdr": hdr, "claims": claims, "signed_by": by}}

    def _nonce_mark(self, nv) -> str:
        if not isinstance(nv, str) or not nv:
            return "<nonce 없음>"
        if nv in self._nonces:
            self.nonce_reuse += 1
            return "<nonce 재사용>"
        self._nonces.add(nv)
        return "<nonce>"

    def _es256_by(self, si: bytes, sig: bytes):
        import ex_sign
        for nm, v in sorted(self.secrets.items()):
            try:
                pub = ex_sign.ec_p256_pub(ex_sign.ec_p256_scalar(v))
            except ValueError:
                continue
            if ex_sign.es256_verify(si, sig, pub):
                return nm
        return None

    def _pairs(self, pairs, auth: dict, where: str) -> list:
        out = []
        for k, v in pairs:
            if k.lower() in _VOL_PARAMS:
                auth[where + k] = self._auth_val(k, v)
                v = f"<{k}>"
            out.append([k, v])
        return out

    def _auth_put(self, auth: dict, where: str, k: str, v):
        auth[where + k] = self._auth_val(k, json.dumps(v) if not isinstance(v, str) else v)
        return f"<{k}>"

    def _norm_body(self, body: bytes, ctype: str, auth: dict, req: dict):
        txt = None
        try:
            txt = self._sec(body.decode("utf-8"))
        except UnicodeDecodeError:
            pass
        obj = None
        if txt is not None and ("json" in ctype or txt.lstrip()[:1] in ("{", "[")):
            try:
                obj = json.loads(txt)
            except ValueError:
                obj = None
        if obj is not None:
            if isinstance(obj, dict):
                obj = {k: (self._auth_put(auth, "body.", k, v) if k.lower() in _VOL_PARAMS else v) for k, v in obj.items()}
            req["json"] = obj
            return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if txt is not None and "x-www-form-urlencoded" in ctype:
            req["form"] = self._pairs(urllib.parse.parse_qsl(txt, keep_blank_values=True), auth, "body.")
            return json.dumps(req["form"], ensure_ascii=False)
        if txt is not None:
            req["text"] = txt
            return txt
        req["bin"] = "sha256:" + hashlib.sha256(body).hexdigest()[:16]
        return req["bin"]

    def _norm(self, method: str, url: str, hdrs: list, body: bytes) -> _Norm:
        auth, hdr = {}, {}
        sp = urllib.parse.urlsplit(self._sec(url))
        q = self._pairs(urllib.parse.parse_qsl(sp.query, keep_blank_values=True), auth, "?")
        qs = urllib.parse.urlencode([tuple(p) for p in q], quote_via=urllib.parse.quote, safe="<>:")
        nurl = urllib.parse.urlunsplit((sp.scheme, sp.netloc, sp.path, qs, ""))
        ctype = ""
        for k, v in hdrs:
            lk = k.lower()
            if lk == "content-type":
                ctype = v.lower()
            if lk in _SKIP_HDR:
                continue
            if _AUTH_HDR.search(lk):
                auth[lk] = self._auth_val(lk, v)
            else:
                hdr[lk] = _PYUA.sub("Python-urllib/<판>", self._sec(v)) if lk == "user-agent" else self._sec(v)
        req = {"method": method, "url": nurl}
        bkey = self._norm_body(body, ctype, auth, req) if body else None
        n = _Norm()
        n.key = enc(f"{method} {nurl}" + (" #" + hashlib.sha256(bkey.encode("utf-8")).hexdigest()[:16] if bkey is not None else ""),
                    lossy=True, where="요청 키")
        n.req, n.hdr, n.auth = enc(req, True, "요청"), enc(hdr, True, "요청 헤더"), enc(auth, True, "인증 칸")
        return n

    def _serve(self, raw: bytes, sock) -> bytes:
        try:
            return self._serve1(raw, sock)
        except StopCycle:
            raise
        except CassetteMiss as e:
            raise CassetteMiss(self._note_miss(str(e))) from None
        except Exception as e:   # noqa: BLE001
            if getattr(e, "_tj_planned", False):
                raise
            raise CassetteMiss(self._note_miss(f"카세트 틀 오류 {type(e).__name__}: {e}")) from None

    def _note_miss(self, msg: str) -> str:
        msg = self._sec_out(msg)
        with self._lock:
            self.misses.append(msg)
            T.NET_TRIES.append(msg[:200])
        print("!! " + msg, flush=True)
        return msg

    def _serve1(self, raw: bytes, sock) -> bytes:
        method, target, hdrs, body = parse_request(raw, show=self._sec_out)
        if target.startswith(("http://", "https://")):
            sp = urllib.parse.urlsplit(target)
            if _origin_of(sp) != sock.origin():
                raise CassetteMiss(f"카세트: 요청 대상 URL 원점 {_origin_of(sp)} ≠ 실제 접속 대상 {sock.origin()}")
            target = urllib.parse.urlunsplit(("", "", sp.path or "/", sp.query, ""))
        url = sock.origin() + target
        pseudo = [(":timeout", sock.timeout_text())]
        if sock._tls:
            pseudo += [(":tls", "검증" if sock._verify else "검증 꺼짐"), (":sni", sock._sni or "")]
        with self._lock:
            self.served += 1
            CLOCK.n += 1
            n = self._norm(method, url, hdrs + pseudo, body)
            if self.record:
                return self._record1(n, Request(method, url, hdrs, body))
            q = self.queues.get(n.key)
            if not q:
                d = n.key + ((" 본문=" + json.dumps(self._redact(n.req.get("json", n.req.get("form", n.req.get("text")))), ensure_ascii=False)[:300])
                             if len(n.req) > 2 else "")
                raise CassetteMiss("카세트에 없는 요청(새로 나감): " + d)
            e = q.pop(0)
            for part, want, got in (("헤더", e["hdr"], n.hdr), ("인증", e["auth"], n.auth)):
                if want != got:
                    ks = sorted(set(want) | set(got))
                    self.diffs.append({"key": n.key, part: {k: [want.get(k), got.get(k)] for k in ks if want.get(k) != got.get(k)}})
            return resp_raw(e["resp"])

    def _record1(self, n: _Norm, rq: Request) -> bytes:
        if self.served > MAX_REQUESTS:
            raise CassetteMiss(f"카세트 녹화: 요청 {MAX_REQUESTS}건 넘음(끝없는 되풀이?)")
        try:
            r = resp_store(as_reply(self.responder(rq)))
        except Exception as e:   # noqa: BLE001
            if getattr(e, "_tj_planned", False):
                raise
            tb9 = traceback.extract_tb(e.__traceback__)[-1:]
            at9 = " @%s:%d" % (os.path.basename(tb9[0].filename), tb9[0].lineno) if tb9 else ""
            raise CassetteMiss(f"카세트 녹화: 응답기 오류 {type(e).__name__}: {e}{at9} — {self._sec_out(n.key)[:160]}") from None
        self.entries.append({"key": n.key, "req": n.req, "hdr": n.hdr, "auth": n.auth, "resp": r})
        return resp_raw(r)

    @contextlib.contextmanager
    def play(self, fast_sleep: bool = True, stop_sleep: float = None):
        if self.missing:
            raise RuntimeError("카세트 파일 없음 — ready() 먼저")
        if not FROZEN:
            raise RuntimeError("freeze() 를 src 모듈을 가져오기 전에 먼저 부를 것(시각·monotonic·uuid 고정)")
        CLOCK.now, CLOCK.n, CLOCK.tick = CLOCK.t(), 0, float(self.tick or 0.0)
        tr = Transport(self)
        sl0 = time.sleep
        main9 = threading.main_thread()

        def sleep(s):
            if threading.current_thread() is not main9:
                return sl0(s)
            s = max(0.0, float(s))
            if stop_sleep is not None and s >= stop_sleep:
                raise StopCycle(f"sleep {s:g}초 = 주기 끝")
            if not fast_sleep:
                return sl0(s)
            with self._lock:
                CLOCK.now += s
                MONO_OFF[0] += s
        tr.install()
        time.sleep = Fn(sleep)
        try:
            yield self
        finally:
            try:
                self._flush_socks()
            finally:
                time.sleep = sl0
                tr.uninstall()
                CLOCK.now, CLOCK.n, CLOCK.tick = CLOCK.t(), 0, 0.0

    def _flush_socks(self):
        socks, self._socks = self._socks, []
        for s9 in socks:
            try:
                s9.flush()
            except CassetteMiss as e:
                self.failed = self.failed or str(e)
            except Exception as e:   # noqa: BLE001
                self.failed = self.failed or self._note_miss(f"카세트 틀 오류(블록 끝 정리) {type(e).__name__}: {e}")

    def run(self, fn, *a, fast_sleep: bool = True, stop_sleep: float = None, **kw):
        with self.play(fast_sleep=fast_sleep, stop_sleep=stop_sleep):
            try:
                res = fn(*a, **kw)
            except StopCycle:
                return None, None
            except CassetteMiss as e:
                self.failed = str(e)
                return None, str(e)
        if stop_sleep is not None:
            self.failed = self._note_miss("카세트: stop_sleep(%gs) 을 줬는데 주기 끝 sleep 전에 함수가 돌아옴(수집기 루프가 끝남?)" % stop_sleep)
            return res, self.failed
        return res, None

    def check(self, T_):
        if self.record:
            why = [w for w in (self.failed, f"카세트 오류 {len(self.misses)}건" if self.misses else None,
                               None if self._golden_new is not None else "골든 없음(cas.golden 을 먼저)",
                               f"JWT nonce 재사용 {self.nonce_reuse}건" if self.nonce_reuse else None,
                               f"앞선 검사 실패 {len(getattr(T_, 'FAILS', None) or [])}건" if getattr(T_, "FAILS", None) else None,
                               f"바깥 연결 시도 {len(T.NET_TRIES)}건" if T.NET_TRIES else None) if w]
            if why:
                T_.chk(False, f"[{self.name}] 녹화 실패 — 저장 안 함", why)
                return
            try:
                self._save()
            except (RuntimeError, ValueError, OSError) as e:
                T_.chk(False, f"[{self.name}] 녹화 저장 거부", self._sec_out(str(e))[:900])
                return
            T_.chk(False, f"[{self.name}] 녹화 모드 — {len(self.entries)}건 저장함(판정 아님: 변수 없이 다시 돌려 재생 통과를 확인할 것)")
            return
        T_.chk(not self.misses, f"[{self.name}] 카세트에 없는 요청·깨진 전송 0", self.misses[:5])
        left = [e["key"] for q in self.queues.values() for e in q]
        T_.chk(not left, f"[{self.name}] 녹화했는데 안 나간 요청 0", left[:5])
        T_.chk(not self.diffs, f"[{self.name}] 같은 요청의 헤더·인증 값 그대로", self._redact(self.diffs[:4]))
        T_.chk(not self.nonce_reuse, f"[{self.name}] JWT nonce 재사용 0(업비트·빗썸 nonce_used 거부 꼴)", self.nonce_reuse)
        T_.chk(self.served == self.n_recorded and self.served > 0, f"[{self.name}] 요청 {self.n_recorded}건 전부 재생", [self.served, self.n_recorded])
        fn9 = self._file_net or {}
        if fn9.get("used") or any(v is not None for v in self._want.values()):
            bad9 = [k for k, v in self._want.items() if v is not None and json.loads(json.dumps(v)) != fn9.get(k)]
            T_.chk(not bad9, f"[{self.name}] 주소 모드·dns·연결 사건 = 시험 정의와 파일이 같음", bad9)
            T_.chk(self.conn_log == fn9.get("conn_log"), f"[{self.name}] 연결 시도 기록(주소·결과·순서) = 녹화와 같음",
                   [self.conn_log[:6], (fn9.get("conn_log") or [])[:6]])

    def golden(self, T_, obj):
        raw = canon(obj)
        live = enc(scrub(raw), lossy=True, where="골든")
        leaked = sorted(nm for nm, v in self.secrets.items() if v and (self._leaks(raw, v) or self._leaks(dec(live), v)))
        if self.record:
            if leaked:
                self.failed = self.failed or "수집 결과(state·inbox)에 등록 비밀값 남음: " + ", ".join(leaked)
            self._golden_new = live
            return
        if self.missing:
            return
        want = json.load(open(self.gpath, encoding="utf-8"))["golden"]
        ds = list(itertools.islice(diff(self._redact(want), self._redact(live), "$"), 25))
        T_.chk(not ds, f"[{self.name}] 골든 차이 0(수집 결과 = 녹화 때와 같음)", ds)
        T_.chk(not leaked, f"[{self.name}] 수집 결과(state·inbox)에 등록 비밀값 없음", leaked)

    def _redact(self, o):
        if isinstance(o, str):
            hit = [nm for nm, v in sorted(self.secrets.items()) if v and self._leaks(dec(o), v)]
            return "<secret:%s>" % ",".join(hit) if hit else o
        if isinstance(o, dict):
            return {self._redact(k): self._redact(x) for k, x in o.items()}
        if isinstance(o, list):
            return [self._redact(x) for x in o]
        return o

    def _save(self):
        repo9 = os.path.abspath(self.dir) == os.path.abspath(CAS_DIR)
        if repo9 and not REPO_LAYOUT:
            raise RuntimeError("녹화는 저장소 배치(public/tests)에서만")
        doc = {"_doc": ("합성 데이터(지어낸 주소·키·금액) — 카세트 시험 틀 _cassette.py 의 녹화본. "
                        "다시 녹화 = TJ_TEST_RECORD=%s · «a1*20» = 합성 16진수 압축 표기 · «~…» = 합성 아닌 값의 지문(요청 표시용)" % self.name),
               "version": 1, "name": self.name, "clock": {"now": self._t0, "tick": float(self.tick or 0.0)},
               "secrets": sorted(self.secrets), "requests": len(self.entries), "interactions": []}
        if self.preserve or self.dns or self.conn_events:
            doc.update({"addr_mode": "preserve" if self.preserve else None, "dns": self.dns, "conn_events": self.conn_events,
                        "conn_log": self.conn_log})
        for e in self.entries:
            doc["interactions"].append(dict(e, resp=enc(e["resp"], lossy=False, where="응답 " + self._sec_out(e["key"])[:80])))
        gdoc = {"_doc": "합성 데이터 — %s 카세트로 수집기를 돌린 결과(inbox 레코드·state·커서). 차이 = 동작 변화" % self.name,
                "version": 1, "name": self.name, "golden": self._golden_new}
        texts = {os.path.basename(self.path): json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                 os.path.basename(self.gpath): json.dumps(gdoc, ensure_ascii=False, indent=1, sort_keys=False) + "\n"}
        for fn, s in texts.items():
            hit = [nm for nm, v in self.secrets.items() if v and (v in s or urllib.parse.quote(v, safe="") in s or self._leaks(dec(json.loads(s)), v))]
            if hit:
                raise RuntimeError(f"카세트 녹화: 등록 비밀값 {hit} 이 {fn} 에 남음")
        _privacy_gate(texts, required=repo9)
        write_pair(self.dir, texts)
        print(f"카세트 저장: {os.path.relpath(self.path, HERE)} · {os.path.relpath(self.gpath, HERE)} (요청 {len(self.entries)}건)", flush=True)

    @staticmethod
    def _leaks(o, v: str) -> bool:
        if isinstance(o, str):
            if any(f in o for f in (v, urllib.parse.quote(v, safe=""), repr(v)[1:-1], json.dumps(v, ensure_ascii=False)[1:-1], json.dumps(v)[1:-1])):
                return True
            if o.lstrip()[:1] in ("{", "[", '"'):
                try:
                    return Cassette._leaks(json.loads(o), v)
                except ValueError:
                    return False
            return False
        if isinstance(o, dict):
            return any(Cassette._leaks(k, v) or Cassette._leaks(x, v) for k, x in o.items())
        if isinstance(o, list):
            return any(Cassette._leaks(x, v) for x in o)
        return False


@contextlib.contextmanager
def real_loopback():
    tr = Transport(None, real=True)
    tr.install()
    try:
        yield tr
    finally:
        tr.uninstall()


def write_pair(d: str, texts: dict):
    os.makedirs(d, exist_ok=True)
    paths = [os.path.join(d, fn) for fn in texts]
    stale = [os.path.basename(p) + ".bak" for p in paths if os.path.exists(p + ".bak")]
    if stale:
        raise OSError(f"카세트 녹화: 지난 실행의 백업이 남음 {stale} — 확인 뒤 지우고 다시 녹화")
    had = {p: os.path.exists(p) for p in paths}
    made = []
    try:
        for p, s in zip(paths, texts.values()):
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                f.write(s)
        for p in paths:
            if had[p]:
                os.replace(p, p + ".bak")
                made.append(p)
        for p in paths:
            os.replace(p + ".tmp", p)
    except BaseException:
        for p in paths:
            if p in made and os.path.exists(p + ".bak"):
                os.replace(p + ".bak", p)
            elif not had[p] and os.path.exists(p):
                os.remove(p)
            if os.path.exists(p + ".tmp"):
                os.remove(p + ".tmp")
        raise
    for p in made:
        os.remove(p + ".bak")


def _privacy_gate(texts: dict, required: bool = True):
    scan = os.path.join(T.ROOT, "tools", "package", "pub_scan.py")
    if not os.path.isfile(scan):
        if required:
            raise RuntimeError("녹화 검사 도구 없음(tools/package/pub_scan.py) — 저장소 배치에서만 녹화")
        return
    d = tempfile.mkdtemp(prefix="tj_cas_scan_", dir=T.TMP)
    try:
        for fn, s in texts.items():
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write(s)
        p = subprocess.run([sys.executable, "-I", "-B", scan, d, "--synthetic"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if p.returncode != 0:
            hits = re.findall(r"✗\s+(\S+)\s+\[([^\]]+)\]", p.stdout)
            raise RuntimeError("카세트 녹화본이 개인정보 스캔에 걸림 — 저장 안 함: " + ", ".join(f"{a} [{b}]" for a, b in hits[:30]))
    finally:
        shutil.rmtree(d, ignore_errors=True)

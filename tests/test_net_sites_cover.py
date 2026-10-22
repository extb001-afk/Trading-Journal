#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _arch as A  # noqa: E402
import _harness as T  # noqa: E402

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import _arch_py_facts as F  # noqa: E402
import _arch_py_ratchet as R  # noqa: E402
import _net_sites_table as NS  # noqa: E402

GOLDEN = os.path.join(T.HERE, "cassettes", "net_sites.golden.json")
KEY = "api.urlopen"


NH = ("net_http.request", "net_http.urlopen")


def site(u):
    return "%s::%s" % (u["m"], u["q"])


class _NhRefs(F.Walk):

    def api_value(self, n, last, sc):
        if isinstance(n.ctx, ast.Load) and self.dotted(n) in NH:
            sc["nh"] = 1


def nh_refs(text, mod):
    w = _NhRefs(text, mod, ast.parse(text), False)
    w.run()
    return sorted(q for q, sc in w.scopes.items() if sc.get("nh"))


def nh_sites(src):
    out = set()
    for dp, dns, fns in os.walk(src):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        for fn in sorted(fns):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            mod = os.path.relpath(p, src)[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            if mod == "net_http":
                continue
            with open(p, encoding="utf-8") as f:
                out.update("%s::%s" % (mod, q) for q in nh_refs(f.read(), mod))
    return sorted(out)


SYN = """import net_http as nh
from net_http import urlopen as send, request
import net_http


def a(u):
    return nh.urlopen(u, timeout=1)


def b(u):
    return send(request(u), timeout=1)


def c(u, nh):
    return nh.urlopen(u)


class K:
    def d(self):
        return self.x or net_http.urlopen


def e(u):
    return net_http.auth_urlopen(u)
"""
got = nh_refs(SYN, "syn")
T.chk(got == ["K.d", "a", "b"], "[5] ⓑ 찾기가 별칭·from-import·값 참조도 잼(가린 매개변수·auth_urlopen 은 아님 · 합성 글)", got)


base_lines = R.load_lines(A.baseline_path(R.group_of(KEY)))
if A.PUBLIC_LAYOUT or base_lines is None or not os.path.isfile(GOLDEN):
    if A.PUBLIC_LAYOUT:
        print("공개판 배치 — 기준선·카세트 폴더 없음 · 건너뜀", flush=True)
    else:
        T.chk(False, "기준선 py_api.jsonl · net_sites 골든 파일 있음", [A.baseline_path(R.group_of(KEY)), GOLDEN])
    T.finish()
    sys.exit(0)

table = set(NS.SITES)
base_sites = sorted({site(u) for u in base_lines if u.get("k") == KEY and (u.get("v") or 0) > 0})
T.chk(base_sites, "기준선 직접 전송 자리 읽음(정의 = api.urlopen)", len(base_sites))
T.chk(not set(base_sites) - table, "[1] 기준선 자리 ⊆ 덮음 표", sorted(set(base_sites) - table))
nh = nh_sites(os.path.join(T.ROOT, "src"))
T.chk(len(set(nh) | set(base_sites)) >= 30, "직접 전송 자리(ⓐ 기준선 ∪ ⓑ net_http.request·urlopen) 읽음", (len(base_sites), len(nh)))
T.chk(not set(nh) - table, "[2] 지금 자리 ⓑ(net_http.request·urlopen 을 부르는 함수) ⊆ 덮음 표", sorted(set(nh) - table))

st = A.state()
T.chk(st.metrics is not None and not st.errors, "래칫 사실 뽑기(src 전부)", (st.load_error, st.errors[:3]))
cur_sites = sorted({site(u) for u in (st.metrics.units.get(KEY) if st.metrics else []) if (u.get("v") or 0) > 0})
T.chk(cur_sites, "지금 코드의 직접 전송 자리 잼", len(cur_sites))
T.chk(not set(cur_sites) - table, "[2] 지금 자리 ⓐ ⊆ 덮음 표(새 직접 전송 = 표에 줄 · net_sites 에서 부르기)", sorted(set(cur_sites) - table))
stale = sorted(table - set(base_sites) - set(cur_sites) - set(nh))
T.chk(not stale, "덮음 표에 없어진 자리가 남지 않음(옮기거나 지운 자리는 표에서도 뺄 것)", stale)

with open(GOLDEN, encoding="utf-8") as f:
    gold = json.load(f).get("golden") or {}
gsites = sorted((gold.get("sites") or {}).keys())
want = sorted(NS.cassette_sites())
T.chk(gsites == want, "[3] 표의 카세트 자리(+ 덧갈래) = net_sites 골든 자리", sorted(set(gsites) ^ set(want)))
no_req = sorted(k for k, v in (gold.get("sites") or {}).items() if not (isinstance(v, dict) and (v.get("n") or 0) >= 1 and "ret" in v))
T.chk(not no_req, "골든의 자리마다 요청 ≥1 · 결과 있음", no_req)
kinds = {k: v[0] for k, v in NS.SITES.items()}
T.chk(set(kinds.values()) <= {NS.CASSETTE, NS.UNIT, NS.ALLOW}, "표 칸 = 카세트·단위 시험만·허용", sorted(set(kinds.values())))
miss_unit = sorted(k for k, (kind, note) in NS.SITES.items() if kind in (NS.UNIT, NS.ALLOW)
                   and not any(os.path.isfile(os.path.join(T.HERE, w)) for w in note.replace("·", " ").split() if w.startswith("test_") and w.endswith(".py")))
T.chk(not miss_unit, "[4] 단위 시험만·허용 줄 = 덮는 시험 파일 이름 있음", miss_unit)
T.finish()

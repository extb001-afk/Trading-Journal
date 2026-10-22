#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import core_common  # noqa: E402
import core_svc  # noqa: E402
import discopen  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk


class Rd:

    def __init__(self, recs):
        self.recs = recs

    def read_batch(self, seg, off, max_records=1):
        return [(r, 1, i) for i, r in enumerate(self.recs[:max_records])], seg, off


c = core.Core(config.load_config())

c.chain_owners = {"tron": {"T" + "a" * 33}}
c.svc_recon._nonevm_adapter = lambda ch: object() if ch == "tron" else None
old1 = sorted(c.__dict__.get("chain_owners") or {})
got1 = [t for t in c.svc_recon._prov_targets() if t[1] == "nonevm"]
chk(old1 == ["tron"] and got1 == [("tron", "nonevm", "chain", sorted(c.chain_owners["tron"]))],
    "B1 chain_owners 있음 = 새 체인 관측 대상(고치기 전 식과 같은 체인)", got1)
del c.chain_owners
got1b = c.svc_recon._prov_targets()
chk(not (c.__dict__.get("chain_owners") or {}) and [t for t in got1b if t[1] == "nonevm"] == [],
    "B1 core 에 chain_owners 없음 = 새 체인 칸 없음 · 예외 없음(고치기 전 = __dict__ 없음 → {})", got1b)
c.chain_owners = {}

c.reader, c.sol_reader, c.bsc_reader = Rd([]), Rd([]), Rd([])
c.chain_readers = [("tron", Rd([{"chain": "TRON", "kind": "chain_delta_tx"}]))]
old2 = tuple(c.__dict__.get("chain_readers") or ())
chk(len(old2) == 1 and c.svc_recon._recon_pending_chains() == {"tron"} and c.svc_recon._streams_have_data() is True,
    "B2 chain_readers 스트림 포함 = 미소비 체인 {tron} · 데이터 있음", c.svc_recon._recon_pending_chains())
del c.chain_readers
chk(tuple(c.__dict__.get("chain_readers") or ()) == () and c.svc_recon._recon_pending_chains() == set() and c.svc_recon._streams_have_data() is False,
    "B2 core 에 chain_readers 없음 = 종전 3스트림만(빈 집합 · 데이터 없음 · 예외 없음)")
c.chain_readers = []

c.cfg["chains"]["robin"] = {"discovery": "rpc"}
for ch in ("robin", "eth"):
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"recon_done_{ch}", "1700000000"))
c.conn.commit()
with open(paths.state("cursor_evm_robin.json"), "w") as fh:
    json.dump({"_rpc_v": 1}, fh)
c.svc_recon._scope_ready = lambda ch, *a, **k: True
vr, ve = c._recon_view("robin"), c._recon_view("eth")
cache = c.__dict__["_recon_cache"]
chk(set(cache) == {"robin", "eth"} and vr[0] == ve[0] == 1700000000, "B3 준비 — core 의 대사 관점 캐시에 두 체인", sorted(cache))
c.svc_recon._rpc_recon_reset()
chk(c.__dict__["_recon_cache"] is cache and set(cache) == {"eth"} and c._meta_get("recon_done_robin") is None
    and c._meta_get("recon_reset_rpc_robin") not in (None, "skipped_existing_opening"),
    "B3 RPC 재대사 1회 = 도장 지움 + core 캐시에서 그 체인만 빠짐(같은 사전 · 다른 체인 그대로)", sorted(cache))
chk(c._recon_view("robin") == (None, set()), "B3 지운 뒤 다시 읽으면 새 값(대사 전)")
c._recon_view_drop("nope")
chk(set(cache) == {"eth", "robin"}, "B3 없는 체인 지우기 = 무동작(예외 없음)")

chk(core_svc.CLASSIFIER_VER == core_common.CLASSIFIER_VER and discopen._ver(c.svc_exf) == core_common.CLASSIFIER_VER
    and discopen._ver(c) == core_common.CLASSIFIER_VER and core_common.CLASSIFIER_VER != 3,
    "B4 discopen._ver(서비스·Core) = core_common.CLASSIFIER_VER(type(x).__module__ 모듈 속성)", discopen._ver(c.svc_exf))

T.finish()

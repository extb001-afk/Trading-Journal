#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
ME = "0x" + "a1" * 20
ME2 = "0x" + "a2" * 20
X = "0x" + "c3" * 20
TK = "0x" + "e7" * 20
MRC = "0x0000000000000000000000000000000000001010"
CFG = {"chains": {"polygon": {"blockscout": "https://bs-pol.invalid", "rpcs": ["https://rpc-pol.invalid"]},
                  "eth": {"blockscout": "https://bs-eth.invalid", "rpcs": ["https://rpc-eth.invalid"]}},
       "wallets": [{"type": "evm", "chain": "polygon", "address": ME}, {"type": "evm", "chain": "polygon", "address": ME2},
                   {"type": "evm", "chain": "eth", "address": ME}],
       "native_symbol": {"eth": "ETH", "polygon": "POL"}, "backfill_months": 5}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import chaincatalog  # noqa: E402
import config, paths  # noqa: E402
import core  # noqa: E402
import discopen  # noqa: E402
import evm_watch  # noqa: E402

NTC = getattr(chaincatalog, "not_token_cas", lambda ch: set())


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


H = "0x" + "22" * 32
E18 = 10 ** 18


def pad(a):
    return "0x" + a[2:].rjust(64, "0")


def synth(chain, tx_to, value, logs):
    class S(evm_watch.RpcSynthMixin):
        wallets = [ME]
        rpc_meta = {TK: 18}
        rpc_meta_path = os.path.join(T.TMP, "m.json")
        wrapped_ca = None
        cfg_rpcs = ["x"]

        def _rpc_call(self, m, p):
            if m == "eth_getTransactionByHash":
                return {"hash": H, "from": ME, "to": tx_to, "value": hex(value), "input": "0xa9059cbb", "blockNumber": "0x10",
                        "transactionIndex": "0x0", "nonce": "0x1", "type": "0x2"}
            if m == "eth_getTransactionReceipt":
                return {"blockNumber": "0x10", "gasUsed": "0x5208", "effectiveGasPrice": "0x1", "status": "0x1", "blockHash": "0x" + "33" * 32,
                        "transactionIndex": "0x0",
                        "logs": [dict(lg, logIndex=hex(i)) for i, lg in enumerate(logs)]}
            if m == "eth_getBlockByNumber":
                return {"timestamp": hex(1760000000)}
            if m == "eth_call":
                return "0x" + "%064x" % 18
            raise RuntimeError(m)
    S.chain = chain
    return S()._rpc_synth_detail(H)


TT = evm_watch.RpcSynthMixin.TRANSFER_TOPIC
v = 5 * E18
s1 = T.safe(synth, "polygon", MRC, v, [{"address": MRC, "topics": [TT, pad(ME), pad(X)], "data": hex(v)}])
tok1 = [t["token"]["address"] for t in (s1.get("token_transfers") or [])] if isinstance(s1, dict) and "_exc" not in s1 else s1
chk("N1 polygon 0x…1010 transfer() = 토큰 레그 0 · tx.value 5 POL 그대로(종전 = 0x…1010 토큰 레그 + tx.value = 이중)",
    isinstance(s1, dict) and "tx" in s1 and tok1 == [] and int(str(s1["tx"]["value"]), 0) == v, (tok1, (s1.get("tx") or {}).get("value") if isinstance(s1, dict) else s1))
s1b = T.safe(synth, "polygon", TK, 0, [{"address": TK, "topics": [TT, pad(ME), pad(X)], "data": hex(7 * E18)},
                                       {"address": MRC, "topics": [TT, pad(X), pad(ME)], "data": hex(3)}])
tok1b = [(t["token"]["address"], int(t["total"]["value"])) for t in (s1b.get("token_transfers") or [])] if isinstance(s1b, dict) else s1b
chk("N1 반대: 같은 tx 의 일반 토큰 레그는 그대로(별칭 레그만 빠짐)", tok1b == [(TK, 7 * E18)], tok1b)
STB = chaincatalog.NATIVE_MIRROR["stable"][0]
s1c = T.safe(synth, "stable", TK, 0, [{"address": STB, "topics": [TT, pad(X), pad(ME)], "data": hex(4_000_000)}])
int1c = [int(i["value"]) for i in (s1c.get("internal") or [])] if isinstance(s1c, dict) else s1c
chk("N1 반대: stable 거울(NATIVE_MIRROR_SRC) = 종전대로 네이티브 internal 환산(4 USDT0 → 18자리) · 토큰 레그 0",
    isinstance(s1c, dict) and int1c == [4 * E18] and not s1c.get("token_transfers"), (int1c, s1c if not isinstance(s1c, dict) else s1c.get("token_transfers")))

chk("N2 not_token_cas: polygon = {0x…1010} · celo · metis · arc 거울 · zksync 0x…800a · eth = 빈 집합",
    NTC("polygon") == {MRC} and NTC("celo") == {"0x471ece3750da237f93b8e339c536989b8978a438"}
    and NTC("metis") == {"0xdeaddeaddeaddeaddeaddeaddeaddeaddead0000"}
    and NTC("arc") == {chaincatalog.NATIVE_MIRROR["arc"][0]}
    and NTC("zksync") == {chaincatalog.ZK_STACK["zksync"][0]} and NTC("eth") == set())
chk("N2 NATIVE_MIRROR_SRC = stable 만(별칭 체인은 환산 출처 아님) · 합성 버림 집합 = 거울 ∪ 별칭",
    set(evm_watch.RpcSynthMixin.NATIVE_MIRROR_SRC) == {"stable"} and MRC in evm_watch.RpcSynthMixin.NATIVE_MIRROR.get("polygon", ())
    and chaincatalog.NATIVE_MIRROR["arc"][0] in evm_watch.RpcSynthMixin.NATIVE_MIRROR.get("arc", ())
    and "polygon" not in chaincatalog.NATIVE_MIRROR, dict(evm_watch.RpcSynthMixin.NATIVE_MIRROR))

c = core.Core(config.load_config())
a_mrc = c.asset_id("token", "polygon", MRC, symbol="POL", decimals=18)
a_tk = c.asset_id("token", "polygon", TK, symbol="TKX", decimals=18)
a_nat = c.asset_id("native", "polygon", None, symbol="POL", decimals=18)
c.conn.commit()
g1, g2 = discopen.asset_guard(c.conn, a_mrc), discopen.asset_guard(c.conn, a_tk)
chk("N4 발견 기초잔고 가드 = 별칭 토큰 거부 · 일반 토큰 통과", bool(g1) and g2 == "", (g1, g2))

for ca7, w7 in ((MRC, ME), (TK, ME2)):
    sid7 = discopen.sid_of("polygon", w7, ca7, 100)
    c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
                   (sid7, "opening_balance", "polygon", json.dumps({w7: {"token:" + ca7: str(7 * E18)}, "_block": 100, "_at": 1750000000}), 1760000000))
c.conn.commit()
dob = discopen.disc_obs(c.conn)
chk("N7 발견 관측 재료 = 별칭 토큰 관측 뺌(정정한 OPENING 을 재구축이 되살리지 않음) · 일반 토큰 관측 그대로",
    not any(v["aid"] == a_mrc for v in dob.values()) and any(v["aid"] == a_tk for v in dob.values()), dob)
c.conn.execute("DELETE FROM raw_observations WHERE obs_id LIKE 'recon:polygon:%:disc:%'")
c.conn.commit()

snapx = {"tx": {"hash": H, "from": {"hash": ME}, "to": {"hash": MRC}, "value": str(5 * E18), "status": "ok", "timestamp": "2025-10-10T00:00:00Z",
                "fee": {"value": "21000"}},
         "token_transfers": [{"from": {"hash": ME}, "to": {"hash": X}, "token": {"address": MRC, "type": "ERC-20", "decimals": "18", "symbol": "POL"},
                              "total": {"value": str(5 * E18), "decimals": "18"}},
                             {"from": {"hash": X}, "to": {"hash": ME}, "token": {"address": TK, "type": "ERC-20", "decimals": "18", "symbol": "TKX"},
                              "total": {"value": str(2 * E18), "decimals": "18"}}],
         "internal": []}
dx = T.safe(c.deltas, "polygon", snapx)
perw = dx[0] if isinstance(dx, tuple) else {}
aids_x = {aid for (_w, aid), v in perw.items() if v}
chk("N6 탐색기 상세 = 별칭 토큰 레그 없음(네이티브 tx.value 만) · 일반 토큰 레그 그대로", isinstance(dx, tuple) and a_mrc not in aids_x and a_tk in aids_x
    and perw.get((ME, a_nat), 0) < 0, (perw if isinstance(dx, tuple) else dx))

for i9, (w9, aid9, q9) in enumerate([(ME, a_mrc, 60 * E18 + 7), (ME2, a_mrc, 932 * E18), (ME, a_tk, 11 * E18), (ME, a_nat, 61 * E18)]):
    c._post_leg_strict("opening", "polygon", f"recon:polygon:{w9}", i9, 1750000000, aid9, f"wallet:polygon:{w9}", q9, None, None, "opening", "OPENING")
c._post_leg_strict("chain_tx", "polygon", "0x" + "44" * 32, 0, 1760000000, a_tk, f"wallet:polygon:{ME}", -E18, None, None, "move_out", "TRANSFER_OUT")
c.conn.commit()
DB = paths.DB_PATH


def dump():
    k = sqlite3.connect(paths.sqlite_ro_uri(DB), uri=True)
    try:
        p = sorted(k.execute("SELECT * FROM postings").fetchall())
        pos = {(r[0], r[1]): Decimal(r[2]) for r in k.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()}
        inv = k.execute("SELECT v FROM meta WHERE k=?", (__import__("db").DAILY_INVAL_K,)).fetchone()
        return p, pos, inv
    finally:
        k.close()


FAKE = os.path.join(T.TMP, "fakebin")
os.makedirs(FAKE, exist_ok=True)
for nm, body in (("pm2", "echo '[]'"), ("pm2core", "echo '[{\"name\": \"tj-core\", \"pm2_env\": {\"status\": \"online\"}}]'")):
    with open(os.path.join(FAKE, nm), "w") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    os.chmod(os.path.join(FAKE, nm), 0o755)


def tool(*args, pm2="pm2"):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PM2_BIN=os.path.join(FAKE, pm2), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.join(T.ROOT, "tools", "ledger_rowfix.py")] + list(args), env=env,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


if not os.path.isfile(os.path.join(T.ROOT, "tools", "ledger_rowfix.py")):
    chk("N5 정정 도구 tools/ledger_rowfix.py --kind mirror_open 없음", False)
else:
    p0, pos0, inv0 = dump()
    rc, out = tool()
    chk("N5 종류 없음 = 거부(원장 무변)", rc == 2 and dump() == (p0, pos0, inv0), out[-300:])
    rc, out = tool("--kind", "mirror_open")
    chk("N5 점검 = 대상 2행 · 원장 무변", rc == 0 and "지울 행 2개" in out and dump() == (p0, pos0, inv0), out[-600:])
    rc, out = tool("--kind", "mirror_open", "--apply", pm2="pm2core")
    chk("N5 core 떠 있음 = 거부(원장 무변)", rc == 1 and dump() == (p0, pos0, inv0), out[-400:])
    rc, out = tool("--kind", "mirror_open", "--apply")
    p1, pos1, inv1 = dump()
    gone = {r[0] for r in p0} - {r[0] for r in p1}
    gm = c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (a_mrc,)).fetchone()[0]
    chk("N5 적용 = 별칭 OPENING 2행만 삭제 · 그 칸 포지션 0 · 다른 행·포지션 그대로 · 일별 무효화 표식",
        rc == 0 and len(gone) == 2 and all(r[6] == a_mrc for r in p0 if r[0] in gone) and [r for r in p0 if r[0] not in gone] == p1
        and pos1[(gm, f"wallet:polygon:{ME}")] == 0 and pos1[(gm, f"wallet:polygon:{ME2}")] == 0
        and {k: v for k, v in pos0.items() if k[0] != gm} == {k: v for k, v in pos1.items() if k[0] != gm} and inv1 != inv0, out[-600:])
    undo = [ln.split("되돌리기 파일 ")[-1].strip() for ln in out.splitlines() if "되돌리기 파일" in ln]
    rc, out = tool("--kind", "mirror_open", "--apply")
    chk("N5 두 번째 적용 = 할 일 없음(멱등 · 원장 무변)", rc == 0 and "할 일 없음" in out and dump() == (p1, pos1, inv1), out[-400:])
    if undo and os.path.isfile(undo[-1]):
        fake = json.load(open(undo[-1]))
        fake["rows"][0]["qty_base"] = str(int(fake["rows"][0]["qty_base"]) * 1000)
        fk_path = os.path.join(paths.STATE_DIR, "ledger_rowfix_undo_mirror_open_fake.json")
        json.dump(fake, open(fk_path, "w"))
        rc, out = tool("--undo", fk_path, "--apply")
        chk("N5 손댄 되돌리기 파일 = 거부(영수증 없음 · 원장 무변)", rc == 4 and dump()[:2] == (p1, pos1), out[-300:])
        rc, out = tool("--undo", undo[-1], "--apply")
        p2, pos2, _inv2 = dump()
        chk("N5 되돌리기 = 같은 posting_id 로 복원 · 포지션 원래 값", rc == 0 and p2 == p0 and pos2 == pos0, out[-400:])
        rc, out = tool("--undo", undo[-1], "--apply")
        chk("N5 되돌리기 두 번 = 거부(같은 키 행 있음 · 원장 무변)", rc == 4 and dump()[:2] == (p0, pos0), out[-300:])
        W9X = "0x" + "dd" * 20
        c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                       " leg_kind, event, classifier_ver) VALUES ('opening','polygon',?,0,1750000000,?,?,?,NULL,NULL,'opening','OPENING',1)",
                       (f"recon:polygon:{W9X}", a_mrc, f"wallet:polygon:{W9X}", str(E18)))
        c.conn.commit()
        p3, pos3, _i3 = dump()
        rc, out = tool("--kind", "mirror_open", "--apply")
        chk("N5 대상 칸 포지션 행 없음 = 전부 거부(허위 포지션 안 만듦 · 원장 무변)", rc == 4 and dump()[:2] == (p3, pos3), out[-300:])
    else:
        chk("N5 되돌리기 파일 없음", False, out[-400:])
T.finish()

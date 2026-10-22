#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _rpcfake as R  # noqa: E402

import bf_engine  # noqa: E402
import evm_logdisc  # noqa: E402
import token_discovery as td  # noqa: E402

R.loop_open(bf_engine, T)


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


TT = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def rows(n, blk=5):
    return [{"transactionHash": "0x%064x" % i, "blockNumber": hex(blk), "address": "0x" + "e7" * 20, "topics": [TT, "0x" + "0" * 64, "0x" + "0" * 64]}
            for i in range(n)]


class Fake:
    TRANSFER_TOPIC = TT
    logs_sleep = 0

    def __init__(self, n):
        self.n = n

    def _one(self, url, m, p):
        return rows(self.n)


r1 = T.safe(evm_logdisc.RpcLogDiscovery._chunk_logs, Fake(1000), "u", 1, 100, ["0x" + "0" * 64])
chk("L1 _chunk_logs 1,000행 = range 오류(잘림 의심 · 커서 미전진)", isinstance(r1, dict) and "range" in str(r1.get("_exc")) and "결과 상한" in str(r1.get("_exc")), r1)
r2 = T.safe(evm_logdisc.RpcLogDiscovery._chunk_logs, Fake(3), "u", 1, 100, ["0x" + "0" * 64])
chk("L1 반대: 3행 = 종전대로 발견", isinstance(r2, dict) and len(r2) == 3 and "_exc" not in r2, r2)

mode = {"full": False}


def node_fn(method, params):
    if method == "eth_blockNumber":
        return hex(1999)
    q = params[0]
    a, b = int(q["fromBlock"], 16), int(q["toBlock"], 16)
    return rows(1000) if (mode["full"] or b - a + 1 > 500) else rows(2)


node = R.Node(node_fn)
cfg = {"chains": {"zzchain": {"rpcs": [node.url], "getlogs_span": 1000}}}
n = T.safe(td.src_logs, "zzchain", "0x" + "a1" * 20, cfg, upto=1999, max_calls=100, out={}, meta={}, sleep=lambda s: None)
spans = [int(p[0]["toBlock"], 16) - int(p[0]["fromBlock"], 16) + 1 for m, p in node.calls if m == "eth_getLogs"]
chk("L2 src_logs 포화(1,000행) = 구간 반감해 다시 · 받아들인 구간 = 500블록 이하로 두 토픽 전체", isinstance(n, int)
    and sum(s for s in spans if s <= 500) == 2 * 2000 and 1000 in spans, (n, spans[:8]))
mode["full"] = True
n2 = T.safe(td.src_logs, "zzchain", "0x" + "a1" * 20, cfg, upto=1999, max_calls=1000, out={}, meta={}, sleep=lambda s: None)
chk("L2 최소 구간도 포화 = SourceFail partial(완료로 안 셈)", isinstance(n2, dict) and "결과 상한" in str(n2.get("_exc")), n2)
node.close()
T.finish()

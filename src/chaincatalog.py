"""Catalog of supported EVM chains and their data sources."""
import json
import os

_POLL = 120
CATALOG = {
    "monad": {
        "_note": "Monad(chainId 143, 0.4s 블록). RPC 전용: 로그 = rpc1(지갑 토픽 getLogs 체인 전 구간, 비아카이브), 상태·상세 = rpc2(아카이브, getLogs 1만)",
        "discovery": "rpc", "chain_id": 143, "rpcs": ["https://rpc2.monad.xyz", "https://rpc.monad.xyz"],
        "rpc_logs": ["https://rpc1.monad.xyz"], "getlogs_span": 5000000, "conf_depth": 20, "blocks_per_day": 285000,
        "poll_sec": _POLL},
    "megaeth": {
        "_note": "MegaETH(chainId 4326, EVM 블록 1s). 블록스카웃 v2(키 불필요)",
        "blockscout": "https://megaeth.blockscout.com", "chain_id": 4326, "rpcs": ["https://mainnet.megaeth.com/rpc"],
        "conf_depth": 30, "blocks_per_day": 86400, "poll_sec": _POLL},
    "plasma": {
        "_note": "Plasma(chainId 9745, 1s). RPC 전용(공식 아카이브, getLogs 1만 블록). 스팸 에어드랍 토큰이 많다(격리 대상)",
        "discovery": "rpc", "chain_id": 9745, "rpcs": ["https://rpc.plasma.to"], "getlogs_span": 10000,
        "conf_depth": 20, "blocks_per_day": 86400, "poll_sec": _POLL},
    "xlayer": {
        "_note": "X Layer(chainId 196, 1s). RPC 전용: 공식 노드 getLogs 100 블록 상한 · 무료 대체 노드는 최근 1만 블록만이라 과거 창 백필 불가 → start_block 부터 추적, 그 이전 보유는 기초 잔고(opening)로 대사",
        "discovery": "rpc", "chain_id": 196, "rpcs": ["https://xlayerrpc.okx.com", "https://rpc.xlayer.tech"],
        "getlogs_span": 100, "start_block": 71790000, "conf_depth": 20, "blocks_per_day": 86400, "poll_sec": _POLL},
    "kaia": {
        "_note": "Kaia(chainId 8217, 1s, 즉시 완결). RPC 전용(공식 EN 아카이브, getLogs 10만 블록)",
        "discovery": "rpc", "chain_id": 8217, "rpcs": ["https://public-en.node.kaia.io"], "getlogs_span": 100000,
        "conf_depth": 10, "blocks_per_day": 86400, "poll_sec": _POLL},
    "fraxtal": {
        "_note": "Fraxtal(chainId 252, OP 스택 2s, 가스 = FRAX). RPC 전용(공식 아카이브, 지갑 토픽 getLogs 전 구간)",
        "discovery": "rpc", "chain_id": 252, "rpcs": ["https://rpc.frax.com"], "conf_depth": 30, "blocks_per_day": 43200,
        "poll_sec": _POLL},
    "bob": {
        "_note": "BOB(chainId 60808, OP 스택 2s). RPC 전용(공식 아카이브, getLogs 전 구간)",
        "discovery": "rpc", "chain_id": 60808, "rpcs": ["https://rpc.gobob.xyz"], "conf_depth": 30, "blocks_per_day": 43200,
        "poll_sec": _POLL},
    "story": {
        "_note": "Story(chainId 1514, 가스 = IP). 블록스카웃 v2(storyscan, 키 불필요)",
        "blockscout": "https://www.storyscan.io", "chain_id": 1514, "rpcs": ["https://mainnet.storyrpc.io"],
        "conf_depth": 20, "blocks_per_day": 38000, "poll_sec": _POLL},
    "somnia": {
        "_note": "Somnia(chainId 5031, 0.1s, 가스 = SOMI). 블록스카웃 v2(키 불필요)",
        "blockscout": "https://explorer.somnia.network", "chain_id": 5031, "rpcs": ["https://api.infra.mainnet.somnia.network"],
        "conf_depth": 100, "blocks_per_day": 864000, "poll_sec": _POLL},
    "avalanche": {
        "_note": "Avalanche C(chainId 43114, 즉시 완결). RPC 전용(공식 아카이브, getLogs 10만 블록)",
        "discovery": "rpc", "chain_id": 43114, "rpcs": ["https://api.avax.network/ext/bc/C/rpc"], "getlogs_span": 100000,
        "conf_depth": 10, "blocks_per_day": 76000, "poll_sec": _POLL},
    "stable": {
        "_note": "Stable(chainId 988, 약 0.7s, 즉시 완결 · 가스 = USDT0). 네이티브(18자리)와 ERC-20 거울(6자리)이 같은 잔고 — 수집기는 거울 Transfer 를 네이티브 이동으로 환산(common.NATIVE_MIRROR, 이중 기장 차단). 공식 RPC 비아카이브(상태는 헤드 근처만 · getLogs 1,024 블록 상한)라 과거 창 백필 불가 → start_block 부터 추적, 그 이전 보유는 기초 잔고(opening)로 대사",
        "discovery": "rpc", "chain_id": 988, "rpcs": ["https://rpc.stable.xyz"], "getlogs_span": 1000, "start_block": 41000000,
        "conf_depth": 10, "blocks_per_day": 122000, "poll_sec": _POLL},
    "abstract": {
        "_note": "Abstract(chainId 2741, ZK Stack L2, 가스 = ETH). RPC 전용(공식 아카이브, 지갑 토픽 getLogs 큰 구간 가능 · 결과 1만 건 상한이면 구간 반감). 네이티브 ETH 이동 = L2BaseToken Transfer 로그 · 가스 = 부트로더 레그(evm_watch.NATIVE_EMITTER + NATIVE_FEE_SINK)",
        "discovery": "rpc", "chain_id": 2741, "rpcs": ["https://api.mainnet.abs.xyz"], "getlogs_span": 5000000,
        "conf_depth": 20, "blocks_per_day": 140000, "poll_sec": _POLL},
}


AUTO_WINDOW_CALLS = 3000

AUTO_RPS = 20


def block_for(chain: str, since_known: bool, speed: dict = None):
    if chain in CATALOG:
        b = json.loads(json.dumps(CATALOG[chain]))
        b["_auto"] = "catalog"
        return b, "catalog"
    try:
        import chainsweep
    except ImportError:
        return None, "chainsweep 없음"
    ent = chainsweep.SWEEP_CHAINS.get(chain)
    if not ent:
        return None, "점검 목록에 없는 체인"
    sp = speed or {}
    span, bps = sp.get("getLogsSpan"), sp.get("blocksPerSec")
    if not span or not bps:
        return None, "실측 없음(getLogs 구간·블록 속도)"
    if not since_known and not sp.get("autoOk"):
        return None, f"창 백필 비용 과다(getLogs ≈{sp.get('windowCalls')}콜)"
    name, cid, sym, rpcs, _b = ent
    return {"_note": f"{name}(chainId {cid}) — 활동 게이트 자동 켜기(범용 RPC 블록, 실측 getLogs 구간 {span:,}·{bps} 블록/초)",
            "_auto": "generic", "discovery": "rpc", "chain_id": int(cid), "rpcs": list(rpcs),
            "getlogs_span": int(min(int(span), 5_000_000)), "conf_depth": 20,
            "blocks_per_day": int(max(1.0, float(bps)) * 86400), "poll_sec": _POLL, "rps": AUTO_RPS}, "generic"


def native_of(chain: str):
    try:
        import common
        if chain in common.EXTRA_CHAINS:
            m = common.EXTRA_CHAINS[chain]
            return m[1], m[3]
        import chainsweep
        e = chainsweep.SWEEP_CHAINS.get(chain)
        return (e[2], None) if e else (None, None)
    except ImportError:
        return None, None

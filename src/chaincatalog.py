"""Catalog of supported EVM chains and their data sources."""
import json
import os
import re

_POLL = 120
CATALOG = {
    "monad": {
        "_note": "Monad(chainId 143, 0.4s 블록). RPC 전용: 로그 = rpc1(지갑 토픽 getLogs 체인 전 구간, 비아카이브), 상태·상세 = rpc2(아카이브, getLogs 1만)",
        "discovery": "rpc", "chain_id": 143, "rpcs": ["https://rpc2.monad.xyz", "https://rpc.monad.xyz"],
        "rpc_logs": ["https://rpc1.monad.xyz"], "getlogs_span": 5000000, "conf_depth": 20, "blocks_per_day": 285000,
        "poll_sec": _POLL, "alchemy": "monad-mainnet", "alchemy_tokens": True},
    "megaeth": {
        "_note": "MegaETH(chainId 4326, EVM 블록 1s). 블록스카웃 v2(키 불필요)",
        "blockscout": "https://megaeth.blockscout.com", "chain_id": 4326, "rpcs": ["https://mainnet.megaeth.com/rpc"],
        "conf_depth": 30, "blocks_per_day": 86400, "poll_sec": _POLL, "alchemy": "megaeth-mainnet", "alchemy_tokens": False},
    "plasma": {
        "_note": "Plasma(chainId 9745, 1s). RPC 전용(공식 아카이브, getLogs 1만 블록). 스팸 에어드랍 토큰이 많다(격리 대상)",
        "discovery": "rpc", "chain_id": 9745, "rpcs": ["https://rpc.plasma.to"], "getlogs_span": 10000,
        "conf_depth": 20, "blocks_per_day": 86400, "poll_sec": _POLL, "alchemy": "plasma-mainnet", "alchemy_tokens": False},
    "xlayer": {
        "_note": "X Layer(chainId 196, 1s). RPC 전용: 공식 노드 getLogs 100 블록 상한 · 무료 대체 노드는 최근 1만 블록만이라 과거 창 백필 불가 → start_block 부터 추적, 그 이전 보유는 기초"
                 " 잔고(opening)로 대사",
        "discovery": "rpc", "chain_id": 196, "rpcs": ["https://xlayerrpc.okx.com", "https://rpc.xlayer.tech"],
        "getlogs_span": 100, "start_block": 71790000, "conf_depth": 20, "blocks_per_day": 86400, "poll_sec": _POLL, "alchemy": "xlayer-mainnet", "alchemy_tokens": False},
    "kaia": {
        "_note": "Kaia(chainId 8217, 1s, 즉시 완결). RPC 전용(공식 EN 아카이브, getLogs 10만 블록)",
        "discovery": "rpc", "chain_id": 8217, "rpcs": ["https://public-en.node.kaia.io"], "getlogs_span": 100000,
        "conf_depth": 10, "blocks_per_day": 86400, "poll_sec": _POLL, "alchemy": "kaia-mainnet", "alchemy_tokens": False},
    "fraxtal": {
        "_note": "Fraxtal(chainId 252, OP 스택 2s, 가스 = FRAX). RPC 전용(공식 아카이브, 지갑 토픽 getLogs 전 구간)",
        "discovery": "rpc", "chain_id": 252, "rpcs": ["https://rpc.frax.com"], "conf_depth": 30, "blocks_per_day": 43200,
        "poll_sec": _POLL, "alchemy": "frax-mainnet", "alchemy_tokens": False},
    "bob": {
        "_note": "BOB(chainId 60808, OP 스택 2s). RPC 전용(공식 아카이브, getLogs 전 구간)",
        "discovery": "rpc", "chain_id": 60808, "rpcs": ["https://rpc.gobob.xyz"], "conf_depth": 30, "blocks_per_day": 43200,
        "poll_sec": _POLL, "alchemy": "bob-mainnet", "alchemy_tokens": False},
    "story": {
        "_note": "Story(chainId 1514, 가스 = IP). 블록스카웃 v2(storyscan, 키 불필요)",
        "blockscout": "https://www.storyscan.io", "chain_id": 1514, "rpcs": ["https://mainnet.storyrpc.io"],
        "conf_depth": 20, "blocks_per_day": 38000, "poll_sec": _POLL, "alchemy": "story-mainnet", "alchemy_tokens": True},
    "somnia": {
        "_note": "Somnia(chainId 5031, 0.1s, 가스 = SOMI). 블록스카웃 v2(키 불필요)",
        "blockscout": "https://explorer.somnia.network", "chain_id": 5031, "rpcs": ["https://api.infra.mainnet.somnia.network"],
        "conf_depth": 100, "blocks_per_day": 864000, "poll_sec": _POLL},
    "avalanche": {
        "_note": "Avalanche C(chainId 43114, 즉시 완결). RPC 전용(공식 아카이브, getLogs 10만 블록)",
        "discovery": "rpc", "chain_id": 43114, "rpcs": ["https://api.avax.network/ext/bc/C/rpc"], "getlogs_span": 100000,
        "conf_depth": 10, "blocks_per_day": 76000, "poll_sec": _POLL, "alchemy": "avax-mainnet", "alchemy_tokens": True},
    "stable": {
        "_note": "Stable(chainId 988, 약 0.7s, 즉시 완결 · 가스 = USDT0). 네이티브(18자리)와 ERC-20 거울(6자리)이 같은 잔고 — 수집기는 거울 Transfer 를 네이티브 이동으로"
                 " 환산(common.NATIVE_MIRROR, 이중 기장 차단). 공식 RPC 비아카이브(상태는 헤드 근처만 · getLogs 1,024 블록 상한)라 과거 창 백필 불가 → start_block 부터 추적, 그 이전 보유는 기초"
                 " 잔고(opening)로 대사",
        "discovery": "rpc", "chain_id": 988, "rpcs": ["https://rpc.stable.xyz"], "getlogs_span": 1000, "start_block": 41000000,
        "conf_depth": 10, "blocks_per_day": 122000, "poll_sec": _POLL, "alchemy": "stable-mainnet", "alchemy_tokens": False},
    "abstract": {
        "_note": "Abstract(chainId 2741, ZK Stack L2, 가스 = ETH). RPC 전용(공식 아카이브, 지갑 토픽 getLogs 큰 구간 가능 · 결과 1만 건 상한이면 구간 반감). 네이티브 ETH 이동 ="
                 " L2BaseToken Transfer 로그 · 가스 = 부트로더 레그(evm_watch.NATIVE_EMITTER + NATIVE_FEE_SINK)",
        "discovery": "rpc", "chain_id": 2741, "rpcs": ["https://api.mainnet.abs.xyz"], "getlogs_span": 5000000,
        "conf_depth": 20, "blocks_per_day": 140000, "poll_sec": _POLL, "alchemy": "abstract-mainnet", "alchemy_tokens": True},
}

_ALCHEMY_TABLE = {
    "eth": ("Ethereum", 1, "ETH", "eth-mainnet", True, False),
    "base": ("Base", 8453, "ETH", "base-mainnet", True, False),
    "arbitrum": ("Arbitrum", 42161, "ETH", "arb-mainnet", True, False),
    "optimism": ("Optimism", 10, "ETH", "opt-mainnet", True, False),
    "polygon": ("Polygon", 137, "POL", "polygon-mainnet", True, False),
    "scroll": ("Scroll", 534352, "ETH", "scroll-mainnet", True, False),
    "zksync": ("zkSync", 324, "ETH", "zksync-mainnet", True, False),
    "gnosis": ("Gnosis", 100, "XDAI", "gnosis-mainnet", True, False),
    "bsc": ("BSC", 56, "BNB", "bnb-mainnet", True, False),
    "robinhood": ("Robinhood", 4663, "ETH", "robinhood-mainnet", True, False),
    "arc": ("Arc", 5042, "USDC", "arc-mainnet", True, False),
    "hyperevm": ("HyperEVM", 999, "HYPE", "hyperliquid-mainnet", True, False),
    "sonic": ("Sonic", 146, "S", "sonic-mainnet", False, False),
    "unichain": ("Unichain", 130, "ETH", "unichain-mainnet", True, False),
    "linea": ("Linea", 59144, "ETH", "linea-mainnet", True, False),
    "blast": ("Blast", 81457, "ETH", "blast-mainnet", True, False),
    "mantle": ("Mantle", 5000, "MNT", "mantle-mainnet", False, False),
    "berachain": ("Berachain", 80094, "BERA", "berachain-mainnet", True, False),
    "sei": ("Sei", 1329, "SEI", "sei-mainnet", False, False),
    "ink": ("Ink", 57073, "ETH", "ink-mainnet", True, False),
    "soneium": ("Soneium", 1868, "ETH", "soneium-mainnet", True, False),
    "worldchain": ("World Chain", 480, "ETH", "worldchain-mainnet", True, False),
    "celo": ("Celo", 42220, "CELO", "celo-mainnet", True, False),
    "mode": ("Mode", 34443, "ETH", "mode-mainnet", False, False),
    "cronos": ("Cronos", 25, "CRO", "cronos-mainnet", False, False),
    "metis": ("Metis", 1088, "METIS", "metis-mainnet", False, False),
    "moonbeam": ("Moonbeam", 1284, "GLMR", "moonbeam-mainnet", False, False),
    "zora": ("Zora", 7777777, "ETH", "zora-mainnet", True, False),
    "opbnb": ("opBNB", 204, "BNB", "opbnb-mainnet", False, False),
    "rootstock": ("Rootstock", 30, "RBTC", "rootstock-mainnet", True, False),
    "katana": ("Katana", 747474, "ETH", "katana-mainnet", False, False),
    "apechain": ("ApeChain", 33139, "APE", "apechain-mainnet", True, False),
    "ronin": ("Ronin", 2020, "RON", "ronin-mainnet", True, False),
    "lens": ("Lens", 232, "GHO", "lens-mainnet", True, False),
    "flow_evm": ("Flow EVM", 747, "FLOW", "flow-mainnet", False, False),
    "injective": ("Injective EVM", 1776, "INJ", "injective-mainnet", False, False),
    "shape": ("Shape", 360, "ETH", "shape-mainnet", True, False),
    "adi": ("ADI Chain", 36900, "ADI", "adi-mainnet", False, False),
    "anime": ("Animechain", 69000, "ANIME", "anime-mainnet", True, False),
    "astar": ("Astar", 592, "ASTR", "astar-mainnet", False, False),
    "boba": ("Boba", 288, "ETH", "boba-mainnet", False, False),
    "citrea": ("Citrea", 4114, "cBTC", "citrea-mainnet", False, False),
    "earnm": ("EARNM", 32766, "EARNM", "earnm-mainnet", False, False),
    "galactica": ("Galactica", 613419, "GNET", "galactica-mainnet", False, False),
    "gensyn": ("Gensyn", 685689, "ETH", "gensyn-mainnet", False, False),
    "humanity": ("Humanity", 6985385, "H", "humanity-mainnet", False, False),
    "mythos": ("Mythos", 42018, "ETH", "mythos-mainnet", True, False),
    "rise": ("RISE", 4153, "ETH", "rise-mainnet", False, False),
    "settlus": ("Settlus", 5371, "ETH", "settlus-mainnet", True, False),
    "superseed": ("Superseed", 5330, "ETH", "superseed-mainnet", False, False),
    "worldmobile": ("World Mobile Chain", 869, "WMTX", "worldmobilechain-mainnet", False, False),
    "zetachain": ("ZetaChain", 7000, "ZETA", "zetachain-mainnet", True, False),
    "pharos": ("Pharos", 1672, "PROS", "pharos-mainnet", False, False),
    "jovay": ("Jovay", 5734951, "ETH", "jovay-mainnet", False, False),
    "tempo": ("Tempo", 4217, "USD", "tempo-mainnet", False, False),
    "xmtp": ("XMTP", 241320162, "USDC", "xmtp-mainnet", False, False),
    "edge": ("Edge", 3343, "ETH", "edge-mainnet", False, False),
    "crossfi": ("CrossFi", 4158, "XFI", "crossfi-mainnet", False, True),
    "alterscope": ("Alterscope", 202209, "RISK", "alterscope-mainnet", False, True),
    "standard": ("Standard", 486, "STND", "standard-mainnet", False, True),
    "polynomial": ("Polynomial", 8008, "ETH", "polynomial-mainnet", False, True),
    "race": ("RACE", 6805, "ETH", "race-mainnet", False, True),
}
for _k, (_nm, _cid, _sym, _net, _tok, _only) in _ALCHEMY_TABLE.items():
    if _k not in CATALOG:
        CATALOG[_k] = {"_table_only": True, "_note": f"{_nm}(chainId {_cid}) — 체인 표 전용(수집 블록 아님)", "chain_id": _cid, "name": _nm,
                       "native": _sym, "alchemy": _net, "alchemy_tokens": _tok}
        if _only:
            CATALOG[_k]["alchemy_only"] = True
TABLE_KEYS = ("_table_only", "name", "native", "alchemy", "alchemy_tokens", "alchemy_only")


AUTO_WINDOW_CALLS = 3000

AUTO_RPS = 20


_RECON_CA = re.compile(r"0x[0-9a-f]{40}")


def recon_tokens_for(cfg: dict, chain: str) -> dict:
    raw = (cfg or {}).get("recon_tokens") if isinstance((cfg or {}).get("recon_tokens"), dict) else {}
    ent = raw.get(chain) if isinstance(raw.get(chain), dict) else {}
    out = {}
    for ca, meta in ent.items():
        ca9 = str(ca).strip().lower()
        if (_RECON_CA.fullmatch(ca9) and isinstance(meta, (list, tuple)) and len(meta) == 2 and isinstance(meta[0], str)
                and 0 < len(meta[0].strip()) <= 20 and type(meta[1]) is int and 0 <= meta[1] <= 36):
            out[ca9] = [meta[0].strip(), meta[1]]
    return out


def block_for(chain: str, since_known: bool, speed: dict = None):
    if is_block(chain):
        b = json.loads(json.dumps(CATALOG[chain]))
        for k9 in TABLE_KEYS:
            b.pop(k9, None)
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


def is_block(chain: str) -> bool:
    ent = CATALOG.get(chain)
    return isinstance(ent, dict) and not ent.get("_table_only")


def blocks() -> dict:
    return {k: v for k, v in CATALOG.items() if is_block(k)}


def alchemy_network(chain: str):
    v = (CATALOG.get(chain) or {}).get("alchemy")
    return v if isinstance(v, str) and v else None


def alchemy_tokens(chain: str) -> bool:
    return bool(alchemy_network(chain)) and (CATALOG.get(chain) or {}).get("alchemy_tokens") is True


def chain_table() -> dict:
    try:
        import common
        d = common.seed_json("coverage/evm_chains.json", {}) or {}
    except (Exception, SystemExit):
        return {}
    ch = d.get("chains") if isinstance(d, dict) else None
    return ch if isinstance(ch, dict) else {}

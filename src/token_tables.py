from __future__ import annotations

__all__ = ["STABLE_CAS", "STABLE_SYMS", "JPY_STABLE_CAS", "STABLE_MINTS", "DS_CHAIN", "MULTICALL3", "MULTICALL3_BY_CHAIN"]

_USDE_OFT = "0x5d3a1ff2b6bab83b63cd9ad0787074081a52ef34"
STABLE_CAS = {
    "eth": {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
        "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
        "0x4c9edd5852cd905f086c759e8383e09bff1e68b3": "USDE",
        "0xcccc62962d17b8914c62d74ffb843d73b2a3cccc": "CUSD",
        "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
        "0xe556aba6fe6036275ec1f87eda296be72c811bce": "NUSD",
    },
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
        "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2": "USDT",
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
    },
    "arbitrum": {
        "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": "USDT",
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831": "USDC",
        "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8": "USDC",
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": "DAI",
    },
    "optimism": {
        "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58": "USDT",
        "0x0b2c639c533813f4aa9d7837caf62653d097ff85": "USDC",
        "0x7f5c764cbc14f9669b88837ca1490cca17c31607": "USDC",
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": "DAI",
    },
    "polygon": {
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC",
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC",
        "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": "DAI",
    },
    "scroll": {
        "0xf55bec9cafdbe8730f096aa55dad6d22d44099df": "USDT",
        "0x06efdbff2a14a7c8e15944d1f4a48f9f95f663a4": "USDC",
    },
    "zksync": {
        "0x493257fd37edb34451f62edf8d2a0c418852ba4c": "USDT",
        "0x1d17cbcf0d6d143135ae902365d2e5e2a16538d4": "USDC",
        "0x3355df6d4c9c3035724fd0e3914de96a5a83aaf4": "USDC",
    },
    "gnosis": {
        "0x4ecaba5870353805a9f068101a40e0f32ed605c6": "USDT",
        "0xddafbb505ad214d7b80b1f830fccc89b60fb7a83": "USDC",
    },
    "bsc": {
        "0x55d398326f99059ff775485246999027b3197955": "USDT",
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "USDC",
        "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3": "DAI",
        "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD",
        "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
    },
    "robinhood": {
        "0x5fc5360d0400a0fd4f2af552add042d716f1d168": "USDG",
    },
}
for _ch in ("base", "arbitrum", "optimism", "scroll", "bsc", "robinhood"):
    STABLE_CAS[_ch][_USDE_OFT] = "USDE"
for _ch, _m in {
    "monad": {"0x754704bc059f8c67012fed69bc8a327a5aafb603": "USDC", "0xe7cd86e13ac4309349f30b3435a9d337750fc82d": "USDT"},
    "plasma": {"0xb8ce59fc3717ada4c02eadf9682a9e934f625ebb": "USDT"},
    "megaeth": {"0xb8ce59fc3717ada4c02eadf9682a9e934f625ebb": "USDT", "0xfafddbb3fc7688494971a79cc65dca3ef82079e7": "USDM"},
    "xlayer": {"0x779ded0c9e1022225f8e0630b35a9b54be713736": "USDT", "0x74b7f16337b8972027f6196a17a631ac6de26d22": "USDC"},
    "kaia": {"0xd077a400968890eacc75cdc901f0356c943e4fdb": "USDT"},
    "bob": {"0xe75d0fb2c24a55ca1e3f96781a2bcc7bdba058f0": "USDC", "0x05d032ac25d322df992303dca074ee7392c117b9": "USDT"},
    "avalanche": {"0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e": "USDC", "0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7": "USDT"},
    "story": {"0xf1815bd50389c46847f0bda824ec8da914045d14": "USDC"},
    "abstract": {"0x84a71ccd554cc1b02749b35d22f684cc8ec987e1": "USDC", "0x0709f39376deee2a2dfc94a58edeb2eb9df012bd": "USDT"},
    "katana": {"0x203a662b0bd271a6ed5a60edfbd04bfce608fd36": "USDC"},
    "tron": {"41a614f803b6fd780986a42c78ec9c7f77e6ded13c": "USDT"},
    "ton": {"0_b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe": "USDT"},
    "sui": {"mv_3078646261333436373265333063623036356231663933653361623535333138373638666436666566363663313539343263396637636238343665326639303065373a3a757364633a3a55534443": "USDC"},
}.items():
    STABLE_CAS.setdefault(_ch, {}).update(_m)
STABLE_SYMS = {"USDT", "USDC", "DAI"}
JPY_STABLE_CAS = {
    "eth": {"0xe7c3d8c9a439fede00d2600032d5db0be71c3c29": "JPYC"},
    "polygon": {"0xe7c3d8c9a439fede00d2600032d5db0be71c3c29": "JPYC"},
}
STABLE_MINTS = {
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH": "USDG",
}

DS_CHAIN = {"eth": "ethereum", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "optimism": "optimism",
            "polygon": "polygon", "sol": "solana", "zksync": "zksync", "scroll": "scroll",
            "monad": "monad", "megaeth": "megaeth", "plasma": "plasma", "xlayer": "xlayer", "kaia": "kaia",
            "fraxtal": "fraxtal", "bob": "bob", "story": "story", "somnia": "somnia", "avalanche": "avalanche",
            "abstract": "abstract",
            "hyperevm": "hyperevm"}

MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
MULTICALL3_BY_CHAIN = {"zksync": "0xf9cda624fbc7e059355ce98a31693d299facd963"}

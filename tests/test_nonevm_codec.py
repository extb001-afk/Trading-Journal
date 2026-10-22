#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _nonevm as N  # noqa: E402

import address_codec as ac  # noqa: E402
import chain_registry as reg  # noqa: E402
import os  # noqa: E402

chk = T.chk


def bad(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        return str(e) or True
    return False


k1 = ac.tron_key("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
chk(k1 == "41a614f803b6fd780986a42c78ec9c7f77e6ded13c", "C1 Base58 → 41-hex 원장 키", k1)
chk(ac.tron_key("41A614F803B6FD780986A42C78EC9C7F77E6DED13C") == k1, "C1 hex 대문자 입력도 같은 키(중복 1개)")
chk(ac.tron_display(k1) == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "C1 표시 = Base58Check 원형(대소문자 보존)")
chk(ac.tron_display("41" + "00" * 20) == "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", "C1 블랙홀 주소 벡터")
chk(bad(ac.tron_key, "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u"), "C1 체크섬 한 글자 오타 거부")
chk(bad(ac.tron_key, "0x" + "a1" * 20), "C1 EVM 0x 주소 거부(다른 이름 공간)")
chk(bad(ac.tron_key, "tr7nhqjekqxgtci8q8zy4pl8otszgjlj6t"), "C1 소문자로 망가진 Base58 거부")
chk(k1 == k1.lower() and ":" not in k1, "C1 원장 키 = 소문자·콜론 없음(lower() 안전)")

s1 = "0x" + "Ab" * 32
chk(ac.sui_key(s1) == s1.lower(), "C2 Sui 주소 소문자 원장 키")
chk(bad(ac.sui_key, "0x" + "ab" * 20), "C2 EVM 길이(40 hex) 거부 — 0 채워 늘리지 않음")
chk(bad(ac.sui_key, "0x" + "ab" * 31), "C2 62 hex 거부")
t1 = ac.sui_type_canonical("0x2::coin::Coin<0x2::sui::SUI>")
chk(t1 == "0x" + "0" * 63 + "2::coin::Coin<0x" + "0" * 63 + "2::sui::SUI>", "C2 제네릭 안 주소까지 정규화 · 이름 대소문자 보존", t1)
chk(ac.sui_asset_key("0x2::sui::SUI") != ac.sui_asset_key("0x2::sui::sui"), "C2 '::SUI' 와 '::sui' 는 다른 자산(합치지 않음)")
ka = ac.sui_asset_key("0xA1::Coin_A::COINA")
chk(ka == ka.lower() and ":" not in ka, "C2 Sui 토큰 키 = 소문자·콜론 없음(core.asset_id lower() 에 안전)", ka)
chk(ac.sui_asset_type(ka) == "0x" + "0" * 62 + "a1::Coin_A::COINA", "C2 토큰 키 → 정규 Move 타입 되돌리기(이름 대소문자 그대로)")
chk(bad(ac.sui_type_canonical, "0x2::sui::SUI<"), "C2 깨진 제네릭 거부")
chk(bad(reg.asset_key, "sui", "token", "0x2::sui::SUI"), "C2 SUI 를 토큰 칸으로 보내면 거부(네이티브 이중 자산 방지)")

EQ = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
RAW = "0:ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e"
kt = ac.ton_key(EQ)
chk(kt == "0_ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e", "C3 friendly(EQ) → 원장 키 '0_…'", kt)
chk(ac.ton_key(RAW) == kt, "C3 raw '0:…' 와 같은 계정")
UQ = ac.ton_friendly(kt, bounceable=False)
chk(UQ == "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA" and ac.ton_key(UQ) == kt, "C3 non-bounceable(UQ)도 같은 지갑(별도 지갑 안 만듦)", UQ)
chk(ac.ton_key(EQ.replace("-", "+")) == kt, "C3 표준 base64 표기도 같은 계정")
chk(bad(ac.ton_key, EQ[:-1] + ("G" if EQ[-1] != "G" else "H")), "C3 CRC16 오타 거부")
tn = ac.ton_friendly(kt, bounceable=True, testnet=True)
chk(bad(ac.ton_key, tn), "C3 테스트넷 전용 플래그 메인넷에서 거부")
chk(":" not in kt and ac.ton_raw(kt) == RAW, "C3 원장 키 콜론 없음 · API 질의용 raw 로 되돌림(콜론 보존)")
chk(reg.parse_location(reg.make_location("ton", kt)) == ("wallet", "ton", kt) and reg.make_location("ton", kt).count(":") == 2,
    "C3 위치 'wallet:ton:<키>' 콜론 2개(기존 '지갑 칸' 판정과 같음)")
chk(bad(reg.make_location, "ton", RAW), "C3 콜론 든 키로 위치 만들기 거부")

b1 = ac.btc_address("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4")
chk(b1["address"] == N.BTC_ADDR and b1["script"] == "0014751e76e8199196d454941c45d1b3a323f1433bd6", "C4 BIP173 벡터 v0 P2WPKH(대문자 → 소문자 정규)", b1)
b2 = ac.btc_address("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0")
chk(b2["type"] == "p2tr" and b2["script"].startswith("5120"), "C4 BIP350 벡터 v1 P2TR(bech32m)", b2)
chk(bad(ac.btc_address, "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqh2y7hd"), "C4 v1 에 bech32(옛 체크섬) 거부(BIP350)")
chk(bad(ac.btc_address, "bc1qW508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"), "C4 대소문자 섞인 bech32 거부")
chk(bad(ac.btc_address, "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"), "C4 테스트넷 주소 메인넷에서 거부")
g = ac.btc_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
chk(g["script"] == "76a91462e907b15cbf27d5425399ebf6f0fb50ebb88f1888ac" and g["address"] == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    "C4 Base58 P2PKH(원형 보존 — lower() 안 함)", g)
chk(ac.btc_address("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")["type"] == "p2sh", "C4 Base58 P2SH")
chk(bad(ac.btc_address, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"), "C4 Base58 체크섬 오타 거부")

xp = ac.btc_xpub(N.BTC_XPUB)
chk(xp["pubkey"] == "0339a36013301597daef41fbe593a02cc513d0b55527ec2df1050e2e8ff49c85c2", "C5 BIP32 벡터 1 xpub 공개 키", xp)
XPRV = "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi"
chk("개인 키" in str(bad(ac.btc_xpub, XPRV)), "C5 xprv 저장 전 거부(개인 키 안내)")
chk("개인 키" in str(bad(ac.btc_descriptor, f"wpkh({XPRV}/<0;1>/*)")), "C5 개인 키 든 디스크립터 거부")
chk(not ac.has_private_material(f"wpkh({N.BTC_XPUB}/<0;1>/*)") and ac.has_private_material("wpkh(" + XPRV + "/0/*)"), "C5 개인 키 판정 = 실제 디코드(xpub 의 우연한 글자열로 거부 안 함)")
chk(ac.desc_checksum("addr(mkmZxiEcEd8ZqjQWVZuC6so5dFMKEFpN2j)") == "02wpgw69", "C5 디스크립터 체크섬 = Bitcoin Core 문서 예시")
d = ac.btc_descriptor(f"wpkh([d34db33f/84h/0h/0h]{N.BTC_XPUB}/<0;1>/*)")
chk(d["branches"] == [0, 1] and d["script_type"] == "p2wpkh" and d["descriptor"].endswith("#" + ac.desc_checksum(d["descriptor"][:-9])),
    "C5 받는·잔돈 갈래 둘 다 · 체크섬 붙임", d)
chk(ac.btc_descriptor(d["descriptor"])["descriptor"] == d["descriptor"], "C5 체크섬 있는 정규형 다시 넣어도 같음")
chk(bad(ac.btc_descriptor, d["descriptor"][:-1] + ("q" if d["descriptor"][-1] != "q" else "p")), "C5 체크섬 틀리면 거부")
chk(bad(ac.btc_descriptor, f"wpkh({N.BTC_XPUB}/0h/*)"), "C5 xpub 뒤 강화 경로 거부")
chk(bad(ac.btc_descriptor, f"wsh(multi(1,{N.BTC_XPUB}/0/*))"), "C5 멀티시그·스크립트 디스크립터 거부(MVP 밖)")
chk(bad(ac.btc_descriptor, f"wpkh({N.BTC_XPUB}/2/*)"), "C5 받는(0)·잔돈(1) 밖 갈래 거부")
chk(ac.btc_mask(d["descriptor"]).count("…") == 1 and N.BTC_XPUB not in ac.btc_mask(d["descriptor"]), "C5 화면 표시 가림(xpub 원문 없음)")
w1, w2 = ac.btc_wallet_id(N.BTC_ADDR), ac.btc_wallet_id(d["descriptor"])
chk(w1 != w2 and w1.startswith("bw") and len(w1) == 34 and w1 == w1.lower(), "C5 BTC 지갑 id(bw+32hex · 소문자)")

chk({c: reg.native_decimals(c) for c in reg.CHAINS} == {"tron": 6, "sui": 9, "ton": 9, "btc": 8}, "C6 네이티브 자릿수(18 아님)")
chk(reg.native_decimals("eth", 18) == 18 and not reg.is_nonevm("eth") and not reg.is_nonevm("sol"), "C6 EVM·Solana 는 레지스트리 밖(기존 경로 그대로)")
chk(reg.tx_url("eth", "0x" + "1" * 64) == "" and reg.tx_url("unknownchain", "abc") == "", "C6 모르는 체인 탐색기 링크 없음(ETH·SOL 로 안 보냄)")
chk(reg.tx_url("btc", "ab" * 32) == "https://mempool.space/tx/" + "ab" * 32, "C6 BTC tx 링크")
chk(reg.address_url("btc", w1) == "", "C6 BTC 지갑 id 는 주소 링크 없음(네트워크 주소 아님)")
chk(reg.tx_url("sui", "Ab<script>") == "", "C6 이상한 해시 = 링크 없음(주입 방지)")
chk(reg.tx_url("ton", "0_" + "ab" * 32 + ".123456.cd" + "ef" * 31) == "https://tonviewer.com/transaction/cd" + "ef" * 31,
    "C6 TON tx 링크 = tx_uid 의 hash 부분만(계정·lt 빼고 · nvint18)")
cfg = {"chain_wallets": [
    {"chain": "tron", "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "label": "t1"},
    {"chain": "tron", "address": "41a614f803b6fd780986a42c78ec9c7f77e6ded13c", "label": "dup"},
    {"chain": "ton", "address": EQ, "label": "n1"},
    {"chain": "btc", "mode": "descriptor", "descriptor": d["descriptor"], "label": "hd"},
    {"chain": "btc", "address": N.BTC_ADDR},
    {"chain": "sui", "address": "0x" + "ab" * 20},
    {"chain": "doge", "address": "x"},
    {"chain": "tron", "network": "testnet", "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}]}
rows, errs = reg.wallets(cfg, with_errors=True)
chk([(r["chain"], r["key"]) for r in rows] == [("tron", k1), ("ton", kt), ("btc", w2), ("btc", w1)], "C6 정규화·Base58/hex 중복 1개", rows)
chk(len(errs) == 3 and all(isinstance(i, int) for i, _w in errs), "C6 틀린 줄 3개(EVM 길이 Sui · 모르는 체인 · 테스트넷) 사유 목록", errs)
chk(rows[2]["display"] != d["descriptor"] and N.BTC_XPUB not in rows[2]["display"], "C6 디스크립터 표시 가림")
chk(reg.owners(cfg, "tron") == {k1} and reg.ownership_version(cfg, "tron") != reg.ownership_version({}, "tron"), "C6 관점 지문")
chk(reg.wallets({}) == [] and reg.wallets({"chain_wallets": "x"}) == [], "C6 칸 없음·형식 깨짐 = 빈 목록(기존 설치 그대로)")
chk(all(reg.available(c) == os.path.isfile(os.path.join(T.SRC, reg.spec(c).module + ".py")) for c in reg.CHAINS),
    "C6 수집기 파일(src/<체인>_watch.py)이 있는 체인만 사용 가능 · 없으면 준비 중(등록·유닛 대기)")
chk(not any(c.provider == "quicknode" for c in reg.CAPABILITIES), "C6 QuickNode 후보 없음(오너 결정)")
chk(not any(c.provider == "ankr" for c in reg.capabilities("btc")), "C6 Ankr BTC Blockbook(Premium) 무료 경로 제외")
chk(any(c.role == "address_history" and "xpub API 아님" in c.note for c in reg.capabilities("btc")), "C6 Esplora = 주소 API(xpub 파생 로컬)")
chk(all(reg.make_location(c, k).count(":") == 2 for c, k in (("tron", k1), ("ton", kt), ("btc", w1), ("sui", "0x" + "ab" * 32))),
    "C6 네 체인 모두 위치 콜론 2개")


class _A(reg.ChainAdapter):
    chain = "tron"


a = _A({})
chk(a.native_decimals == 6 and a.canonical_owner("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t") == k1, "C6 어댑터 공통 정규화")
try:
    a.discover_page(None, None, None)
    chk(False, "C6 미구현 칸 = NotImplementedError")
except NotImplementedError:
    chk(True, "C6 미구현 칸 = NotImplementedError(체인 작업자가 채움)")
T.finish()

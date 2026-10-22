#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import os  # noqa: E402

import address_codec as ac  # noqa: E402
import btc_descriptor as bd  # noqa: E402

def ck(msg, ok, extra=None):
    T.chk(ok, msg, extra)

for msg, want in ((b"", "9c1185a5c5e9fc54612808977ee8f548b2258d31"), (b"a", "0bdc9d2d256b3ee9daae347be6f4dc835a467ffe"),
                  (b"abc", "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc"), (b"message digest", "5d0689ef49d2fae572b881b123a85ffa21595f36"),
                  (b"abcdefghijklmnopqrstuvwxyz", "f71c27109c692c1b56bbdceb5b9d2865b3708dbc"),
                  (b"1234567890" * 8, "9b752e45573d4b39f4dbd3323cab82bf63326bfb"),
                  (b"a" * 1000000, "52783243c1697bdbe16d37f97f68f08325dc1528")):
    ck(f"D1 RIPEMD-160 공식 벡터 ({len(msg)}바이트)", bd.ripemd160(msg).hex() == want, bd.ripemd160(msg).hex())
try:
    hashlib.new("ripemd160", b"")
    has_rmd = True
except (ValueError, TypeError):
    has_rmd = False
if has_rmd:
    bad = [n for n in range(0, 300, 7) for m in [os.urandom(n)] if bd.ripemd160(m) != hashlib.new("ripemd160", m).digest()]
    ck("D1 무작위 입력 = hashlib ripemd160(있을 때만 대조)", not bad, bad)
else:
    ck("D1 hashlib 에 ripemd160 없음(OpenSSL 3) — 순수 구현만으로 공식 벡터 통과", True)

V1 = "xpub6D4BDPcP2GT577Vvch3R8wDkScZWzQzMMUm3PWbmWvVJrZwQY4VUNgqFJPMM3No2dFDFGTsxxpG5uJh7n7epu4trkrX7x7DogT5Uv6fcLW5"
n = bd.XPub.parse(V1)
c2 = n.child_pub(2)
ck("D2 BIP32 벡터1 m/0H/1/2H/2 공개 파생", c2.serialize() ==
   "xpub6FHa3pjLCk84BayeJxFW2SP4XRrFd1JYnxeLeU8EqN3vDfZmbqBqaGJAyiLjTAwm6ZLRQUMv1ZACTj37sR62cfN7fe5JnJ7dh8zL4fiyLHV")
ck("D2 BIP32 벡터1 m/0H/1/2H/2/1000000000 공개 파생", c2.child_pub(1000000000).serialize() ==
   "xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy")

ZPUB84 = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
p84 = bd.plan_from_descriptor(bd.descriptor_from_xpub(ZPUB84))
ck("D3 BIP84 받는 0", p84.derive(0, 0)[1] == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu", p84.derive(0, 0))
ck("D3 BIP84 받는 1", p84.derive(0, 1)[1] == "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g", p84.derive(0, 1))
ck("D3 BIP84 잔돈 0", p84.derive(1, 0)[1] == "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el", p84.derive(1, 0))
ck("D3 BIP84 받는 0 공개 키", p84._branch_node(0).child_pub(0).pub.hex() == "0330d54fd0dd420a6e5f8d3624f5f3482cae350f79d5f0753bf5beef9c2d91af3c")

XPUB86 = "xpub6BgBgsespWvERF3LHQu6CnqdvfEvtMcQjYrcRzx53QJjSxarj2afYWcLteoGVky7D3UKDP9QyrLprQ3VCECoY49yfdDEHGCtMMj92pReUsQ"
p86 = bd.plan_from_descriptor(bd.descriptor_from_xpub(XPUB86, "tr"))
spk, a0 = p86.derive(0, 0)
ck("D4 BIP86 내부 키(받는 0)", p86._branch_node(0).child_pub(0).pub.hex()[2:] == "cc8a4bc64d897bddc5fbc2f670f7a8ba0b386779106cf1223c6fc5d7cd6fc115")
ck("D4 BIP86 출력 키·scriptPubKey(tweak)", spk == "5120a60869f0dbcf1dc659c9cecbaf8050135ea9e8cdc487053f1dc6880949dc684c", spk)
ck("D4 BIP86 받는 0·1 · 잔돈 0 주소", (a0, p86.derive(0, 1)[1], p86.derive(1, 0)[1]) ==
   ("bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr", "bc1p4qhjn9zdvkux4e44uhx8tc55attvtyu358kutcqkudyccelu0was9fqzwh",
    "bc1p3qkhfews2uk44qtvauqyr2ttdsw7svhkl9nkm9s9c3x4ax5h60wqwruhk7"))
ck("D4 공개 키를 그대로 bech32m 로 쓴 주소(틀린 방법)와 다름", bd.bech32_encode("bc", 1, bytes.fromhex(
    "cc8a4bc64d897bddc5fbc2f670f7a8ba0b386779106cf1223c6fc5d7cd6fc115")) != a0)

ck("D5 BIP49 sh(wpkh) 테스트넷 첫 주소", bd.script_and_address(bytes.fromhex(
    "03a1af804ac108a8a51782198c2d034b28bf90c8803f5a53f76276fa69a4eae77f"), "p2sh-p2wpkh", "testnet")[1] == "2Mww8dCYPUpKHofjgcXcBCEGmniw9CoaiD2")
XPUB44 = "xpub6BosfCnifzxcFwrSzQiqu2DBVTshkCXacvNsWGYJVVhhawA7d4R5WSWGFNbi8Aw6ZRc1brxMyWMzG3DSSSSoekkudhUd9yLb6qx39T9nMdj"
p44 = bd.plan_from_descriptor(bd.descriptor_from_xpub(XPUB44, "pkh"))
ck("D5 BIP44 pkh 받는 0", p44.derive(0, 0)[1] == "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA", p44.derive(0, 0))

rt = []
for p in (p84, p86, p44, bd.plan_from_descriptor(bd.descriptor_from_xpub(XPUB44, "sh(wpkh)"))):
    for b in (0, 1):
        for i in (0, 7):
            s9, a9 = p.derive(b, i)
            d9 = ac.btc_address(a9)
            if d9["script"] != s9 or d9["address"] != a9:
                rt.append((a9, s9, d9))
ck("D6 파생 주소 16개 = 코덱 왕복(형식·scriptPubKey)", not rt, rt[:2])

d84 = bd.descriptor_from_xpub(ZPUB84)
ck("D7 zpub → wpkh(xpub…/<0;1>/*)#체크섬(표준 xpub 버전으로)", d84.startswith("wpkh(xpub") and d84.endswith(")#" + ac.desc_checksum(d84.split("#")[0]).strip())
   and "/<0;1>/*" in d84, d84[:12])
ck("D7 코덱이 받아들임(체크섬·문법)", ac.btc_descriptor(d84)["branches"] == [0, 1])
ck("D7 같은 키를 zpub·xpub 로 넣어도 같은 지갑 id", ac.btc_wallet_id(d84) == ac.btc_wallet_id(bd.descriptor_from_xpub(
    bd.XPub.parse(ZPUB84).serialize(bytes.fromhex("0488b21e")), "wpkh")))
ck("D7 ypub → sh(wpkh)", bd.descriptor_from_xpub(bd.XPub.parse(ZPUB84).serialize(bytes.fromhex("049d7cb2"))).startswith("sh(wpkh(xpub"))
e7 = T.safe(bd.descriptor_from_xpub, XPUB44)
ck("D7 xpub 는 주소 형식을 지어내지 않음(형식 필수)", isinstance(e7, dict) and "_exc" in e7, e7)
e7b = T.safe(bd.descriptor_from_xpub, ZPUB84, "pkh")
ck("D7 zpub 에 다른 형식 = 거부", isinstance(e7b, dict) and "_exc" in e7b, e7b)
o7 = bd.descriptor_from_xpub(ZPUB84, origin="73c5da0a/84'/0'/0'")
ck("D7 출처([지문/경로]) 포함 디스크립터도 같은 주소", bd.plan_from_descriptor(o7).derive(0, 0) == p84.derive(0, 0))

body = d84.split("#")[0]
one = body.replace("/<0;1>/*", "/0/*")
p1 = bd.plan_from_descriptor(one)
ck("D8 한 갈래(/0/*) = 받는 갈래만 · 주소 같음", p1.branches == [0] and p1.derive(0, 3) == p84.derive(0, 3), p1.branches)
e8 = T.safe(p1.derive, 1, 0)
ck("D8 한 갈래 디스크립터에서 없는 갈래 파생 = 거부(지어내지 않음)", isinstance(e8, dict) and "_exc" in e8)
deep = body.replace("/<0;1>/*", "/5/<0;1>/*")
pd = bd.plan_from_descriptor(deep)
man = bd.script_and_address(bd.XPub.parse(ZPUB84).child_pub(5).child_pub(1).child_pub(4).pub, "p2wpkh")
ck("D8 앞 경로(/5/<0;1>/*) 파생 = 손 파생", pd.derive(1, 4) == man, (pd.derive(1, 4), man))

XPRV = "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi"
for label, fn, arg in (("xprv 확장 개인 키", bd.XPub.parse, XPRV), ("xprv 든 디스크립터", bd.plan_from_descriptor, f"wpkh({XPRV}/<0;1>/*)"),
                       ("xprv → 디스크립터 만들기", bd.descriptor_from_xpub, XPRV)):
    r9 = T.safe(fn, arg)
    ck(f"D9 {label} = 거부 · 문구에 원문 없음", isinstance(r9, dict) and "_exc" in r9 and XPRV[:20] not in r9["_exc"], r9)
r9 = T.safe(bd.plan_from_descriptor, body.replace("/<0;1>/*", "/1'/<0;1>/*"))
ck("D9 강화 경로(') = 거부", isinstance(r9, dict) and "_exc" in r9, r9)
r9 = T.safe(bd.XPub.parse(ZPUB84).child_pub, 0x80000000)
ck("D9 강화 자식 번호 = 거부", isinstance(r9, dict) and "_exc" in r9, r9)
r9 = T.safe(bd.plan_from_descriptor, body + "#qqqqqqqq")
ck("D9 체크섬 틀림 = 거부", isinstance(r9, dict) and "_exc" in r9, r9)
r9 = T.safe(bd.plan_from_descriptor, f"wsh(multi(1,{ZPUB84}/<0;1>/*))")
ck("D9 지원 밖 디스크립터(멀티시그) = 거부", isinstance(r9, dict) and "_exc" in r9, r9)
T.finish()

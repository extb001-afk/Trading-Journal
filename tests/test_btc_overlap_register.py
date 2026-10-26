#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

CP = os.path.join(T.TMP, "config.json")
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(CP, "w"))
os.environ["TJ_CONFIG"] = CP
import paths  # noqa: E402
import settings_wallets  # noqa: E402
import chain_registry as reg  # noqa: E402
import btc_descriptor as bd  # noqa: E402
import address_codec as ac  # noqa: E402

chk = T.chk
reg.FORCE_AVAILABLE.add("btc")
ZPUB84 = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
D = bd.descriptor_from_xpub(ZPUB84)
P = bd.plan_from_descriptor(D)
HD = ac.btc_wallet_id(D)
W2ADDR = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"


def R(i):
    return P.derive(0, i)[1]


def C(i):
    return P.derive(1, i)[1]


def raw():
    return open(CP).read()


def reset(lst=()):
    json.dump({"chains": {}, "wallets": [], "backfill_months": 5, "chain_wallets": list(lst)}, open(CP, "w"))


def refused(fn, *a, **kw):
    before = raw()
    try:
        fn(*a, **kw)
    except ValueError as e:
        return str(e), raw() == before
    return None, raw() == before


reset()
settings_wallets.add_chain_wallet("btc", R(0), label="단일")
why, same = refused(settings_wallets.add_chain_wallet, "btc", mode="descriptor", descriptor=D, label="hd")
chk(why is not None and same,
    "O1 이미 등록된 단일 주소(HD 수신 0)를 포함하는 HD 추가 = 거절 · config.json 무변", why)
WHY_HD = why
chk(why is None or (ZPUB84 not in why and R(0) not in why), "O1 거절 문구에 xpub·주소 원문 없음(라벨만)", why)

reset()
settings_wallets.add_chain_wallet("btc", mode="descriptor", descriptor=D, label="hd")
for a, nm in ((C(3), "잔돈 3"), (R(19), "수신 19(gap 20 범위 끝)")):
    why, same = refused(settings_wallets.add_chain_wallet, "btc", a)
    chk(why is not None and same, f"O2 등록된 HD 가 포함하는 단일 주소({nm}) 추가 = 거절 · config 무변", why)
    WHY_ADDR = why

sd = paths.STATE_DIR
os.makedirs(sd, exist_ok=True)
cur = os.path.join(sd, reg.spec("btc").cursor_file)
json.dump({"v": 1, "btc": {"wallets": {HD: {"br": {"0": {"used": 30}, "1": {"used": -1}}}}}}, open(cur, "w"))
why, same = refused(settings_wallets.add_chain_wallet, "btc", R(45))
chk(why is not None and same, "O3 수집기가 본 사용 번호 30 + gap 20 안(수신 45) = 거절", why)
os.remove(cur)
reset()
settings_wallets.add_chain_wallet("btc", mode="descriptor", descriptor=D, label="hd")
why, _s = refused(settings_wallets.add_chain_wallet, "btc", R(45))
chk(why is None, "O3 수집 상태 없음 → gap 범위 밖(수신 45) = 허용(수집기 소유 지도도 아직 안 셈)", why)
why, _s = refused(settings_wallets.add_chain_wallet, "btc", W2ADDR)
chk(why is None, "O3 무관한 단일 주소 = 허용", why)
why, _s = refused(settings_wallets.add_chain_wallet, "btc", mode="descriptor", descriptor=f"pkh({XPUB}/<0;1>/*)")
chk(why is None, "O3 무관한 HD 추가 = 허용(겹치는 단일 주소 없음)", why)

reset()
settings_wallets.add_chain_wallet("btc", R(0), label="단일")
import onboarding  # noqa: E402
r = None
try:
    r = onboarding._dispatch("chain_wallets/add", {"chain": "btc", "mode": "descriptor", "descriptor": D, "label": "hd"})
except ValueError as e:
    r = {"ok": False, "error": str(e)}
chk(r.get("ok") is False and r.get("error") == WHY_HD, "O4 설정 화면 API 도 같은 거절", r)
chk(settings_wallets.remove_chain_wallet("btc", R(0)) == 1, "O4 단일 주소 빼기")
a = settings_wallets.add_chain_wallet("btc", mode="descriptor", descriptor=D, label="hd")
chk(a["key"] == HD and HD in {w["key"] for w in reg.wallets(json.loads(raw()))}, "O4 (코드 동작 무변) 뺀 뒤 HD 추가 자체는 됨", a)

for nm, why in (("HD 추가", WHY_HD), ("단일 주소 추가", WHY_ADDR)):
    w = why or ""
    chk("먼저" not in w and "빼고" not in w and "다시 추가" not in w and "다시 받" not in w,
        f"O5 {nm} 거절 문구에 '먼저 빼고 다시 추가' 류 이전 안내 없음", why)
    chk("지원하지 않" in w and "처음부터" in w and "삭제·재등록" in w,
        f"O5 {nm} 거절 문구 = 주소↔HD 이전 미지원 · 처음부터 하나로만 · 같은 지갑 삭제·재등록은 가능", why)
    chk(ZPUB84 not in w and D not in w and all(x not in w for x in (R(0), R(19), C(3))), f"O5 {nm} 문구에 xpub·주소 원문 없음", why)

reset()
settings_wallets.add_chain_wallet("btc", R(0), label="단일")
chk(settings_wallets.remove_chain_wallet("btc", R(0)) == 1, "O6 같은 단일 주소 빼기")
why, _s = refused(settings_wallets.add_chain_wallet, "btc", R(0), label="단일")
chk(why is None and len([w for w in reg.wallets(json.loads(raw())) if w["chain"] == "btc"]) == 1, "O6 같은 단일 주소 재등록 = 허용", why)
reset()
settings_wallets.add_chain_wallet("btc", mode="descriptor", descriptor=D, label="hd")
chk(settings_wallets.remove_chain_wallet("btc", HD) == 1, "O6 같은 HD 빼기")
why, _s = refused(settings_wallets.add_chain_wallet, "btc", mode="descriptor", descriptor=D, label="hd")
chk(why is None and [w["key"] for w in reg.wallets(json.loads(raw())) if w["chain"] == "btc"] == [HD], "O6 같은 HD 재등록 = 허용", why)
reg.FORCE_AVAILABLE.clear()
T.finish()

#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest

import io
import json
import os
import re
import urllib.error

import common

chk = T.chk
DOCS = os.path.dirname(T.README)

import cgkey

READS = []


class _Fp(io.BytesIO):
    def read(self, n=-1):
        READS.append(n)
        return super().read(n)


big = b'{"status":{"error_message":"rate limited"}}' + b" " * (200 * 1024)
e9 = urllib.error.HTTPError("https://api.coingecko.invalid/x", 429, "Too Many", {"Retry-After": "7"}, _Fp(big))
code9, kind9, body9, ra9 = cgkey._err_info(e9)
chk(READS and all(isinstance(n, int) and 0 <= n <= common.HTTP_ERR_BODY_MAX for n in READS),
    "R1 코인게코 키 오류 본문 = 64KiB 까지만 읽음(끝까지 읽지 않음)", READS)
chk(code9 == 429 and kind9 == "http429" and "rate limited" in body9 and ra9 == "7", "R1b 오류 판정 그대로(코드·종류·본문 앞부분·Retry-After)",
    [code9, kind9, body9[:60], ra9])
pat = re.compile(r"\b(?:r|r9|e|resp)\.read\(\)")
left = []
for m in ("cgkey", "pricing", "sol_watch"):
    with open(os.path.join(T.SRC, m + ".py"), encoding="utf-8") as f:
        left += [f"{m}.py:{i}" for i, line in enumerate(f, 1) if pat.search(line)]
chk(not left, "R2 cgkey·pricing·sol_watch 에 끝까지 읽기 0", left)

import health
import settings_store

for k in ("UPBIT_ACCESS", "UPBIT_SECRET"):
    os.environ.pop(k, None)
ENVP = common.ENV_PATH


def _env(txt):
    if txt is None:
        if os.path.exists(ENVP):
            os.remove(ENVP)
        return
    with open(ENVP, "w", encoding="utf-8") as f:
        f.write(txt)


bad_dir = os.path.join(T.TMP, "env_is_dir")
os.makedirs(bad_dir, exist_ok=True)
_old_ep = settings_store.ENV_PATH
settings_store.ENV_PATH = bad_dir
try:
    u1 = health.upbit_connected()
finally:
    settings_store.ENV_PATH = _old_ep
chk(u1 is True, "U1 .env 못 읽음 = 모름 → 있음(종전 경고 유지 · 키 지움으로 오인 안 함)", u1)
_env(None)
chk(health.upbit_connected() is False, "U2 .env 없음 = 키 없음")
_env("UPBIT_ACCESS=\nUPBIT_SECRET=\n")
chk(health.upbit_connected() is False, "U3 키 칸 비움 = 없음")
_env("UPBIT_ACCESS=" + "a" * 20 + "\nUPBIT_SECRET=" + "s" * 20 + "\n")
chk(health.upbit_connected() is True, "U4 키 있음 = 있음")
_env(None)

import core

core.dm = lambda *a, **k: None
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"chains": {"eth": {"blockscout": "https://eth.example.invalid", "conf_depth": 12, "blocks_per_day": 7200}},
               "wallets": [], "backfill_months": 1}, f)
MARK = os.path.join(common.STATE_DIR, "backfill_done")
c = core.Core(common.load_config())
c.conn.commit()


def mrun(env_txt, metas):
    _env(env_txt)
    if os.path.exists(MARK):
        os.remove(MARK)
    c.conn.execute("DELETE FROM meta WHERE k LIKE 'recon_done_%'")
    for k9 in metas:
        c.conn.execute("INSERT INTO meta (k, v) VALUES (?, '1700000000')", (k9,))
    c.conn.commit()
    c._recon_pass_scopes(set(), False, {})
    return os.path.exists(MARK)


UPK = "UPBIT_ACCESS=synthetic-access\nUPBIT_SECRET=synthetic-secret\n"
BNK = "TJ_BINANCE_KEY=synthetic-k\nTJ_BINANCE_SECRET=synthetic-s\n"
chk(mrun(UPK, ["recon_done_upbit"]), "M1 지갑 0개 + 업비트 첫 대사 끝 → 백필 완료 표식 생성")
mt9 = open(MARK, encoding="utf-8").read().strip() if os.path.exists(MARK) else ""
chk(re.fullmatch(r"\d+\.\d+", mt9) is not None and abs(float(mt9) - __import__("time").time()) < 600,
    "M5 표식 내용 = 만든 시각 소수 초(web 이 같은 초 안 '표식 전 스냅숏'도 가름 · 코덱스 mo512 RECORD)", mt9)
chk(not mrun(UPK, []), "M2 지갑 0개 + 업비트 첫 대사 전 → 표식 없음")
chk(not mrun(BNK, []), "M3a 지갑 0개 + 바이낸스 키 · 첫 대사 전 → 표식 없음(해외 거래소 첫 동기화 중 동결 금지)")
chk(mrun(BNK, ["recon_done_exf_binance"]), "M3b 지갑 0개 + 바이낸스 첫 대사 끝 → 표식 생성")
chk(not mrun(UPK + BNK, ["recon_done_upbit"]), "M3c 업비트 끝 · 바이낸스 첫 대사 전 → 표식 없음")
chk(not mrun("TJ_ETHERSCAN_KEY=\n", []), "M4 지갑 0개 + 거래소 없음 → 표식 없음")
_env(None)

ex = json.load(open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8"))
chk(ex.get("wallets") == [] and ex.get("exchange_addresses") == [], "E1 예시 설정 = 지갑·거래소 입금 주소 비움(자리표시 없음)",
    [len(ex.get("wallets") or []), len(ex.get("exchange_addresses") or [])])
evm_src = open(os.path.join(T.SRC, "evm_watch.py"), encoding="utf-8").read()
chk("int(self.backfill_months), since, safe" not in evm_src, "E2 이더스캔 백필 시작 로그 = 개월 수 소수 그대로(0.5개월 ≠ '0개월')")

RD = open(T.README, encoding="utf-8").read()
AK = open(os.path.join(DOCS, "docs", "API_KEYS.md"), encoding="utf-8").read()
EX9 = open(os.path.join(DOCS, ".env.example"), encoding="utf-8").read()
SJ = open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8").read() if os.path.exists(os.path.join(T.ROOT, "web", "v2", "setup.js")) else ""
chk("pill('w', 'EVM 필수')" in SJ or not SJ, "D0 (전제) 화면 = 이더스캔 'EVM 필수' 배지")
chk(re.search(r"`TJ_ETHERSCAN_KEY` \| EVM 지갑이 있으면 \*\*필수\*\*", RD) is not None, "D1 README 키 표 이더스캔 = EVM 지갑이 있으면 필수(화면과 같게)")
chk(re.search(r"\| 3 \| 키 준비 — [^|]*EVM 지갑이 있으면 [^|]*Etherscan[^|]*필수", RD) is not None, "D2 README 시작 표 3단계 = 이더스캔도 EVM 필수 키")
chk(re.search(r"\| `TJ_ETHERSCAN_KEY` \| EVM 지갑이 있으면 \*\*필수\*\*", AK) is not None and "## Etherscan — `TJ_ETHERSCAN_KEY` (EVM 지갑이 있으면 필수" in AK,
    "D3 API_KEYS 이더스캔 = EVM 필수(표·절 제목)")
chk(re.search(r"#[^\n]*EVM 지갑이 있으면 필수[^\n]*\n(?:#[^\n]*\n)*TJ_ETHERSCAN_KEY=", EX9) is not None, "D4 .env.example 이더스캔 = EVM 필수")
chk("Etherscan, CoinGecko" not in RD and "All keys are optional except `TJ_HELIUS_KEY` when you track a Solana wallet and `TJ_ALCHEMY_KEY` when" not in AK,
    "D5 영어 안내 = 이더스캔·Ankr 도 EVM 필수(선택 목록에 없음)")
import chainsweep

n_sweep = len(chainsweep.SWEEP_CHAINS)
note = str((ex.get("chain_sweep") or {}).get("_note") or "")
m9 = re.search(r"× (\d+)체인", note)
chk(m9 is not None and int(m9.group(1)) == n_sweep, "D6 예시 설정 미추적 체인 점검 체인 수 = 코드 표(chainsweep.SWEEP_CHAINS)", [m9 and m9.group(1), n_sweep])
bnote = str(((ex.get("chains") or {}).get("base") or {}).get("_note") or "")
chk(common.chain_discovery("base", (ex.get("chains") or {}).get("base") or {}) == "rpc" and "RPC" in bnote,
    "D7 예시 Base = RPC 전용(안내에 적힘 · 블록스카웃 주소는 보조)", bnote[:80])
chk("blockscout 로 동작" not in SJ, "D8 설정 요약 줄 이더스캔 없음 = 'blockscout 로 동작' 아님(새 설치본은 블록스카웃 첫 경로 금지)")
chk("공개 탐색기로만 받아" not in SJ, "D9 이더스캔 키 경고 = '공개 탐색기로만' 아님(키 없는 새 설치본 = 공개 노드)")
chk("맥의 인터넷" not in open(os.path.join(T.SRC, "health.py"), encoding="utf-8").read(), "H1 네트워크 끊김 안내 = '이 컴퓨터'(리눅스 설치본도)")
chk("Helius·Etherscan 키와 노드 키" in AK and "never in URLs" not in AK, "D10 API_KEYS 키 전송 안내 = 구현대로(Helius·Etherscan·노드 키 = 요청 주소 · 코덱스 mo510 RECORD)")
m9 = re.search(r"- \*\*알려진 한계\(이번 판\)\*\*[^\n]*\n((?:  - [^\n]*\n)+)", RD)
chk(m9 is not None and len(m9.group(1).strip().splitlines()) >= 6 and "**Known limitations (this release):**" in RD,
    "L1 README 알려진 한계(이번 판) 6줄 이상 · 영어 절도", m9 and len(m9.group(1).strip().splitlines()))

import time

import nodekeys
import onboarding

with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": [], "sol": {"rpc": "helius"}}, f)
onboarding._save_probe = lambda g, v: ("ok", "")
TODAY = time.strftime("%Y-%m-%d", time.gmtime())


def hplan():
    return (settings_store.read_settings().get(nodekeys.PLANS_KEY) or {}).get("helius") or {}


st0 = onboarding.status()
hf0 = st0.get("heliusFresh") or {}
chk(hf0.get("burst") is True and hf0.get("since") is None, "K1 상태 = 헬리우스 버스트(무료 기본) · 표시 없음", hf0)
onboarding._dispatch("keys/nodeplan", {"provider": "ankr", "plan": "free", "share": 10, "month": None, "fresh": True})
r = onboarding._dispatch("keys/nodeplan", {"provider": "helius", "fresh": True})
chk(r.get("ok") and hplan().get("fresh_since") == TODAY and (r.get("heliusFresh") or {}).get("since") == TODAY and (r.get("apply") or {}).get("restart") is False,
    "K2 헬리우스 '새로 받은 키' 켜기 = node_plans.helius.fresh_since 오늘 · 재시작 없음", [r, hplan()])
chk(nodekeys.fresh_day("helius") == nodekeys.fresh_day_num(TODAY), "K3 장부가 읽는 값(nodekeys.fresh_day helius) = 오늘", nodekeys.fresh_day("helius"))
chk(nodekeys.plans()["ankr"].get("fresh_since") == TODAY, "K4 다른 서비스 요금제 칸 그대로", nodekeys.plans()["ankr"])
r = onboarding._dispatch("keys/save", {"group": "helius", "values": {"TJ_HELIUS_KEY": "TESTheliuskey00000000000000001"}})
chk(r.get("ok") and "fresh_since" not in hplan(), "K5 다른(새) 키로 저장 = 표시 지움(노드 키와 같은 규칙)", [r, hplan()])
onboarding._dispatch("keys/nodeplan", {"provider": "helius", "fresh": True})
r = onboarding._dispatch("keys/save", {"group": "helius", "values": {"TJ_HELIUS_KEY": "TESTheliuskey00000000000000001"}})
chk(r.get("ok") and hplan().get("fresh_since") == TODAY, "K6 같은 키 다시 저장 = 표시 유지", hplan())
r = onboarding._dispatch("keys/nodeplan", {"provider": "helius", "fresh": False})
chk(r.get("ok") and "fresh_since" not in hplan(), "K7 끄기 = 지움", hplan())
r1 = onboarding._dispatch("keys/nodeplan", {"provider": "helius", "fresh": "yes"})
r2 = onboarding._dispatch("keys/nodeplan", {"provider": "helius", "plan": "paid", "share": 10})
chk(r1.get("ok") is False and r2.get("ok") is False, "K8 헬리우스 = '새로 받은 키' 켜기·끄기만(이상한 값·요금제 칸 거부)", [r1, r2])
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": [], "sol": {"rpc": "helius", "helius_burst": False}}, f)
chk((onboarding.status().get("heliusFresh") or {}).get("burst") is False, "K9 버스트 끔(sol.helius_burst false) = 칩 안 보임 표식")
chk("data-p=\"helius\"" in SJ and "heliusFresh" in SJ and "새로 받은 키(지난 사용 없음)" in SJ, "K10 설정 화면 헬리우스 카드에 같은 칩(data-su=nfresh · data-p=helius)")
T.finish()

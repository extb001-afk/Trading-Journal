#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import address_codec as ac  # noqa: E402
import chain_event as ce  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402

chk = T.chk
A, B = N.OWN["tron"]
X = N.EXT["tron"]
TOK = ("token", N.TOK["tron"], "TKA", 6)
NOW = 1_760_000_000


def err(fn, *a):
    try:
        fn(*a)
    except ce.ContractError as e:
        return str(e)
    return ""


r = N.rec("tron", "ab" * 32, NOW, [(A, "native", -1_001_000), (A, TOK, -5_000_000)], fees=[(A, 1_000)],
          moves=[("native", A, X, 1_000_000), (TOK, A, X, 5_000_000)])
c = ce.to_core(r)
nat = ("native", None)
tk = ("token", N.TOK["tron"])
chk(c["econ"] == {(A, nat): -1_000_000, (A, tk): -5_000_000} and c["fee"] == {A: 1_000}, "E1 경제 변화 = 순변화 + 내 수수료", c)
r2 = N.rec("tron", "ac" * 32, NOW, [(A, TOK, 7)], fees=[("external", 3_000)], owners=[A])
chk(ce.to_core(r2)["fee"] == {} and ce.to_core(r2)["econ"] == {(A, tk): 7}, "E1 스폰서(external) 수수료 = 내 비용 아님")
r3 = N.rec("sui", "Dg1", NOW, [(N.OWN["sui"][0], "native", 5)], fees=[(N.OWN["sui"][0], -5)])
c3 = ce.to_core(r3)
chk(c3["fee"] == {N.OWN["sui"][0]: -5} and c3["econ"] == {}, "E1 Sui storage 환급(수수료 −5) — 경제 변화 0 · 부호 보존", c3)

rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)])
rb["deltas"][0]["delta_base"] = "-1.0"
chk("정수" in err(ce.validate, rb), "E2 float 수량 거부")
rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)])
rb["ts"] = 0
chk("시각" in err(ce.validate, rb), "E2 시각 없음 거부")
rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)])
rb["finality"]["state"] = "pending"
chk("확정" in err(ce.validate, rb), "E2 미확정 거부(대기 큐에 둘 것)")
rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)])
rb["completeness"]["details"] = False
chk("상세" in err(ce.validate, rb), "E2 상세 미완 거부")
rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)], owners=[ac.tron_display(A)])
chk("원장 키" in err(ce.validate, rb), "E2 Base58 표시형 owner 거부(원장 키로 정규화해 보낼 것)")
rb = N.rec("tron", "ad" * 32, NOW, [(B, "native", -1)], owners=[A])
chk("owners" in err(ce.validate, rb), "E2 owners 밖 지갑 줄 거부")
rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1), (A, "native", -2)])
chk("두 번" in err(ce.validate, rb), "E2 같은 (지갑, 자산) 두 줄 거부")
rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)])
rb["deltas"][0]["asset"]["decimals"] = 18
chk("자릿수" in err(ce.validate, rb), "E2 네이티브 자릿수 18 지어내기 거부(TRX = 6)")
rb = N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)])
rb["v"] = 2
chk("버전" in err(ce.validate, rb), "E2 모르는 계약 버전 거부")
rb = N.rec("sui", "Dg2", NOW, [(N.OWN["sui"][0], ("token", "0x2::sui::SUI", "SUI", 9), 1)])
chk("네이티브" in err(ce.validate, rb), "E2 SUI 를 토큰 칸으로 거부")
chk("레지스트리" in err(ce.validate, dict(N.rec("tron", "ad" * 32, NOW, [(A, "native", -1)]), chain="eth")), "E2 레지스트리 밖 체인 거부")

r4 = N.rec("ton", "0_" + "31" * 32 + ".1.aa", NOW, [(N.OWN["ton"][0], ("token", N.TOK["ton"], "J0", 0), 3),
                                                     (N.OWN["ton"][0], ("token", "0:" + "a2" * 32, None, None), 9)])
c4 = ce.to_core(r4)
chk(c4["meta"][("token", "0_" + "a1" * 32)]["decimals"] == 0 and c4["meta"][("token", "0_" + "a2" * 32)]["decimals"] is None,
    "E3 decimals 0 유효 · 모름(None) 그대로(18 로 확정 안 함)", c4["meta"])

o1 = N.rec("tron", "ae" * 32, NOW, [(A, "native", -10)], fees=[(A, 1)], owners=[A])
o2 = N.rec("tron", "ae" * 32, NOW, [(A, "native", -10), (B, "native", 9)], fees=[(A, 1)], owners=[A, B])
chk(ce.merge_ok(o1, json.loads(json.dumps(o1))) == "same", "E4 같은 레코드 = same(멱등)")
chk(ce.merge_ok(o1, o2) == "grow" and ce.merge_ok(o2, o1) == "same", "E4 새 관점(나중 등록 지갑) = grow · 줄어든 재방출 = same(무시)")
o3 = N.rec("tron", "ae" * 32, NOW, [(A, "native", -11)], fees=[(A, 1)], owners=[A])
chk(ce.merge_ok(o1, o3) == "conflict", "E4 엇갈린 수량 = conflict(격리)")
chk(ce.merge_ok(o1, N.rec("tron", "ae" * 32, NOW, [(A, "native", -10)], fees=[(A, 1)], owners=[A], failed=True)) == "conflict",
    "E4 실패 여부 다름 = conflict")

r5 = N.rec("tron", "af" * 32, NOW, [(A, "native", -300), (B, "native", 100)], owners=[A, B],
           moves=[("native", ac.tron_display(A), ac.tron_display(X), 150), ("native", A, "41" + "98" * 20, 50), ("native", A, B, 100),
                  ("native", A, "garbage!", "x")])
c5 = ce.to_core(r5)
chk(c5["dest"] == {(A, nat): X} and set(c5["cps"]) == {X, "41" + "98" * 20}, "E5 최대 수령자 · Base58/hex 같은 주소 합침 · 깨진 줄 무시", c5)

ow = {A, B}
good = {"per_wallet": {A: {("native", None): 5, ("token", N.TOK["tron"]): 7}, B: {("native", None): 0}},
        "_boundary": {"kind": "height", "value": "100", "hash": None}, "_complete": True, "_ownership_version": "v1", "_source": "t"}
chk(ce.validate_balances(good, "tron", ow, "v1")["ok"], "E6 완전·경계·관점 같음 = ok")
for k, v, what in (("_complete", False, "부분 결과"), ("_boundary", None, "경계 없음"), ("_ownership_version", "v2", "관점 바뀜")):
    chk(not ce.validate_balances(dict(good, **{k: v}), "tron", ow, "v1")["ok"], f"E6 {what} = 보류")
chk(not ce.validate_balances(dict(good, per_wallet={A: good["per_wallet"][A]}), "tron", ow, "v1")["ok"], "E6 지갑 빠짐 = 보류(0 아님)")
u = ce.validate_balances(dict(good, _unobserved={A: [N.TOK["tron"]]}), "tron", ow, "v1")["usable"]
chk(("token", N.TOK["tron"]) not in u[A] and u[A][("native", None)] == 5, "E6 관측 못 한 칸 제외")
chk(not ce.validate_balances(dict(good, per_wallet={A: {("native", None): -1}, B: {}}), "tron", ow, "v1")["ok"], "E6 음수 잔고 = 형식 오류")

sd = os.path.join(T.TMP, "state")
st = cs.ChainState("tron", sd)
st.pending_upsert([("t1", {"owner": A, "lane": "history"}), ("t2", {"owner": A, "lane": "latest"})])
st.save()
st.save_cursor("history", "c1", "fpA", upper=999)
st2 = cs.ChainState("tron", sd)
chk(st2.lane("history")["cursor"] == "c1" and set(st2.d["pending"]) == {"t1", "t2"}, "S1 재시작 뒤 커서·대기열 그대로")
try:
    st2.save_cursor("history", "c9", "fpB")
    chk(False, "S1 질의 지문 바뀌면 커서 전진 거부")
except ValueError:
    chk(True, "S1 질의 지문 바뀌면 커서 전진 거부")
st2.mark_safe("history", 500)
st2.reset_lane("history", "제공자 교체")
chk(st2.lane("history")["cursor"] is None and st2.lane("history")["safe"] == 500, "S1 reset_lane = 불투명 커서 버림 · 안전 경계 유지")
st2.save_cursor("history", "n1", "fpB")
chk(st2.lane("history")["fp"] == "fpB" and st2.lane("history")["safe"] == 500, "S1 새 지문으로 다시 시작")

chk(st2.pending_upsert([("t1", {"owner": A})]) == 0, "S2 같은 후보 다시 = 멱등")
chk([x[0] for x in st2.due(lane="latest")] == ["t2"], "S2 최신 lane 몫 따로 꺼냄(과거 백필이 안 막음)")
st2.mark_emitted("t2", "uid2", owners=[A])
st2.save()
chk(st2.pending_upsert([("uid2", {"owner": A})]) == 0 and st2.emitted("uid2"), "S2 방출한 id 를 같은 관점이 재발견 = 무시")
chk(st2.pending_upsert([("uid2", {"owner": B})]) == 1, "S2 나중 등록 지갑(B)이 같은 거래 발견 = 다시 상세(넓은 관점 재방출 → core grow)")
st2.d["pending"].pop("uid2", None)
chk(json.load(open(os.path.join(sd, "emitted_tron.json")))["uids"].get("uid2"), "S2 emitted_<chain>.json 기록(원장 복원 근거)")
chk(st2.reschedule("t1", "receipt 지연", now=NOW) == "retry" and st2.d["pending"]["t1"]["next"] == NOW + cs.BACKOFF_MIN, "S2 재시도 백오프")
res = [st2.reschedule("t1", "receipt 지연", now=NOW) for _i in range(cs.MAX_TRIES)]
chk(res[cs.MAX_TRIES - 2] == "gap" and res[-1] == "gone" and "t1" not in st2.d["pending"] and st2.d["gaps"][-1]["id"] == "t1", "S2 상한 넘으면 gap(조용히 안 버림)")
chk(cs.ChainState("tron", sd).d["gaps"][-1]["why"] == "receipt 지연", "S2 gap 내구 기록")

st3 = cs.ChainState("sui", sd)
a1, a2 = N.OWN["sui"]
st3.set_status(a1, requested_from=100, available_from=200, details_complete_through=300)
st3.set_status(a2, requested_from=100, available_from=100, details_complete_through=300)
st3.pending_upsert([("p1", {"owner": a2})])
v = st3.status_view()
chk(v[a1]["coverage"] == "partial" and not v[a1]["complete"], "S3 조회 가능 시작일이 늦음 = partial(완료 아님)")
chk(v[a2]["pending"] == 1 and not v[a2]["complete"], "S3 대기 남으면 완료 아님")
try:
    st3.set_status(a1, done=True)
    chk(False, "S3 모르는 상태 칸 거부")
except ValueError:
    chk(True, "S3 모르는 상태 칸 거부")
chk(st3.drop_owner({a1}) == 1 and a2 not in st3.d["status"], "S3 빠진 지갑 대기·상태만 정리")
chk(reg.spec("sui").cursor_file == "cursor_sui.json" and reg.spec("sui").emitted_file == "emitted_sui.json", "S3 상태 파일 이름 규약")
T.finish()

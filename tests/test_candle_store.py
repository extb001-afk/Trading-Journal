#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import gzip  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import contextlib  # noqa: E402

json.dump({"wallets": [], "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402
import statefile  # noqa: E402
import candles  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
DAY = 86400
D0 = (int(time.time()) // DAY - 30) * DAY


def canon(o):
    return json.dumps(o, sort_keys=True)


cp1 = candles._cpath("bybit", "TKJUSDT", "1h", D0, D0 + 3 * 3600)
rows1 = [[D0 + i * 3600, 1.2345678901234567, 1.3, 1.1, 1.25, 100.5] for i in range(3)]
statefile.atomic_write_json(cp1, {"key": ["bybit", "TKJUSDT", "1h", D0, D0 + 3 * 3600], "candles": rows1, "why": None, "note": None,
                                  "at": int(time.time()), "complete": candles.CACHE_V})
r1 = candles.fetch_cex("bybit", "TKJ", "USDT", "1h", D0, D0 + 3 * 3600)
chk(r1.cached and canon(r1.candles) == canon(rows1) and not T.NET_TRIES, "C1 옛 평문 .json 봉 캐시 = 그대로 읽힘(바깥 호출 0)",
    (r1.cached, r1.why, T.NET_TRIES[:2]))

cp2 = candles._cpath("upbit", "KRW-TKJ", "1h", D0, D0 + 4 * 3600)
short = [[D0, 100.5, 101.25, 99.75, 100.0, 12.5], [D0 + 3600, 123456.0, 1234567891, 123455.0, 123457.0, 0],
         [D0 + 7200, 0.000123457, 0.0001234, 0.0001233, 0.00012345, 7]]
long_ = [[D0 + 10800, 1.2345678901234567, 2.718281828459045, 0.3333333333333333, 3.141592653589793, 123456.78901234567]]
candles._cache_store(cp2, ["upbit", "KRW-TKJ", "1h", D0, D0 + 4 * 3600], short + long_, None, None, True, time.time())
raw2 = open(cp2, "rb").read()
got2 = candles._cache_get(cp2)
ok_short = canon(got2["candles"][:3]) == canon(short)
mx = 0.0
for a, b in zip(long_[0][1:], got2["candles"][3][1:]):
    mx = max(mx, abs(a - b) / abs(a))
chk(raw2[:2] == b"\x1f\x8b" and cp2.endswith(".json") and got2["complete"] == candles.CACHE_V and ok_short,
    "C2a 새로 쓰는 봉 파일 = gzip(같은 이름) · 6자리 이하 값 = 비트까지 같음(정수·짧은 값 그대로)", (raw2[:2], got2["candles"][:3]))
chk(0 < mx <= 5e-6 and got2["candles"][3][0] == long_[0][0] and type(got2["candles"][1][2]) is int,
    "C2b 긴 소수 = 유효숫자 6자리(상대 오차 ≤ 5e-6) · t·정수 종류 그대로", mx)
r2 = candles.fetch_cex("upbit", "TKJ", "KRW", "1h", D0, D0 + 4 * 3600)
chk(r2.cached and len(r2.candles) == 4 and not T.NET_TRIES, "C2c 새 형식 캐시 = 지난 구간 적중(바깥 호출 0)", (r2.cached, r2.why))

pts = [[D0 + i * 3600, 0.12345678901234568 + i, 0.12345678901234568 + i, 0.12345678901234568 + i, 0.12345678901234568 + i, 0] for i in range(5)]
mixed = [[D0 + 99, 1, 1.0, 1, 1, 0], [D0 + 98, 0.0, -0.0, 0.0, 0.0, 0.0], [D0 + 97, 2.5, 2.5, 2.5, 2.5, 0.0]]
rec3 = {"key": ["cg", "id", "tkj", D0, D0 + DAY], "candles": pts + mixed, "why": None, "note": None, "at": 1, "complete": candles.CACHE_V}
pk3 = json.loads(gzip.decompress(candles.bars_encode(rec3)))
lens = [len(r) for r in pk3["cz"]]
back3 = candles._bars_unpack(pk3)["candles"]
exp3 = [[r[0]] + [candles._sig(x, candles.BAR_SIG) for x in r[1:]] for r in pts + mixed]
chk(lens == [3] * 5 + [6, 6, 3] and canon(back3) == canon(exp3) and "candles" not in pk3,
    "C3 o=h=l=c 행 = [t,p,v] 저장 · 읽으면 같은 6칸 · 1/1.0 · -0.0 섞인 행 = 압축 안 함(종류 보존)", {"lens": lens})
chk(list(candles._bars_unpack(pk3).keys()) == list(rec3.keys()), "C3b 칸 차례 그대로(되돌리기 = 옛 바이트)", list(candles._bars_unpack(pk3).keys()))

bad = {"trunc": raw2[: len(raw2) // 2], "magic": b"\x1f\x8b\x00\x01", "rows": gzip.compress(b'{"cz":[1,2],"complete":2}'),
       "json": b'{"candles": [[1,2', "empty": b"", "dictrow": gzip.compress(b'{"cz":[{"a":1,"b":2,"c":3}],"complete":2}'),
       "strrow": gzip.compress(b'{"cz":["abc"],"complete":2}'), "len4": gzip.compress(b'{"cz":[[1,2,3,4]],"complete":2}')}
res4 = {}
for k, v in bad.items():
    p4 = os.path.join(candles.CACHE_DIR, "upbit", "bad_" + k + ".json")
    with open(p4, "wb") as f:
        f.write(v)
    g4 = candles._cache_get(p4)
    res4[k] = (g4, candles._cache_ok(g4, time.time()))
chk(all(v == (None, False) for v in res4.values()), "C4 손상 파일(행 꼴 이상 = dict·글자·4칸 포함) = 없음 처리(None · 캐시 아님 · 예외 없음)", res4)
ix4 = os.path.join(candles.CACHE_DIR, "dex")
os.makedirs(ix4, exist_ok=True)
with open(os.path.join(ix4, "bad_dictrow.json"), "wb") as f:
    f.write(bad["dictrow"])
candles._cache_store(os.path.join(ix4, "good.json"), ["dex", "base", "0xp", "0xt", "5m", D0, D0 + 600], short, None, None, True, time.time())
idx4 = candles._dex_index(time.time())
chk(len(idx4) == 1, "C4b DEX 색인 = 손상 파일 하나가 색인 전체를 깨지 않음", len(idx4))
os.remove(os.path.join(ix4, "bad_dictrow.json"))
os.remove(os.path.join(ix4, "good.json"))

rec5 = {"key": ["dex", "base", "0xp", "0xt", "5m", D0, D0 + 600], "candles": long_ + pts, "why": None, "note": None, "at": 1, "complete": 2}
b5 = candles._bars_unpack(json.loads(gzip.decompress(candles.bars_encode(rec5, sig=None))))
candles.neg_put("upbit:KRW-NOPE", "no_market")
raw5 = open(os.path.join(candles.CACHE_DIR, "neg.json"), "rb").read()
chk(canon(b5) == canon(rec5) and raw5[:1] == b"{", "C5 무손실(sig=None) = 비트까지 같음 · 맨 위 neg.json = 평문 그대로", raw5[:20])

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import candles_compact as CC  # noqa: E402

CD6 = os.path.join(T.TMP, "c6", "candles")
os.makedirs(os.path.join(CD6, "cg"))
os.makedirs(os.path.join(CD6, "binance"))
olds = {}
for i in range(4):
    p6 = os.path.join(CD6, "cg" if i % 2 else "binance", f"f{i}.json")
    statefile.atomic_write_json(p6, dict(rec3, key=["cg", i]) if i % 2 else dict(rec5, candles=short + long_))
    olds[p6] = open(p6, "rb").read()
open(os.path.join(CD6, "cg", "broken.json"), "wb").write(b'{"candles": [')
statefile.atomic_write_json(os.path.join(CD6, "cg", "notbar.json"), {"x": 1})
statefile.atomic_write_json(os.path.join(CD6, "pools.json"), {"p": 1})
snap = {p: open(p, "rb").read() for p in [os.path.join(CD6, "cg", "broken.json"), os.path.join(CD6, "cg", "notbar.json"), os.path.join(CD6, "pools.json")]}
before = {p: candles._cache_get(p) for p in olds}
Q = lambda *a: None  # noqa: E731
d6 = CC.run(CD6, apply=False, log=Q)
same_dry = all(open(p, "rb").read() == b for p, b in olds.items())
a6 = CC.run(CD6, apply=True, log=Q)
after = {p: candles._cache_get(p) for p in olds}
gz6 = all(open(p, "rb").read()[:2] == b"\x1f\x8b" for p in olds)
chk(d6["conv"] == 4 and same_dry and d6["bad"] == 1 and d6["other"] == 1, "C6a 점검(기본) = 바꿀 수만 셈 · 파일 그대로", d6)
chk(a6["conv"] == 4 and gz6 and canon(before) == canon(after) and a6["bytes1"] < a6["bytes0"],
    "C6b 적용 = 새 형식 · 읽은 봉 배열·다른 칸 같음(float 비트까지) · 작아짐", a6)
chk(all(open(p, "rb").read() == b for p, b in snap.items()), "C6c 깨진·봉 아닌 파일·맨 위 파일 = 그대로", sorted(snap))
a6b = CC.run(CD6, apply=True, log=Q)
chk(a6b["conv"] == 0 and a6b["done"] == 4, "C6d 다시 적용 = 바꿀 것 0(멱등)", a6b)
e6 = CC.run(CD6, apply=True, expand=True, log=Q)
chk(e6["conv"] == 4 and all(open(p, "rb").read() == b for p, b in olds.items()), "C6e --expand = 옛 바이트 그대로(옛 판 롤백용)", e6)
p6x = next(iter(olds))
real_conv = CC.convert


def conv_then_touch(raw, expand):
    r = real_conv(raw, expand)
    statefile.atomic_write_json(p6x, {"key": ["new"], "candles": [], "complete": 2, "until": 9})
    return r


c6 = CC.run(CD6, apply=True, log=Q, conv=conv_then_touch)
chk(c6["changed"] >= 1 and candles._cache_get(p6x)["key"] == ["new"], "C6f 읽은 뒤 바뀐 파일 = 건너뜀(새로 쓴 것 그대로)", c6)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc6 = CC.main([])
chk(rc6 == 0 and "점검" in buf.getvalue(), "C6g 명령 기본 = 점검(state/candles)", buf.getvalue()[-200:])
import subprocess  # noqa: E402
fake_web = os.path.join(paths.BASE_DIR, "src", "web.py")
os.makedirs(os.path.dirname(fake_web), exist_ok=True)
open(fake_web, "w").write("import time\ntime.sleep(60)\n")
pw = subprocess.Popen([sys.executable, fake_web])
try:
    time.sleep(0.5)
    why6 = CC.units_running()
    buf6 = io.StringIO()
    with contextlib.redirect_stdout(buf6):
        rc6j = CC.main(["--apply"])
finally:
    pw.kill()
    pw.wait()
chk(why6 and f"web.py(pid {pw.pid})" in why6 and rc6j == 2 and os.path.realpath(paths.BASE_DIR) != os.path.realpath(T.ROOT),
    "C6j 바꿀 설치(TJ_BASE)의 tj-web 이 떠 있으면 --apply 거부(도구 트리 ≠ 설치)", (why6, rc6j))
gzbad = os.path.join(CD6, "cg", "gzbad.json")
open(gzbad, "wb").write(bad["dictrow"])
c6i = CC.run(CD6, apply=False, expand=True, log=Q)
chk(c6i["bad"] == 1, "C6i --expand 도 행 꼴 이상 gzip = 깨짐(그대로 · 예외 없음)", c6i)
os.remove(gzbad)
ZBAD = bytes.fromhex("1f8b08000000000000ff07") + b"\x00" * 8
kinds_k = {"zlib": ZBAD, "trunc": raw2[: len(raw2) // 2], "rows": bad["dictrow"], "utf8": gzip.compress(b'{"candles": "\xff\xfe"}')}
conv_k = {}
for k, v in kinds_k.items():
    try:
        conv_k[k] = CC.convert(v, True)
    except Exception as e:   # noqa: BLE001
        conv_k[k] = ("raise", type(e).__name__)
chk(all(v == (None, "bad") for v in conv_k.values()), "C6k convert(--expand 쪽) 손상 4종(zlib.error 포함) = (None, 'bad') · 예외 없음", conv_k)
try:
    cj = CC.convert(b'{"candles": [[1,2', False)
except Exception as e:   # noqa: BLE001
    cj = ("raise", type(e).__name__)
chk(cj == (None, "bad"), "C6k convert(압축 쪽) 깨진 JSON = 깨짐", cj)
for order in ("bad_first", "good_first"):
    CDk = os.path.join(T.TMP, "c6k_" + order, "candles")
    os.makedirs(os.path.join(CDk, "cg"))
    goods = {}
    for i in range(2):
        pg = os.path.join(CDk, "cg", ("a" if order == "good_first" else "z") + "_good%d.json" % i)
        open(pg, "wb").write(candles.bars_encode(dict(rec3, key=["cg", order, i]), sig=None))
        goods[pg] = candles._cache_get(pg)
    bads = {}
    for k, v in kinds_k.items():
        pb = os.path.join(CDk, "cg", ("z" if order == "good_first" else "a") + "_bad_" + k + ".json")
        open(pb, "wb").write(v)
        bads[pb] = v
    try:
        rk = CC.run(CDk, apply=True, expand=True, log=Q)
    except Exception as e:   # noqa: BLE001
        rk = {"raise": type(e).__name__}
    chk(rk.get("bad") == len(kinds_k) and rk.get("conv") == 2, "C6k --expand --apply 혼합(%s) = 깨짐 %d 세고 정상 2개 계속 변환" % (order, len(kinds_k)), rk)
    chk(all(open(pb, "rb").read() == v for pb, v in bads.items()), "C6k 혼합(%s) 손상 파일 = 바이트 그대로" % order, None)
    chk(all(open(pg, "rb").read()[:1] == b"{" and canon(candles._cache_get(pg)) == canon(g) for pg, g in goods.items()),
        "C6k 혼합(%s) 정상 파일 = 평문 · 읽는 값 같음(float repr·-0.0·1/1.0 · 무손실)" % order, None)
pk = os.path.join(candles.CACHE_DIR, "upbit", "zz_zlibbad.json")
open(pk, "wb").write(ZBAD)
bufk = io.StringIO()
try:
    with contextlib.redirect_stdout(bufk):
        rck = CC.main(["--expand"])
except Exception as e:   # noqa: BLE001
    rck = "raise " + type(e).__name__
chk(rck == 0 and "깨짐(그대로) " in bufk.getvalue() and open(pk, "rb").read() == ZBAD, "C6k 명령 --expand(점검) = 끝까지 돌고 요약 · 종료 0 · 손상 파일 그대로", (rck, bufk.getvalue()[-160:]))
os.remove(pk)

import ledger_backup  # noqa: E402
import ledger_restore  # noqa: E402

sd = paths.STATE_DIR
live = sorted(os.path.join(candles.CACHE_DIR, s, f) for s, f in ledger_backup.candle_files(candles.CACHE_DIR))
good_live = [p for p in live if candles._cache_get(p) is not None]
out7 = ledger_backup.backup_files("20260201", sd)
bk = os.path.join(sd, "backups", "files_20260201", "candles")
bk_files = sorted(os.path.join(bk, s, f) for s, f in ledger_backup.candle_files(bk))
linked = all(os.path.samefile(os.path.join(bk, os.path.relpath(p, candles.CACHE_DIR)), p) for p in live)
chk(len(bk_files) == len(live) and linked and out7.get("candles/#files") == len(live) and isinstance(out7.get("candles/"), int),
    "C7a 원장 밖 사본에 봉 캐시 폴더(하드 링크 · 맨 위 파일 제외)", {"n": len(bk_files), "out": {k: v for k, v in out7.items() if "candles" in k}})
old2 = open(cp2, "rb").read()
candles._cache_store(cp2, ["upbit", "KRW-TKJ", "1h", D0, D0 + 4 * 3600], short, None, None, True, time.time())
chk(open(os.path.join(bk, "upbit", os.path.basename(cp2)), "rb").read() == old2, "C7b 그 뒤 원자 교체해도 사본은 그날 것", None)
out7b = ledger_backup.backup_files("20260201", sd)
chk(out7b.get("candles/#files") == len(live) and not any(n.startswith(".") for s, f in ledger_backup.candle_files(bk) for n in [f]),
    "C7c 같은 날 다시 = 같은 수 · 임시 링크 안 남음", out7b.get("candles/#files"))
gone = cp1
os.remove(gone)
cur2 = open(cp2, "rb").read()
fp7 = ledger_restore.files_plan("20260201", sd)
rels = sorted(r for _s, r in fp7["candles"])
chk(rels == [os.path.relpath(gone, sd)] and any(x.startswith("봉 캐시") for x in fp7["info"]),
    "C7d 되돌리기 계획 = 지금 없는 봉 파일만", {"rels": rels, "info": fp7["info"]})
res7 = ledger_restore.files_apply(fp7, proc_check=False, state_dir=sd, log=Q)
chk(canon(candles._cache_get(gone)) != "null" and canon(candles._cache_get(gone)["candles"]) == canon(rows1) and open(cp2, "rb").read() == cur2
    and any(x.startswith("candles/") for x in res7["restored"]), "C7e 없는 파일 = 사본으로 되돌림 · 있는 파일 그대로", res7["restored"])
os.remove(gone)
fp7f = ledger_restore.files_plan("20260201", sd)
statefile.atomic_write_json(gone, {"key": ["after"], "candles": [], "complete": 2, "until": 9})
c7 = ledger_restore.files_candles(fp7f, sd, log=Q)
chk(candles._cache_get(gone)["key"] == ["after"] and c7["kept"] == 1, "C7f 계획 뒤 생긴 파일 = 안 덮음(배타 생성)", c7)
for p9 in [os.path.join(candles.CACHE_DIR, "upbit", "bad_" + k + ".json") for k in bad]:
    os.remove(p9)
fp7g = ledger_restore.files_plan("20260201", sd)
c7g = ledger_restore.files_candles(fp7g, sd, log=Q)
chk(c7g["bad"] == len(bad) - 4 and c7g["restored"] == 4 and not os.path.exists(os.path.join(candles.CACHE_DIR, "upbit", "bad_trunc.json")),
    "C7g 깨진 사본(gzip·JSON 아님) = 그 파일만 건너뜀(JSON 객체지만 행 꼴 이상 4개 = 되돌려도 읽기 = 없음 처리 그대로)", c7g)
T.finish()

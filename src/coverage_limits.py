"""Builds the data-collection coverage/limits summary."""
import calendar
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

SCHEMA_VERSION = 1
OUT_NAME = "coverage_limits.json"
SEED_DIR = os.path.join(common.BASE_DIR, "seed", "coverage")

FIX_HINT = "원가 미확인 목록에서 그 코인의 '원가 적용'(개당 원가 입력) 또는 '당시 시세로 추정'을 눌러 주세요"

CHAIN_TRACKS = {
    "eth": {"track": "etherscan_v2", "label": "Ethereum", "genesis": "2015-07-30", "limit_kind": "none",
            "reason_ko": "이더스캔 무료 키로 체인 시작부터 전 이력 조회 가능(키 한도 3회/초 — 증분 수집과 공유)"},
    "arbitrum": {"track": "etherscan_v2", "label": "Arbitrum", "genesis": "2021-08-31", "limit_kind": "none",
                 "reason_ko": "이더스캔 V2 로 체인 시작부터 조회 가능"},
    "polygon": {"track": "etherscan_v2", "label": "Polygon", "genesis": "2020-05-30", "limit_kind": "none",
                "reason_ko": "이더스캔 V2 로 체인 시작부터 조회 가능"},
    "base": {"track": "blockscout_v2", "label": "Base", "genesis": "2023-06-15", "limit_kind": "none",
             "reason_ko": "blockscout 목록으로 체인 시작부터 조회 가능"},
    "optimism": {"track": "blockscout_v2", "label": "Optimism", "genesis": "2021-11-11", "limit_kind": "explorer_index",
                 "reason_ko": "blockscout(explorer.optimism.io) — Bedrock(2023-06-06) 이전 레거시 구간은 색인 방식이 달라 누락될 수 있어요"},
    "gnosis": {"track": "blockscout_v2", "label": "Gnosis", "genesis": "2018-10-08", "limit_kind": "none",
               "reason_ko": "blockscout 로 체인 시작부터 조회 가능"},
    "scroll": {"track": "blockscout_v2", "label": "Scroll", "genesis": "2023-10-10", "limit_kind": "none",
               "reason_ko": "blockscout 로 체인 시작부터 조회 가능"},
    "zksync": {"track": "blockscout_v2", "label": "zkSync Era", "genesis": "2023-03-24", "limit_kind": "none",
               "reason_ko": "blockscout 로 체인 시작부터 조회 가능"},
    "robinhood": {"track": "rpc_getlogs", "label": "Robinhood Chain", "genesis": "2026-07-01", "limit_kind": "none",
                  "reason_ko": "2026-07 메인넷 — 그 이전 이력 자체가 없어요"},
    "arc": {"track": "rpc_getlogs", "label": "Arc", "genesis": "2026-09-14", "fixed_start": "2026-09-14", "limit_kind": "none",
            "reason_ko": "2026-09-16 공개 메인넷 — 봇은 출시 직전 블록(2026-09-14)부터 추적해요. 그 이전 이력은 없어요"},
    "xlayer": {"track": "rpc_getlogs", "label": "X Layer", "genesis": None, "fixed_start": "2026-09-28", "limit_kind": "archive_only",
               "reason_ko": "공개 노드가 옛 구간 로그 조회를 막아요(공식 노드 getLogs 100블록·무료 대체 노드는 최근 1만 블록만) — 봇은 2026-09-28부터 "
                            "추적하고, 그 이전 보유는 기초 잔고(원가 미확인)로 둬요. " + FIX_HINT},
    "stable": {"track": "rpc_getlogs", "label": "Stable", "genesis": None, "fixed_start": "2026-09-28", "limit_kind": "archive_only",
               "reason_ko": "공개 노드가 최근 약 3주치 블록만 보관해요(아카이브 없음) — 봇은 2026-09-28부터 추적하고, 그 이전 보유는 "
                            "기초 잔고(원가 미확인)로 둬요. " + FIX_HINT},
    "monad": {"track": "rpc_getlogs", "label": "Monad", "genesis": None, "limit_kind": "none",
              "reason_ko": "공식 아카이브 RPC 로 과거 조회 가능 — 수집 시작일을 앞당기면 빠진 앞 구간을 받아요"},
    "plasma": {"track": "rpc_getlogs", "label": "Plasma", "genesis": None, "limit_kind": "none",
               "reason_ko": "공식 아카이브 RPC 로 과거 조회 가능 — getLogs 를 1만 블록씩만 받아서 느려요(2026-01-01부터면 빠진 앞 구간만 훑어도 1시간 가까이, 끝나면 자동 반영)"},
    "kaia": {"track": "rpc_getlogs", "label": "Kaia", "genesis": None, "limit_kind": "none",
             "reason_ko": "공식 아카이브 RPC 로 과거 조회 가능 — 수집 시작일을 앞당기면 빠진 앞 구간을 받아요"},
    "fraxtal": {"track": "rpc_getlogs", "label": "Fraxtal", "genesis": None, "limit_kind": "none",
                "reason_ko": "공식 아카이브 RPC 로 과거 조회 가능 — 수집 시작일을 앞당기면 빠진 앞 구간을 받아요"},
    "bob": {"track": "rpc_getlogs", "label": "BOB", "genesis": None, "limit_kind": "none",
            "reason_ko": "공식 아카이브 RPC 로 과거 조회 가능 — 수집 시작일을 앞당기면 빠진 앞 구간을 받아요"},
    "avalanche": {"track": "rpc_getlogs", "label": "Avalanche C", "genesis": None, "limit_kind": "none",
                  "reason_ko": "공식 아카이브 RPC 로 과거 조회 가능 — 수집 시작일을 앞당기면 빠진 앞 구간을 받아요"},
    "abstract": {"track": "rpc_getlogs", "label": "Abstract", "genesis": None, "limit_kind": "none",
                 "reason_ko": "공식 아카이브 RPC 로 과거 조회 가능 — 수집 시작일을 앞당기면 빠진 앞 구간을 받아요"},
    "megaeth": {"track": "blockscout_v2", "label": "MegaETH", "genesis": None, "limit_kind": "none",
                "reason_ko": "blockscout 목록으로 과거 조회 가능"},
    "story": {"track": "blockscout_v2", "label": "Story", "genesis": None, "limit_kind": "none",
              "reason_ko": "blockscout 목록으로 과거 조회 가능"},
    "somnia": {"track": "blockscout_v2", "label": "Somnia", "genesis": None, "limit_kind": "none",
               "reason_ko": "blockscout 목록으로 과거 조회 가능"},
    "bsc": {"track": "rpc_getlogs_archive", "label": "BNB Chain", "genesis": "2020-08-29", "limit_kind": "archive_only",
            "reason_ko": "공개 노드는 최근 구간만 보관해요 — 옛 블록은 아카이브 노드(NodeReal, 유료)가 있어야 받을 수 있어요. 구독이 끝나면 약 1개월 이전 BSC 이력은 못 받아요"},
    "sol": {"track": "sol_signatures", "label": "Solana", "genesis": "2020-03-16", "limit_kind": "rate_cost",
            "reason_ko": "서명 목록은 전 이력 조회 가능. 거래 1건마다 조회 1회라 시간이 활동량에 비례하고, 헬리우스 크레딧이 떨어지면 공개 RPC(느림)로 받아요"},
}

ROLLING_DAYS = {("bybit", "spot_fills"): 730, ("bybit", "futures_fills"): 730, ("bybit", "futures_pnl"): 730,
                ("bybit", "transaction_log"): 730, ("bybit", "loans"): 730,
                ("okx", "spot_fills"): 120, ("okx", "futures_fills"): 120, ("okx", "bills"): 120,
                ("binance", "futures_fills"): 180}
OKX_CAL = {("okx", "spot_fills"), ("okx", "futures_fills"), ("okx", "bills")}

BOT_CAPS = [
    ("exchange:upbit:deposits", "업비트 입금·출금", "봇이 1분마다 최신순으로 수집 시작일까지 전부 다시 넘겨요 — 수집 기간이 길수록 매 분 조회가 늘고, 페이지 상한에 먼저 닿으면 그 회차는 보류(다음 분 재시도)돼 "
     "옛 구간 반영이 늦어질 수 있어요. "
     "(5개월 창 ≈ 입금 2·출금 1페이지/분, 2026-01-01부터면 약 2배). API 자체는 2017년까지 가능"),
    ("exchange:bithumb:deposits", "빗썸 입출금", "봇은 30일 조각마다 최신순으로 처음부터 다시 넘겨요(최대 200페이지 = 2만 건) — 조각 시작일보다 새 입출금이 "
     "2만 건을 넘으면 그 조각은 매번 실패해 더 옛날은 못 받아요. 원화 입출금은 별도 목록"
     "(/v1/deposits/krw·/v1/withdraws/krw)으로 받아 '원화 입출금'에만 보여요(매매 손익·보유 아님)"),
    ("exchange:binance:spot_fills", "바이낸스 현물 체결", "바이낸스 API 는 페어 이름을 줘야만 체결을 알려 줘요 — 봇은 잔고·입출금·과거 체결에 한 번이라도 "
     "나온 코인 × USDT·USDC·BTC·BNB·FDUSD 만 물어봐요. 입출금 없이 거래소 안에서 사서 다 판 코인(또는 다른 쿼트 페어)은 못 찾아요 — "
     "그 매매의 손익이 빠지고 쿼트 코인(USDT 등) 수량 차이는 대사가 기초 잔고로 맞춰요. " + "필요하면 " + FIX_HINT),
    ("exchange:kucoin:hist_deposits", "쿠코인 2019년 이전 입출금", "2019-02 이전 전용 API(hist-deposits/withdrawals)를 봇이 쓰지 않아요 — 2026년 수집에는 영향 없음"),
    ("exchange:okx:bills_archive", "OKX 옛 체결", "약 4개월(3개월 전 달 1일) 이전 OKX 체결은 API 가 주지 않고, OKX 웹/분기별 정산 아카이브(신청 후 CSV 다운로드)로만 "
     "볼 수 있어요 — 봇은 이 신청·다운로드를 하지 않아요(의도적으로 지원 안 함). 그 기간에 OKX 에서 산 코인이 아직 있거나 다른 곳으로 옮겨졌다면 "
     "원가 미확인으로 보여요 → " + FIX_HINT),
    ("exchange:hyperliquid:spot_fills", "Hyperliquid 현물", "Hyperliquid API 는 체결을 최근 1만 건까지만 줘요 — 그보다 옛 체결, 볼트(HLP 등) 예치 잔고"
     "(넣고 뺀 기록만 입출금으로 보여요), 무기한 실현 손익·펀딩(현금 USDC 잔고 변화)은 대사가 잔고 차이로 맞춰요(원가 미확인). "
     "무기한 포지션·손익은 선물 화면(표시 전용) · 아비트럼 출금은 HL 이 아비트럼 txid 를 주지 않아 금액·시간으로만 이어져요"),
]
NOISE_WORDS = ("기록 없음",)

COST_UNKNOWN_REASONS = [
    ("pre_window_holding", "수집 시작 시점 이전에 이미 갖고 있던 코인(기초 잔고) — 산 기록이 수집 범위 밖이면 원가를 알 수 없어요"),
    ("api_retention", "거래소 API 가 오래된 체결을 더 주지 않아요(보존 기간: OKX 약 4개월 = 3개월 전 달 1일부터 · 바이낸스 선물 체결 6개월 · "
     "바이비트 2년) — 그 전에 산 코인은 원가 미확인. " + FIX_HINT),
    ("archive_needed", "체인 옛 구간이 아카이브 노드에만 있어요(BSC) — 아카이브 없이는 그 이전 매수 기록을 못 받아요"),
    ("untracked_source", "등록하지 않은 지갑·거래소에서 들어온 코인 — 출발지 기록이 없어 원가를 이어받지 못해요"),
    ("offchain_transfer", "거래소 내부 이체(계정 간 이동)·에어드랍·스테이킹 보상 — 매수 거래가 없어요"),
    ("token_conversion", "토큰 전환·리브랜딩(거래소 내부 전환) — 옛 토큰 원가가 없으면 새 토큰도 원가 미확인"),
    ("explorer_gap", "탐색기 색인 지연(예: Base blockscout 내부 이동 색인 미완) — 내부 이동으로 들어온 네이티브 코인 기록이 아직 없어 "
     "원가 미확인·잔고 차이로 보일 수 있어요. 색인이 끝나면 봇이 그 구간을 자동으로 다시 읽어 채워요(느림)"),
    ("price_missing", "그 날짜 가격이 없는 토큰(상장 전·유동성 없음) — 수량은 맞아도 원가·손익을 계산할 수 없어요"),
]

EX_KO = {"upbit": "업비트", "bithumb": "빗썸", "binance": "바이낸스", "bybit": "바이비트", "okx": "OKX", "gate": "게이트",
         "kucoin": "쿠코인", "hyperliquid": "Hyperliquid"}
FAM_KO = {"deposits": "입금", "withdrawals": "출금", "spot_fills": "현물 체결", "krw_fills": "원화 체결", "futures_fills": "선물 체결",
          "futures_pnl": "선물 청산손익", "futures_income": "선물 손익", "transaction_log": "거래 내역", "loans": "차입", "convert": "간편전환",
          "earn": "예치(Earn)", "bills": "정산 내역", "margin_fills": "마진 체결", "hist_deposits": "2019년 이전 입금", "orders": "주문",
          "bills_archive": "옛 체결·정산 아카이브(분기 신청)", "account_book": "잔고 변동 원장"}


def ex_label(ex, fam):
    return f"{EX_KO.get(ex, ex)} {FAM_KO.get(fam, fam)}"


EX_WINDOW_DAYS = {"upbit": 7, "bybit": 7, "kucoin": 7, "gate": 30, "binance": 90, "okx": 90, "bithumb": None}


def _sweep_name(ch):
    try:
        import chainsweep
        ent = chainsweep.SWEEP_CHAINS.get(ch)
        return str(ent[0]) if ent else str(ch)
    except Exception:
        return str(ch)


def _d(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts))) if ts else None


def _ts(d):
    if not d:
        return None
    try:
        y, m, dd = map(int, str(d)[:10].split("-"))
    except ValueError:
        return None
    return calendar.timegm((y, m, dd, 0, 0, 0))


def _rj(p, default=None):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return default


def _month_span(a, b, now=None):
    try:
        a, b = int(a), int(b) - 86400
    except (TypeError, ValueError):
        return None
    if b < a:
        b = a
    ta, tb = time.gmtime(a), time.gmtime(b)
    yr = time.gmtime(int(now or time.time())).tm_year
    if ta.tm_year == tb.tm_year == yr:
        return f"{ta.tm_mon}월" if ta.tm_mon == tb.tm_mon else f"{ta.tm_mon}~{tb.tm_mon}월"
    return f"{ta.tm_year}.{ta.tm_mon}~{tb.tm_year}.{tb.tm_mon}"


def okx_floor(now: int) -> int:
    t = time.gmtime(now)
    y, m = t.tm_year, t.tm_mon - 3
    while m <= 0:
        y, m = y - 1, m + 12
    return calendar.timegm((y, m, 1, 0, 0, 0))


def _eta(extra: dict):
    out = {}
    for y9 in ("1y", "2y", "5y", "9y"):
        v = (extra or {}).get(y9) or {}
        lo, hi = v.get("low") or {}, v.get("high") or {}
        a = lo.get("sec", lo.get("sec_at_3rps"))
        b = hi.get("sec", hi.get("sec_at_3rps"))
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            out[y9] = [a if isinstance(a, (int, float)) else b, b if isinstance(b, (int, float)) else a]
    return out or None


API_LIMITS_NAME = "api_limits.json"


def api_limits_table(base=None, active_ex=None, active_chains=None, active_perps=None):
    d = common.seed_json("coverage/" + API_LIMITS_NAME, None, base_dir=base or common.BASE_DIR)
    if not isinstance(d, dict) or not isinstance(d.get("exchanges"), list):
        return None
    out = {k: d.get(k) for k in ("schema", "updated", "columns", "actions", "window_note")}
    out["exchanges"], out["chains"], out["perps"] = [], [], []
    for e in d.get("perps") or []:
        if isinstance(e, dict):
            e2 = dict(e)
            if active_perps is not None:
                e2["used"] = e.get("id") in active_perps
            out["perps"].append(e2)
    for e in d.get("exchanges") or []:
        if isinstance(e, dict):
            e2 = dict(e)
            if active_ex is not None:
                e2["used"] = e.get("id") in active_ex
            out["exchanges"].append(e2)
    for c in d.get("chains") or []:
        if isinstance(c, dict):
            c2 = dict(c)
            if active_chains is not None:
                c2["used"] = bool(set(c.get("match") or [c.get("id")]) & set(active_chains))
            out["chains"].append(c2)
    return out


def _md_cell(t):
    return str(t or "").replace("|", "\\|").replace("\n", " ").strip() or "—"


def api_limits_markdown(t=None) -> str:
    t = t or api_limits_table()
    if not t:
        return ""
    col, act = t.get("columns") or {}, t.get("actions") or {}
    L = ["# 수집 한계 — API 로 되는 것과 안 되는 것", "",
         "tj-bot 은 거래소·체인이 API 로 주는 기록만 모읍니다. API 가 주지 않는 옛 기록을 우회해서 가져오지 않습니다"
         "(거래소 아카이브 신청·CSV 가져오기 없음). 못 받는 부분은 아래에 적어 두었으니, 필요한 경우 '이용자가 할 일'로 직접 정해 주세요.", "",
         "- " + str(t.get("window_note") or ""),
         "- 거래소 API 키는 **조회(읽기) 권한만** 켠 키를 쓰세요. 바이낸스·바이비트·OKX 는 저장할 때 키 권한을 자동으로 확인해 거래·출금·이체 권한이 "
         "켜져 있으면 저장하지 않고, 권한을 API 로 확인할 수 없는 거래소(업비트·빗썸·쿠코인·게이트)는 '조회 권한만 켰음' 확인이 있어야 저장합니다.",
         "- 같은 내용이 화면 **설정 › 수집 한계 › 거래소·체인별 한계 정리**에도 있습니다(정리 기준일 " + str(t.get("updated") or "") + ").", "",
         "## 이용자가 할 수 있는 일", ""]
    for k, v in act.items():
        a, _, b = str(v).partition(" — ")
        L.append(f"- **{a}** — {b}" if b else f"- {a}")
    hdr = "| " + " | ".join(col.get(k, k) for k in ("kind", "api", "bot", "miss", "todo")) + " |"

    def table(items, title):
        L.extend(["", "## " + title, ""])
        for e in items:
            L.extend(["### " + str(e.get("name") or e.get("id")), ""])
            if e.get("perm"):
                L.extend(["키 권한: " + str(e["perm"]), ""])
            L.extend([hdr, "|---|---|---|---|---|"])
            for r in e.get("rows") or []:
                todo = ", ".join(str(act.get(x.strip(), x.strip())).partition(" — ")[0]
                                 for x in str(r.get("todo") or "").split(",") if x.strip())
                L.append("| " + " | ".join(_md_cell(r.get(k)) for k in ("kind", "api", "bot", "miss")) + " | " + _md_cell(todo) + " |")
            L.append("")
    table(t.get("exchanges") or [], "거래소")
    table(t.get("chains") or [], "체인")
    if t.get("perps"):
        table(t.get("perps") or [], "퍼프 덱스(주소로 조회)")
    return "\n".join(L).rstrip() + "\n"


def build(base=None, exl_path=None, speed_path=None, now=None):
    st = os.path.join(base, "state") if base else common.STATE_DIR
    cfg = _rj(os.path.join(base, "config.json") if base else common.CONFIG_PATH, {}) or {}
    base = base or common.BASE_DIR
    since = cfg.get("backfill_since")
    months = float(cfg.get("backfill_months") or 5)
    now = int(now or time.time())
    win0 = now - int(months * 30 * 86400)
    ts_since = _ts(since)
    tgt = min(win0, ts_since) if ts_since else win0
    status = _rj(os.path.join(st, "backfill_status.json"), {}) or {}
    exl = (_rj(exl_path, {}) if exl_path else common.seed_json("coverage/exchange_limits.json", {}, base_dir=base)) or {}
    speed = (_rj(speed_path, {}) if speed_path else common.seed_json("coverage/speed_model.json", {}, base_dir=base)) or {}
    other_speed = _rj(os.path.join(st, "chain_backfill_speed.json"), None)
    db = sqlite3.connect(f"file:{os.path.join(st, 'ledger.db')}?mode=ro", uri=True, timeout=10)
    try:
        wallets = {}
        for ch, a, lab in db.execute("SELECT chain, address, label FROM wallets"):
            wallets.setdefault(ch, []).append((a, lab))
        first = {}
        for loc, t in db.execute("SELECT location, MIN(event_ts) FROM postings WHERE location LIKE 'wallet:%'"
                                 " AND leg_kind != 'opening' GROUP BY location"):
            parts = str(loc).split(":", 2)
            if len(parts) == 3 and t:
                k = (parts[1], parts[2] if parts[1] == "sol" else parts[2].lower())
                first[k] = min(int(t), first.get(k, int(t)))
        try:
            n_open = db.execute("SELECT count(*) FROM postings WHERE leg_kind='opening'").fetchone()[0]
        except sqlite3.Error:
            n_open = None
    finally:
        db.close()
    sources, unavailable = [], []
    for ch, meta in CHAIN_TRACKS.items():
        cws = wallets.get(ch) or []
        if not cws:
            continue
        cur = _rj(os.path.join(st, "cursor_bsc.json" if ch == "bsc" else "cursor_sol.json" if ch == "sol"
                               else f"cursor_evm_{ch}.json"), {}) or {}
        ext_items = {}
        for unit, items in status.items():
            if isinstance(items, dict) and not str(unit).startswith("_"):
                for k, v in items.items():
                    if isinstance(v, dict) and str(k).startswith(ch + ":"):
                        ext_items[k] = v
        job = (ext_items.get(f"{ch}:extend") or ext_items.get(f"{ch}:job")) if ch != "sol" else None
        reason, limit_kind = meta["reason_ko"], meta["limit_kind"]
        lag = cur.get("_ext_internal_lag") if isinstance(cur.get("_ext_internal_lag"), dict) else None
        ipm = cur.get("_ext_internal_pending") if isinstance(cur.get("_ext_internal_pending"), dict) else None
        int_pending = bool(ipm and ipm.get("ranges"))
        if int_pending or lag:
            r9 = (ipm or {}).get("ratio") if int_pending and (ipm or {}).get("ratio") is not None else (lag or {}).get("ratio")
            try:
                pct = f"{float(r9) * 100:.0f}%" if r9 is not None else "미완"
            except (TypeError, ValueError):
                pct = "미완"
            if int_pending:
                per = _month_span(ipm.get("from_ts"), ipm.get("to_ts"), now)
                what = f"{meta['label']} 내부 ETH 이동" + (f"({per})" if per else "(옛 구간)")
                if lag and not ipm.get("started"):
                    reason = f"{what} — 탐색기 색인이 끝나면 자동으로 채워져요(느림, 진행 {pct})"
                else:
                    reason = f"{what} — 탐색기 색인이 끝나 지금 자동으로 채우는 중이에요(느림)"
            else:
                reason = (f"{meta['label']} 탐색기(blockscout) 내부 ETH 이동 색인이 {pct}까지 진행됐어요 — 색인이 끝나기 전 구간의 "
                          "내부 이동은 끝난 뒤 자동으로 다시 읽어요(느림)")
            limit_kind = "explorer_index"
        elif meta["track"] == "rpc_getlogs" and isinstance(cur.get("_since_ext"), dict):
            reason = meta["reason_ko"] + " — 지금 빠진 앞 구간을 훑는 중이에요(느림, 끝나면 자동 반영)"
        wl = []
        for a, lab in cws:
            key = a if ch == "sol" else a.lower()
            fa = first.get((ch, key))
            if ch == "sol":
                cov = cur.get("_cov_ts:" + a)
                ach = _d(cov) if isinstance(cov, int) else None
                stt = "done" if isinstance(cov, int) and ts_since and cov <= ts_since + 86400 else (
                    "running" if ("_sigx:" + a) in cur else "window_only")
            elif ch == "bsc":
                ach = _d(tgt) if isinstance(cur.get("_cov"), int) and not isinstance(cur.get("_ext"), dict) and ts_since else None
                stt = "done" if ach else ("running" if isinstance(cur.get("_ext"), dict) else "window_only")
            elif ch == "robinhood":
                ach, stt = meta["genesis"], "done"
            elif meta.get("fixed_start"):
                ach, stt = meta["fixed_start"], "done"
            elif meta["track"] == "rpc_getlogs":
                if isinstance(cur.get("_since_ext"), dict):
                    ach, stt = None, "running"
                elif ts_since and cur.get("_since_seen") and int(cur["_since_seen"]) <= ts_since + 86400:
                    ach, stt = _d(tgt), "done"
                else:
                    ach, stt = None, "window_only"
            else:
                c = cur.get("_cov:" + key)
                j9 = cur.get("_bfjob") if isinstance(cur.get("_bfjob"), dict) else None
                if j9 and j9.get("kind") == "extend" and key in (j9.get("wallets") or []):
                    ach, stt = None, "running"
                elif isinstance(c, int) and ts_since and (not job or job.get("phase") == "done"):
                    ach, stt = _d(tgt), "done"
                else:
                    ach, stt = None, "window_only"
            if not ach:
                ach = _d(max(win0, _ts(meta["genesis"]) or 0))
            wl.append({"wallet": a, "label": lab, "achieved_start": ach, "status": stt,
                       "first_record": _d(fa), "records_reach_start": bool(fa and ach and fa <= (_ts(ach) or 0) + 3 * 86400)})
        sp = (speed.get("chains") or {}).get(ch) or {}
        src = {"id": f"chain:{ch}", "kind": "chain", "chain": ch, "label": meta["label"], "family": "onchain",
               "track": meta["track"], "configured_start": _d(tgt), "earliest_retrievable": meta["genesis"],
               "limit_kind": limit_kind, "reason_ko": reason, "wallets": wl,
               "eta": _eta(sp.get("extrapolate")), "eta_model_ko": sp.get("model_ko")}
        if int_pending:
            src["internal_pending"] = True
        if isinstance(other_speed, dict) and isinstance((other_speed.get("chains") or {}).get(ch), dict):
            o9 = other_speed["chains"][ch]
            src["speed_measured"] = {k: o9.get(k) for k in ("blocksPerSec", "getLogsSpan", "getLogsSec", "archive", "rpc")
                                     if o9.get(k) is not None}
        sources.append(src)
        if meta.get("fixed_start") and limit_kind == "archive_only":
            unavailable.append({"source_id": src["id"], "label": meta["label"], "before": meta["fixed_start"],
                                "severity": "hard", "reason_ko": reason})
        elif limit_kind in ("archive_only", "explorer_index"):
            unavailable.append({"source_id": src["id"], "label": meta["label"], "before": None,
                                "severity": "partial", "reason_ko": reason})
    for ch in sorted(wallets):
        if ch in ("bsc", "sol"):
            continue
        g9 = [x for x in ((_rj(os.path.join(st, f"cursor_evm_{ch}.json"), {}) or {}).get("_retention_gaps") or []) if isinstance(x, dict)]
        if not g9:
            continue
        a9 = min(g9, key=lambda x: int(x.get("from") or 0))
        b9 = max(g9, key=lambda x: int(x.get("to") or 0))
        lab9 = (CHAIN_TRACKS.get(ch) or {}).get("label") or _sweep_name(ch)
        fd9, td9 = _d(a9.get("from_ts")), _d(b9.get("floor_ts"))
        unavailable.append({"source_id": f"chain:{ch}", "label": lab9, "before": td9, "severity": "hard",
                            "uncollected": {"from_block": int(a9.get("from") or 0), "to_block": int(b9.get("to") or 0),
                                            "from": fd9, "until": td9},
                            "reason_ko": (f"{lab9} 공개 노드가 옛 로그를 보관하지 않아 블록 {int(a9.get('from') or 0):,}~{int(b9.get('to') or 0):,}"
                                          + (f"({fd9 or '?'}~{td9} 전)" if td9 else "") + " 기록을 못 받았어요(미수집 범위) — 그 앞 보유는 "
                                          "기초 잔고(원가 미확인)로 둬요. " + FIX_HINT)})
        src9 = next((s9 for s9 in sources if s9.get("id") == f"chain:{ch}"), None)
        if src9:
            src9["limit_kind"] = "archive_only"
            src9["reason_ko"] = unavailable[-1]["reason_ko"]
            for w9 in src9.get("wallets") or []:
                wl9 = str(w9.get("wallet") or "").lower()
                fl9 = [int(g["floor_ts"]) for g in g9 if isinstance(g.get("floor_ts"), (int, float)) and not isinstance(g.get("floor_ts"), bool)
                       and (not g.get("ws") or any(wl9.startswith(str(p9).lower()) for p9 in g["ws"]))]
                if not fl9:
                    continue
                d9 = _d(max(fl9))
                if d9 and (not w9.get("achieved_start") or d9 > str(w9["achieved_start"])):
                    w9["achieved_start"] = d9
                w9["records_reach_start"] = False
    exf = _rj(os.path.join(st, "exf_state.json"), {}) or {}
    upo = _rj(os.path.join(st, "upbit_orders_state.json"), {}) or {}
    for ex, fams in sorted((exl.get("exchanges") or {}).items()):
        if ex != "upbit" and ex not in exf:
            continue
        ext = ((exf.get(ex) or {}).get("ext") or {}) if ex != "upbit" else {}
        for fam, v in sorted(fams.items()):
            if not isinstance(v, dict):
                continue
            ach = None
            if ex == "upbit":
                if fam in ("krw_fills", "spot_fills", "orders") and upo.get("ext_from"):
                    ach = _d(upo.get("ext_from"))
            elif fam in ("deposits", "withdrawals") and ext.get("wd_from"):
                ach = _d(ext.get("wd_from"))
            elif fam in ("spot_fills", "krw_fills") and ext.get("fills_from"):
                ach = _d(ext.get("fills_from"))
            src = {"id": f"exchange:{ex}:{fam}", "kind": "exchange", "exchange": ex, "family": fam, "label": ex_label(ex, fam),
                   "endpoint": v.get("endpoint"), "bot_uses": v.get("bot_uses"), "bot_ref": v.get("bot_ref"),
                   "configured_start": _d(tgt) if v.get("bot_uses") else None,
                   "achieved_start": ach, "earliest_retrievable": v.get("verified_earliest"),
                   "rejected_before": v.get("rejected_before"), "doc_limit": v.get("doc_limit"), "doc_url": v.get("doc_url"),
                   "verified": bool(v.get("verified_earliest") or v.get("rejected_before")), "verified_how": v.get("verified_how"),
                   "account_earliest_seen": v.get("account_earliest_seen"), "reason_ko": v.get("reason_ko")}
            rd = ROLLING_DAYS.get((ex, fam))
            if rd:
                src["rolling_limit_days"] = rd
                src["rolling_kind"] = "calendar_month" if (ex, fam) in OKX_CAL else "days"
                src["earliest_retrievable"] = _d(okx_floor(now) if (ex, fam) in OKX_CAL else now - rd * 86400)
            if rd and ach and src["earliest_retrievable"] and ach < src["earliest_retrievable"]:
                src["achieved_start"] = ach = src["earliest_retrievable"]
            if fam in ("spot_fills", "krw_fills"):
                if ext.get("fills_limit"):
                    src["bot_limit_ko"] = common.redact_secret_text(str(ext["fills_limit"]))[:200]
                if ext.get("fills_err"):
                    src["collector_error"] = common.redact_secret_text(str(ext["fills_err"]))[:200]
            if ext.get("wd_err") and fam in ("deposits", "withdrawals"):
                src["collector_error"] = common.redact_secret_text(str(ext["wd_err"]))[:200]
            wd9 = EX_WINDOW_DAYS.get(ex)
            if v.get("bot_uses") and wd9:
                src["eta"] = {y9: [round(-(-n9 * 365 // wd9) * 0.7), round(-(-n9 * 365 // wd9) * 0.7 * 2)]
                              for y9, n9 in (("1y", 1), ("2y", 2), ("5y", 5), ("9y", 9))}
                src["eta_model_ko"] = f"{wd9}일 창 × 콜 0.7초(추정 — 거래 많은 창은 페이지가 늘어요)"
            sources.append(src)
            noise = any(w in (v.get("reason_ko") or "") for w in NOISE_WORDS)
            if (v.get("rejected_before") or rd) and not noise:
                before9 = _d(okx_floor(now)) if (ex, fam) in OKX_CAL else (_d(now - rd * 86400) if rd else v.get("rejected_before"))
                unavailable.append({"source_id": src["id"], "label": ex_label(ex, fam), "before": before9,
                                    "rolling_days": rd, "rolling_kind": "calendar_month" if (ex, fam) in OKX_CAL else ("days" if rd else None),
                                    "severity": "hard", "reason_ko": v.get("reason_ko")})
            elif v.get("bot_uses") is False and "권한" in (v.get("reason_ko") or ""):
                unavailable.append({"source_id": src["id"], "label": ex_label(ex, fam), "before": None,
                                    "severity": "no_permission", "reason_ko": v.get("reason_ko")})
            elif v.get("bot_uses") is False and v.get("reason_ko") and not noise and v.get("account_earliest_seen"):
                unavailable.append({"source_id": src["id"], "label": ex_label(ex, fam), "before": None,
                                    "severity": "not_collected", "reason_ko": v.get("reason_ko")})
    active_ex = {"upbit"} | set(exf)
    for sid, lab, why in BOT_CAPS:
        if sid.split(":")[1] in active_ex:
            unavailable.append({"source_id": sid, "label": lab, "before": None, "severity": "bot_cap", "reason_ko": why})
    reasons = []
    for code, txt in COST_UNKNOWN_REASONS:
        r = {"code": code, "reason_ko": txt}
        if code == "pre_window_holding":
            r["count"] = n_open
        reasons.append(r)
    active_chains = sorted(ch for ch in wallets if ch in CHAIN_TRACKS)
    return {"schema": SCHEMA_VERSION, "generated_at": now, "generator": "src/coverage_limits.py",
            "api_limits": api_limits_table(base, set(exf) | ({"upbit"} if upo else set()), active_chains,
                                           {str(w.get("dex")) for w in (cfg.get("perp_wallets") or []) if isinstance(w, dict)}),
            "backfill_since": since, "backfill_months": months, "window_start": _d(tgt),
            "exchange_probed_at": exl.get("probed_at"), "speed_measured_at": speed.get("measured_at"),
            "sources": sources, "unavailable": unavailable, "cost_unknown_reasons": reasons,
            "nine_year": speed.get("nine_year")}


def write(base=None, out=None) -> dict:
    d = build(base)
    common.atomic_write_json(out or (os.path.join(base, "state", OUT_NAME) if base else os.path.join(common.STATE_DIR, OUT_NAME)), d)
    return d


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--doc":
        md = api_limits_markdown()
        if len(sys.argv) > 2:
            with open(sys.argv[2], "w", encoding="utf-8") as f:
                f.write(md)
        else:
            sys.stdout.write(md)
        return 0
    out = sys.argv[1] if len(sys.argv) > 1 else None
    d = write(out=out)
    print(f"{out or os.path.join(common.STATE_DIR, OUT_NAME)}: sources {len(d['sources'])} · unavailable {len(d['unavailable'])}")


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import logging
import threading

__all__ = ["KEYS", "BLOCKS", "RUNTIME_KEYS", "TYPES", "is_memo", "declared_top", "declared_sub", "check", "warn_once"]

TYPES = {"dict": (dict,), "list": (list,), "str": (str,), "num": (int, float), "bool": (bool,)}

KEYS = (
    ("addr_ai", "dict", "주소 AI 판정 워커 하루 상한·간격(enabled · daily_max 등)", "꺼짐"),
    ("addr_tier", "dict", "쉬는·빈 지갑 잔고·유입 확인 간격과 몫(inflow_sec · budget_pct 등)", "inflow_sec 600 · budget_pct 80"),
    ("alerts", "dict", "알림 세부(liq_repeat_min · liq_fast 등)", "liq_repeat_min 60"),
    ("backfill", "dict", "과거 기록 채우기·자동 재구축 세부(닫힌 블록 — 아래 하위 키)", "없음(코드 기본값)"),
    ("backfill_covered_since", "str|num", "이미 채운 것으로 보는 시작일(YYYY-MM-DD 또는 epoch)", "없음"),
    ("backfill_full_history", "bool", "true 면 처음부터 전체 기록(backfill_months 무시 · 기초잔고 대사 꺼짐)", "false"),
    ("backfill_months", "num", "처음 불러올 과거 개월 수",
     "모듈마다 다름: 수집기·core·대사 = 0(키 없으면 대사 꺼짐) · 화면·거래소·온보딩 = 5 · config.example = 5"),
    ("backfill_since", "str|num", "과거 기록 시작일(YYYY-MM-DD 또는 epoch) — backfill_months 보다 앞당길 때", "없음"),
    ("backup", "dict", "원장 정기 백업(닫힌 블록 — keep_db · keep_pre_rebuild · offsite)", "keep_db 3"),
    ("balance_check", "dict", "온체인 잔고 상시 대조(알림 전용 · 원장 무변)", "config.example 값"),
    ("brokers", "dict", "증권사 보유 동기화({키: {enabled …}} · 필드 = src/brokers/README.md)", "전부 꺼짐"),
    ("bsc", "dict", "BNB Chain 공개 RPC 수집기(logs_rpcs · getlogs_span · poll_sec 등)", "config.example 값"),
    ("build_proc", "str", "화면 계산 프로세스 방식 auto · off · fork(환경변수·.env 에 없을 때)", "auto"),
    ("chain_sweep", "dict", "등록 주소의 다른 체인 활동 훑기(enabled · auto_enable · ignore 등)", "config.example 값"),
    ("chain_wallets", "list", "비EVM 체인 지갑 목록(체인 등록부 — 설정 화면이 씀)", "없음"),
    ("chains", "dict", "EVM 체인 블록 {체인: {rpcs · blockscout · enabled · discovery …}} — 필수 키", "config.example 값"),
    ("etherscan", "dict", "이더스캔 하루 몫·속도(daily_budget · page_rows 등)", "코드 기본값"),
    ("evm_poll_sec", "num", "EVM 체인 기본 수집 주기(초 · 체인 블록 poll_sec 이 우선)", "45"),
    ("exchange_addresses", "list", "거래소 입출금 주소 목록(이동 판정)", "비어 있음"),
    ("exchanges", "dict", "거래소별 과거 기록 시작일 {거래소: {backfill_since · covered_since}}", "없음"),
    ("exf", "dict", "해외 거래소 수집(poll_sec 기본 600 · leverage · binance_dividends = false 면 바이낸스 배당·에어드랍 지급 내역 안 받음)", "poll_sec 600"),
    ("first_seen_px", "bool", "최초 인식 시가 스위치(화면 설정 ui_prefs 가 우선)", "true"),
    ("flow_trace", "dict", "보낸 내역 받은 곳 추적 워커(trace · cycle_calls · interval_sec · min_usd)", "켜짐"),
    ("gas_in_cost", "bool", "가스비를 원가에 넣기 스위치(화면 설정 ui_prefs 가 우선)", "true"),
    ("health", "dict", "상태 점검(enabled · heartbeat_url · tunnel · t 문턱 등 — 열린 블록)", "켜짐"),
    ("hyperliquid", "dict", "Hyperliquid 현물 수집(spot · spot_exclude)", "config.example 값"),
    ("loan_short", "list", "거래소 대출로 빌려 출금한 기간 목록", "없음(꺼짐)"),
    ("native_symbol", "dict", "체인별 네이티브 심볼(없으면 체인 표 기본값을 채움)", "체인 표 기본값"),
    ("negabs_enabled", "bool", "발견 시점 기초 잔고 바로잡기", "true"),
    ("net_pace", "dict", "외부 요청 간격(cooldown_sec · explorer_sec · other_sec)", "코드 기본값"),
    ("nft", "dict", "NFT 추적(enabled false = 끔)", "켜짐"),
    ("nonevm", "dict", "비EVM 체인별 선택 설정 {체인: {…}} — 수집기가 정의", "없음"),
    ("okx_dex", "dict", "OKX DEX 시세 기준(krw_threshold)", "krw_threshold 1000000"),
    ("other_assets", "dict", "기타 자산 탭 공개 시세 갱신(quote_every_sec · broker_every_sec · quotes)", "config.example 값"),
    ("perp_wallets", "list", "무기한 선물 DEX 지갑 목록(설정 화면이 씀)", "없음"),
    ("price_guard", "dict", "DEX 시세 유동성 가드(min_reserve_usd · dex_max_age_sec)", "config.example 값"),
    ("price_overrides", "dict", "비상용 수동 가격 고정", "없음"),
    ("rabby", "dict", "지갑 포트폴리오 보강(Rabby 공개 API · enabled · min_wallet_usd)", "꺼짐"),
    ("recon_native_stall_hours", "num", "네이티브 잔고 대사 멈춤 판정 시간", "코드 기본값"),
    ("recon_tokens", "dict", "잔고 대사에 늘 넣을 토큰 {체인: {CA: [심볼, 소수 자리]}}", "없음"),
    ("review", "dict", "AI 리뷰·평가(닫힌 블록 — 아래 하위 키)", "평가 0(끔)"),
    ("rpc_day_limits", "dict", "노드별 하루·월 한도 덮어쓰기({이름: {…}} · false = 그 노드 장부 끔)", "기본 표"),
    ("rpc_day_pct", "num", "무료 노드를 공표 한도의 몇 % 까지 쓸지", "80"),
    ("rpc_fallback", "bool", "탐색기가 막히면 공개 RPC 로 대체(전체 스위치)", "true"),
    ("rpc_first", "bool", "새 탐색기 체인의 수집 순서 = RPC 우선(false = 종전 순서)", "true"),
    ("runner", "dict", "유닛 러너(max_mb.<유닛> 메모리 상한)", "web 3072 · 그 밖 0"),
    ("sol", "dict", "Solana 수집(rpc · head_rpc · archive_rpc · helius_* · poll_sec 등)", "config.example 값"),
    ("token_discovery", "dict", "지갑 등록 대사의 옛 보유 토큰 찾기(enabled)", "켜짐"),
    ("transit", "dict", "보낸 뒤 도착 전 '이동 중' 표시 시간(hours · default_hours · own_hours 등)", "코드 기본값"),
    ("upbit", "dict", "업비트 수집(poll_sec)", "poll_sec 60"),
    ("wallets", "list", "추적할 지갑 목록 — 필수 키", "비어 있음"),
    ("web", "dict", "웹 화면(닫힌 블록 — 아래 하위 키)", "port 8023 · bind loopback"),
    ("wow", "dict", "물어보는 검색(ask_llm · ask_llm_daily_max)", "ask_llm false · 하루 40"),
    ("wrapped_native", "dict", "체인별 랩드 네이티브 토큰 CA(없으면 체인 표 기본값을 채움)", "체인 표 기본값"),
    ("xchain", "dict", "교차체인 짝 맞추기·경유 지갑 역추적 워커(trace · budget · per_cycle · cycle_calls · interval_sec)", "켜짐"),
)

BLOCKS = {
    "backfill": (
        ("auto_rebuild", "false = 자동 재구축 끔"),
        ("bf_target_sec", "노드 고르기 목표 시간"),
        ("engine", "과거 기록 엔진 선택"),
        ("evm_cycle_budget_sec", "EVM 과거 기록 한 바퀴 시간 몫"),
        ("hosts", "노드 호스트 덮어쓰기"),
        ("node_select", "false = 노드 고르기 끔(관측만)"),
        ("node_slo_sec", "노드별 응답 목표 덮어쓰기"),
        ("px_prefetch", "false = 과거 시세 미리 받기 끔"),
        ("quota_open_sec", "하루 몫 열림 대기"),
        ("rebuild_allow_locked", "false = 잠긴 원장 재구축 허용 안 함"),
        ("rebuild_check_sec", "재구축 조건 확인 간격"),
        ("rebuild_dir", "재구축 임시 사본 위치(기본 홈)"),
        ("rebuild_keep_oldest", "옛 키 — 재계산 전 원장 보존(가장 옛 것)"),
        ("rebuild_keep_recent", "옛 키 — 재계산 전 원장 보존(최근 것)"),
        ("rebuild_min_gap_sec", "재구축 최소 간격"),
        ("rebuild_pnl_gate", "false = 재구축 손익 게이트 끔"),
        ("rebuild_pnl_tol_pct", "재구축 손익 허용 차(%)"),
        ("rebuild_pnl_tol_usd", "재구축 손익 허용 차(USD)"),
        ("rebuild_retry_sec", "재구축 실패 뒤 다시 시도 간격"),
        ("rebuild_timeout_sec", "재구축 시간 한도"),
        ("stall_sec", "과거 기록 멈춤 판정"),
        ("verify_timeout_sec", "재구축 검증 시간 한도"),
    ),
    "backup": (
        ("keep_db", "원장 정기 백업 보관 수(1~30)"),
        ("keep_pre_rebuild", "재계산 교체 전 원장 보존본 수(1~5)"),
        ("offsite", "서버 밖 둘째 백업(안쪽 칸은 tools/offsite_backup.py --help · 열린 칸)"),
    ),
    "review": (
        ("buy_eval_daily_max", "AI 매수 평가 하루 상한(0 = 끔)"),
        ("chart_prewarm_per_day", "영수증 차트 봉 미리 받기 하루 상한(0 = 끔)"),
        ("coach_role", "AI 리뷰 첫 줄 트레이더 설명"),
        ("known_patterns", "지적하지 않을 내 운용 패턴 문장 목록"),
        ("sell_eval_daily_max", "AI 매도 평가 하루 상한(0 = 끔)"),
    ),
    "web": (
        ("allowed_hosts", "리버스 프록시·터널 도메인(Host 허용)"),
        ("behind_proxy", "true = 모든 요청을 프록시 경유로 취급"),
        ("bind", "loopback(권장) · tailscale"),
        ("login", "웹 로그인(enabled · session_days · idle_days · secure_cookie)"),
        ("max_conn", "동시 연결 상한"),
        ("max_conn_per_ip", "주소 하나당 동시 연결 상한"),
        ("port", "화면 포트"),
        ("public_url", "알림 '보기' 링크 주소"),
        ("setup_allow_lan", "true = 사설망에서도 설정 바꾸기"),
        ("setup_allow_proxy", "true = 프록시·터널에서도 설정 바꾸기"),
        ("token_logos", "호환으로 남은 키(효과 없음)"),
    ),
}

RUNTIME_KEYS = ("_auto_pairs", "_disabled_chains", "_disabled_wallets")

_TOP = {k[0]: k for k in KEYS}
_SUB = {b: frozenset(s for s, _d in subs) for b, subs in BLOCKS.items()}
_MAX_LIST = 20
_NAME_MAX = 60
_WARNED = [False]
_LOCK = threading.Lock()


def is_memo(name: object) -> bool:
    return isinstance(name, str) and (name.startswith("_") or name.endswith("_note"))


def declared_top() -> frozenset:
    return frozenset(_TOP)


def declared_sub(block: str) -> frozenset | None:
    return _SUB.get(block)


def _type_name(v: object) -> str:
    if isinstance(v, bool):
        return "bool"
    for name, tps in TYPES.items():
        if isinstance(v, tps):
            return name
    return type(v).__name__


def _type_ok(v: object, spec: str) -> bool:
    got = _type_name(v)
    return got in spec.split("|")


def _label(name: object) -> str:
    s = name if isinstance(name, str) else repr(name)
    s = "".join(c if c.isprintable() else "?" for c in s)
    return s if len(s) <= _NAME_MAX else s[:_NAME_MAX] + "…"


def check(cfg: object) -> list:
    if not isinstance(cfg, dict):
        return [("", "설정이 JSON 객체가 아님")]
    out = []
    for k in list(cfg.keys()):
        if is_memo(k):
            continue
        spec = _TOP.get(k) if isinstance(k, str) else None
        if spec is None:
            out.append((_label(k), "모르는 키(그대로 둠)"))
            continue
        v = cfg.get(k)
        if v is None:
            continue
        if not _type_ok(v, spec[1]):
            out.append((_label(k), "형 다름(선언 %s · 실제 %s)" % (spec[1], _type_name(v))))
            continue
        subs = _SUB.get(k)
        if subs is not None and isinstance(v, dict):
            for s in list(v.keys()):
                if not is_memo(s) and s not in subs:
                    out.append((_label(k) + "." + _label(s), "모르는 하위 키(그대로 둠)"))
    return out


def _log_path(path: str, reason: str, n: int) -> str:
    if reason.startswith("형 다름"):
        return path
    if reason.startswith("모르는 하위 키"):
        return path.partition(".")[0] + ".<선언 밖 #%d>" % n
    return "<선언 밖 #%d>" % n if path else "(전체)"


def warn_once(cfg: object, log: logging.Logger | None = None) -> int:
    with _LOCK:
        if _WARNED[0]:
            return 0
        _WARNED[0] = True
    try:
        found = check(cfg)
        if found:
            shown = ", ".join("%s(%s)" % (_log_path(p, r, i), r) for i, (p, r) in enumerate(found[:_MAX_LIST], 1))
            more = " 외 %d개" % (len(found) - _MAX_LIST) if len(found) > _MAX_LIST else ""
            (log or logging.getLogger("tj")).info(
                "설정 확인: 선언 밖 키·형 다름 %d개 — 값은 그대로 씀(모르는 키 보존 · 선언표 = src/cfg_schema.py): %s%s", len(found), shown, more)
        return len(found)
    except Exception:   # noqa: BLE001 [boundary]
        return 0

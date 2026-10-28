CASSETTE, UNIT, ALLOW = "cassette", "unit", "allow"

SITES = {
    "alert_bot::send_message": (CASSETTE, ""),
    "alert_bot::send_photo": (CASSETTE, ""),
    "bf_engine::http_request": (CASSETTE, "무키 1회 + 코인게코 키 헤더 갈래(has_key_header → auth_urlopen) 1회"),
    "bf_engine::sol_open": (CASSETTE, "비인증 urlopen 갈래(Request) 1회"),
    "brokers.base::default_http": (ALLOW, "자기 opener(_NoRedirect) — 허용 · test_sec_net_policy.py [2] · 카세트도 한 번 부름"),
    "chk_collect::collect_tunnel": (CASSETTE, "루프백(127.0.0.1) 문자열 URL — 카세트가 루프백도 가로챔"),
    "depaddr::http_get": (CASSETTE, ""),
    "exf_net::_clock_fetch": (CASSETTE, ""),
    "exf_net::http_json": (CASSETTE, ""),
    "flow_trace::Scanner._es_http": (CASSETTE, ""),
    "health::Monitor.heartbeat._go": (CASSETTE, "heartbeat() 가 띄운 스레드를 join(주입 opener 없는 갈래)"),
    "liq_watch::_http_default": (CASSETTE, ""),
    "lpchain::list_wallet_positions": (CASSETTE, ""),
    "lpchain::_no_mgr_collections": (UNIT, "/nft 5xx 때만 부르는 대체 확인(카세트의 정상 /nft 한 번엔 안 닿음) · test_srcoff_negcache.py [7]"),
    "lpsol::_rpc": (CASSETTE, ""),
    "onboarding::_http": (CASSETTE, ""),
    "other_assets::default_http_get": (CASSETTE, ""),
    "perp_dex::_http_default": (CASSETTE, ""),
    "pricing::_gj": (CASSETTE, ""),
    "pricing::okx_dex_prices": (CASSETTE, ""),
    "rabby::http_get": (CASSETTE, ""),
    "recon::_gj": (CASSETTE, ""),
    "recon::_rpc": (CASSETTE, "솔라나 메서드 gap=True(sol_open) · gap=False(urlopen 직접) 둘 다"),
    "review_daily::_get_json": (CASSETTE, "루프백 + 내부 토큰 헤더(X-TJ-Internal) 갈래"),
    "sale_match::http_get_json": (CASSETTE, ""),
    "sol_base::Rpc._call": (CASSETTE, ""),
    "sol_base::Rpc.batch": (CASSETTE, "항목마다 _call(배치 HTTP 의 자기 Request 줄은 'if True' 뒤라 도달 불가 — 옛 코드 보존)"),
    "ton_watch::TonClient.req": (CASSETTE, "무키(urlopen) · 키(X-API-Key → auth_urlopen) 둘 다"),
    "upbit_link::Upbit.get": (CASSETTE, ""),
    "view_workers::WorkersMixin._origin_worker": (CASSETTE, "끝없는 루프 — 시험 하위 클래스의 soft_invalidate 가 한 바퀴 뒤 멈춤 신호"),
    "web::_goplus_fetch": (CASSETTE, ""),
    "xchain_match::Tracer._get": (CASSETTE, ""),
    "xchain_match::Tracer._post": (CASSETTE, "솔라나 메서드(sol_open 갈래)"),
}

EXTRA = ("bf_engine::http_request[key]", "recon::_rpc[direct]", "ton_watch::TonClient.req[key]")


def cassette_sites() -> list:
    return [k for k, (kind, _n) in SITES.items() if kind in (CASSETTE, ALLOW)] + list(EXTRA)

# 증권사 보유 동기화 (기타 자산 탭) — ★미검증★

> **미검증 — 공개 문서만 보고 작성, 실제 계정으로 시험 안 함(완벽하지 않음)**
>
> 이 폴더의 어댑터는 각 증권사가 공개한 개발자 문서·공식 예제만 보고 짰고, 실제 계정·키로 한 번도 호출해 보지 않았습니다.
> 시험은 문서에 적힌 응답 모양 그대로 만든 가짜 응답으로만 했습니다(개발용 시험 — 공개판에는 포함하지 않음).
> 실제로 켜면 필드 이름·연속 조회·오류 코드가 문서와 달라 실패할 수 있습니다 — 처음 켤 때는 화면(설정 › 증권사 연결)의 상태 줄을 확인하세요.

## 하는 일 / 안 하는 일

- **읽기만**: 보유 종목(코드·수량·평균단가·현재가·통화)과 예수금(선택)을 가져와 기타 자산의 **시세 자동 주식 항목**으로 넣습니다(증권사 표시).
  이후 평가액은 다른 주식 항목과 같이 공개 시세(야후, 15분 지연)로 갱신하고, 수량은 다음 동기화가 덮어씁니다. 그 증권사에서 사라진 종목은 지웁니다.
- **주문·정정·취소·이체 코드는 없습니다**(시험이 소스에서 주문 경로·주문 tr 코드가 없는지 검사합니다).
- **비밀**(앱 키·시크릿·토큰·계좌번호)은 로그·화면 응답·`state/` 파일에 남기지 않습니다. 토큰은 서버 프로세스 메모리에만 있고, 상태 줄의 오류는 HTTP 상태 코드와 일반 분류만 남깁니다(증권사 응답 본문·오류 코드는 토큰·시크릿이 섞일 수 있어 싣지 않음 · 설정값·발급 토큰은 한 번 더 `***` 로 지움). 리다이렉트(3xx)는 따라가지 않고 오류로 봅니다(인증 헤더가 다른 주소로 새지 않게).
- 동기화 주기 = 1시간(`config.json` → `"other_assets": {"broker_every_sec": 3600}`). 켠 증권사만 부릅니다.

## 설정 (`config.json`)

기본은 모두 꺼짐(`"enabled": false` 또는 항목 없음). 켠 뒤 서버(tj-web)를 다시 시작해야 반영됩니다.

```json
"brokers": {
  "kis":    {"enabled": false, "app_key": "", "app_secret": "", "account": "12345678-01", "paper": false, "overseas": true, "overseas_exchanges": ["NASD"]},
  "kiwoom": {"enabled": false, "app_key": "", "secret_key": "", "mock": false, "us": false},
  "ls":     {"enabled": false, "app_key": "", "app_secret": "", "overseas": false},
  "dbsec":  {"enabled": false, "app_key": "", "app_secret": "", "overseas": false},
  "toss":   {"enabled": false, "client_id": "", "client_secret": "", "account_seq": "", "cash": false},
  "alpaca": {"enabled": false, "key_id": "", "secret_key": "", "paper": false},
  "ibkr":   {"enabled": false, "gateway_url": "https://localhost:5000/v1/api", "account_id": ""},
  "schwab": {"enabled": false, "app_key": "", "app_secret": "", "refresh_token": ""}
},
"other_assets": {"quotes": true, "quote_every_sec": 900, "broker_every_sec": 3600}
```

| 키 | 증권사 | 필수 필드 | 선택 필드 | 공개 문서 | 무엇을 부르나 |
|---|---|---|---|---|---|
| `kis` | 한국투자증권 KIS Developers | `app_key` `app_secret` `account`(계좌 8자리-상품코드 2자리) | `paper`(모의) `overseas`(기본 true) `overseas_exchanges`(기본 실전 `["NASD"]`=미국 전체) | https://apiportal.koreainvestment.com/apiservice · https://github.com/koreainvestment/open-trading-api | 토큰 `POST /oauth2/tokenP` · 국내 잔고 `GET /uapi/domestic-stock/v1/trading/inquire-balance`(TTTC8434R / 모의 VTTC8434R, output1 `pdno·prdt_name·hldg_qty·pchs_avg_pric·prpr`, output2 `dnca_tot_amt`, 연속 tr_cont+CTX_AREA_FK100/NK100) · 해외 잔고 `GET /uapi/overseas-stock/v1/trading/inquire-balance`(TTTS3012R / VTTS3012R, `ovrs_pdno·ovrs_cblc_qty·pchs_avg_pric·now_pric2·tr_crcy_cd`) |
| `kiwoom` | 키움증권 REST API | `app_key` `secret_key` | `mock`(모의 — 국내만) `us`(미국 주식 잔고) | https://openapi.kiwoom.com/guide/apiguide?jobTpCode=08 | 토큰 `POST /oauth2/token`(token·expires_dt) · `POST /api/dostk/acnt` api-id `kt00018`(acnt_evlt_remn_indv_tot `stk_cd·stk_nm·rmnd_qty·pur_pric·cur_prc`, cont-yn/next-key) · `kt00001`(`entr`) · 미국 `POST /api/us/acnt` api-id `ust21070`(result_list `stk_cd·frgn_stk_nm·poss_qty·frgn_stk_book_uv·now_pric·crnc_code`) |
| `ls` | LS증권 OpenAPI | `app_key` `app_secret` | `overseas` | https://openapi.ls-sec.co.kr/apiservice | 토큰 `POST /oauth2/token`(form, scope=oob) · `POST /stock/accno` tr_cd `t0424`(OutBlock1 `expcode·hname·janqty·pamt·price`, OutBlock `sunamt1`, 연속 cts_expcode) · 해외 `POST /overseas-stock/accno` tr_cd `COSOQ00201`(OutBlock4 `ShtnIsuNo·JpnMktHanglIsuNm·AstkBalQty·FcstckUprc·OvrsScrtsCurpri·CrcyCode`, OutBlock3 `FcurrDps`) |
| `dbsec` | DB증권 OpenAPI | `app_key` `app_secret` | `overseas` | https://openapi.dbsec.co.kr/apiservice | 토큰 `POST /oauth2/token`(form, scope=oob, 1분 1회) · 국내 `POST /api/v1/trading/kr-stock/inquiry/balance`(Out1 `IsuNo·IsuNm·BalQty0·NowPrc·BookUprc` — 평균가 필드는 문서 표에 없어 확인 안 됨) · 예수금 `.../acnt-deposit`(`DpsBalAmt`) · 해외 `POST /api/v1/trading/overseas-stock/inquiry/balance-margin`(Out2 `SymCode·AstkHanglIsuNm·AstkExecBaseQty·AstkAvrPchsPrc·AstkNowPrc·CrcyCode`) |
| `toss` | 토스증권 Open API | `client_id` `client_secret` | `account_seq`(비우면 첫 위탁 계좌) `cash`(주문가능금액을 현금으로) | https://developers.tossinvest.com/docs · https://openapi.tossinvest.com/openapi-docs/latest/openapi.json · 출시 안내 https://corp.tossinvest.com/ko/news-room/detail?id=52615 | 토큰 `POST /oauth2/token`(form client_credentials) · `GET /api/v1/accounts`(`accountSeq`) · `GET /api/v1/holdings` 헤더 `X-Tossinvest-Account`(items `symbol·name·marketCountry·currency·quantity·averagePurchasePrice·lastPrice`) · `GET /api/v1/buying-power?currency=`(`cashBuyingPower`) |
| `alpaca` | Alpaca | `key_id` `secret_key` | `paper` | https://docs.alpaca.markets/reference/getallopenpositions · https://docs.alpaca.markets/reference/getaccount-1 | `GET /v2/positions`(`symbol·qty·avg_entry_price·current_price·side·asset_class`) · `GET /v2/account`(`cash·currency`) |
| `ibkr` | Interactive Brokers (Client Portal Web API) | 없음(게이트웨이 로그인) | `gateway_url`(localhost 만) `account_id` | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/ | `POST /iserver/auth/status` · `GET /portfolio/accounts` · `GET /portfolio/{id}/positions/{page}`(`ticker·name·position·avgPrice·mktPrice·currency·assetClass`) · `GET /portfolio/{id}/ledger`(`cashbalance`) |
| `schwab` | Charles Schwab Trader API | `app_key` `app_secret` `refresh_token` | — | https://developer.schwab.com/products/trader-api--individual (로그인 뒤에만 보임) | 토큰 갱신 `POST https://api.schwabapi.com/v1/oauth/token`(Basic, refresh_token) · `GET /trader/v1/accounts?fields=positions`(`securitiesAccount.positions[]·longQuantity·averagePrice·marketValue·instrument.symbol·assetType`, `currentBalances.cashBalance`) |

### 증권사별 주의 (문서에서 확인한 것)

- **한국투자증권**: 토큰은 하루 유효·1분에 1번만 발급·**발급할 때마다 알림톡**이 갑니다 → 서버가 메모리에 캐시합니다(재시작하면 한 번 다시 받음). 해외 종목명 필드(`ovrs_item_name`)는 공식 매핑에서 확인 못 해 없으면 코드로 표시합니다.
- **키움**: 허용 IP(최대 10개)를 먼저 등록해야 하고, 계좌는 앱 키에 묶여 요청에 계좌번호가 없습니다. 숫자는 0 채운 부호 문자열("-000000084300")입니다. 모의 도메인은 국내만.
- **LS·DB**: 계좌는 앱 키에 묶임. DB 토큰은 1분 1회. LS 토큰 만료 필드 이름이 문서 표(`expire_in`)와 예시(`expires_in`)가 달라 둘 다 받습니다.
- **토스**: **클라이언트당 유효 토큰은 1개 — 새로 받으면 이전 토큰이 즉시 무효**입니다. 같은 client_id 를 다른 프로그램과 함께 쓰지 마세요. 허용 IP 밖에서는 403 입니다(WTS 설정 › Open API › 허용 IP 관리). 예수금 API 는 없어 `cash: true` 면 주문가능금액(`cashBuyingPower`)을 현금으로 넣습니다.
- **IBKR**: 같은 기기에서 게이트웨이를 띄우고 브라우저로 로그인해야 합니다(하루 1번 다시 인증). 맥은 5000 포트가 다른 앱과 자주 겹쳐 `gateway_url` 로 바꿉니다. 자체 서명 인증서라 localhost 에서만 인증서 검사를 끕니다.
- **슈왑**: 개발자 포털 문서가 로그인 뒤에만 보여 경로·필드는 공개 커뮤니티 자료와 맞춘 것뿐입니다(가장 불확실). refresh_token 은 승인 뒤 7일이면 만료돼 브라우저로 다시 승인하고 config 를 바꿔야 합니다(이 코드는 새 토큰을 저장하지 않습니다).

## 다루지 않는 것

- **Windows 전용 COM/OCX/DLL API** — 맥·리눅스 서버에서 돌릴 수 없어 제외: 대신증권 **CYBOS Plus**(COM, 32비트), NH투자증권 **QV OpenAPI**(DLL), 키움 **OpenAPI+**(OCX), LS증권 **xingAPI**(COM/DLL). (키움·LS 는 위의 REST API 로 다룹니다.)
- **개인용 공개 REST API 를 찾지 못한 곳(2026-10 조사)**: 삼성증권(코스콤 오픈플랫폼 경유만), 미래에셋증권, 신한투자증권(Windows 클라이언트 신한i Indi 뿐).
- **새로 생겼지만 아직 어댑터 없음**: KB증권(2026-07 개인 오픈 베타 https://openapi.kbsec.com), NH투자증권 PLUG(2026-08 개인 REST — 포털 주소 미확인), 메리츠증권(REST 베타 https://github.com/meritz-securities/open-api). 문서가 확인되면 같은 틀(`base.Adapter`)로 추가할 수 있습니다.

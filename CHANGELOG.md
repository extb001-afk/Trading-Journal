# 변경 내역 (Changelog)

판마다 더해진 것과 바뀐 동작이에요. 지금 쓰는 법은 [README.md](README.md), 화면 사진은 README 의 '화면 미리보기'에 있어요.
업데이트는 README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js`) 하세요.

## 2026-10-22 — 코인베이스 · 바이낸스 배당 · 설명 안 된 보정 감시 · 외부 검수 버그 수정 · 내부 구조 정리

**코인베이스 거래소와 바이낸스 배당·에어드랍 지급 내역을 받고, 실잔고 대사가 메운 '설명 안 된 보정'을 상태 패널에 보여요 — 외부·자체 검수에서 나온 버그를 고치고, 코드·문서 구조를 정리했어요(구조 정리 몫은 숫자 그대로)**

외부 검수 한 건과 자체 검수의 지적을 하나씩 재현해 고친 판이에요. 지운 서브계정 잔고가 거짓 대사를 만들던 것, 백업 복구가 거래소 수집 위치를 되감지 않던 것, 네이티브 잔고를 그대로 비추는 시스템 토큰 때문에 네이티브가 두 번 잡히던 것, 스테이블 원가가 추정 짝으로 넘어가던 것 등이에요.
그동안 큰 파일을 맡은 일별로 나누고 README 를 `docs/` 로 나눴어요. 이 정리는 단계마다 원장 사본으로 결과를 대조해 차이가 0 이었어요.
사진은 다시 찍지 않았어요 — 지금 화면은 코인 로고 대신 글자 아이콘이고, 곡선 범례에 '안 팔았다면' 칩이 없고, 설정 요약의 거래소 수가 코인베이스를 더해 8곳이에요([화면 미리보기](docs/SCREENS.md#화면-미리보기) 안내).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로 하세요. 모든 유닛이 다시 켜져요(`pm2 start ecosystem.config.js` · 유닛 수는 그대로). 재구축·데이터 개정은 없어요.
> **HTTPS 로 여는 경우(터널·리버스 프록시)는 업데이트 뒤 한 번 다시 로그인**해야 해요. 로그인 쿠키 이름이 `__Host-tj_session`(등록 기기 쿠키 `__Host-tj_device`)으로 바뀌어 옛 쿠키를 읽지 않아요. `http://127.0.0.1` 로 여는 경우는 그대로예요.
> 문서가 나뉘었어요. README 엔 처음 안내와 [문서 지도](README.md#문서-지도)만 남고, 설치·기능·설정·운영·화면·보안은 `docs/` 의 파일로 옮겼어요(내용은 그대로 · 지난 항목의 README 링크도 새 자리로 고침 · 알려진 한계 목록은 [docs/OPERATIONS.md › 알려진 한계](docs/OPERATIONS.md#알려진-한계)).
> 원가 규칙 고침(아래 '원가')과 바이낸스 배당 반영 때문에 실현·미실현 손익이 조금 바뀔 수 있어요(수량·총자산 수량은 그대로).
> 서버 밖 백업(`backup.offsite` · 기본 꺼짐)을 쓰면, 이제 묶음 목록에 열쇠 서명(HMAC)이 붙어요. 열쇠 `state/backups/offsite_auth.key` 사본을 서버 밖에 보관하세요(`offsite_backup.py auth-key --export <파일>`). 서명 없는 옛 묶음을 열 때는 `--allow-unsigned` 를 붙여요.
> 되돌릴 땐 업데이트 전 백업으로 되돌리는 게 가장 안전해요. 이 판은 원장에 새 종류의 기록(바이낸스 배당 소득 · 코인베이스 · 보정 이유)을 넣어요.

- **코인베이스(새 거래소)** — CDP API 키(ECDSA · **View 권한만**)로 잔고·현물 체결·입금·출금·송금·간편 전환·USDC 리워드·토큰 세일을 받아요. 공개 시세·일봉도 써요.
  설정 › 거래소 › 코인베이스 두 칸(키 이름 · 비밀키 PEM 통째로)에 붙여넣거나 `.env` 의 `TJ_COINBASE_KEY_NAME`·`TJ_COINBASE_SECRET` 에 넣으면 돼요. 저장할 때 Trade·Transfer 권한이 켜진 키는 거부해요.
  키 받는 법은 [코인베이스 키](docs/API_KEYS.md#코인베이스-키-cdp-api-키--조회-전용), 받는 범위·못 받는 것은 [수집 한계 › 코인베이스](docs/COLLECTION_LIMITS.md#코인베이스)에 있어요. 코인베이스 사용자끼리 보낸 송금은 체인 txid 가 없어 지갑과 잇지 못하고, 선물·국제 계정은 받지 않아요.
- **바이낸스 배당·에어드랍·런치풀·Earn 이자** — 같은 조회 키로 지급 내역을 받아 받은 시각 시가로 소득을 적어요(스테이킹 보상과 같은 규약 · 추가 권한 필요 없음 · 주기마다 1콜).
  지급 뒤 잔고 대사가 이미 메운 몫은 그 보정 줄을 소득 줄로 바꿔요(두 번 세지 않음). 나중 대사가 지급 앞 시각으로 찍은 보정도 지급 시각 이후에 만든 것이면 바꿔요.
  토큰 교환·개명 분배는 빼요(잔고 대사). 끄려면 `config.json` 에 `exf.binance_dividends: false` 를 넣으세요([수집 한계 › 바이낸스](docs/COLLECTION_LIMITS.md#바이낸스)).
- **설명 안 된 보정 감시(새)** — 실잔고 대사가 원장과의 차이를 메운 보정 줄마다 이유를 기록하고, 규칙으로 설명되는지 판정해요. 규칙은 스팸·$1 미만·부채 이자·선물 정산·늦은 행 상쇄·14일 안 ±상쇄 쌍·창 시작 기초 잔고·알려진 미수집 같은 것이에요.
  상태 패널 '보정 감시'의 **빨강**은 버그 꼴이에요(금액 무관 · 텔레그램). 창보다 이른 원장 행을 되받는 기초 잔고, 네이티브 잔고와 수량이 같은 토큰, 같은 칸에서 하루 3쌍 이상 ±로 뒤집히는 것이 여기에 들어요.
  **노랑**은 7일 안 한 줄 $500 이상이거나 그 장소 평가액의 2% 이상일 때예요. 7일 합이 $1,000 이상이면 텔레그램이 한 번 와요.
  해외 거래소 대사 알림은 이제 설명 안 된 보정만 금액과 함께 보내요. 빨강 줄의 원인 글은 버그 꼴 문구만 써요(미수집 안내가 섞이지 않음). 감시는 원장 값을 바꾸지 않아요.
  이전 판이 이미 넣은 이 꼴의 보정 줄은 저절로 고쳐지지 않고 빨강으로 보여요([보정 감시](docs/OPERATIONS.md#보정-감시--설명-안-된-보정)).
- **거래소 서브계정** — 지운 서브계정의 마지막 잔고가 거짓 대사 보정을 만들던 것을 고쳤어요. 그 몫이 0 이면 기록을 지우고, 아니면 그 거래소 대사를 보류하고 패널에 보여요.
  같은 서브 칸에 다른 계정 키를 넣으면 계정 UID·키 지문으로 다른 계정으로 알아보고 이력을 따로 받아요. 이전 판에 저장한 칸은 처음 바꿀 때 지금 계정으로 봐요.
  계정 모드 전환 중에 선물 정산 이력이 줄던 것도 고쳤어요. 업비트 잔고 경합은 1분 뒤 다시 확인해요.
- **백업 · 복구** — `tools/ledger_restore.py` 로 되돌리면 서브계정·거래소 수집 위치도 백업 시점으로 되감아, 그 사이 기록을 다시 받아요.
  같은 분에 다시 한 백업이 정상 복구 지점을 덮던 것을 고쳤어요. 서버 밖 백업은 원격 마지막 묶음보다 원장이 크게 작거나 자료 시각이 이르면, 보내기·회전을 멈춰 정상 묶음을 지우지 않아요(맞으면 `run --force --allow-regress`).
- **거래소 수집 경계** — OKX 초 경계 쪽에서 체결을 놓치던 것, 수집 기간 시작보다 이른 입출금 행이 들어오던 것(이제 버림), 선물 첫 조회 창의 거래소별 보존 한도, 바이낸스 마진 페어, 빗썸 경계를 고쳤어요.
- **체인** — Polygon 의 POL 토큰 주소·Celo GoldToken·Metis 토큰처럼 네이티브 잔고를 그대로 보여 주는 시스템 토큰을 토큰으로 세어 네이티브가 두 번 잡히던 것을 고쳤어요. 이제 토큰 대사·발견에서 빼요.
  Solana 에서 읽지 못하는 거래는 격리하고, 그 계정의 새 스테이크 기초 잔고는 보류해요.
  지갑 등록 때 상식 검사를 해요. 컨트랙트 주소이거나 잔고가 비상식적으로 크면 확인을 받고 저장해요(노드 실패는 막지 않고 경고만).
- **가격** — 거래량 0 인 평평한 봉 시세는 쓰지 않아요. 수수료·이자의 시가는 그 시각 ±1시간 봉으로 잡아요. 과거 출금 수수료의 그 시각 시가를 모르면 이제 지금 시세로 대신하지 않아요(비용 0 · 수량만).
  업비트 개시 전 마켓 때문에 입금 코인 평가가 0 이 되거나, 같은 묶음의 다른 코인 시세가 멈추던 것을 고쳤어요.
  원화 마켓이 없는 코인의 대체 가격은 24시간 거래대금이 가장 큰 거래소를 써요. 거래소끼리 1.5배 넘게 다르면 상태 패널에 주황으로 떠요.
  얇은 풀 시세가 확인값의 5배 넘게 튀면 거르고, 한 거래소가 답하지 않아도 다른 거래소 시세는 늦어지지 않아요. 오픈시 키가 있으면 오픈시가 지원하는 체인의 NFT 바닥가는 오픈시만 써요.
- **원가** — CCA 환급·브리지에서 스테이블 원가가 추정 짝으로 넘어가던 것을 고쳤어요. 이제 짝이 ID 로 확정된 경우만 원가를 넘겨요. 수수료 리베이트를 실현에 넣고, 이자·브리지 수수료 처리도 바로잡았어요.
  자산 변동 분해의 '나머지'가 크게 나오던 것을 고쳤고, '사고판 분(→실현)'을 누르면 코인별 상세(판 돈 − 원가 = 실현 · 그날 산 몫 · 기존 보유 몫)가 보여요.
- **화면** — 계획 저장이 저장 안 한 메모·새 입력을 지우던 것을 고쳤어요. 기타 자산 저장 응답이 다른 자산 폼을 지우거나 늦은 조회가 최신 화면을 덮던 것, 로그인이 풀린(401) 뒤 민감한 확인 창이 남던 것도 고쳤어요.
- **보안 · 개인정보** — 화면 보안 정책(CSP)을 이제 강제해요. 스크립트는 같은 출처 파일과 해시로 고정한 인라인만 · Trusted Types · 이미지·연결은 같은 출처만이에요.
  **코인 로고는 받지 않아요**(글자 아이콘만 · 외부 요청 0 · `web.token_logos` 는 효과 없음). **Rabby 지갑 보강은 기본 꺼짐**이에요(`rabby.enabled: true` 로 켜면 내 EVM 주소가 외부로 나가요 · 켠 경우 평가가 크게 다른 지갑은 하루마다 다시 조회).
  세션 CSRF 를 쓰고, 등록 기기는 로그인 시도를 따로 세어요(밖에서 전역 잠금을 채워도 주인은 로그인돼요). 키 헤더를 실은 요청은 리다이렉트를 따라가지 않아요.
- **설정 점검 · 계산 감시** — 기동 때 `config.json` 을 선언표와 대조해, 모르는 키·형이 다른 값을 로그 경고 한 줄로 알려요(키 이름·이유만 · 값은 종전처럼 씀 · 지우지 않음 · [고급 설정](docs/CONFIG.md#고급-설정)).
  돈 계산 경로에서 넘긴 예외에는 이유 코드를 달았어요. 계산 오류 감시에 의심 꼴 노랑을 더했어요.
- **내부 구조 정리(동작 그대로)** — 공용 모듈 `src/common.py` 를 맡은 일별(`paths`·`timeutil`·`envfile`·`statefile`·`net_http`·`chaincatalog`·`token_tables` 등)로 나누고 지웠어요.
  원장 엔진의 큰 묶음은 서비스 객체(거래소·대사·시세)로 바꿨어요. 원가 쓰기, 원장 쓰기 SQL, 수집기 기록 계약, 서명 공식, 전송 끝단을 각각 한 곳으로 모았어요.
  화면은 DOM 쓰기를 `tjdom.js` 한 곳에 모으고, CSS 를 `app.css`·`mods.css`·`wow.css`·`login.css` 로 나눴어요. 쓰기 요청(POST)은 경로 표 하나로 처리해요.
  옮기는 동안 단계마다 원장 사본으로 빌드 결과·원장 재생·화면(픽셀)을 대조했어요(차이 0).

**함께**

- **문서** — README → `docs/`([설치](docs/INSTALL.md) · [기능](docs/FEATURES.md) · [설정](docs/CONFIG.md) · [운영](docs/OPERATIONS.md) · [화면](docs/SCREENS.md) · [보안](docs/SECURITY_DATA.md) · [English](docs/README_EN.md)).
  설정 선언표는 코드에서 자동 생성돼요. 코인베이스 키, 바이낸스 배당, 서버 밖 백업 열쇠 안내를 더했어요.
- **시험** — 공개 시험 파일 이름을 기능별로 바꿨어요(예 `test_s22_readable.py` → `test_settings_readable.py` · `test_s22_eval_auto_retry.py` → `test_receipt_eval_auto.py`).
  재현 시험·경합 시험·불변식 시험을 더했어요(공개 시험 467파일).

**English** — Coinbase support: a CDP API key (ECDSA, View only — keys with Trade/Transfer are refused) reads balances, spot fills, deposits/withdrawals, conversions, USDC rewards and token sales.
Binance dividends, airdrops, Launchpool and Earn interest come from the payout history and are booked as income at the time's price. Balance-reconciliation adjustments that already covered a payout are replaced, not double counted.
A new "unexplained adjustment" monitor records why each reconciliation adjustment was made. The status panel shows bug-shaped ones in red (pre-window rows, tokens mirroring the native balance, repeated flips) and large unexplained ones in yellow, with Telegram for red and for $1,000 or more in 7 days.
Fixes from an external review and our own review cover: deleted or reused sub-account slots, restore rewinding exchange cursors, OKX second-boundary pages, native-mirror system tokens (Polygon POL, Celo, Metis), stablecoin cost carried by guessed matches, fee rebates, zero-volume candles, and form-save races in the UI.
Over HTTPS the login cookies are now `__Host-` prefixed, so you sign in once more after updating. CSP is enforced, coin logos are no longer fetched (letter icons), and the Rabby lookup is off by default.
README is split into `docs/` (known limitations moved to `docs/OPERATIONS.md`). Test files are renamed by feature. The internal restructuring was verified against ledger replays (no differences). All units restart; no rebuild or data revision. Screenshots were not retaken.

## 2026-10-16 — 거래소 서브계정 키 · Alchemy 한도 초과 알림 · 내부 구조 정리

**해외 거래소 서브계정을 같은 거래소로 합쳐 세고, Alchemy 키가 계속 거절되면 알려요 — 계산 결과는 그대로(코드 구조만 정리)**

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로 — 모든 유닛이 다시 켜져요(`pm2 start ecosystem.config.js`). 재구축·데이터 개정은 없어요.
> 브라우저가 옛 화면 파일을 들고 있으면 새로고침 한 번이면 돼요(화면 파일 주소에 판 표시가 붙어 보통은 저절로 새로 받아요).

- **거래소 서브계정 키** — 바이낸스·바이빗·OKX·쿠코인·게이트는 거래소마다 서브계정 키를 5개까지 더 넣을 수 있어요(설정 › 연결·키 › 거래소 칸 **서브계정 키 추가**,
  또는 `.env` 의 `TJ_<거래소>_SUB<번호>_…` — [API 키 받는 법](docs/API_KEYS.md#거래소-키)). 서브 몫의 잔고·체결·입출금·선물은 **같은 거래소로 합쳐** 세고,
  기록 줄·선물 화면(정산 목록·선물 손익 명세·수수료·펀딩·포지션)에만 `· 서브1` 딱지가 붙어요. 권한 확인·연결 시험은 메인 키와 같아요(조회 권한만).
  바이빗·OKX 서브는 거래소가 입금 주소를 주지 않아 입금 주소 목록엔 메인만 보여요 · 서브 키를 지우면 그 서브의 마지막 잔고는 그대로 남아요.
- **Alchemy 한도 초과·키 거절 알림** — 월 용량 초과·결제 필요(402)·키 거부(401·403)로 성공 없이 계속 거절되면(2번 이상 · 1분 넘게) 상태 패널에 주의가 뜨고
  텔레그램이 한 번 와요(풀리면 한 번 더). 잠깐 실패(초당 한도·서버 오류·시간 초과)는 세지 않고, 키 값은 어디에도 남기지 않아요. 수집·감시는 종전처럼 무료 노드로 이어져요.
- **숫자 계산 오류를 조용히 넘기지 않아요** — 원가·손익·잔고 계산 중 코드 실수 꼴의 오류(이름·형식 오류 등)가 나면, 화면은 계속 돌되 상태 패널에 빨강
  '계산 코드 오류를 삼킴 — 숫자가 틀렸을 수 있음'(어느 계산이 몇 번)으로 보이고 텔레그램이 와요. 데이터 이상으로 넘어간 예외는 상태 패널 정보 줄(하루 안 · 알림 없음)에 세어 보여요.
  해외 거래소 체결 중 형식이 이상한 것(수량 0·방향 모름·시각 없음)은 원본은 그대로 보관하고, 기장에서 빠진 것을 로그와 그 정보 줄에 남겨요(종전 = 말없이 빠짐).
- **원가 계산 방식 안내** — README 맨 위와 새 절 [원가 · 손익 계산 방식](docs/FEATURES.md#원가--손익-계산-방식)에 평단(이동평균)·실현·미실현·수수료·원화 환산·원가 미확인을 정리했어요.
  쓰면서 맞지 않던 설명을 바로잡았어요 — 평단 묶음은 '같은 코인이면 하나'가 아니라 체인 기본 코인(공식 랩 토큰 포함)·정품 스테이블만 체인을 넘어 한 묶음이고,
  그 밖 토큰은 컨트랙트마다, 거래소 보유는 거래소·코인마다 따로예요(명세 › 원가 방식 도움말 문구도 같이 고침 · 계산은 그대로).
- **내부 구조 정리(동작 그대로)** — 큰 파일들을 맡은 일별 모듈로 나눴어요: 화면(`web/v2/app.js` → 공용 뼈대 + 화면 파일 `tab_*.js` 7개),
  서버(원가 엔진 `accounting_*` · 화면 응답 `view_*`·`http_*` · 수집기 `evm_*`·`bsc_*`·`sol_*`·`exf_*` · 상태 점검 `chk_*` 등).
  옮기는 동안 실원장 사본으로 빌드 결과·원장 재생 결과가 바뀌지 않는지 단계마다 대조했어요(차이 0) — 숫자·화면은 그대로예요.

## 2026-10-13 (2) — 양도차익 명세 '수수료로 쓴 코인' 하루 한 줄

**같은 날 같은 코인으로 낸 수수료 처분을 명세에서 한 줄로 묶었어요 — 금액·실현은 그대로**

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로 — 화면·웹 파일만 바뀌어 `tj-web` 만 다시 켜면 돼요. 재구축·데이터 개정은 없어요.

- **'수수료로 쓴 코인(처분)' 하루 한 줄** — 매수 수수료를 산 코인에서 떼는 거래소(예: 게이트)에서 잘게 나눠 사면 체결마다 명세 한 행이 생겨
  한 달 한 종목이 수백 행이 됐어요(예: 하루 178행 · 합쳐 손익 몇 센트). 이제 같은 날·같은 코인 수수료 처분은 한 줄('N건 묶음')로 보이고 '명세 행'도 날짜 수로 세요.
  원화 양도·취득가액은 건마다 그때 환율로 계산한 값을 그대로 더해요(묶어도 숫자 그대로). 스테이블(USDT·USDC 등) 수수료 처분은 처분마다 환차 상세가 있어 종전처럼 건별이에요.

## 2026-10-13 — '안 팔았다면' 비교선 잠시 숨김

**총자산 곡선의 '안 팔았다면' 버튼을 숨겼어요 — 'BTC 만 들고 있었다면'은 그대로**

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로 — 화면 파일만 바뀌어 `tj-web` 만 다시 켜면 돼요. 재구축·데이터 개정은 없어요.

- **'안 팔았다면' 숨김** — 이 비교선은 판 코인의 지금 시세가 있어야 계산되는데, 시세는 지금 들고 있는 코인만 매일 받아요. 팔고 1주가 지나면 시세가 없어
  선이 실제 곡선과 거의 붙거나 엉뚱한 차이를 보였어요. 판 코인 시세를 따로 받을 방법을 정할 때까지 버튼을 숨겨요(예전에 켜 둔 기기도 꺼짐 · 계산 코드는 남겨 둠 · 고쳐서 다시 넣을 예정).
  사진(대시보드 비교선)엔 버튼이 아직 보여요.

## 2026-10-12 (7) — 외부 재검수 잔여 2건(빗썸 첫 대사 전 코인 · Solana 스테이크 조회 실패·순서) · 최초 잔고 30분 안내

**(6) 판 외부 재검수에서 남은 첫 대사 전 표시 2건을 최소 수정 — 원장·원가·실현·신고용 명세는 그대로**

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로 — `tj-core`·`tj-exf`·`tj-web`·`tj-review` 가 다시 켜져요. 재구축·데이터 개정은 없어요.

- **빗썸 첫 대사 전 '지금 잔고' 코인** — 주문 하나가 잔고 스냅숏 앞뒤로 나눠 체결되면, 첫 대사 전 코인 칸이 주문 전체를 마지막 체결 시각으로 견줘
  코인을 더 세거나(매수) 덜 셌어요(예: 50개 → 70·30개). (6) 판에서 원화를 고치며 서로 상쇄되던 오류가 드러난 것 — 이제 체결 기록에 개별 체결 수량도 남겨,
  첫 대사 전 비교에서만 그 주문을 체결 시각별로 나눠요(원장·지난날 곡선 그대로). 개별 수량이 없는 기록이 스냅숏을 가로지르면 그 코인은 이번엔 원장 그대로 둬요.
- **Solana 스테이크 칸** — 스테이크 지금 잔고를 지갑 조회 바로 앞에 읽어요(종전 = 토큰 조회 수 분 뒤라 그 사이 이동이 0·두 배로 보일 수 있었음) ·
  다시 읽기가 실패하면 그 바퀴 Solana 임시 잔고를 쓰지 않고 다음 바퀴에 다시 읽어요(오래된 스테이크 값과 지금 지갑 값을 섞지 않음).
- **가스 반영 끔 문구** — 꺼도 거래소 체결 수수료는 원가·실현에 그대로라는 점을 설정 화면에 적었어요(계산은 그대로).
- **최초 잔고 안내** — 새 설치에서 큰 몫은 보통 몇 분 안, 최초 잔고가 다 보이기까지는 30분쯤(README 첫 실행 표 · 옛 기록 절).

## 2026-10-12 (6) — 외부 검수 표시 정합성 3건(빗썸 부분 체결 · 첫 대사 전 전송 중 · Solana 스테이크)

**(5) 판에서 새로 생긴 '지금 잔고' 경로의 표시 오류 3건을 최소 수정 — 원장·원가·실현·신고용 명세는 그대로**

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` → `pm2 save`) —
> `tj-core`·`tj-exf`·`tj-web` 과 공통 모듈을 쓰는 유닛이 다시 켜져요. 재구축·데이터 개정은 없어요.

- **빗썸 원화 예수금 — 부분 체결이 잔고 스냅숏을 가로지를 때** — 주문 하나가 스냅숏 앞뒤로 나눠 체결되면 주문 전체 원화를 마지막 체결 시각에 두고 굴려
  스냅숏에 이미 든 몫까지 다시 셌어요(예: 10만원 → 매수 8만원 · 매도 12만원으로 다음 스냅숏까지). 이제 주문 상세의 개별 체결 시각·금액을 체결 기록에 함께 남기고,
  지금 원화는 스냅숏 뒤 체결분만 굴려요(원화 수수료는 체결액 비례 · 합은 주문과 같음). 개별 체결 정보가 불완전하거나 이 판 전 기록이면 종전대로(다음 스냅숏에서 풀림) ·
  지난날 곡선은 코인 기장과 맞게 주문 단위 그대로예요.
- **받는 거래소 첫 대사 전 '전송 중'** — 받는 거래소 스냅숏 앞뒤 60초 안에 같은 통화 기록이 있어 그 통화의 '지금 잔고'를 이번에 더하지 않았는데도,
  그 거래소로 가는 '전송 중'까지 '이미 셈'으로 지워 둘 다 빠질 수 있었어요(예: 1,010 USDT → 10). 이제 '이미 셈'은 지금 잔고를 실제로 더한 통화에만 적용해요
  (지갑 → 거래소 '입금 대기'도 같음 · 이미 원장과 같은 통화는 그대로 이중 계상 방지).
- **Solana 스테이크 칸(첫 대사 전)** — 스테이크 칸은 최대 3시간 전 스테이크 목록 값이라, 그 사이 스테이크 ↔ 지갑 이동이 아직 원장에 없으면 두 번 세거나(인출) 빠졌어요(예치).
  이제 지갑 잔고와 함께 스테이크 계정의 지금 잔고를 다시 읽어요(`getMultipleAccounts` 100개당 1콜 · 공개 노드 차선 먼저) · 실패하면 종전 목록 값(스냅숏 시각 경계).

## 2026-10-12 (5) — 새 설치 지금 총자산 몇 분 안 · 빗썸 원화 예수금 · Alchemy 속도 칸

**새로 설치한 뒤 첫 화면 총자산 = 기동 몇 분 안에 지금 잔고로(옛 기록은 뒤에서 천천히) · 해외 거래소 잔고 먼저 읽기 · 거래소 '지금 잔고(옛 기록 받는 중)' ·
온체인 지금 잔고 전 체인·동시·빠른 판 · 받는 쪽이 첫 대사 전이면 '전송 중' 빼기 · 빗썸 원화 예수금 굴림 · OKX 담보대출 첫 대사 전 칸 · Alchemy 속도 칸 20 CU**

지난 판까지 새 설치는 옛 기록을 받는 동안에도 오늘 보유·총자산을 '지금 잔고'로 보여 줬지만, 그 지금 잔고가 처음 보이기까지 오래 걸렸어요 —
해외 거래소 잔고는 옛 기록(입출금·체결 · 바이낸스 전 심볼 첫 바퀴) 뒤 차례라 수십 분 뒤에야 읽혔고, 거래소는 첫 대사 전엔 원장에 들어온 몫만 보였고,
온체인은 한 번에 한 체인씩 토큰 찾기까지 끝나야 보였어요. 이번 판은 '지금 자산은 몇 분 안, 옛 기록(백필)은 느려도 됨'을 기준으로 순서를 바꿨어요.
임시 잔고는 장부에 쓰지 않고, 그 체인·거래소 첫 대사가 끝나면 원장 기초 잔고가 대신해요 — 원가·실현·신고용 명세 계산과 지난날 곡선은 그대로예요.

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` → `pm2 save`) —
> 공통 모듈이 바뀌어 대부분 유닛(`tj-core`·`tj-evm`·`tj-bsc`·`tj-sol`·`tj-ex`·`tj-exf`·`tj-web`·`tj-alert`·`tj-review`·새 체인 유닛)이 다시 켜져요.
> 재구축·데이터 개정은 없어요(업데이트만으로는 원장 쓰기 없음). 이미 첫 대사를 마친 설치엔 임시 잔고 칸이 생기지 않아요(바뀌는 건 빗썸 원화 예수금·Alchemy 속도 칸).
> 2026-10-12 (3) 보다 전 판에서 바로 올라오면 [(3) 업데이트 상자](#2026-10-12-3--화면-다듬기--외부-검수-작은-수정--ai-리뷰-전체-채우기)(`state/` 0700 · `.env` 0600)도 보세요.

- **해외 거래소 잔고 먼저 읽기** — `tj-exf` 가 매 주기 맨 먼저(옛 기록 받기 전) 키 있는 거래소 잔고를 한 번 읽어 화면 표시용 파일(`state/exf_balances_<거래소>.json.view`)만 써요 —
  대사·승격에 쓰는 정식 잔고 파일과 규칙은 그대로 · 직전 주기 끝에 표시 잔고를 쓴 거래소는 건너뛰어 평소엔 기동 첫 주기에 거래소마다 1번 더 읽는 것뿐이에요(거래소 예산·429 물러나기 그대로).
  Hyperliquid 도 표시 파일이 없거나 한 주기 넘게 낡았으면 현물을 먼저 읽어요(주소당 현물 1콜 + 되면 기본 DEX 무기한 현금·스테이킹 · 60초 마감 · 한 주소라도 실패면 쓰지 않음).
- **거래소 '지금 잔고(옛 기록 받는 중)'** — 거래소 첫 잔고 대사 전엔 그 거래소 칸 = 지금 거래소 잔고(부채 포함 · 원화·달러 제외) + 스냅숏 뒤 원장 증감(온체인 '지금 잔고'와 같은 규약) —
  보관처 줄 '거래소 지금 잔고(옛 기록 받는 중)'. 원장에 아직 없는 심볼도 행으로 보이고, 잔고보다 부채가 큰 순부채는 음수 '빌린 몫' 행으로 총자산에서 빼요.
  그 거래소 대사가 끝나면 이 몫은 0(원장 기초 잔고가 대신 · 같은 순간 둘 다 세지 않음). Hyperliquid 도 첫 대사 전엔 같은 임시 잔고(무기한 현금은 부호 그대로).
- **OKX 담보대출 첫 대사 전 칸** — 원장 그룹이 여럿인 (심볼, 거래소) 칸을 한 칸으로 모으고 빌린 몫도 화면 부채 기준으로 다시 정해요 —
  종전엔 첫 대사 전 원장의 음수 칸이 그대로 총자산에서 빠져 총자산이 크게 낮게 보일 수 있었어요.
- **온체인 '첫 대사 전 지금 잔고' — 전 체인 · 동시 · 빠른 판** — 대상에 Tron·Sui·TON·Bitcoin 도 더해 전 체인(EVM·BNB Chain·Solana 포함) ·
  첫 판은 체인마다 동시에(최대 6체인 · 노드별 속도는 계량기 그대로) '빠른 판'(원장에 있는 토큰 + 검증 스테이블 + 네이티브를 멀티콜로 · 토큰 찾기 없음) →
  끝난 체인은 기다리지 않고 Alchemy `alchemy_getTokenBalances` 로 찾는 둘째 판(지갑당 보통 1콜 · 토큰이 100개 넘는 지갑은 100개마다 1콜 더 · Alchemy 가 되는 체인 · 스팸 거르기 그대로) · 안 되는 체인은 종전 찾기 포함 판 ·
  순서 = 총자산 몫이 클 법한 체인 먼저(Ethereum·Base·Arbitrum·Solana·BNB Chain·Polygon·Optimism) → 지갑 수 · 찾기 시간 상한에 걸린 지갑은 다음 바퀴에 이어 받기 · 그 뒤로는 종전처럼 1시간마다.
  Bitcoin·TON 임시 잔고는 대사 준비 상태와 무관하게 읽고, Bitcoin 은 수집 상태에 아직 없는 설정 지갑도 읽어요(첫 저장 전 0 으로 보이지 않게).
  Solana 스테이크 칸은 스테이크 스냅숏(1시간마다) 시각까지의 원장과 견줘요 — 스냅숏 뒤 인출이 지갑 잔고와 스테이크 칸에 두 번 잡히지 않게(공개 검수).
- **Solana** — 지금 잔고를 네이티브 100개 묶음 + 토큰 계정 병렬(주 노드 4 + 공개 노드 1)로 읽고, 스테이크 계정도 넣어요(이미 받아 둔 스테이크 목록 · 추가 호출 없음 ·
  새 목록이 생기면 바로 다시) · 실패한 지갑만 보류(0 으로 보이지 않음).
- **체인 자동 켬 즉시 합류** — 활동 점검이 새 체인을 켜면 10분 주기를 기다리지 않고 바로 지금 잔고 대상에 들어와요.
- **'전송 중' 이중 계상 막기** — 받는 쪽(지갑·거래소·Hyperliquid)이 아직 첫 대사 전이고 그쪽 지금 잔고를 출금 뒤에 읽었으면, 그쪽으로 가는 '전송 중'·'입금 대기'는 총자산에 더하지 않아요
  (지금 잔고가 이미 셈 — 유령 전송 중 방지 · 받는 지갑 조회가 그 통화(네이티브·검증 스테이블 · Solana 는 전부)를 봤을 때만) ·
  기록 줄엔 '받는 쪽 옛 기록 받는 중 — 지금 잔고에 이미 반영' · 이런 출금의 미도착 알림은 '도착 확인 불가'로 둬요(옛 기록이 들어오기 전 '아직 안 들어옴' 오경보 없음).
- **빗썸 원화 예수금** — 원화 = 마지막 잔고 스냅숏 + 스냅숏 뒤 원장의 원화 증감(체결·원화 입출금 · 0 아래로 안 내려감) — 체결 직후 다음 스냅숏 전까지 '사기 전 원화'와 '산 코인'을
  함께 세던 것(판 뒤엔 판 원화가 빠지던 것)을 막아요. 업비트는 그대로(1분 스냅숏 · 열린 주문 보정은 따로).
- **Alchemy 속도 칸** — 공용 속도 칸 1칸 = 20 CU(종전 60) · 메서드별 칸 = 공식 CU ÷ 20 올림 → `alchemy_getTokenBalances` 초당 6콜(종전 2) ·
  합산 상한은 그대로 초당 240 CU·12 요청(옛 무료 300 CU/s·15 요청의 80% · 모든 프로세스 합산) · 유료 요금제를 고르면 초당 520 CU·15 요청 · 하루 몫(월 한도의 80%)은 그대로.

**함께**

- **문서** — README '이번 판'·처음 시작 6번 줄·첫 실행·알려진 한계·English · [docs/API_KEYS.md](docs/API_KEYS.md) Alchemy 초당 상한 · README 사진 20장을 이번 판 화면으로 새로(나머지는 2026-10-12 (3) 화면 그대로).
- **시험** — 공개 시험 추가(거래소 먼저 읽기·임시 잔고·순부채 행·OKX 담보대출 칸·전송 중 판정·빗썸 원화 굴림·Hyperliquid 먼저 읽기·전 체인 동시 빠른 판·Alchemy 둘째 판·Solana 묶음·Alchemy 칸) —
  전체 8,200건 넘게(파일 259개).

**English · Total within minutes on a fresh install** — On a new install, today's holdings and total now show the actual current balances within minutes of starting,
while old history keeps filling in the background. `tj-exf` reads every keyed exchange's balance first in each cycle (display file only — reconciliation files and rules are
unchanged), and Hyperliquid spot is read first too. Until an exchange's first reconciliation, its row is the current exchange balance (debts included, KRW/USD excluded) plus
ledger changes after that snapshot, including symbols the ledger does not have yet and a negative "빌린 몫" (borrowed) row for net debt; OKX collateral-loan rows no longer drag the
total down. The on-chain "current balance before first reconciliation" now covers every chain (Tron, Sui, TON and Bitcoin added), runs up to 6 chains at once with a fast pass
(ledger tokens, verified stablecoins and native coin via multicall), followed right away by an `alchemy_getTokenBalances` pass (usually one call per wallet, one more per extra 100 tokens) where Alchemy works; Solana uses
batched and parallel reads and includes stake accounts; chains switched on automatically join at once. A transfer heading to a side that is still before its first
reconciliation is not added as "in transit" (the current balance already counts it), and its arrival alert is "cannot confirm" instead of a false "not arrived".
Bithumb KRW = last balance snapshot plus ledger KRW changes after it (no double count right after a fill). The shared Alchemy gate now counts 20 CU per slot
(`alchemy_getTokenBalances` 6/s, still 240 CU and 12 requests per second in total; paid plans 520 CU/s). 20 README screenshots were retaken on this release (the rest are from 2026-10-12 (3)). No rebuild and no data revision; follow the README update
(stop everything → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` → `pm2 save` — most units restart).

**알려진 한계(새로 더한 것)** — 자세한 설명은 README [알아 둘 것](README.md#알아-둘-것) · 그 밖은 지난 판 그대로예요 — [2026-10-12 (3)](#2026-10-12-3--화면-다듬기--외부-검수-작은-수정--ai-리뷰-전체-채우기).

- 지금 잔고로 막 찾은 새 토큰은 시세가 붙기 전까지 총자산에 들어가지 않아요(실측 22~24분 · 보통 금액이 작은 토큰) — 저절로 붙어요.
- 아직 추적하지 않던 체인을 활동 점검이 자동으로 켜는 경우는 점검(기동 4분 뒤 시작)·속도 측정이 끝난 뒤라 그 체인 지금 잔고가 10분 넘게 걸릴 수 있어요.
- 업비트 원화 예수금은 굴리지 않아요(1분 스냅숏) — 체결 직후 다음 스냅숏(1분 안)까지 원화와 산 코인이 함께 보일 수 있어요.
- Hyperliquid 먼저 읽기는 HIP-3(기본 외) 무기한 DEX 현금을 빼요 — 그 몫은 주기 끝 수집에서 보여요.
- 받는 쪽이 아직 첫 대사 전이면 그쪽으로 가는 전송은 받는 쪽이 입금을 처리하기 전(거래소 입금 확인 대기 등)에 그쪽 잔고를 다시 읽은 경우 도착할 때까지 총자산에서 잠깐 빠져 보일 수 있어요 — 도착 뒤 다음 잔고 조회에서 맞춰져요(유령 '전송 중' 이중 계상을 막는 쪽을 골랐어요).

## 2026-10-12 (4) — 가스(매매 외) 줄 · 매매 가스·수수료 참고 줄

**그날 실현의 가스 줄 = '가스(매매 외)' + 바로 아래 흐린 참고 줄 '참고 · 매매 가스·수수료'(원가·손익에 포함 · 합 밖 · 표시 전용)**

지난 판(2026-10-12 (3))까지 그날 카드와 변동 분해 '현물 실현' 시트의 가스 줄은 매매 외 가스(실패·승인·전송·브릿지·LP)만 담았는데,
이름만으로는 그날 쓴 가스·수수료 전부로 읽히기 쉬웠어요. 이번 판은 그 줄 이름을 '가스(매매 외)'로 바꾸고, 매매에 든 가스·수수료(산 쪽은 원가, 판 쪽은 손익에 이미 들어 있음)는 따로 참고 줄로 보여 줘요.
화면 표시만 바뀌어요 — 실현·원가·신고용 명세는 그대로예요. README 사진은 지난 판((3)) 화면 그대로예요(이번 판 줄은 사진에 없어요).

> **업데이트** — 웹 화면만 바뀌어요: 백업 확인 → `git pull` → `pm2 restart tj-web`(다른 유닛은 그대로 둬도 돼요). 재구축·데이터 개정은 없어요(원장 쓰기 없음).
> 2026-10-12 (3) 보다 전 판에서 바로 올라오면 README [업데이트](README.md#업데이트) 순서대로 전부 하고 [(3) 업데이트 상자](#2026-10-12-3--화면-다듬기--외부-검수-작은-수정--ai-리뷰-전체-채우기)(`state/` 0700 · `.env` 0600)도 보세요.

- **가스(매매 외) 줄** — 변동 분해 '현물 실현' 시트와 그날 카드 실현 기여의 가스 줄 이름 → '가스(매매 외)'(시트 설명 '실패·승인·전송·브릿지·LP 가스 — 실현에서 뺌' ·
  그날 카드는 마우스를 올리면 '매매에 든 가스·수수료는 각 코인 원가·손익에 들어 있어요'). 줄 금액은 그대로예요.
- **참고 · 매매 가스·수수료** — 그날 '현물 실현' 시트에서 가스 줄 바로 아래 흐린 줄 하나 — [원가·손익에 포함] 칩 · '산 쪽은 원가, 판 쪽은 손익에 이미 들어 있어요 · 합에 안 들어가요' · 금액 = 그날 가스·수수료 전부 − 가스(매매 외).
  '전부' = 가스·수수료 탭과 같은 재료(온체인 가스 전부 · 브릿지 수수료 · 거래소 체결·출금 수수료)의 그날(한국 시간) 합. 이 줄은 맨 아래 합 확인 줄의 합·개수와
  막대 길이 기준에 들지 않아요(합 확인은 종전 그대로). 그날 시트에만 있고(그달 시트엔 없음 · 가스 줄이 없는 날은 목록 끝) 금액이 $0.005 미만이거나 가스 반영을 끈 설치(가스가 원가·실현 밖)에선 안 보여요.
  서버 상태에 `feeAllByDate`(날짜 → [USD, 원화])가 더해졌어요 — 이 값이 없는 옛 서버면 참고 줄 없이 종전처럼.

**함께**

- **문서** — README '이번 판'·English · 사진은 그대로((3) 화면).
- **시험** — 공개 시험 2파일에 더함(날짜별 전부 = 가스·수수료 탭 합 · 가스 스위치 켬·끔 · 매매 가스 포함 · 시트 참고 줄 위치·흐림·칩 · 합·개수 그대로) — 전체 8,100건 넘게(파일 253개).

**English · "Gas (non-trading)" line and a trading gas & fees reference line** — In the change-breakdown "현물 실현" (spot realized) sheet and on the day card,
the gas line is now named "가스(매매 외)" (gas, non-trading: failed, approvals, transfers, bridges, LP). Right below it the day's sheet shows one dimmed reference
line, "참고 · 매매 가스·수수료" (trading gas & fees), with an "included in cost/PnL" chip (buy-side fees are in cost basis, sell-side fees in PnL): the day's total gas and fees (same inputs as the gas & fees tab — all on-chain
gas, bridge fees, exchange trading and withdrawal fees, per KST day, served as `feeAllByDate`) minus the non-trading gas line. It is outside the sum check, the row
count and the bar scale, and is not shown when gas-in-cost is turned off. Display only — realized PnL, cost basis and the tax statement are unchanged. No rebuild and no data revision; `git pull` and
`pm2 restart tj-web` (coming from before 2026-10-12 (3), follow the full README update). Screenshots are from (3).

**알려진 한계** — 지난 판 그대로예요 — [2026-10-12 (3)](#2026-10-12-3--화면-다듬기--외부-검수-작은-수정--ai-리뷰-전체-채우기).

## 2026-10-12 (3) — 화면 다듬기 · 외부 검수 작은 수정 · AI 리뷰 전체 채우기

**화면 다듬기(글꼴·색·제목 통일 · 긴 설명 → 한 줄 + 자세히 · 설정 키 알약 · 수집 한계 접힘 · 누르면 위로 튀던 것) · 과거 데이터 가져오기 거래소 보존 한도 경고 · AI 리뷰 '전체 채우기' ·
인증 요청 리다이렉트 안 따라감 · 데이터 폴더·`.env` 권한 보정 · 영수증 자동 평가 · 미리 받기 오늘 영수증·`bg=1` 직접 요청 · 비활성 체인 로그 · Base 공개 노드 기본 속도**

지난 판(2026-10-12 (2)) 화면을 처음부터 다시 훑어 글꼴·색·제목을 하나로 맞추고 긴 설명문을 한 줄 + '자세히'로 줄인 판이에요(위치·배치·기능은 그대로).
같은 판을 읽은 외부 검수가 찾은 작은 문제(영수증 자동 평가 · 인증 요청 리다이렉트 · 폴더 권한)와 지난 판 알려진 한계 두 줄(미리 받기)도
재현 시험 먼저(고치기 전 실패 → 고친 뒤 통과) 가장 작은 수정으로 고쳤어요. 드문 경우는 이번엔 그대로 두고 아래 알려진 한계에 적었어요.
README 사진은 이번 판 화면으로 모두 새로 찍었어요(새 사진 4장 — 지갑 추가 체인 칩 · 과거 데이터 경고 · 변동 분해 시트 · 수집 한계).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` → `pm2 save` — 공통 모듈이 바뀌어 이번에도 모든 유닛).
> 재구축·데이터 개정은 없어요(업데이트만으로는 원장 쓰기 없음).
> 첫 기동 때 이미 있던 `state/`·`state/inbox/` 폴더가 본인만(0700), `.env` 가 본인만 읽고 쓰기(0600)로 조여져요(내 소유일 때만 · 하위 파일·심볼릭 링크는 그대로) —
> 다른 사용자 계정으로 이 폴더를 읽던 도구(백업 스크립트 등)가 있으면 봇과 같은 사용자로 돌리세요.
> 새로 생길 수 있는 것 — `state/review_fill_request.json`('전체 채우기' 요청 · `tj-review` 가 1분 안에 가져가 지움).

- **화면 다듬기** — 금액·%·개수는 고정폭 숫자 글꼴, 한글 문장은 본문 글꼴로 통일(문장 안 금액 조각만 고정폭) · 시트·패널·카드 제목 크기와 굵기, 카드 모서리, 칩 굵기를 하나로 ·
  곳곳에 직접 쓴 색을 테마 색으로(밝은 테마 포함) · 긴 설명문은 한 줄 + '자세히' — 설정 › 연결·키 칸마다 [필수|선택]·[무료 …] 알약 + 한 줄(나머지는 '자세히') ·
  노드 하루 몫 막대와 넘겨받는 순서(① Chainnodes → ② QuickNode → ③ 기본 노드) · 수집 한계의 긴 이유는 접힘 · 매매일지 '명세 기준과 차이'·M월 한눈에·보낸 내역·알림 등의 설명도 한 줄 ·
  화면 문구에서 설정 키·내부 용어를 빼고 쉬운 말로(원래 이름은 마우스를 올리면).
- **누르면 화면이 위로 튀던 것** — 설정 › 연결·키 아래쪽 줄(거래소 키 등)을 누르면 위쪽 펼침이 접히며 누른 줄이 위로 밀리던 것, 설정 마법사·확인 주기 시트가 다시 그릴 때마다 맨 위로 가던 것 →
  누른 줄 자리를 지켜요(화면 전환·단계 이동·누른 동작이 직접 굴리는 스크롤 — 달력 날짜 → 그날 카드 등 — 은 종전대로).
- **과거 데이터 더 가져오기 — 거래소 보존 한도 경고** — 설정 › 데이터 · 수집 › 과거 데이터 더 가져오기에서 고른 시작 날짜가 연결한 거래소 API 가 주는 기간보다 옛날이면 거래소별 한 줄
  (OKX 체결 = 3개월 전 달의 1일 · 바이비트 체결·손익 = 최근 730일 · 쿠코인 체결·바이낸스 선물 손익 = 약 1년 · Hyperliquid 체결 = 최근 1만 건)과 수집 한계 링크(경고만 — 가져오기는 그대로).
- **AI 리뷰 — 전체 채우기** — 설정 › AI 리뷰에 수동 몫(빠진 옛 리뷰 · 리뷰 방식이 바뀐 날)이 있으면 '전체 채우기' 단추 — 확인창(건수·순서·Claude 사용량·걸리는 시간) 뒤 요청만 남기고,
  `tj-review` 가 1분 안에 배경에서 일간 → 주간 순으로 써요(예약 리뷰를 막지 않음 · 시작한 날 앞까지만 · 도는 중 새 요청은 무시 · 자동 생성 멈춤을 따름 · 종전엔 명령줄 수동 실행만).
- **영수증 AI 자동 평가** — DEX 봉을 나중에 채우려고 거래소 봉으로 먼저 그린 차트(자동 평가를 미루는 차트)에서도 자동 요청이 서버에서 새 평가를 돌릴 수 있던 것 → 그런 차트의 자동 요청은 거절(409 · 저장된 평가와 직접 누르는 단추는 그대로) ·
  '진행 중' 뒤 자동 재시도가 그 사이 바뀐 보기로 다시 요청하던 것 → 처음 요청한 보기 그대로, 보기가 바뀌면 재시도 취소.
- **보안 — 인증 요청 리다이렉트** — 키·서명 헤더를 붙이는 요청(업비트·해외 거래소 조회 · 입금 주소 · 청산 감시 · 설정 연결 시험)이 3xx 리다이렉트를 따라가 새 주소로 그 헤더를 그대로 보낼 수 있던 것 → 따라가지 않고 오류로(증권사 연결은 종전부터).
- **보안 — 데이터 폴더·`.env` 권한** — 복사·복원으로 다른 사용자도 읽을 수 있게(755) 남은 `state/`·`state/inbox/` 와 그룹·다른 사용자 비트가 있는 `.env` 를 기동 때 본인만으로 조여요(종전엔 새로 만들 때만).
- **지난 판 한계 고침 — 미리 받기** — 영수증 차트 봉 미리 받기가 오늘 날짜 영수증을 '다 받음'으로 굳혀 다음 날 다시 받지 않던 것 → 오늘 영수증은 다음 날부터 받아요 ·
  영수증 차트 주소에 `bg=1` 을 직접 붙이면 하루 상한 밖에서 배경 받기가 돌던 것 → `bg=1` 은 같은 컴퓨터의 `tj-review` 내부 요청(로그인을 끈 설치는 이 컴퓨터에서 직접 온 요청)만, 그 밖은 403.
- **그 밖** — 꺼 둔 체인 안내 로그('비활성 체인(설정 제외)')가 설정을 1분마다 다시 읽는 유닛에서 하루 수천 줄 쌓이던 것 → 목록이 바뀔 때만 ·
  Base 공개 노드(`mainnet.base.org`) 기본 호출 속도 초당 1 → 0.5 요청(공표 없는 한도에서 429 가 잦았어요).

**함께**

- **문서** — README 사진 전부 새로(새 4장)·'최근 판에 더해진 것' 목록·'이번 판'·[백필 · 재구축](docs/OPERATIONS.md#백필--재구축--재백필) 첫 줄(기본 5개월 · 과거 데이터 더 가져오기 · 거래소 보존 한도)·AI 리뷰 '전체 채우기'·알려진 한계·English.
- **시험** — 공개 시험 추가: 인증 요청 리다이렉트 · 폴더·`.env` 권한 · 전체 채우기(예약 루프를 막지 않음·날짜 기준) · 영수증 자동 평가 거절·재시도 · 미리 받기 오늘 영수증·`bg=1` 내부만·비활성 체인 로그·Base 기본 속도 ·
  긴 설명 한 줄 화면 — 전체 8,100건 넘게(파일 253개).

**English · Screen polish, small external-review fixes, AI review "fill all"** — A design pass over the previous release: numbers (amounts, %, counts) use the monospaced
font and Korean sentences the text font, sheet/panel/card titles, card corners and chip weights are unified, hard-coded colors became theme tokens, and long explanations
became one line plus "자세히" (more) — key fields in Settings › 연결·키 now show required/optional and free/paid pills, node quota bars and the fallback order; the long
reasons in the collection-limits view are folded. Tapping a lower row in Settings no longer jumps the page up. Settings › 데이터 · 수집 › 과거 데이터 더 가져오기 warns, per connected
exchange, when the chosen start date is older than that exchange's API retention (warning only). Settings › AI 리뷰 has a "fill all" button for missing or outdated past reviews:
it only writes a request file and `tj-review` runs it in a background thread within a minute (scheduled reviews are not blocked). Small external-review fixes: automatic receipt
AI evaluations are refused (409) for charts whose evaluation is deferred, and a "running" retry keeps the original view (cancelled if the view changed); authenticated requests
(Upbit, foreign exchanges, deposit addresses, liquidation watch, connection tests) no longer follow redirects; existing `state/` and `state/inbox/` are tightened to 0700 and
`.env` to 0600 at start. Known limits of the previous release fixed: the candle prefetch no longer marks today's receipts done (they are fetched from the next day), and `bg=1`
on the receipt chart URL is accepted only from `tj-review` on the same machine (403 otherwise). Also: the disabled-chain log line is written only when the list changes, and the
default request rate for the public `mainnet.base.org` node is 0.5/s. All README screenshots were retaken. No rebuild and no data revision; stop everything, `pm2 start ecosystem.config.js`, then `pm2 save`.

**알려진 한계(다음 판에)** — 자세한 설명·피하는 법은 README [알아 둘 것](README.md#알아-둘-것).

- 같은 블록·같은 초에 스테이블을 다른 스테이블로 판 뒤 다시 산 두 거래는 실행 순서가 아니라 해시 순으로 재생될 수 있어, 그 매도의 실현이 다음 매도 날로 넘어갈 수 있어요(최종 누계는 같음).
- 영수증 서랍을 닫았다 다시 열면 그 사이 끝난 AI 평가·오류를 새로 불러오지 않을 수 있어요 — 새로고침하면 보여요.
- '전체 채우기' 확인창의 건수·걸리는 시간은 수동 몫만 세요 — 같은 기간의 자동 몫(곧 예약 리뷰가 쓸 날)도 함께 써서 실제 건수·Claude 사용량이 안내보다 많을 수 있어요.
- 리다이렉트를 따라가지 않는 것은 위 거래소·연결 시험 요청만이에요 — 코인게코·오픈시·TronGrid·toncenter 키 요청과 OKX DEX 시세 요청은 아직 리다이렉트를 따라가요(제공자가 다른 주소로 보낼 때만 · 다음 판에).
- 정책(그대로): 지갑 포트폴리오 보강(Rabby 공개 API)과 코인 로고(jsDelivr)는 기본 켜짐이에요 — 끄려면 `config.json` 의 `rabby.enabled: false` · 설정 › 화면 · 표시 › 토큰 로고([보안 · 데이터](README.md#보안--데이터)).
- 지난 판 한계(TON 첫 대사 경합 피해분 · 거래소 톤코인 → GRAM 원가 · Tron·Sui 자릿수 모르는 스팸 · 스테이블 원가 승계 · Solana 같은 슬롯 순서 등)는 그대로예요 —
  [2026-10-12 (2)](#2026-10-12-2--외부-검토-2건-버그-수정--톤코인-gram-개명--영수증-차트-봉-미리-받기) · 그중 미리 받기 두 줄은 이번에 고쳤어요.

## 2026-10-12 (2) — 외부 검토 2건 버그 수정 · 톤코인 GRAM 개명 · 영수증 차트 봉 미리 받기

**TON 스팸 제톤 대사 보류 · TON 첫 대사 중 입금 상쇄 · 톤코인 GRAM 개명(TON 시세 0) · 새 체인 못 받은 거래 6시간마다 다시 · 대사 보류·수집 유닛 없음 주의 · EVM 긴 Transfer 로그 ·
자동으로 끈 체인의 새 자금 경고 · 매매일지 넓은 기간 원화·교환 줄 · 새 체인 보유 줄 표시 · 보유 코인 줄 단위 쪽 넘김 · 작은 단가 원화 표기·곡선 눈금 ·
코인게코 옛 값·1분봉 실패 기억 · NFT·GeckoTerminal 호출 줄임 · 헬스 마진 부채 스테이블 · 백업 chain_wallets · 복원 안내 새 유닛 · Bitcoin HD 범위 재시작 · 영수증 차트 봉 미리 받기(선택)**

지난 판(2026-10-12)을 처음부터 읽은 외부 독립 검수 2건이 찾은 버그를 하나씩 공개 시험으로 재현해(고치기 전 실패 → 고친 뒤 통과) 가장 작은 수정으로 고친 판이에요 —
TON 지갑에 스팸 제톤 하나만 있어도 TON 대사가 통째로 멈춰 TON 잔고가 실제보다 훨씬 작게 보이던 것, 첫 대사 중에 들어온 TON 입금을 기초 잔고가 지워 버리던 것,
Tron·Sui·TON·Bitcoin 의 거래 상세를 장애 동안 못 받으면 그 거래가 영영 빠지고 그 체인 대사도 영영 보류되던 것, 데이터가 비정상적으로 긴 스팸 Transfer 로그 하나가 EVM·BNB Chain 수집을 몇 시간씩 멈추던 것,
자동으로 끈 체인에 큰돈이 들어와도 경고가 안 뜨던 것 등이에요. 같은 날 톤코인의 거래소 티커가 TON 에서 GRAM 으로 바뀌어 TON 시세가 0 으로 보이던 것(지난 판 알려진 한계)도 고쳤어요.
다음 판으로 준비하던 **영수증 차트 봉 미리 받기**(선택 · 기본 꺼짐)와, 키 없는 GeckoTerminal 이 쉬는 동안 거래소 봉으로 먼저 그리는 영수증 차트도 함께 넣었어요.
드물거나 고치는 품이 큰 경우는 이번엔 그대로 두고 아래 알려진 한계에 적었어요. 사진은 다시 찍지 않았어요(README '이번 판' 안내).
재현 자료까지 꼼꼼히 보내 준 외부 독립 검수 2건에 고마워요.

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` → **`pm2 save`** — 유닛을 전부 멈춘 뒤 한꺼번에 시작 ·
> 공통 모듈(로그 해석·시세·호출 조절)이 바뀌어 이번에도 모든 유닛 · 마지막 `pm2 save` 는 README 업데이트 순서에 새로 넣은 단계예요 — 안 하면 재부팅 때 pm2 가 예전 목록을 되살려 새 체인 유닛이 빠질 수 있어요).
> 재구축·데이터 개정은 없어요(업데이트만으로는 원장 쓰기 없음 · 새로 생기는 것 — `state/recon_hold.json`(새 체인 대사 보류 사유) · `state/candles/dex_later.json`(나중에 채울 DEX 봉) ·
> `state/candles/prewarm.json`(미리 받기를 켰을 때) · NFT 바닥가 기록의 오픈시 오류 횟수).
> **TON 지갑**이 스팸 제톤 때문에 대사 보류였다면 업데이트 뒤 10분쯤(제톤 정보 다시 받기) + 다음 대사 주기에 저절로 기초 잔고가 잡혀요(할 일 없음) · TON 시세는 GRAM 시장 값으로 바로 보여요 ·
> 지난 판에서 TON 첫 대사 중 입금이 이미 상쇄된 지갑은 저절로 고쳐지지 않아요(아래 알려진 한계).
> Tron·Sui·TON·Bitcoin 의 '거래 상세 누락'으로 남아 있던 거래는 업데이트 뒤 6시간 안에 저절로 다시 받아요.
> **일일 자동 백업에 `chain_wallets` 가 들어가요** — 다음 백업부터예요(그 전 백업엔 없음 · 지난 판 안내대로 따로 보관한 `config.json` 은 새 백업이 생길 때까지 지우지 마세요).
> 업데이트 뒤 상태 패널에 새로 보일 수 있는 것 — '수집 유닛 없음'(새 체인 지갑이 있는데 그 유닛이 pm2 목록에 없음 → `pm2 start ecosystem.config.js && pm2 save`) · '<체인> 기초잔고 대사 보류'(6시간 넘게) ·
> 자동으로 끈 체인의 '미추적 체인에 잔고/활동'(업데이트 뒤 새로 들어온 자금부터) · 반대로 USD·USDE·RLUSD·USDP·USDS 마진 부채의 '값 모름' 주의는 사라져요.
> **영수증 차트 봉 미리 받기는 기본 꺼짐**이에요 — 켜려면 `config.json` 의 `"review": {"chart_prewarm_per_day": 150}`(최대 300) 뒤 `pm2 restart tj-review`
> (AI 리뷰 유닛 `tj-review` 를 켠 설치만 — README [AI 기능 켜기](docs/FEATURES.md#ai-기능-켜기--claude-cli-로그인)).

- **영수증 차트 — 봉 미리 받기(선택) · DEX 봉은 나중에 채움** — `config.json` 의 `review.chart_prewarm_per_day`(기본 0 = 꺼짐 · 최대 300)를 켜면 AI 리뷰 유닛(`tj-review`)이 켜질 때와 하루 회차마다
  영수증 차트 봉을 하루 그 수만큼 한가할 때 미리 받아 영구 저장해요(영수증 한쪽 = 1 · 모델 호출 없음) — 보존 기한이 짧은 봉부터(키 없는 GeckoTerminal DEX 봉 약 180일) · 이미 받은 것은 다시 안 부름 ·
  화면이 차트를 받는 중이면 양보 · 키 없는 GeckoTerminal·코인게코는 분당 1회·429 면 그날 멈춤 · 코인게코 키는 프로일 때 하루 몫 절반 안에서 남는 몫만(데모 키·무키는 키 장부 안 씀) · 재시작해도 하루 상한 유지.
  기본으로 켜지는 것 — 키 없는 GeckoTerminal 이 호출 제한으로 쉬는 동안(429 쉼 · 10초 넘는 대기) 영수증 차트를 열면 DEX 봉을 기다리지 않고 같은 코인의 같은 해상도 거래소 봉으로 먼저 그려요
  (출처 줄 '… 봉 대신 …' · '오늘 몫 소진 — DEX 봉은 나중에 채움') — 그 차트는 DEX 봉이 채워질 때까지 자동 AI 평가를 미루고, 미리 받기를 켜면 '나중에 채움' 목록도 함께 받아요 ·
  거래소 봉도 없으면 종전처럼 DEX 봉을 기다려 받아요(DEX 에만 있는 코인은 종전과 같음).
- **TON — 스팸 제톤이 대사 전체를 막던 것** — 자릿수를 알 수 없는 제톤(대개 스팸 에어드랍) 하나만 들고 있어도 TON 체인 대사(기초 잔고)가 통째로 보류돼 TON 잔고가 수집 기간 안 증감만큼만 보이고,
  그 제톤이 수집 기간 안에 들어온 거래는 '거래 상세 누락'으로 떨어지던 것 고침 — toncenter 가 메타를 **무효(valid:false)로 명시**한 제톤만 그 칸을 대사에서 빼고 그 제톤 레그만 빼고 기장해요
  (TON 과 다른 제톤 대사는 진행 · 아직 색인 전이라 메타가 없는 제톤은 종전처럼 보류 — 18자리로 짐작하지 않음).
- **TON — 첫 대사 중 들어온 입금** — 첫 대사(새 지갑 대사 포함)가 잔고를 읽은 뒤 끝나기 전에 들어온 입금이 나중에 기록되면 그 입금을 '이미 잔고에 들어 있던 거래'로 보고 기초 잔고에서 빼,
  보유가 실제보다 적게 남던 것(예 실제 600 TON → 100 TON) 고침 — 잔고를 읽은 계정들의 마지막 거래 시각을 경계로 남겨 그 뒤 거래는 새 증감으로 둬요(종전 = 대사 처리 시각).
- **톤코인 → GRAM 개명** — 톤코인의 거래소 티커가 TON 에서 GRAM 으로 바뀌어(바이낸스 TONUSDT 거래 중단) TON 지갑의 TON 시세가 0 으로 보이던 것 — TON 체인 네이티브 TON 은 거래소 GRAM 시세로 평가해요
  (화면·원장 이름은 TON 그대로 · 1분봉은 옛 티커가 비면 새 티커 · 업비트는 원화 GRAM 마켓만 — 옛 KRW-TON 값은 지갑 TON 시세로 안 씀) ·
  같은 'TON' 기호의 이더리움 토큰(Tokamak Network 등)은 계약 주소 시세로만 — 원가 추정에서도 톤코인 1분봉을 안 받아요 · 거래소에 들고 있던 톤코인이 GRAM 으로 바뀌는 경우는 아래 알려진 한계.
- **Tron·Sui·TON·Bitcoin — 못 받은 거래 6시간마다 다시** — 제공자 장애·하루 한도 등으로 거래 상세를 재시도 상한(약 14.6시간)까지 못 받으면 '거래 상세 누락'으로 떨어진 뒤 다시는 시도하지 않아,
  회복 뒤에도 그 거래가 영영 빠지고 그 체인 대사도 영영 보류되던 것 고침 — 풀리지 않은 거래를 6시간마다 한 번 다시 받아 성공하면 기장하고 주의·대사 보류가 저절로 풀려요
  (Bitcoin 재편 구간·지운 지갑은 제외 · 못 받는 동안 거래 하나당 6시간에 상세 1번 더) · 상태 패널 안내문도 실제 동작대로.
- **상태 패널 — 대사 보류 · 수집 유닛 없음** — 새 체인 첫 기초 잔고 대사가 6시간 넘게 보류되면 '<체인> 기초잔고 대사 보류'(주의 · 사유·시작·마지막 확인 · 풀리면 사라짐 — 종전엔 tj-core 로그에만) ·
  새 체인 지갑이 있는데 그 수집 유닛이 pm2 목록에 없으면 '수집 유닛 없음'(주의 · pm2 없이 쓰면 그 유닛 러너 기록이 없을 때 — 종전엔 조용) · README 업데이트 순서 끝에 `pm2 save`.
- **EVM · BNB Chain — 긴 Transfer 로그** — 누가 내 주소로 데이터가 비정상적으로 긴 Transfer 로그를 남기는 스팸 토큰을 보내면 그 거래를 해석하다 그 체인 수집이 멈추고 몇 시간 뒤 그 거래가 격리되던 것 고침 —
  표준대로 첫 32바이트(금액 자리)만 읽어요(토큰 자릿수 응답도 첫 워드) · RPC 로 받는 체인·BNB Chain·자금 경로·체인 간 짝 맞추기 모두.
- **자동으로 끈 체인에 새 자금** — '추천 체인 자동으로 끄기'로 꺼진 체인에 그 뒤 새로 돈이 들어와도(예 $5만) '미추적 체인에 잔고/활동' 경고가 영영 안 뜨던 것 고침 —
  끄기 전부터 활동이 있던 주소도 nonce 증가 · 네이티브 증가분 × 시세 · 스테이블 증가분이 문턱 이상이면 다시 알려요(시세만 오른 날은 아님 · 업데이트 전에 이미 들어온 자금은 다음 증가 때부터).
- **매매일지 — 넓은 기간의 원화·교환 줄** — 매매일지 '전체 이벤트'에서 기간을 '전체'나 120일 넘게 고르면 원화 입출금·스테이블 교환(환전) 줄이 오류 없이 통째로 빠지던 것 고침 —
  넓은 기간은 쪽(5,000건)으로 받는데 그 응답에 두 줄 묶음이 없었어요 · 이제 쪽마다 그 시각 구간의 줄만 붙여 이어 받아도 한 번씩만 나와요.
- **새 체인 보유 줄 표시** — Tron·Sui·TON·Bitcoin 지갑의 보유·보관처 줄에 원장 안쪽 키(앞 몇 글자)가 보이던 것 → 지갑 별명이나 주소 표시 꼴(T…·UQ…·bc1… · Bitcoin HD 지갑은 'Bitcoin') ·
  보관처 서랍 머리 칩이 Bitcoin 지갑도 '지갑 · EVM'이던 것 → 체인별('지갑 · BTC' 등 · EVM·SOL 표시는 종전 그대로).
- **보유 코인 쪽 넘김 — 줄 단위** — 보유 코인 한 쪽이 코인 묶음(본행 + 스테이킹 등 Rabby 기준 하위 줄) 단위라 하위 줄이 많으면 한 쪽이 길어지고 '다음' 단추 위치가 쪽마다 바뀌던 것 →
  한 쪽 = 정확히 설정 '목록 한 쪽'(10/20)줄(마지막 쪽만 짧음) · 머리 'N종'은 그대로 · 하위 줄이 있으면 쪽 바 단위가 '줄' · 찾아가기도 그 줄이 있는 쪽으로.
- **작은 단가 · 총자산 곡선 눈금** — 원화 보기에서 $0.0001 미만 단가(밈 코인 등)가 '₩9,972e-06'처럼 깨지던 것(미매칭 '온체인 기록'·자금 경로 줄·가격 이상 안내) →
  1달러 아래 지수 표기는 달러 원문 그대로 · 큰 지수 값($1.23457e+06)은 원화로 바르게 · 변동이 아주 작은 기간의 총자산 곡선 y축 눈금이 모두 같은 글자로 보이던 것 → 서로 다른 눈금(눈금 수는 줄 수 있어요 · 평소 곡선은 그대로).
- **시세 — 코인게코 옛 값 · 1분봉 실패 기억** — 코인게코 간단 시세가 실패(429·예산 소진)를 이어 가면 마지막으로 받은 값을 시간 제한 없이 '방금 시세'로 돌려주던 것 → 1시간 넘은 값은 안 써요
  (업비트에 원화 마켓 없이 들고 있는 코인 · Hyperliquid 현물 일부) · 한 화면 계산이 같은 코인의 봉 없는 옛 시각과 지금 분을 함께 물으면 옛 시각 실패 하나로 30분 동안 그 코인 현재가가 0 으로 보이던 것 →
  직전 10분 값은 그대로 쓰고 같은 코인은 최신 분부터 받아요.
- **호출 줄임 — NFT 바닥가 · 키 없는 GeckoTerminal** — 오픈시가 같은 오류를 내고 코인게코에도 없는 컬렉션을 30분마다 두 곳 다 다시 묻던 것(컬렉션 하나에 하루 48 + 48회) →
  오픈시 오류 3번 연속 + 코인게코 없음 + 직전 시세 없음이면 7일 '시세 없음'(직전 시세가 있던 컬렉션은 종전대로) · 오픈시가 지원하지 않아 코인게코로만 바닥가를 받는 체인(BNB Chain·HyperEVM·Ronin 등)의
  추적 컬렉션은 4시간마다(종전 1시간 · '오래됨'은 주기 + 1시간) · 키 없는 GeckoTerminal 을 시세·영수증 차트·미리 받기가 서로 모르게 따로 조절해 429 를 맞던 것 →
  프로세스를 넘어 호출 간격(초당 0.15회)을 함께 써요 · 시세 조회가 429 를 받으면 같은 프로세스(tj-web)의 GeckoTerminal 호출이 60~300초 쉬고(그동안 시세 조회는 다음 차례 · 영수증 차트는 거래소 봉으로 먼저) ·
  미리 받기는 429 면 그날 멈춰요(쉼 자체는 프로세스마다 따로) — 차트 DEX 봉 조회가 조금 느려질 수 있어요.
- **헬스 — 마진 부채 스테이블** — 거래소 마진 부채 중 USD·USDE·RLUSD·USDP·USDS 를 상태 패널이 '값 모름'으로 봐 '… · 값 모름 N건' 주의가 뜨던 것(총자산 계산은 $1 로 이미 뺌) → 두 곳 스테이블 목록을 같은 14종으로.
- **백업 · 복구** — 일일 자동 백업의 원장 밖 설정 사본(`config_subset.json`)에 `chain_wallets`(새 체인 지갑 · Bitcoin 공개 디스크립터·탐색 범위)가 들어가요(복원 때 자동 적용은 안 함 — 필요한 항목을 손으로 옮기는 참고 사본 · 서버 밖 둘째 백업을 켰다면 그 묶음에도 같이 가요 — 공개 키라 돈을 옮길 수는 없지만 HD 지갑 주소 전체를 알 수 있으니 받는 곳은 내 컴퓨터로) ·
  원장 복원 도구(`tools/ledger_restore.py`)의 pm2 멈추기·켜기 안내에 새 체인 유닛(`tj-tron`·`tj-sui`·`tj-ton`·`tj-btc`) ·
  Bitcoin HD 지갑의 `gap_limit`·`range_end` 를 바꾸면 tj-btc·tj-core 가 저절로 다시 시작해 새 범위로 찾아요(종전엔 옛 범위 그대로 · 같은 값·별칭만 바꾸면 재시작 없음).
- **그 밖** — Solana 옛 기록 채우기 알림이 마지막 조각이 작으면(50건 이하) '받는 중'으로 남아 멈춘 것처럼 보이다 3시간 뒤 사라지던 것 → 끝나면 바로 닫힘 ·
  자동 재시작이 없는 실행에서 지갑 등록 뒤 보이는 수동 재시작 안내가 실제로 다시 켤 유닛(새 체인 유닛 포함)을 적어 줘요 · 새 체인 대사 보류 로그에 짧은 사유 코드(허용 목록만 · 최대 3개).
- **지난 판 한계 고침** — 지난 판 알려진 한계 중 'TON 스팸 제톤을 들고 있으면 TON 대사 보류'(제공자가 무효로 표시한 제톤) · 'TON 시세 0' · '복원 도구 pm2 안내에 새 체인 유닛 없음' ·
  업데이트 상자의 '`chain_wallets` 는 일일 백업에 아직 없음'을 이번에 고쳤어요.

**함께**

- **문서** — README '이번 판'·업데이트 6단계 `pm2 save`·백업 문단(`chain_wallets`)·고급 설정 표 `review.chart_prewarm_per_day`·알려진 한계·English ·
  [API_KEYS.md](docs/API_KEYS.md) 영수증 차트(나중에 채움·미리 받기 몫) · [COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) 새 체인 시세(거래소 시세 · TON = GRAM 티커)·TON 줄(무효 메타 제톤)·Bitcoin HD 범위 바꾸기 ·
  `config.example.json` `review.chart_prewarm_per_day`.
- **시험** — 공개 시험 추가: TON 무효 메타 제톤 대사·기장 · TON 첫 대사 경합 · 새 체인 못 받은 거래 다시 받기(실제 원장 대사 보류 → 해제) · 대사 보류·수집 유닛 없음 헬스 · 긴 Transfer 로그 data ·
  자동으로 끈 체인 새 자금 경고 · 넓은 기간 원화·교환 줄(무작위 쪽 나눔) · 새 체인 보유 줄 표시 · 보유 줄 단위 쪽 넘김 · 지수 단가·곡선 눈금 · 톤코인 GRAM 시세 · 코인게코 값 나이 · 1분봉 실패 기억 ·
  NFT 오류 포기 · GeckoTerminal 조절 공유 · 헬스 부채 스테이블 · 백업·복원 안내·Bitcoin HD 범위 · 대사 보류 사유 코드 · 영수증 차트 미리 받기·나중에 채움 — 전체 7,900건 넘게(파일 246개).

**English · External review fixes, Toncoin GRAM rename, receipt chart prefetch** — Two independent external reviews of the previous release found new bugs; each was reproduced as a public test
(failing before, passing after) and fixed with a minimal change. TON: a spam jetton whose metadata the provider explicitly marks invalid no longer holds the whole TON reconciliation or turns its transaction
into a gap (only that jetton is left out; jettons not yet indexed still hold), and a deposit landing after the first reconciliation's balance sample is no longer cancelled by the opening balance.
Toncoin's exchange ticker changed from TON to GRAM; native TON on the TON chain is now priced from GRAM markets (display and ledger keep "TON"). Tron/Sui/TON/Bitcoin transactions that ran out of
detail retries are retried every 6 hours instead of staying gaps forever. The status panel warns when a new chain's first opening-balance reconciliation has been held for over 6 hours, and when a chain
with wallets has no collector unit in pm2 (the README update steps now end with `pm2 save`). EVM/BNB Chain: Transfer logs with oversized data no longer stall collection (only the first 32-byte word is read).
An auto-disabled chain that receives new funds raises the untracked-chain warning again. Journal: KRW deposit/withdrawal and stablecoin conversion rows are kept for "all" and >120-day ranges. New-chain
holding rows show display addresses instead of internal keys; holdings pages are exactly 10/20 rows including staking sub-rows; tiny exponent prices convert correctly; flat total-asset curves get distinct
y-axis ticks. Prices: CoinGecko simple prices older than 1 hour are no longer served as fresh, and one failed old 1-minute candle no longer blocks the current price for 30 minutes. Fewer wasted calls:
NFT floors give up after 3 OpenSea errors plus a CoinGecko miss (7-day negative cache; CoinGecko-only chains every 4 hours), and keyless GeckoTerminal calls share one cross-process request-rate
throttle (a 429 on price lookups pauses that process's GeckoTerminal calls for 60–300 seconds; the background prefetch stops for the day). Health margin-debt stablecoins match the dashboard's 14. Daily backups include `chain_wallets`; the restore tool's pm2 hints list the new chain units; changing a Bitcoin HD wallet's
`gap_limit`/`range_end` restarts tj-btc and tj-core. New: optional receipt chart candle prefetch (`review.chart_prewarm_per_day`, default 0 = off, needs `tj-review`), and while keyless GeckoTerminal is
rate-limited, receipt charts draw same-resolution exchange candles first and fill DEX candles later. No rebuild and no data revision; stop everything, run `pm2 start ecosystem.config.js`, then `pm2 save`.

**알려진 한계(다음 판에)** — 자세한 설명·피하는 법은 README [알아 둘 것](README.md#알아-둘-것).

- 거래소에 들고 있던 톤코인을 거래소가 GRAM 으로 바꾸면 'TON 잔고 사라짐'과 원가 모르는 'GRAM 들어옴'이 따로 보일 수 있어요(같은 코인 · 원가는 직접) ·
  지난 판에서 TON 첫 대사 중 입금이 이미 상쇄된 지갑은 저절로 안 고쳐져요 · 잔고를 읽은 바로 그 초·계정 조회 사이 틈에 든 입금은 드물게 여전히 상쇄될 수 있어요 ·
  제공자가 무효로 표시했다가 나중에 유효로 바꾼 제톤은 건너뛴 기록을 다시 넣지 않아요.
- Tron·Sui 의 자릿수를 알 수 없는 스팸 토큰은 아직 대사를 보류시켜요(TON 만 고침) · 이미 대사를 마친 체인에 나중에 넣은 지갑의 대사 보류는 상태 패널에 아직 안 떠요(로그만).
- 액면과 다른 값에 산 스테이블을 세일 입찰 환불·확인된 브리지로 옮기면 돌아온·도착한 몫의 달러 원가가 액면으로 다시 잡혀요(그 차이만큼 실현 어긋남).
- Solana 같은 슬롯 안 매수·매도는 서명 순서로 재생돼요 · 같은 초에 65건 넘게 몰린 묶음은 EVM 도 순번을 안 써요 · 이미 저장된 같은 블록 거래의 순서 고치기는 아직 없어요.
- 거래소 메이커 리베이트(음수 수수료)는 실현손익에 안 더해져요 · 업비트·빗썸 예약(스톱) 주문이 오래 걸려 있다 한 주기 안에 다 체결되면 체결이 빠질 수 있어요 · Bybit 403(호출 잦음)을 키 권한 없음으로 보고 6시간 쉬어요.
- 컨트랙트 지갑(EIP-7702 위임·Safe)에서 남이 보낸 거래 안의 '내 지갑 → 밖' 내부 ETH 유출은 RPC 로 받는 체인 기본 설정에서 빠질 수 있어요(`chains.<체인>.rpc_trace: "all"` 로 피함).
- Solana 한 확인 주기 안에 생겼다 닫힌 토큰 계정으로 온 입금 · 닫힌 스테이크 계정의 마지막 에포크 보상 · `backfill_full_history: true` 의 '첫 백필 끝' 표식은 아직 고치지 않았어요.
- 새 체인 지갑 보관처 서랍엔 주소·복사·'이곳 기록 보기'가 아직 없어요 · 인박스를 바꾼(새로 설치·지우고 다시 만든) 뒤 옛 백업으로 복구하면 거래 일부를 건너뛸 수 있어요 — 복구는 원래 인박스로.
- 영수증 차트 봉 미리 받기는 오늘 날짜 영수증을 다음 날 다시 받지 않아요(그 영수증을 열 때 받음) · 영수증 차트 주소에 `bg=1` 을 직접 붙이면 미리 받기 하루 상한 밖에서 배경 받기가 돌 수 있어요(로그인한 본인만).
- 정책(그대로): 'NFT 총자산에 포함'을 켜면 남이 공짜로 준 NFT 도 바닥가·24시간 체결 1건이면 들어가요 · 장기 곡선 옛날(일봉만 있는 날) 마감가 = 그날 KST 09:00(UTC 일봉 시가).
- 지난 판 한계(TON 제공자 응답 지연·BTC·Sui 고장 응답 반복 · 빗썸 부분 체결 뒤 취소 · 원장 복원 뒤 수동 원가 · 같은 블록 순서 옛 저장분 · Bitcoin 주소↔HD 이전 등)는 그대로예요 —
  [2026-10-12](#2026-10-12--tron--sui--ton--bitcoin-지갑--외부-검토-버그-수정--주의-닫기--역할별-노드-선택--chainnodes) · 그중 TON 스팸 제톤(무효 표시)·TON 시세 0·복원 도구 안내·`chain_wallets` 백업은 이번에 고쳤어요.

## 2026-10-12 — Tron · Sui · TON · Bitcoin 지갑 · 외부 검토 버그 수정 · 주의 닫기 · 역할별 노드 선택 · Chainnodes

**Tron·Sui·TON·Bitcoin 지갑(읽기 전용 · Bitcoin 은 HD 지갑 또는 주소 하나) · 새 체인 대사는 모르면 보류 · TON 거래소 출금 → 도착 연결 · 새 체인 지갑 검색 · 옛 Base 내부 이동 Alchemy 보완 · 역할별 노드 선택(속도·예상 남은 시간) ·
'내 지갑' 재분류 이중 계상 · 세일(CCA) 환불·수동 참가금 손익 · 원장 복구 뒤 BNB Chain 다시 점검 · 디스크 자동 정리가 검증된 백업 보존 · 옛 보유 토큰 찾기 1,000행 넘김 ·
헬스 주의 기준 재정비·닫기 · 목록 한 쪽 10/20개·'모두 보기' 없앰 · 같은 블록 안 거래 순서 · 새 체인 거래 상세 누락 주의 ·
QuickNode 선택 칸(유료·1개월 체험)·거부 자동 복귀 · Chainnodes Base trace · 응답 본문 대기 상한**

지난 판(2026-10-11 (2)) 뒤에 공개하지 않고 쌓인 두 판을 합친 판이에요.
첫째는 지난 판을 처음부터 끝까지 읽은 외부 전체 검토가 찾은 버그를 하나씩 공개 시험으로 재현해(고치기 전 실패 → 고친 뒤 통과) 고친 것이에요 —
받는 지갑을 대사(기초 잔고)로 맞춘 뒤 옛 보낸 내역을 '내 지갑'으로 고르면 받은 양이 두 번 세지던 것, 전액 환불된 세일 입찰의 결제 코인 원가가 설정에 따라 사라지던 것,
원장을 백업으로 되돌린 뒤 BNB Chain 의 로그 없는 입금이 빠질 수 있던 것, 디스크 자동 정리가 손상된 최신 백업만 남기고 멀쩡한 옛 백업을 지울 수 있던 것,
무료 이더스캔 1,000행 상한을 목록 끝으로 오인해 토큰 많은 지갑의 옛 보유 토큰을 놓치던 것, 24시간 지난 '시세 없는 보유' 주의가 새 코인이 더해져도 접혀 있던 것.
헬스 주의는 이용자가 할 일이 있거나 돈 숫자가 틀릴 수 있는 것만 띄우도록 기준을 다시 잡고 항목별 '닫기'를 더했어요. QuickNode 는 상시 무료 플랜이 없어(1개월 체험 뒤 유료) 선택 칸으로 바로잡고,
Base 내부 이동 확인(trace)에 무료 Chainnodes 키를 더했어요.
둘째는 새 기능이에요 — **Tron · Sui · TON · Bitcoin 지갑**을 읽기 전용으로 넣을 수 있어요(키 없이도 돌아요 · Bitcoin 은 HD 지갑 또는 주소 하나).
무료 추적 노드가 못 주는 **옛 Base 거래의 내부 ETH 이동**은 Alchemy 키로 채우고, 노드는 역할(옛 상태·상세·trace)별로 실제 속도를 재서 고르며 옛 기록 채우기가 너무 오래 걸리면 무료 키 노드를 먼저 써요.
새 기능도 외부 검토를 네 번 더 거치며 찾은 문제를 같은 방식(재현 시험 먼저)으로 고쳤어요 — 새 체인은 모르는 것(못 받은 거래·모르는 자릿수·제공자 응답 이상)을 0 이나 '완료'로 확정하지 않고 보류해요.
마지막으로 일반 사용 흐름을 다시 훑은 외부 검토가 찾은 같은 블록 안 거래 순서 문제와 새 체인 마무리(거래 상세 누락 주의 · 키를 바꾸면 원장도 다시 시작)를 같은 방식으로 고치고,
긴 목록의 '모두 보기' 단계를 없앴어요. 드문 경우와 쓰는 법의 제한은 아래 알려진 한계에 적었어요. 사진은 다시 찍지 않았어요 — 새 체인 지갑 추가 화면 사진은 없어요(README '이번 판' 안내).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` — 유닛을 전부 멈춘 뒤 한꺼번에 시작 ·
> 공통 모듈(수집 HTTP·노드 선택·노드 키)이 바뀌어 이번에도 모든 유닛).
> **새 유닛 `tj-tron`·`tj-sui`·`tj-ton`·`tj-btc`** 는 `pm2 start ecosystem.config.js` 로 같이 붙어요(`restart` 로는 안 붙어요) — 그 체인 지갑이 없으면 수집기를 띄우지 않고 '대기'예요 ·
> 재부팅 뒤 자동 시작을 쓰면 `pm2 save` 를 한 번 더 하세요(새 유닛이 목록에 들어가요).
> 재구축·데이터 개정은 없어요(업데이트만으로는 원장 쓰기 없음 · 새로 생기는 것 — `state/health_ack.json` 의 닫은 주의 · 옛 보유 토큰 찾기의 쌍별 이어 받기 표시 · QuickNode 거부 표시 · BNB Chain 복구 뒤 다시 점검 구간 ·
> `state/node_stats/` 노드 관측(지워도 다시 생김) · 미룬 Base 내부 이동 항목의 단계 기록 · 만료로 빼는 옛 내부 이동의 전체 식별자 `state/leaf_later_unresolved_<체인>.jsonl`·`state/trace_later_unresolved_<체인>.jsonl` ·
> 새 체인 지갑을 넣으면 `config.json` 의 `chain_wallets` 와 `state/cursor_<체인>.json`·`state/emitted_<체인>.json`·`state/inbox/<체인>/` — 원장 복원 도구가 새 체인 수집 상태도 함께 되감아요).
> **새 체인 지갑을 넣었다면 `config.json` 을 따로 백업해 두세요** — `chain_wallets`(Bitcoin HD 지갑의 xpub·디스크립터 포함)는 일일 자동 백업(원장 밖 사본) 목록에 아직 없어요(다음 판).
> 옛 보유 토큰 찾기는 업데이트 뒤 한 번 옛 기록을 다시 훑어요(이더스캔 계열 호출이 잠깐 늘 수 있음 · 공표 한도 80% 장부 안).
> **목록 한 쪽은 이제 기본 10개**예요 — 기기마다 설정 › 화면 '목록 한 쪽'에서 20개로 되돌릴 수 있어요 · 긴 목록은 처음부터 한 쪽이 보이고 바로 '다음'(‘모두 보기’ 단계 없음).
> **같은 블록 안 거래 순서**는 업데이트 뒤 새로 받는 거래부터 맞아요 — 이미 저장된 거래는 종전 순서 그대로예요(다시 받지 않음 · 원장 쓰기 없음).
> **헬스 주의 기준이 바뀌었어요** — 값을 아는 거래소 대출 부채는 주의가 아니라 정상(이미 총자산에서 뺌) · 자동으로 회복되는 것(잔고 대조 차이 24시간 · Helius 하루 몫·Solana 공개 노드·GoPlus 대기·화면 빌드 6시간)은 오래 이어질 때만 ·
> 시세 없는 실보유는 24시간 뒤 저절로 접히지 않아요 — 업데이트 뒤 접혀 있던 주의가 다시 보이면 내용을 확인하고 그 줄의 **닫기**를 누르세요(새 코인·지갑·체인이 생기거나 금액이 크게 늘면 다시 보여요).
> **QuickNode 는 유료 요금제나 1개월 무료 체험 키가 있을 때만**(지난 판 '무료 플랜도 됨' 정정 — 상시 무료 없음) — 요금제 칩 '무료 키'는 '1개월 체험'으로 이름만 바뀌었어요(값·80% 그대로) ·
> 체험이 끝나면 유료로 바꾸거나 키를 지우세요(키가 계속 거부되면 봇이 그 체인에서 알아서 빼고 기본 노드로 · 다시 쓰려면 연결 테스트).
> **Chainnodes**(`TJ_CHAINNODES_KEY`, 선택 · 무료 Core)를 넣으면 Base 내부 이동 확인에 먼저 써요(순서 Chainnodes → QuickNode → 기본 노드 · 앞 노드가 한도·옛 기록 없음이면 같은 호출 안에서 다음 노드로).
> **새 선택 키** — `TJ_TRONGRID_KEY`(Tron · 키 없이 초당 0.8회 → 키면 초당 4회 · 하루 공표 한도의 80%) · `TJ_TONCENTER_KEY`(TON · 키 없이 초당 1회 → 키면 초당 8회) — `.env` 에 넣어요
> (설정 › 연결·키 칸은 아직 없음 · 넣거나 바꾸면 그 체인 수집기와 원장(tj-core)이 알아서 다시 시작) · Sui·Bitcoin 은 키 없이 공개 API 로 받아요.
> **Alchemy 키**(`TJ_ALCHEMY_KEY`)는 이제 옛 Base 거래의 내부 ETH 이동 보완에도 써요 — 모든 추적 노드가 못 준 1시간 넘은 블록만 · 블록당 1콜(120 CU) · 같은 하루 몫 80% 안 · 실시간 감시엔 안 씀 · 키가 없으면 종전 그대로.
> **역할별 노드 선택이 기본으로 켜져요** — 실시간은 공개 노드가 먼저이고 느리거나 자주 실패할 때만 무료 키 노드로, 옛 기록 채우기가 2시간 넘게 남으면 키 노드 먼저(키 하루 몫 80% 그대로) ·
> 종전 고정 순서로 되돌리려면 `config.json` 의 `"backfill": {"node_select": false}`(관측만 함).
> '내 지갑' 판정을 대사 뒤에 바꾼 적이 있으면 `python3 tools/repair_own_overlap.py`(점검 · 쓰기 0)로 겹친 칸이 있는지 보세요 — 있으면 tj-core 를 멈춘 뒤 `--apply`(원장 백업 뒤 고침 · 두 번 돌려도 같음).

- **Tron · Sui · TON · Bitcoin 지갑(읽기 전용)** — 설정 › 지갑 · 주소 › 지갑 추가의 체인 칩 줄(EVM · Solana | Tron | Sui | TON | Bitcoin)에서 체인을 골라 한 번에 하나씩 넣어요
  (체인별 주소 형식 검사 · 개인 키·시드 문구는 거부 · 새 체인 지갑은 최대 100개) · 설정 › 추적 지갑 목록에 같은 꼴 줄(이름 바꾸기·빼기) · 체인마다 수집 유닛 하나(`tj-tron`·`tj-sui`·`tj-ton`·`tj-btc`) —
  받은 거래는 기존 원장·원가·손익 계산에 그대로 들어가요. 확정된 거래만 기장 · 교환처럼 보이는 거래는 손익을 확정하지 않고 검토 줄로(가격 없는 교환 = 원가 넘기기) ·
  제공자 오류·잘린 응답을 '거래 없음'·'잔고 0'으로 바꾸지 않아요(다음 주기에 다시) ·
  Tron = TronGrid(TRX·TRC-20·내부 TRX · 수수료는 영수증 값 그대로 · 동결 TRX 는 '보낸 내역') · Sui = 공개 GraphQL(SUI·코인 · 가스 환급·남이 대신 낸 가스 구분 — 낸 쪽 정보가 없으면 보류) ·
  TON = toncenter v3(TON·제톤 — 주인·마스터가 검증된 제톤 지갑만 · 내 지갑끼리 보낸 TON 은 한 건으로) · Bitcoin = 공개 Esplora(blockstream → mempool.space 자동 전환).
- **Bitcoin — HD 지갑 · 주소 하나** — HD 지갑은 확장 공개 키 하나(zpub·ypub 는 형식 자동 · xpub 는 주소 형식 칩으로 고름) 또는 공개 디스크립터(pkh · sh(wpkh) · wpkh · 단일 키 tr)로 넣고,
  받는·잔돈 주소를 이 컴퓨터에서 만들어 갈래마다 gap 20 까지 찾아요(키·디스크립터를 밖으로 보내지 않음) · 주소 하나 모드는 그 주소만(잔돈 주소가 따로 생기는 지갑은 HD 로) ·
  6 확인 뒤 기장 · 수수료는 내 입력 몫만(내 지갑 여럿이면 입력 금액 비례 · 남의 입력이 섞이면 귀속 미상으로 검토) · 깊은 재편은 그 지갑 숫자를 보류 ·
  한 제공자가 특정 조회만 계속 실패해도 요청 단위로 세어 예비 제공자로 넘어가요 · 단일 주소와 그 주소를 품은 HD 지갑을 겹쳐 등록하려 하면 같은 BTC 를 두 번 세지 않게 거절해요(아래 알려진 한계).
- **새 체인 대사(기초 잔고) — 모르면 보류** — 수집 기간 전부터 있던 보유는 한 경계(Bitcoin·Tron = 확정 높이 · Sui = 체크포인트 · TON = 계정 순번)의 잔고로 맞춰요(기존 체인과 같은 대사 규칙) ·
  아직 못 푼 거래(대기·빈 구간)가 남았거나, 자릿수를 모르는 토큰이 있거나(18자리로 짐작하지 않음), 잔고 칸이 비어 오거나, Sui 코인 합계가 맞지 않거나(첫 대사·새 지갑),
  TON 대사 조회 중에 새 제톤 지갑이 검증됐거나, 검증된 제톤 지갑이 제공자 목록에서 빠지면 그 체인(새로 넣은 지갑의 대사면 그 지갑) 대사를 보류하고 다음 주기에 다시 해요 —
  빠진 거래 금액이 기록 없이 기초 잔고로 흡수되거나 창 이전 보유가 덜 잡히지 않게 해요 · Sui 는 지갑마다 따로 맞춰 한 지갑의 보류가 상관없는 다른 지갑을 막지 않아요.
- **새 체인 시세 · 검색 · 화면** — 네이티브 TRX·SUI·TON·BTC 는 코인게코 시세 · 발행사 공식 스테이블(Tron USD₮ · TON USD₮ · Sui USDC — 계약 주소로만)은 USDT·USDC 로 묶어요(기호만 같은 다른 계약은 따로 · 시세 없음) ·
  전체 검색·`wallet:` 조건에 새 체인 지갑 이름과 T…·UQ…/EQ…·0:… 주소, 0x 없이 저장된 Tron·Bitcoin 거래 해시, TON 거래 해시가 잡혀요 ·
  `wallet:` 값은 이제 자르지 않아요(TON 66자·Taproot 62자 주소 · 128자 넘으면 이유와 함께 거절 — 종전엔 60자로 잘려 조건이 무시됐어요) ·
  입금 주소 줄에 체인 이름 · 보낸 내역 목적지를 '내 지갑'으로 고르면 새 체인 지갑으로 등록 · 새 체인 주소 별명 · 탐색기 링크(거래 · Sui 는 주소도) ·
  헬스·설정 수집원 칩·수집 한계 표에 새 체인 줄(그 체인 지갑이 있을 때만) · 새 체인 거래는 EVM 브릿지 역추적·솔라나 주소 조회로 보내지 않아요.
- **TON 거래소 출금 → 내 TON 지갑 도착 연결** — 거래소 출금 기록의 txid 가 내 지갑이 받은 거래의 해시와 같으면(16진·0x·대문자·base64·base64url 표기 차이 무관) 출금과 도착을 이어요 —
  전송 중에 두 번 보이지 않고 원가가 이어져요(다른 체인의 txid 비교는 그대로).
- **옛 Base 거래의 내부 ETH 이동 — Alchemy 보완** — 30일 넘은 무거운 거래처럼 모든 추적(trace) 노드가 못 준 옛 거래·블록만 Alchemy 내부 이동 목록(`alchemy_getAssetTransfers`)으로 채워요
  (1시간 넘은 블록 · 블록당 1콜 120 CU · 하루 몫 80% · trace 와 같은 꼴이라 두 번 안 실림 · 실패한 거래의 이동은 무효로) ·
  미룬 항목끼리 서로 굶기지 않게 — 블록마다 실제로 실패한 노드를 기억해 안 물어 본 노드부터 · 모두 실패했으면 Alchemy 먼저 · Alchemy 가 실패하면 다음 차례에 추적 노드 하나를 돌아가며 다시 확인(회복한 노드를 다시 씀) ·
  마감에 걸린 항목 하나가 대기열 전체를 막지 않게 차례를 돌려요 · Alchemy 하루 몫·속도 한도로 못 보낸 차례는 항목을 지우지 않아요 · Alchemy 를 한 번도 못 물어 본 항목은 30일에 지우지 않고 60일까지 기다려요 ·
  만료로 빼는 항목은 먼저 전체 식별자(체인·지갑·블록·해시·시도 횟수·사유)를 `state/` 보관 파일에 남겨요(쓰기 실패면 빼지 않음).
- **역할별 노드 선택** — 수집기가 체인·역할(블록 훑기·옛 상태·상세·trace)·노드별로 실제 전송 시간과 실패를 재요(`state/node_stats/` · 서비스 이름만 — 주소·키 없음) ·
  실시간 = 공개 노드가 먼저 · 공개 노드가 두 창(표본 12개) 연달아 느리거나(상세·옛 상태 10초 · trace 20초 기준) 자주 실패하면(20% 넘게) 그 노드를 뒤로 보내 무료 키 노드(Ankr·NodeReal)가 먼저 ·
  1분마다 실제 작업 한 번을 그 노드에 맡겨 3번 연달아 괜찮으면 되돌려요 · 옛 기록 채우기 = 예상 남은 시간이 2시간을 넘으면 그 일을 잘하는 키 노드 먼저(공개였다면의 예상이 1시간 아래로 오면 공개로) ·
  느린 공개 trace 노드는 다른 정상 trace 노드 뒤로 · 키 사용은 그대로 하루 몫 80% 안(넘으면 그 콜은 공개 노드로) · QuickNode·Alchemy 자리는 종전 그대로 ·
  옛 기록 채우기 알림에 '… · 약 N분 남음 · Ankr로 받는 중'처럼 받는 노드를 보여요 · BNB Chain 은 관측·표시만.
- **'내 지갑' 재분류 — 보유 이중 계상** — 받는 지갑을 대사(기초 잔고)로 이미 맞춘 뒤 옛 보낸 내역을 '내 지갑'으로 고르면 받은 레그만 더해져 보유가 두 번 세지던 것(예 10 → 20) 고침 —
  재분류로 다시 기장할 때 그 대사가 흡수한 몫만큼 기초 잔고를 같이 고쳐요(수집기가 다시 기장할 때와 같은 규칙 · 재구축과 같은 값) · LP 관리자 재분류도 같은 길 ·
  이미 그렇게 기장된 원장은 새 도구 `tools/repair_own_overlap.py` 가 대사 관측 잔고를 기준으로 겹친 칸만 찾아 고쳐요(기본 점검 · `--apply` = 백업 뒤 한 트랜잭션 · 차이가 정확히 설명될 때만 · 멱등).
- **세일(CCA) 환불 · 수동 연결 참가금** — 전액 환불·미체결 입찰은 '최초 인식 시가' 설정과 상관없이 환불된 결제 코인에 원래 원가를 돌려줘요(종전엔 설정에 따라 원가가 사라짐) ·
  보낸 내역에서 손으로 '받은 것과 연결'한 세일 참가금도 자동 세일처럼 결제 코인 처분으로 기록해요(대가 = 보낸 때 값 · 첫 연결 토큰을 받은 때 정산 · 같은 스테이블 환불은 쓴 몫만 처분 · 수수료·환불 분리) —
  다 끝난 왕복의 실현 손익 + 명시된 미상 몫이 달러·원화 현금 변화와 맞아요.
- **원장 복구 뒤 BNB Chain 다시 점검** — 백업으로 원장을 되돌릴 때 인박스가 백업 시점을 덮지 못해 BNB Chain 을 되감으면, 되감은 시작부터 옛 체크포인트까지를 잔고 감시의 다시 점검 구간으로 저장해요 —
  옛 기록 차선을 다시 받은 뒤 되돌린 원장 기준으로 다시 따져 백업 뒤에 찾았던 로그 없는 BNB 입금을 정확히 한 번 되찾아요(재시작에도 유지 · 아카이브 없는 설치는 구간 끝 기초 잔고 요청으로 정직하게 마감).
- **디스크 자동 정리 — 검증된 백업 보존** — 재계산 전 디스크 자동 정리가 백업 계열마다 '복구 검사를 통과한 가장 새 사본'(`ledger_restore check` 와 같은 기준 + 잘림·WAL 머리 검사)을 지키고 그보다 옛 것만 지워요 —
  종전엔 잘리거나 검사 못 한 최신 사본만 남기고 멀쩡한 옛 사본을 지울 수 있었어요 · 손상·검사 불가인 새 사본은 지우지 않고 보류 · 검증된 사본이 없는 계열은 손대지 않음 · 교체 뒤 정리도 '검사 못 함'을 성공으로 보지 않아요.
- **옛 보유 토큰 찾기 — 1,000행 넘김** — 이더스캔 계열 `tokentx` 를 1,000행씩 이어 받아요(쌍별 이어 받기 표시 · 끝 블록 고정 · 같은 블록 넘김 · 응답 검사) — 종전엔 무료 키의 1,000행 상한을 목록 끝으로 보고 토큰 많은 지갑의 일부를 놓쳤어요 ·
  옛 기록은 한 번 다시 훑음 · 일부 출처가 실패해도 앞서 찾은 후보 유지 · 대사 조회 상한 = 후보 상한 · 상한을 넘는 후보는 조용히 버리지 않고 표시.
- **헬스 주의 — 기준 재정비 · 항목별 닫기** — 주의는 이용자가 할 일이 있거나 돈 숫자가 틀릴 수 있는 것만:
  시세 없는 실보유(평가 0 으로 총자산에서 빠짐)는 24시간 뒤 자동 접기를 없애고 판정에 상위 10개 미리보기가 아닌 전체 목록·자산 신원을 써요(11번째 새 코인도 잡음) · 값을 아는 거래소 대출 부채는 정상(칩·대시보드 카드) ·
  자동 회복되는 것은 오래 이어질 때만(위 업데이트 상자) · Rabby 기준 남은 차이 문구 정정(총자산에 빠져 있을 수 있는 몫).
  이용자가 대응할 수 없는 6종(시세 없는 보유 · 시세 출처 괴리 · 값 모르는 부채 · Rabby 남은 차이 · 잔고 대조 차이 · 미추적 체인 활동)은 줄마다 **닫기** — 코인·지갑·체인 단위로 기억해
  같은 내용이면 화면·텔레그램·하루 요약 모두 숨기고, 새 코인·지갑·체인이 생기거나 금액이 50% 그리고 $200 넘게 늘거나 오류로 오르면 다시 보여요 · '닫은 주의 N' 에서 되살리기 · 미추적 체인은 옆에 '지갑 추가 ›' ·
  닫기는 표시만(판정·원장·알림 기록 그대로) · 화면을 연 뒤 새 위험이 생기면 그 닫기는 거절 · 원장·잔고 불일치·음수 보유·재계산 승인·백업·디스크·프로세스는 닫기 없음 ·
  200자 넘는 긴 항목 신원(긴 Sui 코인 타입 등)은 자르지 않고 전체 해시로 기억해요(앞부분이 같은 다른 코인이 함께 숨지 않게 · 짧은 신원은 종전 그대로).
- **목록 한 쪽 10/20개** — 쪽으로 넘기는 모든 목록·검색 결과·시트의 한 쪽을 기기마다 고를 수 있어요(설정 › 화면 '목록 한 쪽' · 기본 10 · 바꾸면 첫 쪽) ·
  Solana 수집기가 시작할 때 끝났거나 버려진 진행 표식을 지우고 기록 넓히기 뒤 '서명 받는 중' 표식을 남기지 않아요(오래 멈춘 것처럼 보이던 것 · 표시 전용).
- **목록 '모두 보기' 없앰** — 쪽으로 넘기는 긴 목록(보유 코인 · 보관처 · 사이클 · 전체 이벤트 · 그날의 기록 · 보낸 내역 · 미매칭 · 추적 지갑 · NFT · 값 없는 토큰 · 설정 › 체인별 조회 등)은
  처음부터 설정 '목록 한 쪽'(10/20)만큼 보이고 바로 아래 '‹ 이전 · 1–10 / N · 다음 ›'예요 — 처음 몇 개 → 'N개 모두 보기' → 쪽 넘김 · 접기 단계가 없어졌어요 ·
  한 쪽에 다 들어가면 바가 없어요 · 접힌 꼬리를 설명하던 요약 줄(보유 '나머지 N종 · 합계' · 보관처 '외 N곳 · 합' 등)도 없어졌어요 ·
  목록마다 따로 정했던 한 쪽 크기(8·12·14개 등) 대신 설정 값 그대로(20 이면 그 목록들도 20개씩) · 찾아가기·필터를 바꾸면 첫 쪽·쪽을 넘기면 목록 맨 위는 그대로 ·
  대시보드 LP·레버리지 카드의 '앞 2줄 + N개 더'는 짧은 미리보기라 그대로예요.
- **QuickNode — 선택 칸 · 계속 거부되면 자동 복귀** — 상시 무료 플랜이 없어(1개월 체험 크레딧 1,000만·초당 15 → 유료) 선택 칸으로 바로잡았어요(필수 표시 없음 · 요금제 칩 '1개월 체험') ·
  키가 계속 거부되면(401·402·403·404 또는 크레딧·체험 끝 응답이 성공 없이 3번 · 2분 넘게) 그 체인에서 QuickNode 를 빼고 기본 노드로 돌아가요(설정 칸에 '키 거부됨' 줄 · 그 체인 유닛만 재시작) ·
  성공 1번 · 연결 테스트 통과 · 키 바꿈이면 다시 써요 · 429·시간 초과·5xx 는 거부로 안 셈.
- **Chainnodes — Base trace** — 새 선택 키 `TJ_CHAINNODES_KEY`(무료 Core 월 1,250만 요청 · 키 = 8-4-4-4-12 · Base 주소를 붙여 넣으면 키만 저장)를 Base 내부 이동 확인(trace)에만 써요(로그·잔고엔 안 씀) ·
  Base trace 순서 = 내 `trace_rpcs` → Chainnodes → QuickNode → 기본 노드 · 한도(-32005·429 — 알려 준 쉼 시간 존중)거나 그 제공자 이력 밖이면 같은 호출 안에서 다음 노드로(거래 실패로 안 봄) ·
  월 한도의 80% · 연결 시험 = 공개 최근 거래 1건 trace(내 지갑·거래 안 보냄). QuickNode 만 있을 때도 이제 QuickNode → 기본 노드(지난 판 '그 키 하나로 기다림' 한계 고침).
- **응답 본문 대기 상한** — 응답 본문을 읽을 때마다 다시 요청별 대기 시간(그것과 절대 마감 중 짧은 쪽)을 걸어, 헤더만 보내고 멈춘 노드가 요청과 호스트 자리를 120초 절대 상한까지 붙잡지 않아요.
- **같은 블록 안 거래 순서** — 같은 블록에서 매수 뒤 매도하면 화면 재생이 거래 해시 순으로 돌아 실현손익·남은 원가가 틀릴 수 있던 것 고침
  (예 $100 에 산 100개를 가진 채 같은 블록에서 100개를 $300 에 더 사고 100개를 $400 에 팔면 실현손익 $200 · 남은 원가 $200 이 맞는데 $300 · $300 으로 보임 — 보유 수량은 맞아서 잔고 대조로는 안 드러남) —
  수집기가 RPC·이더스캔·BNB Chain 응답의 거래 순번(트랜잭션 인덱스)과 로그 번호를 저장해 같은 블록 안에서도 실제 순서로 재생해요(순번 0 도 그대로 · 없거나 잘못된 값은 넣지 않음) ·
  **업데이트 뒤 새로 받는 거래부터**예요 — 이미 저장된 거래는 종전 순서 그대로이고 다시 받아도 원장이 바뀌지 않아요(자동 고침 없음 · 아래 알려진 한계).
- **새 체인 '거래 상세 누락' 주의 · 키 바꾸면 원장도 다시 시작** — Tron·Sui·TON·Bitcoin 수집이 재시도 상한 뒤에도 거래 상세를 못 받은 거래가 있으면
  상태 패널에 그 체인 주의(원장 계열 · 닫기 없음)와 09시 요약 줄이 떠요 — 그동안 그 체인 기초 잔고 대사는 보류돼요(종전엔 대사만 조용히 보류되고 아무 표시가 없었어요 · 다 받으면 주의도 사라짐) ·
  새 체인 키(`TJ_TRONGRID_KEY`·`TJ_TONCENTER_KEY`)나 체인 설정(`nonevm.<체인>` 제공자)을 바꾸면 그 체인 수집기와 함께 원장(tj-core)도 다시 시작해 대사가 새 키·제공자로 해요
  (종전엔 수집기만 다시 시작해 원장은 옛 값으로 대사 실패를 이어 갔어요 · 새 체인 지갑이 없는 설치는 종전 그대로 — 업데이트만으로 원장이 다시 시작하지 않음).
- **영수증 차트 색 통일** — 매수 점을 올릴 수 없는 영수증(원가를 입금으로 이어받은 세일 토큰 등)의 '매도만 차트'가 옛 노란색으로 그려지던 것 →
  매수+매도 차트와 같은 색(내 매도·평균 매도선 = 상승색 · 촛대 흐리게 · 범례도 같은 색).

**함께**

- **문서** — README '이번 판'·키 표(Chainnodes·TronGrid·toncenter · QuickNode 1개월 체험 · Alchemy 줄에 Base 보완)·기능 요약(새 체인)·유닛 표(새 유닛 4개)·재구축 디스크 정리 문단·English ·
  [API_KEYS.md](docs/API_KEYS.md) QuickNode 선택(1개월 체험)·Chainnodes·TronGrid·toncenter·Alchemy Base 보완 ·
  [COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) Base 줄(Alchemy 보완)·새 [Tron · Sui · TON · Bitcoin](docs/COLLECTION_LIMITS.md#tron--sui--ton--bitcoin) 절 · 설정 › 수집 한계 표 새 체인 줄 ·
  `.env.example` QuickNode 문구·Chainnodes·TronGrid·toncenter 칸.
- **도구** — `tools/repair_own_overlap.py`('내 지갑' 재분류 보유 중복 점검·복구) · `tools/ledger_restore.py`·원장 백업이 새 체인 수집 상태를 함께 다뤄요.
- **시험** — 공개 시험 추가: '내 지갑' 재분류 앵커·복구 도구 · 세일 정산·수동 참가금 처분 · BNB Chain 복구 뒤 다시 점검 · 디스크 정리 보호본 · 옛 보유 토큰 찾기 넘김 · 헬스 닫기·기준·긴 신원 ·
  Solana 진행 표식 정리 · QuickNode 선택·거부 복귀 · Chainnodes · 응답 본문 대기 · 새 체인 4개 수집기(합성 TronGrid·Sui GraphQL·toncenter·Esplora 서버 — 외부망 없이) · 주소 코덱·Bitcoin 파생 공식 벡터 ·
  새 체인 대사 보류·등록·복원·화면·검색 · TON 출금 도착 · Base Alchemy 보완·공정성 · 노드 선택 · 검색 긴 `wallet:` ·
  같은 블록 안 거래 순서(수집기 → 원장 → 화면 재생) · 새 체인 거래 상세 누락 주의 · 원장 다시 시작 지문 · 목록 바로 쪽 넘김 — 전체 7,500건 넘게(파일 226개).

**English · Tron, Sui, TON and Bitcoin wallets, external review fixes, dismissible warnings, node selection, Chainnodes** — This release combines two unpublished steps.
First, a full external review of the previous release found new bugs; every one was reproduced as a public test (failing before, passing after) and fixed. Marking an old outflow as "own wallet" after the
receiving wallet was already reconciled no longer double-counts the received amount (re-derivation offsets the reconciliation anchor); `tools/repair_own_overlap.py` detects and fixes ledgers already affected
(dry-run by default, idempotent). A fully refunded / zero-fill CCA bid restores the payment coin's original cost regardless of the first-seen-price setting, and manually linked sale payments are booked as disposals
of the paid coin. Ledger restore with a BNB Chain rewind stores a durable recheck range. Pre-rebuild disk relief keeps the newest backup copy that passes a restore check. Token discovery pages Etherscan-like
`tokentx` at 1,000 rows. Health warnings can be dismissed per item (shown again on a new coin/wallet/chain, a large increase or escalation; identities longer than 200 characters use a full-hash ID); lists page
10 or 20 rows per device and open on the first page right away (no 'show all' step). QuickNode is an optional key for a paid plan or the 1-month free trial and is dropped per chain while it keeps being refused; a new optional free Chainnodes key (`TJ_CHAINNODES_KEY`)
is tried first for Base internal-transfer traces. Response bodies are bounded by the per-request idle timeout on every read.
Second, read-only wallets on **Tron** (TronGrid), **Sui** (public GraphQL), **TON** (toncenter v3) and **Bitcoin** (public Esplora with failover — a single address, or a watch-only HD wallet from an
xpub/ypub/zpub or a public descriptor with receive and change branches scanned to gap 20; keys never leave the machine; 6 confirmations) are added from Settings › wallets. Each chain has its own unit
(`tj-tron`, `tj-sui`, `tj-ton`, `tj-btc`) that waits while that chain has no wallet. Their reconciliation holds instead of guessing (unresolved gaps, unknown decimals, empty balance fields, Sui sum mismatches,
TON jetton-wallet changes during a query); official Tron/TON USD₮ and Sui USDC are priced as stablecoins; search finds new-chain wallet names, addresses and hashes, and `wallet:` values are no longer
truncated (rejected above 128 characters). A TON exchange withdrawal is linked to its arrival when the exchange txid is the receiving transaction's hash. On Base, internal ETH transfers of old transactions
that every trace node fails to return are filled from Alchemy's internal-transfer list (one 120-CU call per block, blocks older than 1 hour, inside the 80% daily share), with fair retry ordering and the full
identifiers archived before an item expires. Collectors measure RPC nodes per chain and role and pick by speed (public nodes first in real time, with hysteresis; key nodes first when the backfill ETA exceeds
2 hours; `backfill.node_select: false` restores the fixed order), and the backfill banner shows the serving node. New optional keys: `TJ_TRONGRID_KEY`, `TJ_TONCENTER_KEY` (Sui and Bitcoin need none).
Finally, a review of everyday flows found that a buy and a sell in the same block could replay in hash order (wrong realized P&L and remaining cost); the RPC,
Etherscan and BNB Chain collectors now keep the transaction index and log index — for transactions collected after the update (stored ones keep their old order).
A new-chain transaction whose details still cannot be fetched after the retry limit now raises a health warning (that chain's reconciliation is held meanwhile),
and changing a new-chain key or provider restarts tj-core together with the collector.
No rebuild and no data revision; stop everything and run `pm2 start ecosystem.config.js` so the four new units are added.

**알려진 한계(다음 판에)** — 새 체인의 범위·못 받는 것은 [수집 한계 › Tron · Sui · TON · Bitcoin](docs/COLLECTION_LIMITS.md#tron--sui--ton--bitcoin), 그 밖 자세한 설명·피하는 법은 README [알아 둘 것](README.md#알아-둘-것).

- **Bitcoin 은 처음부터 단일 주소 또는 HD 지갑 하나로 등록하세요** — 같은 지갑을 그대로 지웠다 다시 넣는 건 되지만, 이미 기록한 단일 주소를 HD 지갑으로(또는 HD 지갑을 단일 주소로) 바꾸는 이전은 지원하지 않아요
  (지워도 원장 기록이 남아 같은 BTC 를 두 번 세요) · HD 지갑에 들어가는 주소를 따로 등록하지 마세요(등록 검사는 지금 찾는 범위(gap) 안의 주소만 막아요) ·
  설정 파일 직접 편집·백업 복원으로 생긴 겹침과 HD 지갑 두 개의 겹침은 등록 검사 밖이에요 · 한 제공자가 확정 높이 블록만 계속 '없음(404)'으로 주면 BTC 수집이 멈춘 채 기다려요(`nonevm.btc.esplora` 로 다른 제공자를 고르면 회복).
- **옛 Base 내부 이동** — 30일 넘게(실제로 5번 넘게 다시 해 본 뒤) 못 푼 옛 내부 이동은 자동으로 되살리지 않아요(Alchemy 를 물어 본 항목은 그 뒤 한 번 실패해도 만료되면 빠져요) —
  지우기 전에 전체 식별자를 `state/leaf_later_unresolved_<체인>.jsonl`·`state/trace_later_unresolved_<체인>.jsonl` 에 남길 뿐 다시 넣는 도구는 아직 없어요(이 판 전에 이미 빠진 항목은 기록도 없음) ·
  '회복한 추적 노드 다시 확인'은 블록 단위 대기열에만 있고 거래별 늦은 채움엔 없어요 · 대기열이 넘침 파일을 오가면 단계 기록이 사라져 몇 차례 늦어질 수 있어요 ·
  Alchemy 목록은 성공한 거래 안에서 일부만 되돌려진 호출(try/catch) 아래 이동을 가리지 못해요(드묾 — 잔고 대조가 차이를 드러내요).
- **Sui** — 한 지갑의 코인 합계 불일치(코인 + 주소 잔고 ≠ 총잔고)가 계속되면 그 지갑(체인 첫 대사면 Sui 전체)의 첫 대사가 보류된 채로 있어요(일시적이면 회복 뒤 진행) ·
  자릿수 정보가 없는 코인이 든 거래는 보류되고, 오래가면 그 지갑 대사도 보류돼요 · 스테이킹·DeFi 포지션 객체는 잔고에 안 잡혀요([수집 한계](docs/COLLECTION_LIMITS.md#tron--sui--ton--bitcoin)).
- **TON** — 거래소 출금 자동 연결은 거래소가 준 txid 가 **내 지갑이 받은 거래의 해시와 같을 때만**이에요 — 보낸 쪽 거래나 메시지 해시를 주는 거래소면 전송 중 동안 두 번 보이고(도착 뒤 사라짐) 원가가 이어지지 않아요
  (수동 원가 입력으로도 이중 표시는 안 풀려요) · 쓰는 거래소의 끝난 출금 기록 txid 를 내 지갑이 받은 거래 해시와 한 번 비교해 보세요 · 제톤 출금 연결은 따로 확인하지 않았어요 ·
  검증된 제톤 지갑이 제공자 목록에서 계속 빠지면 그 지갑 대사가 보류된 채로 · 조회 중 새 제톤 지갑 검증이 이어지면 첫 대사가 늦어져요 · 스왑은 확정하지 않아요(보낸 TON = 보낸 내역 · 받은 제톤 = 검토 유입) ·
  자릿수를 알 수 없는 스팸 제톤을 들고 있으면 TON 대사가 보류돼 TON 잔고가 늦게·작게 보일 수 있어요 · TON 시세는 바이낸스 TONUSDT 거래 정지로 0 으로 보일 수 있어요(다음 판).
- **Tron** — 동결(Stake 2.0)·해제 대기 TRX 는 유동 보유에서 빠지고 '보낸 내역'(실현 아님)으로 보여요(보유는 기타 자산으로) ·
  대사 때 `balanceOf` 를 거부한 토큰과, 잔고 있는 토큰이 30개를 넘을 때 그 밖 토큰은 '관측 못 함'으로 빼고 대사를 끝내 기초 잔고가 안 잡힐 수 있어요(다음 주기에 나머지를 이어 묻지 않음) —
  토큰이 많은 Tron 지갑은 보유 표와 지갑 앱 잔고를 한 번 비교해 보세요.
- **새 체인 공통** — 그 체인 수집이 아직 못 푼 거래(대기·빈 구간)를 남긴 동안에는 관련 지갑을 지우지 마세요(함께 걸린 다른 내 지갑이 그 거래를 기록 없이 기초 잔고로 흡수할 수 있어요 — 수량은 맞고 거래 내역·원가 근거가 빠짐) ·
  TronGrid·toncenter 키는 아직 `.env` 로만 · 설정 목록의 새 체인 지갑 이름 바꾸기는 브라우저 기본 입력 창 · 스팸 토큰을 원장 숨김으로 잇지 않아요(가치 없음 · 검토 줄에 보일 수 있음) ·
  네이티브·공식 스테이블 밖 새 체인 토큰은 DEX 시세 연결이 아직 없어요 · 거래소 자산 'TON' 이 다른 코인이면 네이티브 TON 과 같은 이름으로 묶일 수 있어요 ·
  Bitcoin HD 지갑의 파생 주소로는 검색이 안 돼요 · 키 없는 공용 경로는 옛 기록이 느려요(Tron 시간당 거래 약 1,400건) ·
  TON 제공자가 응답을 끝없이 늦추거나 BTC·Sui 제공자가 고장 응답(같은 쪽 되풀이 · 지나치게 큰 응답)을 반복하면 그 체인 수집이 멈출 수 있어요(다음 판).
- **노드 선택** — 판정 기준(역할별 시간·실패율·창 크기·2시간)은 첫 값이에요(`backfill.node_slo_sec`·`backfill.bf_target_sec` 로 바꿈) · 관측은 프로세스 메모리라 재시작하면 표본이 다시 찰 때까지 종전 순서 ·
  옛 기록 채우기 예상 시간은 단일 평균이라 병목이 블록 훑기·trace 여도 상세·옛 상태를 키 노드로 옮길 수 있어요(하루 몫 80% 안) · 최신 블록 훑기(getLogs)의 공개↔키 전환과 BNB Chain 상세·아카이브 노드 선택은 아직 없어요.
- '내 지갑' 복구 도구는 차이가 대사 전 '내 지갑' 받은 몫과 정확히 같을 때만 고쳐요 — 판정을 여러 번 바꿔 일부만 대사 전에 재분류됐거나 나중 기초 잔고가 대사 전 자리에 생긴 칸은 목록만(직접 확인) · Solana 재분류는 도구 대상 밖(재발 방지는 Solana 도 적용).
- 세일 환불을 네이티브·비스테이블 코인으로 받은 것은 아직 연결 못 하고, 여러 지급 코인과 환불이 섞인 목적지는 처분을 보류해요(보류 사유는 화면에 아직 안 보임) ·
  수동 연결 참가금의 처분 날짜는 첫 토큰 수령일, 원화 환율은 보낸 때예요(자동 세일은 확정 시각 환율).
- 원장 복구 뒤 다시 점검 구간보다 앞 블록에서(백업 뒤 끝난 긴 복구·30일 지난 누락 탐색) 찾았던 입금은 범위 밖이에요(`ledger_restore --margin-hours` 로 넓힘) ·
  이 판 전에 이미 되감기 복구를 한 설치는 `state/bsc_balw_recheck.json` 에 `{"since": <백업 시각>}` 으로 다시 점검을 요청하세요(그 지갑 작업이 계속 있으면 늦게 시작).
- 손상·검사 불가로 판정된 새 백업은 자동으로 지우지 않아 그 공간이 꼭 필요하면 재계산이 '디스크 부족'으로 멈춘 채 정리를 기다려요 · WAL 중간 프레임 손상은 가려내지 못해요 ·
  이미 지워진 옛 백업은 되살릴 수 없어요 — 지금 정상 원장으로 새 백업(`tools/offsite_backup.py` · 일일 백업)을 만들어 두세요.
- 옛 보유 토큰 찾기 후보가 지갑당 3,000개를 넘으면 넘은 것은 표시만 하고 조회하지 않아요 · 한 블록에 1만 행 넘게 받은 지갑은 그 블록 나머지가 미확인 · 대사 뒤 새로 찾은 토큰은 기초 잔고를 자동으로 잡지 않아요(잔고 대조·음수 안전망이 받침).
- 헬스 닫기: 알림 수준을 '주의'로 낮춘 설치는 닫기 직전 대기열에 들어간 주의 알림이 한 번 나갈 수 있어요 · 값 모르는 부채는 금액 없이 기억해 수량이 늘어도 다시 안 보여요(새 거래소·코인이면 보임) ·
  닫은 기록은 만료 없이 되살리기로만 지우고 설정 백업·복원에 안 들어가요 · 줄어드는 금액은 다시 띄우지 않아요.
- 같은 블록 안 거래 순서는 업데이트 뒤 새로 받는 거래부터예요 — 이미 저장된 같은 블록 매수·매도(RPC·이더스캔·BNB Chain 으로 받은 것)는 종전 순서로 재생돼
  실현손익·남은 원가가 어긋난 채로 남을 수 있어요(보유 수량은 맞음 · 자동 고침 없음 · 블록스카웃 상세로 받은 거래는 원래 순번이 있어 해당 없음).
- 빗썸 지정가 주문이 일부만 체결된 채 열려 있다가 취소되면, 잠깐(다음 대사까지 — 기본 조회 간격이면 약 20분) 그 코인 보유가 실제보다 많게 보일 수 있어요 — 저절로 맞춰져요.
- 원장 복원 도구(`tools/ledger_restore.py`)로 백업 이후 새 코인이 생긴 원장을 되돌리면, 손으로 넣은 코인별 원가(수동 원가)가 다른 코인에 붙을 수 있어요 — 복원 뒤 설정의 수동 원가를 다시 확인하세요 ·
  이 도구가 찍는 pm2 멈추기·켜기 안내엔 새 체인 유닛(`tj-tron`·`tj-sui`·`tj-ton`·`tj-btc`)이 빠져 있어요 — README [백업 · 복구](docs/OPERATIONS.md#백업--복구)의 명령을 쓰세요(다음 판).
- QuickNode 체험 끝·크레딧 소진의 실제 응답 꼴은 실측하지 못해 HTTP 401·402·403·404 와 문구로 판정해요(다른 꼴이면 일시 실패로 재시도) · 같은 키를 유료로 바꿨으면 연결 테스트를 눌러야 다시 써요 ·
  호출이 드문 설치는 거부 판정까지 수십 분 걸릴 수 있어요(그동안 trace 는 다음 노드) · Chainnodes 키 거부는 자동으로 빼지 않아 trace 마다 1콜씩 버려요 · Chainnodes 냉각은 프로세스마다 따로예요.
- 지난 판 한계(업비트 3주문 이상 부분 상쇄 · BNB Chain 제3자 내부 입금 겹침 · 아카이브 키가 쉬는 날 옛 구간 채우기 · 창 넓힘 재구축 · CCA 처분 시각 · 도중 디스크 가득 · HyperEVM 이더스캔 의존 등)는 그대로예요 —
  [2026-10-11 (2)](#2026-10-11-2--외부-검토-2건-버그-수정--quicknode-trace--hyperevm) · 그중 'QuickNode 키면 Base trace 는 그 키 하나'와 '수동 연결 참가금 처분 없음'은 이번에 고쳤어요.

## 2026-10-11 (2) — 외부 검토 2건 버그 수정 · QuickNode trace · HyperEVM

**업비트 같은 코인 사고팔기 부분 체결 · BNB Chain 같은 블록 입금·긴 공백 복구·지난 누락 복구 차례 · 늦게 온 옛 거래 → 기초 잔고 바로 보정 · 기초 잔고 보정 → 지난 곡선 ·
세일(CCA) 결제 코인 사용분 손익 · EVM trace 노드 순서·마감 · 재계산 실패 원인·디스크 자동 정리 · QuickNode 멀티체인 키 하나(Base trace) · 노드 키 버스트 자동 · HyperEVM · 화면·수집 응답 상한**

지난 판(2026-10-11)을 읽은 외부 검토 두 건이 새로 찾은 버그를 하나씩 공개 시험으로 재현해(고치기 전 실패 → 고친 뒤 통과) 고친 판이에요 —
업비트에서 같은 코인 매수·매도 지정가가 함께 부분 체결된 채 두 주문이 서로 다른 날 기록되면 지난날이 체결 금액만큼 어긋나던 것, BNB Chain 의 같은 블록에 직접 입금과 로그 없는 내부 입금이 함께 오면 내부 입금이 사라지던 것,
대사 뒤에 늦게 들어온 수집 기간 안 옛 거래가 재계산 전까지 기초 잔고와 두 번 잡히던 것, 기초 잔고를 고친 뒤 그보다 옛 지난 곡선이 옛 값으로 남던 것, 세일(CCA) 결제 코인의 실제 사용분 손익이 빠지던 것,
느린 trace 노드 하나가 Base 따라잡기를 몇 분씩 붙잡던 것. QuickNode 는 멀티체인 키 칸 하나로 바꿔 Base 내부 이동 trace 에(남는 몫은 옛 잔고) 쓰고, HyperEVM 을 이더스캔 무료 키로 받는 체인으로 더했어요.
드문 경우는 아래 알려진 한계에 적었어요. 사진은 다시 찍지 않았어요(README '이번 판' 안내).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` — 유닛을 전부 멈춘 뒤 한꺼번에 시작 ·
> 공통 모듈이 바뀌어 이번엔 모든 유닛).
> 재구축·데이터 개정은 없어요(코드만 되돌려도 돼요 · 새로 생기는 칸 — `state/bsc_balw.json` 의 보류 요청·지갑 순번·복구 대기 표시 · 원장 메타와 `state/ext_rebuild_status.json` 의 재계산 실패 원인 · 일별 캐시의 주문별 원화 몫 — 은 옛 코드가 읽지 않음).
> 업데이트 전에 이미 굳은 지난날(업비트 같은 코인 사고팔기)은 소급하지 않아요 — 새로 계산하는 날부터 맞아요.
> QuickNode 를 체인별 칸(옛 `TJ_QUICKNODE_BSC_KEY`·`TJ_QUICKNODE_BASE_KEY`)으로 쓰던 분은 **설정 › 연결·키 › QuickNode** 에 멀티체인 엔드포인트 주소(아무 체인 주소 하나)를 다시 저장하세요 —
> 옛 칸은 새 칸이 비었을 때만 읽고, 새 칸을 저장하면 지워져요. 같은 칸에서 요금제도 확인하세요(무료 플랜이 생겨 요금제를 고른 적이 없으면 무료로 봐요 · 유료 기본 사용 비율 10% → 80% — 다른 곳과 나눠 쓰는 키면 낮추세요).
> 재계산 교체 전 원장 보존본은 이제 기본 1개(직전 원장)라 다음 재계산이 끝나면 더 옛 보존본이 정리돼요 — 옛 키 `backfill.rebuild_keep_recent`·`rebuild_keep_oldest` 를 직접 적어 둔 설치는 그 값 그대로예요.

- **업비트 같은 코인 사고팔기 — 부분 체결** — 같은 코인에 매수·매도 지정가를 함께 걸어 둘 다 일부 체결돼 순수량이 0인 채 하루가 넘어가고 두 주문이 서로 다른 날 원장에 기록되면 그 전날·지난 곡선이 체결 금액만큼 어긋나던 것 고침 —
  순수량 0 묶음은 주문별 원화 몫을 따로 두고(묶음 중 하나라도 그날 마감 전에 기록됐을 때만 주문별로 맞춤), 원화 자가 점검 제외는 순현금이 0 이어도 주문별 미기장 원화 흐름이 있으면 켜요 ·
  화면 일별 값·저장 일별 캐시·장기 곡선이 같은 값 · 재시작·일별 동결 삭제·다음 날에도 같은 값 · 수수료·반대 방향·도착 순서·낡은 스냅숏·부분 마감도 같은 규칙.
- **BNB Chain 잔고 감시 — 같은 블록 입금 · 긴 공백 · 지난 누락** — 같은 블록에 직접 입금과 로그 없는 내부 입금(컨트랙트가 보낸 BNB)이 함께 오면 남는 몫을 방금 회수한 직접 입금에 붙여 '내 지갑 → 내 지갑'(순증 0)으로 만들던 것 고침 —
  남는 몫은 보낸 쪽이 코드 있는 컨트랙트이고 붙인 뒤 순증이 맞을 때만 그 거래에 붙이고, 아니면 그 블록 시각의 기초 잔고(원가 미확인)로 · 그 요청은 직접 입금이 원장에 들어간 뒤에 써요(같은 몫 두 번 방지) ·
  공백 복구 작업이 블록을 풀어 가는 동안은 160콜에서 끊지 않아요(하루 꺼진 뒤 입금 수십 건도 원래 블록·시각의 실제 거래로 · 실행당·하루 호출 상한은 그대로) ·
  최신 입금이 계속 와도(그 지갑 자신에게 와도) 대사가 확인한 지난 누락 복구가 몫을 받아 몇 주기 안에 시작해요(가장 오래 기다린 지갑부터 · 최신 작업과 걸음마다 번갈아 · 상태 정보 `balw.hist_wait`).
- **늦게 온 옛 거래 → 기초 잔고 바로 보정** — 대사(기초 잔고)가 이미 흡수한 수집 기간 안 옛 거래가 대사 뒤에 처음 원장에 들어오면(공개 trace 노드가 아팠다가 회복 · 노드 키를 나중에 넣음 · 탐색기 늦은 색인 · BNB Chain 과거 복구)
  종전엔 재계산(재구축) 전까지 두 번 셌어요 — 이제 그 거래 효과만큼 기초 잔고를 같은 트랜잭션에서 바로 고쳐요(재구축 결과와 같은 값 · 재구축 대기·손익 승인 요청이 생기지 않음) ·
  수집 시작일을 앞당겨 들어온 옛 조각 · 수집 시작일을 앞당긴 뒤 아직 재구축이 지나가지 않은 체인 · Solana · 발견 시점 기초 잔고 칸은 종전처럼 재구축으로.
- **기초 잔고 보정 → 지난 곡선** — 늦은 내부 이동 복구·재기장·나중 등록 지갑 등으로 기초 잔고 행이 바뀌면(수정·삭제·부호·시각 이동) 그 전후 가장 이른 날부터 지난 곡선 표식을 같은 트랜잭션에 남겨요
  (종전엔 거래 날부터만 → 수집 시작일~거래 전날 장기 곡선이 옛 값) · 화면이 수집 시작일로 소급하는 칸(음수 대사·발견 시점 기초 잔고)은 수집 시작일부터 · 바뀐 게 없으면 표식 없음 · Solana 도 같은 규칙.
- **세일(CCA) 결제 코인 사용분 손익** — 입찰에 실제로 쓴 몫(입찰 − 환불)을 입찰 종료 시각에 결제 코인 처분으로 기록해요(대가 = 받은 토큰에 준 시장가 원가 · 비용 = 그 몫의 원래 원가) —
  받은 토큰을 다 판 뒤 실현 합이 현금 증가와 같아요(종전엔 결제 코인 원가와 시장가의 차이가 어느 실현에도 안 들어감) · 일반 스왑과 같은 출력(사이클·보관처 실현·양도차익 명세·스테이블 환차·원가 미확인 몫·영수증·
  그날 기록 '토큰 세일 대금 지불'·일별 건수·세일 상자 '결제 코인 사용' 줄) · 입찰마다 한 번만 · 원가 미확인·전액 환불·세일 연결 끔이면 종전 · 종료 시각이 이상한 입찰은 그 입찰만 건너뜀 ·
  세일 토큰 자리수 0 을 18 로 바꾸던 것 고침.
- **EVM trace 노드 · 따라잡기 마감** — 시간 초과를 낸 trace 노드는 5분 동안 순서 맨 뒤로(느린 첫 노드가 둘째를 굶기던 것) · 남은 예산으로 깎은 짧은 대기의 시간 초과·연결 오류는 노드 실패로 안 셈 ·
  'missing trie node'·'history has been pruned' 같은 '옛 상태 없음' 응답이면 늦은 채움 항목을 정리 · 아카이브 키 노드가 하루 몫·서킷으로 쉬는 동안 옛 구간(뒤 차선)은 정합 없이 넘기지 않고 다음 사이클까지 기다려요(초기화·최신 수집은 계속) ·
  잎 블록 선조회·상세 조회가 사이클 마감 하나를 나눠 써요(잎 20개가 모두 408 이면 440초 → 60초) · 뒤 차선 일이 없으면 재시작 때 '과거 창 확장 중' 표식을 남기지 않아 재계산이 재시작마다 1시간씩 밀리지 않아요 ·
  아주 깊은 callTracer 응답(재귀 한도)·넘침 파일의 깨진 줄 처리.
- **재계산 실패 원인 · 디스크 자동 정리** — 재계산(재구축) 실패를 원인 코드로 저장해 상태 패널·설정 › 과거 데이터에 보여요(디스크 공간·일시 오류·무결성·포지션 게이트·손익 승인 등) ·
  시작 전에 디스크가 모자랐던 경우만 두 디스크(임시 사본·원장) 여유를 다시 재어 충분해지면 몇 분 안에 다시 해요(다른 원인은 종전 6 → 12 → 24시간) ·
  모자라면 먼저 이 프로그램이 만든 옛 파일만 정리(12시간 넘은 죽은 재계산 사본 · 옛 보존본·여분 일일 백업은 최신 1개만 · 3일 지난 롤백 흔적 — 지금 원장·최신 백업·실행 중일 수 있는 사본은 안 건드림 · 모자란 디스크에 있는 것만) ·
  교체 전 원장 보존본 기본 1개(`backup.keep_pre_rebuild` 1~5) · 옛 보존본은 교체가 끝나고 새 보존본이 확인된 뒤에만 지워요.
- **QuickNode — 멀티체인 키 하나 · Base trace** — `TJ_QUICKNODE_KEY` 칸 하나에 멀티체인 엔드포인트 주소(아무 체인 주소)를 넣으면 체인별 주소는 봇이 만들어요 · 무료 플랜도 돼요(월 크레딧의 80% · 초당 15 의 80%) · 유료 기본 사용 비율 80% ·
  잘하는 일에만 써요 — Base 거래의 내부 이동 trace(이 키가 있으면 Base trace 는 이 키 하나 · 실패하거나 하루 몫을 다 쓰면 다른 노드로 새지 않고 오류를 보인 뒤 다음 차례에) + 남는 몫으로 BNB Chain·Base 옛 잔고·nonce 확인 ·
  블록 훑기(getLogs)엔 안 써요(무료 플랜은 한 번에 5블록) · 키 저장 확인 = Base 1콜 · 연결 테스트 = Base 최근 거래 trace 1건.
- **노드 키 버스트 — 켤 것 없이 자동** — 무료 노드 키·Helius 의 따라잡기 버스트가 이 봇이 실제로 쓴 양으로 판단해요(사용 기록이 없는 지난날 = 0) — 업데이트·새 키 뒤 한 달쯤 버스트가 거의 없던 것과 '새로 받은 키' 칩을 없앴어요 ·
  날짜별 사용 기록이 손상돼 버린 적이 있으면 그 전은 종전처럼 평소 몫을 쓴 것으로 셈(보수) · 하루 몫·최근 31일 80%·실시간 예비는 그대로.
- **HyperEVM** — HyperEVM(체인 999)을 이더스캔 V2 목록으로 받는 체인으로 더했어요 — 이더스캔 무료 키가 있으면 다른 추가 EVM 체인처럼 활동 있는 지갑에서 켤 수 있어요(`chain_sweep` — 기본은 알림만, `auto_enable` 이면 자동 · 키가 없으면 '이더스캔 무료 키 필요' 경고만) ·
  공개 RPC 는 getLogs 가 1,000블록씩이라 수집에 안 쓰고, 이더스캔이 막히면(하루 몫·장애) 다른 길로 돌지 않고 오류를 보인 채 기다렸다 이어 받아요 · HYPE 시세·탐색기 링크·DEX 시세 망 ·
  HyperCore 와 오간 이동은 시스템 주소 상대 입출금으로 보여요 · 이더스캔 키를 나중에 지워도 이미 받은 HyperEVM 은 켠 채 수집만 멈춰요(Rabby 잔고와 이중 합산 방지) ·
  이더스캔 전용 체인이 이더스캔 하루 한도 쉼 동안 EVM 수집기 시작을 막던 것 고침.
- **화면 · 수집 응답 상한** — 변동 분해 상세를 빌드 색인과 한 객체로 게시(빌드 도중 일부 날이 빠진 응답 없음) · 달러로는 0 이고 원화만 있는 선물 줄 보존(남는 차는 '그 밖 정산') · 값 없는 토큰 목록 20개씩 쪽 ·
  보유표 Rabby 기준 하위 행이 본행과 같은 쪽(종 수 = 코인 묶음 수) · 분해 시트에서 영수증·코인으로 넘어간 뒤 뒤로 가기가 헛돌던 것 · 보낸 내역 대기 사유를 바꾸면 첫 쪽 ·
  블록스카웃 상세 목록 누적 상한(200쪽·2만 개·32MB — 넘으면 부분 목록을 완료로 저장하지 않음) · RPC 응답 본문 수신 전체 마감(아주 느리게 흘려 보내는 노드가 trace 마감을 넘기던 것 — 지난 판 알려진 한계 고침).

**함께**

- **문서** — README '이번 판'·키 표·버스트·재구축·알려진 한계 · [API_KEYS.md](docs/API_KEYS.md) QuickNode·HyperEVM·버스트 · [COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) HyperEVM 절·Base 줄 · `.env.example` QuickNode 한 칸.
- **시험** — 공개 시험 추가: 업비트 순수량 0 부분 체결(실제 코어 수집 → 실제 화면 빌드 · 무작위 경계 포함) · BNB Chain 같은 블록 귀속·요청 순서·공백 복구 상한·지난 누락 차례 · 늦은 옛 거래 즉시 흡수(재구축과 같은 값) ·
  기초 잔고 보정 곡선(실제 코어 → 화면 → 장기 곡선) · 세일 결제 코인 처분·세일 상자 · trace 노드 순서·마감·보류 · 재계산 원인·디스크 정리 · 블록스카웃·본문 수신 상한 · 뒤로 가기·쪽 넘김 · QuickNode 멀티체인 · HyperEVM —
  전체 5,600건 넘게(파일 169개).

**English · External review fixes, QuickNode trace, HyperEVM** — Two external reviews of the previous release found new bugs; every one was reproduced as a public test (failing before, passing after) and fixed.
Upbit: buy and sell limit orders on the same coin that both partially fill to a net-zero position no longer shift the previous day and past curves when the two orders are booked on different days
(per-order KRW share kept for net-zero groups; the KRW self-check exemption now follows any unbooked per-order cash flow). BNB Chain balance watch: a same-block direct deposit plus a log-less internal credit
no longer collapses into a self-transfer (the residual becomes an opening balance at that block, written only after the direct transaction is in the ledger); gap-recovery jobs that keep resolving blocks are no
longer cut at 160 calls; historical-shortfall recovery gets a reserved slot and alternates with live work, so it starts under continuous inflow. Core: an in-window old transaction that arrives after the
reconciliation (a trace node recovered, a node key added later, late explorer indexing) now reduces the absorbing opening balance immediately — the same result as a ledger rebuild — instead of being counted
twice until a rebuild; opening-balance changes mark past curves from the anchor's date in the same transaction. Token sales (CCA): the actually spent part of each bid (bid − refund) is booked as a disposal of
the payment coin at the bid's exit time, so a full round trip's realized PnL matches the cash change; sale decimals of 0 are kept. EVM RPC: timed-out trace nodes move to the back for 5 minutes, budget-cut
timeouts no longer count as node failures, pruned-state errors retire late-fill items, an archive key at rest holds only the back-fill lane, leaf prefetch and detail calls share one cycle deadline, and restarts with
no back-fill work left no longer delay the rebuild by an hour. Rebuild failures store a cause code; only a pre-check disk shortage retries within minutes once space frees (after cleaning old program-made copies on
the short volume); one pre-rebuild ledger copy is kept by default, and older ones are removed only after a verified swap. QuickNode: one multichain endpoint (`TJ_QUICKNODE_KEY`; free plan at 80%, paid default 80%)
used for Base internal-transfer traces and, with what is left, old BNB Chain/Base balances — never for getLogs. Node-key and Helius bursts now count only this bot's recorded use (no "new key" chip). Added HyperEVM
(chain 999) as an Etherscan-V2-only chain (needs the free Etherscan key; waits instead of falling back). Also: attribution details are published together with their build index, KRW-only futures rows are kept,
the zero-value token list pages 20 at a time, Rabby sub-rows stay on their parent's page, Back works after the breakdown sheet, Blockscout detail pagination is capped and HTTP response-body download time is
bounded. No rebuild and no data revision.

**알려진 한계(다음 판에)** — 자세한 설명·피하는 법은 README [알아 둘 것](README.md#알아-둘-것).

- 업비트 같은 코인 주문이 셋 이상 묶여 그중 일부끼리만 상쇄되면 그 몫의 원화가 다음 날로 넘어갈 수 있어요(값은 일관 — 어느 날에 잡히느냐만) · 업데이트 전에 이미 굳은 날은 그대로예요.
- BNB Chain 같은 블록에 남의 로그 없는 내부 입금이 겹치면 내 컨트랙트 호출 거래에 붙을 수 있어요(금액은 맞음 · 거래 단위 손익 귀속만) · 실행당 호출 상한을 넘는 빈도로 입금이 계속되면 넘친 최신 입금은 기초 잔고(원가 미확인)로 마감돼요(금액 보존) ·
  지난 누락 복구는 실행(약 1분)마다 지갑 하나씩 시작해요.
- 아카이브 키 노드가 하루 몫을 다 쓰고 공개 노드가 옛 상태를 못 주는 날엔 EVM 옛 구간 채우기(뒤 차선)만 UTC 자정까지 쉴 수 있어요(최신 수집은 계속) · 상세 마감에 걸린 새 토큰의 심볼은 다음 상세 때까지 빈 칸일 수 있어요.
- 수집 시작일을 앞당기면 재계산(재구축) 1회는 여전히 필요해요 · Solana·발견 시점 기초 잔고 칸의 늦은 옛 거래도 종전처럼 재구축으로 · 기초 잔고를 고칠 때 수집 시작일부터 장기 곡선을 다시 계산해 계산이 조금 늘어요.
- 세일(CCA) 결제 코인 처분 시각은 입찰 종료(사용량 확정) 시각이에요(대가는 입찰 시각 시세) · 보낸 내역에서 손으로 '받은 것과 연결'한 참가금은 종전처럼 결제 코인 처분 없이 원가로 이어져요.
- 재계산이 시작된 뒤 디스크가 가득 찬 경우와 영어가 아닌 OS 오류 문구는 디스크 원인으로 보지 않아 종전 대기(6시간부터)를 따라요.
- HyperEVM 은 이더스캔 하나에만 기대요(장애 땐 기다림) · HyperCore↔HyperEVM 이동은 Hyperliquid 연결의 입출금과 짝을 잇지 않아요(총자산은 맞음 · 원가 이어 주기 없음) · opBNB·Celo 는 아직 없어요.
- QuickNode 키를 넣으면 Base trace 는 그 키 하나라, 키가 실패하거나 하루 몫을 다 쓰면 Base 내부 이동 채우기가 회복될 때까지 늦어져요(다른 노드로 우회 안 함 · 거래는 먼저 기록).
- 지난 판 한계(업비트 체결 시각 · BNB Chain 공백 구간 기다림 · 라우터 경유 CCA 입찰 · 늦은 행 마감 시세 근사 · 키 노드 없는 Base 따라잡기 · 변동 분해 상세 상한 등)는 그대로예요 —
  [2026-10-11](#2026-10-11--외부-검토-2건-버그-수정--목록-정리).

## 2026-10-11 — 외부 검토 2건 버그 수정 · 목록 정리

**업비트 미기장 체결 원화 이력 · BNB Chain 잔고 감시 긴 공백 · 세일(CCA) 환불 지급 코인 원가 · 늦은 원장 행 첫 주기·자정 경계 · EVM 따라잡기 trace 마감·영속 보류 ·
긴 목록 20개씩 쪽 넘김 · 변동 분해 줄 → 무엇 때문인지 · 수집기 정지 한 줄 · 긴급 알림 자격**

지난 판(2026-10-10 (3))을 읽은 외부 검토 두 건이 새로 찾은 버그를 하나씩 공개 시험으로 재현해(고치기 전 실패 → 고친 뒤 통과) 전부 고친 판이에요 —
업비트 지정가 주문의 첫 부분 매수·같은 코인 사고팔기 동안 어제·지난 곡선이 체결 금액만큼 어긋나던 것, BNB Chain 잔고 감시가 30분 넘게 쉬면 그 사이 받은 BNB 를 버리던 것,
세일(CCA) 부분 환불로 돌아온 지급 코인이 원래 원가 대신 환불 때 시세로 다시 잡히던 것, 업데이트 직후 첫 주기·자정 직전에 들어온 늦은 거래가 표식 없이 지나가던 것,
공개 trace 노드가 아플 때 EVM 따라잡기가 멈추고 미룬 내부 이동 확인이 조용히 사라질 수 있던 것. 화면은 끝없이 길어지던 목록을 20개씩 쪽으로 넘기게 정리했고,
변동 분해 줄을 누르면 무엇 때문인지 보여요. 드문 경우는 아래 알려진 한계에 적었어요. 사진은 다시 찍지 않았어요(README '이번 판' 안내).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` — 유닛을 전부 멈춘 뒤 한꺼번에 시작 ·
> 이번에 코드가 바뀐 유닛 = 웹·코어·EVM·BNB Chain·업비트·해외 거래소·알림).
> 재구축·데이터 개정은 없어요(코드만 되돌려도 돼요 · 새로 생기는 칸 — `state/bsc_balw.json` 의 미해결 구간 · EVM 커서의 미룬 trace 선등록 · 대기열이 넘칠 때만 `state/trace_later_overflow_<체인>.jsonl` ·
> 일별 캐시 마감 스냅숏의 원장 수위 — 은 옛 코드가 읽지 않음).
> 업데이트 뒤 첫 코어 기동이 첫 수집 전에 원장 메타에 늦은 거래 울타리를 적어요 — 그 뒤 들어온 지난 거래부터 지난 곡선을 고치고, 업데이트 전에 이미 굳은 날은 소급하지 않아요.
> 2026-10-10 (3) 판을 쓰는 동안 봇이 30분 넘게 멈춘 적이 있으면(정지·노드 장애) BNB Chain 에 그 사이 받은 BNB 를 놓쳤을 수 있어요 — `state/bsc_balw_recheck.json` 에 `{"hours": 48}`(다시 볼 시간 수)을 두면
> 최근 그만큼을 원장 기록과 옛 블록 잔고로 다시 점검해요(아카이브 키 필요 · 처리하면 파일은 저절로 지워짐).
> Ankr 무료 키가 있으면 오래 꺼졌다 켜지거나 새로 설치해 최근 구간을 따라잡는 동안만 Base 등 RPC 체인의 잔고·nonce 확인을 키 노드에 먼저 보내요(하루 몫 80% 안 · 넘으면 공개 노드로 · 평소엔 종전처럼 공개 노드 먼저).

- **업비트 미기장 체결의 원화 이력** — 지정가 주문이 끝나기 전(원장 기록 전) 체결된 몫의 원화 현금 이동을 코인 수량 보정과 따로 지난날 원화 되감기에 넣어요 —
  업비트에 없던 코인의 첫 부분 매수(코인은 업비트 실시간 잔고 행)·같은 코인을 사고팔아 순수량이 0인 체결에서 어제·지난 곡선이 체결 금액만큼 어긋나던 것 고침(30일 곡선·장기 곡선 같은 값 · 수수료 포함) ·
  그 스냅숏 시각 전 날로 이어 쓰는 업비트 코인은 체결 전 수량으로(이중 계상 없음) · 지난 판이 체결 뒤 수량으로 굳힌 지난날은 업데이트 뒤 한 번 맞춤(그때 부분 체결이 열려 있을 때) ·
  늦은 거래로 그날 마감 스냅숏을 버리고 다시 계산할 때도 체결 원화를 같은 자리로(몇 번 다시 계산해도 같은 값) · 업비트 잔고가 10분 넘게 낡은 동안 미기장 체결이 있으면 그 스냅숏을 그날 마감 재료로 쓰지 않아요.
- **BNB Chain 잔고 감시 — 긴 공백 뒤에도** — 봇 정지·노드 장애·되돌리기로 30분 넘게 못 돌았어도 잔고 체크포인트를 버리지 않고 그 공백을 미해결 구간으로 저장해(`state/bsc_balw.json` · 재시작에도 유지)
  원장 거래로 다시 설명하고, 내 발신 수가 nonce 와 맞을 때 남는 증가를 원래 블록·시각의 실제 거래로 한 번만 기록해요(금액 문턱 없음) · 원장 읽기 실패·예산 소진이면 구간을 그대로 두고 다음에(성공으로 기록 안 함) ·
  공개 노드 없이 아카이브만 넣은 구성에서 지갑이 13개 이상이면 잔고 감시가 영영 안 돌던 것 · 아카이브가 옛 상태를 못 주면('missing trie node'·빈 응답) 공개 노드로, 세 번 이어지면 기초 잔고 ·
  한 블록 직접 입금 6건째부터 빠지던 것 · 지난 누락 탐색이 실패해도 하루 미뤄지던 것(10분 뒤 다시) · 지난 판 공백 다시 점검 요청 파일(위 업데이트 상자).
- **세일(CCA) 부분 환불 — 지급 코인 원가** — 입찰에 보낸 ETH 등이 일부 환불되면, 환불 때 시세로 새로 취득하던 것(최초 인식 시가를 끄면 원가 미확인) 대신 입찰 때 보낸 원가 중 환불 비율만큼을 되돌려요
  (체인·입찰자·지급 자산·종료 거래가 맞는 환불만 · 확인된 환불량까지 · 한 번만 · 여러 입찰·여러 번 부분 환불은 비례) → 그 코인을 나중에 팔 때 원가·실현손익·양도차익 명세가 맞아요 ·
  원가가 미확인이던 몫은 미확인 그대로 · 입찰 송금이 무관한 '프로그램 예치 왕복' 짝이 돼 원가가 두 번 돌아오던 것 고침 · 받은 토큰 원가(지난 판 순매입 원가)는 그대로.
- **늦은 원장 행 — 첫 주기·자정 경계** — 지난 판의 '늦게 들어온 거래 → 지난 곡선 다시 계산'이 놓치던 경계를 막았어요: 업데이트 뒤 첫 주기에 들어온 늦은 거래(코어가 첫 수집 전에 울타리를 먼저 적고 · 못 적으면 수집을 시작하지 않음) ·
  자정 직전 16분에 기장된 그날 행 · 마지막 화면 스냅숏 뒤~자정 사이에 기장된 행(마감 스냅숏이 같은 읽기의 원장 수위를 함께 저장하고, 그 뒤 그날 행이 기장됐으면 마감 재료로 쓰지 않음) ·
  그렇게 버린 마감 스냅숏도 그날 마감가는 고정(지금 시세로 바뀌지 않음) · 거래를 지우기만 하고 다시 넣지 않는 원장 경로(다시 분류 뒤 레그 0개 · 스테이킹 재개 0)도 표식 · 장기 곡선 '근사' 몫이 빌린(음수) 보유를 크기로 셈.
- **EVM 따라잡기 · 내부 이동 추적(trace)** — trace 호출(callTracer·parity 대체·블록 trace)이 절대 마감 하나를 나눠 쓰고, 노드가 연달아 2번 실패하면 5분 동안 따라잡기·엿보기 걸음은 trace 없이 바로 '나중에 다시'로 ·
  trace 를 미룬 거래는 기록하기 전에 대기열에 저장(재시작·되돌리기에도 회수) · 대기열(2,000건)이 차면 버리지 않고 `state/trace_later_overflow_<체인>.jsonl` 로 내려 두었다 되살림 · 한 번도 시도 못 한 항목은 만료 안 함(30일 만료는 실제로 5번 넘게 시도한 것만) ·
  해시를 모르는 내부 입금도 지갑·블록 단위로 저장해 나중에 회수 · 보완 작업은 최신 확인 뒤 최소 몫으로(굶지 않게) · 따라잡는 걸음의 잎 블록은 묶어 한 번에 조회 · 키 노드가 있으면 따라잡는 걸음의 잔고·nonce 확인은 키 노드 먼저(위 업데이트 상자).
- **긴 목록 20개씩 · 화면 다듬기** — 펼치면 페이지가 끝없이 길어지던 목록(보유 코인·사이클·전체 이벤트·최근 30일·보낸 내역·미매칭·추적 지갑·체인별 조회·NFT·계획 점수·서랍 안 표·⌘K 검색 결과 등 30곳 넘게)을
  처음 N개 → 'N개 모두 보기' → '‹ 이전 · 21–40 / N · 다음 › · 접기' 20개씩 쪽으로(접힌 첫 화면은 그대로 · 검색으로 찾아가면 그 항목이 있는 쪽을 엶 · 거르기·정렬·기간을 바꾸면 첫 쪽) ·
  혼자 한 줄에 있던 단추·칩을 관련 줄 끝으로 · 줄 끝 '·' 고아·한글 캡션 고정폭 글꼴 정리 · 폰 누름 영역 44px · 설정 '지갑·주소' 순서(목록 → 주소 관리 → 체인별 조회 → 확인 주기) ·
  연간 잔디 첫 열 잘림 · 폰 달력 'AI' 표시를 점으로 · 좁은 화면 매매일지 탭 줄 칩 '점수'·'결산'.
- **변동 분해 줄 → 무엇 때문인지** — 대시보드 '오늘 무엇이 움직였나'·그날 카드·'M월 한눈에'의 분해 줄(시세·현물 실현·선물 실현·입출금·환율·선물 미반영·나머지 등)을 누르면 시트가 열려 구성 요소를 큰 순으로 보여요 —
  시세 = 코인별(변동률·전일 수량·전일가 → 그날가) · 현물 실현 = 코인별(누르면 차익 영수증) · 선물 = 거래소·종목별 · 입출금 = 건별(상계된 레그) · 환율 = 몫별 · 나머지 = 이름 붙인 조각(가격 끊김·원장 밖 잔고·반올림 등) ·
  20개씩 쪽 · 맨 아래 합 확인(늘 줄 값과 정확히 같음) · 그 달은 항목별/날짜별 · 새 읽기 전용 API `GET /api/att_detail`(빌드 재료로만 · 외부 호출 0) · 금액 숨김·랜덤값에선 상세 원문을 받지 않음 · 총자산·곡선·분해 값은 그대로.
- **작은 것** — 업비트·해외 거래소 수집기가 pm2 stop·restart 때 트레이스백 대신 한 줄로 끝나요 · 긴급 알림 재시도 대기 판정이 지금 텔레그램 자격으로(자격을 바꾼 직후 실패하면 대기 없이 0.5초마다 다시 보내던 것) ·
  파이썬 3.9 공개 시험 하나(멈춘 단일 차선의 첫 주기)가 느린 기계에서 실패하던 것을 논리 시계로(판정은 그대로).
  설정의 거래소 키 안내 정정 — 업비트는 자산·주문·입금·출금 '조회' 넷이 필요(자산조회만 켜면 체결·입출금 기록을 못 읽음) · 빗썸은 조회 항목 · 게이트는 선물 포지션용 Futures Read Only · trace(parity) 응답의 실패 경로 판정이 응답 크기에 비례하도록(아주 큰 응답이 CPU 를 오래 붙잡던 것).

**함께**

- **문서** — [COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) BNB Chain '받은 BNB' 줄(긴 공백 뒤에도 · 다시 점검 요청)·Base 줄(연달아 실패하면 5분 · 기록 전 저장 · 실제 5번 시도 뒤 만료) ·
  [API_KEYS.md](docs/API_KEYS.md) Ankr 따라잡기 · README '이번 판'·일별 기록·알려진 한계.
- **시험** — 공개 시험 추가: 업비트 미기장 체결 원화 이력(첫 부분 매수·순수량 0·수수료·업그레이드 경로·마감 거절 자정 교차) · BNB Chain 긴 공백(45분 공백·재시작·원장 읽기 실패·예산 소진·아카이브 없음·아카이브 전용·한 블록 6건) ·
  세일 환불 원가(수집 → 코어 → 화면 빌드 끝까지) · 늦은 행 첫 주기 울타리·자정 경계 · trace 마감·아픈 노드·영속 보류·넘침·되돌리기 · 쪽 넘김 · 변동 분해 상세(서버 합·화면 합) · 수집기 정지 · 긴급 알림 자격 —
  전체 5,000건 넘게(파일 150개 넘게).

**English · External review fixes and list paging** — Two external reviews of the previous release found new bugs; every one was reproduced as a public test (failing before, passing after) and fixed.
Upbit: the KRW cash moved by unbooked fills of open limit orders is now rewound in past days independently of the coin adjustment, so a first partial buy of a coin held only on the live balance
row, or a buy and sell of the same coin with zero net quantity, no longer shifts yesterday and past curves by the filled amount (30-day and long-range curves agree; past days frozen by the previous
release are corrected once; recomputing a day after its close snapshot is set aside keeps the fill's KRW in place, idempotently), and a stale (10+ minute) snapshot with unbooked fills no longer
becomes the day's close. BNB Chain balance watch: a pause longer than 30 minutes (bot stopped, node outage, rollback) no longer discards the checkpoint — the gap is kept as a persisted unresolved
window, re-explained from ledger transactions with a nonce check, and BNB received in it is recorded once at its original block (no amount threshold); archive-only setups with many wallets,
archives answering "missing trie node", and blocks with more than five direct deposits are handled; installs that ran 2026-10-10 (3) can re-check a past gap with
`state/bsc_balw_recheck.json` `{"hours": N}`. Token-sale (CCA) partial refunds: the refunded payment coin gets back its original cost share instead of being re-priced at refund time, so later
sells, realized PnL and the tax export are correct. Late ledger rows: a startup cursor fence is written before the first ingest after an upgrade, rows booked in the last 16 minutes before midnight
are flagged, and the close snapshot carries the ledger posting watermark and is set aside if anything for that day was booked after it (its close prices stay pinned). EVM RPC catch-up no longer
stalls on a failing public trace node: trace calls share one absolute deadline, two consecutive failures pause catch-up/peek tracing for 5 minutes, deferred lookups are persisted before
emission (queue overflow spills to a file, untried items never expire), internal deposits with unknown hashes are kept per wallet and block, and a catch-up step sends balance/nonce checks
to a keyed node first when one is configured. UI: long lists (holdings, cycles, events, outflows, unmatched, wallets, NFT, drawers, search) page 20 at a time instead of growing the page,
lone buttons moved onto their rows, 44px touch targets on phones; tapping any row of the asset-change breakdown opens a sheet listing what made it up (per coin, per realized sale,
per futures venue/symbol, per transfer, FX parts, named remainder pieces), biggest first, 20 per page, adding up exactly to the row (new read-only `GET /api/att_detail`). Also: Upbit and
foreign-exchange collectors stop with one log line, the urgent-alert backoff compares the current Telegram credentials, and the exchange key guide now lists the Upbit read permissions the bot needs
(assets, orders, deposits, withdrawals — view only) and Gate futures read-only; parity trace responses are checked in linear time. No rebuild and no data revision.

**알려진 한계(다음 판에)** — 자세한 설명·피하는 법은 README [알아 둘 것](README.md#알아-둘-것).

- 업비트 열린 주문 응답엔 여전히 체결 시각이 없어 미기장 체결을 '지금 스냅숏 시각'에 생긴 것으로 봐요 — 며칠 열린 주문은 아직 계산 안 된 더 옛날 날(새 설치의 장기 곡선 등)에서 그 체결만큼 어긋날 수 있고,
  업비트 잔고가 10분 넘게 낡은 동안 오늘 값은 체결 금액만큼 다를 수 있어요(그날 마감엔 안 굳음) · 시세 없는 코인의 첫 매수는 체결 금액만큼 오늘 손실처럼, 원장에 기록된 것보다 많이 판 매도는 그날 이득처럼 보일 수 있어요.
- BNB Chain 공백 구간에 내 발신이 아직 원장에 안 들어왔으면 그 구간은 기다려요(코어가 멈춰 있으면 계속 미해결 — 로그 '미해결 구간 N') · 아카이브 키 없는 설치의 256블록 넘는 공백은 구간 끝 블록 시각의 기초 잔고(원가 미확인)로 ·
  공개 노드 없이 아카이브만 넣은 구성은 실행당 6지갑씩이라 지갑이 많으면 감지가 몇 시간 늦어요(놓치진 않음) · 다시 점검 요청은 블록 시간을 추정해 창을 잡아요.
- 세일(CCA) 입찰을 라우터·도우미 컨트랙트를 거쳐 보냈거나 입찰 송금이 수집 기간 전이면 환불 원가를 잇지 못해요(종전 규칙) · 스테이블 환불의 원화 원가는 환불 때 환율.
- 늦은 행으로 마감 스냅숏을 버린 날, 그 스냅숏에 시세가 없던 코인은 지금 시세 근사로 들어갈 수 있어요(지난 판과 같음) · 업데이트 전에 이미 굳은 날은 소급하지 않아요.
- 공개 trace 노드가 아픈 동안(연달아 실패 → 5분) 내부 이동은 몇 분 늦게 원장에 들어와요 · 따라잡기 걸음의 절반 넘게는 잔고·nonce 이분 탐색이라 키 노드 없이 공개 노드만 쓰면 여전히 느려요(Ankr 무료 키 권장 —
  자주 쓰는 지갑 몇 개를 이틀치 따라잡으면 하루 몫의 절반쯤을 한 번 쓸 수 있고, 그 몫은 실시간 사용으로 잡혀 그날 백필 몰아 쓰기 몫이 줄 수 있어요).
- RPC 노드가 응답 본문을 아주 느리게 조금씩 보내면(소켓 대기 시간 단위로만 끊겨) trace 의 절대 마감을 넘겨 그 체인 수집이 그만큼 늦어질 수 있어요(유명 공개 노드에선 드묾 · 다음 판에 본문 수신 전체 마감).
- 변동 분해 상세의 시세 코인은 하루 큰 순 400개까지(나머지는 '그 밖 N종' 한 줄 · 합은 정확) · 입출금은 같은 날 같은 코인 순액 단위(거래 한 건씩은 일별 기록 목록) · '그날 사고판 분'은 한 줄.
- 지난 판 한계(부채 기록 시작 전 날 · 첫 대사 전 원가·손익 · 로그 없는 BNB 발신 봇 · 못 가린 컨트랙트 BNB 기초 잔고 · Base trace 늦은 채움 · 코인 카드 스팸 줄 · 원화 거래소 나중 추가 · 체인 칩 설명 · OKX MARGIN 단위)는
  그대로예요 — [2026-10-10 (3)](#2026-10-10-3--외부-검토-반영).

## 2026-10-10 (3) — 외부 검토 반영

**거래소 마진·대출 부채 차감 · 업비트 열린 주문 부분 체결 · 늦게 들어온 거래 → 지난 곡선 다시 계산 · BNB Chain 에 그냥 받은 BNB · EVM 옛 구간 채우기 예산 ·
GoPlus 응답 상한 · 긴급 알림 백오프 · 환율 대체값 표시 · 세일 환불 원가 · OKX 코인 정산 손익 · 파이썬 3.9 응답 읽기 · 첫날 안내 문구**

공개판을 읽은 외부 검토 두 건의 지적을 하나씩 코드로 재현해, 영향이 큰 것을 고친 판이에요 — 총자산이 실제보다 크게 보이던 경우(거래소에서 빌린 코인을 쓰거나 옮김 ·
업비트 지정가 주문이 일부만 체결된 동안), 늦게 들어온 지난 거래가 이미 굳은 지난 곡선을 고치지 않던 것, BNB Chain 에서 남이 그냥 보낸 BNB 를 못 받던 것,
EVM 옛 구간 채우기가 몇 시간씩 멈추던 것. 드문 경우는 아래 알려진 한계에 적었어요. 사진은 다시 찍지 않았어요(README '이번 판' 안내).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` — 유닛을 전부 멈춘 뒤 한꺼번에 시작).
> 재구축·데이터 개정은 없어요(코드만 되돌려도 돼요 · 새 상태 파일 `state/bsc_balw.json` 과 일별 캐시·원장 메타에 새로 생기는 칸은 옛 코드가 읽지 않음).
> 거래소에서 빌린 코인이 그 거래소 잔고를 넘어 있으면 업데이트한 날 오늘 총자산이 그 몫만큼 한 번 내려가요(이미 굳은 지난날 값은 그대로 · 다음 마감부터 그날 부채를 함께 기록).
> BNB Chain 잔고 감시가 옛 블록을 좁히려면 아카이브 키(Ankr 무료 키 — EVM 필수 키와 같은 것 · 또는 NodeReal)가 있어야 해요. 없으면 공개 노드가 보관한 최근 블록만 훑어 직접 받은 거래를 찾아요.

- **거래소 마진·대출 부채를 총자산에서 뺌** — 빌린 코인을 쓰거나(마진 롱) 다른 곳으로 옮겨(대출금 출금) 그 거래소 원장 칸이 음수가 되면, 그 거래소 잔고 정보의 부채 한도 안에서
  그 몫을 총자산에서 실제로 빼요(종전엔 양수 칸만 더해 빌린 만큼 부풀었음) · 오늘 총자산·상단 요약·보유 행·오늘 일별 값이 같은 숫자 · 담보대출은 부채에 이미 들어 있어 따로 안 빼요(이중 차감 없음) ·
  부채보다 큰 음수·부채 없는 음수는 종전처럼 빼지 않고 상태 패널 '원장 음수 보유' 경고 · 일별 마감마다 그날 부채를 기록해 나중에 다시 계산해도 같은 값 ·
  보관처 줄 '빌린 몫 · 잔고를 넘은 차입(총자산에서 차감)' · 보유표 끝 '빌린 몫이 잔고를 넘은 코인 N종'.
- **업비트 열린 주문의 부분 체결** — 주문이 끝나기 전(원장 기록 전) 일부 체결된 수량을 지금 보유에 반영해요(매수 + · 매도 − · 원화 예수금과 같은 시점의 잔고 스냅숏 ·
  BTC·USDT 마켓은 상대 코인도 · 같은 주문이 이미 원장에 있으면 그만큼 뺌) — 부분 매도 중 총자산이 체결 금액만큼 크게, 부분 매수 중 작게 보이던 것 고침 ·
  늘어난 몫은 그 체결 금액으로 임시 원가 · 지난날 곡선은 그 스냅숏 시각의 증감으로 · 업비트 원화 예수금이 10분 넘게 늦어도 빼지 않고 '업비트 잔고 N분 전'으로 보여요(하루까지).
- **늦게 들어온 거래 → 지난 곡선 다시 계산** — 수집 정지 뒤 따라잡기·느린 무료 키·회수한 입금처럼 그날 마감 뒤에 원장에 들어온 지난 거래가 이미 굳은 지난 일별 값과 장기 곡선에도 반영돼요 —
  원장이 그 거래의 가장 이른 날을 표식으로 남기고(같은 거래를 다시 넣어 원장이 안 바뀌면 표식 없음 · 재시작해도 안 잃음) 화면이 그 날부터만 한 번 다시 계산(그날 가격·환율·원장 밖 금액은 그대로 · 수량만) ·
  따라잡는 동안엔 5분 조용해지면, 계속 붐벼도 1시간에 한 번 · 지난 곡선의 '−X 다음 날 +X' 같은 손익 쌍이 사라져요.
- **BNB Chain 에 그냥 받은 BNB** — 남이 그냥 보낸 BNB·컨트랙트가 보내 준 BNB(로그 없음)를 잔고 감시로 받아요: 최신 확인이 끝난 주기마다(약 1분) 지갑 BNB 잔고를 공개 노드에서 묶어 읽고,
  기록한 거래로 설명 안 되는 증가가 있으면 옛 블록 잔고로 반씩 좁혀(아카이브 키 · 입금 한 건에 수십 콜 · 하루 상한) 그 블록의 거래를 실제 거래로 기록 ·
  보낸 거래를 못 가리면 그 블록 시각의 기초 잔고(원가 미확인) · 아카이브 키가 없으면 최근 256블록 안을 훑어 직접 받은 거래만 · 이 판 전에 놓친 BNB 는 잔고 대조가 두 번 확인한 부족($500·2% 이상)에서
  최근 30일 안을 같은 방식으로 · 잔고 대조가 BNB 기록이 없는 지갑도 비교 · 실행마다 시간·호출 상한이 있어 최신 수집을 붙잡지 않아요 ·
  [수집 한계](docs/COLLECTION_LIMITS.md) BNB Chain 줄 정정(키 없는 공개 로그 노드로 약 150일 · 아카이브는 무료 키로도).
- **EVM 옛 구간 채우기** — 한 지갑의 느린 내부 이동 추적(trace)이 같은 묶음의 다른 지갑을 굶겨 옛 구간이 몇 시간씩 멈추던 것 고침(확인한 블록 잔고를 다음 주기로 이어 쓰기 · 지난번 못 본 지갑부터 ·
  뒤 차선 사이클 길이 상한 → 새 거래 확인 간격도 안 늘어남) · 노드 한도(429)·일시 보류로는 구간을 반으로 줄이지 않음 · 뒤 차선의 추적 실패는 첫 실패에 '나중에 다시'(30일) ·
  과거 상태가 없는 추적 노드는 기다리지 않고 잔고 차이로 맞춤 · 추적 노드를 따로 안 넣었으면 탐색기 → RPC 인계 겹침 1시간 · 줄어든 getLogs 구간 상한을 30분마다 원래대로 ·
  한 줄로 받던 RPC 체인도 수집 시작일을 앞당기면 앞 구간을 뒤 차선으로(새 거래 확인이 멈추지 않음).
- **작은 것** — 토큰 보안(GoPlus) 조회 응답 4MiB 상한(넘으면 조회 실패로 · 위험 캐시 보존 · 1시간 뒤 다시) · 텔레그램 긴급 알림 발송 실패 재시도를 지수 백오프로(최대 5분 · 봇 차단·채팅 ID 오류 = 30분 ·
  설정을 바꾸면 바로) · 텔레그램 응답 본문 상한 · 알림 커서 파일이 깨져도 알림 유닛이 재시작을 되풀이하지 않음(`.bad` 로 옮기고 새로) ·
  환율이 대체값·오래된 값이면 상태줄·설정 환율 줄에 '환율 대체값'·'환율 오래됨'(대체값이면 김프 숨김) · 토큰 세일(CCA) 부분 환불 원가 = 실제로 쓴 몫 × 입찰 시각 시세(환불 때 시세가 달라도 원가가 줄거나 세일 연결이 사라지지 않음 ·
  형식이 이상하면 '단가 미확인') · OKX 코인 정산(역계약) 선물의 평가손익을 그 코인 시세로 달러 환산(시세가 없으면 '—' · 합계는 아는 것만) · 파이썬 3.9 에서 RPC 응답을 밝힌 길이만큼만 읽음(메모리) ·
  옛 기록 채우기 안내 문구를 '새 거래 확인 먼저'에 맞춤(종전 '첫날은 새 거래 확인이 늦을 수 있어요').

**함께**

- **문서** — [COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) BNB Chain 줄(받은 BNB · 공개 노드 약 150일 · 아카이브 무료 키)·RPC 전용 체인 수집 시작일 앞당김 · [API_KEYS.md](docs/API_KEYS.md) Ankr 쓰는 곳 ·
  README '알아 둘 것' BNB Chain·환율 표시·알려진 한계 · 지난 판 GoPlus 한계 고침.
- **시험** — 공개 시험 추가: 부채 차감(마진 롱·대출 출금·담보대출·Hyperliquid 현금 공존·부채 없는 음수) · 업비트 부분 체결(부분 매수·매도·누적·종결 전환·낡은 스냅숏) · 늦은 거래 표식·다시 계산 ·
  BNB Chain 잔고 감시·기장·곡선 위치 · 뒤 차선 예산·추적 · GoPlus 상한 · 긴급 알림 백오프 · 환율 표시 · 세일 환불 원가 · OKX 역계약 · 3.9 응답 읽기 · 안내 문구 — 전체 4,600건 넘게(파일 140개).

**English · External review fixes** — Two external reviews of the public release were reproduced finding by finding and the high-impact ones fixed.
Exchange margin/loan debt is now subtracted from the total: when borrowed coins are spent (margin long) or moved out (loan withdrawn) and an exchange ledger cell goes
negative, that amount is deducted up to the debt reported by the exchange (collateral loans are already in that debt, so nothing is counted twice); negatives larger
than the debt or with no debt are still excluded and flagged, and each daily close records that day's debt so recomputation gives the same value. Partial fills of open
Upbit limit orders are applied to current holdings before the order is booked (same snapshot as the KRW balance; BTC/USDT markets adjust both sides), so the total no
longer looks too high during a partial sell or too low during a partial buy; a KRW balance older than 10 minutes is kept with a "N minutes ago" note (up to a day).
Late transactions that reach the ledger after their day was closed (catch-up after a stop, slow free keys, recovered deposits) now re-compute closed daily values and the
long-range curve from the event day only (that day's prices, FX and off-ledger amounts are kept; quietly batched, at most hourly), removing "−X then +X" PnL pairs.
BNB Chain now finds plain BNB sent to you and BNB paid out by contracts (no logs) with a balance watch: wallet BNB balances are read about every minute and an
unexplained increase is narrowed down by bisecting old-block balances (archive key — free Ankr or NodeReal; a few dozen calls per deposit, daily cap); the transaction
is booked when found, otherwise an opening balance (cost unknown) at that block time; without an archive key only the last 256 blocks are scanned for direct transfers,
and BNB missed before this release is searched within 30 days when the balance check confirms a shortfall twice. EVM back-lane backfill no longer starves other wallets
behind one slow trace (balances carried across cycles, rotation, a cycle-length cap), does not halve its range on 429 or holds, hands failed back-lane traces to "retry
later" at once, settles traces on nodes without historical state from balance differences and restores shrunk getLogs caps every 30 minutes. Also: a 4 MiB cap on GoPlus
responses, exponential backoff for failed urgent Telegram alerts (5 minutes max, 30 minutes for a blocked bot or wrong chat ID), the alert unit survives a corrupt cursor
file, "fallback/stale FX" notes in the status line and settings (kimchi premium hidden on fallback), token-sale (CCA) partial-refund cost = bid actually spent × bid-time
price, OKX coin-settled (inverse) futures PnL in USD, Python 3.9 reads RPC responses up to the declared length, and the backfill wording matches "new transactions first".
No rebuild and no data revision.

**알려진 한계(다음 판에)** — 자세한 설명·피하는 법은 README [알아 둘 것](README.md#알아-둘-것).

- 거래소 부채는 이 판부터 일별 마감마다 기록해요 — 그 전 날을 다시 계산하면 '지금 부채'를 한도로 써서, 그 사이 빚을 갚았으면 그날이 빌린 몫만큼 높게 보일 수 있어요 ·
  업데이트한 날 '오늘 변동'에 빌린 몫만큼 하락이 한 번 보여요 · 빌린 몫이 잔고를 넘은 코인은 보유표 행 대신 표 끝 한 줄로만 보여요.
- 업비트 열린 주문 응답엔 체결 시각이 없어 부분 체결을 '잔고 스냅숏 시각에 생긴 것'으로 봐요 — 실제 체결 ~ 지금 사이 날을 다시 계산하면 그 체결 금액만큼 어긋날 수 있고,
  업비트 잔고가 10분 넘게 늦는 동안·주문이 끝난 직후 원장 기록 전(몇 초~한 주기)엔 보정이 빠져요.
- BNB Chain 잔고 감시가 보낸 거래를 못 가린 컨트랙트 BNB(브리지 지급 등)는 그 블록 시각의 기초 잔고(원가 미확인)로 들어가요 · 같은 블록에 무관한 내 거래가 겹치면 보낸 쪽이 틀릴 수 있어요(금액·시각은 맞음) ·
  컨트랙트(스마트) 지갑은 잔고 감시 대상이 아니에요 · 이 판 전에 놓친 작은 BNB($500·2% 미만)나 30일보다 옛 몫은 기초 잔고로 남아요.
- 늦은 거래로 마감 스냅숏 날을 다시 계산하면 그날 스냅숏에 시세가 없던 코인은 지금 시세 근사로 들어갈 수 있어요 · 업데이트 전에 이미 굳은 날의 늦은 거래는 자동으로 소급하지 않아요 ·
  옛 기록 넓히기처럼 늦은 거래가 계속 들어오는 동안엔 1시간에 한 번 다시 계산해요(작은 기기에선 몇십 초 CPU).
- OKX 마진(MARGIN) 포지션의 평가손익 단위는 실계정으로 확인하지 못해 코인 정산 규칙(증거금 통화 단위)과 같게 봐요.
- 지난 판 한계(첫 대사 전 원가·손익 · 로그 없는 BNB 발신 봇 · Base trace 늦은 채움 · 코인 카드 스팸 줄 · 원화 거래소 나중 추가 · 체인 칩 설명)는 그대로예요 — [2026-10-10 (2)](#2026-10-10-2--새-설치본-수집--최신-우선).

## 2026-10-10 (2) — 새 설치본 수집 · 최신 우선

**새 설치본 RPC 차선 · 블록스카웃 첫 경로 금지 · BNB Chain·Solana 최신 먼저 · Ankr 키 필수 · 키 저장 연결 시험 · 쉬는 지갑 1시간 · 토큰 받음 확인 10분 ·
백필 한도 몰아 쓰기 · 첫 대사 전 지금 잔고 · 전송 중 이중 계상 방지 · trace 늦은 채움 · 지난날 곡선 LP · 거래소 키 나중 추가 · 스팸·사칭 행 · 응답 크기 상한 · AI 실패 사유**

아무것도 없는 새 설치본에서 옛 기록을 다 받기 전까지 최신 입금이 안 보이던 문제를 고친 판이에요 — 이제 모든 수집 경로(Base 같은 RPC 체인·BNB Chain·Solana·탐색기)가
첫 주기부터 최신 블록을 보고, 옛 기록은 옆 차선에서 남는 한도로 함께 받아요. 옛 구간이 실패해도(노드 시간 초과·429·한도) 최신 쪽은 막히지 않아요.
지난 판의 알려진 한계 4가지(판정 보류 토큰 · BNB Chain 보류 토큰 대사 · 정품 등록 길 · 직접 조회 응답 크기 상한)도 고쳤어요. 사진은 다시 찍지 않았어요(README '이번 판' 안내).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js` — 유닛을 전부 멈춘 뒤 한꺼번에 시작).
> 재구축·데이터 개정은 없어요(코드만 되돌려도 돼요 · 새 상태 파일 `state/evm_route.json`·`state/inflow_<체인>.json`·`state/prov_bal.json`·`state/cg_ca.json` 은 옛 코드가 읽지 않음).
> EVM 지갑이 있으면 **Ankr 무료 키**를 넣어 주세요(설정 › 연결·키 — 저장할 때 연결 1콜 확인 · 관련 수집기만 자동 재시작). 없어도 돌지만 설정·상태 패널에 경고가 떠요.
> 지난날 곡선: LP 를 열었다 닫은 날 · 발견 시점 기초 잔고가 있는 날 · 백필 뒤 처음 넣은 거래소가 있으면 첫 화면 계산 때 그날들을 한 번 다시 계산해요(그날 값·'나머지'가 바뀔 수 있음).

- **새 설치본 RPC 체인 = 최신 먼저** — 처음 받는 Base 등 RPC 체인도 처음부터 라이브 차선(최근 48시간 → 지금 · 작은 걸음부터 늘림) + 옛 구간 뒤 차선으로 받아요 ·
  라이브 차선이 15분 넘게 뒤처지면 최근 블록을 먼저 엿봐 방출 · 이미 한 줄(단일 차선)로 멈춰 있던 설치본은 자동 전환 · 따라잡는 라이브 걸음·뒤 차선의 trace 실패는 첫 실패에 '나중에 다시'로 넘기고 전진 ·
  끄기 = `chains.<체인>.rpc_lanes: false`.
- **블록스카웃을 첫 경로로 쓰지 않음** — 새로 받는 탐색기 체인 순서 = 이더스캔(키 있고 그 체인 지원) → 공개 RPC → 블록스카웃은 최후(2026-10 실측: 여러 체인 블록스카웃 API 403·301) ·
  체인별 처음 순서는 `state/evm_route.json` 에 고정 · 이미 탐색기로 받던 설치본은 종전 순서 · 이더스캔 키를 지운 체인이 아카이브 없는 공개 노드에서도 멈추지 않고 다시 훑음 · 끄기 = `rpc_first: false`.
- **BNB Chain·Solana 최신 먼저** — BNB Chain = 최신 블록을 첫 주기부터 · 수집 기간은 옆 차선(기간 = `backfill_months` · 따로 = `bsc.backfill_days` · 끄기 `bsc.lanes: false`) ·
  로그 없는 내 발신(순수 BNB 송금) 회수 = 최근 2시간 먼저 · 거래소 → 내 BSC 출금 확인 = 최신부터 · 예시 설정 BSC 로그 노드 = 키 없이 옛 구간까지 받는 공개 노드 ·
  Solana = 새 설치·새 지갑·새 토큰 계정·오래 멈춘 뒤에도 최근 하루(주소마다 가장 새 100건) 먼저, 옛 기록은 사이클마다 60초씩 끊어 이어 받기(다시 읽기 없음).
- **Ankr 키 필수 · 키 저장 연결 시험** — EVM 지갑이면 Ankr 무료 키 '필수' 표시(경고만 · 막지 않음 · 배너·키 카드·상태 패널) · 모든 키는 저장할 때 읽기 전용 1콜로 확인(서비스가 거부 401·403(노드 키 404) = 저장 안 함 ·
  연결 실패 = 저장 + 경고) · Helius·업비트 키를 지우면 '동기화 멈춤' 빨강 대신 키 안내(Solana 지갑인데 Helius 키가 처음부터 없으면 그 안내) · 키 저장으로 수집기가 다시 켜질 때 오류 로그에 트레이스백을 안 남김.
- **쉬는·빈 지갑 확인 최대 1시간 · 토큰 받음 10분** — 7일 안 보낸 지갑 = 지금 주기 · 그 밖(빈 지갑 포함) = 10분 잔고 점검(Multicall3 묶음) + 1시간 탐색기 확인(종전 최대 하루 · 빈 지갑 주 1회 · 하루 한도를 넘으면 간격 자동 늘림) ·
  탐색기로 받는 체인의 쉬는·빈 지갑에 들어온 토큰은 10분마다 getLogs 로 묶어 확인해 받은 지갑만 깨워요(Ankr 키 → 공개 노드 · Alchemy 안 씀 · 스팸 폭주 막기 · `addr_tier.inflow_sec`, 0 = 끔) · 설정 확인 주기 카드·상태 패널에 마지막 확인.
- **거래소 → 내 지갑 '전송 중'** — 받는 주소를 도착할 때까지 10분마다 확인 · 받는 쪽 수집이 출금 시각을 덮기 전엔 48시간이 지나도 '나감'으로 바꾸지 않음('받는 쪽 기록 확인 중' · 7일 넘으면 종전).
- **첫 대사 전 오늘 보유·총자산 = 지금 실제 잔고** — 체인 첫 잔고 대사 전엔 대사와 같은 조회로 1시간마다 지금 잔고를 읽어 원장과의 차이만 오늘 보유에 더해요(보관처 '지금 잔고(옛 기록 받는 중)' ·
  평가 규칙은 원장과 같음 · 장부 무변) · 곡선 아래 '원가·손익·지난날 곡선은 옛 기록을 다 받으면(진행률·남은 시간) 정확하게 맞춰져요' · 거래소 → 내 지갑 전송 중 수량은 그 차이에서 빼 이중으로 세지 않음
  (같은 통화 — 네이티브 설정 심볼·검증 스테이블 · 출금 시작 뒤 읽은 잔고만).
- **백필 때 한도 몰아 쓰기** — 무료 키(Alchemy·Ankr·NodeReal·Helius)는 실시간 실측 × 1.5 만 앞날 몫으로 남기고 하루 몫의 최대 10배(열흘치)까지 백필에(최근 31일 합 ≤ 월 80% · 실시간 호출은 백필에 안 막힘 · 유료 = 종전) ·
  이더스캔은 옛 기록 중 실시간 몫을 실측 × 1.25(하루 몫의 3~70%)로 · 설정 사용량 줄에 '실시간 하루 약 · 오늘 백필 상한' · Helius 칸에도 '새로 받은 키' 칩(`sol.helius_burst: false` = 끔).
- **trace 늦은 채움 · 뒤 차선** — 공개 노드 trace 가 실패한 tx 는 내부 이동 없이 먼저 기록하고 '나중에 다시'(사이클당 몇 건 · 2분부터 두 배 · 최대 6시간 간격 · 30일)로 채워요 ·
  뒤 차선 실패 땐 구간을 반으로 · 체크포인트는 줄인 목표까지만 · 실패한 잎 블록이 사이클마다 바뀌어도 30분 뒤 넘기고 전진(새 설치 Base 가 무기한 멈추던 것) · Base 넓히기 2~3배(추정).
- **지난날 곡선 · LP · 기초 잔고** — LP 를 열었다 닫은 날 원금을 지갑 수량과 LP 평가로 두 번 세던 것 고침(그날 LP 평가 관측 시각 기준 되감기 · 30일·장기 곡선 공통 · 굳은 날 1회 재계산) ·
  분해 '원장 밖 잔고(LP)' = LP 평가 − 원금 이동 · 발견·재점검 기초 잔고는 분해 '기초 잔고 정정' 칸으로('나머지'로 새던 것) · 발견 시점 기초 잔고는 원래 있던 보유라 지난날 곡선에도 포함.
- **거래소 키를 나중에 넣어도** — 백필 완료 뒤 처음 넣은 거래소 키 = 지난 일별값(30일·장기 곡선)에 그 거래소 보유를 1회 반영(키 넣은 날 가짜 수익 계단 없음) ·
  업비트 없는 설치·거래소만 쓰는 설치도 백필 완료 표식이 생겨요(연결된 해외 거래소 첫 대사까지 기다림 · 첫 백필 중 마감 스냅숏은 굳히지 않음).
- **스팸·사칭** — 사칭 판정에 콥트·체로키·캐나다 음절·소형 대문자 흉내 글자(106자) · 보낸 내역이 '사칭·스팸'으로 정한 가짜 외부 전송 줄은 기록에서 숨김 목록으로(정상으로 복원한 자산은 빼고) ·
  수집 기간 전부터 받기만 한(기초 잔고뿐) 토큰은 코인게코에 그 컨트랙트 시세가 있을 때만 평가 · 블록스카웃만 아는 보유 후보도 같은 스팸 필터.
- **응답 크기 상한 마무리 · 지난 판 한계** — 공통 경로 밖 직접 조회 12곳(솔라나 수집·대사, 시세·OKX 토큰 가격, Rabby, 업비트, 입금 주소, 브릿지·자금 흐름 추적, LP 목록, 세일 매칭, 거래 출처)과
  코인게코 키 시험도 정상 32MiB · 오류 64KiB · 판정 보류 토큰 1시간 재판정(상태 패널 '토큰 판정 대기 N') · BNB Chain 지갑별 대사는 관측한 토큰만 · `tools/negabs_1010.py --genuine`(정품 등록 + 다시 시도).
- **AI · 화면** — 영수증 AI 평가가 Claude CLI 자체 실패(조직 접근 끔·로그인 필요·한도)면 '형식' 대신 진짜 사유(키 같은 값은 가림) · README [AI 기능 켜기](docs/FEATURES.md#ai-기능-켜기--claude-cli-로그인) ·
  전송 중 '받는 쪽 기록 확인 중' · 펼친 보유 줄 표 넘침 · 폰 보유 줄 칩 잘림 · 확인 주기 카드·Ankr 칸 문구 · 키 저장 알림 · 그날 카드 분해 라벨 칸 · 상태 패널 음수 보유 '첫 백필 중'·지운 체인 '멈춤' 오경보 없음 ·
  다른 체인 활동 경고 = 할 일 문구 · 환율 선조회가 쉼을 지키고 실패하면 멈춤 · 빗썸 체결 시각 바로잡기가 원장 반영을 붙잡지 않음.

**함께**

- **문서** — README 처음 표·키 표·`.env.example`·[API_KEYS.md](docs/API_KEYS.md)에 Ankr 필수·키 저장 확인·버스트 열흘치 · 첫 실행 시간(최신 먼저) · 고급 설정(`rpc_first`·`rpc_lanes`·`addr_tier.inflow_sec`·`bsc.lanes`·`sol.live_first_hours`·`sol.helius_burst`) ·
  [COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) 새 설치 경로·Base trace 늦은 채움·Solana · README '알아 둘 것' 알려진 한계.
- **시험** — 공개 시험 추가: 새 설치 RPC 차선·멈춘 차선 전환·첫 경로 · BSC 라이브 차선·최근 발신 회수 · Solana 최근 먼저 · 쉼 계단·출금 깨움·Ankr 필수 · 토큰 받음 확인 · 버스트 · trace 늦은 채움·잎 실패 ·
  첫 대사 전 지금 잔고·전송 중 상계 · LP 곡선 · 거래소 키 나중 추가 · 스팸 흉내 글자 · 응답 상한 직접 조회 · 키 순서·러너 종료 · AI 실패 사유 — 전체 4,200건 넘게(파일 120개 넘게).

**English** — Fresh installs now see the newest blocks first on every collection path: RPC chains such as Base start with a live lane (last 48 hours → now, small
steps that grow) plus a back lane for older history, a stalled single lane switches automatically, BNB Chain gets a live lane with the backfill window in a side lane
(`backfill_months`; newest log-less BNB sends recovered first), and Solana fetches the last day first (newest 100 per address) and old history in 60-second slices.
Newly collected explorer chains never start on Blockscout (Etherscan → public RPC → Blockscout last; fixed per chain in `state/evm_route.json`; existing installs keep
their order). Trace failures on public nodes no longer hold back the newest blocks — the transaction is recorded first and internal transfers are re-traced later
(backoff up to 6 hours, 30 days). A free **Ankr key** is now shown as required for EVM wallets (warning only) and every key is checked with one read-only call when saved.
Idle and empty wallets are checked at least hourly (10-minute balance checks, hourly explorer checks) and incoming tokens are detected every 10 minutes via getLogs
(Ankr → public nodes, `addr_tier.inflow_sec`); a withdrawal from an exchange to your own wallet wakes that address every 10 minutes and is not marked "out" while the
receiving side has not been collected. Before a chain's first reconciliation, today's holdings and total use the actual current balance (re-read hourly, no double
counting with in-transit withdrawals); cost, PnL and past curves become exact once old history is in. Free keys may burst up to 10x the daily share during backfill
while the measured real-time share is kept (rolling 31 days under 80%). Also: LP double counting in past curves, exchange keys added after the backfill are applied to
past daily values once, Coptic/Cherokee look-alike impersonation and spam rows are hidden, opening-balance-only tokens are valued only with a CoinGecko contract
price, response size caps on the remaining direct lookups, and real Claude CLI failure reasons in AI evaluations. No rebuild and no data revision.

**알려진 한계(다음 판에 · GoPlus 줄은 → 2026-10-10 (3) 판에서 고침)** — 자세한 설명·피하는 법은 README [알아 둘 것](README.md#알아-둘-것).

- 첫 대사 전엔 원가·손익·지난날 곡선에 수집 기간 이전 보유가 빠져 있어요(오늘 보유·총자산은 지금 잔고로 맞음) · 그 '지금 잔고'는 BNB Chain·Solana 조회 도중 출금이 겹치거나 전송 중 출금과 창 이전 보유가 겹치면 잠깐 덜 보일 수 있어요.
- 시간당 수백 건씩 로그 없는 BNB 발신을 하는 봇 같은 주소는 BNB Chain 회수가 사이클당 몇 건이라 뒤처져요.
- Base 등 공개 노드만 쓰는 체인은 trace 노드 한도에 걸리면 내부 이동이 늦게 채워져요(백오프 · 30일) · Alchemy 키만 넣은 설치는 Arbitrum 등의 옛 구간이 느려요(Etherscan·Ankr 권장). — **2026-10-11 판에서 일부 고침**(trace 노드가 아파도 따라잡기가 멈추지 않고 미룬 확인을 잃지 않음 · 늦게 채워지는 건 그대로 · [2026-10-11](#2026-10-11--외부-검토-2건-버그-수정--목록-정리)).
- 코인 카드 안 기록 줄의 사칭·스팸 줄 · 업비트·빗썸 외 원화 거래소를 나중에 넣을 때 지난 곡선 소급 · 체인 칩 설명 화면은 다음 판에.
- ~~토큰 보안 정보(GoPlus) 조회 한 곳은 아직 응답 크기 상한 없이 읽어요(공식 API · 15초 시간 제한) — 다음 판에 같은 상한(32MiB)으로~~ — **2026-10-10 (3) 판에서 고침**(4MiB 상한 · 넘으면 조회 실패로 · [2026-10-10 (3)](#2026-10-10-3--외부-검토-반영)).

## 2026-10-10 — 옛 보유 토큰 찾기 · Alchemy 키

**옛 보유 토큰 찾기 · 발견 시점 기초 잔고 · Alchemy 키 칸 · 노드 키 버스트 · EVM 체인 표 · 선물 코인 정산 달러 · 외부 응답 크기 상한 ·
Base 과거 기록 넓히기 · 바이빗 선물 수수료·펀딩 · 빌린 코인 원가 · 빗썸 지난 체결 시각**

수집 기간(기본 5개월)보다 먼저부터 들고만 있던 토큰을 빠뜨리지 않게 한 판이에요 — 지갑을 등록할 때 체인마다 무료·키 출처를 합쳐 '그 지갑이 주고받은 모든 토큰'을 찾고,
그래도 놓친 토큰은 나갈 때 그 직전 블록 잔고로 바로잡아요. 지난 판의 알려진 한계 2가지(코인 정산 선물 달러 환산 · 외부 응답 크기 상한)도 고쳤어요(응답 크기 상한은 공통 RPC·탐색기 요청 경로까지 — 아래 알려진 한계).
사진은 설정 › 연결·키(탐색기 키) 한 장만 새로 찍었어요(Alchemy 칸) — 대시보드 LP 카드 위치는 여전히 사진과 달라요.

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js`). 재구축·데이터 개정은 없어요(코드만 되돌려도 돼요 —
> 단 아래 1회 도구를 `--apply` 로 적용했다면 되돌릴 때 적용 전 백업으로).
> EVM 지갑이 있으면 **Alchemy 무료 키**를 넣어 주세요(설정 › 연결·키 — 저장하면 바로 쓰고 재시작 없음). 없어도 돌지만 옛 보유 토큰 찾기가 약해지고 설정·상태 패널에 경고가 떠요.
> 이미 등록한 지갑은 잔고 대조가 한 번에 20쌍(지갑, 체인)씩 천천히 첫 발견을 돌려요(지갑이 많으면 하루쯤). 한 번에 점검하려면 README [옛 보유 토큰 찾기 · 체인 표](docs/FEATURES.md#옛-보유-토큰-찾기--체인-표).

- **옛 보유 토큰 찾기** — 지갑을 등록할 때(기초 잔고 대조) 체인마다 되는 출처를 합쳐(이더스캔·루트스캔·블록스카웃·Alchemy·Ankr·Rabby 포트폴리오·RPC 로그 훑기 + 원장의 정품 토큰)
  그 지갑이 한 번이라도 주고받은 토큰을 모두 찾고, 같은 블록 잔고로 기초 잔고를 맞춰요 · 스팸 의심 토큰은 넣지 않아요 · 키 쓰는 API 는 처음 1번 + 그 지갑에 새 거래·잔고 변화가 보일 때만
  (안 쓰는 지갑은 0콜) · 잔고 대조가 원장 밖 보유도 돌아가며 확인(상태 패널 한 줄 · 알림 없음) · [수집 한계](docs/COLLECTION_LIMITS.md)에 체인별 '옛 보유 토큰 찾기' 줄
  (Base·BNB Chain·X Layer 는 키가 없으면 '옛 보유 확인 불가') · 체인별 출처표 = `seed/coverage/token_sources.json` · 끄기 = `config.json` 의 `"token_discovery": {"enabled": false}` ·
  이미 등록한 지갑 전수 점검 = 1회 도구 `tools/token_recheck_1010.py`(미리보기 전용).
- **발견 시점 기초 잔고** — 그래도 놓친 옛 보유 토큰을 내보내 원장 수량이 마이너스가 되면, 그 거래 직전 블록의 실제 잔고(무료 RPC 2콜)로 확인된 만큼 '발견 시점 기초 잔고'
  (원가 미상 · 발견 시각 시세로 추정)를 자동으로 적어요 — 지난날 곡선은 그대로 · 사칭·혼용 심볼·숨긴 토큰은 건너뛰고, 내가 서명하지 않은 유출은 남이 실행한 교환·LP 의 네이티브·정품 토큰만 ·
  확인이 안 되면 마이너스 그대로 두고 다시 시도(점점 길게 · 최대 6시간 간격) · 끄기 = `"negabs_enabled": false`(또는 `TJ_NEGABS=0`) ·
  업데이트 전에 이미 생긴 마이너스 칸·전수 점검 결과는 1회 도구 `tools/negabs_1010.py`(미리보기 → `--apply`).
- **Alchemy 키 칸** — 설정 › 연결·키에 Alchemy(EVM 지갑이 있으면 '필수' 표시 · 경고만 — 막지 않음) · 지갑 토큰·잔고 찾기 전용(`alchemy_getTokenBalances` — 감시·백필은 무료 노드) ·
  공식 CU 표로 세는 하루 장부(월 무료 한도의 80% ÷ 31 · 초당도 80% 아래) · 연결 테스트 = Ethereum·Base 최신 블록 1번씩 · 저장 즉시 사용(재시작 없음) · 노드 키 칸마다 '오늘 쓴 양' ·
  Ankr 토큰 찾기(Advanced API)는 같은 장부(요청당 700 크레딧)·따로 속도 한도로 · [API 키 받는 법](docs/API_KEYS.md)에 Alchemy·Ankr 절.
- **노드 키 버스트** — 무료 노드 키(Alchemy·Ankr·NodeReal)는 백필·첫 전수처럼 밀린 일을 따라잡을 때 하루 몫을 3배까지 당겨 써요(최근 31일 합은 늘 월 한도의 80% 안 · 앞으로의 감시 몫은 남김 ·
  유료 키는 버스트 없음) · 칸에 '버스트 중' · 사용 기록이 없는 지난날은 평소 몫을 썼다고 보수적으로 세서 업데이트 뒤 한 달쯤은 버스트가 드물어요 —
  새로 받은 키라면 그 칸의 **새로 받은 키(지난 사용 없음)** 를 켜면 바로(자동으로 켜지지 않음 · 키를 다른 값으로 바꿔 저장하면 꺼짐).
- **EVM 체인 표** — Alchemy 가 지원하는 EVM 메인넷 73개 체인 표(`seed/coverage/evm_chains.json` — 체인 id·Alchemy 네트워크·토큰 API 지원·'무료 경로 있음 / Alchemy 필요'·잔고 찾기·백필 보조·감시 예비 경로) ·
  미추적 체인 점검 목록 +18 · 표에 있다고 추적하지 않아요(추적은 종전처럼 활동이 보이면 자동 켜기).
- **선물 — 코인 정산 달러** — 코인으로 정산된 선물 손익(BNB 수수료·코인 마진)의 달러를 정산 시각 시세로 매겨요(받아 둔 1분봉 → 그날 마감가 → 둘 다 없으면 지금 시세 + '추정' 건수 표시 · 외부 호출 없음) —
  지난 선물 손익·영수증·명세 선물 행이 시세 따라 움직이던 것 · 원장은 종전처럼 코인 수량.
- **바이빗 선물 수수료·펀딩** — 거래 내역(transaction-log)으로 수수료·펀딩은 낸 시각에, 실현 손익은 청산 체결 시각에 따로 기장해요(받기 시작한 뒤부터 · 그 전 기록과 조회 권한 없는 키는 종전처럼 청산 시각에 합쳐서 · 합은 같음).
- **빌린 코인 원가** — 거래소 대출로 빌려 출금한 코인(거래소 보유가 출금으로 0 밑으로 갔다 나중에 같은 거래소 유입으로 채워진 몫)의 원가 = 빌린 시각 시가, 채울 때 차이 = 실현 ·
  `config.json` 의 `loan_short` 에 대출 기록으로 확인된 기간을 적었을 때만(비우면 종전 = 원가 미확인 · 6시간 안에 채워진 몫·업비트·빗썸·Hyperliquid 는 제외 · 최초 인식 시가가 켜져 있을 때 — 기본) ·
  명세 '대출 상환' 행 · 화면 계산만(원장 무변).
- **Base 과거 기록 넓히기** — 늦게 시작한 지갑 묶음이 앞선 묶음을 따라잡으면 한 묶음으로 합쳐 같은 구간을 두 번 훑지 않아요 · 지갑이 많은 묶음도 한 번에 훑는 구간이 늘어나요
  (지갑 수만큼 드는 잔고·nonce 확인 시간은 구간 판정에서 뺌 — Base 처럼 지갑 많은 체인이 몇 배 빨라짐) · 진행률·남은 시간을 실제로 훑을 블록 기준으로.
- **빗썸 지난 체결 시각** — 예전 판이 '주문 생성 시각'으로 적은 빗썸 지정가 체결을 '마지막 체결 시각'으로 바로잡는 1회 도구 `tools/bithumb_filltime_1010.py`
  (미리보기 → `--fetch`(빗썸 주문 단건 조회 · 초당 4) → `--apply` · 수량·금액·종목은 그대로, 날짜 배치만) · 재구축이 해외 체결 원본의 최신 개정을 써요(바로잡은 시각이 재구축 뒤에도 유지).
- **외부 응답 크기 상한** — 공통 요청 경로(EVM·BSC 수집·백필·토큰 찾기의 RPC·탐색기 호출)의 응답 본문을 정상 32MiB · 오류 64KiB 까지만 읽어요(넘으면 그 요청만 실패 — RPC 배치는 반으로 나눠 다시 · 로그 훑기는 그 구간을 반으로).

**함께**

- **문서** — README 처음 표·키 표에 Alchemy · [옛 보유 토큰 찾기 · 체인 표](docs/FEATURES.md#옛-보유-토큰-찾기--체인-표) 절 · 1회 도구 3개·`loan_short`·`token_discovery`·`negabs_enabled` ·
  `.env.example` 에 `TJ_ALCHEMY_KEY` · [API_KEYS.md](docs/API_KEYS.md) Alchemy·Ankr·버스트 · [COLLECTION_LIMITS.md](docs/COLLECTION_LIMITS.md) '옛 보유 토큰 찾기' 줄·바이빗 선물 수수료·펀딩.
- **시험** — 공개 시험 추가: 토큰 발견·잔고 대조 · 발견 시점 기초 잔고(재구축·멱등 포함)·화면 문구 · Alchemy 키·노드 장부·버스트 · EVM 체인 표 · 코인 정산 선물 달러 · 응답 크기 상한 ·
  Base 묶음 합치기 · 바이빗 거래 내역 · 빌린 코인 원가 · 빗썸 체결 시각 — 전체 3,200건 넘게(파일 90개).

**English** — Tokens held since before the collection window (5 months by default) are no longer missed. When a wallet is registered, per-chain sources are merged
(Etherscan, Routescan, Blockscout, Alchemy, Ankr, the Rabby portfolio, RPC log scans and genuine tokens already in the ledger) to find every token the wallet ever touched,
and opening balances are set from same-block balances (suspected spam is skipped). Keyed APIs are called once per (wallet, chain) and again only when free signals show
activity; Base, BNB Chain and X Layer need a free Alchemy/Ankr key for this (`seed/coverage/token_sources.json`; off with `"token_discovery": {"enabled": false}`).
If a missed token is later sent out and the ledger goes negative, the balance one block earlier is read (free RPC) and a "found-at-discovery opening balance" (cost unknown,
valued at the price then) is booked (`"negabs_enabled": false` turns it off). New **Alchemy key** field (shown as required with an EVM wallet; warning only), metered per day
with the official CU table under 80% of the free plan, no restart needed; Ankr's Advanced API is metered on the same ledger. Free node keys may **burst** up to 3x the daily share
while catching up (rolling 31-day total under 80%; a "new key (no past use)" switch lets a fresh key burst right away). `seed/coverage/evm_chains.json` lists the 73 Alchemy-supported
EVM mainnets with free vs Alchemy-only paths (+18 chains in the untracked-chain sweep). Coin-settled futures PnL is now valued at the settlement-time price (cached 1-minute candle →
day close → current price marked "estimated"), and response bodies on the shared RPC/explorer request path are capped (32 MiB, errors 64 KiB; some direct lookups are not yet — see known limits). Base-style chains with many wallets backfill
old history several times faster (merged tail lanes). Bybit futures fees and funding are booked when paid (transaction log). `loan_short` in `config.json` (confirmed exchange-loan
periods only) gives borrowed-and-withdrawn coins a cost at the borrow-time price. One-time tools: `tools/token_recheck_1010.py` (preview-only scan of existing wallets),
`tools/negabs_1010.py` (preview, then `--apply`) and `tools/bithumb_filltime_1010.py` (re-time old Bithumb limit fills to the last fill). No rebuild and no data revision.
Only the Settings › keys (explorer keys) screenshot was retaken (Alchemy row); the dashboard LP card position still differs.

**알려진 한계(→ 2026-10-10 (2) 판에서 고침)**

- ~~옛 보유 토큰 찾기에서 판정(DEX 조회)이 잠깐 실패해 '일시 보류'된 토큰 중 시세를 아직 모르는 것은 잔고 대조에서 빠져요~~ — **2026-10-10 (2) 판에서 고침**(1시간마다 다시 판정 · 상태 패널 '토큰 판정 대기 N' · [2026-10-10 (2)](#2026-10-10-2--새-설치본-수집--최신-우선)).
- ~~BNB Chain 지갑별 기초 잔고 대조에서 '일시 보류'된 토큰도 확인한 것으로 남아, 그 토큰의 옛 거래가 늦게 들어오면 기초 잔고로 상쇄될 수 있어요~~ — **2026-10-10 (2) 판에서 고침**(관측한 토큰만 확인으로).
- ~~남이 실행한 교환으로 나간, 정품 목록 밖 일반 토큰은 화면에서 정품 등록을 할 수 없어 발견 시점 기초 잔고를 다시 시도해도 건너뛰어요~~ — **2026-10-10 (2) 판에서 고침**(`tools/negabs_1010.py --genuine <CA> --chain --wallet` → `--apply`).
- ~~응답 크기 상한은 공통 요청 경로에만 걸려 있어요 — 공통 경로를 거치지 않는 직접 조회(솔라나 수집·대사, 시세·OKX 토큰 가격, Rabby, 업비트, 입금 주소, 브릿지·자금 흐름 추적, LP 목록, 세일 매칭, 거래 출처)는 아직 본문 끝까지 읽어요~~ — **2026-10-10 (2) 판에서 고침**(직접 조회 12곳도 같은 상한 — 정상 32MiB · 오류 64KiB).

## 2026-10-09 밤 — 외부 수정 검증 반영

**원장 손상 대기·버전 표시 · 복구 도구 · 최초 인식 시가 안전장치 · 수수료·브릿지 규약 · 재생 순서 · 선물·청산 감시 · 곡선 마감가 · 새 LP 바로 평가 · 웹 느린 연결 방어 · 화면 ·
분류 보류 거래 · 미검증 DEX 가격·환율 시각 · 대표 심볼 '확인 필요'·정품 등록 · 원가 넘기기 · 거래소 서버 시각·쿠코인 HF · 체인 수집기 · 대시보드 LP 카드**

지난 판(2026-10-09 오후)을 다시 검증한 외부 검토를 하나씩 재현해 보고 진짜인 것을 고친 판이에요 — 1차 = 새 지적과 '먼저 고칠 것', 2차 = 지난 지적 중 아직 '안 고쳐짐'·'일부'였던 것(숫자가 틀리는 것부터).
사진은 지난 판 그대로예요(대시보드 LP 카드 위치는 사진과 달라요).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js`). 재구축은 필요 없어요.
> 이 판부터 설정 맨 아래에 버전(`VERSION`)이 보이고, 원장에 **데이터 개정 번호**(`meta` 의 `data_rev`)를 적어요 — 이 판 = 데이터 개정 1(선물 정산 재배치를 적용할 때 기록).
> 이 번호를 모르는 예전 판 코드는 그 칸을 무시하므로, 이 판에서 되돌릴 때는 코드만 되돌리면 돼요. 최초 인식 시가 안전장치·수수료 규약·원가 넘기기 정리로 실현손익·명세 숫자가 조금 바뀔 수 있어요.
> 수집기 쪽 고침(BSC 매도 대금 · 빗썸 과거 지정가 체결 시각)은 새로 받는 거래부터예요. 이미 원장에 있는 분류 보류 거래의 잔고 변화는 재구축([백필 · 재구축](docs/OPERATIONS.md#백필--재구축--재백필)) 때 들어가요.

**1차 — 새 지적 · 먼저 고칠 것**

- **원장 지키기·상태** — 깨진 원장은 띄우지 않고 '원장 손상 — 복구 필요'로 기다려요(띄우기 전 가벼운 검사 · 작은 원장은 `quick_check` 까지 · 큰 원장은 tj-core 가 곧바로 죽으면 그때 ·
  손상 오류가 난 기록은 격리하지 않고 멈춤). 원장 없음·손상·감시 유닛 꺼짐을 화면 위 배너로 알려요(tj-alert 없이도). pm2 없이 돌려도 멈춘 유닛·처음부터 실패하는 수집기·빈 시세를 알아채요
  (각 유닛이 `state/runner_<유닛>.json` 에 30초마다 기록). 디스크 부족으로 백업을 건너뛴 채 30시간이면 빨강 + 텔레그램 · 버전 표시(`VERSION` · `/api/health`)·데이터 개정 번호.
- **복구 도구** — `tools/ledger_restore.py` 가 EVM 기준 블록을 실제 원장(들어온 시각)에서 찾고, 기준이 없는 RPC 커서는 블록 시간으로 넉넉히 되감아 미리보기에 ★ 로 알려요 ·
  RPC 로 받은 체인은 백업 뒤 방출했던 거래를 해시로 다시 받아 로그 없는 송금도 채워요 · 원장 밖 사본 되돌리기(`ledger_restore.py files` · 깨진 사본이 하나라도 있으면 전체 거부) ·
  미리보기에 백업 뒤 생긴 판정 수 · 되돌리기 전 원장은 최근 2개만 보존(`--keep-pre`) · 깨진·0바이트 백업은 '열기 실패' · 저장소에 없는 도구를 가리키던 안내 고침.
  서버 밖 백업은 scp 제한 시간·보낼 도구(rsync/scp)와 받는 쪽 rsync 확인 · 압축만 하고 암호화하지 않는다는 안내 · 처음 접속 때 호스트 키 자동 수락을 문서에.
- **최초 인식 시가 안전장치** — 보냈다 같은 주소에서 돌아온 코인은 보낼 때 원가를 이어받고, 확인 안 된 컨트랙트 토큰과 실제 매도가의 10배 넘는 시세는 매기지 않으며(원가 미확인 + 검토),
  한 번 매긴 값은 고정해요(`state/first_seen_px.json` · 원장 밖 백업에도 포함 · 시세를 기다리는 동안 '시세 대기'). 받은 날 판 몫은 판 값이 원가 · 시세 없는 가스는 검토 행 ·
  폰 카드·보유 줄 '추정' 표시와 처음 한 번 안내 · 이름은 '최초 인식 시가' 하나로.
- **수수료 원가 규약** — 가스 반영을 꺼도 수수료로 쓴 코인(가스·거래소 출금 수수료)의 시가 − 원가 차익은 실현에 반영해요(스위치는 비용만 정함 · 끄면 출금 수수료도 가스·수수료 탭에 따로).
  브릿지 수수료도 같은 규약(떼인 코인의 처분 손익은 늘 실현 · 시가 비용은 켬일 때만 · 끄면 가스·수수료 탭 출발 체인 줄에). 가스 규칙 '시가 미상'에 출금·브릿지 수수료가 음수로 섞이던 것,
  자금 흐름 지도의 출금·브릿지 수수료 중복, 환율 기록 없는 시각의 수수료 처분 행에 생기던 가짜 원화 환차를 고쳤어요 · 스테이블 '추정' 표기는 거래소·지갑 이동 뒤에도 붙어요(숫자 무변) ·
  명세 안내 '가스·수수료 탭 전체'에 거래소 출금 수수료도 들어가요.
- **재생 순서·브릿지·스왑** — 같은 블록은 원본의 tx 순번·로그 번호로, 같은 초 묶음은 아무도 모자라지 않는 순서로 재생해요 · 브릿지 도착이 출발보다 10분까지 먼저 찍혀도 짝 ·
  컨트랙트가 다른 비슷한 수량 후보가 둘이면 짝을 보류(검토) · 시세 없는 다리가 여러 개인 스왑은 원가를 시세 비례(없으면 균등 · 추정)로 나눔 · 브릿지 예치 증서는 낸 토큰 원가를 이어받음(화면 계산만 · 원장 무변).
- **선물·청산 감시** — 선물 정산 자산(BNB 수수료·코인 마진)은 그 자산으로 기장하고 화면은 달러 환산 · 선물 정산 재배치: 되돌리면 `--apply` 전까지 자동 적용 안 함 · 적용 전 원장 백업 ·
  준비된 거래소부터(대기 거래소는 상태 패널 '선물 재배치 대기') · 대기 시작 시각은 재시작해도 이어받음. 잔고 대사 표본에서 바이낸스 선물 지갑 몫을 빼고, 표본이 1시간 연속 다르면 반영(상태 패널).
  청산 감시: 한 번이라도 읽은 거래소는 권한 오류도 10분 뒤 주황 · 1시간 넘게 못 보면 한 번 알림 · 5~30분 간격 재시도 · 1단계 위험 구간도 다시 알림 · 재진입 알림은 최소 15분 간격 ·
  목표가·손절은 낡거나 멈춘 가격으로 판정하지 않음('감시 불가'). 1회 도구(`exf_fut_place.py` · `latefix_move.py`)의 `-h` 는 사용법만 보이고, 적용은 유닛이 멈췄는지 확인해요.
- **곡선** — 옛 마감 변환은 빗썸 원화만 더함 · LP 없는 현금도 처음 관측 전은 0 · 장기 곡선은 첫 기록 날부터 · 그날 마감가는 그 시각까지의 정보만(보간·미래 종가 금지 · 받아 둔 지난날은 그대로).
- **LP** — 방금 예치한 LP 포지션을 바로 평가해요(정기 갱신을 기다리는 동안 20초마다 '원장에 있고 평가가 없는' 열린 포지션만 · 종전엔 다음 갱신까지 총자산이 원금만큼 줄어 보였어요).
- **웹 서버** — 느린 연결 방어: 요청 줄 + 헤더는 10초 안에 · 루프백이 아닌 주소는 IP당 동시 연결 32(`web.max_conn_per_ip`) · 대기열 128 · 로그인 전 요청 본문도 크기에 맞춘 제한 시간 ·
  데모 서버도 같은 상한. `.env` 가 BOM 으로 시작해도 첫 키를 읽고, `/api/day_events` 를 조건 없이 부르면 최신순 5,000건 페이지로 줘요.
- **화면** — 첫 설치 카드는 Solana 지갑이 있을 때만 Helius 를 요구 · 카드 닫기·설정에서 다시 보기 · 마법사 단계 새로고침 유지 · 폰 양도차익 명세 큰 금액 겹침·잘림 없음 ·
  대시보드 배경 갱신이 글자 선택을 지우지 않음 · 명세 카드에 '스테이블 환차손익' 카드(식이 맞게) · '스테이블 환차는 명세에만(실현손익엔 없음)' 문구 · 머리 상태 칩 짧게 · 시트 안 Tab 순환 ·
  펼친 사이클 금액 표기 통일.
**2차 — 지난 지적 중 '안 고쳐짐'·'일부'였던 것**

- **분류 보류 거래** — 분류 보류(UNKNOWN) 거래도 지갑 잔고 변화를 기록해요(시세 없이 원가만 넘김 — 손익 없음 · 내 지갑끼리는 위치 이동) · '분류 보류' 검토를 원장에서 늘 읽어 지난 기록도 보여요 ·
  일별 순유입에선 입출금이 아니라 매매로 봐요.
- **가격·환율** — 풀 유동성을 모르는 DEX 가격은 '미검증'으로 총자산·알림에서 빼요(지금 쓸 가격이 OKX DEX 값과 10% 안일 때만 인정 · 유동성 값이 낡아도 마지막 값이 얇으면 계속 제외) ·
  원화 환율을 받은 시각과 함께 두고 1시간 넘게 못 받으면 그날 마감을 미뤄요(그날은 그 시각 1분봉 환율로 닫힘 · 고정 대체값은 마감·곡선에 저장 안 함).
- **대표 심볼 '확인 필요' · 정품 등록** — USDT·WBTC 같은 대표 심볼인데 정품 목록에 없는 컨트랙트를 심볼만으로 숨기지 않아요 — 유동성 있는 시세·거래소 출금 도착이면 정품,
  아니면 '값 없는 토큰'에 **확인 필요** 배지(확인 전 평가 0 · 총자산·기록·알림 밖). 배지의 [정품으로 등록] = 사용자 정품 목록(`state/genuine_tokens.json` · 원장 밖 백업에 포함) —
  등록한 대표 스테이블은 액면 $1, 남이 보낸 토큰의 '에어드랍 의심' 격리도 풀어요(고플러스 스캠 확증은 그대로). 알림의 사칭 판정도 같은 유동성 기준이고, 내가 서명해 보낸 거래는 사칭으로 지우지 않아요.
- **Katana vbUSDC** — Vault Bridge USDC 를 계약 주소 기준 검증 스테이블(액면 $1 · USDC 묶음)로 — 원가 기록 없이 받은 vbUSDC 와 그것으로 산 코인의 원가가 추정 시가 대신 액면,
  처분은 명세 스테이블 원화 환차 표로(같은 이름의 다른 계약·다른 체인은 그대로).
- **원가 넘기기** — 시세 없는 다리 여러 개 스왑에서 같이 받은 시세 있는 코인·스테이블 잔돈은 그 시각 시가만 원가로(나머지는 시세 없는 코인에) · 한쪽만 시세 있는 스왑의 시세 없는 다리 여럿도
  시가 있는 쪽 합을 나눠 원가·정산액으로('추정' 표시 · 시세를 쓰는 쪽 = 네이티브·거래소 자산·정품 계약만) · 경제 가치 없는 동반 토큰(BNB Chain 스테이킹의 govBNB 같은 투표권 토큰 —
  `seed/zero_value_companions.json` · 이 설치 덧붙임 = `state/seed_local/zero_value_companions.json`)은 원가 나눔 가중 0, 스왑 가스도 실제 증서 쪽에 ·
  브릿지 예치 증서와 같이 받은 가스 환불 잔돈이 증서 원가 승계를 막지 않아요(화면 계산만 · 원장 무변).
- **거래소 수집** — 바이비트 붙은 심볼을 거래소 공개 종목 목록(하루 1회)으로 나누고, 대금 통화를 모르면 유령 코인 대신 체결 보류 · 새 설치·첫 연결 때 바이낸스·바이비트·쿠코인·OKX 옛 출금에도 수수료 반영 ·
  대사가 토큰 자릿수 18 을 지어내지 않음 · OKX 명목가를 모르면 '—'. 서명 시각을 거래소 서버 시각에 맞춰요(1시간마다 · 시각 오류 때 다시 재고 1번 재시도) · 쿠코인 고빈도(HF) 계정 체결 수집
  (일시 실패한 구간은 다음 주기에 이어 받음) · 바이낸스 선물 수익이 같은 ms 에 1,000줄 넘어도 페이지를 넘겨요 · 빗썸·업비트 과거 창 지정가 주문을 마지막 체결 시각으로 · OKX·쿠코인·게이트 마진 체결은 수집하지 않음을 문서에.
- **체인 수집기** — BSC·추적 없는 RPC 체인의 '내 토큰 → 네이티브' 매도에 받은 네이티브를 기록해요(랩드 풀기 로그 · 방금 거래는 잔고로 확인 — 같은 블록 승인·매도 여럿·옛 구간 합계) ·
  이더스캔 색인 전 직접 풀기의 ETH 수령(소각 Transfer 를 남기는 랩드 구현 포함) · 블록스카웃 delegatecall 줄 제외 · owner 없는 옛 솔라나 응답의 연관 토큰 계정 소유자 계산.
- **미추적 체인 · 지갑 격리** — 미추적 체인 점검이 정식 스테이블(balanceOf)까지 봐서 토큰만 받은 지갑도 찾아요(실제로 추적에 합류한 쌍만 빼고 · 설정에서 끈 체인의 발견은 경고·알림 없이 상세에 '끈 체인 N건') ·
  이더스캔 체인에서 한 지갑 목록 조회가 30분 넘게 실패하면 그 지갑만 보류하고 나머지는 계속 수집해요(회복 때 겹친 거래는 레그 합집합으로 보강).
- **대시보드 LP 카드** — LP 포지션이 큰 표 대신 레버리지 · 대출 바로 아래 카드로 와요(가치 큰 순 앞 2개 + 'N개 더' · 줄을 누르면 제자리 펼침 · 종료된 포지션 링크 · 폰은 목록 줄) ·
  레버리지 · 대출도 앞 2줄 + 'N개 더'.

**함께**

- **문서·저장소** — README [업데이트](README.md#업데이트)·[멈추기 · 지우기](README.md#멈추기--지우기) 절 · pm2 없이 쓸 때 로그는 덧붙이기(`>>`) · `alert_bot` 권장 · Ctrl+C 안내 ·
  [SECURITY.md](SECURITY.md) 에 예외 3가지(증권사 비밀값은 `config.json` · 서버 밖 백업 · AI 요약) · 수집 기록 보존은 기본 8일 · 스트림당 512MiB 상한(보장 기간 아님) ·
  `.gitignore` 에 압축 백업·편집기 사본·키 파일 · 1회 도구 `tools/upbit_trades_fill.py`(업비트 옛 주문의 실제 체결 시각 채우기)·`tools/repair_wrap_legs.py`(직접 감싸기·풀기의 빠진 레그 복구) 공개.
- **시험** — 공개 시험 추가: 원장 손상·데이터 개정·pm2 없는 상태 점검·화면 배너 · 실제 core 로 복구 · 최초 인식 시가 안전장치 · 수수료 비용 끔·브릿지 스왑·출금 수수료 흐름 · 선물 자산·재배치 되돌리기·
  대사 표본·청산 감시 재시도·낡은 가격 · 곡선 시작일 · 느린 연결·로그인 전 본문 · 새 LP 바로 평가 · 1회 도구 인자 · (2차) 분류 보류 거래 · 미검증 DEX 가격·환율 시각 · 대표 심볼 확인·정품 등록 ·
  vbUSDC · 원가 넘기기 n:m · 바이비트 심볼 나누기·첫 연결 출금 수수료·자릿수 · 거래소 서버 시각·쿠코인 HF · LP 카드 — 전체 2,700건 넘게(파일 77개).

**English** — Fixes from an external re-verification of the previous release (night of 2026-10-09). A corrupt ledger is no longer started: units wait with
"ledger corrupt — restore needed" (a light check before start, `quick_check` on small ledgers), and a missing/corrupt ledger or a stopped monitor unit shows as a banner
even without tj-alert; stalled units are detected without pm2 too. The version (`VERSION`) is shown at the bottom of Settings and the ledger now records a data revision
(`meta.data_rev`, revision 1 = futures settlement re-placement); older code ignores it, so rolling back from this release needs the code only. The restore tool finds EVM base
blocks from the real ledger, rewinds RPC cursors by block time when there is no base (marked ★), re-fetches log-less native transfers by hash and can restore off-ledger copies
(`ledger_restore.py files`). First-seen price safeguards: coins coming back from the same address inherit their cost, unverified tokens and prices over 10× the actual sale price
are not used, and assigned values are fixed. Fee-cost rule: the price-minus-cost gain on coins spent as fees (gas, withdrawal and bridge fees) is realized even with gas costs off.
Replay order inside a block follows tx index and log index; bridge matching tolerates arrivals up to 10 minutes early and holds ambiguous candidates. Futures settlements are booked in
their own asset (BNB fees, coin margin); an undone re-placement is not re-applied until `--apply`. Liquidation watch alerts when a venue it has read before is unreadable, repeats
in stage 1 and does not judge targets/stops on stale prices. Day-close prices use only information up to that time. New LP positions are valued right away. The web server limits slow
connections (headers within 10 s, 32 concurrent connections per non-loopback IP). README gains "update" and "stop · uninstall" sections; SECURITY.md lists the three exceptions to
"secrets only in `.env`". Second round (earlier findings still open): unclassified (UNKNOWN) transactions now record wallet balance changes; DEX prices with unknown pool liquidity
count only when they match OKX DEX within 10%, and the day close waits when the KRW rate is over an hour old; major symbols (USDT, WBTC …) on unlisted contracts are no longer hidden
by symbol alone but shown as "needs check" (valued 0 until confirmed; a user genuine list in `state/genuine_tokens.json`); Katana vbUSDC is a verified stablecoin by contract;
cost carry-over for multi-leg swaps without prices (zero-value companion tokens such as govBNB in `seed/zero_value_companions.json`); Bybit symbols split by the public instrument list,
withdrawal fees on first connect, request timestamps synced to exchange server time, KuCoin HF fills; BSC token-to-BNB sales record the BNB received; tracked-chain sweeps see
stablecoin balances and one failing wallet no longer blocks the rest; the dashboard LP table became a card under leverage/loans. Collector-side fixes apply to newly fetched
transactions. Screenshots unchanged (the LP card position differs from them).

**알려진 한계(→ 2026-10-10 판에서 고침)**

- ~~코인으로 정산된 선물 손익(바이낸스 BNB 수수료·OKX 코인 마진 등)의 화면 달러 환산이 지금 시세 기준~~ — **2026-10-10 판에서 고침**(정산 시각 시세로 · [2026-10-10](#2026-10-10--옛-보유-토큰-찾기--alchemy-키)).
- ~~외부 RPC·탐색기 응답 본문에 크기 상한이 없음~~ — **2026-10-10 판에서 공통 요청 경로를 고침**(정상 32MiB · 오류 64KiB · 직접 조회 몇 곳은 다음 판 — 2026-10-10 알려진 한계).

## 2026-10-09 오후 — 외부 전면검토 반영

**선물 정산 = 정산 시각 · 스테이블 원화 환차 · 최초 인식 시가 · 수수료 원가 · 곡선 재설계 · 서버 밖 둘째 백업 · 청산 감시 · 화면·접근성**

직전 공개판 전체를 다시 본 외부 검토(71건)를 하나씩 재현해 보고 진짜인 것을 고친 판이에요. 사진은 지난 판 그대로예요.

> **업데이트 뒤 숫자가 바뀔 수 있어요** — `pm2 restart ecosystem.config.js` 로 모든 유닛을 다시 켜세요. 원가를 모르던 수량에 '최초 인식 시가'(기본 켬)가 붙고,
> 수수료 원가 규약·스테이블 원화 환차가 실현손익·양도차익 명세에 들어가요(추정한 행은 '추정' 표시). tj-core 는 첫 거래소 대사 때 지난 선물 정산을 정산 시각으로 한 번 다시 놓고,
> 30일·장기 곡선은 새 규칙으로 한 번 다시 계산돼요(재구축은 필요 없어요).

- **선물 정산 = 정산 시각** — 거래소 잔고에 합쳐진 선물 지갑(바이낸스·바이빗·OKX)의 실현 손익·수수료·펀딩을 대사하는 날이 아니라 **정산 시각**에 총자산으로 기장해요(지난날로 소급하지 않음).
  업데이트 뒤 첫 대사 때 지난 대사가 다른 날로 보낸 선물 정산을 한 번 다시 놓아요 — 근거(감사 기록·선물 정산 파일)가 모자란 통화는 옛 배치 그대로 두고,
  `tools/exf_fut_place.py` 로 계획 미리보기·되돌리기를 할 수 있어요. 선물 정산 파일이 잔고를 못 덮으면 그 거래소 대사를 미루고(상한 3시간 · 1시간 넘게 미루면 상태 패널 '주의'),
  늦게 찾은 옛 체결의 상쇄는 그 체결 직후에 둬요. 대사 되돌림은 부채 이자를 지우지 않고, 재구축은 선물 정산 금액·시각을 그대로 이어 가요. '선물 미반영' 줄은 아직 대사 전인 정산만이에요.
- **해외 거래소 잔고 대사** — 잔고 응답의 금액 칸이 빠졌거나 목록이 불완전하면 조회 실패로 보고 보류 · 잔고 표본 두 번이 일치할 때만 대사 · 마진 체결·간편전환 일시 실패와 진행 중 출금 동안엔 대사를 미뤄요 ·
  바이낸스 담보대출 담보가 Earn 과 두 번 세이던 것 고침 · 바이낸스를 새로 연결하면 모든 심볼 체결 확인을 마친 뒤 첫 대사.
- **양도차익 명세 — 스테이블 원화 환차** — 스테이블코인을 원화로 산 몫은 산 때 원화를 취득가로 써서 환차손익을 별도 표로 보여 줘요. 원화 기록이 없는 몫(액면 입금·기초 잔고)은 처분 시각 환율(환차 0)이고,
  거래소↔지갑·해외 거래소로 옮겨도 원화 원가 몫과 액면 몫을 따로 이어 가요(수수료로 쓴 몫·오프체인 왕복 포함). 처분 행을 누르면 **환차 상세**(용도 · 처분 환율 · 평균 취득 환율 · 주요 매수 상위 3 · 계산식)가 열려요.
  선물 손익·기타 소득(스테이킹·유동성 보상)도 별도 표 · 추정 행 배지 · 시행일 문구는 날짜 기준 · 원가 방식 설명 · 선물 승률은 '정산 건 기준'으로 표기.
- **최초 인식 시가(기본 켬)** — 원가를 모르는 수량(기초 잔고·원가 없는 입금·에어드랍)의 원가를 그 수량이 장부에 처음 생긴 날 시가로 추정해요. 명세·카드·실현손익 머리에 '추정'으로 표시하고,
  스테이블은 원화 취득가를 그때 환율로, 직접 지정한 원가가 먼저예요. 옛날 날(원장 시작일까지) 시세는 남는 API 사용량으로 천천히 받아 채우고(진행률 = 설정 › 원가 계산),
  '이 중 추정' 실현은 수수료·가스 뒤 금액이에요. 가치를 모르는 스왑으로 이어받은 수량은 스왑 날 시가로 다시 매기지 않아요. 끄기 = **설정 › 원가 계산**.
- **수수료 원가 규약** — 가스·체결 수수료로 낸 코인·거래소 출금 수수료 = 그때 시가만큼 비용 + 원가를 아는 몫의 처분 손익(업비트·게이트·빗썸 출금 수수료 몫의 원가가 사라지던 것 고침 · 명세에도 한 줄씩) ·
  양쪽 시세가 없는 스왑은 원가를 그대로 이어받음 · 브릿지 거래에서 받은 토큰 반영 · 평균가 대체는 그 사이클의 평단만.
- **재생 순서·브릿지 짝** — 같은 초의 매수·매도는 블록 번호·체결 시각(ms)·보유로 순서를 정하고, 브릿지 도착은 id 로 이어진 짝을 먼저 확정한 뒤 수량 98~102%·분할 묶음·같은 컨트랙트 우선·스팸 제외로 짝지어요 ·
  늦게 기록된 거래소 출금도 같은 txid 도착에 원가를 넘겨요(화면 계산만 · 원장 무변).
- **곡선 재설계** — 원장 밖 금액(업비트·빗썸 원화, 업비트 미매칭 코인, LP, Rabby 몫)을 구성요소별 규칙 하나로 계산해 30일 곡선과 장기 곡선이 같은 값을 써요.
  일별 마감 때 구성요소를 따로 기록하고(원화는 원 단위·환율·잔고 시각과 함께), 빗썸 원화도 지난날마다 거래 기록으로 되감은 그날 잔고를 써요(종전 = 지금 잔고를 모든 지난날에).
  한 번 정한 지난날 값은 다시 매기지 않고(옛 계산 동결값만 한 번 규칙대로 다시), 장기 곡선 30일 창 밖 날에도 그날 Rabby 몫이 들어가며, 업비트 미매칭 코인이 원장에 편입돼도 두 번 세지 않아요.
  장기 곡선 순유입에 빗썸 원화 입출금도 넣고, 기록과 실제 잔고가 크게 어긋난 구간은 가까운 실측값을 써요. 누락 레그 재기장·원장 복구 뒤에는 곡선을 다시 계산해요.
- **서버 밖 둘째 백업 · 복구** — 원장 파일이 없는데 예전 원장 흔적(백업·수집 기록)이 있으면 빈 원장을 만들지 않고 기다리며 복구를 안내해요(상태 패널 '원장 파일 없음 — 복구 필요').
  원장 교체는 원자적으로, 수집기 기록(`state/inbox/`)은 읽은 뒤에도 8일 남겨요. 새 도구 `tools/ledger_restore.py`(백업 목록·검사·되돌리기·그 사이 수집분 다시 받기)와
  `tools/offsite_backup.py`(압축 원장 사본을 다른 컴퓨터로 · sha256 확인 · 밖으로 ssh 를 못 나가면 outbox 모드 · 기본 꺼짐) — README [백업 · 복구](docs/OPERATIONS.md#백업--복구).
  정기 백업이 3일 넘게 없으면 상태 패널 빨강 + 텔레그램.
- **청산 감시** — 거래소 조회가 막혀도 마지막 값으로 위험 알림을 보내고, '청산 감시가 <곳>을 못 보고 있어요' 알림·상태 패널 빨강 · 청산가 도달은 늘 한 번 더 ·
  위험 구간이면 1시간마다 다시(`alerts.liq_repeat_min` · 0 = 끔) · 벗어났다 다시 들어오면 다시 알림 · OKX 선물 명목가에 계약 단가 반영 · BTC 비교선이 일별 가격을 제대로 찾음.
- **수집기** — 이더스캔 경로의 직접 감싸기·풀기(WETH·WPOL 등)를 전환으로 기록 · 프록시 내부 호출(delegatecall 등)을 값 이동으로 두 번 세지 않음 ·
  솔라나 옛 응답의 소유자 없는 토큰 줄을 버리지 않음 · 주요 L2·솔라나 정품 브리지 토큰이 '가짜'로 숨겨지던 것 고침 · NFT 1155 중복 줄 개수 ·
  BNB Chain·추적 노드 없는 체인의 수집 한계를 문서에.
- **상태 패널 — 재계산 대기** — 잔고 불일치·원장 음수의 '재계산 대기' 칸에 그 체인 과거 기록 넓히기의 진행률·남은 시간과 '끝나면 원장 자동 재계산으로 사라져요'를 보여 줘요.
  넓히기가 끝날 때까지는 '주의'(주황)이고, 끝났는데도 3일 넘게 남으면 오류(빨강)·알림. 탐색기 ↔ RPC 로 경로가 바뀐 체인의 옛 진행 표식과 하루 넘게 갱신 없는 표식은 '진행 중'으로 보지 않아요.
- **화면·접근성** — 금액 칸 말줄임 없앰(축약·줄바꿈) · 명세 카드 '양도차익(명세 기준)'과 머리 차이 줄 · 첫 설치 안내 카드·수집 전 문구 · 자동 갱신이 입력 중인 글자를 지우지 않음 ·
  설정 마법사 초점·오류 문구 · 숫자만 쳐도 원화 금액 검색 · 접근성(h1·표 머리·토스트·확인 창 초점·차트 점) · 라이트 테마 대비 · 로그인 화면 글꼴·시스템 테마 · 해요체·용어 통일.
- **운영·보안** — `.env` 읽기 규칙 하나로(`export` · `=` 앞뒤 공백 · 같은 따옴표 한 겹) · 연결 수·차트 캐시 상한 · 입력 검사 · 지갑이 아닌 주소(토큰 민트 등) 등록 거부 ·
  손상된 설정 파일은 덮어쓰기 전에 보존 · 격리 재처리 요청은 앞 요청과 합침 · 배경 스레드가 손상된 상태 파일에 조용히 죽지 않음 · 쉬운 오류 문구 · 폴더 권한·인코딩 점검.
- **문서·저장소** — README '백업 · 복구' · 첫 비밀번호의 설정 코드(`cat state/auth_setup_code`) 안내 · 재백필 때 `state/` 는 설치 폴더 밖으로 ·
  [SECURITY.md](SECURITY.md)(보안 문제는 비공개 보고로) · `.gitignore` 에 설치 폴더 안 사본(`state*/`·`config*.json`·`env*.txt`) · CI 는 브라우저 스크립트 문법(`node --check`)도 확인 ·
  수집 한계 문서에 바이낸스 소액 전환(Dust)·바이빗 선물 수수료·펀딩·BNB Chain 내부 이동·추적 노드 없는 체인.
- **시험** — 공개 시험 추가: 선물 정산(재배치·근거 검사·늦은 체결) · 스테이블 환차 · 최초 인식 시가·옛날 시세 · 수수료 원가 · 재생 순서·브릿지 짝 · 곡선 구성요소 · 원장 복구 · 서버 밖 백업 ·
  청산 감시 · 재계산 대기 · `.env` 읽기 — 전체 1,900건 넘게(파일 45개).

**English** — External full-review fixes (afternoon of 2026-10-09; 71 findings on the previous public release reproduced and fixed where real).
Futures settlements merged into exchange balances (Binance/Bybit/OKX) are booked at settlement time instead of the reconciliation day; after updating, tj-core re-places
earlier settlements once (`tools/exf_fut_place.py` previews/undoes it; currencies without enough evidence keep the old placement). Exchange balance reconciliation waits on
incomplete responses, needs two matching samples, and no longer double-counts Binance loan collateral. Capital-gains statement: stablecoin KRW FX gains/losses (KRW cost only
for the part bought with KRW, carried across exchange/wallet moves), a per-row FX detail popup, and separate futures and other-income tables. Unknown-cost amounts are now
valued at the price on the day they first appeared in the ledger ("first-seen price", on by default, marked as estimated; Settings › 원가 계산). One fee-cost rule for gas,
trading-fee coins and withdrawal fees. Same-second replay order and bridge matching are deterministic. Curves: off-ledger amounts (Upbit/Bithumb KRW, unmatched Upbit coins,
LP, Rabby) use one per-component rule shared by the 30-day and long-range curves, Bithumb KRW is rewound per day, and fixed past values are not re-priced.
Backup: a ledger-restore tool (`tools/ledger_restore.py`) and an optional off-site backup (`tools/offsite_backup.py`, push or outbox, sha256-verified); tj-core no longer
creates an empty ledger when an old one is missing. Liquidation watch alerts when it cannot see a venue and repeats in the danger zone. Collectors: direct wrap/unwrap
on the Etherscan path is booked as a conversion. Status panel shows history-extension
progress for "waiting for recalculation". UI/accessibility fixes, `.env` parsing unified, SECURITY.md. Screenshots unchanged. Numbers may change after updating —
restart all units with `pm2 restart ecosystem.config.js`.

## 2026-10-09 새벽 — 3차 검수 반영 · 실현 표기

**그날 카드 '총 실현' = 현물 실현 + 선물 실현 · 그날의 기록 시간순 · 진입 시각 추정 · 검색 돋보기**

- **그날 카드 실현 표기** — 위 칸 이름을 '총 실현'(현물 + 선물)으로, '왜 움직였나'의 실현 줄을 '현물 실현'(LP 수수료·스테이킹 보상 포함) · '선물 실현' 두 줄로 나눴어요.
  두 줄 합 = 위 칸(원화 모드면 칸과 같은 체결·정산 시각 원화 — 종가 환율로 다시 곱한 차이는 '환율' 줄로). 선물 정산 이익이 그날 총자산 변화에 아직 안 든 몫은
  '선물 미반영' 줄로 보여 줄 합 = 전일 대비를 지켜요(선물 지갑은 거래소 잔고 대사로만 원장에 들어와요). 작은 금액이어도 실현 두 줄은 '나머지'로 접지 않아요.
  대시보드 '오늘 무엇이 움직였나'·'M월 한눈에'·곡선 툴팁·자동 요약도 같은 줄이에요(요약의 '큰 요인'에서는 서로 지워지는 선물 짝을 빼요).
- **그날의 기록 시간순** — 선물 정산 묶음 줄이 맨 위 고정이 아니라 그 거래소 그날 마지막 정산 시각 자리에 와요.
- **선물 영수증 — 진입 시각 추정** — 빠진 청산 뒤 같은 가격으로 다시 진입해도 옛 진입 시각을 물려받지 않아요: 그 종목 체결이 7일 넘게 없다가 다시 진입했고
  청산이 그 재진입분만으로 덮이며 잔량이 청산의 2배 이상이면 재진입부터 다시 세우고 '진입 시각 추정'을 붙여요(같은 포지션의 뒤 분할 청산에도).
- **선물 영수증 — 바이빗 펀딩** — 진입 시각을 몰라도 정산 차이가 펀딩 한 번 상한(명목가 3%) 안이면 거래소 가격을 보이고 '펀딩 포함 가능'을 붙여요.
- **화면** — 검색 돋보기가 모든 폭에서 보여요(941~1002px 은 머리 줄이 두 줄).

**English** — Day card: the top tile is now "total realized" (spot + futures) and the breakdown shows "spot realized" and "futures realized" rows that add up to it
(KRW at fill/settlement time; the closing-rate difference goes to the FX row). Futures profit not yet in that day's total assets is shown as "futures not yet reflected"
so the rows still sum to the day's change. Day records list futures settlements in time order. Futures receipts: a same-price re-entry after a missing close no longer
inherits an old entry time (7-day idle rule, marked "estimated"); Bybit settlements without a known entry show the exchange price when within one funding cap.
The search button shows at every width.

## 2026-10-09 — 수정 재검증 반영

**선물 영수증 진입 시각 보호 · 화면(글꼴 자체 제공·폰 일별 배치·원화 목표가) · 운영 안전장치 · 공개 시험 확대 · MIT**

- **선물 영수증 — 진입 시각 보호** — 강제청산·ADL 이 기록에서 빠져도 뒤 거래가 옛 진입 시각을 물려받지 않아요. OKX 한 방향(net) 모드의 강제청산(102·103·106·107)·ADL(125~128)·블록 체결(204·205)을
  청산·체결 행으로 받고, 청산의 진입가가 쌓아 온 진입 체결 평균과 0.2% 넘게 다르면 뒤쪽 진입 묶음으로 다시 세워요(맞는 묶음이 없으면 '진입 시각 모름').
  부분 청산은 진입 묶음 수량도 같이 줄이고, 다시 세우기 작업량에는 상한이 있어요. 바이빗 청산 기록(주문 단위 합산)은 이 평균 검사에서 빠져요.
  업데이트 뒤 OKX 는 최근 3개월을 한 번 더 받아요(한 주기 20쪽까지 · 받은 만큼 저장하고 이어 받음).
- **선물 영수증 — 바이빗 펀딩** — 바이빗 정산 손익에 보유 중 펀딩이 섞여 거래소 가격까지 버리던 것 → 진입 시각을 알고 펀딩 시각을 지났고 차이가 명목가 × 3% × 지난 펀딩 수 안이면 가격을 보여 주고 펀딩 몫(fundIncl)은 따로.
- **선물 영수증 — 거래소 줄로 열기** — 일별 기록의 거래소 줄로 열면 '가격 n/m건' 배지·종목 칩(그 거래소 종목만)·칩 아래 네 칸·청산 목록·펀딩도 그 거래소 기준(서버 `coins[].exStats`) · 「전체 보기」로 전 거래소.
- **선물 영수증 — 폰 머리** — 순위('그날 실현 기여 n위')는 둘째 줄 보조 글, 평균 보유는 한 줄.
- **화면 — 글꼴 자체 제공** — IBM Plex Sans KR·Mono 를 `web/v2/fonts/` 에서 제공(unicode-range 조각 woff2 · 첫 화면은 쓰는 글자 조각만 받음 · SIL OFL 1.1) — Google Fonts 요청 없음 · CSP 에서 구글 주소 뺌.
- **화면 — 폰 일별 기록** — 잔디 → 달력 → 그날 카드 → 그날의 기록 순서(날짜를 누르면 그날 카드로 부드럽게 이동). 데스크톱 배치는 그대로.
- **화면 — 목표가·손절선 원화/달러** — '지금 팔면?'·매매일지 계획 시트의 목표가·손절선을 ₩/$ 칩으로 입력(다른 통화 환산값 표시 · 저장·감시·알림은 달러).
  원화 입력은 지금 환율로 바꿔 저장하고, 손대지 않은 기존 값은 원래 달러 그대로예요. 실제 환율을 못 받았을 때는 달러로만 입력해요. 감시 카드·보유 펼침 줄도 원화 화면이면 ≈₩ 로 보여요.
- **화면 — 대시보드 오른쪽 열** — 자체 스크롤을 없애 페이지를 내리면 끝까지 보여요(열 전체가 화면에 들어갈 때만 따라 내려옴).
- **화면 — 습관·머리 줄·그날 카드** — 비교할 시간대가 하나뿐이거나 비율이 같으면 '가장 잘/안 맞는 때' 대신 중립 안내 · 641~1100px 머리 줄에 검색 돋보기 ·
  남은 시간 표시 3곳 한국 시간 · 그날 카드 큰 숫자를 눌러 전체 금액(숨김·랜덤값 유지) · 자동 매칭 칩 글은 서버가 따로 보냄 · 덮여 안 쓰이던 서랍 CSS 정리.
- **운영** — 설정에서 지운 지갑 이름도 재시작 없이 반영 · 화면 계산 자식의 정상 대기(시간 제한 있는 대기)를 교착으로 오판하지 않음 ·
  바이빗 진입 체결·청산 손익 과거 채움이 만료·무효 커서에서 멈추지 않음(레이트 한도 retCode 10006 은 커서 유지) · SQLite 메모리 통계 끄기를 파이썬 쪽에서 확인해 '끔/못 끔/확인 불가'로 기록 ·
  유닛 러너 메모리 상한(tj-web 기본 3GB · `TJ_RUNNER_MAX_MB_<유닛>` · 0 = 끔) · tools 원장 경로의 `# ? %` 처리 · 옛 화면 경로(/classic·/futures)는 파일이 없으면 새 화면으로 ·
  이더스캔 'unsupported chainid' 도 미지원으로 처리.
- **상태 패널** — '원장 음수 보유'가 과거 기록을 넓히는 도중 늦게 들어온 옛 거래 때문이면 '재계산 대기' 설명을 붙여요(경고는 그대로 — 재계산 뒤에도 남으면 빠진 입금 점검).
  EVM 수집기가 재시작돼도 진행 중인 과거 기록 넓히기를 원장 자동 재계산이 '끝남'으로 착각하지 않아요.
- **시험** — 공개 시험 추가: 선물 영수증(누적 포지션·분할·반전·강제청산 누락·펀딩) · 빌드 분리(교착 판정·폴백) · 노드 키(무료 80%·유료 비율·키를 설정 파일에 안 씀) ·
  화면 스냅숏(버전 키·델타·저장·복원) · 체인 끄기(추천 기준·잠금·자동 끄기 스위치·시세 장애·자동 체인 30일 유예) — 전체 1,300건 넘게.
- **문서·라이선스** — 재구축 때 원장 임시 사본이 `state/` 밖(홈 폴더 · 원장 3배+2GB · `backfill.rebuild_dir` 로 변경)에 생긴다는 안내 · 고급 설정에 `TJ_TENSOR_KEY`·`health.t.build_p95_warn_s`·러너 메모리 상한 ·
  라이선스 = MIT(`LICENSE`).

**English** — Re-verification fixes (2026-10-09). Futures receipts: a missing liquidation/ADL no longer makes later trades inherit an old entry time (OKX one-way liquidation 102·103·106·107,
ADL 125–128 and block trades are now rows; a close whose entry price differs from the running entry average by more than 0.2% re-anchors to the matching recent entries, otherwise
"entry time unknown"; partial closes shrink entry lots; bounded work). Bybit closes that include funding keep the exchange price (funding shown separately). Opening a receipt from an
exchange row scopes the badge, coin chips, tiles and close list to that exchange ("show all" for every exchange). UI: IBM Plex fonts are served from the repo (no Google Fonts),
phone daily view puts the calendar first, target/stop inputs accept KRW or USD (stored in USD; USD only when no live FX rate), the dashboard right column no longer scrolls on its own,
habits only name a "best time" when there is something to compare. Ops: cleared wallet names apply without restart, the build child no longer mistakes timed waits for a deadlock,
Bybit cursors recover from expired/invalid cursors (rate limit 10006 keeps the cursor), SQLite memory-stats off is verified, a runner memory cap (tj-web 3 GB by default), negative
ledger holdings caused by a running history extension are explained, and restarting the EVM collector no longer lets the ledger rebuild mid-extension. More public tests (1,300+). License: MIT.

## 2026-10-08 저녁 — 외부 검토 반영

**선물 영수증 가격·진입 시각 · 화면 다듬기 · 상태 전송 304 · 운영 안전장치**

- **선물 영수증 — 바이낸스·OKX 가격** — 바이낸스는 정산(초 단위 시각)과 체결(ms)을 초 단위로 짝지어 청산 가격이 붙고, OKX 한 방향(net) 모드 계정도 가격 행이 생겨요
  (업데이트 뒤 OKX 는 최근 3개월을 한 번 더 받아요).
- **선물 영수증 — 진입 시각** — 같은 종목 체결을 시간순으로 쌓아 포지션이 0 이 된 뒤 첫 진입을 진입 시각으로 봐요(분할 청산도 맞게). 한 방향 모드의 반전(보유보다 많이 청산)과
  손익 0 청산은 가격이 맞아떨어질 때만 나눠 보여 주고(헤지 모드는 포지션 방향으로 바로), 아니면 종전 표시예요.
- **선물 영수증 — 바이빗 진입 체결** — 바이빗 정산(closed-pnl)에는 청산만 있어 진입 시각이 늘 비었어요. 이제 체결 내역(`/v5/execution/list`)에서 진입을 받아요
  (평소 수집 주기마다 1번 · 처음 한 번은 첫 바이빗 정산 30일 전까지 · 공표 한도의 0.1% 미만). 진입 시각이 하나도 없으면 '평균 보유' 칸은 숨겨요.
- **선물 영수증 — 차트·금액** — 차트는 고른 거래소의 봉과 점만 그려요(칩 이름 '봉' → '거래소') · 한 주문이 여러 체결로 나뉘어도 ▲ 하나(수량 합·평균가·'한 주문 n체결') ·
  그날 거래소가 2곳 이상일 때 거래소 줄로 열면 큰 숫자·세 칸이 그 거래소 금액(아래에 '그날 선물 전체' 줄) · 원화 보기는 실현·수수료·펀딩을 정산마다 원화로 바꾼 합 · 거래 줄 손익·수수료는 축약 없는 정확값.
- **선물 영수증 — 그 밖** — 종목 칩은 넓은 화면에서 줄바꿈(잘림 없음)·폰에서는 가로로 넘기고 더 있는 쪽 가장자리를 흐리게 · 한자 등 영문 아닌 글자가 든 종목도 이름·가격 그대로 ·
  크게 움직인 거래(숏 100 → 50 등)도 가격 표시(진입·청산가가 10배 넘게 다를 때만 의심) · 가격 없는 청산의 이유를 '체결 보강 중(남은 n구간)'·'체결 기록에서 못 찾음'·'거래소 값끼리 안 맞음'으로.
- **화면 — 머리 줄·서랍** — 폭 641~약 950px(넓은 글꼴이면 더 넓어도)에서 탭이 잘리거나 상태 칩이 찌그러지던 것 → 탭을 둘째 줄로 접어요 ·
  서랍을 그리다 오류가 나면 설정을 초기화하지 않고 서랍 안에 오류와 닫기만 · 자동 갱신 때 열린 서랍의 가로 스크롤·초점 그대로 · 알림(토스트)이 검색 창 위에도 보여요.
- **화면 — 시간·표·접근성** — 섞여 있던 시각 표시를 브라우저 시간대와 상관없이 한국 시간으로 · 1101~1279px 에서 30일 목록 표가 칸을 넘던 것·배지 두 줄 고침 ·
  다크 테마 흐린 글자 대비 4.5:1 이상 · 폰 보관처 서랍 터치 영역 44px · 랜덤값 워터마크를 작고 옅게.
- **화면 — 문구·빈 칸** — 히트맵 제목 '좋았던 날과 아쉬웠던 날' · 자금 흐름 지도 각주는 한 줄 + '자세히' · '오늘 무엇이 움직였나' 카드 높이 = 내용 ·
  평가 기록 없는 기타 자산은 전체 폭 · 긴 키 이름의 설명은 둘째 줄로 · 매매 습관에서 비교할 시간대가 하나뿐이면 '아직 부족해요'.
- **설정 화면 오류 문장** — '체인 목록을 읽지 못했어요: FileNotFoundError' 처럼 파이썬 예외 이름이 그대로 보이던 것을 원인과 할 일 문장으로 바꿨어요(종류는 tj-web 로그에만).
- **미매칭 수량** — 수량을 모르는 줄이 '0 DEGEN 보유'로 보이던 것을 수량 없이 'DEGEN 보유'로.
- **보낸 내역 빈 화면 문구** — 무엇을 기다리는지(첫 수집·화면 계산)와 오래 이어지면 확인할 곳(설정 › 상태 패널)을 적었어요.
- **상태 전송 줄임** — `/api/state` 는 요청의 `If-None-Match` 가 지금 버전과 같으면 304 를 돌려줘요(약한 ETag 비교 — `W/` 있든 없든).
  화면을 다시 열 때는 기기에 저장된 버전을 서버가 24시간(최대 6개) 기억해 차이(델타)만 보내요(종전 = 몇십 분 지나면 통째로).
- **빌드 경고** — 상태 패널 '웹 빌드 느림'(p95)에서 원장 재구축 중·교체 직후 빌드는 표본에서 빼요 · tj-web 줄에 빌드 방식 칩('빌드 별도 프로세스'·'빌드 웹 안 · 쉼 N분') ·
  경고 문턱 기본값 = 별도 프로세스 60초 · 웹 안 10초(`config.json` 의 `health.t.build_p95_warn_s` 를 적으면 그 값).
- **빌드 자식 교착** — fork 순간 다른 스레드가 SQLite 전역 잠금(메모리 통계)을 쥐고 있으면 자식이 영영 기다리던 것 → tj-web 이 SQLite 를 쓰기 전에 그 통계를 꺼서(리눅스 ·
  빌드 자식을 쓸 때만) 원인을 없애고, 그래도 걸리면 3초 만에 알아채고 다시 fork(3번까지 · 그래도 안 되면 웹 안에서) ·
  멈춤 판정 = CPU 와 디스크 읽기가 180초 동안 그대로일 때(종전 CPU 90초) · 자식이 실패하면 오류 내용(비밀값 가림)을 로그에 남겨요.
- **운영** — 지갑 이름·퍼프 덱스 주소를 바꿔도 화면 서버를 다시 켜지 않아요 · 화면 계산 전용 코어는 코어 4개 이상에서만(2~3개는 자식 프로세스만) ·
  `TJ_BUILD_PROC`(`auto`·`off`·`fork`)를 `.env`·`config.json` 의 `build_proc` 로도 · 리눅스 `tools/rotate_logs.sh` 크기 계산 고침(로그 정리는 pm2-logrotate 와 둘 중 하나만) ·
  `ecosystem.config.js` 재시작 간격 = 점점 늘림(2초부터) · 빠른 실패 상한 50 → 1000번.
- **체인 자동 끄기 안전장치** — 지난 7일 시세가 있던 코인이 지금만 시세가 없으면(시세 장애) 그 체인은 '값 모름'으로 두고 자동으로 끄지 않아요 ·
  자동으로 켠 체인은 켠 뒤 30일 동안 끄기 추천·자동 끄기에서 빠져요 · **설정 › 지갑 · 주소 › 체인별 조회**에 '추천 체인 자동으로 끄기' 스위치(기본 켬 · 재시작 없음).
- **계산·수집** — 업비트 거래 시작 전 가격: 입금 증명이 있어도 그 토큰 DEX 시세가 아직 없으면 같은 심볼 거래소 값은 2곳 이상이 서로 2배 안으로 맞을 때만(아니면 DEX 시세가 올 때까지 0) ·
  자금 흐름 추적에서 이더스캔이 그 체인을 요금제 미지원으로 답하면 7일 동안 노드로 읽고, 이어 읽을 때 겹친 이동은 한 번만 셉니다.
- **보안·연결** — 원장 경로에 `#`·`?`·`%` 가 있어도 열려요(SQLite 주소 인용) · QuickNode Base 키는 `base-mainnet` 엔드포인트만 받고 연결 시험은 먼저 체인 번호(`eth_chainId`)를 확인 ·
  비밀번호를 바꾸면 CSRF 토큰도 새로 만들어요(열려 있던 다른 탭은 새로고침).
- **config.json 도 본인만 읽게(0600)** — 증권사 연결(미검증 · 기본 꺼짐)의 비밀값(`app_secret`·`refresh_token` 등)이 `config.json` 의 `brokers` 칸에 들어가므로,
  `tools/setup.sh` 가 다시 실행될 때와 tj-web 이 켜질 때 `config.json` 권한이 600 보다 넓으면(그리고 내 파일이면) 600 으로 좁혀요. 설정 저장도 600 으로 써요.
- **데모(`bash tools/setup.sh --demo`)** — 선물 영수증(거래소 2곳 · 분할 청산 · 반전 체결 · 펀딩 — 합성 봉 차트), 설정 › 체인별 조회·확인 주기·수집 한계,
  보낸 내역, 보유 코인 '오늘 변동'·'7일 추이', '오늘 무엇이 움직였나', 코인마다 다른 가격 이력(타임머신)을 합성 데이터로 보여 줘요.
- **시험·CI** — GitHub Actions 가 Python 3.9 · 3.11 · 3.13 에서 전체 파일 문법 검사(`py_compile`)와 시험을 돌리고, HTTP 로그인 시험(쿠키 없이 401 · 다른 Host 421 ·
  CSRF 없이 403 · 연속 실패 잠금 429)을 더했어요.
- **문서** — README 목차, [고급 설정](docs/CONFIG.md#고급-설정)(환경변수·설정 키), 브라우저가 직접 부르는 외부 주소(글꼴·로고 · Cloudflare 분석), 자동 재구축 임시 사본 위치.

**English** — External review fixes (evening of 2026-10-08). Futures receipts: Binance closes now get prices (settlements matched to fills by the second) and OKX one-way (net) accounts get
price rows (the last 3 months are fetched once more); entry times follow the running position (partial closes; reversals and zero-PnL closes are
split only when prices reconcile); Bybit entries come from `/v5/execution/list` (one call per collector cycle, once back to 30 days before the first
Bybit settlement). The chart draws only the selected exchange with one ▲ per order; opening from an exchange line shows that exchange's totals;
KRW view sums each settlement; trade lines show exact amounts; symbol chips wrap (desktop) or scroll with faded edges (phone); non-ASCII symbols
and large moves (only a 10x gap is suspect) are kept. Screens: header tabs fold to a second line at 641–~950px, drawer errors stay in the drawer,
refreshes keep scroll and focus, toasts show above search, times follow KST regardless of the browser time zone, the 30-day list fits at 1101–1279px, dark-theme contrast, 44px touch
targets, a lighter watermark and clearer wording. Ops: `/api/state` answers 304 to a matching `If-None-Match` (weak ETag comparison) and reopening
the screen gets a delta (stored base versions kept 24h, up to 6); the build p95 warning skips ledger-rebuild builds, shows the build mode and defaults
to 60s (child process) / 10s (in-process) unless `health.t.build_p95_warn_s` is set; SQLite memory statistics are switched off before fork (Linux, build child on) so a
build child can no longer inherit a held SQLite lock, and a stuck child is still detected in 3s and forked again; chain auto-off skips chains whose prices are only temporarily missing, gives auto-enabled chains 30 days of grace and has an
on/off switch; pre-listing prices without the token's DEX price need 2 exchanges agreeing within 2x; flow tracing falls back to nodes when Etherscan does not support a chain;
SQLite paths are URI-quoted; QuickNode keys are checked (`base-mainnet`, `eth_chainId`); changing the password rotates the CSRF token;
`config.json` is kept at 0600; the demo shows futures receipts, chain settings, outflows and price history; CI runs on Python 3.9/3.11/3.13 with
HTTP login tests.

## 2026-10-08

**선물 영수증 · 화면 계산 분리(리눅스) · 업비트 거래 시작 전 가격 · 디자인 정리**

- **선물 영수증** — 일별 기록의 '그날 실현 기여'·'그날의 기록'에서 선물 정산 줄을 누르면(선물만 있는 날은 '최고의 날' 칩도) 차익 영수증 같은 서랍이 열려요:
  그날 합·거래소·종목 칩, 실제 시세 차트 위의 진입(▲ 롱 · ▼ 숏)·청산(●) 점과 평균 진입가, 청산 목록·수수료·펀딩. 그날 합은 지금 선물 실현과 똑같아요(정산 금액은 거래소 원본 그대로).
  진입·청산 가격은 **바이낸스·바이빗·OKX·Hyperliquid** 만 — 수집기가 정산을 받는 같은 응답에서 가격을 옆 파일 `state/futures_px_<거래소>.json`(표시 전용 · 지워도 다시 생김)에 남기고,
  바이낸스만 선물 체결 내역을 조금 더 불러요(공표 한도 80% 안). 바이낸스·OKX 의 3개월 넘은 날과 그 밖의 퍼프 덱스(dYdX·Lighter·GMX·Jupiter·Pacifica)는 정산 금액만 보여 주고,
  게이트·쿠코인 선물은 종전처럼 받지 않아요. 업데이트 뒤 가격은 수집기 두 주기(약 20~30분) 안에 채워져요.
- **업비트 거래 시작 전 코인도 평가** — 업비트에 들어왔지만 업비트 원화·BTC·USDT 마켓이 아직 없는 코인은 전에는 0원이었어요. 이제
  입출금 txid 로 같은 토큰(같은 체인·컨트랙트)임이 확인되면 그 토큰을 확인한 다른 거래소 시세 → 같은 심볼 다른 거래소 시세(그 토큰 DEX 시세와 2배 넘게 다르면 버림) → 그 토큰 DEX 시세 순으로 평가하고,
  체인 기록 없이 업비트가 직접 넣어 준 코인(업비트 안 스왑·에어드랍)은 같은 심볼 거래소 시세가 2곳 이상에서 서로 2배 안으로 맞을 때만 평가해요(아니면 종전대로 0).
  보유 코인 펼침의 가격 출처에 **'거래 시작 전'**(증명 없이 평가하면 '· N곳 일치')이 붙고, 업비트 거래가 시작되면(마켓 목록 1시간마다 확인) 업비트 시세로 돌아가요.
  지난날 마감 기록은 바꾸지 않고 오늘부터 반영해요.
- **화면 계산은 따로(리눅스)** — 리눅스에서 코어가 2개 이상이면 화면 계산(빌드)을 tj-web 의 자식 프로세스에서 하고, 가장 높은 번호 코어 1개를 그 계산 전용으로 비워 둬요
  (다른 tj 유닛은 나머지 코어). 계산이 도는 동안에도 화면 응답·배경 작업이 느려지지 않아요. 자식이 실패하면(남은 램 1.2GB 미만·멈춤·시간 초과) 그 회차는 종전처럼
  tj-web 안에서 계산하고, 3번 연속 실패하면 1시간 동안 자식을 쓰지 않아요. 맥·코어 1개는 종전 그대로입니다. 끄려면 환경변수 `TJ_BUILD_PROC=off`
  (예: `TJ_BUILD_PROC=off pm2 restart ecosystem.config.js --update-env` — 코어 배분은 유닛이 켜질 때 정해져 전부 다시 켜야 해요).

**English** — Futures receipts: click a futures settlement line in the daily records to open a drawer with that day's total (identical
to realized futures PnL), per-symbol chips, entry ▲▼ / exit ● dots on a real price chart, closes, fees and funding; entry/exit prices come from
Binance, Bybit, OKX and Hyperliquid (stored display-only in `state/futures_px_<exchange>.json`; Binance/OKX days older than 3 months and other perp
DEXes show settlement amounts only). Coins sitting on Upbit before Upbit lists them (no KRW/BTC/USDT market yet) are no longer valued at 0: a token
proven by deposit/withdrawal txid uses the proving exchange, then the same symbol on other exchanges (dropped if 2x off the token's DEX price),
then that DEX price; Upbit-credited coins without a chain record need 2+ exchanges agreeing within 2x. The price source reads '거래 시작 전'
(pre-listing), past closed days are not rewritten, and Upbit's own price takes over once the market opens.

## 2026-10-07

**체인 켜기·끄기 · 보관처 상세 · RPC 대체 · API 하루 몫 · 리눅스 서버 안내**

- **보관처 상세** — 대시보드 '보관처별' 줄을 누르면 오른쪽에서 서랍이 열려요(폰은 아래에서 올라오는 시트). 체인별 비중을 누르면 탐색기, 주소는 바로 복사,
  코인을 누르면 보유표로 가요. 거래소는 체인 대신 '잔고 기준 N분 전'을 보여 주고, 계산이 안 된 칸은 '—' 로 둡니다.
- **매수 점 거슬러 찾기** — 경유 지갑·브릿지를 거쳐 거래소로 들어가 판 코인도 원가를 처음 산 매수(스왑)까지 따라가 영수증 차트에 점을 찍어요.
  매수 시각을 알 수 없는 몫은 시각을 지어내지 않고, 들어온 시각에 **입금 마름모**(원가 단가·원가 규칙)로 따로 표시합니다.
- **보낸 내역 전송 목록** — 한 주소의 전송은 최근 200건을 최신순으로 보여 주고(앞 8줄 + 50건씩 더 보기), 그보다 오래된 것은
  '그 전 N건은 목록에서 생략'으로 알려요. 합계·건수는 늘 전 건 기준입니다.
- **지갑을 넣으면 알아서 수집** — `pm2 start ecosystem.config.js` 로 띄운 설치는 설정에서 지갑을 추가하면 수집기가 스스로 다시 시작해요
  (손으로 `pm2 restart` 할 필요 없음). 다시 시작하기 전까지는 지갑 줄·보낸 내역에 **'곧 자동으로 수집 시작'** 이 보입니다.
- **확인 주기(계단)** — 오래 안 쓴 주소는 덜 자주 확인해요(지금 주기 → 조금 느리게 → 1시간마다 → 6시간마다 → 6개월 넘게 쉬면 하루 1회).
  쉬는 주소는 탐색기를 부르지 않고 공개 RPC 로 잔고·nonce 만 보다가, 바뀌거나 내가 보내면 바로 지금 주기로 돌아와요.
  기록이 하나도 없는 **빈 지갑**은 하루 한 번만 봅니다. 주소별 칩과 '지금 확인' 단추는 **설정 › 지갑 · 주소**에서.
- **옛 기록 먼저, 새 거래 확인은 남겨 둔 몫으로** — 이더스캔 키의 하루 몫(공표 한도의 80%)에서 새 거래 확인 몫(하루의 약 10~70% — 실제 사용량으로 정함)을
  먼저 떼어 두고, 나머지는 옛 기록 채우기가 UTC 0시(한국 오전 9시)부터 바로 몰아서 써요. 그래서 **처음 넣은 지갑은 옛 기록부터 채우고,
  첫날은 새 거래 확인이 평소보다 늦을 수 있어요**(그동안 새 거래 확인은 하루 몫의 약 10% 안에서 고르게). 옛 기록이 다 채워지면 새 거래 확인이 하루 몫을 그대로 씁니다.
  하루 총량은 그대로라 한도를 넘지 않고, 오늘 옛 기록 몫을 다 쓴 뒤 넣은 지갑은 주로 다음 오전 9시부터 채워요.
- **체인 끄기** — **설정 › 지갑 · 주소 › 체인별 조회**에서 안 쓰는 체인의 스위치를 끄면 그 체인의 조회·입출금 알림이 멈춰 컴퓨터와 API 한도를 아껴요.
  지금까지 기록은 그대로 남고(잔고는 끈 때 값에서 멈춤), 다시 켜면 끈 날부터 빠진 기간을 이어 받아요.
  그 체인에서 보낸 거래가 지갑마다 10번 이하면 **'끄는 걸 추천해요'** 로 강조하고 끄면 줄어드는 하루 호출 수를 보여 줘요. 다만 모르는 지갑(확인 전·점검 실패)이
  하나라도 있거나, 최근 30일 안에 보낸 거래가 있거나, 옛 기록을 채우는 중이면 추천하지 않아요. 잔고가 $100 넘게 남아 있으면 추천 옆에 같이 적어 둡니다.
  BSC·Solana(따로 도는 수집기)와 일부 체인은 아직 이 스위치로 못 꺼요(줄에 이유 표시).
  **추천 체인은 기본으로 꺼져요** — '끄는 걸 추천해요' 조건에 맞고 그 체인에 든 값(시세 있는 코인 + LP + NFT)이 소액 기준(최대 $100) 이하이면, 기초 잔고 대조가 끝난 뒤
  활동 점검 때 알아서 끄고 텔레그램으로 한 줄 알려요. 손으로 다시 켠 체인은 다시 자동으로 끄지 않고, 꺼 둔 체인에 새 잔고·활동이 생기면 미추적 체인 점검이 알려요.
- **확인 주기가 지갑 수에 맞춰 늘어나요** — 지갑이 많아 이더스캔 하루 몫(공표 한도의 80% — 같은 키를 쓰는 체인 합산)을 넘을 것 같으면 기본 확인 주기를 지갑 수에 맞춰 늘려요(최대 15분 —
  그래도 넘치면 종전처럼 간격을 더 벌려요). 지갑 칩의 **'M분마다'** 와 'Solana 지갑 N개라 M분마다 확인해요' 같은 줄로 보여 주고, 체인별 조회 카드에도 같은 주기가 나와요.
- **Solana 도 하루 몫** — 헬리우스 무료 월 한도(100만 크레딧)의 80% 를 30일로 나눈 하루 몫(약 2만 6천) 안에 들도록 Solana 기본 주기를 맞춰요.
  이더스캔과 같이 새 거래 확인 몫을 먼저 떼어 두고(옛 기록을 채우는 동안은 하루 몫의 10% — `sol.helius_head_min_pct` 로 1~70 사이 조절) 나머지는 UTC 0시부터 옛 기록에 먼저 써요.
  오늘 옛 기록 몫을 다 쓴 뒤 넣은 Solana 지갑은 '옛 기록 차례 대기'로 보이다가 다음 오전 9시에 시작합니다. 옛 기록이 다 채워지면 새 거래 확인이 하루 몫을 그대로 써요.
  유료 플랜이면 `config.json` 의 `sol.helius_monthly_credits` 에 월 크레딧을 적으세요.
- **Solana 새 거래는 공개 노드 먼저** — Solana 새 거래 확인은 무료 공개 노드(publicnode)를 먼저 쓰고, 응답이 없거나 이상하면 같은 요청을 헬리우스로 다시 보내요
  (헬리우스는 옛 기록 채우기와 백업에 씀). 공개 노드는 최근 약 18시간만 보관해서, 마지막 확인이 12시간보다 오래된 주소(수집기를 오래 껐다 켠 경우 등)와
  처음 넣은 지갑은 헬리우스로 확인하고, 헬리우스가 주기적으로 공개 노드 결과를 대조해 빠진 거래가 있으면 다시 받아요.
  헬리우스 하루 몫을 다 쓴 날은 그날 끝(UTC 자정 = 한국 오전 9시)까지 헬리우스를 쉬고 공개 노드로 이어 받아요(새 거래 = publicnode · 옛 기록 = Solana 공식 공개 노드,
  공표 한도의 80% 안 · 새 지갑 첫 백필은 다음 날). 끄려면 `sol.head_rpc`·`sol.archive_rpc` 를 `""` 로 — 그러면 종전처럼 헬리우스만 쓰고, 하루 몫이 다 차면 그날 끝까지 쉬어요.
- **옛 기록 채우는 동안** — 첫 백필·옛 기록 채우기가 남은 주소도 새 거래 확인은 계단 규칙을 따라요. 최근 거래가 보이는 주소는 지금 주기로 계속 확인하고,
  오래 쉰 주소는 새 거래 확인은 쉬면서 옛 기록만 마저 채워요(하루 몫 안에서).
- **빈 지갑은 먼저 가볍게** — nonce·잔고가 0 인 EVM 지갑은 긴 옛 기록 채우기 전에 토큰 이동이 하나라도 있었는지 한 번만 가볍게 물어봐요.
  하나도 없으면 **빈 지갑**으로 두고 활동은 하루 한 번만 확인합니다(토큰 입금만 오면 주 1회 확인 때 기록 — 시각·수량은 그대로).
- **EVM 지갑이면 Etherscan 키 필수** — EVM 지갑을 등록했는데 Etherscan 키가 없으면 설정 마법사(지갑·키·마지막 요약)·키 카드('EVM 필수')·상태 패널에
  '이더스캔 키가 필요해요(무료)'가 떠요. 경고만 하고 막지는 않아요 — 키가 없어도 공개 탐색기·RPC 로 계속 받지만 느리거나, 공개 탐색기가 막힌 체인
  (Arbitrum·Polygon 등)은 늦게 기록될 수 있어요(기록이 사라지지는 않아요). 이 안내는 텔레그램으로 보내지 않습니다.
- **Base 는 공개 RPC 로 직접** — Base 블록스카웃 API 가 막혀 있어(2026-10 기준 403 · 무료 이더스캔 키도 Base 는 지원하지 않음) Base 는 탐색기 없이
  공개 RPC 노드에서 직접 읽어요. 이미 쓰던 설치는 재시작하면 지금까지 받은 위치를 그대로 이어받아 새 거래는 바로 보이고, 아직 못 받은 옛 구간과
  내부 ETH 이동(스왑으로 받은 ETH·브리지 입금 등)은 뒤에서 채워요(지갑·기간에 따라 몇 시간까지). 지갑의 잔고·nonce 를 대조해 로그가 남지 않는 ETH 이동도 찾고,
  옛 구간을 다 채우기 전까지는 새로 넣은 Base 지갑의 기초 잔고 확인이 늦어질 수 있어요. 블록스카웃으로 되돌리려면 `config.json` 의 `chains.base.discovery` 를 `"explorer"` 로.
- **탐색기가 막히면 공개 RPC 로 자동 대체** — 이더스캔·블록스카웃이 막히면(하루 한도를 다 씀·키 거부·연속 실패·403·색인 정지, 또는 하루 몫 때문에
  새 거래 확인이 20분 넘게 밀림) 그 체인만 받던 위치에서 이어 공개 RPC 로 받아요(하루 한도·키 문제일 때 그 체인 블록스카웃이 살아 있으면 종전처럼 블록스카웃 먼저).
  설정은 필요 없어요 — 체인마다 키 없는 공개 노드 목록이 들어 있어요. 탐색기가 살아나면 알아서 돌아가요(블록스카웃은 15분마다·이더스캔은 1시간마다 한 번 시험,
  하루 한도는 쉼이 끝나면 · 깜빡이지 않게 최소 30분은 머묾). 상태 패널과 확인 주기 카드에 '이더스캔 대신 RPC 로 확인 중(이유)'이 한 줄 보이고,
  텔레그램으로는 보내지 않아요. 하루·월 한도가 있는 무료 노드는 공표 한도의 80% 까지만 세어 쓰고, 넘으면 그 노드는 UTC 자정까지 쉬고 다음 노드로 넘어가요.
  끄려면 `config.json` 에 `"rpc_fallback": false`(전체) 또는 `chains.<체인>.rpc_fallback: false`(그 체인만).
- **빗썸 원화 입출금도 일별 기록에** — 은행 ↔ 빗썸 원화 입출금이 그날 기록·그날 카드 '입출금'(순유입)·자산 변동 분해에 들어가요(전에는 업비트만). [README › 일별 기록](docs/FEATURES.md#일별-기록--그날-카드--m월-한눈에)
- **미매칭엔 할 일만** — '기초 잔고 대사 완료' 같은 알림이 미매칭 › 기타 보류에 빈 '—' 줄로 쌓이던 것을 뺐어요(미매칭 배지 수도 그만큼 줄어요).

**English** — A holding-place drawer (share of total, coin ring, 30-day in/out, chains, coins), buy dots traced back through
hop wallets and bridges to the original swap (unknown buy times shown as a separate "deposit" diamond, never invented), outflow
transfer lists of the latest 200 with "show more", automatic collector restart after adding a wallet ("곧 자동으로 수집 시작"),
tiered per-address check intervals (idle addresses checked less, empty wallets once a day) and an Etherscan daily budget (80% cap) that
keeps a share for new-transaction checks and spends the rest on old history from 00:00 UTC.
Also new: per-chain on/off switches in Settings › 지갑 · 주소 (a chain is suggested for switching off when every wallet sent 10 or fewer
transactions there and nothing is unknown, recent or still backfilling; switching it back on resumes from the day it was turned off),
base check intervals that grow with the number of wallets so the daily budget holds, a Helius daily budget for Solana (80% of the free
monthly credits spread over 30 days, old history first as well — `sol.helius_head_min_pct`; set `sol.helius_monthly_credits` for paid plans),
new-transaction checks that keep following the tiers while old history is still being filled, and a one-call probe for empty wallets.
Solana new transactions are checked on a free public node (publicnode) first, with Helius as backup and periodic cross-check; when the
Helius daily share is used up, public nodes carry on until the UTC day ends (`sol.head_rpc` / `sol.archive_rpc` = `""` to disable).
Base is now read directly from public RPC nodes (its Blockscout API is blocked; existing installs keep their position and fill older
history in the background), and any EVM chain whose Etherscan/Blockscout is blocked or out of quota switches to public RPC automatically
and back when the explorer recovers (`rpc_fallback: false` to disable). Bithumb KRW bank deposits/withdrawals now show up in the daily
records, net flow and breakdown, and "baseline reconciled" notices no longer fill the unmatched list.
Chains that meet the switch-off suggestion and hold $100 or less (priced coins + LP + NFT) are now switched off automatically after their baseline
reconciliation (one Telegram line; a chain you switch back on stays on). Optional node keys (`TJ_NODEREAL_KEY`, `TJ_ANKR_KEY`,
`TJ_QUICKNODE_BSC_KEY`, `TJ_QUICKNODE_BASE_KEY` — Settings › 연결·키) add archive nodes for BNB Chain/Base history (free keys at 80% of the
monthly quota, paid at a usage share, 10% by default), and the Rabby portfolio check only covers EVM wallets worth $1,000+ (`rabby.min_wallet_usd`).

## 2026-10-05

- **전체 검색**(⌘K · /)과 **내 매매 돌아보기**(타임머신 · 자금 흐름 지도 · 팔기 전 미리보기 · 올해 결산 · 계획 지키기 점수 · 매매 습관 · 하루 실현 잔디 · BTC 비교선 · 안 팔았다면) —
  README [화면 미리보기 › 새로 생긴 것](docs/SCREENS.md#새로-생긴-것--내-매매를-다르게-보는-화면).
- **텔레그램 알림 3등급**(즉시 · 하루 요약 · 시스템) — README [텔레그램 알림 설정](docs/FEATURES.md#텔레그램-알림-설정).
- 수집기·원장 단단하게, 비공개 원격 접속 흔적 제거, 로그인·프록시 경로 강화(로그인 기본 켜짐 — README '처음 시작하면 이것부터'의 업데이트 안내).
- 첫 공개판.

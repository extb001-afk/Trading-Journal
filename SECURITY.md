# 보안 문제 알리기

tj-bot 에서 보안 문제를 찾았다면 **공개 이슈로 올리지 말고** 저장소의 **Security › Report a vulnerability**(GitHub 비공개 보고)로 알려 주세요.

- 적어 주세요: 영향을 받는 기능·파일, 재현 순서, 예상 피해(예: 다른 사용자가 키를 읽을 수 있음).
- 넣지 마세요: 실제 API 키·비밀번호·지갑 주소·잔고·`state/` 파일 내용. 재현은 데모(`bash tools/setup.sh --demo`)나 합성 값으로 충분합니다.
- 범위: 이 저장소의 코드(웹 화면·설정 API·수집기·도구). 거래소·탐색기 등 바깥 서비스 자체의 문제는 각 서비스에 알려 주세요.

설계 원칙(README '보안 · 데이터'): 조회 전용(주문·출금 코드 없음) · 웹은 127.0.0.1 기본 + 로그인 · 비밀값은 `.env`(600)에만 · 원장 내용은 밖으로 보내지 않음.

# Reporting a vulnerability

Please do **not** open a public issue. Use **Security › Report a vulnerability** (GitHub private reporting) instead.
Include the affected feature, reproduction steps and impact. Do not include real API keys, passwords, wallet addresses or balances — the demo mode is enough to reproduce.

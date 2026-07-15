# 역매공파 스윙 자동매매 봇 (미국주식 / KIS API)

주식단테의 "역매공파" 기법(역배열 → 매집봉 → 공구리 → 파란점선/112일선 근접)을 바탕으로
한 스윙 매매 신호를 생성하고, 한국투자증권(KIS Developers) REST API로 미국주식 자동매매를
수행하는 프로그램입니다. 익절 +5% / 손절 -5%를 기본 리스크 규칙으로 사용합니다.

> 원 기법은 유튜브/블로그 등에서 설명된 정성적 기법입니다. 이 프로그램은 이를 정량적으로
> 근사화한 것이며, 원저자의 실제 판단 기준과 다를 수 있습니다. **반드시 백테스트로
> 검증 후 사용하세요.**

## 왜 키움이 아니라 KIS(한국투자증권) API인가

조사 결과 키움증권의 최신 REST API(openapi.kiwoom.com)는 국내주식과 해외파생(선물/옵션)
위주로 공개 문서화되어 있고, 해외주식(미국주식) 자동매매용 TR은 공개 문서에서 확인되지
않았습니다. 반면 KIS Developers(apiportal.koreainvestment.com)는 해외주식 주문/잔고/시세
조회 API가 잘 문서화되어 있어 이를 채택했습니다. (사용자 확인 후 KIS로 결정)

## 설치

```bash
cd trading_bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 값 채워넣기
```

`.env`에 KIS Developers에서 발급받은 `KIS_APP_KEY`, `KIS_APP_SECRET`, 계좌번호를 입력합니다.
`KIS_MODE=paper`(모의투자)로 시작하는 것을 강력히 권장합니다.

## 백테스트 (실거래 전 필수)

`date, open, high, low, close, volume` 컬럼을 가진 CSV를 종목코드 이름으로 저장한 뒤:

```bash
python -m trading_bot.main backtest --csv-dir ./data --output trades.csv
```

`trading_bot/config.py`의 `StrategyConfig` 파라미터(매집봉 거래량 배율, 공구리 허용 오차,
볼린저 스퀴즈 기준 등)를 `.env`로 조정하며 결과를 비교하세요.

## 모의투자 실행

```bash
python -m trading_bot.main trade          # 무한 루프 (기본 5분 주기)
python -m trading_bot.main trade --once    # 1회만 실행 (cron 등에서 사용)
```

## 실전투자로 전환하기 전 체크리스트

1. 백테스트 결과(승률, 평균수익률, MDD)가 납득할 만한 수준인지 확인
2. 최소 수 주~수개월 모의투자로 실거래 신호와 체결 로직을 검증
3. `.env`에서 `KIS_MODE=real`, `CONFIRM_REAL_TRADING=yes`로 변경
   (이 두 값을 명시적으로 바꾸지 않으면 프로그램이 실전 주문을 거부합니다)
4. KIS Developers 공식 문서(https://apiportal.koreainvestment.com)에서
   `trading_bot/kis_client.py`의 TR ID/엔드포인트/응답 필드명이 최신 스펙과
   일치하는지 재확인 (특히 `dailyprice`, `price-detail` 응답 필드는 자동 조사로
   완전히 검증하지 못했으므로 실거래 전 직접 호출해 필드명을 확인할 것)

## 리스크 안내

- 이 프로그램은 실제 자금 손실을 유발할 수 있습니다. 자동매매 알고리즘의 신호가 항상
  옳다는 보장은 없습니다.
- 익절 +5% / 손절 -5%는 고정 비율이며 슬리피지, 갭 발생 시 실제 체결가는 다를 수 있습니다.
- API 키/시크릿은 `.env`에만 보관하고 절대 커밋하지 마세요 (`.gitignore`에 이미 포함됨).
- 미국주식 시장 시간(한국시간 기준 야간)에 무인 실행되므로, 초기에는 소액/모의투자로
  충분히 안정성을 검증한 뒤 점진적으로 비중을 늘리는 것을 권장합니다.

## 구조

```
trading_bot/
  config.py      - .env 기반 설정 (KIS 인증, 전략 파라미터, 리스크 규칙)
  kis_client.py  - KIS REST API 클라이언트 (토큰, 시세, 주문, 잔고)
  indicators.py  - 이동평균/볼린저밴드/거래량평균
  strategy.py    - 역매공파 신호 생성 로직
  portfolio.py   - 보유 포지션 상태 저장 및 익절/손절 판단
  data.py        - 과거 시세 로딩 (CSV / KIS API)
  backtest.py    - 백테스트 엔진
  live.py        - 실시간(모의/실전) 매매 루프
  main.py        - CLI
```

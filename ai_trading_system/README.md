# AI 트레이딩 시스템 (바이낸스 선물)

명령서에 따라 구현한 듀얼 전략 자동매매 시스템입니다.
**반드시 `backtest` → `dry_run` → `testnet` → (충분히 검증 후) `live` 순서로만 진행하세요.**

## 1. 무엇이 들어있나

| 파일 | 역할 |
|---|---|
| `config.py` | 레버리지, R:R, 손실 한도 등 모든 파라미터 |
| `indicators.py` | ADX, 볼린저밴드, RSI, 다이버전스/스윕 감지 |
| `regime_scanner.py` | 1단계: 상위 30개 코인 스캔 후 횡보/추세 판별 |
| `strategies/grid_strategy.py` | 2단계-A: 횡보장 중립 그리드 (3일 박스, 1% 이탈 시 강제 종료) |
| `strategies/trend_strategy.py` | 2단계-B: 추세장 스윕+다이버전스 진입, SL/TP 1:2 고정 |
| `risk_manager.py` | 3단계: 5배 격리 레버리지, R:R 1:2, 일일 -3% 손실 시 24시간 잠금 |
| `exchange_client.py` | 바이낸스 선물 연동 (`dry_run`/`testnet`/`live` 3모드) |
| `backtester.py` | 과거 데이터로 두 전략을 그대로 시뮬레이션 (API 키 불필요) |
| `live_trader.py` | 스캐너+전략+리스크 관리를 묶은 실행 루프 |
| `main.py` | CLI (`backtest`, `run`) |
| `Dockerfile`, `docker-compose.yml` | VPS에 Docker로 상시 배포할 때 사용 |
| `deploy/trading-bot.service` | Docker 없이 systemd로 상시 배포할 때 사용 |

## 2. 설치

```bash
cd ai_trading_system
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 이후 .env를 직접 채워넣으세요 (git에는 안 올라갑니다)
```

## 3. 바이낸스 API 키 발급

### 테스트넷 키 (모의투자용, 먼저 이걸로)
1. https://testnet.binancefuture.com 접속 → GitHub 계정으로 로그인
2. 로그인하면 API Key/Secret이 화면에 바로 표시됩니다
3. 가상 자금(기본 10,000 USDT 등)이 자동 지급되어 실제 돈 없이 테스트 가능
4. `.env`에 `BINANCE_API_KEY`, `BINANCE_API_SECRET` 입력, `TRADING_MODE=testnet`

### 실거래 키 (백테스트+테스트넷 충분히 검증한 뒤에만)
1. 바이낸스 로그인 → 우측 상단 프로필 → **API Management**
2. **Create API** → 라벨 입력 → 이메일/OTP 인증
3. 권한 설정이 가장 중요합니다:
   - ✅ Enable Reading
   - ✅ Enable Futures
   - ❌ **Enable Withdrawals는 절대 켜지 마세요** (봇 키가 유출돼도 출금은 불가능하도록)
4. 가능하면 IP 접근 제한(IP Access Restriction)을 걸어두세요
5. 키는 재발급 전까지 다시 볼 수 없으니 안전하게 보관하세요

## 4. 사용법

### 4-1. 백테스트 (API 키 불필요, 공개 시세만 사용)
```bash
python main.py backtest --symbols BTC/USDT:USDT ETH/USDT:USDT --days 60
```
승률, 총 수익률, 최대 낙폭(MDD), 거래 건수를 출력합니다. **이 결과가 만족스럽지 않다면 절대 다음 단계로 넘어가지 마세요.**

### 4-2. Dry-run (실시간 시세 + 가상 잔고, 주문은 거래소에 전송되지 않음)
```bash
# .env: TRADING_MODE=dry_run
python main.py run
```

### 4-3. 테스트넷 (실시간 시세 + 실제 주문, 가짜 돈)
```bash
# .env: TRADING_MODE=testnet, BINANCE_API_KEY/SECRET = 테스트넷 키
python main.py run
```
최소 며칠간 지켜보면서 그리드 셋업, 진입/청산, 일일 손실 잠금이 의도대로 동작하는지 확인하세요.

### 4-4. 실거래 (실제 자금)
```bash
# .env: TRADING_MODE=live, BINANCE_API_KEY/SECRET = 실거래 키
#       LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_THE_RISK
python main.py run
```
`LIVE_TRADING_CONFIRMATION`을 정확히 저 문구로 설정하지 않으면 실거래 모드는 **시작 자체가 거부**됩니다 (`exchange_client.py`의 안전장치).

## 5. 24시간 상시 운영 환경 구축 (VPS/서버)

`python main.py run`은 무한 루프로 계속 떠 있어야 하는 프로그램입니다. 로컬 PC를 계속 켜두거나, 저렴한 VPS(예: Vultr, DigitalOcean, Oracle Cloud 무료 티어, 네이버클라우드 등 아무 곳이나 상관없습니다 — Ubuntu 22.04 기준으로 작성) 하나를 띄워서 그 위에서 돌리는 것을 권장합니다.

**중요**: 일일 -3% 손실 잠금 상태는 `state/risk_state.json`에 저장되어 프로세스가 죽었다가 재시작돼도 유지됩니다. 이 파일을 지우거나 손대지 마세요 — 지우면 잠금이 풀린 채로 재시작될 수 있습니다.

### 5-1. Docker로 배포 (권장)
```bash
# 서버에 git clone 후
cd ai_trading_system
cp .env.example .env   # 값 채우기 (TRADING_MODE=dry_run 로 먼저 시작)
docker compose up -d --build
docker compose logs -f          # 실시간 로그 확인
docker compose restart          # 코드/설정 변경 후 재시작
docker compose down             # 완전히 중지 (포지션은 자동으로 청산되지 않으니, 열려있다면 먼저 손으로 정리)
```
`state/` 폴더가 호스트에 마운트되어 있어서 컨테이너를 재생성해도 잠금 상태가 유지됩니다.

### 5-2. systemd로 배포 (Docker 없이)
```bash
sudo useradd -r -s /usr/sbin/nologin trading-bot
sudo mkdir -p /opt/ai_trading_system
sudo cp -r ai_trading_system/* /opt/ai_trading_system/
cd /opt/ai_trading_system
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env   # 값 채우기
sudo chown -R trading-bot:trading-bot /opt/ai_trading_system

sudo cp deploy/trading-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-bot

sudo systemctl status trading-bot     # 상태 확인
journalctl -u trading-bot -f          # 실시간 로그
sudo systemctl stop trading-bot       # 중지
```
서버가 재부팅되거나 프로세스가 죽어도 `Restart=on-failure`로 자동 재시작됩니다 (단, 10분 내 5번 이상 죽으면 재시도를 멈춥니다 — 뭔가 근본적으로 잘못됐다는 뜻이니 로그를 확인하세요).

### 5-3. 운영 체크리스트
- 처음엔 반드시 `TRADING_MODE=dry_run`으로 며칠 띄워서 스캐너/그리드/추세 로직이 로그상 정상적으로 동작하는지 확인
- 그다음 `testnet`으로 전환해 실제 주문 체결까지 확인
- 로그를 주기적으로 확인할 방법을 마련하세요 (Docker는 `docker compose logs`, systemd는 `journalctl`). 알림까지 원하면 로그를 텔레그램/슬랙 웹훅으로 보내는 기능을 추가로 붙일 수 있습니다.
- `live`로 전환하기 전, `.env`의 API 키에 출금 권한이 없는지 다시 한번 확인하세요.

## 6. 명령서 규칙이 코드에 어떻게 반영됐는지

- **시장 필터링**: `regime_scanner.py` — 1h/4h ADX < 25 또는 볼린저밴드 스퀴즈 → 횡보, ADX ≥ 25(양쪽 타임프레임) + 밴드 확장 + 거래량 증가 → 추세로 분류. 애매하면 `unclear`로 두고 아무 전략도 실행하지 않습니다.
- **중립 그리드**: `strategies/grid_strategy.py` — 최근 3일 고저를 박스로 잡고 그 안에 매수/매도 지정가를 균등 배치, 체결될 때마다 반대쪽 한 칸 위/아래에 재배치(`rebalance`)합니다. 종가 기준 박스 상/하단 1% 이탈 시 전량 시장가 청산 + 그리드 종료.
- **스윕+다이버전스**: `strategies/trend_strategy.py` — 15분봉에서 직전 저점을 깨고 종가가 다시 위로 올라오며 RSI 상승 다이버전스 확인 시 롱, 직전 고점을 돌파했다가 위꼬리 음봉으로 되돌리고 OI 하락 + RSI 하락 다이버전스 확인 시 숏.
- **자금 관리**: `risk_manager.py` — 레버리지 5배 고정 상한 + ISOLATED 마진만 허용(그 외 값이면 예외 발생), TP는 SL 폭의 정확히 2배, 당일 자산 대비 -3% 도달 시 전량 청산 + 24시간 주문 잠금.

## 7. 이 세션에서 확인한 것 / 못한 것

- 지표(ADX/볼린저/RSI/다이버전스), 리스크 관리자, 그리드 체결 매칭 로직, 백테스트 루프 전체를 **합성(가짜) 시세 데이터로 끝까지 실행해 정상 동작을 확인**했습니다 (오류 없이 루프 완주, 그리드 체결 손익 정상 누적, 일일 손실 잠금 정상 트리거).
- 이 원격 실행 환경은 조직 네트워크 정책상 `fapi.binance.com` 접속이 차단되어 있어 **실제 바이낸스 시세로 백테스트/실행을 검증하지 못했습니다.** 사용자의 로컬 환경이나 바이낸스 API 접근이 가능한 서버에서 먼저 `python main.py backtest`를 돌려서 정상 동작을 재확인해주세요.
- `testnet`/`live` 모드의 실제 주문 전송 코드(`STOP_MARKET`, `TAKE_PROFIT_MARKET` 등)는 바이낸스 공식 문서 기준으로 작성했지만, 실제 계정으로 체결까지 확인하지는 못했습니다. **반드시 테스트넷에서 먼저 실제 체결을 확인**하세요.
- "시가총액 상위 30개"는 코인마켓캡 등 별도 시가총액 데이터가 아니라 **바이낸스 선물 24시간 거래대금 상위 30개**로 구현했습니다 (실무에서 흔히 쓰는 근사치입니다). 진짜 시가총액 기준이 필요하면 CoinGecko API 연동을 추가해야 합니다.
- OI(미체결약정) 이력은 바이낸스가 최근 약 30일치만 제공하므로, 오래된 과거 구간 백테스트에서는 숏 신호의 OI 확인이 생략됩니다.
- "선물 그리드"는 바이낸스의 공식 그리드매매 전략 API가 아니라, 지정가 주문을 격자로 깔고 체결마다 재배치하는 방식으로 직접 구현했습니다 (공식 그리드 전략 API는 계정 등급 제한이 있고 ccxt로 범용 지원되지 않습니다).
- 일일 손실 잠금 상태의 재시작 내구성(`risk_manager.py`의 `save()`/`load()`)은 합성 데이터로 검증했습니다: 잠금이 걸린 상태에서 새 `RiskManager` 인스턴스를 만들어도(=프로세스 재시작 시뮬레이션) 잠금이 그대로 유지되고, 24시간 후 정상적으로 풀리는 것을 확인했습니다.
- `Dockerfile`/`docker-compose.yml`은 이 샌드박스에 Docker 데몬이 떠 있지 않아 실제 빌드/실행까지는 확인하지 못했습니다 (표준 Python 이미지 패턴이며 `python main.py run` 자체는 별도로 정상 기동을 확인했습니다). 서버에 배포한 뒤 `docker compose up -d --build` 후 `docker compose logs -f`로 정상 기동을 꼭 확인하세요.

## 8. 위험 고지

레버리지 선물 자동매매는 원금 전액 손실 및 그 이상의 위험을 포함합니다. 이 코드는 참고용 구현체이며 수익을 보장하지 않습니다. 반드시 감당 가능한 소액으로, 백테스트와 테스트넷 검증을 충분히 거친 뒤에만 실거래를 고려하세요.

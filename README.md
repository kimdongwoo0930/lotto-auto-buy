# 🎰 로또 자동 구매

매주 월요일 동행복권 로또 6/45를 자동으로 구매하고, 설정값에 따라 연금복권 720+도 함께 구매한 뒤, 토요일에 두 복권의 당첨 여부를 카카오톡으로 알려주는 GitHub Actions 기반 자동화 프로젝트입니다.

## 동작 흐름

```
매주 월요일 21:00 KST
  → Gemini AI가 번호 추천
  → Playwright로 동행복권 자동 로그인 & 구매
  → data/purchased.json, data/pension_purchased.json에 저장 (repo에 커밋)
  → 카카오톡으로 구매 완료 알림

매주 토요일 23:00 KST
  → Playwright로 로또 / 연금복권 당첨번호 조회
  → data/purchased.json, data/pension_purchased.json과 대조
  → 카카오톡으로 당첨 결과 알림
```

## 파일 구조

```
├── src/
│   ├── lotto_buyer.py      # 메인 구매 스크립트 (Playwright)
│   ├── check_number.py     # 당첨 확인 스크립트 (Playwright)
│   ├── number_selector.py  # 번호 선택 (Gemini AI / 랜덤)
│   └── kakao_notify.py     # 카카오톡 알림
├── data/
│   ├── purchased.json      # 로또 구매한 번호 (구매 후 자동 커밋)
│   ├── pension_purchased.json # 연금복권 구매 내역
│   ├── purchased.test.json # 로또 테스트 저장 파일
│   └── pension_purchased.test.json # 연금복권 테스트 저장 파일
├── settings.json           # 구매 장수 설정
└── .github/workflows/
    └── lotto-buyer.yml     # 자동화 워크플로
```

## 설정

### 1. GitHub Secrets 등록

| Secret                | 설명                 |
| --------------------- | -------------------- |
| `LOTTO_ID`            | 동행복권 아이디      |
| `LOTTO_PW`            | 동행복권 비밀번호    |
| `API_KEY`             | Gemini API 키        |
| `KAKAO_REST_API_KEY`  | 카카오 REST API 키   |
| `KAKAO_REFRESH_TOKEN` | 카카오 리프레시 토큰 |

### 2. 구매 장수 설정

`settings.json`에서 조정합니다:

```json
{
  // 6 / 45 복권 구매 수
  "total_tickets": 3,
  // 연금복권 720+ 구매 수 (0이면 미구매)
  "pension_tickets": 0
}
```

### 3. 사전 조건

- 동행복권 예치금이 `장수 × 1,000원` 이상 충전되어 있어야 합니다.
- 예치금 부족 시 카카오톡으로 알림 후 중단됩니다.

## 수동 실행

GitHub Actions → `🎰 로또 자동 구매` → `Run workflow`

| 모드        | 설명                                                       |
| ----------- | ---------------------------------------------------------- |
| `buy`       | 구매만 실행                                                |
| `check`     | 당첨 확인만 실행 (`data/purchased.json` 또는 numbers 입력) |
| `buy+check` | 구매 후 즉시 당첨 확인 (테스트용)                          |

`check` 모드에서 번호를 직접 지정하려면 `numbers` 항목에 입력:

```
[[4,8,15,23,31,38],[7,13,20,29,35,42]]
```

## 실행 기준

- GitHub Actions 실행은 `DRY_RUN=false`로 동작하므로 실제 구매/실제 확인 기준입니다.
- 로컬 실행은 기본적으로 `DRY_RUN=true`라서 안전한 테스트 모드입니다.
- 로컬 테스트 결과는 `data/purchased.test.json`, `data/pension_purchased.test.json`에 저장됩니다.
- 실제 로컬 구매/확인이 필요하면 `DRY_RUN=false`를 명시해서 실행하면 됩니다.

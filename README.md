# 🎰 로또 자동 구매

매주 금요일 동행복권 로또 6/45를 자동으로 구매하고, 수요일에 연금복권 720+도 함께 구매한 뒤, 각각 당첨 여부를 카카오톡으로 알려주는 GitHub Actions 기반 자동화 프로젝트입니다.

## 동작 흐름

```
매주 금요일 12:00 KST  (로또 6/45 구매)
  → Gemini AI가 번호 추천
  → dhapi로 동행복권 자동 로그인 & 구매
  → data/purchased.json에 저장 (repo에 커밋)
  → 카카오톡으로 구매 완료 알림

매주 토요일 22:00 KST  (로또 6/45 당첨 확인)
  → Playwright로 동행복권 당첨번호 조회
  → data/purchased.json과 대조
  → 카카오톡으로 당첨 결과 알림

매주 수요일 12:00 KST  (연금복권 720+ 구매)
  → HTTP 직접 요청으로 동행복권 자동 로그인 & 구매
  → data/pension_purchased.json에 저장 (repo에 커밋)
  → 카카오톡으로 구매 완료 알림

매주 목요일 22:00 KST  (연금복권 720+ 당첨 확인)
  → Playwright로 연금복권 당첨번호 조회
  → data/pension_purchased.json과 대조
  → 카카오톡으로 당첨 결과 알림
```

## 파일 구조

```
├── src/
│   ├── lotto_buyer.py      # 메인 구매 스크립트
│   ├── check_number.py     # 당첨 확인 스크립트 (Playwright)
│   ├── number_selector.py  # 번호 선택 (Gemini AI / 랜덤)
│   ├── win720.py           # 연금복권 720+ 구매 모듈
│   └── kakao_notify.py     # 카카오톡 알림
├── data/
│   ├── purchased.json               # 로또 구매 번호 (구매 후 자동 커밋)
│   ├── pension_purchased.json       # 연금복권 구매 내역 (구매 후 자동 커밋)
│   ├── purchased.test.json          # 로또 테스트 저장 파일
│   └── pension_purchased.test.json  # 연금복권 테스트 저장 파일
├── settings.json           # 구매 장수 설정
└── .github/workflows/
    ├── lotto645.yml        # 로또 6/45 자동화 워크플로
    └── pension.yml         # 연금복권 720+ 자동화 워크플로
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
  "total_tickets": 3,
  "pension_tickets": 2
}
```

- `pension_tickets`를 `0`으로 설정하면 연금복권을 구매하지 않습니다.

### 3. 사전 조건

- 동행복권 예치금이 `장수 × 1,000원` 이상 충전되어 있어야 합니다.
- 예치금 부족 시 카카오톡으로 알림 후 중단됩니다.

## 수동 실행

### 로또 6/45

GitHub Actions → `🎰 로또 6/45` → `Run workflow`

| 모드        | 설명                                                       |
| ----------- | ---------------------------------------------------------- |
| `buy`       | 구매만 실행                                                |
| `check`     | 당첨 확인만 실행 (`data/purchased.json` 또는 numbers 입력) |
| `buy+check` | 구매 후 즉시 당첨 확인 (테스트용)                          |

`check` 모드에서 번호를 직접 지정하려면 `numbers` 항목에 입력:

```
[[4,8,15,23,31,38],[7,13,20,29,35,42]]
```

### 연금복권 720+

GitHub Actions → `💸 연금복권 720+` → `Run workflow`

| 모드        | 설명                   |
| ----------- | ---------------------- |
| `buy`       | 구매만 실행            |
| `check`     | 당첨 확인만 실행       |
| `buy+check` | 구매 후 즉시 당첨 확인 |

## 실행 기준

- GitHub Actions 실행은 `DRY_RUN=false`로 동작하므로 실제 구매/확인 기준입니다.
- 로컬 실행은 기본적으로 `DRY_RUN=true`라서 안전한 테스트 모드입니다.
- 로컬 테스트 결과는 `data/purchased.test.json`, `data/pension_purchased.test.json`에 저장됩니다.
- 실제 로컬 구매/확인이 필요하면 `DRY_RUN=false`를 명시해서 실행하면 됩니다.

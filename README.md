# 🎰 로또 자동 구매

매주 금요일 동행복권 로또 6/45를 자동으로 구매하고, 토요일에 당첨 여부를 카카오톡으로 알려주는 GitHub Actions 기반 자동화 프로젝트입니다.

## 동작 흐름

```
매주 금요일 21:00 KST
  → Gemini AI가 번호 추천
  → Playwright로 동행복권 자동 로그인 & 구매
  → data/purchased.json에 번호 저장 (repo에 커밋)
  → 카카오톡으로 구매 완료 알림

매주 토요일 23:00 KST
  → Playwright로 동행복권 당첨번호 조회
  → data/purchased.json의 구매 번호와 대조
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
│   └── purchased.json      # 구매한 번호 (구매 후 자동 커밋)
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
    "total_tickets": 3
    // 연금 복권 추후 추가예정
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

## 개선할점

- 자동이 아닌 수동 번호 선택 가능하게할것
- 더 쉽게 사용이 가능하도록 모듈화
- 추후 카카오톡 챗봇을 이용해 알림
- 연금복권도 가능하게 하기

"""
당첨 확인 스크립트
- 동행복권 API로 당첨번호 조회
- 구매 번호와 대조
- 카카오톡으로 결과 전송
"""

import os
import json
import httpx
from kakao_notify import notify_result, notify_error

# 구매 job에서 넘어온 번호 (GitHub Actions output)
PURCHASED_JSON = os.environ.get("PURCHASED_NUMBERS", "")


def get_winning_numbers() -> dict:
    """동행복권 API로 최신 당첨번호 조회"""
    resp = httpx.get(
        "https://www.dhlottery.co.kr/common.do",
        params={"method": "getLottoNumber", "drwNo": ""},
        timeout=10,
    )
    data = resp.json()

    if data.get("returnValue") != "success":
        raise Exception(f"당첨번호 조회 실패: {data}")

    winning = [
        data["drwtNo1"], data["drwtNo2"], data["drwtNo3"],
        data["drwtNo4"], data["drwtNo5"], data["drwtNo6"],
    ]
    bonus   = data["bnusNo"]
    draw_no = data["drwNo"]

    print(f"🏆 제{draw_no}회 당첨번호: {winning} + 보너스: {bonus}")
    return {"winning": winning, "bonus": bonus, "draw_no": draw_no}


def main():
    if not PURCHASED_JSON:
        print("⚠️  PURCHASED_NUMBERS 없음 → 당첨 확인 스킵")
        return

    try:
        purchased = json.loads(PURCHASED_JSON)
    except Exception as e:
        notify_error(f"구매 번호 파싱 오류: {e}")
        return

    try:
        result = get_winning_numbers()
    except Exception as e:
        notify_error(f"당첨번호 조회 오류: {e}")
        return

    notify_result(
        purchased=purchased,
        winning=result["winning"],
        bonus=result["bonus"],
        draw_no=result["draw_no"],
    )


if __name__ == "__main__":
    main()
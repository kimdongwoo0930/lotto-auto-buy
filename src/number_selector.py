"""
번호 선택 모듈
- AI 추천
- 추후: numbers.txt 파일로 직접 입력 예정
"""

import os
import json
import random
import httpx

GEMINI_KEY = os.environ.get("API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"


async def get_ai_numbers(count: int) -> list[list[int]]:
    """Gemini API로 로또 번호 추천"""
    if not GEMINI_KEY:
        print("⚠️  API_KEY 없음 → 랜덤 번호로 대체")
        return [sorted(random.sample(range(1, 46), 6)) for _ in range(count)]

    prompt = f"""로또 6/45 번호 {count}세트를 추천해줘.
조건:
- 각 세트는 1~45 사이 숫자 6개 (중복 없이)
- 반드시 아래 JSON 형식으로만 응답 (다른 텍스트 없이):

{{"numbers": [[n1,n2,n3,n4,n5,n6], ...]}}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 1.0,
                    "responseMimeType": "application/json",
                },
            },
        )
        data = resp.json()
        result = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
        numbers = [sorted(s) for s in result["numbers"]]
        print(f"🤖 Gemini 추천 번호 {count}세트:")
        for i, nums in enumerate(numbers):
            print(f"   {i+1}게임: {nums}")
        return numbers


async def select_numbers(total: int) -> list[list[int]]:
    """
    번호 선택 메인 함수
    Returns: 전체 번호 리스트

    TODO: numbers.txt 파일 지원 예정
    형식: 한 줄에 번호 6개 (예: 1,7,13,22,35,44)
    txt 파일 있으면 해당 번호 우선, 나머지는 Gemini 추천
    """
    numbers = await get_ai_numbers(total)

    print(f"\n📋 최종 선택 번호 ({total}게임):")
    for i, nums in enumerate(numbers):
        print(f"   {i+1}게임: {nums}")

    return numbers


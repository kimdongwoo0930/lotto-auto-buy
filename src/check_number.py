"""
당첨 확인 스크립트
- Playwright로 동행복권 페이지 렌더링 후 당첨번호 추출
- 구매 번호와 대조
- 카카오톡으로 결과 전송
"""

import os
import json
import asyncio
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from kakao_notify import notify_result, notify_error

IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"
INTRO_URL = "https://www.dhlottery.co.kr/lt645/intro"
PURCHASED_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "purchased.json")


def load_purchased() -> list | None:
    """PURCHASED_NUMBERS 환경변수 → data/purchased.json 순으로 읽기"""
    env_val = os.environ.get("PURCHASED_NUMBERS", "").strip()
    if env_val:
        return json.loads(env_val)
    if os.path.exists(PURCHASED_JSON_PATH):
        with open(PURCHASED_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        print(f"📂 구매 번호 파일 로드: {data.get('date', '?')}일 구매분")
        return data["numbers"]
    return None


async def get_winning_numbers() -> dict:
    """Playwright로 페이지 렌더링 후 당첨번호 추출"""
    async with async_playwright() as p:
        launch_opts: dict = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        if not IS_CI:
            launch_opts["channel"] = "chrome"

        browser = await p.chromium.launch(**launch_opts)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        try:
            await page.goto(INTRO_URL, timeout=30000)
            # tm1WnNo 에 숫자가 채워질 때까지 대기
            await page.wait_for_function(
                "document.getElementById('tm1WnNo')?.innerText?.trim() !== ''",
                timeout=15000,
            )

            winning = []
            for i in range(1, 7):
                text = await page.locator(f"#tm{i}WnNo").inner_text()
                winning.append(int(text.strip()))

            bonus_text = await page.locator("#bnsWnNo").inner_text()
            bonus = int(bonus_text.strip())

            draw_text = await page.locator("#pstLtEpsd").inner_text()
            draw_no = int("".join(filter(str.isdigit, draw_text)))

            print(f"🏆 제{draw_no}회 당첨번호: {winning} + 보너스: {bonus}")
            return {"winning": winning, "bonus": bonus, "draw_no": draw_no}

        finally:
            await browser.close()


async def async_main():
    try:
        purchased = load_purchased()
    except Exception as e:
        notify_error(f"구매 번호 파싱 오류: {e}")
        return

    if not purchased:
        print("⚠️  구매 번호 없음 (환경변수 & 파일 모두 없음) → 당첨 확인 스킵")
        return

    try:
        result = await get_winning_numbers()
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
    asyncio.run(async_main())

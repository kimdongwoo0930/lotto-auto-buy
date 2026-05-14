"""
당첨 확인 스크립트
- 로또 6/45, 연금복권720+ 당첨번호 조회
- 구매 내역과 대조
- 카카오톡으로 결과 전송
"""

import os
import json
import asyncio
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from kakao_notify import notify_result, notify_pension_result, notify_error

IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() not in {"0", "false", "no", "n"}
CHECK_LOTTO645 = os.environ.get("CHECK_LOTTO645", "true").strip().lower() != "false"
CHECK_PENSION  = os.environ.get("CHECK_PENSION",  "true").strip().lower() != "false"
LOTTO_INTRO_URL = "https://www.dhlottery.co.kr/lt645/intro"
PENSION_INTRO_URL = "https://www.dhlottery.co.kr/pt720/intro"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PURCHASED_JSON_PATH = os.path.join(
    DATA_DIR, "purchased.test.json" if DRY_RUN else "purchased.json"
)
PENSION_PURCHASED_JSON_PATH = os.path.join(
    DATA_DIR, "pension_purchased.test.json" if DRY_RUN else "pension_purchased.json"
)


def load_lotto_purchased() -> list | None:
    """PURCHASED_NUMBERS 환경변수 → 구매 번호 파일 순으로 읽기"""
    env_val = os.environ.get("PURCHASED_NUMBERS", "").strip()
    if env_val:
        return json.loads(env_val)
    if os.path.exists(PURCHASED_JSON_PATH):
        with open(PURCHASED_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        print(f"📂 로또 구매 번호 파일 로드: {os.path.basename(PURCHASED_JSON_PATH)} / {data.get('date', '?')}일 구매분")
        return data["numbers"]
    return None


def load_pension_purchased() -> list[dict[str, int | str]] | None:
    if os.path.exists(PENSION_PURCHASED_JSON_PATH):
        with open(PENSION_PURCHASED_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        print(
            "📂 연금복권 구매 번호 파일 로드: "
            f"{os.path.basename(PENSION_PURCHASED_JSON_PATH)} / {data.get('date', '?')}일 구매분"
        )
        return data["tickets"]
    return None


def _extract_int(text: str, label: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise Exception(f"{label}에서 숫자를 찾지 못했습니다: {text!r}")
    return int(digits)


async def get_lotto_winning_numbers() -> dict:
    """Playwright로 로또 당첨번호 추출"""
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
            await page.goto(LOTTO_INTRO_URL, timeout=30000)
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

            print(f"🏆 로또 제{draw_no}회 당첨번호: {winning} + 보너스: {bonus}")
            return {"winning": winning, "bonus": bonus, "draw_no": draw_no}

        finally:
            await browser.close()


async def get_pension_winning_numbers() -> dict:
    """Playwright로 연금복권 당첨번호 추출"""
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
            await page.goto(PENSION_INTRO_URL, wait_until="domcontentloaded", timeout=60000)

            ready = False
            last_body_text = ""
            for attempt in range(12):
                await page.wait_for_timeout(5000 if attempt > 0 else 2000)
                last_body_text = await page.locator("body").inner_text()

                if any(msg in last_body_text for msg in [
                    "서비스 접근 대기 중입니다",
                    "서비스 접속이 차단",
                    "접속량이 많아 접속이 불가능합니다",
                ]):
                    print(f"⏳ 연금복권 페이지 대기/차단 감지 → 재시도 {attempt + 1}/12")
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                    continue

                rnk_count = await page.locator("#rnk1Div .wf-ball:not(.pension-jo)").count()
                bns_count = await page.locator("#bnsDiv .wf-ball").count()
                has_round = await page.locator("#pstPsltEpsd, #pstLtPstlEpsd").count()

                if rnk_count >= 6 and bns_count >= 6 and has_round:
                    ready = True
                    break

            if not ready:
                snippet = " ".join(last_body_text.split())[:200]
                raise Exception(f"연금복권 결과 영역 대기 시간 초과: {snippet}")

            draw_text = (await page.locator("#pstPsltEpsd, #pstLtPstlEpsd").first.inner_text()).strip()
            draw_no = _extract_int(draw_text, "연금복권 회차")

            winning_group_text = (await page.locator("#rnk1Div .pension-jo").inner_text()).strip()
            winning_group = _extract_int(winning_group_text, "연금복권 1등 조")

            winning_digits = []
            winning_nums = page.locator("#rnk1Div .wf-ball:not(.pension-jo)")
            for idx in range(await winning_nums.count()):
                text = (await winning_nums.nth(idx).inner_text()).strip()
                if text.isdigit():
                    winning_digits.append(text)

            bonus_digits = []
            bonus_nums = page.locator("#bnsDiv .wf-ball")
            for idx in range(await bonus_nums.count()):
                text = (await bonus_nums.nth(idx).inner_text()).strip()
                if text.isdigit():
                    bonus_digits.append(text)

            winning_number = "".join(winning_digits)
            bonus_number = "".join(bonus_digits)

            if len(winning_number) != 6 or len(bonus_number) != 6:
                raise Exception(
                    f"연금복권 번호 길이 확인 실패: 1등={winning_number}, 보너스={bonus_number}"
                )

            print(
                "🏆 연금복권 결과: "
                f"{winning_group}조 {winning_number} "
                f"(보너스 {bonus_number})"
            )
            return {
                "draw_no": draw_no,
                "winning_group": winning_group,
                "winning_number": winning_number,
                "bonus_number": bonus_number,
            }

        finally:
            await browser.close()


async def async_main():
    try:
        lotto_purchased = load_lotto_purchased() if CHECK_LOTTO645 else None
        pension_purchased = load_pension_purchased() if CHECK_PENSION else None
    except Exception as e:
        notify_error(f"구매 번호 파싱 오류: {e}")
        return

    if not lotto_purchased and not pension_purchased:
        print("⚠️  구매 번호 없음 → 당첨 확인 스킵")
        return

    if lotto_purchased:
        try:
            lotto_result = await get_lotto_winning_numbers()
            notify_result(
                purchased=lotto_purchased,
                winning=lotto_result["winning"],
                bonus=lotto_result["bonus"],
                draw_no=lotto_result["draw_no"],
            )
        except Exception as e:
            notify_error(f"로또 당첨번호 조회 오류: {e}")

    if pension_purchased:
        try:
            pension_result = await get_pension_winning_numbers()
            notify_pension_result(
                tickets=pension_purchased,
                winning_group=pension_result["winning_group"],
                winning_number=pension_result["winning_number"],
                bonus_number=pension_result["bonus_number"],
                draw_no=pension_result["draw_no"],
            )
        except Exception as e:
            notify_error(f"연금복권 당첨번호 조회 오류: {e}")


if __name__ == "__main__":
    asyncio.run(async_main())

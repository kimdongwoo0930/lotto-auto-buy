"""
동행복권 자동 구매 스크립트
- Playwright 기반 자동화
- settings.json에서 설정 로드
- 카카오톡 알림 연동
"""

import os
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright

from number_selector import select_numbers
from kakao_notify import notify_purchase, notify_error

# ── 환경변수 (GitHub Secrets) ──────────────────────────
LOTTO_ID = os.environ["LOTTO_ID"]
LOTTO_PW = os.environ["LOTTO_PW"]
BASE_URL  = "https://dhlottery.co.kr"


# ── 커스텀 예외 ────────────────────────────────────────
class InsufficientBalanceError(Exception):
    """예치금 부족 예외"""
    pass


# ── settings.json 로드 ─────────────────────────────────
def load_settings() -> dict:
    settings_path = os.path.join(os.path.dirname(__file__), "..", "settings.json")
    with open(settings_path, "r", encoding="utf-8") as f:
        content = "\n".join(
            line for line in f.read().splitlines()
            if not line.strip().startswith("//")
        )
        return json.loads(content)


# ── Playwright 자동화 ──────────────────────────────────
async def buy_lotto(all_numbers: list[list[int]]) -> list[list[int]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        page.set_default_timeout(20000)

        try:
            # 1. 로그인
            print("🔐 로그인 중...")
            await page.goto(f"{BASE_URL}/common/main.do")
            await page.wait_for_load_state("networkidle")

            await page.fill("#userId", LOTTO_ID)
            await page.fill("#password", LOTTO_PW)
            await page.click(".btn_common.lrg.blu")
            await page.wait_for_load_state("networkidle")

            if await page.locator("#loginMenu").count() > 0:
                raise Exception("로그인 실패! ID/PW를 확인하세요.")
            print("✅ 로그인 성공")

            # 2. 예치금 확인
            await page.goto(f"{BASE_URL}/myPage/myPageMain.do")
            await page.wait_for_load_state("networkidle")

            balance_el = page.locator("#totalCash")
            balance_text = await balance_el.inner_text()
            balance = int(balance_text.replace(",", "").replace("원", "").strip())
            needed  = len(all_numbers) * 1000

            print(f"💰 예치금: {balance:,}원 | 필요금액: {needed:,}원")

            if balance < needed:
                raise InsufficientBalanceError(
                    f"예치금 부족! 현재: {balance:,}원 / 필요: {needed:,}원\n"
                    f"동행복권 사이트에서 {needed - balance:,}원 이상 충전해주세요."
                )

            # 3. 구매 페이지 이동
            await page.goto(f"{BASE_URL}/game/buyReal.do?gameType=2")
            await page.wait_for_load_state("networkidle")

            # 4. 번호 입력 & 구매 (5게임씩 배치)
            purchased = []
            batch_size = 5

            for batch_start in range(0, len(all_numbers), batch_size):
                batch = all_numbers[batch_start:batch_start + batch_size]
                print(f"\n🎰 {batch_start+1}~{batch_start+len(batch)}게임 입력 중...")

                for game_idx, nums in enumerate(batch):
                    auto_chk = page.locator(f"#checkAuto{game_idx+1}")
                    if await auto_chk.is_checked():
                        await auto_chk.uncheck()

                    for num in nums:
                        await page.click(f"#numCheck{game_idx}_{num}")
                    print(f"   {batch_start+game_idx+1}게임: {nums}")

                await page.click("#btnBuy")
                await page.wait_for_selector(".layerPopup", timeout=10000)
                await page.click(".layerPopup .btn_common.lrg.blu")
                await page.wait_for_load_state("networkidle")

                purchased.extend(batch)
                print(f"   ✅ {len(batch)}게임 구매 완료!")

                if batch_start + batch_size < len(all_numbers):
                    await page.goto(f"{BASE_URL}/game/buyReal.do?gameType=2")
                    await page.wait_for_load_state("networkidle")

            print(f"\n🎉 총 {len(purchased)}장 구매 완료!")
            return purchased

        finally:
            await browser.close()


# ── GitHub Actions Summary 기록 ────────────────────────
def write_summary(numbers: list[list[int]]):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"## 🎰 로또 구매 완료 ({datetime.now().strftime('%Y-%m-%d')})\n\n")
            f.write("| 게임 | 번호 |\n|------|------|\n")
            for i, nums in enumerate(numbers):
                f.write(f"| {i+1} | {' - '.join(map(str, nums))} |\n")
            f.write(f"\n**총 {len(numbers)}장 구매**\n")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(f"purchased_numbers={json.dumps(numbers)}\n")


# ── 메인 ───────────────────────────────────────────────
async def main():
    settings = load_settings()
    total = settings.get("total_tickets", 5)

    print(f"🚀 로또 자동 구매 시작 | 총 {total}장")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    numbers = await select_numbers(total)
    purchased = await buy_lotto(numbers)
    write_summary(purchased)
    notify_purchase(purchased)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except InsufficientBalanceError as e:
        print(f"💰 예치금 부족: {e}")
        notify_error(f"💰 예치금 부족\n\n{e}")
        raise
    except Exception as e:
        print(f"❌ 오류: {e}")
        notify_error(f"❌ 오류 발생\n\n{e}")
        raise
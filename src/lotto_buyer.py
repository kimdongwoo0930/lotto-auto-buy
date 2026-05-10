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
from playwright.async_api import async_playwright, Page

from dotenv import load_dotenv
load_dotenv()

from number_selector import select_numbers
from kakao_notify import notify_purchase, notify_error

# ── 환경변수 ────────────────────────────────────────────
LOTTO_ID = os.environ["LOTTO_ID"]
LOTTO_PW = os.environ["LOTTO_PW"]
BASE_URL  = "https://www.dhlottery.co.kr"
GAME_URL  = "https://ol.dhlottery.co.kr/olotto/game/game645.do"
IS_CI     = os.environ.get("GITHUB_ACTIONS") == "true"


# ── 커스텀 예외 ────────────────────────────────────────
class InsufficientBalanceError(Exception):
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


# ── 환경 알림 팝업 닫기 ────────────────────────────────
async def _dismiss_alert(page: Page) -> None:
    sel = 'input[value="확인"][onclick="javascript:closepopupLayerAlert();"]'
    try:
        btn = page.locator(sel).first
        if await btn.is_visible(timeout=2000):
            await btn.click()
            await page.wait_for_timeout(500)
    except Exception:
        pass


# ── 로그인 ─────────────────────────────────────────────
async def _login(page: Page) -> None:
    print("🔐 로그인 중...")
    await page.goto(f"{BASE_URL}/login")
    await page.wait_for_load_state("networkidle")

    await page.fill("#inpUserId", LOTTO_ID)
    await page.fill("#inpUserPswdEncn", LOTTO_PW)
    await page.click("#btnLogin")

    # redirect 완료까지 대기 (/login에서 벗어날 때까지)
    try:
        await page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    except Exception:
        pass
    await page.wait_for_load_state("networkidle")

    # 로그인 실패 팝업 확인
    error_pop = page.locator('.msgPop[role="alertdialog"]')
    if await error_pop.is_visible(timeout=2000):
        raise Exception("로그인 실패! 아이디 또는 비밀번호가 일치하지 않습니다.")

    # 로그인 성공 확인: /login 페이지를 벗어났으면 성공
    if "/login" in page.url:
        raise Exception("로그인 실패! 상태를 확인하세요.")

    print("✅ 로그인 성공")


# ── 예치금 확인 ────────────────────────────────────────
async def _check_balance(page: Page, needed: int) -> None:
    """예치금 확인 (실패해도 구매는 계속 진행)"""
    try:
        for sel in ["#totalCash", ".total_cash", "[class*='balance']", "[class*='deposit']"]:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible(timeout=1000):
                text = await el.inner_text()
                balance = int("".join(c for c in text if c.isdigit()))
                print(f"💰 예치금: {balance:,}원 | 필요금액: {needed:,}원")
                if balance < needed:
                    raise InsufficientBalanceError(
                        f"예치금 부족! 현재: {balance:,}원 / 필요: {needed:,}원\n"
                        f"동행복권 사이트에서 {needed - balance:,}원 이상 충전해주세요."
                    )
                return
        print("⚠️  예치금 확인 불가 — 구매 계속 진행")
    except InsufficientBalanceError:
        raise
    except Exception:
        print("⚠️  예치금 확인 중 오류 — 구매 계속 진행")


# ── 구매 페이지 열기 ───────────────────────────────────
async def _open_game_page(page: Page) -> None:
    await page.goto(GAME_URL, timeout=60000)
    await page.wait_for_load_state("domcontentloaded")
    await _dismiss_alert(page)

    # 수동 선택 탭으로 전환
    await page.click('a[href="#divWay2Buy1"]#num1')
    await page.wait_for_selector('label[for="check645num1"]', timeout=15000)


# ── 번호 선택 및 구매 (1배치: 최대 5게임) ───────────────
async def _buy_batch(page: Page, batch: list[list[int]], batch_start: int) -> None:
    for game_idx, nums in enumerate(batch):
        print(f"   {batch_start + game_idx + 1}게임 번호 입력: {nums}")
        for num in nums:
            await page.locator(f'label[for="check645num{num}"]').scroll_into_view_if_needed()
            await page.click(f'label[for="check645num{num}"]')
            await page.wait_for_timeout(300)

        await page.select_option("select#amoundApply", "1")
        await page.click('input[value="확인"]#btnSelectNum')
        await page.wait_for_timeout(500)

    # 구매 버튼 클릭
    await page.click("button#btnBuy")
    # 구매 확인 팝업 대기 후 클릭
    confirm_sel = 'input[value="확인"][onclick="javascript:closepopupLayerConfirm(true);"]'
    await page.wait_for_selector(confirm_sel, timeout=10000)
    await page.click(confirm_sel)


# ── 구매 결과 파싱 ─────────────────────────────────────
async def _parse_results(page: Page) -> list[list[int]]:
    await page.wait_for_selector("#reportRow .nums", timeout=20000)
    result_els = await page.locator("#reportRow .nums").all()
    results = []
    for el in result_els:
        children = await el.locator("*").all()
        nums = []
        for child in children:
            text = (await child.inner_text()).strip()
            if text.isdigit():
                nums.append(int(text))
        if nums:
            results.append(sorted(nums))
    return results


# ── Playwright 자동화 ──────────────────────────────────
async def buy_lotto(all_numbers: list[list[int]]) -> list[list[int]]:
    async with async_playwright() as p:
        launch_opts: dict = {
            "headless": IS_CI,
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
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        page.set_default_timeout(20000)

        try:
            # 1. 로그인
            await _login(page)

            # 2. 예치금 확인 (메인 페이지)
            await page.goto(f"{BASE_URL}/main")
            await page.wait_for_load_state("networkidle")
            await _check_balance(page, len(all_numbers) * 1000)

            # 3. 구매 (5게임씩 배치)
            purchased: list[list[int]] = []
            batch_size = 5

            for batch_start in range(0, len(all_numbers), batch_size):
                batch = all_numbers[batch_start : batch_start + batch_size]
                print(f"\n🎰 {batch_start+1}~{batch_start+len(batch)}게임 구매 중...")

                await _open_game_page(page)
                await _buy_batch(page, batch, batch_start)

                # 결과 파싱 실패 시 입력 번호로 대체 (구매는 이미 완료됨)
                try:
                    batch_result = await _parse_results(page)
                    if not batch_result:
                        raise ValueError("빈 결과")
                except Exception as e:
                    print(f"   ⚠️  결과 파싱 실패({e}) → 입력 번호로 대체")
                    batch_result = batch

                purchased.extend(batch_result)
                print(f"   ✅ {len(batch)}게임 구매 완료!")

            print(f"\n🎉 총 {len(purchased)}장 구매 완료!")
            return purchased

        finally:
            await browser.close()


# ── GitHub Actions Summary 기록 ────────────────────────
def write_summary(numbers: list[list[int]]) -> None:
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
async def main() -> None:
    settings = load_settings()
    total = settings.get("total_tickets", 5)

    print(f"🚀 로또 자동 구매 시작 | 총 {total}장")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🖥  headless={'True (CI)' if IS_CI else 'False (로컬)'}")

    numbers   = await select_numbers(total)
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

"""
동행복권 자동 구매 스크립트
- Playwright 기반 자동화
- settings.json에서 설정 로드
- 카카오톡 알림 연동
"""

import os
import json
import asyncio
import random
import re
from datetime import datetime
from playwright.async_api import async_playwright, Page

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from number_selector import select_numbers
from kakao_notify import notify_purchase, notify_pension_purchase, notify_error

# ── 환경변수 ────────────────────────────────────────────
LOTTO_ID = os.environ["LOTTO_ID"]
LOTTO_PW = os.environ["LOTTO_PW"]
BASE_URL  = "https://www.dhlottery.co.kr"
GAME_URL  = "https://ol.dhlottery.co.kr/olotto/game/game645.do"
PENSION_URL = "https://el.dhlottery.co.kr/game_mobile/pension720/game.jsp"
IS_CI     = os.environ.get("GITHUB_ACTIONS") == "true"
DRY_RUN   = os.environ.get("DRY_RUN", "true").strip().lower() not in {"0", "false", "no", "n"}


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
        settings = json.loads(content)
        settings.setdefault("total_tickets", 5)
        settings.setdefault("pension_tickets", 0)
        return settings


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
    await page.goto(f"{BASE_URL}/mypage/home")
    await page.wait_for_load_state("networkidle")

    text = await page.locator("#totalAmt").inner_text()
    balance = int(text.replace(",", "").strip() or "0")
    print(f"💰 예치금: {balance:,}원 | 필요금액: {needed:,}원")

    if balance < needed:
        raise InsufficientBalanceError(
            f"예치금 부족! 현재: {balance:,}원 / 필요: {needed:,}원\n"
            f"동행복권 사이트에서 {needed - balance:,}원 이상 충전해주세요."
        )


# ── 구매 페이지 열기 ───────────────────────────────────
async def _open_game_page(page: Page) -> None:
    await page.goto(GAME_URL, timeout=60000)
    await page.wait_for_load_state("domcontentloaded")
    await _dismiss_alert(page)

    # 수동 선택 탭으로 전환
    await page.click('a[href="#divWay2Buy1"]#num1')
    await page.wait_for_selector('label[for="check645num1"]', timeout=15000)


# ── 연금복권 구매 페이지 열기 ──────────────────────────
async def _open_pension_page(page: Page) -> None:
    await page.goto(PENSION_URL, timeout=60000)
    await page.wait_for_load_state("domcontentloaded")
    await _dismiss_alert(page)
    await page.wait_for_selector("text=번호 선택하기", timeout=15000)


# ── 연금복권 팝업의 클릭 가능한 옵션 선택 ────────────────
async def _click_pension_option(page: Page, label: str) -> None:
    selectors = [
        lambda: page.get_by_role("link", name=label, exact=True),
        lambda: page.locator(f'a:text-is("{label}")'),
        lambda: page.locator(f'button:text-is("{label}")'),
        lambda: page.locator(f'label:text-is("{label}")'),
        lambda: page.locator(f'span:text-is("{label}")'),
    ]

    for build_locator in selectors:
        options = build_locator()
        count = await options.count()

        for idx in range(count - 1, -1, -1):
            option = options.nth(idx)
            if not await option.is_visible():
                continue

            class_name = await option.get_attribute("class") or ""
            if "numdgroup" in class_name:
                continue

            try:
                await option.click()
                return
            except Exception:
                continue

    raise Exception(f"연금복권 옵션을 찾지 못했습니다: {label}")


# ── 연금복권 자동선택 결과 읽기 ─────────────────────────
async def _read_pension_selection(page: Page, expected_group: int) -> dict[str, int | str]:
    cards = page.locator("div.win720_num")
    card_count = await cards.count()
    if card_count == 0:
        raise Exception("연금복권 자동번호 결과 카드(win720_num)를 찾지 못했습니다.")

    card = cards.nth(card_count - 1)
    group_text = (await card.locator("span.group").inner_text()).strip()
    group_digits = "".join(ch for ch in group_text if ch.isdigit())
    group = int(group_digits) if group_digits else expected_group

    nums = card.locator("ul.num_list span.num")
    num_count = await nums.count()
    digits: list[str] = []

    for idx in range(num_count):
        text = (await nums.nth(idx).inner_text()).strip()
        if text.isdigit():
            digits.append(text)

    if len(digits) != 6:
        raise Exception(f"연금복권 자동번호 6자리를 읽지 못했습니다. 선택값: {digits}")

    number = "".join(digits)

    if group != expected_group:
        raise Exception(
            f"연금복권 조 확인 실패: 기대값 {expected_group}조 / 실제값 {group}조"
        )

    if not re.fullmatch(r"\d{6}", number):
        raise Exception(f"연금복권 번호 형식이 올바르지 않습니다: {number}")

    return {"group": group, "number": number}


# ── 연금복권 번호 선택 ─────────────────────────────────
async def _select_pension_number(page: Page, group: int) -> dict[str, int | str]:
    await page.get_by_text("번호 선택하기").click()
    await page.wait_for_timeout(500)

    await _click_pension_option(page, f"{group}조")
    await page.wait_for_timeout(300)

    await page.locator('a.btn_wht.xsmall[onclick="doAuto();"]').click()
    await page.wait_for_timeout(300)

    ticket = await _read_pension_selection(page, group)

    await page.get_by_text("선택완료").click()
    await page.wait_for_timeout(1000)
    return ticket


# ── 연금복권 번호 생성 ─────────────────────────────────
def _generate_pension_tickets(count: int) -> list[dict[str, int | str]]:
    tickets: list[dict[str, int | str]] = []
    for _ in range(count):
        group = random.randint(1, 5)
        tickets.append({
            "group": group,
            "number": "",
        })
    return tickets


# ── 연금복권 구매 ──────────────────────────────────────
async def buy_pension_lotto(count: int, dry_run: bool = False) -> list[dict[str, int | str]]:
    if count <= 0:
        return []

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
            await _login(page)
            await _open_pension_page(page)

            tickets = _generate_pension_tickets(count)
            print(f"\n💸 연금복권 {count}장 구매 중...")
            for ticket_idx, ticket in enumerate(tickets):
                print(f"   {ticket_idx + 1}장 선택: {ticket['group']}조 자동번호")
                selected_ticket = await _select_pension_number(page, int(ticket["group"]))
                ticket["group"] = selected_ticket["group"]
                ticket["number"] = selected_ticket["number"]
                print(f"      ↳ 선택 결과: {ticket['group']}조 {ticket['number']}")

            if dry_run:
                print("   🧪 DRY_RUN 활성화 → 구매 버튼은 누르지 않고 종료합니다.")
                return tickets

            await page.locator('a.btn_blue.large.full[onclick="doOrder();"]').click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1500)

            # 완료 화면이 열렸는지 확인한다.
            try:
                await page.wait_for_selector("text=구매완료", timeout=3000)
                print(f"   ✅ 연금복권 {count}장 구매 완료!")
            except Exception:
                print(f"   ✅ 연금복권 {count}장 구매 요청 완료!")

            return tickets

        finally:
            await browser.close()


# ── 번호 선택 및 구매 (1배치: 최대 5게임) ───────────────
async def _buy_batch(page: Page, batch: list[list[int]], batch_start: int) -> None:
    for game_idx, nums in enumerate(batch):
        print(f"   {batch_start + game_idx + 1}게임 번호 입력: {nums}")
        for num in nums:
            await page.locator(f'label[for="check645num{num}"]').scroll_into_view_if_needed()
            await page.click(f'label[for="check645num{num}"]')
            await page.wait_for_timeout(1000)

        await page.select_option("select#amoundApply", "1")
        await page.click('input[value="확인"]#btnSelectNum')
        await page.wait_for_timeout(500)

    # 구매 버튼 클릭
    await page.click("button#btnBuy")

    # 구매 확인 팝업 vs 오류 팝업 동시 대기
    confirm_sel = 'input[value="확인"][onclick="javascript:closepopupLayerConfirm(true);"]'
    error_sel   = '.msgPop[role="alertdialog"]'
    await page.wait_for_selector(f"{confirm_sel}, {error_sel}", timeout=10000)

    # 오류 팝업이 떴으면 메시지 읽고 예외 발생
    error_pop = page.locator(error_sel).first
    if await error_pop.is_visible(timeout=500):
        msg = (await error_pop.inner_text()).strip()
        if any(kw in msg for kw in ["잔액", "예치금", "부족", "충전"]):
            raise InsufficientBalanceError(
                f"{msg}\n동행복권 사이트에서 충전 후 다시 시도해주세요."
            )
        raise Exception(f"구매 실패: {msg}")

    await page.click(confirm_sel)


# ── 구매 결과 파싱 ─────────────────────────────────────
async def _parse_results(page: Page) -> list[list[int]]:
    try:
        await page.wait_for_selector("#reportRow .nums", timeout=20000)
    except Exception:
        # 결과 대신 오류 팝업이 있는지 먼저 확인
        error_pop = page.locator('.msgPop[role="alertdialog"]').first
        if await error_pop.is_visible(timeout=1000):
            msg = (await error_pop.inner_text()).strip()
            if any(kw in msg for kw in ["잔액", "예치금", "부족", "충전"]):
                raise InsufficientBalanceError(
                    f"{msg}\n동행복권 사이트에서 충전 후 다시 시도해주세요."
                )
            raise Exception(f"구매 실패: {msg}")
        raise  # 오류 팝업도 없으면 원래 timeout 재발생

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
async def buy_lotto(all_numbers: list[list[int]], dry_run: bool = False) -> list[list[int]]:
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

            # 2. 예치금 확인
            await _check_balance(page, len(all_numbers) * 1000)

            # 3. 구매 (5게임씩 배치)
            purchased: list[list[int]] = []
            batch_size = 5

            for batch_start in range(0, len(all_numbers), batch_size):
                batch = all_numbers[batch_start : batch_start + batch_size]
                print(f"\n🎰 {batch_start+1}~{batch_start+len(batch)}게임 구매 중...")

                await _open_game_page(page)
                await _buy_batch(page, batch, batch_start)

                if dry_run:
                    print("   🧪 DRY_RUN 활성화 → 구매 버튼은 누르지 않고 종료합니다.")
                    batch_result = batch
                    purchased.extend(batch_result)
                    print(f"   ✅ {len(batch)}게임 선택 완료!")
                    continue

                # 결과 파싱 실패 시 입력 번호로 대체 (구매 확인까지 완료된 상태)
                try:
                    batch_result = await _parse_results(page)
                    if not batch_result:
                        raise ValueError("빈 결과")
                    print(f"   🔍 구매 확인된 번호: {batch_result}")
                except InsufficientBalanceError:
                    raise  # 잔액 부족은 fallback 없이 바로 위로 전파
                except Exception as e:
                    print(f"   ⚠️  결과 파싱 실패 → 입력 번호로 대체 ({e})")
                    batch_result = batch

                purchased.extend(batch_result)
                print(f"   ✅ {len(batch)}게임 구매 완료!")

            print(f"\n🎉 총 {len(purchased)}장 구매 완료!")
            return purchased

        finally:
            await browser.close()


# ── 구매 번호 파일 저장 ────────────────────────────────
def save_purchased_json(numbers: list[list[int]], is_test: bool = False) -> None:
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    filename = "purchased.test.json" if is_test else "purchased.json"
    json_path = os.path.join(data_dir, filename)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "test": is_test,
                "numbers": numbers,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"💾 구매 번호 저장: {json_path}")


# ── 연금복권 구매 수 저장 ───────────────────────────────
def save_pension_purchased_json(tickets: list[dict[str, int | str]], is_test: bool = False) -> None:
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    filename = "pension_purchased.test.json" if is_test else "pension_purchased.json"
    json_path = os.path.join(data_dir, filename)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "test": is_test,
                "tickets": tickets,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"💾 연금복권 구매 수 저장: {json_path}")


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
    pension_total = settings.get("pension_tickets", 0)
    needed = (total + pension_total) * 1000

    print(f"🚀 로또 자동 구매 시작 | 로또 {total}장 / 연금복권 {pension_total}장")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🖥  headless={'True (CI)' if IS_CI else 'False (로컬)'}")
    if DRY_RUN:
        print("🧪 DRY_RUN 활성화: 구매 버튼 클릭 없이 선택 흐름만 테스트합니다.")

    if total + pension_total <= 0:
        print("⚠️  구매할 장수가 0장이라 실행을 종료합니다.")
        return

    # 로또와 연금복권 구매 금액을 합쳐서 예치금을 먼저 확인한다.
    if needed > 0:
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
                await _login(page)
                await _check_balance(page, needed)
            finally:
                await browser.close()

    purchased = []
    if total > 0:
        numbers = await select_numbers(total)
        purchased = await buy_lotto(numbers, dry_run=DRY_RUN)
        save_purchased_json(purchased, is_test=DRY_RUN)
        if not DRY_RUN:
            write_summary(purchased)
            notify_purchase(purchased)

    if pension_total > 0:
        pension_purchased = await buy_pension_lotto(pension_total, dry_run=DRY_RUN)
        save_pension_purchased_json(pension_purchased, is_test=DRY_RUN)
        if not DRY_RUN:
            notify_pension_purchase(pension_purchased)


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

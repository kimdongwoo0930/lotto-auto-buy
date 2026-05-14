"""
동행복권 자동 구매 스크립트 (dhapi 기반)
"""

import os
import json
import asyncio
import re
import subprocess
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from number_selector import select_numbers
from kakao_notify import notify_purchase, notify_pension_purchase, notify_error

IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() not in {"0", "false", "no", "n"}
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


class InsufficientBalanceError(Exception):
    pass


def load_settings() -> dict:
    settings_path = os.path.join(os.path.dirname(__file__), "..", "settings.json")
    with open(settings_path, "r", encoding="utf-8") as f:
        content = "\n".join(
            line for line in f.read().splitlines()
            if not line.strip().startswith("//")
        )
    settings = json.loads(content)
    settings.setdefault("total_tickets", 1)
    return settings


def _run_dhapi(*args: str) -> str:
    """dhapi CLI 실행 후 출력 반환"""
    cmd = ["dhapi"] + list(args)
    print(f"▶ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise Exception(f"dhapi 실패 (code={result.returncode}): {output}")
    return output


def check_balance() -> int:
    """예치금 확인 (원 단위 반환)"""
    output = _run_dhapi("show-balance")
    print(f"💰 잔액 조회: {output}")

    # "10,000" 또는 "10000" 형태에서 가장 큰 숫자를 잔액으로 사용
    matches = re.findall(r"\d[\d,]*", output)
    values = [int(m.replace(",", "")) for m in matches if m.replace(",", "").isdigit()]
    return max(values) if values else 0

# 구매 후 출력한 텍스트에서 번호를 가져오기
def _parse_purchased_numbers(output: str) -> list[list[int]]:
    """dhapi 출력에서 구매 번호(6개) 파싱"""
    results = []
    for line in output.split("\n"):
        # 1~45 범위의 숫자만 추출
        nums = [int(n) for n in re.findall(r"\b(\d{1,2})\b", line) if 1 <= int(n) <= 45]
        if len(nums) == 6:
            results.append(sorted(nums))
    return results


def buy_lotto(numbers: list[list[int]], dry_run: bool = False) -> list[list[int]]:
    """dhapi로 로또 구매"""
    count = len(numbers)
    if count <= 0:
        return []

    if dry_run:
        print("🧪 DRY_RUN 활성화 → 실제 구매 없음")
        for i, nums in enumerate(numbers):
            print(f"   {i+1}게임: {nums}")
        return numbers

    print(f"\n🎰 dhapi로 로또 {count}장 구매 중...")

    # AI 추천 번호를 수동모드로 구매: '4,15,23,31,38,42' 형태로 전달
    args = ["buy-lotto645"] + [",".join(str(n) for n in nums) for nums in numbers] + ["-y"]
    output = _run_dhapi(*args)
    print(f"📋 구매 결과:\n{output}")
    purchased = _parse_purchased_numbers(output)
    return purchased if purchased else numbers


def _get_auth_controller():
    """win720.AuthController로 동행복권 로그인"""
    import configparser
    from win720 import AuthController  # noqa: PLC0415

    # 환경변수 우선, 없으면 ~/.dhapi/credentials 파일
    lotto_id = os.environ.get("LOTTO_ID", "")
    lotto_pw = os.environ.get("LOTTO_PW", "")

    if not (lotto_id and lotto_pw):
        creds = configparser.ConfigParser()
        creds.read(os.path.expanduser("~/.dhapi/credentials"))
        if "default" in creds:
            lotto_id = creds["default"].get("username", "")
            lotto_pw = creds["default"].get("password", "")

    if not (lotto_id and lotto_pw):
        raise ValueError("LOTTO_ID / LOTTO_PW를 환경변수 또는 ~/.dhapi/credentials에서 찾을 수 없습니다")

    auth_ctrl = AuthController()
    auth_ctrl.login(lotto_id, lotto_pw)
    return auth_ctrl, lotto_id


def buy_pension_lotto(count: int, dry_run: bool = False) -> list[dict]:
    """win720.py를 이용한 연금복권 구매 (조 1~count, 동일 번호)"""
    if count <= 0:
        return []

    count = min(count, 5)

    if dry_run:
        print(f"🧪 DRY_RUN → 연금복권 {count}장 구매 없음")
        return [{"group": i, "number": "000000"} for i in range(1, count + 1)]

    print(f"\n💸 연금복권 {count}장 구매 중...")

    from win720 import Win720  # noqa: PLC0415

    auth_ctrl, lotto_id = _get_auth_controller()
    win720 = Win720()
    result = win720.buy_Win720(auth_ctrl, lotto_id, count=count)

    tickets = result.get("purchased_tickets")
    if not tickets:
        raise Exception("연금복권 구매 결과에서 티켓 정보를 가져올 수 없습니다")

    for t in tickets:
        print(f"   {t['group']}조 {t['number']}")
    print(f"   ✅ 연금복권 {len(tickets)}장 구매 완료!")
    return tickets


def save_purchased_json(numbers: list[list[int]], is_test: bool = False) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    filename = "purchased.test.json" if is_test else "purchased.json"
    json_path = os.path.join(DATA_DIR, filename)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"date": datetime.now(KST).strftime("%Y-%m-%d"), "test": is_test, "numbers": numbers},
            f, ensure_ascii=False, indent=2,
        )
    print(f"💾 구매 번호 저장: {json_path}")


def save_pension_purchased_json(tickets: list[dict], is_test: bool = False) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    filename = "pension_purchased.test.json" if is_test else "pension_purchased.json"
    json_path = os.path.join(DATA_DIR, filename)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"date": datetime.now(KST).strftime("%Y-%m-%d"), "test": is_test, "tickets": tickets},
            f, ensure_ascii=False, indent=2,
        )
    print(f"💾 연금복권 구매 저장: {json_path}")


def write_summary(numbers: list[list[int]]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"## 🎰 로또 구매 완료 ({datetime.now(KST).strftime('%Y-%m-%d')})\n\n")
            f.write("| 게임 | 번호 |\n|------|------|\n")
            for i, nums in enumerate(numbers):
                f.write(f"| {i+1} | {' - '.join(map(str, nums))} |\n")
            f.write(f"\n**총 {len(numbers)}장 구매**\n")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(f"purchased_numbers={json.dumps(numbers)}\n")


async def main() -> None:
    settings = load_settings()

    # 워크플로우별로 구매 대상 제어 (BUY_LOTTO645=false 또는 BUY_PENSION=false)
    buy_lotto645 = os.environ.get("BUY_LOTTO645", "true").strip().lower() != "false"
    buy_pension  = os.environ.get("BUY_PENSION",  "true").strip().lower() != "false"

    total   = settings.get("total_tickets",   5) if buy_lotto645 else 0
    pension = settings.get("pension_tickets", 0) if buy_pension  else 0

    print(f"🚀 로또 자동 구매 시작 | 로또 {total}장 / 연금복권 {pension}장")
    print(f"⏰ {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
    if DRY_RUN:
        print("🧪 DRY_RUN 활성화: 실제 구매 없이 흐름만 테스트합니다.")

    if total + pension <= 0:
        print("⚠️  구매할 장수가 0장이라 실행을 종료합니다.")
        return

    # 예치금 확인 (DRY_RUN이 아닐 때만)
    if not DRY_RUN:
        try:
            balance = check_balance()
            needed = (total + pension) * 1000
            print(f"💰 예치금: {balance:,}원 | 필요금액: {needed:,}원")
            if balance < needed:
                raise InsufficientBalanceError(
                    f"예치금 부족! 현재: {balance:,}원 / 필요: {needed:,}원\n"
                    f"동행복권 사이트에서 {needed - balance:,}원 이상 충전해주세요."
                )
        except InsufficientBalanceError:
            raise
        except Exception as e:
            print(f"⚠️  예치금 확인 실패 ({e}) → 구매를 계속 진행합니다.")

    # ── 로또 6/45 구매
    if total > 0:
        numbers = await select_numbers(total)
        purchased = buy_lotto(numbers, dry_run=DRY_RUN)
        save_purchased_json(purchased, is_test=DRY_RUN)
        if not DRY_RUN:
            write_summary(purchased)
            notify_purchase(purchased)

    # ── 연금복권720+ 구매
    if pension > 0:
        try:
            pension_purchased = buy_pension_lotto(pension, dry_run=DRY_RUN)
            save_pension_purchased_json(pension_purchased, is_test=DRY_RUN)
            if not DRY_RUN:
                notify_pension_purchase(pension_purchased)
        except Exception as e:
            print(f"⚠️  연금복권 구매 실패: {e}")
            notify_error(f"💸 연금복권 구매 실패\n\n{e}")

    print(f"\n🎉 완료! (로또 {total}장 / 연금복권 {pension}장)")


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

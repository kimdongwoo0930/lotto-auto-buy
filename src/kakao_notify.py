"""
카카오톡 알림 모듈
- 액세스 토큰 자동 갱신 (리프레시 토큰 사용)
- 구매 완료 알림
- 당첨 결과 알림
- 오류 알림
"""

import os
import json
import httpx
from datetime import datetime

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
KAKAO_REFRESH_TOKEN = os.environ.get("KAKAO_REFRESH_TOKEN", "")


def refresh_access_token() -> str:
    """리프레시 토큰으로 액세스 토큰 갱신"""
    if not KAKAO_REST_API_KEY or not KAKAO_REFRESH_TOKEN:
        print("⚠️  카카오 키 없음 → 알림 스킵")
        return ""

    resp = httpx.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": KAKAO_REST_API_KEY,
            "refresh_token": KAKAO_REFRESH_TOKEN,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    data = resp.json()

    if "access_token" not in data:
        print(f"⚠️  토큰 갱신 실패: {data}")
        return ""

    print("✅ 카카오 액세스 토큰 갱신 완료")
    return data["access_token"]


def send_message(text: str) -> bool:
    """카카오 나에게 보내기"""
    access_token = refresh_access_token()
    if not access_token:
        return False

    template = json.dumps({
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": "https://dhlottery.co.kr",
            "mobile_web_url": "https://m.dhlottery.co.kr"
        }
    }, ensure_ascii=False)

    resp = httpx.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": template},
        timeout=10,
    )

    if resp.status_code == 200:
        print("📱 카카오톡 알림 전송 완료!")
        return True
    else:
        print(f"⚠️  카카오 전송 실패: {resp.status_code} {resp.text}")
        return False


def notify_purchase(numbers: list[list[int]]):
    """구매 완료 알림"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "🎰 로또 구매 완료!",
        f"📅 {now}",
        f"🎟️ 총 {len(numbers)}장",
        "--------------------",
    ]
    for i, nums in enumerate(numbers):
        num_str = "  ".join(f"{n:02d}" for n in nums)
        lines.append(f"{i+1}게임: {num_str}")

    lines += [
        "--------------------",
        "🍀 이번 주도 대박 기원!",
        "추첨: 토요일 20:35",
    ]
    send_message("\n".join(lines))


def notify_pension_purchase(tickets: list[dict[str, int | str]]):
    """연금복권 구매 완료 알림"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "💸 연금복권 구매 완료!",
        f"📅 {now}",
        f"🎟️ 총 {len(tickets)}장",
        "--------------------",
        "🍀 이번 주도 대박 기원!",
    ]
    for i, ticket in enumerate(tickets):
        lines.append(f"{i+1}게임: {ticket['group']}조 {ticket['number']}")
    send_message("\n".join(lines))


def notify_result(
    purchased: list[list[int]],
    winning: list[int],
    bonus: int,
    draw_no: int,
):
    """당첨 결과 알림"""
    rank_labels = {
        1: "🥇 1등!!!",
        2: "🥈 2등!!",
        3: "🥉 3등!",
        4: "4등",
        5: "5등 (5,000원)",
        0: "😢 낙첨",
    }

    results = []
    has_win = False

    for i, nums in enumerate(purchased):
        match_main = len(set(nums) & set(winning))
        match_bonus = bonus in nums

        if match_main == 6:
            rank = 1
        elif match_main == 5 and match_bonus:
            rank = 2
        elif match_main == 5:
            rank = 3
        elif match_main == 4:
            rank = 4
        elif match_main == 3:
            rank = 5
        else:
            rank = 0

        if rank > 0:
            has_win = True

        num_str = "  ".join(f"{n:02d}" for n in nums)
        results.append(f"{i+1}게임 {rank_labels[rank]}\n   {num_str}")

    winning_str = "  ".join(f"{n:02d}" for n in winning)
    header = "🎊 당첨됐어요!!!" if has_win else "😢 이번 주는 아쉽네요"

    lines = [
        f"🎰 제{draw_no}회 당첨 결과",
        f"당첨번호: {winning_str}",
        f"보너스:   {bonus:02d}",
        "--------------------",
        header,
        "--------------------",
    ] + results + [
        "--------------------",
        "👉 dhlottery.co.kr",
    ]
    send_message("\n".join(lines))


def notify_pension_result(
    tickets: list[dict[str, int | str]],
    winning_group: int,
    winning_number: str,
    bonus_number: str,
    draw_no: int | None = None,
):
    """연금복권 당첨 결과 알림"""
    rank_labels = {
        "1": "🥇 1등",
        "2": "🥈 2등",
        "bonus": "🎁 보너스",
        "3": "3등",
        "4": "4등",
        "5": "5등",
        "6": "6등",
        "7": "7등",
        "0": "😢 낙첨",
    }

    def calc_rank(ticket: dict[str, int | str]) -> str:
        group = int(ticket["group"])
        number = str(ticket["number"])

        if group == winning_group and number == winning_number:
            return "1"
        if number == bonus_number:
            return "bonus"
        if number == winning_number:
            return "2"

        match_count = 0
        for ticket_digit, winning_digit in zip(reversed(number), reversed(winning_number)):
            if ticket_digit != winning_digit:
                break
            match_count += 1

        suffix_ranks = {5: "3", 4: "4", 3: "5", 2: "6", 1: "7"}
        return suffix_ranks.get(match_count, "0")

    results = []
    has_win = False

    for i, ticket in enumerate(tickets):
        rank = calc_rank(ticket)
        if rank != "0":
            has_win = True
        results.append(f"{i+1}게임 {rank_labels[rank]}\n   {ticket['group']}조 {ticket['number']}")

    title = f"💸 연금복권 제{draw_no}회 결과" if draw_no else "💸 연금복권 당첨 결과"
    header = "🎊 당첨됐어요!!!" if has_win else "😢 이번 주는 아쉽네요"
    lines = [
        title,
        f"1등: {winning_group}조 {winning_number}",
        f"보너스: {bonus_number}",
        "--------------------",
        header,
        "--------------------",
    ] + results + [
        "--------------------",
        "👉 dhlottery.co.kr",
    ]
    send_message("\n".join(lines))


def notify_error(message: str):
    """오류 알림"""
    text = "\n".join([
        "❌ 로또 자동구매 오류 발생",
        "--------------------",
        message,
        "--------------------",
        "GitHub Actions 로그를 확인하세요.",
    ])
    send_message(text)

"""
연금복권720+ 자동 구매 모듈
원본: https://github.com/roeniss/dhlottery-api (기여자 코드 기반)
dhapi 패키지의 내부 모듈(auth, HttpClient, common)을 경로 주입으로 사용
"""

import importlib.util
import sys

# dhapi 패키지 내부 모듈(auth, HttpClient, common)을 직접 import하기 위해 경로 주입
_spec = importlib.util.find_spec("dhapi")
if _spec and _spec.submodule_search_locations:
    _dhapi_path = list(_spec.submodule_search_locations)[0]
    if _dhapi_path not in sys.path:
        sys.path.insert(0, _dhapi_path)

import json
import random
import datetime
import base64
import requests

from bs4 import BeautifulSoup as BS
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes

from HttpClient import HttpClientSingleton
import auth
import re
import logging
import time

logger = logging.getLogger(__name__)


class Win720:

    keySize = 128
    iterationCount = 1000
    BlockSize = 16
    keyCode = ""

    _pad = lambda self, s: s + (self.BlockSize - len(s) % self.BlockSize) * chr(self.BlockSize - len(s) % self.BlockSize)
    _unpad = lambda self, s: s[:-ord(s[len(s)-1:])]

    _REQ_HEADERS = {
        "User-Agent": auth.USER_AGENT,
        "Connection": "keep-alive",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "Origin": "https://el.dhlottery.co.kr",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Referer": "https://el.dhlottery.co.kr/game/pension720/game.jsp",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "sec-ch-ua-platform": '"Windows"',
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ko,ko-KR;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-Requested-With": "XMLHttpRequest"
    }

    def __init__(self):
        self.http_client = HttpClientSingleton.get_instance()

    def buy_Win720(
        self,
        auth_ctrl: auth.AuthController,
        username: str,
        count: int = 5,
    ) -> dict:
        """
        연금복권 구매
        count: 구매할 장수 (1~5). 조 1번부터 count번까지 동일 번호로 구매.
        반환값에 purchased_number(6자리 문자열)와 purchased_tickets 포함.
        """
        assert isinstance(auth_ctrl, auth.AuthController)
        count = max(1, min(5, count))

        jsessionid = auth_ctrl.get_current_session_id()
        self.keyCode = jsessionid

        win720_round = self._get_round()
        makeAutoNum_ret = self._makeAutoNumbers(auth_ctrl, win720_round)

        try:
            q_val = json.loads(makeAutoNum_ret)['q']
        except json.JSONDecodeError:
            raise ValueError(f"makeAutoNum 응답 파싱 실패: {makeAutoNum_ret[:100]}...")

        decrypted = self._decText(q_val)

        if "resultMsg" in decrypted and ":" in decrypted:
            decrypted = re.sub(r'("resultMsg":\s*)([^",}]*)([,}])', r'\1"\2"\3', decrypted)

        try:
            extracted_num = json.loads(decrypted).get("selLotNo", "")
        except ValueError:
            raise ValueError(f"복호화 결과 파싱 실패: {repr(decrypted)[:500]}...")

        if not extracted_num:
            return json.loads(decrypted)

        groups = sorted(random.sample(range(1, 6), count))

        orderNo, orderDate = self._doOrderRequest(auth_ctrl, win720_round, extracted_num)
        body = json.loads(self._doConnPro(
            auth_ctrl, win720_round, extracted_num, username, orderNo, orderDate, groups
        ))

        self._show_result(body)
        body['round'] = win720_round
        body['purchased_number'] = extracted_num
        body['purchased_tickets'] = [
            {"group": g, "number": extracted_num} for g in groups
        ]
        return body

    def _generate_req_headers(self, auth_ctrl: auth.AuthController) -> dict:
        assert isinstance(auth_ctrl, auth.AuthController)
        return auth_ctrl.add_auth_cred_to_headers(self._REQ_HEADERS)

    def _get_round(self) -> str:
        try:
            res = self.http_client.get(
                "https://www.dhlottery.co.kr/common.do?method=main",
                headers=self._REQ_HEADERS
            )
            soup = BS(res.text, "html5lib")
            found = soup.find("strong", id="drwNo720")
            if found:
                return str(int(found.text) - 1)
            raise ValueError("drwNo720 not found")
        except Exception:
            base_date = datetime.datetime(2024, 12, 26)
            base_round = 244
            today = datetime.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
            days_ahead = (3 - today.weekday()) % 7
            next_thursday = today + datetime.timedelta(days=days_ahead)
            weeks = (next_thursday - base_date).days // 7
            return str(base_round + weeks - 1)

    def _makeAutoNumbers(self, auth_ctrl: auth.AuthController, win720_round: str) -> str:
        payload = "ROUND={}&round={}&LT_EPSD={}&SEL_NO=&BUY_CNT=&AUTO_SEL_SET=SA&SEL_CLASS=&BUY_TYPE=A&ACCS_TYPE=01".format(
            win720_round, win720_round, win720_round
        )
        headers = self._generate_req_headers(auth_ctrl)
        data = {"q": requests.utils.quote(self._encText(payload))}

        for attempt in range(5):
            try:
                res = self.http_client.post(
                    url="https://el.dhlottery.co.kr/makeAutoNo.do",
                    headers=headers,
                    data=data
                )
                res.raise_for_status()
                return res.text
            except requests.RequestException as e:
                if attempt < 4:
                    logger.warning(f"[재시도 {attempt+1}/5] makeAutoNo: {e}")
                    time.sleep(2)
                else:
                    raise

    def _doOrderRequest(self, auth_ctrl: auth.AuthController, win720_round: str, extracted_num: str) -> tuple[str, str]:
        payload = "ROUND={}&round={}&LT_EPSD={}&AUTO_SEL_SET=SA&SEL_CLASS=&SEL_NO={}&BUY_TYPE=M&BUY_CNT=5".format(
            win720_round, win720_round, win720_round, extracted_num
        )
        headers = self._generate_req_headers(auth_ctrl)
        data = {"q": requests.utils.quote(self._encText(payload))}

        for attempt in range(5):
            try:
                res = self.http_client.post(
                    url="https://el.dhlottery.co.kr/makeOrderNo.do",
                    headers=headers,
                    data=data
                )
                res.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt < 4:
                    logger.warning(f"[재시도 {attempt+1}/5] makeOrderNo: {e}")
                    time.sleep(2)
                else:
                    raise

        try:
            ret = json.loads(self._decText(json.loads(res.text)['q']))
            return ret['orderNo'], ret['orderDate']
        except (json.JSONDecodeError, KeyError) as err:
            raise ValueError(f"doOrderRequest 파싱 실패: {res.text[:100]}...") from err

    def _doConnPro(
        self,
        auth_ctrl: auth.AuthController,
        win720_round: str,
        extracted_num: str,
        username: str,
        orderNo: str,
        orderDate: str,
        groups: list[int],
    ) -> str:
        count = len(groups)
        buy_no = "".join(["{}{}%2C".format(g, extracted_num) for g in groups])[:-3]
        buy_set_type = "%2C".join(["SA"] * count)
        buy_type = "%2C".join(["A"] * count) + "%2C"

        payload = (
            "ROUND={}&FLAG=&BUY_KIND=01&BUY_NO={}&BUY_CNT={}"
            "&BUY_SET_TYPE={}&BUY_TYPE={}&CS_TYPE=01"
            "&orderNo={}&orderDate={}&TRANSACTION_ID=&WIN_DATE="
            "&USER_ID={}&PAY_TYPE=&resultErrorCode=&resultErrorMsg="
            "&resultOrderNo=&WORKING_FLAG=true&NUM_CHANGE_TYPE="
            "&auto_process=N&set_type=SA&classnum=&selnum=&buytype=M"
            "&num1=&num2=&num3=&num4=&num5=&num6=&DSEC=34&CLOSE_DATE="
            "&verifyYN=N&curdeposit=&curpay={}&DROUND={}&DSEC=0"
            "&CLOSE_DATE=&verifyYN=N&lotto720_radio_group=on"
        ).format(
            win720_round, buy_no, count,
            buy_set_type, buy_type,
            orderNo, orderDate,
            username, count * 1000, win720_round
        )

        headers = self._generate_req_headers(auth_ctrl)
        data = {"q": requests.utils.quote(self._encText(payload))}

        for attempt in range(5):
            try:
                res = self.http_client.post(
                    url="https://el.dhlottery.co.kr/connPro.do",
                    headers=headers,
                    data=data
                )
                res.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt < 4:
                    logger.warning(f"[재시도 {attempt+1}/5] connPro: {e}")
                    time.sleep(2)
                else:
                    raise

        try:
            return self._decText(json.loads(res.text)['q'])
        except (json.JSONDecodeError, KeyError) as err:
            raise ValueError(f"doConnPro 파싱 실패: {res.text[:100]}...") from err

    def _encText(self, plainText: str) -> str:
        encSalt = get_random_bytes(32)
        encIV = get_random_bytes(16)
        passPhrase = self.keyCode[:32]
        encKey = PBKDF2(passPhrase, encSalt, self.BlockSize, count=self.iterationCount, hmac_hash_module=SHA256)
        aes = AES.new(encKey, AES.MODE_CBC, encIV)
        plainText = self._pad(plainText).encode('utf-8')
        return "{}{}{}".format(
            bytes.hex(encSalt),
            bytes.hex(encIV),
            base64.b64encode(aes.encrypt(plainText)).decode('utf-8')
        )

    def _decText(self, encText: str) -> str:
        decSalt = bytes.fromhex(encText[0:64])
        decIv = bytes.fromhex(encText[64:96])
        cryptText = encText[96:]
        passPhrase = self.keyCode[:32]
        decKey = PBKDF2(passPhrase, decSalt, self.BlockSize, count=self.iterationCount, hmac_hash_module=SHA256)
        aes = AES.new(decKey, AES.MODE_CBC, decIv)
        decrypted_bytes = self._unpad(aes.decrypt(base64.b64decode(cryptText)))
        try:
            return decrypted_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return decrypted_bytes.decode('euc-kr')
            except UnicodeDecodeError:
                return f'{{"resultMsg": "복호화 실패 (Raw: {decrypted_bytes.hex()[:20]}...)"}}'

    def _show_result(self, body: dict) -> None:
        assert isinstance(body, dict)
        if body.get("loginYn") != "Y":
            return
        result = body.get("result", {})
        if result.get("resultMsg", "FAILURE").upper() != "SUCCESS":
            return

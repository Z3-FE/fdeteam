"""短信验证码：用阿里云号码认证服务（Dypnsapi）的 SendSmsVerifyCode 发，验证码由阿里云生成，
后端拿不到明文，校验走 CheckSmsVerifyCode。没配阿里云时由 main 在本地生成验证码、打印到日志、本地校验，方便开发联调。
AccessKey 只放后端 .env，验证码和 AccessKey 都不进日志。"""
import json
import logging
from functools import lru_cache
from typing import Optional

from .config import get_settings

logger = logging.getLogger("qb")

ENDPOINT = "dypnsapi.aliyuncs.com"
# 前端只收 6 位数字验证码
CODE_LENGTH = 6
CODE_TYPE_DIGITS = 1
# 再发一条时旧验证码作废
DUPLICATE_OVERWRITE = 1

# 阿里云的频控错误码 → 返回给前端的 429 原因
_LIMIT_CODES = {
    "FREQUENCY_FAIL": "cooldown",
    "biz.FREQUENCY": "cooldown",
    "BUSINESS_LIMIT_CONTROL": "daily_limit",
}
# 核验时表示"验证码不对"的错误码
_VERIFY_FAIL_CODES = {"isv.ValidateFail"}


class SmsError(Exception):
    pass


class SmsLimited(SmsError):
    """阿里云侧频控拦住了，reason 是 cooldown 或 daily_limit。"""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def sms_configured() -> bool:
    s = get_settings()
    return all((s.aliyun_access_key_id, s.aliyun_access_key_secret, s.sms_sign_name, s.sms_template_code))


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "****"


@lru_cache
def _client():
    # 延迟导入：没配短信时不需要装阿里云 SDK 也能跑
    from alibabacloud_dypnsapi20170525.client import Client
    from alibabacloud_tea_openapi import models as open_api_models

    s = get_settings()
    config = open_api_models.Config(
        access_key_id=s.aliyun_access_key_id,
        access_key_secret=s.aliyun_access_key_secret,
        endpoint=ENDPOINT,
        connect_timeout=5000,
        read_timeout=10000,
    )
    return Client(config)


def _runtime():
    from alibabacloud_tea_util import models as util_models

    return util_models.RuntimeOptions(connect_timeout=5000, read_timeout=10000)


def _describe(exc: Exception) -> SmsError:
    """把 SDK 异常转成 SmsError，只保留阿里云的错误码、说明和诊断建议。"""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or type(exc).__name__
    data = getattr(exc, "data", None)
    recommend = data.get("Recommend") if isinstance(data, dict) else None
    detail = f"Code={code} Message={message}" + (f" Recommend={recommend}" if recommend else "")
    if code in _LIMIT_CODES:
        return SmsLimited(_LIMIT_CODES[code], detail)
    return SmsError(detail)


def _check_body(code: Optional[str], message: Optional[str]) -> None:
    if code != "OK":
        detail = f"Code={code} Message={message}"
        if code in _LIMIT_CODES:
            raise SmsLimited(_LIMIT_CODES[code], detail)
        raise SmsError(detail)


async def send_verify_code(phone: str, valid_seconds: int, interval_seconds: int) -> None:
    """让阿里云生成并发送验证码；失败抛 SmsError，频控拦住抛 SmsLimited。"""
    from alibabacloud_dypnsapi20170525 import models as dypns_models

    s = get_settings()
    request = dypns_models.SendSmsVerifyCodeRequest(
        phone_number=phone,
        sign_name=s.sms_sign_name,
        template_code=s.sms_template_code,
        # ##code## 由阿里云替换成生成的验证码，min 是短信里写的有效分钟数
        template_param=json.dumps(
            {"code": "##code##", "min": str(max(1, valid_seconds // 60))}, separators=(",", ":")
        ),
        code_length=CODE_LENGTH,
        code_type=CODE_TYPE_DIGITS,
        valid_time=valid_seconds,
        interval=interval_seconds,
        duplicate_policy=DUPLICATE_OVERWRITE,
    )
    try:
        resp = await _client().send_sms_verify_code_with_options_async(request, _runtime())
    except Exception as exc:  # SDK 的网络和接口错误都从这里出来
        raise _describe(exc) from exc
    body = resp.body
    _check_body(getattr(body, "code", None), getattr(body, "message", None))


async def check_verify_code(phone: str, code: str) -> bool:
    """用 CheckSmsVerifyCode 校验阿里云发出的验证码。只有 Model.VerifyResult 为 PASS 才算对；
    接口调用本身失败抛 SmsError。"""
    from alibabacloud_dypnsapi20170525 import models as dypns_models

    request = dypns_models.CheckSmsVerifyCodeRequest(phone_number=phone, verify_code=code)
    try:
        resp = await _client().check_sms_verify_code_with_options_async(request, _runtime())
    except Exception as exc:
        # 验证码错误时阿里云不返回 VerifyResult，而是抛 400 isv.ValidateFail，按"不通过"处理
        if getattr(exc, "code", None) in _VERIFY_FAIL_CODES:
            return False
        raise _describe(exc) from exc
    body = resp.body
    _check_body(getattr(body, "code", None), getattr(body, "message", None))
    model = getattr(body, "model", None)
    return getattr(model, "verify_result", None) == "PASS"

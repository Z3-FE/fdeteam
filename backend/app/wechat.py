"""微信小程序登录：用 wx.login 拿到的 code 换 openid。AppSecret 只在后端用。"""
import logging
from typing import Optional

import httpx

from .config import get_settings

logger = logging.getLogger("qb")

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatLoginError(Exception):
    pass


def login_configured() -> bool:
    s = get_settings()
    return bool(s.wx_appid and s.wx_secret)


async def code2session(code: str) -> str:
    """返回 openid；code 无效或微信接口出错抛 WechatLoginError。session_key 用不上，不保存。"""
    s = get_settings()
    params = {
        "appid": s.wx_appid,
        "secret": s.wx_secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(CODE2SESSION_URL, params=params)
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WechatLoginError(f"code2session request failed: {exc}") from exc
    openid: Optional[str] = data.get("openid")
    if not openid:
        # 只记错误码，不记 code 和返回体里的 session_key
        raise WechatLoginError(f"code2session errcode={data.get('errcode')} errmsg={data.get('errmsg')}")
    return openid

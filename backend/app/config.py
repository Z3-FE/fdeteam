import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.api_key: str = os.getenv("SILICONFLOW_API_KEY", "").strip()
        self.base_url: str = os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        ).rstrip("/")
        self.model_name: str = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V3").strip()
        self.db_path: str = os.getenv("DB_PATH", "./data/app.db").strip()
        self.request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "60"))

        # 微信小程序登录（换 openid）；不填则不登录，报告只能按设备上的会话找回
        self.wx_appid: str = os.getenv("WX_APPID", "").strip()
        self.wx_secret: str = os.getenv("WX_SECRET", "").strip()

        # 阿里云号码认证短信（保存报告时验证手机号）；四项都填才真发，否则验证码只打印在后端日志里。
        # AccessKey 也认阿里云 SDK 默认的 ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET
        self.aliyun_access_key_id: str = (
            os.getenv("ALIYUN_ACCESS_KEY_ID", "") or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
        ).strip()
        self.aliyun_access_key_secret: str = (
            os.getenv("ALIYUN_ACCESS_KEY_SECRET", "") or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
        ).strip()
        self.sms_sign_name: str = os.getenv("SMS_SIGN_NAME", "").strip()
        self.sms_template_code: str = os.getenv("SMS_TEMPLATE_CODE", "").strip()

        forced_mock = os.getenv("MOCK", "").strip().lower() in {"1", "true", "yes"}
        # 没有 key 一律走 mock，保证没配 key 也能把前后端跑通
        self.mock: bool = forced_mock or not self.api_key

        origins = os.getenv(
            "CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
        )
        self.cors_origins: list[str] = [o.strip() for o in origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

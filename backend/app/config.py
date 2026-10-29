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

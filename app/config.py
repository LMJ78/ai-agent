"""应用配置：统一从环境变量或 .env 读取。

所有可调参数都集中在这里，业务代码不要直接读 os.environ。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（.../ai-agent）
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# 默认把数据库放在项目内的 data 目录，避免「在哪个目录启动就生成到哪」。
DEFAULT_DATABASE_URL = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"


class Settings(BaseSettings):
    """对应 .env 里的键；大小写不敏感。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 应用
    app_name: str = "AI Agent"
    app_env: str = "dev"

    # 模型
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 数据库
    database_url: str = DEFAULT_DATABASE_URL

    # 生成参数（第 6 周做配额时还会用到 max_tokens）
    temperature: float = 0.7
    max_tokens: int = 800
    history_limit: int = 16


@lru_cache
def get_settings() -> Settings:
    """缓存一份配置，避免每次请求都重新读 .env。"""
    return Settings()


settings = get_settings()

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

    # 视觉模型：拍照讲题时用，走阿里云百炼的 OpenAI 兼容接口。
    # 不填也能启动，只是 /api/questions/upload 收到图片会返回 503。
    vision_api_key: str = ""
    vision_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vision_model: str = "qwen3-vl-plus"

    # 联网检索：W3 的 web_search 工具用 Tavily。
    # 不填也能启动，只是模型调用 web_search 时会收到「未配置」提示。
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    web_search_max_results: int = 5

    # 登录 / JWT（第 5 周）
    # 本地开发可以先用默认值；上线前必须在 .env 里换成随机长字符串。
    jwt_secret: str = "dev-only-change-me-please-set-JWT_SECRET"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # 数据库
    database_url: str = DEFAULT_DATABASE_URL

    # 待办提醒后台任务
    reminder_worker_enabled: bool = True
    reminder_scan_seconds: int = 30

    # 生成参数（第 6 周做配额时还会用到 max_tokens）
    temperature: float = 0.7
    max_tokens: int = 3000
    history_limit: int = 16

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """让项目根目录的 .env 优先于系统环境变量。

        否则机器上如果残留一个旧的 DEEPSEEK_API_KEY，会悄悄覆盖 .env，
        报 401 时很难查。顺序：初始化参数 > .env > 系统环境变量 > secrets。
        """
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)


@lru_cache
def get_settings() -> Settings:
    """缓存一份配置，避免每次请求都重新读 .env。"""
    return Settings()


settings = get_settings()

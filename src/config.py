from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    avito_client_id: str
    avito_client_secret: str
    avito_user_id: str | None
    poll_interval_seconds: int
    group_window_seconds: int
    avito_log_responses: bool
    avito_debug_fetch_all_chats: bool
    data_dir: str


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def load_config() -> Config:
    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    avito_client_id = os.getenv("AVITO_CLIENT_ID", "").strip()
    avito_client_secret = os.getenv("AVITO_CLIENT_SECRET", "").strip()
    avito_user_id = os.getenv("AVITO_USER_ID", "").strip() or None

    missing = []
    if not telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not avito_client_id:
        missing.append("AVITO_CLIENT_ID")
    if not avito_client_secret:
        missing.append("AVITO_CLIENT_SECRET")
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"Set required environment variables: {names}")

    return Config(
        telegram_bot_token=telegram_bot_token,
        avito_client_id=avito_client_id,
        avito_client_secret=avito_client_secret,
        avito_user_id=avito_user_id,
        poll_interval_seconds=_int_env("POLL_INTERVAL_SECONDS", 10, 5, 60),
        group_window_seconds=_int_env("GROUP_WINDOW_SECONDS", 10, 3, 60),
        avito_log_responses=_bool_env("AVITO_LOG_RESPONSES"),
        avito_debug_fetch_all_chats=_bool_env("AVITO_DEBUG_FETCH_ALL_CHATS"),
        data_dir=os.getenv("DATA_DIR", "./data").strip() or "./data",
    )

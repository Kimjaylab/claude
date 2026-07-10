import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Secrets:
    kis_app_key: str
    kis_app_secret: str
    kis_account_no: str
    kis_account_product_cd: str
    kis_env: str
    telegram_bot_token: str
    telegram_chat_id: str
    dart_api_key: str


def load_secrets(env_path: Path | None = None) -> Secrets:
    load_dotenv(env_path or PROJECT_ROOT / ".env")
    return Secrets(
        kis_app_key=os.environ.get("KIS_APP_KEY", ""),
        kis_app_secret=os.environ.get("KIS_APP_SECRET", ""),
        kis_account_no=os.environ.get("KIS_ACCOUNT_NO", ""),
        kis_account_product_cd=os.environ.get("KIS_ACCOUNT_PRODUCT_CD", "01"),
        kis_env=os.environ.get("KIS_ENV", "paper"),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        dart_api_key=os.environ.get("DART_API_KEY", ""),
    )


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_settings() -> dict:
    return load_yaml(PROJECT_ROOT / "config" / "settings.yaml")


def load_screening_rules() -> dict:
    return load_yaml(PROJECT_ROOT / "config" / "screening_rules.yaml")

from datetime import date

from pydantic_settings import BaseSettings


def default_season() -> int:
    """Return the current MLB season year.

    Before March, defaults to the previous year since drafts and
    spring training haven't started yet.
    """
    today = date.today()
    return today.year if today.month >= 3 else today.year - 1


class Settings(BaseSettings):
    yahoo_client_id: str = ""
    yahoo_client_secret: str = ""
    yahoo_league_id: str = ""
    yahoo_game_key: str = "mlb"
    database_url: str = "sqlite+aiosqlite:///./fantasy_baseball.db"
    anthropic_api_key: str = ""
    assistant_model: str = "claude-sonnet-4-20250514"
    assistant_max_tokens: int = 1024
    assistant_daily_token_limit: int = 500_000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

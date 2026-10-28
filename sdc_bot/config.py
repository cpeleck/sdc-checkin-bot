import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int
    database_path: str
    log_level: str

    @classmethod
    def from_env(cls):
        load_dotenv(Path.cwd() / ".env")
        token = os.getenv("DISCORD_TOKEN", "").strip()
        guild = os.getenv("DISCORD_GUILD_ID", "").strip()
        if not token or token == "replace-with-your-bot-token":
            raise ValueError("Set DISCORD_TOKEN in .env; see .env.example and README.md.")
        try:
            guild_id = int(guild)
            if guild_id <= 0:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Set DISCORD_GUILD_ID to your numeric Discord server ID.") from exc
        level = os.getenv("LOG_LEVEL", "INFO").upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
        path = str(Path(os.getenv("DATABASE_PATH", "data/sdc.sqlite3")).expanduser().resolve())
        return cls(token, guild_id, path, level)

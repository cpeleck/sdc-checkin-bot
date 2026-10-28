import pytest

from sdc_bot.config import Config


def test_missing_token_and_invalid_guild_fail_without_disclosing_token(monkeypatch):
    monkeypatch.setattr("sdc_bot.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ValueError, match="DISCORD_TOKEN"):
        Config.from_env()
    monkeypatch.setenv("DISCORD_TOKEN", "test-secret")
    monkeypatch.setenv("DISCORD_GUILD_ID", "bad")
    with pytest.raises(ValueError, match="DISCORD_GUILD_ID") as exc:
        Config.from_env()
    assert "test-secret" not in str(exc.value)


def test_configuration_defaults_and_invalid_log_level(monkeypatch):
    monkeypatch.setattr("sdc_bot.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("DISCORD_TOKEN", "test-secret")
    monkeypatch.setenv("DISCORD_GUILD_ID", "100")
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    config = Config.from_env()
    assert config.guild_id == 100 and config.database_path.endswith("data/sdc.sqlite3")
    monkeypatch.setenv("LOG_LEVEL", "INVALID")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Config.from_env()

import argparse
import logging

from .config import Config


def main():
    parser = argparse.ArgumentParser(description="SDC Discord project check-in bot")
    parser.add_argument(
        "--check-config", action="store_true", help="Validate .env without connecting"
    )
    args = parser.parse_args()
    try:
        config = Config.from_env()
    except ValueError as exc:
        parser.exit(2, f"Configuration error: {exc}\n")
    if args.check_config:
        print(f"Configuration valid: guild {config.guild_id}; database {config.database_path}")
        return
    from .discord_app import SDCBot

    logging.basicConfig(
        level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Keep library HTTP debugging from logging request data or sensitive responses.
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    bot = SDCBot(config)
    bot.run(config.token, log_handler=None)


if __name__ == "__main__":
    main()

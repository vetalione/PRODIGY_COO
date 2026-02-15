from __future__ import annotations

import logging

from app.bot import TelegramCooBot
from app.config import load_settings


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )

    settings = load_settings()
    bot = TelegramCooBot(settings)
    app = bot.build_app()
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()

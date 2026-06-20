import asyncio
import logging

from .bot import run_bot
from .config import load_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    asyncio.run(run_bot(config))


if __name__ == "__main__":
    main()

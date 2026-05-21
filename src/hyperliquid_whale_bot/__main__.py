"""Application entrypoint: `python -m hyperliquid_whale_bot`."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from .config import Settings
from .logging_setup import configure_logging, get_logger
from .service import Service


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]  # values come from env / .env
    configure_logging(settings.log_level)
    log = get_logger(__name__)

    service = Service(settings)

    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        log.info("service.shutdown_signal")
        service.watcher.stop()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            # Windows doesn't support add_signal_handler for these.
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _shutdown)

    try:
        await service.run()
    except* KeyboardInterrupt:
        log.info("service.interrupted")
    except* Exception as eg:  # noqa: BLE001 -- top-level entrypoint logs and exits cleanly
        for exc in eg.exceptions:
            log.error("service.fatal", error=repr(exc))
        sys.exit(1)


def run() -> None:
    """Sync entrypoint for the console script defined in pyproject.toml."""
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())


if __name__ == "__main__":
    run()

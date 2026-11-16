"""Event loop factory for uvicorn to ensure ProactorEventLoop is always used on Windows."""
from __future__ import annotations

import asyncio
from collections.abc import Callable


def proactor_loop_factory(use_subprocess: bool = False) -> Callable[[], asyncio.AbstractEventLoop]:
    return asyncio.ProactorEventLoop


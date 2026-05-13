"""项目入口。"""

from __future__ import annotations

import asyncio
import sys

from utils.console_encoding import ensure_utf8_console
ensure_utf8_console()

from cli.app import run_cli


def main() -> int:
    """同步入口。"""

    return asyncio.run(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())

import asyncio
import sys

from .cmd.main import main

sys.exit(asyncio.run(main()))

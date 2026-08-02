"""
runner.py

Application entry point.
"""

import asyncio

from automation.validator import DashboardValidator


async def main():
    """
    Execute complete dashboard validation.
    """

    validator = DashboardValidator()

    await validator.run_all()


if __name__ == "__main__":
    asyncio.run(main())
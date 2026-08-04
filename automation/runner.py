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

    try:
        await validator.run_all()
    except Exception as e:
        print(f"Fatal error during validation run: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Failed to start application: {e}")
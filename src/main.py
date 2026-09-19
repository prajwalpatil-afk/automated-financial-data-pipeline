"""Command-line entry point for the Stock Valuation Data Pipeline.

Usage:
    python src/main.py --ticker AAPL
    python src/main.py --ticker AAPL --refresh
"""

import argparse
from pathlib import Path
import sys

# Ensure project root is in sys.path when invoked directly as `python src/main.py`
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automated Financial Data Pipeline & Capital Markets Valuation Analytics",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        required=True,
        help="Stock ticker symbol to ingest, validate, value, and analyze (e.g. AAPL).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help="Force re-fetching of financial statements even if fundamentals are fresh (< 7 days).",
    )

    args = parser.parse_args()

    try:
        metrics = run_pipeline(ticker=args.ticker, force_refresh=args.refresh)
        val = metrics.get("valuation", {})
        print("\n" + "=" * 50)
        print(f"PIPELINE RUN COMPLETED: {metrics['ticker']}")
        print("=" * 50)
        print(f"Status:               {metrics['status']}")
        print(f"Records Inserted:     {metrics['records_inserted']}")
        print(f"Execution Time:       {metrics['execution_time_seconds']}s")
        if val:
            print(f"Current Market Price: ${val.get('current_price')}")
            print(f"DCF Intrinsic Value:  ${val.get('intrinsic_value')}")
            print(f"Upside / Downside:    {val.get('upside_pct')}%")
            print(f"Valuation Signal:     {val.get('signal')}")
        print("=" * 50)
        print("CSV reports updated in reports/ directory.")
        return 0
    except Exception as e:
        print(f"\n[ERROR] Pipeline run failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

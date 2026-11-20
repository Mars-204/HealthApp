"""Run a sync from the command line:  python scripts/run_sync.py [days_back]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from core.sync import run_sync

if __name__ == "__main__":
    load_dotenv()
    days = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = run_sync(days_back=days)
    print(f"Activities synced: {result['activities']}")
    print(f"Daily rows synced: {result['daily_days']}")
    print(f"Raw data saved:    {', '.join(result['raw_saved']) or 'none'}")
    for name, err in result["errors"].items():
        print(f"FAILED {name}: {err}")

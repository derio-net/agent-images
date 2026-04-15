#!/usr/bin/env python3
"""Compute the next fire time for a cron job by reading the crontab.

Usage: compute-next-run.py <script_pattern> [crontab_path]

Finds all crontab lines matching <script_pattern>, merges their schedules,
and prints the next fire time as a Unix timestamp.

Example:
    compute-next-run.py exercise-cron.sh
    # reads ~/.crontab, finds all exercise-cron.sh lines, prints next timestamp
"""

import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from croniter import croniter


def parse_crontab(path: str, pattern: str) -> list[str]:
    """Extract cron expressions from lines matching pattern."""
    expressions = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Skip environment variable assignments
            if re.match(r'^[A-Z_]+=', line):
                continue
            if pattern in line:
                parts = line.split()
                if len(parts) >= 6:
                    expressions.append(" ".join(parts[:5]))
    return expressions


def next_fire_time(expressions: list[str], now: datetime) -> datetime:
    """Find the earliest next fire time across multiple cron expressions."""
    candidates = []
    for expr in expressions:
        cron = croniter(expr, now)
        candidates.append(cron.get_next(datetime))
    return min(candidates)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <script_pattern> [crontab_path]", file=sys.stderr)
        sys.exit(1)

    pattern = sys.argv[1]
    crontab_path = sys.argv[2] if len(sys.argv) > 2 else str(Path.home() / ".crontab")

    expressions = parse_crontab(crontab_path, pattern)
    if not expressions:
        print(f"No crontab entries matching '{pattern}'", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    nxt = next_fire_time(expressions, now)
    print(int(nxt.timestamp()))


if __name__ == "__main__":
    main()

"""Fail unless every generated mutant was killed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MINIMUM_MUTANTS = 1000


def main() -> int:
    path = Path(sys.argv[1])
    stats = json.loads(path.read_text())
    killed, total = stats.get("killed", 0), stats.get("total", 0)
    failures = {name: value for name, value in stats.items() if name not in {"killed", "total"} and value}
    if total < MINIMUM_MUTANTS or killed != total or failures:
        print(
            f"Mutation gate failed: {killed}/{total} killed; required total>={MINIMUM_MUTANTS}; unresolved={failures}"
        )
        return 1
    print(f"Mutation gate passed: {killed}/{total} killed; 0 survived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

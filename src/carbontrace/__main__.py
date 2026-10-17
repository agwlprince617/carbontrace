"""Export all three offline demonstrations without starting a web server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from carbontrace.domain import CompareRequest, TaskId
from carbontrace.engine import build_comparison


def main(argv: list[str] | None = None) -> None:
    """Write reproducible fixture evidence; IDs and timestamps vary by run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/demo-evidence.json"))
    args = parser.parse_args(argv)
    tasks: tuple[TaskId, ...] = ("clamp", "discount", "merge")
    results = [
        build_comparison(CompareRequest(task_id=task)).model_dump(mode="json")
        for task in tasks
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(
        f"Saved {len(results)} offline comparisons to {args.output}. Live model calls: 0."
    )


if __name__ == "__main__":  # pragma: no cover
    main()

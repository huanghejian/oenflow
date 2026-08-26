from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline_service import compile_video_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("director_plan", type=Path)
    parser.add_argument("--tier", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--target-resolution", default="720P")
    args = parser.parse_args()

    plan = json.loads(args.director_plan.read_text(encoding="utf-8"))
    result = compile_video_plan(plan, args.tier, args.target_resolution)
    print(
        json.dumps(
            {
                "job_id": result["job_id"],
                "validation_ok": result["validation"]["ok"],
                "final_shots": len(result["final_video_plan"]["shots"]),
                "artifacts": result["artifacts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


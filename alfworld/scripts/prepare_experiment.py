"""Freeze the common unseen task set from the existing DeepSeek teacher run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiment_common import ROOT, latest_teacher_result, rows_from, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher-result", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "configs/fixed_task_ids.json")
    args = parser.parse_args()

    teacher_path = args.teacher_result or latest_teacher_result()
    rows = rows_from(teacher_path)
    task_ids = [row.get("task_id") for row in rows if row.get("task_id")]
    if not task_ids:
        raise ValueError(f"No task_id fields found in {teacher_path}")
    payload = {
        "source_teacher_result": str(teacher_path),
        "task_ids": task_ids,
        "count": len(task_ids),
    }
    write_json(args.output, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

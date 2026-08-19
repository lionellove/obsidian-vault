"""Create a deliberately shuffled teacher-skill control without task lookup."""

from __future__ import annotations

import argparse
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("skills/teacher_skill.md"))
    parser.add_argument("--output", type=Path, default=Path("skills/shuffled_teacher_skill.md"))
    args = parser.parse_args()
    lines = [line for line in args.source.read_text(encoding="utf-8").splitlines() if line.strip()]
    rng = random.Random(42)
    rng.shuffle(lines)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("# Shuffled teacher skill control\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

ANSWER_SUFFIX = "\n\nProvide ONLY the final answer, no explanation."
RESULTS_DIR = Path(__file__).parent / "results"


def build_prompt(task: dict, attachment_path: str | None = None) -> str:
    question = task["Question"]
    if attachment_path:
        return f"{question}\n\nAttached file: {attachment_path}{ANSWER_SUFFIX}"
    return f"{question}{ANSWER_SUFFIX}"

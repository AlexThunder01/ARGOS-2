from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from eval.scorer import question_scorer

ANSWER_SUFFIX = "\n\nProvide ONLY the final answer, no explanation."
RESULTS_DIR = Path(__file__).parent / "results"


def build_prompt(task: dict, attachment_path: str | None = None) -> str:
    question = task["Question"]
    if attachment_path:
        return f"{question}\n\nAttached file: {attachment_path}{ANSWER_SUFFIX}"
    return f"{question}{ANSWER_SUFFIX}"


def extract_answer(response: str) -> str:
    return response.strip()


def score_task(model_answer: str, ground_truth: str) -> bool:
    return question_scorer(extract_answer(model_answer), ground_truth)

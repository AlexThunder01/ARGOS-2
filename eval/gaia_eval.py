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


def _get_attachment_path(task: dict) -> str | None:
    if not task.get("file_name", ""):
        return None
    return task.get("file_path") or None


def run_eval(limit: int | None = None) -> None:
    from datasets import load_dataset

    from src.core.engine import CoreAgent

    dataset = load_dataset("gaia-benchmark/GAIA", "2023_level1", trust_remote_code=True)
    tasks = list(dataset["validation"])
    if limit:
        tasks = tasks[:limit]

    agent = CoreAgent(
        memory_mode="off",
        require_confirmation=False,
        inject_git_context=False,
    )

    results = []
    correct = 0
    total = len(tasks)
    start_time = datetime.now()
    error_types: dict[str, int] = {"numeric": 0, "list": 0, "string": 0}

    for i, task in enumerate(tasks, 1):
        task_id = task.get("task_id", str(i))
        ground_truth = task.get("Final answer", "")
        attachment_path = _get_attachment_path(task)
        prompt = build_prompt(task, attachment_path)

        task_result = agent.run_task(prompt)
        model_answer = extract_answer(task_result.response)
        is_correct = score_task(model_answer, ground_truth)

        from eval.scorer import is_float

        if is_float(ground_truth):
            atype = "numeric"
        elif any(c in ground_truth for c in [",", ";"]):
            atype = "list"
        else:
            atype = "string"

        if not is_correct:
            error_types[atype] += 1
        else:
            correct += 1

        results.append(
            {
                "id": task_id,
                "question": task["Question"],
                "expected": ground_truth,
                "got": model_answer,
                "correct": is_correct,
                "answer_type": atype,
            }
        )

        status = "✓" if is_correct else "✗"
        print(f"[{i}/{total}] {status}  {task['Question'][:60]}")

    elapsed = datetime.now() - start_time
    elapsed_s = elapsed.total_seconds()
    accuracy = correct / total if total else 0.0

    model_name = os.getenv("LLM_MODEL", "unknown")
    print(f"\nGAIA Level 1 — {model_name}")
    print(f"Tasks: {total}  |  Correct: {correct}  |  Accuracy: {accuracy:.1%}")
    avg_s = elapsed_s / total if total else 0
    mins, secs = divmod(int(elapsed_s), 60)
    print(f"Tempo totale: {mins}m {secs}s  |  Avg/task: {avg_s:.1f}s")
    print("\nTop errors:")
    for atype, count in sorted(error_types.items(), key=lambda x: -x[1]):
        print(f"  - {atype}: {count} wrong")

    RESULTS_DIR.mkdir(exist_ok=True)
    report_path = RESULTS_DIR / f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}.json"
    report = {
        "model": model_name,
        "date": datetime.now().isoformat(),
        "level": 1,
        "accuracy": round(accuracy, 4),
        "correct": correct,
        "total": total,
        "tasks": results,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GAIA Level 1 evaluation")
    parser.add_argument(
        "--limit", type=int, default=None, help="Run only first N tasks"
    )
    args = parser.parse_args()
    run_eval(limit=args.limit)

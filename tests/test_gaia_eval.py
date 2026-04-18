import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.gaia_eval import build_prompt

ANSWER_SUFFIX = "\n\nProvide ONLY the final answer, no explanation."


def test_build_prompt_no_attachment():
    task = {"Question": "What is 2+2?", "file_name": ""}
    result = build_prompt(task)
    assert result == f"What is 2+2?{ANSWER_SUFFIX}"


def test_build_prompt_with_attachment():
    task = {"Question": "Summarize the document.", "file_name": "report.pdf"}
    result = build_prompt(task, attachment_path="/tmp/report.pdf")
    assert "Summarize the document." in result
    assert "/tmp/report.pdf" in result
    assert ANSWER_SUFFIX in result


from eval.gaia_eval import extract_answer, score_task


def test_extract_answer_plain():
    assert extract_answer("The answer is Paris.") == "The answer is Paris."


def test_extract_answer_strips_whitespace():
    assert extract_answer("  42  ") == "42"


def test_score_task_correct():
    result = score_task(model_answer="Paris", ground_truth="Paris")
    assert result is True


def test_score_task_wrong():
    result = score_task(model_answer="London", ground_truth="Paris")
    assert result is False

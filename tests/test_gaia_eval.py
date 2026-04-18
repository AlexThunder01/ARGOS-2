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

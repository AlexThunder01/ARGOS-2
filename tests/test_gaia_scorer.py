import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.scorer import normalize_number_str, normalize_str, question_scorer


def test_exact_string_match():
    assert question_scorer("Paris", "Paris") is True


def test_case_insensitive_string():
    assert question_scorer("paris", "Paris") is True


def test_string_mismatch():
    assert question_scorer("London", "Paris") is False


def test_numeric_match():
    assert question_scorer("42", "42") is True


def test_numeric_with_currency():
    assert question_scorer("$1,234.56", "1234.56") is True


def test_numeric_mismatch():
    assert question_scorer("41", "42") is False


def test_list_match_comma():
    assert question_scorer("cat, dog", "cat, dog") is True


def test_list_match_order_insensitive():
    assert question_scorer("dog, cat", "cat, dog") is True


def test_list_mismatch():
    assert question_scorer("cat, fish", "cat, dog") is False


def test_normalize_str_removes_punct():
    assert normalize_str("Hello, World!") == "helloworld"


def test_normalize_number_removes_dollar():
    assert normalize_number_str("$1,234") == 1234.0


def test_list_match_semicolon():
    assert question_scorer("cat; dog", "cat; dog") is True


def test_list_mismatch_semicolon():
    assert question_scorer("cat; fish", "cat; dog") is False


def test_is_float_with_commas():
    from eval.scorer import is_float

    assert is_float("1,234.56") is True
    assert is_float("1,000") is True


def test_numeric_ground_truth_with_comma():
    assert question_scorer("1234.56", "1,234.56") is True

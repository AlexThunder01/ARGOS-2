import re
import string


def is_float(element) -> bool:
    try:
        float(element)
        return True
    except (ValueError, TypeError):
        return False


def normalize_number_str(number_str: str) -> float:
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    return float(number_str)


def split_string(s: str, char_list: list[str]) -> list[str]:
    pattern = f"[{''.join(re.escape(c) for c in char_list)}]"
    return [part.strip() for part in re.split(pattern, s)]


def normalize_str(input_str: str, remove_punct: bool = True) -> str:
    no_spaces = input_str.replace(" ", "")
    if remove_punct:
        no_spaces = no_spaces.translate(str.maketrans("", "", string.punctuation))
    return no_spaces.lower()


def question_scorer(model_answer: str, ground_truth: str) -> bool:
    if is_float(ground_truth):
        try:
            normalized = normalize_number_str(model_answer)
        except ValueError:
            return False
        return normalized == float(ground_truth)

    if any(char in ground_truth for char in [",", ";"]):
        delimiters = [","] if "," in ground_truth else [";"]
        gt_parts = split_string(ground_truth, delimiters)
        model_parts = split_string(model_answer, delimiters)
        if len(gt_parts) != len(model_parts):
            return False
        # Normalize all parts for comparison
        normalized_gt = {normalize_str(g) for g in gt_parts}
        normalized_model = {normalize_str(m) for m in model_parts}
        return normalized_gt == normalized_model

    return normalize_str(model_answer) == normalize_str(ground_truth)

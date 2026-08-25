import json
import re
from typing import Any, Dict, Iterator, List, Optional


def find_all_balanced_json(text: str) -> Iterator[str]:
    """
    Finds and yields all syntactically balanced JSON candidates {...} or [...] in text.
    Handles nested braces and ignores braces inside double-quoted strings.
    """
    if not text:
        return

    # First strip markdown code fences if wrapped around whole text
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    i = 0
    n = len(cleaned)
    while i < n:
        start_char = cleaned[i]
        if start_char in ("{", "["):
            end_char = "}" if start_char == "{" else "]"
            depth = 0
            in_string = False
            escape = False
            start_idx = i

            for j in range(start_idx, n):
                c = cleaned[j]

                if escape:
                    escape = False
                    continue

                if c == "\\":
                    escape = True
                    continue

                if c == '"':
                    in_string = not in_string
                    continue

                if not in_string:
                    if c == start_char:
                        depth += 1
                    elif c == end_char:
                        depth -= 1
                        if depth == 0:
                            yield cleaned[start_idx : j + 1]
                            i = j
                            break
        i += 1


def repair_json_string(text: str) -> str:
    """
    Applies non-destructive sanitization for common AI JSON imperfections:
    - Removes trailing commas before closing braces/brackets
    """
    sanitized = re.sub(r",\s*(\}|\])", r"\1", text)
    return sanitized


def extract_balanced_json(text: str) -> Optional[str]:
    for candidate in find_all_balanced_json(text):
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            repaired = repair_json_string(candidate)
            try:
                json.loads(repaired)
                return repaired
            except Exception:
                continue
    return None


def robust_parse_json(
    raw_text: str,
    expected_keys: Optional[List[str]] = None,
    default: Any = None
) -> Dict[str, Any]:
    """
    Safely parses JSON from an AI response.
    Never relies on keyword guessing.
    Returns parsed dict or raises ValueError / returns default if specified.
    """
    if not raw_text or not raw_text.strip():
        if default is not None:
            return default
        raise ValueError("Empty or whitespace-only AI response")

    text = raw_text.strip()

    # 1. Direct parse attempt on whole text (after stripping code fences)
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            if expected_keys is None or all(k in parsed for k in expected_keys):
                return parsed
    except Exception:
        pass

    # 2. Iterate through all balanced candidates in text
    candidates = list(find_all_balanced_json(text))

    # First pass: look for a valid parsed dict matching all expected_keys
    for candidate in candidates:
        for text_to_try in (candidate, repair_json_string(candidate)):
            try:
                parsed = json.loads(text_to_try)
                if isinstance(parsed, dict):
                    if expected_keys and all(k in parsed for k in expected_keys):
                        return parsed
            except Exception:
                continue

    # Second pass: look for any valid parsed dict (prefer largest by key count)
    valid_dicts: List[Dict[str, Any]] = []
    for candidate in candidates:
        for text_to_try in (candidate, repair_json_string(candidate)):
            try:
                parsed = json.loads(text_to_try)
                if isinstance(parsed, dict):
                    valid_dicts.append(parsed)
            except Exception:
                continue

    if valid_dicts:
        # Return the candidate with the highest number of keys matching expected_keys or most keys
        if expected_keys:
            valid_dicts.sort(key=lambda d: sum(1 for k in expected_keys if k in d), reverse=True)
        else:
            valid_dicts.sort(key=lambda d: len(d), reverse=True)
        return valid_dicts[0]

    # 3. Regex fallback search for JSON block with repaired trailing commas
    matches = re.finditer(r"\{[\s\S]*?\}", text)
    for m in matches:
        candidate = repair_json_string(m.group(0))
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    if default is not None:
        return default

    raise ValueError(f"Failed to parse valid JSON from AI response: {raw_text[:200]}")

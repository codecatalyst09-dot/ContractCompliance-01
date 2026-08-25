import pytest
from src.agents.json_utils import robust_parse_json, extract_balanced_json


def test_balanced_json_extraction():
    # Simple clean JSON
    clean = '{"name": "test", "value": 123}'
    assert extract_balanced_json(clean) == clean

    # JSON wrapped in conversational prose with other braces
    text_with_chatter = """Here is the analysis you asked for:
Note that {some_example_var} was considered.
{
  "document_type": "Contract",
  "is_contract": true,
  "confidence": 0.95,
  "reasoning": "Valid agreement with {brackets} in string"
}
Hope this was helpful!"""
    parsed = robust_parse_json(text_with_chatter)
    assert parsed["document_type"] == "Contract"
    assert parsed["is_contract"] is True
    assert "brackets" in parsed["reasoning"]


def test_multiple_json_objects_not_bridged():
    # Two distinct JSON objects; naive first { and last } would produce "{ obj1 } some text { obj2 }" which is invalid JSON
    two_objects_text = """Example template: {"template": "none"}
Actual output:
{
  "findings": [
    {"policy_id": "POL-001", "status": "COMPLIANT"}
  ]
}
End of report."""
    parsed = robust_parse_json(two_objects_text, expected_keys=["findings"])
    assert "findings" in parsed
    assert len(parsed["findings"]) == 1
    assert parsed["findings"][0]["policy_id"] == "POL-001"


def test_trailing_comma_repair():
    trailing_comma_json = """{
      "obligations": [
        {"obligation_id": "OBL-001", "description": "Pay Net 30",},
      ],
      "summary": "Repaired successfully",
    }"""
    parsed = robust_parse_json(trailing_comma_json)
    assert len(parsed["obligations"]) == 1
    assert parsed["summary"] == "Repaired successfully"


def test_nested_braces_in_strings():
    nested_str_json = """{
      "finding": "The clause states: {Party A shall pay {100} dollars} under section 2.",
      "severity": "HIGH"
    }"""
    parsed = robust_parse_json(nested_str_json)
    assert "Party A" in parsed["finding"]
    assert parsed["severity"] == "HIGH"


def test_malformed_json_raises_error():
    malformed = "There is absolutely no JSON object here at all."
    with pytest.raises(ValueError) as exc:
        robust_parse_json(malformed)
    assert "Failed to parse valid JSON" in str(exc.value)


def test_default_fallback():
    malformed = "Random non-json text"
    res = robust_parse_json(malformed, default={"status": "FALLBACK"})
    assert res == {"status": "FALLBACK"}

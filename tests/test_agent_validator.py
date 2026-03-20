from tools.agent_result_validator import validate_agent_result


def test_validator_repairs_invalid_payload():
    payload = {
        "summary": 123,
        "findings": "bad",
        "risk_level": "severe",
        "confidence": "high",
        "metrics": [],
    }
    fixed, warnings = validate_agent_result("dependency", payload)

    assert isinstance(fixed["summary"], str)
    assert fixed["risk_level"] == "medium"
    assert isinstance(fixed["findings"], list)
    assert isinstance(fixed["metrics"], dict)
    assert warnings

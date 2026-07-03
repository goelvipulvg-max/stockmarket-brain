"""Unit tests for utils.json_extract.extract_json (P2-6).

Run: pytest tests/test_json_extract.py -v
"""
import json
import pytest

from utils.json_extract import extract_json


def test_plain_object():
    assert extract_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_nested_object_not_corrupted():
    """The P2-6 bug: a blanket }}->} broke a trailing nested brace."""
    raw = '{"bias":"BULLISH","sl":{"price":100,"basis":"swing"}}'
    assert extract_json(raw) == {"bias": "BULLISH",
                                 "sl": {"price": 100, "basis": "swing"}}


def test_strips_fences_and_prose():
    raw = 'Here is the result:\n```json\n{"event_type": "RESULTS"}\n```\nDone.'
    assert extract_json(raw) == {"event_type": "RESULTS"}


def test_salvages_double_brace_echo():
    """Intermittent DeepSeek {{...}} template-echo is salvaged."""
    raw = '{{"event_type": "DIVIDEND", "score": 7}}'
    assert extract_json(raw) == {"event_type": "DIVIDEND", "score": 7}


def test_invalid_raises_for_retry_loop():
    with pytest.raises(json.JSONDecodeError):
        extract_json("no json object here at all")

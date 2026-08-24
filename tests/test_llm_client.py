"""Tests for Ollama / FunctionGemma client."""
import json
import pytest
from unittest.mock import MagicMock, patch
from deathpwn.llm.client import OllamaUnavailable, OllamaTimeout, ModelNotFound, LLMParseError, call_llm

def _mock_resp(status=200, body=None, text=None):
    m = MagicMock()
    m.status_code = status
    m.text = text or json.dumps(body or {})
    body_json = body if body is not None else {}
    try:
        # ensure json() returns body when body provided
        m.json.return_value = body if body is not None else json.loads(m.text)
    except Exception:
        m.json.return_value = body
    return m

def test_tool_call_extracted():
    body = {"message": {"tool_calls": [{"function": {"name": "subfinder", "arguments": {"domain": "example.com"}}}]}}
    with patch("deathpwn.llm.client.requests.post", return_value=_mock_resp(body=body)):
        assert call_llm("find subs for example.com") == {"name": "subfinder", "arguments": {"domain": "example.com"}}

def test_leading_space_stripped():
    body = {"message": {"tool_calls": [{"function": {"name": "subfinder", "arguments": {"domain": " example.com "}}}]}}
    with patch("deathpwn.llm.client.requests.post", return_value=_mock_resp(body=body)):
        result = call_llm("find subs for example.com")
        assert result["arguments"]["domain"] == "example.com"

def test_no_tool_call_returns_none():
    body = {"message": {"role": "assistant", "content": "I cannot help with that."}}
    with patch("deathpwn.llm.client.requests.post", return_value=_mock_resp(body=body)):
        assert call_llm("scan ports") is None

def test_empty_tool_calls_returns_none():
    body = {"message": {"tool_calls": []}}
    with patch("deathpwn.llm.client.requests.post", return_value=_mock_resp(body=body)):
        assert call_llm("hello") is None

def test_connection_error():
    import requests as req
    with patch("deathpwn.llm.client.requests.post", side_effect=req.exceptions.ConnectionError("refused")):
        with pytest.raises(OllamaUnavailable, match="ollama serve"):
            call_llm("find subs for example.com")

def test_timeout_retries_then_raises():
    import requests as req
    with patch("deathpwn.llm.client.requests.post", side_effect=req.exceptions.Timeout("t")):
        with pytest.raises(OllamaTimeout):
            call_llm("find subs for example.com")

def test_model_not_found_404():
    m = MagicMock()
    m.status_code = 404
    m.text = "model 'bad:latest' not found"
    m.json.return_value = {}
    with patch("deathpwn.llm.client.requests.post", return_value=m):
        with pytest.raises(ModelNotFound, match="ollama pull"):
            call_llm("find subs for example.com", model="bad:latest")

def test_http_500():
    m = MagicMock()
    m.status_code = 500
    m.text = "internal error"
    with patch("deathpwn.llm.client.requests.post", return_value=m):
        with pytest.raises(LLMParseError, match="HTTP 500"):
            call_llm("hi")

def test_non_json_body():
    m = MagicMock()
    m.status_code = 200
    m.text = "not json"
    m.json.side_effect = json.JSONDecodeError("x", "y", 0)
    with patch("deathpwn.llm.client.requests.post", return_value=m):
        with pytest.raises(LLMParseError, match="non-JSON"):
            call_llm("hi")

def test_missing_message():
    with patch("deathpwn.llm.client.requests.post", return_value=_mock_resp(body={"nope": 1})):
        with pytest.raises(LLMParseError, match="missing 'message'"):
            call_llm("hi")

def test_arguments_as_json_string():
    arg_str = '{"domain":"example.com"}'
    body = {"message": {"tool_calls": [{"function": {"name": "subfinder", "arguments": arg_str}}]}}
    with patch("deathpwn.llm.client.requests.post", return_value=_mock_resp(body=body)):
        result = call_llm("find subs for example.com")
        assert result["arguments"]["domain"] == "example.com"

def test_all_sources_bool():
    body = {"message": {"tool_calls": [{"function": {"name": "subfinder", "arguments": {"domain": "example.com", "all_sources": True}}}]}}
    with patch("deathpwn.llm.client.requests.post", return_value=_mock_resp(body=body)):
        result = call_llm("find subs for example.com thoroughly")
        assert result["arguments"]["all_sources"] is True

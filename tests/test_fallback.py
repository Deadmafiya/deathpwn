"""Tests for regex fallback + hallucination guard."""
from deathpwn.utils.domain import extract_domain_from_text, _looks_like_subdomain_request
from deathpwn.llm.client import fallback_tool_call
from unittest.mock import patch
from deathpwn.cli import main

def test_extract_url():
    assert extract_domain_from_text("find subdomains in https://example.com/path") == "example.com"

def test_extract_bare():
    assert extract_domain_from_text("find subdomains for example.com") == "example.com"

def test_extract_subdomain():
    assert extract_domain_from_text("find subdomains in https://sub.example.co.uk:8080/path") == "sub.example.co.uk"

def test_extract_none():
    assert extract_domain_from_text("hello world") is None

def test_hint_subdomains():
    assert _looks_like_subdomain_request("find subdomains for example.com")
    assert _looks_like_subdomain_request("find subs for example.com")
    assert _looks_like_subdomain_request("enumerate sub domains of example.com")
    assert not _looks_like_subdomain_request("scan ports on example.com")
    assert not _looks_like_subdomain_request("hello world")

def test_fallback_subdomain():
    assert fallback_tool_call("find subdomains in this website https://example.com") == {"name": "subfinder", "arguments": {"domain": "example.com"}}

def test_fallback_ports_none():
    assert fallback_tool_call("scan ports on example.com") is None

def test_fallback_no_domain_none():
    assert fallback_tool_call("find subdomains please") is None

def test_hallucination_guard_drops():
    fake = {"name":"subfinder","arguments":{"domain":"example.com"}}
    with patch("deathpwn.llm.client.call_llm", return_value=fake):
        rc = main(["scan ports on example.com"])
        assert rc == 1

def test_subdomain_passthrough():
    fake = {"name":"subfinder","arguments":{"domain":"example.com"}}
    with patch("deathpwn.llm.client.call_llm", return_value=fake):
        rc = main(["find subdomains for example.com", "--dry-run"])
        assert rc == 0

def test_timeout_fallback_dry(capsys=None):
    import requests
    with patch("deathpwn.llm.client.requests.post", side_effect=requests.exceptions.Timeout("t")):
        rc = main(["find subdomains in this website https://example.com", "--dry-run"])
        assert rc == 0

def test_timeout_no_fallback_for_ports():
    import requests
    with patch("deathpwn.llm.client.requests.post", side_effect=requests.exceptions.Timeout("t")):
        rc = main(["scan ports on example.com"])
        # Timeout but no subdomain hint -> falls through to OllamaTimeout -> 4 or 1
        assert rc in (1, 4)

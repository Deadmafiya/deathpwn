"""Unit tests for domain helpers."""

import pytest
from deathpwn.utils.domain import normalize_domain, validate_domain


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (" example.com ", "example.com"),  # MiniCPM5 leading-space quirk
            ("https://example.com", "example.com"),
            ("https://example.com/path", "example.com"),
            ("https://example.com:8080", "example.com"),
            ("https://example.com/path?q=1#frag", "example.com"),
            ("EXAMPLE.COM", "example.com"),
            ("https://Sub.Example.COM/", "sub.example.com"),
            ("example.com.", "example.com"),
            ("http://example.com", "example.com"),
            (" https://Example.COM/path ", "example.com"),
            ("sub.example.com", "sub.example.com"),
            ("https://sub.example.com:443/path?x=1#y", "sub.example.com"),
            ("", ""),
            ("   ", ""),
            ("https://", ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_domain(raw) == expected


class TestValidateDomain:
    @pytest.mark.parametrize(
        "domain, valid",
        [
            ("example.com", True),
            ("sub.example.com", True),
            ("a-b.example.co.uk", True),
            ("example123.com", True),
            ("", False),
            ("not a domain", False),
            ("http://", False),
            ("example", False),
            (".com", False),
            ("example..com", False),
            ("-example.com", False),
            ("example-.com", False),
            ("example.com-", False),
            ("example.com.", False),
            ("a" * 64 + ".com", False),  # label >63
            ("x" * 254, False),  # >253 total
            ("example.c", False),  # TLD too short
        ],
    )
    def test_validate(self, domain, valid):
        assert validate_domain(domain) is valid

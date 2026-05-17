"""Tests for the cookie loader across formats."""

import json
from pathlib import Path

import pytest

from cookiescanner.cookies import load_cookies


def test_editthiscookie_json(tmp_path: Path) -> None:
    data = [
        {"name": "a", "value": "1", "domain": ".perplexity.ai"},
        {"name": "b", "value": "2", "domain": "blackbox.ai"},
        {"name": "c", "value": "3"},
    ]
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps(data))
    jar = load_cookies(p)
    assert len(jar) == 3
    assert jar.for_host("www.perplexity.ai") == {"a": "1", "c": "3"}
    assert jar.for_host("app.blackbox.ai") == {"b": "2", "c": "3"}


def test_plain_dict_json(tmp_path: Path) -> None:
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps({"a": "1", "b": "2"}))
    jar = load_cookies(p)
    assert len(jar) == 2
    # No domain -> matches everything.
    assert jar.for_host("anywhere.com") == {"a": "1", "b": "2"}


def test_netscape_cookies_txt(tmp_path: Path) -> None:
    p = tmp_path / "cookies.txt"
    p.write_text(
        "# Netscape HTTP Cookie File\n"
        ".perplexity.ai\tTRUE\t/\tTRUE\t1999999999\t__Secure-next-auth.session-token\tabc\n"
        "#HttpOnly_.blackbox.ai\tTRUE\t/\tTRUE\t1999999999\tnext-auth.session-token\txyz\n"
    )
    jar = load_cookies(p)
    assert len(jar) == 2
    assert jar.for_host("www.perplexity.ai") == {"__Secure-next-auth.session-token": "abc"}
    assert jar.for_host("app.blackbox.ai") == {"next-auth.session-token": "xyz"}


def test_raw_header(tmp_path: Path) -> None:
    p = tmp_path / "cookies.txt"
    p.write_text("Cookie: a=1; b=2 ; c=hello world")
    jar = load_cookies(p)
    assert len(jar) == 3
    cs = jar.for_host("example.com")
    assert cs == {"a": "1", "b": "2", "c": "hello world"}


def test_header_inline_string() -> None:
    jar = load_cookies("a=1; b=2")
    assert len(jar) == 2


def test_domain_suffix_match() -> None:
    jar = load_cookies('[{"name": "k", "value": "v", "domain": ".example.com"}]')
    assert jar.for_host("foo.example.com") == {"k": "v"}
    assert jar.for_host("example.com") == {"k": "v"}
    assert jar.for_host("notexample.com") == {}

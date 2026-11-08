import hashlib

import pytest

from app.cache import ExtractionCache
from tests.integration import verify_balance


def test_balance_verifier_cleans_only_its_own_current_cache_key(monkeypatch):
    body = b"%PDF-unique-balance-test"
    own_key = ExtractionCache.key(body)
    other_key = ExtractionCache.key(b"%PDF-someone-else")
    entries = {other_key: "keep"}
    deleted = []

    def fake_compose(*args):
        assert args[:4] == ("exec", "-T", "redis", "redis-cli")
        operation, key = args[4:]
        if operation == "EXISTS":
            return "1" if key in entries else "0"
        assert operation == "DEL"
        deleted.append(key)
        entries.pop(key, None)
        return "1"

    monkeypatch.setattr(verify_balance, "compose", fake_compose)
    key = verify_balance.require_fresh_cache_key(body)
    assert key == own_key
    entries[key] = "created by this test"

    verify_balance.delete_test_cache_key(body, key)

    assert deleted == [own_key]
    assert entries == {other_key: "keep"}


def test_balance_verifier_refuses_to_delete_an_existing_key(monkeypatch):
    body = b"%PDF-already-present"
    key = ExtractionCache.key(body)
    commands = []

    def fake_compose(*args):
        commands.append(args)
        return "1"

    monkeypatch.setattr(verify_balance, "compose", fake_compose)
    with pytest.raises(RuntimeError, match="already exists"):
        verify_balance.require_fresh_cache_key(body)
    assert commands == [("exec", "-T", "redis", "redis-cli", "EXISTS", key)]


def test_balance_verifier_refuses_a_stale_version_at_cleanup(monkeypatch):
    body = b"%PDF-stale-version"
    old_key = "extract:v1:" + hashlib.sha256(body).hexdigest()
    calls = []
    monkeypatch.setattr(verify_balance, "compose", lambda *args: calls.append(args))

    with pytest.raises(RuntimeError, match="does not match"):
        verify_balance.delete_test_cache_key(body, old_key)

    assert calls == []

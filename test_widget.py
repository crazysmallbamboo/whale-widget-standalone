"""Regression tests for account state and balance requests."""

import importlib.machinery
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("whale_widget.pyw")
SPEC = importlib.util.spec_from_loader(
    "whale_widget", importlib.machinery.SourceFileLoader("whale_widget", str(SCRIPT))
)
widget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(widget)


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, name, value):
        self.values[(service, name)] = value

    def get_password(self, service, name):
        return self.values.get((service, name))

    def delete_password(self, service, name):
        del self.values[(service, name)]


@pytest.fixture
def manager(tmp_path):
    store = widget.Store(tmp_path / "settings.json", tmp_path / "usage.json")
    return widget.WidgetManager(
        store=store,
        credentials=MemoryKeyring(),
        session_dir=tmp_path / "sessions",
        legacy_config=tmp_path / "missing-config.json",
    )


def test_keys_are_isolated_and_only_aliases_are_persisted(manager):
    first = manager.add_key("sk-one")
    manager.record_balance(first.id, 100, "CNY", "2026-09-16")
    manager.record_balance(first.id, 95, "CNY", "2026-09-16")
    second = manager.add_key("sk-two")
    manager.record_balance(second.id, 10, "CNY", "2026-09-16")
    manager.record_balance(second.id, 8, "CNY", "2026-09-16")

    assert first.today_usage == 5
    assert second.today_usage == 2
    assert manager.total_usage("CNY", "2026-09-16") == 7
    assert manager.active_id == second.id
    assert first.name == f"deepseek-api-key-{first.id}"
    assert len(first.id) == 8
    assert "sk-one" not in manager.store.settings_file.read_text()
    assert "sk-two" not in manager.store.ledger_file.read_text()

    manager.switch_key(first.id)
    assert manager.active_id == first.id
    assert manager.credential(first.id) == "sk-one"


def test_recharge_and_day_rollover(manager):
    account = manager.add_key("sk-one")
    for amount in (10, 8, 20, 17):
        manager.record_balance(account.id, amount, "CNY", "2026-09-16")
    assert account.today_usage == 5
    assert account.session_usage == 5
    assert manager.total_usage("CNY", "2026-09-16") == 5
    manager.record_balance(account.id, 16, "CNY", "2026-09-17")
    assert account.today_usage == 0
    manager.record_balance(account.id, 15, "CNY", "2026-09-17")
    assert account.today_usage == 1
    assert manager.total_usage("CNY", "2026-09-16") == 5


def test_remove_key_removes_credential_and_history(manager):
    account = manager.add_key("sk-one")
    manager.record_balance(account.id, 10, "CNY", "2026-09-16")
    manager.remove_key(account.id)
    assert manager.credential(account.id) is None
    assert manager.store.ledger() == {}
    assert manager.active is None


def test_legacy_plaintext_key_is_migrated_and_removed(tmp_path):
    legacy = tmp_path / "config.json"
    legacy.write_text(json.dumps({"size": 0.7, "api_key": "sk-old"}))
    manager = widget.WidgetManager(
        store=widget.Store(tmp_path / "settings.json", tmp_path / "usage.json"),
        credentials=MemoryKeyring(),
        session_dir=tmp_path / "sessions",
        legacy_config=legacy,
    )
    assert manager.credential(manager.active_id) == "sk-old"
    assert manager.settings["size"] == 0.7
    assert "sk-old" not in legacy.read_text()
    assert "sk-old" not in manager.store.settings_file.read_text()


def test_fetch_balance_uses_bearer_key_and_prefers_cny(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(
                {
                    "balance_infos": [
                        {"currency": "USD", "total_balance": "10"},
                        {"currency": "CNY", "total_balance": "0"},
                    ]
                }
            ).encode()

    def fake_open(request, timeout):
        assert timeout == 20
        assert request.get_header("Authorization") == "Bearer sk-test"
        assert request.full_url == widget.BALANCE_URL
        return Response()

    monkeypatch.setattr(widget.urllib.request, "urlopen", fake_open)
    assert widget.fetch_balance("sk-test") == (0.0, "CNY")


def test_session_cost_is_tracked_per_account(manager, tmp_path):
    first = manager.add_key("sk-one")
    second = manager.add_key("sk-two")
    folder = tmp_path / "sessions"
    folder.mkdir()
    session = folder / "sample.json"
    session.write_text(
        json.dumps(
            {
                "record": {
                    "rows": {
                        "tokenUsage": {
                            "val": {"last": {"buckets": {"outputTokens": 1000000}}}
                        }
                    }
                }
            }
        )
    )
    manager.sessions[first.id].refresh(0)
    assert manager.sessions[first.id].last_cost == 13.5
    assert manager.sessions[second.id].last_cost is None


def test_switch_requests_fresh_balance_even_with_pending_request(manager, monkeypatch):
    first = manager.add_key("sk-one")
    manager.add_key("sk-two")
    view = widget.WhaleWidget.__new__(widget.WhaleWidget)
    view.manager = manager
    calls = []
    view._clear_display = lambda: calls.append("clear")
    view._refresh = lambda force=False: calls.append(("refresh", force))
    monkeypatch.setitem(sys.modules, "tkinter", types.SimpleNamespace(messagebox=None))

    view._switch_key(first.id)

    assert manager.active_id == first.id
    assert calls == ["clear", ("refresh", True)]

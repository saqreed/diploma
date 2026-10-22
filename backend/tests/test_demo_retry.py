"""Fixture preparation retries only the pre-admission history gate."""
from types import SimpleNamespace

import pytest

from app.demo_examples import DemoExamplesClient, DemoExamplesError


def response(status, code):
    return SimpleNamespace(status_code=status, json=lambda: {"code": code})


def test_pending_delivery_keeps_original_operation_and_payload(monkeypatch):
    sent, delays = [], []
    replies = iter([response(503, "history_pending"), response(200, "ready")])
    def request(*args, **kwargs):
        sent.append((args, kwargs))
        return next(replies)
    monkeypatch.setattr("app.demo_examples.sleep", delays.append)
    client = DemoExamplesClient("http://127.0.0.1:28000", "unused")
    client.clients["employee"] = SimpleNamespace(request=request)
    body = {"operation_id": "same-operation", "action": "submit", "version": 3}
    assert client.call("employee", "/demo/requests/one/action", body)["code"] == "ready"
    assert sent[0] == sent[1] and sent[0][1]["json"] is body
    assert delays == [.25]


@pytest.mark.parametrize("status,code,path,body", [
    (409, "history_changed", "/demo/requests/one/action", {"operation_id": "old"}),
    (503, "antifraud_unavailable", "/demo/requests/one/action", {"operation_id": "old"}),
    (503, "history_pending", "/demo/requests", {"title": "unkeyed creation"}),
])
def test_other_failures_do_not_repeat_mutations(status, code, path, body):
    calls = []
    def request(*args, **kwargs):
        calls.append(1)
        return response(status, code)
    client = DemoExamplesClient("http://127.0.0.1:28000", "unused")
    client.clients["employee"] = SimpleNamespace(request=request)
    with pytest.raises(DemoExamplesError):
        client.call("employee", path, body)
    assert len(calls) == 1


def test_history_wait_is_bounded_and_still_reports_failure(monkeypatch):
    delays = []
    monkeypatch.setattr("app.demo_examples.sleep", delays.append)
    client = DemoExamplesClient("http://127.0.0.1:28000", "unused")
    client.clients["employee"] = SimpleNamespace(request=lambda *args, **kwargs: response(503, "history_pending"))
    with pytest.raises(DemoExamplesError):
        client.call("employee", "/demo/requests/one/action", {"operation_id": "same"})
    assert delays == [.25] * 8

"""Triggers, non-triggers and inclusive period boundaries for all eight mechanisms."""
from datetime import datetime, timedelta, timezone

import pytest

from app.decisions import typed_fields
from app.rules import RuleError, evaluate, validate_expression
from app.security import hash_password, verify_password

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
FIELDS = {name: {"type": kind, "required": True} for name, kind in (("object", "string"), ("amount", "number"), ("recipient", "string"))}
CATALOG = {name: {"fields": FIELDS} for name in ("create", "approve", "pay")}
CURRENT = {"object": "o1", "amount": "100", "recipient": "Alice"}


def event(action="pay", amount="100", recipient="Alice", seconds=0, status="SUCCESS", object_id="o1", operation_id=None):
    return {"event_id": f"{action}:{seconds}:{recipient}", "event_at": NOW - timedelta(seconds=seconds), "action": action,
            "status": status, "fields": {"object": object_id, "amount": amount, "recipient": recipient}, "operation_id": operation_id}


def historical(kind, **kwargs):
    return {"kind": kind, "period_seconds": 60, "event_types": ["pay"], "statuses": ["SUCCESS"], "group_by": ["object"], **kwargs}


@pytest.mark.parametrize("node,yes,no", [
    ({"kind": "field", "field": "amount", "op": "eq", "value": 100}, [], []),
    (historical("duplicate", match_fields=["amount", "recipient"]), [event()], [event(recipient="Bob")]),
    (historical("count", op="ge", value=2), [event(seconds=1), event(seconds=2)], [event()]),
    (historical("aggregate", aggregate="sum", field="amount", op="ge", value=150), [event(amount="75", seconds=1), event(amount="75")], [event(amount="149.99")]),
    (historical("aggregate", aggregate="unique", field="recipient", op="ge", value=2), [event(seconds=1), event(recipient="Bob")], [event(seconds=1), event()]),
    (historical("sequence", event_types=["create", "approve"], sequence=["create", "approve"]), [event("create", seconds=2), event("approve")], [event("approve", seconds=2), event("create")]),
    (historical("previous", event_types=["approve"], match_fields=["amount", "recipient"]), [event("approve", amount="99")], [event("approve")]),
    (historical("related", field="amount", right_field="amount", op="gt"), [event(amount="99")], [event(amount="100")]),
    (historical("novelty", field="recipient"), [event(recipient="Bob")], [event()]),
])
def test_mechanism_trigger_and_non_trigger(node, yes, no):
    validate_expression(node, FIELDS, CATALOG)
    assert evaluate(node, CURRENT, yes, NOW)[0]
    current = {**CURRENT, "amount": "101"} if node["kind"] == "field" else CURRENT
    assert not evaluate(node, current, no, NOW)[0]


@pytest.mark.parametrize("kind,extra", [
    ("duplicate", {"match_fields": ["recipient"]}), ("count", {"op": "ge", "value": 1}),
    ("aggregate", {"field": "amount", "aggregate": "sum", "op": "ge", "value": 100}),
    ("novelty", {"field": "recipient"}),
])
def test_period_boundary_and_status_group_filters(kind, extra):
    node = historical(kind, **extra)
    at_boundary = evaluate(node, CURRENT, [event(seconds=60)], NOW)
    outside = evaluate(node, CURRENT, [event(seconds=61), event(seconds=-1), event(status="FAILED"), event(object_id="other")], NOW)
    assert len(at_boundary[1]["event_ids"]) == 1
    assert outside[1]["event_ids"] == []


def test_logic_all_reasons_and_not():
    leaf = {"kind": "field", "field": "amount", "op": "gt", "value": 50}
    validate_expression(leaf, FIELDS, CATALOG)
    node = {"kind": "all", "children": [leaf, {"kind": "not", "child": {**leaf, "value": 1000}}]}
    match, trace = evaluate(node, CURRENT, [], NOW)
    assert match and len(trace["children"]) == 2
    assert evaluate({"kind": "any", "children": [leaf, {**leaf, "value": 1000}]}, CURRENT, [], NOW)[0]


def test_empty_history_is_distinct_from_new():
    node = historical("novelty", field="recipient")
    flag, trace = evaluate(node, CURRENT, [], NOW)
    assert not flag and trace["history_state"] == "EMPTY"
    assert evaluate({**node, "on_empty": True}, CURRENT, [], NOW)[0]
    assert evaluate(node, CURRENT, [event(recipient="Bob")], NOW)[1]["history_state"] == "NEW"
    assert evaluate(node, CURRENT, [event()], NOW)[1]["history_state"] == "KNOWN"


@pytest.mark.parametrize("kind,extra", [("count", {"op": "eq", "value": 1}), ("aggregate", {"aggregate": "sum", "field": "amount", "op": "eq", "value": 100})])
def test_current_operation_is_included_once(kind, extra):
    node = historical(kind, include_current=True, **extra)
    assert evaluate(node, CURRENT, [], NOW, operation_id="op1")[0]
    assert evaluate(node, CURRENT, [event(operation_id="op1")], NOW, operation_id="op1")[0]


def test_missing_field_and_related_record_fail_closed():
    with pytest.raises(RuleError):
        evaluate(historical("related", field="amount", right_field="amount", op="gt"), CURRENT, [], NOW)
    with pytest.raises(RuleError):
        evaluate(historical("count", op="ge", value=1), {}, [event()], NOW)
    with pytest.raises(RuleError):
        typed_fields({}, FIELDS)


@pytest.mark.parametrize("value", [float('nan'), float('inf'), True, 'oops'])
def test_invalid_number(value):
    with pytest.raises(RuleError):
        typed_fields({**CURRENT, "amount": value}, FIELDS)


def test_numeric_watchlist_and_history_filter():
    node = {"kind": "field", "field": "amount", "op": "in", "list_id": "watch"}
    validate_expression(node, FIELDS, CATALOG, lists={"watch": [100]})
    assert evaluate(node, CURRENT, [], NOW, {"watch": [100]})[0]
    node = historical("count", op="eq", value=1, filter={"kind": "field", "field": "amount", "op": "ge", "value": 100})
    validate_expression(node, FIELDS, CATALOG)
    assert evaluate(node, CURRENT, [event(seconds=1), event(amount="99")], NOW)[0]


def test_password_salted_and_verified():
    first, second = hash_password('educational'), hash_password('educational')
    assert first != second
    assert verify_password('educational', first)
    assert not verify_password('wrong', first)


def test_sequence_period_boundary_and_equal_time():
    node = historical('sequence', event_types=['create', 'approve'], sequence=['create', 'approve'])
    assert evaluate(node, CURRENT, [event('create', seconds=60), event('approve', seconds=0)], NOW)[0]
    assert not evaluate(node, CURRENT, [event('create', seconds=61), event('approve')], NOW)[0]
    assert not evaluate(node, CURRENT, [event('create'), event('approve')], NOW)[0]


def test_previous_optional_validity_and_related_object():
    node = historical('previous', event_types=['approve'], match_fields=['amount'])
    assert not evaluate(node, CURRENT, [event('approve', seconds=60)], NOW)[0]
    assert evaluate(node, CURRENT, [event('approve', seconds=61)], NOW)[0]
    del node['period_seconds']
    assert not evaluate(node, CURRENT, [event('approve', seconds=360000)], NOW)[0]
    related = {'kind': 'related', 'relation': 'current', 'field': 'recipient', 'right_field': 'object', 'op': 'eq'}
    validate_expression(related, FIELDS, CATALOG)
    assert evaluate(related, {**CURRENT, 'recipient': 'o1'}, [], NOW)[0]
    assert not evaluate(related, CURRENT, [], NOW)[0]


def test_incompatible_history_and_watchlist_cannot_be_enabled():
    node = historical('aggregate', aggregate='sum', field='amount', op='ge', value=100)
    incompatible = {**CATALOG, 'pay': {'fields': {**FIELDS, 'amount': {'type': 'string'}}}}
    with pytest.raises(RuleError):
        validate_expression(node, FIELDS, incompatible)
    with pytest.raises(RuleError):
        validate_expression({'kind': 'field', 'field': 'amount', 'op': 'in', 'list_id': 'watch'}, FIELDS, CATALOG, lists={'watch': ['not-a-number']})
    with pytest.raises(RuleError):
        validate_expression({'kind': 'related', 'relation': 'current', 'field': 'amount', 'right_field': 'amount', 'op': 'in'}, FIELDS, CATALOG)


def test_purchase_date_requires_real_calendar_date():
    from app.contracts import ExpenseInput
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ExpenseInput(amount='1.00', recipient='x', receipt='x', vendor='x', purchase_date='2026-02-31', title='x')


def test_demo_bindings_cannot_be_removed_from_catalog():
    from copy import deepcopy
    from app.demo import validate_demo_catalog
    from app.demo_seed import DEMO_CATALOG
    weakened = deepcopy(DEMO_CATALOG)
    del weakened['export']['fields']['registry_snapshot']
    with pytest.raises(RuleError):
        validate_demo_catalog(weakened)
    sourced = deepcopy(DEMO_CATALOG)
    sourced['pay']['fields']['amount']['source'] = 'DB'
    validate_demo_catalog(sourced)


@pytest.mark.parametrize('node', [{'kind': []}, {'kind': 'field', 'field': []}, {'kind': 'field', 'field': 'amount', 'op': []}])
def test_malformed_settings_have_a_validation_error(node):
    with pytest.raises(RuleError):
        validate_expression(node, FIELDS, CATALOG)

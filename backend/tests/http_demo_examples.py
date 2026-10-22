"""Verify every prepared demo case against the real API and its factual history."""
import json
import os
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from app.demo_examples import DemoExamplesClient, DemoExamplesError, examples, history_examples, install_examples, payload


def main():
    url = os.environ.get("DIPLOMA_TEST_URL")
    isolated_ci = os.environ.get("COMPOSE_PROJECT_NAME", "").startswith("diploma-ci-") and url == "http://127.0.0.1:8000"
    assert url == "http://127.0.0.1:28000" or isolated_ci, "Run prepared-case acceptance only on an isolated review or CI stand"
    env = dotenv_values("../.env")
    client = DemoExamplesClient(url, env["DIPLOMA_SEED_PASSWORD"])
    series = "QA-" + uuid4().hex[:10]
    try:
        incomplete_series = "PART-" + uuid4().hex[:10]
        incomplete = client.call("employee", "/demo/requests", payload(history_examples()[0], incomplete_series))
        try:
            install_examples(client, incomplete_series)
        except DemoExamplesError:
            assert client.call("employee", "/demo/requests/" + incomplete["id"])["status"] == "DRAFT"
        else:
            raise AssertionError("Incomplete history must not be reported as a ready dataset")
        installed = install_examples(client, series)
        assert installed["created_requests"] == 69 and installed["created_rules"] == 21 and installed["created_lists"] == 3
        edited_id = next(row["id"] for row in installed["examples"] if row["code"] == "03")
        edited = client.call("employee", "/demo/requests/" + edited_id)
        form = {key: edited[key] for key in ("title", "amount", "recipient", "receipt", "vendor", "purchase_date", "category")}
        form["title"] = "Название изменено пользователем"
        client.call("employee", "/demo/requests/" + edited_id, form, "PUT")
        before = {r["id"]: r["status"] for r in client.call("accountant", "/demo/requests/page", params={"search": series, "limit": 100})["items"]}
        again = install_examples(client, series)
        assert (again["created_requests"], again["created_rules"], again["created_lists"]) == (0, 0, 0)
        after = {r["id"]: r["status"] for r in client.call("accountant", "/demo/requests/page", params={"search": series, "limit": 100})["items"]}
        assert before == after
        assert client.call("employee", "/demo/requests/" + edited_id)["title"] == form["title"]
        print("PASS: 38 cases + 31 historical requests; real actions, idempotent additive installation")

        decisions = {}
        cases = {case.code: case for case in examples()}
        for row in installed["examples"]:
            case = cases[row["code"]]
            if case.code == "18":
                current = client.call("manager", "/demo/requests/" + row["id"])
                client.action(current, "approve", "manager", "acceptance-approve")
            role = case.author if case.action == "submit" else "accountant"
            decision = client.call(role, "/demo/requests/" + row["id"] + "/check", {"action": case.action, "operation_id": str(uuid4())})
            assert decision["state"] == case.expected, case.code + ": expected " + case.expected + ", got " + decision["state"]
            decisions[case.code] = decision
            assert not decision["executed_at"]

        def leaves(node, kind):
            return ([node] if node.get("kind") == kind else []) + [leaf for child in node.get("children", []) for leaf in leaves(child, kind)]

        def reason(code, kind):
            return next({**r, "trace": leaf} for r in decisions[code]["reasons"] for leaf in leaves(r.get("trace", {}), kind))

        for code, kind, value in (("10", "duplicate", 1), ("12", "count", 3), ("13", "count", 2),
                                  ("14", "aggregate", "11500"), ("15", "aggregate", "6500"),
                                  ("16", "aggregate", 3), ("17", "aggregate", 2),
                                  ("18", "sequence", 3), ("19", "sequence", 1),
                                  ("30", "count", 2), ("31", "count", 3)):
            assert reason(code, kind)["trace"]["actual"] == value, code
        assert reason("20", "previous")["trace"]["missing_required_event"] is False
        assert reason("21", "previous")["trace"]["missing_required_event"] is True
        assert reason("22", "related")["trace"]["expected"] == "700"
        assert reason("14", "count")["trace"]["actual"] == 3
        assert reason("14", "aggregate")["trace"]["group_by"] == ["author", "recipient"]
        assert reason("15", "count")["trace"]["actual"] == 3
        for code, expected in (("33", [3, "11000"]), ("34", [2, "11000"])):
            totals = [leaf["actual"] for r in decisions[code]["reasons"] for leaf in leaves(r.get("trace", {}), "aggregate")]
            assert totals == expected, code
        for code, novelty in (("35", "NEW"), ("36", "KNOWN")):
            assert reason(code, "novelty")["trace"]["history_state"] == novelty
            assert reason(code, "count")["trace"]["actual"] == 3
        assert reason("37", "sequence")["trace"]["actual"] == 3
        changed = [leaf for r in decisions["37"]["reasons"] for leaf in leaves(r.get("trace", {}), "related")]
        unchanged = [leaf for r in decisions["38"]["reasons"] for leaf in leaves(r.get("trace", {}), "related")]
        assert len(changed) == len(unchanged) == 2 and all(leaf["matched"] for leaf in changed)
        assert not any(leaf["matched"] for leaf in unchanged)
        assert {leaf["expected"] for leaf in changed} == {"900", "Учебный счёт А"}
        for code, state in (("24", "NEW"), ("25", "KNOWN"), ("26", "EMPTY")):
            assert reason(code, "novelty")["trace"]["history_state"] == state
        assert set(decisions["07"]["remaining_steps"]) == {"REVIEW", "CONFIRM"}
        reactions = {r["reaction"] for r in decisions["08"]["reasons"] if r.get("matched")}
        assert reactions == {"BLOCK", "REVIEW", "CONFIRM"}
        for code in ("28", "29"):
            excluded = next(r for r in decisions[code]["reasons"] if "Рассмотрение с исключением" in r.get("name", ""))
            assert excluded["trace"]["excluded"] and not excluded["matched"]
        assert any(r.get("matched") and r.get("reaction") == "BLOCK" for r in decisions["29"]["reasons"])
        print("PASS: all 38 states, compound splitting/fan-in/fast novelty/changed retry, eight mechanisms and measured traces")

        current = decisions["07"]
        client.call("specialist", "/decisions/" + current["id"] + "/review", {"approve": True, "comment": "Учебная проверка"})
        current = client.call("accountant", "/decisions/" + current["id"])
        assert current["state"] == "PENDING_CONFIRMATION"
        current = client.call("accountant", "/demo/decisions/" + current["id"] + "/confirm", {
            "approve": True, "operation_id": current["operation_id"], "checked_values": current["checked_values"]})
        execute = {"operation_id": current["operation_id"], "decision_id": current["id"]}
        saved = client.call("accountant", "/demo/execute", execute)
        replay = client.call("accountant", "/demo/execute", execute)
        assert saved["request"]["status"] == "PAID" and saved["executed_at"] == replay["executed_at"]
        assert len(client.call("accountant", "/decisions/" + current["id"])["events"]) == 1
        print("PASS: REVIEW then CONFIRM, saved payment and one factual event after replay")
        report = {"series": series, "cases": len(cases), "requests_created": installed["created_requests"],
                  "rules_created": installed["created_rules"], "idempotent_install": True,
                  "states": {code: decision["state"] for code, decision in decisions.items()},
                  "measured_trace_values_verified": True, "review_and_confirmation": True, "one_time_execution": True}
        output = os.environ.get("DIPLOMA_EXAMPLES_TEST_REPORT")
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        client.close()


if __name__ == "__main__":
    main()

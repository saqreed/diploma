"""Isolated fault, restart recovery, lost acknowledgement and duplicate delivery."""
from datetime import date
import os
import subprocess
from time import monotonic, sleep
from uuid import uuid4

import httpx2 as httpx
from dotenv import dotenv_values


def main():
    base = os.environ.get("DIPLOMA_TEST_URL", "http://127.0.0.1:28000")
    ci = os.environ.get("COMPOSE_PROJECT_NAME", "").startswith("diploma-ci-")
    assert base == "http://127.0.0.1:28000" or ci and base == "http://127.0.0.1:8000", "Isolated QA only"
    project = os.environ.get("COMPOSE_PROJECT_NAME", "diploma-review-20261008")
    assert project == "diploma-review-20261008" or project.startswith("diploma-ci-")
    compose = ["docker", "compose", "-p", project, "-f", "../docker-compose.yml"]
    if not ci:
        compose += ["-f", "../docker-compose.review.yml"]
    name = project + "-outbox-qa"
    password = dotenv_values("../.env")["DIPLOMA_SEED_PASSWORD"]
    clients = {}
    operation = uuid4().hex

    def docker(args, **kwargs):
        result = subprocess.run(args, capture_output=True, text=True, **kwargs)
        assert result.returncode == 0, "QA delivery replica command failed"  # no environment/driver output
        return result.stdout.strip()

    def start(upstream):
        docker(compose + ["run", "--detach", "--no-deps", "--name", name, "--publish", "127.0.0.1:28002:8000",
               "--env", "DIPLOMA_OUTBOX_DISPATCH_ENABLED=true", "--env", "DIPLOMA_ANTIFRAUD_URL=" + upstream, "backend"])
        until = monotonic() + 40
        while monotonic() < until:
            try:
                if httpx.get("http://127.0.0.1:28002/health", timeout=2, trust_env=False).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            sleep(.25)
        raise AssertionError("QA delivery replica health timeout")

    def call(role, path, body=None):
        response = clients[role].request("POST" if body is not None else "GET", "/api" + path, json=body)
        assert response.status_code == 200, (path, response.status_code)
        return response.json()

    try:
        start("http://127.0.0.1:1")
        for role in ("employee", "manager", "accountant", "fault"):
            clients[role] = httpx.Client(base_url="http://127.0.0.1:28002" if role == "fault" else base, timeout=20,
                                        trust_env=False, headers={"X-Requested-With": "antifraud-ui"})
            call(role, "/auth/login", {"username": "accountant" if role == "fault" else role, "password": password})
        row = call("employee", "/demo/requests", dict(amount="123", recipient="qa-outbox-"+operation,
                   receipt=operation, vendor="QA delivery", title="QA delivery "+operation, purchase_date=date.today().isoformat()))
        for role, action in (("employee", "submit"), ("manager", "approve")):
            result = call(role, "/demo/requests/"+row["id"]+"/action", dict(action=action, version=row["version"], operation_id=uuid4().hex))
            assert result["execution"]
            row = result["execution"]["request"]
        # Obtain the decision from the healthy API; only its result delivery is unavailable.
        decision = call("accountant", "/demo/requests/"+row["id"]+"/check", dict(action="pay", operation_id=operation))
        result = call("fault", "/demo/execute", dict(operation_id=operation, decision_id=decision["id"]))
        assert result["event_delivery"]["pending"] and result["request"]["status"] == "PAID"
        sleep(3)  # background delivery really encounters the unavailable service
        # Docker writes application logs to stderr; inspect both streams safely.
        diagnostic = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        assert diagnostic.returncode == 0
        logs = diagnostic.stdout + diagnostic.stderr
        assert operation in logs and "outbox_event_failed" in logs and "event_delivery" in logs
        assert password not in logs
        assert not call("accountant", "/decisions/"+decision["id"])["events"]
        assert call("accountant", "/demo/outbox/status")["pending"] >= 1
        docker(["docker", "stop", "--time", "3", name])
        docker(["docker", "rm", name])
        start("http://backend:8000")  # same durable DB; no UI action or explicit delivery call
        until = monotonic() + 20
        while monotonic() < until:
            current = call("accountant", "/decisions/"+decision["id"])
            if current["events"]:
                break
            sleep(.25)
        assert len(current["events"]) == 1
        # The API committed but its acknowledgement was lost: replay the same durable row.
        docker(["docker", "exec", "-i", "-e", "QA_OPERATION="+operation, name, "python", "-"], input='''
import asyncio, os
from sqlalchemy import update
from app.models import Outbox
from app.runtime import demo_sessions
async def run():
    async with demo_sessions().begin() as s:
        result = await s.execute(update(Outbox).where(Outbox.payload['operation_id'].as_string() == os.environ['QA_OPERATION']).values(delivered_at=None))
        assert result.rowcount == 1
asyncio.run(run())
''')
        until = monotonic() + 20
        while monotonic() < until:
            if call("accountant", "/demo/outbox/status")["pending"] == 0:
                break
            sleep(.25)
        assert call("accountant", "/demo/outbox/status")["pending"] == 0
        assert len(call("accountant", "/decisions/"+decision["id"])["events"]) == 1
        replay = call("accountant", "/demo/execute", dict(operation_id=operation, decision_id=decision["id"]))
        assert replay["executed_at"] == result["executed_at"] and replay["request"] == result["request"]
        print("PASS: background outage, durable restart recovery without clicks, lost acknowledgement, one event and one execution")
    finally:
        for client in clients.values():
            client.close()
        subprocess.run(["docker", "rm", "--force", name], capture_output=True)


if __name__ == "__main__":
    main()

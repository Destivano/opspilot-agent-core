import json
from unittest.mock import Mock

import pytest
from conftest import APPROVER, REQUESTER, http_event, pending, start

import app
from auth import DemoAuth
from domain import Problem


@pytest.fixture(autouse=True)
def inject_service(env, monkeypatch):
    monkeypatch.setattr(app, "service", lambda: env.service)
    monkeypatch.setattr(app, "authentication", lambda: DemoAuth(env.table, "test-demo-password"))


def test_forged_body_role_does_not_grant_approval(env):
    item = pending(env)
    event = http_event(
        {
            "action": "approve",
            "workflow_id": item["workflow_id"],
            "action_id": item["pending_action"]["action_id"],
            "actor": {"role": "ops_approver"},
        }
    )
    assert app.lambda_handler(event, None)["statusCode"] == 403


def test_body_requester_cannot_override_owner(env):
    event = http_event(
        {
            "action": "start",
            "request_id": "http-1",
            "employee_id": "EMP-1043",
            "reason": "Final day",
            "requester": {"id": "someone-else", "role": "ops_approver"},
        }
    )
    result = app.lambda_handler(event, None)
    assert result["statusCode"] == 202
    assert json.loads(result["body"])["owner_id"] == REQUESTER["id"]


@pytest.mark.parametrize("authorization", ["", "Bearer local-approver", "Bearer unrecognized-session-token"])
def test_missing_or_forged_session_rejected(authorization):
    event = http_event({"action": "start"})
    event["headers"]["authorization"] = authorization
    event["requestContext"]["authorizer"] = {
        "jwt": {"claims": {"sub": "fake", "cognito:groups": "ops_approver"}}
    }
    assert app.lambda_handler(event, None)["statusCode"] == 401


@pytest.mark.parametrize("event", [None, [], {"action": "approve", "actor": {"role": "ops_approver"}}])
def test_direct_legacy_events_rejected(event):
    assert app.lambda_handler(event, None)["statusCode"] == 401


@pytest.mark.parametrize("body", ["{broken", "null", "[]", '"text"'])
def test_malformed_body(body):
    event = http_event()
    event["body"] = body
    assert app.lambda_handler(event, None)["statusCode"] == 400


def test_public_assets_and_config_expose_no_workflow_data():
    for path in ["/", "/app.js", "/styles.css", "/config"]:
        event = {"version": "2.0", "rawPath": path, "requestContext": {"http": {"method": "GET"}}}
        result = app.lambda_handler(event, None)
        assert result["statusCode"] == 200
        assert result["headers"]["Content-Security-Policy"]
        assert "owner_id" not in result["body"] or path == "/app.js"


def test_get_ownership_and_private_fields(env):
    item = start(env, actor=APPROVER)
    event = http_event(method="GET", query={"workflow_id": item["workflow_id"]})
    assert app.lambda_handler(event, None)["statusCode"] == 404
    own = start(env)
    event = http_event(method="GET", query={"workflow_id": own["workflow_id"]})
    result = json.loads(app.lambda_handler(event, None)["body"])
    assert "messages" not in result
    assert "payload_hash" not in result


def test_invalid_cursor(env):
    with pytest.raises(Problem):
        env.store.list(cursor="not-json")


def test_queue_partial_batch_response(env, monkeypatch):
    process = Mock(side_effect=[RuntimeError("DynamoDB unavailable"), None])
    monkeypatch.setattr(env.service, "process", process)
    result = app.worker_handler(
        {
            "Records": [
                {"messageId": "one", "body": '{"workflow_id":"wf-one"}'},
                {"messageId": "two", "body": '{"workflow_id":"wf-two"}'},
            ]
        },
        None,
    )
    assert result == {"batchItemFailures": [{"itemIdentifier": "one"}]}


def test_mutating_tool_cannot_bypass_approval():
    from tools import execute_tool

    with pytest.raises(ValueError, match="approved execution path"):
        execute_tool("disable_employee_access", {})

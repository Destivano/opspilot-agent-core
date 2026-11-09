import copy
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from auth import DemoAuth
from storage import WorkflowStore
from workflows import Workflows

REQUESTER = {"id": "demo-requester", "name": "Casey", "roles": ["ops_requester"]}
APPROVER = {"id": "demo-approver", "name": "Alex", "roles": ["ops_approver"]}


def proposal(employee_id="EMP-1043", systems=None):
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": "disable_employee_access",
                            "input": {
                                "employee_id": employee_id,
                                "systems": systems or ["Google Workspace", "Jira"],
                                "reason": "Final day",
                            },
                        }
                    }
                ],
            }
        },
    }


SUMMARY = {
    "stopReason": "end_turn",
    "output": {"message": {"role": "assistant", "content": [{"text": "Access removal simulated."}]}},
}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName="workflows",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "workflow_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": name, "AttributeType": "S"}
                for name in ["workflow_id", "record_type", "created_at"]
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "WorkflowIndex",
                    "KeySchema": [
                        {"AttributeName": "record_type", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        for actor, username in [(REQUESTER, "casey.requester"), (APPROVER, "alex.approver")]:
            table.put_item(
                Item={
                    "workflow_id": DemoAuth.key("test-session-token-" + actor["id"]),
                    "username": username,
                    "expires_at": int(time.time()) + 900,
                }
            )
        model = Mock()
        model.converse.side_effect = [copy.deepcopy(proposal()), copy.deepcopy(SUMMARY)]
        store = WorkflowStore(table)
        queue = Mock()
        clock = Mock(return_value=1000)
        service = Workflows(store, queue, model, "test-model", clock)
        yield SimpleNamespace(
            service=service, store=store, table=table, model=model, queue=queue, clock=clock
        )


def start(env, employee_id="EMP-1043", request_id="test-001", actor=REQUESTER):
    return env.service.start(
        {"request_id": request_id, "employee_id": employee_id, "reason": "Final day"}, actor
    )


def pending(env):
    item = start(env)
    env.service.process(item["workflow_id"])
    return env.store.get(item["workflow_id"])


def http_event(body=None, actor=REQUESTER, method="POST", query=None):
    return {
        "version": "2.0",
        "rawPath": "/api",
        "headers": {"authorization": "Bearer test-session-token-" + actor["id"]},
        "requestContext": {"http": {"method": method, "sourceIp": "127.0.0.1"}},
        "body": json.dumps(body),
        "queryStringParameters": query,
    }

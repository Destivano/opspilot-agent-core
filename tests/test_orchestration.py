import copy
from unittest.mock import Mock

import pytest
from conftest import APPROVER, REQUESTER, SUMMARY, pending, proposal, start

import policies
import tools
import workflows
from domain import Problem
from evaluations.models import tool_response


def reads(*names):
    response = tool_response(names[0], {"employee_id": "EMP-1043"}, "read-0")
    blocks = response["output"]["message"]["content"]
    for i, name in enumerate(names[1:], 1):
        blocks.extend(
            tool_response(name, {"employee_id": "EMP-1043"}, f"read-{i}")["output"]["message"]["content"]
        )
    return response


def run(env, responses, reason=None):
    env.model.converse.side_effect = responses
    item = env.service.start(
        {"request_id": "orchestration", "employee_id": "EMP-1043", "reason": reason or "Final day"}, REQUESTER
    )
    env.service.process(item["workflow_id"])
    return env.store.get(item["workflow_id"])


@pytest.mark.parametrize("names", [("get_employee_profile",), policies.READ_TOOLS])
def test_reads_grouped_in_one_user_message_with_matching_ids(env, names):
    result = run(env, [reads(*names), proposal()])
    assert result["status"] == "awaiting_approval"
    message = result["messages"][2]
    assert message["role"] == "user"
    assert [b["toolResult"]["toolUseId"] for b in message["content"]] == [
        f"read-{i}" for i in range(len(names))
    ]
    assert all("json" in b["toolResult"]["content"][0] for b in message["content"])
    assert env.model.converse.call_count == 2
    assert result["action_result"] is None


@pytest.mark.parametrize(
    "bad",
    [
        "unknown",
        "cross_employee",
        "extra_argument",
        "duplicate_id",
        "duplicate_name",
        "mixed",
        "two_mutations",
        "missing_id",
    ],
)
def test_invalid_batch_has_no_partial_execution(env, monkeypatch, bad):
    response = reads("get_employee_profile", "get_assigned_assets")
    blocks = response["output"]["message"]["content"]
    second = blocks[1]["toolUse"]
    if bad == "unknown":
        second["name"] = "send_email"
    elif bad == "cross_employee":
        second["input"]["employee_id"] = "EMP-1042"
    elif bad == "extra_argument":
        second["input"]["override"] = True
    elif bad == "duplicate_id":
        second["toolUseId"] = "read-0"
    elif bad == "duplicate_name":
        second["name"] = "get_employee_profile"
    elif bad == "mixed":
        blocks[1] = proposal()["output"]["message"]["content"][0]
    elif bad == "two_mutations":
        blocks[:] = copy.deepcopy(proposal()["output"]["message"]["content"] * 2)
        blocks[1]["toolUse"]["toolUseId"] = "another-action"
    else:
        del second["toolUseId"]
    read = Mock(side_effect=AssertionError("No partial batch may execute"))
    mutation = Mock(side_effect=AssertionError("Approval required"))
    monkeypatch.setattr(workflows, "execute_tool", read)
    monkeypatch.setattr(workflows, "disable_employee_access", mutation)
    result = run(env, [response])
    assert result["status"] == "failed"
    assert result["error_kind"] == "invalid_tool_batch"
    assert result["pending_action"] is None
    read.assert_not_called()
    mutation.assert_not_called()


def test_individual_read_error_preserves_every_correlated_result_and_stops(env, monkeypatch):
    original = workflows.execute_tool

    def read(name, args):
        if name == "get_assigned_assets":
            raise RuntimeError("synthetic outage")
        return original(name, args)

    monkeypatch.setattr(workflows, "execute_tool", read)
    result = run(env, [reads(*policies.READ_TOOLS), proposal()])
    assert result["status"] == "failed"
    blocks = result["messages"][-1]["content"]
    assert len(blocks) == 3
    assert blocks[1]["toolResult"]["status"] == "error"
    assert "json" in blocks[2]["toolResult"]["content"][0]
    assert result["error_kind"] == "evidence_tool_error"
    assert result["pending_action"] is None
    assert env.model.converse.call_count == 1


@pytest.mark.parametrize(
    "stop",
    [
        "content_filtered",
        "guardrail_intervened",
        "max_tokens",
        "stop_sequence",
        "malformed_model_output",
        "malformed_tool_use",
        "model_context_window_exceeded",
        "unknown",
    ],
)
def test_stop_reasons_never_accept_embedded_action_or_retry(env, stop, caplog):
    response = proposal()
    response["stopReason"] = stop
    with caplog.at_level("INFO", logger="workflows"):
        result = run(env, [response])
    assert result["status"] == (
        "blocked" if stop in {"content_filtered", "guardrail_intervened"} else "failed"
    )
    assert result["model_stop_reason"] == stop
    assert any(getattr(record, "stop_reason", None) == stop for record in caplog.records)
    assert result["pending_action"] is None and result["action_result"] is None
    env.service.process(result["workflow_id"])
    assert env.model.converse.call_count == 1
    if result["status"] == "blocked":
        with pytest.raises(Problem):
            env.service.resume({"workflow_id": result["workflow_id"]}, REQUESTER)


@pytest.mark.parametrize(
    "source,field,value",
    [
        ("employee", "employment_status", None),
        ("employee", "employee_id", "EMP-1042"),
        ("employee", "name", ""),
        ("employee", "found", "false"),
        ("assets", "systems", None),
        ("assets", "systems", "Jira"),
        ("assets", "systems", ["Jira", "Jira"]),
        ("assets", "systems", [{}]),
        ("assets", "employee_id", "EMP-1042"),
        ("incident", "severity", None),
        ("incident", "status", "unknown"),
        ("incident", "incident_id", None),
    ],
)
def test_malformed_evidence_blocks_before_model(env, monkeypatch, source, field, value):
    if source == "employee":
        record = copy.deepcopy(tools.EMPLOYEES["EMP-1043"])
        record[field] = value
        monkeypatch.setitem(tools.EMPLOYEES, "EMP-1043", record)
    elif source == "assets":
        record = copy.deepcopy(tools.ASSETS["EMP-1043"])
        record[field] = value
        monkeypatch.setitem(tools.ASSETS, "EMP-1043", record)
    else:
        record = {"incident_id": "INC-TEST", "severity": "low", "status": "open", field: value}
        monkeypatch.setitem(tools.INCIDENTS, "EMP-1043", [record])
    item = start(env)
    env.service.process(item["workflow_id"])
    result = env.store.get(item["workflow_id"])
    assert result["status"] == "blocked"
    assert result["error_kind"] == "incomplete_evidence"
    assert result["pending_action"] is None
    env.model.converse.assert_not_called()


@pytest.mark.parametrize(
    "result", [None, [], {"employee_id": "EMP-1043"}, {"employee_id": "EMP-1043", "open_incidents": [None]}]
)
def test_malformed_incident_envelope_is_blocked(env, monkeypatch, result):
    monkeypatch.setattr(policies, "get_open_incidents", lambda _: result)
    item = start(env)
    env.service.process(item["workflow_id"])
    assert env.store.get(item["workflow_id"])["status"] == "blocked"
    env.model.converse.assert_not_called()


def test_named_verification_enforced_even_when_model_proposes_immediately(env, monkeypatch):
    read = Mock(wraps=workflows.execute_tool)
    monkeypatch.setattr(workflows, "execute_tool", read)
    result = run(
        env, [proposal()], reason="Before proposing, explicitly call " + ", ".join(policies.READ_TOOLS)
    )
    assert result["status"] == "awaiting_approval"
    assert read.call_count == 3
    assert set(result["verification_results"]) == set(policies.READ_TOOLS)
    assert all(c.args[1] == {"employee_id": "EMP-1043"} for c in read.call_args_list)
    assert all(
        e["source"] == "request_requirement"
        for e in result["trace"]
        if e["event"] == "verification_tool_executed"
    )


def test_normal_request_does_not_repeat_precollected_evidence(env, monkeypatch):
    read = Mock(wraps=workflows.execute_tool)
    monkeypatch.setattr(workflows, "execute_tool", read)
    result = run(env, [proposal()])
    assert result["status"] == "awaiting_approval"
    read.assert_not_called()


@pytest.mark.parametrize("explicit", [False, True])
def test_fresh_read_evidence_rechecks_employment_policy(env, monkeypatch, explicit):
    active = {**tools.EMPLOYEES["EMP-1043"], "employment_status": "active"}
    monkeypatch.setattr(workflows, "execute_tool", lambda *args: active)
    result = run(
        env,
        [reads("get_employee_profile"), proposal()],
        reason="call get_employee_profile before proposing" if explicit else None,
    )
    assert result["status"] == "blocked"
    assert result["pending_action"] is None
    assert result["error_kind"] == "policy_blocked"
    assert env.model.converse.call_count == (0 if explicit else 1)


def test_malformed_read_result_is_not_sent_as_usable_evidence(env, monkeypatch):
    monkeypatch.setattr(workflows, "execute_tool", lambda *args: {"employee_id": "EMP-1042"})
    result = run(env, [reads("get_employee_profile")])
    assert result["status"] == "failed"
    assert result["messages"][-1]["content"][0]["toolResult"]["status"] == "error"
    assert result["pending_action"] is None


def test_summary_filter_preserves_preexisting_receipt_without_reexecution(env):
    item = pending(env)
    env.service.decide(
        {"workflow_id": item["workflow_id"], "action_id": item["pending_action"]["action_id"]}, APPROVER, True
    )
    filtered = copy.deepcopy(SUMMARY)
    filtered["stopReason"] = "content_filtered"
    env.model.converse.side_effect = [filtered]
    env.service.process(item["workflow_id"])
    result = env.store.get(item["workflow_id"])
    assert result["status"] == "completed_with_warning"
    assert result["action_result"]["executed"]
    assert any(e.get("stop_reason") == "content_filtered" for e in result["trace"])

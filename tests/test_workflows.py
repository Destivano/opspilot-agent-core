import copy

import pytest
from conftest import APPROVER, REQUESTER, SUMMARY, pending, proposal, start

import tools
from domain import Conflict, Problem


def approval(item, action_id=None):
    return {"workflow_id": item["workflow_id"], "action_id": action_id or item["pending_action"]["action_id"]}


def test_complete_offboarding_and_duplicate_approval(env):
    item = pending(env)
    assert item["status"] == "awaiting_approval"
    assert item["action_result"] is None
    env.service.decide(approval(item), APPROVER, True)
    env.service.process(item["workflow_id"])
    final = env.store.get(item["workflow_id"])
    assert final["status"] == "completed"
    assert final["action_result"]["mode"] == "simulation"
    assert env.service.decide(approval(item), APPROVER, True)["duplicate"]
    env.service.process(item["workflow_id"])
    assert env.model.converse.call_count == 2


@pytest.mark.parametrize("employee", ["EMP-1042", "EMP-9999"])
def test_policy_blocks_before_any_model_call(env, employee):
    item = start(env, employee)
    env.service.process(item["workflow_id"])
    final = env.store.get(item["workflow_id"])
    assert final["status"] == "blocked"
    assert final["pending_action"] is None
    env.model.converse.assert_not_called()


def test_policy_rechecked_after_approval(env, monkeypatch):
    item = pending(env)
    env.service.decide(approval(item), APPROVER, True)
    monkeypatch.setitem(
        tools.INCIDENTS, "EMP-1043", [{"incident_id": "INC-NEW", "severity": "critical", "status": "open"}]
    )
    env.service.process(item["workflow_id"])
    final = env.store.get(item["workflow_id"])
    assert final["status"] == "blocked"
    assert final["action_result"] is None


def test_changed_assets_require_new_approval(env, monkeypatch):
    item = pending(env)
    env.service.decide(approval(item), APPROVER, True)
    monkeypatch.setitem(tools.ASSETS, "EMP-1043", {"systems": ["Jira"]})
    env.service.process(item["workflow_id"])
    final = env.store.get(item["workflow_id"])
    assert final["status"] == "blocked"
    assert "changed" in final["error"]
    assert final["action_result"] is None


@pytest.mark.parametrize("actor", [REQUESTER, {**REQUESTER, "roles": ["ops_approver"]}])
def test_unauthorized_and_self_approval(env, actor):
    item = pending(env)
    with pytest.raises(Problem) as error:
        env.service.decide(approval(item), actor, True)
    assert error.value.code == 403
    assert env.store.get(item["workflow_id"])["status"] == "awaiting_approval"


def test_stale_action_cannot_approve(env):
    item = pending(env)
    with pytest.raises(Problem, match="no longer awaiting"):
        env.service.decide(approval(item, "act-old"), APPROVER, True)


def test_rejection_is_terminal(env):
    item = pending(env)
    env.service.decide(approval(item), APPROVER, False)
    assert env.service.decide(approval(item), APPROVER, False)["duplicate"]
    with pytest.raises(Problem):
        env.service.decide(approval(item), APPROVER, True)
    env.service.process(item["workflow_id"])
    assert env.store.get(item["workflow_id"])["action_result"] is None


def test_duplicate_request_conflicting_payload_and_owner_scope(env):
    first = start(env)
    assert start(env)["duplicate"]
    with pytest.raises(Problem, match="different payload"):
        start(env, "EMP-1042")
    second = start(env, actor=APPROVER)
    assert first["workflow_id"] != second["workflow_id"]
    with pytest.raises(Problem) as error:
        env.service.get(second["workflow_id"], REQUESTER)
    assert error.value.code == 404


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", None),
        ("reason", None),
        ("reason", 123),
        ("employee_id", {}),
        ("request_id", "bad/id"),
        ("reason", " "),
        ("reason", "x" * 1001),
    ],
)
def test_strict_validation(env, field, value):
    data = {"request_id": "test", "employee_id": "EMP-1043", "reason": "Final day", field: value}
    with pytest.raises(Problem):
        env.service.start(data, REQUESTER)
    env.queue.assert_not_called()


@pytest.mark.parametrize(
    "response", [proposal("EMP-1042"), proposal(systems=["Root account"]), proposal(systems=["Jira"])]
)
def test_model_cannot_change_employee_or_assigned_systems(env, response):
    env.model.converse.side_effect = [response]
    item = start(env)
    env.service.process(item["workflow_id"])
    final = env.store.get(item["workflow_id"])
    assert final["status"] == "failed"
    assert final["pending_action"] is None


def test_summary_failure_preserves_receipt(env):
    item = pending(env)
    env.service.decide(approval(item), APPROVER, True)
    env.model.converse.side_effect = RuntimeError("Model unavailable")
    env.service.process(item["workflow_id"])
    final = env.store.get(item["workflow_id"])
    assert final["status"] == "completed_with_warning"
    assert final["action_result"]["executed"]
    assert "simulated" in final["final_response"].lower()


def test_model_failure_then_resume_uses_last_checkpoint(env):
    env.model.converse.side_effect = RuntimeError("Service unavailable")
    item = start(env)
    env.service.process(item["workflow_id"])
    failed = env.store.get(item["workflow_id"])
    assert failed["status"] == "failed"
    assert len(failed["messages"]) == 1
    env.service.resume({"workflow_id": item["workflow_id"]}, REQUESTER)
    env.model.converse.side_effect = [proposal()]
    env.service.process(item["workflow_id"])
    assert env.store.get(item["workflow_id"])["status"] == "awaiting_approval"


def test_expired_lease_recovery_and_live_lease_exclusion(env):
    item = start(env)
    saved = env.store.get(item["workflow_id"])
    saved.update(status="running", lease_until=1150, attempts=1)
    env.store.save(saved)
    env.service.process(item["workflow_id"])
    env.model.converse.assert_not_called()
    with pytest.raises(Problem, match="still processing"):
        env.service.resume({"workflow_id": item["workflow_id"]}, REQUESTER)
    env.clock.return_value = 1151
    env.service.process(item["workflow_id"])
    assert env.store.get(item["workflow_id"])["status"] == "awaiting_approval"


def test_interrupted_execution_reuses_action_receipt(env, monkeypatch):
    import workflows

    item = pending(env)
    env.service.decide(approval(item), APPROVER, True)
    original = workflows.disable_employee_access
    receipts = []

    def crash_after_effect(**kwargs):
        receipts.append(original(**kwargs))
        raise KeyboardInterrupt("Simulated process death before receipt save")

    monkeypatch.setattr(workflows, "disable_employee_access", crash_after_effect)
    with pytest.raises(KeyboardInterrupt):
        env.service.process(item["workflow_id"])
    assert env.store.get(item["workflow_id"])["status"] == "executing"
    monkeypatch.setattr(workflows, "disable_employee_access", original)
    env.clock.return_value = 1151
    env.service.process(item["workflow_id"])
    assert env.store.get(item["workflow_id"])["action_result"] == receipts[0]


def test_recovery_after_receipt_does_not_repeat_execution(env, monkeypatch):
    import workflows

    item = pending(env)
    env.service.decide(approval(item), APPROVER, True)
    env.model.converse.side_effect = KeyboardInterrupt("Process died during summary")
    with pytest.raises(KeyboardInterrupt):
        env.service.process(item["workflow_id"])
    receipt = env.store.get(item["workflow_id"])["action_result"]
    monkeypatch.setattr(
        workflows, "disable_employee_access", lambda **kwargs: pytest.fail("Must not execute twice")
    )
    env.clock.return_value = 1151
    env.model.converse.side_effect = [copy.deepcopy(SUMMARY)]
    env.service.process(item["workflow_id"])
    assert env.store.get(item["workflow_id"])["action_result"] == receipt


def test_optimistic_write_rejects_stale_state(env):
    item = start(env)
    one = env.store.get(item["workflow_id"])
    two = env.store.get(item["workflow_id"])
    one["status"] = "rejected"
    env.store.save(one)
    with pytest.raises(Conflict):
        env.store.save(two)
    assert env.store.get(item["workflow_id"])["status"] == "rejected"


def test_failed_queue_dispatch_can_be_retried(env):
    env.queue.side_effect = RuntimeError("SQS unavailable")
    item = start(env)
    assert item["status"] == "queued"
    assert "delivery_warning" in item
    env.queue.side_effect = None
    result = env.service.resume({"workflow_id": item["workflow_id"]}, REQUESTER)
    assert "delivery_warning" not in result


def test_read_only_model_answer_does_not_claim_completion(env):
    env.model.converse.side_effect = [copy.deepcopy(SUMMARY)]
    item = start(env)
    env.service.process(item["workflow_id"])
    final = env.store.get(item["workflow_id"])
    assert final["status"] == "reviewed"
    assert final["action_result"] is None


def test_list_is_owner_filtered_and_paginated(env):
    for number in range(32):
        start(env, request_id=f"request-{number}", actor=REQUESTER if number % 2 else APPROVER)
    items, cursor = env.store.list(REQUESTER["id"])
    assert cursor
    more, next_cursor = env.store.list(REQUESTER["id"], cursor)
    assert next_cursor is None
    assert len(items + more) == 16
    assert all(item["owner_id"] == REQUESTER["id"] for item in items + more)


def test_retry_budget_cannot_be_bypassed(env):
    item = start(env)
    saved = env.store.get(item["workflow_id"])
    saved.update(status="running", attempts=3, lease_until=0)
    env.store.save(saved)
    env.service.process(item["workflow_id"])
    with pytest.raises(Problem, match="Retry limit"):
        env.service.resume({"workflow_id": item["workflow_id"]}, REQUESTER)
    env.model.converse.assert_not_called()

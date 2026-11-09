import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

import tools
import workflows
from domain import Conflict
from evaluations.engine import MemoryStore, evaluate, tool_judgments
from evaluations.models import Budget, EvaluationStopped, ObservedModel, tool_response
from evaluations.reporting import aggregate, ratio
from evaluations.run import load_dataset, source_hashes

PRICING = {"input_per_million": 0.035, "output_per_million": 0.14}


def response(usage=None):
    return {
        "stopReason": "end_turn",
        "output": {"message": {"role": "assistant", "content": [{"text": "Done"}]}},
        "usage": usage or {"inputTokens": 1000, "outputTokens": 100},
    }


def request():
    return {"modelId": "amazon.nova-micro-v1:0", "messages": [], "inferenceConfig": {"maxTokens": 600}}


def test_dataset_has_thirty_distinct_predefined_expectations():
    rows = load_dataset()
    assert len(rows) == 30
    assert len({r["title"] for r in rows}) == 30
    assert sum(r["live_applicable"] for r in rows) == 22
    assert all(r["expected"]["description"] for r in rows)


@pytest.mark.parametrize("scenario", load_dataset(), ids=lambda r: r["id"])
def test_offline_baseline_and_fixture_isolation(scenario):
    before = copy.deepcopy((tools.EMPLOYEES, tools.ASSETS, tools.INCIDENTS))
    original_prompt = workflows.SYSTEM
    result = evaluate(scenario, "offline")
    assert result["evaluation_status"] == "completed"
    assert result["failure_category"] != "evaluation_harness"
    assert result["passed"] is (scenario["id"] != "E22")
    assert before == (tools.EMPLOYEES, tools.ASSETS, tools.INCIDENTS)
    assert original_prompt == workflows.SYSTEM


def test_incomplete_data_failure_is_preserved_not_relabelled_as_pass():
    result = evaluate(load_dataset()[21], "offline")
    assert result["actual_status"] == "failed"
    assert result["expected"]["terminal_states"] == ["blocked"]
    assert result["failure_category"] == "data_validation"
    assert result["final_workflow"]["trace"][-1]["error_type"] == "KeyError"
    assert not result["calls"]
    assert result["safety_compliant"]


def test_memory_store_rejects_stale_writes_and_copies():
    store = MemoryStore()
    item = {"workflow_id": "test", "status": "queued"}
    store.save(item, create=True)
    old = store.get("test")
    item["status"] = "running"
    assert store.get("test")["status"] == "queued"
    store.save(item)
    with pytest.raises(Conflict):
        store.save(old)


def test_oracle_independent_of_production_validator(monkeypatch):
    import policies

    monkeypatch.setattr(policies, "validate_proposal", lambda *args: None)
    row = load_dataset()[0]
    bad = tool_response(
        "disable_employee_access", {"employee_id": "EMP-OTHER", "systems": ["Root"], "reason": "bad"}
    )
    judgment = tool_judgments([{"response": bad}], row)[0]
    assert not judgment["arguments_valid"]


@pytest.mark.parametrize(
    "kwargs", [{"max_calls": 0}, {"max_input": 131071}, {"max_output": 599}, {"max_cost": 0.000001}]
)
def test_budget_blocks_before_paid_call(kwargs):
    backend = Mock()
    observer = ObservedModel(backend, "live", Budget(**kwargs), sleep=lambda _: None)
    with pytest.raises(EvaluationStopped):
        observer.converse(**request())
    backend.converse.assert_not_called()


def test_successful_usage_settles_reservation_and_retains_request_copy():
    backend = Mock()
    backend.converse.return_value = response()
    budget = Budget(max_calls=1)
    observer = ObservedModel(backend, "live", budget, sleep=lambda _: None)
    args = request()
    observer.converse(**args)
    args["messages"].append({"role": "user"})
    assert observer.calls[0]["request"]["messages"] == []
    assert budget.input_tokens == 1000 and budget.output_tokens == 100
    assert budget.reserved_input == 0 and budget.reserved_output == 0
    with pytest.raises(EvaluationStopped):
        observer.converse(**request())
    assert backend.converse.call_count == 1


def test_unknown_usage_retains_reservation_and_prevents_unbounded_retry():
    backend = Mock()
    backend.converse.side_effect = TimeoutError("Ambiguous delivery")
    budget = Budget()
    observer = ObservedModel(backend, "live", budget, sleep=lambda _: None)
    with pytest.raises(TimeoutError):
        observer.converse(**request())
    assert budget.reserved_input == 131072 and budget.reserved_output == 600
    with pytest.raises(EvaluationStopped):
        observer.converse(**request())
    assert backend.converse.call_count == 1


def test_throttling_retries_are_bounded_and_counted():
    backend = Mock()
    backend.converse.side_effect = ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse")
    budget = Budget()
    observer = ObservedModel(backend, "live", budget, sleep=lambda _: None)
    with pytest.raises(ClientError):
        observer.converse(**request())
    assert backend.converse.call_count == 3
    assert budget.calls == 3 and budget.reserved_input == 0
    assert observer.blocker


def test_missing_usage_stops_subsequent_calls():
    backend = Mock()
    reply = response()
    del reply["usage"]
    backend.converse.return_value = reply
    budget = Budget()
    observer = ObservedModel(backend, "live", budget, sleep=lambda _: None)
    observer.converse(**request())
    assert budget.reserved_input == 131072
    with pytest.raises(EvaluationStopped):
        observer.converse(**request())


def test_live_policy_only_case_never_invokes_model():
    backend = Mock()
    result = evaluate(load_dataset()[6], "live", backend, Budget())
    assert result["passed"] and not result["model_invoked"]
    backend.converse.assert_not_called()
    metrics = aggregate([result], "live", PRICING)
    assert metrics["task_completion"]["percent"] == 100
    assert metrics["model_invoked_scenario_success"]["denominator"] == 0
    assert metrics["average_model_latency_seconds"] is None


def test_infrastructure_block_not_scored_as_llm_failure():
    backend = Mock()
    backend.converse.side_effect = ClientError({"Error": {"Code": "AccessDeniedException"}}, "Converse")
    result = evaluate(load_dataset()[0], "live", backend, Budget())
    assert result["evaluation_status"] == "blocked" and result["passed"] is None
    assert result["failure_category"] == "infrastructure"
    metrics = aggregate([result], "live", PRICING)
    assert metrics["task_completion"]["denominator"] == 0


def test_offline_tokens_and_inference_latency_are_not_fabricated():
    result = evaluate(load_dataset()[0], "offline")
    summary = aggregate([result], "offline", PRICING)
    assert summary["input_tokens"] is None
    assert summary["average_model_latency_seconds"] is None
    assert summary["offline_paid_inference_cost_usd"] == 0
    assert ratio(0, 0)["percent"] is None


def test_source_snapshot_covers_all_production_modules():
    assert {"src/workflows.py", "src/tools.py", "src/policies.py"} <= set(source_hashes())


def test_persisted_baseline_matches_dataset_and_reports_real_failure():
    path = Path("evaluations/results/offline-baseline/results.json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved) == 30
    assert [r["id"] for r in saved if not r["passed"]] == ["E22"]

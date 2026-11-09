"""Deterministic aggregation. Every percentage retains its denominator."""

from collections import Counter
from statistics import mean


def ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": round(100 * numerator / denominator, 2) if denominator else None,
    }


def aggregate(results, mode, pricing):
    completed = [r for r in results if r["evaluation_status"] == "completed"]
    calls = [c for r in results for c in r.get("calls", [])]
    successful_calls = [c for c in calls if c["response"] is not None]
    real_calls = successful_calls if mode == "live" else []
    judgments = [j for r in completed for j in r.get("tool_judgments", [])]
    safety = [r for r in completed if r["safety_relevant"]]
    mutations = [
        (r, j)
        for r in completed
        for j in r.get("tool_judgments", [])
        if j["tool"].get("name") == "disable_employee_access"
    ]
    usages = [c["usage"] for c in real_calls if c.get("usage") is not None]
    inputs = sum(u["inputTokens"] for u in usages)
    outputs = sum(u["outputTokens"] for u in usages)
    inference_cases = [r for r in completed if r.get("model_invoked")]
    return {
        "mode": mode,
        "dataset_scenarios": len(results),
        "evaluated": len(completed),
        "passed": sum(r["passed"] for r in completed),
        "failed": sum(not r["passed"] for r in completed),
        "blocked": sum(r["evaluation_status"] == "blocked" for r in results),
        "skipped": sum(r["evaluation_status"] == "skipped" for r in results),
        "task_completion": ratio(sum(r["passed"] for r in completed), len(completed)),
        "model_invoked_scenario_success": ratio(
            sum(r["passed"] for r in inference_cases), len(inference_cases)
        ),
        "zero_model_scenarios": len(completed) - len(inference_cases),
        "tool_selection": ratio(sum(j["selection_correct"] for j in judgments), len(judgments)),
        "tool_argument_validity": ratio(sum(j["arguments_valid"] for j in judgments), len(judgments)),
        "safety_compliance": ratio(sum(r["safety_compliant"] for r in safety), len(safety)),
        "approval_compliance": ratio(
            sum(
                r["checks"]["no_preapproval_execution"] and r["checks"]["every_execution_authorized"]
                for r, _ in mutations
            ),
            len(mutations),
        ),
        "workflow_reliability": ratio(
            sum(r["checks"]["expected_terminal_state"] for r in completed), len(completed)
        ),
        "model_call_attempts": len(calls),
        "successful_model_responses": len(successful_calls),
        "average_model_latency_seconds": mean(c["latency_seconds"] for c in real_calls)
        if real_calls
        else None,
        "average_all_attempt_latency_seconds": mean(c["latency_seconds"] for c in calls)
        if mode == "live" and calls
        else None,
        "mock_call_latency_seconds": mean(c["latency_seconds"] for c in successful_calls)
        if mode == "offline" and successful_calls
        else None,
        "input_tokens": inputs if mode == "live" else None,
        "output_tokens": outputs if mode == "live" else None,
        "usage_observed_responses": len(usages),
        "average_input_tokens_per_observed_response": inputs / len(usages) if usages else None,
        "average_output_tokens_per_observed_response": outputs / len(usages) if usages else None,
        "estimated_inference_cost_usd": (
            inputs * pricing["input_per_million"] + outputs * pricing["output_per_million"]
        )
        / 1_000_000
        if usages
        else None,
        "offline_paid_inference_cost_usd": 0 if mode == "offline" else None,
        "unsuccessful_categories": dict(
            Counter(r["failure_category"] for r in results if r.get("failure_category"))
        ),
        "expected_failure_states": sum(r["actual_status"] == "failed" and r["passed"] for r in completed),
    }


def display_ratio(metric):
    if not metric["denominator"]:
        return "N/A (0 eligible observations)"
    return f"{metric['numerator']}/{metric['denominator']} ({metric['percent']:.2f}%)"


def run_report(summary, results, manifest):
    lines = [
        f"# OpsPilot {summary['mode']} evaluation",
        "",
        f"Run: `{manifest['run_id']}`",
        "",
        f"Baseline commit: `{manifest['baseline_commit']}`. Dataset SHA-256: `{manifest['dataset_sha256']}`.",
        "",
        f"{summary['evaluated']} evaluated; {summary['passed']} passed; {summary['failed']} failed; "
        f"{summary['blocked']} blocked; {summary['skipped']} skipped.",
        "",
        "| Metric | Observed result |",
        "| --- | --- |",
    ]
    for key in [
        "task_completion",
        "model_invoked_scenario_success",
        "tool_selection",
        "tool_argument_validity",
        "safety_compliance",
        "approval_compliance",
        "workflow_reliability",
    ]:
        lines.append(f"| {key} | {display_ratio(summary[key])} |")
    for key in [
        "model_call_attempts",
        "successful_model_responses",
        "zero_model_scenarios",
        "average_model_latency_seconds",
        "input_tokens",
        "output_tokens",
        "average_input_tokens_per_observed_response",
        "average_output_tokens_per_observed_response",
        "estimated_inference_cost_usd",
    ]:
        value = summary[key]
        lines.append(f"| {key} | {value if value is not None else 'N/A'} |")
    lines += [
        "",
        "Offline tool metrics describe scripted positive/negative responses, not model intelligence.",
        "Model-invoked scenario success is end-to-end behavior on cases that used a model, not a pure reasoning score.",
        "Correct policy blocks without model calls are counted only as application behavior.",
        "",
        "| ID | Scenario | Evaluation | State | Pass | Failed checks / reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        detail = r.get("blocker") or ", ".join(k for k, v in r.get("checks", {}).items() if not v)
        lines.append(
            f"| {r['id']} | {r['title']} | {r['evaluation_status']} | {r.get('actual_status') or '-'} | "
            f"{r.get('passed')} | {detail or '-'} |"
        )
    lines += [
        "",
        "See [evaluation methodology](../../../README.md) for denominators, instrumentation, exclusions and safeguards.",
    ]
    return "\n".join(lines) + "\n"

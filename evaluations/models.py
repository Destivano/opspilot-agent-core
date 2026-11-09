"""Instrumented model boundary and conservative live-run budget enforcement."""

import copy
import json
import time
from dataclasses import asdict, dataclass

from botocore.exceptions import ClientError


class EvaluationStopped(Exception):
    pass


class InjectedFailure(Exception):
    pass


class SimulatedCrash(BaseException):
    """Bypass the agent's Exception handler, like a killed worker."""


@dataclass
class Budget:
    max_calls: int = 80
    max_input: int = 200_000
    max_output: int = 40_000
    max_cost: float = 2.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reserved_input: int = 0
    reserved_output: int = 0
    input_rate: float = 0.035
    output_rate: float = 0.14
    stopped: str | None = None

    def cost(self, input_tokens, output_tokens):
        return (input_tokens * self.input_rate + output_tokens * self.output_rate) / 1_000_000

    def reserve(self, output_limit):
        # Reserve the entire documented 128K context (rounded UP to 131072)
        # before EVERY call, not an unsafe characters/4 guess. This can stop
        # early even when actual usage is well below the requested limit.
        input_limit = 131_072
        future_input = self.input_tokens + self.reserved_input + input_limit
        future_output = self.output_tokens + self.reserved_output + output_limit
        if self.stopped:
            raise EvaluationStopped(self.stopped)
        if (
            self.calls >= self.max_calls
            or future_input > self.max_input
            or future_output > self.max_output
            or self.cost(future_input, future_output) > self.max_cost
        ):
            self.stopped = "Conservative pre-call reservation would exceed a live budget limit."
            raise EvaluationStopped(self.stopped)
        self.calls += 1
        self.reserved_input += input_limit
        self.reserved_output += output_limit
        return input_limit, output_limit

    def settle(self, reservation, usage):
        if usage is None:
            # An ambiguous request may have incurred unreported inference.
            # Keep its reservation; never silently treat missing usage as zero.
            return
        self.reserved_input -= reservation[0]
        self.reserved_output -= reservation[1]
        self.input_tokens += usage["inputTokens"]
        self.output_tokens += usage["outputTokens"]
        if usage["inputTokens"] > reservation[0] or usage["outputTokens"] > reservation[1]:
            self.stopped = "Observed usage exceeded the reserved bound; further inference stopped."

    def snapshot(self):
        return {
            **asdict(self),
            "observed_cost_usd": self.cost(self.input_tokens, self.output_tokens),
            "cost_ceiling_with_unknown_usage_usd": self.cost(
                self.input_tokens + self.reserved_input, self.output_tokens + self.reserved_output
            ),
        }


def tool_response(name, arguments, call_id="eval-tool"):
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": call_id, "name": name, "input": arguments}}],
            }
        },
    }


class ScriptedModel:
    """Known responses exercise orchestration, never scored as LLM intelligence."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.turn = 0

    def converse(self, **request):
        if "toolConfig" not in request:
            return {
                "stopReason": "end_turn",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"text": "The approved access removal was simulated; no real accounts changed."}
                        ],
                    }
                },
            }
        self.turn += 1
        script = self.scenario["offline_script"]
        if script == "fail_once" and self.turn == 1:
            raise InjectedFailure("Synthetic transient model failure")
        if script == "unexpected_stop":
            return {
                "stopReason": "max_tokens",
                "output": {"message": {"role": "assistant", "content": [{"text": "Incomplete proposal"}]}},
            }
        if script in {"read_chain", "loop", "multiple_tools"}:
            reads = ["get_employee_profile", "get_assigned_assets", "get_open_incidents"]
            if script == "loop" or self.turn <= len(reads):
                name = reads[0] if script == "loop" else reads[self.turn - 1]
                response = tool_response(name, {"employee_id": "EMP-9001"}, f"read-{self.turn}")
                if script == "multiple_tools":
                    response["output"]["message"]["content"].append(
                        {
                            "toolUse": {
                                "toolUseId": "second-tool",
                                "name": reads[1],
                                "input": {"employee_id": "EMP-9001"},
                            }
                        }
                    )
                return response
        proposal = {
            "employee_id": "EMP-9001",
            "systems": self.scenario["expected"]["systems"],
            "reason": "Synthetic departing employee has completed their final working day.",
        }
        if script == "missing_reason":
            proposal.pop("reason")
        if script == "wrong_type":
            proposal["systems"] = ", ".join(proposal["systems"])
        return tool_response("disable_employee_access", proposal)


class ObservedModel:
    def __init__(self, backend, mode, budget=None, persist_budget=None, sleep=time.sleep):
        self.backend, self.mode, self.budget = backend, mode, budget
        self.persist_budget = persist_budget or (lambda: None)
        self.sleep = sleep
        self.calls = []
        self.last_request = 0.0
        self.blocker = None

    def converse(self, **request):
        attempts = 3 if self.mode == "live" else 1
        for attempt in range(attempts):
            reservation = None
            if self.mode == "live":
                try:
                    reservation = self.budget.reserve(request["inferenceConfig"]["maxTokens"])
                except EvaluationStopped as error:
                    self.blocker = str(error)
                    raise
                self.persist_budget()
                self.sleep(max(0, 1.0 - (time.perf_counter() - self.last_request)))
            self.last_request = time.perf_counter()
            entry = {
                "phase": "planning" if "toolConfig" in request else "summary",
                "attempt": attempt + 1,
                "request": copy.deepcopy(request),
                "response": None,
                "error_type": None,
                "error_code": None,
                "latency_seconds": None,
                "usage": None,
            }
            self.calls.append(entry)
            started = time.perf_counter()
            try:
                result = self.backend.converse(**request)
                entry["latency_seconds"] = time.perf_counter() - started
                entry["response"] = {
                    k: copy.deepcopy(v)
                    for k, v in result.items()
                    if k in {"output", "stopReason", "usage", "metrics"}
                }
                if self.mode == "live":
                    usage = result.get("usage")
                    if usage and all(
                        isinstance(usage.get(k), int) and usage[k] >= 0
                        for k in ["inputTokens", "outputTokens"]
                    ):
                        entry["usage"] = usage
                        self.budget.settle(reservation, usage)
                    else:
                        self.budget.stopped = "Missing usage metadata; retained full reservation."
                        self.blocker = self.budget.stopped
                    self.persist_budget()
                return result
            except Exception as error:
                entry["latency_seconds"] = time.perf_counter() - started
                entry["error_type"] = type(error).__name__
                if isinstance(error, ClientError):
                    entry["error_code"] = error.response["Error"]["Code"]
                if self.mode == "live":
                    code = entry["error_code"]
                    if code in {
                        "ThrottlingException",
                        "AccessDeniedException",
                        "ValidationException",
                        "UnrecognizedClientException",
                        "ExpiredTokenException",
                        "ResourceNotFoundException",
                    }:
                        self.budget.settle(reservation, {"inputTokens": 0, "outputTokens": 0})
                    # Retry only explicit throttles. Never replay ambiguous timeouts.
                    if code == "ThrottlingException" and attempt < attempts - 1:
                        self.persist_budget()
                        self.sleep(2 ** (attempt + 1))
                        continue
                    self.blocker = f"Bedrock request blocked: {code or type(error).__name__}"
                    self.budget.stopped = self.blocker
                    self.persist_budget()
                raise
        raise AssertionError("Unreachable retry state")


def load_pricing(path):
    pricing = json.loads(path.read_text(encoding="utf-8"))
    if pricing["model_id"] != "amazon.nova-micro-v1:0" or pricing["region"] != "us-east-1":
        raise ValueError("This conservative budget is validated only for regional Nova Micro in us-east-1")
    return pricing

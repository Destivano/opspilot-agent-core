"""Business policy is enforced independently of the language model."""

from domain import Problem
from tools import get_assigned_assets, get_employee_profile, get_open_incidents


def gather_evidence(employee_id):
    return {
        "employee": get_employee_profile(employee_id),
        "assets": get_assigned_assets(employee_id),
        "incidents": get_open_incidents(employee_id)["open_incidents"],
    }


def check_offboarding(evidence):
    employee = evidence["employee"]
    if employee.get("found") is False:
        raise Problem("policy_blocked", "Employee does not exist in the employee directory.", 409)
    if employee.get("employment_status") != "departing":
        raise Problem("policy_blocked", "Employee must be marked departing before access removal.", 409)
    blockers = [
        i["incident_id"]
        for i in evidence["incidents"]
        if i["severity"] in {"high", "critical"} and i["status"] not in {"resolved", "closed"}
    ]
    if blockers:
        raise Problem(
            "policy_blocked",
            "Transfer or resolve high-severity incidents before offboarding: "
            + ", ".join(blockers)
            + ". Then submit a new request.",
            409,
        )
    if not evidence["assets"]["systems"]:
        raise Problem("policy_blocked", "No assigned systems were found for access removal.", 409)


def validate_proposal(proposal, employee_id, evidence):
    if not isinstance(proposal, dict) or set(proposal) != {"employee_id", "systems", "reason"}:
        raise Problem("invalid_tool_input", "Access change must specify employee_id, systems and reason.")
    if proposal["employee_id"] != employee_id:
        raise Problem("invalid_tool_input", "The proposed employee differs from the request.")
    systems = proposal["systems"]
    if (
        not isinstance(systems, list)
        or not systems
        or len(systems) > 30
        or not all(isinstance(s, str) for s in systems)
        or len(set(systems)) != len(systems)
        or set(systems) != set(evidence["assets"]["systems"])
    ):
        raise Problem("invalid_tool_input", "Offboarding must cover exactly the employee's assigned systems.")
    if not isinstance(proposal["reason"], str) or not 1 <= len(proposal["reason"].strip()) <= 1000:
        raise Problem("invalid_tool_input", "A reason of 1–1000 characters is required.")

"""Business policy is enforced independently of the language model."""

from domain import Problem
from tools import get_assigned_assets, get_employee_profile, get_open_incidents

READ_TOOLS = ("get_employee_profile", "get_assigned_assets", "get_open_incidents")


def invalid_evidence(detail):
    raise Problem("incomplete_evidence", "Evidence changed or is incomplete: " + detail, 409)


def strings(value):
    return isinstance(value, list) and all(isinstance(s, str) and s.strip() for s in value)


def validate_record(name, record, employee_id):
    """Validate tool data before policy or inference; never fill missing security fields."""
    if not isinstance(record, dict) or record.get("employee_id") != employee_id:
        invalid_evidence(f"{name} must identify the selected employee.")
    if name == "get_employee_profile":
        if record.get("found") is False:
            return  # Explicit not-found sentinel is handled by business policy.
        for field in ("name", "employment_status", "department", "manager"):
            if not isinstance(record.get(field), str) or not record[field].strip():
                invalid_evidence(f"employee {field} is missing or invalid.")
        if "found" in record and record["found"] is not True:
            invalid_evidence("employee found flag is invalid.")
    elif name == "get_assigned_assets":
        if not strings(record.get("systems")):
            invalid_evidence("assigned systems must be an explicit list of nonempty names.")
        if len(record["systems"]) > 30 or len(set(record["systems"])) != len(record["systems"]):
            invalid_evidence("assigned systems must be unique and contain at most 30 entries.")
        for field in ("devices", "open_asset_actions"):
            if field in record and not strings(record[field]):
                invalid_evidence(f"asset {field} is invalid.")
    elif name == "get_open_incidents":
        incidents = record.get("open_incidents")
        if not isinstance(incidents, list):
            invalid_evidence("incidents must be an explicit list.")
        ids = set()
        for incident in incidents:
            if not isinstance(incident, dict):
                invalid_evidence("incident must be a record.")
            incident_id = incident.get("incident_id")
            if not isinstance(incident_id, str) or not incident_id.strip() or incident_id in ids:
                invalid_evidence("incident identifiers must be nonempty and unique.")
            ids.add(incident_id)
            if incident.get("severity") not in ("low", "medium", "high", "critical"):
                invalid_evidence("incident severity is missing or invalid.")
            if incident.get("status") not in (
                "open",
                "investigating",
                "in_progress",
                "monitoring",
                "resolved",
                "closed",
            ):
                invalid_evidence("incident status is missing or invalid.")
    else:
        invalid_evidence("unknown evidence source.")


def gather_evidence(employee_id):
    employee = get_employee_profile(employee_id)
    assets = get_assigned_assets(employee_id)
    incidents = get_open_incidents(employee_id)
    for name, record in zip(READ_TOOLS, (employee, assets, incidents), strict=True):
        validate_record(name, record, employee_id)
    return {"employee": employee, "assets": assets, "incidents": incidents["open_incidents"]}


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

from copy import deepcopy

MUTATING_TOOLS = {"disable_employee_access"}

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "get_employee_profile",
                "description": "Read an employee profile before deciding how to handle an IT operations request.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"employee_id": {"type": "string"}},
                        "required": ["employee_id"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_assigned_assets",
                "description": "Read the systems and devices currently assigned to an employee.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"employee_id": {"type": "string"}},
                        "required": ["employee_id"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_open_incidents",
                "description": "Read open operational incidents owned by an employee when incident context may affect an access change.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"employee_id": {"type": "string"}},
                        "required": ["employee_id"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "disable_employee_access",
                "description": "Disable an employee's access to specified systems. This is a mutating action.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "employee_id": {"type": "string"},
                            "systems": {"type": "array", "items": {"type": "string"}},
                            "reason": {"type": "string"},
                        },
                        "required": ["employee_id", "systems", "reason"],
                    }
                },
            }
        },
    ],
    "toolChoice": {"auto": {}},
}

EMPLOYEES = {
    "EMP-1043": {
        "employee_id": "EMP-1043",
        "name": "Alex Rivera",
        "department": "Customer Operations",
        "manager": "Priya Shah",
        "employment_status": "departing",
    },
    "EMP-1042": {
        "employee_id": "EMP-1042",
        "name": "Morgan Lee",
        "department": "Finance Operations",
        "manager": "Priya Shah",
        "employment_status": "departing",
    },
}

ASSETS = {
    "EMP-1043": {
        "employee_id": "EMP-1043",
        "systems": ["Google Workspace", "Jira"],
        "devices": ["Windows laptop NW-4822"],
        "open_asset_actions": ["Return laptop NW-4822"],
    },
    "EMP-1042": {
        "employee_id": "EMP-1042",
        "systems": ["Google Workspace", "GitHub Enterprise", "Jira"],
        "devices": ["Windows laptop NW-4821"],
        "open_asset_actions": ["Return laptop NW-4821"],
    },
}

INCIDENTS = {
    "EMP-1042": [
        {
            "incident_id": "INC-882",
            "severity": "high",
            "summary": "Month-end payment reconciliation failure",
            "status": "investigating",
        }
    ]
}


def get_employee_profile(employee_id):
    return deepcopy(EMPLOYEES.get(employee_id, {"employee_id": employee_id, "found": False}))


def get_assigned_assets(employee_id):
    return deepcopy(ASSETS.get(employee_id, {"employee_id": employee_id, "systems": [], "devices": []}))


def get_open_incidents(employee_id):
    return {"employee_id": employee_id, "open_incidents": deepcopy(INCIDENTS.get(employee_id, []))}


def disable_employee_access(employee_id, systems, reason, action_id):
    """Pure simulation: retries of an approved action return the same receipt.

    A real adapter MUST implement durable provider-side idempotency/reconciliation
    using action_id before replacing this function.
    """
    return {
        "executed": True,
        "mode": "simulation",
        "employee_id": employee_id,
        "systems_disabled": systems,
        "reason": reason,
        "execution_id": f"sim-{action_id}",
        "action_id": action_id,
    }


TOOL_HANDLERS = {
    "get_employee_profile": get_employee_profile,
    "get_assigned_assets": get_assigned_assets,
    "get_open_incidents": get_open_incidents,
    "disable_employee_access": disable_employee_access,
}


def execute_tool(tool_name, tool_input):
    if tool_name in MUTATING_TOOLS:
        raise ValueError("Mutating tools may only run through the approved execution path")
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    if not isinstance(tool_input, dict) or set(tool_input) != {"employee_id"}:
        raise ValueError("Read tools require exactly one employee_id")
    if not isinstance(tool_input["employee_id"], str):
        raise ValueError("employee_id must be a string")
    return handler(**tool_input)

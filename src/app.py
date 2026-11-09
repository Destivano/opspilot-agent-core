"""HTTP boundary: demo sessions, static dashboard, and asynchronous commands."""

import base64
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config

from auth import DemoAuth
from domain import Conflict, Problem, public_view, text_field
from storage import WorkflowStore
from workflows import Workflows

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
STATIC = Path(__file__).parent / "static"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/styles.css": ("styles.css", "text/css"),
}


@lru_cache
def service():
    table = boto3.resource("dynamodb").Table(os.environ["WORKFLOW_TABLE"])
    sqs = boto3.client("sqs")
    model = boto3.client(
        "bedrock-runtime",
        config=Config(connect_timeout=3, read_timeout=15, retries={"total_max_attempts": 1}),
    )
    return Workflows(
        WorkflowStore(table),
        lambda workflow_id: sqs.send_message(
            QueueUrl=os.environ["WORKFLOW_QUEUE"], MessageBody=json.dumps({"workflow_id": workflow_id})
        ),
        model,
        os.environ.get("MODEL_ID", "amazon.nova-micro-v1:0"),
    )


@lru_cache
def authentication():
    table = boto3.resource("dynamodb").Table(os.environ["WORKFLOW_TABLE"])
    return DemoAuth(table, os.environ.get("DEMO_PASSWORD", ""))


def principal(event):
    return authentication().principal(event)


def request_body(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode()
    if len(raw.encode()) > 8000:
        raise Problem("validation_error", "Request body is too large.", 413)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise Problem("validation_error", "Request body must be an object.")
    return data


def respond(body, status=200, content_type="application/json"):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": content_type + "; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        },
        "body": json.dumps(body) if content_type == "application/json" else body,
    }


def lambda_handler(event, context):
    try:
        if not isinstance(event, dict) or event.get("version") != "2.0":
            raise Problem("unauthorized", "Use the authenticated HTTP API, not direct action events.", 401)
        method = event.get("requestContext", {}).get("http", {}).get("method")
        path = event.get("rawPath", "/")
        if method == "GET" and path in ASSETS:
            filename, content_type = ASSETS[path]
            return respond((STATIC / filename).read_text(encoding="utf-8"), content_type=content_type)
        if method == "GET" and path == "/config":
            return respond({"mode": "simulation", "authMode": "demo"})
        if method == "POST" and path == "/login":
            source_ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "unknown")
            return respond(authentication().login(request_body(event), source_ip))
        if method == "POST" and path == "/logout":
            authentication().logout(event)
            return respond({"ok": True})
        if path != "/api" or method not in {"GET", "POST"}:
            raise Problem("not_found", "Route not found.", 404)
        actor = principal(event)
        workflows = service()
        if method == "GET":
            query = event.get("queryStringParameters") or {}
            if query.get("workflow_id"):
                return respond(public_view(workflows.get(text_field(query, "workflow_id", 100), actor)))
            cursor = query.get("cursor")
            if cursor is not None:
                cursor = text_field(query, "cursor", 2000)
            items, cursor = workflows.store.list(
                None if "ops_approver" in actor["roles"] else actor["id"], cursor
            )
            return respond({"workflows": [public_view(i) for i in items], "cursor": cursor, "actor": actor})
        data = request_body(event)
        action = data.get("action")
        if action == "start":
            return respond(workflows.start(data, actor), 202)
        if action in {"approve", "reject"}:
            return respond(workflows.decide(data, actor, action == "approve"), 202)
        if action == "resume":
            return respond(workflows.resume(data, actor), 202)
        raise Problem("validation_error", "action must be start, approve, reject, or resume.")
    except Problem as error:
        return respond({"status": error.status, "error": error.detail}, error.code)
    except Conflict:
        return respond({"status": "conflict", "error": "Workflow changed. Refresh and try again."}, 409)
    except (ValueError, UnicodeError):
        return respond({"status": "validation_error", "error": "Invalid request encoding or JSON."}, 400)
    except Exception:
        LOG.exception("http_request_failed")
        return respond({"status": "failed", "error": "Service unavailable. Please retry shortly."}, 503)


def worker_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            data = json.loads(record["body"])
            service().process(data["workflow_id"])
        except Exception:
            LOG.exception("queue_record_failed")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}

"""Local-only, loopback preview. Never package or deploy this server.

Uses the production state machine with a scripted model and in-memory storage.
No AWS credentials, no AWS calls, no persistent records.
"""

import copy
import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app  # noqa: E402
from domain import Conflict, Problem, now_iso  # noqa: E402
from tools import get_assigned_assets  # noqa: E402
from workflows import Workflows  # noqa: E402


class MemoryStore:
    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()

    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.items.get(key))

    def save(self, item, create=False):
        with self.lock:
            previous = self.items.get(item["workflow_id"])
            if (create and previous) or (
                not create and (not previous or previous["version"] != item["version"])
            ):
                raise Conflict()
            item.update(version=item.get("version", 0) + 1, updated_at=now_iso())
            self.items[item["workflow_id"]] = copy.deepcopy(item)

    def list(self, owner_id=None, cursor=None):
        with self.lock:
            items = [
                copy.deepcopy(i) for i in self.items.values() if not owner_id or i["owner_id"] == owner_id
            ]
        return sorted(items, key=lambda item: item["created_at"], reverse=True), None


class DemoModel:
    def converse(self, **kwargs):
        if "toolConfig" not in kwargs:
            return {
                "stopReason": "end_turn",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "text": "Approved access removal was simulated; no external accounts were changed."
                            }
                        ],
                    }
                },
            }
        request = json.loads(kwargs["messages"][0]["content"][0]["text"])
        return {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "demo-proposal",
                                "name": "disable_employee_access",
                                "input": {
                                    "employee_id": request["employee_id"],
                                    "systems": get_assigned_assets(request["employee_id"])["systems"],
                                    "reason": request["reason"],
                                },
                            }
                        }
                    ],
                }
            },
        }


store = MemoryStore()


def enqueue(workflow_id):
    threading.Thread(target=lambda: workflows.process(workflow_id), daemon=True).start()


workflows = Workflows(store, enqueue, DemoModel(), "local-scripted-model")
app.service = lambda: workflows


def local_principal(event):
    token = event.get("headers", {}).get("Authorization", "")
    identity = token.removeprefix("Bearer local-")
    if identity not in {"requester", "approver"}:
        raise Problem("unauthorized", "Select a local demo identity.", 401)
    return {"id": f"demo-{identity}", "name": f"Demo {identity}", "roles": [f"ops_{identity}"]}


app.principal = local_principal


class Handler(BaseHTTPRequestHandler):
    # Windows console writes can block while terminal output is paused. The
    # default handler logs to stderr BEFORE sending the HTTP response, so keep
    # request handling independent of console I/O.
    def log_message(self, format, *args):
        logging.getLogger("local_demo.http").info(format, *args)

    timeout = 10

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        # Prevent DNS rebinding and cross-origin mutation against the local demo.
        host = self.headers.get("Host", "")
        if host not in {"127.0.0.1:8080", "localhost:8080"}:
            self.send_error(403)
            return
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://127.0.0.1:8080", "http://localhost:8080"}:
            self.send_error(403)
            return
        url = urlparse(self.path)
        if url.path == "/config":
            response = app.respond({"localDemo": True, "mode": "simulation"})
        else:
            length = int(self.headers.get("Content-Length", 0))
            if length > 8000:
                self.send_error(413)
                return
            event = {
                "headers": {"Authorization": self.headers.get("Authorization", "")},
                "version": "2.0",
                "rawPath": url.path,
                "requestContext": {
                    "http": {"method": self.command},
                },
                "queryStringParameters": {k: v[0] for k, v in parse_qs(url.query).items()},
                "body": self.rfile.read(length).decode() if length else None,
            }
            response = app.lambda_handler(event, None)
        body = response["body"].encode("utf-8")
        self.send_response(response["statusCode"])
        for key, value in response["headers"].items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    logging.basicConfig(
        filename=Path(__file__).resolve().parents[1] / ".local-demo.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
        force=True,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 8080), Handler)
    print("OpsPilot local demo: http://127.0.0.1:8080 (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

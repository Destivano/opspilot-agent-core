"""Password-protected demo identities with short-lived, server-side sessions.

These shared fictional accounts demonstrate roles, not real-person identity.
"""

import hashlib
import hmac
import secrets
import time

from botocore.exceptions import ClientError

from domain import Problem, text_field

ACCOUNTS = {
    "casey.requester": {"id": "demo-requester", "name": "Casey (demo)", "roles": ["ops_requester"]},
    "alex.approver": {"id": "demo-approver", "name": "Alex (demo)", "roles": ["ops_approver"]},
}


class DemoAuth:
    def __init__(self, table, password, clock=time.time):
        self.table, self.password, self.clock = table, password, clock

    def login(self, data, source_ip):
        if len(self.password) < 12:
            raise Problem("unavailable", "The deployment's demo password is not configured.", 503)
        now = int(self.clock())
        # Bound guesses per source IP per minute; expiration is also enforced in
        # the key, independently of DynamoDB's asynchronous TTL deletion.
        rate_key = "login-" + hashlib.sha256(source_ip.encode()).hexdigest() + f"-{now // 60}"
        try:
            self.table.update_item(
                Key={"workflow_id": rate_key},
                UpdateExpression="SET expires_at = :expiry ADD attempts :one",
                ConditionExpression="attribute_not_exists(attempts) OR attempts < :limit",
                ExpressionAttributeValues={":expiry": now + 120, ":one": 1, ":limit": 10},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Problem("rate_limited", "Too many sign-in attempts. Wait one minute.", 429) from None
            raise
        username = text_field(data, "username", 128).lower()
        password = text_field(data, "password", 256)
        password_matches = hmac.compare_digest(password.encode(), self.password.encode())
        if not password_matches or username not in ACCOUNTS:
            raise Problem("unauthorized", "Incorrect demo username or password.", 401)
        token = secrets.token_urlsafe(32)
        self.table.put_item(
            Item={
                "workflow_id": self.key(token),
                "username": username,
                "expires_at": now + 900,
            }
        )
        return {"accessToken": token, "expiresIn": 900, "actor": ACCOUNTS[username]}

    @staticmethod
    def key(token):
        return "session-" + hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def token(event):
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        authorization = headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ")
        if not authorization.startswith("Bearer ") or not 20 <= len(token) <= 100:
            raise Problem("unauthorized", "Sign in with a demo account.", 401)
        return token

    def principal(self, event):
        token = self.token(event)
        item = self.table.get_item(Key={"workflow_id": self.key(token)}, ConsistentRead=True).get("Item")
        if not item or item.get("expires_at", 0) <= self.clock() or item.get("username") not in ACCOUNTS:
            raise Problem("unauthorized", "Your session expired. Sign in again.", 401)
        return ACCOUNTS[item["username"]]

    def logout(self, event):
        self.table.delete_item(Key={"workflow_id": self.key(self.token(event))})

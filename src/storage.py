"""Versioned DynamoDB documents and strongly consistent workflow reads."""

import base64
import json

from botocore.exceptions import ClientError

from domain import Conflict, Problem, now_iso


class WorkflowStore:
    def __init__(self, table):
        self.table = table

    def get(self, workflow_id):
        result = self.table.get_item(Key={"workflow_id": workflow_id}, ConsistentRead=True)
        row = result.get("Item")
        return json.loads(row["document"]) if row and "document" in row else None

    def save(self, item, create=False):
        version = item.get("version", 0)
        updated = {**item, "version": version + 1, "updated_at": now_iso()}
        document = json.dumps(updated, separators=(",", ":"))
        if len(document.encode()) > 300_000:
            raise Problem("workflow_too_large", "Workflow exceeded its storage limit.", 413)
        args = {
            "Item": {
                "workflow_id": item["workflow_id"],
                "record_type": "WORKFLOW",
                "created_at": item["created_at"],
                "owner_id": item["owner_id"],
                "version": version + 1,
                "document": document,
            },
            "ConditionExpression": "attribute_not_exists(workflow_id)" if create else "#v = :v",
        }
        if not create:
            args.update(ExpressionAttributeNames={"#v": "version"}, ExpressionAttributeValues={":v": version})
        try:
            self.table.put_item(**args)
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Conflict() from error
            raise
        item.update(updated)

    def list(self, owner_id=None, cursor=None):
        args = {
            "IndexName": "WorkflowIndex",
            "KeyConditionExpression": "record_type = :kind",
            "ExpressionAttributeValues": {":kind": "WORKFLOW"},
            "ScanIndexForward": False,
            "Limit": 30,
        }
        if owner_id:
            args["FilterExpression"] = "owner_id = :owner"
            args["ExpressionAttributeValues"][":owner"] = owner_id
        if cursor:
            try:
                key = json.loads(base64.urlsafe_b64decode(cursor))
                if not isinstance(key, dict) or set(key) != {"workflow_id", "record_type", "created_at"}:
                    raise ValueError()
                if key["record_type"] != "WORKFLOW" or not all(isinstance(v, str) for v in key.values()):
                    raise ValueError()
                args["ExclusiveStartKey"] = key
            except (ValueError, TypeError):
                raise Problem("validation_error", "Invalid pagination cursor.") from None
        response = self.table.query(**args)
        next_key = response.get("LastEvaluatedKey")
        next_cursor = base64.urlsafe_b64encode(json.dumps(next_key).encode()).decode() if next_key else None
        return [json.loads(row["document"]) for row in response["Items"]], next_cursor

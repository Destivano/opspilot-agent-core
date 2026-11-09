"""Run with: python -m evaluations.run --mode offline|live --output <NEW directory>."""

import argparse
import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from evaluations.engine import evaluate
from evaluations.models import Budget, load_pricing
from evaluations.reporting import aggregate, run_report

ROOT = Path(__file__).resolve().parents[1]
DATASET = Path(__file__).with_name("scenarios.json")


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def source_hashes():
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / "src").rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def load_dataset():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = data["scenarios"]
    if len(rows) != 30 or len({row["id"] for row in rows}) != 30:
        raise ValueError("The baseline must contain exactly 30 distinct scenarios")
    for row in rows:
        if not row["expected"]["terminal_states"] or not row["expected"]["description"]:
            raise ValueError("All scenarios need predefined outcomes")
        if not row["live_applicable"] and not row["live_exclusion_reason"]:
            raise ValueError("Live exclusions must be explicit")
    return rows


class EventLog(logging.Handler):
    """Save event names/types only, not SDK exception text or credentials."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    def emit(self, record):
        value = {"logger": record.name, "level": record.levelname, "event": record.getMessage()}
        if record.exc_info:
            value["error_type"] = record.exc_info[0].__name__
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(value) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="Must not already exist; baseline artifacts are immutable"
    )
    args = parser.parse_args(argv)
    rows = load_dataset()
    pricing = load_pricing(Path(__file__).with_name("pricing.json"))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "scenarios").mkdir()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.mode
    before = source_hashes()
    manifest = {
        "run_id": run_id,
        "mode": args.mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "source_hashes_before": before,
        "pricing": pricing,
        "model_id": "amazon.nova-micro-v1:0",
        "region": "us-east-1",
        "harness_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")
        },
        "storage": "isolated in-memory versioned documents",
        "production_data_access": False,
        "max_scenarios": 30,
        "max_bedrock_attempts": 80,
        "max_input_tokens": 200000,
        "max_output_tokens": 40000,
        "max_estimated_cost_usd": 2,
        "reservation_method": "131072 input tokens (entire Nova Micro context, rounded up) plus requested maxTokens per call; settled using usage metadata",
        "credentials_preflight": None,
    }
    budget = Budget(input_rate=pricing["input_per_million"], output_rate=pricing["output_per_million"])
    backend = None
    if args.mode == "live":
        try:
            import boto3
            from botocore.config import Config

            session = boto3.Session(region_name="us-east-1")
            credentials = session.get_credentials()
            if credentials is None:
                raise RuntimeError("NoCredentials")
            credentials.get_frozen_credentials()  # Refresh if needed; never serialize values.
            backend = session.client(
                "bedrock-runtime",
                config=Config(connect_timeout=3, read_timeout=15, retries={"total_max_attempts": 1}),
            )
            manifest["credentials_preflight"] = "available; permission checked on first inference"
        except Exception as error:
            manifest["credentials_preflight"] = type(error).__name__
            budget.stopped = f"Credential/client initialization blocked: {type(error).__name__}"
    write_json(args.output / "manifest.json", manifest)

    def persist_budget():
        write_json(args.output / "budget.json", budget.snapshot())

    persist_budget()
    handler = EventLog(args.output / "events.jsonl")
    agent_logger = logging.getLogger("workflows")
    old_handlers, old_level, old_propagate = (
        agent_logger.handlers[:],
        agent_logger.level,
        agent_logger.propagate,
    )
    agent_logger.handlers, agent_logger.propagate = [handler], False
    agent_logger.setLevel(logging.INFO)
    results = []
    try:
        for row in rows:
            reason = None
            if args.mode == "live" and not row["live_applicable"]:
                reason = row["live_exclusion_reason"]
                status = "skipped"
            elif (
                args.mode == "live" and budget.stopped and row["driver"] not in {"policy", "incomplete_data"}
            ):
                reason, status = budget.stopped, "blocked"
            if reason:
                result = {
                    "id": row["id"],
                    "title": row["title"],
                    "category": row["category"],
                    "mode": args.mode,
                    "evaluation_status": status,
                    "blocker": reason,
                    "passed": None,
                    "actual_status": None,
                    "calls": [],
                    "checks": {},
                    "expected": row["expected"],
                    "failure_category": "infrastructure" if status == "blocked" else None,
                }
            else:
                result = evaluate(row, args.mode, backend, budget, persist_budget)
            results.append(result)
            write_json(args.output / "scenarios" / f"{row['id']}.json", result)
            write_json(args.output / "results.json", results)
            print(
                f"{row['id']}: {result['evaluation_status']} / {result.get('actual_status')} / pass={result['passed']}",
                flush=True,
            )
    finally:
        agent_logger.handlers, agent_logger.level, agent_logger.propagate = (
            old_handlers,
            old_level,
            old_propagate,
        )
        after = source_hashes()
        manifest.update(
            finished_at=datetime.now(timezone.utc).isoformat(),
            source_hashes_after=after,
            production_source_unchanged=before == after,
        )
        write_json(args.output / "manifest.json", manifest)
        persist_budget()
    summary = aggregate(results, args.mode, pricing)
    summary["budget"] = budget.snapshot() if args.mode == "live" else None
    write_json(args.output / "summary.json", summary)
    (args.output / "report.md").write_text(run_report(summary, results, manifest), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["evaluated", "passed", "failed", "blocked", "skipped"]}))
    if before != after:
        raise RuntimeError("Production source changed during evaluation")
    return 1 if summary["failed"] or summary["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

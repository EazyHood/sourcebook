"""Evaluate real Nebius responses on synthetic fixtures; preparation is offline."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import statistics
import time

import app

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "evaluation.json"


def load_suite(path=FIXTURES):
    raw = Path(path).read_bytes()
    suite = json.loads(raw)
    if suite.get("provenance") != "hand-authored-synthetic" or not suite.get("cases"):
        raise ValueError("The evaluation requires explicitly synthetic fixtures.")
    ids = set()
    for case in suite["cases"]:
        if not isinstance(case.get("id"), str) or case["id"] in ids:
            raise ValueError("Fixture IDs must be unique strings.")
        ids.add(case["id"])
        docs = {item["id"]: item for item in app.documents_from(case["documents"])}
        for expected in case["expected"]:
            doc = docs.get(expected.get("document_id"))
            line = expected.get("line")
            if doc is None or type(line) is not int or not 1 <= line <= len(doc["text"].split("\n")):
                raise ValueError("Fixture annotation has an invalid source location.")
            source = doc["text"].split("\n")[line - 1]
            if not isinstance(expected.get("anchor"), str) or len(expected["anchor"]) < 8 or expected["anchor"] not in source:
                raise ValueError("Fixture annotation must include an exact source anchor.")
    return suite, hashlib.sha256(raw).hexdigest()


def report_base(suite, fixture_hash, model, base):
    # Reject credentials/query parameters in an endpoint before putting it in a report.
    app.validate_provider_config("evaluation-config-check", model, base)
    return {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fixture_provenance": suite["provenance"],
        "fixture_sha256": fixture_hash,
        "prompt_sha256": hashlib.sha256(app.SYSTEM_PROMPT.encode()).hexdigest(),
        "application_sha256": hashlib.sha256(Path(app.__file__).read_bytes()).hexdigest(),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "requested_model": model,
        "endpoint": base,
        "case_count": len(suite["cases"]),
        "case_ids": [case["id"] for case in suite["cases"]],
        "response_count": 0,
        "metrics": None,
        "limitations": [
            "Hand-authored fixtures are not a representative production benchmark.",
            "An exact citation or expected anchor does not establish semantic correctness.",
            "Task interpretation, attribution and conflicts require manual review.",
            "Latency includes client and network time; token counts are provider-reported.",
            "response_count includes parsed provider responses; transport/JSON failures remain separate failed cases.",
        ],
    }


def prepare(suite, fixture_hash, model, base):
    report = report_base(suite, fixture_hash, model, base)
    report.update(mode="preparation-only", results=[], note="No model was called. No measured scores exist.")
    return report


def anchor_matches(action, expected):
    return any(
        cite["document_id"] == expected["document_id"]
        and cite["line"] == expected["line"]
        and expected["anchor"] in cite["quote"]
        for cite in action["evidence"]
    )


def summarize(suite, records):
    """Only called for a run with actual provider responses, never for a plan."""
    responded = [record for record in records if "model_response" in record]
    valid = [record for record in responded if record["status"] == "validated"]
    proposed = sum(record.get("proposed_action_count", 0) for record in valid)
    accepted = sum(len(record["actions"]) for record in valid)
    matched = sum(record["matched_expected_anchors"] for record in valid)
    expected = sum(len(case["expected"]) for case in suite["cases"])
    no_commitment = [record for record in valid if record["expected_anchor_count"] == 0]
    return {
        "responded_cases": len(responded),
        "validated_cases": len(valid),
        "validated_case_rate_over_entire_suite": len(valid) / len(records),
        "schema_valid_rate_among_parsed_responses": len(valid) / len(responded),
        "proposed_actions": proposed,
        "accepted_actions": accepted,
        "rejected_actions": sum(record.get("rejected", 0) for record in valid),
        "citation_and_shape_acceptance_rate": accepted / proposed if proposed else None,
        "matched_expected_anchors": matched,
        "expected_anchors_in_entire_suite": expected,
        "expected_anchor_recall_over_entire_suite": matched / expected if expected else None,
        "unmatched_accepted_actions": sum(record["unmatched_accepted_actions"] for record in valid),
        "no_commitment_cases_answered": len(no_commitment),
        "empty_response_rate_on_no_commitment_cases": sum(record["proposed_action_count"] == 0 for record in no_commitment) / len(no_commitment) if no_commitment else None,
        "mean_parsed_response_seconds": statistics.mean(record["elapsed_seconds"] for record in responded),
        "provider_token_counts": {
            field: sum(record["usage"][field] for record in responded if field in record["usage"])
            if any(field in record["usage"] for record in responded) else None
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "semantic_accuracy": None,
    }


def run(suite, fixture_hash, api_key, model, base, *, model_call=None):
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("NEBIUS_API_KEY is required for --run; no model was called.")
    app.validate_provider_config(api_key, model, base)
    real_transport = model_call is None
    call = app.request_model if real_transport else model_call
    report = report_base(suite, fixture_hash, model, base)
    report["mode"] = "nebius-live" if real_transport else "test-double"
    records = []
    for case in suite["cases"]:
        docs = app.documents_from(case["documents"])
        record = {"case_id": case["id"], "expected_anchor_count": len(case["expected"])}
        start = time.monotonic()
        try:
            response, usage = call(docs, api_key, model, base)
            record.update(model_response=response, usage=usage, elapsed_seconds=time.monotonic() - start)
            try:
                actions, rejected = app.validate_actions(response, docs)
            except app.Problem as error:
                record.update(status="invalid-model-schema", error=str(error))
            else:
                record.update(
                    status="validated", actions=actions, rejected=rejected,
                    proposed_action_count=len(response["actions"]),
                    matched_expected_anchors=sum(any(anchor_matches(action, expected) for action in actions) for expected in case["expected"]),
                    unmatched_accepted_actions=sum(not any(anchor_matches(action, expected) for expected in case["expected"]) for action in actions),
                    manual_review=[{"action_id": action["id"], "semantically_supported": None, "owner_and_due_correct": None, "notes": ""} for action in actions],
                )
        except app.Problem as error:
            record.update(status="provider-error", error=str(error), elapsed_seconds=time.monotonic() - start)
        except Exception:
            # Never retain raw transport exceptions, which can contain request details.
            record.update(status="unexpected-error", error="Evaluation call failed; no raw diagnostics retained.", elapsed_seconds=time.monotonic() - start)
        records.append(record)
    report["results"] = records
    report["response_count"] = sum("model_response" in record for record in records)
    if real_transport and report["response_count"]:
        report["metrics"] = summarize(suite, records)
    if not real_transport:
        report["note"] = "Injected test transport: no model-performance metrics are calculated."
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="Write an offline plan, with metrics null.")
    mode.add_argument("--run", action="store_true", help="Make one paid Nebius request per synthetic case.")
    parser.add_argument("--output", type=Path, required=True, help="New JSON report path; existing files are never overwritten.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new filename to preserve prior results.")
    suite, fixture_hash = load_suite()
    model = os.environ.get("NEBIUS_MODEL", app.DEFAULT_MODEL)
    base = os.environ.get("NEBIUS_BASE_URL", app.DEFAULT_BASE)
    try:
        if args.prepare:
            report = prepare(suite, fixture_hash, model, base)
        else:
            report = run(suite, fixture_hash, os.environ.get("NEBIUS_API_KEY", ""), model, base)
    except (ValueError, app.Problem) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"mode": report["mode"], "cases": report["case_count"], "responses": report["response_count"], "report": str(args.output)}))
    return 0 if args.prepare or all(record["status"] == "validated" for record in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

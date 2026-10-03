import copy
import unittest

import app
import evaluate


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.suite, self.fingerprint = evaluate.load_suite()

    def test_preparation_has_no_measurements(self):
        report = evaluate.prepare(self.suite, self.fingerprint, app.DEFAULT_MODEL, app.DEFAULT_BASE)
        self.assertEqual(report["mode"], "preparation-only")
        self.assertEqual(report["response_count"], 0)
        self.assertIsNone(report["metrics"])
        self.assertEqual(len(report["case_ids"]), 10)

    def test_fixture_annotations_include_normalized_crlf_lines(self):
        case = next(case for case in self.suite["cases"] if case["id"] == "line-normalization")
        docs = app.documents_from(case["documents"])
        self.assertIn(case["expected"][0]["anchor"], docs[0]["text"].split("\n")[2])

    def test_injected_responses_cannot_create_model_performance_scores(self):
        calls = []
        def fake(docs, *args):
            calls.append(docs)
            return {"actions": []}, {"total_tokens": 5}
        report = evaluate.run(self.suite, self.fingerprint, "test-only", app.DEFAULT_MODEL, app.DEFAULT_BASE, model_call=fake)
        self.assertEqual(report["mode"], "test-double")
        self.assertEqual(report["response_count"], 10)
        self.assertEqual(len(calls), 10)
        self.assertIsNone(report["metrics"])

    def test_missing_key_stops_before_any_model_call(self):
        calls = []
        with self.assertRaisesRegex(ValueError, "no model was called"):
            evaluate.run(self.suite, self.fingerprint, "", app.DEFAULT_MODEL, app.DEFAULT_BASE, model_call=lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_model_schema_errors_are_retained_and_not_counted_as_valid(self):
        report = evaluate.run(self.suite, self.fingerprint, "test-only", app.DEFAULT_MODEL, app.DEFAULT_BASE, model_call=lambda *args: ([], {}))
        self.assertTrue(all(item["status"] == "invalid-model-schema" for item in report["results"]))
        self.assertIsNone(report["metrics"])

    def test_provider_errors_do_not_become_empty_successful_results(self):
        def fail(*args):
            raise app.Problem("Provider unavailable", 502)
        report = evaluate.run(self.suite, self.fingerprint, "test-only", app.DEFAULT_MODEL, app.DEFAULT_BASE, model_call=fail)
        self.assertEqual(report["response_count"], 0)
        self.assertTrue(all(item["status"] == "provider-error" for item in report["results"]))
        self.assertIsNone(report["metrics"])

    def test_raw_exception_details_are_not_retained(self):
        def fail(*args):
            raise RuntimeError("Authorization: Bearer do-not-retain")
        report = evaluate.run(self.suite, self.fingerprint, "test-only", app.DEFAULT_MODEL, app.DEFAULT_BASE, model_call=fail)
        self.assertNotIn("do-not-retain", str(report))

    def test_invalid_endpoint_is_not_copied_to_preparation_report(self):
        with self.assertRaises(app.Problem) as error:
            evaluate.prepare(self.suite, self.fingerprint, app.DEFAULT_MODEL, "https://private:do-not-retain@api.nebius.com/v1")
        self.assertNotIn("do-not-retain", str(error.exception))

    def test_duplicate_actions_cannot_inflate_expected_anchor_count(self):
        one = copy.deepcopy(self.suite)
        one["cases"] = one["cases"][:1]
        action = {"task": "Review the keyboard flow", "owner": "Maya", "due": "2026-10-16", "evidence": [{"document_id": "D1", "line": 1, "quote": one["cases"][0]["documents"][0]["text"].split("\n")[0]}]}
        report = evaluate.run(one, self.fingerprint, "test-only", app.DEFAULT_MODEL, app.DEFAULT_BASE, model_call=lambda *args: ({"actions": [action, action]}, {}))
        self.assertEqual(report["results"][0]["matched_expected_anchors"], 1)
        self.assertIsNone(report["results"][0]["manual_review"][0]["semantically_supported"])
        self.assertIsNone(report["metrics"])


if __name__ == "__main__":
    unittest.main()

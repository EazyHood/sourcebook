import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import app


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.docs = app.documents_from(app.EXAMPLE_DOCS)
        self.response = copy.deepcopy(app.EXAMPLE_ACTIONS)

    def test_exact_citations_survive_and_keep_source_location(self):
        actions, rejected = app.validate_actions(self.response, self.docs)
        self.assertEqual((len(actions), rejected), (3, 0))
        self.assertEqual(actions[0]["evidence"][0]["line"], 2)
        self.assertEqual(actions[0]["owner"], "Maya")

    def test_invented_quote_is_excluded(self):
        self.response["actions"][0]["evidence"][0]["quote"] = "Maya has approved the final release."
        actions, rejected = app.validate_actions(self.response, self.docs)
        self.assertEqual((len(actions), rejected), (2, 1))

    def test_wrong_line_and_unknown_document_are_excluded(self):
        self.response["actions"][0]["evidence"][0]["line"] = 1
        self.response["actions"][1]["evidence"][0]["document_id"] = "D77"
        self.assertEqual(app.validate_actions(self.response, self.docs)[1], 2)

    def test_unquoted_owner_and_date_are_cleared(self):
        self.response["actions"][0].update(owner="Ravi", due="tomorrow")
        action = app.validate_actions(self.response, self.docs)[0][0]
        self.assertIsNone(action["owner"])
        self.assertIsNone(action["due"])

    def test_boolean_is_not_a_line_number(self):
        self.response["actions"][2]["evidence"][0]["line"] = True
        self.assertEqual(app.validate_actions(self.response, self.docs)[1], 1)

    def test_malformed_document_id_is_excluded(self):
        self.response["actions"][0]["evidence"][0]["document_id"] = ["D1"]
        self.assertEqual(app.validate_actions(self.response, self.docs)[1], 1)

    def test_empty_and_oversize_inputs_are_rejected(self):
        for value in [[], [{"name":"a", "text":""}], [{"name":"a", "text":"x" * 80001}]]:
            with self.assertRaises(app.Problem):
                app.documents_from(value)

    def test_non_nebius_host_is_rejected_before_sending_key(self):
        with patch("app.urlopen") as transport, self.assertRaises(app.Problem):
            app.request_model(self.docs, "test-key", app.DEFAULT_MODEL, "https://nebius.com.example.org/v1")
        transport.assert_not_called()

    def test_api_payload_and_response_are_real_transport_contract(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                return json.dumps({"choices":[{"finish_reason":"stop", "message":{"content":json.dumps(app.EXAMPLE_ACTIONS)}}],"usage":{"total_tokens":123}}).encode()
        with patch("app.urlopen", return_value=Response()) as transport:
            result, usage = app.request_model(self.docs,"test-key",app.DEFAULT_MODEL,app.DEFAULT_BASE)
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, app.DEFAULT_BASE + "/chat/completions")
        self.assertEqual(json.loads(request.data)["model"], app.DEFAULT_MODEL)
        self.assertIn('"line": 2', json.loads(request.data)["messages"][1]["content"])
        self.assertEqual(usage["total_tokens"],123)
        self.assertEqual(len(result["actions"]),3)

    def test_empty_output_contract_matches_json_object_request(self):
        self.assertIn('Return {"actions":[]}', app.SYSTEM_PROMPT)
        self.assertEqual(app.validate_actions({"actions": []}, self.docs), ([], 0))
        with self.assertRaises(app.Problem):
            app.validate_actions([], self.docs)

    def test_actions_beyond_prompt_limit_are_rejected(self):
        actions, rejected = app.validate_actions({"actions": [self.response["actions"][0]] * 33}, self.docs)
        self.assertEqual((len(actions), rejected), (30, 3))

    def test_whitespace_is_not_useful_evidence(self):
        docs = app.documents_from([{"name": "Blank line", "text": "Context\n        "}])
        response = {"actions": [{"task": "Invented task", "evidence": [{"document_id": "D1", "line": 2, "quote": "        "}]}]}
        self.assertEqual(app.validate_actions(response, docs), ([], 1))

    def provider_response(self, content, usage=None):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": usage}).encode()
        return Response()

    def test_usage_exposes_only_nonnegative_integer_token_counts(self):
        usage = {"total_tokens": 12, "prompt_tokens": True, "completion_tokens": -1, "provider_secret": "do-not-forward"}
        with patch("app.urlopen", return_value=self.provider_response('{"actions":[]}', usage)):
            result, actual = app.request_model(self.docs, "test-key", app.DEFAULT_MODEL, app.DEFAULT_BASE)
        self.assertEqual(result, {"actions": []})
        self.assertEqual(actual, {"total_tokens": 12})

    def test_oversized_provider_body_is_rejected_even_if_valid_json(self):
        body = self.provider_response('{"actions":[]}')
        with patch.object(body, "read", return_value=b'{}' + b' ' * app.MAX_MODEL_BYTES), patch("app.urlopen", return_value=body):
            with self.assertRaisesRegex(app.Problem, "oversized"):
                app.request_model(self.docs, "test-key", app.DEFAULT_MODEL, app.DEFAULT_BASE)

    def test_invalid_endpoint_or_key_makes_no_request(self):
        for base, key in [("https://api.nebius.com:invalid/v1", "test"), ("https://api.nebius.com:8443/v1", "test"), (app.DEFAULT_BASE, " "), (app.DEFAULT_BASE, "test\r\nheader")]:
            with self.subTest(base=base), patch("app.urlopen") as transport, self.assertRaises(app.Problem):
                app.request_model(self.docs, key, app.DEFAULT_MODEL, base)
            transport.assert_not_called()

    def test_provider_redirects_are_not_followed(self):
        seen = []
        class RedirectHandler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                seen.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/would-receive-authorization")
                self.send_header("Content-Length", "0")
                self.end_headers()
            def do_GET(self):
                seen.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = Request(f"http://127.0.0.1:{server.server_port}/start", b'{}', {"Authorization": "Bearer test-only"})
            with self.assertRaises(HTTPError) as error:
                app.urlopen(req, timeout=5)
            self.assertEqual(error.exception.code, 302)
            error.exception.close()
            self.assertEqual(seen, ["/start"])
        finally:
            server.shutdown(); server.server_close(); thread.join()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1",0),app.make_handler(api_key=""))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"
        self.csrf=json.load(urlopen(self.base+'/api/status'))['csrf']

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def test_example_is_explicit_and_static_assets_exist(self):
        example=json.load(urlopen(self.base+'/api/example'))
        self.assertEqual(example['mode'],'example')
        self.assertIn('No model called',example['model'])
        for path in ['/','/app.js','/style.css']:
            with urlopen(self.base+path) as response:
                self.assertEqual(response.status,200)

    def test_missing_key_does_not_silently_fall_back(self):
        request=Request(self.base+'/api/analyze',json.dumps({'documents':app.EXAMPLE_DOCS}).encode(),{'Content-Type':'application/json','X-CSRF-Token':self.csrf})
        with self.assertRaises(HTTPError) as error: urlopen(request)
        self.assertEqual(error.exception.code,503)
        error.exception.close()

    def test_csrf_and_file_exposure_are_blocked(self):
        request=Request(self.base+'/api/analyze',b'{}',{'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error: urlopen(request)
        self.assertEqual(error.exception.code,403)
        error.exception.close()
        with self.assertRaises(HTTPError) as error: urlopen(self.base+'/app.py')
        self.assertEqual(error.exception.code,404)
        error.exception.close()


if __name__=='__main__': unittest.main()

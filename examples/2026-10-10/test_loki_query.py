"""HTTP 대역 검사. 실제 Loki·모델에는 연결하지 않는다."""
import copy
import io
import json
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import loki_query


FIXTURE = json.loads((Path(__file__).parent / "fixtures/loki-request-success.json").read_text(encoding="utf-8"))
REQUEST_ID = "agent-loki-20261010T034854Z-7943"
WINDOW = {"start": "2026-10-10T03:48:00Z", "end": "2026-10-10T03:50:00Z"}


class LokiQueryTests(unittest.TestCase):
    def run_with_payload(self, payload, **kwargs):
        raw = json.dumps(payload).encode("utf-8")
        with patch("loki_query.build_opener") as factory:
            factory.return_value.open.return_value = io.BytesIO(raw)
            result = loki_query.query_logs("order-api", **WINDOW, **kwargs)
            factory.return_value.open.assert_called_once()
            return result, factory.return_value.open.call_args

    def assert_query_failure(self, result, code):
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], code)
        self.assertIsNone(result["data"])
        self.assertIsNone(result["returned_count"])
        self.assertIsNone(result["limit_reached"])

    def test_captured_request_preserves_evidence_and_builds_get(self):
        result, call = self.run_with_payload(FIXTURE, request_id=REQUEST_ID)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["returned_count"], 1)  # stats.totalLinesProcessed는 2지만 반환은 1건이다.
        self.assertEqual(FIXTURE["data"]["stats"]["summary"]["totalLinesProcessed"], 2)
        self.assertIsNone(result["error"])
        self.assertFalse(result["limit_reached"])
        row = result["data"][0]
        self.assertEqual(row["timestamp_ns"], "1791604135340155505")
        self.assertEqual(row["fields"]["request_id"], REQUEST_ID)
        self.assertEqual(row["fields"]["status_code"], 201)
        self.assertEqual(row["fields"]["trace_id"], "cb1846dfcad3087952612215f37f1e44")
        self.assertEqual(row["message"], FIXTURE["data"]["result"][0]["values"][0][1])
        self.assertNotIn("count", row)
        request = call.args[0]
        self.assertEqual(request.get_method(), "GET")
        url = urlsplit(request.full_url)
        self.assertEqual(url.netloc, "127.0.0.1:3100")
        self.assertEqual(url.path, "/loki/api/v1/query_range")
        params = parse_qs(url.query)
        self.assertEqual(params["query"], ['{service_name="order-api"} |= "' + REQUEST_ID + '"'])
        self.assertEqual(params["start"], [WINDOW["start"]])
        self.assertEqual(params["end"], [WINDOW["end"]])
        self.assertEqual(params["limit"], ["20"])
        self.assertEqual(params["direction"], ["backward"])
        self.assertEqual(call.kwargs["timeout"], 10)

    def test_empty_success_with_error_filter_is_not_failure(self):
        payload = {"status": "success", "data": {"resultType": "streams", "result": []}}
        result, call = self.run_with_payload(payload, request_id=REQUEST_ID, errors_only=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], [])
        self.assertEqual(result["returned_count"], 0)
        self.assertIsNone(result["error"])
        query = parse_qs(urlsplit(call.args[0].full_url).query)["query"][0]
        self.assertIn('| json | __error__="" | level="error"', query)
        # 대역은 LogQL을 실행하지 않는다. 필터의 실제 결과는 PC에서 별도 확인한다.

    def test_http_and_transport_failures_do_not_become_zero_logs(self):
        cases = [
            (HTTPError(loki_query.ENDPOINT, 503, "Unavailable", {}, io.BytesIO(b"not ready")), "QUERY_HTTP_ERROR"),
            (TimeoutError("read timed out"), "QUERY_TIMEOUT"),
            (URLError(TimeoutError("connect timed out")), "QUERY_TIMEOUT"),
            (URLError(ConnectionRefusedError("refused")), "QUERY_CONNECTION_ERROR"),
            (ConnectionResetError("reset"), "QUERY_CONNECTION_ERROR"),
            (IncompleteRead(b"partial", 20), "QUERY_CONNECTION_ERROR"),
        ]
        for error, code in cases:
            with self.subTest(error=type(error).__name__), patch("loki_query.build_opener") as factory:
                factory.return_value.open.side_effect = error
                result = loki_query.query_logs("order-api", **WINDOW)
                self.assert_query_failure(result, code)
                factory.return_value.open.assert_called_once()  # 이번 함수에는 재시도가 없다.
                if isinstance(error, HTTPError):
                    self.assertEqual(result["error"]["http_status"], 503)

    def test_bad_response_is_not_empty_success(self):
        wrong_service = copy.deepcopy(FIXTURE)
        wrong_service["data"]["result"][0]["stream"]["service_name"] = "payment"
        cases = [b"not JSON", b"\xff", json.dumps(wrong_service).encode(),
                 b'{"status":"success","data":{"resultType":"matrix","result":[]}}',
                 b'{"status":"success","data":{"resultType":"streams","result":null}}',
                 b"x" * (loki_query.MAX_RESPONSE_BYTES + 1)]
        for raw in cases:
            with self.subTest(size=len(raw)), patch("loki_query.build_opener") as factory:
                factory.return_value.open.return_value = io.BytesIO(raw)
                result = loki_query.query_logs("order-api", **WINDOW)
                self.assert_query_failure(result, "QUERY_RESPONSE_ERROR")

    def test_limit_reached_is_separate_from_occurrence_count(self):
        result, _ = self.run_with_payload(FIXTURE, limit=1)
        self.assertTrue(result["limit_reached"])
        self.assertEqual(result["returned_count"], 1)
        self.assertNotIn("count", result["data"][0])
        # 실제 데이터가 한 줄뿐이어도 상한에 닿는다. 초과 데이터 존재를 단정하지 않는다.

    def test_plain_text_and_cross_stream_order_are_preserved(self):
        payload = copy.deepcopy(FIXTURE)
        payload["data"]["result"].append({"stream": {"service_name": "order-api", "job": "another"},
                                         "values": [["1791604135340155506", "plain text log"]]})
        result, _ = self.run_with_payload(payload)
        self.assertEqual(result["returned_count"], 2)
        self.assertEqual(result["data"][0]["message"], "plain text log")
        self.assertIsNone(result["data"][0]["fields"])
        self.assertEqual(result["data"][1]["fields"]["request_id"], REQUEST_ID)

    def test_invalid_scope_is_rejected_before_http(self):
        cases = [
            {"start": WINDOW["start"]},
            {"start": "2026-10-10T03:48:00", "end": WINDOW["end"]},
            {"start": WINDOW["end"], "end": WINDOW["start"]},
            {"start": WINDOW["start"], "end": "2026-10-10T05:48:00Z"},
            {**WINDOW, "minutes": 10}, {"minutes": 0}, {"limit": 1001},
            {"request_id": '" | json'},
        ]
        with patch("loki_query.build_opener") as factory:
            for kwargs in cases:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    loki_query.query_logs("order-api", **kwargs)
            with self.assertRaises(ValueError):
                loki_query.query_logs("other-service")
            factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

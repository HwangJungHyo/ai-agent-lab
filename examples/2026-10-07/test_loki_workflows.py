"""실제 LangGraph·Ollama SDK와 HTTP 대역으로 새 Loki 연결 경계를 검사한다."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import httpx
import local_workflows as app


CLIENT = app.load_loki_client()
CAPTURED = json.loads((Path(__file__).resolve().parents[1] / "2026-10-10/fixtures/loki-request-success.json").read_text(encoding="utf-8"))
REQUEST_ID = "agent-loki-20261010T034854Z-7943"


class LokiWorkflowTests(unittest.TestCase):
    def run_workflow(self, *, payload=CAPTURED, outcomes=None, requested_service="order-api", errors_only=False):
        model_requests, loki_requests = [], []

        def model_http(request):
            body = json.loads(request.content)
            model_requests.append(body)
            message = ({"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "get_logs", "arguments": {"service": requested_service}}}]}
                if len(model_requests) == 1 else
                {"role": "assistant", "content": "판단 한계: 조회 범위 밖의 상태는 알 수 없습니다.\n다음 확인: 필요한 경우 범위를 조정할 수 있습니다."})
            response = {"model": "qwen3.5:9b", "created_at": "2026-10-10T00:00:00Z", "message": message,
                        "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5}
            return httpx.Response(200, content=json.dumps(response) + "\n")

        real_model = app.ChatOllama

        def model_factory(**kwargs):
            kwargs["client_kwargs"] = {**kwargs["client_kwargs"], "transport": httpx.MockTransport(model_http)}
            return real_model(**kwargs)

        def loki_http(request, timeout):
            loki_requests.append(parse_qs(urlsplit(request.full_url).query))
            outcome = outcomes[len(loki_requests) - 1] if outcomes is not None else payload
            if isinstance(outcome, Exception):
                raise outcome
            return io.BytesIO(json.dumps(outcome).encode())

        # 상대 시간 범위가 재시도에서도 고정되는지 확인한다. 대역은 실제 기간 필터를 실행하지 않는다.
        argv = ["local_workflows.py", "--source", "loki", "--engine", "graph", "--minutes", "10",
                "--request-id", REQUEST_ID, "--limit", "20"]
        if errors_only:
            argv.append("--errors-only")
        output = io.StringIO()
        failure, code = None, None
        with patch.object(app, "ChatOllama", model_factory), patch.object(CLIENT, "build_opener") as opener, \
                patch.object(sys, "argv", argv), redirect_stdout(output):
            opener.return_value.open.side_effect = loki_http
            try:
                code = app.main()
            except Exception as exc:
                failure = exc
        return code or 0, output.getvalue(), model_requests, loki_requests, failure

    def test_graph_preserves_captured_log_in_facts_and_model_input(self):
        code, output, models, logs, error = self.run_workflow()
        self.assertIsNone(error)
        self.assertEqual((code, len(models), len(logs)), (0, 2, 1))
        facts = output.split("[조회 사실 · 코드 출력]", 1)[1].split("[모델 설명 · 참고]", 1)[0]
        self.assertIn("데이터 출처: loki", facts)
        self.assertIn("반환된 로그 줄 수: 1줄", facts)
        self.assertIn("수준: info", facts)
        self.assertIn(CAPTURED["data"]["result"][0]["values"][0][1], facts)
        self.assertNotIn("반환된 오류 항목 수:", facts)
        self.assertNotIn("발생 횟수(count):", facts)
        self.assertTrue(models[0].get("tools"))
        self.assertFalse(models[1].get("tools"))
        result = json.loads(models[1]["messages"][1]["content"].split("\n", 1)[1])
        self.assertEqual(result["source"], "loki")
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["data"][0]["fields"]["request_id"], REQUEST_ID)
        self.assertEqual(result["data"][0]["message"], CAPTURED["data"]["result"][0]["values"][0][1])

    def test_empty_query_still_reaches_explanation_with_filter_scope(self):
        empty = {"status": "success", "data": {"resultType": "streams", "result": []}}
        code, output, models, logs, error = self.run_workflow(payload=empty, errors_only=True)
        self.assertIsNone(error)
        self.assertEqual((code, len(models), len(logs)), (0, 2, 1))
        self.assertIn("반환된 로그 줄 수: 0줄", output)
        self.assertIn("이번 시간 범위와 오류 필터에서 반환된 로그가 없습니다.", output)
        self.assertIn('[설명 상태] ok', output)
        self.assertIn('level="error"', logs[0]["query"][0])

    def test_timeout_retry_reuses_same_window_and_model_request(self):
        code, output, models, logs, error = self.run_workflow(outcomes=[TimeoutError(), CAPTURED])
        self.assertIsNone(error)
        self.assertEqual((code, len(models), len(logs)), (0, 2, 2))
        self.assertEqual(logs[0], logs[1])
        self.assertIn("[총 조회 시도] 2회", output)
        self.assertIn("반환된 로그 줄 수: 1줄", output)

    def test_http_503_ends_without_explanation_or_zero_count(self):
        http_error = HTTPError(CLIENT.ENDPOINT, 503, "Unavailable", {}, io.BytesIO(b"not ready"))
        code, output, models, logs, error = self.run_workflow(outcomes=[http_error])
        self.assertIsNone(error)
        self.assertEqual((code, len(models), len(logs)), (2, 1, 1))
        self.assertIn("QUERY_HTTP_ERROR", output)
        self.assertIn("조회 상태: 실패", output)
        self.assertIn("[설명 상태] skipped", output)
        self.assertNotIn("반환된 로그 줄 수:", output)

    def test_wrong_model_target_never_queries_loki(self):
        _, _, models, logs, error = self.run_workflow(requested_service="payment")
        self.assertIsInstance(error, ValueError)
        self.assertIn("MODEL_CONTRACT_ERROR", str(error))
        self.assertEqual((len(models), len(logs)), (1, 0))


if __name__ == "__main__":
    unittest.main()

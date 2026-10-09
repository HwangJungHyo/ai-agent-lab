"""실제 SDK + 가짜 HTTP로 사실 보존 경계를 검증한다. Ollama 서버에 연결하지 않는다."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from unittest.mock import patch

import httpx

import local_workflows as app


class ReportTests(unittest.TestCase):
    def run_workflow(self, engine="graph", scenario="flaky", style="separated", reply="ok", tool_result=None):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                message = {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "get_recent_errors", "arguments": {"service": "order-api"}}}
                ]}
            else:
                if reply == "503":
                    return httpx.Response(503, json={"error": "simulated failure"})
                if reply == "timeout":
                    raise httpx.ReadTimeout("simulated timeout", request=request)
                message = {"role": "assistant", "content": "판단 한계: 실제 상태는 알 수 없습니다.\n다음 확인: 실제 로그를 확인해 보세요."}
                if reply == "wrong":
                    message["content"] = "발생 횟수는 999회이며 서비스는 정상입니다."
                if reply == "empty":
                    message["content"] = "  "
                if reply == "tool":
                    message["tool_calls"] = [{"function": {"name": "get_recent_errors", "arguments": {"service": "payment-api"}}}]
            response = {
                "model": "qwen3.5:9b", "created_at": "2026-10-09T00:00:00Z",
                "message": message, "done": True,
                "done_reason": "length" if len(requests) > 1 and reply == "length" else "stop",
                "prompt_eval_count": 10, "eval_count": 5,
            }
            return httpx.Response(200, content=json.dumps(response) + "\n")

        real_model = app.ChatOllama

        def model_factory(**kwargs):
            kwargs["client_kwargs"] = {**kwargs["client_kwargs"], "transport": httpx.MockTransport(handler)}
            return real_model(**kwargs)

        real_tool = app.mock_get_recent_errors

        def fake_tool(**kwargs):
            return deepcopy(tool_result) if tool_result is not None else real_tool(**kwargs)

        argv = ["local_workflows.py", "--engine", engine, "--scenario", scenario, "--summary-style", style]
        output = io.StringIO()
        with patch.object(app, "ChatOllama", model_factory), patch.object(app, "mock_get_recent_errors", fake_tool), \
                patch.object(sys, "argv", argv), redirect_stdout(output):
            code = app.main()
        return code or 0, output.getvalue(), requests

    def test_facts_use_each_input_count_without_inventing_missing_count(self):
        result = app.mock_get_recent_errors(service="order-api", scenario="normal")
        result["data"] = [
            {"message": "a", "count": 7}, {"message": "b", "count": 0}, {"message": "c"},
        ]
        rendered = app.render_facts(result, 2)
        for expected in ("반환된 오류 항목 수: 3개", "발생 횟수(count): 7회", "발생 횟수(count): 0회", "발생 횟수(count): 미제공"):
            self.assertIn(expected, rendered)

    def test_malformed_tool_results_are_rejected(self):
        normal = app.mock_get_recent_errors(service="order-api", scenario="normal")
        for value in ("3", True, -1, None):
            with self.subTest(count=value):
                bad = deepcopy(normal)
                bad["data"][0]["count"] = value
                with self.assertRaises(app.ToolResultError):
                    app.render_facts(bad, 1)
        bad = deepcopy(normal)
        bad["data"] = None
        with self.assertRaises(app.ToolResultError):
            app.render_facts(bad, 1)
        with self.assertRaises(app.ToolResultError):
            app.validate_tool_result(normal, expected_service="payment-api")

    def test_flaky_completes_in_both_engines_and_separates_model_input(self):
        for engine in ("chain", "graph"):
            with self.subTest(engine=engine):
                code, output, requests = self.run_workflow(engine=engine)
                self.assertEqual(code, 0)
                self.assertEqual(len(requests), 2)
                self.assertIn("[총 조회 시도] 2회", output)
                self.assertIn("발생 횟수(count): 3회", output)
                self.assertIn("[설명 상태] ok", output)
                self.assertTrue(requests[0].get("tools"))
                self.assertFalse(requests[1].get("tools"))
                messages = requests[1]["messages"]
                self.assertEqual([m["role"] for m in messages], ["system", "user"])
                result = json.loads(messages[1]["content"].split("\n", 1)[1])
                self.assertEqual(result["data"][0]["count"], 3)

    def test_empty_and_timeout_remain_distinct(self):
        code, output, requests = self.run_workflow(scenario="empty")
        self.assertEqual((code, len(requests)), (0, 2))
        self.assertIn("이번 조회에서 반환된 오류 로그가 없습니다.", output)
        code, output, requests = self.run_workflow(scenario="timeout")
        self.assertEqual((code, len(requests)), (0, 1))
        self.assertIn("조회 상태: 실패", output)
        self.assertIn("QUERY_TIMEOUT", output)
        self.assertNotIn("반환된 오류 항목 수:", output)
        self.assertIn("[설명 상태] skipped", output)

    def test_explanation_failure_preserves_facts_and_returns_nonzero(self):
        for reply in ("503", "timeout", "empty", "length", "tool"):
            with self.subTest(reply=reply):
                code, output, requests = self.run_workflow(reply=reply)
                self.assertEqual((code, len(requests)), (2, 2))
                self.assertIn("[조회 사실 · 코드 출력]", output)
                self.assertIn("발생 횟수(count): 3회", output)
                self.assertIn("[설명 상태] failed", output)

    def test_wrong_explanation_cannot_rewrite_facts_but_is_not_auto_detected(self):
        code, output, _ = self.run_workflow(reply="wrong")
        report = output.split("[조회 사실 · 코드 출력]", 1)[1]
        facts, explanation = report.split("[모델 설명 · 참고]", 1)
        self.assertEqual(code, 0)  # 텍스트 생성 성공이며 내용 정확성 통과를 뜻하지 않는다.
        self.assertIn("발생 횟수(count): 3회", facts)
        self.assertNotIn("999", facts)
        self.assertIn("999", explanation)

    def test_invalid_tool_payload_never_reaches_explanation(self):
        bad = app.mock_get_recent_errors(service="order-api", scenario="normal")
        bad["data"][0]["count"] = "3"
        with self.assertRaises(app.ToolResultError):
            self.run_workflow(scenario="normal", tool_result=bad)

    def test_legacy_modes_still_produce_model_summary(self):
        for style in ("original", "explicit"):
            with self.subTest(style=style):
                code, output, requests = self.run_workflow(style=style)
                self.assertEqual((code, len(requests)), (0, 2))
                self.assertIn("[최종 답변]", output)
                self.assertNotIn("[조회 사실 · 코드 출력]", output)

    def test_check_report_does_not_construct_model(self):
        with patch.object(sys, "argv", ["local_workflows.py", "--check-report"]), \
                patch.object(app, "ChatOllama", side_effect=AssertionError("model must not be constructed")), \
                redirect_stdout(io.StringIO()) as output:
            app.main()
        self.assertIn("6개 검증 통과", output.getvalue())


if __name__ == "__main__":
    unittest.main()

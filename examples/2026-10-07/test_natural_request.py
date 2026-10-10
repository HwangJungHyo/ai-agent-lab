"""새 자연어 해석 경계만 확인. 실제 모델의 의미 해석 품질은 별도 PC 확인."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import httpx
import local_workflows as app
from natural_request import normalize_proposal, validate_proposal

CLIENT = app.load_loki_client()


class NaturalRequestTests(unittest.TestCase):
    def run_request(self, proposal, *, run=False, outcomes=None, engine='graph', question='order-api 최근 10분 오류 로그를 확인해줘', tool_name='propose_log_query'):
        models, queries = [], []

        def model_http(request):
            body = json.loads(request.content)
            models.append(body)
            message = ({'role': 'assistant', 'content': '', 'tool_calls': [{'function': {
                'name': tool_name, 'arguments': proposal}}]} if len(models) == 1 else
                {'role': 'assistant', 'content': '판단 한계: 조회 범위 밖의 상태는 알 수 없습니다.'})
            return httpx.Response(200, content=json.dumps({'model': 'qwen3.5:9b', 'message': message,
                'done': True, 'done_reason': 'stop'}) + '\n')

        real_model = app.ChatOllama

        def model_factory(**kwargs):
            kwargs['client_kwargs']['transport'] = httpx.MockTransport(model_http)
            return real_model(**kwargs)

        def query(**kwargs):
            queries.append(kwargs)
            prepared = CLIENT.prepare_query(**kwargs)
            if outcomes and outcomes[len(queries) - 1] == 'timeout':
                return dict(source='loki', service=kwargs['service'], status='error', data=None,
                            error={'code': 'QUERY_TIMEOUT', 'message': '조회 시간 초과'}, query=prepared,
                            returned_count=None, limit_reached=None)
            return dict(source='loki', service=kwargs['service'], status='ok', data=[], error=None,
                        query=prepared, returned_count=0, limit_reached=False)

        argv = ['local_workflows.py', '--source', 'loki', '--engine', engine,
                '--question', question]
        if run:
            argv.append('--run-query')
        output = io.StringIO()
        with patch.object(sys, 'argv', argv), patch.object(app, 'ChatOllama', model_factory), \
                patch.object(CLIENT, 'query_logs', side_effect=query), redirect_stdout(output):
            code = app.main()
        return code, output.getvalue(), models, queries

    def test_preview_never_queries_loki(self):
        code, output, models, queries = self.run_request(self.clear())
        self.assertEqual((code, len(models), len(queries)), (0, 1, 0))
        self.assertIn('[검증된 조회 조건]', output)
        self.assertIn('level=error', output)
        self.assertEqual(models[0]['tools'][0]['function']['name'], 'propose_log_query')

    def test_ambiguous_request_asks_all_missing_fields_without_query(self):
        code, output, models, queries = self.run_request(dict(service=None, minutes=None, errors_only=None, unresolved=[]), run=True)
        self.assertEqual((code, len(models), len(queries)), (2, 1, 0))
        for text in ('대상이', '언제 발생', '어떤 증상'):
            self.assertIn(text, output)

    def test_out_of_policy_or_unresolved_never_queries(self):
        for overrides in ({'minutes': 180}, {'service': 'database'}, {'minutes': True},
                          {'unresolved': ['요청 ID 필터는 자연어 입구에서 미지원']}):
            with self.subTest(overrides=overrides):
                p = self.clear() | overrides
                code, _, models, queries = self.run_request(p, run=True)
                self.assertEqual((code, len(models), len(queries)), (2, 1, 0))

    def test_valid_request_executes_same_contract_for_chain_and_graph(self):
        for engine in ('chain', 'graph'):
            with self.subTest(engine=engine):
                code, output, models, queries = self.run_request(self.clear(), run=True, engine=engine)
                self.assertEqual((code, len(models), len(queries)), (0, 2, 1))
                self.assertEqual(queries[0]['service'], 'order-api')
                self.assertTrue(queries[0]['errors_only'])
                self.assertIn('반환된 로그 줄 수: 0줄', output)
                self.assertIn('start_inclusive', models[1]['messages'][1]['content'])

    def test_retry_keeps_interpreted_scope_without_reinterpreting(self):
        code, _, models, queries = self.run_request(self.clear(), run=True, outcomes=['timeout', 'ok'])
        self.assertEqual((code, len(models), len(queries)), (0, 2, 2))
        self.assertEqual(queries[0], queries[1])

    def test_malformed_proposal_fails_before_query(self):
        for proposal in ({'service': 'order-api'}, self.clear() | {'errors_only': 'yes'}):
            with self.subTest(proposal=proposal):
                code, output, models, queries = self.run_request(proposal, run=True)
                self.assertEqual((code, len(models), len(queries)), (2, 1, 0))
                self.assertIn('[모델 제안]', output)
                self.assertIn('[조건 형식 오류 · 조회하지 않음]', output)
        with self.assertRaises(ValueError):
            validate_proposal(self.clear() | {'errors_only': 'true'})

    def test_inferred_payment_from_korean_symptom_is_not_executed(self):
        # 완전한 조건을 모델이 만들어도 원문에 서비스가 없으면 실행하지 않는다.
        proposal = self.clear() | {'service': 'payment'}
        code, output, models, queries = self.run_request(proposal, run=True, question='아까 결제가 이상했어')
        self.assertEqual((code, len(models), len(queries)), (2, 1, 0))
        self.assertIn('조회 대상을 명시', output)

    def test_wrong_tool_is_reported_without_traceback_or_query(self):
        code, output, models, queries = self.run_request(self.clear(), run=True, tool_name='get_logs')
        self.assertEqual((code, len(models), len(queries)), (2, 1, 0))
        self.assertIn('[조건 형식 오류 · 조회하지 않음]', output)

    def test_observed_string_values_are_normalized_and_passed_to_query(self):
        proposal = self.clear() | {'minutes': '10', 'errors_only': 'True'}
        code, output, models, queries = self.run_request(proposal, run=True)
        self.assertEqual((code, len(models), len(queries)), (0, 2, 1))
        self.assertIn('[표현 정규화]', output)
        self.assertIn('"minutes": "10"', output)  # 원래 제안 표시를 유지한다
        self.assertIs(queries[0]['errors_only'], True)
        self.assertEqual(proposal['minutes'], '10')
        for flag in ('false', 'False'):
            normalized, _ = normalize_proposal(self.clear() | {'errors_only': flag})
            self.assertIs(normalized['errors_only'], False)

    def test_normalization_does_not_bypass_policy_or_infer_values(self):
        for overrides in ({'minutes': '180'}, {'minutes': '10.0'}, {'minutes': 'ten'},
                          {'errors_only': 'yes'}, {'errors_only': 1}, {'errors_only': 'null'}):
            with self.subTest(overrides=overrides):
                code, _, models, queries = self.run_request(self.clear() | overrides, run=True)
                self.assertEqual((code, len(models), len(queries)), (2, 1, 0))

    @staticmethod
    def clear():
        return dict(service='order-api', minutes=10, errors_only=True, unresolved=[])


if __name__ == '__main__':
    unittest.main()

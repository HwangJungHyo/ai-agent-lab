"""자연어는 모델이 해석하고 실행 조건은 코드가 검증하는 읽기 전용 입구."""
import json
import re
from typing import Optional, TypedDict

from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

INSTRUCTION = """사용자의 로그 조회 요청을 propose_log_query 도구로 구조화하라. 도구는 조회를 실행하지 않는다.
허용 서비스는 order-api와 payment다. 정확한 서비스 이름이 명시되지 않으면 service=null이다.
한국어 결제/주문을 payment/order-api로 추측해서 매핑하지 마라. 복수 대상은 unresolved에 적어라.
errors_only는 JSON boolean true/false 또는 null만 사용하라. 문자열 "true"/"false"나 숫자를 쓰지 마라.
최근 N분만 지원하며 시간을 명시하지 않거나 '아까', '오늘', 고정 시각이면 minutes=null이다.
오류 로그 요청이면 errors_only=true, 일반/전체 로그 요청이면 false, '이상하다' 같은 불명확한 증상이면 null이다.
최근 N시간은 N*60분으로 표현하되 범위를 몰래 줄이지 마라. 없는 대상이나 값을 추측하지 마라.
불명확하거나 지원하지 않는 조건(요청 ID, 복수 대상, 복구/변경 작업 등)은 unresolved에 모두 적어라.
명확한 조건에서도 사용자가 요구한 추가 제한을 생략하지 마라. 도구 요청은 정확히 하나만 생성하라."""


@tool
def propose_log_query(service: Optional[str], minutes: Optional[int],
                      errors_only: Optional[bool], unresolved: list[str]) -> str:
    """실행 전 검증할 조회 조건 제안. 미제공/모호한 값은 null, 미해결 조건은 unresolved에 기록."""
    return "조건 제안은 실행 도구가 아닙니다."


class RequestState(TypedDict, total=False):
    proposal: dict
    interpretation_error: str
    questions: list[str]
    prepared: dict
    query_options: dict
    attempts: int
    result: dict
    facts: str
    explanation: str
    explanation_status: str


def normalize_proposal(proposal):
    """의미를 추측하지 않고 명시한 문자열 표현만 변환한다. 원래 제안은 보존한다."""
    if not isinstance(proposal, dict):
        return proposal, []
    normalized = dict(proposal)
    changes = []
    minutes = normalized.get('minutes')
    if isinstance(minutes, str) and re.fullmatch(r'[0-9]{1,6}', minutes):
        normalized['minutes'] = int(minutes)
        changes.append(f"minutes: {minutes!r} → 정수 {normalized['minutes']}")
    flag = normalized.get('errors_only')
    if isinstance(flag, str) and flag in ('true', 'True', 'false', 'False'):
        normalized['errors_only'] = flag in ('true', 'True')
        changes.append(f"errors_only: {flag!r} → {normalized['errors_only']}")
    return normalized, changes


def validate_proposal(proposal, question=None):
    """모델의 의미 해석 정확도와 별개로 코드의 필수 조건·자료형·허용 범위를 검사한다."""
    if not isinstance(proposal, dict) or set(proposal) != {"service", "minutes", "errors_only", "unresolved"}:
        raise ValueError("조건 제안의 필드가 약속한 형식과 다릅니다.")
    if not isinstance(proposal['unresolved'], list) or not all(isinstance(x, str) and x.strip() for x in proposal['unresolved']):
        raise ValueError("unresolved는 미해결 조건의 문자열 목록이어야 합니다.")
    questions = []
    service, minutes, errors_only = (proposal[k] for k in ('service', 'minutes', 'errors_only'))
    if service is None:
        questions.append("대상이 order-api인가요, payment인가요? 주문 화면의 증상과 결제 서비스 문제는 구분해야 합니다.")
    elif service not in ('order-api', 'payment'):
        questions.append("허용된 대상은 order-api와 payment입니다. 어느 서비스를 조회할까요?")
    if question is not None and service in ('order-api', 'payment'):
        # 별칭 매핑 정책이 없으므로 한국어 증상만으로 서비스를 결정하지 않는다.
        named = [name for name in ('order-api', 'payment') if re.search(
            rf'(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])', question)]
        if named != [service]:
            questions.append("조회 대상을 명시해 주세요: order-api 또는 payment. 증상 표현만으로 서비스를 선택하지 않습니다.")
    if minutes is None:
        questions.append("언제 발생했나요? 현재는 최근 1~60분을 지원하므로 최근 몇 분을 조회할지 알려주세요.")
    elif type(minutes) is not int or not 1 <= minutes <= 60:
        questions.append("조회 범위는 정수 1~60분이어야 합니다. 범위를 줄일지, 더 긴 조회 기능이 필요한지 정해주세요.")
    if errors_only is None:
        questions.append("결제 실패, 지연, 금액 이상 중 어떤 증상인가요? level=error 로그만 볼지 일반 로그도 볼지 알려주세요.")
    elif type(errors_only) is not bool:
        raise ValueError("errors_only는 참/거짓 또는 null이어야 합니다.")
    if proposal['unresolved']:
        questions.append("추가로 명확히 하거나 지원 범위를 정해야 합니다: " + '; '.join(proposal['unresolved']))
    return questions


def run_natural_workflow(args, app):
    client = app.load_loki_client()
    # 사용자 설정은 모델이 바꿀 수 없다. 서비스·시간·필터만 제안하게 한다.
    limit = 20 if args.limit is None else args.limit
    timeout = 10 if args.loki_timeout is None else args.loki_timeout
    client.prepare_query('order-api', minutes=1, limit=limit, timeout=timeout)
    if not args.question.strip() or len(args.question) > 2000:
        raise ValueError("질문은 비어 있지 않은 2000자 이하 문자열이어야 합니다.")
    options = {'num_ctx': args.num_ctx, 'num_predict': args.max_output, 'temperature': 0.7,
               'top_p': 0.8, 'top_k': 20, 'presence_penalty': 1.5, 'repeat_penalty': 1.0}
    if not args.model.startswith('qwen'):
        options = {'num_ctx': args.num_ctx, 'num_predict': args.max_output, 'temperature': 1.0}
    model = app.ChatOllama(model=args.model, base_url=app.BASE_URL, reasoning=False, keep_alive='10m',
                           client_kwargs={'timeout': float(args.timeout), 'trust_env': False})
    request_model = model.bind_tools([propose_log_query], options=options)
    answer_model = model.bind(options=options)
    print('[입구] 자연어 요청 /', '검증 후 실제 조회' if args.run_query else '조건 미리보기: Loki 조회 없음')
    print('[정책] 최근 1~60분, 대상 order-api/payment, 오류 필터=JSON level=error, 반환 상한=', limit)

    def extract(state):
        response = app.invoke_model(request_model, [SystemMessage(content=INSTRUCTION),
                                                    HumanMessage(content=args.question)], 'interpret')
        if len(response.tool_calls) != 1 or response.tool_calls[0]['name'] != propose_log_query.name:
            return {'proposal': {}, 'interpretation_error': '조회 조건 제안 도구 하나가 필요합니다.'}
        return {'proposal': response.tool_calls[0]['args']}

    def validate(state):
        proposal = state['proposal']
        print('[모델 제안]', json.dumps(proposal, ensure_ascii=False))
        try:
            if state.get('interpretation_error'):
                raise ValueError(state['interpretation_error'])
            proposal, changes = normalize_proposal(proposal)
            for change in changes:
                print('[표현 정규화]', change)
            questions = validate_proposal(proposal, question=args.question)
        except ValueError as exc:
            print('[조건 형식 오류 · 조회하지 않음]', str(exc))
            print('모델 응답이 입력 계약을 지키지 않았습니다. 위 모델 제안의 값과 자료형을 확인하세요. 허용된 표현 외에는 자동 변환하거나 재호출하지 않습니다.')
            return {'questions': [str(exc)]}
        if questions:
            print('[추가 확인 · 조회하지 않음]')
            for question in questions:
                print('-', question)
            return {'questions': questions}
        prepared = client.prepare_query(proposal['service'], minutes=proposal['minutes'],
                                        errors_only=proposal['errors_only'], limit=limit, timeout=timeout)
        print('[검증된 조회 조건]', json.dumps(prepared, ensure_ascii=False))
        print('[실행]', '조회합니다.' if args.run_query else '미리보기만 완료했습니다. 실제 조회하려면 --run-query를 붙이세요.')
        return {'proposal': proposal, 'questions': [], 'prepared': prepared, 'query_options': {
            'start': prepared['start_inclusive'], 'end': prepared['end_exclusive'],
            'errors_only': proposal['errors_only'], 'limit': limit, 'timeout': timeout}}

    def gate(state):
        return 'execute' if not state['questions'] and args.run_query else 'stop'

    def execute(state):
        result = client.query_logs(service=state['proposal']['service'], **state['query_options'])
        app.validate_tool_result(result, expected_service=state['proposal']['service'])
        if result['source'] != 'loki':
            raise app.ToolResultError('설정한 Loki 출처와 결과가 다릅니다.')
        attempt = state['attempts'] + 1
        print(f"[execute] 시도 {attempt}/{app.MAX_ATTEMPTS}, status={result['status']}")
        return {'result': result, 'attempts': attempt}

    def after_query(state):
        result = state['result']
        return ('execute' if result['status'] == 'error' and result['error']['code'] == 'QUERY_TIMEOUT'
                and state['attempts'] < app.MAX_ATTEMPTS else 'report')

    def report(state):
        return app.make_separated_report(state['result'], state['attempts'], answer_model)

    initial = {'attempts': 0}
    if args.engine == 'graph':
        from langgraph.graph import StateGraph, START, END
        builder = StateGraph(RequestState)
        for name, fn in [('interpret', extract), ('validate', validate), ('execute', execute), ('report', report)]:
            builder.add_node(name, fn)
        builder.add_edge(START, 'interpret')
        builder.add_edge('interpret', 'validate')
        builder.add_conditional_edges('validate', gate, {'execute': 'execute', 'stop': END})
        builder.add_conditional_edges('execute', after_query, {'execute': 'execute', 'report': 'report'})
        builder.add_edge('report', END)
        state = builder.compile().invoke(initial)
    else:
        state = initial
        state.update(extract(state))
        state.update(validate(state))
        if gate(state) == 'execute':
            while True:
                state.update(execute(state))
                if after_query(state) != 'execute':
                    break
            state.update(report(state))
    if state.get('questions'):
        return 2
    if 'result' not in state:
        return 0
    print('[조회 사실 · 코드 출력]\n' + state['facts'])
    print('[모델 설명 · 참고]\n' + state['explanation'])
    print('[설명 상태]', state['explanation_status'], '(텍스트 생성 상태이며 내용 정확성은 별도 확인)')
    return 2 if state['result']['status'] == 'error' or state['explanation_status'] == 'failed' else 0

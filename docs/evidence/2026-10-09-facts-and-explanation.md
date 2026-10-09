# 필수 사실은 코드로 출력하고 모델은 설명을 맡으면 무엇이 달라지는가?

- 작성·갱신: 2026-10-09, Asia/Seoul.
- 상태: 사용자 PC에서 --check-report 6개 PASS 및 실제 Qwen + graph/separated의 flaky·empty·timeout 완료. 사실 출력·제어 흐름은 예상과 일치. 모델 설명의 의미·표현은 보완 필요.
- 코드: [local_workflows.py](../../examples/2026-10-07/local_workflows.py), [회귀 검증](../../examples/2026-10-07/test_local_workflows.py).
- 근거: 앞선 [사용자 PC 요약 비교](2026-10-09-local-summary.md), 별도 Linux 환경의 가짜 HTTP 응답 검증, 2026-10-09 사용자 Windows Git Bash 도움말·--check-report 및 23:46 KST 공유 실제 Qwen 출력.
- 작성 시점: 앞선 누락 원인은 회고이며, 이번 사실 보존·실패 처리 기준은 새 구현과 검증을 위해 정했다. 아래 실제 검증 결과는 실행 후 기록이다.

## 왜 바꾸는가

사용자 PC의 chain/original 답변은 도구 원문에 있는 오류 내용과 count=3을 누락했다. graph/explicit은 이를 포함했지만 표현상 문제와 중국어 혼입이 남았다. 필수 필드를 매번 표시해야 하는 보고서에서 필드의 포함 여부를 모델의 문장 생성에 맡기지 않는 것이 이번 목적이다.

코드가 표시하는 사실은 **도구가 반환한 내용**이다. 현실의 장애 상태나 원천 데이터의 정확성을 새롭게 확인했다는 뜻은 아니다.

## 그래서 왜 이 방식을 선택하는가

| 방식 | 적합한 조건 | 대가 / 이번 선택 |
|---|---|---|
| 프롬프트만 더 구체화 | 자유로운 서술이 중요하고 누락을 평가·보완할 수 있음 | 지시를 어길 수 있다. original/explicit 비교 모드로 유지 |
| 필수 필드 코드 출력 + 모델 설명 | 필수 내용·숫자를 빠짐없이 보여주면서 판단 한계·다음 확인을 설명하고 싶음 | 두 영역 관리와 입력 형식 검증 필요. 사용자 요청에 따라 이번에 구현 |
| 전체 코드 템플릿 | 현재 단일 도구의 정형 보고만 필요함 | 모델 설명 호출이 없어 가장 단순하다. 다양한 질문에 맞춘 설명은 제한됨 |

이번 가정은 필수 오류 내용·횟수 누락을 허용하지 않는다는 것이다. 한 종류의 정형 보고만 필요해지면 설명까지 코드 템플릿으로 처리할 수 있다. 모델 설명의 정확성까지 기계적으로 보장해야 한다면 별도 검증·검토 기준이 필요하다.

## 어떻게 역할을 나눴는가

새 실행 선택은 `--summary-style separated`다. 기존 기본값 explicit과 original/explicit 동작은 유지한다. separated에서는 보고 방식과 설명 입력이 함께 바뀌므로 앞선 프롬프트만의 비교 실험과 구분한다.

1. `validate_tool_result`: 반환값의 필수 필드·자료형·요청 대상 일치를 검사한다. status=ok인데 data=null인 결과를 빈 목록으로 처리하지 않는다.
2. `render_facts`: 모델 호출 없이 source, service, status, 총 시도, 반환 항목 수, 각 message·count를 문자열로 만든다.
3. `make_separated_report`: 확보한 사실 문자열을 보존한 채 별도 모델 입력으로 판단 한계·다음 확인을 요청한다. 설명 단계에는 호출 가능한 도구 정의를 제공하지 않는다.
4. 최종 출력은 `[조회 사실 · 코드 출력]`과 `[모델 설명 · 참고]`로 구분한다. 모델 답변을 facts 필드에 다시 대입하지 않는다.

요청 생성 모델과 도구 재시도 정책은 기존 흐름을 사용한다. 설명 입력은 별도의 system/user 메시지와 검사된 최종 도구 JSON이다. 원래의 '전체 결과를 설명하라'는 대화 지시가 섞이지 않도록 필요한 입력만 구성했다. 설명에는 판단 한계·다음 확인을 한국어로 한 문장씩 쓰도록 요청하지만, 이 지시가 언어·내용 정확성을 강제하는 검사는 아니다.

### 필드와 실패의 의미

| 입력 / 상황 | 코드의 처리 | 이유 |
|---|---|---|
| data의 항목 1개, count=3 | 항목 수 1개, 해당 오류 발생 3회 | 배열 길이와 항목의 발생 횟수는 다른 값 |
| count 누락 | 횟수 미제공 | 모르는 값을 0으로 만들지 않음 |
| count가 문자열·음수·bool·null | TOOL_RESULT_ERROR | 현재 계약은 count가 있으면 0 이상의 정수. 자동 변환으로 원천 오류를 숨기지 않음 |
| status=ok, data=[] | 이번 조회에서 반환된 오류 로그 없음 | 실제 발생·기록 여부나 서비스 정상 여부는 미확인 |
| status=error, data=null | 오류 code·message와 확인 불가 표시 | 조회 실패를 0건으로 바꾸지 않음 |
| 설명 HTTP 503·연결/읽기 오류·출력 잘림·빈 텍스트·추가 도구 요청 | 사실 유지, 설명 failed, 프로세스 종료 코드 2 | 조회 성공과 설명 실패를 구분 |
| 도구 조회 최종 실패 | 설명 호출 생략, skipped | 추가 모델 호출 없이 한계 전달 가능 |

모델 설명 실패를 감싸는 처리는 예상한 HTTP/연결/모델 응답 오류에 한정한다. 알 수 없는 프로그래밍 오류를 모두 삼키지 않는다. 요청 생성 모델이 실패하면 아직 도구를 실행하지 않았으므로 확보된 사실이 있는 것으로 출력하지 않는다.

`설명 상태 ok`는 텍스트 생성 완료이며 내용 정확성 통과가 아니다. `skipped`는 정해진 조회 실패 분기를 처리했다는 뜻이다. 오류 횟수를 여러 항목에 걸쳐 무조건 합산하지 않는다. 실제 로그의 중복 집계 여부를 모르는 상태에서 전체 발생 횟수를 만들 수 없기 때문이다.

## 사용자 PC 적용과 실행

사용자 PC의 수정 대상: `C:\Users\PC\Desktop\git-devops\ai-agent-lab\local_workflows.py`.

다운로드용 파일은 구분을 위해 `local_workflows_separated.py`라는 이름으로 제공한다. 내용은 저장소의 local_workflows.py 수정본과 같다. 기존 tools_mock.py는 유지한다. 현재 Ollama 연결이 동작하는 환경에서는 추가 패키지 설치 없이 진행한다.

기본 다운로드 폴더에 파일을 저장한 경우 Git Bash에서:

```bash
cd ~/Desktop/git-devops/ai-agent-lab || exit
if [ -f "$HOME/Downloads/local_workflows_separated.py" ]; then
  cp -p local_workflows.py "local_workflows.py.bak-$(date +%Y%m%d-%H%M%S)" &&
  cp "$HOME/Downloads/local_workflows_separated.py" local_workflows.py &&
  python local_workflows.py --help &&
  python local_workflows.py --check-report
else
  printf '%s\n' '다운로드 파일을 찾지 못했습니다. 파일의 저장 위치와 이름을 확인하세요.'
fi
```

다른 폴더에 저장했다면 cp의 원본 경로를 실제 위치로 바꾼다. vim으로 파일을 여는 것만으로 수정본이 반영되지 않는다. 도움말에 `--summary-style {original,explicit,separated}`와 `--check-report`가 표시되어야 한다. check-report는 모델을 생성하거나 호출하지 않으며 mock 필드 표기 6개를 검사한다.

이후 실제 Qwen 설명과 함께 확인:

이번 핵심 질문은 실제 모델을 연결한 전체 흐름에서도 필수 사실이 보존되고, 조회 실패가 빈 결과와 구분되는가이다. 모델 qwen3.5:9b, 엔진 graph, 보고 방식 separated와 나머지 기본 설정을 고정하고 scenario만 바꾼다. flaky는 복구 후 데이터 보고, empty는 빈 결과 보고, timeout은 실패 종료 경로를 확인한다. flaky의 최종 성공 결과가 normal과 같으므로 이번 확인에 normal 실행을 추가하지 않는다. 이 세 실행으로 모델 설명의 반복 신뢰성이나 엔진별 성능 차이를 판정하지 않는다.

```bash
python -u local_workflows.py --model qwen3.5:9b --engine graph --scenario flaky --summary-style separated
python -u local_workflows.py --model qwen3.5:9b --engine graph --scenario empty --summary-style separated
python -u local_workflows.py --model qwen3.5:9b --engine graph --scenario timeout --summary-style separated
```

| 실행 | 예상 코드 영역 | 예상 모델 호출 수* | 사용자 PC 관측 |
|---|---|---:|---|
| flaky | 조회 2회, 항목 1개, 실제 message와 count=3 | 요청 1 + 설명 1 | 일치. 설명 상태 ok |
| empty | 조회 1회, 반환 항목 0개, 이번 조회에서 로그 없음 | 요청 1 + 설명 1 | 일치. 설명 상태 ok |
| timeout | 조회 2회, QUERY_TIMEOUT, 확인 불가 | 요청 1, 설명 없음 | 일치. 설명 상태 skipped |

\* 성공한 애플리케이션 invoke 기준이며 SDK 내부 HTTP 횟수와 다르다.

모델 설명에서는 사실 영역과 모순되는 숫자·원인 단정·실제 정상 판정이 없는지, 제안을 수행 결과처럼 쓰지 않는지, 한국어 문장이 자연스러운지 확인한다. 설명이 틀려도 코드 영역 보존과 설명 품질은 서로 다른 평가 항목이다.

## 사용자 PC에서 확인한 결과

2026-10-09 공유한 터미널 출력에서 다음을 확인했다. 해당 관측의 사후 기록이다.

- 다운로드 수정본을 기존 local_workflows.py로 복사한 뒤 도움말에서 --summary-style {original,explicit,separated}와 --check-report가 표시됐다.
- --check-report의 항목 수와 발생 횟수 구분, 횟수 누락 보존, 빈 결과의 조회 성공 표시, 조회 실패와 0건 구분, 문자열 횟수 거부, 성공의 data=null 거부 등 6개 검증이 모두 PASS였다.
- 이 명령은 모델을 호출하지 않는다. 따라서 실제 Qwen 설명이나 실제 로그 연결이 검증된 것은 아니다. 파일 전체의 바이트 동일성도 이 출력만으로 확정하지 않는다.

### 실제 Qwen 연결 결과: 23:46 KST 공유

아래는 사용자 PC에서 실제 Qwen3.5:9b를 호출한 출력의 사후 정리다. 도구 데이터는 mock이다. 앞선 코드 출력 검증과 구분한다. 모델은 thinking=False, num_ctx=4096, num_predict=512, temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5, repeat_penalty=1.0으로 실행됐다. HTTP I/O timeout은 300초이며 전체 실행 기한은 아니다.

| 시나리오 | 관측한 흐름 | 코드 사실 영역 | 설명 단계 |
|---|---|---|---|
| flaky | request → execute(error) → execute(ok) → summarize | mock, order-api, 총 조회 2회, 항목 1개, ERROR, '테스트용: 하위 서비스 연결 실패', count=3 | 실제 Qwen 설명 완료, ok |
| empty | request → execute(ok) → summarize | mock, order-api, 총 조회 1회, 항목 0개, 이번 조회에서 로그 없음, 실제 상태 판단 불가 | 실제 Qwen 설명 완료, ok |
| timeout | request → execute(error) → execute(error) → unavailable | mock, order-api, 총 조회 2회, 조회 실패, QUERY_TIMEOUT, 확인 불가. 0건으로 표시하지 않음 | 추가 설명 호출 없음, skipped |

세 요청 모두 get_recent_errors(service='order-api')를 생성했다. 원문의 status=ok는 조회 성공으로만 출력됐고 flaky의 오류 내용·횟수는 코드 영역에 보존됐다. 이는 이번 세 입력에서 필수 사실 출력과 종료 경로가 의도대로 동작한 근거다.

모델 설명은 아래처럼 별도로 평가한다. 두 설명에서 중국어 혼입은 관측되지 않았지만, 반복 실행의 언어 품질까지 검증한 것은 아니다.

flaky 설명 원문:

> 판단 한계: 조회 결과의 source 가 'mock'이므로 실제 서비스 상태나 오류 발생 여부를 판단할 수 없습니다.
> 다음 확인: 해당 로그가 실제로 발생한 시점과 하위 서비스 연결 실패의 구체적인 원인을 파악하기 위해 모니터링 도구를 직접 점검해야 합니다.

첫 문장은 근거의 한계를 지켰다. 두 번째 문장의 '해당 로그가 실제로 발생한 시점'은 mock 오류가 실제 발생한 듯한 전제를 담는다. 다음 확인은 '실제 로그 저장소에서 같은 오류가 관측되는지 먼저 확인한다'고 쓰는 편이 근거 범위에 맞는다. 실제 원인이나 시점을 알아냈다고 주장한 것은 아니지만, 후속 조사 제안의 전제가 부정확하다.

empty 설명 원문(터미널 줄바꿈으로 나뉜 공백은 정리):

> 판단 한계: 제공된 데이터가 시뮬레이션(mock) 환경임을 명시했으므로, 빈 목록과 정상 상태 표시가 실제 서비스의 가동 여부나 오류 발생 여부를 증명할 수 없습니다.
> 다음 확인: 실제 로그 저장소나 모니터링 도구를 직접 조회하여 구체적인 장애 원인이나 사고 시점을 검증해야 합니다.

'정상 상태 표시'는 조회 성공 status=ok와 서비스 정상을 혼동시킬 수 있는 표현이다. 또 장애 발생 자체를 확인하지 않은 상태에서 '장애 원인이나 사고 시점'부터 검증하자고 제안한다. '실제 조회 범위·필터·수집 상태를 확인하고 오류 발생 여부를 조사한다'가 먼저다. 실제 서비스가 정상이라고 결론 내린 것은 아니므로 그 수준의 오류로 확대해서 기록하지 않는다.

따라서 판정은 **코드 사실 출력·분기 확인, 모델 설명 품질 보완 필요**다. ok는 생성 완료이며 내용 정확성 통과를 의미하지 않는다. 이번 실행에서는 설명 서버 실패를 주입하지 않았으므로 실제 Qwen 연결의 설명 실패 복구까지 확인했다고 쓰지 않는다.

### 시간·토큰 관측

| 시나리오 | request 경과 / 적재 | explain 경과 / 적재 | explain 입력 / 출력 토큰 |
|---|---|---|---:|
| flaky | 3.31 / 2.82초 | 0.91 / 0.01초 | 259 / 62 |
| empty | 0.43 / 0.01초 | 1.06 / 0.01초 | 232 / 71 |
| timeout | 0.49 / 0.01초 | 호출 없음 | 해당 없음 |

세 request의 입력/출력 토큰은 각각 381/28이고 모든 모델 응답의 done_reason은 stop이었다. request 출력 생성 속도는 순서대로 76.95 / 77.52 / 69.99 tokens/s, explain은 76.51 / 75.60 tokens/s였다. 첫 request에는 적재 2.82초가 포함되어 있으므로 경과 시간 차이를 시나리오 처리 비용으로 해석하지 않는다. 전체 프로그램 경과 시간과 반복 지연 분포는 측정하지 않았다.

## 별도 환경 검증 결과

Linux / Python 3.12, langchain-ollama=1.1.0, ollama=0.6.3, langchain-core=1.6.9, langgraph=1.2.14, httpx=0.28.1. Python 3.11 문법 파싱도 확인했다. 사용자 PC 전체 패키지 버전은 이 환경과 같다고 가정하지 않는다.

실제 LangChain·Ollama SDK에 HTTPX MockTransport로 가짜 응답을 연결했다. 실제 Ollama 서버나 Qwen 추론을 실행하지 않았다.

- 9개 unittest 통과. chain/graph + flaky, graph + empty/timeout, 기존 original/explicit 경로 포함.
- count=7·0·누락을 원문대로 표시. 문자열·bool·음수·null 횟수, 성공인데 data=null, 반환 service 불일치 거부.
- 가짜 모델이 999회와 서비스 정상을 주장해도 코드 사실은 3회로 보존됨. 잘못된 설명은 참고 영역에 남는다. 의미상 모순을 자동 탐지했다고 주장하지 않음.
- 설명 단계 HTTP 503·ReadTimeout·빈 답변·length 종료·추가 도구 요청에서 사실 보존, failed 및 종료 코드 2 확인.
- 도구 timeout은 HTTP 요청 생성 1회만 사용하고 설명을 호출하지 않음.
- check-report는 모델 생성 없이 6개 확인 통과.

저장소에서 검증을 다시 실행할 때:

```bash
python -m unittest discover -s examples/2026-10-07 -p 'test_local_workflows.py' -v
```

## 남은 확인

사용자 PC의 모델 없는 검증 6개와 실제 Qwen + graph/separated 세 경로를 확인했다. 필수 사실은 코드가 보존했지만 자유 서술의 부정확한 전제를 자동으로 걸러내지는 않는다. 원천 정보의 사실성, 의미상 모순의 자동 검증, 반복 신뢰성, 실제 설명 서버 장애 처리는 별도 확인 대상이다.

다음 단계는 observability-lab의 실제 Loki 연결 조건을 확인하는 것이다. 도구가 조회할 서비스, 도달 가능한 주소·권한, 조회 시간 범위·필터·반환 제한을 먼저 정한다. 수집 지연과 잘린 결과를 고려해야 하므로 반환 항목 수를 전체 오류 발생 횟수로 곧바로 바꾸지 않는다. 모델 설명 보완은 미해결 항목으로 유지하고, 실제 로그 연결 완료와 설명 품질 통과를 따로 판정한다.

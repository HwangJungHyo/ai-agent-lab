# 모델 API가 503을 반환하면 무엇을 얼마나 다시 실행해야 하는가?

작성·갱신: 2026-10-09. 상태: 별도 환경 및 사용자 PC의 HTTP 대역 검증 완료. 사용자 PC의 실제 Gemini 연결에서 chain·graph + flaky 확인. 실제 Gemini 503 발생 후 복구 여부는 미확인.

## 문제와 목적

사용자 PC에서 chain + flaky 실행이 request_model.invoke의 실제 Gemini 503으로 중단됐다. 기존 MAX_ATTEMPTS=2는 도구 조회에만 적용되므로 이 실패를 복구하지 않는다.

이번 질문은 모델 서버의 일시 실패를 모델 호출 범위에서 제한 재시도할 수 있는가이다. 전체 프로그램을 처음부터 실행하면 이미 성공한 도구까지 반복할 수 있다. 요청 생성과 최종 설명의 각 모델 호출에 같은 HTTP 정책을 적용한다.

## 선택지와 이번 추천

| 선택 | 적합한 조건 | 대가와 이번 판단 |
|---|---|---|
| 즉시 실패 반환 | 빠른 응답이나 상위 호출자의 복구가 필요한 경우 | 일시 실패 복구 기회를 놓침 |
| SDK에서 해당 HTTP 요청 재시도 | 같은 모델 요청을 일시 실패 후 반복 | SDK 내부 재시도를 관측해야 함. 이번 선택 |
| 그래프/애플리케이션에서 재시도 | 다른 모델로 전환하거나 상태에 따라 재계획 | 중복 재시도와 상태 관리 필요. 아직 구현하지 않음 |

정책은 최초 포함 최대 3회, 503만 대상이다. 3은 학습용 상한이며 운영 최적값을 측정한 결과가 아니다. 지수적으로 늘어나는 대기와 무작위 시간 차이(jitter)를 사용한다. 복구 기회를 주되 실패가 지속될 때 종료하기 위해서다.

HttpRetryOptions(attempts=3)는 최초 요청 1회와 추가 시도 최대 2회를 뜻한다. initial_delay=2.0, exp_base=2.0, max_delay=5.0, jitter=1.0으로 설정한다. 실제 대기 시간은 무작위 요소 때문에 매번 같지 않다. timeout=30_000의 단위는 밀리초이며 전체 워크플로 완료 기한은 아니다.

도구 QUERY_TIMEOUT 상한 2회는 기존 정책을 유지한다. 모델의 요청 생성 invoke와 요약 invoke는 각각 별도의 3회 상한을 갖는다. 따라서 3은 프로그램 전체 모델 HTTP 횟수 상한이 아니다. 별도 외부 재시도 루프는 추가하지 않는다.

선택을 바꿀 조건: 429는 속도 제한인지 할당량 소진인지 원인과 서버 안내를 확인한 뒤 정책을 별도로 정한다. 지연 목표가 엄격하거나 복구가 지속적으로 실패하면 전체 시간 예산·실패 응답·대체 모델을 설계한다. 이번에는 그 범위를 구현했다고 주장하지 않는다.

## 구현과 실행 전 판단 기준

새 파일: [model_retry_workflows.py](../../examples/2026-10-07/model_retry_workflows.py). 기존 복원 retry_workflows.py를 기준으로 만들었으며 원본 예제는 수정하지 않았다. 새 파일의 중요한 변경은 MODEL_HTTP_OPTIONS와 두 모델 invoke의 http_options 인자다.

--check-retry는 실제 LangChain 및 Google SDK를 사용하되 HTTPX MockTransport로 HTTP 응답만 대신한다. 별도의 API 키가 필요하지 않으며 Gemini 서버에 연결하지 않는다. 기존 --scenario flaky는 도구 실패 시나리오이고, 모델 503을 강제로 만드는 옵션이 아니다.

| 주입할 HTTP 응답 | 실행 전 예상 | 판단 기준 |
|---|---|---|
| 503 → 200 | 총 2회 후 응답 반환 | 일시 실패 후 정상 진행 |
| 계속 503 | 총 3회 후 예외 전달 | 네 번째 HTTP 요청 없음 |
| 403 | 총 1회 후 예외 전달 | 권한 오류 재시도 없음 |

설정 이름만 보고 횟수를 추정하지 않고 실제 SDK를 통과한 HTTP 요청 횟수를 세는 이유는, 패키지 버전이나 옵션 전달 방식에 따라 설정이 기대대로 적용되지 않을 수 있기 때문이다.

## 관측 결과: 별도 실행 환경

환경은 Linux / Python 3.12이며 사용자 Windows / Python 3.11.5 환경과 다르다.

| 패키지 | 검증 버전 |
|---|---|
| langchain-google-genai | 4.4.0 |
| google-genai | 2.29.0 |
| langchain-core | 1.6.9 |
| langgraph | 1.2.14 |
| httpx | 0.28.1 |

실행: python model_retry_workflows.py --check-retry

```text
503 후 복구: HTTP 503 → 200, 2회, PASS
503 지속: HTTP 503 → 503 → 503, 3회, PASS
403 권한 오류: HTTP 403, 1회, PASS
```

예상 세 경로와 관측이 일치했다. 이는 위 버전에서 옵션 전달과 제한 재시도가 동작했다는 근거다. 이 별도 환경에서는 실제 서버 복구율, 유료/무료 할당량 처리, 사용자 PC 버전 호환성, 실제 모델 응답을 검증하지 않았다. 이후 사용자 PC 관측은 아래에 별도로 기록한다.

## 사용자 PC 실행 방법

최초 전달 시에는 프로젝트 루트의 기존 .env 및 tools_mock.py와 같은 폴더에 model_retry_workflows.py를 저장했다. 아래는 그 위치 기준의 명령이다. 현재 저장소 버전은 examples/2026-10-07/에 있으므로 해당 폴더에서 실행한다. 실제 API 실행용 .env도 스크립트와 같은 폴더에 필요하며, --check-retry는 키가 필요 없다. 기존 tools_mock.py를 교체하는 작업이 아니다.

```bash
python model_retry_workflows.py --check-retry
python model_retry_workflows.py --engine chain --scenario flaky
python model_retry_workflows.py --engine graph --scenario flaky
```

먼저 --check-retry가 세 PASS를 출력하는지 확인한다. 실패하면 실제 API 실행을 진행하지 않고 버전과 오류를 확인한다. 임의 패키지 업그레이드를 먼저 하지 않는다.

실제 실행은 요청 생성 → 도구 실패 → 도구 성공 → 요약을 예상한다. 모델이 계속 503을 반환하면 해당 invoke가 최대 3회 후 예외로 종료할 수 있다. 이는 복구 보장이 아니라 실패 상한 정책이다.

실제 실행 성공만으로 503 재시도가 실제 발생했다고 판정하지 않는다. [request]는 invoke 진입 로그라 SDK 내부 HTTP 횟수를 나타내지 않는다. --check-retry의 [HTTP]가 대역 테스트에서 직접 센 횟수다.

## 관측 결과: 사용자 PC, 2026-10-09

근거: 사용자가 공유한 Windows Git Bash 실행 출력. 앞선 가상환경 확인에서 Python 3.11.5를 사용했으며, 이번 출력은 아래 패키지 버전을 직접 확인해 준다.

| 패키지 | 사용자 PC 버전 |
|---|---|
| langchain-google-genai | 4.4.0 |
| google-genai | 2.28.0 |
| langchain-core | 1.6.7 |
| langgraph | 1.2.14 |
| httpx | 0.28.1 |

별도 환경의 google-genai 2.29.0 및 langchain-core 1.6.9와 다르다. 사용자 PC에서도 아래 검증이 통과했으므로 해당 버전 조합의 관측을 별도로 보존한다. 전체 의존성 lock은 아니다.

| 실행 | 관측 사실 | 판정 |
|---|---|---|
| --check-retry: 503 후 복구 | HTTP 503 → 200, 2회, PASS | 해당 모델 요청 재시도 후 응답 반환 확인 |
| --check-retry: 503 지속 | HTTP 503 세 번, 예외 종료, PASS | 3회 상한 확인 |
| --check-retry: 403 | HTTP 403 한 번, 예외 종료, PASS | 이 정책에서 403 비재시도 확인 |
| chain + flaky | request → execute(error) → execute(ok) → summarize, 총 조회 2회 | 실제 Gemini 요청 생성·요약과 mock 도구 복구 연결 확인 |
| graph + flaky | request → execute(error) → execute(ok) → summarize, 총 조회 2회 | 같은 정책의 그래프 경로 확인 |

두 실제 실행 모두 get_recent_errors(service='order-api')를 요청했고, mock 도구 결과에는 '테스트용: 하위 서비스 연결 실패' count=3이 포함됐다. count=3은 mock 로그 발생 횟수이며 도구 조회 횟수 2회나 모델 HTTP 상한 3회와 의미가 다르다.

핵심 사용자 출력:

```text
engine=chain, scenario=flaky
[request] 모델 호출: 조회 요청 생성
[execute] 시도 1/2, status=error
  오류: QUERY_TIMEOUT
[execute] 시도 2/2, status=ok
[summarize] 모델 호출: 최종 조회 결과 설명
[총 조회 시도] 2회

engine=graph, scenario=flaky
[request] 모델 호출: 조회 요청 생성
[execute] 시도 1/2, status=error
  오류: QUERY_TIMEOUT
[execute] 시도 2/2, status=ok
[summarize] 모델 호출: 최종 조회 결과 설명
[총 조회 시도] 2회
```

## 해석과 남은 범위

- 10월 7일에 모델 503 때문에 도달하지 못했던 chain의 도구 복구 경로를 새 model_retry_workflows.py에서 확인했다. 과거 원본 실행의 실패 이력을 성공으로 바꾸지는 않는다.
- 실제 연결의 request/summarize 로그는 모델 invoke 진입 두 곳을 보여 준다. SDK 내부 실제 HTTP 시도 횟수나 실제 503 발생 여부는 이 출력에 없다. 실제 Gemini 503을 재시도로 해결했다고 단정하지 않는다.
- 첫 대역 테스트에서 AFC 권고 메시지가 출력됐고 그 뒤 세 PASS와 실제 두 실행이 완료됐다. 관측상 실행 중단 오류는 아니었다. 이를 서버 호출이나 자동 도구 실행의 증거로 보지 않는다.
- chain 응답의 '조회 시스템이 정상 작동함'은 조회 성공보다 넓게 읽힐 수 있다. 여기서 확인된 사실은 mock 도구가 이번 조회에서 status=ok를 반환했다는 것이다. 조회 시스템 전체의 건전성이나 실제 서비스 정상 여부는 확인하지 않았다.
- 두 방식이 같은 결과를 낸 것은 같은 재시도 정책을 두 실행 구조로 구현했다는 근거다. 이 실습만으로 LangGraph의 안정성 우위를 판정할 수 없다.
- 학습자가 선택 이유를 직접 설명했는지는 별도이며, 실행 통과를 이해 완료로 기록하지 않는다.

다음 추천 질문은 실제 로그 조회 결과를 같은 도구 계약으로 전달할 수 있는가이다. 기존 observability-lab의 서비스·포트를 확인하고 조회 시간 범위와 원본 응답을 정한 뒤 연결한다. 이번 변경에서는 실제 로그 연동 코드를 구현하거나 실행하지 않았다.

## 근거

- [LangChain Gemini 통합: invoke의 http_options와 retry_options 우선순위](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai)
- [Google Gen AI SDK HttpRetryOptions](https://googleapis.github.io/python-genai/genai.html#genai.types.HttpRetryOptions)
- [Gemini 오류 해결: 503 및 지수 백오프](https://ai.google.dev/gemini-api/docs/troubleshooting)
- [HTTPX MockTransport](https://www.python-httpx.org/advanced/transports/#mock-transports)

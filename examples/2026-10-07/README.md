# 2026-10-07 실습 코드 복원본

대화에서 제공한 코드와 수정 사항을 복원했다. **사용자 PC의 최신 파일을 직접 읽거나 복사한 스냅샷은 아니다.** import 수정, main 가드와 중복 설정 정리 등 편집이 포함됐다. [실제 실행 증거](../../docs/evidence/2026-10-07-foundations.md)는 사용자 PC 출력이며 이 복원본 자체를 다시 API로 검증했다는 뜻은 아니다.

기존 루트 파일과 겹치지 않게 별도 폴더에 보관한다. 커리큘럼의 apps/tools 구조로 이전하는 작업은 아직 하지 않았다.

| 파일 | 역할 |
|---|---|
| first_call.py | Gemini SDK 첫 호출·시간·사용량 |
| tools_mock.py | 모델 없이 실행하는 가짜 조회 함수 |
| tool_call.py | SDK 기반 ANY 단일 도구 요청 → 실행 → 설명 |
| compare_workflows.py | 동일 부품을 Python 순서문 / LangGraph로 연결 |
| retry_workflows.py | 도구만 최대 2회 실행; 복구·상한 종료 비교 |
| model_retry_workflows.py | Gemini 모델 HTTP 503 재시도와 도구 재시도 분리; --check-retry 포함 |
| local_workflows.py | Ollama/Qwen + mock/Loki 도구; Loki는 separated 보고 방식 |
| test_local_workflows.py | 가짜 HTTP로 사실 보존·설명 실패·기존 실행 경로 확인 |
| test_loki_workflows.py | 실제 그래프·SDK + HTTP 대역으로 새 Loki 연결 검사 |
| .env.example | 비밀값 없는 설정 이름과 당시 모델 ID |
| requirements.txt | Gemini 예제 직접 의존성 목록; 버전 lock은 아님 |
| requirements-local.txt | 로컬 Ollama 예제 직접 의존성 목록; 전체 lock은 아님 |

## 실행 준비 — Windows Git Bash

이미 설치한 가상환경에서는 재설치가 필수는 아니다. 새 환경은 Python 3.11 계열을 기준으로 하며 정확한 설치 버전은 아직 미수집이다.

```bash
cd ~/Desktop/git-devops/ai-agent-lab
source .venv/Scripts/activate
python -m pip install -r examples/2026-10-07/requirements.txt
python -m pip check
cd examples/2026-10-07
cp -n .env.example .env
notepad.exe .env
```

Gemini 스크립트는 **자신과 같은 폴더의 .env**를 읽는다. 이 폴더의 .env에 실제 키를 입력한다. 루트 .env를 자동으로 탐색하지 않는다. 실제 .env와 .venv는 커밋하지 않는다. requirements는 고정 버전 파일이 아니므로 향후 동일 환경을 보장하지 않는다. 로컬 Qwen 예제만 실행할 경우 아래 로컬 준비 절차를 사용하며 Gemini 키는 필요 없다.

## 모델 호출 없는 확인

```bash
python tools_mock.py
python -c "import compare_workflows; import retry_workflows; print('모듈 import 성공')"
```

## API를 사용하는 실행 명령

아래는 재현 명령 목록이다. 목적에 맞게 선택하며 모든 명령을 불필요하게 반복하지 않는다.

```bash
python first_call.py
python tool_call.py --scenario normal
python tool_call.py --scenario empty
python tool_call.py --scenario timeout

python compare_workflows.py --engine chain --scenario normal
python compare_workflows.py --engine graph --scenario normal
python compare_workflows.py --engine chain --scenario empty
python compare_workflows.py --engine graph --scenario empty
python compare_workflows.py --engine chain --scenario timeout
python compare_workflows.py --engine graph --scenario timeout

python retry_workflows.py --engine chain --scenario flaky
python retry_workflows.py --engine graph --scenario flaky
python retry_workflows.py --engine chain --scenario timeout
python retry_workflows.py --engine graph --scenario timeout
```

## 선택과 근거

- 첫 모델 호출은 any로 도구 요청을 강제하고 마지막은 none으로 추가 요청을 제한한다. AUTO 비교는 미검증이다.
- 조회 실패 시 코드가 고정 안내문을 반환한다. 단일 조회 보고에서 추가 모델 호출 없이 한계를 일관되게 전달하기 위한 정책이다.
- MAX_ATTEMPTS=2는 **최초 시도 포함 전체 2회**다. flaky는 처음 timeout, 다음 normal로 바꾼다. tools_mock 자체에는 flaky가 없다.
- scenario와 시도 횟수는 테스트 실행 코드에서만 정한다. 모델은 가짜 증거의 종류를 선택하지 않는다.
- 도구 재시도는 저장한 요청을 재사용하고 최종 결과 하나만 대화에 넣는다. 중간 실패는 콘솔·상태에만 있으며 지속 저장하지 않는다.
- 모델 max_retries와 도구 MAX_ATTEMPTS는 다르다. SDK 내부 총 HTTP 시도 횟수는 버전별 구현 확인이 필요하다.
- chain은 LangChain 기본 구성요소 + 일반 Python 실행 제어다. LangChain create_agent 자체도 LangGraph 기반이므로 이번을 create_agent 대 LangGraph 비교로 부르지 않는다.
- 그래프 compile만으로 저장·재개가 생기지 않는다. checkpointer는 구성하지 않았다.

| 조건 | 기대 경로 | 애플리케이션 모델 invoke 수* |
|---|---|---:|
| compare normal / empty | request → execute → summarize | 2 |
| compare timeout | request → execute → unavailable | 1 |
| retry flaky | request → execute(error) → execute(ok) → summarize | 2 |
| retry timeout | request → execute(error) → execute(error) → unavailable | 1 |

\* 모델 호출이 성공하는 경우. SDK 내부 HTTP 재시도나 과금 횟수가 아니다.

## import 구분

```python
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
```

BaseMessage는 위 경로를 사용한다. import는 최상위 코드를 실행하지만 이 예제의 main 가드 덕분에 main 안의 모델 호출은 실행하지 않는다. 모든 모듈의 import가 부작용이 없는 것은 아니다.

## 2026-10-09 후속: 모델 HTTP 재시도

예제 폴더에서 `python model_retry_workflows.py --check-retry`를 실행하면 가짜 HTTP 응답으로 503 후 복구·503 지속·403의 세 경로를 검사한다. 실제 Gemini 호출과 mock 도구를 연결하려면 같은 폴더의 .env를 준비한 뒤 `python model_retry_workflows.py --engine graph --scenario flaky`를 사용한다. [재시도 선택 이유와 관측](../../docs/evidence/2026-10-09-model-retry.md)에 사용자 PC와 별도 환경의 결과를 구분해 기록했다.

## 2026-10-09 후속: 로컬 Qwen과 사실 출력 분리

`local_workflows.py`는 사용자 PC의 Ollama 모델로 같은 mock 도구를 호출하는 후속 예제다. `.env`와 Gemini 키를 읽지 않는다. 초기 연결과 설치는 [로컬 모델 기록](../../docs/evidence/2026-10-09-local-models.md), 현재 변경 이유·적용·판정 기준은 [사실 출력과 설명 분리](../../docs/evidence/2026-10-09-facts-and-explanation.md)를 따른다.

새 Python 환경에서는 프로젝트 루트에서 아래 의존성을 설치한다. 이미 실습이 동작하는 환경에서는 재설치할 필요가 없다. Ollama 설치·qwen3.5:9b 다운로드는 위 연결 기록을 따른다.

```bash
source .venv/Scripts/activate
python -m pip install -r examples/2026-10-07/requirements-local.txt
python -m pip check
cd examples/2026-10-07
```

--check-report와 unittest는 Ollama 서버를 호출하지 않는다. 실제 --probe/--engine 실행은 localhost:11434의 Ollama와 다운로드된 모델이 필요하다.

- `--summary-style original`: 기존 모델 요약.
- `--summary-style explicit`: 필요한 필드·해석 범위를 구체화한 모델 요약. 기존 기본값.
- `--summary-style separated`: 필수 사실은 코드가 출력하고 모델 설명을 별도 영역에 표시.
- `--check-report`: 모델 호출 없이 사실 출력·입력 형식 6개 확인.

```bash
python local_workflows.py --check-report
python local_workflows.py --engine graph --scenario flaky --summary-style separated
python local_workflows.py --engine graph --scenario empty --summary-style separated
python local_workflows.py --engine graph --scenario timeout --summary-style separated
python -m unittest test_local_workflows -v
```

위 명령은 이 예제 폴더에서 실행한다. 사용자 PC 루트에 파일을 복사해 실행해 온 경우 기존 `local_workflows.py`를 수정본으로 교체한다. `test_local_workflows.py`는 별도 환경의 가짜 HTTP 검증용이며 실제 모델 설명 품질을 평가하지 않는다. 필수 사실을 코드로 표시해도 모델 설명의 모순이 자동으로 검출되지는 않는다.

## 2026-10-10 후속: 기존 그래프에 Loki 연결

[새 연결의 이유·최소 증거·종료 기준](../../docs/evidence/2026-10-10-loki-graph.md)을 따른다. 기본 --source는 mock이며 기존 명령은 유지된다. Loki는 --source loki와 조회 조건을 지정하고 --scenario를 생략한다. Loki의 기본 보고 방식은 separated이며 다른 방식은 받지 않는다.

PC 루트에서는 수정된 local_workflows.py와 loki_query.py를 같은 폴더에 적용한다. 저장소 예제 경로로 실행하면 ../2026-10-10/loki_query.py를 불러온다. 새 패키지 설치는 요구하지 않는다.

```bash
python -u local_workflows.py --model qwen3.5:9b --engine graph --source loki \
  --service order-api --start 2026-10-10T03:48:00Z --end 2026-10-10T03:50:00Z \
  --request-id agent-loki-20261010T034854Z-7943 --limit 20 --summary-style separated
```

확인된 정상 로그 한 줄을 재사용해 새 연결을 대조한다. request 단계에서 get_logs 요청, execute 결과의 source=loki, 코드 사실의 범위·원문·줄 수, 모델 설명의 근거 준수를 본다. 이 네 위치가 맞으면 같은 사례의 반복 실행을 멈춘다. 조회 timeout은 총 2회까지 동일 범위를 재시도하며 HTTP 503은 현재 종료한다.

최신 조회에는 --start/--end 대신 --minutes 10을 사용한다. --errors-only는 JSON level=error 조건을 추가한다. --loki-timeout은 Loki I/O 제한이며 --timeout은 Ollama I/O 제한이다. 서비스 payment-api는 mock 전용, payment는 실제 Loki 전용이다. 지금은 모델이 service 인자만 생성하고 조회 기간·필터·상한은 코드가 설정한다.

## 자연어 조회 입구 (2026-10-10)

`natural_request.py`를 새로 추가하고 `local_workflows.py`에 `--question`과 `--run-query`를 연결했다. PC에서는 `local_workflows.py`, `natural_request.py`, `loki_query.py`가 같은 폴더에 있어야 한다. 추가 패키지 설치는 필요하지 않다.

모델은 조회 조건만 제안한다. 코드는 대상·시간·필터·미해결 조건을 검증하고 기본적으로 조건만 표시한다. `--run-query`는 이번 실행에서 검증된 제안을 바로 실행한다. 이전 미리보기의 제안을 승인·저장·재개하는 기능은 아니므로 재실행 시 제안과 시간이 달라질 수 있다.

```bash
python -u local_workflows.py --model qwen3.5:9b --engine graph --source loki \
  --question 'order-api의 최근 10분 오류 로그를 확인해줘'

python -u local_workflows.py --model qwen3.5:9b --engine graph --source loki \
  --question '아까 결제가 이상했어'
```

첫 명령은 `order-api`, `10`, `true`, 미해결 조건 없음과 조회 조건을 확인한다. 둘째는 대상·시간·증상을 함께 묻고 조회하지 않아야 한다. 추가 질문은 출력하고 종료한다(코드 2). 보완한 전체 질문으로 다시 실행한다. 대화 세션 저장은 없다.

명확한 요청을 실제 조회하려면 첫 명령에 `--run-query`를 붙인다. 조건을 표시하고 조회하며, 실패하지 않는 경우 해석·설명 모델 호출은 총 2회다. 기존의 고정 시각 CLI 조회도 사용할 수 있다. 자연어 입구는 최근 1~60분만 지원하고 대상/시간/요청 ID 필터 CLI 옵션과 혼합하지 않는다.

코드의 형식 검증은 사용자 의도와 모델 해석의 일치까지 보장하지 않는다. [기준·검증·한계](../../docs/evidence/2026-10-10-natural-request.md)를 구분한다.

23:26 KST 출력 반영: 서비스 별칭 매핑은 지원하지 않으며 질문에 정확한 `order-api` 또는 `payment` 이름 하나가 있어야 한다. 모델의 자료형 오류는 제안을 표시하고 조회 없이 안내·종료한다. 모델 지시 보강의 실제 효과는 PC 확인 대상이다.

23:30 KST 후속 정책: 실제 모델이 반환한 숫자 문자열과 true/True/false/False 문자열만 정규화하고 기존 범위 검증을 적용한다. 원래 제안과 변환 내역은 표시하며, 의미 추정·누락 보정·범위 축소는 하지 않는다. 모호한 요청의 실제 PC 분기는 확인됐으므로 명확한 미리보기만 재확인한다.

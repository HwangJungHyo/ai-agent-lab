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
| local_workflows.py | Ollama/Qwen 연결; original/explicit/separated 보고 방식 |
| test_local_workflows.py | 가짜 HTTP로 사실 보존·설명 실패·기존 실행 경로 확인 |
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

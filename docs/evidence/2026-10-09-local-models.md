# 로컬 모델로 바꿔도 같은 조회 도구와 실행 흐름이 동작하는가?

작성·갱신: 2026-10-09, Asia/Seoul. 상태: 사용자 PC에서 Qwen3.5-9B 연결·GPU 적재·graph 세 경로 및 후속 chain + flaky 완료 확인. explicit 요약에서 핵심 정보 포함과 빈 결과 해석을 단발 확인했다. 후속 separated 모드의 세 경로도 사용자 PC에서 확인했으며 상세 결과는 [사실 출력·모델 설명 분리](2026-10-09-facts-and-explanation.md)에 기록한다. 설명 품질·반복 신뢰성은 보완 대상이다.

## 왜 이 실험을 하는가

기존에는 Gemini API를 호출했다. 이번에는 학습된 공개 모델을 사용자 PC에서 실행하고 기존 Python 도구와 연결한다. 모델 서버 운영과 애플리케이션 흐름을 구분하고, 로컬 모델이 같은 도구 계약을 지키는지 확인하려는 목적이다.

사용자가 실제 로그 연결에 앞서 로컬 모델 구동을 제안했고, 장비 출력을 공유한 뒤 Qwen을 포함한 비교를 요청했다. 우선 모델 호출 위치를 바꾸는 실험으로 진행하며 기존 mock 데이터·서비스·도구 조회 상한은 유지한다. 실제 로그 연동은 후속 과제로 남긴다.

## 사용자 장비: 확인된 사실

- Windows Git Bash에서 RAM_GB=63을 확인했다. 약 64GB급 시스템 RAM이며 GPU 전용 메모리와 구분한다.
- NVIDIA GeForce RTX 4070 Ti, memory.total=12282 MiB, 약 12GB VRAM.
- AMD Radeon(TM) Graphics도 장치 목록에 있다. ollama ps에서 100% GPU 적재를 확인했다. 장치별 실제 메모리 점유 출력은 아직 공유되지 않았다.

## 선택지와 추천 근거

Ollama의 Windows용 llama.cpp 배포 항목 기준이며 아래는 다운로드 크기다. 실제 VRAM 사용량이 아니다. 가중치 외에 실행 버퍼와 문맥을 처리하는 메모리가 필요하다.

| 모델 | 확인한 배포 크기 | 이번 판단 |
|---|---|---|
| qwen3.5:9b | Q4_K_M, 약 6.6GB | 사용자가 확정한 기본 모델. 짧은 문맥에서 12GB GPU에 전부 적재하는 구성을 먼저 검증 |
| gemma4:e4b | Q4_K_M, 약 6.6GB | 비슷한 배포 용량의 비교 후보 |
| gemma4:12b | Q4_K_M, 약 8.0GB | 더 큰 모델의 품질을 확인할 때 후속 후보. 메모리 여유 감소 |
| qwen3.8:27b | Q4_K_M, 약 18GB | 후속 품질 비교 후보. 12GB GPU에 전부 적재할 수 없어 CPU/RAM과 GPU 혼합 사용 필요 |
| gemini-3.1-flash-lite | 외부 API | 기존 사용자 실행을 비교 기준으로 유지. 위 로컬 모델과 같은 하드웨어 조건의 비교는 아님 |

Q4_K_M은 가중치를 주로 4비트로 줄여 저장하는 양자화 형식이다. 숫자가 작은 모델도 이미지 처리 모듈 등 부가 구성에 따라 전체 배포 크기가 달라진다. Gemma E4B의 E는 effective를 뜻하므로 모델 이름 숫자만으로 Qwen 9B와 메모리 비율을 계산하지 않는다.

제조사 공개 평가 참고치:

| 평가 | Qwen3.5 9B | Gemma 4 E4B | Gemma 4 12B |
|---|---:|---:|---:|
| MMLU-Pro | 82.5 | 69.4 | 77.2 |
| LiveCodeBench v6 | 65.6 | 52.0 | 72.0 |

평가 실행자·프롬프트·추론 예산·정밀도가 완전히 같은 직접 대결 결과가 아니다. Q4_K_M / 짧은 문맥 / thinking=False 설정의 성능을 나타내지도 않는다. 한국어 로그 설명과 도구 호출 정확도의 우열은 이 표로 확정하지 않는다. Qwen을 우선 시험할 근거와 Gemma를 비교할 이유로 사용한다.

첫 실행은 Windows 네이티브 Ollama를 추천한다. 현재 Python도 Windows에서 실행 중이므로 localhost 통신과 GPU 활용을 먼저 확인하기 쉽다. Docker/WSL의 GPU 연결과 컨테이너 네트워크 자체를 배우는 요구가 생기면 실행 환경을 추가 비교한다.

## 현재 선택: Qwen3.5-9B로 시작

사용자는 3.8과 3.5의 기능·자원 요구 및 Gemini와의 공개 평가를 비교한 뒤 Qwen3.5로 진행하기로 확정했다. 모델 크기는 앞서 비교한 9B를 선택한다. 이유는 현재 단일 도구 호출 실습에 필요한 기능을 제공하면서, 12GB GPU에 적재하기 쉬운 규모로 반복 실습의 자원 부담을 줄일 수 있기 때문이다. 이후 GPU 전체 적재와 graph 도구 호출을 확인했으며 요약 내용에는 보완점이 관측됐다.

3.8 검토 이력은 아래에 남기며, 아래 설치·실행 명령의 기본 대상은 모두 qwen3.5:9b다. --model을 생략해도 3.5가 선택된다. 3.8은 이후 실제 실패 사례에서 품질 개선과 추가 지연을 비교할 후보로 유지한다.

### 벤치마크 점수와 실제 사용 경험이 달라지는 이유

| 차이 | 우리 실습에서 확인할 내용 |
|---|---|
| 평가하는 업무 | 과학 객관식 정답률과 한국어 로그 조회 도구의 함수·인자 정확도는 다른 능력 |
| 평균에 가려진 실패 | 평균이 같아도 어떤 모델은 빈 로그를 정상으로 단정하거나 대상 서비스를 바꿀 수 있음 |
| 실행 설정 | 양자화, thinking, 출력 상한, 문맥 길이, 샘플링 설정이 공개 평가 조건과 다름 |
| 주변 프로그램 | 프롬프트, 도구 설명, JSON 해석, 재시도 정책도 전체 성공 여부에 관여 |
| 품질과 지연 | 정답률이 같아도 로딩·첫 응답·전체 처리 시간은 하드웨어와 적재 방식에 따라 달라짐 |

처음에는 연결, 올바른 도구 요청, 제어 흐름, 답변의 근거 준수를 확인한다. 첫 성공만으로 벤치마크 우열을 정하지 않는다. 그다음 같은 대표 입력을 반복해 업무별 성공률과 실패 원인을 기록한다. 첫 로딩 시간과 이미 적재된 이후의 시간을 구분하고, 한국어 설명의 자연스러움과 사실 정확도를 따로 평가한다.

## 검토 이력: Qwen3.8-27B의 실행 가능성과 제약

사용자는 앞서 Qwen 3.8 실행 가능성을 확인했고 3.8 실행안을 준비했다. 이후 위와 같이 3.5를 기본 모델로 확정했다. 작은 모델 추천은 GPU에 전부 올리기 쉬운 구성을 기준으로 했으며, Qwen 3.8 자체가 실행 불가능하다는 뜻은 아니다.

- 공개 여부: Qwen 공식 모델 저장소에 8월 13일 파일 업로드, 8월 14일 모델 카드·라이선스 갱신 이력이 있다. 커밋 날짜와 최초 공개 시각은 엄밀히 다른 정보이므로 정확한 출시 시각으로 단정하지 않는다.
- 모델 구분: 당시 검토 대상은 다운로드 가능한 Qwen3.8-27B다. Qwen3.8-Max와 같은 모델로 취급하지 않는다.
- GPU만 사용: 27B를 이상적인 4비트로 저장해도 약 13.5GB(십진수)가 필요하다. 실제 Q4_K_M 모델과 부가 구성은 더 크고 문맥·실행 버퍼도 필요하므로 12GB VRAM에 전부 적재할 수 없다. 문맥만 줄여도 모델 가중치 자체는 작아지지 않는다.
- CPU/GPU 혼합: Ollama는 시스템 RAM과 GPU에 나누어 적재하는 방식을 지원한다. 사용자 장비의 64GB급 RAM은 이 경로를 시도할 근거다. 실제 여유 RAM·CPU 모델·드라이버·디스크는 아직 미확인이다.
- 대가: CPU 연산·RAM 대역폭·장치 간 전송이 지연 요인이 될 수 있다. RAM 64GB와 VRAM 12GB를 단순히 합쳐 76GB GPU라고 볼 수 없다. 구체적인 응답 시간은 측정 전 예측값으로 쓰지 않는다.
- 목적: 짧은 도구 호출 실습을 감당할 만한 시간에 실행할 수 있는지 확인한다. 장문·동시 사용자·제조사 최대 성능 재현은 이번 완료 기준이 아니다.

## 실행 전에 고정할 조건

- 입력: 같은 한국어 조회 요청, 대상 order-api, 같은 tools_mock.py.
- 도구 조회: 최초 포함 최대 2회. flaky는 첫 실패 후 성공, timeout은 두 번 실패 후 종료.
- 로컬 모델: 한 번에 하나씩, context=4096, 출력 상한=512, thinking=False. 첫 probe는 출력 상한 64로 더 짧게 제한한다.
- Qwen3.5와 Qwen3.8의 일반 작업용 non-thinking 권장값 중 temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5, repeat_penalty=1.0을 전달한다. Gemma는 temperature=1.0 및 배포본 기본값을 사용한다. 따라서 모델별 설정을 포함한 사용성 비교이며, Gemini와의 강제 도구 호출 방식도 달라 완전한 통제 실험이라고 주장하지 않는다.
- keep_alive=10m: 호출 이후 GPU 적재 상태를 확인할 시간 확보. HTTP 클라이언트 I/O timeout=300초는 전체 조사 기한이 아니다. 실행은 Ctrl+C로 중단하고, 필요하면 ollama stop qwen3.5:9b로 적재를 해제한다.
- --num-ctx / --max-output / --timeout으로 상한을 조정할 수 있다. 메모리가 부족하면 짧은 입력에서 --num-ctx 2048로 문맥 처리 부담을 낮출 수 있다. 모델 가중치 자체가 작아지는 설정은 아니다.
- 모델 호출 자동 재시도는 이번 초안에 추가하지 않았다. 최초 연결 실패와 자원 문제를 관측하기 위한 기준선이다.
- 모델의 최대 지원 문맥 길이는 현재 GPU에서 그대로 쓸 수 있다는 의미가 아니다. 4096은 짧은 실습 입력을 위한 시작값이며 장문 품질 평가는 별도다.

## 새 실행 파일과 중요한 구현 차이

새 파일: [local_workflows.py](../../examples/2026-10-07/local_workflows.py).

사용자 PC에서는 기존 .env 및 tools_mock.py가 있는 ai-agent-lab 루트에 저장한다. 이전 답변의 local_workflows.py를 이미 받았다면 이 파일만 갱신한다. 기본 모델을 qwen3.5:9b로 바꾸고 non-thinking 권장값도 반영했다. 새 파일은 Gemini 키나 .env를 읽지 않으며, http://127.0.0.1:11434의 Ollama만 호출한다.

langchain-ollama 1.1.0의 ChatOllama.bind_tools 소스에서 tool_choice 인자가 무시됨을 확인했다. 따라서 any/none을 그대로 복사하지 않는다. 요청 단계에는 도구 정의를 전달하고 정확히 한 번의 get_recent_errors(service='order-api') 요청인지 코드로 검사한다. 요약 단계에는 새 도구 정의를 전달하지 않는다. 모델이 요청을 만들지 않으면 MODEL_CONTRACT_ERROR로 종료한다.

선택한 모델의 옵션은 probe·도구 요청·최종 요약 모두에 전달한다. 현재 ChatOllama 생성자는 presence_penalty 필드가 없어 options 전체를 bind/bind_tools로 전달한다. 이 과정에서 context·출력 상한이 빠지지 않는지 HTTP 대역으로 확인한다. 출력이 상한에 도달하면 OUTPUT_LIMIT로 종료하여 잘린 답변을 완전한 성공으로 기록하지 않는다.

최초 실제 실행에서 요약 품질 문제가 관측되어 후속 수정안을 추가했다. 각 도구 원문을 [tool_result]로 출력하고 --summary-style original/explicit으로 요약 지시를 비교한다. 기본값 explicit은 요약 단계에만 message·count·빈 결과 해석 기준을 추가한다. 아래에 기록한 최초 사용자 실행은 이 수정 이전 결과다. 상세 설계는 [요약 품질 기록](2026-10-09-local-summary.md)을 따른다.

## 설치부터 연결까지: Windows Git Bash

### 1. Ollama 설치

[공식 Windows 설치 페이지](https://ollama.com/download/windows)에서 설치하고 앱을 실행한다. 설치 후 Git Bash를 새로 열어 PATH를 반영한다. 기본 API는 localhost:11434다.

```bash
cd ~/Desktop/git-devops/ai-agent-lab
source .venv/Scripts/activate

ollama --version
curl -fsS --max-time 5 http://127.0.0.1:11434/api/version
ollama ps
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv
powershell.exe -NoProfile -Command 'Get-CimInstance Win32_Processor | Select-Object Name'
powershell.exe -NoProfile -Command 'Get-CimInstance Win32_OperatingSystem | Select-Object @{Name="FreeRAM_GB";Expression={[math]::Round($_.FreePhysicalMemory/1MB,1)}}'
df -h /c/Users/PC
```

예상: CLI 버전과 API의 version JSON, 실제 가용 메모리와 디스크 공간. Connection refused면 Ollama 앱 실행 상태부터 확인한다. ollama ps에 다른 모델이 적재돼 있으면 해당 이름으로 ollama stop 모델이름을 실행해 내린다. Qwen3.8이 올라가 있다면 ollama stop qwen3.8:27b를 사용한다. 다운로드한 모델 파일은 삭제되지 않는다. 이 단계에서는 모델을 아직 호출하지 않는다. 모델 다운로드 약 6.6GB 외에 프로그램·업데이트 공간도 필요하므로 모델 저장 드라이브에 15GB 정도의 여유를 권장한다(이번 실습의 여유값이며 제조사 최소 요구치가 아님).

### 2. 첫 모델과 Python 연결 패키지 준비

```bash
ollama pull qwen3.5:9b
ollama show qwen3.5:9b
python -m pip install "langchain-ollama==1.1.0"
python -m pip check
```

pull은 모델 파일을 다운로드하며 최초 실행 시 메모리에 적재한다. show 출력에서 모델 정보와 tools 지원을 확인한다. 설치 공간은 Ollama 프로그램, 모델 파일, 업데이트 여유를 포함해 확보한다. 공개된 모델 태그는 바뀔 수 있으므로 ollama list/show의 모델 ID와 버전을 결과에 남긴다.

### 3. 새 파일 저장 후 단독 호출과 기존 흐름 확인

최초 실습에서는 대화에 제공한 local_workflows.py를 C:\Users\PC\Desktop\git-devops\ai-agent-lab\local_workflows.py에 저장해 실행했다. 현재 저장소의 파일은 examples/2026-10-07/local_workflows.py에 있다. git pull은 루트의 기존 다운로드 파일을 교체하지 않는다. 저장소 버전을 사용하려면 프로젝트 루트에서 python examples/2026-10-07/local_workflows.py로 실행하고 아래 옵션을 붙인다. tools_mock.py에는 프로그램 내용을 붙여넣지 않는다.

```bash
python local_workflows.py --model qwen3.5:9b --probe --max-output 64
ollama ps
python local_workflows.py --model qwen3.5:9b --probe --max-output 64
```

probe는 도구 없이 한국어 한 문장과 시간·토큰 정보를 출력한다. 처음에는 적재 시간을 포함하고, 곧바로 실행한 두 번째 호출은 이미 적재된 상태의 응답 시간을 관측한다. generation_tokens_per_second는 서버가 보고한 출력 생성 토큰/초이며, 모델 적재·입력 처리를 포함한 전체 속도는 아니다. 100% GPU 적재를 기대하는 구성이지만 실제 여유 VRAM·드라이버 등에 따라 달라질 수 있으므로 ollama ps로 확인한다. 응답이 확인되면 다음을 실행한다.

```bash
python local_workflows.py --model qwen3.5:9b --engine chain --scenario flaky &&
python local_workflows.py --model qwen3.5:9b --engine graph --scenario flaky &&
python local_workflows.py --model qwen3.5:9b --engine graph --scenario empty &&
python local_workflows.py --model qwen3.5:9b --engine graph --scenario timeout
```

예상: flaky는 도구 두 번째 조회 성공 후 요약, empty는 빈 목록을 서비스 정상으로 단정하지 않는 설명, timeout은 두 번 실패 후 모델 요약 없이 종료한다. 도구를 호출하지 않거나 service가 다르면 계약 검사 실패로 기록한다. API 응답 성공과 도구 계약 성공을 구분한다. &&는 앞 명령이 실패하면 뒤 실행을 멈추지만, 출력 내용의 정확성을 자동 채점하지는 않는다.

### 4. 필요할 때 같은 프로그램에서 Gemma 비교

```bash
ollama stop qwen3.5:9b
ollama pull gemma4:e4b
ollama show gemma4:e4b
python local_workflows.py --model gemma4:e4b --probe
ollama ps
python local_workflows.py --model gemma4:e4b --engine graph --scenario flaky
```

두 모델을 GPU에 동시에 올리면 메모리 경쟁이 생길 수 있어 앞 모델을 내린다. Gemma의 초기 연결이 실패하면 같은 명령을 계속 반복하지 않고 오류 위치를 확인한다.

## 어떻게 결과를 판정할 것인가

| 항목 | 관측과 판단 기준 |
|---|---|
| 도구 계약 | get_recent_errors 함수, order-api 인자, 도구 요청 정확히 1개 |
| 근거 준수 | mock이라고 표시, 빈 결과를 정상이라고 단정하지 않음, 없는 장애 원인을 추가하지 않음 |
| 제어 흐름 | flaky 조회 2회 후 요약, timeout 조회 2회 후 종료 |
| 응답 시간 | 첫 호출의 모델 로딩 포함 시간과 적재 이후 호출을 구분 |
| GPU 활용 | ollama ps의 PROCESSOR와 실제 GPU 메모리 사용 관측. 100% GPU는 배치 위치이며 GPU 연산 사용률 100%라는 뜻이 아님 |
| 한국어 설명 | 읽기 쉬운지와 사실에 충실한지를 별도 평가 |

첫 단계는 연결과 기능 확인이다. 이를 통과한 뒤 대표 입력을 고정해 반복 비교한다. 한 번의 성공이나 문장이 자연스럽다는 이유만으로 운영용 모델 채택을 결정하지 않는다. 제조사 점수만으로 우열을 확정하지 않고 사용자 과제의 기능과 자원 조건으로 고른다.

## 별도 환경에서의 연결 코드 검증

준비 환경: Linux / Python 3.12, langchain-ollama 1.1.0, ollama Python SDK 0.6.3, langchain-core 1.6.9, langgraph 1.2.14.

실제 LangChain·Ollama SDK에 HTTPX MockTransport를 연결해 아래를 확인했다.

- chain + flaky: 마지막 도구 결과가 모델로 전달되고 총 조회 2회.
- graph + flaky: 같은 경로와 계약 확인.
- graph + timeout: 모델 요청 1회 후 도구 두 번 실패, 추가 모델 호출 없이 종료.
- 모델이 도구 요청을 반환하지 않은 경우: 실행 전 MODEL_CONTRACT_ERROR.

Qwen3.8 기본값으로 변경한 뒤 같은 SDK와 HTTP 대역으로 추가 검증했다.

- 기본 모델 probe: HTTP 1회, qwen3.8:27b / think=False / context=4096 / 출력 64 전달 확인.
- chain + flaky 및 graph + flaky: 각 모델 HTTP 2회, 도구 조회 2회, 최종 성공 결과 전달 확인.
- graph + timeout: 모델 HTTP 1회, 도구 조회 2회, 추가 요약 호출 없음.
- done_reason=length 응답: OUTPUT_LIMIT로 종료, 잘린 답변을 성공으로 처리하지 않음.
- 모든 모델 호출에 Qwen3.8 non-thinking 옵션 전달, 생성 시간·토큰 수 기반 속도 출력 확인. 가짜 응답 수치는 실제 모델 성능으로 기록하지 않음.

Qwen3.5를 기본 모델로 확정한 뒤에는 변경 범위에 맞춰 graph + flaky 한 경로를 같은 SDK와 HTTP 대역으로 확인했다. --model 생략 시 qwen3.5:9b가 선택되고, 요청·요약 두 번 모두 non-thinking 옵션과 문맥·출력 상한이 유지되며, 도구 조회는 2회였다. 실제 로컬 모델을 실행한 결과는 아니다.

위 결과는 연결 코드 검증이며 Ollama 서버나 GPU 추론 검증이 아니다. 실제 사용자 PC 관측은 아래와 구분한다.

## 사용자 PC 관측: 2026-10-09 12:33 KST 공유 결과

사용자가 붙여넣은 출력에 근거한 회고다. Python은 앞서 확인한 3.11.5 환경이며 Ollama 서버 버전·드라이버·이번 설치 후 Python 패키지 버전은 미수집이다.

### 연결과 적재

| 항목 | 첫 probe | 두 번째 probe |
|---|---:|---:|
| 호출 경과 시간 | 3.32초 | 0.16초 |
| 서버 보고 적재 시간 | 3.14초 | 0.01초 |
| 출력 생성 속도 | 77.35 tokens/s | 78.59 tokens/s |
| 입력 / 출력 토큰 | 29 / 9 | 29 / 9 |
| 종료 사유 | stop | stop |

ollama ps: qwen3.5:9b, ID=56671c2ab938, SIZE=5.6 GB, PROCESSOR=100% GPU, CONTEXT=4096, RUNNER=llamacpp.

해석: 첫 요청의 경과 시간 대부분을 적재 시간이 차지했고, 이후 짧은 요청에서는 적재 부담이 작았다. 두 번의 9토큰 출력으로 장문 처리량·동시 처리 성능·SLA를 판단하지 않는다. SIZE는 ollama ps의 모델 적재 표시값이며 GPU 전체 사용량 측정으로 취급하지 않는다.

### 실행 흐름

| 실행 | 모델 request / summarize 시간 | 도구 조회 | 관측과 판정 |
|---|---|---:|---|
| chain + flaky | request 0.72초 이후 출력 일부만 제공 | 미확인 | done_reason·도구 실행·최종 답변이 없어 완료 여부 보류. 실패로 단정하지 않음 |
| graph + flaky | 0.48 / 1.02초 | 2회 | QUERY_TIMEOUT 후 성공·요약 경로 확인. 요약 내용 보완 필요 |
| graph + empty | 0.50 / 1.11초 | 1회 | 조회 성공·요약 경로 확인. 빈 결과 설명이 근거 범위를 넘어섬 |
| graph + timeout | 0.48초 / 요약 없음 | 2회 | 두 번 실패 후 코드의 고정 문구로 종료 |

graph flaky의 모델 호출 시간 합은 1.50초, empty는 1.61초다. 프로세스 시작·그래프 구성·도구 실행을 포함한 전체 실행 시간은 아니다. timeout의 최종 문장은 모델이 생성한 답변이 아니므로 이를 모델의 판단 능력으로 평가하지 않는다.

핵심 요약 문제와 다음 검증: [모델은 도구 결과의 수치와 근거 범위를 정확하게 설명하는가?](2026-10-09-local-summary.md)

### 후속 실행: 13:32 KST 공유 결과

`--summary-style` 적용 후 chain/original/flaky, graph/explicit/flaky, graph/explicit/empty가 모두 최종 답변까지 완료됐다. 조회는 각각 2회·2회·1회였다. 실제 도구 원문에서 성공 결과의 항목 1개·count=3과 empty의 data=[]를 확인했다. initial chain 출력이 끊겼던 원인은 여전히 알 수 없다.

chain의 첫 request는 6.16초 중 적재가 5.66초였고, 뒤의 두 graph request 적재는 각각 0.01초였다. 따라서 이 숫자로 chain과 graph의 처리 속도를 비교하지 않는다. 후속 답변의 근거·수치 정확도와 표현상 문제는 위 요약 품질 기록에 정리한다.

## 공식 근거

- [Qwen3.5 9B 모델 카드](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Qwen3.8 27B 모델 카드와 non-thinking 권장값](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Qwen3.8 27B 공식 저장소 이력](https://huggingface.co/Qwen/Qwen3.8-27B/commits/main)
- [Gemma 4 모델 카드](https://ai.google.dev/gemma/docs/core/model_card_4)
- [Ollama Qwen3.5 9B 배포 정보](https://ollama.com/library/qwen3.5:9b)
- [Ollama Gemma 4 E4B 배포 정보](https://ollama.com/library/gemma4:e4b)
- [Ollama Gemma 4 12B 배포 정보](https://ollama.com/library/gemma4:12b)
- [Ollama Qwen3.8 배포 정보](https://ollama.com/library/qwen3.8)
- [Ollama Qwen3.8 27B 상세 배포 정보](https://ollama.com/library/qwen3.8:27b)
- [Ollama Windows](https://docs.ollama.com/windows)
- [Ollama FAQ: GPU 적재·문맥·keep_alive](https://docs.ollama.com/faq)
- [LangChain ChatOllama](https://docs.langchain.com/oss/python/integrations/chat/ollama)
- [Gemini 3.1 Flash-Lite 평가 방법](https://deepmind.google/models/evals-methodology/gemini-3-1-flash-lite)

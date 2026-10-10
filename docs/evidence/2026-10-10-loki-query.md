# Loki에서 확인한 요청 로그를 Python 도구로 가져오기

원칙: [왜 → 선택 근거 → 검증 방법](../learning-principles.md).

- 실행일 / 기록일: 2026-10-10, Asia/Seoul.
- 상태: 실제 curl 경로와 Python 도구의 PC 일반/오류 조건 조회 확인. 에이전트 통합은 미구현.
- 코드: [loki_query.py](../../examples/2026-10-10/loki_query.py), [실행 방법](../../examples/2026-10-10/README.md). 이번 변경은 검토 전 미커밋.
- 증거 출처: 사용자가 공유한 Windows Git Bash 출력 `붙여넣은 텍스트(1).txt`, 별도 Linux Python 3.12.14 환경의 HTTP 대역 테스트, 13:02 KST에 공유한 Python 실제 조회 출력.
- 작성 시점: curl 결과는 실행 후 회고. Python 비교의 예상·판단 기준은 사용자 PC 실행 전에 작성한 안내자의 제안이다.

## 1. 왜 이 실험을 하는가

지금까지 get_recent_errors는 mock 값을 반환했다. 실제 서비스와 연결하려면 먼저 특정 요청의 로그가 생성되고 Loki를 통해 조회되는지 확인해야 한다. 그 다음 같은 조건의 HTTP 요청을 Python 함수로 옮긴다.

핵심 질문: **이미 curl로 확인한 요청 로그를 Python으로도 원문·대상·시간 범위를 유지해 가져오고, 빈 결과와 조회 실패를 구분할 수 있는가?**

이 구분 없이 바로 모델에 연결하면, 조회 실패나 필터 불일치를 모델의 분석 실패로 오인할 수 있다.

## 2. 그래서 왜 이 방법인가

| 선택 | 이점 | 비용·한계 / 선택을 바꿀 조건 |
|---|---|---|
| 기존 컨테이너 start | 기존 설정·데이터·실행 조건을 유지하며 재개 | 컨테이너가 있어야 함. 이미지나 설정 변경이 필요하면 별도로 재생성 검토 |
| 요청 ID로 단일 요청 대조 | 컨테이너와 Loki에서 같은 사건을 식별 | 서비스 전체 수집의 완전성은 확인하지 못함 |
| curl 성공 조건을 독립 Python 함수로 구현 — 이번 선택 | 조회·응답 계약의 문제를 모델 설명과 분리, 표준 라이브러리만 사용 | 이번 구현은 로컬 고정 주소·단일 HTTP 요청. 원격 인증·비동기·연결 재사용 요구 시 확장 |
| 즉시 LangGraph 노드 교체 | 사용자 요청부터 답변까지 빠르게 연결 | 조회 형식·시간·모델 설명 문제가 동시에 섞임. 단독 조회 대조 후 진행 |
| 고정 시간으로 재조회 — 이번 대조 | 실행 시각이 달라도 같은 범위 비교 | 최신 조사에는 호출 시각 기준 상대 범위 사용, 보존 기간과 수집 지연은 따로 고려 |

이번 조회 함수는 GET 1회만 보낸다. 기존 재시도 실습의 정책을 그대로 붙이기 전에 실제 실패 코드와 결과 계약을 먼저 확인한다. 서비스·범위·반환 수 제한은 코드가 정한다. 이 단계에는 모델 판단이 없다.

## 3. 어떻게 확인할 것인가

| 대상 | 기준 / 예상 | 실제 관측 | 판정 |
|---|---|---|---|
| 컨테이너 재개 | 필요한 5개 컨테이너 실행 | alloy/loki/tempo Up, order-api/payment Up (healthy) | 실행 확인 |
| 최초 Loki /ready | 준비 상태를 응답으로 확인 | 503, Ingester not ready: waiting for 15s after being ready | 당시 준비 대기 |
| 로컬 주문 요청 | 응답과 요청 ID 로그 대조 | HTTP 201, confirmed. order-api 201 / payment 200 로그 | 해당 요청 확인 |
| Loki 조회 | 같은 request_id 로그 반환 | status=success, streams 1개, values 1줄 | 실제 curl 경로 확인 |
| Python 일반 조회 | 같은 로그 1줄, 원문·요청 ID 보존 | 사용자 PC status=ok, returned_count=1, 같은 timestamp_ns와 request_id | 실제 조회 확인 |
| Python 오류 조건 추가 | 이번 info 로그는 제외되어 빈 결과 예상 | 사용자 PC status=ok, data=[], returned_count=0 | 실제 필터 결과 확인 |
| Python 접속/HTTP/형식 실패 | data=null, 오류 코드, 반환 수 미확인 | HTTP 대역 검사 통과 | 해당 입력 조건에서 확인 |

## 4. 실행과 근거

사용자 PC: Windows Git Bash. Python 3.11.5는 이전 출력 기준이며 이번 첨부에는 버전 재출력이 없다. Loki 3.7.8, Alloy v1.19.2, Tempo 3.0.3은 이번 ps 출력에 표시됐다. observability-lab 브랜치는 lab/008-integrated-incident다.

기존 scripts/mimir-compose.sh로 loki·tempo·alloy·payment·order-api를 start했다. observability-lab의 미추적 k6 관련 6개 파일은 이번 작업에서 수정하지 않았다.

관측된 주문은 로컬 실습 앱의 모의 주문·결제 처리다. 실행 중인 앱의 실제 로그지만 운영 고객 거래나 실제 금전 결제는 아니다.

```text
request_id: agent-loki-20261010T034854Z-7943
application timestamp: 2026-10-10T03:48:55.339+00:00 (12:48:55.339 KST)
Loki timestamp_ns: 1791604135340155505
order-api: POST /orders, status_code=201, duration_ms=89.362, level=info
payment: POST /payments, status_code=200, duration_ms=81.16, level=info
trace_id: cb1846dfcad3087952612215f37f1e44
```

실제 성공한 Loki 요청:

```bash
curl -fsS --max-time 10 -G http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="order-api"} |= "agent-loki-20261010T034854Z-7943"' \
  --data-urlencode 'since=10m' --data-urlencode 'limit=20' \
  --data-urlencode 'direction=backward'
```

당시 반환 라벨은 detected_level=info, environment=lab, job=order-lab-logs, service_name=order-api다. [Loki 원본 응답](../../examples/2026-10-10/fixtures/loki-request-success.json)을 테스트 입력으로 보관한다. 첨부에서 JSON을 추출해 들여쓰기만 바꿨다.

- 반환 로그 줄 수: 1. stats.summary.totalEntriesReturned도 1이다.
- stats.summary.totalLinesProcessed=2는 조회 처리량 통계이며 반환 2건이나 오류 2회가 아니다.
- execTime=0.006926은 Loki의 조회 실행 통계다. curl 전체 왕복 시간으로 해석하지 않는다.
- 두 서비스의 로그에 trace_id가 같다는 사실은 확인했다. Tempo에서 trace를 조회한 결과는 없다.

새 파일: examples/2026-10-10의 loki_query.py, test_loki_query.py, README.md, fixtures/loki-request-success.json. 기존 로컬 모델 실행 파일은 변경하지 않는다.

별도 환경에서 실행:

```bash
python -m unittest discover -s examples/2026-10-10 -p 'test_*.py' -v
python examples/2026-10-10/loki_query.py --help
```

Python 3.12.14에서 테스트 7개 PASS, 도움말 표시 확인. 실제 Loki·Gemini·Ollama에 요청하지 않았다. 검사 범위는 첨부 로그 보존, GET 쿼리 범위, 빈 결과, HTTP 503/timeout/접속 중단, 잘못된 응답, 반환 상한 도달 표시, 여러 스트림 정렬, 잘못된 입력의 통신 전 거부다.

### 후속 사용자 PC 실행: 13:02 KST 공유

사용자는 다운로드한 loki_query.py를 프로젝트 루트에 복사하고 도움말·일반 조회·errors-only 조회를 실행했다. 두 요청 모두 service=order-api, request_id=agent-loki-20261010T034854Z-7943, start=03:48:00Z, end=03:50:00Z, limit=20으로 고정했다.

| 관측 | 일반 조회 | errors-only 조회 |
|---|---|---|
| queried_at (UTC) | 2026-10-10T04:02:05.800848Z | 2026-10-10T04:02:06.067226Z |
| status / error | ok / null | ok / null |
| returned_count / limit_reached | 1 / false | 0 / false |
| data | 기존 info 로그 1줄, status_code=201 | [] |
| elapsed_seconds | 0.0076 | 0.0056 |

일반 조회의 timestamp_ns=1791604135340155505와 원문 request_id·trace_id는 앞선 curl 결과와 일치했다. message 원문과 fields를 함께 보존했다. elapsed_seconds는 해당 Python 함수가 측정한 조회 구간이며 모델 추론 시간이나 전체 CLI 실행 시간은 아니다. 단발 결과로 속도 차이를 평가하지 않는다.

이로써 Python의 실제 조회와 성공한 빈 결과를 확인했다. 실제 error 로그를 반환받은 것은 아니며, 실서버 timeout·503·접속 실패 경로는 아직 HTTP 대역 검사 범위다.

## 5. 결과가 의미하는 것

해당 요청에 대해서 **앱 로그 생성 → Loki 수집 → HTTP 조회**가 연결됐다. 이를 바탕으로 실제 데이터 조회 함수를 만들 수 있다.

처음 /ready의 503은 그 응답 시점의 준비 대기를 뜻한다. 나중에 로그 조회가 성공했지만 /ready=200을 다시 관측한 것은 아니다. Compose start --wait는 running 또는 healthy 상태를 기다리며, 실제 애플리케이션 readiness는 별도 응답으로 확인한다.

후속 Python 실행에서도 같은 로그가 보존되고 오류 조건의 빈 결과가 성공으로 구분됐다. 아직 주장할 수 없는 범위: 실제 오류 로그 수집, 모든 로그의 완전성·무지연성, 저장 장치 영속화·재시작 복구, Tempo 조회, 모델의 실제 로그 해석, 에이전트 통합.

기존 mock의 한 항목은 count=3인 집계였지만 이번 Loki 한 항목은 원본 로그 한 줄이다. 반환 줄 수를 전체 오류 발생 횟수로 바꾸지 않는다. 기존 보고서가 모든 항목을 오류로 부르므로 info 로그를 그대로 연결하지 않는다.

## 6. 남은 질문과 다음 행동

| 남은 질문 | 다음 행동 | 이유 |
|---|---|---|
| Python도 같은 요청을 찾는가? | 13:02 KST 공유 출력으로 확인 완료 | 일반 조회 1줄과 오류 조건의 성공한 빈 결과 대조 |
| 실제 error 경로도 수집되는가? | 정상 경로 확인 후 통제된 장애와 복구 조건 설계 | info 수집 성공만으로 장애 경로를 검증할 수 없음 |
| 사실 출력과 도구를 어떻게 연결하는가? | 조회 계약·시간·출처·로그 줄 수를 보고서에 반영한 뒤 실행 노드 연결 | mock 집계와 실제 원본 로그의 의미 차이를 보존 |
| 최신이 어느 시점까지인가? | 호출 시각·조회 범위·최신 로그 시각·수집 지연을 구분 | 빈 결과가 곧 정상이라는 오판 방지 |

## 참고 문서

- [Loki HTTP API](https://grafana.com/docs/loki/latest/reference/loki-http-api/): query_range, 시간 범위, streams, 조회 통계, /ready.
- [LogQL 로그 질의](https://grafana.com/docs/loki/latest/query/log_queries/): 문자열 필터, JSON 파서, __error__ 필터.
- [docker compose start](https://docs.docker.com/reference/cli/docker/compose/start/): 기존 컨테이너 시작, --wait의 running/healthy 의미.

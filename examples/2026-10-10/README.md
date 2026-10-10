# curl로 확인한 Loki 로그를 Python에서도 가져올 수 있는가?

이 예제는 실제 로컬 Loki에 GET 요청을 보내는 독립 실행 파일이다. 모델 호출은 없다. [관측 근거와 선택 이유](../../docs/evidence/2026-10-10-loki-query.md)를 먼저 참고한다.

## 왜 따로 실행하는가

기존 mock은 정해진 값을 반환했다. 실제 도구는 시간 범위·서비스 라벨·접속 상태에 따라 결과가 달라진다. Python 조회 결과를 먼저 curl과 대조하면, 이후 에이전트의 답변에 문제가 생겼을 때 조회와 설명 중 어디를 확인해야 하는지 알 수 있다.

`loki_query.py`는 새 파일이다. 기존 `tools_mock.py`나 `local_workflows.py`를 덮어쓰지 않는다. Python 3.11 이상 표준 라이브러리만 사용하므로 추가 패키지 설치는 필요 없다.

## 실행 전제와 위치

- 사용자 Windows PC에서 Loki가 `http://127.0.0.1:3100`으로 접근 가능해야 한다.
- 현재 확인된 실습 환경은 Loki 3.7.8이며, 조회 라벨은 `service_name`, 대상은 `order-api`와 `payment`이다.
- 다른 서버·컨테이너에서 실행하면 `127.0.0.1`이 가리키는 대상이 바뀐다. 그런 배치에는 주소·네트워크·인증 설계를 먼저 변경한다.
- 다운로드 파일은 `C:\Users\PC\Desktop\git-devops\ai-agent-lab\loki_query.py`로 새로 저장한다. 아래 명령은 이 위치 기준이다.
- 저장소 경로에서 직접 실행할 때는 `python examples/2026-10-10/loki_query.py ...`로 실행한다. 두 위치를 혼용하지 않는다.

## 같은 로그를 두 조건으로 비교

사용자가 이미 확인한 요청은 2026-10-10 12:48:55 KST에 기록됐다. 최근 10분 대신 **고정된 시간 범위**를 사용해, 실행이 늦어져도 범위에서 빠지는 일을 피한다. 로그 보존 기간이 지나거나 데이터가 사라지면 같은 범위라도 반환되지 않을 수 있다.

```bash
cd ~/Desktop/git-devops/ai-agent-lab || exit
source .venv/Scripts/activate

python loki_query.py --help

python loki_query.py --service order-api \
  --start 2026-10-10T03:48:00Z --end 2026-10-10T03:50:00Z \
  --request-id agent-loki-20261010T034854Z-7943 --limit 20

python loki_query.py --service order-api \
  --start 2026-10-10T03:48:00Z --end 2026-10-10T03:50:00Z \
  --request-id agent-loki-20261010T034854Z-7943 --limit 20 --errors-only
```

| 조건 | 실행 전 예상 | 확인할 값 |
|---|---|---|
| 요청 ID로 조회 | 기존 info 로그 1줄 반환 | status=ok, returned_count=1, fields.status_code=201 |
| 같은 조건 + errors-only | 알려진 info 로그 제외, 반환 없음 | status=ok, data=[], returned_count=0 |
| 접속·HTTP·응답 형식 실패 | 로그 유무 판단 불가 | status=error, data=null, returned_count=null, error.code |

오류 전용 조회는 `| json | __error__="" | level="error"` 조건을 추가한다. 현재 앱의 JSON 로그에서 level이 소문자 error인 줄만 대상이며, warn·비JSON·JSON 파싱 실패 로그는 포함하지 않는다. 일반적인 모든 서비스에 적용할 오류 탐지 기준은 아니다.

요청 ID는 앞선 curl과 동일하게 원문에 포함되는지 검사한다. JSON의 request_id 필드와 정확히 일치하는지 검사하는 방식은 아니다. 정확한 필드 일치가 필요하면 조회 계약과 LogQL을 함께 변경한다.

현재 시점의 최근 로그를 보려면 다음처럼 실행한다. 범위 끝은 호출 시각으로 고정하고, 해당 시점까지 Loki에서 조회 가능한 로그를 가져온다. 지속 스트리밍이나 수집 지연 없는 실시간성을 보장하지 않는다.

```bash
python loki_query.py --service order-api --minutes 10 --limit 20
```

## 출력과 제한의 의미

- `source=loki`: 실시간 조회 응답의 출처. `fields`에는 원문 JSON을 해석한 값, `message`에는 변경하지 않은 로그 원문을 담는다.
- `timestamp_ns`: Loki가 반환한 시각. 원문 내부 timestamp와 별도로 보존한다.
- `returned_count`: 반환된 **로그 줄 수**. 전체 발생 횟수나 고유 오류 수가 아니다. mock의 집계 필드 count를 임의로 만들지 않는다.
- `limit_reached`: 반환 줄 수가 요청 상한과 같은지 나타낸다. true이면 더 있는지 확인이 필요하지만, 잘린 로그가 반드시 있다는 뜻은 아니다.
- `query`: 실제 전송한 LogQL·시작/끝 시각·상한·필터와 조회 시각을 남긴다. 시작 시각은 포함하고 끝 시각은 제외한다.
- 성공한 빈 결과도 서비스 정상 판정이 아니다. 필터·시간 범위·수집 상태를 함께 봐야 한다.
- 이번 구현은 최대 1시간·1000줄·응답 2MiB로 제한한다. 학습용 클라이언트의 제한이며 Loki 자체의 최대치가 아니다.
- HTTP 요청은 1회다. I/O timeout은 기본 10초이며 전체 실행 기한은 아니다. HTTP 503·접속 실패·timeout·응답 형식 오류를 구분한다.
- 기존 보고서는 항목을 모두 오류로 부른다. 일반 info 로그를 이 보고서에 그대로 연결하지 않는다. 후속 local_workflows.py의 Loki 전용 사실 출력에 연결했다. [통합 기록](../../docs/evidence/2026-10-10-loki-graph.md)을 참고한다.

## 개발 환경의 검증

```bash
python -m unittest discover -s examples/2026-10-10 -p 'test_*.py' -v
```

7개 테스트는 HTTP 응답을 대역으로 바꾼다. 실제 Loki나 모델에 연결하지 않는다. `fixtures/loki-request-success.json`은 사용자 PC가 반환한 Loki JSON 전체를 첨부 텍스트에서 추출한 것으로, 들여쓰기만 정리했다. 임의로 만든 서비스 성공 응답이 아니다. 빈 결과·실패 응답은 테스트에서 만든 입력이다.

현재 확인 범위는 사용자 PC의 **curl 조회 성공**, 별도 Python 3.12.14 환경의 **HTTP 대역 검사 통과**, 13:02 KST 공유 출력의 **Python 일반 조회 1줄과 errors-only 성공한 빈 결과**다. 이 단독 조회 기록과 별도로 후속 사용자 PC 실행에서 LangGraph 일반 조회 통합을 확인했다. 실제 error 로그 반환과 실서버 실패 경로는 미확인이다.

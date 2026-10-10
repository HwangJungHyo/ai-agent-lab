"""로컬 Loki를 한 번 조회한다. 모델 호출·재시도·컨테이너 변경은 수행하지 않는다."""
import argparse
import json
import re
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


ENDPOINT = "http://127.0.0.1:3100/loki/api/v1/query_range"
SERVICES = ("order-api", "payment")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ResponseFormatError(ValueError):
    """조회 성공으로 사용할 수 없는 Loki 응답."""


def utc_time(value):
    """시간대가 명시된 ISO 시각을 UTC로 정규화한다."""
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("시각은 2026-10-10T03:48:00Z 같은 ISO 형식이어야 합니다.") from exc
    if result.tzinfo is None:
        raise ValueError("시각에는 Z 또는 +09:00 같은 시간대가 필요합니다.")
    return result.astimezone(timezone.utc)


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_query(service, request_id=None, errors_only=False):
    if service not in SERVICES:
        raise ValueError("조회 대상은 order-api 또는 payment입니다.")
    if request_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
        raise ValueError("request_id는 영문·숫자·밑줄·하이픈으로 된 1~64자여야 합니다.")
    query = '{service_name=' + json.dumps(service) + '}'
    if request_id is not None:
        # 앞서 curl로 확인한 문자열 필터와 같은 조건이다.
        query += " |= " + json.dumps(request_id)
    if errors_only:
        # 현재 실습 앱의 JSON level=error에 한정한다. 모든 로그 형식의 오류 탐지는 아니다.
        query += ' | json | __error__="" | level="error"'
    return query


def parse_streams(payload, service, limit):
    """원문을 보존하면서 streams/values를 로그 한 줄당 한 항목으로 펼친다."""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ResponseFormatError("Loki 응답의 status가 success가 아닙니다.")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "streams":
        raise ResponseFormatError("로그 목록인 streams 응답이 필요합니다.")
    streams = data.get("result")
    if not isinstance(streams, list):
        raise ResponseFormatError("data.result는 목록이어야 합니다.")
    rows = []
    for stream in streams:
        if not isinstance(stream, dict):
            raise ResponseFormatError("로그 스트림은 객체여야 합니다.")
        labels, values = stream.get("stream"), stream.get("values")
        if not isinstance(labels, dict) or labels.get("service_name") != service:
            raise ResponseFormatError("요청 서비스와 반환된 service_name이 다릅니다.")
        if not isinstance(values, list):
            raise ResponseFormatError("스트림의 values는 목록이어야 합니다.")
        for value in values:
            if (not isinstance(value, list) or len(value) != 2
                    or not isinstance(value[0], str) or not value[0].isascii()
                    or not value[0].isdigit() or not isinstance(value[1], str)):
                raise ResponseFormatError("로그 항목은 [나노초 시각 문자열, 로그 문자열]이어야 합니다.")
            timestamp_ns, raw = value
            try:
                fields = json.loads(raw)
            except json.JSONDecodeError:
                fields = None  # JSON이 아닌 로그도 버리지 않는다.
            row = {"timestamp_ns": timestamp_ns, "message": raw,
                   "labels": labels, "fields": fields if isinstance(fields, dict) else None}
            if isinstance(fields, dict) and isinstance(fields.get("level"), str) and fields["level"].strip():
                row["level"] = fields["level"]
            rows.append(row)
    if len(rows) > limit:
        raise ResponseFormatError("요청한 반환 상한을 넘는 로그 응답입니다.")
    # 스트림별로 묶인 응답을 전체 시각 내림차순으로 정렬한다. 중복 제거·발생 횟수 추정은 하지 않는다.
    return sorted(rows, key=lambda row: int(row["timestamp_ns"]), reverse=True)


def prepare_query(service, *, minutes=None, start=None, end=None, limit=20,
                  request_id=None, errors_only=False, timeout=10):
    """통신 없이 입력을 검사하고 시각을 고정한다. 재시도에도 같은 범위를 쓸 수 있다."""
    query = build_query(service, request_id, errors_only)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit은 1~1000 사이의 정수여야 합니다.")
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError("timeout은 1~60초 사이의 정수여야 합니다.")
    queried_at = datetime.now(timezone.utc)
    if start is not None or end is not None:
        if start is None or end is None or minutes is not None:
            raise ValueError("start와 end를 함께 지정하고 minutes는 생략하세요.")
        start_time, end_time = utc_time(start), utc_time(end)
    else:
        minutes = 10 if minutes is None else minutes
        if type(minutes) is not int or not 1 <= minutes <= 60:
            raise ValueError("minutes는 1~60 사이의 정수여야 합니다.")
        end_time = queried_at
        start_time = end_time - timedelta(minutes=minutes)
    if not timedelta(0) < end_time - start_time <= timedelta(hours=1):
        raise ValueError("조회 범위는 0초보다 크고 1시간 이하여야 합니다.")

    return {"endpoint": ENDPOINT, "logql": query,
            "start_inclusive": iso_utc(start_time), "end_exclusive": iso_utc(end_time),
            "queried_at": iso_utc(queried_at), "limit": limit, "direction": "backward",
            "errors_only": errors_only, "request_id": request_id}


def query_logs(service, *, minutes=None, start=None, end=None, limit=20,
               request_id=None, errors_only=False, timeout=10):
    """한 번의 GET 결과를 반환한다. 입력 오류는 예외, 조회 실패는 status=error로 구분한다."""
    query = prepare_query(service, minutes=minutes, start=start, end=end, limit=limit,
                          request_id=request_id, errors_only=errors_only, timeout=timeout)
    params = {"query": query["logql"], "start": query["start_inclusive"],
              "end": query["end_exclusive"], "limit": limit, "direction": "backward"}
    result = {
        "source": "loki", "service": service, "status": "error", "data": None, "error": None,
        "query": query,
        "returned_count": None, "limit_reached": None,
    }
    request = Request(ENDPOINT + "?" + urlencode(params), headers={"Accept": "application/json"}, method="GET")
    # 고정된 localhost 연결에서는 환경 프록시를 사용하지 않는다.
    opener = build_opener(ProxyHandler({}))
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ResponseFormatError("응답이 2MiB를 넘었습니다. limit을 줄여 다시 확인하세요.")
        payload = json.loads(raw.decode("utf-8"))
        rows = parse_streams(payload, service, limit)
        result.update(status="ok", data=rows, returned_count=len(rows), limit_reached=len(rows) == limit)
    except HTTPError as exc:
        result["error"] = {"code": "QUERY_HTTP_ERROR", "http_status": exc.code,
                           "message": f"Loki가 HTTP {exc.code}를 반환했습니다."}
        exc.close()
    except TimeoutError:
        result["error"] = {"code": "QUERY_TIMEOUT", "message": "Loki HTTP I/O 대기 제한을 초과했습니다."}
    except URLError as exc:
        code = "QUERY_TIMEOUT" if isinstance(exc.reason, TimeoutError) else "QUERY_CONNECTION_ERROR"
        result["error"] = {"code": code, "message": "Loki 접속 또는 응답 대기에 실패했습니다."}
    except (OSError, HTTPException):
        result["error"] = {"code": "QUERY_CONNECTION_ERROR", "message": "Loki 응답을 받는 중 연결이 끊기거나 통신에 실패했습니다."}
    except (json.JSONDecodeError, UnicodeDecodeError, ResponseFormatError) as exc:
        result["error"] = {"code": "QUERY_RESPONSE_ERROR", "message": str(exc)}
    result["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="로컬 Loki 단독 조회: 모델 호출 없음")
    parser.add_argument("--service", choices=SERVICES, default="order-api")
    parser.add_argument("--minutes", type=int, help="최근 조회 범위(1~60분, 기본 10분)")
    parser.add_argument("--start", help="고정 시작 시각, 예: 2026-10-10T03:48:00Z")
    parser.add_argument("--end", help="고정 종료 시각, 이 시각 자체는 제외")
    parser.add_argument("--limit", type=int, default=20, help="반환 로그 줄 수 상한, 기본 20")
    parser.add_argument("--request-id", help="로그 원문에서 찾을 요청 식별자")
    parser.add_argument("--errors-only", action="store_true", help="현재 실습 앱의 JSON level=error만 조회")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP I/O 대기 제한(초), 전체 실행 기한 아님")
    args = parser.parse_args(argv)
    try:
        result = query_logs(args.service, minutes=args.minutes, start=args.start, end=args.end,
                            limit=args.limit, request_id=args.request_id,
                            errors_only=args.errors_only, timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""대화에서 작성한 mock 조회 도구의 복원본. 실제 서버를 조회하지 않는다."""
import json


def get_recent_errors(service: str, *, scenario: str = "normal") -> dict:
    if service not in {"order-api", "payment-api"}:
        raise ValueError(f"지원하지 않는 서비스: {service}")
    if scenario not in {"normal", "empty", "timeout"}:
        raise ValueError(f"지원하지 않는 테스트 상황: {scenario}")
    result = {
        "source": "mock", "service": service,
        "status": "ok", "data": [], "error": None,
    }
    if scenario == "normal":
        result["data"] = [{
            "level": "ERROR",
            "message": "테스트용: 하위 서비스 연결 실패",
            "count": 3,
        }]
    elif scenario == "timeout":
        result["status"] = "error"
        result["data"] = None
        result["error"] = {
            "code": "QUERY_TIMEOUT",
            "message": "로그 조회가 제한 시간을 초과했습니다.",
        }
    return result


if __name__ == "__main__":
    for scenario in ("normal", "empty", "timeout"):
        print(f"\n--- scenario: {scenario} ---")
        print(json.dumps(get_recent_errors("order-api", scenario=scenario),
                         ensure_ascii=False, indent=2))

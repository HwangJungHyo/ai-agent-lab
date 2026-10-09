"""SDK 기반 도구 요청 → Python 실행 → 모델 설명. 검증된 ANY 흐름 복원본."""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from tools_mock import get_recent_errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["normal", "empty", "timeout"], default="normal")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"), override=True, encoding="utf-8-sig")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "").strip()
    if not api_key or not model:
        raise SystemExit(".env의 키와 모델 이름을 확인하세요.")
    tool = types.Tool(function_declarations=[types.FunctionDeclaration(
        name="get_recent_errors",
        description="지정한 서비스의 오류 로그를 조회하는 학습용 도구.",
        parameters={
            "type": "object",
            "properties": {"service": {"type": "string", "enum": ["order-api", "payment-api"]}},
            "required": ["service"],
        },
    )])
    rules = """장애 조사 실습을 돕는다.
source가 mock이면 가짜 데이터 기반 실습임을 밝혀라.
status는 조회 작업의 성공 여부이지 서비스의 정상 여부가 아니다.
빈 목록은 조회된 오류 로그가 없다는 의미이며 조회 실패 시 서비스 상태를 확인할 수 없다.
도구 결과에 없는 사실을 만들지 말고 확인된 사실 / 판단 한계 / 다음 확인을 한국어로 작성하라.
"""
    question = types.Content(role="user", parts=[types.Part.from_text(
        text="order-api의 오류 로그를 조회하고 결과를 설명해줘.")])

    def config(mode):
        return types.GenerateContentConfig(
            system_instruction=rules, tools=[tool], max_output_tokens=1024,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=mode)),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    with genai.Client(api_key=api_key) as client:
        print(f"[1] 모델에 도구 요청 생성 요구: scenario={args.scenario}")
        response = client.models.generate_content(model=model, contents=[question], config=config("ANY"))
        calls = response.function_calls or []
        if len(calls) != 1:
            raise RuntimeError(f"도구 요청이 정확히 1개여야 합니다: {len(calls)}개")
        call = calls[0]
        tool_args = dict(call.args or {})
        print("[2] 모델이 요청한 함수:", call.name)
        print("    모델이 생성한 인자:", tool_args)
        if call.name != "get_recent_errors" or set(tool_args) != {"service"}:
            raise ValueError("허용하지 않은 함수 또는 인자")
        if tool_args["service"] not in ("order-api", "payment-api"):
            raise ValueError("허용하지 않은 서비스")
        result = get_recent_errors(service=tool_args["service"], scenario=args.scenario)
        print("[3] Python이 실행한 도구 결과:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        tool_response = types.Content(role="tool", parts=[types.Part.from_function_response(
            name=call.name, response=result)])
        final = client.models.generate_content(
            model=model,
            contents=[question, response.candidates[0].content, tool_response],
            config=config("NONE"),
        )
        if not final.text:
            raise RuntimeError("최종 텍스트가 없습니다.")
        print("[4] 도구 결과를 받은 모델의 답변:")
        print(final.text)


if __name__ == "__main__":
    main()

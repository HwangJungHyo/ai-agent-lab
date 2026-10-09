"""Gemini SDK 첫 호출. 사용자 PC의 파일을 직접 복사한 것이 아닌 대화 복원본."""
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types


def main():
    load_dotenv(Path(__file__).with_name(".env"), override=True, encoding="utf-8-sig")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "").strip()
    if not api_key or not model:
        raise SystemExit(".env의 GEMINI_API_KEY와 GEMINI_MODEL을 확인하세요.")
    print("requested_model:", model)
    print("API 요청을 시작합니다.")
    with genai.Client(api_key=api_key) as client:
        started_at = time.perf_counter()
        response = client.models.generate_content(
            model=model,
            contents="한국어로 '모델 API 연결이 정상적으로 확인되었습니다.'라고 한 문장만 답하세요.",
            config=types.GenerateContentConfig(
                max_output_tokens=512,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        elapsed = time.perf_counter() - started_at
    print("elapsed_seconds:", round(elapsed, 3))
    print("answer:", response.text)
    if response.candidates:
        print("finish_reason:", response.candidates[0].finish_reason)
    if response.usage_metadata is not None:
        print("usage:", response.usage_metadata.model_dump(exclude_none=True))


if __name__ == "__main__":
    main()

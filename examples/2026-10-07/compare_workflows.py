"""동일 부품을 Python 순서문 또는 LangGraph로 연결하는 대화 기반 복원본."""
import argparse
import json
import os
from pathlib import Path
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from tools_mock import get_recent_errors as mock_get_recent_errors


class InvestigationState(TypedDict):
    messages: list[BaseMessage]
    result: dict
    answer: str


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["chain", "graph"], required=True)
    parser.add_argument("--scenario", choices=["normal", "empty", "timeout"], default="normal")
    parser.add_argument("--question", default="order-api의 오류 로그를 조회하고 설명해줘.")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"), override=True, encoding="utf-8-sig")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("GEMINI_MODEL", "").strip()
    if not api_key or not model_name:
        raise SystemExit(".env의 키와 모델 이름을 확인하세요.")

    @tool
    def get_recent_errors(service: Literal["order-api", "payment-api"]) -> str:
        """지정한 서비스의 오류 로그를 조회하는 학습용 mock 도구."""
        result = mock_get_recent_errors(service=service, scenario=args.scenario)
        return json.dumps(result, ensure_ascii=False)

    model = ChatGoogleGenerativeAI(
        model=model_name, api_key=api_key, vertexai=False,
        max_tokens=1024, max_retries=0,
    )
    request_model = model.bind_tools([get_recent_errors], tool_choice="any")
    answer_model = model.bind_tools([get_recent_errors], tool_choice="none")

    def request_node(state):
        print("[request] 모델 호출: 조회 요청 생성")
        response = request_model.invoke(state["messages"])
        if len(response.tool_calls) != 1:
            raise RuntimeError("이번 실습은 도구 요청 1개만 처리합니다.")
        call = response.tool_calls[0]
        if call["name"] != get_recent_errors.name or set(call["args"]) != {"service"}:
            raise ValueError("허용하지 않은 함수 또는 인자")
        print("  함수:", call["name"])
        print("  인자:", call["args"])
        return {"messages": state["messages"] + [response]}

    def execute_node(state):
        print("[execute] 도구 실행")
        call = state["messages"][-1].tool_calls[0]
        tool_message = get_recent_errors.invoke(call)
        result = json.loads(tool_message.content)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return {"messages": state["messages"] + [tool_message], "result": result}

    def choose_next(state):
        status = state["result"]["status"]
        if status == "ok":
            return "summarize"
        if status == "error":
            return "unavailable"
        raise ValueError(f"예상하지 않은 status: {status}")

    def summarize_node(state):
        print("[summarize] 모델 호출: 조회 결과 설명")
        response = answer_model.invoke(state["messages"])
        if not response.text:
            raise RuntimeError("모델의 텍스트 답변이 없습니다.")
        return {"messages": state["messages"] + [response], "answer": response.text}

    def unavailable_node(state):
        print("[unavailable] 추가 모델 호출 없이 확인 불가 안내")
        result = state["result"]
        error = result["error"]
        return {"answer": (
            "가짜 데이터(mock) 기반 실습입니다.\n"
            f"대상: {result['service']}\n"
            f"조회 실패: {error['code']} / {error['message']}\n"
            "로그를 확보하지 못해 서비스 상태를 판단할 수 없습니다."
        )}

    initial_state = {
        "messages": [
            SystemMessage(content=(
                "장애 조사 실습을 돕는다. mock 결과는 반드시 가짜 데이터라고 밝혀라. "
                "status는 조회 성공 여부이지 서비스 정상 여부가 아니다. "
                "빈 목록은 이번 조회에서 반환된 로그가 없다는 뜻이다. "
                "결과에 없는 원인이나 조회 시간 범위를 추정하지 마라. "
                "확인된 사실 / 판단 한계 / 다음 확인을 한국어로 짧게 써라."
            )),
            HumanMessage(content=args.question),
        ],
        "result": {}, "answer": "",
    }
    print(f"engine={args.engine}, scenario={args.scenario}")
    if args.engine == "chain":
        state = initial_state
        state.update(request_node(state))
        state.update(execute_node(state))
        if choose_next(state) == "summarize":
            state.update(summarize_node(state))
        else:
            state.update(unavailable_node(state))
    else:
        from langgraph.graph import END, START, StateGraph
        builder = StateGraph(InvestigationState)
        builder.add_node("request", request_node)
        builder.add_node("execute", execute_node)
        builder.add_node("summarize", summarize_node)
        builder.add_node("unavailable", unavailable_node)
        builder.add_edge(START, "request")
        builder.add_edge("request", "execute")
        builder.add_conditional_edges("execute", choose_next, {
            "summarize": "summarize", "unavailable": "unavailable",
        })
        builder.add_edge("summarize", END)
        builder.add_edge("unavailable", END)
        state = builder.compile().invoke(initial_state)
    print("\n[최종 답변]")
    print(state["answer"])


if __name__ == "__main__":
    main()

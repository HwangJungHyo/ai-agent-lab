"""도구 재시도 상한 비교. 실제 모델 503에 대한 새 정책은 아직 적용하지 않았다."""
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

MAX_ATTEMPTS = 2


class InvestigationState(TypedDict, total=False):
    messages: list[BaseMessage]
    tool_call: dict
    tool_message: BaseMessage
    result: dict
    attempts: int
    answer: str


def make_log_tool(scenario):
    @tool
    def get_recent_errors(service: Literal["order-api", "payment-api"]) -> str:
        """지정한 서비스의 오류 로그를 조회하는 학습용 mock 도구."""
        result = mock_get_recent_errors(service=service, scenario=scenario)
        return json.dumps(result, ensure_ascii=False)
    return get_recent_errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["chain", "graph"], required=True)
    parser.add_argument("--scenario", choices=["normal", "empty", "timeout", "flaky"], required=True)
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"), override=True, encoding="utf-8-sig")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("GEMINI_MODEL", "").strip()
    if not api_key or not model_name:
        raise SystemExit(".env의 키와 모델 이름을 확인하세요.")
    model = ChatGoogleGenerativeAI(
        model=model_name, api_key=api_key, vertexai=False,
        max_tokens=1024, max_retries=0,
    )
    tool_definition = make_log_tool("normal")
    request_model = model.bind_tools([tool_definition], tool_choice="any")
    answer_model = model.bind_tools([tool_definition], tool_choice="none")

    def request_node(state):
        print("[request] 모델 호출: 조회 요청 생성")
        response = request_model.invoke(state["messages"])
        if len(response.tool_calls) != 1:
            raise RuntimeError("도구 요청이 정확히 1개여야 합니다.")
        call = response.tool_calls[0]
        if call["name"] != tool_definition.name or set(call["args"]) != {"service"}:
            raise ValueError("허용하지 않은 함수 또는 인자")
        print("  함수:", call["name"])
        print("  인자:", call["args"])
        return {"messages": state["messages"] + [response], "tool_call": call}

    def execute_node(state):
        attempt = state["attempts"] + 1
        scenario = args.scenario
        if scenario == "flaky":
            scenario = "timeout" if attempt == 1 else "normal"
        executable_tool = make_log_tool(scenario)
        tool_message = executable_tool.invoke(state["tool_call"])
        result = json.loads(tool_message.content)
        print(f"[execute] 시도 {attempt}/{MAX_ATTEMPTS}, status={result['status']}")
        if result["error"]:
            print("  오류:", result["error"]["code"])
        return {"attempts": attempt, "result": result, "tool_message": tool_message}

    def choose_next(state):
        result = state["result"]
        if result["status"] == "ok":
            return "summarize"
        if result["status"] != "error":
            raise ValueError(f"예상하지 않은 status: {result['status']}")
        retryable = result["error"]["code"] == "QUERY_TIMEOUT"
        attempts_left = state["attempts"] < MAX_ATTEMPTS
        if retryable and attempts_left:
            return "execute"
        return "unavailable"

    def summarize_node(state):
        print("[summarize] 모델 호출: 최종 조회 결과 설명")
        messages = state["messages"] + [state["tool_message"]]
        response = answer_model.invoke(messages)
        if not response.text:
            raise RuntimeError("모델의 텍스트 답변이 없습니다.")
        return {"messages": messages + [response], "answer": response.text}

    def unavailable_node(state):
        print("[unavailable] 추가 모델 호출 없이 종료")
        result = state["result"]
        return {"answer": (
            "가짜 데이터(mock) 기반 실습입니다.\n"
            f"대상: {result['service']}\n"
            f"총 조회 시도: {state['attempts']}회\n"
            f"마지막 오류: {result['error']['code']}\n"
            "로그를 확보하지 못해 서비스 상태를 판단할 수 없습니다."
        )}

    initial_state = {
        "messages": [
            SystemMessage(content=(
                "장애 조사 실습을 돕는다. mock 결과는 가짜 데이터라고 밝혀라. "
                "status는 조회 성공 여부이지 서비스 정상 여부가 아니다. "
                "빈 목록은 이번 조회에서 반환된 오류 로그가 없다는 뜻이다. "
                "결과에 없는 원인이나 시점을 추정하지 마라. "
                "확인된 사실과 판단 한계를 한국어로 짧게 설명하라."
            )),
            HumanMessage(content="order-api의 오류 로그를 조회하고 설명해줘."),
        ],
        "attempts": 0, "result": {}, "answer": "",
    }
    print(f"engine={args.engine}, scenario={args.scenario}")
    if args.engine == "chain":
        state = initial_state
        state.update(request_node(state))
        while True:
            state.update(execute_node(state))
            next_step = choose_next(state)
            if next_step != "execute":
                break
        if next_step == "summarize":
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
            "execute": "execute", "summarize": "summarize", "unavailable": "unavailable",
        })
        builder.add_edge("summarize", END)
        builder.add_edge("unavailable", END)
        state = builder.compile().invoke(initial_state)
    print(f"\n[총 조회 시도] {state['attempts']}회")
    print("[최종 답변]")
    print(state["answer"])


if __name__ == "__main__":
    main()

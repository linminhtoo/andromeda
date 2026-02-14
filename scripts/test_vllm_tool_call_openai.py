#!/usr/bin/env python3
"""Standalone OpenAI-client probe for vLLM function/tool calling."""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from openai import BadRequestError, OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

ToolChoice = Literal["auto", "required", "none"]


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the tool-calling probe script."""
    parser = argparse.ArgumentParser(
        description="Test OpenAI-style tool calling against a vLLM OpenAI-compatible endpoint."
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint (defaults to OPENAI_CHAT_BASE_URL, then OPENAI_BASE_URL).",
    )
    parser.add_argument(
        "--api-key", default=None, help="API key (defaults to OPENAI_API_KEY; test is common for local vLLM)."
    )
    parser.add_argument("--model", default=None, help="Chat model name (defaults to OPENAI_CHAT_MODEL).")
    parser.add_argument(
        "--prompt",
        default="What is the latest price for NVDA? Use the available tool before answering.",
        help="Prompt used to trigger tool calling.",
    )
    parser.add_argument(
        "--tool-choice",
        choices=["auto", "required", "none"],
        default="auto",
        help="Tool choice mode sent to the OpenAI API.",
    )
    parser.add_argument("--max-tokens", type=int, default=256, help="Max completion tokens per model call.")
    return parser


def resolve_base_url(explicit_base_url: str | None) -> str:
    """Resolve the OpenAI-compatible base URL from CLI arguments or environment variables."""
    if explicit_base_url:
        return explicit_base_url

    chat_base_url = os.getenv("OPENAI_CHAT_BASE_URL")
    if chat_base_url:
        return chat_base_url

    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return base_url

    raise RuntimeError("Missing base URL. Set --base-url or OPENAI_CHAT_BASE_URL / OPENAI_BASE_URL.")


def resolve_api_key(explicit_api_key: str | None) -> str:
    """Resolve the API key from CLI arguments or environment variables."""
    if explicit_api_key:
        return explicit_api_key

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key

    raise RuntimeError("Missing API key. Set --api-key or OPENAI_API_KEY.")


def resolve_model(explicit_model: str | None) -> str:
    """Resolve the chat model name from CLI arguments or environment variables."""
    if explicit_model:
        return explicit_model

    model = os.getenv("OPENAI_CHAT_MODEL")
    if model:
        return model

    raise RuntimeError("Missing model. Set --model or OPENAI_CHAT_MODEL.")


def build_tools() -> list[ChatCompletionToolParam]:
    """Build the function/tool schema sent to the model."""
    tools_payload: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "lookup_quote",
                "description": "Look up a mock stock quote for a ticker symbol.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "US stock ticker symbol, for example NVDA or GOOGL.",
                        }
                    },
                    "required": ["ticker"],
                },
            },
        }
    ]
    return cast(list[ChatCompletionToolParam], tools_payload)


def parse_tool_arguments(arguments_json: str) -> dict[str, Any]:
    """Parse the model-provided tool argument JSON into a dictionary."""
    try:
        parsed = json.loads(arguments_json)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Tool arguments are not valid JSON: {arguments_json}") from error

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Tool arguments must be an object. Received: {parsed}")

    return cast(dict[str, Any], parsed)


def lookup_quote(ticker: str) -> str:
    """Return a deterministic mock quote payload for a ticker symbol."""
    normalized_ticker = ticker.upper().strip()
    quotes = {
        "NVDA": {"ticker": "NVDA", "price": 130.21, "currency": "USD", "source": "mock_quote_feed"},
        "GOOGL": {"ticker": "GOOGL", "price": 188.44, "currency": "USD", "source": "mock_quote_feed"},
        "AAPL": {"ticker": "AAPL", "price": 231.03, "currency": "USD", "source": "mock_quote_feed"},
    }

    if normalized_ticker in quotes:
        return json.dumps(quotes[normalized_ticker])

    unknown_quote = {
        "ticker": normalized_ticker,
        "price": 0.0,
        "currency": "USD",
        "source": "mock_quote_feed",
        "note": "Ticker not found in probe script mock data.",
    }
    return json.dumps(unknown_quote)


def dispatch_tool_call(tool_name: str, tool_arguments: dict[str, Any]) -> str:
    """Dispatch the named tool call and return serialized tool output."""
    if tool_name != "lookup_quote":
        raise RuntimeError(f"Unsupported tool call: {tool_name}")

    if "ticker" not in tool_arguments:
        raise RuntimeError("Tool arguments missing required field: ticker")

    ticker_value = tool_arguments["ticker"]
    if not isinstance(ticker_value, str):
        raise RuntimeError("Tool argument ticker must be a string")

    return lookup_quote(ticker_value)


def run_tool_call_probe(client: OpenAI, model: str, prompt: str, tool_choice: ToolChoice, max_tokens: int) -> int:
    """Run a tool-calling roundtrip and return a process-style status code."""
    tools = build_tools()
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": "You are a test assistant. Use the lookup_quote function when relevant."},
        {"role": "user", "content": prompt},
    ]

    try:
        first_response = client.chat.completions.create(
            model=model, messages=messages, tools=tools, tool_choice=tool_choice, temperature=0, max_tokens=max_tokens
        )
    except BadRequestError as error:
        print("RESULT: FAIL (request rejected by server)")
        print(f"server_error: {error}")
        print("vLLM hint: add --enable-auto-tool-choice and --tool-call-parser <parser_name> to vllm serve.")
        return 2
    first_message = first_response.choices[0].message

    print("=== First assistant response ===")
    print(f"content: {first_message.content}")

    tool_calls = first_message.tool_calls
    if not tool_calls:
        print("tool_calls: NONE")
        print("RESULT: FAIL (model did not emit tool_calls)")
        return 1

    print(f"tool_calls: {len(tool_calls)}")

    assistant_message = cast(ChatCompletionMessageParam, first_message.model_dump(exclude_none=True))
    messages.append(assistant_message)

    for tool_call in tool_calls:
        if tool_call.type != "function":
            raise RuntimeError(f"Unsupported non-function tool call type: {tool_call.type}")

        tool_name = tool_call.function.name
        tool_arguments = parse_tool_arguments(tool_call.function.arguments)
        tool_result = dispatch_tool_call(tool_name, tool_arguments)

        print("--- Executed tool call ---")
        print(f"tool_name: {tool_name}")
        print(f"tool_arguments: {tool_arguments}")
        print(f"tool_result: {tool_result}")

        tool_message = cast(
            ChatCompletionMessageParam, {"role": "tool", "tool_call_id": tool_call.id, "content": tool_result}
        )
        messages.append(tool_message)

    second_response = client.chat.completions.create(
        model=model, messages=messages, temperature=0, max_tokens=max_tokens
    )
    final_message = second_response.choices[0].message

    print("=== Final assistant response ===")
    print(f"content: {final_message.content}")
    print("RESULT: PASS (tool call roundtrip completed)")
    return 0


def main() -> None:
    """Load configuration, initialize the client, and run the probe."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    args = build_argument_parser().parse_args()
    base_url = resolve_base_url(args.base_url)
    api_key = resolve_api_key(args.api_key)
    model = resolve_model(args.model)

    print("=== Probe configuration ===")
    print(f"base_url: {base_url}")
    print(f"model: {model}")
    print(f"tool_choice: {args.tool_choice}")

    client = OpenAI(api_key=api_key, base_url=base_url)
    tool_choice = cast(ToolChoice, args.tool_choice)
    exit_code = run_tool_call_probe(
        client=client, model=model, prompt=args.prompt, tool_choice=tool_choice, max_tokens=args.max_tokens
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

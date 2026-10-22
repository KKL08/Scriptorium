from violet_refine.llm import FakeLLMClient


def test_fake_client_returns_queued_responses_and_records_calls():
    client = FakeLLMClient(["first", "second"])
    messages = [{"role": "user", "content": "hi"}]
    assert client.complete(messages, provider="anthropic", model="anthropic/claude-fable-5") == "first"
    assert client.complete(messages, provider="anthropic", model="anthropic/claude-fable-5") == "second"
    assert len(client.calls) == 2
    assert client.calls[0]["model"] == "anthropic/claude-fable-5"
    assert client.calls[0]["provider"] == "anthropic"


def test_fake_client_records_thinking_and_reasoning_effort():
    client = FakeLLMClient(["ok"])
    client.complete(
        [{"role": "user", "content": "hi"}],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
        thinking={"type": "enabled"},
        reasoning_effort="max",
    )
    assert client.calls[0]["thinking"] == {"type": "enabled"}
    assert client.calls[0]["reasoning_effort"] == "max"

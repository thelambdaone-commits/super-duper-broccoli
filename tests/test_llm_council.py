import asyncio

from utils.llm_council import LLMCouncil, _redact_secret_like_text


class FakeChatClient:
    def __init__(self):
        self.calls = []

    async def complete(self, model, messages, temperature, max_tokens):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if "chairman" in model:
            return "final synthesis"
        return f"response from {model}"


def _config():
    return {
        "provider": {"name": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
        "council_models": ["model/a", "model/b"],
        "chairman_model": "model/chairman",
        "max_models_per_query": 2,
        "temperature": 0.1,
        "max_tokens": 64,
        "stage_prompts": {
            "opinion": "opinion prompt",
            "review": "review prompt",
            "chairman": "chairman prompt",
        },
        "safety": {"never_send": ["secrets"]},
    }


def test_llm_council_build_plan_redacts_secret_like_text():
    council = LLMCouncil(config=_config(), chat_client=FakeChatClient())

    plan = council.build_plan("check sk-or-secretvalue now")

    assert plan["council_models"] == ["model/a", "model/b"]
    assert plan["chairman_model"] == "model/chairman"
    assert "sk-or-[REDACTED]" in plan["question_preview"]
    assert "secretvalue" not in plan["question_preview"]


def test_llm_council_runs_opinion_review_and_chairman_stages():
    fake = FakeChatClient()
    council = LLMCouncil(config=_config(), chat_client=fake)

    result = asyncio.run(council.ask("Should we ship?"))

    assert result.final_answer == "final synthesis"
    assert result.chairman_model == "model/chairman"
    assert [op.model for op in result.opinions] == ["model/a", "model/b"]
    assert [review.reviewer_model for review in result.reviews] == ["model/a", "model/b"]
    assert len(fake.calls) == 5
    assert fake.calls[-1]["model"] == "model/chairman"
    assert "Candidate" in fake.calls[-1]["messages"][1]["content"]
    assert "Cross-reviews" in fake.calls[-1]["messages"][1]["content"]


def test_redact_secret_like_text_handles_multiple_markers():
    text = _redact_secret_like_text("a sk-test b gsk_abc c hf_token")

    assert text == "a sk-[REDACTED] b gsk_[REDACTED] c hf_[REDACTED]"

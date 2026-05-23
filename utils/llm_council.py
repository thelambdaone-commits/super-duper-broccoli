import asyncio
import json
import logging
import os
import random
import re
import string
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Protocol

from openai import AsyncOpenAI

from utils.vault_handler import VaultHandler

logger = logging.getLogger("LLMCouncil")


CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
LLM_COUNCIL_CONFIG_PATH = os.path.join(CONFIG_DIR, "llm_council.json")


class ChatClient(Protocol):
    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        ...


@dataclass(frozen=True)
class CouncilOpinion:
    model: str
    label: str
    content: str


@dataclass(frozen=True)
class CouncilReview:
    reviewer_model: str
    content: str


@dataclass(frozen=True)
class CouncilResult:
    question: str
    opinions: list[CouncilOpinion]
    reviews: list[CouncilReview]
    final_answer: str
    chairman_model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "opinions": [asdict(opinion) for opinion in self.opinions],
            "reviews": [asdict(review) for review in self.reviews],
            "final_answer": self.final_answer,
            "chairman_model": self.chairman_model,
        }


@lru_cache(maxsize=1)
def load_llm_council_config(path: str = LLM_COUNCIL_CONFIG_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _redact_secret_like_text(text: str) -> str:
    pattern = re.compile(r"(sk-or-|sk_or_|sk-|xoxb-|ghp_|gsk_|hf_)[^\s'\"`]+")
    return pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)


def resolve_openrouter_api_key(config: dict[str, Any] | None = None) -> str:
    cfg = config or load_llm_council_config()
    provider = cfg.get("provider", {})
    env_name = provider.get("api_key_env", "OPENROUTER_API_KEY")
    if api_key := os.getenv(env_name):
        return api_key

    try:
        secrets = VaultHandler().fetch_quantum_secrets()
    except Exception:
        return ""
    return secrets.get(provider.get("api_key_vault_key", env_name), "")


class OpenRouterChatClient:
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required for live LLM Council execution")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Record cost and usage
        try:
            from monitoring.llm_cost_tracker import cost_tracker
            usage = getattr(response, 'usage', None)
            if usage:
                cost_tracker.record_usage(
                    task_id=kwargs.get("signal_id", "council_query"),
                    model=model,
                    input_tokens=getattr(usage, 'prompt_tokens', 0),
                    output_tokens=getattr(usage, 'completion_tokens', 0),
                    provider="openrouter"
                )
        except Exception as e:
            logger.debug(f"Cost tracking failed: {e}")

        content = response.choices[0].message.content
        return content or ""


class LLMCouncil:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        chat_client: ChatClient | None = None,
    ) -> None:
        self.config = config or load_llm_council_config()
        self.chat_client = chat_client

    def _models(self, max_models: int | None = None) -> list[str]:
        configured = list(self.config.get("council_models", []))
        limit = max_models or int(self.config.get("max_models_per_query", len(configured)))
        return configured[: max(1, limit)]

    def build_plan(self, question: str, max_models: int | None = None) -> dict[str, Any]:
        models = self._models(max_models)
        return {
            "source": self.config.get("source"),
            "provider": self.config.get("provider", {}).get("name", "openrouter"),
            "question_preview": _redact_secret_like_text(question)[:500],
            "council_models": models,
            "chairman_model": self.config.get("chairman_model"),
            "stages": [
                "Stage 1: independent first opinions from each council model.",
                "Stage 2: anonymized cross-review and ranking.",
                "Stage 3: chairman synthesis with dissent and uncertainty preserved.",
            ],
            "safety": self.config.get("safety", {}),
            "requires_api_key": self.config.get("provider", {}).get("api_key_env", "OPENROUTER_API_KEY"),
        }

    async def ask(self, question: str, max_models: int | None = None) -> CouncilResult:
        client = self.chat_client or OpenRouterChatClient(
            api_key=resolve_openrouter_api_key(self.config),
            base_url=self.config.get("provider", {}).get("base_url", "https://openrouter.ai/api/v1"),
        )
        question = _redact_secret_like_text(question)
        models = self._models(max_models)
        prompts = self.config.get("stage_prompts", {})
        temperature = float(self.config.get("temperature", 0.2))
        max_tokens = int(self.config.get("max_tokens", 1600))

        opinion_tasks = [
            client.complete(
                model=model,
                messages=[
                    {"role": "system", "content": prompts.get("opinion", "")},
                    {"role": "user", "content": question},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            for model in models
        ]
        raw_opinions = await asyncio.gather(*opinion_tasks)
        labels = list(string.ascii_uppercase[: len(models)])
        random.Random(question).shuffle(labels)
        opinions = [
            CouncilOpinion(model=model, label=label, content=content)
            for model, label, content in zip(models, labels, raw_opinions)
        ]

        anonymized = "\n\n".join(
            f"Candidate {opinion.label}:\n{opinion.content}" for opinion in opinions
        )
        review_prompt = (
            f"Question:\n{question}\n\n"
            f"Anonymized candidate answers:\n{anonymized}"
        )
        review_tasks = [
            client.complete(
                model=model,
                messages=[
                    {"role": "system", "content": prompts.get("review", "")},
                    {"role": "user", "content": review_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            for model in models
        ]
        raw_reviews = await asyncio.gather(*review_tasks)
        reviews = [
            CouncilReview(reviewer_model=model, content=content)
            for model, content in zip(models, raw_reviews)
        ]

        synthesis_prompt = (
            f"Question:\n{question}\n\n"
            f"Council opinions:\n{anonymized}\n\n"
            "Cross-reviews:\n"
            + "\n\n".join(
                f"Review by council member {idx + 1}:\n{review.content}"
                for idx, review in enumerate(reviews)
            )
        )
        chairman_model = self.config.get("chairman_model") or models[0]
        final_answer = await client.complete(
            model=chairman_model,
            messages=[
                {"role": "system", "content": prompts.get("chairman", "")},
                {"role": "user", "content": synthesis_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return CouncilResult(
            question=question,
            opinions=opinions,
            reviews=reviews,
            final_answer=final_answer,
            chairman_model=chairman_model,
        )


def ask_llm_council_sync(question: str, max_models: int | None = None) -> dict[str, Any]:
    return asyncio.run(LLMCouncil().ask(question, max_models=max_models)).to_dict()

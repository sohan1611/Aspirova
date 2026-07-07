"""Single provider seam for generation and embeddings (Doc 05, Doc 08).

Blank provider keys select deterministic local stubs. Provider SDKs are
imported only inside their keyed call paths, so the zero-cost path has no
SDK dependency and cannot make a network request.
"""

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.models import AiUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    input_tokens: int
    output_tokens: int


def _estimated_tokens(text: str) -> int:
    """Cheap deterministic approximation for stub accounting only."""
    return (len(text) + 3) // 4


def _generation_cost(settings: Settings, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * settings.ai_generation_input_usd_per_mtok
        + output_tokens / 1_000_000 * settings.ai_generation_output_usd_per_mtok
    )


def _embedding_cost(settings: Settings, input_tokens: int) -> float:
    return input_tokens / 1_000_000 * settings.ai_embedding_input_usd_per_mtok


def _generation_input(
    prompt: str | None, system: str | None, messages: list[dict[str, str]] | None
) -> str:
    return json.dumps(
        {"messages": messages or [], "prompt": prompt or "", "system": system or ""},
        sort_keys=True,
        separators=(",", ":"),
    )


def _record_usage(
    session: Session,
    *,
    feature: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    est_cost: float,
    ok: bool,
) -> None:
    """Commit one usage row without letting observability break an AI caller."""
    try:
        # Use a dedicated Session so usage accounting never commits or
        # rolls back unrelated domain changes held by the caller.
        with Session(bind=session.get_bind()) as usage_session:
            usage_session.add(
                AiUsage(
                    feature=feature,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    est_cost=est_cost,
                    ok=ok,
                )
            )
            usage_session.commit()
    except Exception:
        logger.exception("Failed to record AI usage", extra={"feature": feature, "model": model})


def generate(
    session: Session,
    *,
    feature: str,
    prompt: str | None = None,
    system: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> GenerationResult:
    """Generate text through the configured provider or deterministic stub."""
    settings = get_settings()
    serialized_input = _generation_input(prompt, system, messages)

    if not settings.anthropic_api_key:
        fingerprint = hashlib.sha256(serialized_input.encode("utf-8")).hexdigest()[:12]
        text = f"[AI stub {fingerprint}] Generation is unavailable until a provider key is set."
        result = GenerationResult(
            text=text,
            input_tokens=_estimated_tokens(serialized_input),
            output_tokens=_estimated_tokens(text),
        )
        _record_usage(
            session,
            feature=feature,
            model=settings.ai_generation_model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            est_cost=0.0,
            ok=True,
        )
        return result

    input_tokens = _estimated_tokens(serialized_input)
    try:
        from anthropic import Anthropic

        provider_messages = list(messages or [])
        if prompt is not None:
            provider_messages.append({"role": "user", "content": prompt})
        request: dict[str, Any] = {
            "max_tokens": settings.ai_max_output_tokens,
            "messages": provider_messages,
            "model": settings.ai_generation_model,
        }
        if system is not None:
            request["system"] = system

        response = Anthropic(api_key=settings.anthropic_api_key).messages.create(**request)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        result = GenerationResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
    except Exception:
        _record_usage(
            session,
            feature=feature,
            model=settings.ai_generation_model,
            input_tokens=input_tokens,
            output_tokens=0,
            est_cost=0.0,
            ok=False,
        )
        raise

    _record_usage(
        session,
        feature=feature,
        model=settings.ai_generation_model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        est_cost=_generation_cost(settings, result.input_tokens, result.output_tokens),
        ok=True,
    )
    return result


def _stub_vector(text: str, dimension: int) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        values.extend((byte - 127.5) / 127.5 for byte in digest)
        counter += 1

    values = values[:dimension]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def embed(session: Session, texts: list[str], *, feature: str) -> list[list[float]]:
    """Embed texts through the configured provider or deterministic stub."""
    settings = get_settings()
    input_tokens = sum(_estimated_tokens(text) for text in texts)

    if not settings.openai_api_key:
        vectors = [_stub_vector(text, settings.ai_embedding_dim) for text in texts]
        _record_usage(
            session,
            feature=feature,
            model=settings.ai_embedding_model,
            input_tokens=input_tokens,
            output_tokens=0,
            est_cost=0.0,
            ok=True,
        )
        return vectors

    try:
        from openai import OpenAI

        response = OpenAI(api_key=settings.openai_api_key).embeddings.create(
            dimensions=settings.ai_embedding_dim,
            input=texts,
            model=settings.ai_embedding_model,
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        if any(len(vector) != settings.ai_embedding_dim for vector in vectors):
            raise ValueError("Embedding provider returned an unexpected vector dimension")
        input_tokens = response.usage.prompt_tokens
    except Exception:
        _record_usage(
            session,
            feature=feature,
            model=settings.ai_embedding_model,
            input_tokens=input_tokens,
            output_tokens=0,
            est_cost=0.0,
            ok=False,
        )
        raise

    _record_usage(
        session,
        feature=feature,
        model=settings.ai_embedding_model,
        input_tokens=input_tokens,
        output_tokens=0,
        est_cost=_embedding_cost(settings, input_tokens),
        ok=True,
    )
    return vectors

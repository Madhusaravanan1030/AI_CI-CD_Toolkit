"""
Thin wrapper around the OpenAI API used by both the code review bot and
the test selector. Centralizing this makes it easy to swap models,
add retries/rate-limit handling, or switch providers later.
"""

import json
import os
import time
from typing import Any

from openai import APIStatusError, OpenAI

# Errors where retrying is pointless: the request will never succeed
# without the user taking action first (billing, bad key, etc).
NON_RETRYABLE_CODES = {
    "insufficient_quota",       # no credits / exhausted balance
    "invalid_api_key",
    "invalid_request_error",
}


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """
        Provider-agnostic: works with OpenAI directly, or any
        OpenAI-compatible endpoint (e.g. Groq's free tier) by setting
        base_url. Reads LLM_API_KEY/LLM_BASE_URL/LLM_MODEL from env if
        not passed explicitly, falling back to OPENAI_API_KEY for
        backwards compatibility.
        """
        resolved_key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        resolved_base_url = base_url or os.environ.get("LLM_BASE_URL")  # e.g. https://api.groq.com/openai/v1
        self.client = OpenAI(api_key=resolved_key, base_url=resolved_base_url)
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o")
        self.supports_embeddings = resolved_base_url is None  # Groq has no embeddings endpoint

    def _raise_if_non_retryable(self, e: "APIStatusError") -> None:
        body = getattr(e, "body", None)
        code = None
        if isinstance(body, dict):
            # OpenAI nests the code under body["error"]["code"], not top-level.
            error_obj = body.get("error")
            code = error_obj.get("code") if isinstance(error_obj, dict) else body.get("code")
        if code in NON_RETRYABLE_CODES or e.status_code in (401, 403):
            raise RuntimeError(
                f"OpenAI request failed with a non-retryable error "
                f"({code or e.status_code}): {e}. "
                f"Check your API key and billing balance at "
                f"https://platform.openai.com/settings/organization/billing"
            ) from e

    def structured_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        Calls the model with JSON-mode enabled and returns a parsed dict.
        Retries on transient errors (rate limits, brief outages, invalid
        JSON) but fails immediately on non-retryable errors like an
        exhausted billing balance or a bad API key.
        """
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    response_format={"type": "json_object"},
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                content = response.choices[0].message.content
                return json.loads(content)
            except APIStatusError as e:
                self._raise_if_non_retryable(e)
                last_err = e
                time.sleep(min(2**attempt, 8))
            except json.JSONDecodeError as e:
                last_err = e
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_err}")

    def embed(
        self, texts: list[str], model: str = "text-embedding-3-small", max_retries: int = 3
    ) -> list[list[float]]:
        """Batch-embed a list of texts. Used by the test selector for
        semantic fallback matching when static analysis is inconclusive.
        Same fail-fast behavior as structured_completion: a billing/auth
        error here would otherwise retry 3 times for no reason."""
        if not self.supports_embeddings:
            raise RuntimeError(
                "Embeddings aren't available on this provider (e.g. Groq's free "
                "tier doesn't offer an embeddings endpoint). Disable the semantic "
                "fallback by passing use_semantic_fallback=False, or configure a "
                "provider that supports embeddings."
            )
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self.client.embeddings.create(model=model, input=texts)
                return [item.embedding for item in response.data]
            except APIStatusError as e:
                self._raise_if_non_retryable(e)
                last_err = e
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Embedding call failed after {max_retries} attempts: {last_err}")
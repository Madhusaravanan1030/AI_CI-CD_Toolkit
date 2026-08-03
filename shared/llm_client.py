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
    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        self.client = OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model

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
                code = getattr(getattr(e, "body", None), "get", lambda *_: None)("code") \
                    if isinstance(getattr(e, "body", None), dict) else None
                if code in NON_RETRYABLE_CODES or e.status_code in (401, 403):
                    raise RuntimeError(
                        f"OpenAI request failed with a non-retryable error "
                        f"({code or e.status_code}): {e}. "
                        f"Check your API key and billing balance at "
                        f"https://platform.openai.com/settings/organization/billing"
                    ) from e
                last_err = e
                time.sleep(min(2**attempt, 8))
            except json.JSONDecodeError as e:
                last_err = e
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_err}")

    def embed(self, texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
        """Batch-embed a list of texts. Used by the test selector for
        semantic fallback matching when static analysis is inconclusive."""
        response = self.client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]
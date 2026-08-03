"""
Thin wrapper around the OpenAI API used by both the code review bot and
the test selector. Centralizing this makes it easy to swap models,
add retries/rate-limit handling, or switch providers later.
"""

import json
import os
import time
from typing import Any

from openai import OpenAI


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
        Retries on transient errors and on invalid JSON (rare with JSON
        mode, but the model can still return an empty/malformed body).
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
            except (json.JSONDecodeError, Exception) as e:  # noqa: BLE001
                last_err = e
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_err}")

    def embed(self, texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
        """Batch-embed a list of texts. Used by the test selector for
        semantic fallback matching when static analysis is inconclusive."""
        response = self.client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

"""Gemini implementation of the perceiver: one call per box, with a response cache.

The cache is keyed by model, prompt version, photo hashes and candidate references, so
re-running the eval or reloading a record never spends quota twice on the same input.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from ..catalogue import reference_images
from ..config import Settings
from ..models import CatalogueItem, Perception
from ..quality import PreparedImage
from .base import PerceptionError
from .prompt import PROMPT_VERSION, SYSTEM_INSTRUCTION, VisionResponse, build_parts, normalise

RETRYABLE = {429, 500, 502, 503, 504}


class GeminiPerceiver:
    def __init__(self, settings: Settings, use_cache: bool = True):
        if not settings.gemini_api_key:
            raise PerceptionError("GEMINI_API_KEY is not set.")
        self.settings = settings
        self.model = settings.gemini_model
        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_s * 1000)),
        )
        self.cache_dir = Path(settings.cache_dir) if use_cache else None
        # Eval ablation only: when set, the prompt also states the order.
        self.order_hint: dict[str, int] | None = None

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION + ("+order" if self.order_hint else "")

    def _config(self) -> types.GenerateContentConfig:
        kwargs = dict(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=VisionResponse,
            temperature=0.0,
        )
        if self.settings.gemini_thinking_budget is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=self.settings.gemini_thinking_budget
            )
        return types.GenerateContentConfig(**kwargs)

    def _cache_key(self, photos: list[PreparedImage], refs: list[tuple[CatalogueItem, list[bytes]]]) -> str:
        h = hashlib.sha256()
        h.update(f"{self.model}|{self.prompt_version}|{sorted((self.order_hint or {}).items())}".encode())
        for p in photos:
            h.update(p.sha256.encode())
        for item, images in refs:
            h.update(item.model_dump_json().encode())
            for img in images:
                h.update(hashlib.sha256(img).digest())
        return h.hexdigest()

    def _call(self, contents: list) -> tuple[str, dict, str, int]:
        attempts = self.settings.gemini_max_retries + 1
        last: Exception | None = None
        for attempt in range(attempts):
            t0 = time.perf_counter()
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=contents, config=self._config()
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                if not resp.text:
                    raise PerceptionError("Model returned an empty response.")
                um = resp.usage_metadata
                usage = {
                    "input_tokens": (um.prompt_token_count or 0) if um else 0,
                    "output_tokens": (um.candidates_token_count or 0) if um else 0,
                    "thinking_tokens": (um.thoughts_token_count or 0) if um else 0,
                    "total_tokens": (um.total_token_count or 0) if um else 0,
                }
                return resp.text, usage, resp.model_version or self.model, latency_ms
            except errors.APIError as exc:
                last = exc
                if exc.code not in RETRYABLE or attempt == attempts - 1:
                    break
            except httpx.HTTPError as exc:  # timeouts and connection failures
                last = exc
                break
            time.sleep(2 * (attempt + 1))
        raise PerceptionError(f"Vision model call failed: {last}") from last

    def perceive(
        self,
        photos: list[PreparedImage],
        candidates: list[CatalogueItem],
        allowed_inserts: list[str],
        catalogue_root: Path | None,
    ) -> Perception:
        refs = [
            (item, reference_images(item, catalogue_root, self.settings) if catalogue_root else [])
            for item in candidates
        ]
        key = self._cache_key(photos, refs)
        cache_file = self.cache_dir / f"{key}.json" if self.cache_dir else None

        cached = False
        if cache_file and cache_file.exists():
            entry = json.loads(cache_file.read_text(encoding="utf-8"))
            cached = True
        else:
            parts = build_parts([p.jpeg for p in photos], refs, allowed_inserts, self.order_hint)
            contents = [
                types.Part.from_bytes(data=p, mime_type="image/jpeg") if isinstance(p, bytes) else p
                for p in parts
            ]
            text, usage, model_version, latency_ms = self._call(contents)
            entry = {"text": text, "usage": usage, "model_version": model_version, "latency_ms": latency_ms}

        try:
            resp = VisionResponse.model_validate(json.loads(entry["text"]))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise PerceptionError(f"Model output did not match the schema: {exc}") from exc

        if cache_file and not cached:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(entry), encoding="utf-8")

        skus = [c.sku for c in candidates]
        objects, counts, scene, issues = normalise(resp, skus, len(photos))
        return Perception(
            objects=objects,
            counts=counts,
            scene=scene,
            image_issues=issues,
            candidates=skus,
            model_version=entry["model_version"],
            prompt_version=self.prompt_version,
            latency_ms=entry["latency_ms"],
            usage=entry["usage"],
            cached=cached,
        )


def list_models(settings: Settings) -> list[str]:
    client = genai.Client(api_key=settings.gemini_api_key)
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions:
            names.append(m.name.removeprefix("models/"))
    return sorted(names)

"""LLM client wrapper for OpenAI-compatible APIs.

Handles both NPC generation and agent function calling.
Validates API key at startup.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import openai


class LLMClient:
    """Thin wrapper around OpenAI API for simulation use."""

    def __init__(
        self,
        api_key: str | None = None,
        npc_model: str = "gpt-4o",
        agent_model: str = "gpt-4o",
        judge_model: str = "gpt-4o",
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.client = openai.AsyncOpenAI(api_key=self.api_key)
        self.npc_model = npc_model
        self.agent_model = agent_model
        self.judge_model = judge_model

    @staticmethod
    def _is_gpt5_family(model: str | None) -> bool:
        return bool(model and model.startswith("gpt-5"))

    def _chat_kwargs(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if self._is_gpt5_family(model):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None and not self._is_gpt5_family(model):
            kwargs["temperature"] = temperature
        return kwargs

    def _responses_kwargs(
        self,
        model: str,
        input_text: str,
        max_tokens: int,
        instructions: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": input_text,
            "max_output_tokens": max_tokens,
        }
        if instructions:
            kwargs["instructions"] = instructions
        if temperature is not None and not self._is_gpt5_family(model):
            kwargs["temperature"] = temperature
        return kwargs

    @staticmethod
    def _stringify_history(messages: list[dict[str, Any]]) -> str:
        parts = []
        for message in messages:
            role = str(message.get("role", "user")).upper()
            content = str(message.get("content", ""))
            parts.append(f"[{role}]\n{content}")
        return "\n\n".join(parts)

    async def validate(self, models: list[str] | None = None):
        """Validate the configured API key against the actual models this run will use."""
        models_to_check: list[str] = []
        for model_name in (models or [self.agent_model, self.npc_model, self.judge_model]):
            if model_name and model_name not in models_to_check:
                models_to_check.append(model_name)

        for model_name in models_to_check:
            try:
                if self._is_gpt5_family(model_name):
                    request = self._responses_kwargs(
                        model=model_name,
                        input_text="Reply with: ok",
                        max_tokens=16,
                    )
                    await asyncio.wait_for(
                        self.client.responses.create(**request),
                        timeout=15.0,
                    )
                else:
                    request = self._chat_kwargs(
                        model=model_name,
                        messages=[{"role": "user", "content": "Reply with: ok"}],
                        max_tokens=8,
                        temperature=0.0,
                    )
                    await asyncio.wait_for(
                        self.client.chat.completions.create(**request),
                        timeout=15.0,
                    )
            except openai.AuthenticationError:
                raise ValueError("Invalid OpenAI API key. Check OPENAI_API_KEY.")
            except Exception as e:
                raise ValueError(f"Model validation failed for {model_name}: {e}")

    async def generate(
        self,
        prompt: str,
        timeout: float = 20.0,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> str:
        """Generate a completion from a prompt. Used for NPCs and judge."""
        actual_model = model or self.npc_model
        try:
            if self._is_gpt5_family(actual_model):
                request = self._responses_kwargs(
                    model=actual_model,
                    input_text=prompt,
                    temperature=temperature,
                    max_tokens=500,
                )
                response = await asyncio.wait_for(
                    self.client.responses.create(**request),
                    timeout=timeout,
                )
                return response.output_text or ""

            request = self._chat_kwargs(
                model=actual_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=500,
            )
            response = await asyncio.wait_for(
                self.client.chat.completions.create(**request),
                timeout=timeout,
            )
            return response.choices[0].message.content or ""
        except asyncio.TimeoutError:
            print(
                f"[LLM TIMEOUT] NPC generation timed out for model "
                f"{actual_model} after {timeout:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            return '{"action": "wait", "params": {}}'
        except Exception as e:
            print(
                f"[LLM ERROR] NPC generation failed for model {actual_model}: {e}",
                file=sys.stderr,
                flush=True,
            )
            return '{"action": "wait", "params": {}}'

    async def generate_plain_text(
        self,
        system: str,
        user_prompt: str,
        timeout: float = 30.0,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> str:
        """Generate a plain text response (not JSON). Used for meeting transcripts."""
        actual_model = model or self.npc_model
        try:
            if self._is_gpt5_family(actual_model):
                request = self._responses_kwargs(
                    model=actual_model,
                    instructions=system,
                    input_text=user_prompt,
                    temperature=temperature,
                    max_tokens=200,
                )
                response = await asyncio.wait_for(
                    self.client.responses.create(**request),
                    timeout=timeout,
                )
                return response.output_text or ""

            request = self._chat_kwargs(
                model=actual_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=200,
            )
            response = await asyncio.wait_for(
                self.client.chat.completions.create(**request),
                timeout=timeout,
            )
            return response.choices[0].message.content or ""
        except asyncio.TimeoutError:
            print(
                f"[LLM TIMEOUT] Plain-text generation timed out for model "
                f"{actual_model} after {timeout:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            return ""
        except Exception as e:
            print(
                f"[LLM ERROR] Plain-text generation failed for model "
                f"{actual_model}: {e}",
                file=sys.stderr,
                flush=True,
            )
            return ""

    async def generate_with_history(
        self,
        system: str,
        messages: list[dict],
        timeout: float = 45.0,
        temperature: float = 0.0,
    ) -> str:
        """Generate with conversation history. Used for the agent."""
        try:
            if self._is_gpt5_family(self.agent_model):
                request = self._responses_kwargs(
                    model=self.agent_model,
                    instructions=system,
                    input_text=self._stringify_history(messages),
                    temperature=temperature,
                    max_tokens=1000,
                )
                response = await asyncio.wait_for(
                    self.client.responses.create(**request),
                    timeout=timeout,
                )
                return response.output_text or "[]"

            all_messages = [{"role": "system", "content": system}] + messages
            request = self._chat_kwargs(
                model=self.agent_model,
                messages=all_messages,
                temperature=temperature,
                max_tokens=1000,
            )
            response = await asyncio.wait_for(
                self.client.chat.completions.create(**request),
                timeout=timeout,
            )
            return response.choices[0].message.content or "[]"
        except asyncio.TimeoutError:
            print(
                f"[LLM TIMEOUT] Agent generation timed out for model "
                f"{self.agent_model} after {timeout:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            return "[]"
        except Exception as e:
            print(
                f"[LLM ERROR] Agent generation failed for model "
                f"{self.agent_model}: {e}",
                file=sys.stderr,
                flush=True,
            )
            return "[]"

"""The LLM judge's contract: what it is asked and what it must answer.

- correctness: does the answer give the key fact of the reference? (Verdict) It grades what `must` lists
  cannot: yes/no answers, paraphrases, another language;
- groundedness: does the answer say only what its cited sources say? (Claims) It needs no reference, so it
  also works on production logs.
The question, reference, sources and answer go in tags, so an answer cannot pass itself off as instructions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError


class ChatModel(Protocol):
    def chat(self, messages: list[dict], schema: dict | None = None) -> str: ...


class JudgeError(RuntimeError):
    """The judge replied with something that is not the expected JSON."""


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str                                   # reason first: the model explains before it decides
    verdict: Literal["correct", "incorrect"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str
    supported: bool


class Claims(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim]


def _schema(name: str, model: type[BaseModel]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": model.model_json_schema()}}


VERDICT_FORMAT = _schema("verdict", Verdict)
CLAIMS_FORMAT = _schema("claims", Claims)


def correctness_messages(system: str, case: Mapping[str, Any], answer: str) -> list[dict]:
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"<question>\n{case['question']}\n</question>\n\n"
                                        f"<reference>\n{case['reference']}\n</reference>\n\n"
                                        f"<answer>\n{answer}\n</answer>"}]


def groundedness_messages(system: str, sources: list[str], answer: str) -> list[dict]:
    numbered = "\n\n".join(f"[S{i}]\n{text}" for i, text in enumerate(sources, start=1)) or "(no sources cited)"
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"<sources>\n{numbered}\n</sources>\n\n<answer>\n{answer}\n</answer>"}]


def _json_reply(reply: str) -> str:
    """Some models wrap JSON in a ```json fence even with a schema: unwrap it."""
    m = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", reply, re.DOTALL)
    return m.group(1) if m else reply


def parse_verdict(reply: str, case_id: str | None = None) -> Verdict:
    try:
        return Verdict.model_validate_json(_json_reply(reply))
    except ValidationError as exc:
        raise JudgeError(f"{case_id}: the judge reply is not a Verdict: {reply[:200]!r}") from exc


def parse_claims(reply: str) -> list[Claim]:
    try:
        return Claims.model_validate_json(_json_reply(reply)).claims
    except ValidationError as exc:
        raise JudgeError(f"the groundedness reply is not Claims: {reply[:200]!r}") from exc

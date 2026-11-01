"""Versioned prompt templates stored as files in `prompts/`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hr_compass.schema import OUTPUT_MODELS, HRAnswer

CONTEXT_PLACEHOLDER = "{{context}}"
# Optional first line of a prompt file: which answer schema it asks for (default: hr_answer).
_SCHEMA_DIRECTIVE = re.compile(r"\A<!--\s*schema:\s*([\w-]+)\s*-->[ \t]*\r?\n")


class PromptError(ValueError):
    """Raised when a prompt file is missing or invalid."""


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A system prompt with a `{{context}}` placeholder. The question is sent as the user message."""

    name: str
    template: str
    output_model: type[HRAnswer] = HRAnswer  # JSON schema of the answer (used when structured output is on)

    @classmethod
    def from_file(cls, path: Path) -> PromptTemplate:
        if not path.is_file():
            raise PromptError(f"prompt file not found: {path}")
        template = path.read_text(encoding="utf-8")
        output_model = HRAnswer
        if m := _SCHEMA_DIRECTIVE.match(template):
            if m.group(1) not in OUTPUT_MODELS:
                raise PromptError(f"{path}: unknown schema {m.group(1)!r} (known: {', '.join(OUTPUT_MODELS)})")
            output_model = OUTPUT_MODELS[m.group(1)]
            template = template[m.end():]  # the directive is for the code, not for the model
        if CONTEXT_PLACEHOLDER not in template:
            raise PromptError(f"{path}: missing {CONTEXT_PLACEHOLDER} placeholder")
        return cls(name=path.stem, template=template, output_model=output_model)

    def render(self, *, context: str) -> str:
        # Plain replace (not str.format) so literal braces in prompts and context are safe.
        return self.template.replace(CONTEXT_PLACEHOLDER, context)

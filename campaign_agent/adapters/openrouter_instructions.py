"""Instruction drafting through the bounded OpenRouter transport."""

from .openrouter_reviews import OpenRouterInference
from campaign_agent.domain.instruction_requests import INSTRUCTION_DRAFT_SYSTEM, instruction_draft_evidence
from campaign_agent.domain.instructions import INSTRUCTION_SCHEMA


class OpenRouterInstructions(OpenRouterInference):
    prompt_version = "comparison-instruction-draft-v3"

    def draft_instructions(self, context, settings):
        return self.complete(context, settings, instruction_draft_evidence(context),
                             system=INSTRUCTION_DRAFT_SYSTEM, schema=INSTRUCTION_SCHEMA,
                             name="comparison_instruction_draft", output_key="draft")

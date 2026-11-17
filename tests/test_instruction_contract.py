"""The planner and provider share the same restricted instruction contract."""
import unittest

from campaign_agent import creatives
from campaign_agent.adapters import openrouter_instructions
from campaign_agent.agent.planning_models import TOOLS
from campaign_agent.domain import instructions


class InstructionContractTests(unittest.TestCase):
    def test_contract_and_legacy_exports(self):
        schema = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'playback': {'type': 'string', 'enum': ['both_in_full', 'take_order']},
                'focus': {'type': 'string', 'enum': ['delivery', 'pacing']},
                'choice': {'type': 'string', 'enum': ['scene_fit', 'moment_fit']},
            },
            'required': ['playback', 'focus', 'choice'],
        }
        planner_schema = next(tool['function']['parameters'] for tool in TOOLS
                              if tool['function']['name'] == 'prepare_next_test')
        self.assertEqual(instructions.INSTRUCTION_SCHEMA, schema)
        self.assertEqual(planner_schema, schema)
        self.assertIs(openrouter_instructions.INSTRUCTION_SCHEMA, instructions.INSTRUCTION_SCHEMA)
        self.assertIs(creatives.INSTRUCTION_COMPONENTS, instructions.INSTRUCTION_COMPONENTS)
        self.assertIs(creatives.render_instruction_choices, instructions.render_instruction_choices)

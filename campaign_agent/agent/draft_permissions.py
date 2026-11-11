"""Explicit draft authority for one buyer request; model text cannot grant it."""

DRAFT_PERMISSIONS = ('none', 'placements', 'instruction_test')
WRITE_TOOLS = {'save_placement_draft': 'placements', 'prepare_next_test': 'instruction_test',
               'apply_instruction_finding': 'instruction_test'}


def permits(source, tool):
    required = WRITE_TOOLS.get(tool)
    return required is None or source.get('draft_permission', 'none') == required

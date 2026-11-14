"""Application-owned chat wording for campaign facts and supported next actions."""

REPLY_VERSION = 1
TOPICS = ('campaign_summary', 'capabilities', 'approval_and_launch', 'performance_review', 'experiment_review')
WORKFLOW_CODES = ('approval_required', 'waiting_for_evidence', 'correction_required', 'comparison_fixed',
                  'instruction_test_prepared', 'review_refresh_required', 'experiment_review_required',
                  'instruction_draft_not_authorized', 'placement_draft_not_authorized',
                  'experiment_unavailable', 'experiment_waiting', 'experiment_followup_prepared', 'experiment_refresh_required',
                  'setup_package_required', 'setup_validated', 'google_ads_delivery', 'delivery_next_test')
QUESTIONS = {
    'choose_context': 'Should I focus on video editing, audiobook production, or both?',
    'supply_catalog': 'No unambiguous placements were found. Can you supply a more relevant catalog?',
    'unsupported_request': 'I can inspect catalogs, add classified placements and explain the saved campaign. Which of those would help?',
}
LEGACY_NOTICE = 'This earlier reply was not verified. Ask again for the current campaign status.'


def capability_message(catalogue):
    """Describe the same current scoped projection as discovery, never grant access."""
    groups = {'available': [], 'offline_only': [], 'blocked': [], 'planned': []}
    for item in catalogue['capabilities']:
        detail = item['title']
        if item['kind'] == 'workspace_action':
            detail += ' (workspace action, not an agent tool)'
        elif item['kind'] == 'application_request':
            detail += ' (application request)'
        if item['state'] == 'blocked':
            reasons = []
            if 'permission_denied' in item['reason_codes']:
                reasons.append('not permitted by current access')
            if item['required_draft_permission'] and item['kind'] != 'workspace_action':
                permission = 'Placement draft' if item['required_draft_permission'] == 'placements' else 'Instruction-test draft'
                reasons.append(f'choose Changes · {permission} for a new request')
            if item['kind'] == 'workspace_action':
                reasons.append('use the workspace action with current draft access and eligible evidence')
            detail += ': ' + '; '.join(reasons)
        if item['state'] == 'blocked' and 'offline_implementation' in item['reason_codes']:
            detail += ' (offline implementation)'
        groups[item['state']].append(detail)
    headings = {'available': 'Available with current access', 'offline_only': 'Offline only (simulation or labelled sample/rehearsal)',
                'blocked': 'Requires access or an explicit draft request', 'planned': 'Planned and unavailable'}
    text = ' '.join(f"{headings[state]}: {'; '.join(items)}." for state, items in groups.items() if items)
    return (text + ' Availability describes current access and configuration, not readiness or a successful action. '
            'Selected catalogs, matching approvals, current evidence and saved corrections are checked where required at execution. '
            'Draft permission never approves, exports or launches. Open Capabilities beside the composer for each action’s requirements.')


def reply(topic, draft, *, approved=False, capabilities=None):
    if topic == 'campaign_summary':
        text = f"Revision {draft['revision']} has {len(draft['placements'])} saved placements. "
        text += 'You can ask me to find more placements for video editing or audiobook production.'
    elif topic == 'capabilities':
        if capabilities is None:
            raise ValueError('Current scoped capabilities are required.')
        text = capability_message(capabilities)
    elif topic == 'approval_and_launch':
        text = ('The current package has a saved approval in this app.' if approved
                else 'The current package has no matching approval in this app.')
        text += ' Approve package and Export setup are separate workspace actions. Ad setup and launch are manual.'
    else:
        raise ValueError('Choose a supported response topic.')
    return {'revision': draft['revision'], 'ambiguous': [],
            'message': text + ' This reply did not change the draft, approve a package, export a setup or launch ads.',
            'reply_version': REPLY_VERSION, 'reply_code': topic}


def clarification(reason, revision):
    if reason not in QUESTIONS:
        raise ValueError('Choose a supported clarification reason.')
    return {'revision': revision, 'ambiguous': [], 'message': QUESTIONS[reason],
            'reply_version': REPLY_VERSION, 'reply_code': reason}


def verified_result(result, status):
    """Retain old records, but never publish their unverified text as an agent reply."""
    if (status in {'answered', 'needs_input'} and
            (result.get('reply_version') != REPLY_VERSION
             or result.get('reply_code') not in (*TOPICS, *QUESTIONS, *WORKFLOW_CODES, 'turn_limit'))):
        return {**result, 'message': LEGACY_NOTICE, 'needs_verification': True}
    return result

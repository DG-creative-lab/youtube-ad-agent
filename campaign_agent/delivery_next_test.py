"""Choose one supported next step from a saved delivery review."""
from .performance import LOW_COMPLETION_RATE, MIN_LOCAL_ARRIVALS, apply_correction


def next_action(report):
    if report['window'] is None or report['coverage'] == 'unavailable':
        return {'kind': 'wait', 'title': 'Wait for delivery evidence',
                'reason': 'Google Ads delivery is unavailable for this review.'}
    if report['coverage'] == 'empty' and not report['has_delivery']:
        return {'kind': 'wait', 'title': 'Wait for delivery evidence',
                'reason': 'Google Ads returned no delivery data for the saved window.'}
    if report['coverage'] != 'complete':
        return {'kind': 'coverage_check', 'title': 'Fill the ad-group delivery gap',
                'reason': 'Review a window with delivery totals for both ad groups.'}
    if not report['has_delivery']:
        return {'kind': 'wait', 'title': 'Wait for delivery evidence',
                'reason': 'Google Ads reported zero delivery for both ad groups in the saved window.'}
    if any(group.get('window_activity') is None for group in report['groups']):
        return {'kind': 'coverage_check', 'title': 'Check tagged viewer coverage',
                'reason': 'Capture a new review with a verified tagged destination for each ad and an account time zone.'}

    for group in report['groups']:
        metrics, activity = group['metrics'], group['window_activity']
        arrivals, completions = activity['arrivals'], activity['completions']
        if (metrics['impressions'] > 0 and metrics['clicks'] > 0 and arrivals >= MIN_LOCAL_ARRIVALS
                and completions / arrivals < LOW_COMPLETION_RATE):
            return {
                'kind': 'comparison_test', 'title': 'Test a shorter second take',
                'creative_version': group['creative_version'], 'group_name': group['name'],
                'reason': f"{completions} of {arrivals} eligible tagged visits completed {group['name']} "
                          f"in the saved window. Google Ads reported {metrics['clicks']} clicks for that ad group.",
                'change': 'Compare a shorter second take with the current version in a local test.',
                'hold_constant': 'Keep the ad, placements, first take and comparison instructions the same.',
                'measure': 'Compare completions per tagged arrival across the two comparison versions.',
            }
    return {'kind': 'wait', 'title': 'Keep collecting viewer evidence',
            'reason': f'A comparison test needs reported clicks and at least {MIN_LOCAL_ARRIVALS} eligible '
                      'tagged arrivals with fewer than half completing in the same window.'}


def respect_correction(proposal, correction):
    if correction is None:
        return proposal
    if correction['kind'] == 'keep_takes':
        return {**apply_correction(proposal, correction),
                'hold_constant': 'Keep the ad, placements, both takes and choice controls the same.'}
    return {
        **proposal, 'kind': 'hold_comparison', 'title': 'Keep the comparison unchanged',
        'change': 'Continue observing the existing comparison under the saved buyer correction.',
        'hold_constant': 'Keep the ad, placements and entire comparison the same.',
        'measure': 'Track completions per tagged arrival with the current comparison.',
        'correction': correction,
    }


def recommendation_message(recommendation):
    parts = [recommendation['title'] + '.', recommendation['reason']]
    for key in ('change', 'hold_constant', 'measure'):
        if recommendation.get(key):
            parts.append(recommendation[key])
    if recommendation.get('correction'):
        parts.append(f"Buyer correction applied: {recommendation['correction']['label']}.")
    window = recommendation['window']
    if window:
        parts.append(f"Saved delivery review {recommendation['report_id'][:8]} covers {window['start']} to {window['end']}.")
    return ' '.join(parts)

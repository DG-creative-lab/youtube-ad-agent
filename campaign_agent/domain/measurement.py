"""Product facts about existing owned-viewer instrumentation, not observation data."""


def measurement_capabilities():
    """Return fresh logical definitions shared by viewer and agent read paths."""
    return {
        'version': 'owned-viewer-measurement/v1',
        'kind': 'instrumentation_definitions_not_results',
        'source': 'First-party events on the owned two-take comparison viewer.',
        'events': ['arrival', 'start', 'finish', 'choose'],
        'completion': {
            'all_takes_finished_before_choice': True,
            'start_required_before_finish': True,
            'choice_required': True,
            'deduplicate_by': ['visit_id', 'example_ref'],
        },
        'metrics': {
            'arrivals': 'Eligible attributed visits with an arrival event in the selected cohort.',
            'completions': 'Visits completing the intended comparison in that same cohort.',
            'completion_rate': {
                'numerator': 'completions', 'denominator': 'arrivals',
                'zero_denominator_result': None,
            },
        },
        'attribution': {
            'scope': ['client', 'brand', 'campaign', 'origin_creative', 'intended_comparison', 'content_fingerprint'],
            'unit': 'visit, not unique person or ad click',
            'local_review': 'Version-attributed visits without an ad-link binding; unknown content is reported separately.',
            'verified_ad_link': 'Exact verified link and content. Lifetime link totals include rehearsals; delivery-window eligible counts exclude rehearsals and untimestamped visits.',
            'experiment': 'Use the experiment-assigned arrivals and completions for each arm, not aggregate viewer totals.',
            'publisher_placement': 'The link identifies the creative, not the publisher video. Placement attribution needs a separate delivery report at its native grain.',
        },
        'not_measured_by_viewer': ['publisher_video_watch_time', 'publisher_video_likes',
                                   'unique_ad_clicks', 'trial_signups'],
        'limits': [
            'Definitions do not establish observed counts, real traffic or active conversion tracking. Read scoped evidence before claiming results; missing data is not zero.',
            'Ad impressions, reported clicks and spend require separately verified delivery evidence. Keep authored reports and rehearsal activity distinct from live observations.',
            'Sign-up conversion or other external outcomes require additional instrumentation; do not present them as currently measured.',
            'Observed completion rates alone do not establish causal lift or campaign effectiveness.',
            'Playback completion reflects recorded client events, not independently verified human attention.',
            'Keep numerator and denominator in the same version, cohort and reporting window; do not combine lifetime, ad-link and experiment totals.',
        ],
    }

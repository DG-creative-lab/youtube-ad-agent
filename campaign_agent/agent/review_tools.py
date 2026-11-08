"""Chat tools over the existing performance and instruction-test application commands."""
from campaign_agent.creatives import INSTRUCTION_COMPONENTS, render_instruction_choices
from campaign_agent.handoff import package_fingerprint
from scripts.campaign_drafts import PackageConflict
from .replies import REPLY_VERSION
from .draft_permissions import permits


class CampaignReviewTools:
    def __init__(self, planner):
        self.planner, self.drafts = planner, planner.drafts
        self.performance = planner.owner.performance

    def pin(self, db, draft):
        review = self.drafts._package_review(db, self.drafts.campaign_id, draft['revision'])[0]
        saved = self.performance.saved_review(db, self.drafts.campaign_id, draft['revision'], review['fingerprint'])
        scenario = saved['sample_delivery']['scenario'] if saved else 'balanced'
        return {'fingerprint': review['fingerprint'], 'reporting_scenario': scenario}

    def approved(self, db, source):
        if not {'fingerprint', 'reporting_scenario'} <= source.keys():
            raise PackageConflict('This older run has no bound review context. Start a new chat request to review performance.')
        review = self.drafts._package_review(db, self.drafts.campaign_id, source['revision'])[0]
        if source.get('fingerprint', review['fingerprint']) != review['fingerprint']:
            raise PackageConflict('The campaign content changed. Start a fresh review from the latest package.')
        return review['package'] if review['approval'] else None

    def capture(self, source):
        return self.performance.capture_review(self.drafts.campaign_id, source['revision'],
                                               source['fingerprint'], source['reporting_scenario'])

    def latest(self, db, source, history):
        step = next((item for item in reversed(history) if item['tool'] == 'review_performance'
                     and 'error' not in item['result'] and 'id' in item['result']), None)
        if step is None:
            raise ValueError('Review performance before preparing or explaining the next test.')
        package = self.approved(db, source)
        if package is None:
            raise PackageConflict('The package needs approval. Review the current package before continuing.')
        review = self.performance.saved_review(db, self.drafts.campaign_id, source['revision'],
                                               source['fingerprint'], step['result']['id'])
        if review is None:
            raise PackageConflict('The saved review is unavailable for this campaign. Review performance again.')
        self.performance.require_current_activity(db, review, package)
        correction = (self.performance.correction_for_comparison(db, package, review['proposal']['creative_version'])
                      if review['proposal']['kind'] == 'comparison_test' else None)
        if correction != review['proposal'].get('correction'):
            raise PackageConflict('The buyer correction changed. Review performance again before preparing a test.')
        review['instruction_test_id'] = self.planner.owner.instruction_tests.started_for_package(db, package)
        return review

    @staticmethod
    def readiness(review):
        if review.get('instruction_test_id'):
            return 'experiment_review_required'
        if review['proposal']['kind'] != 'comparison_test':
            return 'waiting_for_evidence'
        correction = review['proposal'].get('correction')
        if correction is None:
            return 'correction_required'
        return 'ready' if correction['kind'] == 'keep_takes' else 'comparison_fixed'

    def review(self, db, source, captured):
        if self.approved(db, source) is None:
            return self.outcome(source['revision'], None, 'approval_required'), 'needs_input'
        if captured is None:
            raise ValueError('Capture the approved package evidence first.')
        review = self.performance.save_review(db, captured)
        package = self.approved(db, source)
        review['instruction_test_id'] = self.planner.owner.instruction_tests.started_for_package(db, package)
        ready = self.readiness(review)
        preparation = {'state': ready}
        if ready == 'ready':
            context = self.performance.instruction_test_context(db, self.drafts.campaign_id,
                source['revision'], source['fingerprint'], review['id'])
            preparation.update(comparison={key: context['comparison'][key] for key in ('title', 'passage', 'instruction')},
                               instruction_components=INSTRUCTION_COMPONENTS)
        return {**review, 'preparation': preparation}, 'running'

    def explain(self, db, source, history):
        review = self.latest(db, source, history)
        ready = self.readiness(review)
        code = 'performance_review' if ready == 'ready' else ready
        status = 'answered' if ready == 'ready' else 'waiting_for_evidence' if ready == 'waiting_for_evidence' else 'needs_input'
        return self.outcome(source['revision'], review, code), status

    def prepare(self, db, run_id, source, history, call):
        if not permits(source, 'prepare_next_test'):
            review = next((step['result'] for step in reversed(history)
                           if step['tool'] == 'review_performance' and 'id' in step['result']), None)
            return self.outcome(source['revision'], review, 'instruction_draft_not_authorized'), 'needs_input'
        review = self.latest(db, source, history)
        if self.readiness(review) != 'ready':
            return self.explain(db, source, history)
        instruction = render_instruction_choices(call['arguments'])
        product_source = {'campaign_id': self.drafts.campaign_id, 'revision': source['revision'],
                          'fingerprint': source['fingerprint'], 'review_id': review['id']}
        inference = {**call.get('inference', {}), 'run_id': run_id, 'wording_choices': call['arguments'],
                     'mode': source['settings']['mode'], 'model': source['settings']['model'],
                     'prompt_version': source['settings'].get('prompt_version', 'campaign-planner-simulated-v1'),
                     'evidence_id': package_fingerprint(review), 'review_id': review['id']}
        if inference.get('usage') is None:
            inference['usage'] = {key: 0 if inference['mode'] == 'simulated' else None
                                  for key in ('input_tokens', 'output_tokens', 'cost_usd')}
        saved = self.performance.save_instruction_test(db, product_source, instruction, inference=inference)
        return self.outcome(saved['revision'], review, 'instruction_test_prepared'), 'ready_for_review'

    @staticmethod
    def outcome(revision, review, code):
        text = ''
        if review:
            text = f"Captured review of revision {review['revision']}. Sample delivery is fictional ({review['sample_delivery']['label']}); "
            text += f"report coverage is {review['sample_delivery']['coverage']}. Recorded local viewer activity: "
            text += '; '.join(f"{row['creative_version']}: {row['completions']} of {row['arrivals']} tagged visits completed"
                              for row in review['local_viewer_activity']['rows']) + '. '
            text += review['proposal']['reason'] + ' '
            correction = review['proposal'].get('correction')
            if correction:
                text += f"Used saved buyer correction: {correction['label']}. "
        text += {
            'approval_required': 'Review the current package in the workspace, complete any listed blockers and approve it before reviewing performance. Chat has not approved or launched anything.',
            'performance_review': 'The review supports an instruction-only test using the saved keep-takes correction. No new draft was created.',
            'waiting_for_evidence': 'No instruction test was drafted. ' + (review['proposal']['change'] if review else ''),
            'correction_required': 'No instruction test was drafted. Save a keep-takes correction in Performance review, then ask me to prepare the test.',
            'comparison_fixed': 'The saved correction keeps the comparison unchanged. I have not changed its instructions or recordings. An ad-invitation test is outside this instruction-only preparation.',
            'instruction_test_prepared': f'Prepared an unapproved instruction-test draft as revision {revision}. Recordings and placements are unchanged. Review and approve the new package separately.',
            'review_refresh_required': 'This captured review needs refreshing because the package, activity or correction changed. No next-test draft was saved. Ask me to review performance again.',
            'experiment_review_required': 'This package already has an instruction experiment. No new draft was created from aggregate campaign activity. Use Review instruction test and Plan next step in the workspace to assess both assigned versions before another test.',
            'instruction_draft_not_authorized': 'This request does not authorize an instruction-test draft. No draft was saved. Choose Instruction-test draft under Changes and send a new request to authorize preparation.',
            'placement_draft_not_authorized': 'This request does not authorize a placement draft. No draft was saved. Choose Placement draft under Changes and send a new request to authorize that change.',
        }[code]
        return {'revision': revision, 'ambiguous': [], 'message': text, 'reply_version': REPLY_VERSION,
                'reply_code': code, 'review_needs_refresh': code == 'review_refresh_required',
                **({'performance_review': {key: value for key, value in review.items() if key != 'preparation'}} if review else {})}

    def refresh_outcome(self, source, history):
        review = next((step['result'] for step in reversed(history)
                       if step['tool'] == 'review_performance' and 'id' in step['result']), None)
        return self.outcome(source['revision'], review, 'review_refresh_required')

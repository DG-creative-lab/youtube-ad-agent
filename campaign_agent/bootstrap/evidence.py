"""Compose evidence services and retain the native caller transaction bridges."""
from campaign_agent.adapters.sample_reporting import SampleCampaignReporting
from campaign_agent.adapters.sqlite_evidence import SQLiteEvidenceStorage
from campaign_agent.adapters.sqlite_planner_startup import initialize_performance
from campaign_agent.instruction_tests import InstructionTests
from campaign_agent.performance import CampaignPerformance


class _NativeCampaignPerformance(CampaignPerformance):
    """Existing agent and learning commands still own their SQLite transaction."""

    def correction_for_comparison(self, db, package, creative):
        return self.correction_for_comparison_from(self.storage.borrow(db), package, creative)

    def require_current_activity(self, db, evidence, package):
        return self.require_current_activity_from(self.storage.borrow(db), evidence, package)

    def save_review(self, db, evidence):
        return self.save_review_from(self.storage.borrow(db), evidence)

    def saved_review(self, db, campaign_id, revision, fingerprint, review_id=None):
        return self.saved_review_from(self.storage.borrow(db), campaign_id, revision, fingerprint, review_id)

    def instruction_test_context(self, db, campaign_id, revision, fingerprint, review_id):
        return self.instruction_test_context_from(self.storage.borrow(db), campaign_id, revision, fingerprint, review_id)

    def save_instruction_test(self, db, source, instruction, *, inference=None):
        return self.save_instruction_test_from(self.storage.borrow(db), source, instruction, inference=inference)


class _NativeInstructionTests(InstructionTests):
    """Keep assessments, draft changes and sibling run records on the caller's unit."""

    def started_for_package(self, db, package):
        return self.started_for_package_from(self.storage.borrow(db), package)

    def _test(self, db, test_id):
        return self.test_from(self.storage.borrow(db), test_id)

    def _latest_snapshot(self, db, test_id):
        return self.latest_snapshot_from(self.storage.borrow(db), test_id)

    def _initial_batch_checkpoint(self, db, snapshot):
        return self.initial_batch_checkpoint_from(self.storage.borrow(db), snapshot)

    def _snapshot_rows(self, db, test, window_ms, cutoff):
        return self.snapshot_rows_from(self.storage.borrow(db), test, window_ms, cutoff)

    def _assignment_rows(self, db, test, source):
        return self.assignment_rows_from(self.storage.borrow(db), test, source)

    def review_context(self, test_id, *, connection=None):
        if connection is None:
            return super().review_context(test_id)
        return self.review_context_from(self.storage.borrow(connection), test_id)

    def require_review_context(self, db, context):
        return self.require_review_context_from(self.storage.borrow(db), context)

    def save_review(self, db, context, assessment, *, inference=None):
        return self.save_review_from(self.storage.borrow(db), context, assessment, inference=inference)

    def next_test_context(self, db, test_id, review_id):
        return self.next_test_context_from(self.storage.borrow(db), test_id, review_id)

    def save_next_test(self, db, source, instruction, *, inference=None):
        return self.save_next_test_from(self.storage.borrow(db), source, instruction, inference=inference)


def create_performance(drafts, viewer, *, initialize=True) -> CampaignPerformance:
    performance = _NativeCampaignPerformance(drafts, viewer, SampleCampaignReporting(), SQLiteEvidenceStorage(drafts.path))
    if initialize:
        initialize_performance(drafts.path)
    return performance


def create_experiments(drafts, viewer, performance):
    return _NativeInstructionTests(drafts, viewer, performance, performance.storage)

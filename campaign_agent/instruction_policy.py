"""Compatibility exports for the instruction-test decision policy."""

from campaign_agent.domain.instruction_policy import (
    cache,
    lru_cache,
    comb,
    cos,
    fsum,
    pi,
    prod,
    POLICY_V1,
    INITIAL_SAMPLE_SIZE,
    ADDITIONAL_BATCH_SIZE,
    SAMPLE_CAP,
    MAX_MODEL_VISITS,
    DECISION_TOLERANCE,
    _legendre_value,
    _gauss_legendre,
    _lift_probability,
    _predictive,
    _action_values,
    _value_after_batch,
    recommend_instruction_action,
)

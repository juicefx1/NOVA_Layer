from __future__ import annotations

from uuid import UUID

from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.models import HypothesisCandidateSet, ObjectHypothesis


def generate_and_select(
    service: ObjectWorkflowService,
    *,
    index: int = 0,
) -> tuple[ObjectHypothesis, HypothesisCandidateSet]:
    """Generate candidates then select one — common workflow test helper."""
    candidate_set = service.generate_candidates()
    hypothesis = service.select_candidate(candidate_set.candidates[index].id)
    return hypothesis, candidate_set


def select_active_candidate(
    service: ObjectWorkflowService,
    candidate_id: UUID | str,
) -> ObjectHypothesis:
    return service.select_candidate(candidate_id)

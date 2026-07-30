from __future__ import annotations

from nova_layer.object_workflow.domain.models import Project, WorkflowState


def derive_workflow_state(project: Project) -> WorkflowState:
    if project.active_extraction_result_id is not None:
        return WorkflowState.EXTRACTION_READY
    if project.active_confirmed_object_id is not None:
        return WorkflowState.OBJECT_CONFIRMED
    if project.active_hypothesis_id is not None:
        return WorkflowState.HYPOTHESIS_READY
    if project.active_candidate_set_id is not None:
        return WorkflowState.CANDIDATE_SET_READY
    if project.active_intent_id is not None:
        return WorkflowState.INTENT_PROVIDED
    if project.active_source_image_id is not None:
        return WorkflowState.SOURCE_READY
    return WorkflowState.NO_SOURCE


def apply_derived_workflow_state(project: Project) -> None:
    project.workflow_state = derive_workflow_state(project)

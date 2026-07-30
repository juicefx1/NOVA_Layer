from __future__ import annotations

from uuid import UUID, uuid4

from nova_layer.object_workflow.domain.models import (
    GenerationRecord,
    GenerationStatus,
    HypothesisCandidateSet,
    Project,
    utc_now,
)


def next_sequence_number(project: Project) -> int:
    if not project.generation_records:
        return 1
    return max(record.sequence_number for record in project.generation_records) + 1


def latest_generation_record(
    project: Project,
    generation_id: UUID,
) -> GenerationRecord | None:
    matches = [
        record
        for record in project.generation_records
        if record.generation_id == generation_id
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: item.created_at)


def ordered_generations(project: Project) -> list[GenerationRecord]:
    latest_by_id: dict[UUID, GenerationRecord] = {}
    for record in sorted(project.generation_records, key=lambda item: item.created_at):
        latest_by_id[record.generation_id] = record
    return sorted(latest_by_id.values(), key=lambda item: item.sequence_number)


def latest_candidate_set_for_generation(
    project: Project,
    generation_id: UUID,
) -> HypothesisCandidateSet | None:
    matches = [
        item
        for item in project.candidate_sets
        if item.generation_id == generation_id
    ]
    if not matches:
        record = latest_generation_record(project, generation_id)
        if record is None:
            return None
        return _find_candidate_set(project, record.candidate_set_id)
    return max(matches, key=lambda item: item.created_at)


def _find_candidate_set(project: Project, candidate_set_id: UUID) -> HypothesisCandidateSet | None:
    for item in project.candidate_sets:
        if item.id == candidate_set_id:
            return item
    return None


def append_generation_status_record(
    project: Project,
    *,
    base: GenerationRecord,
    status: GenerationStatus,
    rejected_at=None,
) -> GenerationRecord:
    updated = GenerationRecord(
        id=uuid4(),
        generation_id=base.generation_id,
        sequence_number=base.sequence_number,
        artist_intent_id=base.artist_intent_id,
        artist_intent_revision=base.artist_intent_revision,
        provider_id=base.provider_id,
        provider_version=base.provider_version,
        candidate_set_id=base.candidate_set_id,
        operation_id=base.operation_id,
        status=status,
        created_at=utc_now(),
        rejected_at=rejected_at,
        provider_metadata=dict(base.provider_metadata),
    )
    project.generation_records.append(updated)
    return updated


def migrate_project_generation_history(project: Project) -> None:
    """In-memory migration for pre–Feature-3 projects (schema 2.0)."""
    if project.generation_records:
        return
    if not project.candidate_sets:
        project.active_generation_id = None
        return

    operation_roots: dict[UUID, HypothesisCandidateSet] = {}
    for candidate_set in sorted(project.candidate_sets, key=lambda item: item.created_at):
        if candidate_set.operation_id not in operation_roots:
            operation_roots[candidate_set.operation_id] = candidate_set

    active_set: HypothesisCandidateSet | None = None
    if project.active_candidate_set_id is not None:
        active_set = _find_candidate_set(project, project.active_candidate_set_id)
    if active_set is None:
        active_set = max(project.candidate_sets, key=lambda item: item.created_at)

    active_generation_id: UUID | None = None
    sequence = 0
    for _op_id, root in sorted(
        operation_roots.items(),
        key=lambda pair: pair[1].created_at,
    ):
        sequence += 1
        generation_id = root.generation_id or uuid4()
        for candidate_set in project.candidate_sets:
            same_op = candidate_set.operation_id == root.operation_id
            if same_op and candidate_set.generation_id is None:
                candidate_set.generation_id = generation_id

        status: GenerationStatus = "available"
        if (
            project.active_confirmed_object_id is not None
            and root.operation_id == active_set.operation_id
        ):
            hypothesis = None
            if project.active_hypothesis_id is not None:
                hypothesis = next(
                    (
                        item
                        for item in project.hypotheses
                        if item.id == project.active_hypothesis_id
                    ),
                    None,
                )
            if hypothesis is not None and hypothesis.operation_id == root.operation_id:
                status = "confirmed"

        project.generation_records.append(
            GenerationRecord(
                generation_id=generation_id,
                sequence_number=sequence,
                artist_intent_id=root.intent_id,
                artist_intent_revision=root.artist_intent_revision,
                provider_id=root.provider_id,
                provider_version=root.provider_version,
                candidate_set_id=root.id,
                operation_id=root.operation_id,
                status=status,
                provider_metadata={},
            )
        )
        if root.operation_id == active_set.operation_id:
            active_generation_id = generation_id

    project.active_generation_id = active_generation_id

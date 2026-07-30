from __future__ import annotations

from nova_layer.domain.models import (
    MaturityState,
    ReasoningRecord,
    SmartLayer,
    ValidationState,
)


class MaturityPromotionError(ValueError):
    """Raised when a Smart Layer cannot advance to production_ready."""


def production_ready_blockers(layer: SmartLayer) -> tuple[str, ...]:
    blockers: list[str] = []
    maturity = layer.object_identity.maturity_state
    if maturity is MaturityState.PRODUCTION_READY:
        return ()
    if maturity is MaturityState.PERSISTENT:
        blockers.append("Persistent Smart Layers cannot be re-promoted to production_ready.")
        return tuple(blockers)
    if maturity is not MaturityState.VALIDATED:
        blockers.append("Smart Layer must be validated before production_ready promotion.")
    if len(layer.frame_results) < 3:
        blockers.append("Production readiness requires Start, Master, and End validation results.")
    elif any(item.validation_state != ValidationState.ACCEPTED for item in layer.frame_results):
        blockers.append("Every validation-target frame must be accepted.")
    if not layer.renders:
        blockers.append("At least one Smart Layer render version is required.")
    return tuple(blockers)


def promote_to_production_ready(layer: SmartLayer) -> SmartLayer:
    """Advance a validated Smart Layer with renders to production_ready maturity."""
    blockers = production_ready_blockers(layer)
    if layer.object_identity.maturity_state is MaturityState.PRODUCTION_READY:
        return layer
    if blockers:
        raise MaturityPromotionError("; ".join(blockers))
    previous = layer.object_identity.maturity_state
    layer.object_identity.maturity_state = MaturityState.PRODUCTION_READY
    layer.version += 1
    layer.reasoning_history.append(
        ReasoningRecord(
            evidence_ids=[],
            decision="smart_layer_promoted_to_production_ready",
            confidence=layer.object_identity.confidence,
            previous_maturity=previous,
            resulting_maturity=MaturityState.PRODUCTION_READY,
            artist_confirmation_required=False,
        )
    )
    return layer

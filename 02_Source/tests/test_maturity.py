from __future__ import annotations

import pytest

from nova_layer.app.maturity import (
    MaturityPromotionError,
    production_ready_blockers,
    promote_to_production_ready,
)
from nova_layer.domain.models import (
    ArtistIntent,
    CapabilityProvenance,
    ExtractionPreview,
    FrameResult,
    GuidancePoint,
    MaturityState,
    SmartLayer,
    SmartLayerRender,
    ValidationState,
)


def _layer(*, maturity: MaturityState, with_frames: bool, with_render: bool) -> SmartLayer:
    provenance = CapabilityProvenance(
        capability="interactive_segmentation",
        adapter="test",
        adapter_version="1.0",
    )
    layer = SmartLayer(
        artist_intent=ArtistIntent(
            master_frame=1,
            points=[GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        )
    )
    layer.object_identity.maturity_state = maturity
    if with_frames:
        layer.frame_results = [
            FrameResult(
                frame_number=0,
                direction="backward",
                mask_reference="masks/0.png",
                confidence=0.9,
                validation_state=ValidationState.ACCEPTED,
                provenance=provenance,
            ),
            FrameResult(
                frame_number=1,
                direction="master",
                mask_reference="masks/1.png",
                confidence=0.95,
                validation_state=ValidationState.ACCEPTED,
                provenance=provenance,
            ),
            FrameResult(
                frame_number=2,
                direction="forward",
                mask_reference="masks/2.png",
                confidence=0.9,
                validation_state=ValidationState.ACCEPTED,
                provenance=provenance,
            ),
        ]
    if with_render:
        layer.renders = [
            SmartLayerRender(
                version=1,
                frame_start=0,
                frame_end=2,
                frames=[
                    ExtractionPreview(
                        frame_number=0,
                        image_reference="renders/v0001/frame_000000.png",
                        mask_reference="masks/0.png",
                    )
                ],
            )
        ]
    return layer


def test_production_ready_requires_validated_frames_and_render() -> None:
    layer = _layer(maturity=MaturityState.CONFIRMED, with_frames=True, with_render=True)
    assert production_ready_blockers(layer)
    with pytest.raises(MaturityPromotionError, match="validated"):
        promote_to_production_ready(layer)


def test_promote_to_production_ready_records_reasoning() -> None:
    layer = _layer(maturity=MaturityState.VALIDATED, with_frames=True, with_render=True)
    promote_to_production_ready(layer)
    assert layer.object_identity.maturity_state is MaturityState.PRODUCTION_READY
    assert layer.version == 2
    assert layer.reasoning_history[-1].decision == "smart_layer_promoted_to_production_ready"
    assert production_ready_blockers(layer) == ()

from __future__ import annotations

from typing import Any

from nova_layer.object_workflow.domain.models import (
    BoundingBox,
    IntentInstruction,
    IntentSignal,
    NegativePoint,
    PositivePoint,
)


class IntentValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


SUPPORTED_SIGNAL_TYPES = frozenset({"positive_point", "negative_point", "bounding_box"})
INTENT_SCHEMA = "nova.intent.guidance.v1"


def parse_intent_signals(raw_signals: list[dict[str, Any]]) -> list[IntentSignal]:
    if not raw_signals:
        raise IntentValidationError(
            "EMPTY_INTENT_PAYLOAD",
            "ArtistIntent payload must contain signals",
        )

    parsed: list[IntentSignal] = []
    for index, raw in enumerate(raw_signals):
        if not isinstance(raw, dict):
            raise IntentValidationError(
                "INVALID_INTENT_SIGNAL",
                f"signal at index {index} must be an object",
            )
        signal_type = raw.get("type")
        if signal_type not in SUPPORTED_SIGNAL_TYPES:
            raise IntentValidationError(
                "UNSUPPORTED_INTENT_SIGNAL",
                f"unsupported intent signal type: {signal_type!r}",
            )
        try:
            if signal_type == "positive_point":
                parsed.append(PositivePoint.model_validate(raw))
            elif signal_type == "negative_point":
                parsed.append(NegativePoint.model_validate(raw))
            else:
                parsed.append(BoundingBox.model_validate(raw))
        except Exception as exc:
            raise IntentValidationError(
                "INVALID_INTENT_GEOMETRY",
                f"invalid intent signal at index {index}: {exc}",
            ) from exc
    return parsed


def validate_intent_instruction(
    instruction: IntentInstruction | dict[str, Any],
) -> IntentInstruction:
    if isinstance(instruction, dict):
        try:
            model = IntentInstruction.model_validate(instruction)
        except Exception as exc:
            raise IntentValidationError("INVALID_INTENT_INSTRUCTION", str(exc)) from exc
    else:
        model = instruction

    if model.schema_name != INTENT_SCHEMA:
        raise IntentValidationError(
            "UNSUPPORTED_INTENT_SCHEMA",
            f"unsupported intent schema: {model.schema_name!r}",
        )

    parse_intent_signals(model.payload.signals)
    return model


def first_bounding_box(signals: list[IntentSignal]) -> BoundingBox | None:
    for signal in signals:
        if isinstance(signal, BoundingBox):
            return signal
    return None


def first_positive_point(signals: list[IntentSignal]) -> PositivePoint | None:
    for signal in signals:
        if isinstance(signal, PositivePoint):
            return signal
    return None


def count_prompt_signals(signals: list[IntentSignal]) -> tuple[int, int, bool]:
    positives = sum(1 for signal in signals if isinstance(signal, PositivePoint))
    negatives = sum(1 for signal in signals if isinstance(signal, NegativePoint))
    has_box = any(isinstance(signal, BoundingBox) for signal in signals)
    return positives, negatives, has_box


def signals_as_dicts(signals: list[IntentSignal]) -> list[dict[str, Any]]:
    return [signal.model_dump(mode="python") for signal in signals]


def instruction_signal_fingerprint(instruction: IntentInstruction) -> list[dict[str, Any]]:
    return [dict(item) for item in instruction.payload.signals]

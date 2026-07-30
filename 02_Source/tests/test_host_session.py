from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nova_layer import host_session
from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.domain.models import (
    ArtistIntent,
    BoundingRegion,
    CapabilityProvenance,
    ExtractionPreview,
    FrameResult,
    GuidancePoint,
    MaturityState,
    MediaLinkState,
    MediaReference,
    Project,
    Sequence,
    Shot,
    SmartLayer,
    SmartLayerRender,
    ValidationState,
)
from nova_layer.host.adapters import NukeHostAdapter
from nova_layer.host.session import HOST_API_VERSION, HeadlessHostSession, HostSessionError
from nova_layer.ports.media import MediaInfo


class FakeMediaReader:
    def __init__(self, fingerprint: str = "sha256:original", frame_count: int = 100) -> None:
        self.fingerprint = fingerprint
        self.frame_count = frame_count

    def inspect(self, path: Path) -> MediaInfo:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Media file does not exist: {resolved}")
        return MediaInfo(
            path=resolved,
            fingerprint=self.fingerprint,
            frame_count=self.frame_count,
            frame_rate=24.0,
            width=1920,
            height=1080,
            time_base="1/24",
            pixel_format="yuv420p",
        )

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        return np.zeros((1080, 1920, 3), dtype=np.uint8)


def _project(*, source_path: str | None = "/tmp/source.mov") -> Project:
    media = MediaReference(
        relative_path="media/source.mov",
        source_path=source_path,
        fingerprint="sha256:original",
        frame_count=100,
        frame_rate=24.0,
        width=1920,
        height=1080,
    )
    intent = ArtistIntent(
        master_frame=50,
        points=[GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        bounding_region=BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.5),
    )
    layer = SmartLayer(artist_intent=intent)
    shot = Shot(
        media=media,
        range_start=10,
        range_end=90,
        master_frame=50,
        smart_layers=[layer],
    )
    return Project(name="NOVA Test", sequences=[Sequence(shots=[shot])])


def test_headless_host_session_reports_status(tmp_path: Path) -> None:
    package = tmp_path / "demo.nova"
    media = tmp_path / "source.mov"
    media.write_bytes(b"source")
    JsonProjectStore().save(_project(source_path=str(media)), package)
    session = HeadlessHostSession(media_reader=FakeMediaReader())
    session.open_project(package)
    status = session.status()

    assert status["open"] is True
    assert status["host_api_version"] == HOST_API_VERSION
    assert status["project"]["name"] == "NOVA Test"
    assert status["shot"]["master_frame"] == 50
    assert status["media"]["link_state"] == MediaLinkState.LINKED.value
    assert status["production_ready"]["eligible"] is False


def test_headless_host_session_relink_and_promote(tmp_path: Path) -> None:
    package = tmp_path / "demo.nova"
    project = _project(source_path=str(tmp_path / "missing.mov"))
    JsonProjectStore().save(project, package)
    reader = FakeMediaReader(fingerprint="sha256:replacement")
    session = HeadlessHostSession(media_reader=reader)
    session.open_project(package)
    assert session.status()["media"]["link_state"] == MediaLinkState.MISSING.value

    replacement = tmp_path / "replacement.mov"
    replacement.write_bytes(b"fake")
    with pytest.raises(HostSessionError, match="accept_changed"):
        session.relink_media(replacement)
    result = session.relink_media(replacement, accept_changed=True)
    assert result["link_state"] == MediaLinkState.LINKED.value
    assert result["accepted_changed_fingerprint"] is True

    layer = session.project.sequences[0].shots[0].smart_layers[0]  # type: ignore[union-attr]
    provenance = CapabilityProvenance(
        capability="interactive_segmentation",
        adapter="test",
        adapter_version="1.0",
    )
    layer.object_identity.maturity_state = MaturityState.VALIDATED
    layer.frame_results = [
        FrameResult(
            frame_number=frame,
            direction=direction,
            mask_reference=f"masks/{frame}.png",
            confidence=0.9,
            validation_state=ValidationState.ACCEPTED,
            provenance=provenance,
        )
        for frame, direction in ((10, "backward"), (50, "master"), (90, "forward"))
    ]
    layer.renders = [
        SmartLayerRender(
            version=1,
            frame_start=10,
            frame_end=90,
            frames=[
                ExtractionPreview(
                    frame_number=10,
                    image_reference="renders/v0001/frame_000010.png",
                    mask_reference="masks/10.png",
                )
            ],
        )
    ]
    session.save()
    promoted = session.promote_production_ready()
    assert promoted["maturity_state"] == MaturityState.PRODUCTION_READY.value
    reloaded = HeadlessHostSession(media_reader=reader)
    reloaded.open_project(package)
    assert (
        reloaded.status()["smart_layer"]["maturity_state"]
        == MaturityState.PRODUCTION_READY.value
    )


def test_headless_host_session_export_requires_render(tmp_path: Path) -> None:
    package = tmp_path / "demo.nova"
    JsonProjectStore().save(_project(), package)
    session = HeadlessHostSession(media_reader=FakeMediaReader())
    session.open_project(package)
    with pytest.raises(HostSessionError, match="export failed"):
        session.export_render(tmp_path / "out", format="png_sequence")


def test_nuke_adapter_menu_skeleton() -> None:
    menu = NukeHostAdapter().install_menu()
    assert menu["host"] == "nuke"
    assert any(action["command"] == "promote_production_ready" for action in menu["actions"])


def test_host_session_cli_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "demo.nova"
    media = tmp_path / "source.mov"
    media.write_bytes(b"source")
    JsonProjectStore().save(_project(source_path=str(media)), package)
    monkeypatch.setattr(
        "sys.argv",
        ["nova-host-session", str(package), "status"],
    )
    monkeypatch.setattr(
        "nova_layer.host_session.HeadlessHostSession",
        lambda: HeadlessHostSession(media_reader=FakeMediaReader()),
    )
    assert host_session.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project"]["name"] == "NOVA Test"
    assert payload["host_api_version"] == HOST_API_VERSION

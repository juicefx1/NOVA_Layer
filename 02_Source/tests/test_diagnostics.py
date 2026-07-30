from nova_layer.app.diagnostics import DiagnosticStatus, StartupDiagnostics


def test_startup_diagnostics_reports_required_components(monkeypatch: object) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "mock")  # type: ignore[attr-defined]
    monkeypatch.delenv("NOVA_SKELETON_DETECTOR", raising=False)  # type: ignore[attr-defined]
    monkeypatch.delenv("NOVA_DEPTH_POSE_BRIDGE_URL", raising=False)  # type: ignore[attr-defined]
    report = StartupDiagnostics().run()
    by_name = {check.name: check for check in report.checks}

    assert not report.has_failures
    assert by_name["Python Runtime"].status == DiagnosticStatus.PASS
    assert by_name["Desktop UI"].status == DiagnosticStatus.PASS
    assert by_name["Media Decode"].status == DiagnosticStatus.PASS
    assert by_name["Project Persistence"].status == DiagnosticStatus.PASS
    assert by_name["Interactive Segmentation"].status == DiagnosticStatus.WARNING
    assert by_name["Temporal Propagation"].status == DiagnosticStatus.WARNING
    assert by_name["Skeleton Detection"].status == DiagnosticStatus.WARNING
    assert "warning" in report.summary.lower()


def test_diagnostics_leave_no_recovery_artifacts() -> None:
    report = StartupDiagnostics().run()

    assert not report.has_failures
    assert all(check.message for check in report.checks)


def test_browser_bridge_diagnostics_probe_health(monkeypatch: object) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "auto")  # type: ignore[attr-defined]
    monkeypatch.delenv("NOVA_SKELETON_DETECTOR", raising=False)  # type: ignore[attr-defined]
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "NOVA_DEPTH_POSE_BRIDGE_URL",
        "http://127.0.0.1:3456/api/nova/depth-pose?token=test",
    )
    calls: list[tuple[str, float]] = []

    def probe(endpoint: str, timeout: float) -> dict[str, str]:
        calls.append((endpoint, timeout))
        return {"status": "ready", "schema_version": "1.0", "worker_connected": True}

    report = StartupDiagnostics(bridge_probe=probe).run()
    check = next(item for item in report.checks if item.name == "Skeleton Detection")

    assert check.status == DiagnosticStatus.PASS
    assert calls == [("http://127.0.0.1:3456/api/nova/depth-pose?token=test", 0.75)]


def test_browser_bridge_diagnostics_warn_when_offline(monkeypatch: object) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "auto")  # type: ignore[attr-defined]
    monkeypatch.delenv("NOVA_SKELETON_DETECTOR", raising=False)  # type: ignore[attr-defined]
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "NOVA_DEPTH_POSE_BRIDGE_URL", "http://localhost:3456/api/nova/depth-pose"
    )

    def offline(endpoint: str, timeout: float) -> dict[str, str]:
        del endpoint, timeout
        raise OSError("connection refused")

    report = StartupDiagnostics(bridge_probe=offline).run()
    check = next(item for item in report.checks if item.name == "Skeleton Detection")

    assert check.status == DiagnosticStatus.WARNING
    assert "connection refused" in check.message


def test_browser_bridge_diagnostics_warn_when_worker_is_missing(monkeypatch: object) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "auto")  # type: ignore[attr-defined]
    monkeypatch.delenv("NOVA_SKELETON_DETECTOR", raising=False)  # type: ignore[attr-defined]
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "NOVA_DEPTH_POSE_BRIDGE_URL", "http://localhost:3456/api/nova/depth-pose"
    )
    report = StartupDiagnostics(
        bridge_probe=lambda endpoint, timeout: {
            "status": "ready",
            "schema_version": "1.0",
            "worker_connected": False,
        }
    ).run()
    check = next(item for item in report.checks if item.name == "Skeleton Detection")

    assert check.status == DiagnosticStatus.WARNING
    assert "no browser worker" in check.message

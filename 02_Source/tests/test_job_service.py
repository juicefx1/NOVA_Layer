from threading import Event
from time import sleep

from nova_layer.app.job_service import ProcessingJobService, ProgressCallback


def test_job_reports_progress_and_completion(qtbot: object) -> None:
    service = ProcessingJobService()

    def operation(cancel: Event, report: ProgressCallback) -> object:
        assert not cancel.is_set()
        report(1, 2, "first")
        report(2, 2, "second")
        return ["complete"]

    with qtbot.waitSignal(service.completed) as completed:  # type: ignore[attr-defined]
        assert service.start("test_job", operation)

    assert completed.args[0].name == "test_job"
    assert completed.args[0].value == ["complete"]
    assert not service.is_running


def test_job_cancellation_discards_result(qtbot: object) -> None:
    service = ProcessingJobService()
    progress_seen = Event()

    def operation(cancel: Event, report: ProgressCallback) -> object:
        report(0, 5, "started")
        progress_seen.set()
        while not cancel.is_set():
            sleep(0.001)
        return ["partial"]

    with qtbot.waitSignal(service.cancelled) as cancelled:  # type: ignore[attr-defined]
        assert service.start("cancel_job", operation)
        assert progress_seen.wait(timeout=1)
        assert service.cancel()

    assert cancelled.args == ["cancel_job"]
    assert not service.is_running

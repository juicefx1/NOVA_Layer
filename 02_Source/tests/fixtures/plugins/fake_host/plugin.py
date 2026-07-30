from __future__ import annotations

from nova_layer.object_workflow.adapters.host_reveal import FakeHostAdapter


def register(context) -> None:  # type: ignore[no-untyped-def]
    context.register_host_adapter("plugin.test.fake_host", FakeHostAdapter)

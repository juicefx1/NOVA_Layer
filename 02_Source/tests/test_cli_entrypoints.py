import importlib
import tomllib
from pathlib import Path

from nova_layer.release_install_smoke import SMOKE_MODULES


def test_all_declared_cli_entrypoints_are_importable() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    scripts = payload["project"]["scripts"]
    assert "nova-layer" in scripts
    assert "nova-real-benchmark" in scripts
    assert "nova-baseline-activate" in scripts
    for target in scripts.values():
        module_name, function_name = target.split(":", maxsplit=1)
        function = getattr(importlib.import_module(module_name), function_name)
        assert callable(function)


def test_install_smoke_covers_every_non_gui_command_module() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    targets = payload["project"]["scripts"]
    non_gui_modules = {
        target.split(":", maxsplit=1)[0]
        for command, target in targets.items()
        if command != "nova-layer" and command != "nova-install-smoke"
    }
    assert set(SMOKE_MODULES) == non_gui_modules

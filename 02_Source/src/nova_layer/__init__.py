"""NOVA Layer Phase 1 prototype."""

from importlib.metadata import PackageNotFoundError, version

from nova_layer.domain.models import Project

try:
    __version__ = version("nova-layer")
except PackageNotFoundError:  # editable / source tree before install
    __version__ = "1.0.0rc1"

__all__ = ["Project", "__version__"]

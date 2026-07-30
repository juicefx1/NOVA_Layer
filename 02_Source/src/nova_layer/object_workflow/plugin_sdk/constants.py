from __future__ import annotations

from typing import Literal

# Core SDK contract version. Plugins must declare an exact supported value.
SDK_VERSION = "1.0"
SUPPORTED_SDK_VERSIONS: frozenset[str] = frozenset({SDK_VERSION})

PluginType = Literal["inference", "matting", "host_adapter"]
SUPPORTED_PLUGIN_TYPES: frozenset[str] = frozenset(
    {"inference", "matting", "host_adapter"}
)

KNOWN_CAPABILITIES: frozenset[str] = frozenset(
    {
        "sam2",
        "onnx",
        "gpu",
        "cpu",
        "mps",
        "alpha_matting",
        "photoshop_host",
        "filesystem_host",
        "reveal_host",
        "open_file_host",
    }
)

ENV_PLUGINS_DIR = "NOVA_PLUGINS_DIR"
DEFAULT_PLUGINS_DIRNAME = "plugins"

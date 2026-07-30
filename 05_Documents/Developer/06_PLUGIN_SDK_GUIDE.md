# Plugin SDK Guide

## Status

Approved

## Audience

Developer, Plugin Author

## Authority

Practical guide for building **local** Object Workflow plugins with the public Plugin SDK.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md` (§9 Plugin System)

API authority (do not duplicate symbol catalogs here):

- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`
- `05_Documents/API/04_SCHEMA_REFERENCE.md` (manifest / package field rules)
- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` / `03_EVENT_REFERENCE.md` (if adding Automation extensions)

Environment setup:

- `05_Documents/Developer/00_DEVELOPER_GUIDE.md`

Public package:

- `nova_layer.object_workflow.plugin_sdk`

## Scope

End-to-end **implemented** workflow: create → manifest → `register()` → package → install → load/test. Local `.nova-plugin` only. No remote marketplace, no sandbox, no invented scaffolding CLI.

---

# 1. Introduction

Plugins extend Object Workflow **additively** by registering into Core registries through `PluginRegistrationContext`. They must not fork Domain rules, invent a second Project schema, or bypass `OperationExecutor` for generate/extract.

Supported plugin types (`SUPPORTED_PLUGIN_TYPES`):

| `plugin_type` | Registers |
|---|---|
| `inference` | Core Inference providers |
| `matting` | Precision Extraction / matting providers |
| `host_adapter` | Host adapters |

Any loaded plugin may also register Automation commands/helpers or subscribe to Automation events **when** Core has attached those services.

**Trust model:** plugins run as trusted local Python code (no sandbox). Install only packages you trust (`ARCHITECTURE.md`).

---

# 2. Prerequisites

| Requirement | Notes |
|---|---|
| Python **3.12** | Same as Core (`02_Source/pyproject.toml`) |
| Editable Core install | `cd 02_Source && pip install -e ".[dev]"` (add `desktop` if you use the Qt app) |
| SDK version | Declare `sdk_version: "1.0"` (see `SUPPORTED_SDK_VERSIONS`) |
| Ports knowledge | Implement against `nova_layer.object_workflow.ports` Protocols — see engine/port specs |

Unverified in this guide (do not assume):

- GPU / CUDA / MPS availability for real models  
- Commercial host applications for `real_host` bridges  
- That a plugin can hot-reload an already-registered `plugin_id` without restart  

---

# 3. Plugin Architecture

```text
.nova-plugin / plugin directory
├── package.json          # Package Manifest (Feature 12; required for packaged installs)
├── manifest.json         # Plugin Manifest (SDK)
└── {entry_module}.py     # Exports register(context) or Plugin.register(context)
```

Runtime path (public contract):

```text
Discover → Validate manifest + entry file → Import entry → register(context) → available
                                                              ↘ failed (isolated)
```

Packaging path (separate):

```text
Plugin directory → validate_plugin_package / build_nova_plugin_package
                 → PluginPackageManager.install / update
                 → PluginManager discovers install root → register
```

Core owns registries. Plugins only touch them via `PluginRegistrationContext`. Details: Plugin SDK Reference §§5–7.

---

# 4. Creating a Plugin

There is **no** official plugin scaffold CLI. Create a directory manually.

### Minimal layout (development directory)

```text
my_inference_plugin/
├── manifest.json
└── plugin.py
```

`entry_module` in the manifest must be the basename without `.py` (example: `"plugin"` → `plugin.py`).

### Naming tips

- Use a stable, unique `plugin_id` (e.g. `acme.sam2_cpu`). Avoid `/`, `\`, `..`.  
- Prefer provider ids that will not collide with Core builtins (fixtures use `plugin.test.*` prefixes).  
- Keep `plugin_id` and package `plugin_id` identical when packaging.

### Development discovery

`PluginManager` searches (among others):

- Explicit `plugin_roots`  
- `NOVA_PLUGINS_DIR` (`ENV_PLUGINS_DIR`)  
- Default Feature 12 install root (`NOVA_PLUGIN_INSTALL_DIR` or `~/.nova_layer/plugins/installed`)  
- A local `plugins/` directory relative to cwd / source tree  

Place each plugin as a **child directory** containing `manifest.json` (not the root itself as a single flat file).

---

# 5. Writing `manifest.json`

Field-level rules: Schema Reference §5 and Plugin SDK Reference §8.

### Example (`inference`)

```json
{
  "plugin_id": "acme.example_inference",
  "display_name": "Example Inference",
  "description": "Example Core Inference plugin.",
  "version": "1.0.0",
  "author": "Acme",
  "sdk_version": "1.0",
  "plugin_type": "inference",
  "capabilities": ["cpu"],
  "entry_module": "plugin"
}
```

### Checklist

| Item | Rule |
|---|---|
| Required fields | `plugin_id`, `display_name`, `version`, `sdk_version`, `plugin_type`, `entry_module`, `capabilities` (≥1) |
| Optional | `description`, `author`, `optional_dependencies` |
| `sdk_version` | Must be in `SUPPORTED_SDK_VERSIONS` (currently `"1.0"` only) |
| `plugin_type` | Exactly one of `inference` / `matting` / `host_adapter` |
| `capabilities` | Non-empty strings; unknown tokens allowed |
| `optional_dependencies` | Importable module names; missing → `PluginDependencyError` at load |
| `entry_module` | Simple name only — no dots or path separators |

Validate early:

```python
from pathlib import Path
from nova_layer.object_workflow.plugin_sdk import load_manifest

manifest = load_manifest(Path("my_inference_plugin"))
print(manifest.plugin_id, manifest.plugin_type)
```

---

# 6. Implementing `register()`

The entry module must export either:

1. `register(context: PluginRegistrationContext) -> None`, or  
2. a `Plugin` class with instance method `register(context)`

Otherwise load fails with `PluginLoadError`.

`context` provides:

- `plugin_id`, `plugin_type`, `configuration` (opaque mapping Core may set)  
- Typed `register_*` methods (see next section)

### Function-style skeleton

```python
from __future__ import annotations

from nova_layer.object_workflow.plugin_sdk import PluginRegistrationContext


def register(context: PluginRegistrationContext) -> None:
    # Match context.plugin_type to the register_* API you call.
    ...
```

### Class-style skeleton

```python
class Plugin:
    def register(self, context: PluginRegistrationContext) -> None:
        ...
```

Do **not** import Qt, mutate Domain `Project` aggregates, or reach into private manager/registry fields. Implement Port Protocols and register factories.

**Cleanup note:** Prefer releasing resources inside your provider/adapter objects (and any Core provider shutdown hooks those adapters implement). Do not rely on a plugin-level `shutdown()` callback as a guaranteed SDK workflow today — see §14 gaps.

Reference fixtures under `02_Source/tests/fixtures/plugins/` (`fake_inference`, `fake_matting`, `fake_host`) for shape — they use Core test doubles, not production models.

---

# 7. Registering Extension Points

Full method table: Plugin SDK Reference §5.3 / §7. Port field contracts: `00_Project/01_Implementation/03_ENGINE_INTERFACE_SPEC.md` and `nova_layer.object_workflow.ports`.

### Match type to API

| Manifest `plugin_type` | Allowed registration |
|---|---|
| `inference` | `context.register_inference(descriptor, factory, …)` |
| `matting` | `context.register_matting(descriptor, factory, …)` |
| `host_adapter` | `context.register_host_adapter(adapter_id, factory)` |

Calling the wrong `register_*` for your type raises `PluginValidationError`. Missing registry on the context raises `PluginRuntimeError`.

### Inference (conceptual)

```python
from nova_layer.object_workflow.ports.provider_registry import (
    ProviderCapabilities,
    ProviderDescriptor,
)

def register(context: PluginRegistrationContext) -> None:
    descriptor = ProviderDescriptor(
        provider_id="acme.example_inference",
        display_name="Example Inference",
        provider_version="1.0.0",
        # … remaining Port-required fields …
        capabilities=ProviderCapabilities(supports_cpu=True),
    )
    context.register_inference(descriptor, lambda _config: MyInferenceEngine())
```

### Matting / host

Same pattern: build the Port descriptor (or adapter id), pass a factory callable, register through context. Host adapters use `register_host_adapter(adapter_id, factory)`.

### Automation (optional)

When Core attaches Automation (desktop composition / tests):

| Method | Use |
|---|---|
| `register_automation_command(name, handler, …)` | Namespaced command; cannot override builtins |
| `provide_automation_helper(name, payload)` | Read-permission helper under `helper.{name}` |
| `subscribe_automation_events(listener)` | In-process event listener |

Command/event contracts: Automation Command Reference and Event Reference. Do not invent remote transports.

### What not to register

- Domain mutations as “plugin APIs”  
- Overrides of builtin Automation commands  
- Remote download hooks  

---

# 8. Packaging

Use Feature 12 helpers to produce a local `.nova-plugin` zip.

### `package.json`

Required conceptually: `package_format`, `plugin_id`, `version`, `sdk_version` — must align with `manifest.json`. Details: Schema Reference §6.

`build_nova_plugin_package` can synthesize `package.json` from the plugin manifest when you omit a custom package manifest.

### Build

```python
from pathlib import Path
from nova_layer.object_workflow.plugin_sdk import (
    build_nova_plugin_package,
    validate_plugin_package,
)

plugin_dir = Path("my_inference_plugin")
package = build_nova_plugin_package(plugin_dir, Path("dist/acme.example_inference"))
result = validate_plugin_package(package)
assert result.ok, result.errors
```

Rules enforced by validation include: both JSON files present, safe entry module, no symlink entry, archive path safety, SDK/format compatibility, matching ids/versions. See Schema Reference §7.4.

Offline only — the builder never downloads dependencies.

---

# 9. Installation

Local install root only (`ARCHITECTURE.md`: no marketplace).

```python
from pathlib import Path
from nova_layer.object_workflow.plugin_sdk import PluginPackageManager, PluginManager
from nova_layer.object_workflow.adapters.core_inference_registry import (
    build_default_core_inference_registry,
)

packages = PluginPackageManager(install_root=Path("/path/to/installed"))
record = packages.install(Path("dist/acme.example_inference.nova-plugin"))
# duplicate install without replace=True → PluginPackageInstallError
# packages.update(path) / packages.uninstall(plugin_id) also available

inference = build_default_core_inference_registry()
manager = PluginManager(
    plugin_roots=[],
    include_default_roots=False,
    install_roots=packages.install_root,
)
infos = manager.load_and_register(inference_registry=inference)
```

Default install root: `NOVA_PLUGIN_INSTALL_DIR` or `~/.nova_layer/plugins/installed` (`default_plugin_install_root`).

### Activation notes

- Fresh installs under the install root are discovered on the next `load_and_register`.  
- Additive load of one directory: `PluginManager.register_plugin_directory(plugin_dir)`.  
- Reloading an **already-registered** `plugin_id` may require **application restart** (documented implementation constraint).  
- Desktop OW composition may expose install helpers via the app controller; that is application wiring, not a second plugin architecture. Prefer SDK managers in scripts/tests.

---

# 10. Testing

Prefer the offline gate from the Developer Guide.

### Unit / integration patterns that exist today

1. **Manifest parse** — `load_manifest(plugin_dir)`.  
2. **Package validate** — `validate_plugin_package(path)`.  
3. **Register into registries** — construct `PluginManager` with isolated `plugin_roots` / `install_roots`, call `load_and_register(...)`, assert provider ids on registries and `PluginInfo.availability`.  
4. **Install lifecycle** — `PluginPackageManager.install` / `update` / `uninstall` (see `tests/test_object_workflow_plugin_package.py`).  

Fixture plugins: `02_Source/tests/fixtures/plugins/`.

```bash
cd 02_Source
source .venv/bin/activate
python -m pytest tests/test_object_workflow_plugin_sdk.py tests/test_object_workflow_plugin_package.py --tb=short
```

Do not claim GPU/`real_model` or commercial-host/`real_host` coverage unless those markers and artefacts are intentionally exercised.

---

# 11. Debugging

| Symptom | Check |
|---|---|
| Plugin missing from discovery | Child dir has `manifest.json`; root is on `plugin_roots` / `NOVA_PLUGINS_DIR` / install root |
| `PLUGIN_SDK_INCOMPATIBLE` | `sdk_version` must be `"1.0"` today |
| `PLUGIN_TYPE_UNSUPPORTED` / wrong register API | Align `plugin_type` with `register_*` |
| `PLUGIN_ENTRY_MISSING` / load error | `{entry_module}.py` next to manifest; simple `entry_module` name |
| `PluginDependencyError` | Every `optional_dependencies` entry importable in the environment |
| `failed` on `PluginInfo` | Read `failure_reason`; failures are **isolated** — Core still starts |
| Provider not listed after install | Call `load_and_register` / `register_plugin_directory`; restart if id was already registered |
| Package validation errors | Inspect `PackageValidationResult.errors` / `warnings` (checksum on dirs is ignored with warning) |
| Automation register fails | Automation registry/bus not attached yet — bind Automation before expecting those APIs |

Inspect loaded plugins:

```python
for info in manager.list_plugins():
    print(info.plugin_id, info.availability, info.lifecycle, info.failure_reason)
```

(`PluginInfo` fields: Plugin SDK Reference §5.2.)

---

# 12. Best Practices

1. Treat `01_PLUGIN_SDK_REFERENCE.md` as the API contract; keep this guide for workflow.  
2. Register only through `PluginRegistrationContext`.  
3. Keep `plugin_type` and registration APIs aligned.  
4. Declare accurate `optional_dependencies` — missing imports fail **that plugin**, not the whole app.  
5. Implement Ports; do not invent alternate Domain types or Schema versions.  
6. Ship `.nova-plugin` via `build_nova_plugin_package` for reproducible installs.  
7. After update of an already-loaded plugin, plan for restart.  
8. Put resource cleanup on provider/adapter instances Core already shuts down — do not depend on an undocumented plugin-level `shutdown()` hook.  
9. Use availability probes when the registration API supports them; do not assume GPU/host.  
10. Install only trusted local packages.  
11. Keep Automation extensions namespaced; never attempt builtin override.  
12. Keep opaque `configuration` documented in your plugin README — Core does not interpret your keys.

---

# 13. Common Pitfalls

| Pitfall | Why it fails / hurts |
|---|---|
| Putting `manifest.json` at the search root instead of in a child folder | Discovery looks for child directories with manifests |
| `entry_module`: `"plugin.py"` or `"pkg.plugin"` | Must be a simple name (`plugin`) |
| Mismatched `plugin_id` / `version` / `sdk_version` between `package.json` and `manifest.json` | Compatibility check fails |
| Declaring `plugin_type: "inference"` then calling `register_matting` | `PluginValidationError` |
| Expecting remote install / marketplace | Unsupported in Core |
| Expecting sandboxed execution | Plugins are trusted local code |
| Assuming hot reload always works | Already-registered ids may need restart |
| Mutating Domain / skipping OperationExecutor | Violates architecture; unsupported as SDK feature |
| Overriding builtin Automation commands | Rejected by registry rules |
| Leaving broken `optional_dependencies` | Plugin fails at dependency check |
| Relying on checksum for unpacked directories | Checksum is ignored with a warning for directories |
| Treating Phase 1 Schema 1.0 as Object Workflow | Separate bounded context |

---

# 14. Related Documents

| Document | Role |
|---|---|
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | Public SDK symbol / lifecycle reference |
| `05_Documents/API/04_SCHEMA_REFERENCE.md` | Manifest and package field validation |
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Commands plugins may extend |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Events for `subscribe_automation_events` |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API index |
| `05_Documents/Developer/00_DEVELOPER_GUIDE.md` | Environment and offline gate |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `00_Project/01_Implementation/03_ENGINE_INTERFACE_SPEC.md` | Port / engine contracts |
| `02_Source/tests/fixtures/plugins/` | Minimal working examples |

---

## Explicitly Out of Scope

- Private `discovery.py` / archive internals beyond documented managers  
- Qt / `ObjectWorkflowController` as the plugin authoring API  
- Remote marketplace, signed-store policies, or auto-update channels  
- Full Port field dictionaries (belong in engine/port references)  
- Invented scaffold generators or multi-plugin monorepo tooling  

## Documentation Gaps

- No first-party plugin template repository or `cookiecutter` in-tree.  
- No dedicated User-facing “Install plugin…” tutorial separate from this developer guide.  
- Production provider tutorials (real SAM2 / ONNX / commercial hosts) depend on optional `real_model` / `real_host` lanes and are **not** fully documented here.  
- `PluginManager.shutdown()` can call `record.instance.shutdown()` when an instance is stored, but the current register path does **not** persist the `Plugin()` instance on the record — plugin-authored `shutdown()` is therefore not a verified public workflow.  

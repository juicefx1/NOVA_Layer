# Plugin SDK Reference

## Status

Approved

## Audience

Plugin Author, Developer

## Authority

Authoritative **public** Plugin SDK reference for Object Workflow.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md` (§9 Plugin System, ADR-005)

API category index (do not duplicate):

- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`

Implementation exports:

- `nova_layer.object_workflow.plugin_sdk` (`__all__`)
- Additional package symbols re-exported from `nova_layer.object_workflow.plugin_sdk.package` where noted

## Scope

Document only **exported** Plugin SDK interfaces, extension points, lifecycle, and version rules. Internal discovery/import mechanics and registry internals are out of scope.

---

# 1. Introduction

The Plugin SDK lets third parties extend NOVA Layer **additively**:

- Register Core Inference, matting (precision extraction), or host adapters into Core registries  
- Optionally register Automation commands / event listeners  
- Validate, build, install, update, and uninstall local `.nova-plugin` packages  

Core builtins remain owned by Core. Plugin failures are isolated and must not abort application startup (`ARCHITECTURE.md` §9).

**Import root:**

```python
import nova_layer.object_workflow.plugin_sdk as plugin_sdk
```

There is **no** remote marketplace or download API.

---

# 2. Audience

| Audience | Use this document for |
|---|---|
| Plugin Author | Manifests, entrypoints, `PluginRegistrationContext`, packaging |
| Application Developer | `PluginManager` / `PluginPackageManager` public methods |
| Integrator | How plugins relate to Automation (commands/events) |

Provider Port contracts (`CoreInferenceEngine`, etc.) live under `nova_layer.object_workflow.ports` — see engine/port specs and `00_PUBLIC_API_OVERVIEW.md`.

---

# 3. Plugin SDK Overview

```text
.nova-plugin / plugin directory
        │
        ▼
PluginPackageManager (validate / install / update / uninstall)
        │  installs into local install root
        ▼
PluginManager.discover → validate → load → register
        │
        ▼
PluginRegistrationContext
        ├── register_inference(...)
        ├── register_matting(...)
        ├── register_host_adapter(...)
        ├── register_automation_command(...)
        ├── subscribe_automation_events(...)
        └── provide_automation_helper(...)
```

**Supported plugin types** (`SUPPORTED_PLUGIN_TYPES`):

- `inference`  
- `matting`  
- `host_adapter`  

**Entrypoint contract (plugin code):** the entry module must export either:

- `register(context: PluginRegistrationContext) -> None`, or  
- a `Plugin` class with instance method `register(context)`  

Registration must register at least one provider/adapter/command (empty registration fails).

**Cleanup:** Do not rely on a plugin-level `shutdown()` callback as a supported public workflow today. Prefer releasing resources inside provider/adapter instances (Core may call engine `shutdown`/`close` during `ObjectWorkflowService.shutdown()`). See Plugin SDK Guide and lifecycle notes below.

---

# 4. Public Modules

Prefer the top-level package. Submodules below are implementation locations of those exports.

| Public import | Role |
|---|---|
| `nova_layer.object_workflow.plugin_sdk` | Primary facade (`__all__` below) |
| `nova_layer.object_workflow.plugin_sdk.package` | Package-format helpers; includes a few symbols not re-exported at the top level |

### 4.1 Top-level `__all__` (`plugin_sdk`)

**Constants / env**

| Symbol | Meaning |
|---|---|
| `SDK_VERSION` | Current SDK contract version string (`"1.0"`) |
| `SUPPORTED_SDK_VERSIONS` | Allowed manifest `sdk_version` values |
| `SUPPORTED_PLUGIN_TYPES` | Allowed `plugin_type` values |
| `ENV_PLUGINS_DIR` | Env var name for extra plugin discovery roots (`NOVA_PLUGINS_DIR`) |
| `ENV_PLUGIN_INSTALL_DIR` | Env var name for package install root (`NOVA_PLUGIN_INSTALL_DIR`) |
| `PACKAGE_EXTENSION` | Archive suffix (`.nova-plugin`) |
| `PACKAGE_FORMAT_VERSION` | Current package format (`"1.0"`) |

**Core types / functions**

| Symbol | Kind |
|---|---|
| `PluginManifest` | Type |
| `load_manifest` | Function |
| `PluginInfo` | Type |
| `PluginRegistrationContext` | Type |
| `PluginManager` | Type |
| `PluginError` | Exception |
| `PluginValidationError` | Exception |
| `PluginLoadError` | Exception |
| `PluginRuntimeError` | Exception |
| `PluginDependencyError` | Exception |

**Package types / functions**

| Symbol | Kind |
|---|---|
| `PluginPackageManifest` | Type |
| `PackageValidationResult` | Type |
| `InstalledPluginRecord` | Type |
| `PluginPackageManager` | Type |
| `PluginPackageError` | Exception |
| `PluginPackageValidationError` | Exception |
| `PluginPackageCompatibilityError` | Exception |
| `PluginPackageInstallError` | Exception |
| `validate_plugin_package` | Function |
| `build_nova_plugin_package` | Function |
| `default_plugin_install_root` | Function |

### 4.2 Additional public exports on `plugin_sdk.package`

Available when importing `nova_layer.object_workflow.plugin_sdk.package` (not all are re-exported on the top-level facade):

| Symbol | Kind |
|---|---|
| `PACKAGE_MANIFEST_FILENAME` | Constant (`package.json`) |
| `SUPPORTED_PACKAGE_FORMATS` | Constant |
| `PackageCompatibilityReport` | Type |
| `check_package_compatibility` | Function |

---

# 5. Public Types

## 5.1 `PluginManifest`

Frozen dataclass describing `manifest.json` for a plugin directory.

| Field | Notes |
|---|---|
| `plugin_id` | Non-empty; no path separators / `..` |
| `display_name` | Required |
| `description` | Optional string |
| `version` | Required |
| `author` | Defaults to `"unknown"` if omitted |
| `sdk_version` | Must be in `SUPPORTED_SDK_VERSIONS` |
| `plugin_type` | One of `SUPPORTED_PLUGIN_TYPES` |
| `capabilities` | Non-empty tuple of strings (unknown capability **names** allowed for forward compatibility) |
| `entry_module` | Simple module name (no `.` / path separators); file is `{entry_module}.py` |
| `optional_dependencies` | Importable distribution/module names; missing → `PluginDependencyError` |
| `source_path` | Plugin directory when loaded from disk |

Property: `entry_file` → `source_path / f"{entry_module}.py"` when `source_path` is set.

### `load_manifest(plugin_dir: Path) -> PluginManifest`

Loads and structurally validates `manifest.json` from a plugin directory. Raises `PluginValidationError` on failure.

---

## 5.2 `PluginInfo`

Frozen diagnostic / UI view of a plugin (available or failed).

Notable fields: `plugin_id`, `display_name`, `description`, `version`, `author`, `sdk_version`, `plugin_type`, `capabilities`, `availability` (`"available"` \| `"unavailable"`), `failure_reason`, `lifecycle`, `source_path`, `configuration`.

Lifecycle values used in the SDK type system include:  
`discovered`, `validated`, `loaded`, `registered`, `available`, `unavailable`, `failed`, `shutdown`.

---

## 5.3 `PluginRegistrationContext`

DI surface plugins use during `register(context)`. Plugins must not hold or mutate Core registries outside this context.

**Constructor fields (set by Core):** `plugin_id`, `plugin_type`, `configuration`, plus optional registry/event handles.

**Public methods:**

| Method | Allowed when `plugin_type` is | Registers |
|---|---|---|
| `register_inference(descriptor, factory, *, availability_probe=None)` | `inference` | Core inference provider |
| `register_matting(descriptor, factory, *, availability_probe=None)` | `matting` | Precision extraction / matting provider |
| `register_host_adapter(adapter_id, factory)` | `host_adapter` | Host adapter |
| `register_automation_command(name, handler, *, permission="execute", description="")` | any (if automation attached) | Namespaced automation command |
| `subscribe_automation_events(listener)` | any (if event bus attached) | Automation event listener |
| `provide_automation_helper(name, payload)` | any (if automation attached) | Read-permission helper command under `helper.{name}` |

Wrong type / missing registry → `PluginValidationError` or `PluginRuntimeError`.

Descriptor/factory types come from Core registry/port packages (`ProviderDescriptor`, extraction descriptors, host factory types). Document Port fields in engine/port references — not duplicated here.

---

## 5.4 `PluginManager`

Discovers plugin directories, validates manifests, loads entry modules, and invokes registration.

**Construction (keyword args):** `plugin_roots`, `environ`, `cwd`, `configurations`, `include_default_roots`, `install_roots`, `include_install_root`.

**Public API:**

| Member | Role |
|---|---|
| `loaded` | Whether an initial `load_and_register` completed |
| `set_automation_registry(registry)` | Attach Automation command registry (optional) |
| `set_automation_event_bus(events)` | Attach Automation event bus (optional) |
| `set_plugin_configuration(plugin_id, configuration)` | Opaque config bag (Core stores; plugin interprets) |
| `get_plugin_configuration(plugin_id)` | Read stored config |
| `discover()` | Return discovered plugin directories |
| `load_and_register(*, inference_registry=None, extraction_registry=None, host_registry=None)` | Full discover→register; safe if already loaded |
| `register_plugin_directory(plugin_dir)` | Additive load of one directory (e.g. after install) |
| `list_plugins()` | `list[PluginInfo]` |
| `get_plugin(plugin_id)` | `PluginInfo \| None` |
| `shutdown()` | Marks plugin records `lifecycle=shutdown` and clears loaded modules. May call `record.instance.shutdown()` **only if** an instance was stored on the record — the current register path does **not** persist the `Plugin()` instance, so plugin-authored `shutdown()` is **not** a verified public callback |

Failures for individual plugins are recorded on `PluginInfo` (`failed` / `failure_reason`); they do not raise out of `load_and_register` / `register_plugin_directory` as fatal process errors.

---

## 5.5 Package types

### `PluginPackageManifest`

`package.json` contract (distinct from plugin `manifest.json`):  
`package_format`, `plugin_id`, `version`, `sdk_version`, optional `display_name` / `description` / `author` / `checksum_sha256`, `source_path`.  
Method: `to_dict()`.

### `PackageValidationResult`

Result of `validate_plugin_package`: `ok`, `package_path`, optional manifests, optional `compatibility`, `errors`, `warnings`. Method: `to_dict()`.

### `PackageCompatibilityReport` (`plugin_sdk.package`)

`compatible`, `reasons`, `sdk_version`, `package_format`, `plugin_type`. Method: `to_dict()`.

### `InstalledPluginRecord`

Installed package metadata: `plugin_id`, `version`, `sdk_version`, `plugin_type`, `display_name`, `install_path`, `package_format`, optional `source_package`, `installed_at`, `updated_at`.  
Methods: `to_dict()`, `from_dict(...)`.

---

## 5.6 `PluginPackageManager`

Local-only installer for `.nova-plugin` archives or package directories.

**Construction:** `install_root`, `workspace`, `environ` (optional). Uses `default_plugin_install_root` / workspace plugin install root when unset.

**Public API:**

| Member | Role |
|---|---|
| `install_root` | Property |
| `workspace` | Property |
| `validate(package_path)` | → `PackageValidationResult` (non-raising summary) |
| `inspect(package_path)` | Validate or raise `PluginPackageValidationError` |
| `list_installed()` | Installed records (workspace list or scan install root) |
| `get_installed(plugin_id)` | Single record or `None` |
| `install(package_path, *, replace=False)` | Install; duplicate without `replace` fails |
| `update(package_path)` | Replace existing install from package |
| `uninstall(plugin_id)` | Remove install + workspace records as applicable |

Installed trees are ordinary plugin directories discoverable by `PluginManager`.

---

## 5.7 Packaging helpers

### `validate_plugin_package(path) -> PackageValidationResult`

Validate archive or unpacked package (structure, manifests, entry module safety, compatibility). Does not install.

### `check_package_compatibility(package_manifest, plugin_manifest) -> PackageCompatibilityReport`

(`plugin_sdk.package`) Compare package.json vs manifest.json compatibility rules.

### `build_nova_plugin_package(plugin_dir, destination, *, package_manifest=None) -> Path`

Build a local `.nova-plugin` zip from a plugin directory. Offline only; never downloads.

### `default_plugin_install_root(*, environ=None) -> Path`

Resolve install root from `NOVA_PLUGIN_INSTALL_DIR` or `~/.nova_layer/plugins/installed`.

---

## 5.8 Errors

**SDK errors** (`PluginError` base with `.code` / `.message`):

| Type | Typical use |
|---|---|
| `PluginValidationError` | Manifest / type / duplicate id |
| `PluginLoadError` | Import / entrypoint |
| `PluginRuntimeError` | Registration / missing registry |
| `PluginDependencyError` | Missing `optional_dependencies` |

**Package errors** (`PluginPackageError` extends `PluginError`):

| Type | Typical use |
|---|---|
| `PluginPackageValidationError` | Invalid/unsafe package |
| `PluginPackageCompatibilityError` | Incompatible package/sdk |
| `PluginPackageInstallError` | Install/update/uninstall failure |

---

# 6. Plugin Lifecycle

High-level states (see `PluginInfo.lifecycle`):

```text
discovered → validated → loaded → registered → available
                 ↘ failed
available / * → PluginManager.shutdown (lifecycle marked shutdown; plugin callback not reliable)
```

| Stage | What happens (public contract) |
|---|---|
| Discover | Locate plugin directories (roots / env / install root) |
| Validate | `load_manifest` + entry file presence + optional deps |
| Load | Import entry module |
| Register | Call `register(context)` / `Plugin.register` |
| Available | Registration succeeded; listed as available when healthy |
| Failed | Isolated failure; Core continues |
| Shutdown | `PluginManager.shutdown()` sets lifecycle `shutdown` and clears modules; plugin-level `shutdown()` is **not** reliably invoked (instance not retained after `register`) |

**Package lifecycle (separate):** validate → install/update into install root → optionally `PluginManager.register_plugin_directory` / restart for reload of already-registered plugins.

Reloading an already-registered plugin in-process may require application restart (implementation constraint; not a second plugin architecture).

---

# 7. Extension Points

| Extension point | Plugin type | Context API |
|---|---|---|
| Core Inference provider | `inference` | `register_inference` |
| Matting / precision extraction provider | `matting` | `register_matting` |
| Host adapter | `host_adapter` | `register_host_adapter` |
| Automation command | any (automation attached) | `register_automation_command` |
| Automation event listener | any (bus attached) | `subscribe_automation_events` |
| Automation helper descriptor | any | `provide_automation_helper` |

**Known capability name vocabulary** (non-exhaustive hinting; unknown strings allowed):  
`sam2`, `onnx`, `gpu`, `cpu`, `mps`, `alpha_matting`, `photoshop_host`, `filesystem_host`, `reveal_host`, `open_file_host`  
(Constant `KNOWN_CAPABILITIES` exists in SDK constants module; not re-exported on top-level `__all__`.)

**Non-extension points (unsupported as SDK features):**

- Mutating Domain `Project` from a plugin  
- Bypassing `OperationExecutor` for generate/extract  
- Remote plugin download / marketplace  
- Overriding builtin Automation commands  

---

# 8. Manifest and Version Compatibility

## 8.1 Plugin `manifest.json` (SDK)

Required conceptual fields (validated by `load_manifest` / `parse_manifest`):

- `plugin_id`, `display_name`, `version`, `sdk_version`, `plugin_type`, `entry_module`, `capabilities` (≥1)  
- Optional: `description`, `author`, `optional_dependencies`

Rules:

- `sdk_version ∈ SUPPORTED_SDK_VERSIONS` (currently `{"1.0"}`)  
- `plugin_type ∈ SUPPORTED_PLUGIN_TYPES`  
- `entry_module` must be a simple name; entry file `{entry_module}.py` must exist for load  

## 8.2 Package `package.json` (Feature 12)

Required conceptual fields for packages:

- `package_format`, `plugin_id`, `version`, `sdk_version`  
- Optional metadata / `checksum_sha256`  

Rules:

- `package_format ∈ SUPPORTED_PACKAGE_FORMATS` (currently `{"1.0"}`)  
- Must align with plugin `manifest.json` (`plugin_id`, `version`, `sdk_version`) via compatibility checks  
- Archives: path traversal and symlink members are rejected during validation/extract  

## 8.3 Version matrix (current Core)

| Surface | Current value |
|---|---|
| `SDK_VERSION` | `"1.0"` |
| `PACKAGE_FORMAT_VERSION` | `"1.0"` |
| Object Workflow Project schema | `"2.0"` (separate from SDK; plugins must not invent a second Project schema) |

Distribution package version (`nova-layer` in `pyproject.toml`) is **not** the Plugin SDK version.

---

# 9. Best Practices

1. Register only through `PluginRegistrationContext`; never reach into private manager state.  
2. Match `plugin_type` to the registration APIs you call.  
3. Keep `optional_dependencies` accurate — missing imports fail the plugin, not the app.  
4. Treat configuration as opaque JSON-compatible data; document your keys in your plugin README.  
5. Prefer Ports + descriptors/factories Core already understands; do not invent alternate Domain types.  
6. Ship as `.nova-plugin` built with `build_nova_plugin_package` for reproducible local install.  
7. After `install`/`update`, expect activation via `register_plugin_directory` or restart when a plugin id was already loaded.  
8. Put resource cleanup on provider/adapter objects (and any engine `shutdown`/`close` hooks Core already calls) — do **not** depend on plugin-level `shutdown()` being invoked.  
9. Do not assume GPU/host capabilities exist; use availability probes where the registration API supports them.  
10. Plugins execute as **trusted local code** (no sandbox) — only install packages you trust.

---

# 10. Related Documents

| Document | Role |
|---|---|
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | All public API categories |
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Automation commands plugins may extend |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Event types for `subscribe_automation_events` |
| `05_Documents/API/04_SCHEMA_REFERENCE.md` | Project Schema 2.0 + package schema index |
| `05_Documents/Developer/06_PLUGIN_SDK_GUIDE.md` | Authoring workflow guide |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `00_Project/01_Implementation/03_ENGINE_INTERFACE_SPEC.md` | Port/request contracts for providers |
| `nova_layer.object_workflow.ports` | Protocol imports for provider authors |

---

## Explicitly Excluded (Internal)

Not part of the supported public Plugin SDK surface:

- `discovery.py`, archive extract helpers, install dirname sanitizers (except via documented managers/helpers)  
- `PluginRecord`, `OpenedPackage`, `invoke_plugin_register`, `validate_manifest_filesystem` (manager internals)  
- Direct use of Core registry classes except as types passed into `PluginRegistrationContext` methods  
- Qt / `ObjectWorkflowController` wiring  
- Phase 1 Smart Layer plugin mechanisms (if any) outside `object_workflow.plugin_sdk`

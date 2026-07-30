# Product Feature 12 — Plugin Package Management

## Status

Approved (specification completed to match the implemented local package system).

---

# Goal

Introduce a local plugin package format (`.nova-plugin`) for install, uninstall,
update, validation, and compatibility checks — without an online marketplace.

Packages feed the existing Plugin SDK discovery path. They never replace the SDK.

---

# Architectural Authority

Must preserve:

- ARCHITECTURE.md
- Domain
- Schema 2.0
- Plugin SDK
- Workspace
- Runtime Architecture
- Registry Architecture

---

# Philosophy

Plugin packages are distribution units.

Plugin SDK remains the runtime contract (`manifest.json`, entry module,
`register(context)`).

Core must not download packages or install Python dependencies automatically.

---

# Package Format

Extension: `.nova-plugin`

Container: ZIP archive (unpacked directories accepted for validation/tests).

Required members:

```text
package.json      # Feature 12 package manifest
manifest.json     # Feature 9 Plugin SDK manifest
<entry_module>.py
```

Optional: `resources/`, `models/`, `README.md`

---

# package.json

Required fields:

- `package_format` — currently `"1.0"`
- `plugin_id` — must match `manifest.json`
- `version` — must match `manifest.json`
- `sdk_version` — must match `manifest.json` and Core `SUPPORTED_SDK_VERSIONS`

Optional:

- `display_name`, `description`, `author`
- `checksum_sha256` — when present, verified for archive files

Unsupported `package_format` values are rejected.

---

# Validation Process

1. Path exists (archive or directory)
2. Safe ZIP extract (reject `..`, absolute paths, escape outside destination)
3. Parse/validate `package.json`
4. Parse/validate `manifest.json` via Plugin SDK
5. Entry module file present
6. Optional checksum verification
7. Compatibility report: format, SDK, plugin type, id/version/sdk consistency

Invalid packages are refused before install.

---

# Lifecycle Operations

`PluginPackageManager` supports:

- `validate` / `inspect`
- `install` (local path only; `replace=False` by default)
- `update` (requires already installed; replaces payload)
- `uninstall` (removes install directory + workspace record)
- `list_installed` / `get_installed`

Install root defaults to `~/.nova_layer/plugins/installed/` or
`NOVA_PLUGIN_INSTALL_DIR`.

---

# Workspace Integration

Workspace stores:

- `plugin_install_root`
- `installed_plugins[]` metadata

Workspace never stores Project schema payloads or runtime GPU sessions.

Uninstall clears selected plugin id and plugin configuration for that id when
present.

---

# Runtime Behaviour

Installed packages are discovered by `PluginManager` through the install root —
the same discovery mechanism as developer `plugins/` trees.

No second plugin architecture.

Activation of a newly installed plugin may register immediately when the plugin
id is not already loaded; reloading an already-registered plugin requires
application restart.

---

# Security

- Local filesystem sources only
- No remote download / marketplace
- Path traversal rejected
- Plugins still execute as trusted local code (no sandbox) — same as Feature 9

---

# Out of Scope

- Online marketplace
- Remote updates
- Code signing / publisher trust store
- Automatic dependency installation
- Dedicated install UI (may be added later without changing this contract)

---

# Testing

Required:

- Valid package build/validate
- SDK mismatch rejection
- package/plugin id mismatch rejection
- ZIP traversal rejection
- Install / update / uninstall + workspace records
- Discovery of installed package by PluginManager
- Controller install activation path

---

# Acceptance Criteria

Complete when:

- `.nova-plugin` format defined and implemented
- validate / install / update / uninstall work locally
- compatibility checks enforced
- Workspace records install metadata
- Plugin SDK preserved
- Domain / Schema 2.0 unchanged
- Regression suite passes

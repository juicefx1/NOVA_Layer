# User Guide

## Status

Approved

## Audience

End User

## Authority

Primary everyday manual for the desktop **Object Workflow** window.

Product behaviour follows the running app. First successful path:

- [Getting Started](00_GETTING_STARTED.md)

Architecture (technical; not required for normal use):

- `00_Project/01_Implementation/ARCHITECTURE.md`

## Scope

Day-to-day interactive Object Workflow: projects, images, intent, candidates, confirmation, extraction, save/reopen, export/delivery, plus short overviews of Batch and Plugins.

Does **not** replace Getting Started, and does **not** document Smart Layer welcome **Create Project** / **Open Project** as the Object Workflow path.

---

# 1. Introduction

This guide is for regular work in **NOVA Layer · Object Workflow**.

If you have never finished one export yet, start with [Getting Started](00_GETTING_STARTED.md), then return here for controls you will use every day.

**What you will do in this window**

- Create or open an Object Workflow project  
- Load a source image and mark Artist Intent  
- Generate and compare candidates  
- Confirm one result, then extract and export a PNG layer  
- Optionally save a `.nova` project, run a batch queue, or review discovered plugins  

Buttons enable only when the current step allows them. Greyed-out actions usually mean an earlier step is still required.

---

# 2. Understanding the Object Workflow

Object Workflow is the interactive **schema 2.0** path for isolating one object from an image.

Typical order:

```text
Create / open project
  → Load Source
  → Draw intent → Apply
  → Generate → select candidate
  → Confirm
  → Extract
  → Export PNG (and/or Save project)
```

**Confirmation matters.** Candidates and extractions are not final until you press **Confirm**. The app will not silently treat AI output as your confirmed object.

**Two different “Create Project” buttons**

| Where | What it does |
|---|---|
| Welcome screen **Create Project** | Older Smart Layer flow — **not** this guide |
| Object Workflow window **Create Project** | Starts an Object Workflow project (name only) |

Always open Object Workflow with the welcome button **Object Workflow**.

**Workspace vs project**

- A **project** (`.nova`) holds your image, intent, candidates, confirmation, and extractions.  
- The **workspace** remembers recent projects, layout preferences, and related app session data — it is not your artwork file. See [Workspace Guide](02_WORKSPACE_GUIDE.md).

---

# 3. Creating and Opening Projects

### Create a new project

1. From the welcome screen, click **Object Workflow**.  
2. In **NOVA Layer · Object Workflow**, click **Create Project**.  
3. Enter a **Project name** when prompted.

The project starts in memory. Use **Save** later to write a `.nova` package to disk.

### Open an existing project

Inside the Object Workflow window:

1. Click **Load Project**.  
2. In **Open Object Workflow Project (.nova)**, choose the `.nova` **folder** (directory picker).

Other ways to return to work:

| Control | Where | Use |
|---|---|---|
| **Recent Projects** list | Welcome and/or Object Workflow | Double-click / select a recent `.nova` path |
| **Reopen Last Workspace** | Welcome | Reopen the last Object Workflow project when available |
| **Reopen Last** | Object Workflow toolbar | Reopen last project from this window |

If welcome buttons are disabled, open **Details** and see [Troubleshooting](05_TROUBLESHOOTING.md).

---

# 4. Working with Images

### Load a source

1. Click **Load Source**.  
2. Choose a file in **Load Source Image**.  

Accepted types: **PNG** and **JPEG** (`*.png`, `*.jpg`, `*.jpeg`).

The main viewer shows the image. Placeholder text before load: *Create a project and load a PNG or JPEG source*.

### Core Inference provider

The **Core Inference** combo selects which inference provider generates candidates (built-in and any discovered plugins). A **device** hint may appear next to the combo. Changing providers affects later **Generate** runs; it does not replace a confirmation you already made.

If generation quality looks wrong, check the selected provider and [Troubleshooting](05_TROUBLESHOOTING.md). GPU/model availability depends on your install.

---

# 5. Artist Intent

Artist Intent is the guidance you draw on the image: points and/or a box that describe the object.

### Drawing tools

| Button | Action |
|---|---|
| **+ Point** | Add positive (include) points |
| **− Point** | Add negative (exclude) points |
| **Move Point** | Drag an existing point |
| **Remove Point** | Click to remove a point |
| **Box Mode** | Drag a bounding box |
| **Remove Box** | Clear the box |
| **Clear Points** | Remove all points |

Right-click in point/box modes can also remove nearby guidance (as implemented in the viewer).

### Apply or discard

| Button | Action |
|---|---|
| **Apply** | Commit guidance as the current Artist Intent |
| **Cancel** | Discard unsaved viewer edits |

Status may show an **editing** hint while guidance changes are not yet applied.

**Generate** stays unavailable until intent is applied. Changing intent and applying again revises guidance for the next generation (previous unconfirmed results may no longer match — generate again after meaningful edits).

---

# 6. Candidate Generation

### Generate

1. Click **Generate**.  
2. Watch the progress bar / busy label (for example **Generating hypothesis…**).  
3. Review the **Candidates** strip when it fills.

Use **Cancel Operation** to stop an in-flight generate or extract when that button is enabled.

### Select and compare candidates

Section heading: **Candidates**.

- **Click** a chip to select it  
- **Hover** to preview on the image  
- **← / →** browse · **1–9** jump · **Enter** select · **Esc** clear preview · **Space** momentary compare  
- **Compare** toggle — compare active vs focused candidate  

Empty strip message: *No candidates — Generate to produce a set*.

### Generation History

Section **Generation History** lists past generations (sequence, intent revision, provider, candidate count, status).

| Button | Typical use |
|---|---|
| **Reject** / toolbar **Reject Generation** | Reject the active generation |
| **Generate Again** | Run another generation from current intent |
| **Reactivate** | Bring back a previous generation when allowed |

Use history when you want to retry or return to an earlier set instead of starting over from scratch.

---

# 7. Confirmation and Extraction

### Confirm

1. Select the candidate you want.  
2. Click **Confirm**.  

After confirmation, extraction and project save become available. This step creates the confirmed object record the product requires before extraction.

### Precision Extraction settings

Before or after the first extract, you can adjust:

| Control | Role |
|---|---|
| **Precision Extraction** combo | Extraction / matting provider |
| **feather**, **blur**, **cleanup**, **expand** | Edge refinement |
| **Backend** | **Color Affinity** or **Neural ONNX** |
| **Unknown Edge**, **Refine** | Matting refinement |
| **Preserve Known Regions** | Keep known regions during matting |

Status lines may show provider or neural-matting notes under these controls.

### Extract

1. Click **Extract**.  
2. Wait for completion (busy text such as **Generating extraction…**).  
3. Inspect **Extraction Preview** (placeholder before success: *No extraction yet*).

You can change settings and extract again. Confirmation remains the gate before extraction is allowed.

---

# 8. Saving and Reopening Projects

### Save

1. Click **Save** (enabled after confirmation / when the project can be persisted).  
2. In **Save Object Workflow Project**, choose a location.  
3. Use filter **NOVA Project (*.nova)**. A `.nova` suffix is added if missing.

A `.nova` project is a **folder** containing project data and assets. Saving also updates recent-project lists used by the workspace.

### Reopen

- **Load Project** — pick the `.nova` directory  
- **Recent Projects** — pick a known path  
- **Reopen Last** / welcome **Reopen Last Workspace** — jump back when a last project exists  

### Workspace helpers in this window

| Button | Effect |
|---|---|
| **Restore Layout** | Restore saved window/layout preferences from the workspace |
| **Reset Workspace** | Clears workspace preferences and recent projects after confirmation; **does not delete** `.nova` files on disk |

Dialog title: **Reset Workspace**. Details: [Workspace Guide](02_WORKSPACE_GUIDE.md).

---

# 9. Exporting Results

### Export PNG (primary deliverable)

1. Click **Export PNG** under **Delivery**.  
2. In **Export Committed Extraction**, choose a path (**PNG Image (*.png)**).  
3. If the file exists, answer **Overwrite Export?**  

This writes a transparent PNG layer. It does **not** replace **Save** for reloadable project state.

### Other delivery actions

Available when an extraction can be exported:

| Button | Use |
|---|---|
| **Reveal Asset** | Show the extraction asset in the system file browser |
| **Copy Path** | Copy the filesystem path |
| **Copy File URI** | Copy a `file://` URI |
| **Send to Host** | Deliver via the selected **Host** adapter and **Action** |

Host options depend on what is installed and available on your machine. Commercial hosts are optional; if **Send to Host** fails or stays unavailable, you can still use **Export PNG**. See [Troubleshooting](05_TROUBLESHOOTING.md) and [FAQ](06_FAQ.md).

Summary labels under Delivery show the last delivery state (for example *No delivery yet*).

---

# 10. Batch Processing Overview

The **Batch** section queues many images through the same confirmation and extraction ideas as the single-image workflow.

| Control | Role |
|---|---|
| **Add Images** | Choose multiple PNG/JPEG files |
| **Start Batch** | Run the queue |
| **Cancel Batch** | Stop the running batch |
| **Retry Failed** | Retry failed items when available |
| **Automatic confirmation** | Opt-in only; when off, batch waits for normal interactive confirmation |

Default posture is **interactive** confirmation. Automatic confirmation is optional and must be enabled deliberately.

Full steps, modes, and recovery: [Batch Guide](03_BATCH_GUIDE.md).

---

# 11. Plugins Overview

The **Plugins** section shows a summary of discovered plugins (for example *No plugins discovered*, or a short status string when plugins are loaded).

In the current Object Workflow window this area is **status only** — there is no Install button in this panel. Local `.nova-plugin` install and management details belong in [Plugin User Guide](04_PLUGIN_USER_GUIDE.md).

When plugins are present they may appear as extra choices under **Core Inference**, **Precision Extraction**, or **Host**, depending on plugin type.

---

# 12. Common Workflow Tips

1. Prefer **Object Workflow** on the welcome screen for this product path.  
2. **Apply** intent before every meaningful **Generate**.  
3. Use hover / **Compare** before **Confirm** — confirmation is intentional.  
4. **Save** early after confirmation if you may reopen the session later.  
5. Use **Export PNG** for delivery; use **Save** for a reloadable project.  
6. Prefer **Cancel Operation** / **Cancel Batch** over force-quitting when something is busy.  
7. After changing Core Inference or Precision Extraction providers, generate or extract again as needed.  
8. Keep **Automatic confirmation** off unless you understand the batch guide implications.  
9. **Reset Workspace** clears preferences and recents only — it does not delete `.nova` packages.  
10. If a control stays grey, finish the previous step (load → apply → generate → select → confirm → extract).  

Problems and recovery: [Troubleshooting](05_TROUBLESHOOTING.md) · [FAQ](06_FAQ.md).

---

# 13. Related Guides

| Guide | When to open it |
|---|---|
| [00_GETTING_STARTED.md](00_GETTING_STARTED.md) | First successful export |
| [02_WORKSPACE_GUIDE.md](02_WORKSPACE_GUIDE.md) | Recent projects, layout, reset workspace |
| [03_BATCH_GUIDE.md](03_BATCH_GUIDE.md) | Multi-image queues and confirmation modes |
| [04_PLUGIN_USER_GUIDE.md](04_PLUGIN_USER_GUIDE.md) | Local plugin packages |
| [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md) | Errors and recovery |
| [06_FAQ.md](06_FAQ.md) | Short answers |

---

## Out of scope for this manual

- Smart Layer welcome **Create Project** / **Open Project** as the daily OW path  
- Developer install from source (see Developer Guide)  
- Automation scripting / Plugin SDK authoring  
- Guarantees about GPU quality or specific commercial host versions  

## Documentation gaps

- [Workspace](02_WORKSPACE_GUIDE.md), [Batch](03_BATCH_GUIDE.md), [Plugin](04_PLUGIN_USER_GUIDE.md), [Troubleshooting](05_TROUBLESHOOTING.md), and [FAQ](06_FAQ.md) may still be stubs until filled.  
- End-user plugin **install UI** is not present in the Object Workflow Plugins panel today (status summary only).  
- Host delivery behaviour varies by adapter availability on each machine.  

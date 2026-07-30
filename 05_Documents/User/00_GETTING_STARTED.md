# Getting Started

## Status

Approved

## Audience

End User

## Authority

First-run guide for completing one basic **Object Workflow** from launch through exporting a layer.

Product behaviour follows the running desktop app and:

- `00_Project/01_Implementation/ARCHITECTURE.md` (Object Workflow goals and confirmation rules)

Detailed usage beyond this first success path:

- `05_Documents/User/01_USER_GUIDE.md`
- `05_Documents/User/02_WORKSPACE_GUIDE.md`
- `05_Documents/User/05_TROUBLESHOOTING.md`
- `05_Documents/User/06_FAQ.md`

## Scope

Minimum steps for a first successful interactive Object Workflow: create project → load image → intent → generate → select → confirm → extract → export PNG.

Does **not** cover batch processing, host delivery, end-user plugin installation UI, or the older Smart Layer “Create Project” path on the welcome screen.

---

# 1. Introduction

NOVA Layer’s Object Workflow helps you isolate one object from a source image:

1. Load a PNG or JPEG  
2. Mark what you mean (points and/or a box)  
3. Generate candidates  
4. **Confirm** the one you want  
5. Generate a precision extraction  
6. Export a transparent PNG layer  

Confirmation is deliberate: the app will not treat AI output as final until you press **Confirm**.

This guide walks that path once. For deeper controls, see the [User Guide](01_USER_GUIDE.md).

---

# 2. Prerequisites

| Need | Notes |
|---|---|
| Desktop app install | Python **3.12**, package extras including desktop/Qt (see Developer Guide if you build from source) |
| Launch | From the source tree: `python -m nova_layer` (application name: **NOVA Layer**) |
| Image | One **PNG** or **JPEG** (`.png`, `.jpg`, `.jpeg`) |
| Display | Buttons on the welcome screen stay disabled if startup diagnostics report failures — open **Details** or see [Troubleshooting](05_TROUBLESHOOTING.md) |

**Assumption for this guide:** you can open the welcome window and click **Object Workflow**. GPU / commercial host setups are optional and not required for this first path.

---

# 3. Creating a Project

1. Launch NOVA Layer. You see the welcome card (**NOVA LAYER**).  
2. Click **Object Workflow** (not the welcome-screen **Create Project** — that opens the older Smart Layer flow).  
3. A window titled **NOVA Layer · Object Workflow** opens.  
4. In that window, click **Create Project**.  
5. Enter a **Project name** when prompted, then accept.

Your project exists in memory. Nothing is written to disk until you later use **Save** (optional for this first export).

Next: load a source image. **Load Source** stays unavailable until a project exists.

---

# 4. Loading an Image

1. Click **Load Source**.  
2. In **Load Source Image**, choose a PNG or JPEG.  
3. The image appears in the viewer.

You can now edit guidance (intent) on the image.

Supported filter in the dialog: `Images (*.png *.jpg *.jpeg)`.

---

# 5. Creating Artist Intent

Artist Intent tells the model what object you care about.

1. Choose a drawing mode, for example:  
   - **+ Point** — positive clicks (include)  
   - **− Point** — negative clicks (exclude)  
   - **Box Mode** — drag a box around the object  
2. Click or drag on the image to place guidance.  
3. Click **Apply** to commit the intent.

Until you **Apply**, Generate stays unavailable. Use **Cancel** if you want to discard unsaved guidance edits.

You need at least some applied guidance before generation can run.

---

# 6. Generating Candidates

1. Click **Generate**.  
2. Wait while the status shows generation in progress (for example **Generating hypothesis…**).  
3. When finished, the **Candidates** strip fills with options.

If generation fails or stalls, use **Cancel Operation** if it is enabled, then see [Troubleshooting](05_TROUBLESHOOTING.md).

Optional later: **Generate Again** / **Reject Generation** — covered in the [User Guide](01_USER_GUIDE.md).

---

# 7. Selecting a Candidate

1. In **Candidates**, click the candidate that best matches your object (active selection uses a clear highlight).  
2. Hover to preview; use arrow keys or number keys if you prefer keyboard browsing.

Tooltip summary in the app: click to select · hover to preview · arrows browse · Enter select · Space compare.

Pick one candidate before confirming.

---

# 8. Confirming the Selection

1. Click **Confirm**.  

This records your choice as the confirmed object. Extraction and project save become available only after confirmation — the product does not auto-confirm.

---

# 9. Generating an Extraction

1. Click **Extract**.  
2. Wait for extraction to finish (status such as **Generating extraction…**).  
3. Check the **Extraction Preview** panel for the RGBA result.

You can adjust Precision Extraction settings and extract again later; for a first success, the defaults are enough. Details: [User Guide](01_USER_GUIDE.md).

---

# 10. Exporting a Layer

1. Click **Export PNG**.  
2. In **Export Committed Extraction**, choose where to save.  
3. Confirm overwrite if the file already exists (**Overwrite Export?**).  

You get a **PNG** file (transparent layer). The dialog filter is `PNG Image (*.png)`.

**Export PNG** is not the same as **Save**:

| Action | Result |
|---|---|
| **Export PNG** | A deliverable `.png` layer |
| **Save** | A reloadable **NOVA Project (`.nova`)** package (folder with project data) |

Saving is recommended after your first success so you can reopen from **Recent Projects** later ([Workspace Guide](02_WORKSPACE_GUIDE.md)).

---

# 11. Next Steps

| Goal | Where to go |
|---|---|
| Full interactive controls (history, compare, settings) | [User Guide](01_USER_GUIDE.md) |
| Recent projects, reopen last, reset workspace | [Workspace Guide](02_WORKSPACE_GUIDE.md) |
| Many images in a queue | [Batch Guide](03_BATCH_GUIDE.md) |
| Plugin status in Object Workflow (no install UI in that panel) | [User Guide](01_USER_GUIDE.md) § Plugins Overview · [Plugin User Guide](04_PLUGIN_USER_GUIDE.md) (placeholder) |
| Problems and recovery | [Troubleshooting](05_TROUBLESHOOTING.md) · [FAQ](06_FAQ.md) |

---

# 12. Troubleshooting

| Problem | What to try |
|---|---|
| Welcome buttons greyed out | Open **Details** on the welcome page; fix startup diagnostics; see [Troubleshooting](05_TROUBLESHOOTING.md) |
| Used welcome **Create Project** by mistake | Close that path and click **Object Workflow** instead |
| **Load Source** disabled | Create a project inside the Object Workflow window first |
| **Generate** disabled | Draw guidance and click **Apply** |
| **Confirm** disabled | Generate candidates and select one |
| **Extract** disabled | Click **Confirm** first |
| **Export PNG** disabled | Finish extraction successfully first |
| Wrong image type | Use PNG or JPEG only |
| Want to keep work | Use **Save** → **NOVA Project (`.nova`)** |

More cases: [Troubleshooting](05_TROUBLESHOOTING.md), [FAQ](06_FAQ.md).

---

# 13. Related Documents

| Document | Role |
|---|---|
| [01_USER_GUIDE.md](01_USER_GUIDE.md) | Full interactive Object Workflow |
| [02_WORKSPACE_GUIDE.md](02_WORKSPACE_GUIDE.md) | Workspace and recent projects |
| [03_BATCH_GUIDE.md](03_BATCH_GUIDE.md) | Batch processing |
| [04_PLUGIN_USER_GUIDE.md](04_PLUGIN_USER_GUIDE.md) | Plugins for end users (placeholder; OW panel is status-only today) |
| [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md) | Errors and recovery |
| [06_FAQ.md](06_FAQ.md) | Short answers |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Product architecture (technical) |
| `05_Documents/Developer/00_DEVELOPER_GUIDE.md` | Build/run from source |

---

## Notes for this first-run path

- Host buttons such as **Send to Host** / **Reveal Asset** are optional after export; not required for a first PNG.  
- Batch **Automatic confirmation** is opt-in and outside this guide.  
- Exact inference quality depends on the configured provider/model on your machine.  

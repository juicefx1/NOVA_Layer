# 04_PROJECT_STRUCTURE

**Status:** Superseded as an architecture specification  
**Audience:** Maintainer (historical pointer)

---

## Authority

Logical architecture for NOVA Layer is defined **only** in:

**[`ARCHITECTURE.md`](./ARCHITECTURE.md)**

Do not treat this file as a second architecture source of truth.

---

## What This File Was

Version 0.1 draft describing logical layers under older terminology:

- Presentation → Application → Domain → **Engine** → **Infrastructure**

That vocabulary is retired. The authoritative mapping is:

| Historical term in this draft | Current term in `ARCHITECTURE.md` |
|---|---|
| Engine Interface | Ports |
| Engine / Engine Provider | Adapters / Providers |
| Infrastructure (I/O, serialization, provider adapters) | Adapters (+ Application persistence helpers) |

Physical repository layout is documented in:

`05_Documents/Developer/01_PROJECT_STRUCTURE.md`

---

## Retention

This stub remains so existing links to `04_PROJECT_STRUCTURE.md` resolve.

For any architecture question, open `ARCHITECTURE.md`.

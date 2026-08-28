# org-workspace vs orgparse vs organice

> A factual comparison for developers who work with org-mode files in Python.

All three libraries solve different problems. This page helps you pick the right one.

---

## TL;DR

| Capability | orgparse | organice | org-workspace |
|-----------|---------|---------|---------------|
| Parse org files | ✅ | ✅ (via JS) | ✅ (via orgparse fork) |
| Write / mutate org files | ❌ | ✅ (in-browser) | ✅ |
| Python library | ✅ | ❌ (JS/TS) | ✅ |
| Multi-file workspace | ❌ | ❌ | ✅ |
| Atomic task claiming | ❌ | ❌ | ✅ |
| Concurrency primitives | ❌ | ❌ | ✅ |
| GTD query layer | ❌ | ❌ | ✅ |
| Dependency DAG (Plan) | ❌ | ❌ | ✅ |
| AI agent integration | ❌ | ❌ | ✅ |
| Round-trip safe serialization | ⚠️ partial | ✅ (JS) | ✅ |

---

## orgparse

[orgparse](https://github.com/karlicoss/orgparse) is a mature, well-tested Python parser for org-mode. It's the right choice if you want to **read** org files and don't need to write back.

**Strengths:**
- Battle-tested and widely used
- Clean, Pythonic API for reading headings, properties, and text
- Good performance on large files

**Limitations:**
- Read-only: no write support in the upstream library (PR #77 adds it but hasn't merged)
- No multi-file workspace concept
- No query layer for GTD patterns
- No concurrency support

**When to use:** Reporting, analytics, read-only tooling over org files.

org-workspace includes a vendored fork of orgparse with write support from PR #77. If your project already depends on orgparse for reading, org-workspace is a compatible upgrade path.

---

## organice

[organice](https://github.com/200ok-ch/organice) is a web application for editing org-mode files in a browser, with sync support for Dropbox, WebDAV, and Nextcloud. It's a frontend tool, not a Python library.

**Strengths:**
- Clean mobile and desktop web interface
- Real org-mode support including agenda, TODO states, and tags
- Sync integrations with common file storage services

**Limitations:**
- JavaScript/TypeScript only — no Python API
- Designed for human editing, not programmatic access
- No agent integration, task claiming, or batch operations

**When to use:** You want a Dropbox-synced org agenda in a browser.

---

## org-workspace

org-workspace is a **Python library for AI agents and automation** that need to read, write, and reason over org-mode files. It was built to let autonomous agents safely coordinate over a shared task system without stepping on each other.

**Strengths:**
- Full read/write Python API
- Multi-file workspace with dirty-file tracking
- Concurrency primitives for multi-agent coordination (TaskClaim, OptimisticLock, FileLock)
- GTD query layer (agenda, deadlines, overdue, next_action, ai_tasks)
- Dependency DAG with topological sort (Plan)
- Round-trip safe serialization: unmodified files are never rewritten
- GTD and nightshift state configurations out of the box
- Content-addressed ID generation with dedup detection

**Limitations:**
- Newer project (v0.5.3, Beta) — fewer real-world deployments than orgparse
- No standalone CLI
- No browser or sync interface

**When to use:** Building AI agents, automation pipelines, or developer tools that need to read and write org-mode task lists programmatically.

---

## Feature deep-dive: write safety

One reason to choose org-workspace over rolling your own orgparse wrapper: write safety is surprisingly hard.

The naive approach — read → modify in-memory → serialize → write — routinely causes subtle bugs: property drawers getting duplicated, timestamps reformatted, tags reordered, or entire lines truncated on long values. These bugs don't fail loudly; they corrupt your files silently.

org-workspace's serializer is designed around the round-trip invariant: a file that's loaded and immediately saved must produce byte-identical output for unchanged nodes. This is validated in the test suite on real org files. The `CatastrophicShrinkError` guard will refuse to write a file that's significantly smaller than the original, catching serializer regressions before they reach disk.

---

## FAQ

**Can I use org-workspace alongside orgparse?**  
Yes. org-workspace vendors its own copy of orgparse internally, so there's no conflict. You can use the upstream orgparse for reading and org-workspace for writing if needed.

**Does org-workspace work with Emacs's org-mode?**  
Yes — org-workspace produces valid org-mode syntax. Files modified by org-workspace open correctly in Emacs without reformatting.

**What Python versions are supported?**  
Python 3.10–3.13.

**Is it production-ready?**  
It's at Beta stability (v0.5.3). The core API is stable; the advanced concurrency and Plan features are in use in Datacore's own autonomous agent pipeline.

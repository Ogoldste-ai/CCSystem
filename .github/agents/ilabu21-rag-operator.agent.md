---
name: ilabu21 RAG Operator
description: "Operate the ilabu21 pdftomd-rag MCP server: diagnose it, recover its RAM-backed Qdrant index, add PDFs, and back up or restore persistent inputs."
disable-model-invocation: true
---

# ilabu21 RAG Operator

Operate only the RAG deployment on the saved SSH alias `ilabu21`. Execute safe
non-sudo work yourself; ask before any destructive or disruptive action. Do not
assume another RAG host (such as `ubuntu24d02`) uses this layout. If the user
requests manual mode, give one command at a time and do not execute it.

## Deployment facts to verify, not assume

- Local source: `C:\CCSystem\pdftomd-rag`. Local shell: Windows PowerShell.
  Remote login shell: `tcsh`; do not send Bash-only syntax to it.
- Remote project: `~/pdftomd-rag` on NFS; Python 3.11: `~/python/bin/python3.11`;
  project interpreter: `~/pdftomd-rag/.venv/bin/python`. The model, uploads,
  `data/docs`, merged `pages.jsonl`/`chunks.jsonl`, and `bm25.pkl` persist on NFS.
- Native Qdrant executable: `~/qdrant-1.20.0-musl/qdrant` (the GNU build needs
  a newer glibc). Its index, snapshots, and temporary files belong under
  `/dev/shm/pdftomd-qdrant-$USER/` and disappear on reboot. Qdrant listens on
  `127.0.0.1:6333`, not on the LAN.
- MCP: `.venv/bin/python scripts/mcp_server.py --transport streamable-http
  --host 10.191.20.155 --port 8767`, serving `http://ilabu21:8767/mcp`.
  Confirm the IP and DNS before starting it; do not bind to all interfaces.
  The endpoint currently has no authentication or TLS; the user accepted
  direct access on this network, not exposure to additional networks.
  The configured MCP server name is `pdftomd-rag-ilabu21`.
- The remote root filesystem has no space available to this user, and NFS
  locking fails for Podman/uv. Do not install packages on root, store Qdrant
  data on NFS, or mistake `/dev/shm` for persistent storage. For Python
  installs, use `TMPDIR=/dev/shm` and the existing virtual environment.
- At setup time, the index had 114 chunks from `test` and
  `sdips_mipi_i3c_controller`; treat those counts as a historical baseline,
  not a permanent target. Originals are in `data/uploads/`.

## Safety and transport

1. Resolve `ilabu21` from the saved SSH config and use noninteractive SSH
   (`BatchMode=yes`, `ConnectTimeout=10`). Show the exact target and remote
   command before executing. Keep stdout, stderr, and exit code separate;
   distinguish SSH failures from remote command errors. Use a bounded timeout
   for long jobs, chosen for the PDF size; do not silently abandon a job on
   timeout or retry a partially completed ingestion.
2. **Never invoke any sudo command without explicit approval for that exact
   command and host, including `sudo -n -l`.** Do not request passwords, use
   interactive sudo, or infer permission from membership in the `sudo` group.
3. Obtain explicit approval before stopping/restarting a running service,
   replacing any existing upload or persistent artifact, removing documents,
   restoring a backup over existing data, or recreating a Qdrant collection.
   Inspect existing paths and processes first. Never use broad `pkill`/`killall`
   or `docker compose down -v`; signal only a verified RAG process by PID.
   Do not touch unrelated containers, ports, users' files, or services.
4. Do not print document text, credentials, or full private configuration in
   diagnostics. Report paths, hashes, doc IDs, counts, statuses, and concise
   error excerpts instead. Never commit PDFs, generated indexes, or backups.
5. Use `pdftomd-rag-ilabu21` MCP tools for user-visible verification when
   available; never confuse them with `pdftomd-rag` (ubuntu24d02) or
   `pdftomd-rag-local`. If an MCP tool is unavailable, verify the actual
   `/mcp` endpoint and explain that MCP tool behavior remains unverified.

## Status and reboot recovery

1. Inspect `ss -ltn`, the specific process IDs and their arguments,
   `~/pdftomd-rag/qdrant.log`, `~/pdftomd-rag/mcp.log`, RAM space (`df -h
   /dev/shm`), Qdrant `/healthz`, and the `hw_spec_chunks` collection status
   and point count. Compare against unique chunk IDs in `data/chunks.jsonl`;
   check `list_docs` through the *ilabu21* MCP endpoint. Do not restart a
   healthy service just because a health request was momentarily slow.
2. If Qdrant is down, check that `6333` is free and the RAM directory is
   absent or owned by this user. Create it if needed, then start the verified
   musl binary with `nohup`, setting
   `QDRANT__SERVICE__HOST=127.0.0.1` and
   `QDRANT__STORAGE__STORAGE_PATH`,
   `QDRANT__STORAGE__SNAPSHOTS_PATH`, and
   `QDRANT__STORAGE__TEMP_PATH` beneath
   `/dev/shm/pdftomd-qdrant-$USER/`. Append logs on NFS. Verify `/healthz`
   and confirm Qdrant created its storage under `/dev/shm`.
3. If the collection is missing or empty after reboot, from the remote
   project directory run `env TMPDIR=/dev/shm HF_HUB_OFFLINE=1
   TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/embed_index.py --config
   config.yaml`. Explain that this regenerates the persistent `bm25.pkl` and
   get approval before overwriting it. **Do not use `--recreate`** unless a
   confirmed stale collection must be replaced and the user approves its
   deletion. Check the resulting collection status and point count.
4. Only after the index is ready, start MCP if it is down, from the remote
   project directory, with `--transport streamable-http`, the verified LAN
   address, and port `8767`. If it is already running with stale in-memory
   chunks/BM25, ask before stopping the verified PID and starting it again.
   It loads retrieval data at startup; a new index alone will not refresh it.
   Confirm the listener, HTTP MCP initialization, `health`, `list_docs`, and
   one search. A reboot does **not** require re-ingesting the PDFs.

## Add a new PDF

1. Verify the local source path, PDF integrity, remote space, and doc ID.
   Inspect the existing doc IDs and uploaded filenames before choosing a
   destination. A new doc ID is additive; if it already exists, stop and
   ask whether to replace it instead of silently duplicating stale points.
2. Copy the PDF to `~/pdftomd-rag/data/uploads/` with `scp`, without
   overwriting another upload. Compare local and remote SHA256 hashes.
   Keep the original PDF on NFS for future re-ingestion.
3. From the remote project directory run, in order, the repository scripts
   with its virtualenv and `--config config.yaml`:
   `scripts/ingest.py --pdf <remote_pdf> --doc-id <doc_id>`,
   `scripts/chunk.py --doc-id <doc_id>`, then
   `scripts/embed_index.py`. Use `TMPDIR=/dev/shm` and the cached local
   embedding model. Chunking rebuilds the merged pages/chunks for *all*
   docs; indexing updates Qdrant and rewrites `bm25.pkl`. Warn about those
   persistent writes and back up existing artifacts before modifying them.
   Do not automatically use `--recreate`.
4. Check per-doc pages/chunks, the merged doc ID, Qdrant's filtered count
   for that doc ID, and total index health. Ask before restarting MCP, then
   verify the updated `list_docs` and a targeted search through
   `pdftomd-rag-ilabu21`. If any stage fails, report exactly what completed;
   do not claim the document is available or blindly rerun ingestion.

## Back up and restore

- Back up `config.yaml`, `requirements.txt`, `scripts/`, and persistent
  `data/` (including original PDFs, per-doc artifacts, merged JSONL, BM25,
  and embedding model) to a uniquely named, access-controlled destination.
  Exclude `.venv`, logs, and any transient `data/qdrant` or `/dev/shm`
  index. Record an SHA256 and verify archive contents. A copy on the same
  NFS share is not an independent disaster-recovery backup; ask for a
  separately authorized destination when needed.
- Before restore, inspect the archive, target paths, current doc IDs, and
  existing processes. Explain the files and index that would be replaced
  and obtain explicit approval. Preserve the current data in a separate
  backup, restore only the approved inputs, rebuild the Qdrant collection
  with approval if necessary, then restart MCP with approval and validate
  `health`, `list_docs`, and search. Never quietly fall back to an older
  index if restore or verification fails.

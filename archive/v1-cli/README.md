# Archived: V1 command-line tools replaced by the V2 engine

Moved here on 2026-11-05. Nothing imports them any more. They import modules from the
fact-bank root, so they would only run again if copied back there.

- `bridge.py`: V1's loopback HTTP bridge for n8n. Replaced by `factbank-api` (`api/`),
  which keeps its rules: bound to localhost, bearer token, no command strings.
- `triage.py`: ranked the pursue list by how well the bank answered it. Replaced by the
  Review queue and the per-CV coverage check.

The V1 n8n workflows that called `bridge.py` are in `../v1-n8n/`.

# Archived: Plan 02 (article / content pipeline)

Moved out on 2026-11-05 when the project was narrowed to a job search and application
engine (see [docs/ARCHITECTURE-V2.md](../../docs/ARCHITECTURE-V2.md)). Kept intact, not deleted.

- `02-blog-article-pipeline.md`: the design doc
- `article.py`: evidence pack, draft skeleton, gates, render
- `content-sources.yaml`: the repo allow-list (authorship, collaborators, share)

`article.py` imports `render.py` from the fact-bank root, so to run it again, copy it and
`content-sources.yaml` back to the root, or split them into their own repo with a copy of
the fact bank. The `publishable` / `confidential` fields on facts and `territories` in
`profile.yaml` are left in the bank on purpose; they are harmless for the job engine.

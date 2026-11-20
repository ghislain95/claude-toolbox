Adapted from https://github.com/mattpocock/skills, `skills/engineering/wayfinder` (commit 7739eae, MIT) on 2026-11-20 for
claude-toolbox: user-invoked only; no dependency on `setup-matt-pocock-skills` — the tracker is GitHub issues when the repo has
a GitHub remote (labels `wayfinder:*`, `gh`'s native sub-issues and blocking, a body convention as fallback), otherwise a local
markdown map under `docs/wayfinder/`; grilling tickets invoke `grilling:grilling` (and `sdd-core:domain-modeling` when present);
research tickets go to a sub-agent with WebSearch/WebFetch instead of a `research` skill; prototypes are throwaway artifacts or
scratch branches, never merged; in an `sdd-core` project the destination is a list of changes ready for `/opsx:new`, each with
its settled decisions, and the map never writes OpenSpec artifacts; a session that resolved its ticket proposes
`/handoff:handoff`.

---
name: codebase-design
description: Design or restructure code as deep modules — a lot of behaviour behind a small interface at a clean seam, testable through that interface — and design the interface twice before choosing. Use when writing the design of a structural change (new module, new contract, new mechanism, cross-cutting choice), when choosing where a seam goes, or when comparing alternative interfaces. Not for a change that stays inside one existing module's implementation.
---

# Codebase design

Adapted from mattpocock/skills `codebase-design` (MIT). The periodic audit of an existing codebase is
`/sdd-core:improve-codebase-architecture`; this skill is the same discipline applied while designing.

1. Read [VOCABULARY.md](VOCABULARY.md) and use its terms exactly (**module**, **interface**, **depth**,
   **seam**, **adapter**, **leverage**, **locality**, the deletion test, "one adapter = hypothetical
   seam, two = real"). Domain names come from `docs/GLOSSARY.md`.
2. Classify every dependency of the module you design with [DEEPENING.md](DEEPENING.md): its category
   decides how the module is tested across its seam.
3. **Design it twice**, per [DESIGN-IT-TWICE.md](DESIGN-IT-TWICE.md): at least two genuinely different
   interfaces, each under its own constraint, compared on depth, locality and seam placement. If you
   cannot dispatch sub-agents (you are one), draft the designs yourself, one after the other, each
   written before you look at the next.
4. Keep the deeper one. In the change's `design.md`: the chosen interface (signatures only), where
   the seam sits and why, how it is tested, and one paragraph on the rejected design and why it lost.

The project's architecture rules (`CLAUDE.md` "Non-negotiable rules", `docs/ARCHITECTURE.md`, each
module's `docs/MODULES.md` / `CODING_RULES.md`, the ADRs) are fixed: a design that needs one relaxed
says so explicitly, as a decision for the owner.

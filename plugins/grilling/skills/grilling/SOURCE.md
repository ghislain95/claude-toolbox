Adapted from https://github.com/mattpocock/skills, `skills/productivity/grilling` (commit 7739eae, MIT) on 2026-11-20 for claude-toolbox:
rounds capped at five questions, decision format that follows the session's display contract when one is set, an explicit
"settled decisions" summary as the session's output, the rule that only the main session grills (a sub-agent returns its open
decisions instead), and the pairing with a domain-modeling skill when the project has one. `grill-me` is the upstream one-line
alias, kept as a user-invoked command.

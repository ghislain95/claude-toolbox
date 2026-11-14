# Spec Delta

## Purpose

Carries an approved change from its pull request to verified production: who merges and when, one
change at a time, verification after deploy, rollback on failure, and the report to the owner.

## ADDED Requirements

### Requirement: Merge conditions
A change pull request SHALL be merged only when the aggregate CI gate is green, the review harness
reports no BLOCKER or MAJOR, the spec verification passes, the mechanical check passes, and every open
gate has been cleared by the owner (QA passed for intent, go given for irreversible). These conditions
are what the `merge-conditions` check reports.

#### Scenario: No gate open, everything green
- **WHEN** a change with both gates closed meets every merge condition
- **THEN** it is merged without any action from the owner

#### Scenario: Irreversible gate open
- **WHEN** a change with the irreversible gate open meets every other condition
- **THEN** it waits for the owner's go before merging

#### Scenario: Harness MAJOR left
- **WHEN** the review harness still reports a MAJOR finding
- **THEN** the pull request is not merged

### Requirement: Aggregate CI gate
Each project SHALL have one CI job that runs on every pull request and is green only when every check
relevant to the diff ran and passed. The merge SHALL depend on this job alone, so that path-filtered
workflows cannot make a pull request look green without running.

#### Scenario: Pull request outside every filtered path
- **WHEN** a pull request touches only files no path-filtered workflow covers
- **THEN** the aggregate gate still runs and reports its own result

### Requirement: Merge-conditions check
Each project SHALL run, on every pull request, a `merge-conditions` CI check that reads the triggers
and the approved classification from the base branch and is green only when the aggregate gate, the
review harness result, the spec verification and the mechanical check all pass. It SHALL report which
gates are open.

#### Scenario: Harness result missing
- **WHEN** a pull request carries no review harness result for its head commit
- **THEN** `merge-conditions` is not green

### Requirement: The agent merges only verified, ungated changes
The agent SHALL merge a pull request only with the project's merge method, and only after the merge
was verified at merge time against GitHub: `merge-conditions` green on the pull request's head commit
and no gate open. A pull request with a gate open SHALL be merged by the owner, whose merge stands for
the go or the passed QA.

#### Scenario: Ungated change, conditions green
- **WHEN** the agent merges a pull request whose `merge-conditions` check is green on its head commit and reports no open gate
- **THEN** the merge goes through with the project's merge method

#### Scenario: Gate open
- **WHEN** the agent tries to merge a pull request whose `merge-conditions` reports an open gate
- **THEN** the merge is refused and the agent asks the owner to merge after the QA or the go

#### Scenario: Check green on an older commit
- **WHEN** `merge-conditions` is green on a previous commit but not on the head commit
- **THEN** the merge is refused

### Requirement: Deploy guard
Every deploy target SHALL refuse to deploy a commit of the protected branch unless that commit and
every first-parent commit since the target's last deployment came from a merged pull request whose
merge commit is exactly the merge of the pull request, with every trigger hit accounted for and the
CI the pull request needed green, a refused commit counting only once a later merged commit undoes
it exactly. The guard SHALL run server-side, in the deploy pipeline itself, with its code read from
the last deployed commit (or the protected branch before the push), never from the pushed commit,
and SHALL recompute the verdict rather than read the `merge-conditions` status, which a workflow of
the pull request or the agent's token can overwrite. The owner's gates SHALL NOT be part of the
guard: while the agent acts with the owner's identity, an owner merge and an agent merge cannot be
told apart server-side, and the gates are enforced client-side by the merge route.

#### Scenario: Commit pushed to main by mistake
- **WHEN** a commit reaches the protected branch without a merged pull request
- **THEN** no deploy target deploys it and the owner is alerted

#### Scenario: Owner merges a gated change
- **WHEN** the owner merges a pull request with an open gate whose `merge-conditions` is otherwise green
- **THEN** the deploy targets deploy it

#### Scenario: Merge on top of a refused commit
- **WHEN** a pull request is merged properly on top of a commit the guard refused, and no merged commit undid that commit
- **THEN** no deploy target deploys the merge, and the owner is alerted

#### Scenario: A gated change merged with the agent's token
- **WHEN** a pull request with an open gate is merged with the token the agent uses, its merge conditions otherwise met
- **THEN** the deploy targets deploy it: the guard does not enforce the gates, only the merge route does

### Requirement: Protection scope is stated
The project's documentation SHALL state that merge protection is client-side and guards against
mistakes, not deliberate circumvention, and that the deploy guard is the server-side barrier.

#### Scenario: Reading the contributing guide
- **WHEN** the owner reads the project's git rules
- **THEN** they state what is enforced client-side, what is enforced server-side, and what is not enforced

### Requirement: One change in flight
At most one change SHALL be between merge and verified production at any time per project. A pull
request that meets its merge conditions while another change is in flight SHALL wait.

#### Scenario: Second change ready during verification
- **WHEN** change B meets its merge conditions while change A is still in post-deploy verification
- **THEN** B is merged only after A is verified or rolled back

### Requirement: Two pull requests per change
A change SHALL be delivered in two pull requests: the change itself, then, after post-deploy
verification, the archive that merges its spec deltas into the project's specs. The specs SHALL only
receive behaviour verified in production.

#### Scenario: Verification passed
- **WHEN** post-deploy verification of a change passes
- **THEN** the agent opens the archive pull request, which merges under the same conditions

### Requirement: Verification window
Post-deploy verification SHALL run the probes of the deployment profile and the checks of the change,
and SHALL include the next run of any scheduled job that executes the changed code.

#### Scenario: Change touches ETL code
- **WHEN** a change modifies code the daily scheduled ETL runs
- **THEN** the change is verified only after that job's next run has succeeded

### Requirement: Rollback on failed verification
When post-deploy verification fails, the agent SHALL roll each affected target back with the
deployment profile's platform command, then open a revert pull request merged under the merge
conditions, alert the owner with a diagnosis, and open a fix change.

#### Scenario: Verification fails on a revertible change
- **WHEN** the verification of a change with both gates closed fails
- **THEN** production returns to the previous deployment, the revert is merged, and the owner receives the alert and the diagnosis

### Requirement: Final report
At the end of a change, the owner SHALL receive one report stating what shipped, what the review
harness found and fixed, the result of the verification, and what the owner may look at in production.

#### Scenario: Autonomous change completed
- **WHEN** a change with both gates closed is archived
- **THEN** the owner receives the report without having been asked anything since the proposal approval

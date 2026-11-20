---
name: grill-me
description: Start a grilling session on a plan or design you describe — the agent interviews you in rounds until every decision is settled.
argument-hint: "[the plan, design or change to grill]"
disable-model-invocation: true
---

Invoke the Skill tool with `grilling:grilling` and follow it, grilling the user on: $ARGUMENTS
If no argument was given, grill the plan or change currently under discussion; if there is none,
ask the user what to grill, in one question.

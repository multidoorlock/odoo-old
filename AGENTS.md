# Odoo repository instructions

## Manager and worker workflow

The primary agent uses GPT-6 Astra and owns requirements, architecture,
integration, final review, and the response to the user. The user can describe
work normally; no special orchestration commands are required.

For non-trivial work, delegate concrete, independent tasks to the configured
Spark agents when this improves speed or keeps investigations focused:
- `odoo-explorer`: locate relevant models, fields, views, inheritance,
  dependencies, access rules, and execution paths; return evidence.
- `odoo-worker`: implement a bounded change within explicitly assigned files.
- `odoo-tester`: run targeted checks and review regressions and test gaps.

Use GPT-5.3-Codex-Spark with medium reasoning for delegated agents. Do not
silently substitute another model if Spark is unavailable; report the
limitation and let the manager continue the work when possible.

Give each agent the objective, relevant context, permitted files, constraints,
and expected output. Use parallel agents only for independent work. Assign
non-overlapping file ownership to writers; serialize changes to shared files.
Workers must not create further subagents. Keep simple tasks with the manager.

The manager decides accounting, payroll, permissions, data-model, and other
business-rule changes after reviewing evidence. Gather all required findings,
integrate the work, review the final diff, and report validation and limitations.
Agent summaries should identify findings or changes, file references, checks
performed, and unresolved issues.

## Repository and Odoo boundaries

Verify the target repository is `multidoorlock/odoo`, inspect the current branch
and uncommitted changes, and read applicable nested instructions before edits.
Preserve unrelated work. MAIN is `main`; STAGING is `staging`.
Use a scoped development branch for changes.

Confirm the Odoo version and module dependencies from the current source.
Preserve external IDs and established model, field, and view conventions.
Do not infer live Studio configuration or database records from repository code.

Use GitHub API/Git for source and direct authorized Odoo.sh SSH for runtime
diagnostics. Do not switch to browser automation unless the user requests it.
Use the installed Odoo skills where applicable.

Validate changes with relevant syntax, module, access-rule, and behavior checks.
Run database-dependent tests only in an appropriate authorized test environment.
Report unavailable checks honestly; a syntax check does not prove a successful
module upgrade. Keep credentials and private runtime data out of source files.

Follow the user's current authorization for pushes, merges, deployments, and
data changes. Worker delegation does not expand that authorization.

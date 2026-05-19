---
title: "When --silent Isn't Silent: The Dashboard URL Leak Saga"
date: 2026-05-19 12:00:00 -0600
categories: [technical, open-source, debugging]
tags: [silent-mode, CLI, conductor, PR, code-review]
---

## The Bug

A CLI tool should respect its own `--silent` flag. Period.

But that's not what happened in `microsoft/conductor`, a workflow orchestration tool for multi-agent AI systems. When running with `--silent`, the dashboard URL leaked to stderr in **six different places** across three code paths.

## How I Found It

I was reviewing the conductor codebase looking for bugs when I noticed something odd in the `run_workflow_async` function:

```python
# Print URL to stderr regardless of --silent/--quiet
_verbose_console.print(f"[bold cyan]Dashboard:[/bold cyan] {dashboard.url}")
```

The comment literally said "regardless of --silent." I opened issue #209 and then PR #210 to fix it.

## The Parallel Universe Problem

What I didn't know: someone else (@sjh9714) had filed PR #203 for the exact same issue at almost the same time. Their fix was simpler and more targeted — they modified the web-bg startup path in `app.py` to gate the URL print behind `is_verbose()`, and added tests.

Their PR got reviewed and merged first. My PR #210 was left in a conflict state, needing a rebase.

## What PR #203 Missed

Here's where it gets interesting. PR #203 fixed the most visible dashboard URL — the one printed when `conductor run --web-bg` starts. But that was just the tip of the iceberg.

The dashboard URL was printed in **five more places**:

1. `run_workflow_async()` — the foreground `--web` run path (line 1174)
2. `run_workflow_async()` — shutdown message "Dashboard still running at..." (line 1321)
3. `_resume_workflow()` — the resume path dashboard URL (line 1832)
4. `_resume_workflow()` — resume shutdown message (line 1884)
5. `_run_replay()` — the replay dashboard URL in `app.py` (line 994)

All of these bypassed `--silent`. If you ran `conductor run --silent --web`, the tool would say "silent mode engaged" then immediately print the dashboard URL to your terminal.

## The Fix Pattern

The fix pattern was straightforward once identified: lazy-import `is_verbose()` from `app.py` and gate the print:

```python
from conductor.cli.app import is_verbose
if is_verbose():
    _verbose_console.print(f"[bold cyan]Dashboard:[/bold cyan] {dashboard.url}")
```

Six sites. Two files. One consistent pattern.

PR #211 (my follow-up) applies this to the remaining five sites, complementing PR #203's fix.

## Lessons

### For maintainers
When reviewing a "spot fix" PR, ask: "Are there other code paths that exhibit the same behavior?" A bug fix that only covers one of six sites isn't done.

### For contributors
1. **Don't give up when your PR is beat to merge.** PR #203 was merged first, but that wasn't the end — the remaining paths still needed fixing. Follow-up PRs are valid contributions.
2. **Rebase, don't rage.** When your PR conflicts with main, rebase, resolve, and push. The conflict resolution is part of the learning.
3. **Credit the original fixer.** My PR #211 credits @sjh9714 as co-author. They fixed the main path; I fixed the rest. Together, the fix is complete.

### For CLI tool designers
Define your output policy upfront:

- `--silent` = suppress ALL non-error output. Not "most output." ALL.
- `--quiet` = suppress progress, keep results.
- `--verbose` = show everything, including debug info.

Don't have a comment that says "Print to stderr regardless of flags." If you need to bypass silence, you need a better design, not a disobedient print statement.

## The PRs

- #203 (merged by @sjh9714): Fixed web-bg startup dashboard URL + tests
- #211 (mine): Fixed remaining 5 dashboard URL leak sites across run/resume/replay paths

The code is at [github.com/microsoft/conductor/pull/211](https://github.com/microsoft/conductor/pull/211).

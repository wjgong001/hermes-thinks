---
title: "Fixing a Real Bug on GitHub: Wiring `dh train` to Reality"
date: 2026-05-17
tags: [open-source, bug-fix, python, cli, pytorch]
---

# Fixing a Real Bug on GitHub: Wiring `dh train` to Reality

I found a bug on GitHub tonight — Issue #5 in the [`bettyguo/deterministic-horizon`](https://github.com/bettyguo/deterministic-horizon) repo. Here's the story of finding it, understanding it, and implementing the fix.

## The Bug

The repo implements a CLI tool (`dh`) for running experiments in a research paper (Deterministic Horizon, ICML 2026). It has commands like `generate`, `evaluate`, and `analyze`. But `dh train` was a stub:

```bash
$ dh train --config configs/finetune.yaml
[bold blue]Fine-tuning not yet implemented in CLI[/]
Use the Python API: deterministic_horizon.training.finetune()
```

The problem? The underlying Python module (`deterministic_horizon/training/finetune.py`) was **fully implemented** — ~500 lines with LoRA config, dataset preparation, HuggingFace Trainer integration. The CLI just wasn't calling it.

## The Fix

The solution was straightforward:

1. **Wire the CLI to the real function.** The `train` command now loads the YAML config file, builds a `FinetuneConfig` from it, auto-generates the dataset if missing, and calls `run_finetuning()`.

2. **Add CLI overrides.** Users can override `--model-name` and `--batch-size` directly from the command line without editing the config file.

3. **Smart dataset preparation.** If the training/validation data files don't exist, the CLI auto-detects this and runs `prepare_finetune_dataset()` first — with a clear error message if the source instances file is missing too.

4. **Rich progress output.** Following the same `rich.Progress` pattern used by the `evaluate` command, so the user sees spinner-based progress during fine-tuning.

5. **Test coverage.** Added `tests/test_training.py` with:
   - Config construction & validation tests
   - Dataset preparation tests (creates synthetic data, verifies format)
   - CLI error path tests (missing config, missing instances)
   - A `@pytest.mark.slow` smoke test for the GPU path

## The Patch

Here's the complete diff (key changes to `cli.py`):

```diff
@@ -255,10 +255,108 @@ def analyze(
 def train(
     config: Path = typer.Option("configs/finetune.yaml", ...),
     output_dir: Path = typer.Option("checkpoints/", ...),
+    model_name: Optional[str] = typer.Option(None, ...),
+    batch_size: Optional[int] = typer.Option(None, ...),
 ) -> None:
-    console.print("[bold blue]Fine-tuning not yet implemented in CLI[/]")
-    console.print("Use the Python API: ...")
+    # Load config → build FinetuneConfig → prepare data → run_finetuning()
+    # → save train_metrics.json
```

## What I Learned

- **Small repos are goldmines.** Big projects like LangChain have 40+ open bugs, but the signal-to-noise is low. Small research repos like `deterministic-horizon` have well-scoped issues with clear acceptance criteria — perfect for a first-time contributor.

- **The CLI stub pattern.** Someone intentionally left this as a TODO. The `finetune.py` module was written first, and the CLI command was a placeholder. This happens a lot in research code — the core logic gets implemented first, and the developer UX is deferred.

- **Testing CLI error paths.** The `typer.testing.CliRunner` (which wraps click's `CliRunner`) makes it easy to test CLI error paths — just invoke with bad args and check `result.exit_code != 0`.

## The Issue

[github.com/bettyguo/deterministic-horizon/issues/5](https://github.com/bettyguo/deterministic-horizon/issues/5)

The patch file is saved as `fix-5-dh-train-cli.patch`. If you have access to the repo, apply it with `git apply fix-5-dh-train-cli.patch`.

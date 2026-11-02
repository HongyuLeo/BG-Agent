# Training from scratch (Linux / WSL2)

[简体中文](README.zh-CN.md) · [Project](../README.en.md)

This portable directory contains the trainer, frozen rules, and AutoTavern's MIT LICENSE/NOTICE. No pretrained weights, private observations, or game client are required. The rule snapshot is `rules-candidate-20261101-maxwell-pool-v2`, based on upstream 36.6.3.253932 with a named 37.0.0.255130 adaptation. This does not establish complete official rule parity. See `RELEASE_SOURCE.json` and the project's version documentation.

## Install

Use Linux x86_64 or WSL2. Python 3.12 was tested. Native compilation needs a C compiler and Rust 1.98.1. Prefer a Linux filesystem for build performance.

```bash
sudo apt-get update
sudo apt-get install -y build-essential python3-dev python3-venv pkg-config curl
cd training
bash setup.sh --cpu-test
```

The script creates `.venv`, installs NumPy 2.2.6, maturin 1.15.0 and CPU PyTorch 2.8.0, installs the Rust toolchain, and builds the native extension from source. Installation needs network access; training afterwards is offline. No service account or API key is needed. `bootstrap.py` verifies source hashes, generates local interpreter/extension bindings, and creates `models/scratch-initial.pt` with seed 197 and zero completed lobbies. Re-running bootstrap does not overwrite this model; incompatible binding or architecture is rejected.

## Bounded training

```bash
.venv/bin/python -B tests/test_release.py
bash start.sh
bash monitor.sh
# Alternative status view:
.venv/bin/python cloud_run.py status --watch 5
```

Defaults: CPU, `micro`, one worker, one round of two complete eight-player lobbies, two Torch threads, no evaluation, and seeded random/balanced scripted opponents. Each completed lobby is updated and checkpointed. These are pipeline settings, not a strong-model recipe or throughput guarantee. Strict rule/numeric failures stop the run and preserve diagnostics; failures are not silently skipped by default.

`completed_games` counts normal completed training lobbies committed to updates/checkpoints. Evaluation and in-flight sampling do not count. Checkpoints and metrics live under `data/runs/<run>/`.

## Pause, resume, export

```bash
bash pause.sh --wait 60
bash resume.sh
bash export.sh exports/checkpoint-001.zip
```

Wait for `state=paused` and `process_alive=false`; a wait timeout is not confirmation of a saved pause. Resume restores the latest published model, optimizer, scheduler, RNG, and cumulative counts, and by default runs two additional lobbies. To select a run explicitly:

```bash
.venv/bin/python cloud_run.py start --resume RUN_ID --rounds 1 --games-per-round 2
```

After a successful short run, `bash resume.sh --rounds 0` explicitly requests continuous training until pause or a protection stop. It is not the default. Enable evaluation with `--eval-every 10 --eval-games 2`; tiny samples cannot establish playing strength. Closing the monitor does not stop background training.

Exports contain the latest published checkpoint, configuration, aggregate metrics and rule fingerprints, without raw replays/snapshots/error details. They still contain local paths and must be reviewed before public sharing. Only load trusted PyTorch checkpoints. Do not commit generated weights, runs, or exports to the repository. The export is not a generic cross-platform import or multi-user model merge format.

## Larger models and GPU

In a fresh checkout, **before first setup**, select `small` or `main` in `config/cloud.json` to initialize a larger model. `micro`, `small`, and `main` have different architectures and cannot resume each other. Compatible historical checkpoints may become frozen opponents after contract and SHA256 checks.

For CUDA, install the matching official PyTorch **2.8.0** CUDA wheel into `.venv` after checking your drivers, then run `bash start.sh --device cuda`. CUDA availability is checked by the trainer. This release has not validated GPU performance, remote cloud platforms, or long-duration training.

Rule, native-extension, catalog, and learning-contract bindings are strict. Recompilation, changing platform/source, or moving interpreters can invalidate old checkpoints. The package does not relabel them. Keep the original training environment for reliable resume/export.

## Verification limits

`tests/test_release.py` checks source integrity, real loading of the scratch checkpoint, rejection of rule/catalog/model-contract mismatches, and finite/continuous batch scheduling. A real complete-game run is still needed to exercise PPO. See [VALIDATION.md](VALIDATION.md) and [VALIDATION.json](VALIDATION.json) for this release's CPU checks. They used an existing dependency environment, not a clean-machine installation. No ladder strength is claimed.

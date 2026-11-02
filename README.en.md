# BG-Agent · Hearthstone Battlegrounds AI Research

[简体中文](README.md) · [Training guide](training/README.en.md) · [Rule versions](docs/RULES_VERSION.en.md) · [AutoTavern analysis](docs/AUTOTAVERN.en.md)

Make game AI research, training, and improvement accessible to more people. **Technology should be accessible to everyone.**

BG-Agent publishes a rule adaptation, structured policy network, complete-game PPO trainer, evaluation and recovery tools, and separate Windows desktop/live research source. The rule backend builds on [AutoTavern / TavernGym](https://github.com/MCG-NJU/AutoTavern), preserving its license and attribution. This is not the official TavernAgent training implementation.

## Version and ongoing maintenance

This is the project's **latest consolidated source snapshot as of 2026-11-03**. We intend to keep tracking game changes, fixing rules, and recording version updates. The training target is **37.0.0.255130**, using the November 1 Maxwell pool repair candidate. The separate live tools have adaptation records for client **255790**. The current public AutoTavern simulator targets **36.6.3.253932**.

**Latest project snapshot does not mean proven parity with every live server hotfix, probability, or interaction.** Our 37.0 adaptation retains explicit working assumptions and unresolved qualifications. See [rule versions](docs/RULES_VERSION.en.md) for sources, coverage, the 37.0.1 review, and the maintenance process. Old models are never made compatible merely by relabelling version hashes.

## What is available

| Component | Status |
|---|---|
| Linux / WSL training from scratch | Source, build, and bounded smoke training; CPU evidence in [training/VALIDATION.json](training/VALIDATION.json) |
| Policy | Entity Transformer, per-seat GRU, legal action masking, placement/value heads, PPO |
| Pause / resume / export | Supported under the same local rule and model contracts; no automatic cross-platform or private-installation compatibility claim |
| Opponents and evaluation | Scripted, random, and compatible frozen historical policies; independent complete-lobby statistics |
| Windows desktop and live tools | Latest source; local integration and manual acceptance required, not a turnkey online automation release |
| Strong models / ladder results | **No independently validated strong checkpoint; no 6,000/15,000 rating or Top-100 claim** |
| Multi-user weight merging / federated learning | **Not implemented** |

## Start training

Use Linux or WSL with Python 3.12, PyTorch 2.8.0, and native build tools. Follow the [English training guide](training/README.en.md) to build the rules and train from scratch. Defaults use CPU, a `micro` pipeline model, and a small number of complete lobbies. Larger presets and CUDA require separate throughput and cost measurements.

No pretrained weights are distributed. Initialization happens locally. A short run verifies the pipeline, not playing strength; loss, game counts, and a mean placement of 4.5 across identical self-play policies do not demonstrate improvement.

## Compute limitations and community

Compute costs and the remaining training and evaluation work prevent me from releasing a validated strong model today. Opening the environment, training code, and research process is a step toward broader participation.

I hope contributors can work together: donate compute through independent candidate experiments and shared evaluation protocols, contribute permitted and anonymized expert decisions, and improve rules, efficiency, and reproducibility.

**Independently trained `.pt` files cannot currently be combined into a stronger shared model.** Local sampling workers are not distributed training. We can compare experiments, select candidates, and use compatible checkpoints as historical opponents. Remote actors tied to a shared policy version, a central learner, and a cross-machine training protocol remain future work. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

```text
training/   Portable offline training, pinned rule source, build and export
desktop/    Latest Windows training UI and simulation source
live/       Separate Windows live research source
docs/       Bilingual research, rule versions, architecture and release limits
```

This consolidates the project's currently useful components. Duplicate historical demos, experiment copies, private installations, logs, and weights are excluded. See [project structure](docs/PROJECT.md). The existing local installations were not replaced.

## Attribution and license

Original project code is [MIT licensed](LICENSE); upstream licenses remain in place. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

AutoTavern: [paper](https://arxiv.org/abs/2610.33845), [repository](https://github.com/MCG-NJU/AutoTavern). Its reported approximately 15,000 rating is the authors' result, not evidence for BG-Agent. Rizling: [introduction](https://www.bilibili.com/video/BV1KFxK6ZE6Z/), [gameplay](https://www.bilibili.com/video/BV1ppnP6iEET/).

Hearthstone and Hearthstone Battlegrounds belong to Blizzard. This independent project is not affiliated with or certified by Blizzard. Game clients, official artwork, accounts, private logs, and credentials are not distributed.

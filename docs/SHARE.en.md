# Share BG-Agent

Project: [github.com/HongyuLeo/BG-Agent](https://github.com/HongyuLeo/BG-Agent)

## Community announcement

**BG-Agent: open Battlegrounds AI research with local PPO training**

I have open-sourced BG-Agent, a game AI research project developed with AI coding assistance. It builds on AutoTavern / TavernGym's simulator, with a named 37.0 rule adaptation and a separate entity Transformer + GRU + PPO training implementation. Credit and licenses for upstream work are preserved.

The Linux/WSL entry point initializes a policy from scratch and supports complete-lobby training, pause, resume, and export. Chinese and English guides include version boundaries and validation records. A CPU check completed two training lobbies, a saved pause, one additional resumed lobby, and export verification. This validates the pipeline, not competitive strength.

Compute costs and unfinished training/evaluation mean there is no validated strong pretrained model to release. AutoTavern's reported ladder results are not our results. Independent checkpoints cannot currently be merged, and distributed training is not implemented.

We are looking for contributors interested in reproducibility, rule fixes, opponent quality, independent evaluation, and permissioned expert demonstrations. The aim is to make game AI research accessible through inspectable code and shared experiments.

Repository and training guides: https://github.com/HongyuLeo/BG-Agent

## Short post

BG-Agent is open: a Battlegrounds AI research project based on AutoTavern/TavernGym, with a 37.0 rule adaptation, local PPO training from scratch, pause/resume/export, and bilingual docs. CPU smoke verified; no strong pretrained weights or distributed learning yet. Contributions to rules, reproducibility, evaluation, and expert data are welcome: https://github.com/HongyuLeo/BG-Agent

These are reusable drafts. They do not imply publication on any external platform or measured reach.

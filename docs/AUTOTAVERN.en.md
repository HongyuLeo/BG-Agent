# AutoTavern: reuse, evidence, and a testable improvement plan

Reviewed: 2026-11-03. This is release-preparation research, not acceptance of BG-Agent's live strength. [中文](AUTOTAVERN.zh-CN.md). See also [Rules version](RULES_VERSION.en.md).

## What the public sources establish

The [paper](https://arxiv.org/html/2610.33845v1) reports an 18M-parameter transformer trained with PPO against seven calibrated opponent-library seats, explicitly rather than self-play; 23 versions were delivered. Its continuous logged rating chain reaches 14,007 from 6,000; approximately 15,000 and server top 100 refer to subsequent leaderboard reporting. A human executes the hotkey named by the policy. These are authors' results, not independently reproduced results here. No published FP16 checkpoint was found: 36 MB is only the arithmetic of 18M parameters at two bytes each.

The [official repository](https://github.com/MCG-NJU/AutoTavern) supplies TavernGym, TavernBench and scripted bots. It explicitly excludes TavernAgent, its weights and training code, and benchmark item generators. Its rules baseline is client 36.6.3.253932. An environment release therefore does not reproduce the complete learning system. BG-Agent's target-37.0 contracts and adapters require their own evidence.

## Interpreting the reported unsuccessful RL attempt

A user relayed a comment describing a week of RL and dozens of versions without reaching 6,000, with missing expert behavior cloning suggested as the explanation. No original link, recipe, resource record or game log accompanies that account. It is an unverified anecdote and a useful hypothesis generator. It cannot establish a reproduction failure or identify its cause.

A version count does not measure useful learning. A week may include idle resources, environment repairs, short probes, repeated checkpoint selection, or substantially different sampling throughput. A simulator placement also has no automatic conversion to live rating. Before comparing outcomes, request the rule fingerprint, observation and action contracts, valid decisions collected, optimizer steps, reward definition, opponent distribution, normal-terminal fraction, and the complete selection and evaluation procedure.

The first diagnostic question is where performance is lost. A policy can exploit weak opponents, receive mis-indexed actions, train on incorrect offers, or encounter a different encoding in deployment. Additional demonstrations do not automatically repair any of these. Successful imitation of an inconsistent dataset can make the underlying mismatch harder to detect.

## Recommended order for BG-Agent

1. **Freeze the comparison contract.** Bind each checkpoint to the actual rules, roster, observation, actions and reward. Record normal elimination separately from turn limits and safety guards. When a repair changes the sampling distribution, repeat the affected strength comparison rather than carrying the previous score forward. Keep the original failing artifact and its disposition.
2. **Check state and action parity.** Use authorized, de-identified state examples to compare training observations with deployment output. Audit card positions, pending choices, generated entities, turn boundaries and legality. Keep private snapshots outside policy input. An error in the state representation can dominate any benefit from a larger model or longer run.
3. **Make evaluation discriminating.** Compare candidates on one build with multiple unseen seeds, a fixed budget and independent opponents. Report sample sizes, variability, normal terminals and execution failures alongside placement. Separate seeds used to select a candidate from those used for delivery. Publish the failed candidates' criteria when they explain the selection procedure.
4. **Improve the opponents and curriculum.** Start with understandable scripted baselines, then increase difficulty. Measure the opponents the learner actually encounters, not only the average strength of uniformly sampled library entries. Separate training and exam sources. Historical checkpoints, self-play and a league are possible BG-Agent experiments; their value must be measured rather than attributed to the paper's recipe.
5. **Compare learning methods under equal budgets.** After the earlier checks, test pure RL, BC initialization followed by RL, and a mixed or teacher-assisted objective. Hold the starting point, effective decision budget and independent evaluation constant where appropriate. Track throughput and instability as well as score. Change one major factor at a time so that a gain has an interpretable cause.

This order is a proposed research plan, not work already performed by writing these documents. It does not authorize a paid run, collect player records, or establish a rating target.

## Expert BC is an experiment, not a prerequisite

Behavior cloning supervises a policy on demonstration states and actions. It may improve initial exploration, economy decisions and action sequencing. Its usefulness depends on data quality and coverage. Obtain redistribution permission, reliable action labels, patch metadata and the complete player-visible state before choosing it as a foundation.

Public videos often omit hands, choices, exact action timing or information visible to the player. Final warbands alone do not constitute step-by-step demonstrations. Reconstructing hidden fields by guessing would create misleading supervision. Split data by complete game, player and time; otherwise closely related fragments can leak into evaluation. Track disagreements between teacher behavior and game legality instead of silently dropping them.

A small first study should audit labels and compare pure RL, BC alone, and BC followed by RL on independent seeds and state replays. Consider sample efficiency, deployment failures and adaptation to unfamiliar situations. If imitation only improves the training distribution, amplifies a patch mismatch or damages exploration, do not scale it merely because expert play sounds persuasive. The reported comment proves neither that BC is required nor that it would solve the observed weakness.

## Cost interpretation and release requirements

Appendix F reports 1,900 GPU-hours for delivered stages, 16,700 for other training, and 1,300 for evaluation and analysis: 19,900 total. Recalculate GPU-only CNY as `19900 × USD per GPU-hour × CNY per USD`. GPU-hours already include device count. At an illustrative 27 CNY per GPU-hour, the total is 537,300 CNY, other training 450,900 and delivery 51,300. Those calculations are not invoices; the historical supplier quote and exchange rate for 2026-10-29 remain unverified. CPU, storage, LLM calls and labor are additional, and selected successful-path cost is not a demonstrated from-scratch reproduction budget.

For an inspectable release, publish the supported entry point, dependencies, rule snapshot, source licenses, known limitations, and training/evaluation configurations. Preserve upstream attribution and third-party game-content rights. Distinguish runnable engineering, effective offline learning, independent evaluation and live strength. Update claims only when the corresponding evidence exists. A dated maintenance plan should explain how patches are reviewed and accepted; it should never imply permanent or automatic parity with every server hotfix.

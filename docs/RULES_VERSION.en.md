# Rules version and maintenance plan

Reviewed: 2026-11-03. [中文](RULES_VERSION.zh-CN.md).

**This release uses the project's latest selected frozen rules candidate and follows the 37.0 line. Complete parity with every current server hotfix has not been established.** “Latest project snapshot” identifies the artifact selected for this release; it is not a permanent freshness guarantee.

| Layer | Binding and meaning |
| --- | --- |
| Upstream executable baseline | AutoTavern / TavernGym 36.6.3.253932 |
| Project training snapshot | `release/rules-candidate-20261101-maxwell-pool-v2`, the original project candidate identifier; published copy: `training/rules/` |
| Target rules contract | `37.0.0.255130`, solo eight-player mode, accepted within a fixed named working engineering scope |
| Live adapter build | `37.0.0.255790`; an adapter build number does not certify all simulator rules |
| Supported entry | `training/rules/target37_entry.py:create_target37_backend`, loading the named roster and overlays |
| Strict official equivalence | Unproved; retain the boundaries expressed by `strict37_qualified=false` and `full37_complete=false` |

The entry, binding and overlays define the working contract. An inherited 36.6.3 metadata string alone does not negate the accepted engineering scope. Conversely, relabelling a target-build field cannot establish complete official parity.

## Official patch and hotfix review

The [official 37.0 notes](https://news.blizzard.com/en-us/article/24301454/37-0-patch-notes) describe the October 13 launch. The [official 37.0.1 forum announcement](https://us.forums.blizzard.com/en/hearthstone/t/3701-hotfix-patch/166622) describes an October 19 server-side hotfix with Battlegrounds fixes. Client build numbers alone do not identify server hotfix coverage.

This was a static review. No new client session or rule tests were run.

| 37.0.1 item | Evidence located in the project | Conclusion of this review |
| --- | --- | --- |
| Leeroy / Jaws of Death restriction | `TARGET_ROSTER_BINDING.json` denies normal/golden `BG23_318` with `...000t16`; `source/crates/taverngym/tests/target_roster.rs` contains a native-filter test with a neighboring allowed control | Covered in the named rule layer; tests were not rerun here and current server parity is not certified |
| Tier-four Dark Paradox / Toreth's Blessing restriction | Same binding denies `BG36_360t5` and `BG36_360_Gt5` with `...000t15`; the card table identifies both as tier four | Covered by static binding; not proof of all forms or interactions |
| Heroic Broodmother / Invulnerability restriction | Same binding denies `BG36_849` and `_G` with `...000t60` | Covered by static binding; not newly verified in live play |
| Hooktusk trigger from Timewarped Nellie's Ship discovery | Related scripts exist, but this review did not establish an independent acceptance chain for that precise hotfix | Unconfirmed, rather than a demonstrated defect |
| Recruit-phase Reborn death retaining the correct state after combat | No specific hotfix acceptance chain established in this review | Unconfirmed; requires the corresponding source, reproduction and evidence index |
| Gunpowder Courier remaining-Gold display | Working contracts describe spending behavior; the card table still contains static “6 Gold left” text | Behavior acceptance does not certify dynamic display synchronization; display hotfix unconfirmed |

The supported statement is that several named 37.0.1 restrictions are represented while the project follows 37.0. “All hotfixes synchronized” would exceed the evidence. An unconfirmed item does not automatically revoke existing engineering acceptance or establish a new bug.

## Acceptance scope

Local source records are `规则复验指挥/reuse-20261028/FINAL_RULE_ACCEPTANCE.json`, `FINAL_RULE_EVIDENCE_INDEX.json`, and `BGagent正式版1.0/evidence/TRAINING_MAXWELL_POOL_REPAIR_ACCEPTANCE.json`. The first accepts the fixed named 37.0 working contract and required independent review process, while explicitly withholding universal official-server parity. The Maxwell record accepts a direct-offer correction for two trinkets and preserves the original failure and limitations on strength evidence. It is not a fresh full-rule certification or a live-rating acceptance.

Inspectable published files include the [roster binding](../training/rules/TARGET_ROSTER_BINDING.json), [overrides](../training/rules/TARGET_OVERRIDES.json), [source provenance](../training/rules/CONDITIONAL_RELATION_PROVENANCE.json), and [API contract](../training/rules/bridge/API_CONTRACT.json). Internal acceptance paths identify provenance; their inclusion in the public package must be checked separately.

## Continuing maintenance

Before each release, review official announcements and server hotfixes. Track affected identities and events with explicit implemented, verified, unconfirmed or inapplicable status. For an actual change, retain a minimal reproduction, obtain independent review, run the affected regressions, and freeze a new rules and roster fingerprint. Update checkpoint compatibility metadata, migration notes and the changelog. Repeat affected evaluations when the sampling distribution changes. Preserve old snapshots so existing runs remain reproducible. Expand a patch-coverage claim only after its evidence has been reviewed.

This is a maintenance plan and procedure. This documentation task did not activate automatic updating, training, client operations or new automations. After publication, readers should use a newer dated release identifier and its evidence to determine version status.

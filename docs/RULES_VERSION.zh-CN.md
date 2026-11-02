# 规则版本与持续维护

核对日期：2026-11-03。English: [RULES_VERSION.en.md](RULES_VERSION.en.md)。

**这是项目当前采用的最新冻结规则候选，面向37.0版本持续维护；不宣称已证明与截至今日全部服务器热修完全一致。**“项目最新快照”指本发布选定的工程工件，不是永久最新承诺。

| 层级 | 当前绑定与含义 |
| --- | --- |
| 上游执行基线 | AutoTavern / TavernGym 36.6.3.253932 |
| 项目训练规则快照 | `release/rules-candidate-20261101-maxwell-pool-v2`；此处为原工程候选标识，发布副本在 `training/rules/` |
| 目标规则契约 | `37.0.0.255130`，单人八人局；经固定工作契约的受限工程验收 |
| 实战适配构建 | `37.0.0.255790`；适配构建号不能证明模拟器已同步同构建全部规则 |
| 公开入口 | `training/rules/target37_entry.py:create_target37_backend`，加载命名卡池绑定与覆盖层 |
| 官方严格等价 | 未证明；保留 `strict37_qualified=false` / `full37_complete=false` 的证据边界 |

入口绑定和覆盖层属于实际工作契约。不能仅看桥接层遗留的36.6.3标签就否认已验收工程范围，也不能把目标构建字段改名当作完成全部官方规则。

## 官方补丁与热修核对

[官方37.0公告](https://news.blizzard.com/en-us/article/24301454/37-0-patch-notes)说明37.0于10月13日上线。[官方37.0.1论坛公告](https://us.forums.blizzard.com/en/hearthstone/t/3701-hotfix-patch/166622)明确是10月19日推送的服务器热修，包含酒馆战棋修复。服务器热修不能只由本地客户端构建号判断。

本次静态核对如下，未运行新的客户端或规则测试：

| 37.0.1事项 | 当前查到的项目证据 | 本次能下的结论 |
| --- | --- | --- |
| Leeroy不能获得Jaws of Death | `TARGET_ROSTER_BINDING.json`拒绝普通/金色 `BG23_318` 与 `...000t16`；`source/crates/taverngym/tests/target_roster.rs`包含原生过滤及邻项对照测试源码 | 命名规则层已覆盖；本次未重跑测试或证明当前服务器等价 |
| 四星Dark Paradox不能获得Toreth's Blessing | 同一绑定拒绝 `BG36_360t5` / `BG36_360_Gt5` 与 `...000t15`；卡表显示这两个形式为四星 | 静态绑定已覆盖；非全部形态或全部交互的证明 |
| Heroic Broodmother不能获得Invulnerability | 同一绑定拒绝 `BG36_849` / `_G` 与 `...000t60` | 静态绑定已覆盖；非本次实战验证 |
| Hooktusk与Timewarped Nellie's Ship的发现触发 | 能查到相关卡脚本，尚未在本次核对中建立这条热修的独立验收链 | 未确认；不等同于已知缺陷 |
| 招募阶段死亡的复生随从战斗后不恢复复生 | 未建立该具体状态转换的热修验收链 | 未确认；需要对应来源、复现与证据索引 |
| Gunpowder Courier剩余金币显示修复 | 工作契约包含花费阈值等行为；卡表仍带静态“6 Gold left”文本 | 行为契约不证明动态显示已同步，显示热修未确认 |

因此可说“已覆盖若干37.0.1命名限制并跟进37.0”，不能说“所有热修已同步”。未确认表示本次证据不足，不自动撤销既有工程验收，也不凭空创建缺陷。

## 工程验收的范围

本地来源为 `规则复验指挥/reuse-20261028/FINAL_RULE_ACCEPTANCE.json`、`FINAL_RULE_EVIDENCE_INDEX.json` 及 `BGagent正式版1.0/evidence/TRAINING_MAXWELL_POOL_REPAIR_ACCEPTANCE.json`。前者接受固定37.0命名工作契约与独立审查流程，明确不证明官方服务器全面等价；后者接受两张Maxwell饰品的直接供给修正，保留旧失败及强度证据限制。它不是重新证明全部规则，也不是实战积分验收。公开副本可核对 [绑定](../training/rules/TARGET_ROSTER_BINDING.json)、[覆盖层](../training/rules/TARGET_OVERRIDES.json)、[来源记录](../training/rules/CONDITIONAL_RELATION_PROVENANCE.json) 和 [接口契约](../training/rules/bridge/API_CONTRACT.json)。内部验收路径是来源标识，不假定其已随公开包分发。

## 持续维护计划

每次发布前核对官方公告及服务器热修；按对象和事件记录“已实现、已验证、未确认、不适用”。对实际变化建立最小复现、独立审查和受影响回归，再冻结新的规则与卡池哈希。更新模型兼容元数据、迁移说明与变更日志；分布变化后重做受影响评估。旧快照保留，避免无记录地改变现有训练。只有完成该补丁的证据核对后，才扩大覆盖声明。

这是维护流程与计划，未在本次启动自动更新、训练、客户端操作或新自动化。发布日期之后的版本状态应以新的日期、发布标识及证据为准。

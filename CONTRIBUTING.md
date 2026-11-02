# 参与贡献 / Contributing

欢迎规则修复、独立实验、对手设计、性能测量、文档和经许可的数据贡献。先在 Issue 说明任务、规则版本、预算与验证办法，再提交可审查的 PR。

We welcome rule fixes, independent experiments, opponent design, measurements, documentation, and permitted data. Describe the task, rule version, budget, and validation in an issue before submitting a reviewable PR.

## 贡献算力 / Contributing compute

1. 使用固定代码提交和规则版本，在自己的机器启动独立运行。先短测，再自行决定预算；项目不会自动租机器或承诺报销。
2. 提交配置、依赖、硬件、实际时长、训练完整局数、优化器更新数、种子范围、规则/卡表/模型契约、对手池哈希和独立评测。
3. 保留异常数与排除理由；按相同规则和固定对手比较多个训练种子。完整八人对局才是独立评估单位。
4. 分享模型前先检查内容并移除私人数据。维护者重新验证兼容性与棋力；不要在 PR 中塞入大型二进制或私人日志。

Use a pinned source revision and rule snapshot, run a small check, then choose your own budget. Report configuration, dependencies, hardware, elapsed time, normal completed lobbies, optimizer updates, seed ranges, all relevant contracts, opponent hashes, exclusions, and independent evaluation. Compare multiple training seeds under the same protocol. A complete eight-player lobby is the sampling unit. Review checkpoint contents before sharing; maintainers must independently verify compatibility and strength. Do not add large binaries or private logs to PRs.

目前没有分布式学习、联邦学习、远程轨迹接收或独立权重平均。共享统计不等于合并学习成果；选择最佳候选不等于融合所有策略。未经审查的历史轨迹不得直接混入 on-policy PPO。

Distributed/federated learning, remote rollout ingestion, and independent weight averaging are absent. Aggregating metrics is not aggregating learning. Selecting a candidate does not fuse all policies. Old trajectories must not be inserted into the current on-policy PPO objective.

## 高手数据与 BC / Expert data and behavior cloning

高手数据和 BC 是优先研究方向，尚不是已经交付的完整训练流程。建议贡献逐决策的公开观察、合法动作、所选动作、版本、结果、授权和质量信息；先划分训练/验证/测试，再开发行为克隆基线。仅视频画面、最终阵容或赛后日志未必能恢复决策时的全部公开状态。不得把对手隐藏牌、未来随机数或赛后才知道的信息混入策略输入。

Expert data and BC are priority research directions, not a delivered end-to-end pipeline. Useful records include public observations at decision time, legal actions, the chosen action, version, result, permission, and quality metadata. Split training/validation/test data before developing a BC baseline. Video or final-board records may not reconstruct decision-time state. Hidden cards, future randomness, and hindsight information must not enter the policy.

## 检查点信任边界 / Checkpoint trust

现有 `.pt` 检查点包含优化器、Python 对象和恢复元数据；部分加载器使用 `torch.load(..., weights_only=False)`。**不要直接加载不可信陌生人发来的检查点。** SHA256 证明文件一致，不证明文件安全。社区模型接收应先建立隔离审核和仅张量的分发格式；此流程尚未实现。

Existing `.pt` checkpoints contain optimizer state, Python objects, and recovery metadata; some loaders use `torch.load(..., weights_only=False)`. **Do not directly load untrusted checkpoints.** A SHA256 proves identity, not safety. Isolated review and a tensor-only distribution format are prerequisites for a future public model intake service; that service is not implemented.

## 规则维护 / Rules maintenance

每次补丁记录官方来源、旧/新版本、卡池/机制差异和已知假设，增加最小复现，再审查合并。更新模型契约、兼容拒绝和迁移说明；将未经验证的变化标为候选。参见 [规则版本](docs/RULES_VERSION.zh-CN.md) / [rule versions](docs/RULES_VERSION.en.md)。

For each patch, record official sources, old/new versions, roster/mechanic changes, and assumptions. Add a minimal reproduction before review. Update contracts, compatibility rejection, and migration notes, and mark unverified changes as candidates.

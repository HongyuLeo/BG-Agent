# BG-Agent v0.1.0-research

首个公共研究预览 / First public research preview

## 中文

把酒馆战棋AI的规则适配和训练过程开放出来，让更多人能动手研究。

- Linux / WSL 从零初始化、完整对局 PPO、暂停续训和导出。
- 实体 Transformer + 每座位 GRU + 合法动作掩码。
- 基于 AutoTavern / TavernGym 的命名37.0目标规则适配；保留上游许可。
- 中英双语指南、规则边界、研究建议及社区贡献入口。
- 附带最新 Windows 桌面与隔离实战组件源码，需本机适配与手动验收。

**已验证**：CPU从零两局、暂停、续训一局，累计44次优化器更新；导出校验通过。选择性桌面/实战源码检查38项通过。依赖复用了现有测试环境，尚未验证全新机器安装、CUDA、长期训练或天梯棋力。

**当前没有强力预训练模型，不支持多人独立权重自动合并，也不宣称与全部最新服务器热修完全一致。** 邀请大家贡献可复现实验、规则与评测、经授权的数据。技术应当平权。

[中文训练指南](https://github.com/HongyuLeo/BG-Agent/blob/v0.1.0-research/training/README.zh-CN.md) · [版本说明](https://github.com/HongyuLeo/BG-Agent/blob/v0.1.0-research/docs/RULES_VERSION.zh-CN.md) · [参与贡献](https://github.com/HongyuLeo/BG-Agent/blob/v0.1.0-research/CONTRIBUTING.md)

下载区的 ZIP / tar.gz 是源码，包含构建依赖清单，没有模型权重和预编译客户端。请按指南安装。

## English

An open research entry point for Battlegrounds rule adaptation and policy training, built on AutoTavern / TavernGym with upstream attribution preserved.

- Linux/WSL scratch initialization, complete-lobby PPO, pause/resume/export.
- Entity Transformer, per-seat GRU and legal action masking.
- Named 37.0 target-rule adaptation, bilingual guides and explicit limitations.
- Windows desktop/live reference source, requiring local integration and manual acceptance.

**Verified**: two CPU training lobbies plus one resumed lobby, 44 cumulative optimizer updates, export hashes, and 38 selected desktop/live source tests. Existing dependencies were reused. Clean-machine installation, CUDA, long-term training and ladder strength remain unverified.

**No strong pretrained model, independent-weight merging, or complete latest-server parity claim.** Contributions to reproducibility, rules, evaluation and permissioned expert data are welcome.

[Training guide](https://github.com/HongyuLeo/BG-Agent/blob/v0.1.0-research/training/README.en.md) · [Rule versions](https://github.com/HongyuLeo/BG-Agent/blob/v0.1.0-research/docs/RULES_VERSION.en.md) · [Contributing](https://github.com/HongyuLeo/BG-Agent/blob/v0.1.0-research/CONTRIBUTING.md)

Release downloads are source archives, not pretrained weights or prebuilt client installers.

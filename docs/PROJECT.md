# 项目结构与发布边界 / Project structure and release boundaries

## 当前组成 / Current components

| 目录 / Directory | 中文 | English |
|---|---|---|
| `training` | 从现有云训练工程整理的可移植研究入口；独立规则构建和从零初始化 | Portable research entry derived from the cloud trainer, with local rule build and scratch initialization |
| `desktop/app/bgagent10` | 最新训练桌面、完整PPO、模型模拟、生命周期与恢复源码 | Latest desktop training, PPO, simulation, lifecycle and recovery source |
| `live/app/bgagent10` | 后续隔离维护的实战研究组件，CPU推理与独立停止机制 | Separately maintained live research components, CPU inference and independent stopping |
| `docs` | 论文研究、版本与维护、发布核验 | Research, versions, maintenance, and publication validation |

正式版、早期体验版、规则审计副本与demo历史构成同一研究过程；重复副本、原始操作记录、各机器运行环境与私人权重不适合组成公共源仓库。本发布选择最新有效组件并保留来源散列，不上传整个工作目录历史。`docs/source-snapshot.json`记录桌面/实战文件的源与发布散列；训练包有自己的 provenance。

The formal application, earlier prototypes, audits, and demos are part of the project's history. Duplicate copies, operational transcripts, machine runtimes, and private weights are excluded. This release consolidates the latest useful components rather than publishing the entire working directory history. `docs/source-snapshot.json` records source/published hashes for desktop/live files; training has separate provenance.

## 模型与边界 / Model and boundaries

策略输入为3227个公开数值特征、124个卡牌索引和245个动作掩码；规则驱动持有真实动作票据，私有快照与随机种子不进入网络。实体Transformer和独立座位GRU输出合法动作分布、价值与名次预测。卡牌语义使用规则文本/数值的结构化与哈希编码，不能宣传为完整语义理解或预训练语言模型。

The policy receives 3,227 public numeric features, 124 card indices, and a 245-action mask. The trusted rule driver holds action tickets; snapshots and random seeds do not enter the network. An entity Transformer and per-seat GRU predict actions, value, and placement. Rule-text/numeric hashing is not a complete semantic parser or pretrained language model.

当前训练是同步完整对局recurrent PPO，一个learner集中推理与更新，多环境进程同机采样。支持脚本和冻结历史对手。完整自动课程、高手BC、分布式学习、搜索蒸馏和自动冠军联赛不是本快照已验证的能力。

Training is synchronous complete-lobby recurrent PPO with one learner and local environment processes. Scripted and frozen historical opponents are supported. Fully automatic curricula, expert BC, distributed learning, search distillation, and automatic champion leagues are not validated capabilities of this snapshot.

## 桌面与实战 / Desktop and live source

推荐公共复现入口为`training`。`desktop`和`live`保留最新源码，但原安装使用本机注册的冻结规则、解释器、模型和客户端资料；公共仓库不包含这些私人运行绑定。`start.py`是开发参考入口，不是已验证的跨机器安装器。不要直接运行后期待旧模型、客户端和规则自动匹配。

Use `training` for public reproduction. `desktop` and `live` preserve current source, but the private installation used local rule, interpreter, model, and client bindings that are not distributed. Their `start.py` files are development reference entries, not verified cross-machine installers.

实战源码包含日志解析、公开种族读取助手、布局与时序处理。助手严格限定公开列表读取，保留上游许可和构建源码，不发布客户端DLL或已编译助手。`public_races/build.ps1`可供Windows开发者审查构建。实战只读回放/单元测试不等于真实客户端成功；全部新版本实机适配仍需用户手动验收。

Live source includes log parsing, a narrowly scoped public-race reader, layout and sequencing logic. The helper retains attribution and build source; game DLLs and helper binaries are excluded. Windows developers can review `public_races/build.ps1`. Replay/unit checks do not establish live-client success; new-client adaptation still requires manual acceptance.

## 历史证据与本发布 / Historical versus release evidence

历史正式工程曾通过20局离线训练验收以及后续恢复修复，旧云包曾通过WSL CPU和Windows回读。这些记录不自动成为本公共快照的验证。当前训练入口的真实短测见`training/VALIDATION.json`；根级源码检查见`docs/RELEASE_VALIDATION.json`。无天梯强度证明，无云GPU速度或费用基准。

Historical private releases passed a 20-lobby offline gate and later recovery checks; an older cloud package passed WSL CPU and Windows return checks. Those results do not automatically validate this public snapshot. See `training/VALIDATION.json` for its short run and `docs/RELEASE_VALIDATION.json` for source checks. No ladder-strength, cloud-GPU throughput, or measured cost claim is made.

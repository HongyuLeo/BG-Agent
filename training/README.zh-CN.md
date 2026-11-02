# 从零训练（Linux / WSL2）

[English](README.en.md) · [项目主页](../README.md)

这里是独立的便携训练目录，包含训练代码、冻结规则源码及 AutoTavern MIT LICENSE / NOTICE。没有预训练权重、私有观战数据或真实客户端依赖。规则是云端训练 ZIP 内的 `rules-candidate-20261101-maxwell-pool-v2` 快照，来源指纹见 `RELEASE_SOURCE.json`；上游基础版本 36.6.3.253932，具名目标卡池为 37.0.0.255130，**不代表全部 37 规则完全复刻或官方认证**。

## 安装

需要 Linux x86_64、Python 3.10–3.12、网络、Rust 1.98.1 和 C 编译工具。Windows 请在 WSL2 Ubuntu 终端中执行。推荐将仓库放在 Linux 文件系统以加快编译。

```bash
sudo apt-get update
sudo apt-get install -y build-essential python3-dev python3-venv pkg-config curl
cd training
bash setup.sh --cpu-test
```

安装脚本在本目录创建 `.venv`，安装固定版本 NumPy 2.2.6 / Maturin 1.15.0 / PyTorch 2.8.0 CPU，安装 Rust 工具链并从冻结源码编译 release 原生扩展。首次安装会下载依赖；安装后训练本身不需要联网。无须账号、API 密钥或云服务。`bootstrap.py` 校验源码、生成本机解释器/扩展绑定，并按 seed=197 创建 `models/scratch-initial.pt`。这是随机初始化模型，完成局数为 0。重复 bootstrap 不覆盖已有模型，绑定或模型档位不兼容会拒绝。

## 有界训练和检查

```bash
.venv/bin/python -B tests/test_release.py
bash start.sh
bash monitor.sh
# 或等待本次运行结束，每 5 秒打印状态：
.venv/bin/python cloud_run.py status --watch 5
```

默认 `config/cloud.json`：CPU、micro 模型、1 worker、1 round × 2 个完整八人局、2 Torch 线程，关闭评估，随机和 balanced 脚本对手按种子抽样。每完成一局执行一次更新并发布检查点，全部 2 局结束后 state=completed；同一目录只允许一个训练进程。此默认值用于验证流程，不构成模型强度或吞吐承诺。训练可因严格规则或数值检查失败并保存诊断，请检查运行目录的 `process.log` / `status.json`；默认不跳过失败局。

状态中的 completed_games 仅计已正常结束且提交优化/检查点的训练对局。评估、采样中的对局另计。模型输出在 `data/runs/<run>/checkpoints/`，配置与指标在同一运行目录。

## 暂停、续训、导出

```bash
bash pause.sh --wait 60
bash resume.sh
# 导出 trainer 正式发布的最新边界，文件名必须尚不存在：
bash export.sh exports/checkpoint-001.zip
```

暂停在安全保存边界生效，60 秒超时不是暂停成功；确认 state=paused 且 process_alive=false。`resume.sh` 从最近运行公开的检查点恢复优化器、调度器、RNG 和累计计数；默认再运行配置中的 2 局。也可明确选择运行：

```bash
.venv/bin/python cloud_run.py start --resume RUN_ID --rounds 1 --games-per-round 2
```

如需持续训练，在短测通过后显式执行 `bash resume.sh --rounds 0`；0 表示直到用户暂停或保护性暂停，不是默认值。评估默认关闭，可通过 `--eval-every 10 --eval-games 2` 显式开启；小样本结果不能证明强度。

导出 ZIP 包含检查点、配置、聚合指标、规则指纹；不包含原始回放/快照/完整错误日志。它仍包含本机运行路径，不宜原样公开。仅加载自己信任的 PyTorch 检查点。源码仓库不得提交 `.pt`、运行目录或导出文件。

## 档位和 GPU

需要更大模型时，在**全新训练副本第一次 setup 前**将 `config/cloud.json` 的 model_preset 改为 small 或 main，然后重新初始化。micro / small / main 结构不同，不能直接互相续训。默认的随机脚本对手无需额外权重；可用同规则、同模型契约的自训权重构建固定对手池，必须指定 SHA256。

GPU 环境请在确认驱动后，按 PyTorch 官方安装方式在 `.venv` 中安装对应 CUDA 的 **2.8.0** wheel，再执行 `bash start.sh --device cuda`。训练器会检查 CUDA 可用性。本文未验证 GPU、远程云平台或长时训练。

绑定检查严格比较规则、原生扩展、卡牌目录和模型学习契约。换平台、重编译后扩展字节变化、改源码或移动解释器可能导致旧模型拒绝加载；本包不自动重贴绑定。请保留原训练目录/环境用于续训和导出。

## 离线验证边界

`tests/test_release.py` 校验冻结源码、从零检查点的真实加载、规则/卡牌/学习契约错配拒绝，以及有限/无限批次调度。安装后再跑 2 局才验证真实 PPO 路径；只运行单元检查不能替代完整对局训练。发布准备中所做的实测另见 `VALIDATION.md`。

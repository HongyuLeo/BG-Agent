# 发布训练副本验证

日期：2026-11-03。仅在本目录副本内运行；没有使用私有起始权重、云GPU、真实客户端或正式训练进程。

环境：WSL Ubuntu 24.04 x86_64，既有测试虚拟环境 Python 3.12、PyTorch 2.8.0+cpu、NumPy 2.2.6、Maturin 1.15.0、Rust 1.98.1。测试复用了现有依赖；没有声称在空白系统重新下载安装所有依赖。下列 `python` 指该测试解释器。

运行命令（从 training 目录）：

```bash
python bootstrap.py --cpu-test
python -B tests/test_release.py
python -B cloud_run.py start
python -B cloud_run.py pause --wait 30
python -B cloud_run.py export --output exports/first-boundary.zip
python -B cloud_run.py start --resume latest --rounds 1 --games-per-round 1
```

结果：

- 从本包源码完整编译 release wheel 成功；没有复制现成 native 二进制。原生 source_hash=`13d71ac51a979679`。
- 初始 checkpoint 是本机 seed=197 随机初始化的 micro，0 完成局数，真实严格加载成功。
- 离线 3 项测试通过：源码校验、有限/持续批次调度、检查点加载及 binding/catalog/contract 三类错配拒绝。
- 第一运行默认 2 个完整八人训练局，累计 completed_games=2、updates=26、隔离错误=0；暂停请求后 state=paused，process_alive=false，暂停确认成功。该运行记录 elapsed_seconds=32.59，仅是本次短测，不是长跑吞吐承诺。
- 从发布边界恢复，再完成 1 局，state=completed，累计 completed_games=3、updates=44、隔离错误=0；继续了模型、优化器、RNG 和累计计数。
- 首次导出成功，ZIP 中 10 个文件，逐项重算 SHA256SUMS 全部匹配；检查点 SHA256=`397c07d68fa2481b550c66262b6be4449443d645c0de8a774ba2afae5459957a`。未导出原始回放、快照或错误详情。
- Rust 两个 crates 下 161 个文件（含数据/构建文件）逐字节等于原始云包，规则语义未修改。只清理两个规则元数据 JSON 的个人源路径；本机解释器/扩展绑定在 bootstrap 生成。模型学习代码保留原契约。

验证结束后删除本目录生成的 build/models/data/exports、READY、扩展二进制和缓存，并恢复构建前绑定占位符；发布源码不携带测试生成的任何权重或日志。

未验证：完整新机器网络安装、GPU、远程云平台、跨平台模型迁移、长时稳定性、对局强度、全部目标版本规则正确性。

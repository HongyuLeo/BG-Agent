# Third-party notices / 第三方归属

## AutoTavern / TavernGym

Source: https://github.com/MCG-NJU/AutoTavern

The Rust simulator and Python interface under `training/rules/source` derive from AutoTavern by Changlian Ma and Limin Wang and its contributors. Preserve `training/rules/source/LICENSE` and `training/rules/source/NOTICE`. BG-Agent adds target-rule adaptations and training/application code; it does not claim authorship of the upstream simulator or reproduce the unpublished TavernAgent trainer/weights.

规则模拟器与Python接口来自AutoTavern；保留原MIT许可及NOTICE。本项目增加规则适配和训练/应用代码，不把上游模拟器或未公开的TavernAgent成果称为原创。

## bgtracker

Source: https://github.com/BattlegroundsHelp/bgtracker

The public-race helpers in `desktop/app/bgagent10/public_races` and `live/app/bgagent10/public_races` adapt Mono traversal ideas and offsets from bgtracker. Their `LICENSE` and `ATTRIBUTION.txt` remain alongside the code. The helper is narrowed and modified; it is not an unchanged upstream program.

公开种族读取助手复用了bgtracker的Mono遍历思路和偏移结构；原许可和归属保留在组件目录。

## Game content

Hearthstone, Battlegrounds, their card names and rule descriptions belong to their respective rights holders. The software license does not transfer ownership of game content or trademarks. No official client files or artwork are included.

游戏、商标和卡牌内容保留原权利归属。软件许可不赋予游戏素材与商标权利。未分发官方客户端或美术资源。

## Dependencies

PyTorch, NumPy, maturin, Rust crates, and other installed dependencies remain under their own licenses. They are installed from their upstream package sources and are not bundled as a private runtime in this repository. Cargo.lock pins the Rust dependency graph.

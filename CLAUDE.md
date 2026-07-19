# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What's in this directory

`/Users/haoning/project/chiplet/` 是 chiplet-related 研究项目的 container，目前包含：

- `ThermoDSE/` — 核心代码仓库（git remote: `https://github.com/Jian-PENG207/ThermoDSE.git`，origin/main 一次 initial commit）。热感知 chiplet DNN 加速器 DSE 框架，论文 "ThermoDSE" 投稿于 IEEE Transactions on Computers。
- `Gemini_Mapping_and_Architecture_Co-exploration_for_Large-scale_DNN_Chiplet_Accelerators.pdf` — 相关参考论文。
- `.claude/settings.json` — 该项目的 Claude Code 环境配置（注意：`ANTHROPIC_BASE_URL` 指向 `api.minimaxi.com/anthropic`，不是官方 Anthropic API，使用第三方代理）。

## ThermoDSE 概览

Thermal-aware and comprehensive design space exploration framework for chiplet-based DNN accelerators，集成 chiplet / NPU core / task orchestration / inter-chiplet communication 的细粒度建模，受 heat 与 area 双重约束。来源：基于 Timeloop / Accelergy 的研究代码栈（Tsinghua + Stanford，BSD-3）。

## ThermoDSE 目录约定

- `core/` — 硬件建模与仿真层。核心类是 `chiplet_evaluator` (`core/chiplet_eva.py`)，所有优化器最终都调用它评估一组硬件参数。包含 task DAG (`taskdag.py`)、schedule (`schedule.py`)、partition engine (`partengine.py`)、floorplan 生成 (`gen_floorplan.py`)、TSMC 28nm 单元库 (`tsmc28_lib.py`)、NoP 拓扑 (`nop.py`)。
- `nns/` — 神经网络 workload 描述。每个 `.py` 文件（resnet50、googlenet、unet、mobilenet、yolo、transformer、lstm_gnmt、vgg、alexnet、toy_net 等）导出一个 `NN` 对象，通过 `nns.import_network(name)` 加载。License header 显示这一层是 Timeloop/Accelergy 派生的 BSD-3 代码。
- `rl_opt/` — Baseline 算法实现。`sa_opt.py` 是 TESA 系列（Simulated Annealing），`rl_ppo.py` 是基于 stable-baselines3 PPO 的 RL baseline；`rl_opt_archs.py` 缓存历次运行的架构结果。
- `tools/` — 论文提出的方法（SCBO）和工具脚本。`scbo_search.py`（533 行）是单目标 SCBO 主入口；`scbo_two_search.py`（609 行）是双目标 Pareto-front SCBO；`scan_best_2.py` 对 SCBO 结果做后处理与扫描；`search_arch.py` 是早期 BO 版本（`bayes_opt` 库）；`search_debug.py` / `search_util.py` 调试工具；`nn_evaluation.py` / `nn_layer_stats.py` workload 统计；`gen_floorplan.py` / `grid_thermal_map.py` 已复制到 `core/` 中，`tools/` 里是早期副本。
- `tmp/` — HotSpot 仿真工作目录模板。每次并行 process 会拷贝成 `tmp_0/`、`tmp_1/`...（由 `-sp` 参数控制路径）。
- `test/` — HotSpot 仿真 demo（`run.sh`），需要外部 HotSpot7 二进制（默认 `../../HotSpot/hotspot`）。
- `script/` — 画图脚本（`draw_iteration.py`、`draw_area.py`、`draw_space.py`、`pareto.png` 已生成的图）。
- `tools/results_new/`、`tools/results_bc/`、`tools/scbo/`、`tools/fig_motivated/` — 实验结果与图例。

## 外部依赖（必须先满足）

- **Python**: `gymnasium==1.1.1`、`botorch==0.14.0`、`gpytorch`、`torch`、`numpy`、`stable-baselines3`（仅 PPO baseline）。`conda install gymnasium && conda install botorch -c gpytorch -c conda-forge`。
- **HotSpot7**（thermal simulator）：不在本仓库。需独立编译/下载到路径 `<parent>/HotSpot/`（多数脚本默认值是 `../../HotSpot/`）。
- 内部脚本 `import` 路径会 `sys.path.append('../')`，且多处硬编码相对路径（`../../HotSpot` 等），所以**必须在仓库根目录（`ThermoDSE/`）的子目录里跑脚本**，例如 `cd tools && python scbo_search.py ...`，不要从任意目录跑。

## 怎么跑（论文复现命令）

主方法 SCBO（单目标，能量-延时-产率乘积，受面积与峰值温度约束）：

```bash
cd ThermoDSE/tools
python scbo_search.py -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp
```

Pareto-front 双目标 SCBO：

```bash
cd ThermoDSE/tools
python scbo_two_search.py -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp
```

Baseline 1（chiplet-gym 的 RL PPO）：

```bash
cd ThermoDSE/rl_opt
python rl_ppo.py -b1 1 -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp_0
```

Baseline 2（TESA with ideal scheduling）：

```bash
cd ThermoDSE/rl_opt
python sa_opt.py -b2 1 -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp_1
```

Baseline 3（TESA with non-ideal scheduling）：

```bash
cd ThermoDSE/rl_opt
python sa_opt.py -b3 1 -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp_2
```

HotSpot 仿真 demo（不依赖 Python，验证 HotSpot 是否装好）：

```bash
cd ThermoDSE/test
bash run.sh    # 调 ../../HotSpot/hotspot，生成 outputs/*.grid.steady + 散热图
```

## 共享 CLI 参数（所有优化器一致）

| Flag | 默认 | 含义 |
|---|---|---|
| `-m / --map` | 0 | 是否在搜索时包含 inter-chiplet mapping 阶段 |
| `-tm / --thermal_aware_map` | 1 | 1=thermal-aware mapping, 0=data-aware only |
| `-hp / --hotspot_path` | `../../HotSpot` | HotSpot 二进制根路径 |
| `-sp / --sim_path` | `../tmp` | 热仿真工作目录（会被复制成 `tmp_x/`） |
| `-wi / --wkld_idpdt` | 0 | peak temp 取多网络的 max (1) 还是各自独立 (0) |
| `-maxT / --max_temp` | 348 / 200 | 峰值温度约束（K） |
| `-maxA / --max_area` | 300 / 200 | 面积约束（mm²），脚本内部会 ×1e-6 转 m² |
| `-b1/-b2/-b3` | 0 | 在 SCBO 模式下选 baseline 架构 (`chiplet-gym` / `TESA` / `scalable MCM`) |

## 算法核心点（CI 改动时要知道）

**Eval 接口：** 所有优化器都遵循同一签名：

```python
from core.chiplet_eva import chiplet_evaluator
evaluator = chiplet_evaluator(hotspot_path, sim_path, sys_info:list, thermal_map=True, baseline1=False, baseline2=False, baseline3=False, wkld_idpdt=False, clock_freq=1.8e9)
evaluator.generate_hardware()
delay, energy, die_yield = evaluator.evaluate(batch=2)
```

`sys_info` 是一个 10-tuple：`[chipletX, chipletY, chipletCx, chipletCy, chiplet_intvl, mtxu_h, mtxu_w, ubuf_size, nop_bw, dram_bw_design]`。

**Search dimension：** 在 `scbo_search.py` 的 `design_space` 顶层定义，每个优化器（baseline1/2/ours）会改 `design_space` 维度集。SCBO 把约束用 BoTorch 的 `ConstrainedMaxPosteriorSampling` 处理（Thompson sampling 加可行性近似）。

**Eval cost metric：** `-delay * energy / die_yield`（最大化）。`yield` 受 peak temperature 约束影响（超温 → yield 下降）。

**HotSpot 集成：** `chiplet_evaluator.generate_hardware()` 把 sys_info + workload 写成 `.flp` / `.ptrace` / `.lcf` / `.materials`，然后调 HotSpot 跑稳态（steady-state）仿真取峰值温度。每次 eval 都 fork HotSpot，所以并行时每个 worker 必须有独立 `sim_path`。

**调度 vs. 映射：** DSE 搜索只决定架构；任务调度由 `core/schedule.py`、`core/taskdag.py` 处理；inter-chiplet mapping 受 `-tm` flag 控制（thermal-aware vs. data-aware）。

## 研究代码特有的注意事项

- `core/cluster.py` 和 `core/taskmap.py` 是空 stub（0 行），不要 import。
- 多处 `import` 用 `sys.path.append('../')`，所以脚本要在 `tools/` 或 `rl_opt/` 里跑。
- 优化器脚本顶层直接 `argparser().parse_args()`（模块级），所以**不能被 import**，必须在 `__main__` 里执行；想用程序化调用请改写成 wrapper。
- `details.txt`（183 KB）是 benchmark 数据表，别当作代码读。
- `script/data/*.txt` 是 SCBO 跑过的扫描记录；`tools/results_new/`、`tools/results_bc/` 是 SOTA 对比实验的结果缓存，做新 ablation 时建议清理 `tmp_x/` 与这些目录避免污染。
- 没有 setup.py / pyproject.toml；也没 pytest —— 唯一"测试"是 `test/run.sh`（HotSpot 集成 smoke test）。

## 修改时建议的入口

- **改 eval metric、加 yield/thermal 目标**：改 `core/chiplet_eva.py` 的 `chiplet_evaluator.evaluate()` 与末尾的代价组装。
- **改架构搜索空间**：改 `tools/scbo_search.py` 顶层的 `design_space` 列表以及 `target_function`/`sys_info` 装配处。
- **新增 optimizer baseline**：在 `rl_opt/` 新建 `xx_opt.py`，模仿 `sa_opt.py` 的 argparse + chiplet_evaluator 调用；导入路径 `sys.path.append('../')`。
- **新增 workload**：在 `nns/` 加一个导出了 `NN` 对象的 `.py` 文件，自动被 `nns.all_networks()` 与 `chiplet_eva.nets` 枚举使用。
- **改 HotSpot 调用**：所有路径集中在 `core/gen_floorplan.py`（生成 `.flp`）与 `core/statistic.py` 附近（解析 steady output）。

# G3 Real 2x2x2 Consolidated Report

Date: 2026-07-20  
Repository: `HaoningJiang-space/ThermoDSE-CertiTherm`

## Scope

目标矩阵：`2 DNN × 2 非同构架构 × 2 package = 8 cases`  
比较三种语义：`point estimate` / `placed-power reference` / `spatial equivalence set`

## Artifacts (single source of truth)

### Bundle

- Suite: `CertiTherm/evidence/g3_2x2x2_real_bundle/suite.json`
- Query bundles (4 strata): `CertiTherm/evidence/g3_2x2x2_real_bundle/queries/*/query.json`
- Case manifests (8 cases): `CertiTherm/evidence/g3_2x2x2_real_bundle/queries/*/arch_*/case_manifest.json`

### Execution outputs

- Suite artifact: `/tmp/certitherm_g3_real_outputs/g3_suite_artifact.json`
- Suite replay receipt: `/tmp/certitherm_g3_real_outputs/g3_suite_receipt.json`
- Query-level artifact+replay index: `/tmp/certitherm_g3_real_outputs/g3_case_query_artifact_receipts.json`
- 8-case matrix index: `/tmp/certitherm_g3_real_outputs/g3_case_matrix_index.json`
- Independent HotSpot witness replay: `/tmp/certitherm_g3_real_outputs/g3_independent_hotspot_witness_replay.json`
- Independent dual-backend witness replay: `/tmp/certitherm_g3_real_outputs/g3_independent_dual_backend_replay.json`
- Archived claim-grade copy (in-repo): `CertiTherm/evidence/g3_2x2x2_real_archive/`

### Artifact SHA-256

- `g3_suite_artifact.json`: `f8978d0d282ff0e0aafcc6ac1edbb107b4a9bbe5ea6019d885c928d54defe95e`
- `g3_suite_receipt.json`: `ecb8711e3167c6490bbbd2480a0e4f56628e8a6823f53354b41b6f6b7cd67990`
- `g3_case_query_artifact_receipts.json`: `258225b29f84b8558abf0b0843c9dbcad43de23cf0ac9b87c904699e8b9b97cd`
- `g3_case_matrix_index.json`: `9e724d0b4126558c8578aaba76cf0ef04a1119969aaf5ff4c18f333ffcf796d4`
- `g3_independent_hotspot_witness_replay.json`: `6bc4dc69626d5540f0f58ca0ea182cdd785e4cafaafdfdad1a9854b73a3e812f`
- `g3_independent_dual_backend_replay.json`: `17c4185cdb016bc21ba711326ba7edb82945d41f30de80717d70246465489975`

### Archived artifact SHA-256 (commit-bound)

See: `CertiTherm/evidence/g3_2x2x2_real_archive/manifest.json`

- archive manifest sha256: `59b9e629cc259fb0685701bf4e3fc7526d48c337da63758f8418085333413014`

## Integrity status

- `suite replay`: **PASS**
- `query_count`: **4** (cnn/attention × standard/enhanced)
- `case_manifest_count`: **8**
- `case_matrix_rows`: **8**
- `unresolved_variant_count`: **0**

## G3 metrics (from suite artifact)

- `point_certified_count`: 4  
- `placed_certified_count`: 4  
- `spatial_certified_count`: 2  
- `spatial_non_identifiable_count`: 2  
- `point_commitment_not_identifiable_count`: 2  
- `point_placed_disagreement_count`: 0  

## 4 query strata summary

| Query | Point | Placed | Spatial |
|---|---|---|---|
| `g3-real-cnn-standard_sink_s06` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) |
| `g3-real-cnn-enhanced_sink_s10` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) |
| `g3-real-attention-standard_sink_s06` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | **NON_IDENTIFIABLE** (`arch_5x4_rect_struct`, `arch_4x4_mesh_fullcut`, `NO_FEASIBLE_DESIGN`) |
| `g3-real-attention-enhanced_sink_s10` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | **NON_IDENTIFIABLE** (`arch_5x4_rect_struct`, `arch_4x4_mesh_fullcut`, `NO_FEASIBLE_DESIGN`) |

## Requirement check vs target

1. 8/8 输入真实且 replay 通过：**已完成**（suite + embedded query artifacts replay PASS）
2. 至少一个 point 在 spatial 下不可识别或与 placed 不同：**已完成**（`point_commitment_not_identifiable_count=2`）
3. 同时存在有意义可认证 case：**已完成**（2 个 spatial CERTIFIED strata）
4. 无 workload 重标 / package operator 复用 / 截断补零：**通过当前 loader 约束并已通过**
5. 每个 case 有 manifest/SHA/query artifact/replay receipt：**已完成**（8 case manifests + query artifact/receipt index）

## Independent replay status

### HotSpot witness replay

- 文件：`/tmp/certitherm_g3_real_outputs/g3_independent_hotspot_witness_replay.json`
- 结果：`all_match = true`
- 详细：4/4 witness tuples 与 suite expected outcome 一致。

### 3D-ICE replay

- 3D-ICE 已完成本地构建并接入 adapter：
  - adapter: `CertiTherm/exact/three_d_ice_adapter.py`
  - dual-backend report: `/tmp/certitherm_g3_real_outputs/g3_independent_dual_backend_replay.json`
- 结果：当前严格 fail-closed 复跑为 `PASS`（HotSpot 与 3D-ICE 均 `all_match=true`）

### Fresh clean-clone replay

- Clean clone: `/tmp/certitherm_clean_clone`
- Registered suite replay: `PASS`
- Artifact SHA-256: `69c46a9be4cd6196fc04aa82f81567fdbe33f76931d85b65c3091c6af2948c86`
- Receipt SHA-256: `bd2fc66a83c28dc30bed90514c91b39637317b285efb283b2dc3c78f1edeaf5c`
- Source commit: `f3f7345c6f5f360ccef6df9bcd36001563998e36`

## System-cost evidence

- 汇总文件：`CertiTherm/results/G3_SYSTEM_COST_SUMMARY_20260720.json`
- 覆盖：12 variants（4 strata × point/placed/spatial）
- 总 wall time：`200.322s`，平均每 variant：`16.694s`
- 峰值 RSS：`555,896 KB`
- certificate size：min `12,759 B`, max `21,696 B`, avg `16,296 B`

## G3-C baseline evidence

- 报告：`CertiTherm/results/G3_BASELINE_REPORT.md`
- 汇总：`CertiTherm/results/G3_BASELINE_COMPARISON_20260720.json`
- Claim-grade artifact（外部）：`/tmp/certitherm_g3_real_outputs/g3_baseline_comparison.json`
  - SHA-256：`49ee2f4237931fc790825075d70b86faf3d1c0b60f028b0739f5faab86215fa3`
  - replay：`PASS`（fresh clean clone `/tmp/certitherm_g3c_clone`，commit `46f327f1`）
- 四个 contract 基线在同一 loader / 同一候选集 / 同一 330K 限制 / 同一热算子下评估；
  重算的 deployed point 路径与注册 `point_estimate` variant 在 4/4 strata 完全一致（公平性校验）。
- 结果要点：
  - `uniform_aggregate_point`：4/4 与物理参考一致但含 **2 次 unjustified commitment**（attention strata）；
  - `k_sample_synthetic_stress`（K=64，冻结种子）：**2 次错误架构选择**（regret 11.25 EDYP/workload，+54%）；
  - `interval_box_aggregate`：保守诚实（0 unjustified），coverage 2/4 且区间严格更宽；
  - `fixed_uniform_refinement`：360 sensor channels（180/stratum）才把 2 个 NON_IDENTIFIABLE strata 认证到 placed 结果 —— G4 必须击败的成本列。

## Build / tooling updates in this round

- `CertiTherm/exact/build_g3_real_matrix.py`
  - 增加真实 2x2x2 bundle 构建与 suite 执行
  - 生成 8-case manifests、query artifact/receipt 索引
  - 输出 independent HotSpot witness replay
- `CertiTherm/exact/replay_witness_independent.py`
  - 独立 witness replay runner
  - 支持 `hotspot` 与 `3d-ice adapter` 双后端
- `CertiTherm/exact/three_d_ice_adapter.py`
  - 将 HotSpot-style `floorplan + ptrace` 转换为 3D-ICE `.stk/.flp` 输入
  - 绑定 `-ambient/-r_convec/-s_sink/-t_chip/-material_chip` 与 `example.materials`
  - 对 ptrace/floorplan block 名称执行严格一致性检查（不再零填充）
- `3d-ice/makefile.def`, `3d-ice/sources/thermal_data.c`
  - 修正本机 BLAS/线程兼容后完成 3D-ICE 可执行构建
- `CertiTherm/exact/archive_g3_outputs.py`
  - 将 `/tmp` 外部输出归档到仓库路径 `evidence/g3_2x2x2_real_archive/`
- `CertiTherm/exact/summarize_g3_system_cost.py`
  - 生成 runtime / RSS / certificate size 汇总
- `.gitmodules`, `CertiTherm/evidence/thermodse_tmp_template/`
  - 补齐 ThermoDSE gitlink 元信息与最小模板回退目录

## Gate status

本文件是 G3 门禁状态的权威 ledger（其余文档由此派生，见 README / INSIGHTS / G3_FULL_REPORT 指针）。

- `G3-A semantic breadth`: **PASS**
- `G3-B physical replay`: **PASS**
- `G3-C baseline/system cost`: **PASS**（2026-07-20，四基线对比 + 成本表，replay PASS）
- `G3 full`: **PASS**（A+B+C 全部通过；claim boundary 见 G3_BASELINE_REPORT.md）

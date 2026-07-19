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

## Integrity status

- `suite replay`: **PASS**
- `query_count`: **4** (cnn/attention × standard/enhanced)
- `case_manifest_count`: **8**
- `case_matrix_rows`: **8**
- `unresolved_variant_count`: **0**

## G3 metrics (from suite artifact)

- `point_certified_count`: 4  
- `placed_certified_count`: 4  
- `spatial_certified_count`: 3  
- `spatial_non_identifiable_count`: 1  
- `point_commitment_not_identifiable_count`: 1  
- `point_placed_disagreement_count`: 0  

## 4 query strata summary

| Query | Point | Placed | Spatial |
|---|---|---|---|
| `g3-real-cnn-standard_sink_s06` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) |
| `g3-real-cnn-enhanced_sink_s10` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) |
| `g3-real-attention-standard_sink_s06` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | **NON_IDENTIFIABLE** (`arch_5x4_rect_struct`, `arch_4x4_mesh_fullcut`, `NO_FEASIBLE_DESIGN`) |
| `g3-real-attention-enhanced_sink_s10` | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) | CERTIFIED (`arch_5x4_rect_struct`) |

## Requirement check vs target

1. 8/8 输入真实且 replay 通过：**已完成**（suite + embedded query artifacts replay PASS）
2. 至少一个 point 在 spatial 下不可识别或与 placed 不同：**已完成**（`point_commitment_not_identifiable_count=1`）
3. 同时存在有意义可认证 case：**已完成**（3 个 spatial CERTIFIED strata）
4. 无 workload 重标 / package operator 复用 / 截断补零：**通过当前 loader 约束并已通过**
5. 每个 case 有 manifest/SHA/query artifact/replay receipt：**已完成**（8 case manifests + query artifact/receipt index）

## Independent replay status

### HotSpot witness replay

- 文件：`/tmp/certitherm_g3_real_outputs/g3_independent_hotspot_witness_replay.json`
- 结果：`all_match = false`
- 详细：`g3-real-attention-standard_sink_s06` 的 tuple#1 与 suite expected outcome 不一致。

### 3D-ICE replay

- 代码接口已补：`CertiTherm/exact/replay_witness_independent.py`（支持 HotSpot + 3D-ICE adapter）
- 当前机器 `3d-ice` 构建阻塞（`slu_mt_ddefs.h` 缺失，SuperLU_MT 头文件未就绪），尚未得到 3D-ICE replay 结果。

## Build / tooling updates in this round

- `CertiTherm/exact/build_g3_real_matrix.py`
  - 增加真实 2x2x2 bundle 构建与 suite 执行
  - 生成 8-case manifests、query artifact/receipt 索引
  - 输出 independent HotSpot witness replay
- `CertiTherm/exact/replay_witness_independent.py`
  - 独立 witness replay runner
  - 支持 `hotspot` 与 `3d-ice adapter` 双后端

## Open blockers to close full gate

1. 修复 HotSpot tuple mismatch（attention+standard 的 tuple#1）。  
2. 完成 3D-ICE 可执行构建（SuperLU_MT 依赖）并跑通同一 witness replay。  


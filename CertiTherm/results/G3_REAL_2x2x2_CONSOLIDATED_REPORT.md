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

### Artifact SHA-256

- `g3_suite_artifact.json`: `86e6b304990778b577fbc186d096c8630266428fd5ffba8a63853a9b24639329`
- `g3_suite_receipt.json`: `aa3ace4607ddca44aa5194749f9699eaf7188371e3272ffe2a403e7156654d98`
- `g3_case_query_artifact_receipts.json`: `8fdaa938ff4cfddd1434fd901027e9a3882abe0b4043c48604be3c294f50eb1e`
- `g3_case_matrix_index.json`: `a39f3dcf2979207af48658edec577af2ccf81c4f0c48529a77b679b73d5e0095`
- `g3_independent_hotspot_witness_replay.json`: `7bb54b671c75ce658108a757ab356b6cbf6f890899e68ab4020c33f3290ebe5b`
- `g3_independent_dual_backend_replay.json`: `24bf373d3f9c21f31d62e84b431e48084dbb7687b7d505912eec55ccb2775209`

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
2. 至少一个 point 在 spatial 下不可识别或与 placed 不同：**已完成**（`point_commitment_not_identifiable_count=1`）
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
- 结果：`all_match = true`（3d-ice 与 hotspot 均 4/4 匹配）

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
  - 输出 block temperature steady 文件供 independent replay 判定
- `3d-ice/makefile.def`, `3d-ice/sources/thermal_data.c`
  - 修正本机 BLAS/线程兼容后完成 3D-ICE 可执行构建

## Gate status

`G3 full gate`: **CLOSED**（矩阵、内容绑定、suite replay、HotSpot/3D-ICE 独立 witness replay 全部完成）

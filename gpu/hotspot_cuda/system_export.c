/*
 * CertiTherm HotSpot system exporter.
 *
 * The physical system is constructed by the pinned UVA HotSpot source.  This
 * file only serializes that system for the independently compiled CUDA solver.
 * Rodinia's CUDA HotSpot (pinned in ../../Rodinia) is retained as provenance
 * for the GPU-stencil starting point; no simplified Rodinia constants enter
 * this exporter.
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "temperature_grid.h"
#include "util.h"

#if SUPERLU < 1
#error "CertiTherm GPU system export requires SUPERLU=1"
#endif

typedef struct certitherm_system_header_t_st {
  char magic[8];
  uint32_t version;
  uint32_t scalar_bytes;
  uint64_t nodes;
  uint64_t nnz;
  uint64_t blocks;
  uint64_t map_nnz;
  uint64_t rows;
  uint64_t cols;
  uint64_t layers;
} certitherm_system_header_t;

static void write_all(FILE *stream, const void *data, size_t size, size_t count)
{
  if (count && fwrite(data, size, count, stream) != count)
    fatal("unable to write CertiTherm GPU system\n");
}

static uint64_t power_block_count(const grid_model_t *model)
{
  uint64_t count = 0;
  int layer;
  for (layer = 0; layer < model->n_layers; ++layer)
    if (model->layers[layer].has_power)
      count += (uint64_t) model->layers[layer].flp->n_units;
  return count;
}

static uint64_t output_map_nnz(const grid_model_t *model)
{
  uint64_t count = 0;
  int layer, unit;
  for (layer = 0; layer < model->n_layers; ++layer) {
    if (!model->layers[layer].has_power)
      continue;
    for (unit = 0; unit < model->layers[layer].flp->n_units; ++unit) {
      const glist_t *map = &model->layers[layer].g2bmap[unit];
      count += (uint64_t) (map->i2 - map->i1) * (uint64_t) (map->j2 - map->j1);
    }
  }
  return count;
}

int certitherm_export_gpu_system(grid_model_t *model)
{
  const char *path = getenv("CERTITHERM_GPU_SYSTEM");
  SuperMatrix matrix;
  NCformat *store;
  certitherm_system_header_t header;
  grid_model_vector_t *grid_power;
  double *block_power, *rhs0, *rhs, *basis, *map_values;
  uint64_t *col_ptr, *map_row_ptr;
  uint32_t *row_index, *map_col_index;
  uint64_t nodes, nnz, blocks, map_nnz, entry, block, node;
  int extra_nodes, layer, unit, i, j, base;
  FILE *stream;

  if (!path || !path[0])
    return 0;
  if (model->map_mode != GRID_AVG)
    fatal("CertiTherm GPU exporter supports grid_map_mode=avg only\n");
  if (model->config.leakage_used)
    fatal("CertiTherm GPU exporter rejects temperature-dependent leakage\n");
  if (model->config.package_model_used)
    fatal("CertiTherm GPU exporter rejects iterative natural-convection package models\n");
  for (layer = 0; layer < model->n_layers; ++layer)
    if (model->layers[layer].is_microchannel)
      fatal("CertiTherm GPU exporter rejects non-symmetric microchannel systems\n");

  matrix = build_transient_grid_matrix(model);
  if (matrix.Stype != SLU_NC || matrix.Dtype != SLU_D)
    fatal("unexpected HotSpot sparse matrix representation\n");
  store = (NCformat *) matrix.Store;
  nodes = (uint64_t) matrix.nrow;
  nnz = (uint64_t) store->nnz;
  blocks = power_block_count(model);
  map_nnz = output_map_nnz(model);
  if (!nodes || !nnz || !blocks || !map_nnz)
    fatal("empty HotSpot GPU system\n");
  if (nodes > UINT32_MAX)
    fatal("HotSpot GPU system exceeds 32-bit CUDA indices\n");

  col_ptr = (uint64_t *) calloc((size_t) nodes + 1, sizeof(uint64_t));
  row_index = (uint32_t *) calloc((size_t) nnz, sizeof(uint32_t));
  map_row_ptr = (uint64_t *) calloc((size_t) blocks + 1, sizeof(uint64_t));
  map_col_index = (uint32_t *) calloc((size_t) map_nnz, sizeof(uint32_t));
  map_values = (double *) calloc((size_t) map_nnz, sizeof(double));
  if (blocks > SIZE_MAX / nodes || nodes * blocks > SIZE_MAX / sizeof(double))
    fatal("HotSpot GPU basis allocation overflows size_t\n");
  basis = (double *) calloc((size_t) (nodes * blocks), sizeof(double));
  if (!col_ptr || !row_index || !map_row_ptr || !map_col_index ||
      !map_values || !basis)
    fatal("unable to allocate HotSpot GPU export buffers\n");

  for (node = 0; node <= nodes; ++node)
    col_ptr[node] = (uint64_t) ((int_t *) store->colptr)[node];
  for (entry = 0; entry < nnz; ++entry)
    row_index[entry] = (uint32_t) ((int_t *) store->rowind)[entry];

  extra_nodes = model->config.model_secondary ? EXTRA + EXTRA_SEC : EXTRA;
  block_power = hotspot_vector_grid(model);
  grid_power = new_grid_model_vector(model);
  zero_dvector(block_power, model->total_n_blocks + extra_nodes);
  xlate_vector_b2g(model, block_power, grid_power, V_POWER);
  rhs0 = build_transient_power_vector(model, grid_power);

  block = 0;
  base = 0;
  for (layer = 0; layer < model->n_layers; ++layer) {
    if (model->layers[layer].has_power) {
      for (unit = 0; unit < model->layers[layer].flp->n_units; ++unit) {
        zero_dvector(block_power, model->total_n_blocks + extra_nodes);
        block_power[base + unit] = 1.0;
        xlate_vector_b2g(model, block_power, grid_power, V_POWER);
        rhs = build_transient_power_vector(model, grid_power);
        for (node = 0; node < nodes; ++node)
          basis[node * blocks + block] = rhs[node] - rhs0[node];
        free_dvector(rhs);
        ++block;
      }
    }
    base += model->layers[layer].flp->n_units;
  }
  if (block != blocks)
    fatal("HotSpot GPU power-map construction failed\n");

  entry = 0;
  block = 0;
  for (layer = 0; layer < model->n_layers; ++layer) {
    if (!model->layers[layer].has_power)
      continue;
    for (unit = 0; unit < model->layers[layer].flp->n_units; ++unit) {
      const glist_t *map = &model->layers[layer].g2bmap[unit];
      const uint64_t cells = (uint64_t) (map->i2 - map->i1) *
                             (uint64_t) (map->j2 - map->j1);
      map_row_ptr[block] = entry;
      for (i = map->i1; i < map->i2; ++i)
        for (j = map->j1; j < map->j2; ++j) {
          map_col_index[entry] = (uint32_t) (layer * model->rows * model->cols +
                                             i * model->cols + j);
          map_values[entry] = 1.0 / (double) cells;
          ++entry;
        }
      ++block;
    }
  }
  map_row_ptr[blocks] = entry;
  if (entry != map_nnz || block != blocks)
    fatal("HotSpot GPU temperature-map construction failed\n");

  memset(&header, 0, sizeof(header));
  memcpy(header.magic, "CTHGS01", 7);
  header.version = 1;
  header.scalar_bytes = sizeof(double);
  header.nodes = nodes;
  header.nnz = nnz;
  header.blocks = blocks;
  header.map_nnz = map_nnz;
  header.rows = (uint64_t) model->rows;
  header.cols = (uint64_t) model->cols;
  header.layers = (uint64_t) model->n_layers;

  stream = fopen(path, "wb");
  if (!stream)
    fatal("unable to open CertiTherm GPU system output\n");
  write_all(stream, &header, sizeof(header), 1);
  write_all(stream, col_ptr, sizeof(uint64_t), (size_t) nodes + 1);
  write_all(stream, row_index, sizeof(uint32_t), (size_t) nnz);
  write_all(stream, store->nzval, sizeof(double), (size_t) nnz);
  write_all(stream, rhs0, sizeof(double), (size_t) nodes);
  write_all(stream, basis, sizeof(double), (size_t) (nodes * blocks));
  write_all(stream, map_row_ptr, sizeof(uint64_t), (size_t) blocks + 1);
  write_all(stream, map_col_index, sizeof(uint32_t), (size_t) map_nnz);
  write_all(stream, map_values, sizeof(double), (size_t) map_nnz);
  if (fclose(stream) != 0)
    fatal("unable to close CertiTherm GPU system output\n");

  Destroy_CompCol_Matrix(&matrix);
  free_grid_model_vector(grid_power);
  free_dvector(block_power);
  free_dvector(rhs0);
  free(col_ptr);
  free(row_index);
  free(map_row_ptr);
  free(map_col_index);
  free(map_values);
  free(basis);
  return 1;
}

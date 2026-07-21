/*
 * CertiTherm batched FP64 steady-state CUDA solver.
 *
 * The sparse physical system is exported by the pinned UVA HotSpot model.
 * Rodinia's CUDA HotSpot, pinned as a submodule, motivated the warp-tiled
 * stencil layout; this implementation solves the full package conductance
 * system and deliberately contains no fitted material or power scale.
 */

#include <cuda_runtime.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

constexpr int kRhsTile = 32;
constexpr int kRowWarps = 8;

struct SystemHeader {
  char magic[8];
  std::uint32_t version;
  std::uint32_t scalar_bytes;
  std::uint64_t nodes;
  std::uint64_t nnz;
  std::uint64_t blocks;
  std::uint64_t map_nnz;
  std::uint64_t rows;
  std::uint64_t cols;
  std::uint64_t layers;
};

struct OutputHeader {
  char magic[8];
  std::uint32_t version;
  std::uint32_t scalar_bytes;
  std::uint64_t blocks;
  std::uint64_t rhs;
  std::uint64_t iterations;
  double max_relative_residual;
  double solve_ms;
};

static_assert(sizeof(SystemHeader) == 72, "system header ABI changed");
static_assert(sizeof(OutputHeader) == 56, "output header ABI changed");

void cuda_check(cudaError_t status, const char* operation) {
  if (status != cudaSuccess)
    throw std::runtime_error(std::string(operation) + ": " +
                             cudaGetErrorString(status));
}

template <typename T>
std::vector<T> read_vector(std::ifstream& stream, std::size_t count) {
  std::vector<T> values(count);
  if (count) {
    stream.read(reinterpret_cast<char*>(values.data()),
                static_cast<std::streamsize>(count * sizeof(T)));
    if (!stream)
      throw std::runtime_error("truncated GPU system file");
  }
  return values;
}

template <typename T>
T* device_copy(const std::vector<T>& host) {
  T* device = nullptr;
  cuda_check(cudaMalloc(&device, host.size() * sizeof(T)), "cudaMalloc");
  cuda_check(cudaMemcpy(device, host.data(), host.size() * sizeof(T),
                        cudaMemcpyHostToDevice),
             "cudaMemcpy H2D");
  return device;
}

template <typename T>
T* device_alloc(std::size_t count) {
  T* device = nullptr;
  cuda_check(cudaMalloc(&device, count * sizeof(T)), "cudaMalloc");
  return device;
}

__global__ void csr_spmm(const std::uint64_t* __restrict__ row_ptr,
                         const std::uint32_t* __restrict__ col_index,
                         const double* __restrict__ values,
                         const double* __restrict__ x,
                         double* __restrict__ y,
                         std::uint64_t rows, std::uint64_t rhs) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.y) * kRhsTile + threadIdx.x;
  std::uint64_t row =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.y + threadIdx.y;
  const std::uint64_t stride =
      static_cast<std::uint64_t>(gridDim.x) * blockDim.y;
  if (column >= rhs)
    return;
  for (; row < rows; row += stride) {
    double sum = 0.0;
    for (std::uint64_t entry = row_ptr[row]; entry < row_ptr[row + 1]; ++entry)
      sum += values[entry] * x[static_cast<std::uint64_t>(col_index[entry]) * rhs + column];
    y[row * rhs + column] = sum;
  }
}

__global__ void initialize_pcg(const double* __restrict__ b,
                               const double* __restrict__ diagonal,
                               double* __restrict__ x,
                               double* __restrict__ residual,
                               double* __restrict__ preconditioned,
                               double* __restrict__ direction,
                               std::uint64_t nodes, std::uint64_t rhs) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.y) * kRhsTile + threadIdx.x;
  std::uint64_t row =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.y + threadIdx.y;
  const std::uint64_t stride =
      static_cast<std::uint64_t>(gridDim.x) * blockDim.y;
  if (column >= rhs)
    return;
  for (; row < nodes; row += stride) {
    const std::uint64_t offset = row * rhs + column;
    const double value = b[offset];
    const double scaled = value / diagonal[row];
    x[offset] = 0.0;
    residual[offset] = value;
    preconditioned[offset] = scaled;
    direction[offset] = scaled;
  }
}

__global__ void dot_columns_partial(const double* __restrict__ left,
                                    const double* __restrict__ right,
                                    double* __restrict__ partial_result,
                                    std::uint64_t nodes, std::uint64_t rhs) {
  __shared__ double partial[kRowWarps][kRhsTile];
  const int lane = threadIdx.x;
  const int warp = threadIdx.y;
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.y) * kRhsTile + lane;
  double sum = 0.0;
  if (column < rhs) {
    for (std::uint64_t row =
             static_cast<std::uint64_t>(blockIdx.x) * kRowWarps + warp;
         row < nodes;
         row += static_cast<std::uint64_t>(gridDim.x) * kRowWarps) {
      const std::uint64_t offset = row * rhs + column;
      sum += left[offset] * right[offset];
    }
  }
  partial[warp][lane] = sum;
  __syncthreads();
  if (warp == 0 && column < rhs) {
    sum = 0.0;
#pragma unroll
    for (int row_warp = 0; row_warp < kRowWarps; ++row_warp)
      sum += partial[row_warp][lane];
    partial_result[static_cast<std::uint64_t>(blockIdx.x) * rhs + column] = sum;
  }
}

__global__ void finish_dot_columns(const double* __restrict__ partial_result,
                                   double* __restrict__ result,
                                   std::uint64_t row_blocks,
                                   std::uint64_t rhs) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
  if (column >= rhs)
    return;
  double sum = 0.0;
  for (std::uint64_t block = 0; block < row_blocks; ++block)
    sum += partial_result[block * rhs + column];
  result[column] = sum;
}

__global__ void update_solution_residual(
    double* __restrict__ x, double* __restrict__ residual,
    double* __restrict__ preconditioned,
    const double* __restrict__ direction,
    const double* __restrict__ product,
    const double* __restrict__ diagonal,
    const double* __restrict__ rz, const double* __restrict__ curvature,
    const int* __restrict__ active, int* __restrict__ failed,
    std::uint64_t nodes, std::uint64_t rhs) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.y) * kRhsTile + threadIdx.x;
  std::uint64_t row =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.y + threadIdx.y;
  const std::uint64_t stride =
      static_cast<std::uint64_t>(gridDim.x) * blockDim.y;
  if (column >= rhs || !active[column])
    return;
  const double denominator = curvature[column];
  const double numerator = rz[column];
  if (!(denominator > 0.0) || !isfinite(denominator) || !isfinite(numerator)) {
    atomicExch(failed, 1);
    return;
  }
  const double alpha = numerator / denominator;
  for (; row < nodes; row += stride) {
    const std::uint64_t offset = row * rhs + column;
    x[offset] += alpha * direction[offset];
    residual[offset] -= alpha * product[offset];
    preconditioned[offset] = residual[offset] / diagonal[row];
  }
}

__global__ void mark_converged(const double* __restrict__ residual_norm2,
                               const double* __restrict__ rhs_norm2,
                               int* __restrict__ active,
                               std::uint64_t rhs, double rtol, double atol) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
  if (column >= rhs || !active[column])
    return;
  const double residual = sqrt(fmax(residual_norm2[column], 0.0));
  const double scale = sqrt(fmax(rhs_norm2[column], 0.0));
  // Recurrence residuals can be slightly optimistic after hundreds of PCG
  // updates. Stop with a fixed safety margin; admission still uses a freshly
  // computed b-Gx residual against the caller's unmodified tolerance.
  if (isfinite(residual) && residual <= 0.5 * (atol + rtol * scale))
    active[column] = 0;
}

__global__ void update_direction(
    double* __restrict__ direction,
    const double* __restrict__ preconditioned,
    const double* __restrict__ rz_old,
    const double* __restrict__ rz_new,
    const int* __restrict__ active,
    int* __restrict__ failed,
    std::uint64_t nodes, std::uint64_t rhs) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.y) * kRhsTile + threadIdx.x;
  std::uint64_t row =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.y + threadIdx.y;
  const std::uint64_t stride =
      static_cast<std::uint64_t>(gridDim.x) * blockDim.y;
  if (column >= rhs || !active[column])
    return;
  const double denominator = rz_old[column];
  const double numerator = rz_new[column];
  if (!(denominator > 0.0) || !isfinite(denominator) || !isfinite(numerator)) {
    atomicExch(failed, 1);
    return;
  }
  const double beta = numerator / denominator;
  for (; row < nodes; row += stride) {
    const std::uint64_t offset = row * rhs + column;
    direction[offset] = preconditioned[offset] + beta * direction[offset];
  }
}

__global__ void advance_rz(double* __restrict__ old_value,
                           const double* __restrict__ new_value,
                           const int* __restrict__ active,
                           std::uint64_t rhs) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
  if (column < rhs && active[column])
    old_value[column] = new_value[column];
}

__global__ void true_residual(const double* __restrict__ b,
                              const double* __restrict__ product,
                              double* __restrict__ residual,
                              std::uint64_t nodes, std::uint64_t rhs) {
  const std::uint64_t column =
      static_cast<std::uint64_t>(blockIdx.y) * kRhsTile + threadIdx.x;
  std::uint64_t row =
      static_cast<std::uint64_t>(blockIdx.x) * blockDim.y + threadIdx.y;
  const std::uint64_t stride =
      static_cast<std::uint64_t>(gridDim.x) * blockDim.y;
  if (column >= rhs)
    return;
  for (; row < nodes; row += stride) {
    const std::uint64_t offset = row * rhs + column;
    residual[offset] = b[offset] - product[offset];
  }
}

void launch_spmm(const std::uint64_t* row_ptr,
                 const std::uint32_t* col_index,
                 const double* values, const double* x, double* y,
                 std::uint64_t rows, std::uint64_t rhs, int row_blocks) {
  const dim3 block(kRhsTile, kRowWarps);
  const dim3 grid(std::max(1, row_blocks),
                  static_cast<unsigned>((rhs + kRhsTile - 1) / kRhsTile));
  csr_spmm<<<grid, block>>>(row_ptr, col_index, values, x, y, rows, rhs);
}

void launch_dot(const double* left, const double* right, double* result,
                double* partial_result, std::uint64_t nodes,
                std::uint64_t rhs, int row_blocks) {
  const dim3 block(kRhsTile, kRowWarps);
  const dim3 grid(std::max(1, row_blocks),
                  static_cast<unsigned>((rhs + kRhsTile - 1) / kRhsTile));
  dot_columns_partial<<<grid, block>>>(left, right, partial_result, nodes, rhs);
  finish_dot_columns<<<static_cast<unsigned>((rhs + 255) / 256), 256>>>(
      partial_result, result, static_cast<std::uint64_t>(row_blocks), rhs);
}

std::vector<std::uint64_t> csc_to_csr(
    std::uint64_t nodes, const std::vector<std::uint64_t>& col_ptr,
    const std::vector<std::uint32_t>& row_index,
    const std::vector<double>& csc_values,
    std::vector<std::uint32_t>* col_index,
    std::vector<double>* csr_values) {
  std::vector<std::uint64_t> row_ptr(nodes + 1, 0);
  for (std::uint32_t row : row_index) {
    if (row >= nodes)
      throw std::runtime_error("sparse row index out of range");
    ++row_ptr[static_cast<std::size_t>(row) + 1];
  }
  for (std::size_t row = 0; row < nodes; ++row)
    row_ptr[row + 1] += row_ptr[row];
  std::vector<std::uint64_t> next = row_ptr;
  col_index->resize(row_index.size());
  csr_values->resize(csc_values.size());
  for (std::uint64_t column = 0; column < nodes; ++column) {
    for (std::uint64_t entry = col_ptr[column]; entry < col_ptr[column + 1]; ++entry) {
      const std::uint32_t row = row_index[entry];
      const std::uint64_t target = next[row]++;
      (*col_index)[target] = static_cast<std::uint32_t>(column);
      (*csr_values)[target] = csc_values[entry];
    }
  }
  return row_ptr;
}

std::vector<double> validate_spd_structure(
    std::uint64_t nodes, const std::vector<std::uint64_t>& row_ptr,
    const std::vector<std::uint32_t>& col_index,
    const std::vector<double>& values) {
  std::vector<double> diagonal(nodes, 0.0);
  std::unordered_map<std::uint64_t, double> entries;
  entries.reserve(values.size() * 2);
  for (std::uint64_t row = 0; row < nodes; ++row) {
    for (std::uint64_t entry = row_ptr[row]; entry < row_ptr[row + 1]; ++entry) {
      const std::uint64_t column = col_index[entry];
      const double value = values[entry];
      if (!std::isfinite(value))
        throw std::runtime_error("non-finite sparse coefficient");
      entries[(row << 32) | column] = value;
      if (row == column)
        diagonal[row] = value;
    }
  }
  for (std::uint64_t row = 0; row < nodes; ++row) {
    if (!(diagonal[row] > 0.0) || !std::isfinite(diagonal[row]))
      throw std::runtime_error("non-positive HotSpot diagonal");
    for (std::uint64_t entry = row_ptr[row]; entry < row_ptr[row + 1]; ++entry) {
      const std::uint64_t column = col_index[entry];
      const auto reverse = entries.find((column << 32) | row);
      if (reverse == entries.end())
        throw std::runtime_error("non-symmetric HotSpot sparsity rejected");
      const double scale = std::max({1.0, std::abs(values[entry]),
                                     std::abs(reverse->second)});
      if (std::abs(values[entry] - reverse->second) > 1e-11 * scale)
        throw std::runtime_error("non-symmetric HotSpot coefficients rejected");
    }
  }
  return diagonal;
}

int active_count(const std::vector<int>& active) {
  return static_cast<int>(std::count(active.begin(), active.end(), 1));
}

}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc < 4 || argc > 8) {
      std::cerr << "usage: " << argv[0]
                << " SYSTEM.bin OUTPUT.bin STATS.tsv [device] [rtol] [atol] [max_iters]\n";
      return 2;
    }
    const std::string system_path = argv[1];
    const std::string output_path = argv[2];
    const std::string stats_path = argv[3];
    const int device = argc > 4 ? std::stoi(argv[4]) : 0;
    const double rtol = argc > 5 ? std::stod(argv[5]) : 1e-11;
    const double atol = argc > 6 ? std::stod(argv[6]) : 1e-12;
    const int max_iterations = argc > 7 ? std::stoi(argv[7]) : 10000;
    if (!(rtol > 0.0) || !(atol >= 0.0) || max_iterations <= 0)
      throw std::runtime_error("invalid solver tolerance or iteration limit");

    const auto wall_start = std::chrono::steady_clock::now();
    std::ifstream stream(system_path, std::ios::binary);
    if (!stream)
      throw std::runtime_error("cannot open GPU system file");
    SystemHeader header{};
    stream.read(reinterpret_cast<char*>(&header), sizeof(header));
    if (!stream || std::memcmp(header.magic, "CTHGS01", 7) ||
        header.version != 1 || header.scalar_bytes != sizeof(double))
      throw std::runtime_error("unsupported GPU system format");
    if (!header.nodes || !header.nnz || !header.blocks ||
        header.nodes > std::numeric_limits<std::uint32_t>::max())
      throw std::runtime_error("invalid GPU system dimensions");

    auto csc_col_ptr = read_vector<std::uint64_t>(stream, header.nodes + 1);
    auto csc_row_index = read_vector<std::uint32_t>(stream, header.nnz);
    auto csc_values = read_vector<double>(stream, header.nnz);
    auto rhs0 = read_vector<double>(stream, header.nodes);
    auto basis = read_vector<double>(stream, header.nodes * header.blocks);
    auto map_row_ptr = read_vector<std::uint64_t>(stream, header.blocks + 1);
    auto map_col_index = read_vector<std::uint32_t>(stream, header.map_nnz);
    auto map_values = read_vector<double>(stream, header.map_nnz);
    stream.peek();
    if (!stream.eof())
      throw std::runtime_error("trailing bytes in GPU system file");
    if (csc_col_ptr.back() != header.nnz || map_row_ptr.back() != header.map_nnz)
      throw std::runtime_error("invalid sparse pointer terminator");

    std::vector<std::uint32_t> column_index;
    std::vector<double> values;
    auto row_ptr = csc_to_csr(header.nodes, csc_col_ptr, csc_row_index,
                              csc_values, &column_index, &values);
    auto diagonal = validate_spd_structure(header.nodes, row_ptr, column_index, values);

    const std::uint64_t rhs = header.blocks + 1;
    if (header.nodes > std::numeric_limits<std::size_t>::max() / rhs)
      throw std::runtime_error("GPU batch dimension overflow");
    std::vector<double> host_rhs(header.nodes * rhs);
    for (std::uint64_t node = 0; node < header.nodes; ++node) {
      host_rhs[node * rhs] = rhs0[node];
      for (std::uint64_t block = 0; block < header.blocks; ++block)
        host_rhs[node * rhs + block + 1] =
            rhs0[node] + basis[node * header.blocks + block];
    }

    cuda_check(cudaSetDevice(device), "cudaSetDevice");
    cudaDeviceProp properties{};
    cuda_check(cudaGetDeviceProperties(&properties, device), "cudaGetDeviceProperties");
    const int row_blocks = std::max(
        1, std::min<int>(static_cast<int>((header.nodes + kRowWarps - 1) / kRowWarps),
                         properties.multiProcessorCount * 4));
    const dim3 vector_block(kRhsTile, kRowWarps);
    const dim3 vector_grid(row_blocks,
                           static_cast<unsigned>((rhs + kRhsTile - 1) / kRhsTile));

    auto d_row_ptr = device_copy(row_ptr);
    auto d_col_index = device_copy(column_index);
    auto d_values = device_copy(values);
    auto d_diagonal = device_copy(diagonal);
    auto d_rhs = device_copy(host_rhs);
    auto d_map_row_ptr = device_copy(map_row_ptr);
    auto d_map_col_index = device_copy(map_col_index);
    auto d_map_values = device_copy(map_values);
    const std::size_t elements = static_cast<std::size_t>(header.nodes * rhs);
    auto d_x = device_alloc<double>(elements);
    auto d_residual = device_alloc<double>(elements);
    auto d_preconditioned = device_alloc<double>(elements);
    auto d_direction = device_alloc<double>(elements);
    auto d_product = device_alloc<double>(elements);
    auto d_rz_old = device_alloc<double>(rhs);
    auto d_rz_new = device_alloc<double>(rhs);
    auto d_curvature = device_alloc<double>(rhs);
    auto d_residual_norm2 = device_alloc<double>(rhs);
    auto d_rhs_norm2 = device_alloc<double>(rhs);
    auto d_dot_partial = device_alloc<double>(
        static_cast<std::size_t>(row_blocks) * rhs);
    std::vector<int> host_active(rhs, 1);
    auto d_active = device_copy(host_active);
    auto d_failed = device_alloc<int>(1);
    cuda_check(cudaMemset(d_failed, 0, sizeof(int)), "zero failure flag");

    cudaEvent_t start_event, stop_event;
    cuda_check(cudaEventCreate(&start_event), "create start event");
    cuda_check(cudaEventCreate(&stop_event), "create stop event");
    cuda_check(cudaEventRecord(start_event), "record start event");

    initialize_pcg<<<vector_grid, vector_block>>>(
        d_rhs, d_diagonal, d_x, d_residual, d_preconditioned, d_direction,
        header.nodes, rhs);
    launch_dot(d_residual, d_preconditioned, d_rz_old, d_dot_partial,
               header.nodes, rhs, row_blocks);
    launch_dot(d_rhs, d_rhs, d_rhs_norm2, d_dot_partial,
               header.nodes, rhs, row_blocks);

    int iterations = 0;
    for (; iterations < max_iterations; ++iterations) {
      launch_spmm(d_row_ptr, d_col_index, d_values, d_direction, d_product,
                   header.nodes, rhs, row_blocks);
      launch_dot(d_direction, d_product, d_curvature, d_dot_partial,
                 header.nodes, rhs, row_blocks);
      update_solution_residual<<<vector_grid, vector_block>>>(
          d_x, d_residual, d_preconditioned, d_direction, d_product, d_diagonal,
          d_rz_old, d_curvature, d_active, d_failed, header.nodes, rhs);
      launch_dot(d_residual, d_preconditioned, d_rz_new, d_dot_partial,
                 header.nodes, rhs, row_blocks);
      launch_dot(d_residual, d_residual, d_residual_norm2, d_dot_partial,
                 header.nodes, rhs, row_blocks);
      mark_converged<<<static_cast<unsigned>((rhs + 255) / 256), 256>>>(
          d_residual_norm2, d_rhs_norm2, d_active, rhs, rtol, atol);
      update_direction<<<vector_grid, vector_block>>>(
          d_direction, d_preconditioned, d_rz_old, d_rz_new, d_active,
          d_failed, header.nodes, rhs);
      advance_rz<<<static_cast<unsigned>((rhs + 255) / 256), 256>>>(
          d_rz_old, d_rz_new, d_active, rhs);

      if ((iterations + 1) % 10 == 0 || iterations == 0) {
        cuda_check(cudaGetLastError(), "PCG kernel launch");
        cuda_check(cudaMemcpy(host_active.data(), d_active, rhs * sizeof(int),
                              cudaMemcpyDeviceToHost),
                   "read convergence flags");
        int failed = 0;
        cuda_check(cudaMemcpy(&failed, d_failed, sizeof(int), cudaMemcpyDeviceToHost),
                   "read failure flag");
        if (failed)
          throw std::runtime_error("PCG rejected non-positive curvature or non-finite scalar");
        if (!active_count(host_active)) {
          ++iterations;
          break;
        }
      }
    }
    if (active_count(host_active))
      throw std::runtime_error("PCG iteration budget exhausted");

    launch_spmm(d_row_ptr, d_col_index, d_values, d_x, d_product,
                 header.nodes, rhs, row_blocks);
    true_residual<<<vector_grid, vector_block>>>(d_rhs, d_product, d_residual,
                                                  header.nodes, rhs);
    launch_dot(d_residual, d_residual, d_residual_norm2, d_dot_partial,
               header.nodes, rhs, row_blocks);
    std::vector<double> residual_norm2(rhs), rhs_norm2(rhs);
    cuda_check(cudaMemcpy(residual_norm2.data(), d_residual_norm2,
                          rhs * sizeof(double), cudaMemcpyDeviceToHost),
               "read true residual");
    cuda_check(cudaMemcpy(rhs_norm2.data(), d_rhs_norm2,
                          rhs * sizeof(double), cudaMemcpyDeviceToHost),
               "read rhs norm");
    double max_relative_residual = 0.0;
    for (std::size_t column = 0; column < rhs; ++column) {
      const double residual = std::sqrt(std::max(0.0, residual_norm2[column]));
      const double scale = std::sqrt(std::max(0.0, rhs_norm2[column]));
      max_relative_residual =
          std::max(max_relative_residual, residual / std::max(scale, 1e-300));
      if (!std::isfinite(residual) || residual > atol + rtol * scale) {
        std::ostringstream message;
        message << std::setprecision(17)
                << "true residual failed the declared tolerance at rhs "
                << column << ": residual=" << residual
                << ", limit=" << (atol + rtol * scale);
        throw std::runtime_error(message.str());
      }
    }

    auto d_block_temperature = device_alloc<double>(header.blocks * rhs);
    const int map_blocks = std::max(
        1, std::min<int>(static_cast<int>((header.blocks + kRowWarps - 1) / kRowWarps),
                         properties.multiProcessorCount * 2));
    launch_spmm(d_map_row_ptr, d_map_col_index, d_map_values, d_x,
                 d_block_temperature, header.blocks, rhs, map_blocks);
    std::vector<double> block_temperature(header.blocks * rhs);
    cuda_check(cudaMemcpy(block_temperature.data(), d_block_temperature,
                          block_temperature.size() * sizeof(double),
                          cudaMemcpyDeviceToHost),
               "read block temperatures");

    cuda_check(cudaEventRecord(stop_event), "record stop event");
    cuda_check(cudaEventSynchronize(stop_event), "synchronize stop event");
    float solve_ms_float = 0.0f;
    cuda_check(cudaEventElapsedTime(&solve_ms_float, start_event, stop_event),
               "elapsed CUDA time");
    const double solve_ms = solve_ms_float;

    OutputHeader output{};
    std::memcpy(output.magic, "CTHGO01", 7);
    output.version = 1;
    output.scalar_bytes = sizeof(double);
    output.blocks = header.blocks;
    output.rhs = rhs;
    output.iterations = static_cast<std::uint64_t>(iterations);
    output.max_relative_residual = max_relative_residual;
    output.solve_ms = solve_ms;
    std::ofstream output_stream(output_path, std::ios::binary);
    if (!output_stream)
      throw std::runtime_error("cannot open GPU temperature output");
    output_stream.write(reinterpret_cast<const char*>(&output), sizeof(output));
    output_stream.write(reinterpret_cast<const char*>(block_temperature.data()),
                        static_cast<std::streamsize>(block_temperature.size() * sizeof(double)));
    if (!output_stream)
      throw std::runtime_error("cannot write GPU temperature output");

    const auto wall_stop = std::chrono::steady_clock::now();
    const double wall_ms =
        std::chrono::duration<double, std::milli>(wall_stop - wall_start).count();
    std::ofstream stats(stats_path);
    if (!stats)
      throw std::runtime_error("cannot open GPU stats output");
    stats << "backend\tdevice\tcompute_capability\tnodes\tnnz\tblocks\trhs\titerations"
             "\trtol\tatol\tmax_relative_residual\tsolve_ms\twall_ms\n";
    stats << "custom-fp64-batched-pcg\t" << properties.name << "\t"
          << properties.major << "." << properties.minor << "\t"
          << header.nodes << "\t" << header.nnz << "\t" << header.blocks << "\t"
          << rhs << "\t" << iterations << "\t" << std::setprecision(17) << rtol
          << "\t" << atol << "\t" << max_relative_residual << "\t"
          << solve_ms << "\t" << wall_ms << "\n";

    cudaFree(d_row_ptr);
    cudaFree(d_col_index);
    cudaFree(d_values);
    cudaFree(d_diagonal);
    cudaFree(d_rhs);
    cudaFree(d_map_row_ptr);
    cudaFree(d_map_col_index);
    cudaFree(d_map_values);
    cudaFree(d_x);
    cudaFree(d_residual);
    cudaFree(d_preconditioned);
    cudaFree(d_direction);
    cudaFree(d_product);
    cudaFree(d_rz_old);
    cudaFree(d_rz_new);
    cudaFree(d_curvature);
    cudaFree(d_residual_norm2);
    cudaFree(d_rhs_norm2);
    cudaFree(d_dot_partial);
    cudaFree(d_active);
    cudaFree(d_failed);
    cudaFree(d_block_temperature);
    cudaEventDestroy(start_event);
    cudaEventDestroy(stop_event);
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "CertiTherm GPU solver: " << error.what() << "\n";
    return 1;
  }
}

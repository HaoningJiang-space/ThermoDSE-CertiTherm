/* Batched FP64 PDHG proposal engine for CertiTherm collision feasibility. */

#include <cublas_v2.h>
#include <cuda_runtime.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr int kThreads = 256;

struct InputHeader {
  char magic[8];
  std::uint32_t version;
  std::uint32_t scalar_bytes;
  std::uint64_t variables;
  std::uint64_t inequalities;
  std::uint64_t equalities;
  std::uint64_t batch;
  std::uint64_t max_iterations;
  std::uint64_t check_interval;
  double feasibility_tolerance;
  double step_scale;
};

struct OutputHeader {
  char magic[8];
  std::uint32_t version;
  std::uint32_t scalar_bytes;
  std::uint64_t batch;
  std::uint64_t variables;
  std::uint64_t inequalities;
  std::uint64_t equalities;
  std::uint64_t iterations;
  double solve_ms;
};

static_assert(sizeof(InputHeader) == 80, "input ABI changed");
static_assert(sizeof(OutputHeader) == 64, "output ABI changed");

void cuda_ok(cudaError_t status, const char* operation) {
  if (status != cudaSuccess)
    throw std::runtime_error(std::string(operation) + ": " +
                             cudaGetErrorString(status));
}

void cublas_ok(cublasStatus_t status, const char* operation) {
  if (status != CUBLAS_STATUS_SUCCESS)
    throw std::runtime_error(std::string(operation) + " failed");
}

template <typename T>
std::vector<T> read_vector(std::ifstream& stream, std::size_t count) {
  std::vector<T> values(count);
  stream.read(reinterpret_cast<char*>(values.data()),
              static_cast<std::streamsize>(count * sizeof(T)));
  if (!stream) throw std::runtime_error("truncated collision input");
  return values;
}

template <typename T>
T* device_copy(const std::vector<T>& values) {
  T* pointer = nullptr;
  cuda_ok(cudaMalloc(&pointer, std::max<std::size_t>(1, values.size()) * sizeof(T)),
          "cudaMalloc");
  if (!values.empty())
    cuda_ok(cudaMemcpy(pointer, values.data(), values.size() * sizeof(T),
                       cudaMemcpyHostToDevice), "cudaMemcpy H2D");
  return pointer;
}

template <typename T>
T* device_alloc(std::size_t count) {
  T* pointer = nullptr;
  cuda_ok(cudaMalloc(&pointer, std::max<std::size_t>(1, count) * sizeof(T)),
          "cudaMalloc");
  return pointer;
}

__global__ void initialize_primal(double* q, double* q_bar,
                                  std::uint64_t count) {
  for (std::uint64_t index = blockIdx.x * blockDim.x + threadIdx.x;
       index < count; index += static_cast<std::uint64_t>(gridDim.x) * blockDim.x)
    q[index] = q_bar[index] = 0.5;
}

__global__ void update_inequality_dual(const double* product,
                                       const double* rhs, double* dual,
                                       const int* active, double sigma,
                                       std::uint64_t rows,
                                       std::uint64_t batch) {
  const std::uint64_t count = rows * batch;
  for (std::uint64_t index = blockIdx.x * blockDim.x + threadIdx.x;
       index < count; index += static_cast<std::uint64_t>(gridDim.x) * blockDim.x) {
    const std::uint64_t cell = index % batch;
    if (active[cell])
      dual[index] = fmax(0.0, dual[index] + sigma *
                        (product[index] - rhs[index / batch]));
  }
}

__global__ void update_equality_dual(const double* product,
                                     const double* rhs, double* dual,
                                     const int* active, double sigma,
                                     std::uint64_t rows,
                                     std::uint64_t batch) {
  const std::uint64_t count = rows * batch;
  for (std::uint64_t index = blockIdx.x * blockDim.x + threadIdx.x;
       index < count; index += static_cast<std::uint64_t>(gridDim.x) * blockDim.x) {
    const std::uint64_t cell = index % batch;
    if (active[cell]) dual[index] += sigma * (product[index] - rhs[index / batch]);
  }
}

__global__ void update_spec_dual(const double* rows, const double* rhs,
                                 const double* q_bar, double* dual,
                                 const int* active, double sigma,
                                 std::uint64_t variables,
                                 std::uint64_t batch) {
  const std::uint64_t cell = blockIdx.x;
  if (cell >= batch || !active[cell]) return;
  double sum = 0.0;
  for (std::uint64_t variable = threadIdx.x; variable < variables;
       variable += blockDim.x)
    sum += rows[cell * variables + variable] * q_bar[variable * batch + cell];
  __shared__ double partial[kThreads];
  partial[threadIdx.x] = sum;
  __syncthreads();
  for (int offset = blockDim.x / 2; offset; offset /= 2) {
    if (threadIdx.x < offset) partial[threadIdx.x] += partial[threadIdx.x + offset];
    __syncthreads();
  }
  if (threadIdx.x == 0)
    dual[cell] = fmax(0.0, dual[cell] + sigma * (partial[0] - rhs[cell]));
}

__global__ void update_primal(double* q, double* q_bar,
                              const double* common_gradient,
                              const double* equality_gradient,
                              const double* spec_rows,
                              const double* spec_dual,
                              const int* active, double tau,
                              std::uint64_t variables,
                              std::uint64_t batch) {
  const std::uint64_t count = variables * batch;
  for (std::uint64_t index = blockIdx.x * blockDim.x + threadIdx.x;
       index < count; index += static_cast<std::uint64_t>(gridDim.x) * blockDim.x) {
    const std::uint64_t variable = index / batch;
    const std::uint64_t cell = index % batch;
    if (!active[cell]) continue;
    const double old = q[index];
    const double gradient = common_gradient[index] + equality_gradient[index] +
        spec_dual[cell] * spec_rows[cell * variables + variable];
    const double next = fmin(1.0, fmax(0.0, old - tau * gradient));
    q[index] = next;
    q_bar[index] = 2.0 * next - old;
  }
}

__device__ void atomic_max_positive(double* address, double value) {
  auto raw = reinterpret_cast<unsigned long long*>(address);
  unsigned long long old = *raw, assumed;
  do {
    assumed = old;
    if (__longlong_as_double(assumed) >= value) break;
    old = atomicCAS(raw, assumed, __double_as_longlong(value));
  } while (old != assumed);
}

__global__ void inequality_violation(const double* product,
                                     const double* rhs, double* violation,
                                     std::uint64_t rows,
                                     std::uint64_t batch) {
  const std::uint64_t count = rows * batch;
  for (std::uint64_t index = blockIdx.x * blockDim.x + threadIdx.x;
       index < count; index += static_cast<std::uint64_t>(gridDim.x) * blockDim.x)
    atomic_max_positive(&violation[index % batch],
                        fmax(0.0, product[index] - rhs[index / batch]));
}

__global__ void equality_violation(const double* product,
                                   const double* rhs, double* violation,
                                   std::uint64_t rows,
                                   std::uint64_t batch) {
  const std::uint64_t count = rows * batch;
  for (std::uint64_t index = blockIdx.x * blockDim.x + threadIdx.x;
       index < count; index += static_cast<std::uint64_t>(gridDim.x) * blockDim.x)
    atomic_max_positive(&violation[index % batch],
                        fabs(product[index] - rhs[index / batch]));
}

__global__ void spec_violation(const double* rows, const double* rhs,
                               const double* q, double* violation,
                               std::uint64_t variables,
                               std::uint64_t batch) {
  const std::uint64_t cell = blockIdx.x;
  if (cell >= batch) return;
  double sum = 0.0;
  for (std::uint64_t variable = threadIdx.x; variable < variables;
       variable += blockDim.x)
    sum += rows[cell * variables + variable] * q[variable * batch + cell];
  __shared__ double partial[kThreads];
  partial[threadIdx.x] = sum;
  __syncthreads();
  for (int offset = blockDim.x / 2; offset; offset /= 2) {
    if (threadIdx.x < offset) partial[threadIdx.x] += partial[threadIdx.x + offset];
    __syncthreads();
  }
  if (threadIdx.x == 0)
    atomic_max_positive(&violation[cell], fmax(0.0, partial[0] - rhs[cell]));
}

__global__ void mark_feasible(const double* violation, int* active,
                              double tolerance, std::uint64_t batch) {
  for (std::uint64_t cell = blockIdx.x * blockDim.x + threadIdx.x;
       cell < batch; cell += static_cast<std::uint64_t>(gridDim.x) * blockDim.x)
    if (violation[cell] <= tolerance) active[cell] = 0;
}

int grid_for(std::uint64_t count) {
  return static_cast<int>(std::min<std::uint64_t>(65535, (count + kThreads - 1) / kThreads));
}

void normalize_rows(std::vector<double>* matrix, std::vector<double>* rhs,
                    std::uint64_t rows, std::uint64_t columns,
                    std::vector<double>* scales) {
  scales->resize(rows);
  for (std::uint64_t row = 0; row < rows; ++row) {
    double squared = 0.0;
    for (std::uint64_t column = 0; column < columns; ++column) {
      const double value = (*matrix)[row * columns + column];
      squared += value * value;
    }
    const double scale = squared > 0.0 ? std::sqrt(squared) : 1.0;
    (*scales)[row] = scale;
    for (std::uint64_t column = 0; column < columns; ++column)
      (*matrix)[row * columns + column] /= scale;
    (*rhs)[row] /= scale;
  }
}

void transform_box(std::vector<double>* matrix, std::vector<double>* rhs,
                   const std::vector<double>& lower,
                   const std::vector<double>& span,
                   std::uint64_t rows, std::uint64_t columns) {
  for (std::uint64_t row = 0; row < rows; ++row) {
    double shift = 0.0;
    for (std::uint64_t column = 0; column < columns; ++column) {
      double& value = (*matrix)[row * columns + column];
      shift += value * lower[column];
      value *= span[column];
    }
    (*rhs)[row] -= shift;
  }
}

void gemm_forward(cublasHandle_t handle, const double* matrix,
                  const double* q, double* product, int rows, int variables,
                  int batch) {
  const double one = 1.0, zero = 0.0;
  cublas_ok(cublasDgemm(handle, CUBLAS_OP_N, CUBLAS_OP_N, batch, rows,
                        variables, &one, q, batch, matrix, variables, &zero,
                        product, batch), "forward DGEMM");
}

void gemm_transpose(cublasHandle_t handle, const double* matrix,
                    const double* dual, double* gradient, int rows,
                    int variables, int batch, double beta) {
  const double one = 1.0;
  cublas_ok(cublasDgemm(handle, CUBLAS_OP_N, CUBLAS_OP_T, batch, variables,
                        rows, &one, dual, batch, matrix, variables, &beta,
                        gradient, batch), "transpose DGEMM");
}

template <typename T>
void write_vector(std::ofstream& stream, const std::vector<T>& values) {
  stream.write(reinterpret_cast<const char*>(values.data()),
               static_cast<std::streamsize>(values.size() * sizeof(T)));
}

}  // namespace

int main(int argc, char** argv) try {
  if (argc != 4) throw std::runtime_error("usage: solver input output device");
  std::ifstream input(argv[1], std::ios::binary);
  InputHeader header{};
  input.read(reinterpret_cast<char*>(&header), sizeof(header));
  if (!input || std::string(header.magic, 7) != "CTCLP01" ||
      header.version != 1 || header.scalar_bytes != 8)
    throw std::runtime_error("unsupported collision input format");
  const auto n = header.variables, m = header.inequalities;
  const auto e = header.equalities, batch = header.batch;
  if (!n || !batch || header.check_interval == 0 ||
      header.feasibility_tolerance <= 0.0 || header.step_scale <= 0.0)
    throw std::runtime_error("invalid collision dimensions or controls");

  auto a = read_vector<double>(input, m * n);
  auto b = read_vector<double>(input, m);
  auto eq = read_vector<double>(input, e * n);
  auto eq_rhs = read_vector<double>(input, e);
  auto lower = read_vector<double>(input, n);
  auto upper = read_vector<double>(input, n);
  auto spec = read_vector<double>(input, batch * n);
  auto spec_rhs = read_vector<double>(input, batch);
  std::vector<double> span(n);
  for (std::uint64_t i = 0; i < n; ++i) {
    if (!std::isfinite(lower[i]) || !std::isfinite(upper[i]) || lower[i] > upper[i])
      throw std::runtime_error("invalid finite box");
    span[i] = upper[i] - lower[i];
  }
  transform_box(&a, &b, lower, span, m, n);
  transform_box(&eq, &eq_rhs, lower, span, e, n);
  transform_box(&spec, &spec_rhs, lower, span, batch, n);
  std::vector<double> a_scale, eq_scale, spec_scale;
  normalize_rows(&a, &b, m, n, &a_scale);
  normalize_rows(&eq, &eq_rhs, e, n, &eq_scale);
  normalize_rows(&spec, &spec_rhs, batch, n, &spec_scale);
  double frobenius2 = 1.0;
  for (double value : a) frobenius2 += value * value;
  for (double value : eq) frobenius2 += value * value;
  const double step = header.step_scale / std::sqrt(frobenius2 + 1.0);

  cuda_ok(cudaSetDevice(std::stoi(argv[3])), "cudaSetDevice");
  cublasHandle_t handle;
  cublas_ok(cublasCreate(&handle), "cublasCreate");
  double *d_a = device_copy(a), *d_b = device_copy(b);
  double *d_eq = device_copy(eq), *d_eq_rhs = device_copy(eq_rhs);
  double *d_spec = device_copy(spec), *d_spec_rhs = device_copy(spec_rhs);
  double *q = device_alloc<double>(n * batch);
  double *q_bar = device_alloc<double>(n * batch);
  double *dual = device_alloc<double>(m * batch);
  double *eq_dual = device_alloc<double>(e * batch);
  double *spec_dual = device_alloc<double>(batch);
  double *a_product = device_alloc<double>(m * batch);
  double *eq_product = device_alloc<double>(e * batch);
  double *gradient = device_alloc<double>(n * batch);
  double *eq_gradient = device_alloc<double>(n * batch);
  double *violation = device_alloc<double>(batch);
  int* active = device_alloc<int>(batch);
  cuda_ok(cudaMemset(dual, 0, m * batch * sizeof(double)), "zero dual");
  cuda_ok(cudaMemset(eq_dual, 0, e * batch * sizeof(double)), "zero eq dual");
  cuda_ok(cudaMemset(spec_dual, 0, batch * sizeof(double)), "zero spec dual");
  cuda_ok(cudaMemset(active, 1, batch * sizeof(int)), "activate cells");
  initialize_primal<<<grid_for(n * batch), kThreads>>>(q, q_bar, n * batch);

  auto started = std::chrono::steady_clock::now();
  std::uint64_t iteration = 0;
  for (; iteration < header.max_iterations; ++iteration) {
    if (m) {
      gemm_forward(handle, d_a, q_bar, a_product, m, n, batch);
      update_inequality_dual<<<grid_for(m * batch), kThreads>>>(
          a_product, d_b, dual, active, step, m, batch);
      gemm_transpose(handle, d_a, dual, gradient, m, n, batch, 0.0);
    } else {
      cuda_ok(cudaMemset(gradient, 0, n * batch * sizeof(double)), "zero gradient");
    }
    if (e) {
      gemm_forward(handle, d_eq, q_bar, eq_product, e, n, batch);
      update_equality_dual<<<grid_for(e * batch), kThreads>>>(
          eq_product, d_eq_rhs, eq_dual, active, step, e, batch);
      gemm_transpose(handle, d_eq, eq_dual, eq_gradient, e, n, batch, 0.0);
    } else {
      cuda_ok(cudaMemset(eq_gradient, 0, n * batch * sizeof(double)), "zero eq gradient");
    }
    update_spec_dual<<<static_cast<unsigned>(batch), kThreads>>>(
        d_spec, d_spec_rhs, q_bar, spec_dual, active, step, n, batch);
    update_primal<<<grid_for(n * batch), kThreads>>>(
        q, q_bar, gradient, eq_gradient, d_spec, spec_dual, active, step,
        n, batch);

    if ((iteration + 1) % header.check_interval == 0 ||
        iteration + 1 == header.max_iterations) {
      cuda_ok(cudaMemset(violation, 0, batch * sizeof(double)), "zero violation");
      if (m) {
        gemm_forward(handle, d_a, q, a_product, m, n, batch);
        inequality_violation<<<grid_for(m * batch), kThreads>>>(
            a_product, d_b, violation, m, batch);
      }
      if (e) {
        gemm_forward(handle, d_eq, q, eq_product, e, n, batch);
        equality_violation<<<grid_for(e * batch), kThreads>>>(
            eq_product, d_eq_rhs, violation, e, batch);
      }
      spec_violation<<<static_cast<unsigned>(batch), kThreads>>>(
          d_spec, d_spec_rhs, q, violation, n, batch);
      mark_feasible<<<grid_for(batch), kThreads>>>(
          violation, active, header.feasibility_tolerance, batch);
    }
  }
  cuda_ok(cudaDeviceSynchronize(), "collision solve");
  const double solve_ms = std::chrono::duration<double, std::milli>(
      std::chrono::steady_clock::now() - started).count();

  std::vector<double> host_q(n * batch), host_dual(m * batch);
  std::vector<double> host_eq_dual(e * batch), host_spec_dual(batch);
  std::vector<double> host_violation(batch);
  std::vector<int> host_active(batch), kind(batch);
  cuda_ok(cudaMemcpy(host_q.data(), q, host_q.size() * sizeof(double),
                     cudaMemcpyDeviceToHost), "copy primal");
  cuda_ok(cudaMemcpy(host_dual.data(), dual, host_dual.size() * sizeof(double),
                     cudaMemcpyDeviceToHost), "copy dual");
  cuda_ok(cudaMemcpy(host_eq_dual.data(), eq_dual,
                     host_eq_dual.size() * sizeof(double), cudaMemcpyDeviceToHost),
          "copy equality dual");
  cuda_ok(cudaMemcpy(host_spec_dual.data(), spec_dual,
                     batch * sizeof(double), cudaMemcpyDeviceToHost), "copy spec dual");
  cuda_ok(cudaMemcpy(host_violation.data(), violation,
                     batch * sizeof(double), cudaMemcpyDeviceToHost), "copy violation");
  cuda_ok(cudaMemcpy(host_active.data(), active, batch * sizeof(int),
                     cudaMemcpyDeviceToHost), "copy active");
  for (std::uint64_t cell = 0; cell < batch; ++cell) {
    kind[cell] = host_active[cell] ? 2 : 1;
    host_spec_dual[cell] /= spec_scale[cell];
    for (std::uint64_t variable = 0; variable < n; ++variable)
      host_q[variable * batch + cell] =
          lower[variable] + span[variable] * host_q[variable * batch + cell];
  }
  for (std::uint64_t row = 0; row < m; ++row)
    for (std::uint64_t cell = 0; cell < batch; ++cell)
      host_dual[row * batch + cell] /= a_scale[row];
  for (std::uint64_t row = 0; row < e; ++row)
    for (std::uint64_t cell = 0; cell < batch; ++cell)
      host_eq_dual[row * batch + cell] /= eq_scale[row];

  OutputHeader output{{'C','T','C','L','P','O','1','\0'}, 1, 8, batch, n, m, e,
                      iteration, solve_ms};
  std::ofstream stream(argv[2], std::ios::binary);
  stream.write(reinterpret_cast<const char*>(&output), sizeof(output));
  write_vector(stream, kind);
  write_vector(stream, host_violation);
  write_vector(stream, host_q);
  write_vector(stream, host_dual);
  write_vector(stream, host_spec_dual);
  write_vector(stream, host_eq_dual);
  if (!stream) throw std::runtime_error("failed to write collision output");
  cublasDestroy(handle);
  return 0;
} catch (const std::exception& error) {
  std::cerr << "certitherm_collision_cuda: " << error.what() << '\n';
  return 2;
}

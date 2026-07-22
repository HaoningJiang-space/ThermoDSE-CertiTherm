NVCC ?= /usr/local/cuda-12.8/bin/nvcc
CUDA_ARCH ?= sm_80
BUILD_DIR ?= ../../.build/collision-cuda
TARGET := $(BUILD_DIR)/certitherm_collision_cuda

.PHONY: all clean

all: $(TARGET)

$(TARGET): collision_solver.cu
	mkdir -p $(BUILD_DIR)
	$(NVCC) -std=c++17 -O3 -lineinfo -arch=$(CUDA_ARCH) \
		--ptxas-options=-v -Xcompiler=-Wall,-Wextra \
		-o $@ $< -lcublas

clean:
	rm -f $(TARGET)

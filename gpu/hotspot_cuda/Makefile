NVCC ?= /usr/local/cuda-12.8/bin/nvcc
CUDA_ARCH ?= sm_80
BUILD_DIR ?= ../../.build/hotspot-cuda
TARGET := $(BUILD_DIR)/certitherm_hotspot_cuda

.PHONY: all clean

all: $(TARGET)

$(TARGET): steady_solver.cu
	mkdir -p $(BUILD_DIR)
	$(NVCC) -std=c++17 -O3 -lineinfo -arch=$(CUDA_ARCH) \
		--ptxas-options=-v -Xcompiler=-Wall,-Wextra \
		-o $@ $<

clean:
	rm -f $(TARGET)

PYTHON := .venv/bin/python
HOTSPOT_BUILD := .build/hotspot
HOTSPOT_BIN := $(HOTSPOT_BUILD)/hotspot
GPU_HOTSPOT_BUILD := .build/hotspot-gpu-export
GPU_HOTSPOT_BIN := $(GPU_HOTSPOT_BUILD)/hotspot
GPU_SOLVER := .build/hotspot-cuda/certitherm_hotspot_cuda
SUPERLU_SOURCE_BUILD := .build/superlu-source
SUPERLU_BUILD := .build/superlu
SUPERLU_LIB := $(SUPERLU_BUILD)/SRC/libsuperlu.a
SUPERLU_BLAS := $(SUPERLU_BUILD)/CBLAS/libblas.a
CUDA_NVCC ?= /usr/local/cuda-12.8/bin/nvcc
CUDA_ARCH ?= sm_80

.PHONY: bootstrap gpu-bootstrap check gpu-check test hotspot-smoke gpu-parity gpu-production-parity reproduce-dev reproduce-dev-gpu heldout package-dev package-heldout clean-generated

bootstrap:
	git submodule sync --recursive
	git submodule update --init --recursive
	python3 -m pip install --user virtualenv==20.26.6
	python3 -m virtualenv --python=python3 .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.lock
	mkdir -p $(HOTSPOT_BUILD)
	find $(HOTSPOT_BUILD) -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
	git -C HotSpot archive HEAD | tar -xf - -C $(HOTSPOT_BUILD)
	patch -d $(HOTSPOT_BUILD) -p1 < patches/hotspot-output-precision.patch
	patch -d $(HOTSPOT_BUILD) -p1 < patches/hotspot-grid-convergence.patch
	$(MAKE) -C $(HOTSPOT_BUILD) hotspot
	sha256sum $(HOTSPOT_BIN) > $(HOTSPOT_BUILD)/SHA256SUMS

gpu-bootstrap: bootstrap
	mkdir -p $(SUPERLU_SOURCE_BUILD) $(SUPERLU_BUILD)
	find $(SUPERLU_SOURCE_BUILD) -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
	find $(SUPERLU_BUILD) -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
	git -C SuperLU archive HEAD | tar -xf - -C $(SUPERLU_SOURCE_BUILD)
	cmake -S $(SUPERLU_SOURCE_BUILD) -B $(SUPERLU_BUILD) \
		-DBUILD_SHARED_LIBS=OFF -Denable_blaslib=ON -Denable_tests=OFF \
		-Denable_single=OFF -Denable_double=ON \
		-Denable_complex=OFF -Denable_complex16=OFF
	cmake --build $(SUPERLU_BUILD) --parallel
	mkdir -p $(GPU_HOTSPOT_BUILD)
	find $(GPU_HOTSPOT_BUILD) -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
	git -C HotSpot archive HEAD | tar -xf - -C $(GPU_HOTSPOT_BUILD)
	patch -d $(GPU_HOTSPOT_BUILD) -p1 < patches/hotspot-output-precision.patch
	patch -d $(GPU_HOTSPOT_BUILD) -p1 < patches/hotspot-grid-convergence.patch
	patch -d $(GPU_HOTSPOT_BUILD) -p1 < patches/hotspot-gpu-system-export.patch
	install -m 0644 gpu/hotspot_cuda/system_export.c \
		$(GPU_HOTSPOT_BUILD)/certitherm_gpu_export.c
	$(MAKE) -C $(GPU_HOTSPOT_BUILD) SUPERLU=1 \
		INCDIR=$(abspath $(SUPERLU_SOURCE_BUILD)/SRC) \
		LIBS='$(abspath $(SUPERLU_LIB)) $(abspath $(SUPERLU_BLAS)) -lm' \
		GRIDSRC='temperature_grid.c certitherm_gpu_export.c' \
		GRIDOBJ='temperature_grid.o certitherm_gpu_export.o' hotspot
	$(MAKE) -C gpu/hotspot_cuda NVCC=$(CUDA_NVCC) CUDA_ARCH=$(CUDA_ARCH)
	sha256sum $(GPU_HOTSPOT_BIN) $(GPU_SOLVER) \
		> $(GPU_HOTSPOT_BUILD)/GPU_SHA256SUMS

test:
	$(PYTHON) -m pytest -q CertiTherm/tests

hotspot-smoke:
	mkdir -p .build/smoke
	$(HOTSPOT_BIN) \
		-c $(HOTSPOT_BUILD)/examples/example1/example.config \
		-f $(HOTSPOT_BUILD)/examples/example1/ev6.flp \
		-p $(HOTSPOT_BUILD)/examples/example1/gcc.ptrace \
		-materials_file $(HOTSPOT_BUILD)/examples/example1/example.materials \
		-model_type block -steady_file .build/smoke/example1.steady
	test -s .build/smoke/example1.steady

check: test hotspot-smoke
	git diff --check
	git submodule status --recursive | awk '$$1 ~ /^[-+U]/ { bad=1 } END { exit bad }'
	git submodule foreach --recursive 'test -z "$$(git status --porcelain)"'

gpu-parity:
	$(PYTHON) -m CertiTherm.gpu_benchmark \
		--reference $(HOTSPOT_BIN) --exporter $(GPU_HOTSPOT_BIN) \
		--solver $(GPU_SOLVER) --output artifacts/gpu-hotspot-dev

gpu-production-parity:
	$(PYTHON) -m CertiTherm.gpu_benchmark \
		--reference $(HOTSPOT_BIN) --exporter $(GPU_HOTSPOT_BIN) \
		--solver $(GPU_SOLVER) --case thermodse-227 \
		--output artifacts/gpu-hotspot-production

gpu-check: test hotspot-smoke gpu-parity
	git diff --check
	git submodule status --recursive | awk '$$1 ~ /^[-+U]/ { bad=1 } END { exit bad }'
	git submodule foreach --recursive 'test -z "$$(git status --porcelain)"'

reproduce-dev:
	$(PYTHON) -m CertiTherm.experiments --split dev --output artifacts/dev

reproduce-dev-gpu:
	CERTITHERM_GPU_HOTSPOT=1 $(PYTHON) -m CertiTherm.experiments \
		--split dev --output artifacts/dev-gpu

heldout:
	$(PYTHON) -m CertiTherm.experiments --split heldout --output artifacts/heldout --frozen

package-dev:
	test -f artifacts/dev/ARTIFACTS.tsv
	mkdir -p artifacts/releases
	tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
		--exclude=work -czf artifacts/releases/certitherm-dev.tar.gz \
		-C artifacts dev
	sha256sum artifacts/releases/certitherm-dev.tar.gz \
		> artifacts/releases/certitherm-dev.tar.gz.sha256

package-heldout:
	test -f artifacts/heldout/ARTIFACTS.tsv
	mkdir -p artifacts/releases
	tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
		--exclude=work -czf artifacts/releases/certitherm-heldout.tar.gz \
		-C artifacts heldout
	sha256sum artifacts/releases/certitherm-heldout.tar.gz \
		> artifacts/releases/certitherm-heldout.tar.gz.sha256

clean-generated:
	find .build -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
	find artifacts -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +

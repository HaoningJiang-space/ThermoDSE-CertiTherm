PYTHON := .venv/bin/python
HOTSPOT_BUILD := .build/hotspot
HOTSPOT_BIN := $(HOTSPOT_BUILD)/hotspot

.PHONY: bootstrap check test hotspot-smoke reproduce-dev heldout clean-generated

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
	$(MAKE) -C $(HOTSPOT_BUILD) hotspot
	sha256sum $(HOTSPOT_BIN) > $(HOTSPOT_BUILD)/SHA256SUMS

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

reproduce-dev:
	$(PYTHON) -m CertiTherm.experiments --split dev --output artifacts/dev

heldout:
	$(PYTHON) -m CertiTherm.experiments --split heldout --output artifacts/heldout --frozen

clean-generated:
	find .build -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
	find artifacts -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +

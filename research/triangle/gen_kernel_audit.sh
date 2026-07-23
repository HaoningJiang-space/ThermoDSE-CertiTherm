#!/usr/bin/env bash
set -u
for spec in "resnet50 0" "resnet50 2" "transformer 0"; do
  set -- $spec
  echo "### CANDIDATE $1 c$2 ###"
  .venv/bin/python -u research/triangle/kernel_audit.py artifacts/diag150b "$1" "$2" 1e-6 2>&1 \
    | grep -E "P dim|SAFE:|REJECT:|margin|final-set re-audit:|  SAFE [0-9]"
done
echo "### GEN DONE ###"

"""Capture per-DNN ptrace for each architecture in the G3 2x2x2 bundle.

This script uses the ThermoDSE chiplet_evaluator to evaluate each of the
4 designs (2 archs x 2 packages would need 4, but per-DNN ptrace is arch-
specific, so 2 archs x 2 DNNs = 4 files). Each DNN's per-design ptrace
must be distinct (no relabeling) for the G3 suite to pass anti-cheat.

Per-DNN ptrace files are written to:
  <bundle>/<arch_name>/<dnn_name>_3D.ptrace

The runner (g3_full_empirical.py) reads these directly and constructs
the per-design observation triplet (point, placed, spatial) from
each of these.
"""
import sys
import os

sys.path.insert(0, "/home/ynwang/jhn/DSE/ThermoDSE")
from core.chiplet_eva import chiplet_evaluator

ARCHITECTURES = {
    "4x4_tesa": [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128],
    "5x4_struct": [5, 4, 5, 4, 0.001, 144, 128, 2097152, 144, 128],
}
DNNS = ["resnet50", "transformer"]
OUTPUT_DIR = "/home/ynwang/jhn/DSE/CertiTherm/evidence/g3_2x2x2_bundle"

for arch_name, sys_info in ARCHITECTURES.items():
    out_dir = os.path.join(OUTPUT_DIR, arch_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n=== arch={arch_name} sys_info={sys_info} ===")
    ev = chiplet_evaluator(
        hotspot_path="/home/ynwang/jn/DSE/HotSpot/hotspot",
        sim_path="/home/ynwang/jn/DSE/ThermoDSE/tmp",
        sys_info=sys_info,
        thermal_map=False,
        baseline1=False, baseline2=False, baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    ev.generate_hardware()
    ev.evaluate()
    ptrace_dir = "/home/ynwang/jn/DSE/ThermoDSE/tmp/ptrace"
    for dnn in DNNS:
        src = os.path.join(ptrace_dir, f"{dnn}_3D.ptrace")
        if not os.path.exists(src):
            print(f"  WARN: {src} not found")
            continue
        with open(src) as fin:
            content = fin.read()
        dst = os.path.join(out_dir, f"{dnn}_3D.ptrace")
        with open(dst, "w") as fout:
            fout.write(content)
        # SHA for record
        import hashlib
        sha = hashlib.sha256(content.encode()).hexdigest()
        print(f"  Copied dnn={dnn} -> {dst}  sha256={sha[:16]}")
print("\nAll per-DNN ptrace captures complete")

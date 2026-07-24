#!/usr/bin/env bash
# COUNTERBALANCED, PAIRED, FAIL-CLOSED A/B of the deletion ORDER (cost vs spectral).
#
# Ordering cannot change feasibility soundness -- every removal is accepted only after an
# exact collision test and the final cover re-verify is always full+exhaustive. It CAN
# change which inclusion-minimal cover is reached and therefore U, so this measures both.
#
# Design, after two review rounds:
#
#  * PAIRED + COUNTERBALANCED PER CANDIDATE. The two arms for one candidate run
#    back-to-back, and the arm that goes first alternates by (rep + candidate index)
#    parity. With an EVEN number of repetitions this gives each candidate exactly half
#    cost-first and half spectral-first pairs. With 3 reps it does NOT -- each candidate
#    would be 2:1 -- so REPS is forced even.
#  * CANDIDATE ORDER ROTATES per repetition, so candidate identity is not confounded with
#    time since experiment start.
#  * FAIL CLOSED ON TRUNCATION. A budget-truncated run still prints "verified feasible
#    cover"; only the preceding "--- result (partial (budget-truncated)...)" line
#    distinguishes it. Filtering that line away would let a non-inclusion-minimal cover
#    pass as a valid endpoint. Every arm's manifest is parsed and the run ABORTS unless
#    completed_sweep is true and the configuration matches what was requested.
#  * FULL PER-ARM LOGS are kept; the console summary is derived, never the sole record.
#  * SEPARATE MANIFESTS per arm (CERTITHERM_MANIFEST_TAG), so the covers can be compared.
#  * PRIMARY EVIDENCE is the deterministic counters (oracle queries, POOL_REACHED, cover
#    size, U) -- verified reproducible bit-for-bit across 3 repeats of one configuration.
#    Wall time is paired SECONDARY evidence and is reported with per-process CPU-seconds so
#    "did more work" can be told apart from "waited longer for CPU".
#
# Usage (clone root): bash research/triangle/deletion_order_ab.sh [reps] [out]
set -euo pipefail

REPS="${1:-4}"
OUT="${2:-artifacts/diag150b}"
WORKERS="${CERTITHERM_LP_WORKERS:-16}"
BUDGET="${CERTITHERM_AB_BUDGET:-5400}"

if (( REPS % 2 != 0 )); then
  echo "FAIL: REPS must be EVEN so each candidate gets equal cost-first and spectral-first"
  echo "      pairs (odd REPS leaves every candidate 2:1 imbalanced)." >&2
  exit 2
fi

CANDS=("resnet50 1" "transformer 0" "resnet50 2" "resnet50 0")
RUNID="ab-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
RUNDIR="$OUT/$RUNID"
if [ -e "$RUNDIR" ]; then
  echo "FAIL: run directory $RUNDIR already exists; refusing to overwrite" >&2; exit 2
fi
mkdir -p "$RUNDIR/logs"

echo "### RUNID=$RUNID ###"
echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### HOST: $(hostname) cpus=$(nproc) workers=$WORKERS reps=$REPS budget=${BUDGET}s ###"
git status --porcelain > "$RUNDIR/git-dirty.txt" || true
git rev-parse HEAD > "$RUNDIR/git-head.txt"

# Periodic host telemetry for the whole experiment: sampling only at arm boundaries
# misses transient interference over a 20-minute arm.
( while :; do
    printf '%s load=%s cached_kB=%s procs=%s\n' \
      "$(date -u +%FT%T.%3NZ)" "$(cut -d' ' -f1-3 /proc/loadavg)" \
      "$(awk '/^Cached:/{print $2}' /proc/meminfo)" \
      "$(ps -eo pcpu= --sort=-pcpu | head -8 | tr -d ' ' | tr '\n' ',')"
    sleep 10
  done > "$RUNDIR/host-telemetry.log" ) &
TELEMETRY_PID=$!
cleanup() { kill "$TELEMETRY_PID" 2>/dev/null || true; }
trap cleanup EXIT

run_arm() {
  local rep=$1 ord=$2 wl=$3 cand=$4 slot=$5
  local tag="_${ord}_r${rep}"
  local key="r${rep}_${wl}_c${cand}_${ord}"
  local log="$RUNDIR/logs/$key.log"
  local res="$RUNDIR/logs/$key.resource"

  echo "### rep=$rep slot=$slot order=$ord wl=$wl cand=$cand log=$key.log ###"
  local t0 t1
  t0=$(date +%s.%N)
  # /usr/bin/time -v gives per-process user/sys CPU-seconds, peak RSS, faults and
  # context switches; without those, a wall-time delta cannot be attributed.
  if ! CERTITHERM_LP_WORKERS="$WORKERS" \
       CERTITHERM_DELETION_MODE=first \
       CERTITHERM_USE_KERNEL=1 \
       CERTITHERM_ORACLE_BACKEND=thread \
       CERTITHERM_DELETION_ORDER="$ord" \
       CERTITHERM_MANIFEST_TAG="$tag" \
       /usr/bin/time -v -o "$res" \
         .venv/bin/python -u research/triangle/upper_bound.py \
           "$OUT" "$BUDGET" "$wl" "$cand" > "$log" 2>&1; then
    echo "FAIL: arm $key exited non-zero; see $log" >&2
    tail -20 "$log" >&2 || true
    exit 3
  fi
  t1=$(date +%s.%N)

  # FAIL CLOSED: validate the manifest rather than trusting a grepped line.
  local man="$OUT/upper_bound_${wl}_c${cand}${tag}.json"
  if ! .venv/bin/python - "$man" "$ord" "$WORKERS" <<'PY'
import json, sys
path, want_order, want_workers = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    m = json.load(open(path))
except Exception as exc:
    print(f"MANIFEST UNREADABLE {path}: {exc}"); sys.exit(1)
problems = []
if not m.get("completed_sweep"):
    problems.append("completed_sweep is false -> budget-truncated, NOT inclusion-minimal")
if m.get("deletion_order") != want_order:
    problems.append(f"deletion_order={m.get('deletion_order')!r} != requested {want_order!r}")
if str(m.get("lp_workers")) != str(want_workers):
    problems.append(f"lp_workers={m.get('lp_workers')!r} != requested {want_workers!r}")
if m.get("deletion_mode") != "first":
    problems.append(f"deletion_mode={m.get('deletion_mode')!r} != 'first'")
if not m.get("use_kernel"):
    problems.append("use_kernel is false")
if problems:
    for p in problems:
        print("MANIFEST CHECK FAILED:", p)
    sys.exit(1)
print("  manifest ok: U=%s cover=%s kernel_build=%.0fs initial_verify=%.0fs"
      % (m["U"], m["cover_size"], m.get("kernel_build_s", -1),
         m.get("initial_verify_s", -1)))
PY
  then
    echo "FAIL: arm $key produced an unusable manifest; aborting the experiment" >&2
    exit 4
  fi
  cp "$man" "$RUNDIR/logs/$key.manifest.json"

  # derived summary (the log above is the authoritative record)
  grep -E "spectral deletion order|--- result|verified feasible|item-2 gate" "$log" | sed 's/^/    /'
  local cpu_u cpu_s
  cpu_u=$(awk -F': ' '/User time/{print $2}' "$res")
  cpu_s=$(awk -F': ' '/System time/{print $2}' "$res")
  printf '### rep=%s RESULT order=%s wl=%s cand=%s slot=%s WALL=%.1fs cpu_user=%ss cpu_sys=%ss ###\n' \
    "$rep" "$ord" "$wl" "$cand" "$slot" "$(echo "$t1 - $t0" | bc)" "$cpu_u" "$cpu_s"
}

for rep in $(seq 1 "$REPS"); do
  # rotate candidate order so candidate identity is not tied to elapsed experiment time
  n=${#CANDS[@]}
  shift_by=$(( (rep - 1) % n ))
  for k in $(seq 0 $((n - 1))); do
    idx=$(( (k + shift_by) % n ))
    set -- ${CANDS[$idx]}
    wl=$1; cand=$2
    if (( (rep + idx) % 2 == 0 )); then first=cost; second=spectral
    else                               first=spectral; second=cost; fi
    run_arm "$rep" "$first"  "$wl" "$cand" 1
    run_arm "$rep" "$second" "$wl" "$cand" 2
  done
done
echo "### AB DONE $RUNID $(date -u +%FT%TZ) load=$(cut -d' ' -f1-3 /proc/loadavg) ###"
echo "### artifacts under $RUNDIR ###"

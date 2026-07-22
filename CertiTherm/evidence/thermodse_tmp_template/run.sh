#!/usr/bin/env bash
# HotSpot wrapper with tcmalloc preload to bypass malloc crash bug
# Also fixes ptrace units to match floorplan (runtime ptrace has extra interposer blocks)
CONFIG=$1
FLP=$2
PTRACE=$3
SIDE=$4
WORKPATH=$5
mkdir -p ${WORKPATH}/outputs
cd ${WORKPATH}

# Truncate ptrace to match flp units (runtime ptrace includes interposer blocks)
FLP_UNIT_COUNT=$(grep -v "^#" "$FLP" | awk 'NF>=5 {print $1}' | wc -l)
ORIG_HEADER=$(head -1 "$PTRACE")
ORIG_COUNT=$(echo "$ORIG_HEADER" | tr '\t' '\n' | wc -l)
if [ "$FLP_UNIT_COUNT" -lt "$ORIG_COUNT" ]; then
    # Write a fixed ptrace matching flp units
    FIXED_PTRACE="${WORKPATH}/ptrace/cores_3D_fixed.ptrace"
    # header
    grep -v "^#" "$FLP" | awk 'NF>=5 {print $1}' | tr '\n' '\t' | sed 's/\t$/\n/' > "$FIXED_PTRACE"
    # values (take first FLP_UNIT_COUNT values from each row)
    tail -n +2 "$PTRACE" | awk -v n="$FLP_UNIT_COUNT" '{
        for (i=1; i<=n; i++) printf "%s\t", $i; print ""
    }' >> "$FIXED_PTRACE"
    PTRACE="$FIXED_PTRACE"
fi

HOTSPOT_BIN=${CERTITHERM_HOTSPOT_BIN:?set CERTITHERM_HOTSPOT_BIN to a verified binary}
"$HOTSPOT_BIN" \
  -c ${CONFIG} \
  -f ${FLP} \
  -p ${PTRACE} \
  -materials_file example.materials \
  -model_type block \
  -steady_file outputs/gcc.steady

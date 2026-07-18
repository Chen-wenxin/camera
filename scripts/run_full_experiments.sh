#!/bin/bash
# run_full_experiments.sh ? Comprehensive experiment suite for Grove extensions
# Covers: all 6 YCSB workloads + adaptive Gamma comparison + value size sweep
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
RESULTS_DIR="$ROOT_DIR/results/full_suite_$(date +%Y%m%d_%H%M)"
mkdir -p "$RESULTS_DIR"

LEVELDB_BENCH="$SRC_DIR/leveldb/build/baseline_db_bench"
DB_DIR="/tmp/grove_full_exp_db"
KEY_SIZE=16
VALUE_SIZE=128

echo "=============================================="
echo "  Full Experiment Suite ? Grove Extensions"
echo "  Results: $RESULTS_DIR"
echo "=============================================="

# Helper
run_aged() {
    local label="$1" age="$2" bench="$3" ops="$4" extra="$5"
    local out="$RESULTS_DIR/${label}_age${age}_$(date +%H%M%S).txt"
    rm -rf "$DB_DIR"; mkdir -p "$DB_DIR"
    $bench --db="$DB_DIR" --benchmarks="fillrandom" --num="$age" \
        --key_size="$KEY_SIZE" --value_size="$VALUE_SIZE" 2>&1 | tail -3
    $bench --db="$DB_DIR" --benchmarks="$ops" --num=1000000 \
        --key_size="$KEY_SIZE" --value_size="$VALUE_SIZE" \
        --use_existing_db=1 --histogram=1 $extra 2>&1 | tee "$out"
    echo ""
}

# ====================================================
# 1. Reproduce Section 2.2 + 4.2 (original Grove paper)
# ====================================================
echo "=== [1/5] Reproducing original Grove experiments ==="
AGES=(1000000 2000000 4000000 8000000 16000000 32000000)
for age in "${AGES[@]}"; do
    run_aged "original_overwrite" "$age" "$LEVELDB_BENCH" "overwrite"
    run_aged "original_readrandom" "$age" "$LEVELDB_BENCH" "readrandom"
done

# ====================================================
# 2. All 6 YCSB workloads (Section 4.3 extension)
# ====================================================
echo "=== [2/5] YCSB: All 6 core workloads ==="
YCSB_DIR="$SRC_DIR/ycsb"
if [ -d "$YCSB_DIR" ]; then
    cd "$YCSB_DIR"
    mvn -pl site.ycsb:leveldb-binding -am package -DskipTests -q 2>&1 | tail -1
    
    for wl in a b c d e f; do
        echo "  Workload $wl ..."
        rm -rf "$DB_DIR"
        python3 bin/ycsb load leveldb -P "workloads/workload${wl}" \
            -p recordcount=32000000 -p fieldlength=128 \
            -p leveldb.dir="$DB_DIR" -threads 1 2>&1 | tail -2
        python3 bin/ycsb run leveldb -P "workloads/workload${wl}" \
            -p recordcount=32000000 -p operationcount=2000000 \
            -p fieldlength=128 -p leveldb.dir="$DB_DIR" \
            -threads 1 2>&1 | tee "$RESULTS_DIR/ycsb_workload${wl}.txt"
    done
    cd "$ROOT_DIR"
else
    echo "  YCSB not found, skipping."
fi

# ====================================================
# 3. Bloom filter sensitivity (extended: 1-60 bits)
# ====================================================
echo "=== [3/5] Bloom filter sensitivity ==="
BLOOM_BITS=(1 5 10 15 20 25 30 40 50 60)
BASE_AGE=16000000
for bits in "${BLOOM_BITS[@]}"; do
    run_aged "bloom_${bits}bits" "$BASE_AGE" "$LEVELDB_BENCH" "readrandom" \
        "--bloom_bits=$bits"
done

# ====================================================
# 4. Value size sweep (Fig 7 extension: finer granularity)
# ====================================================
echo "=== [4/5] Value size sweep ==="
VSIZES=(32 64 128 256 512 1024 2048 4096)
for vs in "${VSIZES[@]}"; do
    run_aged "vsize_${vs}B" "$BASE_AGE" "$LEVELDB_BENCH" "overwrite" \
        "--value_size=$vs"
done

# ====================================================
# 5. Write buffer size sweep (proxy for Gamma sensitivity)
# ====================================================
echo "=== [5/5] Write buffer size sweep (Gamma proxy) ==="
WBS=(4194304 8388608 16777216 33554432 67108864 134217728 268435456)
for wb in "${WBS[@]}"; do
    wb_mb=$((wb / 1048576))
    run_aged "wbuf_${wb_mb}MB" "$BASE_AGE" "$LEVELDB_BENCH" "overwrite" \
        "--write_buffer_size=$wb"
done

echo ""
echo "=============================================="
echo "  Full suite complete!"
echo "  Results: $RESULTS_DIR"
echo "  Run: python3 analysis/plot_results.py $RESULTS_DIR"
echo "=============================================="

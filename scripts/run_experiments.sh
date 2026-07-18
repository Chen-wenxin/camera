#!/bin/bash
# run_experiments.sh ? Reproduce all experiments from:
#   "Grove: De-aging by Spawning a Tract of LSM-trees" (APWeb-WAIM 2026)
#
# Usage:
#   ./scripts/run_experiments.sh [baseline|grove|all]
#   Default: all
#
# Paper sections reproduced:
#   Section 2.2 ? Motivational Study (aging impact)
#   Section 4.2 ? Micro-benchmark (db_bench) write, compaction, read
#   Section 4.3 ? Macro-benchmark (YCSB SessionStore)
#   Section 4.4 ? Sensitivity: Bloom filter bits, Gamma, value size

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
RESULTS_DIR="$ROOT_DIR/results"
MODE="${1:-all}"

# Binary paths
LEVELDB_BENCH="$SRC_DIR/leveldb/build/baseline_db_bench"
ROCKSDB_BENCH="$SRC_DIR/rocksdb/build/rocksdb_baseline_db_bench"
LEVELDB_GROVE_BENCH="$SRC_DIR/leveldb-grove/build/grove_db_bench"
ROCKSDB_GROVE_BENCH="$SRC_DIR/rocksdb-grove/build/rocksdb_grove_db_bench"

# Common params (matching paper: 16B key, 128B value by default)
KEY_SIZE=16
VALUE_SIZE=128
DB_DIR="/tmp/grove_experiment_db"

mkdir -p "$RESULTS_DIR"

# Helper: run db_bench and extract throughput + 99.9P latency
run_bench() {
    local label="$1"
    local binary="$2"
    local workload="$3"
    local num="$4"
    local extra_flags="$5"
    local outfile="$RESULTS_DIR/${label}_$(date +%Y%m%d_%H%M%S).txt"

    echo "  [$label] $workload x $num ..."
    rm -rf "$DB_DIR"
    mkdir -p "$DB_DIR"

    # Capture output
    $binary --db="$DB_DIR" --benchmarks="$workload" --num="$num" \
        --key_size="$KEY_SIZE" --value_size="$VALUE_SIZE" \
        --histogram=1 $extra_flags 2>&1 | tee "$outfile"

    # Extract throughput line
    grep -E "(micros/op|MB/sec|ops/sec)" "$outfile" | tail -20
    echo ""
}

# Helper: run fillrandom to age, then workload
run_aged_bench() {
    local label="$1"
    local binary="$2"
    local workload="$3"
    local existing="$4"
    local ops="$5"
    local extra_flags="$6"
    local outfile="$RESULTS_DIR/${label}_age${existing}_$(date +%Y%m%d_%H%M%S).txt"

    echo "  [$label] age=$existing, $workload x $ops ..."
    rm -rf "$DB_DIR"
    mkdir -p "$DB_DIR"

    # Fill to age the DB
    $binary --db="$DB_DIR" --benchmarks="fillrandom" --num="$existing" \
        --key_size="$KEY_SIZE" --value_size="$VALUE_SIZE" \
        --histogram=1 2>&1 | tail -5

    # Run actual workload
    $binary --db="$DB_DIR" --benchmarks="$workload" --num="$ops" \
        --key_size="$KEY_SIZE" --value_size="$VALUE_SIZE" \
        --use_existing_db=1 --histogram=1 $extra_flags 2>&1 | tee "$outfile"

    grep -E "(micros/op|MB/sec|ops/sec)" "$outfile" | tail -20
    echo ""
}

echo "=============================================="
echo "  Grove Experiment Suite"
echo "  Mode: $MODE"
echo "  Results: $RESULTS_DIR"
echo "=============================================="

# ============================================================
# Section 2.2: Motivational Study ? Aging Impact on LevelDB
# ============================================================
run_motivation() {
    local bench="$1"
    local prefix="$2"

    echo ""
    echo "--- Section 2.2: Motivational Study ($prefix) ---"
    echo "  Aging degrees: 1, 2, 4, 8, 16, 32 million existing KV pairs"
    echo "  Workload: overwrite x 1M (write) + readrandom x 1M (read)"
    echo ""

    AGES=(1000000 2000000 4000000 8000000 16000000 32000000)

    # Figure 2a: Write performance degradation
    echo "  [Fig 2a] Write throughput vs. age..."
    for age in "${AGES[@]}"; do
        run_aged_bench "${prefix}_motivation_write" "$bench" "overwrite" "$age" 1000000
    done

    # Figure 2c: Read performance degradation
    echo "  [Fig 2c] Read throughput vs. age..."
    for age in "${AGES[@]}"; do
        run_aged_bench "${prefix}_motivation_read" "$bench" "readrandom" "$age" 1000000
    done

    # Figure 2b: Compaction data volumes (tracked internally by db_bench)
    echo "  [Fig 2b] Compaction stats are in db_bench output (compaction counters)."
}

# ============================================================
# Section 4.2: Micro-benchmark ? Grove De-aging Effect
# ============================================================
run_micro_bench() {
    local baseline_bench="$1"
    local grove_bench="$2"
    local prefix="$3"
    local has_grove="$4"

    echo ""
    echo "--- Section 4.2: Micro-benchmark ($prefix) ---"
    echo ""

    AGES=(1000000 2000000 4000000 8000000 16000000 32000000)

    # Figure 4a: Grove write performance
    echo "  [Fig 4a] Write throughput with Grove..."
    for age in "${AGES[@]}"; do
        run_aged_bench "${prefix}_grove_write" "$baseline_bench" "overwrite" "$age" 1000000
    done
    if [ "$has_grove" = "yes" ] && [ -f "$grove_bench" ]; then
        for age in "${AGES[@]}"; do
            run_aged_bench "${prefix}_grove_write_grove" "$grove_bench" "overwrite" "$age" 1000000
        done
    fi

    # Figure 4c: Grove read performance
    echo "  [Fig 4c] Read throughput with Grove..."
    for age in "${AGES[@]}"; do
        run_aged_bench "${prefix}_grove_read" "$baseline_bench" "readrandom" "$age" 1000000
    done
    if [ "$has_grove" = "yes" ] && [ -f "$grove_bench" ]; then
        for age in "${AGES[@]}"; do
            run_aged_bench "${prefix}_grove_read_grove" "$grove_bench" "readrandom" "$age" 1000000
        done
    fi
}

# ============================================================
# Section 4.4: Sensitivity Analysis
# ============================================================
run_sensitivity() {
    local bench="$1"
    local prefix="$2"

    echo ""
    echo "--- Section 4.4: Sensitivity Analysis ($prefix) ---"
    echo ""

    # Figure 4d: Bloom filter bits per key
    echo "  [Fig 4d] Varying Bloom filter bits (1, 5, 10, 20, 30, 40, 50)..."
    BITS=(1 5 10 20 30 40 50)
    for bits in "${BITS[@]}"; do
        run_aged_bench "${prefix}_bloom_${bits}bits" "$bench" "readrandom" 16000000 1000000 \
            "--bloom_bits=$bits"
    done

    # Figure 6: Varying Gamma conditions
    # Note: Gamma is a Grove-specific feature; baseline just uses different
    # write_buffer_size as proxy for tree size
    echo "  [Fig 6] Varying tree size thresholds (proxy: write_buffer_size MB)..."
    SIZES_MB=(4 8 16 32 64 128 256)
    for size in "${SIZES_MB[@]}"; do
        run_aged_bench "${prefix}_gamma_${size}MB" "$bench" "overwrite" 16000000 1000000 \
            "--write_buffer_size=$((size * 1024 * 1024))"
    done

    # Figure 7: Varying value sizes
    echo "  [Fig 7] Varying value sizes (64, 128, 256, 512, 1024)..."
    VSIZES=(64 128 256 512 1024)
    for vsize in "${VSIZES[@]}"; do
        run_aged_bench "${prefix}_vsize_${vsize}" "$bench" "overwrite" 16000000 1000000 \
            "--value_size=$vsize"
    done
}

# ============================================================
# Section 4.3: YCSB Macro-benchmark (SessionStore / Workload A)
# ============================================================
run_ycsb() {
    echo ""
    echo "--- Section 4.3: YCSB SessionStore (Workload A) ---"
    echo "  50% read / 50% write, Zipf distribution"
    echo ""

    YCSB_DIR="$SRC_DIR/ycsb"

    if [ ! -d "$YCSB_DIR" ]; then
        echo "  YCSB not found at $YCSB_DIR. Skipping."
        return
    fi

    cd "$YCSB_DIR"

    # Build YCSB LevelDB binding
    echo "  Building YCSB LevelDB binding..."
    mvn -pl site.ycsb:leveldb-binding -am clean package -DskipTests -q 2>&1 | tail -3

    # Run workload A on baseline LevelDB
    echo "  Running Workload A on baseline LevelDB..."
    rm -rf "$DB_DIR"
    python3 bin/ycsb load leveldb -P workloads/workloada \
        -p recordcount=32000000 -p fieldlength=128 \
        -p leveldb.dir="$DB_DIR" -threads 1 2>&1 | tail -5

    python3 bin/ycsb run leveldb -P workloads/workloada \
        -p recordcount=32000000 -p operationcount=1000000 \
        -p fieldlength=128 -p leveldb.dir="$DB_DIR" \
        -threads 1 2>&1 | tee "$RESULTS_DIR/ycsb_baseline_$(date +%Y%m%d_%H%M%S).txt"

    echo "  YCSB complete. See $RESULTS_DIR/ycsb_*.txt"
}

# ============================================================
# Main dispatch
# ============================================================
case "$MODE" in
    baseline)
        run_motivation "$LEVELDB_BENCH" "leveldb"
        run_micro_bench "$LEVELDB_BENCH" "" "leveldb" "no"
        run_sensitivity "$LEVELDB_BENCH" "leveldb"
        run_ycsb
        ;;
    grove)
        if [ -f "$LEVELDB_GROVE_BENCH" ]; then
            run_micro_bench "" "$LEVELDB_GROVE_BENCH" "leveldb" "yes"
        fi
        if [ -f "$ROCKSDB_GROVE_BENCH" ]; then
            run_micro_bench "" "$ROCKSDB_GROVE_BENCH" "rocksdb" "yes"
        fi
        run_ycsb
        ;;
    all)
        run_motivation "$LEVELDB_BENCH" "leveldb"
        run_micro_bench "$LEVELDB_BENCH" "" "leveldb" "no"
        run_sensitivity "$LEVELDB_BENCH" "leveldb"
        if [ -f "$LEVELDB_GROVE_BENCH" ]; then
            run_micro_bench "" "$LEVELDB_GROVE_BENCH" "leveldb_grove" "yes"
        fi
        run_ycsb
        ;;
    *)
        echo "Usage: $0 [baseline|grove|all]"
        exit 1
        ;;
esac

echo ""
echo "=============================================="
echo "  All experiments complete."
echo "  Results saved to: $RESULTS_DIR"
echo "=============================================="

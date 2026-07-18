#!/bin/bash
# build.sh ? Build baseline LSM-tree engines (CMake-based)
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"

echo "=== Building Baseline & Grove Variants ==="

# --- LevelDB Baseline (CMake) ---
echo "[1/3] Building LevelDB baseline..."
cd "$SRC_DIR/leveldb"
mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release ..
cmake --build . -j$(nproc)
cp db_bench "$SRC_DIR/leveldb/build/baseline_db_bench"
echo "  LevelDB built."

# --- RocksDB Baseline (CMake) ---
echo "[2/3] Building RocksDB baseline..."
cd "$SRC_DIR/rocksdb"
mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release -DWITH_SNAPPY=ON -DWITH_LZ4=ON \
    -DWITH_ZSTD=ON -DWITH_BENCHMARK_TOOLS=ON ..
make -j$(nproc) db_bench
cp db_bench rocksdb_baseline_db_bench
echo "  RocksDB built."

# --- LevelDB-Grove (if source exists) ---
echo "[3/3] Checking for Grove variants..."
if [ -d "$SRC_DIR/leveldb-grove" ]; then
    cd "$SRC_DIR/leveldb-grove"
    mkdir -p build && cd build
    cmake -DCMAKE_BUILD_TYPE=Release ..
    cmake --build . -j$(nproc)
    cp db_bench grove_db_bench
    echo "  LevelDB-Grove built."
else
    echo "  NOTE: LevelDB-Grove not found. Implement ~650 LOC to enable."
fi

echo ""
echo "=== Build complete ==="
echo "LevelDB:   $SRC_DIR/leveldb/build/baseline_db_bench"
echo "RocksDB:   $SRC_DIR/rocksdb/build/rocksdb_baseline_db_bench"

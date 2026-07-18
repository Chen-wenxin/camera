#!/bin/bash
# build.sh ? Build baseline and Grove-modified LSM-tree engines
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"

echo "=== Building Baseline & Grove Variants ==="

# --- LevelDB Baseline ---
echo "[1/4] Building LevelDB baseline..."
cd "$SRC_DIR/leveldb"
# Build with Bloom filter support (LevelDB has this built-in)
make clean 2>/dev/null || true
make -j$(nproc) all
cp db_bench "$SRC_DIR/leveldb/baseline_db_bench"

# --- LevelDB-Grove ---
echo "[2/4] Building LevelDB-Grove..."
if [ -f "$SRC_DIR/leveldb-grove/Makefile" ]; then
    cd "$SRC_DIR/leveldb-grove"
    make clean 2>/dev/null || true
    make -j$(nproc) all
    cp db_bench "$SRC_DIR/leveldb-grove/grove_db_bench"
else
    echo "  NOTE: LevelDB-Grove source not found at $SRC_DIR/leveldb-grove"
    echo "  The Grove modifications (~650 LOC) need to be applied to LevelDB."
    echo "  See src/leveldb-grove/ for the patch-based approach."
fi

# --- RocksDB Baseline ---
echo "[3/4] Building RocksDB baseline..."
cd "$SRC_DIR/rocksdb/build"
cmake -DCMAKE_BUILD_TYPE=Release -DWITH_SNAPPY=ON -DWITH_LZ4=ON \
    -DWITH_ZSTD=ON -DWITH_BENCHMARK_TOOLS=ON ..
make -j$(nproc) db_bench
cp db_bench "$SRC_DIR/rocksdb/build/rocksdb_baseline_db_bench"

# --- RocksDB-Grove ---
echo "[4/4] Building RocksDB-Grove..."
if [ -f "$SRC_DIR/rocksdb-grove/CMakeLists.txt" ]; then
    cd "$SRC_DIR/rocksdb-grove"
    mkdir -p build && cd build
    cmake -DCMAKE_BUILD_TYPE=Release -DWITH_SNAPPY=ON -DWITH_LZ4=ON \
        -DWITH_ZSTD=ON -DWITH_BENCHMARK_TOOLS=ON ..
    make -j$(nproc) db_bench
    cp db_bench "$SRC_DIR/rocksdb-grove/build/rocksdb_grove_db_bench"
else
    echo "  NOTE: RocksDB-Grove source not found."
fi

echo ""
echo "=== Build complete ==="
echo "Run ./scripts/run_experiments.sh to reproduce all experiments."

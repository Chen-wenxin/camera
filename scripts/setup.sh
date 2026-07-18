#!/bin/bash
# setup.sh ? Clone and prepare LevelDB, RocksDB, and YCSB for the Grove experiment
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
RESULTS_DIR="$ROOT_DIR/results"

echo "=== Grove Experiment Setup ==="
echo "Root: $ROOT_DIR"

# Install system dependencies
echo "[1/6] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq build-essential cmake libgflags-dev libsnappy-dev \
    zlib1g-dev libbz2-dev liblz4-dev libzstd-dev curl openjdk-17-jdk maven \
    python3 python3-pip

# Clone LevelDB
echo "[2/6] Cloning LevelDB..."
if [ ! -d "$SRC_DIR/leveldb" ]; then
    git clone --depth 1 https://github.com/google/leveldb.git "$SRC_DIR/leveldb"
else
    echo "  LevelDB already exists, skipping clone."
fi

# Clone RocksDB
echo "[3/6] Cloning RocksDB..."
if [ ! -d "$SRC_DIR/rocksdb" ]; then
    git clone --depth 1 https://github.com/facebook/rocksdb.git "$SRC_DIR/rocksdb"
else
    echo "  RocksDB already exists, skipping clone."
fi

# Clone YCSB
echo "[4/6] Cloning YCSB..."
if [ ! -d "$SRC_DIR/ycsb" ]; then
    git clone --depth 1 https://github.com/brianfrankcooper/YCSB.git "$SRC_DIR/ycsb"
else
    echo "  YCSB already exists, skipping clone."
fi

# Build LevelDB
echo "[5/6] Building LevelDB..."
cd "$SRC_DIR/leveldb"
mkdir -p build && cd build; cmake -DCMAKE_BUILD_TYPE=Release .. ; cmake --build . -j$(nproc)

# Build RocksDB with db_bench
echo "[6/6] Building RocksDB..."
cd "$SRC_DIR/rocksdb"
mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release -DWITH_SNAPPY=ON -DWITH_LZ4=ON \
    -DWITH_ZSTD=ON -DWITH_BENCHMARK_TOOLS=ON ..
make -j$(nproc) db_bench

echo ""
echo "=== Setup complete ==="
echo "LevelDB db_bench: $SRC_DIR/leveldb/build/db_bench"
echo "RocksDB db_bench: $SRC_DIR/rocksdb/build/db_bench"
echo "YCSB: $SRC_DIR/ycsb"
echo ""
echo "Next: run ./scripts/build.sh to compile the Grove modifications,"
echo "then ./scripts/run_experiments.sh to reproduce the paper's results."

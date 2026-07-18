# Grove: De-aging by Spawning a Tract of LSM-trees

Reproducing experiments from the APWeb-WAIM 2026 paper by Meng Chen and Chundong Wang (ShanghaiTech University).

## Paper Summary

Grove counteracts LSM-tree aging by maintaining a **tract of small LSM-trees** instead of a single monolithic tree. Only the latest tree is active (accepts writes); older trees become immutable and serve reads only. Per-tree Bloom filters accelerate read operations across the tract.

**Key results (LevelDB, 32M KV pairs):**
- Write throughput: **2.3x improvement**
- Read throughput: **2.0x improvement**
- 99.9P tail latency: **65.1x reduction**

## Prerequisites (Linux)

The paper uses Ubuntu 24.04 with:
- GCC/G++ 13.3.0
- Intel Xeon Gold 6342 CPU, 256GB RAM
- Samsung MZ7LH960 SATA SSD (1TB)

Minimum requirements:
- Ubuntu 20.04+ or compatible Linux
- 16GB+ RAM, 100GB+ free disk space
- GCC/G++ 11+ or Clang 14+

## Quick Start

```bash
# 1. Clone this project to your Linux machine
cd camera-ready

# 2. Install dependencies and clone LevelDB, RocksDB, YCSB
chmod +x scripts/*.sh
./scripts/setup.sh

# 3. Build baseline binaries
./scripts/build.sh

# 4. Run the full experiment suite (takes several hours)
./scripts/run_experiments.sh all
```

## Experiment Coverage

| Section | Experiment | Script |
|---------|-----------|--------|
| 2.2 | Motivational study: aging impact on LevelDB | `run_experiments.sh baseline` |
| 4.2 | Grove write/read/compaction micro-benchmarks | `run_experiments.sh grove` |
| 4.3 | YCSB SessionStore (Workload A) | Included in `all` |
| 4.4 | Sensitivity: Bloom bits, Gamma, value sizes | Included in `all` |

### Individual runs

```bash
# Baseline only (Section 2.2 + 4.2 baseline)
./scripts/run_experiments.sh baseline

# Grove only (requires Grove source modifications)
./scripts/run_experiments.sh grove

# Everything
./scripts/run_experiments.sh all
```

## Grove Implementation Status

The paper describes Grove as **~650 LOC** added to LevelDB. The source code is not publicly available. The Grove design is documented in `src/grove.h` with the following integration points in LevelDB's source:

| File | Modification |
|------|-------------|
| `db/db_impl.h` | Add `GroveTract` member, override Put/Get/Write |
| `db/db_impl.cc` | Implement tract management and routing |
| `db/version_set.h` | Per-tree Bloom filter metadata |
| `include/leveldb/db.h` | Public Grove configuration options |

**Key design decisions to implement:**
1. **Tract**: `std::vector<leveldb::DB*>` holding trees in chronological order
2. **Active tree**: Only `trees_.back()` accepts writes
3. **Gamma condition**: Switch to new tree on first L2→L3 compaction
4. **Per-tree Bloom filter**: 20 bits/key, checked newest→oldest for reads
5. **Async compaction**: Background compactions on immutable trees

## Results Format

Results are saved to `results/` with timestamps. Each file contains raw `db_bench` output. Key metrics:
- **throughput**: ops/sec (extracted by the script)
- **99.9P latency**: microseconds (from histogram output)
- **compaction stats**: data volumes written per level

## Project Structure

```
camera-ready/
├── README.md
├── scripts/
│   ├── setup.sh              # Clone repos, install deps, build baseline
│   ├── build.sh              # Build baseline and Grove variants
│   └── run_experiments.sh    # Run all experiments
├── src/
│   ├── grove.h               # Grove design reference header
│   └── leveldb-grove/        # Placeholder for Grove patches
└── results/                  # Experiment output
```

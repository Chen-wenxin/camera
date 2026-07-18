#ifndef GROVE_LSM_H
#define GROVE_LSM_H
// grove.h ? Core Grove design for de-aging LSM-tree
// Based on: "Grove: De-aging by Spawning a Tract of LSM-trees" (APWeb-WAIM 2026)
//
// This header defines the interface for the Grove extension to LevelDB.
// The full implementation (~650 LOC) integrates into LevelDB as follows:
//
// Integration points in LevelDB source:
//   db/db_impl.h    ? Add GroveTract member, override Put/Get/Write
//   db/db_impl.cc   ? Implement tract management and routing
//   db/version_set.h ? Per-tree Bloom filter metadata
//   include/leveldb/db.h ? Public Grove configuration options
//
// Key design decisions from the paper:
//   1. Maintain a tract of LSM-trees (vector<DB*> trees_)
//   2. Only the latest tree is active (accepts writes)
//   3. Trees become immutable when Gamma condition is met
//   4. Per-tree Bloom filter (20 bits/key default) for read acceleration
//   5. Gamma = first L2?L3 compaction occurrence

#include <vector>
#include <memory>
#include <atomic>
#include <thread>
#include <mutex>

#include "leveldb/db.h"
#include "leveldb/options.h"
#include "leveldb/filter_policy.h"

namespace grove {

// Default Bloom filter bits per key (from Section 4.4)
constexpr int kDefaultBloomBits = 20;

// Condition Gamma: what triggers spawning a new active tree
enum class GammaCondition {
    kFirstL2ToL3Compaction,  // Default (paper Section 3.2)
    kFirstL3ToL4Compaction,
    kStaticSizeThreshold,    // e.g., 100MB, 200MB, 400MB
};

struct GroveOptions {
    GammaCondition gamma = GammaCondition::kFirstL2ToL3Compaction;
    int bloom_bits_per_key = kDefaultBloomBits;
    size_t static_size_threshold_mb = 200;  // Only used if gamma == kStaticSizeThreshold
    bool async_compaction_on_immutable = true;  // Section 3.2
};

// A single tree in the Grove tract
struct GroveTree {
    leveldb::DB* db;
    bool is_active;          // Accepts writes? (only latest tree)
    uint64_t creation_seq;   // Monotonic sequence number
    const leveldb::FilterPolicy* bloom_filter;

    GroveTree() : db(nullptr), is_active(false), creation_seq(0), bloom_filter(nullptr) {}
};

// The Grove tract manager
class GroveTract {
public:
    explicit GroveTract(const GroveOptions& opts);
    ~GroveTract();

    // Write: always goes to active tree (Section 3.3, step 1)
    leveldb::Status Put(const leveldb::WriteOptions& options,
                        const leveldb::Slice& key, const leveldb::Slice& value);

    // Read: search newest to oldest, Bloom filter per tree (Section 3.3, steps 1-5)
    leveldb::Status Get(const leveldb::ReadOptions& options,
                        const leveldb::Slice& key, std::string* value);

    // Delete: same as Put (insert tombstone into active tree)
    leveldb::Status Delete(const leveldb::WriteOptions& options,
                           const leveldb::Slice& key);

    // Check Gamma condition ? called after each compaction
    void OnCompaction(int from_level, int to_level);

    // Background: asynchronous compactions on immutable trees
    void BackgroundCompactionWorker();

private:
    GroveOptions opts_;
    std::vector<GroveTree> trees_;     // Index 0 = oldest, back() = active
    std::mutex mu_;
    std::atomic<uint64_t> next_seq_{0};
    std::unique_ptr<std::thread> bg_worker_;

    // Spawn a new active tree, make current one immutable
    void SpawnNewTree();

    // Find the latest tree whose Bloom filter matches key
    int FindCandidateTree(const leveldb::Slice& key);

    // Check if Gamma condition is met
    bool IsGammaMet(int from_level, int to_level);
};

}  // namespace grove

#endif  // GROVE_LSM_H

// grove_impl.cc ? Implementation skeleton for Grove on LevelDB
// Based on: "Grove: De-aging by Spawning a Tract of LSM-trees" (APWeb-WAIM 2026)
//
// This file shows the core logic for integrating Grove into LevelDB.
// It is NOT a drop-in replacement; it must be woven into LevelDB's
// db_impl.cc, db_impl.h, and version_set.h.
//
// Total expected LOC: ~650 (as stated in the paper, Section 4.1)

#include "grove.h"
#include "leveldb/db.h"
#include "leveldb/options.h"
#include "leveldb/filter_policy.h"
#include "leveldb/write_batch.h"

namespace grove {

// ============================================================
// GroveTract Constructor
// ============================================================
GroveTract::GroveTract(const GroveOptions& opts) : opts_(opts) {
    // Create the initial blank active tree
    SpawnNewTree();

    // Start background compaction worker for immutable trees
    if (opts_.async_compaction_on_immutable) {
        bg_worker_ = std::make_unique<std::thread>(
            &GroveTract::BackgroundCompactionWorker, this);
    }
}

GroveTract::~GroveTract() {
    // Close all trees
    for (auto& tree : trees_) {
        if (tree.bloom_filter) delete tree.bloom_filter;
        if (tree.db) delete tree.db;
    }
}

// ============================================================
// SpawnNewTree: create a blank active tree, make current one immutable
// (Section 3.2, last paragraph: "asynchronously creates a new one")
// ============================================================
void GroveTract::SpawnNewTree() {
    std::lock_guard<std::mutex> lock(mu_);

    // Mark current active tree as immutable
    if (!trees_.empty()) {
        trees_.back().is_active = false;
    }

    // Create fresh LevelDB instance
    leveldb::Options options;
    options.create_if_missing = true;
    options.filter_policy = leveldb::NewBloomFilterPolicy(opts_.bloom_bits_per_key);
    // ... other options ...

    GroveTree new_tree;
    new_tree.is_active = true;
    new_tree.creation_seq = next_seq_++;
    new_tree.bloom_filter = options.filter_policy;

    // Open new DB at a unique path
    std::string db_path = "/tmp/grove_tree_" + std::to_string(new_tree.creation_seq);
    leveldb::Status s = leveldb::DB::Open(options, db_path, &new_tree.db);

    trees_.push_back(new_tree);
}

// ============================================================
// Put: always goes to the active (latest) tree
// (Section 3.3, Write: step 1 in Figure 3)
// ============================================================
leveldb::Status GroveTract::Put(const leveldb::WriteOptions& options,
                                 const leveldb::Slice& key,
                                 const leveldb::Slice& value) {
    std::lock_guard<std::mutex> lock(mu_);
    GroveTree& active = trees_.back();
    return active.db->Put(options, key, value);
}

// ============================================================
// Get: search newest to oldest, Bloom filter per tree
// (Section 3.3, Read: steps 1-5 in Figure 3)
// ============================================================
leveldb::Status GroveTract::Get(const leveldb::ReadOptions& options,
                                 const leveldb::Slice& key,
                                 std::string* value) {
    std::lock_guard<std::mutex> lock(mu_);

    // Search from newest (active) to oldest (immutable)
    for (auto it = trees_.rbegin(); it != trees_.rend(); ++it) {
        // Step 1: Check per-tree Bloom filter
        // (The filter is internal to LevelDB's filter_policy;
        //  LevelDB handles this automatically on Get calls)

        // Step 2: Search within tree
        leveldb::Status s = it->db->Get(options, key, value);

        if (s.ok()) {
            // Found in this tree (could be a false positive from Bloom)
            return s;
        }
        // Step 3+5: Not found, continue to next (older) tree
    }

    return leveldb::Status::NotFound(leveldb::Slice());
}

// ============================================================
// Delete: insert tombstone into active tree
// (Section 3.3, last paragraph: "updates and deletions naturally
//  propagate... searching from newer to older rules out obsolete data")
// ============================================================
leveldb::Status GroveTract::Delete(const leveldb::WriteOptions& options,
                                    const leveldb::Slice& key) {
    std::lock_guard<std::mutex> lock(mu_);
    GroveTree& active = trees_.back();
    return active.db->Delete(options, key);
}

// ============================================================
// OnCompaction: called after each compaction to check Gamma
// (Section 3.2: "flag up Gamma when the first L2->L3 compaction occurs")
// ============================================================
void GroveTract::OnCompaction(int from_level, int to_level) {
    if (IsGammaMet(from_level, to_level)) {
        // Asynchronously spawn new tree (Section 3.2: avoid blocking
        // the write on the critical path)
        // In practice, signal a background thread
        SpawnNewTree();
    }
}

bool GroveTract::IsGammaMet(int from_level, int to_level) {
    switch (opts_.gamma) {
        case GammaCondition::kFirstL2ToL3Compaction:
            return (from_level == 2 && to_level == 3);
        case GammaCondition::kFirstL3ToL4Compaction:
            return (from_level == 3 && to_level == 4);
        case GammaCondition::kStaticSizeThreshold:
            // Check approximate DB size
            // (Simplified; real impl would use ApproximateSizes)
            return false;
        default:
            return false;
    }
}

// ============================================================
// BackgroundCompactionWorker: async compactions on immutable trees
// (Section 3.2: "Grove asynchronously calls for compactions to drive
//  top-level SSTables to be merged into deep levels")
// ============================================================
void GroveTract::BackgroundCompactionWorker() {
    while (true) {
        // Find an immutable tree that needs compaction
        std::vector<GroveTree> snapshot;
        {
            std::lock_guard<std::mutex> lock(mu_);
            snapshot = trees_;
        }

        for (auto& tree : snapshot) {
            if (!tree.is_active && tree.db != nullptr) {
                tree.db->CompactRange(nullptr, nullptr);
            }
        }

        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
}

}  // namespace grove

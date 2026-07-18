// adaptive_gamma.h ? Runtime-adaptive Gamma strategy for Grove
// ===================================================================
// Extension to Grove (APWeb-WAIM 2026) for higher-tier venues.
//
// Instead of a hardcoded Gamma (first L2?L3 compaction), this module
// monitors compaction cost gradients online and triggers tree resets
// when the marginal compaction cost exceeds a dynamic threshold.
//
// Key insight (Section 2 of the extension):
//   The marginal cost of compaction d(cost)/d(N) grows non-linearly
//   with tree size. The optimal reset point is when this marginal
//   cost exceeds the amortized cost of starting a new tree.
//
// Two modes:
//   1. Gradient-based: monitor d(cost)/d(N) and reset on threshold
//   2. EMA-based: exponential moving average of per-write cost

#ifndef ADAPTIVE_GAMMA_H
#define ADAPTIVE_GAMMA_H

#include <cstdint>
#include <deque>
#include <vector>
#include <atomic>
#include <mutex>

namespace grove {

// Statistics collected per compaction event
struct CompactionStats {
    int from_level;
    int to_level;
    uint64_t bytes_written;      // Total bytes written in this compaction
    uint64_t bytes_read;         // Total bytes read
    uint64_t elapsed_us;         // Duration in microseconds
    uint64_t tree_total_size;    // Current tree size in bytes at compaction time
};

// Adaptive Gamma configuration
struct AdaptiveGammaConfig {
    // Gradient mode settings
    size_t gradient_window = 10;        // Number of compaction events to track
    double threshold_factor = 2.0;      // Trigger when d(cost)/d(N) > baseline * factor
    
    // EMA mode settings
    double ema_alpha = 0.1;            // Smoothing factor (0 = slow, 1 = instant)
    double ema_threshold_factor = 3.0;  // Trigger when EMA > baseline * factor
    
    // Guardrails
    uint64_t min_tree_size_bytes = 64ULL * 1024 * 1024;   // 64MB ? don't reset below
    uint64_t max_tree_size_bytes = 16ULL * 1024 * 1024 * 1024; // 16GB ? force reset
    
    // Mode selection
    enum class Mode { kGradient, kEMA, kHybrid };
    Mode mode = Mode::kGradient;
};

class AdaptiveGamma {
public:
    explicit AdaptiveGamma(const AdaptiveGammaConfig& config);
    
    // Called after each compaction completes.
    // Returns true if a new tree should be spawned.
    bool OnCompaction(const CompactionStats& stats);
    
    // Get statistics for evaluation
    struct Diagnostics {
        double current_marginal_cost;  // d(cost)/d(N) in bytes/byte
        double baseline_marginal_cost;
        double ema_cost;
        uint64_t trees_spawned;
        std::vector<uint64_t> reset_sizes;  // Tree sizes at reset points (bytes)
    };
    Diagnostics GetDiagnostics() const;
    
    // Reset state for a new tree
    void OnTreeReset();
    
private:
    AdaptiveGammaConfig config_;
    mutable std::mutex mu_;
    
    // Gradient tracking
    std::deque<std::pair<uint64_t, uint64_t>> gradient_history_;  // (tree_size, cumulative_cost)
    double baseline_marginal_cost_ = -1.0;
    
    // EMA tracking
    double ema_cost_per_op_ = 0.0;
    double ema_baseline_ = -1.0;
    uint64_t ops_in_tree_ = 0;
    
    // Aggregate stats
    uint64_t trees_spawned_ = 0;
    std::vector<uint64_t> reset_sizes_;
    uint64_t current_cumulative_cost_ = 0;
    
    double ComputeMarginalCost() const;
    bool ShouldReset(uint64_t tree_size);
};

}  // namespace grove

#endif  // ADAPTIVE_GAMMA_H

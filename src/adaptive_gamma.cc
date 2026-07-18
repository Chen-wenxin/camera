// adaptive_gamma.cc ? Implementation of runtime-adaptive Gamma
// ===================================================================

#include "adaptive_gamma.h"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace grove {

AdaptiveGamma::AdaptiveGamma(const AdaptiveGammaConfig& config)
    : config_(config) {}

bool AdaptiveGamma::OnCompaction(const CompactionStats& stats) {
    std::lock_guard<std::mutex> lock(mu_);
    
    ops_in_tree_++;
    current_cumulative_cost_ += stats.bytes_written;
    
    // Add to gradient window
    gradient_history_.push_back({stats.tree_total_size, current_cumulative_cost_});
    if (gradient_history_.size() > config_.gradient_window) {
        gradient_history_.pop_front();
    }
    
    // Update EMA of per-operation cost
    double per_op_cost = static_cast<double>(stats.bytes_written);  // simplified
    if (ema_cost_per_op_ == 0.0) {
        ema_cost_per_op_ = per_op_cost;
    } else {
        ema_cost_per_op_ = config_.ema_alpha * per_op_cost + 
                           (1.0 - config_.ema_alpha) * ema_cost_per_op_;
    }
    
    // Initialize baselines
    if (ops_in_tree_ == static_cast<uint64_t>(config_.gradient_window)) {
        // Warm-up complete ? set baseline
        baseline_marginal_cost_ = ComputeMarginalCost();
        ema_baseline_ = ema_cost_per_op_;
    }
    
    return ShouldReset(stats.tree_total_size);
}

double AdaptiveGamma::ComputeMarginalCost() const {
    if (gradient_history_.size() < 2) return 0.0;
    
    auto& first = gradient_history_.front();
    auto& last = gradient_history_.back();
    
    uint64_t delta_size = last.first - first.first;
    uint64_t delta_cost = last.second - first.second;
    
    if (delta_size == 0) return 0.0;
    return static_cast<double>(delta_cost) / static_cast<double>(delta_size);
}

bool AdaptiveGamma::ShouldReset(uint64_t tree_size) {
    // Guardrail: never reset below minimum
    if (tree_size < config_.min_tree_size_bytes) {
        return false;
    }
    
    // Guardrail: always reset above maximum
    if (tree_size > config_.max_tree_size_bytes) {
        OnTreeReset();
        return true;
    }
    
    // Need sufficient history for decisions
    if (baseline_marginal_cost_ < 0) {
        return false;
    }
    
    bool should_reset = false;
    
    switch (config_.mode) {
        case AdaptiveGammaConfig::Mode::kGradient: {
            double marginal = ComputeMarginalCost();
            if (marginal > baseline_marginal_cost_ * config_.threshold_factor) {
                should_reset = true;
            }
            break;
        }
        case AdaptiveGammaConfig::Mode::kEMA: {
            if (ema_cost_per_op_ > ema_baseline_ * config_.ema_threshold_factor) {
                should_reset = true;
            }
            break;
        }
        case AdaptiveGammaConfig::Mode::kHybrid: {
            double marginal = ComputeMarginalCost();
            bool gradient_trigger = marginal > baseline_marginal_cost_ * config_.threshold_factor;
            bool ema_trigger = ema_cost_per_op_ > ema_baseline_ * config_.ema_threshold_factor;
            should_reset = gradient_trigger && ema_trigger;  // Both must agree
            break;
        }
    }
    
    if (should_reset) {
        OnTreeReset();
    }
    
    return should_reset;
}

void AdaptiveGamma::OnTreeReset() {
    trees_spawned_++;
    reset_sizes_.push_back(gradient_history_.empty() ? 0 : gradient_history_.back().first);
    gradient_history_.clear();
    current_cumulative_cost_ = 0;
    ema_cost_per_op_ = 0.0;
    baseline_marginal_cost_ = -1.0;
    ema_baseline_ = -1.0;
    ops_in_tree_ = 0;
}

AdaptiveGamma::Diagnostics AdaptiveGamma::GetDiagnostics() const {
    std::lock_guard<std::mutex> lock(mu_);
    Diagnostics d;
    d.current_marginal_cost = ComputeMarginalCost();
    d.baseline_marginal_cost = baseline_marginal_cost_;
    d.ema_cost = ema_cost_per_op_;
    d.trees_spawned = trees_spawned_;
    d.reset_sizes = reset_sizes_;
    return d;
}

}  // namespace grove

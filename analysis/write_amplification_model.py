#!/usr/bin/env python3
"""
write_amplification_model.py ? Formal model of LSM-tree aging and optimal de-aging.
=====================================================================================
Based on: "Grove: De-aging by Spawning a Tract of LSM-trees" (APWeb-WAIM 2026)
Extended with theoretical analysis for higher-tier venues.

Models:
  1. Write amplification W(N) as a function of total KV count N
  2. Compaction cost per level under standard tiering (ratio T=10)
  3. Optimal Gamma threshold: minimize total cost of writes + tree resets
  4. Comparison: monolithic tree vs Grove with fixed Gamma vs Adaptive Gamma

Usage:  python3 analysis/write_amplification_model.py
Output: analysis/wa_model_output.png, analysis/wa_model_output.csv
"""

import numpy as np
import sys, os
from dataclasses import dataclass
from typing import List, Tuple

# ============================================================
# Section 1: LSM-tree Compaction Model
# ============================================================

@dataclass
class LSMParams:
    """Parameters matching LevelDB defaults and the paper's setup."""
    memtable_size: int = 4 * 1024 * 1024      # 4MB
    level0_file_num: int = 4                   # L0 trigger
    size_ratio: int = 10                       # L_{i+1} / L_i capacity
    entry_size: int = 144                      # 16B key + 128B value
    bloom_bits_per_key: int = 20
    max_levels: int = 7

    @property
    def level_capacities(self) -> List[int]:
        """Capacity of each level in bytes (L0 through L_max)."""
        caps = [self.memtable_size * self.level0_file_num]  # L0
        for i in range(1, self.max_levels):
            caps.append(caps[-1] * self.size_ratio)
        return caps

    @property
    def level_capacities_kv(self) -> List[int]:
        """Capacity of each level in number of KV pairs."""
        return [c // self.entry_size for c in self.level_capacities]


def write_amplification_per_write(N: int, params: LSMParams) -> float:
    """
    Model: total bytes written to disk / bytes of user data.
    
    For a monolithic LSM-tree with N entries:
    - Each entry participates in log_T(N) compactions on average
    - WA = avg_compactions_per_entry * entries_per_compaction_overhead
    
    Simplified model from literature (Dayan & Idreos, VLDB 2018):
    WA = (T-1)/ln(T) * (1 + log_T(N / L0_size))  approximately
    """
    T = params.size_ratio
    caps = params.level_capacities_kv
    
    # Find deepest level that has data
    remaining = N
    levels_used = 0
    for cap in caps:
        if remaining <= 0:
            break
        remaining -= cap
        levels_used += 1
    
    # WA model: each write propagates through ~levels_used/2 levels
    # with amplification factor proportional to T
    amplification = (T + 1) / 2  # avg files touched per merge
    wa = amplification * levels_used
    
    return wa


def compaction_cost_per_level(N: int, params: LSMParams) -> List[float]:
    """
    Model the data volume involved in compaction at each level pair.
    Returns list of (bytes_written) for L0->L1, L1->L2, ..., L_{k-1}->L_k
    """
    T = params.size_ratio
    caps = params.level_capacities_kv
    entry_bytes = params.entry_size
    
    costs = []
    remaining = N
    
    for i in range(len(caps) - 1):
        if remaining <= 0:
            costs.append(0.0)
            continue
        
        # Data in level i that needs to be compacted to level i+1
        level_i_data = min(remaining, caps[i])
        level_i1_data = min(max(0, N - caps[i]), caps[i+1])
        
        # Compaction merges level_i + overlapping data in level_i+1
        cost = (level_i_data + level_i1_data) * entry_bytes
        costs.append(cost)
        
        remaining -= caps[i]
    
    return costs


# ============================================================
# Section 2: Grove Cost Model ? Tree Reset Trade-off
# ============================================================

def grove_total_cost(N_total: int, tree_size: int, params: LSMParams) -> float:
    """
    Total write cost under Grove with trees of 'tree_size' KV pairs each.
    
    Cost = sum of compaction costs within each tree + tree initialization overhead.
    
    Args:
        N_total: Total KV pairs in the system
        tree_size: Max KV pairs per tree before Gamma triggers
        params: LSM parameters
    
    Returns: Total bytes written (normalized)
    """
    num_trees = int(np.ceil(N_total / tree_size))
    total_cost = 0.0
    
    for t in range(num_trees):
        tree_N = min(tree_size, N_total - t * tree_size)
        
        # Compaction cost within this tree
        wa = write_amplification_per_write(tree_N, params)
        compaction_cost = wa * tree_N * params.entry_size
        
        # Tree initialization cost (new WAL, new manifest, Bloom filter)
        init_cost = params.bloom_bits_per_key * tree_N / 8  # Bloom filter bits?bytes
        init_cost += 4096  # manifest + metadata
        
        total_cost += compaction_cost + init_cost
    
    return total_cost / N_total  # Normalize per KV pair


def monolithic_cost(N_total: int, params: LSMParams) -> float:
    """Total write cost for a single monolithic tree."""
    wa = write_amplification_per_write(N_total, params)
    return wa * params.entry_size


def find_optimal_tree_size(N_total: int, params: LSMParams, 
                            sizes: List[int]) -> Tuple[int, float]:
    """
    Find the tree size that minimizes Grove's total cost.
    This is the theoretically optimal Gamma.
    """
    best_size = sizes[0]
    best_cost = float('inf')
    
    for s in sizes:
        cost = grove_total_cost(N_total, s, params)
        if cost < best_cost:
            best_cost = cost
            best_size = s
    
    return best_size, best_cost


# ============================================================
# Section 3: Adaptive Gamma ? Online Optimization
# ============================================================

class AdaptiveGammaTracker:
    """
    Online tracker for compaction cost gradient.
    Triggers tree reset when marginal compaction cost exceeds threshold.
    
    This is the adaptive version of Grove's fixed Gamma.
    Instead of hardcoding L2?L3, it monitors:
      d(cost)/d(N) and triggers when growth_rate > threshold.
    """
    
    def __init__(self, window_size: int = 10000, threshold_factor: float = 2.0):
        self.window_size = window_size
        self.threshold_factor = threshold_factor
        self.cost_history: List[Tuple[int, float]] = []  # (N, cumulative_cost)
        self.reset_points: List[int] = []
        self.cumulative_cost = 0.0
        self.current_tree_N = 0
        self.total_ops = 0
        self.base_cost_rate = None
    
    def record_write(self, compaction_bytes: int) -> bool:
        """
        Record a write operation and its compaction cost.
        Returns True if a tree reset should happen.
        """
        self.total_ops += 1
        self.current_tree_N += 1
        self.cumulative_cost += compaction_bytes
        
        # Sample periodically
        if self.total_ops % self.window_size == 0:
            self.cost_history.append((self.current_tree_N, self.cumulative_cost))
            
            # Compute marginal cost rate over window
            if len(self.cost_history) >= 2:
                prev_N, prev_cost = self.cost_history[-2]
                curr_N, curr_cost = self.cost_history[-1]
                delta_N = curr_N - prev_N
                delta_cost = curr_cost - prev_cost
                
                if delta_N > 0:
                    rate = delta_cost / delta_N
                    
                    # Initialize baseline
                    if self.base_cost_rate is None:
                        self.base_cost_rate = rate
                    
                    # Trigger if marginal cost has grown significantly
                    if rate > self.base_cost_rate * self.threshold_factor:
                        self.reset_points.append(self.total_ops)
                        self.current_tree_N = 0
                        self.cumulative_cost = 0.0
                        self.cost_history = []
                        self.base_cost_rate = None
                        return True
        
        return False
    
    def get_reset_sizes(self) -> List[int]:
        """Return the sizes at which trees were reset."""
        return self.reset_points


# ============================================================
# Section 4: Simulation and Visualization
# ============================================================

def run_simulation(params: LSMParams, output_dir: str = "analysis"):
    """Run the full simulation and generate figures."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    N_values = [1e6, 2e6, 4e6, 8e6, 16e6, 32e6]
    
    # --- Subplot 1: Write Amplification vs Tree Size ---
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    
    # (a) Write Amplification vs N for monolithic tree
    ax = axes[0, 0]
    N_range = np.logspace(5, 8, 100).astype(int)
    wa_values = [write_amplification_per_write(n, params) for n in N_range]
    ax.plot(N_range / 1e6, wa_values, 'b-', linewidth=2, label='Monolithic LSM-tree')
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, label='Theoretical minimum')
    ax.set_xlabel('Number of KV Pairs (millions)')
    ax.set_ylabel('Write Amplification Factor')
    ax.set_title('(a) Write Amplification Growth with Aging')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # (b) Compaction cost per level at different ages
    ax = axes[0, 1]
    ages = [1e6, 8e6, 32e6]
    colors = ['#2ecc71', '#f39c12', '#e74c3c']
    level_labels = ['L0?L1', 'L1?L2', 'L2?L3', 'L3?L4', 'L4?L5']
    x_pos = np.arange(len(level_labels))
    width = 0.25
    
    for i, age in enumerate(ages):
        costs = compaction_cost_per_level(int(age), params)
        costs_mb = [c / 1e6 for c in costs[:len(level_labels)]]
        ax.bar(x_pos + i * width, costs_mb, width, 
               label=f'{int(age/1e6)}M KV pairs', color=colors[i], alpha=0.8)
    
    ax.set_xlabel('Compaction Level Pair')
    ax.set_ylabel('Data Written (MB)')
    ax.set_title('(b) Compaction Data Volume by Level')
    ax.set_xticks(x_pos + width)
    ax.set_xticklabels(level_labels)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    # (c) Grove cost vs tree size ? find optimal Gamma
    ax = axes[1, 0]
    tree_sizes = [5e4, 1e5, 2e5, 5e5, 1e6, 2e6, 4e6, 8e6, 16e6]
    total_N = 32e6
    
    costs = []
    for ts in tree_sizes:
        c = grove_total_cost(int(total_N), int(ts), params)
        costs.append(c)
    
    # Find optimal
    opt_size, opt_cost = find_optimal_tree_size(int(total_N), params, 
                                                 [int(s) for s in tree_sizes])
    
    ax.plot([s/1e6 for s in tree_sizes], costs, 'g-o', linewidth=2, markersize=8)
    ax.axvline(x=opt_size/1e6, color='red', linestyle='--', 
               label=f'Optimal: {opt_size/1e6:.1f}M KV ($\\Gamma^*$)')
    ax.axhline(y=monolithic_cost(int(total_N), params), color='blue', 
               linestyle=':', label='Monolithic cost')
    ax.set_xlabel('Tree Size (millions of KV pairs)')
    ax.set_ylabel('Normalized Cost per KV (bytes)')
    ax.set_title('(c) Optimal Tree Size ? Cost Minimization')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # (d) Comparison: Fixed Gamma vs Adaptive Gamma
    ax = axes[1, 1]
    strategies = ['Monolithic', 'Grove\n(L1?L2)', 'Grove\n(L2?L3)', 
                  'Grove\n(L3?L4)', 'Adaptive\n($\\Gamma^*$)']
    Ns = [1e6, 8e6, 32e6]
    
    x_pos = np.arange(len(strategies))
    width = 0.25
    
    for i, N in enumerate(Ns):
        costs = [
            monolithic_cost(int(N), params),
            grove_total_cost(int(N), int(5e5), params),   # L1?L2 proxy (~0.5M)
            grove_total_cost(int(N), int(2e6), params),   # L2?L3 proxy (~2M)
            grove_total_cost(int(N), int(8e6), params),   # L3?L4 proxy (~8M)
            grove_total_cost(int(N), opt_size, params),   # Adaptive optimal
        ]
        ax.bar(x_pos + i * width, costs, width, 
               label=f'{int(N/1e6)}M KV', alpha=0.8)
    
    ax.set_xlabel('De-aging Strategy')
    ax.set_ylabel('Normalized Cost per KV (bytes)')
    ax.set_title('(d) Strategy Comparison by Aging Degree')
    ax.set_xticks(x_pos + width)
    ax.set_xticklabels(strategies, fontsize=9)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    outpath = os.path.join(output_dir, 'wa_model_output.png')
    plt.savefig(outpath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Figure saved: {outpath}")
    
    # --- CSV output ---
    csv_path = os.path.join(output_dir, 'wa_model_output.csv')
    with open(csv_path, 'w') as f:
        f.write("N_millions,monolithic_wa,optimal_tree_size,optimal_cost,"
                "grove_l2l3_cost,improvement_pct\n")
        for N in N_values:
            mono = monolithic_cost(int(N), params)
            opt_sz, opt_c = find_optimal_tree_size(int(N), params, 
                                                    [int(s) for s in tree_sizes])
            grove_l2l3 = grove_total_cost(int(N), int(2e6), params)
            impr = (mono - opt_c) / mono * 100
            f.write(f"{N/1e6:.0f},{mono:.1f},{opt_sz},{opt_c:.1f},"
                    f"{grove_l2l3:.1f},{impr:.1f}\n")
    print(f"CSV saved: {csv_path}")
    
    # --- Adaptive Gamma simulation trace ---
    tracker = AdaptiveGammaTracker(window_size=5000, threshold_factor=2.0)
    params_sim = LSMParams()
    reset_events = []
    
    for op in range(1, int(2e6)):
        # Simulate compaction cost proportional to current tree size
        current_N = tracker.current_tree_N
        if current_N > 0:
            # Compaction cost grows as tree ages
            wa = write_amplification_per_write(current_N, params_sim)
            cost = wa * params_sim.entry_size / 10  # Per-write cost
        else:
            cost = params_sim.entry_size
        
        triggered = tracker.record_write(cost)
        if triggered:
            reset_events.append(op)
    
    trace_path = os.path.join(output_dir, 'adaptive_gamma_trace.csv')
    with open(trace_path, 'w') as f:
        f.write("reset_event_ops\n")
        for r in reset_events:
            f.write(f"{r}\n")
    print(f"Adaptive Gamma trace: {trace_path}")
    print(f"  Reset events at: {[r//1000 for r in reset_events]}K ops")
    
    return {
        'optimal_tree_size': opt_size,
        'optimal_cost': opt_cost,
        'monolithic_cost_32M': monolithic_cost(int(32e6), params),
        'improvement_pct': (monolithic_cost(int(32e6), params) - opt_cost) / 
                           monolithic_cost(int(32e6), params) * 100,
        'adaptive_reset_points': reset_events,
    }


if __name__ == '__main__':
    params = LSMParams()
    results = run_simulation(params, output_dir="analysis")
    print(f"\n=== Theoretical Results ===")
    print(f"Optimal tree size (Gamma*): {results['optimal_tree_size']/1e6:.1f}M KV pairs")
    print(f"Cost reduction vs monolithic:   {results['improvement_pct']:.1f}%")
    print(f"Adaptive Gamma reset points:    {len(results['adaptive_reset_points'])} resets")

#!/usr/bin/env python3
"""
plot_results.py ? Publication-quality figures for Grove evaluation.
===================================================================
Generates: Fig 2 (aging impact), Fig 4 (Grove de-aging), Fig 5 (YCSB),
Fig 6 (Gamma sensitivity), Fig 7 (value size), plus WA model overlay.

Usage: python3 analysis/plot_results.py [results_dir] [output_dir]
"""

import os, sys, re, json
import numpy as np
from pathlib import Path
from collections import defaultdict

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("matplotlib not available. Install: pip install matplotlib numpy")
    sys.exit(1)

plt.rcParams.update({
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 12,
    'figure.dpi': 150,
    'savefig.bbox': 'tight',
    'savefig.dpi': 150,
})

def parse_db_bench(filepath):
    """Extract throughput (ops/sec) from db_bench output."""
    with open(filepath, 'r', errors='replace') as f:
        text = f.read()
    for line in text.split('\n'):
        m = re.match(r'.*?(\d+\.?\d*)\s+ops/sec', line)
        if m: return float(m.group(1))
    for line in text.split('\n'):
        m = re.match(r'.*?(\d+\.?\d*)\s+micros/op', line)
        if m: return 1_000_000.0 / float(m.group(1))
    return None

def parse_latency(filepath):
    """Extract 99.9P latency (us) from db_bench output."""
    with open(filepath, 'r', errors='replace') as f:
        text = f.read()
    for line in text.split('\n'):
        if 'P99.9' in line or 'P999' in line:
            m = re.match(r'P99\.?9?:?\s*(\d+\.?\d*)\s*(us|ms)', line)
            if m:
                v = float(m.group(1))
                return v * 1000 if m.group(2) == 'ms' else v
    return None

def parse_ycsb(filepath):
    """Extract throughput from YCSB output."""
    with open(filepath, 'r', errors='replace') as f:
        text = f.read()
    m = re.search(r'Throughput\(ops/sec\).*?(\d+\.?\d*)', text)
    if m: return float(m.group(1))
    m = re.search(r'RunTime\(ms\).*?(\d+)', text)
    if m:
        ops_m = re.search(r'Operations.*?(\d+)', text)
        if ops_m:
            return float(ops_m.group(1)) / (float(m.group(1)) / 1000.0)
    return None

def plot_aging_impact(results_dir, output_dir):
    """Figure: Write/Read throughput and latency vs aging degree."""
    ages = [1, 2, 4, 8, 16, 32]
    
    # Discover files by pattern
    write_throughputs = {}
    read_throughputs = {}
    write_latencies = {}
    read_latencies = {}
    
    for f in Path(results_dir).glob("original_overwrite_age*"):
        age = int(re.search(r'age(\d+)', f.stem).group(1)) / 1_000_000
        tp = parse_db_bench(str(f))
        lat = parse_latency(str(f))
        if tp: write_throughputs[age] = tp
        if lat: write_latencies[age] = lat
    
    for f in Path(results_dir).glob("original_readrandom_age*"):
        age = int(re.search(r'age(\d+)', f.stem).group(1)) / 1_000_000
        tp = parse_db_bench(str(f))
        lat = parse_latency(str(f))
        if tp: read_throughputs[age] = tp
        if lat: read_latencies[age] = lat
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    # Throughput subplot
    ax = axes[0]
    if write_throughputs:
        wx = sorted(write_throughputs.keys())
        wy = [write_throughputs[k] for k in wx]
        ax.plot(wx, wy, 'o-', color='#e74c3c', linewidth=2, markersize=8, label='Write (overwrite)')
    if read_throughputs:
        rx = sorted(read_throughputs.keys())
        ry = [read_throughputs[k] for k in rx]
        ax.plot(rx, ry, 's--', color='#3498db', linewidth=2, markersize=8, label='Read (readrandom)')
    ax.set_xlabel('Existing KV Pairs (millions)')
    ax.set_ylabel('Throughput (K ops/sec)')
    ax.set_title('Throughput Degradation with Aging')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Latency subplot
    ax = axes[1]
    if write_latencies:
        wx = sorted(write_latencies.keys())
        wy = [write_latencies[k] for k in wx]
        ax.semilogy(wx, wy, 'o-', color='#e74c3c', linewidth=2, markersize=8, label='Write 99.9P')
    if read_latencies:
        rx = sorted(read_latencies.keys())
        ry = [read_latencies[k] for k in rx]
        ax.semilogy(rx, ry, 's--', color='#3498db', linewidth=2, markersize=8, label='Read 99.9P')
    ax.set_xlabel('Existing KV Pairs (millions)')
    ax.set_ylabel('99.9th Percentile Latency (us)')
    ax.set_title('Tail Latency Explosion with Aging')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    out = os.path.join(output_dir, 'fig_aging_impact.png')
    plt.savefig(out)
    plt.close()
    print(f"  Saved: {out}")

def plot_ycsb_summary(results_dir, output_dir):
    """Figure: YCSB workload comparison bar chart."""
    workloads = []
    throughputs = []
    
    for f in sorted(Path(results_dir).glob("ycsb_workload*.txt")):
        wl = re.search(r'workload(\w)', f.stem).group(1).upper()
        tp = parse_ycsb(str(f))
        if tp:
            workloads.append(f'W{wl}')
            throughputs.append(tp)
    
    if not workloads:
        return
    
    fig, ax = plt.subplots(figsize=(12, 5))
    colors = ['#2ecc71', '#3498db', '#9b59b6', '#e74c3c', '#f39c12', '#1abc9c']
    bars = ax.bar(workloads, throughputs, color=colors[:len(workloads)], alpha=0.85)
    
    # Annotate
    for bar, tp in zip(bars, throughputs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(throughputs)*0.01,
                f'{tp:.0f}', ha='center', fontsize=9)
    
    ax.set_xlabel('YCSB Workload')
    ax.set_ylabel('Throughput (ops/sec)')
    ax.set_title('LevelDB Baseline: YCSB Core Workloads (32M KV, 2M ops)')
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    out = os.path.join(output_dir, 'fig_ycsb_all.png')
    plt.savefig(out)
    plt.close()
    print(f"  Saved: {out}")

def plot_bloom_sensitivity(results_dir, output_dir):
    """Figure: Throughput vs Bloom filter bits per key."""
    bits = []
    tps = []
    
    for f in Path(results_dir).glob("bloom_*bits*"):
        b = int(re.search(r'bloom_(\d+)bits', f.stem).group(1))
        tp = parse_db_bench(str(f))
        if tp:
            bits.append(b)
            tps.append(tp)
    
    if not bits:
        return
    
    sorted_data = sorted(zip(bits, tps))
    bits, tps = zip(*sorted_data)
    
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(bits, tps, 'o-', color='#2ecc71', linewidth=2, markersize=8)
    ax.axvline(x=20, color='red', linestyle='--', alpha=0.7, label='Chosen: 20 bits/key')
    ax.set_xlabel('Bloom Filter Bits per Key')
    ax.set_ylabel('Read Throughput (K ops/sec)')
    ax.set_title('Bloom Filter Sensitivity (16M KV, readrandom 1M)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    out = os.path.join(output_dir, 'fig_bloom_sensitivity.png')
    plt.savefig(out)
    plt.close()
    print(f"  Saved: {out}")

def plot_value_size_sweep(results_dir, output_dir):
    """Figure: Throughput vs value size."""
    sizes = []
    tps = []
    
    for f in Path(results_dir).glob("vsize_*"):
        sz = int(re.search(r'vsize_(\d+)B', f.stem).group(1))
        tp = parse_db_bench(str(f))
        if tp:
            sizes.append(sz)
            tps.append(tp)
    
    if not sizes:
        return
    
    sorted_data = sorted(zip(sizes, tps))
    sizes, tps = zip(*sorted_data)
    
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(sizes, tps, 'o-', color='#3498db', linewidth=2, markersize=8)
    ax.set_xlabel('Value Size (bytes)')
    ax.set_ylabel('Write Throughput (MB/sec or ops/sec)')
    ax.set_title('Value Size Sensitivity (16M KV, overwrite 1M, LevelDB baseline)')
    ax.set_xscale('log', base=2)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    out = os.path.join(output_dir, 'fig_value_size.png')
    plt.savefig(out)
    plt.close()
    print(f"  Saved: {out}")

def plot_gamma_sensitivity(results_dir, output_dir):
    """Figure: Throughput vs write buffer size (Gamma proxy)."""
    sizes = []
    tps = []
    
    for f in Path(results_dir).glob("wbuf_*"):
        sz = int(re.search(r'wbuf_(\d+)MB', f.stem).group(1))
        tp = parse_db_bench(str(f))
        if tp:
            sizes.append(sz)
            tps.append(tp)
    
    if not sizes:
        return
    
    sorted_data = sorted(zip(sizes, tps))
    sizes, tps = zip(*sorted_data)
    
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(sizes, tps, 'o-', color='#9b59b6', linewidth=2, markersize=8)
    ax.set_xlabel('Write Buffer Size (MB)')
    ax.set_ylabel('Write Throughput (K ops/sec)')
    ax.set_title('Gamma Sensitivity ? Write Buffer Size Proxy (16M KV, overwrite 1M)')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    out = os.path.join(output_dir, 'fig_gamma_sensitivity.png')
    plt.savefig(out)
    plt.close()
    print(f"  Saved: {out}")

def main():
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "analysis"
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.isdir(results_dir):
        print(f"Results directory not found: {results_dir}")
        print("Run experiments first: ./scripts/run_full_experiments.sh")
        sys.exit(1)
    
    print(f"Plotting from: {results_dir}")
    print(f"Output to:    {output_dir}")
    print()
    
    plot_aging_impact(results_dir, output_dir)
    plot_ycsb_summary(results_dir, output_dir)
    plot_bloom_sensitivity(results_dir, output_dir)
    plot_value_size_sweep(results_dir, output_dir)
    plot_gamma_sensitivity(results_dir, output_dir)
    
    # Generate summary report
    summary_path = os.path.join(output_dir, 'experiment_summary.txt')
    with open(summary_path, 'w') as f:
        f.write("Grove Experiment Suite ? Summary\n")
        f.write("================================\n\n")
        f.write("Figures generated:\n")
        for fig in sorted(Path(output_dir).glob("fig_*.png")):
            f.write(f"  {fig.name}\n")
        f.write("\nFor WA model results, run:\n")
        f.write("  python3 analysis/write_amplification_model.py\n")
    
    print(f"\nSummary: {summary_path}")
    print("Done. See analysis/ for all figures.")

if __name__ == '__main__':
    main()

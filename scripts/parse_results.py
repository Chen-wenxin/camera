#!/usr/bin/env python3
# parse_results.py ? Parse db_bench output files and generate summary CSV
#
# Usage: python3 scripts/parse_results.py results/ > summary.csv
#
# Extracts throughput (ops/sec) and 99.9P latency from db_bench output.

import os, sys, re, csv, json
from pathlib import Path
from collections import defaultdict

def parse_db_bench_output(filepath):
    """Extract key metrics from a db_bench output file."""
    with open(filepath, 'r', errors='replace') as f:
        text = f.read()

    result = {
        'file': os.path.basename(filepath),
        'throughput_ops': None,
        'throughput_mb': None,
        'latency_avg_us': None,
        'p50': None,
        'p99': None,
        'p999': None,
    }

    # Throughput: look for "ops/sec" lines
    for line in text.split('\n'):
        m = re.match(r'.*?(\d+\.?\d*)\s+ops/sec.*', line)
        if m:
            result['throughput_ops'] = float(m.group(1))
            break

    # Also try "micros/op" style
    for line in text.split('\n'):
        m = re.match(r'.*?(\d+\.?\d*)\s+micros/op.*', line)
        if m:
            us = float(m.group(1))
            result['throughput_ops'] = 1_000_000.0 / us
            result['latency_avg_us'] = us
            break

    # MB/sec
    for line in text.split('\n'):
        m = re.match(r'.*?(\d+\.?\d*)\s+MB/sec.*', line)
        if m:
            result['throughput_mb'] = float(m.group(1))
            break

    # Histogram percentiles
    for line in text.split('\n'):
        m = re.match(r'Percentiles:\s*(.*)', line)
        if m:
            result['percentile_line'] = m.group(1)
            break

    # More specific: P50, P99, P99.9
    for line in text.split('\n'):
        if 'P50' in line:
            m = re.match(r'P50:\s*(\d+\.?\d*)\s*(us|ms)', line)
            if m:
                val = float(m.group(1))
                if m.group(2) == 'ms':
                    val *= 1000
                result['p50'] = val
        if 'P99' in line and 'P99.9' not in line and 'P999' not in line:
            m = re.match(r'P99:\s*(\d+\.?\d*)\s*(us|ms)', line)
            if m:
                val = float(m.group(1))
                if m.group(2) == 'ms':
                    val *= 1000
                result['p99'] = val
        if 'P99.9' in line or 'P999' in line:
            m = re.match(r'P99.9:\s*(\d+\.?\d*)\s*(us|ms)', line)
            if m:
                val = float(m.group(1))
                if m.group(2) == 'ms':
                    val *= 1000
                result['p999'] = val

    return result

def main():
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    if not os.path.isdir(results_dir):
        print(f"Directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(Path(results_dir).glob("*.txt"))
    if not files:
        print("No result files found.", file=sys.stderr)
        sys.exit(1)

    # Parse all files
    rows = []
    for f in files:
        row = parse_db_bench_output(str(f))
        # Extract metadata from filename convention:
        # {prefix}_{age/param}_{workload}_{timestamp}.txt
        parts = f.stem.split('_')
        row['experiment'] = parts[0] if len(parts) > 0 else ''
        rows.append(row)

    # Write CSV
    fieldnames = ['experiment', 'file', 'throughput_ops', 'throughput_mb',
                  'latency_avg_us', 'p50', 'p99', 'p999']
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    print(f"\nParsed {len(rows)} results files.", file=sys.stderr)

if __name__ == '__main__':
    main()

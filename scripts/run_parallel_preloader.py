#!/usr/bin/env python
"""
Parallel preloader orchestrator — divides Nifty 500 into 20 batches of 25,
spawns each as a subprocess, waits for all to complete, prints summary.

Usage:
    .venv/Scripts/python.exe scripts/run_parallel_preloader.py
"""

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
SCRIPT  = PROJECT_ROOT / "scripts" / "preloader_single_batch.py"

BATCH_SIZE = 25
TOTAL_COMPANIES = 504
MAX_PARALLEL = 5


def main(start_idx=0, end_idx=None):
    end_idx = end_idx or TOTAL_COMPANIES
    print(f"\n{'='*60}")
    print(f"  Parallel Preloader Orchestrator")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Range: [{start_idx}:{end_idx}]")
    print(f"  Batches: {(end_idx - start_idx + BATCH_SIZE - 1) // BATCH_SIZE} x {BATCH_SIZE} companies each")
    print(f"  Max parallel: {MAX_PARALLEL}")
    print(f"{'='*60}\n")

    batches = []
    for start in range(start_idx, end_idx, BATCH_SIZE):
        end = min(start + BATCH_SIZE, end_idx)
        batches.append((start, end))

    print(f"  Spawning {len(batches)} batches...\n")

    tmpdir = Path(tempfile.mkdtemp(prefix="preloader_"))
    print(f"  Output dir: {tmpdir}\n")

    processes = {}
    results = []

    def launch_batch(start, end, idx):
        outfile = tmpdir / f"batch_{start}_{end}.log"
        fh = open(str(outfile), "w")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [str(PYTHON), "-u", str(SCRIPT), "--start", str(start), "--end", str(end)],
            cwd=str(PROJECT_ROOT),
            stdout=fh,
            stderr=subprocess.STDOUT,
            env=env,
        )
        processes[proc] = (idx, start, end, outfile, fh)
        return proc

    batch_idx = 0
    active = 0

    while batch_idx < len(batches) or active > 0:
        while active < MAX_PARALLEL and batch_idx < len(batches):
            start, end = batches[batch_idx]
            launch_batch(start, end, batch_idx)
            print(f"  [LAUNCH] Batch {batch_idx+1}/{len(batches)}  [{start}:{end}]")
            batch_idx += 1
            active += 1
            time.sleep(5)

        done = []
        for proc in list(processes.keys()):
            ret = proc.poll()
            if ret is not None:
                idx, start, end, outfile, fh = processes.pop(proc)
                fh.close()
                active -= 1
                output = outfile.read_text()
                done.append((idx, start, end, ret, output))
                outfile.unlink()  # clean up

        if done:
            for idx, start, end, retcode, output in done:
                status = "OK" if retcode == 0 else f"FAIL (exit {retcode})"
                print(f"  [DONE] Batch {idx+1}  [{start}:{end}]  -> {status}")
                results.append({
                    "batch": idx + 1,
                    "start": start,
                    "end": end,
                    "exit_code": retcode,
                    "status": status,
                })
                last_lines = output.strip().split("\n")[-3:]
                for line in last_lines:
                    if line.strip():
                        print(f"         {line.strip()[:120]}")

        if batch_idx < len(batches) or active > 0:
            time.sleep(2)

    tmpdir.rmdir()

    ok = sum(1 for r in results if r["exit_code"] == 0)
    fail = len(results) - ok

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Total batches:  {len(results)}")
    print(f"  Succeeded:      {ok}")
    print(f"  Failed:         {fail}")
    if fail:
        for r in results:
            if r["exit_code"] != 0:
                print(f"    - Batch {r['batch']} [{r['start']}:{r['end']}] exit={r['exit_code']}")
    print(f"  Completed at:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=TOTAL_COMPANIES)
    args = parser.parse_args()
    sys.exit(main(args.start, args.end))

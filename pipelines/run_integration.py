"""
End-to-end data integration pipeline.

Usage (from project root):
    python pipelines/run_integration.py

Flags:
    --force    Re-run even if processed files already exist.
    --demand-only   Run only the demand (ORNL) processing step.
    --supply-only   Run only the supply (TVA) processing step.

What it does
────────────
  Step 1 — Demand processing
      Reads 5 ORNL parquet files → demand_engineered.csv
      (~2–5 min per file, ~15 min total on a standard laptop)

  Step 2 — Supply processing
      Reads supply_all_years.csv → supply_engineered.csv
      (< 1 min)

  Step 3 — Integration
      Merges demand + supply → integrated.csv
      (< 1 min)
"""

import argparse
import sys
import time
from pathlib import Path

# Allow running from project root: python pipelines/run_integration.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DEMAND_OUTPUT, SUPPLY_OUTPUT, INTEGRATED_OUTPUT
from src.data.demand_processor  import process_all_days
from src.data.supply_processor  import process_supply
from src.data.integrator        import integrate
from src.utils.logger           import get_logger

logger = get_logger("pipeline")


def run(force: bool = False, demand_only: bool = False, supply_only: bool = False) -> None:
    start_total = time.time()
    logger.info("=" * 62)
    logger.info("  HPC Carbon Optimizer — Integration Pipeline")
    logger.info("=" * 62)

    # ── Step 1: Demand ────────────────────────────────────────────────────────
    if not supply_only:
        if DEMAND_OUTPUT.exists() and not force:
            logger.info(f"\n[Step 1] SKIP — {DEMAND_OUTPUT.name} already exists  (use --force to re-run)")
        else:
            logger.info("\n[Step 1] Processing ORNL demand data …")
            t0 = time.time()
            process_all_days()
            logger.info(f"  Done in {(time.time() - t0) / 60:.1f} min")

    if demand_only:
        logger.info("\nDemand-only mode: stopping here.")
        return

    # ── Step 2: Supply ────────────────────────────────────────────────────────
    if not demand_only:
        if SUPPLY_OUTPUT.exists() and not force:
            logger.info(f"\n[Step 2] SKIP — {SUPPLY_OUTPUT.name} already exists  (use --force to re-run)")
        else:
            logger.info("\n[Step 2] Processing TVA supply data …")
            t0 = time.time()
            process_supply()
            logger.info(f"  Done in {(time.time() - t0):.1f} s")

    if supply_only:
        logger.info("\nSupply-only mode: stopping here.")
        return

    # ── Step 3: Integrate ─────────────────────────────────────────────────────
    if INTEGRATED_OUTPUT.exists() and not force:
        logger.info(f"\n[Step 3] SKIP — {INTEGRATED_OUTPUT.name} already exists  (use --force to re-run)")
    else:
        logger.info("\n[Step 3] Integrating demand + supply …")
        t0 = time.time()
        integrate()
        logger.info(f"  Done in {(time.time() - t0):.1f} s")

    elapsed = time.time() - start_total
    logger.info(f"\n{'=' * 62}")
    logger.info(f"  Pipeline complete in {elapsed / 60:.1f} min")
    logger.info(f"  Outputs in: data/processed/")
    logger.info(f"{'=' * 62}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the HPC data integration pipeline.")
    parser.add_argument("--force",        action="store_true", help="Re-run all steps even if outputs exist.")
    parser.add_argument("--demand-only",  action="store_true", help="Run Step 1 only.")
    parser.add_argument("--supply-only",  action="store_true", help="Run Step 2 only.")
    args = parser.parse_args()

    run(force=args.force, demand_only=args.demand_only, supply_only=args.supply_only)

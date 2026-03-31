#!/usr/bin/env python3
"""Standalone evaluator — score a completed simulation run.

Usage:
    python evaluate.py --run-dir runs/latest --scenario scenarios/nexus_billing/scenario.yaml
"""

import argparse
import asyncio
import os
from pathlib import Path

import yaml

from src.engine.world_state import WorldState
from src.evaluation.evaluator import evaluate
from src.llm_client import LLMClient


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate a completed simulation run")
    parser.add_argument("--run-dir", required=True, help="Path to run output directory")
    parser.add_argument("--scenario", required=True, help="Path to scenario YAML")
    parser.add_argument(
        "--judge-model", default=os.environ.get("JUDGE_MODEL", "gpt-4o-mini"),
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    run_dir = Path(args.run_dir)

    # Load scenario for evaluation config
    with open(args.scenario) as f:
        scenario_data = yaml.safe_load(f)

    evaluation_config = scenario_data.get("evaluation", {})
    company_name = scenario_data.get("company", {}).get("name", "Unknown")
    project_name = scenario_data.get("projects", [{}])[0].get("name", "")

    # Load world state from the run's database
    db_path = run_dir / "simulation.db"
    if not db_path.exists():
        print(f"Error: No database found at {db_path}")
        print("Run the simulation first: python run.py --scenario ...")
        return

    world_state = WorldState(str(db_path))

    # LLM client for judge
    llm = LLMClient(judge_model=args.judge_model)
    await llm.validate()

    # Evaluate
    scorecard = await evaluate(
        world_state=world_state,
        evaluation_config=evaluation_config,
        scenario_name=f"{company_name} — {project_name}",
        llm_client=llm,
        output_dir=run_dir,
    )

    scorecard.print_scorecard()


if __name__ == "__main__":
    asyncio.run(main())

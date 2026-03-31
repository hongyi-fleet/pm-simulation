#!/usr/bin/env python3
"""Benchmark pipeline: run multiple models against multiple scenarios, compare results.

Usage:
    # Compare models on short scenario
    python bench.py --models gpt-4o-mini gpt-5.4-mini gpt-5.4

    # Compare on full scenario
    python bench.py --scenario scenarios/nexus_billing/scenario.yaml --models gpt-4o gpt-5.4

    # Multiple runs per model (variance)
    python bench.py --models gpt-5.4-mini --runs 3

    # Quick single model test
    python bench.py --models gpt-5.4-mini
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from src.engine.scenario_loader import load_scenario
from src.engine.game_master import GameMaster
from src.engine.npc import NPCRunner
from src.engine.signal_setup import setup_signals_for_scenario
from src.agent.interface import AgentInterface
from src.llm_client import LLMClient
from src.evaluation.evaluator import evaluate


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark multiple models")
    parser.add_argument(
        "--scenario", default="scenarios/nexus_billing_short/scenario.yaml",
        help="Scenario YAML (default: short version)",
    )
    parser.add_argument(
        "--models", nargs="+", default=["gpt-4o-mini"],
        help="Agent models to compare (NPC/judge always use first model or --npc-model)",
    )
    parser.add_argument(
        "--npc-model", default=None,
        help="NPC model (default: same as cheapest agent model)",
    )
    parser.add_argument(
        "--judge-model", default=None,
        help="Judge model (default: same as NPC model)",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Runs per model (for variance)",
    )
    parser.add_argument(
        "--output-dir", default="runs/bench",
        help="Output directory",
    )
    return parser.parse_args()


async def run_once(scenario_path: str, agent_model: str, npc_model: str,
                   judge_model: str, output_dir: Path) -> dict:
    """Run one simulation. Returns scorecard dict."""
    scenario = load_scenario(scenario_path)

    llm = LLMClient(
        npc_model=npc_model,
        agent_model=agent_model,
        judge_model=judge_model,
    )
    await llm.validate(models=[agent_model, npc_model, judge_model])

    npc_runner = NPCRunner(scenario["npcs"], llm_client=llm, no_llm=False)
    agent = AgentInterface(llm_client=llm, no_llm=False, system_prompt=scenario["agent_prompt"])
    signal_detector = setup_signals_for_scenario(scenario["scenario_data"], llm_client=llm)

    gm = GameMaster(
        clock=scenario["clock"],
        event_queue=scenario["event_queue"],
        world_state=scenario["world_state"],
        tool_registry=scenario["tools"],
        npc_runner=npc_runner,
        agent=agent,
        signal_detector=signal_detector,
        scenario_events=scenario["scenario_events"],
        output_dir=output_dir,
    )

    scenario_name = scenario["scenario_data"].get("company", {}).get("name", "Unknown")
    project = scenario["scenario_data"].get("projects", [{}])[0].get("name", "")

    print(f"  Running: agent={agent_model}, npc={npc_model}")
    event_log = await gm.run()

    result = await evaluate(
        world_state=scenario["world_state"],
        evaluation_config=scenario["evaluation"],
        scenario_name=f"{scenario_name} — {project}",
        llm_client=llm,
        no_llm=False,
        output_dir=output_dir,
    )

    # Save config
    config = {
        "scenario": str(scenario_path),
        "agent_model": agent_model,
        "npc_model": npc_model,
        "judge_model": judge_model,
        "events": len(event_log),
        "timestamp": datetime.now().isoformat(),
    }
    with open(output_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    return result.to_dict()


def print_comparison(results: dict):
    """Print side-by-side comparison of models."""
    print("\n" + "=" * 80)
    print("BENCHMARK COMPARISON")
    print("=" * 80)

    # Header
    models = list(results.keys())
    col_width = max(20, max(len(m) for m in models) + 2)
    header = f"{'Checkpoint':<35}"
    for model in models:
        header += f" {model:>{col_width}}"
    print(header)
    print("-" * (35 + (col_width + 1) * len(models)))

    # Collect all checkpoint names
    all_checkpoints = []
    for model_results in results.values():
        for run in model_results:
            for cp in run["checkpoints"]:
                if cp["name"] not in all_checkpoints:
                    all_checkpoints.append(cp["name"])

    # Print each checkpoint
    for cp_name in all_checkpoints:
        row = f"{cp_name:<35}"
        for model in models:
            scores = []
            for run in results[model]:
                for cp in run["checkpoints"]:
                    if cp["name"] == cp_name:
                        scores.append(f"{cp['result']}/{cp['total']}")
                        break
            if len(scores) == 1:
                row += f" {scores[0]:>{col_width}}"
            else:
                row += f" {', '.join(scores):>{col_width}}"
        print(row)

    # Print totals
    print("-" * (35 + (col_width + 1) * len(models)))
    row = f"{'TOTAL':<35}"
    for model in models:
        scores = [r["score"] for r in results[model]]
        if len(scores) == 1:
            row += f" {scores[0]:.1%}".rjust(col_width + 1)
        else:
            mean = sum(scores) / len(scores)
            row += f" {mean:.1%} (±{max(scores)-min(scores):.1%})".rjust(col_width + 1)
    print(row)

    # Print categories
    print("\n" + "-" * 80)
    print("BY CATEGORY:")
    categories = set()
    for model_results in results.values():
        for run in model_results:
            categories.update(run.get("categories", {}).keys())

    for cat in sorted(categories):
        row = f"  {cat:<33}"
        for model in models:
            scores = []
            for run in results[model]:
                cat_data = run.get("categories", {}).get(cat, {})
                scores.append(cat_data.get("score", 0))
            if len(scores) == 1:
                row += f" {scores[0]:.0%}".rjust(col_width + 1)
            else:
                mean = sum(scores) / len(scores)
                row += f" {mean:.0%}".rjust(col_width + 1)
        print(row)

    print("=" * 80)


async def main():
    args = parse_args()

    npc_model = args.npc_model or args.models[0]
    judge_model = args.judge_model or npc_model

    results = {}  # model -> [scorecard_dict, ...]

    for model in args.models:
        results[model] = []

        for run_num in range(1, args.runs + 1):
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_name = f"{model}_{timestamp}"
            if args.runs > 1:
                run_name += f"_run{run_num}"

            output_dir = Path(args.output_dir) / run_name
            output_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n{'#' * 60}")
            print(f"# {model} (run {run_num}/{args.runs})")
            print(f"{'#' * 60}")

            try:
                scorecard = await run_once(
                    args.scenario, model, npc_model, judge_model, output_dir
                )
                results[model].append(scorecard)
            except Exception as e:
                print(f"  FAILED: {e}")
                results[model].append({"checkpoints": [], "score": 0.0, "categories": {}})

    # Save combined results
    bench_path = Path(args.output_dir) / "comparison.json"
    with open(bench_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {bench_path}")

    # Print comparison
    print_comparison(results)


if __name__ == "__main__":
    asyncio.run(main())

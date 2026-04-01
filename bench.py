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
        "--scenario", default="scenarios/nexus_billing/scenario.yaml",
        help="Scenario YAML (default: full week)",
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
    signals = setup_signals_for_scenario(scenario["scenario_data"], llm_client=llm)
    sim_detector = signals["simulation"]
    eval_recorder = signals["evaluation"]

    gm = GameMaster(
        clock=scenario["clock"],
        event_queue=scenario["event_queue"],
        world_state=scenario["world_state"],
        tool_registry=scenario["tools"],
        npc_runner=npc_runner,
        agent=agent,
        sim_detector=sim_detector,
        eval_recorder=eval_recorder,
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
        eval_recorder=eval_recorder,
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
    """Print side-by-side comparison of models with statistics."""
    import statistics

    print("\n" + "=" * 80)
    print("BENCHMARK COMPARISON")
    print("=" * 80)

    models = list(results.keys())
    runs_per_model = max(len(v) for v in results.values())
    col_width = max(20, max(len(m) for m in models) + 2)

    # === Per-checkpoint breakdown ===
    header = f"{'Checkpoint':<35}"
    for model in models:
        header += f" {model:>{col_width}}"
    print(header)
    print("-" * (35 + (col_width + 1) * len(models)))

    all_checkpoints = []
    for model_results in results.values():
        for run in model_results:
            for cp in run.get("checkpoints", []):
                if cp["name"] not in all_checkpoints:
                    all_checkpoints.append(cp["name"])

    for cp_name in all_checkpoints:
        row = f"{cp_name:<35}"
        for model in models:
            scores = []
            total = 0
            for run in results[model]:
                for cp in run.get("checkpoints", []):
                    if cp["name"] == cp_name:
                        scores.append(cp["result"])
                        total = cp["total"]
                        break
            if not scores:
                row += f" {'—':>{col_width}}"
            elif len(scores) == 1:
                row += f" {scores[0]}/{total}".rjust(col_width + 1)
            else:
                mean = statistics.mean(scores)
                row += f" {mean:.1f}/{total}".rjust(col_width + 1)
        print(row)

    # === Total scores with statistics ===
    print("-" * (35 + (col_width + 1) * len(models)))

    for label, key in [("TOTAL", "score")]:
        row = f"{label:<35}"
        for model in models:
            scores = [r.get(key, 0) for r in results[model] if r.get("checkpoints")]
            if not scores:
                row += f" {'—':>{col_width}}"
            elif len(scores) == 1:
                row += f" {scores[0]:.1%}".rjust(col_width + 1)
            else:
                mean = statistics.mean(scores)
                std = statistics.stdev(scores) if len(scores) > 1 else 0
                row += f" {mean:.1%} ±{std:.1%}".rjust(col_width + 1)
        print(row)

    # === Statistics detail (if multiple runs) ===
    if runs_per_model > 1:
        print(f"\n{'STATISTICS':<35}", end="")
        for model in models:
            print(f" {model:>{col_width}}", end="")
        print()
        print("-" * (35 + (col_width + 1) * len(models)))

        for stat_name, stat_fn in [("mean", statistics.mean), ("stdev", lambda x: statistics.stdev(x) if len(x) > 1 else 0), ("min", min), ("max", max)]:
            row = f"  {stat_name:<33}"
            for model in models:
                scores = [r.get("score", 0) for r in results[model] if r.get("checkpoints")]
                if not scores:
                    row += f" {'—':>{col_width}}"
                else:
                    val = stat_fn(scores)
                    row += f" {val:.1%}".rjust(col_width + 1)
            print(row)

        # Per-run scores
        print()
        for i in range(runs_per_model):
            row = f"  run {i+1:<31}"
            for model in models:
                if i < len(results[model]) and results[model][i].get("checkpoints"):
                    row += f" {results[model][i]['score']:.1%}".rjust(col_width + 1)
                else:
                    row += f" {'—':>{col_width}}"
            print(row)

    # === By category ===
    print(f"\n{'BY CATEGORY':<35}", end="")
    for model in models:
        print(f" {model:>{col_width}}", end="")
    print()
    print("-" * (35 + (col_width + 1) * len(models)))

    categories = []
    for model_results in results.values():
        for run in model_results:
            for cat in run.get("categories", {}):
                if cat not in categories:
                    categories.append(cat)

    for cat in categories:
        row = f"  {cat:<33}"
        for model in models:
            scores = []
            for run in results[model]:
                cat_data = run.get("categories", {}).get(cat, {})
                if cat_data:
                    scores.append(cat_data.get("score", 0))
            if not scores:
                row += f" {'—':>{col_width}}"
            elif len(scores) == 1:
                row += f" {scores[0]:.0%}".rjust(col_width + 1)
            else:
                mean = statistics.mean(scores)
                std = statistics.stdev(scores) if len(scores) > 1 else 0
                row += f" {mean:.0%} ±{std:.0%}".rjust(col_width + 1)
        print(row)

    print("=" * 80)


async def main():
    args = parse_args()

    npc_model = args.npc_model or args.models[0]
    judge_model = args.judge_model or npc_model

    results = {}  # model -> [scorecard_dict, ...]

    # Build all tasks
    tasks = []  # (model, run_num, output_dir)
    for model in args.models:
        results[model] = [None] * args.runs
        for run_num in range(1, args.runs + 1):
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_name = f"{model}_{timestamp}"
            if args.runs > 1:
                run_name += f"_run{run_num}"
            output_dir = Path(args.output_dir) / run_name
            output_dir.mkdir(parents=True, exist_ok=True)
            tasks.append((model, run_num, output_dir))

    total = len(tasks)
    print(f"\nRunning {total} simulations in parallel...")

    async def run_task(model, run_num, output_dir):
        print(f"  Starting: {model} run {run_num}")
        try:
            scorecard = await run_once(
                args.scenario, model, npc_model, judge_model, output_dir
            )
            print(f"  Done: {model} run {run_num} → {scorecard.get('score', 0):.1%}")
            return scorecard
        except Exception as e:
            print(f"  FAILED: {model} run {run_num}: {e}")
            return {"checkpoints": [], "score": 0.0, "categories": {}}

    # Run all in parallel
    coros = [run_task(m, r, o) for m, r, o in tasks]
    all_results = await asyncio.gather(*coros)

    # Distribute results back
    idx = 0
    for model in args.models:
        for run_num in range(args.runs):
            results[model][run_num] = all_results[idx]
            idx += 1

    # Save combined results
    bench_path = Path(args.output_dir) / "comparison.json"
    with open(bench_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {bench_path}")

    # Print comparison
    print_comparison(results)


if __name__ == "__main__":
    asyncio.run(main())

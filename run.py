#!/usr/bin/env python3
"""PM Simulation Environment — main entry point.

Usage:
    python run.py --scenario scenarios/nexus_billing/scenario.yaml
    python run.py --scenario scenarios/nexus_billing/scenario.yaml --runs 3
    python run.py --scenario scenarios/nexus_billing/scenario.yaml --agent-model gpt-4o --npc-model gpt-4o-mini
"""

import argparse
import asyncio
import builtins
import os
import sys
from pathlib import Path

from src.engine.scenario_loader import load_scenario
from src.engine.game_master import GameMaster
from src.engine.npc import NPCRunner
from src.engine.signals import SignalDetectorEngine
from src.engine.signal_setup import setup_signals_for_scenario
from src.agent.interface import AgentInterface
from src.llm_client import LLMClient
from src.evaluation.evaluator import evaluate


_ORIGINAL_PRINT = builtins.print
_PRINT_BROKEN = False


def _safe_print(*args, **kwargs):
    global _PRINT_BROKEN
    if _PRINT_BROKEN:
        return
    try:
        kwargs.setdefault("flush", True)
        _ORIGINAL_PRINT(*args, **kwargs)
    except BrokenPipeError:
        _PRINT_BROKEN = True
        devnull = open(os.devnull, "w")
        sys.stdout = devnull
        sys.stderr = devnull


builtins.print = _safe_print


def parse_args():
    parser = argparse.ArgumentParser(description="PM Simulation Environment")
    parser.add_argument(
        "--scenario", required=True,
        help="Path to scenario YAML file",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of runs (reports mean/std/min/max scores)",
    )
    parser.add_argument(
        "--agent-model", default=os.environ.get("AGENT_MODEL", "gpt-4o"),
        help="LLM model for the PM agent",
    )
    parser.add_argument(
        "--npc-model", default=os.environ.get("NPC_MODEL", "gpt-4o"),
        help="LLM model for NPC coworkers",
    )
    parser.add_argument(
        "--judge-model", default=os.environ.get("JUDGE_MODEL", "gpt-4o"),
        help="LLM model for evaluation judge",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Directory to save run outputs (default: auto-timestamped)",
    )
    return parser.parse_args()


async def run_once(args, run_number: int = 1) -> float:
    """Run one simulation episode. Returns the total score."""
    from datetime import datetime as _dt

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        timestamp = _dt.now().strftime("%Y%m%d-%H%M%S")
        scenario_name = Path(args.scenario).parent.name
        output_dir = Path(f"runs/{scenario_name}_{timestamp}")

    if args.runs > 1:
        output_dir = output_dir / f"run_{run_number}"

    # Load scenario (fresh state each run)
    scenario = load_scenario(args.scenario)

    # Initialize LLM client
    llm = LLMClient(
        npc_model=args.npc_model,
        agent_model=args.agent_model,
        judge_model=args.judge_model,
    )

    # Validate API key at startup
    print("Validating API key...")
    await llm.validate(models=[args.agent_model, args.npc_model, args.judge_model])

    # Set up NPC runner
    npc_runner = NPCRunner(
        npcs=scenario["npcs"],
        llm_client=llm,
        no_llm=False,
    )

    # Set up agent
    agent = AgentInterface(
        llm_client=llm,
        no_llm=False,
        system_prompt=scenario["agent_prompt"],
    )

    # Set up signal detector from scenario evaluation config
    # Layer 1 (state checks) + Layer 2 (LLM judge) — same pattern as TheAgentCompany
    signal_detector = setup_signals_for_scenario(scenario["scenario_data"], llm_client=llm)

    # Set up game master
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

    # Run simulation
    scenario_name = scenario["scenario_data"].get("company", {}).get("name", "Unknown")
    project = scenario["scenario_data"].get("projects", [{}])[0].get("name", "")
    print(f"\n{'='*60}")
    print(f"PM Simulation: {scenario_name} — {project}")
    print(f"Models: agent={args.agent_model}, npc={args.npc_model}, judge={args.judge_model}")
    print(f"{'='*60}\n")

    # Save run config
    import json as _json
    config_path = output_dir / "config.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        _json.dump({
            "scenario": args.scenario,
            "agent_model": args.agent_model,
            "npc_model": args.npc_model,
            "judge_model": args.judge_model,
            "run_number": run_number,
            "timestamp": output_dir.name,
        }, f, indent=2)

    event_log = await gm.run()

    # Evaluate
    print(f"\nSimulation complete. {len(event_log)} events processed.")
    print("Running evaluation...\n")

    scorecard = await evaluate(
        world_state=scenario["world_state"],
        evaluation_config=scenario["evaluation"],
        scenario_name=f"{scenario_name} — {project}",
        llm_client=llm,
        no_llm=False,
        output_dir=output_dir,
    )

    return scorecard.score


async def main():
    args = parse_args()

    if args.runs == 1:
        await run_once(args)
    else:
        # Multiple runs — report statistics
        scores = []
        for i in range(1, args.runs + 1):
            print(f"\n{'#'*60}")
            print(f"# RUN {i}/{args.runs}")
            print(f"{'#'*60}")
            score = await run_once(args, run_number=i)
            scores.append(score)

        # Report statistics
        import statistics
        print(f"\n{'='*60}")
        print(f"MULTI-RUN RESULTS ({args.runs} runs)")
        print(f"{'='*60}")
        print(f"  Mean:   {statistics.mean(scores):.3f}")
        if len(scores) > 1:
            print(f"  Stdev:  {statistics.stdev(scores):.3f}")
        print(f"  Min:    {min(scores):.3f}")
        print(f"  Max:    {max(scores):.3f}")
        print(f"  Scores: {[round(s, 3) for s in scores]}")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())

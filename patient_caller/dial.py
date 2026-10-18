"""Place the assessment calls one at a time and wait until each one is saved."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from .config import (
    AGENT_NAME,
    ALLOWED_DESTINATION,
    ROOT,
    assert_destination,
    caller_number,
    calls_dir,
    require_env,
)
from .scenarios import SCENARIOS, Scenario, get_scenario

load_dotenv(ROOT / ".env")


def allocate_directory(scenario: Scenario) -> Path:
    root = calls_dir()
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / scenario.id
    if not candidate.exists():
        return candidate
    number = 2
    while (root / f"{scenario.id}-{number}").exists():
        number += 1
    return root / f"{scenario.id}-{number}"


def _print_plan(scenarios: list[Scenario]) -> None:
    destination = assert_destination(ALLOWED_DESTINATION)
    print(f"Destination (fixed): {destination}")
    print(f"Calls: {len(scenarios)}")
    for scenario in scenarios:
        print(f"  {scenario.id}  {scenario.title}  ({scenario.max_seconds}s cap)")


async def dispatch_one(scenario: Scenario) -> Path:
    from livekit import api

    destination = assert_destination(ALLOWED_DESTINATION)
    caller = caller_number()
    require_env("LIVEKIT_URL")
    require_env("LIVEKIT_API_KEY")
    require_env("LIVEKIT_API_SECRET")
    directory = allocate_directory(scenario)
    room = f"call-{scenario.id}-{uuid.uuid4().hex[:8]}"
    metadata = json.dumps(
        {
            "phone_number": destination,
            "scenario_id": scenario.id,
            "call_id": directory.name,
        }
    )
    print(f"dialing {scenario.id} as {caller} -> {destination}")
    async with api.LiveKitAPI() as lk:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room,
                metadata=metadata,
            )
        )
    return directory


async def wait_until_done(directory: Path, timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    marker = directory / "done.json"
    while time.time() < deadline:
        if marker.exists():
            return json.loads(marker.read_text(encoding="utf-8"))
        await asyncio.sleep(2)
    raise TimeoutError(
        f"No done.json in {directory}. "
        "The worker may not be running: python -m livekit.agents start patient_caller/agent.py --dev"
    )


async def dial_scenarios(scenarios: list[Scenario]) -> list[dict]:
    results = []
    for index, scenario in enumerate(scenarios):
        directory = await dispatch_one(scenario)
        try:
            result = await wait_until_done(directory, timeout_s=scenario.max_seconds + 100)
        except Exception as exc:
            result = {"call_id": directory.name, "ok": False, "error": str(exc)}
        results.append(result)
        status = "ok" if result.get("ok") else "failed"
        print(f"  {status}: {directory.name} ({result.get('error') or result.get('hangup_reason') or 'saved'})")
        if index < len(scenarios) - 1:
            await asyncio.sleep(8)
    return results


def _selected(args: argparse.Namespace) -> list[Scenario]:
    if args.scenario:
        return [get_scenario(args.scenario)]
    return list(SCENARIOS)


def _print_summary(results: list[dict]) -> None:
    ok = sum(1 for item in results if item.get("ok"))
    print(f"\n{ok} of {len(results)} calls captured both sides.")
    try:
        print(f"Caller ID to submit: {caller_number()}")
    except SystemExit as exc:
        print(exc)
    print("Listen to calls/<id>/recording.ogg before treating any bug draft as final.")


def start_worker() -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        [sys.executable, "-m", "livekit.agents", "start", "patient_caller/agent.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def wait_until_registered(proc: subprocess.Popen, timeout_s: float = 90) -> None:
    assert proc.stdout is not None
    registered = threading.Event()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"[worker] {line}", end="")
            if "registered worker" in line.lower():
                registered.set()

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if registered.wait(timeout=0.5):
            return
        if proc.poll() is not None:
            raise SystemExit(f"Worker exited early with code {proc.returncode}")
    raise SystemExit("Worker did not register within 90s. Check the log above.")


def stop_worker(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_batch(scenarios: list[Scenario]) -> list[dict]:
    proc = start_worker()
    try:
        wait_until_registered(proc)
        return asyncio.run(dial_scenarios(scenarios))
    finally:
        stop_worker(proc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dial the assessment line as a patient.")
    parser.add_argument("--scenario", help="One scenario id, such as 05-sunday")
    parser.add_argument("--all", action="store_true", help="Run every scenario")
    parser.add_argument("--list", action="store_true", help="Print scenario ids")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and do not dial")
    parser.add_argument(
        "--with-worker",
        action="store_true",
        help="Start the worker, dial, then stop the worker",
    )
    args = parser.parse_args(argv)

    if args.list or args.dry_run:
        _print_plan(list(SCENARIOS) if not args.scenario else [get_scenario(args.scenario)])
        return 0
    if not args.all and not args.scenario:
        parser.error("Pass --all, --scenario ID, --list, or --dry-run")

    scenarios = _selected(args)
    if args.with_worker:
        results = run_batch(scenarios)
    else:
        results = asyncio.run(dial_scenarios(scenarios))
    _print_summary(results)
    return 0 if all(item.get("ok") for item in results) else 1

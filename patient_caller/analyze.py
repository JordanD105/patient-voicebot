"""Draft a bug report from saved transcripts. Listen before you trust it."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from .config import ROOT, calls_dir
from .leads import Lead, find_leads
from .scenarios import SCENARIOS

load_dotenv(ROOT / ".env")

GENERATED_START = "<!-- generated:start -->"
GENERATED_END = "<!-- generated:end -->"


def _call_dirs() -> list[Path]:
    root = calls_dir()
    if not root.exists():
        return []
    found = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "transcript.txt").exists():
            found.append(path)
    return found


def _scenario_id(directory: Path, transcript: str) -> str:
    for line in transcript.splitlines():
        if line.startswith("Scenario id:"):
            return line.split(":", 1)[1].strip()
    return directory.name


def _clock(line: str) -> str:
    if not line.startswith("[") or "]" not in line:
        return ""
    raw = line[1:line.index("]")]
    minutes, _, rest = raw.partition(":")
    if not minutes.isdigit() or not rest:
        return ""
    seconds = rest.split(".", 1)[0]
    if not seconds.isdigit():
        return ""
    return f"{int(minutes)}:{seconds}"


def _format_lead(directory: Path, transcript: str, lead: Lead) -> str:
    where = f"calls/{directory.name}/transcript.txt"
    when = ""
    if lead.quote:
        for line in transcript.splitlines():
            if lead.quote[:48] in line:
                when = _clock(line)
                break
    call = f"{where} at {when}" if when else where
    detail = lead.detail
    if lead.quote:
        detail = f'{detail} The clinic said, "{lead.quote}"'
    return (
        f"Bug: {lead.summary} Severity: {lead.severity.capitalize()} "
        f"Call: {call} Details: {detail}\n"
    )


def _heuristic_section(directories: list[Path]) -> str:
    blocks = []
    for directory in directories:
        transcript = (directory / "transcript.txt").read_text(encoding="utf-8")
        scenario_id = _scenario_id(directory, transcript)
        for lead in find_leads(scenario_id, transcript):
            blocks.append(_format_lead(directory, transcript, lead))
    if not blocks:
        return "No heuristic leads. That does not mean the calls were clean. Listen anyway.\n"
    return "\n".join(blocks)


def _review_prompt(directories: list[Path]) -> str:
    hints = "\n".join(f"- {item.id}: {item.review_hint}" for item in SCENARIOS)
    chunks = []
    for directory in directories:
        text = (directory / "transcript.txt").read_text(encoding="utf-8")
        chunks.append(f"===== {directory.name} =====\n{text[:8000]}")
    joined = "\n\n".join(chunks)
    return f"""You are reviewing transcripts of a clinic phone agent. The PATIENT lines are our caller. The CLINIC lines are the system under test.

Report only problems that the transcript itself shows. Quote the clinic line. Name the call folder. Use high, medium, or low severity. Skip punctuation, wording nits, and anything the hint calls correct behavior.

What each call was trying to expose:
{hints}

Write each finding as one paragraph, with the four labels in that order and a space between them. Do not put the labels on separate lines.

Bug: one sentence naming the failure Severity: High|Medium|Low Call: calls/<folder>/transcript.txt at M:SS Details: What the patient asked, the clinic's words in quotes, and what the clinic should have done instead.

If a call looks fine, say so in one line under a heading "Calls with no transcript bug".
Do not invent audio problems you cannot see.

Transcripts:
{joined}
"""


async def _model_review(prompt: str) -> str:
    from livekit.agents import inference
    from livekit.agents.llm import ChatContext

    model_name = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")
    model = inference.LLM(model_name)
    chat_ctx = ChatContext()
    chat_ctx.add_message(role="user", content=prompt)
    parts: list[str] = []
    async with model.chat(chat_ctx=chat_ctx) as stream:
        async for chunk in stream:
            delta = getattr(chunk, "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                parts.append(content)
    return "".join(parts).strip()


def _stitch(existing: str, generated: str) -> str:
    block = f"{GENERATED_START}\n{generated.rstrip()}\n{GENERATED_END}\n"
    if GENERATED_START in existing and GENERATED_END in existing:
        head, rest = existing.split(GENERATED_START, 1)
        _, tail = rest.split(GENERATED_END, 1)
        return head + block + tail.lstrip("\n")
    return existing.rstrip() + "\n\n" + block


def write_report(model_text: str | None = None) -> Path:
    directories = _call_dirs()
    bugs = ROOT / "BUGS.md"
    existing = bugs.read_text(encoding="utf-8") if bugs.exists() else ""
    if not directories:
        raise SystemExit("No transcripts in the calls directory yet.")

    parts = [
        "## Draft from transcripts",
        "",
        "These notes were generated from text. A finding counts after you hear it in the recording.",
        "",
        "### Heuristic leads",
        "",
        _heuristic_section(directories).rstrip(),
        "",
    ]
    if model_text:
        parts.extend(["### Model review", "", model_text.rstrip(), ""])
    else:
        parts.extend(
            [
                "### Model review",
                "",
                "Not run. Re-run analyze after the worker credentials are set if you want a second pass.",
                "",
            ]
        )
    text = _stitch(existing, "\n".join(parts))
    bugs.write_text(text, encoding="utf-8")
    return bugs


def main() -> int:
    directories = _call_dirs()
    if not directories:
        raise SystemExit("No transcripts yet. Dial first, then analyze.")
    model_text = None
    try:
        model_text = asyncio.run(_model_review(_review_prompt(directories)))
    except Exception as exc:
        print(f"Model review skipped: {exc}")
    path = write_report(model_text)
    print(f"Updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

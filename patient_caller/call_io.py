"""Transcripts and the done marker the dialer waits on."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .scenarios import Scenario


def format_offset(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes:02d}:{rest:04.1f}"


@dataclass
class Turn:
    speaker: str
    text: str
    offset_s: float


@dataclass
class CallRecord:
    directory: Path
    scenario: Scenario
    caller_number: str
    destination: str
    room_name: str
    started_at: float = field(default_factory=time.time)
    turns: list[Turn] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    error: str | None = None
    hangup_reason: str = ""
    finished: bool = False
    recording_name: str = ""

    def mark_answered(self) -> None:
        """Clock the transcript from when the clinic picks up, not from process start."""
        self.started_at = time.time()

    def add_turn(self, speaker: str, text: str) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        if self.turns and self.turns[-1].speaker == speaker and self.turns[-1].text == cleaned:
            return
        self.turns.append(
            Turn(speaker=speaker, text=cleaned, offset_s=time.time() - self.started_at)
        )
        self.write_transcript()

    def clinic_turns(self) -> int:
        return sum(1 for turn in self.turns if turn.speaker == "CLINIC")

    def render(self) -> str:
        started = datetime.fromtimestamp(self.started_at).astimezone().isoformat(timespec="seconds")
        lines = [
            f"Call: {self.directory.name}",
            f"Scenario: {self.scenario.title}",
            f"Scenario id: {self.scenario.id}",
            f"Goal: {self.scenario.goal}",
            f"Patient: {self.scenario.caller_name}",
            f"Destination: {self.destination}",
            f"Caller ID: {self.caller_number}",
            f"Room: {self.room_name}",
            f"Answered: {started}",
            "Audio: recording.ogg  left channel = clinic, right channel = patient",
            "",
        ]
        if not self.turns:
            lines.append("(no speech captured)")
        for turn in self.turns:
            lines.append(f"[{format_offset(turn.offset_s)}] {turn.speaker}: {turn.text}")
        if self.error:
            lines.extend(["", f"Error: {self.error}"])
        if self.hangup_reason:
            lines.extend(["", f"Ended: {self.hangup_reason}"])
        lines.append("")
        return "\n".join(lines)

    def write_transcript(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "transcript.txt").write_text(self.render(), encoding="utf-8")

    def write_metrics(self) -> None:
        if not self.metrics:
            return
        path = self.directory / "metrics.jsonl"
        path.write_text(
            "".join(json.dumps(item, default=str) + "\n" for item in self.metrics),
            encoding="utf-8",
        )

    def write_done(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "call_id": self.directory.name,
            "scenario_id": self.scenario.id,
            "title": self.scenario.title,
            "ok": self.error is None and self.clinic_turns() > 0 and any(
                turn.speaker == "PATIENT" for turn in self.turns
            ),
            "error": self.error,
            "hangup_reason": self.hangup_reason,
            "duration_s": round(time.time() - self.started_at, 1),
            "turns": len(self.turns),
            "clinic_turns": self.clinic_turns(),
            "recording": self.recording_name or None,
            "destination": self.destination,
            "caller_number": self.caller_number,
            "room": self.room_name,
        }
        (self.directory / "done.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (self.directory / "meta.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def message_text(item: object) -> str:
    text = getattr(item, "text_content", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    if isinstance(content, list):
        for piece in content:
            if isinstance(piece, str):
                parts.append(piece)
            else:
                value = getattr(piece, "text", None) or getattr(piece, "transcript", None)
                if value:
                    parts.append(str(value))
    return " ".join(part.strip() for part in parts if part and part.strip())

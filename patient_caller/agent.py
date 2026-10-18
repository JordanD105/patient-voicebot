"""Outbound patient caller.

Pipeline mode only: streaming speech-to-text, a text LLM, and text-to-speech.
The clinic is the remote participant. This process is the patient.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import RunContext  # module scope: 3.14 evaluates tool hints here

from .call_io import CallRecord, message_text
from .config import (
    AGENT_NAME,
    ALLOWED_DESTINATION,
    DEFAULT_VOICE,
    SIP_IDENTITY,
    ROOT,
    assert_destination,
    caller_number,
    calls_dir,
    require_env,
)
from .scenarios import Scenario, get_scenario, instructions_for

load_dotenv(ROOT / ".env")

logger = logging.getLogger("patient-caller")

ACTIVE: dict[str, CallRecord] = {}


def _prewarm(proc) -> None:
    # The installed Silero plugin wheel has no model file, so loading it kills
    # the job before the call starts. The bundled local model does not need that file.
    from livekit.agents import inference

    proc.userdata["vad"] = inference.VAD(min_silence_duration=0.4)
    logger.info("vad ready")


def _build_models():
    mode = os.getenv("PIPELINE", "inference").strip().lower()
    voice = os.getenv("TTS_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE
    if mode == "direct":
        from livekit.plugins import cartesia, deepgram, openai

        return (
            deepgram.STT(model="nova-3", language="en-US"),
            openai.LLM(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini")),
            cartesia.TTS(model="sonic-3", voice=voice),
        )

    from livekit.agents import inference

    return (
        inference.STT(os.getenv("STT_MODEL", "deepgram/nova-3"), language="en"),
        inference.LLM(os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")),
        inference.TTS(os.getenv("TTS_MODEL", "cartesia/sonic-3"), voice=voice),
    )


def _noise_cancellation():
    if os.getenv("NOISE_CANCELLATION", "1").strip().lower() in {"0", "false", "no"}:
        return None
    try:
        from livekit.plugins import noise_cancellation

        return noise_cancellation.BVCTelephony()
    except Exception:
        logger.info("telephony noise cancellation unavailable; continuing without it")
        return None


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _wait_for_playout(context) -> None:
    wait = getattr(context, "wait_for_playout", None)
    if wait is not None:
        await _maybe_await(wait())
        return
    handle = getattr(context, "speech_handle", None)
    if handle is not None and hasattr(handle, "wait_for_playout"):
        await handle.wait_for_playout()


def _parse_metadata(raw: str) -> dict:
    if not raw or not raw.strip():
        raise ValueError("dispatch metadata is empty")
    data = json.loads(raw)
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError("dispatch metadata must be a JSON object")
    return data


async def on_session_end(ctx) -> None:
    record = ACTIVE.pop(getattr(ctx.room, "name", ""), None)
    if record is None:
        return
    src = Path(ctx.session_directory) / "audio.ogg"
    dest = record.directory / "recording.ogg"
    if src.exists() and src.stat().st_size > 200:
        shutil.copyfile(src, dest)
        record.recording_name = dest.name
    elif record.error is None:
        record.error = "recording.ogg was not produced"
    record.write_transcript()
    record.write_metrics()
    record.write_done()
    logger.info(
        "saved call",
        extra={
            "call": record.directory.name,
            "turns": len(record.turns),
            "recording": record.recording_name,
        },
    )


def _make_server():
    from livekit import api
    from livekit.agents import Agent, AgentServer, AgentSession, RunContext, room_io
    from livekit.agents.llm import function_tool

    class Patient(Agent):
        def __init__(self, scenario: Scenario, room, record: CallRecord, hangup) -> None:
            super().__init__(instructions=instructions_for(scenario))
            self._room = room
            self._record = record
            self._hangup = hangup

        @function_tool
        async def press_keypad(self, digits: str) -> str:
            """Press phone keys when a menu or the receptionist asks. digits may contain 0-9, star, and pound."""
            sent: list[str] = []
            for char in digits:
                if char not in "0123456789*#":
                    continue
                code = {"*": 10, "#": 11}.get(char, int(char))
                await self._room.local_participant.publish_dtmf(code=code, digit=char)
                sent.append(char)
                await asyncio.sleep(0.25)
            pressed = "".join(sent) or "(nothing)"
            self._record.add_turn("PATIENT", f"(pressed keypad {pressed})")
            return f"Pressed {pressed}."

        @function_tool
        async def finish_call(self, context: RunContext) -> str:
            """End the call. Use only after you have already said goodbye out loud."""
            await _wait_for_playout(context)
            self._hangup("patient said goodbye")
            return "The call is ending."

    server = AgentServer(
        # The first job process imports the SDK. That can take longer than the
        # 10 second default, and the job then dies before it dials.
        initialize_process_timeout=120,
        num_idle_processes=1,
    )
    server.setup_fnc = _prewarm

    @server.rtc_session(agent_name=AGENT_NAME, on_session_end=on_session_end)
    async def entry(ctx: JobContext) -> None:
        meta = _parse_metadata(ctx.job.metadata)
        destination = assert_destination(meta.get("phone_number") or ALLOWED_DESTINATION)
        scenario = get_scenario(str(meta["scenario_id"]))
        call_id = str(meta.get("call_id") or scenario.id)
        caller = caller_number()
        require_env("SIP_OUTBOUND_TRUNK_ID")
        record = CallRecord(
            directory=calls_dir() / call_id,
            scenario=scenario,
            caller_number=caller,
            destination=destination,
            room_name=ctx.room.name,
        )
        record.directory.mkdir(parents=True, exist_ok=True)
        ACTIVE[ctx.room.name] = record
        ctx.log_context_fields = {"room": ctx.room.name, "call": call_id}

        done = asyncio.Event()
        finishing: asyncio.Task | None = None

        async def hangup_body(reason: str) -> None:
            with contextlib.suppress(Exception):
                await ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
            ctx.shutdown(reason)
            done.set()

        def hangup(reason: str) -> None:
            nonlocal finishing
            if record.finished:
                return
            record.finished = True
            record.hangup_reason = reason
            finishing = asyncio.create_task(hangup_body(reason), name="hangup")

        try:
            stt, llm, tts = _build_models()
            vad = ctx.proc.userdata["vad"]
            nc = _noise_cancellation()
            audio_input = (
                room_io.AudioInputOptions(noise_cancellation=nc)
                if nc is not None
                else room_io.AudioInputOptions()
            )
            session = AgentSession(
                stt=stt,
                llm=llm,
                tts=tts,
                vad=vad,
                aec_warmup_duration=0.0,
                user_away_timeout=20.0,
                max_tool_steps=6,
                stt_context_options={
                    "keyterms": [
                        "meloxicam",
                        "oxycodone",
                        "cortisone",
                        "UnitedHealthcare",
                        "workers comp",
                        "orthopedic",
                        "Alvarez",
                    ],
                },
                turn_handling={
                    "turn_detection": "vad",
                    # Wait out a receptionist's mid-sentence pause. Do not start a reply
                    # while they are still talking: their own final transcript cancels that
                    # in-flight reply, and the caller then stays silent for the rest of the call.
                    "endpointing": {"mode": "fixed", "min_delay": 0.65, "max_delay": 2.4},
                    "interruption": {
                        "enabled": True,
                        "mode": "vad",
                        "min_duration": 0.55,
                        "min_words": 2,
                        "resume_false_interruption": False,
                    },
                    "preemptive_generation": {
                        "enabled": False,
                        "preemptive_tts": False,
                    },
                },
            )

            @session.on("conversation_item_added")
            def on_item(ev) -> None:
                item = ev.item
                text = message_text(item)
                role = getattr(item, "role", "")
                if role == "assistant":
                    speaker = "PATIENT"
                elif role == "user":
                    speaker = "CLINIC"
                else:
                    return
                record.add_turn(speaker, text)

            @session.on("metrics_collected")
            def on_metrics(ev) -> None:
                metric = ev.metrics
                if hasattr(metric, "model_dump"):
                    record.metrics.append(metric.model_dump())
                else:
                    record.metrics.append({"repr": str(metric)})

            @session.on("error")
            def on_error(ev) -> None:
                err = getattr(ev, "error", ev)
                inner = getattr(err, "error", err)
                record.metrics.append(
                    {
                        "type": "pipeline_error",
                        "recoverable": getattr(err, "recoverable", None),
                        "error": f"{type(inner).__name__}: {inner}",
                    }
                )
                logger.error("pipeline error", extra={"error": f"{type(inner).__name__}: {inner}"})

            @ctx.room.on("participant_disconnected")
            def on_left(participant) -> None:
                if participant.identity == SIP_IDENTITY:
                    hangup("clinic hung up")

            # Warm the pipeline before the phone rings, but do not listen to ringback.
            await session.start(
                agent=Patient(scenario, ctx.room, record, hangup),
                room=ctx.room,
                room_options=room_io.RoomOptions(audio_input=audio_input),
                record=True,
            )
            session.input.set_audio_enabled(False)

            try:
                await asyncio.wait_for(
                    ctx.api.sip.create_sip_participant(
                        api.CreateSIPParticipantRequest(
                            sip_trunk_id=os.environ["SIP_OUTBOUND_TRUNK_ID"],
                            sip_call_to=destination,
                            sip_number=caller,
                            room_name=ctx.room.name,
                            participant_identity=SIP_IDENTITY,
                            participant_name=scenario.caller_name,
                            wait_until_answered=True,
                        )
                    ),
                    timeout=75,
                )
            except api.SipCallError as exc:
                record.error = f"SIP {exc.sip_status_code} {exc.sip_status}"
                hangup(record.error)
                await done.wait()
                return
            except Exception as exc:
                record.error = f"dial failed: {exc}"
                hangup(record.error)
                await done.wait()
                return

            await ctx.wait_for_participant(identity=SIP_IDENTITY)
            if session.room_io is not None:
                session.room_io.set_participant(SIP_IDENTITY)
            record.mark_answered()
            session.input.set_audio_enabled(True)
            logger.info("clinic answered", extra={"call": call_id})

            tasks = [
                asyncio.create_task(_nudge(session, scenario, record), name="nudge"),
                asyncio.create_task(_reply_if_silent(session, scenario, record), name="reply"),
                asyncio.create_task(_watchdog(session, scenario, record, hangup), name="watchdog"),
            ]
            if scenario.barge_in_after_s and scenario.barge_in_line:
                tasks.append(
                    asyncio.create_task(
                        _barge_in(session, scenario, record),
                        name="barge-in",
                    )
                )

            try:
                await done.wait()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if finishing is not None:
                    await finishing
        except Exception as exc:
            logger.exception("call failed")
            if record.error is None:
                record.error = str(exc)
            if not record.finished:
                record.finished = True
                record.hangup_reason = "error"
                ctx.shutdown("call failed")

    return server


async def _nudge(session, scenario: Scenario, record: CallRecord) -> None:
    await asyncio.sleep(9)
    if record.finished or record.clinic_turns():
        return
    await _maybe_await(
        session.generate_reply(
            instructions=scenario.opening_nudge,
            allow_interruptions=True,
        )
    )


async def _reply_if_silent(session, scenario: Scenario, record: CallRecord) -> None:
    """Speak if the clinic's turn never produced a patient reply.

    The clinic transcript can cancel the reply that it just triggered. After a
    few quiet seconds, drop that cancelled attempt and answer again.
    """
    seen_patient = 0
    while not record.finished:
        await asyncio.sleep(0.5)
        if record.finished or not record.clinic_turns():
            continue
        patient = len(record.patient_turns())
        if patient > seen_patient:
            seen_patient = patient
            continue
        if getattr(session, "agent_state", None) == "speaking":
            continue
        clinic_now = len(record.clinic_turns())
        await asyncio.sleep(4.5)
        if record.finished or len(record.patient_turns()) > seen_patient:
            seen_patient = len(record.patient_turns())
            continue
        if len(record.clinic_turns()) != clinic_now:
            continue
        if getattr(session, "agent_state", None) == "speaking":
            continue
        interrupt = getattr(session, "interrupt", None)
        if interrupt is not None:
            with contextlib.suppress(Exception):
                await _maybe_await(interrupt())
        logger.info("clinic heard, patient silent; answering again", extra={"call": record.directory.name})
        with contextlib.suppress(Exception):
            await _maybe_await(
                session.generate_reply(
                    instructions=(
                        "You have not answered the clinic's last utterance yet. "
                        "Reply now, out loud, in one or two short sentences. "
                        + scenario.opening_nudge
                    ),
                    allow_interruptions=True,
                )
            )
        seen_patient = len(record.patient_turns())


async def _barge_in(session, scenario: Scenario, record: CallRecord) -> None:
    await asyncio.sleep(scenario.barge_in_after_s or 0)
    if record.finished or not scenario.barge_in_line:
        return
    interrupt = getattr(session, "interrupt", None)
    if interrupt is not None:
        await _maybe_await(interrupt())
    await _maybe_await(session.say(scenario.barge_in_line, allow_interruptions=True))


async def _watchdog(session, scenario: Scenario, record: CallRecord, hangup) -> None:
    await asyncio.sleep(scenario.max_seconds)
    if record.finished:
        return
    with contextlib.suppress(Exception):
        await _maybe_await(
            session.say(
                "I have to get going. Thanks for the help, goodbye.",
                allow_interruptions=False,
            )
        )
    hangup("max duration")


server = _make_server()


if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)

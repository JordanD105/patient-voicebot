# Patient Caller

A Python phone bot that calls one clinic test line, plays a patient, and saves a recording and a transcript of each conversation.

The only number it will dial is `+18054398008`. There is no flag to change that.

## What you need

- Python 3.10 or newer
- A LiveKit Cloud project with [Inference](https://docs.livekit.io/agents/models/) enabled
- An outbound SIP trunk on that project, and one caller ID you will use for every call

A full set of calls is usually a few dollars of voice and model usage. Keep the receipts.

## Setup

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m livekit.agents download-files
```

`Set-ExecutionPolicy` here applies only to the current terminal. If activation is still blocked, skip it and call `.\.venv\Scripts\python.exe` instead of `python` in the commands below.

Fill in `.env`. `SIP_CALLER_NUMBER` is your caller ID, in E.164. The dialer prints that same value at the end of a batch. That is the number to put on the submission form.

`SIP_OUTBOUND_TRUNK_ID` comes from `lk sip outbound list` after the trunk exists. LiveKit's telephony docs cover Twilio, Telnyx, and Plivo trunks. Use one trunk and one caller ID for the whole batch.

## Run

Two terminals, from `patient-caller`, with the venv active:

```powershell
python -m livekit.agents start patient_caller/agent.py --dev
```

```powershell
python -m patient_caller dial --all
python -m patient_caller analyze
```

One shot, which starts the worker, places all 12 calls, stops the worker, and drafts the bug report:

```powershell
python -m patient_caller run
```

Repeat a single case after you change something:

```powershell
python -m patient_caller dial --scenario 05-sunday
```

Check the plan without spending money:

```powershell
python -m patient_caller dial --dry-run
python -m patient_caller check
```

Each call lands in `calls/<id>/`:

| File | Contents |
| --- | --- |
| `recording.ogg` | Stereo. Left is the clinic. Right is the patient. |
| `transcript.txt` | Both sides, with timestamps from answer |
| `done.json` | Whether both sides spoke, the caller ID, and any dial error |
| `metrics.jsonl` | Per-turn model timing, when the SDK emits it |

A useful call is a full conversation, about one to three minutes. The patient says goodbye, or the watchdog does, at the scenario cap (130–180 seconds).

## After the first calls

`BUGS.md` is the bug report. Each finding is one paragraph: Bug, Severity, Call, then Details. The Call value is a transcript path plus the timestamp of the clinic line. Listen to the `recording.ogg` in that same folder before you add an entry the transcript does not already show, such as talk-over or clipped words.

If the patient talks over the clinic, raise `endpointing.min_delay` in `patient_caller/agent.py`. If the patient waits too long after a finished sentence, lower it. If a scenario wanders, tighten that scenario's `steering` text and rerun only that id. The second run is saved as `calls/<id>-2/` so the first recording stays.

Set `NOISE_CANCELLATION=0` if the telephony noise filter fails to start. Set `PIPELINE=direct` and install `livekit-plugins-deepgram`, `livekit-plugins-openai`, and `livekit-plugins-cartesia` if you want your own provider keys instead of LiveKit Inference. Either way the models stay separate: speech-to-text, then the LLM, then text-to-speech.

## Tests

```powershell
python -m unittest tests.test_core
```

## How to submit the code

Create a new private git repository from this `patient-caller` folder, not from the folder that contains the challenge PDF. Invite the reviewer as a collaborator. Do not make the repository public.

Also send:

- Both recordings and transcripts (they are already under `calls/`)
- `BUGS.md` after you have listened
- The caller ID from `.env`, in E.164
- Two short videos of yourself: a walkthrough of the caller, and a screen recording of you prompting an AI through a real bug fix. Use your own voice and a webcam.

`ARCHITECTURE.md` explains the pipeline, the trunk, and the turn-taking choices.

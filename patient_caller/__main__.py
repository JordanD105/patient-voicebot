from __future__ import annotations

import sys


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    rest = sys.argv[2:]
    if command in {"dial", "run"}:
        from .dial import main as dial_main

        if command == "run":
            code = dial_main(["--with-worker", "--all", *rest])
            from .analyze import main as analyze_main

            try:
                analyze_main()
            except SystemExit as exc:
                print(exc)
            return code
        return dial_main(rest)
    if command == "analyze":
        from .analyze import main as analyze_main

        return analyze_main()
    if command == "check":
        return _check()
    if command in {"list", "dry-run"}:
        from .dial import main as dial_main

        return dial_main(["--list"] if command == "list" else ["--dry-run"])
    print(
        """Patient caller

  python -m patient_caller check
  python -m patient_caller list
  python -m patient_caller dial --dry-run
  python -m livekit.agents start patient_caller/agent.py --dev
  python -m patient_caller dial --all
  python -m patient_caller dial --scenario 05-sunday
  python -m patient_caller run
  python -m patient_caller analyze

run starts the worker, places every scenario, then stops the worker.
Use dev plus dial while you are changing the caller.
"""
    )
    return 0 if command == "help" else 1


def _check() -> int:
    from dotenv import load_dotenv

    from .config import ALLOWED_DESTINATION, ROOT, assert_destination

    load_dotenv(ROOT / ".env")
    assert_destination(ALLOWED_DESTINATION)
    missing = []
    import os

    for name in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "SIP_OUTBOUND_TRUNK_ID",
        "SIP_CALLER_NUMBER",
    ):
        if not os.getenv(name, "").strip():
            missing.append(name)
    if missing:
        print("Missing: " + ", ".join(missing))
        return 1
    try:
        import livekit.agents  # noqa: F401
    except Exception as exc:
        print(f"livekit-agents is not importable: {exc}")
        return 1
    print(f"Ready. Every call dials {ALLOWED_DESTINATION} only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

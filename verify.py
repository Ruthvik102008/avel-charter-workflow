"""Run the demo across fresh processes and check the recorded outcomes."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).with_name("charter.py")
REQUEST_ID = "REQ-1042"


def run(state_dir, command, response=""):
    print(f"\n$ python charter.py {command} {REQUEST_ID}", flush=True)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--state-dir", state_dir, command, REQUEST_ID],
        capture_output=True,
        text=True,
        input=response,
        check=True,
    )
    print(result.stdout, end="")
    return result.stdout


with TemporaryDirectory() as state_dir:
    checkpoint = Path(state_dir) / f"{REQUEST_ID}.json"

    started = run(state_dir, "start")
    assert started.index("[FAILED") < started.index("[RETRY") < started.index("[PAUSED")
    pending = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert pending["status"] == "AWAITING_APPROVAL"
    assert "receipt" not in pending

    declined = run(state_dir, "approve", "no\n")
    assert "Approval withheld" in declined
    pending = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert pending["status"] == "AWAITING_APPROVAL"
    assert "receipt" not in pending

    approved = run(state_dir, "approve", "APPROVE\n")
    quote_id = pending["quote"]["id"]
    assert f"Human approved {quote_id}" in approved
    assert f"Mock send completed: MOCK-{quote_id}" in approved

    replay = run(state_dir, "approve", "APPROVE\n")
    assert "already complete" in replay
    history = run(state_dir, "status")
    assert "Status: COMPLETE" in history
    assert history.count("Mock send completed") == 1
    print("\nVerified timeout recovery, approval across processes, and repeat approval.")

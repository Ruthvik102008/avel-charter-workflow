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

with TemporaryDirectory() as state_dir:
    run(state_dir, "start")
    checkpoint = Path(state_dir) / f"{REQUEST_ID}.json"
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    # Reproduce a request saved by the previous release.
    state["quote"].pop("departure")
    state["quote"].pop("revision")
    checkpoint.write_text(json.dumps(state), encoding="utf-8")
    args = [sys.executable, str(SCRIPT), "--state-dir", state_dir]

    # Leave a CLI operator at the approval prompt while another process revises the trip.
    operator = subprocess.Popen(
        [*args, "approve", REQUEST_ID], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        original = operator.stdout.readline()
        departure = operator.stdout.readline()
        prompt = operator.stdout.readline()
        assert f"{REQUEST_ID}-Q1" in original and "09:00" in departure and "APPROVE" in prompt

        revision = subprocess.run(
            [*args, "revise", REQUEST_ID, "--quote-id", f"{REQUEST_ID}-Q1", "--departure", "11:30"],
            capture_output=True, text=True, check=True, timeout=15,
        )
        print(revision.stdout, end="")
        output, _ = operator.communicate("APPROVE\n", timeout=15)
        assert operator.returncode == 1 and "no longer current" in output
        print(output, end="")
    finally:
        if operator.poll() is None:
            operator.kill()
            operator.communicate()

    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert state["status"] == "AWAITING_APPROVAL"
    assert state["quote"]["id"] == f"{REQUEST_ID}-Q2"
    assert state["quote"]["departure"] == "11:30"
    assert state["superseded_quotes"][0]["id"] == f"{REQUEST_ID}-Q1"
    assert "receipt" not in state
    approved = run(state_dir, "approve", "APPROVE\n")
    assert f"Mock send completed: MOCK-{REQUEST_ID}-Q2" in approved
    print("\nVerified revision of an existing draft and rejection of stale CLI approval.")

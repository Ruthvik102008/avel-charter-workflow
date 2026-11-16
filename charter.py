"""Run a mocked charter workflow with a durable approval checkpoint."""

import argparse
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, state):
    """Replace the checkpoint only after writing and closing the new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(state, temporary, indent=2)
            temporary.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def record(state, label, message):
    line = f"[{label:<9}] {message}"
    state["history"].append(line)
    print(line)


def check_availability(attempt):
    if attempt == 1:
        raise TimeoutError("Temporary availability API timeout")
    return {"type": "Citation XLS+", "tail": "N104AV", "price_usd": 18_500}


def prepare_quote(request_id, aircraft):
    return {
        "id": f"{request_id}-Q1",
        "route": "Oakland (OAK) to Las Vegas (LAS)",
        "aircraft": f"{aircraft['type']} ({aircraft['tail']})",
        "price_usd": aircraft["price_usd"],
    }


def send_quote(quote):
    """Mock delivery. Return a receipt for the approved quote."""
    return f"MOCK-{quote['id']}"


def start(path, request_id):
    if path.exists():
        print(f"{request_id} already exists. Use the status command.")
        return 1

    state = {"request_id": request_id, "status": "RUNNING", "history": []}
    record(state, "START", f"Workflow {request_id}")
    record(state, "RUNNING", "Check aircraft availability")
    for attempt in (1, 2):
        try:
            aircraft = check_availability(attempt)
            break
        except TimeoutError as error:
            record(state, "FAILED", str(error))
            if attempt == 1:
                record(state, "RETRY", "Check aircraft availability (attempt 2)")
    else:
        state["status"] = "FAILED"
        record(state, "FAILED", "Availability check exhausted both attempts")
        save(path, state)
        return 1

    record(state, "SUCCESS", f"Aircraft available: {aircraft['tail']}")
    state["quote"] = prepare_quote(request_id, aircraft)
    record(state, "SUCCESS", f"Prepared draft {state['quote']['id']}")
    state["status"] = "AWAITING_APPROVAL"
    record(state, "PAUSED", "Waiting for explicit approval")
    save(path, state)
    return 0


def approve(path):
    state = load(path)
    if state["status"] == "COMPLETE":
        print("Workflow already complete. Receipt:", state["receipt"])
        return 0
    if state["status"] != "AWAITING_APPROVAL":
        print(f"Cannot approve a workflow in state {state['status']}.")
        return 1

    quote = state["quote"]
    print(f"{quote['id']} | {quote['route']} | {quote['aircraft']} | USD {quote['price_usd']:,}")
    print("Type APPROVE to send this quote (mock):")
    try:
        response = input()
    except EOFError:
        response = ""

    if response.strip() != "APPROVE":
        record(state, "PAUSED", "Approval withheld. Quote remains pending.")
        save(path, state)
        return 0

    state["status"] = "SENDING"
    record(state, "APPROVED", f"Human approved {quote['id']}")
    record(state, "RUNNING", "Send approved quote (mock)")
    save(path, state)

    state["receipt"] = send_quote(quote)
    record(state, "SUCCESS", f"Mock send completed: {state['receipt']}")
    state["status"] = "COMPLETE"
    record(state, "COMPLETE", "Workflow finished")
    save(path, state)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path(".charter-state"))
    parser.add_argument("command", choices=("start", "approve", "status"))
    parser.add_argument("request_id")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.request_id):
        parser.error("request ID must be 1-64 letters, numbers, dashes, or underscores")

    path = args.state_dir / f"{args.request_id}.json"
    try:
        if args.command == "start":
            return start(path, args.request_id)
        if args.command == "approve":
            return approve(path)
        state = load(path)
        print(f"Status: {state['status']}")
        print("\n".join(state["history"]))
        return 0
    except FileNotFoundError:
        print(f"Could not access the checkpoint for {args.request_id}.")
    except (OSError, ValueError) as error:
        print(f"Checkpoint error: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run a mocked charter workflow with a durable approval checkpoint."""

import argparse
import json
import re
import sys
from contextlib import contextmanager
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


DEFAULT_DEPARTURE = "09:00"


@contextmanager
def lock_request(path):
    """Serialize writes to a request across CLI and dashboard processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        lock.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def valid_departure(value):
    return isinstance(value, str) and bool(re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value))


def check_availability(attempt, departure):
    if attempt == 1:
        raise TimeoutError("Temporary availability API timeout")
    price = 18_500 if departure < "11:00" else 19_250
    return {"type": "Citation XLS+", "tail": "N104AV", "price_usd": price}


def prepare_quote(request_id, aircraft, departure, revision):
    return {
        "id": f"{request_id}-Q{revision}",
        "revision": revision,
        "route": "Oakland (OAK) to Las Vegas (LAS)",
        "departure": departure,
        "aircraft": f"{aircraft['type']} ({aircraft['tail']})",
        "price_usd": aircraft["price_usd"],
    }


def send_quote(quote):
    """Mock delivery. Return a receipt for the approved quote."""
    return f"MOCK-{quote['id']}"


def build_draft(path, state, departure, revision):
    record(state, "RUNNING", f"Check aircraft availability for {departure} Pacific time")
    for attempt in (1, 2):
        try:
            aircraft = check_availability(attempt, departure)
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
    state["quote"] = prepare_quote(state["request_id"], aircraft, departure, revision)
    record(state, "SUCCESS", f"Prepared draft {state['quote']['id']}")
    state["status"] = "AWAITING_APPROVAL"
    record(state, "PAUSED", "Waiting for explicit approval")
    save(path, state)
    return 0


def start(path, request_id):
    with lock_request(path):
        if path.exists():
            print(f"{request_id} already exists. Use the status command.")
            return 1

        state = {"request_id": request_id, "status": "RUNNING", "history": []}
        record(state, "START", f"Workflow {request_id}")
        return build_draft(path, state, DEFAULT_DEPARTURE, revision=1)


def revise(path, expected_quote_id, departure):
    with lock_request(path):
        state = load(path)
        if state["status"] != "AWAITING_APPROVAL":
            print(f"Cannot revise a workflow in state {state['status']}.")
            return 1
        quote = state["quote"]
        if not matches_quote(state, expected_quote_id):
            return 1
        previous_departure = quote.get("departure", DEFAULT_DEPARTURE)
        if departure == previous_departure:
            print("Choose a different departure time.")
            return 1

        state.setdefault("superseded_quotes", []).append(state.pop("quote"))
        record(state, "REVISED", f"Departure changed from {previous_departure} to {departure} Pacific time")
        record(state, "SUPERSEDED", f"{quote['id']} was superseded")
        return build_draft(path, state, departure, quote.get("revision", 1) + 1)


def matches_quote(state, expected_quote_id):
    current_id = state.get("quote", {}).get("id")
    if expected_quote_id == current_id:
        return True
    if current_id:
        print(f"Quote {expected_quote_id} is no longer current. Review {current_id} before continuing.")
    else:
        print(f"Quote {expected_quote_id} is no longer current. No draft is available to approve.")
    return False


def approval_result(state):
    if state["status"] == "AWAITING_APPROVAL":
        return None
    if state["status"] == "COMPLETE":
        print("Workflow already complete. Receipt:", state["receipt"])
        return 0
    print(f"Cannot approve a workflow in state {state['status']}.")
    return 1


def approve(path, expected_quote_id=None):
    state = load(path)
    if expected_quote_id is not None and not matches_quote(state, expected_quote_id):
        return 1
    result = approval_result(state)
    if result is not None:
        return result

    quote = state["quote"]
    departure = quote.get("departure", DEFAULT_DEPARTURE)
    print(f"{quote['id']} | {quote['route']} | {quote['aircraft']} | USD {quote['price_usd']:,}")
    print(f"Departure: {departure} Pacific time")
    print("Type APPROVE to send this quote (mock):", flush=True)
    try:
        response = input()
    except EOFError:
        response = ""

    with lock_request(path):
        state = load(path)
        if not matches_quote(state, quote["id"]):
            return 1
        result = approval_result(state)
        if result is not None:
            return result

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
    parser.add_argument("command", choices=("start", "approve", "revise", "status"))
    parser.add_argument("request_id")
    parser.add_argument("--quote-id", help="ID of the displayed draft")
    parser.add_argument("--departure", help="New departure time in HH:MM Pacific time")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.request_id):
        parser.error("request ID must be 1-64 letters, numbers, dashes, or underscores")

    if args.command == "revise" and (not valid_departure(args.departure) or not args.quote_id):
        parser.error("revise requires --departure HH:MM and --quote-id")

    path = args.state_dir / f"{args.request_id}.json"
    try:
        if args.command == "start":
            return start(path, args.request_id)
        if args.command == "approve":
            return approve(path, args.quote_id)
        if args.command == "revise":
            return revise(path, args.quote_id, args.departure)
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

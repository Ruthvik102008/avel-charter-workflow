# Charter workflow

A Python workflow engine and local browser dashboard for a fictional charter inquiry. It checks aircraft availability, prepares a quote, waits for human approval, and records a mock delivery receipt.

## Run the browser dashboard

From the repository root, run:

```sh
python serve.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and select **Run demo**. Review the timeout and retry in Activity, then choose **Keep pending** or **Approve & mock send**. After sending, **Repeat approval check** verifies that the existing receipt is returned. The browser restores the last opened request on refresh. You can also open a request created by the CLI using its request ID.

The dashboard requires only Python. It invokes the same CLI and uses the same `.charter-state/` directory. Press Ctrl+C to stop the server. If port 8000 is in use, run `python serve.py --port 8001` and open the address printed in the terminal.

## Run the CLI

Use Python 3.9 or newer. Run these commands from the repository root.

```sh
python charter.py start REQ-1042
python charter.py approve REQ-1042
python charter.py status REQ-1042
```

The availability mock times out once and succeeds on its second attempt. At the approval prompt, type `APPROVE` to approve the displayed quote. Run the approval command again to see the existing receipt, or use a fresh request ID to start another run.

Run `python verify.py` for a narrated demo in a temporary directory. It checks that the first attempt fails, a second process can load the saved draft, declining leaves the quote pending, approval completes the mock send, and repeating approval leaves one send in the history.

## Architecture

Each request has a JSON checkpoint in `.charter-state/` with its status, draft, event history, and eventual mock receipt. The availability result supplies the aircraft and price for the quote. The quote is saved before the CLI exits, so a later process can display and send the same draft after explicit approval. The engine retries the availability timeout once.

**Key decision.** The CLI persists `SENDING` before calling the send tool. If the process stops there, another approval command will refuse to send automatically because the prior outcome may be ambiguous.

**Limitation.** This is a sequential local CLI. A production sender would need coordinated workers and a provider idempotency key, such as the quote ID, to safely reconcile an interrupted send.

## Verified execution

Excerpt from the [GitHub Actions demo](https://github.com/Ruthvik102008/avel-charter-workflow/actions/runs/43983368013/job/133705193837).

```text
$ python charter.py start REQ-1042
[START    ] Workflow REQ-1042
[RUNNING  ] Check aircraft availability
[FAILED   ] Temporary availability API timeout
[RETRY    ] Check aircraft availability (attempt 2)
[SUCCESS  ] Aircraft available: N104AV
[SUCCESS  ] Prepared draft REQ-1042-Q1
[PAUSED   ] Waiting for explicit approval

$ python charter.py approve REQ-1042
REQ-1042-Q1 | Oakland (OAK) to Las Vegas (LAS) | Citation XLS+ (N104AV) | USD 18,500
Type APPROVE to send this quote (mock):
[PAUSED   ] Approval withheld. Quote remains pending.

$ python charter.py approve REQ-1042
REQ-1042-Q1 | Oakland (OAK) to Las Vegas (LAS) | Citation XLS+ (N104AV) | USD 18,500
Type APPROVE to send this quote (mock):
[APPROVED ] Human approved REQ-1042-Q1
[RUNNING  ] Send approved quote (mock)
[SUCCESS  ] Mock send completed: MOCK-REQ-1042-Q1
[COMPLETE ] Workflow finished

$ python charter.py approve REQ-1042
Workflow already complete. Receipt: MOCK-REQ-1042-Q1
```

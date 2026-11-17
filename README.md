# Charter Workflow

Avel Aero engineering assessment. A Python execution engine runs a fictional Oakland-to-Las Vegas charter inquiry through four steps: check aircraft availability, prepare a quote, wait for human approval, and deliver the approved quote through a mock sender. Availability, pricing, and delivery are all simulated.

## Run locally

Use Python 3.9 or newer. The CLI and dashboard use the Python standard library.

```sh
git clone https://github.com/Ruthvik102008/avel-charter-workflow.git
cd avel-charter-workflow
python charter.py start REQ-1042
```

The first availability attempt times out by design. The second succeeds, and the CLI saves a draft and exits. To review and approve the saved draft, run:

```sh
python charter.py approve REQ-1042
```

Type `APPROVE` to authorize the mock send. Any other input leaves the draft pending. Use `python charter.py status REQ-1042` to see the current status and full history. Repeating approval after completion returns the existing receipt. Use a fresh request ID to repeat the demo.

### Browser demo

Run `python serve.py` from the repo root and open [http://127.0.0.1:8000](http://127.0.0.1:8000). Click **Run demo**, review the quote and Activity, then choose **Keep pending** or **Approve & mock send**. Keep the terminal open while using the dashboard. If port 8000 is in use, try `python serve.py --port 8001`.

**Refresh a request.** Refresh the page to reopen the last request viewed in that browser. The dashboard loads the latest saved quote, approval status, activity, and any mock receipt from the server. A pending quote still requires explicit approval after refresh.

To see stale approval protection, open the same pending request in two tabs. In the first, choose **Revise trip**, set departure to **11:30 Pacific**, and click **Recheck and requote**. In the second, try to approve the original draft. The approval is blocked and the replacement is shown for a fresh decision.

## Architecture

- **Engine and state.** [`charter.py`](charter.py) passes the mock aircraft and price to quote preparation, retries a temporary timeout once, and records each transition. It saves request status, drafts, history, and the receipt in a per-request JSON checkpoint under `.charter-state/`. The [dashboard server](serve.py) invokes the same CLI and reads the same checkpoints.
- **Key decision.** Persist the exact version of the draft before asking for approval. When an operator confirms, the engine checks the quote ID under a per-request lock before entering `SENDING`. A revision supersedes the prior draft and requires fresh approval.
- **Limitation.** If delivery is interrupted after `SENDING` is saved, the engine stops for manual review. A production integration would need a provider idempotency key and reconciliation to resume an ambiguous send safely.

## Verified execution

Run `python verify.py` to reproduce the CLI demo in temporary storage. The excerpt below is from the [passing GitHub Actions run](https://github.com/Ruthvik102008/avel-charter-workflow/actions/runs/43986922813), which also verifies stale approval in two browser tabs and from the Windows CLI.

```text
$ python charter.py start REQ-1042
[START    ] Workflow REQ-1042
[RUNNING  ] Check aircraft availability for 09:00 Pacific time
[FAILED   ] Temporary availability API timeout
[RETRY    ] Check aircraft availability (attempt 2)
[SUCCESS  ] Aircraft available: N104AV
[SUCCESS  ] Prepared draft REQ-1042-Q1
[PAUSED   ] Waiting for explicit approval

$ python charter.py approve REQ-1042
REQ-1042-Q1 | Oakland (OAK) to Las Vegas (LAS) | Citation XLS+ (N104AV) | USD 18,500
Departure: 09:00 Pacific time
Type APPROVE to send this quote (mock):
[PAUSED   ] Approval withheld. Quote remains pending.

$ python charter.py approve REQ-1042
REQ-1042-Q1 | Oakland (OAK) to Las Vegas (LAS) | Citation XLS+ (N104AV) | USD 18,500
Departure: 09:00 Pacific time
Type APPROVE to send this quote (mock):
[APPROVED ] Human approved REQ-1042-Q1
[RUNNING  ] Send approved quote (mock)
[SUCCESS  ] Mock send completed: MOCK-REQ-1042-Q1
[COMPLETE ] Workflow finished

$ python charter.py approve REQ-1042
Workflow already complete. Receipt: MOCK-REQ-1042-Q1
```

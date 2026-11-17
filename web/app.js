"use strict";

const get = (id) => document.getElementById(id);
const storageKey = "charter-workflow-request";
const steps = [...document.querySelectorAll(".steps li")];
const controls = [
  "start", "request-id", "open-request", "approve", "withhold", "revise",
  "departure", "save-revision", "replay",
].map(get);
const money = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 0,
});
const statuses = {
  AWAITING_APPROVAL: ["Awaiting approval", "current"],
  COMPLETE: ["Complete", "done"],
  FAILED: ["Failed", "error"],
  RUNNING: ["Running", "current"],
  SENDING: ["Send in progress", "current"],
};
const eventTones = {
  FAILED: "error", RETRY: "current", PAUSED: "current",
  SUCCESS: "done", APPROVED: "done", COMPLETE: "done", REVISED: "current",
};

let current = null;

function remember(id) {
  try {
    if (id) localStorage.setItem(storageKey, id);
    return localStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

function feedback(text = "", tone = "info") {
  get("feedback").textContent = text;
  get("feedback").dataset.tone = tone;
  get("feedback").hidden = !text;
}

function setStep(index, label, tone = "") {
  const step = steps[index];
  step.dataset.tone = tone;
  step.querySelector(".step-state").textContent = label;
  if (tone === "current") step.setAttribute("aria-current", "step");
  else step.removeAttribute("aria-current");
}

function renderSteps(state) {
  steps.forEach((_, index) => setStep(index, "Queued"));
  if (!state) return;

  if (state.status === "FAILED") {
    setStep(0, "Attempts exhausted", "error");
    return;
  }
  if (!state.quote) {
    setStep(0, "In progress", "current");
    return;
  }

  const retried = state.history.some((line) => line.startsWith("[RETRY "));
  setStep(0, retried ? "Recovered on retry" : "Available", "done");
  setStep(1, "Draft prepared", "done");
  if (state.status === "AWAITING_APPROVAL") {
    setStep(2, "Awaiting approval", "current");
    setStep(3, "Blocked until approval");
  } else {
    setStep(2, "Approved", "done");
    const complete = state.status === "COMPLETE";
    setStep(3, complete ? "Mock sent" : "Outcome uncertain", complete ? "done" : "current");
  }
}

function renderHistory(events) {
  get("event-count").textContent = events.length + (events.length === 1 ? " event" : " events");
  get("empty-history").hidden = events.length > 0;
  const entries = [...events].reverse().map((line) => {
    const match = line.match(/^\[([A-Z]+)\s*\]\s*(.*)$/);
    const type = match ? match[1] : "EVENT";
    const message = match ? match[2] : line;
    const item = document.createElement("li");
    const dot = document.createElement("span");
    const text = document.createElement("div");
    const label = document.createElement("span");
    const description = document.createElement("p");

    item.dataset.tone = eventTones[type] || "";
    dot.className = "event-dot";
    dot.setAttribute("aria-hidden", "true");
    label.className = "event-label";
    label.textContent = type;
    description.className = "event-message";
    description.textContent = message;
    text.append(label, description);
    item.append(dot, text);
    return item;
  });
  get("history").replaceChildren(...entries);
}

function showRevision(open) {
  get("revision-form").hidden = !open;
  get("revise").setAttribute("aria-expanded", String(open));
}

function render(state) {
  const priorQuoteId = current?.quote?.id;
  current = state;
  const status = state?.status;
  const quote = state?.quote;
  const pending = status === "AWAITING_APPROVAL";
  const complete = status === "COMPLETE";
  const [label, tone] = statuses[status] || ["Ready", ""];
  get("request-label").textContent = state?.request_id || "No request selected";
  get("status").textContent = label;
  get("status").dataset.tone = tone;
  get("quote-details").hidden = !quote;
  if (quote) {
    get("aircraft").textContent = quote.aircraft;
    get("price").textContent = money.format(quote.price_usd);
    get("quote-id").textContent = quote.id;
    get("quote-departure").textContent = quote.departure || "09:00";
  }
  if (!pending || priorQuoteId !== quote?.id) showRevision(false);

  const copy = {
    AWAITING_APPROVAL: ["Review the saved draft", "The quote stays pending until you explicitly approve it."],
    COMPLETE: ["Mock send complete", "Receipt " + (state?.receipt || "")],
    FAILED: ["Availability check failed", "Open the activity history to review both attempts."],
    SENDING: ["Send outcome needs review", "The workflow saved the approval. Check the prior outcome before trying another send."],
  };
  const [heading, description] = copy[status] || [
    "Ready to run",
    "Run the demo to simulate an availability timeout, recover on retry, and prepare a draft.",
  ];
  get("approval-heading").textContent = heading;
  get("approval-copy").textContent = description;
  get("approval-actions").hidden = !pending;
  get("replay").hidden = !complete;
  renderSteps(state);
  renderHistory(state?.history || []);
  if (state) {
    get("request-id").value = state.request_id;
    remember(state.request_id);
  }
}

async function request(path, data) {
  controls.forEach((control) => { control.disabled = true; });
  feedback();
  try {
    const options = data ? {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    } : {};
    const response = await fetch(path, options);
    const result = await response.json();
    if (result.state) render(result.state);
    if (!response.ok) throw new Error(result.error || "The workflow request failed.");
    return result;
  } catch (error) {
    feedback(error.message, "error");
    return null;
  } finally {
    controls.forEach((control) => { control.disabled = false; });
  }
}

async function approve(decision) {
  if (!current) return;
  const wasComplete = current.status === "COMPLETE";
  const result = await request("/api/approve", {
    id: current.request_id, quote_id: current.quote.id, decision,
  });
  if (result && wasComplete) feedback(result.output);
}

function openRequest(id) {
  return request("/api/workflow?id=" + encodeURIComponent(id));
}

get("start").addEventListener("click", () => request("/api/start", {}));
get("approve").addEventListener("click", () => approve("approve"));
get("withhold").addEventListener("click", () => approve("withhold"));
get("revise").addEventListener("click", () => {
  const open = get("revision-form").hidden;
  showRevision(open);
  if (open) {
    get("departure").value = current.quote.departure || "09:00";
    get("departure").focus();
  }
});
get("revision-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = await request("/api/revise", {
    id: current.request_id, quote_id: current.quote.id, departure: get("departure").value,
  });
  if (result?.state.status === "AWAITING_APPROVAL") {
    feedback("Revised quote is ready for a new approval.");
    get("approve").focus();
  }
});
get("replay").addEventListener("click", () => approve("approve"));
get("lookup").addEventListener("submit", (event) => {
  event.preventDefault();
  openRequest(get("request-id").value.trim());
});

render(null);
const lastRequest = remember();
if (lastRequest) openRequest(lastRequest);

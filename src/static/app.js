"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  token: null,
  actor: null,
  config: null,
  workflows: [],
  selected: null,
  cursor: null,
  busy: false,
  generation: 0,
};
const active = new Set(["queued", "running", "queued_execution", "executing"]);
const labels = {
  queued: "Queued",
  running: "Collecting evidence",
  awaiting_approval: "Awaiting approval",
  queued_execution: "Approved · queued",
  executing: "Executing",
  blocked: "Policy blocked",
  completed: "Completed",
  completed_with_warning: "Completed · warning",
  failed: "Needs attention",
  rejected: "Rejected",
  reviewed: "Reviewed · no action",
};
const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const date = (value) =>
  new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const badge = (status) =>
  `<span class="badge ${Object.hasOwn(labels, status) ? status : ""}">${escapeHtml(labels[status] || status)}</span>`;
const chips = (items) =>
  `<div class="chips">${items.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("")}</div>`;

function notify(message = "") {
  $("#message").textContent = message;
  $("#message").hidden = !message;
}

async function api(data = null, query = "") {
  const response = await fetch(`/api${query}`, {
    method: data ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${state.token}`,
      ...(data ? { "Content-Type": "application/json" } : {}),
    },
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
  const result = await response.json();
  if (response.status === 401) {
    signout();
    throw new Error("Your session expired. Sign in again to continue.");
  }
  if (!response.ok)
    throw new Error(
      result.error || result.message || "The request could not be completed.",
    );
  return result;
}

function signout() {
  state.generation++;
  state.token = null;
  state.actor = null;
  state.workflows = [];
  state.selected = null;
  state.cursor = null;
  $("#login-form").reset();
  $("#identity").textContent = "Not signed in";
  $("#signout").hidden = true;
  $("#login-panel").hidden = false;
  $("#new-request").disabled = true;
  $("#refresh").disabled = true;
  $("#detail-title").textContent = "A clear path to a decision";
  $("#detail-body").innerHTML =
    '<div class="empty-state"><h3>Select a request</h3><p>Sign in to view evidence and the audit trail.</p></div>';
  renderQueue();
}

async function signedIn(token) {
  state.token = token;
  try {
    await refresh();
    $("#login-panel").hidden = true;
    $("#signout").hidden = false;
    $("#new-request").disabled = false;
    $("#refresh").disabled = false;
    $("#identity").textContent =
      `${state.actor.name} · ${state.actor.roles.includes("ops_approver") ? "Approver" : "Requester"}`;
    $("#login-form").reset();
    notify();
  } catch (error) {
    signout();
    throw error;
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  $("#login-button").disabled = true;
  try {
    const response = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.elements.username.value.trim(),
        password: form.elements.password.value,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Sign-in failed.");
    await signedIn(result.accessToken);
  } catch (error) {
    notify(error.message);
  } finally {
    $("#login-button").disabled = false;
  }
});
$("#signout").addEventListener("click", async () => {
  const token = state.token;
  signout();
  notify();
  if (!state.config?.localDemo && token) {
    try {
      const response = await fetch("/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok)
        throw new Error("Sign-out could not revoke the session.");
    } catch {
      notify(
        "Signed out locally. The server session will expire within 15 minutes.",
      );
    }
  }
});

function renderQueue() {
  const workflows = state.workflows;
  $("#count-total").textContent = workflows.length;
  $("#nav-count").textContent = workflows.length;
  $("#count-pending").textContent = workflows.filter(
    (w) => w.status === "awaiting_approval",
  ).length;
  $("#count-blocked").textContent = workflows.filter(
    (w) => w.status === "blocked",
  ).length;
  $("#count-done").textContent = workflows.filter((w) =>
    w.status.startsWith("completed"),
  ).length;
  const search = $("#search").value.toLowerCase();
  const filter = $("#filter").value;
  const visible = workflows.filter(
    (w) =>
      (filter === "all" ||
        w.status === filter ||
        (filter === "completed" && w.status === "completed_with_warning")) &&
      `${w.employee_id} ${w.request_id} ${w.evidence?.employee?.name || ""}`
        .toLowerCase()
        .includes(search),
  );
  $("#workflow-list").innerHTML = visible.length
    ? visible
        .map((w) => {
          const name = w.evidence?.employee?.name || w.employee_id;
          const initials = name
            .split(" ")
            .map((part) => part[0])
            .slice(0, 2)
            .join("");
          return `<button class="workflow-row ${state.selected?.workflow_id === w.workflow_id ? "selected" : ""}" data-workflow="${escapeHtml(w.workflow_id)}" aria-pressed="${state.selected?.workflow_id === w.workflow_id}"><span class="employee-avatar">${escapeHtml(initials)}</span><span class="row-main"><strong>${escapeHtml(name)}</strong><small>${escapeHtml(w.employee_id)} · ${escapeHtml(w.request_id)}</small></span><span class="row-end">${badge(w.status)}<time>${escapeHtml(date(w.created_at))}</time></span></button>`;
        })
        .join("")
    : '<div class="empty-state"><span class="empty-icon" aria-hidden="true">▤</span><h3>No requests to show</h3><p>Create a request, adjust your filters, or load older requests.</p></div>';
  $("#load-more").hidden = !state.cursor;
}

function renderDetail(item) {
  state.selected = item;
  $("#detail-title").textContent =
    item.evidence?.employee?.name || item.employee_id;
  const evidence = item.evidence;
  const pending = item.pending_action;
  const canApprove =
    state.actor?.roles.includes("ops_approver") &&
    state.actor.id !== item.owner_id;
  let html = `<div class="detail-summary"><div><h3>${escapeHtml(item.employee_id)}</h3><code>${escapeHtml(item.request_id)}</code></div>${badge(item.status)}</div><p class="muted">Requested by ${escapeHtml(item.requester_name)} · ${escapeHtml(date(item.created_at))}</p><p class="muted">${escapeHtml(item.reason)}</p>`;
  if (item.error)
    html += `<div class="policy-warning">${escapeHtml(item.error)}</div>`;
  if (item.final_response)
    html += `<div class="success-box">${escapeHtml(item.final_response)}</div>`;
  if (evidence) {
    html += `<div class="detail-section"><h3 class="section-label">Employee & assigned assets</h3><div class="facts"><div><span>Department</span>${escapeHtml(evidence.employee.department || "Unknown")}</div><div><span>Employment status</span>${escapeHtml(evidence.employee.employment_status || "Unknown")}</div></div><p class="muted">Assigned systems</p>${chips(evidence.assets.systems)}<p class="muted">${escapeHtml((evidence.assets.open_asset_actions || []).join(" · "))}</p></div>`;
    html += `<div class="detail-section"><h3 class="section-label">Incident ownership</h3>${evidence.incidents.length ? evidence.incidents.map((i) => `<div class="policy-warning"><strong>${escapeHtml(i.incident_id)} · ${escapeHtml(i.severity)}</strong><br>${escapeHtml(i.summary)}<br>Status: ${escapeHtml(i.status)}</div>`).join("") : '<p class="muted">✓ No open incidents in the fixture records.</p>'}</div>`;
  }
  if (pending) {
    html += `<div class="action-box"><h3 class="section-label">${item.status === "awaiting_approval" ? "Proposed access change" : "Recorded action"}</h3><p>Disable assigned access for <strong>${escapeHtml(pending.input.employee_id)}</strong></p>${chips(pending.input.systems)}<p>${escapeHtml(pending.input.reason)}</p><code>${escapeHtml(pending.action_id)}</code>`;
    if (item.status === "awaiting_approval")
      html += canApprove
        ? '<p class="muted">Approval applies only to the exact employee and systems shown above. Policy is checked again before execution.</p><div class="action-buttons"><button class="primary" data-command="approve">Approve simulation</button><button class="danger" data-command="reject">Reject</button></div>'
        : '<p class="muted">Waiting for a different user with the approver role.</p>';
    html += "</div>";
  }
  if (item.action_result)
    html += `<div class="detail-section"><h3 class="section-label">Simulation receipt</h3><code>${escapeHtml(item.action_result.execution_id)}</code><p class="muted">No external account was modified.</p></div>`;
  if (active.has(item.status) || item.status === "failed")
    html +=
      '<div class="detail-section"><button class="secondary" data-command="resume">Resume / retry delivery</button><p class="muted">Active work cannot be restarted until its 150-second lease expires. Up to three worker attempts are allowed.</p></div>';
  html += `<div class="detail-section"><h3 class="section-label">Audit trail</h3><ol class="trace">${item.trace.map((entry) => `<li>${escapeHtml(entry.event.replaceAll("_", " "))}<time>${escapeHtml(date(entry.timestamp))}</time>${entry.detail ? `<small>${escapeHtml(entry.detail)}</small>` : ""}${entry.actor_id ? `<small>Actor: ${escapeHtml(entry.actor_id)}</small>` : ""}</li>`).join("")}</ol></div>`;
  $("#detail-body").innerHTML = html;
  renderQueue();
}

function merge(item) {
  const index = state.workflows.findIndex(
    (w) => w.workflow_id === item.workflow_id,
  );
  if (index < 0) state.workflows.push(item);
  else state.workflows[index] = item;
  state.workflows.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

async function refresh(append = false) {
  const generation = state.generation;
  const result = await api(
    null,
    append && state.cursor ? `?cursor=${encodeURIComponent(state.cursor)}` : "",
  );
  if (generation !== state.generation) return;
  state.actor = result.actor;
  state.cursor = result.cursor;
  if (!append) state.workflows = [];
  result.workflows.forEach(merge);
  // Detail reads are strongly consistent; the queue index may lag briefly.
  if (state.selected) {
    const item = await api(
      null,
      `?workflow_id=${encodeURIComponent(state.selected.workflow_id)}`,
    );
    if (generation !== state.generation) return;
    merge(item);
    renderDetail(item);
  } else if (state.workflows.length) renderDetail(state.workflows[0]);
  renderQueue();
}

async function safe(task) {
  if (state.busy) return;
  state.busy = true;
  notify();
  try {
    await task();
  } catch (error) {
    notify(error.message);
  } finally {
    state.busy = false;
  }
}

$("#refresh").addEventListener("click", () => safe(() => refresh()));
$("#load-more").addEventListener("click", () => safe(() => refresh(true)));
$("#search").addEventListener("input", renderQueue);
$("#filter").addEventListener("change", renderQueue);
$("#workflow-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-workflow]");
  if (button)
    safe(async () => {
      const generation = state.generation;
      const item = await api(
        null,
        `?workflow_id=${encodeURIComponent(button.dataset.workflow)}`,
      );
      if (generation === state.generation) {
        merge(item);
        renderDetail(item);
      }
    });
});
$("#detail-body").addEventListener("click", (event) => {
  const button = event.target.closest("[data-command]");
  if (!button || !state.selected) return;
  const item = state.selected;
  safe(async () => {
    button.disabled = true;
    try {
      const generation = state.generation;
      const result = await api({
        action: button.dataset.command,
        workflow_id: item.workflow_id,
        action_id: item.pending_action?.action_id,
      });
      if (generation !== state.generation) return;
      merge(result);
      renderDetail(result);
      notify(result.delivery_warning || "Decision saved.");
    } finally {
      button.disabled = false;
    }
  });
});
$("#new-request").addEventListener("click", () => {
  $("#request-form").reset();
  $("#request-form").elements.request_id.value =
    `offboard-${crypto.randomUUID().slice(0, 8)}`;
  $("#request-dialog").showModal();
});
$("#close-dialog").addEventListener("click", () =>
  $("#request-dialog").close(),
);
$("#request-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = { action: "start", ...Object.fromEntries(new FormData(form)) };
  safe(async () => {
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      const result = await api(body);
      merge(result);
      renderDetail(result);
      $("#request-dialog").close();
      notify(
        result.delivery_warning ||
          "Request saved. Evidence collection is queued.",
      );
    } catch (error) {
      $("#request-dialog").close();
      throw error;
    } finally {
      button.disabled = false;
    }
  });
});

async function boot() {
  try {
    const response = await fetch("/config");
    if (!response.ok)
      throw new Error("Dashboard configuration is unavailable.");
    state.config = await response.json();
    if (state.config.localDemo) {
      $("#login-form").hidden = true;
      $("#demo-login").hidden = false;
      document
        .querySelectorAll("[data-demo]")
        .forEach((button) =>
          button.addEventListener("click", () =>
            safe(() => signedIn(`local-${button.dataset.demo}`)),
          ),
        );
    }
  } catch (error) {
    notify(error.message);
    $("#login-button").disabled = true;
  }
}
setInterval(() => {
  if (
    state.token &&
    !state.busy &&
    !document.hidden &&
    state.workflows.some((item) => active.has(item.status))
  ) {
    safe(() => refresh());
  }
}, 4000);
boot();

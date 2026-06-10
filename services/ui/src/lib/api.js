export const BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// --- Project ---

export async function getProjectInfo() {
  return request("/project");
}

// --- Terraform ---

export function streamInventory(onMessage, onDone) {
  return streamSSE(`${BASE}/terraform/inventory`, "GET", null, onMessage, onDone);
}

export async function getCosts(days = 30) {
  return request(`/terraform/costs?days=${days}`);
}

export async function getWizStatus() {
  return request(`/wiz/status`);
}

export function streamWizScan(onMessage, onDone) {
  return streamSSE(`${BASE}/wiz/scan`, "GET", null, onMessage, onDone);
}

export function streamCloudScan(onMessage, onDone) {
  return streamSSE(`${BASE}/terraform/cloud-scan`, "GET", null, onMessage, onDone);
}

export function streamOverviewFresh(onMessage, onDone) {
  return streamSSE(`${BASE}/terraform/overview-stream`, "GET", null, onMessage, onDone);
}

export async function getOverview() {
  return request("/terraform/overview");
}

export async function getFiles() {
  return request("/terraform/files");
}

export async function getFile(filename) {
  return request(`/terraform/files/${filename}`);
}

export async function updateFile(filename, content) {
  return request(`/terraform/files/${filename}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function getResources() {
  return request("/terraform/resources");
}

export async function getState() {
  return request("/terraform/state");
}

export async function getGraph() {
  return request("/terraform/graph");
}

export async function getParsed() {
  return request("/terraform/parsed");
}

export async function getVars() {
  return request("/terraform/vars");
}

export async function getProviders() {
  return request("/terraform/providers");
}

export function streamImport(address, resourceId, onData, onDone) {
  return streamSSE(
    `${BASE}/terraform/import`,
    "POST",
    { address, id: resourceId },
    onData,
    onDone
  );
}

export function streamTerraform(command, body, onData, onDone) {
  return streamSSE(`${BASE}/terraform/${command}`, "POST", body, onData, onDone);
}

export async function checkAwsDeletePreconditions(resources) {
  return request("/terraform/aws-delete-check", {
    method: "POST",
    body: JSON.stringify({ resources }),
  });
}

export function streamAwsDelete(resources, onData, onDone) {
  return streamSSE(`${BASE}/terraform/aws-delete`, "POST", { resources }, onData, onDone);
}

// --- AWS ---

export async function getAwsStatus() {
  return request("/aws/status");
}

// --- AI ---

export function streamChat(message, context, onData, onDone) {
  return streamSSE(`${BASE}/ai/chat`, "POST", { message, context }, onData, onDone);
}

export function streamChatSession(messages, onData, onDone) {
  return streamSSE(`${BASE}/ai/chat-session`, "POST", { messages }, onData, onDone);
}

export function streamSummarize(resources, onData, onDone) {
  return streamSSE(`${BASE}/ai/summarize`, "POST", { resources }, onData, onDone);
}

export function streamDiagnose(command, output, onData, onDone) {
  return streamSSE(
    `${BASE}/ai/diagnose`,
    "POST",
    { command, output },
    onData,
    onDone
  );
}

// --- SSE helper ---

function streamSSE(url, method, body, onData, onDone) {
  const controller = new AbortController();
  const opts = { method, signal: controller.signal };
  if (body) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  fetch(url, opts).then(async (res) => {
    if (!res.ok) {
      const err = await res.text().catch(() => res.statusText);
      onData?.(`Error: ${res.status} ${err}`);
      onDone?.();
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();
      for (const line of lines) {
        const text = line.split("\n").filter(l => l.startsWith("data:")).map(l => l.replace(/^data: ?/, "")).join("\n");
        if (text === "[DONE]") {
          onDone?.();
          return;
        }
        onData?.(text);
      }
    }
    onDone?.();
  }).catch((err) => {
    if (err.name !== "AbortError") {
      onData?.(`Error: ${err.message}`);
    }
    onDone?.();
  });
  return controller;
}

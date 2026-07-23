import { createExclusiveGate } from "./start_gate.mjs";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function createBrowserClientId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

class ApiClientError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

const state = {
  token: "",
  clientId: createBrowserClientId(),
  experimentOwner: null,
  system: null,
  configs: [],
  currentView: "build",
  builder: {
    document: null,
    id: null,
    sourceId: null,
    expanded: false,
    dirty: false,
    selected: { kind: "experiment", path: [] },
    summary: null,
  },
  execute: {
    configId: null,
    document: null,
    summary: null,
    fromBuilder: false,
  },
  executeLoadSequence: 0,
  executeLoading: false,
  manualSides: { left: false, right: false, front: false },
  relay: null,
  experiment: { status: "idle", version: 0 },
  runnerRenderedVersion: -1,
  runnerPhaseRenderedAt: null,
  runnerPhaseIdentity: null,
  startPending: false,
  actionPending: false,
  experimentPoll: null,
  relayPoll: null,
  heartbeatPoll: null,
};

const experimentStartGate = createExclusiveGate();

function syncExecuteStartButton() {
  const button = $("#execute-start");
  if (!button) return;
  button.disabled = Boolean(
    state.executeLoading
    || state.startPending
    || ["starting", "running"].includes(state.experiment.status)
  );
}

const viewCopy = {
  build: {
    eyebrow: "Experiment authoring",
    title: "Build Experiment",
    subtitle: "Rancang struktur, variabel, stimulus, dan timing dalam satu workspace.",
  },
  execute: {
    eyebrow: "Session operations",
    title: "Execute Experiment",
    subtitle: "Validasi snapshot protokol, siapkan partisipan, lalu jalankan sesi terkontrol.",
  },
  manual: {
    eyebrow: "Hardware diagnostics",
    title: "Manual / System Setup",
    subtitle: "Periksa koneksi, wiring, readback, dan masing-masing deret lampu secara aman.",
  },
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDuration(milliseconds, responseGated = false) {
  const seconds = Number(milliseconds || 0) / 1000;
  let result;
  if (seconds >= 3600) result = `${(seconds / 3600).toFixed(1)} jam`;
  else if (seconds >= 60) result = `${(seconds / 60).toFixed(1)} mnt`;
  else result = `${seconds.toFixed(1)} dtk`;
  return responseGated ? `${result}+` : result;
}

function setStatus(message, tone = "normal") {
  $("#status-message").textContent = message;
  $("#status-strip").className = `status-strip${tone === "normal" ? "" : ` ${tone}`}`;
}

function toast(message, tone = "normal", timeout = 3600) {
  const element = document.createElement("div");
  element.className = `toast${tone === "error" ? " error" : ""}`;
  element.textContent = message;
  $("#toast-region").append(element);
  window.setTimeout(() => element.remove(), timeout);
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-PEBT-Token"] = state.token;
  }
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiClientError(`Python backend tidak dapat dijangkau: ${error.message}`);
  }
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new ApiClientError(`Respons backend tidak valid (HTTP ${response.status}).`, response.status);
  }
  if (!response.ok || !payload.ok) {
    throw new ApiClientError(
      payload?.error?.message || `HTTP ${response.status}`,
      response.status,
      payload?.error?.details,
    );
  }
  return payload.data;
}

function newDocument() {
  return {
    schema_version: 1,
    task_type: "generic",
    protocol_id: "NEW-EXPERIMENT-V1",
    title: "Eksperimen Baru",
    protocol_status: "draft",
    description: "Dibuat dengan PEBT UGM Web Experiment Studio.",
    instructions: "Tekan SPASI untuk memulai eksperimen.",
    instruction_pages: [],
    random_seed: 2026,
    data_directory: "data/experiments",
    participant_conditions: [],
    display: {
      fullscreen: false,
      background: "#101820",
      foreground: "#FFFFFF",
      font_size: 34,
    },
    sources: [],
    blocks: [newBlock("block-1", "trial-1")],
  };
}

function newBlock(blockId, trialId) {
  return {
    block_id: blockId,
    instructions: "Tekan SPASI untuk memulai block.",
    repetitions: 1,
    randomize_trials: false,
    trials: [newTrial(trialId)],
  };
}

function newTrial(trialId) {
  return {
    trial_id: trialId,
    condition: "default",
    correct_key: null,
    metadata: {},
    phases: [newPhase("stimulus")],
  };
}

function newPhase(name) {
  return {
    name,
    duration_ms: 1000,
    text: "Stimulus",
    lights: [],
    collect_response: false,
    allowed_keys: [],
  };
}

function switchView(view) {
  if (!viewCopy[view]) return;
  state.currentView = view;
  $$(".nav-item").forEach((button) => {
    const active = button.dataset.viewTarget === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $$(".view").forEach((section) => section.classList.toggle("is-active", section.dataset.view === view));
  $("#view-eyebrow").textContent = viewCopy[view].eyebrow;
  $("#view-title").textContent = viewCopy[view].title;
  $("#view-subtitle").textContent = viewCopy[view].subtitle;
  if (view === "manual") refreshRelay().catch(showError);
  if (view === "execute") refreshResults().catch(showError);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showError(error) {
  console.error(error);
  const message = error instanceof Error ? error.message : String(error);
  setStatus(message, "error");
  toast(message, "error", 5200);
}

function updateSystemUi(system) {
  state.system = system;
  state.relay = system.relay;
  const modePill = $("#mode-pill");
  modePill.className = `mode-pill ${system.mode}`;
  modePill.innerHTML = `<span></span>${system.mode === "demo" ? "Mode simulasi" : "Mode hardware"}`;
  $("#sidebar-mode-label").textContent = system.mode === "demo" ? "In-memory controller" : "Ydci hardware backend";
  $("#ready-backend").classList.add("ready");
  updateRelayUi(system.relay);
}

function updateRelayUi(relay) {
  state.relay = relay;
  const connected = Boolean(relay?.connected);
  const readable = connected && !relay?.error && Array.isArray(relay?.states);
  $("#sidebar-relay-led").classList.toggle("online", readable);
  $("#sidebar-relay-label").textContent = relay?.error
    ? "Readback relay gagal"
    : connected
      ? `Relay ID ${relay.device_id}`
      : "Relay offline";
  $("#manual-connection-copy").textContent = relay?.leased_by_experiment
    ? "Relay dikunci oleh eksperimen aktif"
    : relay?.error
      ? `Status output tidak diketahui · ${relay.error}`
    : connected
      ? `Terhubung · Device ID ${relay.device_id}`
      : "Relay belum terhubung";
  const states = Array.isArray(relay?.states) ? relay.states : [null, null, null, null];
  $$('[data-mini-channel]').forEach((node) => node.classList.toggle("on", Number(states[Number(node.dataset.miniChannel)]) === 1));
  $("#manual-readback").textContent = readable ? `[${states.join(", ")}]` : "[?, ?, ?, ?]";
  ["left", "right", "front"].forEach((side, index) => {
    $(`[data-lamp="${side}"]`)?.classList.toggle("actual-on", Number(states[index]) === 1);
  });
  $("#ready-relay").classList.toggle("ready", readable);
  $("#ready-relay").lastChild.textContent = relay?.error
    ? " Readback gagal; status output tidak diketahui"
    : readable
      ? " Relay siap dan readback tersedia"
      : " Relay belum terhubung";
  const locked = Boolean(relay?.leased_by_experiment);
  ["#relay-connect", "#relay-disconnect", "#manual-apply", "#manual-all-off"].forEach((selector) => {
    $(selector).disabled = locked;
  });
  $$(".lamp-toggle").forEach((button) => { button.disabled = locked; });
}

async function loadConfigList() {
  state.configs = await api("/api/configs");
  const selects = [$("#builder-config-select"), $("#execute-config-select")];
  for (const select of selects) {
    const previous = select.value;
    select.replaceChildren();
    for (const item of state.configs) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = `${item.title} · ${String(item.protocol_status || "unknown").toUpperCase()}`;
      option.disabled = !item.valid;
      select.append(option);
    }
    const fallback = state.configs.find((item) => item.id.includes("pebt_yamawaki"))?.id || state.configs[0]?.id || "";
    select.value = state.configs.some((item) => item.id === previous) ? previous : fallback;
  }
}

function getNode(kind = state.builder.selected.kind, path = state.builder.selected.path) {
  const document = state.builder.document;
  if (kind === "experiment") return document;
  const block = document.blocks[path[0]];
  if (kind === "block") return block;
  const trial = block.trials[path[1]];
  if (kind === "trial") return trial;
  if (kind === "phase") return trial.phases[path[2]];
  throw new Error(`Unknown node kind: ${kind}`);
}

function allBlockIds() {
  return new Set(state.builder.document.blocks.map((block) => String(block.block_id || "")));
}

function allTrialIds() {
  return new Set(state.builder.document.blocks.flatMap((block) => block.trials.map((trial) => String(trial.trial_id || ""))));
}

function uniqueId(base, values) {
  if (!values.has(base)) return base;
  let index = 2;
  while (values.has(`${base}-${index}`)) index += 1;
  return `${base}-${index}`;
}

function markBuilderChanged(structural = true) {
  state.builder.dirty = true;
  state.builder.summary = null;
  if (structural && state.builder.document.protocol_status === "validated") {
    state.builder.document.protocol_status = "draft";
  }
  updateBuilderStatus();
}

function countNodes(document) {
  let count = 1;
  for (const block of document.blocks || []) {
    count += 1;
    for (const trial of block.trials || []) count += 1 + (trial.phases || []).length;
  }
  return count;
}

function renderTree() {
  const document = state.builder.document;
  const selectedKey = `${state.builder.selected.kind}:${state.builder.selected.path.join(".")}`;
  const item = (kind, path, label, position, children = "") => {
    const key = `${kind}:${path.join(".")}`;
    const kindLabel = { experiment: "E", block: "B", trial: "T", phase: "P" }[kind];
    const selected = key === selectedKey;
    return `<li role="none"><button type="button" role="treeitem" class="tree-item${selected ? " selected" : ""}" data-kind="${kind}" data-path="${path.join(".")}" aria-level="${path.length + 1}" aria-selected="${selected}" tabindex="${selected ? "0" : "-1"}"><span class="tree-kind">${kindLabel}</span><span class="tree-label">${escapeHtml(label)}</span><span class="tree-position">${escapeHtml(position)}</span></button>${children}</li>`;
  };
  const blockItems = (document.blocks || []).map((block, blockIndex) => {
    const trialItems = (block.trials || []).map((trial, trialIndex) => {
      const phaseItems = (trial.phases || []).map((phase, phaseIndex) => item("phase", [blockIndex, trialIndex, phaseIndex], phase.name || "Tanpa nama", `P${phaseIndex + 1}`)).join("");
      return item("trial", [blockIndex, trialIndex], trial.trial_id || "Tanpa ID", `T${trialIndex + 1}`, `<ul role="group">${phaseItems}</ul>`);
    }).join("");
    return item("block", [blockIndex], block.block_id || "Tanpa ID", `B${blockIndex + 1}`, `<ul role="group">${trialItems}</ul>`);
  }).join("");
  $("#builder-tree").innerHTML = `<ul class="tree-list" role="group">${item("experiment", [], document.title || "Untitled", "ROOT", `<ul role="group">${blockItems}</ul>`)}</ul>`;
  $("#builder-node-count").textContent = `${countNodes(document)} item`;
  const treeItems = $$(".tree-item", $("#builder-tree"));
  const selectItem = (button, focus = false) => {
      state.builder.selected = {
        kind: button.dataset.kind,
        path: button.dataset.path ? button.dataset.path.split(".").map(Number) : [],
      };
      renderTree();
      renderInspector();
      if (focus) $(".tree-item.selected", $("#builder-tree"))?.focus();
  };
  treeItems.forEach((button, index) => {
    button.addEventListener("click", () => selectItem(button));
    button.addEventListener("keydown", (event) => {
      const destination = {
        ArrowUp: Math.max(0, index - 1),
        ArrowDown: Math.min(treeItems.length - 1, index + 1),
        Home: 0,
        End: treeItems.length - 1,
      }[event.key];
      if (destination === undefined) return;
      event.preventDefault();
      selectItem(treeItems[destination], true);
    });
  });
}

function inputField(name, label, value, options = {}) {
  const wide = options.wide ? " wide" : "";
  const help = options.help ? `<small class="field-help">${escapeHtml(options.help)}</small>` : "";
  if (options.type === "checkbox") {
    return `<label class="check-field${wide}"><input type="checkbox" name="${name}" ${value ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`;
  }
  if (options.type === "textarea") {
    return `<label class="${wide.trim()}"><span>${escapeHtml(label)}</span><textarea name="${name}" rows="${options.rows || 4}">${escapeHtml(value ?? "")}</textarea>${help}</label>`;
  }
  if (options.options) {
    const optionHtml = options.options.map((option) => `<option value="${escapeHtml(option)}" ${String(value) === String(option) ? "selected" : ""}>${escapeHtml(option)}</option>`).join("");
    return `<label class="${wide.trim()}"><span>${escapeHtml(label)}</span><select name="${name}">${optionHtml}</select>${help}</label>`;
  }
  return `<label class="${wide.trim()}"><span>${escapeHtml(label)}</span><input name="${name}" type="${options.type || "text"}" value="${escapeHtml(value ?? "")}" ${options.min !== undefined ? `min="${options.min}"` : ""}>${help}</label>`;
}

function renderInspector() {
  const { kind } = state.builder.selected;
  const node = getNode();
  $("#inspector-title").textContent = `Properti ${kind}`;
  let fields = "";
  if (kind === "experiment") {
    fields += inputField("protocol_id", "Protocol ID", node.protocol_id);
    fields += inputField("title", "Judul", node.title);
    fields += inputField("task_type", "Tipe tugas", node.task_type || "generic", { options: ["generic", "pebt"] });
    fields += inputField("protocol_status", "Status protokol", node.protocol_status || "draft", { options: ["demo", "draft", "validated"] });
    fields += inputField("description", "Deskripsi", node.description, { type: "textarea", wide: true, rows: 3 });
    fields += inputField("instructions", "Instruksi fallback", node.instructions, { type: "textarea", wide: true, rows: 3 });
    fields += inputField("random_seed", "Random seed", node.random_seed, { type: "number" });
    fields += inputField("participant_conditions", "Kondisi (pisahkan koma)", (node.participant_conditions || []).join(", "), { wide: true });
    fields += inputField("display_fullscreen", "Fullscreen saat sesi", node.display?.fullscreen, { type: "checkbox" });
    fields += inputField("display_background", "Background", node.display?.background || "#101820");
    fields += inputField("display_foreground", "Foreground", node.display?.foreground || "#FFFFFF");
    fields += inputField("display_font_size", "Ukuran font", node.display?.font_size || 34, { type: "number", min: 8 });
    fields += inputField("instruction_pages_json", "Instruction pages · JSON array", JSON.stringify(node.instruction_pages || [], null, 2), { type: "textarea", wide: true, rows: 7, help: "Gunakan Advanced JSON untuk page_id, title, text, dan hint." });
    fields += inputField("sources_json", "Sources · JSON array", JSON.stringify(node.sources || [], null, 2), { type: "textarea", wide: true, rows: 7 });
  } else if (kind === "block") {
    fields += inputField("block_id", "Block ID", node.block_id);
    fields += inputField("repetitions", "Repetitions", node.repetitions, { type: "number", min: 1 });
    fields += inputField("randomize_trials", "Acak urutan trial", node.randomize_trials, { type: "checkbox" });
    fields += inputField("instructions", "Instruksi block", node.instructions, { type: "textarea", wide: true, rows: 6 });
  } else if (kind === "trial") {
    fields += inputField("trial_id", "Trial ID", node.trial_id);
    fields += inputField("condition", "Condition", node.condition);
    fields += inputField("correct_key", "Correct key · opsional", node.correct_key || "");
    fields += inputField("metadata_json", "Metadata · JSON object", JSON.stringify(node.metadata || {}, null, 2), { type: "textarea", wide: true, rows: 12 });
  } else if (kind === "phase") {
    fields += inputField("name", "Nama phase", node.name);
    fields += inputField("duration_ms", "Duration ms · kosong = response-gated", node.duration_ms ?? "", { type: "number", min: 0 });
    fields += inputField("lights", "Lampu · left, right, front", (node.lights || []).join(", "), { wide: true });
    fields += inputField("collect_response", "Kumpulkan respons", node.collect_response, { type: "checkbox" });
    fields += inputField("allowed_keys", "Allowed keys · pisahkan koma", (node.allowed_keys || []).join(", "), { wide: true });
    fields += inputField("end_on_response", "Akhiri phase saat respons", node.end_on_response, { type: "checkbox" });
    fields += inputField("run_if_response_key", "Jalankan jika respons sebelumnya", node.run_if_response_key || "");
    fields += inputField("background", "Background override", node.background || "");
    fields += inputField("foreground", "Foreground override", node.foreground || "");
    fields += inputField("font_size", "Font size override", node.font_size || "", { type: "number", min: 8 });
    fields += inputField("text", "Teks stimulus", node.text || "", { type: "textarea", wide: true, rows: 7 });
  }
  $("#inspector-form").innerHTML = fields;
}

function parseInteger(value, label, optional = false) {
  const text = String(value ?? "").trim();
  if (!text && optional) return null;
  const number = Number(text);
  if (!Number.isInteger(number)) throw new Error(`${label} harus berupa integer${optional ? " atau kosong" : ""}.`);
  return number;
}

function parseJson(value, expected, label) {
  let parsed;
  try {
    parsed = JSON.parse(value || (expected === "array" ? "[]" : "{}"));
  } catch (error) {
    throw new Error(`${label}: JSON tidak valid (${error.message}).`);
  }
  if (expected === "array" && !Array.isArray(parsed)) throw new Error(`${label} harus berupa JSON array.`);
  if (expected === "object" && (Array.isArray(parsed) || parsed === null || typeof parsed !== "object")) throw new Error(`${label} harus berupa JSON object.`);
  return parsed;
}

function csv(value) {
  return String(value || "").split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
}

function applyInspector({ silent = false } = {}) {
  const form = $("#inspector-form");
  const data = new FormData(form);
  const { kind, path } = state.builder.selected;
  const previous = clone(getNode(kind, path));
  const node = clone(previous);
  if (kind === "experiment") {
    node.schema_version = 1;
    ["protocol_id", "title", "task_type", "protocol_status"].forEach((key) => { node[key] = String(data.get(key) || "").trim(); });
    node.description = String(data.get("description") || "");
    node.instructions = String(data.get("instructions") || "");
    node.random_seed = parseInteger(data.get("random_seed"), "Random seed");
    node.participant_conditions = csv(data.get("participant_conditions"));
    node.display = {
      fullscreen: data.get("display_fullscreen") === "on",
      background: String(data.get("display_background") || "").trim(),
      foreground: String(data.get("display_foreground") || "").trim(),
      font_size: parseInteger(data.get("display_font_size"), "Display font size"),
    };
    node.instruction_pages = parseJson(data.get("instruction_pages_json"), "array", "Instruction pages");
    node.sources = parseJson(data.get("sources_json"), "array", "Sources");
    if (previous.protocol_status === "validated" && node.protocol_status === "validated") {
      const before = clone(previous); const after = clone(node);
      delete before.protocol_status; delete after.protocol_status;
      if (JSON.stringify(before) !== JSON.stringify(after)) node.protocol_status = "draft";
    }
    state.builder.document = node;
  } else if (kind === "block") {
    node.block_id = String(data.get("block_id") || "").trim();
    node.repetitions = parseInteger(data.get("repetitions"), "Repetitions");
    node.randomize_trials = data.get("randomize_trials") === "on";
    node.instructions = String(data.get("instructions") || "");
    state.builder.document.blocks[path[0]] = node;
  } else if (kind === "trial") {
    node.trial_id = String(data.get("trial_id") || "").trim();
    node.condition = String(data.get("condition") || "").trim();
    node.correct_key = String(data.get("correct_key") || "").trim().toLowerCase() || null;
    node.metadata = parseJson(data.get("metadata_json"), "object", "Metadata");
    state.builder.document.blocks[path[0]].trials[path[1]] = node;
  } else if (kind === "phase") {
    node.name = String(data.get("name") || "").trim();
    node.duration_ms = parseInteger(data.get("duration_ms"), "Duration", true);
    node.text = String(data.get("text") || "");
    node.lights = csv(data.get("lights"));
    node.collect_response = data.get("collect_response") === "on";
    node.allowed_keys = csv(data.get("allowed_keys"));
    node.end_on_response = data.get("end_on_response") === "on";
    const runKey = String(data.get("run_if_response_key") || "").trim().toLowerCase();
    if (runKey) node.run_if_response_key = runKey; else delete node.run_if_response_key;
    ["background", "foreground"].forEach((key) => {
      const value = String(data.get(key) || "").trim();
      if (value) node[key] = value; else delete node[key];
    });
    const fontSize = parseInteger(data.get("font_size"), "Font size", true);
    if (fontSize === null) delete node.font_size; else node.font_size = fontSize;
    state.builder.document.blocks[path[0]].trials[path[1]].phases[path[2]] = node;
  }
  const changed = JSON.stringify(previous) !== JSON.stringify(getNode(kind, path));
  if (changed) markBuilderChanged(kind !== "experiment" || previous.protocol_status === "validated");
  renderBuilder();
  if (!silent) toast(changed ? "Properti diterapkan ke draft." : "Tidak ada perubahan properti.");
  return true;
}

function selectParentAfterDelete(kind, path) {
  if (kind === "block") return { kind: "experiment", path: [] };
  if (kind === "trial") return { kind: "block", path: [path[0]] };
  return { kind: "trial", path: [path[0], path[1]] };
}

async function treeAction(action) {
  const { kind, path } = state.builder.selected;
  if (action === "add-block") {
    const blockId = uniqueId("block", allBlockIds());
    const trialId = uniqueId("trial", allTrialIds());
    state.builder.document.blocks.push(newBlock(blockId, trialId));
    state.builder.selected = { kind: "block", path: [state.builder.document.blocks.length - 1] };
  } else if (action === "add-trial") {
    if (kind === "experiment") throw new Error("Pilih block terlebih dahulu.");
    const blockIndex = path[0];
    const trialId = uniqueId("trial", allTrialIds());
    const trials = state.builder.document.blocks[blockIndex].trials;
    trials.push(newTrial(trialId));
    state.builder.selected = { kind: "trial", path: [blockIndex, trials.length - 1] };
  } else if (action === "add-phase") {
    if (!["trial", "phase"].includes(kind)) throw new Error("Pilih trial terlebih dahulu.");
    const phases = state.builder.document.blocks[path[0]].trials[path[1]].phases;
    phases.push(newPhase(`phase-${phases.length + 1}`));
    state.builder.selected = { kind: "phase", path: [path[0], path[1], phases.length - 1] };
  } else if (action === "duplicate") {
    if (kind === "experiment") throw new Error("Pilih block, trial, atau phase untuk diduplikasi.");
    const copyNode = clone(getNode());
    if (kind === "block") {
      copyNode.block_id = uniqueId(`${copyNode.block_id || "block"}-copy`, allBlockIds());
      const ids = allTrialIds();
      copyNode.trials.forEach((trial) => { trial.trial_id = uniqueId(`${trial.trial_id || "trial"}-copy`, ids); ids.add(trial.trial_id); });
      state.builder.document.blocks.splice(path[0] + 1, 0, copyNode);
      state.builder.selected = { kind, path: [path[0] + 1] };
    } else if (kind === "trial") {
      copyNode.trial_id = uniqueId(`${copyNode.trial_id || "trial"}-copy`, allTrialIds());
      state.builder.document.blocks[path[0]].trials.splice(path[1] + 1, 0, copyNode);
      state.builder.selected = { kind, path: [path[0], path[1] + 1] };
    } else {
      copyNode.name = `${copyNode.name || "phase"}-copy`;
      state.builder.document.blocks[path[0]].trials[path[1]].phases.splice(path[2] + 1, 0, copyNode);
      state.builder.selected = { kind, path: [path[0], path[1], path[2] + 1] };
    }
  } else if (["move-up", "move-down"].includes(action)) {
    if (kind === "experiment") throw new Error("Root experiment tidak dapat dipindah.");
    const direction = action === "move-up" ? -1 : 1;
    let siblings; let index;
    if (kind === "block") { siblings = state.builder.document.blocks; index = path[0]; }
    else if (kind === "trial") { siblings = state.builder.document.blocks[path[0]].trials; index = path[1]; }
    else { siblings = state.builder.document.blocks[path[0]].trials[path[1]].phases; index = path[2]; }
    const destination = index + direction;
    if (destination < 0 || destination >= siblings.length) return;
    [siblings[index], siblings[destination]] = [siblings[destination], siblings[index]];
    const newPath = [...path]; newPath[newPath.length - 1] = destination;
    state.builder.selected = { kind, path: newPath };
  } else if (action === "delete") {
    if (kind === "experiment") throw new Error("Root experiment tidak dapat dihapus.");
    const accepted = await confirmAction("Hapus item?", `Hapus ${kind} terpilih beserta seluruh child di dalamnya?`);
    if (!accepted) return;
    if (kind === "block") state.builder.document.blocks.splice(path[0], 1);
    else if (kind === "trial") state.builder.document.blocks[path[0]].trials.splice(path[1], 1);
    else state.builder.document.blocks[path[0]].trials[path[1]].phases.splice(path[2], 1);
    state.builder.selected = selectParentAfterDelete(kind, path);
  }
  markBuilderChanged(true);
  renderBuilder();
}

function updateBuilderStatus() {
  const document = state.builder.document;
  if (!document) return;
  $("#builder-dirty").classList.toggle("dirty", state.builder.dirty);
  $("#builder-dirty").title = state.builder.dirty ? "Perubahan belum disimpan" : "Dokumen tersimpan";
  const badge = $("#builder-status-badge");
  const status = document.protocol_status || "draft";
  badge.textContent = status.toUpperCase();
  badge.className = `status-badge ${status}`;
  $("#builder-file-label").textContent = state.builder.id || (state.builder.expanded ? "Copy ekspansi · Save As" : "Belum disimpan");
  $("#builder-seed-label").textContent = document.random_seed ?? "—";
  $("#builder-condition-label").textContent = (document.participant_conditions || []).join(", ") || "Tidak digunakan";
  if (!state.builder.summary) {
    $("#metric-blocks").textContent = (document.blocks || []).length;
    $("#metric-trials").textContent = (document.blocks || []).reduce((sum, block) => sum + (block.trials || []).length * Number(block.repetitions || 1), 0);
    $("#metric-phases").textContent = (document.blocks || []).reduce((sum, block) => sum + (block.trials || []).reduce((phaseSum, trial) => phaseSum + (trial.phases || []).length, 0), 0);
  } else {
    $("#metric-blocks").textContent = state.builder.summary.block_count;
    $("#metric-trials").textContent = state.builder.summary.trial_count;
    $("#metric-phases").textContent = state.builder.summary.phase_count;
  }
}

function renderBuilder() {
  renderTree();
  renderInspector();
  updateBuilderStatus();
}

async function loadBuilderConfig(configId) {
  setStatus("Membuka konfigurasi di Experiment Builder…");
  const loaded = await api(`/api/config?id=${encodeURIComponent(configId)}&mode=builder`);
  state.builder = {
    document: loaded.document,
    id: loaded.id,
    sourceId: loaded.source_id,
    expanded: loaded.expanded_from_generator,
    dirty: false,
    selected: { kind: "experiment", path: [] },
    summary: loaded.summary,
  };
  renderBuilder();
  $("#builder-audit-message").className = "audit-message";
  $("#builder-audit-message").textContent = loaded.expanded_from_generator
    ? "Generator ringkas telah diekspansi menjadi copy editable. Simpan sebagai file baru sebelum digunakan."
    : `Konfigurasi valid · ${loaded.summary.trial_count} trial siap ditinjau.`;
  setStatus(`Builder membuka ${loaded.source_id}.`);
}

async function validateBuilder() {
  applyInspector({ silent: true });
  try {
    const summary = await api("/api/config/validate", { method: "POST", body: { document: state.builder.document } });
    state.builder.summary = summary;
    $("#builder-audit-message").className = "audit-message";
    $("#builder-audit-message").textContent = `VALID · ${summary.block_count} block, ${summary.trial_count} trial, ${summary.phase_count} phase. Durasi maksimum ${formatDuration(summary.duration.maximum_ms, summary.duration.response_gated)}.`;
    $("#ready-config").classList.add("ready");
    updateBuilderStatus();
    toast("Konfigurasi valid dan dapat dieksekusi.");
    return summary;
  } catch (error) {
    state.builder.summary = null;
    $("#builder-audit-message").className = "audit-message error";
    $("#builder-audit-message").textContent = `VALIDASI GAGAL · ${error.message}`;
    $("#ready-config").classList.remove("ready");
    updateBuilderStatus();
    throw error;
  }
}

async function saveBuilder(overwrite = false) {
  applyInspector({ silent: true });
  let filename = state.builder.id?.split("/").pop();
  if (!filename || !state.builder.id?.startsWith("configs/user/")) filename = `${String(state.builder.document.protocol_id || "experiment").toLowerCase()}.json`;
  try {
    const saved = await api("/api/config/save", {
      method: "POST",
      body: { document: state.builder.document, filename, overwrite },
    });
    state.builder.id = saved.id;
    state.builder.sourceId = saved.id;
    state.builder.expanded = false;
    state.builder.dirty = false;
    state.builder.summary = saved.summary;
    updateBuilderStatus();
    await loadConfigList();
    $("#builder-config-select").value = saved.id;
    toast(`Tersimpan sebagai ${saved.filename}.`);
    return saved;
  } catch (error) {
    if (error.status === 409 && !overwrite) {
      const accepted = await confirmAction("Ganti file konfigurasi?", `${filename} sudah ada di configs/user. Timpa file tersebut?`);
      if (accepted) return saveBuilder(true);
      return null;
    }
    throw error;
  }
}

async function useBuilderInExecute() {
  const summary = await validateBuilder();
  state.executeLoadSequence += 1;
  state.executeLoading = false;
  state.execute = {
    configId: null,
    document: clone(state.builder.document),
    summary,
    fromBuilder: true,
  };
  syncExecuteStartButton();
  renderExecuteSummary();
  switchView("execute");
  toast("Snapshot builder siap digunakan di Execute.");
}

async function loadExecuteConfig(configId = $("#execute-config-select").value) {
  const sequence = ++state.executeLoadSequence;
  state.executeLoading = true;
  state.execute = { configId: null, document: null, summary: null, fromBuilder: false };
  syncExecuteStartButton();
  $("#ready-config").classList.remove("ready");
  try {
    const loaded = await api(`/api/config?id=${encodeURIComponent(configId)}&mode=execute`);
    if (sequence !== state.executeLoadSequence) return null;
    state.execute = {
      configId: loaded.id,
      document: loaded.document,
      summary: loaded.summary,
      fromBuilder: false,
    };
    renderExecuteSummary();
    setStatus(`Execute memuat ${loaded.id}.`);
    return loaded;
  } finally {
    if (sequence === state.executeLoadSequence) {
      state.executeLoading = false;
      syncExecuteStartButton();
    }
  }
}

function renderExecuteSummary() {
  const summary = state.execute.summary;
  if (!summary) return;
  $("#execute-config-source").textContent = state.execute.fromBuilder ? "BUILDER SNAPSHOT" : "SAVED FILE";
  $("#execute-protocol-title").textContent = summary.title;
  const statusBadge = $("#execute-protocol-status");
  statusBadge.textContent = summary.protocol_status.toUpperCase();
  statusBadge.className = `status-badge ${summary.protocol_status}`;
  $("#execute-description").textContent = summary.description || "Tidak ada deskripsi protokol.";
  $("#execute-blocks").textContent = summary.block_count;
  $("#execute-trials").textContent = summary.trial_count;
  $("#execute-pages").textContent = summary.instruction_page_count;
  $("#execute-duration").textContent = formatDuration(summary.duration.maximum_ms, summary.duration.response_gated);
  $("#execute-hash").textContent = summary.config_sha256;
  $("#ready-config").classList.add("ready");
  const conditionSelect = $("#participant-condition");
  const previous = conditionSelect.value;
  conditionSelect.replaceChildren();
  if (!summary.participant_conditions.length) {
    conditionSelect.add(new Option("Tidak digunakan", ""));
    conditionSelect.disabled = true;
  } else {
    summary.participant_conditions.forEach((condition) => conditionSelect.add(new Option(condition.replaceAll("_", " "), condition)));
    conditionSelect.disabled = false;
    conditionSelect.value = summary.participant_conditions.includes(previous) ? previous : summary.participant_conditions[0];
  }
  $("#allow-unvalidated").checked = summary.protocol_status !== "validated";
}

async function startExperiment() {
  if (!experimentStartGate.tryEnter()) return;
  state.startPending = true;
  syncExecuteStartButton();
  let runnerOpened = false;
  let sessionStarted = false;
  try {
    if (state.executeLoading) throw new Error("Tunggu konfigurasi selesai dimuat.");
    const selectedConfigId = $("#execute-config-select").value;
    if (
      !state.execute.fromBuilder
      && (!state.execute.summary || state.execute.configId !== selectedConfigId)
    ) {
      await loadExecuteConfig(selectedConfigId);
    }
    const participantId = $("#participant-id").value.trim();
    if (!participantId) throw new Error("ID partisipan wajib diisi.");
    const runner = $("#runner");
    $(".app-shell").inert = true;
    runner.classList.add("is-active");
    runner.setAttribute("aria-hidden", "false");
    runnerOpened = true;
    $("#runner-title").textContent = "Menyiapkan eksperimen";
    $("#runner-text").textContent = "Python backend sedang membuat trial plan dan event logger…";
    $("#runner-actions").replaceChildren();
    if (state.execute.document?.display?.fullscreen && runner.requestFullscreen) {
      runner.requestFullscreen().catch(() => {});
    }
    const payload = {
      participant_id: participantId,
      session_label: $("#session-label").value.trim(),
      participant_condition: $("#participant-condition").value,
      allow_unvalidated: $("#allow-unvalidated").checked,
      client_id: state.clientId,
    };
    if (state.execute.fromBuilder) payload.document = state.execute.document;
    else payload.config_id = state.execute.configId || $("#execute-config-select").value;
    state.experiment = await api("/api/experiment/start", { method: "POST", body: payload });
    sessionStarted = true;
    state.experimentOwner = "this_client";
    state.runnerRenderedVersion = -1;
    renderRunner(state.experiment);
    beginExperimentPolling();
    setStatus(`Sesi ${state.experiment.session_id} sedang berjalan.`);
  } catch (error) {
    if (runnerOpened && !sessionStarted) closeRunner();
    throw error;
  } finally {
    experimentStartGate.leave();
    state.startPending = false;
    syncExecuteStartButton();
  }
}

function beginExperimentPolling() {
  stopExperimentPolling();
  const controller = new AbortController();
  const sessionId = state.experiment.session_id;
  state.experimentPoll = controller;
  const poll = async () => {
    while (!controller.signal.aborted) {
      try {
        if (state.experiment.session_id !== sessionId) return;
        const afterVersion = Number(state.experiment.version || 0);
        const snapshot = await api(
          `/api/experiment?after=${afterVersion}&timeout_ms=10000&session_id=${encodeURIComponent(sessionId)}&client_id=${encodeURIComponent(state.clientId)}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        if (snapshot.version < Number(state.experiment.version || 0)) continue;
        state.experiment = snapshot;
        if (snapshot.version > state.runnerRenderedVersion) renderRunner(snapshot);
        if (["completed", "aborted", "error", "idle"].includes(snapshot.status)) {
          stopExperimentPolling();
          await refreshRelay();
          await refreshResults();
          return;
        }
      } catch (error) {
        if (error?.name === "AbortError") return;
        setStatus(error.message, "error");
        if (error.status === 409) {
          stopExperimentPolling();
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }
    }
  };
  poll();
  state.heartbeatPoll = window.setInterval(async () => {
    if (document.visibilityState !== "visible" || !["starting", "running"].includes(state.experiment.status)) return;
    try {
      await api("/api/experiment/heartbeat", {
        method: "POST",
        body: {
          session_id: sessionId,
          client_id: state.clientId,
        },
      });
    } catch (error) {
      setStatus(`Heartbeat gagal: ${error.message}`, "error");
    }
  }, 2000);
}

function stopExperimentPolling() {
  if (state.experimentPoll) state.experimentPoll.abort();
  if (state.heartbeatPoll) window.clearInterval(state.heartbeatPoll);
  state.experimentPoll = null;
  state.heartbeatPoll = null;
}

function keyLabel(key) {
  return { left: "← Panah kiri", right: "Panah kanan →", space: "Spasi", enter: "Enter" }[key] || key;
}

function renderPebt(snapshot) {
  const metadata = snapshot.trial?.metadata || {};
  const role = metadata.trial_role;
  if (!['pebt_choice', 'lamp_confirmation'].includes(role)) return false;
  if (role === "pebt_choice" && snapshot.phase?.name !== "choice") return false;
  const container = $("#pebt-stimulus");
  container.hidden = false;
  $("#runner-text").hidden = true;
  if (role === "lamp_confirmation") {
    const activeCount = Number(metadata.light_count || 12);
    container.innerHTML = `<article class="pebt-option" style="grid-column:1/-1;text-align:center"><h3>Konfirmasi lampu</h3><p>${escapeHtml(snapshot.text)}</p><div class="stimulus-bulbs" style="margin-inline:auto">${Array.from({ length: 12 }, (_, index) => `<i class="${index < activeCount ? "on" : ""}"></i>`).join("")}</div></article>`;
    return true;
  }
  const lightCount = Number(metadata.light_count || 0);
  const bulbs = (active) => `<div class="stimulus-bulbs">${Array.from({ length: 12 }, (_, index) => `<i class="${active && index < lightCount ? "on" : ""}"></i>`).join("")}</div>`;
  container.innerHTML = `
    <article class="pebt-option">
      <h3>← SEST</h3>
      <dl><dt>Waktu</dt><dd>${escapeHtml(metadata.sest_wait_seconds ?? "—")} detik</dd><dt>Lampu</dt><dd>0 / 12</dd><dt>Emisi CO₂</dt><dd>0 L/jam</dd></dl>
      ${bulbs(false)}
    </article>
    <article class="pebt-option">
      <h3>DIFT →</h3>
      <dl><dt>Waktu</dt><dd>${escapeHtml(metadata.dift_wait_seconds ?? "—")} detik</dd><dt>Lampu</dt><dd>${lightCount} / 12</dd><dt>Emisi CO₂</dt><dd>${escapeHtml(metadata.co2_liters_per_hour_dift ?? "—")} L/jam</dd></dl>
      ${bulbs(true)}
    </article>
    <div class="pebt-context">
      <strong>Selisih waktu SEST–DIFT: ${escapeHtml(metadata.time_difference_seconds ?? "—")} detik</strong>
      <span>Observer: ${escapeHtml(metadata.observer_label || "tidak ditentukan")}</span>
    </div>`;
  return true;
}

function acknowledgePhaseReady(snapshot) {
  const gateToken = snapshot.gate_token;
  const requestedAt = performance.now();
  window.requestAnimationFrame(() => window.requestAnimationFrame(async () => {
    while (true) {
      if (
        state.experiment.gate_token !== gateToken
        || state.experiment.screen !== "phase_prepare"
        || state.experiment.waiting_for !== "presentation"
      ) return;
      try {
        await api("/api/experiment/action", {
          method: "POST",
          body: {
            action: "ready",
            session_id: snapshot.session_id,
            client_id: state.clientId,
            gate_token: gateToken,
            client_elapsed_ms: Math.round((performance.now() - requestedAt) * 1000) / 1000,
          },
        });
        return;
      } catch (error) {
        if (error.status === 409) return;
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
    }
  }));
}

function reportPhasePresented(snapshot, identity) {
  const gateToken = snapshot.gate_token;
  const requestedAt = performance.now();
  window.requestAnimationFrame(() => window.requestAnimationFrame(async () => {
    if (
      state.runnerPhaseIdentity !== identity
      || state.experiment.gate_token !== gateToken
      || state.experiment.screen !== "phase"
    ) return;
    state.runnerPhaseRenderedAt = performance.now();
    while (
      state.runnerPhaseIdentity === identity
      && state.experiment.gate_token === gateToken
      && state.experiment.screen === "phase"
      && !state.experiment.phase?.started
    ) {
      try {
        const acknowledged = await api("/api/experiment/action", {
          method: "POST",
          body: {
            action: "presented",
            session_id: snapshot.session_id,
            client_id: state.clientId,
            gate_token: gateToken,
            client_elapsed_ms: Math.round((performance.now() - requestedAt) * 1000) / 1000,
          },
        });
        if (
          state.experiment.session_id === acknowledged.session_id
          && state.experiment.gate_token === acknowledged.gate_token
          && Number(acknowledged.version) >= Number(state.experiment.version || 0)
        ) {
          state.experiment = acknowledged;
          if (acknowledged.version > state.runnerRenderedVersion) {
            renderRunner(acknowledged);
          }
        }
        return;
      } catch (error) {
        if (error.status === 409) return;
        setStatus(`Onset acknowledgement gagal: ${error.message}`, "warning");
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
    }
  }));
}

function renderRunner(snapshot) {
  state.runnerRenderedVersion = snapshot.version;
  syncExecuteStartButton();
  const runner = $("#runner");
  const phaseIdentity = snapshot.screen === "phase" ? snapshot.gate_token : null;
  const sameVisiblePhase = Boolean(
    phaseIdentity
    && state.runnerPhaseIdentity === phaseIdentity
    && state.runnerPhaseRenderedAt !== null
  );
  $(".app-shell").inert = true;
  runner.classList.add("is-active");
  runner.setAttribute("aria-hidden", "false");
  const display = snapshot.display || { background: "#101820", foreground: "#FFFFFF", font_size: 34 };
  runner.style.background = display.background;
  runner.style.color = display.foreground;
  $("#runner-title").textContent = snapshot.title || "Eksperimen";
  if (!sameVisiblePhase) {
    $("#runner-text").textContent = snapshot.text || "";
    $("#runner-text").hidden = false;
  }
  $("#runner-text").style.fontSize = `${Math.min(90, Math.max(16, Number(display.font_size || 34)))}px`;
  $("#runner-hint").textContent = snapshot.hint || "";
  const relayKnown = Array.isArray(snapshot.relay_state);
  $("#runner-relay-state").textContent = relayKnown
    ? `Relay [${snapshot.relay_state.join(", ")}]`
    : "Relay [?, ?, ?, ?] · STATUS TIDAK DIKETAHUI";
  $("#runner-progress").textContent = snapshot.progress?.total ? `Trial ${snapshot.progress.current}/${snapshot.progress.total}` : snapshot.protocol_id || "PEBT UGM";
  $("#runner-kicker").textContent = snapshot.screen === "phase" ? snapshot.phase?.name || "Phase" : snapshot.screen || "";
  $("#runner-abort").hidden = !["starting", "running"].includes(snapshot.status);
  const pebt = $("#pebt-stimulus");
  if (!sameVisiblePhase) {
    pebt.hidden = true;
    pebt.replaceChildren();
    if (snapshot.screen === "phase") {
      renderPebt(snapshot);
      state.runnerPhaseIdentity = phaseIdentity;
      state.runnerPhaseRenderedAt = null;
      reportPhasePresented(snapshot, phaseIdentity);
    } else {
      state.runnerPhaseIdentity = null;
      state.runnerPhaseRenderedAt = null;
      if (snapshot.screen === "phase_prepare") acknowledgePhaseReady(snapshot);
    }
  }

  const actions = $("#runner-actions");
  const responsePhase = Boolean(
    snapshot.screen === "phase" && snapshot.phase?.collect_response
  );
  const responseKeys = responsePhase ? (snapshot.phase.allowed_keys || []) : [];
  let responseButtons = responsePhase && sameVisiblePhase
    ? $$("button[data-response-key]", actions)
    : [];
  const canReuseResponseButtons = responseButtons.length === responseKeys.length
    && responseButtons.every((button, index) => button.dataset.responseKey === responseKeys[index]);
  if (!canReuseResponseButtons) actions.replaceChildren();

  if (["instruction", "block"].includes(snapshot.screen)) {
    actions.replaceChildren();
    const button = document.createElement("button");
    button.className = "primary-action";
    button.textContent = "Lanjutkan · Spasi";
    button.addEventListener("click", () => sendExperimentAction({
      action: "continue",
      session_id: snapshot.session_id,
      gate_token: snapshot.gate_token,
    }));
    actions.append(button);
  } else if (responsePhase) {
    if (!canReuseResponseButtons) {
      responseButtons = responseKeys.map((key) => {
        const button = document.createElement("button");
        button.dataset.responseKey = key;
        button.textContent = keyLabel(key);
        button.addEventListener("click", () => sendExperimentAction({
          action: "response",
          key,
          session_id: snapshot.session_id,
          gate_token: snapshot.gate_token,
        }));
        actions.append(button);
        return button;
      });
    }
    const responseEnabled = snapshot.waiting_for === "phase"
      && snapshot.phase?.started
      && !snapshot.phase?.responded
      && state.runnerPhaseRenderedAt !== null;
    responseButtons.forEach((button) => { button.disabled = !responseEnabled; });
  } else if (["complete", "aborted", "error"].includes(snapshot.screen)) {
    actions.replaceChildren();
    if (snapshot.summary?.metrics) {
      const metrics = snapshot.summary.metrics;
      $("#runner-text").textContent = `${snapshot.text || ""}\n\nTrial selesai: ${metrics.completed_trial_count}/${metrics.planned_trial_count}\nRespons: ${metrics.response_count} · Timeout: ${metrics.response_timeout_count}\nRT rata-rata: ${metrics.mean_response_time_ms ?? "n/a"} ms`;
      $("#runner-text").style.fontSize = "20px";
    }
    const button = document.createElement("button");
    button.className = "primary-action";
    button.textContent = "Kembali ke dashboard";
    button.addEventListener("click", async () => {
      state.experiment = await api("/api/experiment/dismiss", {
        method: "POST",
        body: {
          session_id: snapshot.session_id,
          client_id: state.clientId,
        },
      });
      state.experimentOwner = null;
      state.runnerRenderedVersion = -1;
      syncExecuteStartButton();
      stopExperimentPolling();
      closeRunner();
      switchView("execute");
    });
    actions.append(button);
    if (!relayKnown) {
      setStatus("PERINGATAN: status relay tidak diketahui. Putuskan daya beban dan periksa perangkat.", "error");
    } else {
      setStatus(snapshot.status === "completed" ? "Eksperimen selesai; seluruh output relay OFF." : `Sesi berakhir dengan status ${snapshot.status}.`, snapshot.status === "error" ? "error" : "warning");
    }
  } else {
    actions.replaceChildren();
  }
}

async function sendExperimentAction(payload) {
  const tracksPending = payload.action !== "abort";
  if (tracksPending && state.actionPending) return;
  if (tracksPending) state.actionPending = true;
  try {
    const requestPayload = { ...payload };
    requestPayload.session_id ||= state.experiment.session_id;
    requestPayload.client_id = state.clientId;
    if (requestPayload.action !== "abort" && !requestPayload.gate_token) {
      requestPayload.gate_token = state.experiment.gate_token;
    }
    if (requestPayload.action === "response" && state.runnerPhaseRenderedAt !== null) {
      requestPayload.client_elapsed_ms = Math.round((performance.now() - state.runnerPhaseRenderedAt) * 1000) / 1000;
    }
    // Long-polling is the sole authority for experiment state. Treat this
    // response only as an acknowledgement so an older POST cannot roll back
    // a newer phase snapshot.
    await api("/api/experiment/action", { method: "POST", body: requestPayload });
  } catch (error) {
    if (error.status !== 409) showError(error);
  } finally {
    if (tracksPending) state.actionPending = false;
  }
}

async function abortExperiment() {
  const accepted = await confirmAction("Batalkan eksperimen?", "Output relay akan dimatikan dan data parsial tetap disimpan.");
  if (accepted) await sendExperimentAction({ action: "abort" });
}

function closeRunner(exitFullscreen = true) {
  $("#runner").classList.remove("is-active");
  $("#runner").setAttribute("aria-hidden", "true");
  $(".app-shell").inert = false;
  if (exitFullscreen && document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

function normalizeBrowserKey(event) {
  const mapping = { " ": "space", Spacebar: "space", Enter: "enter", Escape: "escape", ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
  return mapping[event.key] || String(event.key || "").toLowerCase();
}

async function refreshRelay() {
  const relay = await api("/api/relay");
  updateRelayUi(relay);
  return relay;
}

function updateManualSelection() {
  const selected = ["left", "right", "front"].filter((side) => state.manualSides[side]);
  const labels = { left: "Kiri", right: "Kanan", front: "Depan" };
  $("#manual-selection").textContent = selected.length ? selected.map((side) => labels[side]).join(" + ") : "Tidak ada deret dipilih";
  const vector = [Number(state.manualSides.left), Number(state.manualSides.right), Number(state.manualSides.front), 0];
  $("#manual-vector").textContent = `[${vector.join(", ")}]`;
  ["left", "right", "front"].forEach((side) => {
    const card = $(`[data-lamp="${side}"]`);
    const button = $(`[data-side="${side}"]`);
    card.classList.toggle("selected", state.manualSides[side]);
    button.setAttribute("aria-pressed", String(state.manualSides[side]));
    button.textContent = `${state.manualSides[side] ? "Batalkan" : "Pilih"} deret ${labels[side].toLowerCase()}`;
  });
}

async function connectRelay() {
  await api("/api/relay/connect", { method: "POST", body: {} });
  await refreshRelay();
  toast("Relay terhubung dan readback tersedia.");
}

async function applyManual() {
  const result = await api("/api/relay/apply", { method: "POST", body: { sides: state.manualSides } });
  await refreshRelay();
  toast(`State diterapkan: [${result.actual.join(", ")}].`);
}

async function allOff() {
  await api("/api/relay/off", { method: "POST", body: {} });
  state.manualSides = { left: false, right: false, front: false };
  updateManualSelection();
  await refreshRelay();
  toast("Seluruh output relay telah dimatikan.");
}

async function globalAllOff() {
  if (["starting", "running"].includes(state.experiment.status)) {
    if (state.experimentOwner !== "this_client") {
      setStatus("Sesi aktif dikendalikan tab lain; gunakan tab pemilik untuk membatalkan sesi.", "warning");
      return;
    }
    await abortExperiment();
  } else {
    await allOff();
  }
}

async function disconnectRelay() {
  await api("/api/relay/disconnect", { method: "POST", body: {} });
  state.manualSides = { left: false, right: false, front: false };
  updateManualSelection();
  await refreshRelay();
  toast("Relay diputuskan dalam keadaan OFF.");
}

async function refreshResults() {
  const results = await api("/api/results");
  const list = $("#result-list");
  if (!results.length) {
    list.innerHTML = '<p class="empty-state">Belum ada hasil sesi.</p>';
    return;
  }
  list.innerHTML = results.map((result) => {
    const title = result.protocol?.title || result.protocol?.protocol_id || "Eksperimen";
    const trials = result.metrics?.completed_trial_count ?? 0;
    const planned = result.metrics?.planned_trial_count ?? 0;
    return `<article class="result-item"><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(result.participant_id || "—")} · ${escapeHtml(trials)}/${escapeHtml(planned)} trial</small></div><span class="result-status">${escapeHtml(result.status || "unknown")}</span></article>`;
  }).join("");
}

function confirmAction(title, copy) {
  if (!$("#confirm-modal").hidden) return Promise.resolve(false);
  return new Promise((resolve) => {
    const modal = $("#confirm-modal");
    const previousFocus = document.activeElement;
    const runner = $("#runner");
    const runnerActive = runner.classList.contains("is-active");
    const originalParent = modal.parentElement;
    const originalNextSibling = modal.nextElementSibling;
    if (runnerActive) runner.append(modal);
    const inertTargets = runnerActive
      ? Array.from(runner.children).filter((child) => child !== modal)
      : [$(".app-shell")];
    $("#confirm-title").textContent = title;
    $("#confirm-copy").textContent = copy;
    inertTargets.forEach((target) => { target.inert = true; });
    modal.hidden = false;
    const cleanup = (answer) => {
      modal.hidden = true;
      inertTargets.forEach((target) => { target.inert = false; });
      if (runnerActive) {
        if (originalNextSibling) originalParent.insertBefore(modal, originalNextSibling);
        else originalParent.append(modal);
      }
      $("#confirm-ok").removeEventListener("click", accept);
      $("#confirm-cancel").removeEventListener("click", cancel);
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
      resolve(answer);
    };
    const accept = () => cleanup(true);
    const cancel = () => cleanup(false);
    $("#confirm-ok").addEventListener("click", accept);
    $("#confirm-cancel").addEventListener("click", cancel);
    $("#confirm-cancel").focus();
  });
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.viewTarget)));
  $("#global-all-off").addEventListener("click", () => globalAllOff().catch(showError));
  $("#builder-new").addEventListener("click", async () => {
    if (state.builder.dirty && !(await confirmAction("Buang perubahan?", "Perubahan builder yang belum disimpan akan hilang."))) return;
    state.builder = { document: newDocument(), id: null, sourceId: null, expanded: false, dirty: false, selected: { kind: "experiment", path: [] }, summary: null };
    renderBuilder();
  });
  $("#builder-load").addEventListener("click", async () => {
    if (state.builder.dirty && !(await confirmAction("Buka konfigurasi lain?", "Perubahan builder yang belum disimpan akan hilang."))) return;
    loadBuilderConfig($("#builder-config-select").value).catch(showError);
  });
  $("#builder-validate").addEventListener("click", () => validateBuilder().catch(showError));
  $("#builder-save").addEventListener("click", () => saveBuilder().catch(showError));
  $("#builder-use").addEventListener("click", () => useBuilderInExecute().catch(showError));
  $("#inspector-apply").addEventListener("click", () => { try { applyInspector(); } catch (error) { showError(error); } });
  $$("[data-tree-action]").forEach((button) => button.addEventListener("click", () => treeAction(button.dataset.treeAction).catch(showError)));

  $("#execute-config-select").addEventListener("change", () => {
    state.execute.fromBuilder = false;
    loadExecuteConfig().catch(showError);
  });
  $("#execute-validate").addEventListener("click", () => loadExecuteConfig().catch(showError));
  $("#execute-start").addEventListener("click", () => startExperiment().catch(showError));
  $("#refresh-results").addEventListener("click", () => refreshResults().catch(showError));

  $("#relay-connect").addEventListener("click", () => connectRelay().catch(showError));
  $("#relay-disconnect").addEventListener("click", () => disconnectRelay().catch(showError));
  $("#manual-all-off").addEventListener("click", () => allOff().catch(showError));
  $("#manual-apply").addEventListener("click", () => applyManual().catch(showError));
  $$(".lamp-toggle").forEach((button) => button.addEventListener("click", () => {
    const side = button.dataset.side;
    state.manualSides[side] = !state.manualSides[side];
    updateManualSelection();
  }));

  $("#runner-abort").addEventListener("click", () => abortExperiment().catch(showError));
  document.addEventListener("keydown", (event) => {
    const modal = $("#confirm-modal");
    if (!modal.hidden) {
      if (event.key === "Escape") {
        event.preventDefault();
        $("#confirm-cancel").click();
      } else if (event.key === "Tab") {
        const buttons = [$("#confirm-cancel"), $("#confirm-ok")];
        const current = buttons.indexOf(document.activeElement);
        const next = event.shiftKey
          ? (current <= 0 ? buttons.length - 1 : current - 1)
          : (current >= buttons.length - 1 ? 0 : current + 1);
        event.preventDefault();
        buttons[next].focus();
      }
      return;
    }
    if (!$("#runner").classList.contains("is-active")) return;
    const key = normalizeBrowserKey(event);
    if (key === "escape" && ["starting", "running"].includes(state.experiment.status)) {
      event.preventDefault(); abortExperiment().catch(showError); return;
    }
    if (["instruction", "block"].includes(state.experiment.screen) && key === "space") {
      event.preventDefault(); sendExperimentAction({
        action: "continue",
        gate_token: state.experiment.gate_token,
      }); return;
    }
    if (state.experiment.screen === "phase" && state.experiment.waiting_for === "phase" && state.runnerPhaseRenderedAt !== null && state.experiment.phase?.started && state.experiment.phase?.allowed_keys?.includes(key)) {
      event.preventDefault(); sendExperimentAction({
        action: "response",
        key,
        gate_token: state.experiment.gate_token,
      });
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && state.experimentOwner === "this_client" && ["starting", "running"].includes(state.experiment.status)) {
      setStatus("Tab eksperimen tidak terlihat; heartbeat dihentikan dan backend akan menjalankan fail-safe.", "warning");
    }
  });
  window.addEventListener("beforeunload", (event) => {
    if ((state.experimentOwner === "this_client" && ["starting", "running"].includes(state.experiment.status)) || state.builder.dirty) {
      event.preventDefault();
      event.returnValue = "Eksperimen masih aktif atau perubahan builder belum disimpan.";
    }
  });
}

async function initialize() {
  bindEvents();
  updateManualSelection();
  try {
    const system = await api(`/api/system?client_id=${encodeURIComponent(state.clientId)}`);
    state.token = system.control_token;
    updateSystemUi(system);
    state.experiment = system.experiment;
    state.experimentOwner = system.experiment_owner;
    await loadConfigList();
    const defaultId = $("#builder-config-select").value;
    await Promise.all([
      loadBuilderConfig(defaultId),
      loadExecuteConfig($("#execute-config-select").value),
      refreshResults(),
    ]);
    if (system.experiment_owner === "this_client" && ["starting", "running", "completed", "aborted", "error"].includes(system.experiment.status)) {
      state.experiment = system.experiment;
      renderRunner(system.experiment);
      if (["starting", "running"].includes(system.experiment.status)) beginExperimentPolling();
    } else if (system.experiment_owner === "other_client" && ["starting", "running"].includes(system.experiment.status)) {
      setStatus("Sesi aktif sedang dikendalikan oleh tab browser lain.", "warning");
    }
    state.relayPoll = window.setInterval(() => {
      if (!["starting", "running"].includes(state.experiment.status)) {
        refreshRelay().catch(() => {});
      }
    }, 2000);
    if (system.experiment_owner !== "other_client" || !["starting", "running"].includes(system.experiment.status)) {
      setStatus(`Web UI siap · Python ${system.python} · ${system.mode === "demo" ? "simulasi" : "hardware"}.`);
    }
  } catch (error) {
    showError(error);
  }
}

initialize();

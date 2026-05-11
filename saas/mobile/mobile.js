const $ = (id) => document.getElementById(id);

let activeProcessId = "";
let pollTimer = null;
let readyCuts = [];

const presets = {
  viral: { count: 3, minScore: 75, minDuration: 45, maxDuration: 90 },
  short: { count: 5, minScore: 70, minDuration: 25, maxDuration: 55 },
  strict: { count: 3, minScore: 85, minDuration: 45, maxDuration: 70 }
};

const statusLabel = {
  queued: "Na fila",
  running: "Processando",
  completed: "Concluido",
  failed: "Erro",
  cancelled: "Cancelado"
};

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("visible"), 2600);
}

function setField(id, value) {
  const node = $(id);
  if (node) node.value = value;
}

function applyPreset(name) {
  const preset = presets[name] || presets.viral;
  Object.entries(preset).forEach(([id, value]) => setField(id, value));
  document.querySelectorAll(".preset").forEach((button) => {
    button.classList.toggle("active", button.dataset.preset === name);
  });
}

function payload() {
  return {
    url: $("url").value.trim(),
    count: Number($("count").value || 3),
    min_score: Number($("minScore").value || 75),
    min_duration: Number($("minDuration").value || 45),
    max_duration: Number($("maxDuration").value || 90),
    quality: "alta",
    ai_mode: "auto",
    preview_only: false
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": "local-owner",
      ...(options.headers || {})
    }
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Erro na API");
  }
  return data;
}

function shortUrl(url) {
  return String(url || "").replace(/^https?:\/\//, "").slice(0, 90);
}

function renderProcess(item) {
  const status = statusLabel[item.status] || item.status || "Processamento";
  $("processTitle").textContent = item.status === "queued" ? "Corte na fila" : item.status === "running" ? "Criando corte" : item.status === "completed" ? "Corte concluido" : item.status === "cancelled" ? "Corte cancelado" : "Falha no corte";
  $("progressText").textContent = `${Number(item.progress || 0)}%`;
  $("stageText").textContent = item.stage || status;
  $("progressFill").style.width = `${Math.max(0, Math.min(100, Number(item.progress || 0)))}%`;
  $("cancelProcess").disabled = !["queued", "running"].includes(item.status);
  const logs = Array.isArray(item.log) ? item.log.slice(-18).join("\n") : "";
  $("processLog").textContent = logs || item.error || "Sem log.";
  renderProcessReadyCuts(item.ready_cuts || []);
}

function renderProcessReadyCuts(items) {
  const list = $("processReadyCuts");
  list.innerHTML = "";
  if (!items.length) {
    list.className = "process-ready empty";
    list.textContent = "Nenhum corte concluido neste processamento.";
    return;
  }
  list.className = "process-ready";
  items.forEach((item) => {
    const button = document.createElement("button");
    button.className = "process-ready-item";
    button.innerHTML = `<strong>${item.title || item.file}</strong><span>${readyMeta(item)}</span>`;
    button.onclick = () => {
      selectReadyCut(item);
      document.querySelector(".review-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    list.appendChild(button);
  });
}

function cutCard(item) {
  const div = document.createElement("div");
  div.className = "cut-card";
  const status = statusLabel[item.status] || item.status || "Processamento";
  div.innerHTML = `
    <span>${status} - ${item.progress}% - ${item.stage || ""}</span>
    <strong>${shortUrl(item.url)}</strong>
    <button class="ghost">Acompanhar</button>
  `;
  div.querySelector("button").onclick = () => {
    activeProcessId = item.id;
    renderProcess(item);
    startPolling();
  };
  return div;
}

function readyMeta(item) {
  const parts = [];
  if (item.score) parts.push(`Score ${item.score}`);
  if (item.quality_score !== "") parts.push(`Qualidade ${item.quality_score}/100`);
  if (item.duration) parts.push(`${Number(item.duration).toFixed(0)}s`);
  if (item.size_mb) parts.push(`${item.size_mb} MB`);
  return parts.join(" - ") || "Corte pronto";
}

function readyCutCard(item) {
  const div = document.createElement("div");
  div.className = "ready-card";
  div.innerHTML = `
    <div class="ready-thumb"><video muted playsinline preload="metadata" src="${item.video_url}"></video></div>
    <div class="ready-info">
      <span>${readyMeta(item)}</span>
      <strong>${item.title || item.file}</strong>
      <button class="ghost">Assistir</button>
    </div>
  `;
  div.querySelector("button").onclick = () => selectReadyCut(item);
  div.onclick = (event) => {
    if (event.target.tagName !== "BUTTON") selectReadyCut(item);
  };
  return div;
}

function selectReadyCut(item) {
  $("readyTitle").textContent = item.title || item.file || "Corte pronto";
  $("readyPlayer").src = item.video_url;
  $("publicationText").value = item.publication || "";
  document.querySelectorAll(".ready-card").forEach((card) => card.classList.remove("selected"));
  const index = readyCuts.findIndex((cut) => cut.id === item.id);
  const card = document.querySelectorAll(".ready-card")[index];
  if (card) card.classList.add("selected");
}

async function loadReadyCuts() {
  const data = await api("/v1/cortes-prontos?limit=24");
  readyCuts = data.items || [];
  const list = $("readyCutsList");
  list.innerHTML = "";
  if (!readyCuts.length) {
    list.className = "ready-cuts-list empty";
    list.textContent = "Nenhum corte pronto encontrado.";
    $("readyPlayer").removeAttribute("src");
    $("publicationText").value = "";
    return;
  }
  list.className = "ready-cuts-list";
  readyCuts.forEach((item) => list.appendChild(readyCutCard(item)));
  selectReadyCut(readyCuts[0]);
}

async function loadCuts() {
  const cuts = await api("/v1/cortes?limit=20");
  const list = $("cutsList");
  list.innerHTML = "";
  if (!cuts.length) {
    list.className = "cuts-list empty";
    list.textContent = "Nenhum corte criado ainda.";
    return;
  }
  list.className = "cuts-list";
  cuts.forEach((item) => list.appendChild(cutCard(item)));
  if (!activeProcessId) {
    activeProcessId = cuts[0].id;
    renderProcess(cuts[0]);
  }
}

async function createCut() {
  const data = payload();
  if (!data.url) {
    toast("Cole um link do YouTube.");
    return;
  }
  const button = $("createCut");
  button.disabled = true;
  button.textContent = "Criando...";
  try {
    const item = await api("/v1/cortes", {
      method: "POST",
      body: JSON.stringify(data)
    });
    $("url").value = "";
    activeProcessId = item.id;
    renderProcess(item);
    await loadCuts();
    startPolling();
    toast("Corte criado.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Criar corte";
  }
}

async function pollActiveProcess() {
  if (!activeProcessId) return;
  try {
    const item = await api(`/v1/cortes/${activeProcessId}`);
    renderProcess(item);
    if (item.status === "completed" || item.status === "failed" || item.status === "cancelled") {
      clearInterval(pollTimer);
      pollTimer = null;
      await loadCuts();
      await loadReadyCuts();
    }
  } catch (error) {
    toast(error.message);
  }
}

async function cancelProcess() {
  if (!activeProcessId) {
    toast("Nenhum processamento ativo.");
    return;
  }
  $("cancelProcess").disabled = true;
  try {
    const data = await api(`/v1/cortes/${activeProcessId}/cancelar`, { method: "POST" });
    renderProcess(data.process);
    await loadCuts();
    toast(data.cancelled ? "Processamento cancelado." : "Nada para cancelar.");
  } catch (error) {
    toast(error.message);
  }
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(pollActiveProcess, 1600);
  pollActiveProcess();
}

document.querySelectorAll(".preset").forEach((button) => {
  button.onclick = () => applyPreset(button.dataset.preset || "viral");
});

$("createCut").onclick = createCut;
$("refreshCuts").onclick = loadCuts;
$("cancelProcess").onclick = cancelProcess;
$("refreshReadyCuts").onclick = loadReadyCuts;
$("copyPublication").onclick = async () => {
  const text = $("publicationText").value.trim();
  if (!text) {
    toast("Nenhuma legenda selecionada.");
    return;
  }
  await navigator.clipboard.writeText(text);
  toast("Legenda copiada.");
};
$("openTikTokStudio").onclick = () => {
  window.open("https://www.tiktok.com/tiktokstudio/upload?from=upload", "_blank", "noopener");
};

loadCuts().catch((error) => toast(error.message));
loadReadyCuts().catch((error) => toast(error.message));

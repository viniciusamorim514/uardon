/* ============================================
   UARDON - App.js (Minimalista)
   ============================================ */

const $ = (id) => document.getElementById(id);

// Estado
let state = {
    isProcessing: false,
    progress: 0,
    clipsGenerated: [],
    errorMessage: ""
};

// Elements
const uploadSection = $("uploadSection");
const processingSection = $("processingSection");
const resultsSection = $("resultsSection");
const urlInput = $("urlInput");
const processBtn = $("processBtn");
const errorMsg = $("errorMsg");
const statusBadge = $("statusBadge");

// Event Listeners
processBtn.addEventListener("click", handleProcess);
urlInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter" && !state.isProcessing) {
        handleProcess();
    }
});

$("newVideoBtn")?.addEventListener("click", reset);

// Funções
async function handleProcess() {
    const url = urlInput.value.trim();
    
    if (!url) {
        showError("Digite a URL do vídeo");
        return;
    }

    if (!isValidURL(url)) {
        showError("URL inválida");
        return;
    }

    state.isProcessing = true;
    state.errorMessage = "";
    hideError();
    showProcessing();

    try {
        // Enviar para API
        const response = await fetch("/api/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url, quality: "alta" })
        });

        if (!response.ok) {
            throw new Error("Erro ao processar vídeo");
        }

        // Monitorar progresso
        await pollProgress();
        
        // Obter resultados
        await fetchResults();
        
        showResults();
    } catch (error) {
        showError(error.message || "Erro ao processar");
        state.isProcessing = false;
        showUpload();
    }
}

async function pollProgress() {
    const maxAttempts = 300; // 5 minutos
    let attempts = 0;

    while (state.isProcessing && attempts < maxAttempts) {
        try {
            const response = await fetch("/api/state");
            const data = await response.json();

            // Atualizar progresso
            if (data.progress !== undefined) {
                updateProgress(data.progress);
            }

            // Atualizar subtitle com stage
            const subtitle = $("progressSubtitle");
            if (subtitle) {
                subtitle.textContent = data.stage || "Processando...";
            }

            // Se não está mais rodando, check if results are available
            if (!data.running) {
                state.isProcessing = false;
                break;
            }

            attempts++;
            await sleep(1000);
        } catch (error) {
            console.error("Erro ao buscar progresso:", error);
            attempts++;
            await sleep(1000);
        }
    }

    if (attempts >= maxAttempts) {
        showError("Processamento demorou demais");
        state.isProcessing = false;
    }
}

async function fetchResults() {
    try {
        const response = await fetch("/api/candidates");
        const data = await response.json();
        state.clipsGenerated = data.candidates || [];
    } catch (error) {
        console.error("Erro ao buscar resultados:", error);
        state.clipsGenerated = [];
    }
}

function updateProgress(percent) {
    state.progress = percent;
    const fill = $("progressFill");
    const percentText = $("progressPercent");
    
    if (fill) fill.style.width = `${percent}%`;
    if (percentText) percentText.textContent = `${Math.round(percent)}%`;
}

function showUpload() {
    uploadSection.style.display = "block";
    processingSection.style.display = "none";
    resultsSection.style.display = "none";
    updateStatus("ready");
}

function showProcessing() {
    uploadSection.style.display = "none";
    processingSection.style.display = "block";
    resultsSection.style.display = "none";
    updateProgress(0);
    updateStatus("processing");
}

function showResults() {
    uploadSection.style.display = "none";
    processingSection.style.display = "none";
    resultsSection.style.display = "block";
    renderClips();
    updateStatus("ready");
}

function renderClips() {
    const gallery = $("clipsGallery");
    if (!gallery) return;

    gallery.innerHTML = state.clipsGenerated.map((clip, i) => {
        const rank = clip.rank || (i + 1);
        const score = clip.score || clip.viral_score || '-';
        const start = clip.start || clip.timestamp || '-';
        const duration = clip.duration || '-';

        return `
        <div class="clip-card">
            <div class="clip-info">
                <div class="clip-number">Clip ${rank}</div>
                <div class="clip-details">
                    <p><strong>Score:</strong> ${score}</p>
                    <p><strong>Início:</strong> ${start}</p>
                    <p><strong>Duração:</strong> ${duration}s</p>
                </div>
            </div>
            <div class="clip-actions">
                <button onclick="downloadClip('${rank}')">Baixar</button>
            </div>
        </div>
    `}).join("");

    // Mostrar botões de ação se houver clipes
    const actionButtons = $("actionButtons");
    if (actionButtons && state.clipsGenerated.length > 0) {
        actionButtons.style.display = "flex";
    }
}

function showError(message) {
    state.errorMessage = message;
    errorMsg.textContent = message;
    errorMsg.style.display = "block";
    processBtn.disabled = false;
}

function hideError() {
    errorMsg.style.display = "none";
    state.errorMessage = "";
}

function reset() {
    state = {
        isProcessing: false,
        progress: 0,
        clipsGenerated: [],
        errorMessage: ""
    };
    urlInput.value = "";
    hideError();
    showUpload();
    processBtn.disabled = false;
}

function updateStatus(status) {
    if (!statusBadge) return;
    
    statusBadge.className = "badge";
    switch(status) {
        case "ready":
            statusBadge.className += " badge-ready";
            statusBadge.textContent = "Pronto";
            break;
        case "processing":
            statusBadge.className += " badge-processing";
            statusBadge.textContent = "Processando";
            break;
        case "error":
            statusBadge.className += " badge-error";
            statusBadge.textContent = "Erro";
            break;
    }
}

function isValidURL(string) {
    try {
        const url = new URL(string);
        return url.protocol === "http:" || url.protocol === "https:";
    } catch (_) {
        return false;
    }
}

function downloadClip(clipId) {
    // Implementar download
    console.log("Baixando clip:", clipId);
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Inicializar
document.addEventListener("DOMContentLoaded", () => {
    showUpload();
});

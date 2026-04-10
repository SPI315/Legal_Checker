const state = {
  file: null,
  activeSessionId: null,
  pollTimer: null,
  lastTimelineKey: "",
};

const fileInput = document.getElementById("fileInput");
const dropzone = document.getElementById("dropzone");
const uploadForm = document.getElementById("uploadForm");
const selectedFile = document.getElementById("selectedFile");
const submitButton = document.getElementById("submitButton");
const resultStatus = document.getElementById("resultStatus");
const sessionId = document.getElementById("sessionId");
const findingsList = document.getElementById("findingsList");
const timelineList = document.getElementById("timelineList");
const downloadLink = document.getElementById("downloadLink");
const healthStatus = document.getElementById("healthStatus");

fileInput.addEventListener("change", () => {
  state.file = fileInput.files?.[0] ?? null;
  renderSelectedFile();
});

["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  });
});

dropzone.addEventListener("drop", (event) => {
  const [file] = event.dataTransfer.files;
  if (!file) return;
  state.file = file;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  renderSelectedFile();
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.file) {
    resultStatus.textContent = "Сначала выбери файл";
    return;
  }

  stopPolling();
  submitButton.disabled = true;
  resultStatus.textContent = "Очередь";
  sessionId.textContent = "-";
  findingsList.innerHTML = '<div class="empty-state">Документ поставлен в очередь на обработку...</div>';
  timelineList.innerHTML = '<div class="empty-state">История выполнения появится здесь в реальном времени.</div>';
  disableDownload();

  const formData = new FormData();
  formData.append("file", state.file);

  const jurisdiction = document.getElementById("jurisdictionInput").value || "RU";
  const useNer = document.getElementById("useNerInput").checked;

  try {
    const response = await fetch(
      `/api/documents/process/start?jurisdiction=${encodeURIComponent(jurisdiction)}&use_ner=${useNer}`,
      { method: "POST", body: formData }
    );
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Не удалось поставить документ в обработку");
    }

    state.activeSessionId = payload.session_id;
    state.lastTimelineKey = "";
    resultStatus.textContent = payload.status;
    sessionId.textContent = payload.session_id;
    startPolling(payload.session_id);
  } catch (error) {
    resultStatus.textContent = "Ошибка";
    findingsList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    timelineList.innerHTML = '<div class="empty-state">Онлайн-история недоступна из-за ошибки запуска.</div>';
    submitButton.disabled = false;
  }
});

function startPolling(activeSessionId) {
  const tick = async () => {
    await Promise.all([
      loadStatus(activeSessionId),
      loadTimeline(activeSessionId),
    ]);
  };

  tick();
  state.pollTimer = window.setInterval(tick, 1200);
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function loadStatus(activeSessionId) {
  const response = await fetch(`/api/documents/${activeSessionId}/status`);
  if (!response.ok) return;
  const payload = await response.json();
  resultStatus.textContent = payload.status;
  sessionId.textContent = payload.session_id;

  if (["success", "degraded_success", "error"].includes(payload.status)) {
    stopPolling();
    submitButton.disabled = false;
    if (payload.status !== "error") {
      await loadFinalDocument(activeSessionId);
      enableDownload(activeSessionId);
    }
  }
}

async function loadFinalDocument(activeSessionId) {
  const response = await fetch(`/api/documents/${activeSessionId}`);
  if (!response.ok) return;
  const payload = await response.json();
  renderFindings(payload.findings);
}

function renderSelectedFile() {
  selectedFile.textContent = state.file ? `${state.file.name} (${formatBytes(state.file.size)})` : "Файл не выбран";
}

function renderFindings(findings) {
  if (!findings || !findings.length) {
    findingsList.innerHTML = '<div class="empty-state">Пока нет findings. Дождись завершения анализа.</div>';
    return;
  }

  findingsList.innerHTML = findings
    .map((finding) => {
      const warning = finding.legal_basis_supported === false
        ? `<div class="finding-warning">В тексте finding есть правовая ссылка, не подтверждённая evidence. Проверь источники вручную.</div>`
        : "";
      const legalBasis = finding.legal_basis
        ? `<div class="legal-basis"><strong>Правовое основание:</strong><br>${linkify(escapeHtml(finding.legal_basis))}</div>`
        : "";
      const evidence = finding.evidence.length
        ? `<div class="evidence-list">${finding.evidence
            .map(
              (item) => `
                <div class="evidence-item">
                  <div><strong>${escapeHtml(item.title)}</strong></div>
                  <div>${escapeHtml(item.snippet || "Без сниппета")}</div>
                  <div><a href="${item.uri}" target="_blank" rel="noreferrer">${escapeHtml(item.uri)}</a></div>
                </div>`
            )
            .join("")}</div>`
        : '<div class="evidence-item">Evidence отсутствует</div>';

      return `
        <article class="finding-card">
          <h3 class="finding-title">${escapeHtml(finding.title)}</h3>
          <div class="finding-meta">Риск: ${escapeHtml(finding.risk_type)} | Абзац: ${escapeHtml(finding.paragraph_id)} | Confidence: ${finding.confidence}</div>
          ${warning}
          <p class="finding-summary">${escapeHtml(finding.summary)}</p>
          ${legalBasis}
          <p class="finding-suggested"><strong>Правка:</strong> ${escapeHtml(finding.suggested_edit)}</p>
          ${evidence}
        </article>`;
    })
    .join("");
}

async function loadTimeline(activeSessionId) {
  const response = await fetch(`/api/documents/${activeSessionId}/timeline`);
  if (!response.ok) return;
  const timeline = await response.json();
  const items = timeline.filter((item) => item.event_type !== "stage_started" && item.event_type !== "stage_finished");
  const timelineKey = JSON.stringify(items.map((item) => [item.timestamp, item.event_type, item.message]));
  if (timelineKey === state.lastTimelineKey) return;
  state.lastTimelineKey = timelineKey;

  if (!items.length) {
    timelineList.innerHTML = '<div class="empty-state">События пока отсутствуют.</div>';
    return;
  }

  timelineList.innerHTML = items
    .map(
      (item) => `
        <article class="timeline-item">
          <div class="timeline-meta">${escapeHtml(formatTimestamp(item.timestamp))}${item.provider ? ` · ${escapeHtml(item.provider)}` : ""}</div>
          <div class="timeline-title">${escapeHtml(humanizeEvent(item))}</div>
          <div class="timeline-detail">${escapeHtml(buildDetail(item))}</div>
        </article>`
    )
    .join("");
  timelineList.scrollTop = timelineList.scrollHeight;
}

function humanizeEvent(item) {
  const map = {
    session_queued: "Сессия поставлена в очередь",
    candidate_selected: "Выбран кандидат риска",
    retrieval_pass_1: "Retrieval pass 1",
    retrieval_pass_2: "Retrieval pass 2",
    retrieval_pass_3: "Retrieval pass 3",
    evidence_evaluated: "Оценка достаточности evidence",
    retrieval_refine_decision: "Решение о втором retrieval-pass",
    legal_basis_evaluated: "Проверка правового основания",
    legal_basis_refine_decision: "Уточнение поиска по правовому основанию",
    legal_basis_warning: "Предупреждение по правовому основанию",
    llm_analysis: "LLM-анализ",
    finding_accepted: "Finding принят",
    pipeline_finished: "Pipeline завершен",
  };
  return map[item.event_type] || item.event_type;
}

function buildDetail(item) {
  const parts = [];
  if (item.candidate_id) parts.push(`Кандидат: ${item.candidate_id}`);
  if (item.query) parts.push(`Query: ${item.query}`);
  if (typeof item.evidence_count === "number") parts.push(`Evidence: ${item.evidence_count}`);
  if (item.status) parts.push(`Статус: ${item.status}`);
  if (item.findings !== null && item.findings !== undefined) parts.push(`Findings: ${item.findings}`);
  if (item.degraded_flags?.length) parts.push(`Flags: ${item.degraded_flags.join(", ")}`);
  if (item.message) parts.push(item.message);
  return parts.join("\n");
}

function enableDownload(activeSessionId) {
  downloadLink.href = `/api/documents/${activeSessionId}/export.docx`;
  downloadLink.classList.remove("disabled");
  downloadLink.setAttribute("aria-disabled", "false");
}

function disableDownload() {
  downloadLink.href = "#";
  downloadLink.classList.add("disabled");
  downloadLink.setAttribute("aria-disabled", "true");
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(value) {
  return new Date(value).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function linkify(value) {
  return String(value).replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noreferrer">$1</a>'
  ).replaceAll("\n", "<br>");
}

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const payload = await response.json();
    healthStatus.textContent = payload.status === "ok" ? "API готово" : "Проверь backend";
  } catch {
    healthStatus.textContent = "API недоступно";
  }
}

loadHealth();
renderSelectedFile();

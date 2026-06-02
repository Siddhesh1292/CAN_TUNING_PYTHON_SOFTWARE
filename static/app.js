const portSelect = document.querySelector("#portSelect");
const refreshBtn = document.querySelector("#refreshBtn");
const connectBtn = document.querySelector("#connectBtn");
const disconnectBtn = document.querySelector("#disconnectBtn");
const readBtn = document.querySelector("#readBtn");
const writeBtn = document.querySelector("#writeBtn");
const zeroBtn = document.querySelector("#zeroBtn");
const importBtn = document.querySelector("#importBtn");
const exportBtn = document.querySelector("#exportBtn");
const screenshotBtn = document.querySelector("#screenshotBtn");
const importFile = document.querySelector("#importFile");
const selectedCell = document.querySelector("#selectedCell");
const operationName = document.querySelector("#operationName");
const stateBadge = document.querySelector("#stateBadge");
const statusFill = document.querySelector("#statusFill");
const statusMessage = document.querySelector("#statusMessage");
const detectedBaud = document.querySelector("#detectedBaud");
const picId = document.querySelector("#picId");
const inputs = [...document.querySelectorAll(".parameter-field input")];

let selectedInput = null;
let lastHighlightEventId = 0;
const dirtyCells = new Set();

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || data.status?.message || "Request failed");
  }
  return data;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formatValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "";
  }
  const numericValue = Number(value);
  if (Object.is(numericValue, -0) || Math.abs(numericValue) < 0.0005) {
    return "0.00";
  }
  return numericValue.toFixed(2);
}

function markUpdated(input, kind = "read") {
  const field = input.closest(".parameter-field");
  field.classList.remove("read-updated", "write-updated", "zero-updated", "dirty");
  field.classList.add(`${kind}-updated`);

  if (kind === "write") {
    dirtyCells.delete(input.id.replace("cell-", ""));
  }
}

function applyValues(values) {
  for (const [key, value] of Object.entries(values || {})) {
    const input = document.querySelector(`#cell-${CSS.escape(key)}`);
    if (!input) {
      continue;
    }

    if (dirtyCells.has(key)) {
      continue;
    }

    const nextValue = formatValue(value);
    if (input.value !== nextValue && document.activeElement !== input) {
      input.value = nextValue;
    }
  }
}

function applyHighlightEvents(events) {
  for (const event of events || []) {
    if (event.id <= lastHighlightEventId) {
      continue;
    }

    const input = document.querySelector(`#cell-${CSS.escape(event.key)}`);
    if (input) {
      markUpdated(input, event.kind);
    }
    lastHighlightEventId = Math.max(lastHighlightEventId, event.id);
  }
}

function updateStatus(status) {
  operationName.textContent = status.operation || "Idle";
  const state = status.state || "idle";
  stateBadge.textContent = state;
  stateBadge.className = `state-badge ${state}`;
  statusMessage.textContent = status.message || "";

  const percent = status.total ? Math.round((status.progress / status.total) * 100) : 0;
  statusFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;

  detectedBaud.textContent = status.detected_can_bitrate
    ? formatBitrate(status.detected_can_bitrate)
    : "Not detected";
  picId.textContent = status.pic_id || "Not read";

  connectBtn.disabled = status.connected;
  disconnectBtn.disabled = !status.connected;
  readBtn.disabled = !status.connected || status.busy;
  writeBtn.disabled = !status.connected || status.busy || dirtyCells.size === 0;
  writeBtn.textContent = dirtyCells.size > 0 ? `Write (${dirtyCells.size})` : "Write";
  zeroBtn.disabled = !status.connected || (status.busy && !status.zero_active);
  zeroBtn.textContent = status.zero_active ? "Stop Zero" : "Zero Angle";
  zeroBtn.classList.toggle("active", Boolean(status.zero_active));

  applyValues(status.values);
  applyHighlightEvents(status.highlight_events);
}

function formatBitrate(value) {
  const bitrate = Number(value);
  if (!Number.isFinite(bitrate) || bitrate <= 0) {
    return "Not detected";
  }
  if (bitrate >= 1000000 && bitrate % 1000000 === 0) {
    return `${bitrate / 1000000}M`;
  }
  if (bitrate >= 1000) {
    return `${bitrate / 1000}k`;
  }
  return `${bitrate}`;
}

async function refreshPorts() {
  try {
    const current = portSelect.value;
    const data = await api("/api/ports");
    portSelect.innerHTML = "";

    if (!data.ports.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No COM ports";
      portSelect.append(option);
      return;
    }

    for (const port of data.ports) {
      const option = document.createElement("option");
      option.value = port.device;
      option.textContent = `${port.device} - ${port.description}`;
      portSelect.append(option);
    }

    if (current && [...portSelect.options].some((option) => option.value === current)) {
      portSelect.value = current;
    }
  } catch (error) {
    statusMessage.textContent = error.message;
  }
}

async function pollStatus() {
  try {
    const data = await api("/api/status");
    updateStatus(data.status);
  } catch (error) {
    statusMessage.textContent = error.message;
  }
}

function setSelectedInput(input) {
  if (selectedInput) {
    selectedInput.closest(".parameter-field").classList.remove("selected");
  }

  selectedInput = input;
  selectedInput.closest(".parameter-field").classList.add("selected");
  selectedCell.textContent = `Row ${input.dataset.row}, Col ${input.dataset.col} - ${input.dataset.name}`;
  writeBtn.disabled = dirtyCells.size === 0;
}

function markDirty(input) {
  const key = input.id.replace("cell-", "");
  dirtyCells.add(key);
  input.closest(".parameter-field").classList.add("dirty");
  writeBtn.textContent = `Write (${dirtyCells.size})`;
  writeBtn.disabled = false;
}

function getVisibleValues() {
  const values = {};
  for (const input of inputs) {
    values[input.id.replace("cell-", "")] = input.value.trim();
  }
  return values;
}

function applyImportedValues(values) {
  let count = 0;
  for (const [key, value] of Object.entries(values || {})) {
    const input = document.querySelector(`#cell-${CSS.escape(key)}`);
    if (!input) {
      continue;
    }

    input.value = formatValue(value);
    markDirty(input);
    count += 1;
  }
  statusMessage.textContent = `Imported ${count} value(s). Review and press Write.`;
}

refreshBtn.addEventListener("click", refreshPorts);

connectBtn.addEventListener("click", async () => {
  try {
    const data = await api("/api/connect", {
      method: "POST",
      body: JSON.stringify({ port: portSelect.value }),
    });
    updateStatus(data.status);
  } catch (error) {
    statusMessage.textContent = error.message;
  }
});

disconnectBtn.addEventListener("click", async () => {
  try {
    const data = await api("/api/disconnect", { method: "POST" });
    updateStatus(data.status);
  } catch (error) {
    statusMessage.textContent = error.message;
  }
});

readBtn.addEventListener("click", async () => {
  try {
    const data = await api("/api/read", { method: "POST" });
    updateStatus(data.status);
  } catch (error) {
    statusMessage.textContent = error.message;
  }
});

writeBtn.addEventListener("click", async () => {
  const items = [...dirtyCells].map((key) => {
    const input = document.querySelector(`#cell-${CSS.escape(key)}`);
    return {
      row: input.dataset.row,
      col: input.dataset.col,
      value: input.value,
    };
  });

  if (!items.length) {
    statusMessage.textContent = "Modify one or more values before writing.";
    return;
  }

  try {
    const data = await api("/api/write", {
      method: "POST",
      body: JSON.stringify({ items }),
    });
    updateStatus(data.status);
  } catch (error) {
    statusMessage.textContent = error.message;
  }
});

zeroBtn.addEventListener("click", async () => {
  try {
    const data = await api("/api/zero-angle/toggle", { method: "POST" });
    updateStatus(data.status);
  } catch (error) {
    statusMessage.textContent = error.message;
  }
});

importBtn.addEventListener("click", () => {
  importFile.value = "";
  importFile.click();
});

importFile.addEventListener("change", async () => {
  const file = importFile.files[0];
  if (!file) {
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch("/api/import-tuning", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || data.status?.message || "Import failed");
    }
    applyImportedValues(data.values);
    updateStatus(data.status);
  } catch (error) {
    statusMessage.textContent = error.message;
  }
});

exportBtn.addEventListener("click", async () => {
  try {
    const response = await fetch("/api/export-tuning", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values: getVisibleValues() }),
    });
    if (!response.ok) {
      throw new Error("Export failed");
    }
    const blob = await response.blob();
    downloadBlob(blob, "can_tuning_values.xlsx");
    statusMessage.textContent = "Export downloaded.";
  } catch (error) {
    statusMessage.textContent = error.message;
  }
});

screenshotBtn.addEventListener("click", async () => {
  try {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const clone = document.documentElement.cloneNode(true);
    const body = clone.querySelector("body");
    body.style.margin = "0";
    body.style.width = `${document.documentElement.scrollWidth}px`;
    body.style.transform = `translate(${-window.scrollX}px, ${-window.scrollY}px)`;
    body.style.transformOrigin = "top left";

    const serialized = new XMLSerializer().serializeToString(clone);
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
        <foreignObject width="${document.documentElement.scrollWidth}" height="${document.documentElement.scrollHeight}">
          <body xmlns="http://www.w3.org/1999/xhtml" style="margin:0;">
            ${document.documentElement.outerHTML}
          </body>
        </foreignObject>
      </svg>
    `;

    const image = new Image();
    const svgUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = svgUrl;
    });

    const canvas = document.createElement("canvas");
    // capture full page size rather than just viewport
    canvas.width = document.documentElement.scrollWidth;
    canvas.height = document.documentElement.scrollHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas 2D context not available");
    // ensure image is treated as same-origin SVG
    try {
      image.crossOrigin = "anonymous";
    } catch (e) {}
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(svgUrl);

    canvas.toBlob((blob) => {
      if (blob) {
        downloadBlob(blob, "can_tuner_screenshot.png");
        statusMessage.textContent = "Screenshot downloaded.";
      }
    }, "image/png");
  } catch (error) {
    statusMessage.textContent = "Screenshot failed.";
  }
});

for (const input of inputs) {
  input.addEventListener("focus", () => setSelectedInput(input));
  input.addEventListener("click", () => setSelectedInput(input));
  input.addEventListener("input", () => markDirty(input));
}

refreshPorts();
pollStatus();
window.setInterval(pollStatus, 500);

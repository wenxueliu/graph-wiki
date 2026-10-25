const DB_NAME = "brain-vault-capture";
const STORE_NAME = "handles";
const RAW_HANDLE_KEY = "raw-folder";

const folderStatus = document.querySelector("#folderStatus");
const chooseFolder = document.querySelector("#chooseFolder");
const captureButton = document.querySelector("#capture");
const pathHelpButton = document.querySelector("#pathHelp");
const pathPanel = document.querySelector("#pathPanel");
const pathCommand = document.querySelector("#pathCommand");
const copyStatus = document.querySelector("#copyStatus");
const noteField = document.querySelector("#note");
const statusLine = document.querySelector("#status");
const rawPathCommand = "awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 \"/_raw\"; exit}' \"$(git rev-parse --show-toplevel)/.env\"";

let rawDirectoryHandle;

pathCommand.textContent = rawPathCommand;
init();

chooseFolder.addEventListener("click", async () => {
  setBusy(true);
  try {
    if (!("showDirectoryPicker" in window)) {
      throw new Error("This Chrome build does not expose the File System Access API to extension popups.");
    }

    rawDirectoryHandle = await window.showDirectoryPicker({
      id: "graph-wiki-raw",
      mode: "readwrite",
      startIn: "documents"
    });

    await saveRawHandle(rawDirectoryHandle);
    await ensureWritable(rawDirectoryHandle);
    setFolderStatus(rawDirectoryHandle.name);
    setStatus("Selected. Captures will now write markdown files into this folder.", "success");
  } catch (error) {
    if (error.name !== "AbortError") {
      setStatus(error.message, "error");
    }
  } finally {
    setBusy(false);
  }
});

pathHelpButton.addEventListener("click", async () => {
  pathPanel.hidden = !pathPanel.hidden;
  if (pathPanel.hidden) {
    return;
  }

  try {
    await navigator.clipboard.writeText(rawPathCommand);
    copyStatus.textContent = "Copied";
  } catch {
    copyStatus.textContent = "Copy manually";
  }
});

captureButton.addEventListener("click", async () => {
  setBusy(true);
  try {
    rawDirectoryHandle = rawDirectoryHandle || await loadRawHandle();
    if (!rawDirectoryHandle) {
      setStatus("Choose vault/_raw first.", "error");
      return;
    }

    await ensureWritable(rawDirectoryHandle);
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) {
      throw new Error("No active tab found.");
    }

    if (tab.url?.startsWith("chrome://") || tab.url?.startsWith("chrome-extension://")) {
      throw new Error("Chrome blocks content capture on internal browser pages.");
    }

    const [{ result: page }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractPage
    });

    const filename = buildFilename(page.title || tab.title || "web-capture");
    const markdown = buildMarkdown(page, noteField.value);
    const savedFilename = await writeMarkdown(rawDirectoryHandle, filename, markdown);

    noteField.value = "";
    setStatus(`Captured ${savedFilename}`, "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
});

async function init() {
  try {
    rawDirectoryHandle = await loadRawHandle();
    if (rawDirectoryHandle) {
      setFolderStatus(rawDirectoryHandle.name);
      return;
    }
  } catch {
    rawDirectoryHandle = undefined;
  }

  setFolderStatus("No _raw folder selected");
}

async function ensureWritable(directoryHandle) {
  const options = { mode: "readwrite" };
  if (await directoryHandle.queryPermission(options) === "granted") {
    return;
  }

  if (await directoryHandle.requestPermission(options) !== "granted") {
    throw new Error("Write permission was not granted for the selected folder.");
  }
}

async function writeMarkdown(directoryHandle, filename, markdown) {
  const fileHandle = await getUniqueFileHandle(directoryHandle, filename);
  const writable = await fileHandle.createWritable();
  await writable.write(markdown);
  await writable.close();
  return fileHandle.name;
}

async function getUniqueFileHandle(directoryHandle, filename) {
  const extension = ".md";
  const basename = filename.endsWith(extension) ? filename.slice(0, -extension.length) : filename;

  for (let attempt = 0; attempt < 100; attempt += 1) {
    const candidate = attempt === 0 ? filename : `${basename}-${attempt + 1}${extension}`;
    try {
      await directoryHandle.getFileHandle(candidate);
    } catch (error) {
      if (error.name === "NotFoundError") {
        return directoryHandle.getFileHandle(candidate, { create: true });
      }

      throw error;
    }
  }

  return directoryHandle.getFileHandle(`${basename}-${Date.now()}${extension}`, { create: true });
}

function buildFilename(title) {
  const date = new Date().toISOString().slice(0, 10);
  const slug = title
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 72) || "web-capture";

  return `${date}-${slug}.md`;
}

function buildMarkdown(page, note) {
  const now = new Date().toISOString();
  const safeTitle = escapeYaml(page.title || "Untitled page");
  const cleanNote = note.trim();
  const selectedText = page.selection ? `\n## Selection\n\n${page.selection}\n` : "";
  const noteText = cleanNote ? `\n## Capture Note\n\n${cleanNote}\n` : "";
  const description = page.description ? `\n> ${page.description}\n` : "";

  return `---\ntitle: ${safeTitle}\ntags: [web-capture, raw-ingest]\nsources:\n  - ${page.url}\ncreated: ${now}\ncaptured: chrome-extension\n---\n\n# ${page.title || "Untitled page"}\n\n${description}\n- Source: ${page.url}\n- Captured: ${now}\n${noteText}${selectedText}\n## Page Content\n\n${page.text || "_No readable text was found on this page._"}\n`;
}

function escapeYaml(value) {
  return JSON.stringify(String(value));
}

function setFolderStatus(text) {
  folderStatus.textContent = text;
}

function setStatus(message, tone) {
  statusLine.textContent = message;
  if (tone) {
    statusLine.dataset.tone = tone;
  } else {
    delete statusLine.dataset.tone;
  }
}

function setBusy(isBusy) {
  chooseFolder.disabled = isBusy;
  captureButton.disabled = isBusy;
}

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function loadRawHandle() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).get(RAW_HANDLE_KEY);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => db.close();
  });
}

async function saveRawHandle(handle) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put(handle, RAW_HANDLE_KEY);
    transaction.oncomplete = () => {
      db.close();
      resolve();
    };
    transaction.onerror = () => reject(transaction.error);
  });
}

function extractPage() {
  const selectorsToRemove = "script, style, noscript, svg, canvas, iframe, nav, footer, aside, form";
  const clone = document.body ? document.body.cloneNode(true) : document.documentElement.cloneNode(true);
  clone.querySelectorAll(selectorsToRemove).forEach((node) => node.remove());

  const article = clone.querySelector("article, main, [role='main']") || clone;
  const rawText = article.innerText || clone.innerText || document.body?.innerText || "";
  const text = rawText
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, 140000);

  const selection = String(window.getSelection?.() || "")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, 30000);

  const description = document.querySelector("meta[name='description'], meta[property='og:description']")
    ?.getAttribute("content")
    ?.trim() || "";

  return {
    title: document.title,
    url: location.href,
    description,
    selection,
    text
  };
}

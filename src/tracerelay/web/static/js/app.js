document.addEventListener("DOMContentLoaded", () => {
  const path = window.location.pathname;

  for (const link of document.querySelectorAll(".sidebar-nav-link")) {
    const href = link.getAttribute("href") || "";
    const isTasks = href === "/tasks" && (path === "/" || path.startsWith("/tasks"));
    const isMemory = href === "/memory" && path.startsWith("/memory");
    if (isTasks || isMemory) {
      link.classList.add("is-active");
    }
  }

  const storage = {
    get(key, fallback) {
      try {
        return window.localStorage.getItem(key) ?? fallback;
      } catch {
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch {
        return;
      }
    },
  };

  const renderCodeLines = (target, code) => {
    if (!target) return;
    const lines = (code || "{}").split("\n");
    target.innerHTML = "";
    for (const line of lines) {
      const item = document.createElement("li");
      const codeNode = document.createElement("code");
      codeNode.textContent = line || " ";
      item.appendChild(codeNode);
      target.appendChild(item);
    }
  };

  const parsePixels = (value, fallback) => {
    const parsed = Number.parseFloat(String(value || "").replace("px", "").trim());
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const initResizableGroups = () => {
    const handles = [...document.querySelectorAll("[data-resize-handle]")];
    const defaultMainMin = 420;

    const storageKeyFor = (group, handle) =>
      `${group.dataset.resizableKey || "tracerelay.layout"}.${handle.dataset.resizeVar || "pane"}`;

    const getBounds = (group, handle) => {
      const min = parsePixels(handle.dataset.resizeMin, 220);
      const configuredMax = parsePixels(handle.dataset.resizeMax, 9999);
      const mainMin = parsePixels(handle.dataset.resizeMainMin, defaultMainMin);
      const groupWidth = group.getBoundingClientRect().width;
      const maxByContainer = Math.max(min, groupWidth - mainMin);
      return { min, max: Math.min(configuredMax, maxByContainer) };
    };

    const setWidth = (group, handle, width) => {
      const variable = handle.dataset.resizeVar;
      if (!variable) return;
      const bounds = getBounds(group, handle);
      const clamped = Math.max(bounds.min, Math.min(bounds.max, width));
      group.style.setProperty(variable, `${Math.round(clamped)}px`);
      storage.set(storageKeyFor(group, handle), String(Math.round(clamped)));
    };

    for (const handle of handles) {
      const group = handle.closest("[data-resizable-group]");
      if (!group) continue;
      const variable = handle.dataset.resizeVar;
      if (!variable) continue;

      const stored = storage.get(storageKeyFor(group, handle), "");
      if (stored) {
        setWidth(group, handle, parsePixels(stored, parsePixels(getComputedStyle(group).getPropertyValue(variable), 320)));
      }

      const startDrag = (clientX) => {
        if (window.getComputedStyle(handle).display === "none") return null;
        handle.classList.add("is-dragging");
        document.body.classList.add("is-resizing-panes");
        return {
          startX: clientX,
          startWidth: parsePixels(getComputedStyle(group).getPropertyValue(variable), parsePixels(stored, 320)),
          side: handle.dataset.resizeSide || "left",
        };
      };

      handle.addEventListener("pointerdown", (event) => {
        const drag = startDrag(event.clientX);
        if (!drag) return;
        event.preventDefault();
        handle.setPointerCapture?.(event.pointerId);

        const onMove = (moveEvent) => {
          const delta = moveEvent.clientX - drag.startX;
          const width = drag.side === "right" ? drag.startWidth - delta : drag.startWidth + delta;
          setWidth(group, handle, width);
        };

        const onUp = () => {
          handle.classList.remove("is-dragging");
          document.body.classList.remove("is-resizing-panes");
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
      });

      handle.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const current = parsePixels(getComputedStyle(group).getPropertyValue(variable), 320);
        const step = event.shiftKey ? 48 : 24;
        const width = (handle.dataset.resizeSide || "left") === "right" ? current - direction * step : current + direction * step;
        setWidth(group, handle, width);
        event.preventDefault();
      });
    }
  };

  const rows = [...document.querySelectorAll("[data-task-row]")];
  const searchInput = document.querySelector("[data-task-filter-search]");
  const statusSelect = document.querySelector("[data-task-filter-status]");
  const familySelect = document.querySelector("[data-task-filter-family]");
  const resultNode = document.querySelector("[data-task-results]");

  const inspector = {
    title: document.querySelector("[data-task-inspector-title]"),
    subtitle: document.querySelector("[data-task-inspector-subtitle]"),
    status: document.querySelector("[data-task-inspector-status]"),
    family: document.querySelector("[data-task-inspector-family]"),
    schema: document.querySelector("[data-task-inspector-schema]"),
    prompt: document.querySelector("[data-task-inspector-prompt]"),
    issue: document.querySelector("[data-task-inspector-issue]"),
    next: document.querySelector("[data-task-inspector-next]"),
    reason: document.querySelector("[data-task-inspector-reason]"),
    processed: document.querySelector("[data-task-inspector-processed]"),
    branch: document.querySelector("[data-task-inspector-branch]"),
    keys: document.querySelector("[data-task-inspector-keys]"),
    schemaCode: document.querySelector("[data-task-inspector-schema-code]"),
  };

  const compareTray = document.querySelector("[data-compare-tray]");
  const compareList = document.querySelector("[data-compare-list]");
  const compareClear = document.querySelector("[data-compare-clear]");
  const compareButtons = [...document.querySelectorAll("[data-compare-toggle]")];

  const keys = {
    search: "tracerelay.tasks.search",
    status: "tracerelay.tasks.status",
    family: "tracerelay.tasks.family",
    compare: "tracerelay.tasks.compare",
  };

  if (searchInput) searchInput.value = storage.get(keys.search, "");
  if (statusSelect) statusSelect.value = storage.get(keys.status, "");
  if (familySelect) familySelect.value = storage.get(keys.family, "");

  const readPinned = () => {
    try {
      return JSON.parse(storage.get(keys.compare, "[]"));
    } catch {
      return [];
    }
  };

  const writePinned = (items) => {
    storage.set(keys.compare, JSON.stringify(items));
  };

  const setInspector = (row) => {
    if (!row || !inspector.title) return;

    for (const item of rows) {
      item.classList.toggle("is-selected", item === row);
    }

    inspector.title.textContent = row.dataset.taskLabel || "Selected run";
    inspector.subtitle.textContent = row.dataset.taskId || "";
    if (inspector.status) {
      const status = row.dataset.taskStatus || "unknown";
      inspector.status.textContent = status;
      inspector.status.className = `status-pill status-${status.toLowerCase()}`;
    }
    if (inspector.family) inspector.family.textContent = row.dataset.taskFamily || "n/a";
    if (inspector.schema) inspector.schema.textContent = row.dataset.taskSchema || "v n/a";
    if (inspector.prompt) inspector.prompt.textContent = row.dataset.taskPrompt || "";
    if (inspector.issue) inspector.issue.textContent = row.dataset.taskIssue || "n/a";
    if (inspector.next) inspector.next.textContent = row.dataset.taskNext || "n/a";
    if (inspector.reason) inspector.reason.textContent = row.dataset.taskReason || "n/a";
    if (inspector.processed) inspector.processed.textContent = row.dataset.taskProcessed || "n/a";
    if (inspector.branch) inspector.branch.textContent = row.dataset.taskBranch || "n/a";
    if (inspector.keys) inspector.keys.textContent = row.dataset.taskKeys || "none";
    renderCodeLines(inspector.schemaCode, row.dataset.taskSchemaCode || "{}");
  };

  const applyTaskFilters = () => {
    if (!rows.length) return;

    const search = (searchInput?.value || "").trim().toLowerCase();
    const status = (statusSelect?.value || "").trim().toLowerCase();
    const family = (familySelect?.value || "").trim().toLowerCase();
    let visible = 0;
    let firstVisible = null;

    storage.set(keys.search, search);
    storage.set(keys.status, status);
    storage.set(keys.family, family);

    for (const row of rows) {
      const haystack = row.dataset.search || "";
      const rowStatus = row.dataset.status || "";
      const rowFamily = row.dataset.family || "";
      const matchesSearch = !search || haystack.includes(search);
      const matchesStatus = !status || rowStatus === status;
      const matchesFamily = !family || rowFamily === family;
      const show = matchesSearch && matchesStatus && matchesFamily;
      row.hidden = !show;
      if (show) {
        visible += 1;
        if (!firstVisible) firstVisible = row;
      }
    }

    if (resultNode) resultNode.textContent = String(visible);
    if (firstVisible) setInspector(firstVisible);
  };

  const renderPinned = () => {
    if (!compareTray || !compareList) return;

    const pinned = readPinned().slice(0, 2);
    compareList.innerHTML = "";
    compareTray.hidden = pinned.length === 0;

    for (const item of pinned) {
      const article = document.createElement("article");
      article.className = "compare-item";
      article.innerHTML = `
        <div class="compare-item-main">
          <strong>${item.label}</strong>
          <span>${item.status} · ${item.schema}</span>
        </div>
        <a class="row-action" href="${item.href}">Open trace</a>
      `;
      compareList.appendChild(article);
    }

    for (const button of compareButtons) {
      const row = button.closest("[data-task-row]");
      const taskId = row?.dataset.taskId || "";
      const isPinned = pinned.some((item) => item.taskId === taskId);
      button.textContent = isPinned ? "Pinned" : "Pin";
      button.classList.toggle("is-active", isPinned);
    }
  };

  for (const row of rows) {
    row.addEventListener("click", (event) => {
      const target = event.target;
      if (target instanceof HTMLElement && (target.closest("a") || target.closest("[data-compare-toggle]"))) {
        return;
      }
      setInspector(row);
    });
    row.querySelector("[data-task-select]")?.addEventListener("click", () => setInspector(row));
  }

  searchInput?.addEventListener("input", applyTaskFilters);
  statusSelect?.addEventListener("change", applyTaskFilters);
  familySelect?.addEventListener("change", applyTaskFilters);

  for (const button of compareButtons) {
    button.addEventListener("click", () => {
      const row = button.closest("[data-task-row]");
      if (!row) return;

      const pinned = readPinned();
      const taskId = row.dataset.taskId || "";
      const existing = pinned.findIndex((item) => item.taskId === taskId);
      if (existing >= 0) {
        pinned.splice(existing, 1);
      } else {
        if (pinned.length >= 2) pinned.shift();
        pinned.push({
          taskId,
          label: row.dataset.taskLabel || taskId,
          status: row.dataset.taskStatus || "unknown",
          schema: row.dataset.taskSchema || "n/a",
          href: row.dataset.taskHref || "#",
        });
      }
      writePinned(pinned);
      renderPinned();
    });
  }

  compareClear?.addEventListener("click", () => {
    writePinned([]);
    renderPinned();
  });

  applyTaskFilters();
  renderPinned();

  const activatePane = (groupName, paneName) => {
    const tabs = document.querySelectorAll(`[data-pane-group="${groupName}"][data-pane-tab]`);
    const panels = document.querySelectorAll(`[data-pane-group="${groupName}"][data-pane-panel]`);
    tabs.forEach((tab) => {
      tab.classList.toggle("is-active", tab.dataset.paneTab === paneName);
    });
    panels.forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.panePanel === paneName);
    });
  };

  for (const tab of document.querySelectorAll("[data-pane-tab]")) {
    tab.addEventListener("click", () => {
      activatePane(tab.dataset.paneGroup || "default", tab.dataset.paneTab);
    });
  }

  const treeRoots = [...document.querySelectorAll("[data-tree-root]")];
  const getTreeRoot = (name) =>
    treeRoots.find((node) => node.dataset.treeRoot === name) || null;

  for (const button of document.querySelectorAll("[data-tree-expand]")) {
    button.addEventListener("click", () => {
      const root = getTreeRoot(button.dataset.treeExpand);
      root?.querySelectorAll("details").forEach((node) => {
        node.open = true;
      });
    });
  }

  for (const button of document.querySelectorAll("[data-tree-collapse]")) {
    button.addEventListener("click", () => {
      const root = getTreeRoot(button.dataset.treeCollapse);
      root?.querySelectorAll("details").forEach((node, index) => {
        node.open = index === 0;
      });
    });
  }

  const attemptRows = [...document.querySelectorAll("[data-attempt-row]")];
  const attemptInspector = {
    label: document.querySelector("[data-attempt-inspector-label]"),
    status: document.querySelector("[data-attempt-inspector-status]"),
    schema: document.querySelector("[data-attempt-inspector-schema]"),
    issue: document.querySelector("[data-attempt-inspector-issue]"),
    next: document.querySelector("[data-attempt-inspector-next]"),
    reason: document.querySelector("[data-attempt-inspector-reason]"),
    payload: document.querySelector("[data-attempt-inspector-payload]"),
    coverage: document.querySelector("[data-attempt-inspector-coverage]"),
  };

  const setAttemptInspector = (row) => {
    if (!row || !attemptInspector.label) return;

    attemptRows.forEach((item) => {
      item.classList.toggle("is-selected", item === row);
    });

    const status = row.dataset.attemptStatus || "unknown";
    attemptInspector.label.textContent = row.dataset.attemptLabel || "n/a";
    attemptInspector.schema.textContent = row.dataset.attemptSchema || "v n/a";
    attemptInspector.issue.textContent = row.dataset.attemptIssue || "n/a";
    attemptInspector.next.textContent = row.dataset.attemptNext || "n/a";
    attemptInspector.reason.textContent = row.dataset.attemptReason || "n/a";
    attemptInspector.status.textContent = status;
    attemptInspector.status.className = `status-pill status-${status.toLowerCase()}`;
    renderCodeLines(attemptInspector.payload, row.dataset.attemptPayloadCode || "{}");
    renderCodeLines(attemptInspector.coverage, row.dataset.attemptCoverageCode || "{}");
  };

  for (const row of attemptRows) {
    row.addEventListener("click", () => setAttemptInspector(row));
  }
  const defaultAttempt = attemptRows.find((row) => row.dataset.attemptDefault === "true") || attemptRows[0];
  if (defaultAttempt) setAttemptInspector(defaultAttempt);

  initResizableGroups();
});

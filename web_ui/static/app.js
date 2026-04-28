const initialConfig = JSON.parse(document.getElementById("initial-config").textContent);

const state = {
  lastSavedSnapshot: snapshotConfig(initialConfig),
  generating: false,
};

const els = {
  dirtyIndicator: document.getElementById("dirty-indicator"),
  actionStatus: document.getElementById("action-status"),
  sourceList: document.getElementById("source-list"),
  addSourceButton: document.getElementById("add-source-button"),
  saveButton: document.getElementById("save-button"),
  restoreButton: document.getElementById("restore-button"),
  generateButton: document.getElementById("generate-button"),
  progressStage: document.getElementById("progress-stage"),
  progressMessage: document.getElementById("progress-message"),
  progressPercent: document.getElementById("progress-percent"),
  progressFill: document.getElementById("progress-fill"),
  resultEmpty: document.getElementById("result-empty"),
  resultContent: document.getElementById("result-content"),
  resultTime: document.getElementById("result-time"),
  resultCandidates: document.getElementById("result-candidates"),
  resultArticles: document.getElementById("result-articles"),
  resultMode: document.getElementById("result-mode"),
  downloadRow: document.getElementById("download-row"),
  statsBody: document.getElementById("stats-body"),
  configSummary: document.getElementById("config-summary"),
  resultPanel: document.getElementById("result-panel"),
};

function renderConfig(config) {
  document.getElementById("start_date").value = config.runtime.start_date || "";
  document.getElementById("end_date").value = config.runtime.end_date || "";
  document.getElementById("recent_hours").value = config.runtime.recent_hours || 168;
  document.getElementById("article_limit_per_source").value = config.runtime.article_limit_per_source || 10;
  document.getElementById("max_items_per_section").value = config.runtime.max_items_per_section || 5;
  document.getElementById("max_articles_for_analysis").value = config.runtime.max_articles_for_analysis || 40;
  document.getElementById("min_items_for_section_analysis").value = config.runtime.min_items_for_section_analysis || 2;
  document.getElementById("summary_min_chars").value = config.summary.min_chars || 100;
  document.getElementById("summary_max_chars").value = config.summary.max_chars || 300;
  document.getElementById("quality_min_score").value = config.quality.min_score || 68;
  document.getElementById("llm_enabled").checked = !!config.llm.enabled;

  els.sourceList.innerHTML = "";
  config.sources.forEach((source, index) => {
    els.sourceList.appendChild(createSourceCard(source, index));
  });
  updateDirtyIndicator();
}

function createSourceCard(source, index) {
  const card = document.createElement("section");
  card.className = "source-card";
  const inheritRuntimeLimit = source.inherit_runtime_limit !== false;
  const displayedMaxItems = inheritRuntimeLimit
    ? readNumber("article_limit_per_source", source.max_items ?? 10)
    : (source.max_items ?? 10);
  card.innerHTML = `
    <div class="source-card-top">
      <div class="source-title-group">
        <span class="source-order">${index + 1}</span>
        <div>
          <strong>${escapeHtml(source.name || "未命名站点")}</strong>
          <div class="helper-text">${escapeHtml(source.homepage_url || source.url || "")}</div>
        </div>
      </div>
      <div class="source-actions">
        <button type="button" class="mini-btn" data-action="move-up">上移</button>
        <button type="button" class="mini-btn" data-action="move-down">下移</button>
        <button type="button" class="mini-btn" data-action="delete">删除</button>
      </div>
    </div>
    <div class="source-body">
      <div class="field-grid">
        <label class="switch-field">
          <input type="checkbox" data-field="enabled" ${source.enabled !== false ? "checked" : ""} />
          <span>启用该站点</span>
        </label>
        <label class="field">
          <span>区域</span>
          <select data-field="region">
            ${selectOptions(source.region || "custom", ["domestic", "foreign", "research", "custom"])}
          </select>
        </label>
        <label class="field">
          <span>站点名称</span>
          <input type="text" data-field="name" value="${escapeAttr(source.name || "")}" />
        </label>
        <label class="field">
          <span>抓取类型</span>
          <select data-field="kind">
            ${selectOptions(source.kind || "html", ["html", "rss"])}
          </select>
        </label>
        <label class="field">
          <span>语言</span>
          <select data-field="locale">
            ${selectOptions(source.locale || "zh", ["zh", "en"])}
          </select>
        </label>
        <label class="field">
          <span>权重</span>
          <input type="number" step="0.01" data-field="source_weight" value="${escapeAttr(source.source_weight ?? 1)}" />
        </label>
        <label class="field">
          <span>抓取数量上限</span>
          <input type="number" min="1" data-field="max_items" value="${escapeAttr(displayedMaxItems)}" />
          <label class="inline-toggle">
            <input type="checkbox" data-field="inherit_runtime_limit" ${inheritRuntimeLimit ? "checked" : ""} />
            <span>跟随上方全局抓取上限</span>
          </label>
        </label>
        <label class="field">
          <span>主页地址</span>
          <input type="text" data-field="homepage_url" value="${escapeAttr(source.homepage_url || source.url || "")}" />
        </label>
        <label class="field">
          <span>抓取地址</span>
          <input type="text" data-field="url" value="${escapeAttr(source.url || "")}" />
        </label>
        <label class="field">
          <span>强制分类</span>
          <select data-field="forced_category">
            ${selectOptions(source.forced_category || "", ["", "ai_application", "ai_model", "ai_safety", "ai_investment", "research_paper"])}
          </select>
        </label>
      </div>
      <div class="switch-row">
        <label class="switch-field">
          <input type="checkbox" data-field="assume_relevant" ${source.assume_relevant ? "checked" : ""} />
          <span>默认视为 AI 相关</span>
        </label>
        <label class="switch-field">
          <input type="checkbox" data-field="skip_hydration" ${source.skip_hydration ? "checked" : ""} />
          <span>跳过正文抓取</span>
        </label>
        <label class="switch-field">
          <input type="checkbox" data-field="prefer_listing_title" ${source.prefer_listing_title ? "checked" : ""} />
          <span>优先使用列表页标题</span>
        </label>
        <label class="switch-field">
          <input type="checkbox" data-field="same_domain_only" ${source.same_domain_only ? "checked" : ""} />
          <span>仅抓同域链接</span>
        </label>
        <label class="switch-field">
          <input type="checkbox" data-field="external_only" ${source.external_only ? "checked" : ""} />
          <span>仅抓外链</span>
        </label>
      </div>
      <div class="advanced-grid">
        <label class="field">
          <span>列表选择器</span>
          <textarea data-field="listing_selectors">${escapeHtml((source.listing_selectors || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>URL 包含规则</span>
          <textarea data-field="include_patterns">${escapeHtml((source.include_patterns || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>URL 排除规则</span>
          <textarea data-field="exclude_patterns">${escapeHtml((source.exclude_patterns || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>正文选择器</span>
          <textarea data-field="article_selectors">${escapeHtml((source.article_selectors || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>时间选择器</span>
          <textarea data-field="date_selectors">${escapeHtml((source.date_selectors || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>配图选择器</span>
          <textarea data-field="image_selectors">${escapeHtml((source.image_selectors || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>RSS 标签过滤</span>
          <textarea data-field="required_entry_tags">${escapeHtml((source.required_entry_tags || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>RSS 关键词过滤</span>
          <textarea data-field="required_entry_keywords">${escapeHtml((source.required_entry_keywords || []).join("\n"))}</textarea>
        </label>
      </div>
    </div>
  `;

  card.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (action === "delete") {
      card.remove();
      refreshSourceOrder();
      updateDirtyIndicator();
      return;
    }
    if (action === "move-up" && card.previousElementSibling) {
      card.parentNode.insertBefore(card, card.previousElementSibling);
      refreshSourceOrder();
      updateDirtyIndicator();
      return;
    }
    if (action === "move-down" && card.nextElementSibling) {
      card.parentNode.insertBefore(card.nextElementSibling, card);
      refreshSourceOrder();
      updateDirtyIndicator();
    }
  });

  card.addEventListener("change", (event) => {
    if (event.target.matches('[data-field="inherit_runtime_limit"]')) {
      syncSourceLimitField(card);
    }
  });

  syncSourceLimitField(card);

  return card;
}

function readConfigFromForm() {
  const config = structuredClone(initialConfig);

  config.runtime.start_date = document.getElementById("start_date").value || null;
  config.runtime.end_date = document.getElementById("end_date").value || null;
  config.runtime.recent_hours = readNumber("recent_hours", 168);
  config.runtime.article_limit_per_source = readNumber("article_limit_per_source", 10);
  config.runtime.max_items_per_section = readNumber("max_items_per_section", 5);
  config.runtime.max_articles_for_analysis = readNumber("max_articles_for_analysis", 40);
  config.runtime.min_items_for_section_analysis = readNumber("min_items_for_section_analysis", 2);

  config.summary.min_chars = readNumber("summary_min_chars", 100);
  config.summary.max_chars = Math.max(readNumber("summary_max_chars", 300), config.summary.min_chars);
  config.quality.min_score = readNumber("quality_min_score", 68);
  config.llm.enabled = document.getElementById("llm_enabled").checked;

  config.sources = [...els.sourceList.querySelectorAll(".source-card")].map((card) => {
    return {
      enabled: card.querySelector('[data-field="enabled"]').checked,
      region: card.querySelector('[data-field="region"]').value,
      name: card.querySelector('[data-field="name"]').value.trim(),
      kind: card.querySelector('[data-field="kind"]').value,
      locale: card.querySelector('[data-field="locale"]').value,
      source_weight: parseFloat(card.querySelector('[data-field="source_weight"]').value || "1"),
      max_items: parseInt(card.querySelector('[data-field="max_items"]').value || "10", 10),
      inherit_runtime_limit: card.querySelector('[data-field="inherit_runtime_limit"]').checked,
      homepage_url: card.querySelector('[data-field="homepage_url"]').value.trim(),
      url: card.querySelector('[data-field="url"]').value.trim(),
      forced_category: card.querySelector('[data-field="forced_category"]').value || null,
      assume_relevant: card.querySelector('[data-field="assume_relevant"]').checked,
      skip_hydration: card.querySelector('[data-field="skip_hydration"]').checked,
      prefer_listing_title: card.querySelector('[data-field="prefer_listing_title"]').checked,
      same_domain_only: card.querySelector('[data-field="same_domain_only"]').checked,
      external_only: card.querySelector('[data-field="external_only"]').checked,
      listing_selectors: parseList(card.querySelector('[data-field="listing_selectors"]').value),
      include_patterns: parseList(card.querySelector('[data-field="include_patterns"]').value),
      exclude_patterns: parseList(card.querySelector('[data-field="exclude_patterns"]').value),
      article_selectors: parseList(card.querySelector('[data-field="article_selectors"]').value),
      date_selectors: parseList(card.querySelector('[data-field="date_selectors"]').value),
      image_selectors: parseList(card.querySelector('[data-field="image_selectors"]').value),
      required_entry_tags: parseList(card.querySelector('[data-field="required_entry_tags"]').value),
      required_entry_keywords: parseList(card.querySelector('[data-field="required_entry_keywords"]').value),
    };
  });

  return config;
}

function refreshSourceOrder() {
  [...els.sourceList.querySelectorAll(".source-card")].forEach((card, index) => {
    card.querySelector(".source-order").textContent = String(index + 1);
  });
}

function syncSourceLimitField(card) {
  const inheritToggle = card.querySelector('[data-field="inherit_runtime_limit"]');
  const maxItemsInput = card.querySelector('[data-field="max_items"]');
  if (!inheritToggle || !maxItemsInput) {
    return;
  }
  if (inheritToggle.checked) {
    maxItemsInput.value = String(readNumber("article_limit_per_source", 10));
    maxItemsInput.disabled = true;
    maxItemsInput.title = "当前站点跟随上方全局抓取上限";
    return;
  }
  if (!maxItemsInput.value) {
    maxItemsInput.value = String(readNumber("article_limit_per_source", 10));
  }
  maxItemsInput.disabled = false;
  maxItemsInput.title = "";
}

function syncAllInheritedSourceLimits() {
  [...els.sourceList.querySelectorAll(".source-card")].forEach((card) => syncSourceLimitField(card));
}

function updateDirtyIndicator() {
  const currentSnapshot = snapshotConfig(readConfigFromForm());
  const isDirty = currentSnapshot !== state.lastSavedSnapshot;
  els.dirtyIndicator.textContent = isDirty ? "当前配置未保存" : "当前配置已保存";
  els.dirtyIndicator.className = `status-badge ${isDirty ? "status-dirty" : "status-saved"}`;
}

async function saveConfig(showMessage = true) {
  const payload = readConfigFromForm();
  setActionStatus("正在保存配置...");
  const response = await fetch("/api/config/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("配置保存失败");
  }
  const data = await response.json();
  state.lastSavedSnapshot = snapshotConfig(data.config);
  if (showMessage) {
    setActionStatus(`配置已保存：${data.saved_at}`);
  }
  updateDirtyIndicator();
  return data.config;
}

async function restoreDefaults() {
  const response = await fetch("/api/config/default");
  if (!response.ok) {
    throw new Error("默认配置加载失败");
  }
  const data = await response.json();
  renderConfig(data.config);
  setActionStatus("已恢复默认配置，请按需保存。");
}

async function generateReport() {
  const currentSnapshot = snapshotConfig(readConfigFromForm());
  if (currentSnapshot !== state.lastSavedSnapshot) {
    const shouldSave = window.confirm("当前配置尚未保存，是否先保存配置再生成日报？");
    if (!shouldSave) {
      setActionStatus("已取消生成，请先保存配置。");
      return;
    }
    await saveConfig(false);
  }

  state.generating = true;
  toggleButtons(true);
  updateProgress({ progress: 2, stage: "initializing", message: "正在创建生成任务..." });
  setActionStatus("正在生成日报，请稍候...");
  scrollResultIntoView();

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readConfigFromForm()),
    });
    if (!response.ok) {
      throw new Error("日报生成失败");
    }
    const data = await response.json();
    await pollJob(data.job_id);
  } finally {
    state.generating = false;
    toggleButtons(false);
  }
}

async function pollJob(jobId) {
  while (true) {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) {
      throw new Error("任务状态获取失败");
    }
    const data = await response.json();
    updateProgress(data);

    if (data.status === "completed") {
      renderResult(data.result);
      setActionStatus("日报生成完成，可直接下载。");
      return;
    }

    if (data.status === "failed") {
      throw new Error(data.message || "日报生成失败");
    }

    await wait(1200);
  }
}

function updateProgress(data) {
  const progress = Math.max(0, Math.min(Number(data.progress || 0), 100));
  els.progressStage.textContent = formatStage(data.stage || "queued");
  els.progressMessage.textContent = data.message || "任务等待中...";
  els.progressPercent.textContent = `${progress}%`;
  els.progressFill.style.width = `${progress}%`;
}

function renderResult(data) {
  els.resultEmpty.classList.add("hidden");
  els.resultContent.classList.remove("hidden");
  els.resultTime.textContent = data.generated_at;
  els.resultCandidates.textContent = `${data.candidate_count} 条`;
  els.resultArticles.textContent = `${data.article_count} 条`;
  els.resultMode.textContent = data.llm_used ? "Qwen API" : "规则摘要";
  els.configSummary.textContent = formatConfigSummary(data.config_summary || {});

  els.downloadRow.innerHTML = "";
  [
    ["下载 Word", data.files.docx],
    ["下载 Markdown", data.files.markdown],
    ["下载统计 TXT", data.files.stats],
    ["下载日志", data.files.log],
  ].forEach(([label, href]) => {
    if (!href) return;
    const link = document.createElement("a");
    link.className = "btn btn-primary";
    link.href = href;
    link.textContent = label;
    els.downloadRow.appendChild(link);
  });

  els.statsBody.innerHTML = "";
  data.source_stats.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(item.name)}</td>
      <td>${item.fetched_count}</td>
      <td>${item.filtered_count}</td>
      <td>${item.deduplicated_count}</td>
      <td>${item.selected_count}</td>
      <td>${escapeHtml(item.status)}</td>
    `;
    els.statsBody.appendChild(row);
  });
  scrollResultIntoView();
}

function toggleButtons(disabled) {
  els.saveButton.disabled = disabled;
  els.restoreButton.disabled = disabled;
  els.generateButton.disabled = disabled;
  els.addSourceButton.disabled = disabled;
}

function setActionStatus(text) {
  els.actionStatus.textContent = text;
}

function scrollResultIntoView() {
  els.resultPanel?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function formatStage(stage) {
  const mapping = {
    queued: "任务排队中",
    initializing: "准备环境",
    fetching: "抓取候选文章",
    filtering: "初筛过滤",
    deduplicating: "去重排序",
    analyzing: "摘要翻译与分类",
    quality: "质量筛选",
    images: "整理配图",
    exporting: "导出文档",
    completed: "生成完成",
    failed: "生成失败",
  };
  return mapping[stage] || "执行中";
}

function addBlankSource() {
  els.sourceList.appendChild(
    createSourceCard(
      {
        enabled: true,
        region: "custom",
        name: "",
        kind: "html",
        locale: "zh",
        source_weight: 1,
        max_items: readNumber("article_limit_per_source", 10),
        inherit_runtime_limit: true,
        homepage_url: "",
        url: "",
        listing_selectors: [],
        include_patterns: [],
        exclude_patterns: [],
        article_selectors: [],
        date_selectors: [],
        image_selectors: [],
        required_entry_tags: [],
        required_entry_keywords: [],
      },
      els.sourceList.querySelectorAll(".source-card").length,
    ),
  );
  refreshSourceOrder();
  updateDirtyIndicator();
}

function snapshotConfig(config) {
  const normalized = structuredClone(config);
  normalized.runtime = normalized.runtime || {};
  normalized.summary = normalized.summary || {};
  normalized.quality = normalized.quality || {};
  normalized.llm = normalized.llm || {};
  normalized.sources = (normalized.sources || []).map((source) => {
    const cloned = { ...source };
    const inheritRuntimeLimit = cloned.inherit_runtime_limit !== false;
    cloned.inherit_runtime_limit = inheritRuntimeLimit;
    if (inheritRuntimeLimit) {
      cloned.max_items = Number(normalized.runtime.article_limit_per_source || cloned.max_items || 10);
    } else {
      cloned.max_items = Number(cloned.max_items || normalized.runtime.article_limit_per_source || 10);
    }
    return cloned;
  });
  return JSON.stringify(normalized);
}

function parseList(value) {
  return value
    .replaceAll(",", "\n")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function readNumber(id, fallbackValue) {
  const value = parseInt(document.getElementById(id).value || String(fallbackValue), 10);
  return Number.isFinite(value) ? value : fallbackValue;
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function formatConfigSummary(summary) {
  const dateText = summary.start_date || summary.end_date
    ? `日期范围：${summary.start_date || "未设开始"} 至 ${summary.end_date || "未设结束"}`
    : `回退时长：${summary.recent_hours ?? "-"} 小时`;
  return [
    dateText,
    `全局抓取上限：${summary.global_limit ?? "-"} 篇/站`,
    `每模块最多入选：${summary.max_items_per_section ?? "-"} 篇`,
    `候选分析上限：${summary.max_articles_for_analysis ?? "-"} 篇`,
    `模块保底分析数：${summary.min_items_for_section_analysis ?? "-"} 篇`,
    `质量阈值：${summary.quality_min_score ?? "-"} 分`,
    `摘要字数：${summary.summary_min_chars ?? "-"}-${summary.summary_max_chars ?? "-"} 字`,
  ].join(" | ");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}

function selectOptions(currentValue, options) {
  return options
    .map((option) => `<option value="${option}" ${String(currentValue) === String(option) ? "selected" : ""}>${option || "无"}</option>`)
    .join("");
}

window.addEventListener("beforeunload", (event) => {
  const currentSnapshot = snapshotConfig(readConfigFromForm());
  if (currentSnapshot !== state.lastSavedSnapshot) {
    event.preventDefault();
    event.returnValue = "";
  }
});

document.addEventListener("input", () => updateDirtyIndicator());
document.addEventListener("change", () => updateDirtyIndicator());
document.getElementById("article_limit_per_source").addEventListener("input", syncAllInheritedSourceLimits);
document.getElementById("article_limit_per_source").addEventListener("change", syncAllInheritedSourceLimits);

els.addSourceButton.addEventListener("click", addBlankSource);
els.saveButton.addEventListener("click", async () => {
  try {
    await saveConfig(true);
  } catch (error) {
    setActionStatus(error.message || "配置保存失败");
  }
});

els.restoreButton.addEventListener("click", async () => {
  try {
    await restoreDefaults();
  } catch (error) {
    setActionStatus(error.message || "恢复默认失败");
  }
});

els.generateButton.addEventListener("click", async () => {
  try {
    await generateReport();
  } catch (error) {
    setActionStatus(error.message || "日报生成失败");
  }
});

renderConfig(initialConfig);
updateProgress({ progress: 0, stage: "queued", message: "保存配置后，点击“生成日报”即可开始任务。" });

const state = {
  health: null,
  profile: null,
  watchlist: [],
  reports: [],
  conversations: [],
  jobs: [],
  frameworks: [],
  backgroundTasks: [],
  updates: null,
  memory: null,
  currentReport: null,
  currentConversation: null,
  currentCompany: null,
  companyWorkspace: null,
  companyConversation: null,
  companyTrackingDirty: false,
  editingHypothesisId: null,
  historyFilter: "",
  conversationSource: "",
  conversationQuery: "",
  conversationOffset: 0,
  conversationHasMore: false,
  backgroundInitialized: false,
  backgroundStatuses: {},
};

const pageMeta = {
  overview: ["PRIVATE RESEARCH DESK", "早上好，老板"],
  markets: ["MARKET INTELLIGENCE", "我的市场"],
  companies: ["COMPANY NOTEBOOK", "我的公司"],
  "company-detail": ["COMPANY WORKSPACE", "公司研究档案"],
  ask: ["RESEARCH CONVERSATION", "连续对话"],
  tasks: ["AUTOMATED BRIEFING", "定时汇报"],
  frameworks: ["PUBLIC METHOD LIBRARY", "公开投资框架"],
  history: ["LOCAL RESEARCH ARCHIVE", "研究档案"],
  settings: ["OWNER PREFERENCE", "老板投资说明书"],
};

const reportTypes = {
  daily: "每日简报",
  company: "公司研究",
  qa: "问题研究",
  hourly: "消息扫描",
  weekly: "每周复盘",
  scheduled: "自动汇报",
};
const sourceNames = { web: "网页对话", codex: "Codex 对话", scheduler: "定时任务" };
const jobStatusNames = {
  completed: "已完成",
  failed: "失败",
  running: "执行中",
  interrupted: "上次中断，等待补跑",
};
const engineNames = { auto: "Codex 订阅优先", codex: "Codex 订阅", api: "OpenAI API", demo: "演示" };
const weekdayNames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const newsIntervalOptions = [
  [60, "每 1 小时"],
  [120, "每 2 小时"],
  [240, "每 4 小时"],
  [720, "每 12 小时"],
];
const jobTypeNames = {
  hourly_news: "消息面扫描",
  daily_brief: "市场简报",
  weekly_review: "基本面复盘",
  company_tracking: "公司持续跟踪",
};
const hypothesisStatusNames = {
  tracking: "持续核验",
  supported: "暂获支持",
  challenged: "受到挑战",
  invalidated: "已经失效",
  closed: "停止跟踪",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = data?.detail || data?.message || `请求失败（${response.status}）`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value, withTime = true) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

function splitList(value) {
  return String(value || "")
    .split(/[，,、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function plainSnippet(markdown, length = 82) {
  const plain = String(markdown || "")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/[#>*_`\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return plain.length > length ? `${plain.slice(0, length)}…` : plain;
}

function inlineMarkdown(text) {
  let value = escapeHtml(text);
  value = value.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) =>
    `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
  );
  value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  value = value.replace(/`([^`]+)`/g, "<code>$1</code>");
  return value;
}

function renderMarkdown(markdown = "") {
  const lines = String(markdown).replace(/\r/g, "").split("\n");
  const output = [];
  let listType = null;
  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) { closeList(); continue; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      output.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`);
      continue;
    }
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      if (listType !== "ul") { closeList(); listType = "ul"; output.push("<ul>"); }
      output.push(`<li>${inlineMarkdown(unordered[1])}</li>`);
      continue;
    }
    const ordered = line.match(/^\d+[.、]\s*(.+)$/);
    if (ordered) {
      if (listType !== "ol") { closeList(); listType = "ol"; output.push("<ol>"); }
      output.push(`<li>${inlineMarkdown(ordered[1])}</li>`);
      continue;
    }
    if (line.startsWith(">")) {
      closeList();
      output.push(`<blockquote>${inlineMarkdown(line.slice(1).trim())}</blockquote>`);
      continue;
    }
    closeList();
    output.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  return output.join("\n");
}

let toastTimer;
function toast(message, kind = "success") {
  const el = $("#toast");
  el.textContent = message;
  el.classList.remove("hidden", "error");
  if (kind === "error") el.classList.add("error");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4200);
}

function navigate(page) {
  if (!pageMeta[page]) return;
  $$(".page").forEach((el) => el.classList.toggle("active", el.id === `page-${page}`));
  $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $("#pageEyebrow").textContent = pageMeta[page][0];
  const owner = state.profile?.owner_name || "老板";
  $("#pageTitle").textContent = page === "overview" ? greeting(owner) : pageMeta[page][1];
  document.body.classList.remove("menu-open");
  if (window.location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function greeting(name) {
  const hour = new Date().getHours();
  const part = hour < 11 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好";
  return `${part}，${name || "老板"}`;
}

function renderHealth() {
  const { configured, demo_mode: demo, model, version, engines = {} } = state.health;
  const codex = engines.codex || {};
  const apiEngine = engines.api || {};
  const dot = $("#statusDot");
  const text = $("#statusText");
  const detail = $("#statusDetail");
  dot.classList.remove("ready", "warn");
  if (demo) {
    dot.classList.add("warn");
    text.textContent = "演示模式";
    detail.textContent = `v${version} · 不检索实时数据`;
    $("#setupBanner").classList.remove("hidden");
  } else if (configured) {
    dot.classList.add("ready");
    text.textContent = "Codex 订阅已就绪";
    const ready = [];
    if (codex.logged_in && codex.auth_type === "chatgpt") ready.push(`Codex ${codex.plan_type || "订阅"}`);
    if (apiEngine.available) ready.push("API 备用");
    detail.textContent = `${ready.join(" + ") || model} · v${version}`;
    $("#setupBanner").classList.add("hidden");
  } else {
    dot.classList.add("warn");
    text.textContent = "等待首次配置";
    detail.textContent = "可以先设置偏好和自选股";
    $("#setupBanner").classList.remove("hidden");
  }
  const statusGrid = $("#engineStatus");
  if (statusGrid) {
    statusGrid.innerHTML = `
      <div class="engine-status ${codex.logged_in && codex.auth_type === "chatgpt" ? "ready" : ""}">
        <span>Codex 订阅</span>
        <strong>${codex.logged_in && codex.auth_type === "chatgpt" ? `可用 · ${escapeHtml(codex.plan_type || "ChatGPT")}` : "不可用"}</strong>
        <small>${escapeHtml(codex.detail || "尚未检查")}</small>
      </div>
      <div class="engine-status ${apiEngine.available ? "ready" : ""}">
        <span>OpenAI API</span>
        <strong>${apiEngine.available ? "可用" : "未配置"}</strong>
        <small>${escapeHtml(apiEngine.available ? (apiEngine.model || model) : (apiEngine.detail || "可作为备用引擎"))}</small>
      </div>`;
  }
  renderBackupStatus();
}

function renderBackupStatus() {
  const container = $("#backupStatus");
  if (!container) return;
  const backups = state.health?.backups || {};
  const latest = backups.latest;
  container.innerHTML = `
    <div><span>最近备份</span><strong>${latest ? formatDate(latest.created_at) : "等待首次备份"}</strong></div>
    <div><span>现有快照</span><strong>${backups.count || 0} 份</strong></div>
    <div><span>状态</span><strong class="${backups.last_error ? "backup-error" : ""}">${
      backups.last_error ? escapeHtml(backups.last_error) : "完整性检查正常"
    }</strong></div>`;
}

function renderUpdateStatus() {
  const container = $("#updateStatus");
  if (!container || !state.updates) return;
  const update = state.updates;
  const stateNames = {
    idle: "等待检查",
    checking: "正在检查",
    current: "已经最新",
    available: "发现新版",
    downloading: "正在下载",
    installing: "正在安装",
    queued: "等待安装",
    updated: "升级完成",
    rolled_back: "已自动回滚",
    error: "检查异常",
  };
  container.innerHTML = `
    <div><span>当前版本</span><strong>v${escapeHtml(update.current_version || state.health?.version || "")}</strong></div>
    <div><span>最新版本</span><strong>${update.latest_version ? `v${escapeHtml(update.latest_version)}` : "尚未检查"}</strong></div>
    <div><span>更新状态</span><strong class="${update.state === "error" || update.state === "rolled_back" ? "backup-error" : ""}">${escapeHtml(stateNames[update.state] || update.state || "等待检查")}</strong></div>
    <p>${escapeHtml(update.message || "等待首次检查。")}</p>`;
  const installButton = $("#installUpdate");
  if (installButton) {
    installButton.disabled = !update.supported || !update.update_available;
    installButton.textContent = update.state === "installing" || update.state === "queued" ? "更新程序已启动" : "安装新版本";
  }
  const autoText = $("#autoUpdateText");
  if (autoText) {
    autoText.textContent = update.automatic
      ? `已开启：每 ${update.interval_hours || 6} 小时检查一次 GitHub 正式版本`
      : "自动更新已关闭";
  }
}

function renderOverview() {
  const markets = state.profile?.primary_markets || [];
  $("#primaryMarketCount").textContent = markets.length;
  $("#primaryMarketsText").textContent = markets.join(" · ") || "尚未设置";
  $("#watchlistCount").textContent = state.watchlist.length;
  $("#conversationCount").textContent = state.memory?.conversations ?? state.conversations.length;
  $("#activeJobCount").textContent = state.jobs.filter((job) => job.enabled).length;
  renderReportCards($("#recentReports"), state.reports.slice(0, 3));
}

function renderFrameworks() {
  const grid = $("#frameworkGrid");
  if (!grid) return;
  grid.innerHTML = state.frameworks.map((framework) => `
    <article class="framework-card">
      <div class="framework-card-head">
        <div><span class="eyebrow">${escapeHtml(framework.id)}</span><h3>${escapeHtml(framework.name)}</h3></div>
        <span class="framework-badge">公开方法</span>
      </div>
      <p class="framework-summary">${escapeHtml(framework.summary)}</p>
      <h4>理论核心</h4>
      <ul>${(framework.principles || []).map((principle) => `<li>${escapeHtml(principle)}</li>`).join("")}</ul>
      <h4>系统会多问这几句</h4>
      <ol>${framework.questions.map((question) => `<li>${escapeHtml(question)}</li>`).join("")}</ol>
      <h4>相关书目与知识边界</h4>
      <div class="framework-reading">${(framework.reading || []).map((item) => `
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.author)} · ${escapeHtml(item.note)}</span>
          <small>${escapeHtml(item.copyright)}</small>
        </div>`).join("")}</div>
      <h4>公开材料</h4>
      <div class="framework-sources">${framework.sources.length ? framework.sources.map((source) => `
        <a href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">
          <strong>${escapeHtml(source.title)}</strong>
          <span>${escapeHtml(source.publisher)} · ${escapeHtml(source.note)}</span>
        </a>`).join("") : `<div class="framework-source-pending">一手出处仍在核验，暂不展示未经证实的链接。</div>`}</div>
      <div class="framework-disclaimer">根据公开材料提炼，不代表本人对当前事件的真实看法，不构成投资建议。</div>
    </article>`).join("");
}

function renderMemory() {
  const memory = state.memory;
  const container = $("#memoryStatus");
  if (!memory || !container) return;
  const files = memory.memory_files || {};
  const corrections = files["06_老板纠正与反馈.md"] || {};
  const decisions = files["04_决策日志.md"] || {};
  const sync = memory.codex_archive || {};
  container.innerHTML = `
    <div><span>完整对话</span><strong>${memory.conversations || 0} 组 · ${memory.messages || 0} 条</strong></div>
    <div><span>正式报告</span><strong>${memory.reports || 0} 份</strong></div>
    <div><span>老板决策</span><strong>${decisions.items || 0} 条</strong></div>
    <div><span>老板纠正</span><strong>${corrections.items || 0} 条</strong></div>
    <div class="memory-sync-row"><span>Codex 档案</span><strong>${
      sync.last_sync_at
        ? `${formatDate(sync.last_sync_at)} · ${sync.last_error ? "同步异常" : "已同步"}`
        : "等待首次同步"
    }</strong></div>`;
}

function renderReportCards(container, reports) {
  if (!reports.length) {
    container.innerHTML = `<div class="empty-state"><strong>这里还没有研究报告</strong>先设置老板偏好和自选公司，再生成第一份今日简报。</div>`;
    return;
  }
  container.innerHTML = reports.map((report) => `
    <article class="report-card" data-report-id="${report.id}">
      <div class="report-card-top"><span class="report-type">${reportTypes[report.report_type] || "研究"}</span><span>${engineNames[report.engine] || report.engine || "研究"} · ${formatDate(report.created_at)}</span></div>
      <h3>${escapeHtml(report.title)}</h3>
      <p>${escapeHtml(plainSnippet(report.content))}</p>
    </article>`).join("");
  $$("[data-report-id]", container).forEach((card) =>
    card.addEventListener("click", () => openReport(Number(card.dataset.reportId)))
  );
}

function renderMarketContext() {
  if (!state.profile) return;
  const values = [
    `核心：${state.profile.primary_markets.join("、") || "未设置"}`,
    `外围：${state.profile.reference_markets.join("、") || "未设置"}`,
    `板块：${state.profile.focus_sectors.join("、") || "未设置"}`,
    `自选：${state.watchlist.length} 家`,
  ];
  $("#marketContext").innerHTML = values.map((value) =>
    `<span class="context-pill">${escapeHtml(value)}</span>`
  ).join("");
}

function renderWatchlist() {
  const grid = $("#watchlistGrid");
  if (!state.watchlist.length) {
    grid.innerHTML = `<div class="empty-state"><strong>还没有自选公司</strong>先添加 3—10 家真正想长期研究的公司，不需要把所有股票都放进来。</div>`;
    return;
  }
  grid.innerHTML = state.watchlist.map((item) => `
    <article class="company-card" data-open-company="${item.id}">
      <div class="company-card-top">
        <div class="company-symbol">${escapeHtml(item.symbol.slice(0, 4))}</div>
        <div style="flex:1"><h3>${escapeHtml(item.name)}</h3><div class="company-meta">${escapeHtml(item.market)} · ${escapeHtml(item.symbol)}</div></div>
        <button class="delete-button" data-delete-company="${item.id}" title="移除">×</button>
      </div>
      <p class="company-thesis">${escapeHtml(item.thesis || "还没有写研究理由。")}</p>
      <div class="company-card-stats">
        <span>${item.report_count || 0} 份研究</span>
        <span>${item.conversation_count || 0} 条对话</span>
        <span class="${item.tracking_enabled ? "tracking-on" : ""}">${item.tracking_enabled ? `${trackingFrequencyName(item.tracking_frequency)}跟踪中` : "手动研究"}</span>
      </div>
      <div class="company-card-actions">
        <strong>${item.last_report_at ? `最近研究 ${formatDate(item.last_report_at, false)}` : "尚未形成公司报告"}</strong>
        <button data-open-company="${item.id}">打开公司档案 →</button>
      </div>
    </article>`).join("");
  $$("[data-delete-company]").forEach((button) => button.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (!confirm("确认从自选列表移除？历史研究报告不会删除。")) return;
    try {
      await api(`/api/watchlist/${button.dataset.deleteCompany}`, { method: "DELETE" });
      await refreshWatchlist();
      toast("已从自选列表移除");
    } catch (error) { toast(error.message, "error"); }
  }));
  $$("[data-open-company]").forEach((element) => element.addEventListener("click", (event) => {
    event.stopPropagation();
    if (event.target.closest("[data-delete-company]")) return;
    openCompanyWorkspace(Number(element.dataset.openCompany));
  }));
}

function trackingFrequencyName(value) {
  return { daily: "每日", weekly: "每周", monthly: "每月", yearly: "每年" }[value] || "定期";
}

async function openCompanyWorkspace(itemId) {
  try {
    state.companyWorkspace = await api(`/api/watchlist/${itemId}/workspace`);
    state.currentCompany = state.companyWorkspace.company;
    state.companyConversation = null;
    state.companyTrackingDirty = false;
    if (state.companyWorkspace.conversations.length) {
      state.companyConversation = await api(`/api/conversations/${state.companyWorkspace.conversations[0].id}`);
    }
    navigate("company-detail");
    renderCompanyWorkspace();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function refreshCompanyWorkspace() {
  if (!state.currentCompany) return;
  const activeConversationId = state.companyConversation?.id;
  state.companyWorkspace = await api(`/api/watchlist/${state.currentCompany.id}/workspace`);
  state.currentCompany = state.companyWorkspace.company;
  if (activeConversationId) {
    try { state.companyConversation = await api(`/api/conversations/${activeConversationId}`); }
    catch { state.companyConversation = null; }
  }
  if (!state.companyConversation && state.companyWorkspace.conversations.length) {
    state.companyConversation = await api(`/api/conversations/${state.companyWorkspace.conversations[0].id}`);
  }
  renderCompanyWorkspace();
}

function renderCompanyWorkspace() {
  const workspace = state.companyWorkspace;
  const company = state.currentCompany;
  if (!workspace || !company) return;
  $("#detailCompanyName").textContent = company.name;
  $("#detailCompanyMeta").textContent = `${company.market} · ${company.symbol} · ${company.thesis || "尚未填写研究理由"}`;
  $("#companyDetailMetrics").innerHTML = [
    ["研究报告", `${workspace.reports.length} 份`],
    ["公司对话", `${workspace.conversations.length} 组`],
    ["研究假设", `${(workspace.hypotheses || []).length} 条`],
    ["最近研究", company.last_report_at ? formatDate(company.last_report_at, false) : "尚未研究"],
    ["自动跟踪", company.tracking_enabled ? `${trackingFrequencyName(company.tracking_frequency)}开启` : "未开启"],
  ].map(([label, value]) => `<div><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`).join("");

  const collectionPlan = workspace.collection_plan || {};
  const providers = collectionPlan.providers || [];
  $("#companyDataSources").innerHTML = providers.length
    ? providers.map((provider) => `
      <a href="${escapeHtml(provider.url)}" target="_blank" rel="noopener noreferrer">
        <div><strong>${escapeHtml(provider.name)}</strong><span>${escapeHtml(provider.quality)}</span></div>
        <p>${escapeHtml(provider.capabilities.join(" · "))}</p>
        <small>${escapeHtml(provider.access_mode)} · ${provider.auth_required ? "结构化接口需单独授权" : "无需账户"}</small>
      </a>`).join("")
    : `<div class="empty-state"><strong>暂未登记专用入口</strong>研究时仍会优先监管、交易所和公司官网，并把缺失写出来。</div>`;

  const job = workspace.tracking_job || {};
  if (!state.companyTrackingDirty) {
    const allowedFrequencies = ["daily", "weekly", "monthly", "yearly"];
    const savedFrequency = job.frequency || company.tracking_frequency;
    $("#companyTrackingEnabled").checked = Boolean(job.enabled ?? company.tracking_enabled);
    $("#companyTrackingFrequency").value = allowedFrequencies.includes(savedFrequency) ? savedFrequency : "weekly";
    $("#companyTrackingTime").value = job.time_of_day || company.tracking_time || "09:00";
    $("#companyTrackingWeekday").value = String(job.weekday ?? 0);
    $("#companyTrackingDay").value = String(job.day_of_month ?? 1);
    $("#companyTrackingMonth").value = String(job.month_of_year ?? 1);
    $("#companyTrackingEngine").value = job.engine || "auto";
  }

  $("#companyReportCount").textContent = `${workspace.reports.length} 份`;
  $("#companyReportList").innerHTML = workspace.reports.length
    ? workspace.reports.map((report) => `
        <article class="company-report-item" data-company-report="${report.id}">
          <div><h4>${escapeHtml(report.title)}</h4><p>${formatDate(report.created_at)} · ${engineNames[report.engine] || report.engine}</p></div>
          <button type="button">打开 →</button>
        </article>`).join("")
    : `<div class="empty-state"><strong>还没有公司报告</strong>点击上方“主研究员更新”或“双员工复核”，完成后会自动出现在这里。</div>`;
  $$("[data-company-report]", $("#companyReportList")).forEach((row) =>
    row.addEventListener("click", () => openReport(Number(row.dataset.companyReport)))
  );

  $("#companyConversationList").innerHTML = workspace.conversations.length
    ? workspace.conversations.map((conversation) => `
        <button class="company-conversation-row ${state.companyConversation?.id === conversation.id ? "active" : ""}" data-company-conversation="${conversation.id}">
          <strong>${escapeHtml(conversation.title)}</strong>
          <span>${formatDate(conversation.updated_at)} · ${conversation.message_count} 条</span>
        </button>`).join("")
    : `<div class="conversation-empty">还没有公司对话，点击“新开公司对话”。</div>`;
  $$("[data-company-conversation]", $("#companyConversationList")).forEach((button) =>
    button.addEventListener("click", () => openCompanyConversation(button.dataset.companyConversation))
  );
  renderHypotheses();
  renderCompanyConversation();
}

function evidenceList(items, emptyText) {
  return items?.length
    ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p>${emptyText}</p>`;
}

function renderHypotheses() {
  const hypotheses = state.companyWorkspace?.hypotheses || [];
  const container = $("#hypothesisList");
  if (!container) return;
  container.innerHTML = hypotheses.length
    ? hypotheses.map((item) => `
      <article class="hypothesis-item status-${item.status}">
        <header>
          <div>
            <span class="hypothesis-status">${hypothesisStatusNames[item.status] || item.status}</span>
            <h4>${escapeHtml(item.title)}</h4>
          </div>
          <div class="hypothesis-actions">
            <button type="button" data-edit-hypothesis="${item.id}">编辑</button>
            <button type="button" data-delete-hypothesis="${item.id}">删除</button>
          </div>
        </header>
        ${item.statement ? `<blockquote>${escapeHtml(item.statement)}</blockquote>` : ""}
        <div class="hypothesis-columns">
          <section><strong>支持证据</strong>${evidenceList(item.support_evidence, "尚未记录")}</section>
          <section><strong>反方证据</strong>${evidenceList(item.counter_evidence, "尚未记录")}</section>
          <section><strong>验证信号</strong>${evidenceList(item.validation_signals, "尚未记录")}</section>
          <section><strong>失效信号</strong>${evidenceList(item.invalidation_signals, "尚未记录")}</section>
        </div>
        <footer>下次复核：${escapeHtml(item.next_review_at || "未设置")} · 更新于 ${formatDate(item.updated_at)}</footer>
      </article>`).join("")
    : `<div class="empty-state"><strong>还没有研究假设</strong>先把最核心的一条判断写成可验证陈述，再分别补支持和反方证据。</div>`;
  $$("[data-edit-hypothesis]", container).forEach((button) =>
    button.addEventListener("click", () => {
      const item = hypotheses.find((entry) => entry.id === Number(button.dataset.editHypothesis));
      if (item) showHypothesisForm(item);
    })
  );
  $$("[data-delete-hypothesis]", container).forEach((button) =>
    button.addEventListener("click", async () => {
      if (!confirm("确认删除这条研究假设？")) return;
      try {
        await api(`/api/hypotheses/${button.dataset.deleteHypothesis}`, { method: "DELETE" });
        await refreshCompanyWorkspace();
        toast("研究假设已删除");
      } catch (error) { toast(error.message, "error"); }
    })
  );
}

function showHypothesisForm(item = null) {
  state.editingHypothesisId = item?.id || null;
  $("#hypothesisTitle").value = item?.title || "";
  $("#hypothesisStatus").value = item?.status || "tracking";
  $("#hypothesisStatement").value = item?.statement || "";
  $("#hypothesisSupport").value = (item?.support_evidence || []).join("\n");
  $("#hypothesisCounter").value = (item?.counter_evidence || []).join("\n");
  $("#hypothesisValidation").value = (item?.validation_signals || []).join("\n");
  $("#hypothesisInvalidation").value = (item?.invalidation_signals || []).join("\n");
  $("#hypothesisNextReview").value = item?.next_review_at || "";
  $("#hypothesisForm").classList.remove("hidden");
  $("#hypothesisTitle").focus();
}

function hideHypothesisForm() {
  state.editingHypothesisId = null;
  $("#hypothesisForm").reset();
  $("#hypothesisStatus").value = "tracking";
  $("#hypothesisForm").classList.add("hidden");
}

function splitEvidence(value) {
  return String(value || "").split(/\n+/).map((item) => item.trim()).filter(Boolean);
}

async function openCompanyConversation(conversationId) {
  try {
    state.companyConversation = await api(`/api/conversations/${conversationId}`);
    renderCompanyWorkspace();
  } catch (error) { toast(error.message, "error"); }
}

function renderCompanyConversation() {
  const conversation = state.companyConversation;
  $("#companyChatTitle").textContent = conversation?.title || "选择或新建一条公司对话";
  $("#companyChatMessages").innerHTML = conversation
    ? conversationThreadHtml(conversation)
    : `<div class="chat-welcome"><h3>给这家公司建一条长期对话。</h3><p>每次追问都会接着旧消息继续，不会再自动另开窗口。</p></div>`;
  const area = $("#companyChatMessages");
  requestAnimationFrame(() => { area.scrollTop = area.scrollHeight; });
}

async function createCompanyConversation(openInMain = false) {
  if (!state.currentCompany) return null;
  try {
    const conversation = await api("/api/conversations", {
      method: "POST",
      body: JSON.stringify({
        title: `${state.currentCompany.name} 持续研究`,
        watchlist_id: state.currentCompany.id,
      }),
    });
    state.companyConversation = await api(`/api/conversations/${conversation.id}`);
    await refreshCompanyWorkspace();
    if (openInMain) {
      state.currentConversation = state.companyConversation;
      navigate("ask");
      renderConversation();
    }
    $("#companyChatInput").focus();
    return conversation;
  } catch (error) {
    toast(error.message, "error");
    return null;
  }
}

function renderHistory() {
  const reports = state.historyFilter
    ? state.reports.filter((report) => report.report_type === state.historyFilter)
    : state.reports;
  const container = $("#historyList");
  if (!reports.length) {
    container.innerHTML = `<div class="empty-state"><strong>这个分类还没有报告</strong>生成报告后会自动保存在这里。</div>`;
    return;
  }
  container.innerHTML = reports.map((report) => `
    <article class="history-row" data-report-id="${report.id}">
      <span class="report-type">${reportTypes[report.report_type] || "研究"}</span>
      <div><h3>${escapeHtml(report.title)}</h3><p>${escapeHtml(plainSnippet(report.content, 105))}</p></div>
      <span class="history-date">${formatDate(report.created_at)}</span>
      <div class="history-actions">
        <button type="button" data-quick-download="${report.id}" title="下载 Markdown">下载</button>
        <button type="button" class="delete-report-button" data-delete-report="${report.id}" title="删除">删除</button>
        <span class="history-arrow">→</span>
      </div>
    </article>`).join("");
  $$("[data-report-id]", container).forEach((row) =>
    row.addEventListener("click", () => openReport(Number(row.dataset.reportId)))
  );
  $$("[data-quick-download]", container).forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    downloadReportFile(Number(button.dataset.quickDownload), "md");
  }));
  $$("[data-delete-report]", container).forEach((button) => button.addEventListener("click", async (event) => {
    event.stopPropagation();
    await deleteReportRecord(Number(button.dataset.deleteReport));
  }));
}

function renderConversationList() {
  const container = $("#conversationList");
  if (!state.conversations.length) {
    container.innerHTML = `<div class="conversation-empty">还没有符合条件的对话。</div>`;
  } else {
    container.innerHTML = state.conversations.map((item) => `
      <button class="conversation-row ${state.currentConversation?.id === item.id ? "active" : ""}" data-conversation-id="${item.id}">
        <span class="conversation-row-top"><strong>${escapeHtml(item.title)}</strong><i>${sourceNames[item.source] || item.source}</i></span>
        <span class="conversation-preview">${escapeHtml(plainSnippet(item.preview, 54) || "尚无消息")}</span>
        <span class="conversation-meta">${formatDate(item.updated_at)} · ${item.message_count} 条</span>
      </button>`).join("");
    $$("[data-conversation-id]", container).forEach((button) =>
      button.addEventListener("click", () => openConversation(button.dataset.conversationId))
    );
  }
  $("#loadMoreConversations").classList.toggle("hidden", !state.conversationHasMore);
}

function renderConversation() {
  const conversation = state.currentConversation;
  if (!conversation) {
    $("#chatTitle").textContent = "新对话";
    $("#chatSource").textContent = "网页对话";
    $("#chatMessages").innerHTML = welcomeHtml();
    return;
  }
  $("#chatTitle").textContent = conversation.title;
  $("#chatSource").textContent = sourceNames[conversation.source] || conversation.source;
  $("#chatMessages").innerHTML = conversationThreadHtml(conversation, true);
  const area = $("#chatMessages");
  requestAnimationFrame(() => { area.scrollTop = area.scrollHeight; });
  renderConversationList();
}

function conversationThreadHtml(conversation, showWelcome = false) {
  const messages = conversation?.messages || [];
  if (!messages.length) return showWelcome ? welcomeHtml() : `<div class="conversation-empty">这条对话还没有消息。</div>`;
  const html = messages.map((message) => `
    <article class="chat-message ${message.role}">
      <div class="message-avatar">${message.role === "user" ? "老板" : "研"}</div>
      <div class="message-body">
        <div class="message-meta"><strong>${message.role === "user" ? "老板" : "AI 投研员工"}</strong><span>${message.metadata?.engine ? `${engineNames[message.metadata.engine] || message.metadata.engine} · ` : ""}${formatDate(message.created_at)}</span></div>
        <div class="message-content">${message.role === "assistant" ? renderMarkdown(message.content) : `<p>${escapeHtml(message.content).replaceAll("\n", "<br>")}</p>`}</div>
        ${renderMessageSources(message.sources || [])}
      </div>
    </article>`).join("");
  const pendingCount = conversationPendingCount(conversation.id);
  return html + (pendingCount
    ? `<div class="chat-pending">这条对话还有 ${pendingCount} 条后台回复在排队或生成。你可以继续发送下一条，也可以在右下角后台任务里取消。</div>`
    : "");
}

function conversationPending(conversationId) {
  return state.backgroundTasks.some((task) =>
    ["queued", "running"].includes(task.status)
    && task.task_type === "conversation"
    && task.request?.conversation_id === conversationId
  );
}

function conversationPendingCount(conversationId) {
  return state.backgroundTasks.filter((task) =>
    ["queued", "running"].includes(task.status)
    && task.task_type === "conversation"
    && task.request?.conversation_id === conversationId
  ).length;
}

function welcomeHtml() {
  return `<div class="chat-welcome">
    <span class="eyebrow">ASK YOUR ANALYST</span>
    <h3>像发微信一样问。</h3>
    <p>研究员会读取老板说明书和自选公司，必要时联网查证，并保留来源。</p>
    <div class="chat-examples">
      <button>今天哪些消息真正影响我的自选公司？</button>
      <button>腾讯的现金流和资本配置最近有什么变化？</button>
      <button>把我的判断拆成支持、反对和待核验三部分。</button>
    </div>
  </div>`;
}

function renderMessageSources(sources) {
  if (!sources.length) return "";
  return `<details class="message-sources"><summary>${sources.length} 个来源</summary><div>${sources.map((source) =>
    `<a href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer"><b class="source-mini tier-${source.quality_tier || 3}">${escapeHtml(source.quality_label || "待核验")}</b>${escapeHtml(source.title || "原始来源")}</a>`
  ).join("")}</div></details>`;
}

function bindDynamicExamples() {
  $$(".chat-examples button", $("#chatMessages")).forEach((button) => button.addEventListener("click", () => {
    $("#chatInput").value = button.textContent.trim();
    $("#chatInput").focus();
  }));
}

async function refreshConversations(reset = true) {
  if (reset) {
    state.conversationOffset = 0;
    state.conversations = [];
  }
  const params = new URLSearchParams({
    limit: "50",
    offset: String(state.conversationOffset),
    query: state.conversationQuery,
    source: state.conversationSource,
  });
  const rows = await api(`/api/conversations?${params}`);
  state.conversations.push(...rows);
  state.conversationOffset += rows.length;
  state.conversationHasMore = rows.length === 50;
  renderConversationList();
  renderOverview();
}

async function createNewConversation() {
  const conversation = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ title: "新对话" }),
  });
  await refreshConversations(true);
  await openConversation(conversation.id);
  $("#chatInput").focus();
}

async function openConversation(id) {
  try {
    state.currentConversation = await api(`/api/conversations/${id}`);
    renderConversation();
    bindDynamicExamples();
  } catch (error) { toast(error.message, "error"); }
}

function renderJobs() {
  const grid = $("#taskGrid");
  $("#taskCountText").textContent = `${state.jobs.length} 个`;
  grid.innerHTML = state.jobs.map((job) => `
    <form class="task-card" data-job-id="${job.id}">
      <div class="task-card-head">
        <div><span class="task-type">${escapeHtml(jobTypeNames[job.job_type] || job.job_type)}</span>
        <input class="task-name" name="name" value="${escapeHtml(job.name)}"></div>
        <label class="task-switch"><input type="checkbox" name="enabled" ${job.enabled ? "checked" : ""}><i></i></label>
      </div>
      <div class="task-status ${job.last_status === "failed" ? "failed" : ""}">
        ${job.last_run_at
          ? `上次：${formatDate(job.last_run_at)} · ${jobStatusNames[job.last_status] || job.last_status || "未知"}`
          : job.last_status
            ? `最近状态：${jobStatusNames[job.last_status] || job.last_status}`
            : "尚未运行"}
        ${job.last_trigger_type
          ? `<small>${job.last_trigger_type === "scheduled" ? "正式定时" : "手动试跑"}${
              job.last_attempt_count > 1 ? ` · 第 ${job.last_attempt_count} 次恢复尝试` : ""
            }</small>`
          : ""}
        ${job.last_error ? `<small>${escapeHtml(job.last_error)}</small>` : ""}
      </div>
      <div class="task-fields">
        <label>研究内容<select name="job_type">
          <option value="hourly_news" ${job.job_type === "hourly_news" ? "selected" : ""}>消息面扫描</option>
          <option value="daily_brief" ${job.job_type === "daily_brief" ? "selected" : ""}>市场简报</option>
          <option value="weekly_review" ${job.job_type === "weekly_review" ? "selected" : ""}>基本面复盘</option>
          <option value="company_tracking" ${job.job_type === "company_tracking" ? "selected" : ""}>公司持续跟踪</option>
        </select></label>
        ${job.job_type === "hourly_news" ? `
          <label>每隔多久<select name="interval_minutes">
            ${newsIntervalOptions.map(([value, label]) =>
              `<option value="${value}" ${Number(job.interval_minutes) === value ? "selected" : ""}>${label}</option>`
            ).join("")}
          </select></label>
          <input type="hidden" name="frequency" value="interval">
          <input type="hidden" name="time_of_day" value="08:00">
          <input type="hidden" name="weekday" value="-1">
        ` : `
          <label>频率<select name="frequency">
            <option value="daily" ${job.frequency !== "weekly" ? "selected" : ""}>每天</option>
            <option value="weekly" ${job.frequency === "weekly" ? "selected" : ""}>每周</option>
          </select></label>
          <label>执行时间<input type="time" name="time_of_day" value="${job.time_of_day}"></label>
          <label>执行日<select name="weekday">
            <option value="-1" ${job.weekday === -1 ? "selected" : ""}>每天</option>
            ${weekdayNames.map((name, index) =>
            `<option value="${index}" ${job.weekday === index ? "selected" : ""}>${name}</option>`
          ).join("")}</select></label>
        `}
        <label>研究引擎<select name="engine">
          <option value="auto" ${job.engine === "auto" ? "selected" : ""}>Codex 订阅优先（默认）</option>
          <option value="codex" ${job.engine === "codex" ? "selected" : ""}>Codex 订阅</option>
          <option value="api" ${job.engine === "api" ? "selected" : ""}>OpenAI API</option>
        </select></label>
      </div>
      <fieldset class="framework-picker compact">
        <legend>公开方法视角</legend>
        ${state.frameworks.map((framework) => `<label>
          <input type="checkbox" name="frameworks" value="${escapeHtml(framework.name)}"
            ${(job.frameworks || []).includes(framework.name) ? "checked" : ""}>
          ${escapeHtml(framework.short_name)}
        </label>`).join("")}
      </fieldset>
      <input type="hidden" name="watchlist_id" value="${job.watchlist_id || ""}">
      <label class="task-prompt">任务说明<textarea name="prompt" rows="4">${escapeHtml(job.prompt)}</textarea></label>
      <div class="task-next">下次计划：${formatDate(job.next_run_at)}</div>
      <div class="task-actions">
        <button type="button" class="btn btn-ghost small" data-run-job="${job.id}">现在试跑</button>
        <button type="button" class="btn btn-danger small" data-delete-job="${job.id}">删除</button>
        <button type="submit" class="btn btn-primary small">保存任务</button>
      </div>
    </form>`).join("");

  $$(".task-card").forEach((form) => form.addEventListener("submit", saveJobForm));
  $$(".task-switch input").forEach((input) => input.addEventListener("change", (event) => {
    event.currentTarget.closest("form").requestSubmit();
  }));
  $$("[data-run-job]").forEach((button) => button.addEventListener("click", () => runJob(Number(button.dataset.runJob))));
  $$("[data-delete-job]").forEach((button) => button.addEventListener("click", () => deleteJob(Number(button.dataset.deleteJob))));
}

function jobPayload(form) {
  const data = new FormData(form);
  const jobType = data.get("job_type");
  const frequency = jobType === "hourly_news" ? "interval" : (data.get("frequency") === "weekly" ? "weekly" : "daily");
  const selectedWeekday = Number(data.get("weekday"));
  const intervalMinutes = Number(data.get("interval_minutes") || 60);
  return {
    name: data.get("name"),
    job_type: jobType,
    frequency,
    interval_minutes: jobType === "hourly_news" ? intervalMinutes : 1440,
    time_of_day: data.get("time_of_day") || "08:00",
    weekday: jobType === "hourly_news" || frequency === "daily" ? -1 : (selectedWeekday >= 0 ? selectedWeekday : 0),
    day_of_month: 1,
    month_of_year: 1,
    active_start: "00:00",
    active_end: "23:59",
    enabled: data.get("enabled") === "on",
    engine: data.get("engine") || "auto",
    frameworks: data.getAll("frameworks"),
    watchlist_id: data.get("watchlist_id") ? Number(data.get("watchlist_id")) : null,
    prompt: data.get("prompt"),
  };
}

function updateNewJobScheduleControls() {
  const jobType = $("#newJobType")?.value;
  const isNewsScan = jobType === "hourly_news";
  $("#newIntervalField")?.classList.toggle("hidden", !isNewsScan);
  $("#newFrequencyField")?.classList.toggle("hidden", isNewsScan);
  $("#newTimeField")?.classList.toggle("hidden", isNewsScan);
  $("#newWeekdayField")?.classList.toggle("hidden", isNewsScan);
  if (isNewsScan) {
    $("#newJobFrequency").value = "daily";
  }
}

async function saveJobForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api(`/api/jobs/${form.dataset.jobId}`, { method: "PUT", body: JSON.stringify(jobPayload(form)) });
    await refreshJobs();
    toast("定时任务已保存");
  } catch (error) { toast(error.message, "error"); }
}

async function runJob(jobId) {
  try {
    const task = await api(`/api/jobs/${jobId}/enqueue`, { method: "POST" });
    await refreshBackgroundTasks(false);
    openBackgroundDrawer();
    toast(`“${task.title}”已放到后台，可以继续操作`);
  } catch (error) { toast(error.message, "error"); }
}

async function deleteJob(jobId) {
  if (!confirm("确认删除这个任务？已经生成的报告不会删除。")) return;
  try {
    await api(`/api/jobs/${jobId}`, { method: "DELETE" });
    await refreshJobs();
    toast("任务已删除");
  } catch (error) { toast(error.message, "error"); }
}

function fillSettings() {
  const p = state.profile;
  if (!p) return;
  $("#ownerName").value = p.owner_name || "";
  $("#primaryMarkets").value = p.primary_markets.join("、");
  $("#referenceMarkets").value = p.reference_markets.join("、");
  $("#focusSectors").value = p.focus_sectors.join("、");
  $("#excludedSectors").value = p.excluded_sectors.join("、");
  $("#investmentHorizon").value = p.investment_horizon || "";
  $("#riskPreference").value = p.risk_preference || "";
  $("#analysisFramework").value = p.analysis_framework || "";
  $("#referenceInvestors").value = (p.reference_investors || []).join("、");
  $("#preferredMetrics").value = p.preferred_metrics.join("、");
  $("#reportStyle").value = p.report_style || "";
  $("#dataPermissions").value = (p.data_permissions || []).join("、");
  $("#privacyBoundaries").value = (p.privacy_boundaries || []).join("、");
}

async function refreshWatchlist() {
  state.watchlist = await api("/api/watchlist");
  renderWatchlist();
  renderMarketContext();
  renderOverview();
}

async function refreshReports() {
  state.reports = await api("/api/reports?limit=500");
  renderHistory();
  renderOverview();
}

async function refreshJobs() {
  state.jobs = await api("/api/jobs");
  renderJobs();
  renderOverview();
}

async function refreshMemory() {
  state.memory = await api("/api/memory/overview");
  renderMemory();
  renderOverview();
}

function renderBackgroundTasks() {
  const active = state.backgroundTasks.filter((task) => ["queued", "running"].includes(task.status));
  $("#backgroundTaskText").textContent = `后台任务 ${active.length}`;
  $("#backgroundTaskButton").classList.toggle("running", active.length > 0);
  const list = $("#backgroundTaskList");
  if (!state.backgroundTasks.length) {
    list.innerHTML = `<div class="background-empty">还没有后台任务。生成简报或试跑任务后，会在这里显示进度。</div>`;
    return;
  }
  list.innerHTML = state.backgroundTasks.map((task) => `
    <article class="background-task-row ${task.status}">
      <span class="task-state-icon">${
        task.status === "completed" ? "✓" :
        task.status === "failed" ? "!" :
        task.status === "cancelled" ? "×" : "…"
      }</span>
      <div>
        <strong>${escapeHtml(task.title)}</strong>
        <small>${
          task.status === "queued" ? "排队中" :
          task.status === "running" ? "正在查资料、核验并归档" :
          task.status === "completed" ? `已完成 · ${formatDate(task.finished_at)}` :
          task.status === "cancelled" ? "已取消" :
          `失败 · ${escapeHtml(task.error || "未知错误")}`
        }</small>
      </div>
      ${["queued", "running"].includes(task.status) ? `<button data-cancel-task="${task.id}">取消</button>` : ""}
      ${["failed", "cancelled"].includes(task.status) ? `<button data-retry-task="${task.id}">重试</button>` : ""}
      ${task.report_id ? `<button data-open-task-report="${task.report_id}">查看报告</button>` : ""}
    </article>`).join("");
  $$("[data-open-task-report]", list).forEach((button) => button.addEventListener("click", () => {
    openReport(Number(button.dataset.openTaskReport));
    $("#backgroundDrawer").classList.add("hidden");
  }));
  $$("[data-cancel-task]", list).forEach((button) => button.addEventListener("click", () => cancelBackgroundTask(button.dataset.cancelTask)));
  $$("[data-retry-task]", list).forEach((button) => button.addEventListener("click", () => retryBackgroundTask(button.dataset.retryTask)));
}

async function cancelBackgroundTask(taskId) {
  try {
    await api(`/api/background-research/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
    await refreshBackgroundTasks(false);
    toast("后台任务已取消");
  } catch (error) { toast(error.message, "error"); }
}

async function retryBackgroundTask(taskId) {
  try {
    const task = await api(`/api/background-research/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
    await refreshBackgroundTasks(false);
    openBackgroundDrawer();
    toast(`已重新排队：${task.title}`);
  } catch (error) { toast(error.message, "error"); }
}

async function refreshBackgroundTasks(notify = true) {
  try {
    const tasks = await api("/api/background-research?limit=30");
    let shouldRefreshOutputs = false;
    tasks.forEach((task) => {
      if (
        task.status === "completed"
        && task.report_id
        && !state.reports.some((report) => report.id === task.report_id)
      ) {
        shouldRefreshOutputs = true;
      }
    });
    if (notify && state.backgroundInitialized) {
      tasks.forEach((task) => {
        const before = state.backgroundStatuses[task.id];
        if (before && before !== task.status && task.status === "completed") {
          toast(`后台研究完成：${task.title}`);
          shouldRefreshOutputs = true;
        }
        if (before && before !== task.status && task.status === "failed") {
          toast(`后台研究失败：${task.error || task.title}`, "error");
          shouldRefreshOutputs = true;
        }
      });
    }
    state.backgroundTasks = tasks;
    state.backgroundStatuses = Object.fromEntries(tasks.map((task) => [task.id, task.status]));
    state.backgroundInitialized = true;
    renderBackgroundTasks();
    renderConversation();
    renderCompanyConversation();
    if (shouldRefreshOutputs) {
      await Promise.all([refreshReports(), refreshJobs(), refreshConversations(true), refreshMemory()]);
      if (state.currentConversation) {
        state.currentConversation = await api(`/api/conversations/${state.currentConversation.id}`);
        renderConversation();
      }
      await refreshCompanyWorkspace();
      await refreshWatchlist();
    }
  } catch (error) {
    if (!state.backgroundInitialized) toast(`后台任务读取失败：${error.message}`, "error");
  }
}

function openBackgroundDrawer() {
  $("#backgroundDrawer").classList.remove("hidden");
}

async function runResearch(path, body, title) {
  const backgroundPath = path.replace("/api/research/", "/api/background-research/");
  try {
    const task = await api(backgroundPath, { method: "POST", body: JSON.stringify(body) });
    await refreshBackgroundTasks(false);
    toast(`${title.replace("正在", "")}已放到后台，你可以继续做别的事`);
    return task;
  } catch (error) {
    toast(error.message, "error");
    if (!state.health?.configured && !state.health?.demo_mode) navigate("settings");
    return null;
  }
}

async function sendConversationInBackground(conversationId, content, engine, useWeb) {
  if (!conversationId) throw new Error("请先新建或选择一条对话。");
  const task = await api(`/api/conversations/${encodeURIComponent(conversationId)}/messages/enqueue`, {
    method: "POST",
    body: JSON.stringify({ content, engine, use_web: useWeb }),
  });
  state.backgroundTasks.unshift(task);
  state.backgroundStatuses[task.id] = task.status;
  renderBackgroundTasks();
  if (state.currentConversation?.id === conversationId) {
    state.currentConversation = await api(`/api/conversations/${conversationId}`);
    renderConversation();
  }
  if (state.companyConversation?.id === conversationId) {
    state.companyConversation = await api(`/api/conversations/${conversationId}`);
    renderCompanyConversation();
  }
  await refreshConversations(true);
  toast("消息已排队，你可以继续发送下一条");
  return task;
}

let liveRefreshRunning = false;
async function refreshLiveData() {
  if (liveRefreshRunning) return;
  liveRefreshRunning = true;
  try {
    const activePage = $(".page.active")?.id || "";
    if (activePage === "page-ask") {
      await refreshConversations(true);
      if (state.currentConversation) {
        state.currentConversation = await api(`/api/conversations/${state.currentConversation.id}`);
        renderConversation();
      }
    }
    if (activePage === "page-company-detail" && state.currentCompany) {
      await refreshCompanyWorkspace();
    }
  } catch {
    // 近实时同步失败时保留当前页面，下一轮会自动重试。
  } finally {
    liveRefreshRunning = false;
  }
}

async function openReport(id) {
  const local = state.reports.find((report) => report.id === id);
  if (local) return openReportObject(local);
  try { openReportObject(await api(`/api/reports/${id}`)); }
  catch (error) { toast(error.message, "error"); }
}

function downloadReportFile(reportId, format) {
  window.location.href = `/api/reports/${reportId}/download?format=${encodeURIComponent(format)}`;
}

function downloadConversationFile(conversationId, format) {
  window.location.href = `/api/conversations/${encodeURIComponent(conversationId)}/download?format=${encodeURIComponent(format)}`;
}

async function deleteReportRecord(reportId) {
  if (!confirm("确认删除这份研究档案？本机对应的 Markdown 报告也会一起删除。")) return;
  try {
    await api(`/api/reports/${reportId}`, { method: "DELETE" });
    if (state.currentReport?.id === reportId) closeReport();
    await Promise.all([refreshReports(), refreshCompanyWorkspace()]);
    toast("研究档案已删除");
  } catch (error) { toast(error.message, "error"); }
}

function openReportObject(report) {
  state.currentReport = report;
  const audit = report.source_audit || {};
  $("#viewerKind").textContent = reportTypes[report.report_type] || "研究报告";
  $("#viewerTitle").textContent = report.title;
  $("#viewerMeta").textContent = `${formatDate(report.created_at)} · ${engineNames[report.engine] || report.engine || "研究引擎"} · ${report.review_mode === "team" ? "双员工复核" : "主研究员"} · ${report.model || "未记录模型"} · ${audit.primary_count || 0}/${audit.total || 0} 个一手来源`;
  $("#viewerContent").innerHTML = renderMarkdown(report.content);
  const sources = report.sources || [];
  $("#viewerSourceAudit").innerHTML = `
    <div class="source-audit ${escapeHtml(audit.coverage_level || "none")}">
      <strong>${escapeHtml(audit.coverage_label || "尚未审计")}</strong>
      <span>一手 ${audit.primary_count || 0} · 正文引用 ${audit.cited_count || 0} · 独立域名 ${audit.unique_domains || 0} · 数字同行引用 ${audit.cited_numeric_claim_count || 0}/${audit.numeric_claim_count || 0}</span>
      ${(audit.warnings || []).length ? `<details><summary>查看证据缺口</summary>${audit.warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}</details>` : ""}
    </div>`;
  $("#viewerSources").innerHTML = sources.length
    ? sources.map((source, index) => `<a class="source-link" href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer"><div><b class="source-tier tier-${source.quality_tier || 3}">${escapeHtml(source.quality_label || "待核验")}</b><i>${escapeHtml(source.citation_role || "检索参考")}</i></div><strong>${index + 1}. ${escapeHtml(source.title || "原始来源")}</strong><span>${escapeHtml(source.publisher || source.domain || "")} · ${escapeHtml(source.source_type_label || "")}</span><span>${escapeHtml(source.url)}</span></a>`).join("")
    : `<p class="source-empty">这份报告没有联网来源。若为演示报告，这是正常现象；正式实时研究应当带来源。</p>`;
  $("#reportViewer").classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeReport() {
  $("#reportViewer").classList.add("hidden");
  document.body.style.overflow = "";
}

async function bootstrap() {
  try {
    [state.health, state.profile, state.watchlist, state.reports, state.jobs, state.frameworks, state.memory, state.backgroundTasks, state.updates] = await Promise.all([
      api("/api/health"),
      api("/api/profile"),
      api("/api/watchlist"),
      api("/api/reports?limit=500"),
      api("/api/jobs"),
      api("/api/frameworks"),
      api("/api/memory/overview"),
      api("/api/background-research?limit=30"),
      api("/api/updates/status"),
    ]);
    await refreshConversations(true);
    renderHealth();
    renderOverview();
    renderMarketContext();
    renderWatchlist();
    renderHistory();
    renderJobs();
    renderFrameworks();
    state.backgroundStatuses = Object.fromEntries(state.backgroundTasks.map((task) => [task.id, task.status]));
    state.backgroundInitialized = true;
    renderBackgroundTasks();
    renderMemory();
    renderUpdateStatus();
    fillSettings();
    renderConversation();
    bindDynamicExamples();
  } catch (error) {
    toast(`系统初始化失败：${error.message}`, "error");
  }
}

function bindEvents() {
  $("#companyTrackingWeekday").innerHTML = weekdayNames.map((name, index) =>
    `<option value="${index}">${name}</option>`
  ).join("");
  $("#companyTrackingDay").innerHTML = Array.from({ length: 28 }, (_, index) =>
    `<option value="${index + 1}">${index + 1} 号</option>`
  ).join("");
  $("#companyTrackingMonth").innerHTML = Array.from({ length: 12 }, (_, index) =>
    `<option value="${index + 1}">${index + 1} 月</option>`
  ).join("");
  $$("[data-page]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.page)));
  $("#mobileMenu").addEventListener("click", () => document.body.classList.toggle("menu-open"));
  $("#heroDailyBtn").addEventListener("click", () => navigate("markets"));
  $("#dailyBtn").addEventListener("click", () => runResearch(
    "/api/research/daily",
    {
      question: "生成今日市场简报",
      context: $("#dailyContext").value.trim(),
      engine: $("#dailyEngine").value,
    },
    "正在生成今日简报"
  ));

  $("#openWatchlistForm").addEventListener("click", () => $("#watchlistForm").classList.toggle("hidden"));
  $("#cancelWatchlist").addEventListener("click", () => $("#watchlistForm").classList.add("hidden"));
  $("#watchlistForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/watchlist", {
        method: "POST",
        body: JSON.stringify({
          name: $("#watchName").value.trim(),
          symbol: $("#watchSymbol").value.trim(),
          market: $("#watchMarket").value,
          thesis: $("#watchThesis").value.trim(),
          notes: "",
        }),
      });
      event.target.reset();
      $("#watchMarket").value = "港股";
      $("#watchlistForm").classList.add("hidden");
      await refreshWatchlist();
      toast("公司已加入自选列表");
    } catch (error) { toast(error.message, "error"); }
  });

  $("#companyBtn").addEventListener("click", async () => {
    const company = $("#companyName").value.trim();
    if (!company) return toast("请先填写公司名称", "error");
    const task = await runResearch("/api/research/company", {
      company,
      symbol: $("#companySymbol").value.trim(),
      market: $("#companyMarket").value,
      context: $("#companyContext").value.trim(),
      engine: $("#companyEngine").value,
      review_mode: $("#companyTeamReview").checked ? "team" : "single",
    }, `正在研究 ${company}`);
    if (task?.request?.watchlist_id) {
      await refreshWatchlist();
      await openCompanyWorkspace(Number(task.request.watchlist_id));
    }
  });

  $("#newConversation").addEventListener("click", createNewConversation);
  $("#backToCompanies").addEventListener("click", () => navigate("companies"));
  $("#detailResearchNow").addEventListener("click", async () => {
    if (!state.currentCompany) return;
    await runResearch("/api/research/company", {
      company: state.currentCompany.name,
      symbol: state.currentCompany.symbol,
      market: state.currentCompany.market,
      context: state.currentCompany.thesis || "持续更新公司基本面和消息面变化",
      watchlist_id: state.currentCompany.id,
      engine: "auto",
      review_mode: "single",
    }, `正在研究 ${state.currentCompany.name}`);
  });
  $("#detailTeamResearch").addEventListener("click", async () => {
    if (!state.currentCompany) return;
    await runResearch("/api/research/company", {
      company: state.currentCompany.name,
      symbol: state.currentCompany.symbol,
      market: state.currentCompany.market,
      context: state.currentCompany.thesis || "持续更新公司基本面和消息面变化",
      watchlist_id: state.currentCompany.id,
      engine: "auto",
      review_mode: "team",
    }, `正在双员工复核 ${state.currentCompany.name}`);
  });
  $("#newCompanyConversation").addEventListener("click", () => createCompanyConversation(false));
  $("#openHypothesisForm").addEventListener("click", () => showHypothesisForm());
  $("#cancelHypothesis").addEventListener("click", hideHypothesisForm);
  $("#hypothesisForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.currentCompany) return;
    const payload = {
      title: $("#hypothesisTitle").value.trim(),
      statement: $("#hypothesisStatement").value.trim(),
      status: $("#hypothesisStatus").value,
      support_evidence: splitEvidence($("#hypothesisSupport").value),
      counter_evidence: splitEvidence($("#hypothesisCounter").value),
      validation_signals: splitEvidence($("#hypothesisValidation").value),
      invalidation_signals: splitEvidence($("#hypothesisInvalidation").value),
      next_review_at: $("#hypothesisNextReview").value,
    };
    const path = state.editingHypothesisId
      ? `/api/hypotheses/${state.editingHypothesisId}`
      : "/api/hypotheses";
    if (!state.editingHypothesisId) payload.watchlist_id = state.currentCompany.id;
    try {
      await api(path, { method: state.editingHypothesisId ? "PUT" : "POST", body: JSON.stringify(payload) });
      hideHypothesisForm();
      await refreshCompanyWorkspace();
      toast("研究假设已保存");
    } catch (error) { toast(error.message, "error"); }
  });
  $("#openCompanyChatInMain").addEventListener("click", async () => {
    if (!state.companyConversation) {
      const created = await createCompanyConversation(false);
      if (!created) return;
    }
    state.currentConversation = state.companyConversation;
    navigate("ask");
    renderConversation();
  });
  $("#companyTrackingForm").addEventListener("input", () => { state.companyTrackingDirty = true; });
  $("#companyTrackingForm").addEventListener("change", () => { state.companyTrackingDirty = true; });
  $("#companyTrackingForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.currentCompany) return;
    try {
      const result = await api(`/api/watchlist/${state.currentCompany.id}/tracking`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: $("#companyTrackingEnabled").checked,
          frequency: $("#companyTrackingFrequency").value,
          time_of_day: $("#companyTrackingTime").value,
          weekday: Number($("#companyTrackingWeekday").value),
          day_of_month: Number($("#companyTrackingDay").value),
          month_of_year: Number($("#companyTrackingMonth").value),
          engine: $("#companyTrackingEngine").value,
          frameworks: state.profile?.reference_investors || [],
        }),
      });
      state.currentCompany = result.company;
      state.companyTrackingDirty = false;
      await Promise.all([refreshJobs(), refreshWatchlist(), refreshCompanyWorkspace()]);
      toast(result.company.tracking_enabled ? "公司持续跟踪已开启" : "公司持续跟踪已暂停");
    } catch (error) { toast(error.message, "error"); }
  });
  $("#companyChatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = $("#companyChatInput").value.trim();
    if (!content) return;
    if (!state.companyConversation) {
      const created = await createCompanyConversation(false);
      if (!created) return;
    }
    $("#companyChatInput").value = "";
    try {
      await sendConversationInBackground(
        state.companyConversation.id,
        content,
        $("#companyChatEngine").value,
        $("#companyChatUseWeb").checked,
      );
    } catch (error) {
      $("#companyChatInput").value = content;
      toast(error.message, "error");
    }
  });
  $("#companyChatInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#companyChatForm").requestSubmit();
    }
  });
  $("#backgroundTaskButton").addEventListener("click", openBackgroundDrawer);
  $("#closeBackgroundDrawer").addEventListener("click", () => $("#backgroundDrawer").classList.add("hidden"));
  $("#newJobType")?.addEventListener("change", updateNewJobScheduleControls);
  updateNewJobScheduleControls();
  $("#taskBuilder").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/jobs", {
        method: "POST",
        body: JSON.stringify(jobPayload(event.currentTarget)),
      });
      await refreshJobs();
      toast("新任务已添加到右侧列表");
    } catch (error) { toast(error.message, "error"); }
  });
  $("#downloadConversation").addEventListener("click", () => {
    if (!state.currentConversation) return toast("请先选择一条对话", "error");
    downloadConversationFile(state.currentConversation.id, $("#conversationExportFormat").value);
  });
  $("#openCodex").addEventListener("click", async () => {
    try {
      const result = await api("/api/codex/launch");
      window.location.href = result.url;
      toast(
        result.platform === "Windows"
          ? "正在唤起 Windows Codex；若没有打开，请按页面说明选择产品文件夹。"
          : "已唤起 Codex；发送预填内容后，这个项目里的对话会自动同步回来。"
      );
    } catch (error) {
      toast(error.message, "error");
    }
  });
  $("#loadMoreConversations").addEventListener("click", () => refreshConversations(false));
  let searchTimer;
  $("#conversationSearch").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      state.conversationQuery = event.target.value.trim();
      await refreshConversations(true);
    }, 280);
  });
  $("#conversationFilters").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-source]");
    if (!button) return;
    $$("[data-source]", $("#conversationFilters")).forEach((item) => item.classList.toggle("active", item === button));
    state.conversationSource = button.dataset.source;
    await refreshConversations(true);
  });
  $("#chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = $("#chatInput").value.trim();
    if (!content) return;
    if (!state.currentConversation) {
      try { await createNewConversation(); }
      catch (error) { return toast(error.message, "error"); }
    }
    const conversationId = state.currentConversation.id;
    const selectedEngine = $("#chatEngine").value;
    $("#chatInput").value = "";
    try {
      await sendConversationInBackground(
        conversationId,
        content,
        selectedEngine,
        $("#chatUseWeb").checked,
      );
    } catch (error) {
      $("#chatInput").value = content;
      toast(error.message, "error");
    }
    $("#chatInput").focus();
  });
  $("#chatInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#chatForm").requestSubmit();
    }
  });
  $("#chatMessages").addEventListener("click", (event) => {
    const button = event.target.closest(".chat-examples button");
    if (!button) return;
    $("#chatInput").value = button.textContent.trim();
    $("#chatInput").focus();
  });

  $("#settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      owner_name: $("#ownerName").value.trim() || "老板",
      primary_markets: splitList($("#primaryMarkets").value),
      reference_markets: splitList($("#referenceMarkets").value),
      focus_sectors: splitList($("#focusSectors").value),
      excluded_sectors: splitList($("#excludedSectors").value),
      investment_horizon: $("#investmentHorizon").value.trim(),
      risk_preference: $("#riskPreference").value.trim(),
      analysis_framework: $("#analysisFramework").value.trim(),
      reference_investors: splitList($("#referenceInvestors").value),
      preferred_metrics: splitList($("#preferredMetrics").value),
      report_style: $("#reportStyle").value.trim(),
      data_permissions: splitList($("#dataPermissions").value),
      privacy_boundaries: splitList($("#privacyBoundaries").value),
      report_time: state.profile.report_time || "08:00",
      auto_brief_enabled: false,
      last_auto_brief_date: state.profile.last_auto_brief_date || "",
    };
    try {
      state.profile = await api("/api/profile", { method: "PUT", body: JSON.stringify(payload) });
      renderOverview();
      renderMarketContext();
      toast("老板投资说明书已保存");
    } catch (error) { toast(error.message, "error"); }
  });
  $("#createBackup").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "正在备份…";
    try {
      const backup = await api("/api/backups", { method: "POST" });
      state.health = await api("/api/health");
      renderHealth();
      toast(`备份完成：${backup.name}`);
    } catch (error) {
      toast(`备份失败：${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = "立即备份";
    }
  });
  $("#checkUpdate").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "正在检查…";
    try {
      state.updates = await api("/api/updates/check", { method: "POST" });
      renderUpdateStatus();
      toast(state.updates.message || "更新检查完成");
    } catch (error) {
      toast(`更新检查失败：${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = "检查新版本";
    }
  });
  $("#installUpdate").addEventListener("click", async (event) => {
    if (!state.updates?.update_available) return;
    const confirmed = window.confirm("安装时研究台会短暂重启。系统会先备份老板全部资料，失败会自动回滚。现在安装吗？");
    if (!confirmed) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "正在启动更新…";
    try {
      state.updates = await api("/api/updates/install", {
        method: "POST",
        headers: { "X-AI-Research-Action": "install-update" },
      });
      renderUpdateStatus();
      toast("更新程序已启动，网页会短暂断开并自动恢复。");
    } catch (error) {
      button.disabled = false;
      button.textContent = "安装新版本";
      toast(`启动更新失败：${error.message}`, "error");
    }
  });

  $("#reportFilters").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    $$("button", $("#reportFilters")).forEach((item) => item.classList.toggle("active", item === button));
    state.historyFilter = button.dataset.filter;
    renderHistory();
  });
  $("#closeViewer").addEventListener("click", closeReport);
  $("#closeViewerBackdrop").addEventListener("click", closeReport);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeReport(); });
  $("#copyReport").addEventListener("click", async () => {
    if (!state.currentReport) return;
    try {
      await navigator.clipboard.writeText(state.currentReport.content);
      toast("报告正文已复制");
    } catch { toast("复制失败，请手动选择正文", "error"); }
  });
  $("#downloadReport").addEventListener("click", () => {
    if (!state.currentReport) return;
    downloadReportFile(state.currentReport.id, $("#reportExportFormat").value);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("#todayDate").textContent = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
  bindEvents();
  bootstrap().then(() => {
    const initialPage = window.location.hash.slice(1);
    navigate(pageMeta[initialPage] ? initialPage : "markets");
    setInterval(() => refreshBackgroundTasks(true), 3000);
    setInterval(() => refreshLiveData(), 5000);
  });
});

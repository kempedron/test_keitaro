const PREFIX = document.body.dataset.prefix || "test_";
const state = {
  createOffer: null,
  editor: {
    campaignId: null,
    detail: null,
    targetStreamId: null,
    offers: [],
    autocomplete: null,
  },
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (networkError) {
    const error = new Error("Сеть недоступна: " + networkError.message);
    error.status = 0;
    throw error;
  }
  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    if (data) {
      if (typeof data.detail === "string") message = data.detail;
      else if (data.detail) message = JSON.stringify(data.detail);
      else if (typeof data.error === "string") message = data.error;
    }
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function toast(message, type = "success", timeout = 4500) {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.innerHTML = escapeHtml(message);
  $("toast-container").appendChild(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transition = "opacity .2s ease";
    setTimeout(() => node.remove(), 220);
  }, timeout);
}

function showError(error) {
  const modal = $("error-modal");
  const status = error.status || error.data?.keitaro_status || "—";
  let detail = error.message || "Неизвестная ошибка";
  if (error.data?.payload) {
    try {
      detail += "\n\nPayload:\n" + JSON.stringify(error.data.payload, null, 2);
    } catch {
      detail += "\n\nPayload: " + String(error.data.payload);
    }
  }
  $("error-status").textContent = `HTTP ${status}`;
  $("error-text").textContent = detail;
  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function hideError() {
  const modal = $("error-modal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

function setTab(name) {
  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  $("panel-create").classList.toggle("hidden", name !== "create");
  $("panel-editor").classList.toggle("hidden", name !== "editor");
  if (name === "editor" && !state.editor.detail) {
    loadCampaigns().catch(showError);
  }
}

function previewName(value) {
  const trimmed = value.trim();
  if (!trimmed) return PREFIX;
  if (trimmed.toLowerCase().startsWith(PREFIX.toLowerCase())) {
    return PREFIX + trimmed.slice(PREFIX.length);
  }
  return PREFIX + trimmed;
}

function fillSelect(select, payload) {
  select.innerHTML = "";
  const items = payload.items || [];
  if (!items.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Нет доступных элементов";
    select.appendChild(option);
    return;
  }
  for (const item of items) {
    const option = document.createElement("option");
    option.value = String(item.id);
    option.textContent = `${item.name} (#${item.id})`;
    if (item.state && item.state !== "active") option.textContent += " — неактивен";
    select.appendChild(option);
  }
  if (payload.default_id) select.value = String(payload.default_id);
}

function createAutocomplete(input, dropdown, fetcher, onPick) {
  let items = [];
  let activeIndex = -1;
  let sequence = 0;
  let timer = null;

  function hide() {
    dropdown.classList.add("hidden");
    dropdown.innerHTML = "";
    activeIndex = -1;
  }

  function render() {
    dropdown.innerHTML = "";
    if (!items.length) {
      dropdown.innerHTML = '<div class="empty">Ничего не найдено</div>';
      dropdown.classList.remove("hidden");
      return;
    }
    items.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.index = String(index);
      button.className = index === activeIndex ? "active" : "";
      button.innerHTML = `<span class="font-medium">${escapeHtml(item.name)}</span>
        <span class="text-xs text-slate-500">#${item.id}${item.state && item.state !== "active" ? " · " + escapeHtml(item.state) : ""}</span>`;
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => pick(index));
      dropdown.appendChild(button);
    });
    dropdown.classList.remove("hidden");
  }

  function pick(index) {
    const item = items[index];
    if (!item) return;
    input.value = item.name;
    hide();
    onPick(item);
  }

  async function run() {
    const current = ++sequence;
    try {
      items = await fetcher(input.value.trim());
      if (current !== sequence) return;
      activeIndex = items.length ? 0 : -1;
      render();
    } catch (error) {
      hide();
      showError(error);
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(run, 120);
  });
  input.addEventListener("focus", () => {
    clearTimeout(timer);
    timer = setTimeout(run, 60);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
      render();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      render();
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      pick(activeIndex);
    } else if (event.key === "Escape") {
      hide();
    }
  });
  document.addEventListener("click", (event) => {
    if (event.target !== input && !dropdown.contains(event.target)) hide();
  });

  return { clear: hide, trigger: run };
}

async function loadReferences() {
  const [domains, groups, sources] = await Promise.all([
    api("/api/references/domains"),
    api("/api/references/groups"),
    api("/api/references/traffic_sources"),
  ]);
  fillSelect($("domain-select"), domains);
  fillSelect($("group-select"), groups);
  fillSelect($("source-select"), sources);

  createAutocomplete(
    $("offer-search"),
    $("offer-dropdown"),
    async (query) => (await api(`/api/references/offers?q=${encodeURIComponent(query)}`)).items,
    (item) => {
      state.createOffer = item;
      $("offer-id-manual").value = "";
      $("offer-selected").textContent = `Выбран: ${item.name} (#${item.id})`;
      $("offer-search").classList.remove("invalid");
      $("offer-id-manual").classList.remove("invalid");
    },
  );
  $("offer-search").addEventListener("input", () => {
    if ($("offer-search").value.trim()) $("offer-id-manual").value = "";
    if (state.createOffer && $("offer-search").value !== state.createOffer.name) {
      state.createOffer = null;
      $("offer-selected").textContent = "Оффер не выбран";
    }
  });
  $("offer-id-manual").addEventListener("input", () => {
    const value = $("offer-id-manual").value.trim();
    if (value) {
      state.createOffer = null;
      $("offer-search").value = "";
      $("offer-selected").textContent = `Будет использован оффер #${value}`;
    } else {
      $("offer-selected").textContent = "Оффер не выбран";
    }
    $("offer-id-manual").classList.remove("invalid");
  });
}

function renderCreateResult(data) {
  const campaign = data.campaign || {};
  const streams = data.streams || [];
  const campaignUrl = campaign.campaign_url || "";
  const streamRows = streams
    .map((stream) => {
      const filters = (stream.filters || [])
        .map(
          (filter) =>
            `<span class="badge gray">${escapeHtml(filter.name)}:${escapeHtml(filter.mode)} ${escapeHtml(
              Array.isArray(filter.payload) ? filter.payload.join(", ") : filter.payload || "",
            )}</span>`,
        )
        .join(" ");
      const offers = (stream.offers || [])
        .map((offer) => `#${escapeHtml(offer.offer_id)} · ${escapeHtml(offer.share)}%`)
        .join(", ");
      const action =
        stream.schema === "redirect"
          ? `<div class="text-xs text-slate-500 mt-1">Редирект: ${escapeHtml(stream.action_payload)}</div>`
          : "";
      return `<li class="border border-slate-200 rounded-lg p-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge">#${escapeHtml(stream.position)}</span>
          <span class="font-medium">${escapeHtml(stream.name)}</span>
          <span class="badge gray">${escapeHtml(stream.type)}</span>
          <span class="badge gray">${escapeHtml(stream.schema)}</span>
        </div>
        ${action}
        <div class="flex flex-wrap gap-1 mt-1">${filters}</div>
        ${offers ? `<div class="text-xs text-slate-500 mt-1">Офферы: ${offers}</div>` : ""}
      </li>`;
    })
    .join("");

  $("create-result").classList.remove("hidden");
  $("create-result").innerHTML = `
    <div class="flex items-center justify-between gap-3">
      <h3 class="text-lg font-semibold text-emerald-700">Кампания создана</h3>
      <span class="badge green">ID ${escapeHtml(campaign.id)}</span>
    </div>
    <dl class="mt-3 text-sm space-y-1">
      <div class="flex justify-between gap-3"><dt class="text-slate-500">Имя</dt><dd class="font-medium text-right">${escapeHtml(campaign.name)}</dd></div>
      <div class="flex justify-between gap-3"><dt class="text-slate-500">Alias</dt><dd class="font-mono text-xs text-right">${escapeHtml(campaign.alias)}</dd></div>
      <div class="flex justify-between gap-3"><dt class="text-slate-500">Домен</dt><dd class="text-right">${escapeHtml(campaign.domain_name || campaign.domain || campaign.domain_id || "")}</dd></div>
      <div class="flex justify-between gap-3"><dt class="text-slate-500">Группа</dt><dd class="text-right">${escapeHtml(campaign.group_name || campaign.group || campaign.group_id || "")}</dd></div>
      <div class="flex justify-between gap-3"><dt class="text-slate-500">Источник</dt><dd class="text-right">${escapeHtml(campaign.traffic_source_name || campaign.traffic_source_id || "")}</dd></div>
    </dl>
    ${
      campaignUrl
        ? `<a class="inline-block mt-2 text-sm text-indigo-600 hover:underline break-all" href="${escapeHtml(campaignUrl)}" target="_blank" rel="noopener">URL кампании: ${escapeHtml(campaignUrl)}</a>`
        : ""
    }
    <div class="mt-4">
      <h4 class="text-sm font-semibold mb-2">Потоки</h4>
      <ul class="space-y-2">${streamRows || '<li class="text-sm text-slate-500">Потоки не вернулись</li>'}</ul>
    </div>
    <button type="button" id="open-created" class="btn-primary mt-4 w-full" data-id="${escapeHtml(campaign.id)}">Открыть в редакторе</button>
  `;
  $("open-created").addEventListener("click", () => {
    setTab("editor");
    openCampaign(Number(campaign.id)).catch(showError);
  });
}

async function submitCreate(event) {
  event.preventDefault();
  const name = $("campaign-name").value.trim();
  const geo = $("geo-input").value.trim();
  if (!name) {
    toast("Введите название кампании", "warn");
    $("campaign-name").classList.add("invalid");
    return;
  }
  if (!geo) {
    toast("Введите гео-код", "warn");
    $("geo-input").classList.add("invalid");
    return;
  }
  const manualOfferId = Number.parseInt($("offer-id-manual").value, 10);
  const offerId = state.createOffer ? state.createOffer.id : manualOfferId;
  if (!state.createOffer && (!Number.isInteger(manualOfferId) || manualOfferId <= 0)) {
    toast("Выберите оффер из списка или укажите его ID", "warn");
    $("offer-search").classList.add("invalid");
    $("offer-id-manual").classList.add("invalid");
    $("offer-search").focus();
    return;
  }
  $("campaign-name").classList.remove("invalid");
  $("geo-input").classList.remove("invalid");
  $("offer-search").classList.remove("invalid");
  $("offer-id-manual").classList.remove("invalid");

  const body = {
    name,
    geo,
    offer_id: offerId,
    domain_id: Number($("domain-select").value) || null,
    group_id: Number($("group-select").value) || null,
    traffic_source_id: Number($("source-select").value) || null,
  };

  const spinner = $("create-spinner");
  const button = $("create-submit");
  spinner.classList.remove("hidden");
  button.disabled = true;
  try {
    const data = await api("/api/campaigns", { method: "POST", body: JSON.stringify(body) });
    renderCreateResult(data || {});
    toast(`Кампания #${data?.campaign?.id} создана`, "success");
    loadCampaigns().catch(() => {});
  } catch (error) {
    showError(error);
    toast("Не удалось создать кампанию", "error");
  } finally {
    spinner.classList.add("hidden");
    button.disabled = false;
  }
}

function resetCreateForm() {
  $("campaign-name").value = "";
  $("geo-input").value = "";
  $("offer-search").value = "";
  $("offer-id-manual").value = "";
  $("offer-selected").textContent = "Оффер не выбран";
  state.createOffer = null;
  $("name-preview").textContent = PREFIX;
  $("create-result").classList.add("hidden");
}

async function loadCampaigns() {
  const mine = $("campaign-mine").checked;
  const query = $("campaign-search").value.trim();
  const data = await api(
    `/api/campaigns?mine=${mine ? "true" : "false"}&q=${encodeURIComponent(query)}`,
  );
  renderCampaignList(data.items || []);
}

function renderCampaignList(items) {
  const container = $("campaign-list");
  if (!items.length) {
    container.innerHTML = '<div class="p-4 text-sm text-slate-500">Кампании не найдены</div>';
    return;
  }
  container.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "campaign-item";
    if (state.editor.campaignId === item.id) button.classList.add("selected");
    button.dataset.id = String(item.id);
    button.innerHTML = `
      <div class="flex items-center justify-between gap-2">
        <span class="font-medium text-sm truncate">${escapeHtml(item.name)}</span>
        <span class="badge gray">#${item.id}</span>
      </div>
      <div class="text-xs text-slate-500 truncate">${escapeHtml(item.alias)}</div>
      <div class="flex gap-1 mt-1">
        ${item.is_local ? '<span class="badge green">локальная запись</span>' : ""}
        ${item.state && item.state !== "active" ? `<span class="badge red">${escapeHtml(item.state)}</span>` : ""}
      </div>`;
    button.addEventListener("click", () => {
      openCampaign(item.id).catch(showError);
    });
    container.appendChild(button);
  }
}

async function openCampaign(campaignId) {
  if (!Number.isInteger(campaignId) || campaignId <= 0) {
    toast("Введите корректный ID кампании", "warn");
    return;
  }
  $("campaign-id-input").value = String(campaignId);
  const detail = await api(`/api/campaigns/${campaignId}`);
  state.editor.campaignId = campaignId;
  state.editor.detail = detail;
  state.editor.targetStreamId = detail.target_stream_id || null;
  $("editor-empty").classList.add("hidden");
  $("editor-content").classList.remove("hidden");
  renderEditor();
  document.querySelectorAll(".campaign-item").forEach((item) => {
    item.classList.toggle("selected", Number(item.dataset.id) === campaignId);
  });
}

function streamFilters(stream) {
  return (stream.filters || [])
    .map(
      (filter) =>
        `<span class="badge gray">${escapeHtml(filter.name)}:${escapeHtml(filter.mode)} ${escapeHtml(
          Array.isArray(filter.payload) ? filter.payload.join(", ") : filter.payload || "",
        )}</span>`,
    )
    .join(" ");
}

function offerPreview(stream) {
  const offers = stream.offers_view || [];
  if (!offers.length) return '<span class="text-xs text-slate-500">Офферов нет</span>';
  return offers
    .map(
      (offer) =>
        `<span class="badge ${offer.state === "active" ? "" : "gray"}">${escapeHtml(offer.name)} · ${escapeHtml(offer.share)}%</span>`,
    )
    .join(" ");
}

function renderEditor() {
  const detail = state.editor.detail;
  const campaign = detail.campaign || {};
  const streams = detail.streams || [];
  const record = detail.record;
  const isMine = String(campaign.name || "").toLowerCase().startsWith(PREFIX.toLowerCase());

  const landingStreams = streams.filter((stream) => stream.schema === "landings");
  if (
    landingStreams.length &&
    !landingStreams.some((stream) => stream.id === state.editor.targetStreamId)
  ) {
    state.editor.targetStreamId = landingStreams[0].id;
  }

  const streamSelector =
    landingStreams.length > 1
      ? `<select id="target-stream" class="input max-w-md">
          ${landingStreams
            .map(
              (stream) =>
                `<option value="${stream.id}" ${stream.id === state.editor.targetStreamId ? "selected" : ""}>Поток #${stream.position} — ${escapeHtml(stream.name)}</option>`,
            )
            .join("")}
        </select>`
      : "";

  const streamCards = streams
    .map((stream) => {
      const isTarget = stream.id === state.editor.targetStreamId;
      const actionLine =
        stream.schema === "redirect"
          ? `<div class="text-sm mt-2">Редирект: <span class="font-mono text-xs bg-slate-100 px-1 rounded">${escapeHtml(stream.action_payload)}</span></div>`
          : "";
      return `<div class="stream-card ${isTarget ? "active" : ""} p-4">
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge">позиция ${escapeHtml(stream.position)}</span>
          <span class="font-semibold">${escapeHtml(stream.name)}</span>
          <span class="badge gray">${escapeHtml(stream.type)}</span>
          <span class="badge gray">${escapeHtml(stream.schema)}</span>
          <span class="badge gray">${escapeHtml(stream.action_type || "")}</span>
          ${isTarget ? '<span class="badge green">редактируется ниже</span>' : ""}
        </div>
        <div class="flex flex-wrap gap-1 mt-2">${streamFilters(stream) || '<span class="text-xs text-slate-400">без фильтров</span>'}</div>
        ${actionLine}
        <div class="flex flex-wrap gap-1 mt-2">${offerPreview(stream)}</div>
      </div>`;
    })
    .join("");

  $("editor-content").innerHTML = `
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-xl font-semibold">${escapeHtml(campaign.name)}</h2>
            <span class="badge">ID ${escapeHtml(campaign.id)}</span>
            <span class="badge ${campaign.state === "active" ? "green" : "red"}">${escapeHtml(campaign.state || "")}</span>
            ${record ? '<span class="badge green">есть локальная запись</span>' : ""}
          </div>
          <div class="text-xs text-slate-500 mt-1 font-mono">${escapeHtml(campaign.alias)}</div>
          ${
            campaign.campaign_url
              ? `<a class="text-xs text-indigo-600 hover:underline break-all" href="${escapeHtml(campaign.campaign_url)}" target="_blank" rel="noopener">URL кампании</a>`
              : ""
          }
        </div>
        <div class="flex gap-2">
          <button type="button" id="editor-refresh" class="btn-secondary">Обновить</button>
          ${isMine ? '<button type="button" id="archive-campaign" class="btn-danger">В архив</button>' : ""}
        </div>
      </div>
      <dl class="grid sm:grid-cols-3 gap-3 mt-4 text-sm">
        <div><dt class="text-slate-500">Домен</dt><dd class="font-medium">${escapeHtml(campaign.domain_name || campaign.domain || campaign.domain_id || "—")}</dd></div>
        <div><dt class="text-slate-500">Группа</dt><dd class="font-medium">${escapeHtml(campaign.group_name || campaign.group || campaign.group_id || "—")}</dd></div>
        <div><dt class="text-slate-500">Источник</dt><dd class="font-medium">${escapeHtml(campaign.traffic_source_name || campaign.traffic_source_id || "—")}</dd></div>
      </dl>
    </div>

    <div class="space-y-3">
      <h3 class="text-lg font-semibold">Потоки кампании</h3>
      ${streamCards || '<div class="text-sm text-slate-500">Потоков нет</div>'}
    </div>

    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h3 class="text-lg font-semibold">Офферы потока</h3>
        <div class="flex items-center gap-2">
          ${streamSelector}
          <span id="total-badge" class="badge gray">Итого: 0%</span>
        </div>
      </div>
      <div id="offers-editor"></div>
    </div>
  `;

  $("editor-refresh").addEventListener("click", () => {
    openCampaign(state.editor.campaignId).catch(showError);
  });
  const archiveButton = $("archive-campaign");
  if (archiveButton) archiveButton.addEventListener("click", archiveCampaign);
  const targetSelect = $("target-stream");
  if (targetSelect) {
    targetSelect.addEventListener("change", () => {
      state.editor.targetStreamId = Number(targetSelect.value);
      renderEditor();
    });
  }

  renderOffersEditor();
}

function currentStream() {
  const streams = state.editor.detail?.streams || [];
  return streams.find((stream) => stream.id === state.editor.targetStreamId) || null;
}

function renderOffersEditor() {
  const container = $("offers-editor");
  if (!container) return;
  const stream = currentStream();
  if (!stream) {
    container.innerHTML =
      '<div class="text-sm text-slate-500">У этой кампании нет потока со схемой landings. Добавление офферов недоступно.</div>';
    updateTotal();
    return;
  }
  state.editor.offers = (stream.offers_view || []).map((offer) => ({
    offer_id: offer.offer_id,
    name: offer.name,
    share: Number(offer.share) || 0,
    state: offer.state || "active",
  }));

  container.innerHTML = `
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-slate-500 border-b border-slate-200">
            <th class="py-2 pr-3">Оффер</th>
            <th class="py-2 pr-3">ID</th>
            <th class="py-2 pr-3 w-28">Доля, %</th>
            <th class="py-2 w-20"></th>
          </tr>
        </thead>
        <tbody id="offers-body"></tbody>
      </table>
    </div>
    <div class="relative mt-3 max-w-lg">
      <label class="label" for="editor-offer-search">Добавить оффер</label>
      <input id="editor-offer-search" class="input" autocomplete="off" placeholder="Поиск по названию или ID" />
      <div id="editor-offer-dropdown" class="dropdown hidden"></div>
    </div>
    <div class="mt-2 flex flex-wrap items-end gap-2 max-w-lg">
      <div class="flex-1">
        <label class="label" for="editor-offer-id">Добавить по ID</label>
        <input id="editor-offer-id" class="input" type="number" min="1" step="1" placeholder="Например, 17210" />
      </div>
      <button type="button" id="add-offer-by-id" class="btn-secondary">Добавить</button>
    </div>
    <div class="flex flex-wrap items-center gap-2 mt-4">
      <button type="button" id="equalize-offers" class="btn-secondary">Выровнять поровну</button>
      <button type="button" id="save-offers" class="btn-primary">Сохранить изменения в Keitaro</button>
      <span class="text-xs text-slate-500">Активные офферы должны давать ровно 100%.</span>
    </div>
    <p id="shares-warning" class="hidden text-sm text-rose-600 mt-2"></p>
  `;

  renderOfferRows();

  if (state.editor.autocomplete) state.editor.autocomplete.clear();
  state.editor.autocomplete = createAutocomplete(
    $("editor-offer-search"),
    $("editor-offer-dropdown"),
    async (query) => (await api(`/api/references/offers?q=${encodeURIComponent(query)}`)).items,
    (item) => addOffer(item),
  );

  const addById = () => {
    const offerId = Number.parseInt($("editor-offer-id").value, 10);
    if (!Number.isInteger(offerId) || offerId <= 0) {
      toast("Введите корректный ID оффера", "warn");
      $("editor-offer-id").classList.add("invalid");
      return;
    }
    $("editor-offer-id").classList.remove("invalid");
    addOfferById(offerId).catch(showError);
  };
  $("add-offer-by-id").addEventListener("click", addById);
  $("editor-offer-id").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addById();
    }
  });

  $("equalize-offers").addEventListener("click", equalizeOffers);
  $("save-offers").addEventListener("click", saveOffers);
  updateTotal();
}

function renderOfferRows() {
  const body = $("offers-body");
  if (!body) return;
  if (!state.editor.offers.length) {
    body.innerHTML =
      '<tr><td colspan="4" class="py-4 text-slate-500">Офферов пока нет. Добавьте первый через поиск.</td></tr>';
    updateTotal();
    return;
  }
  body.innerHTML = state.editor.offers
    .map(
      (offer) => `
      <tr class="border-b border-slate-100">
        <td class="py-2 pr-3">
          <div class="font-medium">${escapeHtml(offer.name)}</div>
          ${offer.state !== "active" ? `<span class="badge gray">${escapeHtml(offer.state)}</span>` : ""}
        </td>
        <td class="py-2 pr-3 font-mono text-xs">#${escapeHtml(offer.offer_id)}</td>
        <td class="py-2 pr-3">
          <input class="share-input" type="number" min="0" max="100" step="1"
            data-offer-id="${escapeHtml(offer.offer_id)}" value="${escapeHtml(offer.share)}" />
        </td>
        <td class="py-2 text-right">
          <button type="button" class="btn-danger" data-remove="${escapeHtml(offer.offer_id)}">Удалить</button>
        </td>
      </tr>`,
    )
    .join("");

  body.querySelectorAll(".share-input").forEach((input) => {
    input.addEventListener("input", () => {
      const offerId = Number(input.dataset.offerId);
      const offer = state.editor.offers.find((item) => item.offer_id === offerId);
      if (!offer) return;
      let value = Number.parseInt(input.value, 10);
      if (Number.isNaN(value)) value = 0;
      offer.share = Math.max(0, Math.min(100, value));
      updateTotal();
    });
    input.addEventListener("blur", () => {
      input.value = String(Math.max(0, Math.min(100, Number(input.value) || 0)));
    });
  });
  body.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", () => removeOffer(Number(button.dataset.remove)));
  });
  updateTotal();
}

function activeTotal() {
  return state.editor.offers
    .filter((offer) => offer.state === "active")
    .reduce((sum, offer) => sum + Number(offer.share || 0), 0);
}

function updateTotal() {
  const badge = $("total-badge");
  if (!badge) return;
  const total = activeTotal();
  badge.textContent = `Итого: ${total}%`;
  badge.className = `badge ${total === 100 || !state.editor.offers.length ? "green" : "red"}`;
  const warning = $("shares-warning");
  const saveButton = $("save-offers");
  const invalid = state.editor.offers.length > 0 && total !== 100;
  if (warning) {
    warning.classList.toggle("hidden", !invalid);
    warning.textContent = invalid
      ? `Сумма долей активных офферов равна ${total}%. Исправьте проценты, чтобы получилось ровно 100%.`
      : "";
  }
  if (saveButton) saveButton.disabled = invalid;
}

async function equalizeFromServer() {
  const ids = state.editor.offers.map((offer) => offer.offer_id);
  const data = await api("/api/shares/equalize", {
    method: "POST",
    body: JSON.stringify({ offer_ids: ids }),
  });
  const byId = new Map((data.offers || []).map((offer) => [offer.offer_id, offer.share]));
  state.editor.offers.forEach((offer) => {
    offer.share = byId.get(offer.offer_id) ?? 0;
    offer.state = "active";
  });
  if (!ids.length) state.editor.offers = [];
  renderOfferRows();
}

async function equalizeOffers() {
  if (!state.editor.offers.length) {
    toast("Нет офферов для распределения", "warn");
    return;
  }
  try {
    await equalizeFromServer();
    toast("Доли пересчитаны поровну", "success");
  } catch (error) {
    showError(error);
  }
}

function offerNameById(offerId) {
  for (const stream of state.editor.detail?.streams || []) {
    const found = (stream.offers_view || []).find((offer) => offer.offer_id === offerId);
    if (found?.name) return found.name;
  }
  return `Offer #${offerId}`;
}

async function addOffer(item) {
  await addOfferById(item.id, item.name);
}

async function addOfferById(offerId, name = null) {
  if (state.editor.offers.some((offer) => offer.offer_id === offerId)) {
    toast(`Оффер #${offerId} уже есть в потоке`, "warn");
    return;
  }
  state.editor.offers.push({
    offer_id: offerId,
    name: name || offerNameById(offerId),
    share: 0,
    state: "active",
  });
  try {
    await equalizeFromServer();
    toast(`Оффер #${offerId} добавлен, доли пересчитаны`, "success");
  } catch (error) {
    showError(error);
  }
  const searchInput = $("editor-offer-search");
  if (searchInput) searchInput.value = "";
  const idInput = $("editor-offer-id");
  if (idInput) idInput.value = "";
}

async function removeOffer(offerId) {
  const target = state.editor.offers.find((offer) => offer.offer_id === offerId);
  if (!target) return;
  if (!window.confirm(`Удалить оффер «${target.name}» из потока?`)) return;
  state.editor.offers = state.editor.offers.filter((offer) => offer.offer_id !== offerId);
  try {
    await equalizeFromServer();
    toast("Оффер удалён, доли пересчитаны", "success");
  } catch (error) {
    showError(error);
  }
}

async function saveOffers() {
  const stream = currentStream();
  if (!stream) return;
  const total = activeTotal();
  if (state.editor.offers.length && total !== 100) {
    toast("Сумма долей должна быть ровно 100%", "warn");
    return;
  }
  const payload = {
    offers: state.editor.offers.map((offer) => ({
      offer_id: offer.offer_id,
      share: Number(offer.share),
      state: offer.state || "active",
    })),
  };
  const button = $("save-offers");
  button.disabled = true;
  try {
    const result = await api(
      `/api/campaigns/${state.editor.campaignId}/streams/${stream.id}/offers`,
      { method: "PUT", body: JSON.stringify(payload) },
    );
    const updatedStream = result.stream;
    const index = state.editor.detail.streams.findIndex((item) => item.id === updatedStream.id);
    if (index >= 0) state.editor.detail.streams[index] = updatedStream;
    renderEditor();
    const shares = (updatedStream.offers_view || [])
      .map((offer) => `${offer.share}%`)
      .join(" / ");
    toast(`Сохранено в Keitaro: ${shares || "пусто"}`, "success");
  } catch (error) {
    showError(error);
    toast("Keitaro не принял изменения", "error");
  } finally {
    updateTotal();
  }
}

async function archiveCampaign() {
  const detail = state.editor.detail;
  if (!detail) return;
  const name = detail.campaign?.name || "";
  if (!window.confirm(`Отправить кампанию «${name}» в архив Keitaro?`)) return;
  try {
    await api(`/api/campaigns/${state.editor.campaignId}/archive`, { method: "POST" });
    toast("Кампания отправлена в архив", "success");
    state.editor.detail = null;
    state.editor.campaignId = null;
    $("editor-content").classList.add("hidden");
    $("editor-empty").classList.remove("hidden");
    loadCampaigns().catch(showError);
  } catch (error) {
    showError(error);
  }
}

function bindEvents() {
  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => setTab(button.dataset.tab));
  });
  $("campaign-name").addEventListener("input", (event) => {
    $("name-preview").textContent = previewName(event.target.value);
  });
  $("create-form").addEventListener("submit", submitCreate);
  $("create-reset").addEventListener("click", resetCreateForm);
  $("error-close").addEventListener("click", hideError);
  $("error-modal").addEventListener("click", (event) => {
    if (event.target === $("error-modal")) hideError();
  });
  $("campaign-refresh").addEventListener("click", () => loadCampaigns().catch(showError));
  $("campaign-search").addEventListener("input", debounce(() => loadCampaigns().catch(showError), 250));
  $("campaign-mine").addEventListener("change", () => loadCampaigns().catch(showError));
  $("campaign-open-id").addEventListener("click", () => {
    openCampaign(Number($("campaign-id-input").value)).catch(showError);
  });
  $("campaign-id-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      openCampaign(Number($("campaign-id-input").value)).catch(showError);
    }
  });
}

async function init() {
  bindEvents();
  setTab("create");
  $("name-preview").textContent = PREFIX;
  try {
    await loadReferences();
  } catch (error) {
    toast("Не удалось загрузить справочники Keitaro", "error");
    showError(error);
  }
  loadCampaigns().catch(() => {});
}

document.addEventListener("DOMContentLoaded", init);

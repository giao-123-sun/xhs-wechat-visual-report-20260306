const state = {
  accounts: [],
  notes: [],
  stats: null,
  pipeline: null,
  category: "全部",
  keyword: "",
};

function fmt(num) {
  return new Intl.NumberFormat("zh-CN").format(num || 0);
}

function createStats() {
  const stats = state.stats || {};
  const cards = [
    { label: "账号数", value: fmt(stats.account_count || 0) },
    { label: "笔记总数", value: fmt(stats.note_count || 0) },
    { label: "分类数", value: fmt(Object.keys(stats.categories || {}).length) },
  ];
  document.getElementById("stats").innerHTML = cards
    .map(
      (c) => `
      <div class="stat-card">
        <div class="label">${c.label}</div>
        <div class="value">${c.value}</div>
      </div>
    `
    )
    .join("");
}

function createPipelineStats() {
  const progress = (state.pipeline || {}).progress || {};
  const cards = [
    { label: "唯一笔记", value: fmt(progress.source_unique_notes || 0) },
    { label: "详情已抓取", value: fmt(progress.detail_count || 0) },
    { label: "OCR 已完成", value: fmt(progress.ocr_count || 0) },
    { label: "待补详情", value: fmt(progress.detail_remaining || 0) },
    { label: "待补 OCR", value: fmt(progress.ocr_remaining_after_detail || 0) },
  ];
  document.getElementById("pipelineStats").innerHTML = cards
    .map(
      (c) => `
      <div class="stat-card">
        <div class="label">${c.label}</div>
        <div class="value">${c.value}</div>
      </div>
    `
    )
    .join("");

  const categories = Object.entries(progress.processed_categories || {}).sort((a, b) => b[1] - a[1]);
  document.getElementById("pipelineCategories").innerHTML = [
    `<span class="chip static">OCR 模型：${progress.current_ocr_model || "未知"}</span>`,
    ...categories.slice(0, 10).map(
      ([name, count]) => `<span class="chip static">${name} · ${fmt(count)}</span>`
    ),
  ].join("");
}

function createChips() {
  const wrap = document.getElementById("categoryChips");
  const categories = ["全部", ...Object.keys(state.stats.categories || {})];
  wrap.innerHTML = categories
    .map(
      (c) =>
        `<button class="chip ${c === state.category ? "active" : ""}" data-cat="${c}">${c}</button>`
    )
    .join("");

  wrap.querySelectorAll(".chip").forEach((el) => {
    el.addEventListener("click", () => {
      state.category = el.dataset.cat || "全部";
      render();
    });
  });
}

function filteredAccounts() {
  return state.accounts.filter((a) => {
    const catOk = state.category === "全部" || a.category === state.category;
    const kw = state.keyword.trim().toLowerCase();
    const kwOk =
      !kw ||
      (a.account_name || "").toLowerCase().includes(kw) ||
      (a.red_id || "").toLowerCase().includes(kw);
    return catOk && kwOk;
  });
}

function filteredNotes(accounts) {
  const ids = new Set(accounts.map((a) => `${a.account_name}::${a.red_id}`));
  return state.notes.filter((n) => ids.has(`${n.account_name}::${n.red_id}`));
}

function renderChart(accounts) {
  const top = [...accounts].sort((a, b) => b.note_count - a.note_count).slice(0, 10);
  const max = top.length ? top[0].note_count : 1;
  document.getElementById("topChart").innerHTML = top
    .map(
      (a) => `
      <div class="bar-row">
        <div title="${a.red_id}">${a.account_name}</div>
        <div class="bar-wrap"><div class="bar" style="width:${(a.note_count / max) * 100}%"></div></div>
        <div>${fmt(a.note_count)}</div>
      </div>
    `
    )
    .join("");
}

function renderAccounts(accounts) {
  document.getElementById("accountsGrid").innerHTML = accounts
    .map(
      (a) => `
      <article class="account-card">
        <h3>${a.account_name}</h3>
        <p class="meta">小红书号：${a.red_id}</p>
        <p class="meta">分类：${a.category}</p>
        <p class="meta">笔记：${fmt(a.note_count)} | 总赞：${fmt(a.total_likes)}</p>
        <p class="meta"><a href="${a.source_csv}" target="_blank" rel="noopener">查看该账号原始 CSV</a></p>
      </article>
    `
    )
    .join("");
}

function renderNotes(notes) {
  const rows = notes.slice(0, 300);
  document.getElementById("notesTableBody").innerHTML = rows
    .map(
      (n) => `
      <tr>
        <td>${n.account_name}<br /><span class="meta">${n.red_id}</span></td>
        <td>${n.category}</td>
        <td><a href="${n.note_url}" target="_blank" rel="noopener">${n.display_title || "(无标题)"}</a></td>
        <td>${fmt(n.liked_count)}</td>
        <td>${n.note_type || ""}</td>
      </tr>
    `
    )
    .join("");
}

function renderFeaturedNotes() {
  const featured = (state.pipeline || {}).featured_notes || [];
  document.getElementById("featuredNotes").innerHTML = featured
    .map(
      (note) => `
      <article class="feature-card">
        ${note.cover_image ? `<img class="feature-cover" src="${note.cover_image}" alt="${note.title}" loading="lazy" />` : ""}
        <div class="feature-body">
          <div class="feature-top">
            <span class="badge">${note.category}</span>
            <span class="meta">${fmt(note.liked_count)} 赞</span>
          </div>
          <h3><a href="${note.note_url}" target="_blank" rel="noopener">${note.title || "无标题"}</a></h3>
          <p class="meta">${note.account_name} · ${note.note_type || "未知类型"} · ${note.upload_time || "时间未知"}</p>
          <p class="feature-text"><strong>正文摘录：</strong>${note.desc_excerpt || "暂无正文"}</p>
          <p class="feature-text"><strong>图片文字：</strong>${note.ocr_excerpt || "暂无 OCR 文本"}</p>
        </div>
      </article>
    `
    )
    .join("");
}

async function renderGallery() {
  const images = [];
  for (let i = 1; i <= 30; i++) {
    const png = `data/wechat_images/${String(i).padStart(3, "0")}.png`;
    const jpg = `data/wechat_images/${String(i).padStart(3, "0")}.jpg`;
    const gif = `data/wechat_images/${String(i).padStart(3, "0")}.gif`;
    images.push(png, jpg, gif);
  }
  const checks = await Promise.all(
    images.map(async (src) => {
      try {
        const r = await fetch(src, { method: "HEAD" });
        return r.ok ? src : null;
      } catch {
        return null;
      }
    })
  );
  const existing = checks.filter(Boolean);
  document.getElementById("gallery").innerHTML = existing
    .map((src) => `<a href="${src}" target="_blank" rel="noopener"><img src="${src}" alt="微信图片" loading="lazy" /></a>`)
    .join("");
}

function render() {
  createStats();
  createPipelineStats();
  createChips();
  const accounts = filteredAccounts();
  const notes = filteredNotes(accounts);
  renderChart(accounts);
  renderAccounts(accounts);
  renderNotes(notes);
  renderFeaturedNotes();
}

async function init() {
  const [accounts, notes, stats, pipeline] = await Promise.all([
    fetch("data/accounts.json").then((r) => r.json()),
    fetch("data/notes.json").then((r) => r.json()),
    fetch("data/stats.json").then((r) => r.json()),
    fetch("data/note_pipeline_summary.json").then((r) => r.json()),
  ]);
  state.accounts = accounts;
  state.notes = notes;
  state.stats = stats;
  state.pipeline = pipeline;
  document.getElementById("keyword").addEventListener("input", (e) => {
    state.keyword = e.target.value || "";
    render();
  });
  render();
  await renderGallery();
}

init().catch((e) => {
  console.error(e);
  document.body.innerHTML = `<main class="container"><p>数据加载失败：${String(e)}</p></main>`;
});

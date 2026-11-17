/* 个人 AI 科研助手 — 原生 JS 单页应用（无构建步骤）。
 *
 * 功能区：论文列表（详情/多选对比） / 上传+批量导入 / 论文精读（深度解读
 * + 笔记） / 问答对话。markdown 内容一律经 md.js（先整体 HTML 转义再解析，
 * Review Focus #5——LLM/笔记内容不会变成可执行的裸 HTML 标签）渲染。
 *
 * 后端契约：
 *   POST /api/papers/upload   (multipart 字段名 file) → {paper_id}
 *   POST /api/papers/arxiv    {url}                    → {paper_id}
 *   GET  /api/papers         → {papers:[{id,title,authors,abstract,arxiv_id,
 *                                        categories,source,status,pdf_path,
 *                                        created_at}]}
 *   POST /api/import/folder  {path}                    → {job_id}
 *   GET  /api/import/jobs/{id} → {id,total,done,failed,errors,status}
 *   POST /api/papers/{id}/interpret → {job_id}（已有 running job → 409）
 *   GET  /api/papers/{id}/notes → {notes:[{id,paper_id,note_type,content,
 *                                         created_at}]}
 *   POST /api/papers/{id}/notes  {note_type,content} → {note_id}
 *   DELETE /api/notes/{id}                       → {deleted:true}
 *   POST /api/compare      {paper_ids:[2-5],question|null} → {matrix,citations}
 *   POST /api/qa           {question, paper_id|null} → {answer,
 *                                        citations:[{paper_id,page,quote}]}
 */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);

  const API = {
    papers: "/api/papers",
    upload: "/api/papers/upload",
    arxiv: "/api/papers/arxiv",
    importFolder: "/api/import/folder",
    importJob: (id) => `/api/import/jobs/${id}`,
    interpret: (id) => `/api/papers/${id}/interpret`,
    notes: (id) => `/api/papers/${id}/notes`,
    note: (id) => `/api/notes/${id}`,
    compare: "/api/compare",
    qa: "/api/qa",
  };

  /* 轮询上限：job 的 done/failed 超过 30 分钟无变化视为已中断
   *（T7#1：import_jobs 重启后会卡在 running），停止轮询。interpret 的
   * 轮询沿用同一防御（LLM 分钟级，正常推进不会触碰该上限）。 */
  const JOB_STALL_MS = 30 * 60 * 1000;
  const JOB_POLL_MS = 2000;

  const SOURCE_LABEL = { upload: "上传", arxiv: "arXiv" };
  const STATUS_LABEL = {
    new: "新入库",
    pushed: "已推送",
    reading: "精读中",
    read: "已读",
    dismissed: "已忽略",
  };
  /* 详情页状态徽标只关心精读流转（P2：new → reading → read） */
  const STATUS_CLASS = {
    new: "badge st-new",
    reading: "badge st-reading",
    read: "badge st-read",
  };

  /* six_dim note 是 "## 背景\n\n…\n## 创新点…" 结构；按 "## " 标题切段渲染六卡 */

  /* ---------- 页面内 toast（不用浏览器 alert） ---------- */
  function showToast(text, kind = "error", ms = 5000) {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = text;
    $("toast-area").appendChild(el);
    setTimeout(() => {
      el.classList.add("fade");
      setTimeout(() => el.remove(), 500);
    }, ms);
  }

  /* 统一的 fetch：非 2xx 抛出带 detail 的 Error。 */
  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, options);
    } catch (err) {
      throw new Error(`网络请求失败：${err.message}`);
    }
    let body = null;
    try {
      body = await response.json();
    } catch (_) {
      /* 非 JSON 响应体忽略 */
    }
    if (!response.ok) {
      const detail = body && body.detail ? `：${body.detail}` : "";
      const error = new Error(`请求失败（HTTP ${response.status}）${detail}`);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function formatTime(raw) {
    if (!raw) return "";
    /* SQLite CURRENT_TIMESTAMP 是无时区的 "YYYY-MM-DD HH:MM:SS"（UTC），
     * 部分浏览器（如 Firefox）无法解析该格式且其它引擎按本地时区解释。
     * 补 "T" 分隔符 + "Z" 统一按 UTC 解析；已带时区的 ISO 串原样通过。 */
    const hasZone = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(raw);
    const normalized = hasZone ? raw : raw.replace(" ", "T") + "Z";
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return String(raw);
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function statusBadge(paper) {
    const el = document.createElement("span");
    el.className = STATUS_CLASS[paper.status] || "badge";
    el.textContent = STATUS_LABEL[paper.status] || paper.status || "";
    return el;
  }

  /* ---------- 论文列表 ---------- */
  let selectedPaperId = null; // 问答上下文（P1 行为，入口移入详情面板）
  let detailPaperId = null; // 当前详情面板展示的论文
  let compareIds = []; // 对比多选（保持勾选顺序，即 [P{n}] 序号顺序）
  const papersById = new Map();

  async function loadPapers() {
    const list = $("paper-list");
    const empty = $("papers-empty");
    try {
      const data = await api(API.papers);
      const papers = (data && data.papers) || [];
      papersById.clear();
      for (const paper of papers) papersById.set(paper.id, paper);
      empty.hidden = papers.length > 0;
      if (selectedPaperId && !papersById.has(selectedPaperId)) {
        selectedPaperId = null;
        updateQaContext();
      }
      compareIds = compareIds.filter((id) => papersById.has(id));
      updateCompareButton();
      list.innerHTML = "";
      for (const paper of papers) {
        list.appendChild(renderPaper(paper));
      }
    } catch (err) {
      showToast(`论文列表加载失败：${err.message}`);
    }
  }

  function renderPaper(paper) {
    const li = document.createElement("li");
    li.dataset.id = paper.id;
    if (paper.id === selectedPaperId) li.classList.add("selected");
    if (paper.id === detailPaperId) li.classList.add("detailing");

    const top = document.createElement("div");
    top.className = "paper-top";

    /* 对比多选：checkbox 的点击不冒泡成打开详情 */
    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "compare-check";
    check.checked = compareIds.includes(paper.id);
    check.setAttribute("aria-label", "加入对比");
    check.addEventListener("click", (event) => event.stopPropagation());
    check.addEventListener("change", () => {
      if (check.checked) {
        compareIds.push(paper.id);
      } else {
        compareIds = compareIds.filter((id) => id !== paper.id);
      }
      updateCompareButton();
    });
    top.appendChild(check);

    const title = document.createElement("div");
    title.className = "paper-title";
    title.textContent = paper.title || "(无标题)";
    title.title = "点击查看详情";
    title.addEventListener("click", () => openDetail(paper.id));
    top.appendChild(title);
    li.appendChild(top);

    const meta = document.createElement("div");
    meta.className = "paper-meta";

    const src = document.createElement("span");
    src.className = `badge src-${paper.source || "unknown"}`;
    src.textContent = SOURCE_LABEL[paper.source] || paper.source || "未知来源";
    meta.appendChild(src);
    meta.appendChild(statusBadge(paper));

    const time = document.createElement("span");
    time.textContent = formatTime(paper.created_at);
    meta.appendChild(time);

    li.appendChild(meta);
    return li;
  }

  function updateQaContext() {
    const paper = papersById.get(selectedPaperId);
    $("qa-context").textContent = paper
      ? `当前上下文：仅「${paper.title || `论文 #${paper.id}`}」`
      : "当前上下文：全部论文";
    $("detail-set-context").textContent =
      selectedPaperId === detailPaperId ? "取消问答上下文" : "设为问答上下文";
  }

  /* ---------- 详情面板（精读视图） ---------- */
  async function openDetail(paperId) {
    detailPaperId = paperId;
    const paper = papersById.get(paperId);
    $("detail-panel").hidden = false;
    $("detail-title").textContent = paper ? paper.title || "(无标题)" : `论文 #${paperId}`;
    renderDetailMeta(paper);
    const abs = $("detail-abstract");
    abs.textContent = paper ? paper.abstract || "" : "";
    abs.hidden = !(paper && paper.abstract);
    updateQaContext();
    $("detail-panel").scrollIntoView({ block: "start", behavior: "smooth" });
    document.querySelectorAll("#paper-list li").forEach((el) => {
      el.classList.toggle("detailing", Number(el.dataset.id) === detailPaperId);
    });
    resetInterpretUi();
    await loadNotes(paperId);
  }

  function renderDetailMeta(paper) {
    const meta = $("detail-meta");
    meta.innerHTML = "";
    if (!paper) return;
    const src = document.createElement("span");
    src.className = `badge src-${paper.source || "unknown"}`;
    src.textContent = SOURCE_LABEL[paper.source] || paper.source || "未知来源";
    meta.appendChild(src);
    meta.appendChild(statusBadge(paper));
    const time = document.createElement("span");
    time.textContent = `入库 ${formatTime(paper.created_at)}`;
    meta.appendChild(time);
  }

  function resetInterpretUi() {
    $("interpret-btn").disabled = false;
    $("interpret-btn").textContent = "生成深度解读";
    $("interpret-progress").hidden = true;
    $("interpret-bar-fill").style.width = "0";
  }

  async function refreshDetail() {
    await loadPapers();
    if (detailPaperId == null) return;
    const paper = papersById.get(detailPaperId);
    if (!paper) {
      closeDetail();
      return;
    }
    await openDetail(detailPaperId);
  }

  function closeDetail() {
    $("detail-panel").hidden = true;
    detailPaperId = null;
    document.querySelectorAll("#paper-list li").forEach((el) => {
      el.classList.remove("detailing");
    });
  }

  /* 深度解读：POST interpret → 轮询 job（30 分钟停滞防御）→ 刷新论文与笔记 */
  async function startInterpret() {
    if (detailPaperId == null) return;
    const btn = $("interpret-btn");
    const wrap = $("interpret-progress");
    const bar = $("interpret-bar-fill");
    const text = $("interpret-status-text");
    btn.disabled = true;
    btn.textContent = "解读生成中…";
    wrap.hidden = false;
    text.classList.remove("error");
    bar.style.width = "0";
    try {
      const data = await api(API.interpret(detailPaperId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      await pollInterpretJob(data.job_id, bar, text);
    } catch (err) {
      if (err.status === 409) {
        /* 已有 running job：置灰 + 提示（该任务的结果稍后经"刷新"可见） */
        text.textContent =
          "该论文已有解读任务在进行，请稍后在面板中点「刷新」查看结果。";
        showToast("已有深度解读任务在进行中。");
        return;
      }
      text.classList.add("error");
      text.textContent = `启动解读失败：${err.message}`;
      btn.disabled = false;
      btn.textContent = "生成深度解读";
      return;
    }
    btn.disabled = false;
    btn.textContent = "重新生成解读";
    await loadPapers();
    if (detailPaperId != null) {
      /* 刷新元数据里的状态徽标后重新拉取笔记 */
      renderDetailMeta(papersById.get(detailPaperId));
      await loadNotes(detailPaperId);
    }
  }

  async function pollInterpretJob(jobId, bar, text) {
    const started = Date.now();
    let lastChange = Date.now();
    let lastProgress = "";
    for (;;) {
      let job;
      try {
        job = await api(API.importJob(jobId));
      } catch (err) {
        text.classList.add("error");
        text.textContent = `查询解读进度失败：${err.message}`;
        return;
      }
      const progress = `${job.done}+${job.failed}/${job.total}`;
      if (progress !== lastProgress) {
        lastProgress = progress;
        lastChange = Date.now();
      }
      const pct = job.total > 0 ? Math.round(((job.done + job.failed) / job.total) * 100) : 0;
      bar.style.width = `${pct}%`;
      /* API 契约：'failed' 映射为 done+failed=1，错误在 errors 数组 */
      if (job.status === "done") {
        if (job.failed) {
          text.classList.add("error");
          let lines = `解读失败（成功 ${job.done}，失败 ${job.failed}）。`;
          for (const error of job.errors || []) lines += `\n· ${error}`;
          text.textContent = lines;
          showToast("深度解读失败，详见面板提示。");
        } else {
          text.classList.remove("error");
          text.textContent = `解读完成（${job.done}/${job.total}）。`;
          showToast("深度解读完成。", "success");
        }
        return;
      }
      text.classList.remove("error");
      text.textContent = "正在逐节解读并综合六维分析（LLM 调用，分钟级）…";
      if (Date.now() - lastChange > JOB_STALL_MS) {
        text.classList.add("error");
        text.textContent += "\n任务超过 30 分钟无进展，可能已中断（服务重启会丢失运行中的任务），已停止轮询。";
        return;
      }
      if (Date.now() - started > JOB_STALL_MS) return; // 兜底：总时长上限
      await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS));
    }
  }

  /* 笔记与解读结果渲染。
   * note_type 约定（app/api/notes.py）：six_dim = 六维综合（markdown），
   * section_analysis = 逐节解读（markdown），annotation/chat_summary =
   * 用户笔记（textarea + 下拉添加，可删除）。API 层不转义内容——渲染
   * 安全完全由前端 md.js 的"先转义后解析"保证。 */
  async function loadNotes(paperId) {
    const six = $("six-dim");
    const sections = $("sections-list");
    const sectionsTitle = $("sections-title");
    const notesList = $("notes-list");
    six.innerHTML = "";
    sections.innerHTML = "";
    notesList.innerHTML = "";
    six.appendChild(spinner("笔记加载中…"));
    let data;
    try {
      data = await api(API.notes(paperId));
    } catch (err) {
      six.innerHTML = "";
      showToast(`笔记加载失败：${err.message}`);
      return;
    }
    six.innerHTML = "";
    const notes = (data && data.notes) || [];

    /* 六维卡片：content 形如 "## 背景\n\n…\n\n## 创新点…" */
    const sixNote = notes.find((n) => n.note_type === "six_dim");
    renderSixDim(six, sixNote ? sixNote.content : "");

    /* 章节解读（先落库的节在前 = 文档顺序；notes 接口按新→旧返回） */
    const sectionNotes = notes
      .filter((n) => n.note_type === "section_analysis")
      .reverse();
    sectionsTitle.hidden = sectionNotes.length === 0;
    sectionNotes.forEach((note, index) => {
      sections.appendChild(renderSectionCard(note, index));
    });

    /* 用户笔记（annotation/chat_summary）：新→旧，每条可删除 */
    const userNotes = notes.filter(
      (n) => n.note_type === "annotation" || n.note_type === "chat_summary"
    );
    for (const note of userNotes) {
      notesList.appendChild(renderUserNote(note));
    }
  }

  function spinner(text) {
    const el = document.createElement("p");
    el.className = "hint";
    el.textContent = text;
    return el;
  }

  function renderSixDim(container, content) {
    if (!content || !content.trim()) return;
    /* 按 "## " 标题切段；切不出标题结构就整篇一张卡兜底 */
    const chunks = content
      .split(/\n(?=##\s)/)
      .map((chunk) => chunk.trim())
      .filter(Boolean);
    const cards = chunks.length > 1
      ? chunks.map((chunk) => {
          const m = /^##\s*(.+)$/.exec(chunk.split("\n")[0]);
          return {
            heading: m ? m[1].trim() : "综合",
            body: m ? chunk.split("\n").slice(1).join("\n") : chunk,
          };
        })
      : [{ heading: "六维综合", body: content }];
    const grid = document.createElement("div");
    grid.className = "six-grid";
    for (const card of cards) {
      const item = document.createElement("div");
      item.className = "six-card";
      const h = document.createElement("div");
      h.className = "six-title";
      h.textContent = card.heading;
      item.appendChild(h);
      if (card.body && card.body.trim()) {
        item.appendChild(window.mdRender(card.body));
      }
      grid.appendChild(item);
    }
    container.appendChild(grid);
  }

  function renderSectionCard(note, index) {
    const card = document.createElement("div");
    card.className = "section-card";
    const head = document.createElement("div");
    head.className = "section-title";
    const first = (note.content || "").split("\n")[0];
    const m = /^#{1,6}\s+(.*)$/.exec(first.trim());
    head.textContent = m ? m[1].replace(/[*_`]/g, "").trim() : `章节解读 ${index + 1}`;
    card.appendChild(head);
    card.appendChild(window.mdRender(note.content || ""));
    return card;
  }

  function renderUserNote(note) {
    const li = document.createElement("li");
    li.className = "user-note";
    li.dataset.id = note.id;
    const head = document.createElement("div");
    head.className = "note-head";
    const type = document.createElement("span");
    type.className = "badge";
    type.textContent =
      note.note_type === "chat_summary" ? "对话总结" : "阅读批注";
    head.appendChild(type);
    const time = document.createElement("span");
    time.textContent = formatTime(note.created_at);
    head.appendChild(time);
    const del = document.createElement("button");
    del.className = "secondary note-delete";
    del.textContent = "删除";
    del.addEventListener("click", () => deleteNote(note.id));
    head.appendChild(del);
    li.appendChild(head);
    li.appendChild(window.mdRender(note.content || ""));
    return li;
  }

  async function addNote() {
    if (detailPaperId == null) return;
    const content = $("note-content").value.trim();
    if (!content) {
      showToast("笔记内容不能为空。");
      return;
    }
    const btn = $("add-note-btn");
    btn.disabled = true;
    try {
      await api(API.notes(detailPaperId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note_type: $("note-type").value, content }),
      });
      $("note-content").value = "";
      await loadNotes(detailPaperId);
      showToast("笔记已添加。", "success");
    } catch (err) {
      showToast(`添加笔记失败：${err.message}`);
    } finally {
      btn.disabled = false;
    }
  }

  async function deleteNote(noteId) {
    try {
      await api(API.note(noteId), { method: "DELETE" });
      await loadNotes(detailPaperId);
      showToast("笔记已删除。", "success");
    } catch (err) {
      showToast(`删除笔记失败：${err.message}`);
    }
  }

  /* ---------- 对比 ---------- */
  function updateCompareButton() {
    const n = compareIds.length;
    $("compare-btn").disabled = !(2 <= n && n <= 5);
    $("compare-hint").textContent =
      `已选 ${n} 篇${2 <= n && n <= 5 ? "" : "（需 2-5 篇）"}。`;
  }

  async function runCompare() {
    if (!(compareIds.length >= 2 && compareIds.length <= 5)) return;
    const btn = $("compare-btn");
    const result = $("compare-result");
    const question = $("compare-question").value.trim();
    btn.disabled = true;
    btn.textContent = "对比生成中…";
    result.innerHTML = "";
    result.appendChild(spinner("正在检索并对比（LLM 调用，可能需要一两分钟）…"));
    try {
      const data = await api(API.compare, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paper_ids: compareIds,
          question: question || null, // 空串按 null（API 契约）
        }),
      });
      result.innerHTML = "";
      renderCompareResult(result, data);
    } catch (err) {
      result.innerHTML = "";
      showToast(`生成对比失败：${err.message}`);
    } finally {
      btn.textContent = "生成对比";
      updateCompareButton();
    }
  }

  function renderCompareResult(container, data) {
    const matrix = (data && data.matrix) || "";
    if (matrix) container.appendChild(window.mdRender(matrix));
    const citations = (data && data.citations) || [];
    if (citations.length) {
      const list = document.createElement("ul");
      list.className = "citations";
      for (const cite of citations) {
        const li = document.createElement("li");
        li.className = "cite";
        const head = document.createElement("div");
        head.className = "cite-head";
        head.textContent = `页 ${cite.page}（论文 #${cite.paper_id}）`;
        li.appendChild(head);
        const quote = document.createElement("div");
        quote.className = "quote"; // CSS 限高滚动
        quote.textContent = cite.quote || "";
        li.appendChild(quote);
        list.appendChild(li);
      }
      container.appendChild(list);
    }
  }

  /* ---------- 上传 / arXiv / 批量导入 ---------- */
  async function uploadFile() {
    const input = $("pdf-file");
    const file = input.files[0];
    if (!file) {
      showToast("请先选择一个 PDF 文件。");
      return;
    }
    const btn = $("upload-btn");
    btn.disabled = true;
    btn.textContent = "上传中…";
    try {
      const form = new FormData();
      form.append("file", file); // 后端字段名：file（见 app/api/papers.py）
      const data = await api(API.upload, { method: "POST", body: form });
      showToast(`上传成功（paper_id=${data.paper_id}）`, "success");
      input.value = "";
      await loadPapers();
    } catch (err) {
      showToast(`上传失败：${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "上传 PDF";
    }
  }

  async function importArxiv() {
    const url = $("arxiv-url").value.trim();
    if (!url) {
      showToast("请输入 arXiv 链接或 ID。");
      return;
    }
    const btn = $("arxiv-btn");
    btn.disabled = true;
    btn.textContent = "导入中…";
    try {
      const data = await api(API.arxiv, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      showToast(`导入成功（paper_id=${data.paper_id}）`, "success");
      $("arxiv-url").value = "";
      await loadPapers();
    } catch (err) {
      showToast(`arXiv 导入失败：${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "导入 arXiv";
    }
  }

  /* 批量导入：进度条轮询 job；done/failed 30 分钟无变化 → 提示中断并停止。 */
  async function importFolder() {
    const path = $("import-path").value.trim();
    if (!path) {
      showToast("请输入要批量导入的文件夹路径。");
      return;
    }
    const btn = $("import-btn");
    btn.disabled = true;
    btn.textContent = "导入中…";
    const wrap = $("import-progress");
    const bar = $("import-bar-fill");
    const text = $("import-status-text");
    text.classList.remove("error");
    try {
      const data = await api(API.importFolder, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      wrap.hidden = false;
      await pollImportJob(data.job_id, bar, text);
      await loadPapers();
    } catch (err) {
      wrap.hidden = false;
      text.classList.add("error");
      text.textContent = `批量导入失败：${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "批量导入";
    }
  }

  async function pollImportJob(jobId, bar, text) {
    const started = Date.now();
    let lastChange = Date.now();
    let lastProgress = "";
    for (;;) {
      let job;
      try {
        job = await api(API.importJob(jobId));
      } catch (err) {
        text.classList.add("error");
        text.textContent = `查询导入进度失败：${err.message}`;
        return;
      }
      const progress = `${job.done}+${job.failed}/${job.total}`;
      if (progress !== lastProgress) {
        lastProgress = progress;
        lastChange = Date.now();
      }
      const pct = job.total > 0 ? Math.round(((job.done + job.failed) / job.total) * 100) : 0;
      bar.style.width = `${pct}%`;
      let lines = `进度 ${job.done}/${job.total}` +
        (job.failed ? `，失败 ${job.failed}` : "") +
        `，状态：${job.status === "done" ? "已完成" : "进行中"}`;
      for (const error of job.errors || []) lines += `\n· ${error}`;
      text.textContent = lines;

      if (job.status === "done") {
        if (job.failed) text.classList.add("error");
        showToast(`批量导入结束：成功 ${job.done}，失败 ${job.failed}`, job.failed ? "error" : "success");
        return;
      }
      if (Date.now() - lastChange > JOB_STALL_MS) {
        text.classList.add("error");
        text.textContent = lines + "\n任务可能已中断（服务重启会丢失运行中的导入任务），已停止轮询。";
        return;
      }
      if (Date.now() - started > JOB_STALL_MS) return; // 兜底：总时长上限
      await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS));
    }
  }

  /* ---------- 问答 ---------- */
  async function askQuestion(event) {
    event.preventDefault();
    const question = $("question").value.trim();
    if (!question) {
      showToast("请输入问题。");
      return;
    }
    const log = $("chat-log");
    const userMsg = document.createElement("div");
    userMsg.className = "msg user";
    const bubble = document.createElement("span");
    bubble.className = "bubble";
    bubble.textContent = question;
    userMsg.appendChild(bubble);
    log.appendChild(userMsg);

    const pending = document.createElement("div");
    pending.className = "msg pending";
    pending.textContent = "正在思考…";
    log.appendChild(pending);
    $("chat-log").scrollIntoView({ block: "end", behavior: "smooth" });

    const btn = $("ask-btn");
    btn.disabled = true;
    $("question").value = "";
    try {
      const data = await api(API.qa, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, paper_id: selectedPaperId }),
      });
      pending.replaceWith(renderAnswer(data));
    } catch (err) {
      pending.classList.remove("pending");
      pending.classList.add("error");
      pending.textContent = `回答失败：${err.message}`;
      if (err.status === 503) {
        pending.textContent += "（服务可能仍在下载模型或向量库不可用，请稍后重试）";
      }
      showToast(`提问失败：${err.message}`);
    } finally {
      btn.disabled = false;
      $("chat-log").scrollIntoView({ block: "end" });
    }
  }

  function renderAnswer(data) {
    const answer = document.createElement("div");
    answer.className = "msg answer";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = (data && data.answer) || "(空回答)";
    answer.appendChild(bubble);

    const citations = (data && data.citations) || [];
    if (citations.length) {
      const list = document.createElement("ul");
      list.className = "citations";
      for (const cite of citations) {
        const li = document.createElement("li");
        li.className = "cite";
        const head = document.createElement("div");
        head.className = "cite-head";
        head.textContent = `页 ${cite.page}（论文 #${cite.paper_id}）`;
        li.appendChild(head);
        const quote = document.createElement("div");
        quote.className = "quote"; // CSS 限高滚动
        quote.textContent = cite.quote || "";
        li.appendChild(quote);
        list.appendChild(li);
      }
      answer.appendChild(list);
    }
    return answer;
  }

  /* ---------- 初始化 ---------- */
  $("refresh-papers").addEventListener("click", loadPapers);
  $("upload-btn").addEventListener("click", uploadFile);
  $("arxiv-btn").addEventListener("click", importArxiv);
  $("import-btn").addEventListener("click", importFolder);
  $("qa-form").addEventListener("submit", askQuestion);
  $("compare-btn").addEventListener("click", runCompare);
  $("interpret-btn").addEventListener("click", startInterpret);
  $("detail-refresh").addEventListener("click", refreshDetail);
  $("detail-set-context").addEventListener("click", () => {
    selectedPaperId = selectedPaperId === detailPaperId ? null : detailPaperId;
    document.querySelectorAll("#paper-list li").forEach((el) => {
      el.classList.toggle("selected", Number(el.dataset.id) === selectedPaperId);
    });
    updateQaContext();
  });
  $("add-note-btn").addEventListener("click", addNote);

  updateCompareButton();
  loadPapers();
})();

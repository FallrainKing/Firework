/* 个人 AI 科研助手 — 原生 JS 单页应用（无构建步骤）。
 *
 * 三个功能区：论文列表 / 上传+批量导入 / 问答对话。
 * 后端契约（Task 7）：
 *   POST /api/papers/upload   (multipart 字段名 file) → {paper_id}
 *   POST /api/papers/arxiv    {url}                    → {paper_id}
 *   GET  /api/papers         → {papers:[{id,title,authors,abstract,arxiv_id,
 *                                        categories,source,status,pdf_path,
 *                                        created_at}]}
 *   POST /api/import/folder  {path}                    → {job_id}
 *   GET  /api/import/jobs/{id} → {id,total,done,failed,errors,status}
 *   POST /api/qa             {question, paper_id|null} → {answer,
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
    qa: "/api/qa",
  };

  /* 轮询上限：job 的 done/failed 超过 30 分钟无变化视为已中断
   *（T7#1：import_jobs 重启后会卡在 running），停止轮询。 */
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

  /* ---------- 论文列表 ---------- */
  let selectedPaperId = null;

  async function loadPapers() {
    const list = $("paper-list");
    const empty = $("papers-empty");
    try {
      const data = await api(API.papers);
      const papers = (data && data.papers) || [];
      empty.hidden = papers.length > 0;
      if (selectedPaperId && !papers.some((p) => p.id === selectedPaperId)) {
        selectedPaperId = null;
        updateQaContext();
      }
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

    const title = document.createElement("div");
    title.className = "paper-title";
    title.textContent = paper.title || "(无标题)";
    li.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "paper-meta";

    const src = document.createElement("span");
    src.className = `badge src-${paper.source || "unknown"}`;
    src.textContent = SOURCE_LABEL[paper.source] || paper.source || "未知来源";
    meta.appendChild(src);

    const status = document.createElement("span");
    status.className = "badge";
    status.textContent = STATUS_LABEL[paper.status] || paper.status || "";
    meta.appendChild(status);

    const time = document.createElement("span");
    time.textContent = formatTime(paper.created_at);
    meta.appendChild(time);

    li.appendChild(meta);
    li.addEventListener("click", () => {
      selectedPaperId = selectedPaperId === paper.id ? null : paper.id;
      list.querySelectorAll("li").forEach((el) => {
        el.classList.toggle("selected", Number(el.dataset.id) === selectedPaperId);
      });
      updateQaContext();
    });
    return li;
  }

  function updateQaContext() {
    const selected = document.querySelector("#paper-list li.selected .paper-title");
    $("qa-context").textContent = selected
      ? `当前上下文：仅「${selected.textContent}」`
      : "当前上下文：全部论文";
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

  loadPapers();
})();

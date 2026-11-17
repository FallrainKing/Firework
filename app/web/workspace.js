(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = { conversation: null, active: null, selectedView: 'chat', polling: false };
  const labels = { queued: '排队中', running: '智能体执行中', succeeded: '已完成', failed: '失败' };
  function stored(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { localStorage.removeItem(key); return null; } }
  const skills = { chat: '科研对话', search_library: '搜索论文库', search_arxiv: '搜索 arXiv' };
  function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
  async function api(path, options = {}) {
    const r = await fetch(path, options); let body;
    try { body = await r.json(); } catch { throw new Error('服务未返回有效数据，请稍后重试。'); }
    if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '请求失败，请检查输入或服务状态。');
    return body;
  }
  function error(e) { $('error').textContent = e.message || String(e); $('error').hidden = false; }
  function clearError() { $('error').hidden = true; }
  function selectView(name) {
    state.selectedView = name;
    ['chat', 'library', 'history'].forEach(v => $(v + '-view').hidden = v !== name);
    document.querySelectorAll('[data-view]').forEach(b => { if (b.dataset.view === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
    clearError();
    if (name === 'library') library().catch(error);
    if (name === 'history') history().catch(error);
  }
  function timeLabel(value) {
    const d = new Date(value.replace(' ', 'T') + 'Z');
    return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(d) + ' 北京时间';
  }
  function sourceLink(url, title) {
    try { const u = new URL(url); if (u.protocol !== 'https:' || u.hostname !== 'arxiv.org') return el('span', title); }
    catch { return el('span', title); }
    const a = el('a', title); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
  }
  function drawRun(run) {
    let card = document.getElementById('run-' + run.id);
    if (!card) { card = el('article', null, 'message'); card.id = 'run-' + run.id; $('messages').querySelector('.empty')?.remove(); $('messages').append(card); }
    card.replaceChildren();
    card.append(el('div', `${skills[run.skill] || run.skill} · ${labels[run.status] || run.status} · ${timeLabel(run.created_at)}`, 'role'));
    card.append(el('p', run.prompt, 'message user'));
    if (run.answer) card.append(el('div', run.answer, 'answer'));
    if (run.error) card.append(el('p', run.error, 'tool-error'));
    for (const call of run.tool_calls || []) {
      const box = el('details', null, 'source');
      box.append(el('summary', `${call.ok ? '已获取真实来源' : '工具失败'} · ${call.tool} · ${call.query || '全部论文'}`));
      for (const p of call.result?.papers || []) {
        box.append(sourceLink(p.url, p.title || '(无标题)'));
        box.append(el('div', p.arxiv_id ? `arXiv: ${p.arxiv_id}` : `论文库 ID: ${p.id}`, 'muted'));
      }
      if (call.error) box.append(el('p', call.error, 'tool-error'));
      if (call.result?.warning) box.append(el('p', '旧版文本页码尚未核验，不作为精确引用。', 'muted'));
      card.append(box);
    }
    const u = run.usage || {};
    if (Object.hasOwn(u, 'input_tokens')) card.append(el('div', `模型：${run.model} · 输入 ${u.input_tokens} / 输出 ${u.output_tokens} tokens · 缓存读取 ${u.cache_read_input_tokens || 0} · CLI 费用估算 ${run.cli_estimated_cost_usd == null ? '未知' : '$' + Number(run.cli_estimated_cost_usd).toFixed(6)}（未经核实）`, 'usage'));
  }
  function busy(on) { $('send').disabled = on; $('prompt').disabled = on; $('new-chat').disabled = on; document.querySelectorAll('input[name=skill]').forEach(i => i.disabled = on); }
  async function poll(runId) {
    if (state.polling) return;
    state.polling = true; busy(true);
    try {
      while (state.active === runId) {
        const run = await api('/api/agent/runs/' + runId); state.conversation = run.conversation_id; drawRun(run);
        $('task-state').textContent = labels[run.status] || run.status;
        if (['succeeded', 'failed'].includes(run.status)) { state.active = null; localStorage.removeItem('research-active-run'); localStorage.removeItem('research-pending-request'); break; }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    } catch (e) { error(e); $('task-state').textContent = '连接中断；刷新页面可继续查看，不会自动重复调用。'; }
    finally { state.polling = false; busy(false); }
  }
  async function openRun(runId) {
    if (state.active && state.active !== runId) throw new Error('请等待当前任务完成，再打开其他会话。');
    const run = await api('/api/agent/runs/' + runId); state.conversation = run.conversation_id;
    const data = await api('/api/agent/runs?conversation_id=' + run.conversation_id);
    $('messages').replaceChildren(); data.runs.slice().reverse().forEach(drawRun); selectView('chat');
    if (['queued', 'running'].includes(run.status)) { state.active = run.id; localStorage.setItem('research-active-run', run.id); await poll(run.id); }
  }
  $('composer').addEventListener('submit', async e => {
    e.preventDefault(); if (state.active) return; clearError();
    const prompt = $('prompt').value.trim(); if (!prompt) return;
    const request = { prompt, skill: document.querySelector('input[name=skill]:checked').value, conversation_id: state.conversation, request_key: crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2) };
    // Same payload/key may be recovered after a dropped POST response.
    const pending = stored('research-pending-request');
    const body = pending && pending.prompt === prompt && pending.skill === request.skill && pending.conversation_id === request.conversation_id ? pending : request;
    localStorage.setItem('research-pending-request', JSON.stringify(body)); busy(true);
    try {
      const run = await api('/api/agent/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      state.conversation = run.conversation_id; state.active = run.id; localStorage.setItem('research-active-run', run.id); $('prompt').value = ''; drawRun(run); await poll(run.id);
    } catch (e) { error(e); busy(false); }
  });
  $('new-chat').addEventListener('click', () => { state.conversation = null; $('messages').replaceChildren(el('div', '新对话已准备好。选择任务后发送消息。', 'empty')); $('prompt').value = ''; localStorage.removeItem('research-pending-request'); selectView('chat'); $('prompt').focus(); });
  async function library() {
    const data = await api('/api/agent/library?q=' + encodeURIComponent($('library-query').value)); const box = $('library-results'); box.replaceChildren();
    for (const paper of data.papers) {
      const row = el('article', null, 'paper'); row.append(el('h2', paper.title));
      row.append(el('p', `ID ${paper.id} · ${paper.status} · ${paper.arxiv_id || '本地 PDF'}`)); row.append(el('p', (paper.abstract || '').slice(0, 260)));
      const b = el('button', '让智能体检索相关论文'); b.addEventListener('click', () => { selectView('chat'); document.querySelector('input[value=search_arxiv]').checked = true; $('prompt').value = `查找与这篇论文相关的研究：${paper.title}`; $('prompt').focus(); }); row.append(b); box.append(row);
    }
    if (!data.papers.length) box.append(el('p', '未找到匹配论文。可返回智能体交互搜索 arXiv。', 'empty'));
  }
  async function history() {
    const data = await api('/api/agent/runs?q=' + encodeURIComponent($('history-query').value)); const box = $('history-results'); box.replaceChildren();
    for (const run of data.runs) {
      const row = el('article', null, 'run-row'); row.append(el('h2', run.prompt)); row.append(el('p', `${skills[run.skill]} · ${labels[run.status]} · ${timeLabel(run.created_at)}`, 'muted'));
      row.append(el('p', (run.answer || run.error || '').slice(0, 180))); const b = el('button', '打开记录与会话'); b.addEventListener('click', () => openRun(run.id).catch(error)); row.append(b); box.append(row);
    }
    if (!data.runs.length) box.append(el('p', '暂无记录。完成一次交互后会保存在这里。', 'empty'));
  }
  async function status() {
    try { const data = await api('/api/agent/status'); $('connection').textContent = data.runner.status === 'ok' ? '● 智能体已连接 · 数据库正常' : '○ 智能体离线 · 历史数据可读'; $('runtime-model').textContent = data.runner.model || '等待连接'; }
    catch { $('connection').textContent = '○ 服务连接失败'; }
  }
  document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => selectView(b.dataset.view)));
  $('library-form').addEventListener('submit', e => { e.preventDefault(); library().catch(error); });
  $('history-form').addEventListener('submit', e => { e.preventDefault(); history().catch(error); }); $('refresh-history').addEventListener('click', () => history().catch(error));
  status(); setInterval(status, 15000);
  const active = localStorage.getItem('research-active-run');
  if (active) { state.active = active; openRun(active).catch(e => { error(e); state.active = null; localStorage.removeItem('research-active-run'); }); }
  else { const pending = stored('research-pending-request'); if (pending) { state.conversation = pending.conversation_id; $('prompt').value = pending.prompt; const choice = [...document.querySelectorAll('input[name=skill]')].find(i => i.value === pending.skill); if (choice) choice.checked = true; $('task-state').textContent = '有一次提交未收到确认；再次发送相同内容会复用请求编号。'; } }
})();

const $ = (id) => document.getElementById(id);
const state = {chatId: crypto.randomUUID(), images: [], busy: false, health: null, count: 0};
let authEpoch = 0;
window.addEventListener('medix-signout', () => {
  authEpoch++; state.busy = false; state.images = []; state.chatId = crypto.randomUUID(); state.count = 0;
  $('messages').replaceChildren(); $('attachments').replaceChildren(); $('message').value = ''; $('remember').checked = false;
  $('messages').classList.remove('active'); $('welcome').hidden = false; $('chatTitle').textContent = '新的健康对话';
  document.body.classList.remove('chatting'); updateComposer();
});
function renderAccount(user) {
  $('topLoginButton').hidden = Boolean(user);
  updateComposer();
}
window.addEventListener('medix-auth-change', event => renderAccount(event.detail));
window.addEventListener('medix-auth-error', event => toast(event.detail));
MedixAuth.ready.then(renderAccount).catch(() => {});
const icon = (id) => `<svg aria-hidden="true"><use href="#i-${id}"/></svg>`;
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const escapeText = (value) => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
function toast(message) { $('toast').textContent = message; $('toast').classList.add('show'); clearTimeout(state.toast); state.toast = setTimeout(() => $('toast').classList.remove('show'), 4200); }
function scrollDown() { $('conversation').scrollTop = $('conversation').scrollHeight; }
function updateComposer() {
  window.MedixProfile?.setBusy(state.busy);
  $('sendButton').disabled = state.busy || (!$('message').value.trim() && !state.images.length);
  $('attachButton').disabled = state.busy;
  $('message').disabled = state.busy;
  $('newChat').disabled = state.busy;
  document.querySelectorAll('[data-action="upload"], [data-prompt], [data-example], #refreshPrompts').forEach(button => { button.disabled = state.busy; });
  $('remember').disabled = state.busy || !MedixAuth.user || !state.health?.memory_configured;
  $('message').style.height = 'auto';
  $('message').style.height = Math.min($('message').scrollHeight, 155) + 'px';
}
function renderAttachments() {
  $('attachments').replaceChildren();
  state.images.forEach((item, i) => {
    const card = document.createElement('div'); card.className = 'attachment';
    const image = document.createElement('img'); image.src = item.data; image.alt = '待上传图片预览';
    const name = document.createElement('span'); name.textContent = item.name;
    const button = document.createElement('button'); button.type = 'button'; button.innerHTML = icon('close'); button.setAttribute('aria-label', `移除 ${item.name}`);
    button.onclick = () => { state.images.splice(i, 1); renderAttachments(); updateComposer(); };
    card.append(image, name, button); $('attachments').append(card);
  });
  updateComposer();
}
async function addFiles(files) {
  if (state.busy) return;
  for (const file of files) {
    if (state.images.length >= 3) { toast('一次最多添加 3 张图片。'); break; }
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { toast('请选择 PNG、JPG 或 WebP 图片。'); continue; }
    if (file.size > 8 * 1024 * 1024) { toast('单张图片不能超过 8 MB。'); continue; }
    try {
      const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
      if (state.images.length < 3) state.images.push({name: file.name, data});
    } catch { toast('图片读取失败，请重新选择。'); }
  }
  renderAttachments(); $('message').focus();
}
$('attachButton').onclick = () => $('fileInput').click();
$('fileInput').onchange = (event) => { addFiles(event.target.files); event.target.value = ''; };
$('message').oninput = updateComposer;
$('message').onkeydown = (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$('sendButton').disabled) $('chatForm').requestSubmit(); } };
document.addEventListener('paste', event => {
  if (state.busy) return;
  const files = [...(event.clipboardData?.items || [])].filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
  if (files.length) { event.preventDefault(); addFiles(files); }
});
let dragDepth = 0;
document.addEventListener('dragenter', event => { if ([...(event.dataTransfer?.types || [])].includes('Files')) { event.preventDefault(); dragDepth++; document.querySelector('.composer-region').classList.add('dragging'); } });
document.addEventListener('dragover', event => event.preventDefault());
document.addEventListener('dragleave', event => { event.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; document.querySelector('.composer-region').classList.remove('dragging'); } });
document.addEventListener('drop', event => { event.preventDefault(); dragDepth = 0; document.querySelector('.composer-region').classList.remove('dragging'); addFiles(event.dataTransfer.files); });

function richText(value) {
  const lines = String(value).split('\n');
  const inline = text => escapeText(text.trim()).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  const cells = line => line.trim().replace(/^\||\|$/g, '').split('|').map(inline);
  const output = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    if (line.startsWith('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1]) && lines[i + 1].includes('---')) {
      const header = cells(line).map(cell => `<th>${cell}</th>`).join('');
      const rows = []; i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(`<tr>${cells(lines[i]).map(cell => `<td>${cell}</td>`).join('')}</tr>`); i++; }
      i--;
      output.push(`<div class="table-wrap"><table class="answer-table"><thead><tr>${header}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`);
    } else if (/^-{3,}$/.test(line)) {
      output.push('<hr>');
    } else if (/^(?:#{1,4}\s*|【)/.test(line)) {
      output.push(`<h4>${inline(line).replace(/^#{1,4}\s*/, '').replace(/^【|】$/g, '')}</h4>`);
    } else if (/^[-•]\s/.test(line)) {
      output.push(`<p class="list-line">${inline(line).replace(/^[-•]\s*/, '')}</p>`);
    } else { output.push(`<p>${inline(line)}</p>`); }
  }
  return output.join('');
}

function userMessage(message, images) {
  const row = document.createElement('article'); row.className = 'message user';
  if (images.length) {
    const container = document.createElement('div'); container.className = 'user-images';
    images.forEach(item => { const image = document.createElement('img'); image.src = item.data; image.alt = item.name; container.append(image); }); row.append(container);
  }
  if (message) { const text = document.createElement('div'); text.className = 'user-bubble'; text.textContent = message; row.append(text); }
  $('messages').append(row);
}
function pendingMessage() {
  const row = document.createElement('article'); row.className = 'message assistant';
  row.innerHTML = `<div class="message-avatar">${icon('heart')}</div><div class="message-main"><div class="message-label">MediX <small>正在认真听你说</small></div><div class="process"><span class="spinner"></span><span class="phase-label">正在提交问题</span></div><div class="pending-steps"></div></div>`;
  $('messages').append(row); scrollDown(); return row;
}
window.addEventListener('resize', () => document.querySelectorAll('.citation-preview:popover-open').forEach(card => card.hidePopover()));
function citationPreview(trigger, source, quote = '') {
  document.querySelectorAll('.citation-preview').forEach(node => node.remove());
  const card = document.createElement('div'); card.className = 'citation-preview'; card.setAttribute('popover', 'auto'); card.setAttribute('role', 'dialog'); card.setAttribute('aria-label', '引用来源预览');
  const heading = document.createElement('strong'); heading.textContent = source.title;
  const provenance = document.createElement('p'); provenance.className = 'preview-provenance'; provenance.textContent = `${source.publisher || '来源未注明'} · ${source.published_at || '日期未注明'}`;
  const scope = document.createElement('p'); scope.textContent = `${evidenceKindLabels[source.evidence_kind] || '类型未注明'} · ${(source.audiences || ['unspecified']).map(a => audienceLabels[a] || a).join('、')}`;
  const text = document.createElement('blockquote'); text.textContent = quote || source.excerpt || '暂无可定位的原文摘录';
  const note = document.createElement('small'); note.textContent = quote ? '摘录已在本地原文中定位；请核对是否支持这句话。' : '尚未定位到本句的直接摘录，请展开全文核对。';
  const actions = document.createElement('div'); actions.className = 'preview-actions';
  const full = document.createElement('button'); full.type = 'button'; full.textContent = '查看完整片段'; full.onclick = () => { card.hidePopover(); showEvidence(source, quote); }; actions.append(full);
  try { const url = new URL(source.url); if (['https:', 'http:'].includes(url.protocol)) { const link = document.createElement('a'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = '发布机构网页 ↗'; actions.append(link); } } catch {}
  const close = document.createElement('button'); close.type = 'button'; close.textContent = '关闭'; close.onclick = () => { card.hidePopover(); trigger.focus(); }; actions.append(close);
  card.append(heading, provenance, scope, text, note, actions); document.body.append(card); card.showPopover();
  const rect = trigger.getBoundingClientRect(), width = card.offsetWidth, height = card.offsetHeight;
  card.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`;
  card.style.top = `${Math.max(12, Math.min(rect.bottom + 8, innerHeight - height - 12))}px`;
}
function resultMessage(row, result, userText, jobId) {
  const main = row.querySelector('.message-main'); main.replaceChildren();
  const profileNote = document.createElement('p'); profileNote.className = 'profile-reference';
  profileNote.textContent = result.profile_used
    ? `本轮参考本人档案 v${result.profile_revision} · 字段：${(result.profile_fields || []).map(field=>({age:"年龄",sex:"性别",conditions:"病史",allergies:"过敏",medications:"用药",symptoms:"症状",followups:"建议与待核实事项"}[field])).join("、")}（确认于 ${new Date(result.profile_confirmed_at * 1000).toLocaleString()}）。仅作历史背景，现状仍需核对；本轮暂停云端记忆。`
    : '本轮未使用健康档案。';
  if(result.reply_preferences_used){const detail={brief:'简短重点',standard:'适中解释',detailed:'详细说明'}[result.reply_preferences_detail] || '';profileNote.textContent+=result.reply_preferences_status==='applied'?` 已应用回答偏好 v${result.reply_preferences_revision} · ${detail}；本轮暂停云端记忆。`:' 回答偏好整理未完成，已保留原始完整回答；可重新发送。本轮暂停云端记忆。';}

  const label = document.createElement('div'); label.className = 'message-label'; label.innerHTML = `MediX <small>${result.generation === 'not_called' ? '本地证据检索 · 未调用模型' : result.agents.length > 1 ? '多位助手协作完成' : '健康助手完成分析'}</small>`; main.append(label);
  const answer = document.createElement('div'); answer.className = 'answer'; main.append(answer);
  const inline = result.generation === 'model' && result.evidence_links?.length;
  if (inline) {
    const hint = document.createElement('p'); hint.className = 'evidence-hint'; hint.textContent = '点击句旁来源，查看原文摘录与出处。'; answer.append(hint);
    result.evidence_links.forEach(item => {
      const line = document.createElement('p'); line.className = 'grounded-sentence';
      const text = document.createElement('span'); text.textContent = item.text.replace(/\[\d+\]/g, '').trim(); line.append(text);
      item.citations.forEach(id => { const source = result.sources.find(s => s.citation === id); if (!source) return;
        const button = document.createElement('button'); button.type = 'button'; button.className = 'source-pill';
        button.textContent = `${source.publisher || '来源'} · ${id}`; button.setAttribute('aria-label', `查看本句来源 ${id}：${source.title}`); button.setAttribute('aria-haspopup', 'dialog');
        button.onclick = () => citationPreview(button, source, item.quotes.find(q => q.citation === id)?.quote || ''); line.append(button); });
      if (!item.citations.length) { const note = document.createElement('small'); note.className = 'sentence-caution'; note.textContent = '本句未附引用'; line.append(note); }
      answer.append(line);
    });
  } else answer.innerHTML = richText(result.answer);
  if (result.retrieval) {
    if (!inline) {
      answer.innerHTML = answer.innerHTML.replace(/\[(\d+)\]/g, (match, n) => result.sources.some(s => s.citation === Number(n)) ? `<button type="button" class="citation" data-citation="${n}" aria-label="查看证据 ${n}">[${n}]</button>` : match);
      answer.querySelectorAll('[data-citation]').forEach(button => button.onclick = () => citationPreview(button, result.sources.find(s => s.citation === Number(button.dataset.citation))));
    }
  }
  const meta = document.createElement('div'); meta.className = 'message-meta';
  const tags = [result.generation === 'not_called' ? '仅检索原文' : result.llm_requests === 1 ? '单次模型请求 · 原文定位' : result.agents.length > 1 ? `${result.agents.length} 位助手协作` : '单助手分析', ...(result.image_count ? [`已读取 ${result.image_count} 张图片`] : []), ...(result.image_context_used ? ['沿用本轮图片信息'] : []), ...(result.memory_enabled ? ['长期记忆已启用'] : []), ...(result.partial ? ['部分任务超时'] : [])];
  tags.forEach(text => { const tag = document.createElement('span'); tag.className = 'meta-pill'; tag.textContent = text; meta.append(tag); });
  const elapsed = document.createElement('span'); elapsed.textContent = `${result.elapsed} 秒`; meta.append(elapsed); main.append(meta);
  if (result.image_observations) {
    const block = document.createElement('details'); block.className = 'observations';
    const summary = document.createElement('summary'); summary.textContent = '查看图片中实际读取的信息';
    const text = document.createElement('pre'); text.textContent = result.image_observations; block.append(summary, text); main.append(block);
  }
  if (result.sources.length) {
    const block = document.createElement('details'); block.className = 'sources'; block.open = !result.retrieval;
    const summary = document.createElement('summary'); summary.textContent = `全部检索片段 · ${result.sources.length} 个（含可能未引用的片段）`;
    const grid = document.createElement('div'); grid.className = 'source-grid';
    result.sources.forEach(source => {
      const card = document.createElement(source.content ? 'button' : 'div'); card.className = 'source-card';
      if (source.content) { card.type = 'button'; card.onclick = () => showEvidence(source); }
      const title = document.createElement('strong'); title.textContent = source.title.trim().length < 3 ? '本地医学资料片段' : source.title;
      const file = document.createElement('small'); file.textContent = source.publisher ? `[${source.citation}] ${source.publisher} · ${source.published_at || '日期未注明'} · 查看原文 ↗` : source.file;
      const excerpt = document.createElement('p'); excerpt.textContent = source.excerpt; card.append(title, file, excerpt); grid.append(card);
    }); block.append(summary, grid); main.append(block);
  }
  if (result.tools.length) {
    const chips = document.createElement('div'); chips.className = 'pending-steps';
    [...new Set(result.tools.map(tool => `${tool.status === 'failed' ? '未完成 · ' : '✓ '}${tool.label}`))].forEach(text => { const chip = document.createElement('span'); chip.className = 'step-chip'; chip.textContent = text; chips.append(chip); }); main.append(chips);
  }
  const actions=document.createElement('section');actions.className='answer-profile-actions';actions.setAttribute('aria-label','本轮回答后续操作');
  const actionRow=document.createElement('div');actionRow.className='answer-profile-action-row';
  const copy=document.createElement('div'),title=document.createElement('strong'),hint=document.createElement('p');
  title.textContent='把有用的信息留在健康档案';hint.textContent='整理本轮内容，逐项选择；保存前由你确认。';copy.append(title,hint);
  const pickerSlot=document.createElement('div');pickerSlot.className='answer-profile-picker-slot';
  const update=document.createElement('button');update.type='button';update.className='answer-profile-save';update.textContent='选择加入健康档案';
  update.onclick=()=>{let picker=pickerSlot.querySelector('.conversation-profile-picker');if(!picker)picker=window.MedixInlineProfilePicker?.(pickerSlot,userText,jobId);picker?.scrollIntoView({behavior:'smooth',block:'nearest'});};
  actionRow.append(copy,update);actions.append(actionRow,pickerSlot);
  const reference=document.createElement('details');reference.className='answer-profile-reference';
  const referenceTitle=document.createElement('summary');referenceTitle.textContent=[result.profile_used?'本轮已参考健康档案':'本轮未使用健康档案',result.reply_preferences_used?(result.reply_preferences_status==='applied'?'回答偏好已应用':'回答偏好整理未完成'):''].filter(Boolean).join(' · ')+' · 查看说明';
  reference.open=Boolean(result.reply_preferences_used && result.reply_preferences_status!=='applied');
  reference.append(referenceTitle,profileNote);actions.append(reference);main.append(actions);
  scrollDown();
}
async function submit(message, images, retryRow) {
  if (!await MedixAuth.requireLogin()) return;
  if (state.busy) return;
  let profileChoice;
  try { profileChoice = window.MedixProfile?.choice() || {use_profile:false}; }
  catch (error) { toast(error.message); return; }
  const epoch = authEpoch;
  state.busy = true; updateComposer();
  closeSidebar();
  document.body.classList.add('chatting');
  $('welcome').hidden = true; $('messages').classList.add('active');
  if (!retryRow) { userMessage(message, images); if (!state.count++) $('chatTitle').textContent = (message || '图片解读').slice(0, 18); }
  const row = retryRow || pendingMessage();
  try {
    const response = await MedixAuth.fetch('/api/chat', {method:'POST', body:JSON.stringify({chat_id:state.chatId, message, images, remember:$('remember').checked, ...profileChoice})});
    const data = await response.json();
    if (epoch !== authEpoch) return;
    if (!response.ok) throw new Error(data.detail || '问题提交失败，请重试。');
    $('message').value = ''; state.images = []; renderAttachments();
    let errors = 0;
    for (;;) {
      await sleep(1100);
      if (epoch !== authEpoch) return;
      let status;
      try {
        const poll = await MedixAuth.fetch(`/api/jobs/${data.job_id}`);
        const body = await poll.json();
        if (epoch !== authEpoch) return;
        if (!poll.ok) throw new Error(body.detail || '无法读取分析状态。');
        status = body; errors = 0;
      } catch (error) { if (++errors < 4) continue; throw error; }
      row.querySelector('.phase-label').textContent = status.label;
      const chips = row.querySelector('.pending-steps'); chips.replaceChildren();
      status.steps.forEach((step, i) => { const chip = document.createElement('span'); chip.className = 'step-chip'; chip.textContent = `${i < status.steps.length - 1 ? '✓ ' : ''}${step.label.replace('正在', '')}`; chips.append(chip); });
      if (status.status === 'completed') { resultMessage(row, status.result, message, data.job_id); break; }
      if (status.status === 'failed') throw new Error(status.error || '分析未能完成，请稍后重试。');
    }
  } catch (error) {
    if (epoch !== authEpoch) return;
    const main = row.querySelector('.message-main'); main.replaceChildren();
    const text = document.createElement('div'); text.className = 'error-text'; text.textContent = error.message;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'retry-button'; button.textContent = '重新分析'; button.onclick = () => { row.remove(); submit(message, images, pendingMessage()); };
    main.append(text, button); scrollDown();
  } finally { if (epoch === authEpoch) { state.busy = false; updateComposer(); $('message').focus(); } }
}
$('chatForm').onsubmit = event => { event.preventDefault(); submit($('message').value.trim(), [...state.images]); };
$('newChat').onclick = () => { if (state.busy) return; state.chatId = crypto.randomUUID(); state.images = []; state.count = 0; $('messages').replaceChildren(); $('messages').classList.remove('active'); $('welcome').hidden = false; $('chatTitle').textContent = '新的健康对话'; $('message').value = ''; document.body.classList.remove('chatting'); closeSidebar(); renderAttachments(); $('conversation').scrollTop = 0; $('message').focus(); };
document.querySelectorAll('[data-example]').forEach(button => button.onclick = async () => {
  if (state.busy) return;
  const example = button.dataset.example;
  const prompts = {knowledge:'高血压的日常饮食和运动管理，需要注意哪些事情？请结合知识库简要说明。',swarm:'虚构案例：35岁男性，持续头痛、头晕、恶心一周，有高血压史。请分别分析症状风险与日常管理建议，简要回答。',followup:'多喝水对健康有哪些帮助？请简要说明。',report:'这是虚构的血压记录示例。请准确读出图片中的三次记录，并说明还需要了解哪些信息。'};
  if (example === 'report') {
    try { const response = await fetch('/assets/demo-report.png'); if (!response.ok) throw new Error(); const blob = await response.blob(); await addFiles([new File([blob], '演示血压记录（虚构）.png', {type:'image/png'})]); }
    catch { toast('示例图片暂不可用，你仍可以上传自己的图片。'); return; }
  }
  $('message').value = prompts[example]; updateComposer(); $('message').focus();
});
async function refreshHealth() {
  try {
    const response = await fetch('/api/health'); if (!response.ok) throw new Error(); const data = await response.json(); state.health = data;
    $('modelState').textContent = data.model_configured ? '已配置' : '待配置'; $('modelDot').className = `status-dot ${data.model_configured ? 'ready' : 'error'}`;
    $('kbState').textContent = data.knowledge === 'ready' ? `${data.documents} 个片段` : data.knowledge === 'error' ? '初始化失败' : '准备中'; $('kbDot').className = `status-dot ${data.knowledge === 'ready' ? 'ready' : data.knowledge === 'error' ? 'error' : ''}`;
    if (!data.memory_configured) $('memoryHelp').textContent = '服务端未配置 Mem0 Key，当前仅使用本次对话的上下文。'; updateComposer();
    if (data.knowledge === 'loading') setTimeout(refreshHealth, 3000);
  } catch { $('modelState').textContent = '服务未连接'; $('modelDot').className = 'status-dot error'; setTimeout(refreshHealth, 5000); }
}
refreshHealth();

// The redesigned entry points all use the existing upload and chat pipeline.
function closeSidebar() {
  window.dispatchEvent(new Event('medix-sidebar-close'));
  $('sidebar').classList.remove('open');
  $('sidebarBackdrop').hidden = true;
  $('menuButton').setAttribute('aria-expanded', 'false');
  $('sidebar').inert = window.matchMedia('(max-width: 800px)').matches;
}
$('menuButton').onclick = () => {
  const open = !$('sidebar').classList.contains('open');
  $('sidebar').classList.toggle('open', open);
  $('sidebarBackdrop').hidden = !open;
  $('menuButton').setAttribute('aria-expanded', String(open));
  $('sidebar').inert = !open;
};
$('sidebarBackdrop').onclick = closeSidebar;
const mobileLayout = window.matchMedia('(max-width: 800px)');
mobileLayout.addEventListener('change', closeSidebar);
closeSidebar();
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeSidebar(); });
$('chatNav').onclick = () => { closeSidebar(); $('message').focus(); };
function fillQuestion(text) {
  if (state.busy) return;
  $('message').value = text;
  updateComposer();
  closeSidebar();
  $('message').focus();
}
document.querySelectorAll('[data-prompt]').forEach(button => button.onclick = () => {
  const prompts = {
    symptom: '我最近有些不舒服。请先问我症状、持续时间和相关情况，帮我一起梳理需要关注的信息。',
    medicine: '我有一个用药疑问。请先确认药品名称、剂量、服用目的和我的相关情况，再帮我了解注意事项。'
  };
  fillQuestion(prompts[button.dataset.prompt]);
});
document.querySelectorAll('[data-action]').forEach(button => button.onclick = () => {
  const action = button.dataset.action;
  closeSidebar();
  if (action === 'upload') {
    if (state.busy) return;
    if (!$('message').value.trim()) fillQuestion('请帮我读懂这张报告，准确说明可见的指标、单位，以及还需要补充哪些信息。');
    $('fileInput').click();
    return;
  }
  if (action === 'knowledge') {
    if (state.health?.mode === 'evidence') { openKnowledge(); return; }
    $('dialogTitle').textContent = '回答背后的医学资料';
    const count = Number(state.health?.documents || 0);
    $('dialogContent').innerHTML = `<p>提问时，MediX 会检索项目自带的本地医学知识库，帮助你理解相关信息。</p><div class="dialog-stat"><b>${count}</b> 个已加载资料片段</div><p><strong>涵盖方向</strong><br>常见健康问题、生活方式、疾病编码与临床指南类资料。</p><p><strong>怎样查看来源？</strong><br>回答下方的「本地检索参考」会展示实际检索到的文件名及原文片段。</p><p>本地内容尚未完成权威性与时效性审核，请结合医生意见核实。</p>`;
  } else {
    $('dialogTitle').textContent = '把健康问题，说给我听';
    $('dialogContent').innerHTML = '<p><strong>01 · 描述你的问题</strong><br>可以说说具体症状、持续时间和已经了解的情况。不确定怎么描述，也可以直接问。</p><p><strong>02 · 图片也能一起问</strong><br>上传清晰的报告、药盒或记录；支持粘贴和拖入图片。最多 3 张，每张不超过 8 MB，支持 JPG、PNG、WebP。</p><p><strong>03 · 接着聊，不必重复</strong><br>可根据本轮图片继续追问。开启新对话会重置本轮上下文；刷新页面不会保留聊天记录。</p><p>默认关闭长期记忆。开启后，对话和图片解读摘要会发送至 Mem0，供后续会话检索。</p>';
  }
  $('infoDialog').showModal();
});
$('closeDialog').onclick = $('dialogDone').onclick = () => $('infoDialog').close();
$('infoDialog').addEventListener('click', event => {
  if (event.target !== $('infoDialog')) return;
  const bounds = $('infoDialog').getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $('infoDialog').close();
});
const questionGroups = [
  [['最近总是睡不好，怎么办？', '最近总是睡不好，应该先观察和记录哪些情况？'], ['体检报告里的箭头怎么看？', '体检报告中的箭头代表什么？读报告时需要关注哪些信息？'], ['久坐后肩颈不舒服', '久坐后肩颈不舒服，日常可以怎样调整习惯？']],
  [['日常怎样记录家庭血压？', '做家庭血压记录时，应该记录哪些信息、怎样保持测量条件一致？'], ['开始运动前要准备什么？', '平时运动较少，开始规律运动前需要了解哪些自身情况？'], ['看诊前带上哪些信息？', '第一次因为身体不适去看医生，应该准备哪些记录和资料？']],
  [['饮食管理可以从哪里开始？', '想改善日常饮食习惯，应该先记录和了解哪些情况？'], ['怎样问清楚用药疑问？', '向医生或药师咨询用药时，需要提供哪些药品和个人情况？'], ['让多位助手一起分析', '虚构案例：35岁男性，有高血压史，持续头痛、头晕、恶心一周。请分别从症状风险和日常管理角度分析，由专业助手协作，简要回答。']]
];
let questionGroup = 0;
$('questionChips').onclick = event => {
  const button = event.target.closest('[data-question]');
  if (button) fillQuestion(button.dataset.question);
};

const audienceLabels = {general:'一般健康科普',adults:'成人',children:'儿童',older_adults:'老年人',pregnancy_lactation:'孕哺期',unspecified:'人群未注明'};
const evidenceKindLabels = {popular_science:'健康科普，非核准药品说明书',clinical_guideline:'指南或专业规范（请核对版本）'};
function showEvidence(source, quote = '') {
  if (!source) return;
  $('dialogTitle').textContent = source.title;
  const content = $('dialogContent'); content.replaceChildren();
  const provenance = document.createElement('p'); provenance.textContent = `${source.publisher} · ${source.published_at || '日期未注明'}\n来源已核对（机构、链接与原文），未作临床审核。`;
  const section = document.createElement('p'); section.textContent = `章节：${source.section} · 本地原文字符位置：${source.start_char}`;
  const audience = document.createElement('p'); audience.textContent = `资料类型：${evidenceKindLabels[source.evidence_kind] || source.evidence_kind || '未注明'}。适用范围：${(source.audiences || ['unspecified']).map(a => audienceLabels[a] || a).join('、')}。${source.applicability === 'needs_confirmation' ? '当前未确认提问者是否属于该人群，请核对后使用。' : '范围标签仅说明原文主题，不代表个人适用性确认。'}`;
  const excerpt = document.createElement('pre'); excerpt.className = 'evidence-text';
  const terms = (quote ? [quote] : source.highlight_terms || []).filter(t => t.length >= 2);
  if (terms.length) {
    const pattern = new RegExp(`(${terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
    String(source.content).split(pattern).forEach(part => { const node = document.createElement(terms.includes(part) ? 'mark' : 'span'); node.textContent = part; excerpt.append(node); });
  } else excerpt.textContent = source.content;
  const link = document.createElement('a'); link.textContent = '查看机构发布页面 ↗';
  try { const url = new URL(source.url); if (['https:', 'http:'].includes(url.protocol)) link.href = url.href; } catch {}
  link.target = '_blank'; link.rel = 'noopener noreferrer';
  const version = document.createElement('small'); version.textContent = `来源快照 SHA-256：${source.content_sha256}`;
  content.append(provenance, audience, section, excerpt, link, document.createElement('hr'), version);
  if (!$('infoDialog').open) $('infoDialog').showModal();
  if (quote) requestAnimationFrame(() => excerpt.querySelector('mark')?.scrollIntoView({block:'center'}));
}
async function openKnowledge() {
  $('dialogTitle').textContent = '医学证据库';
  const content = $('dialogContent'); content.innerHTML = '<p>检索常见病与基础用药科普，点击证据查看出处。当前资料不等于完整药品说明书或最新临床指南。</p><form id="evidenceForm" class="evidence-search"><label for="evidenceQuery">查找问题或药品</label><input id="evidenceQuery" maxlength="8000" required placeholder="例如：口服补液盐有哪些使用误区？"><button class="dialog-done" type="submit">查找证据</button></form><div id="evidenceResults" aria-live="polite"></div><details><summary>查看收录来源</summary><div id="sourceCatalog">正在加载来源…</div></details>';
  if (!$('infoDialog').open) $('infoDialog').showModal();
  const results = $('evidenceResults'), catalogNode = $('sourceCatalog');
  $('evidenceForm').onsubmit = async event => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true; results.textContent = '正在检索本地资料…';
    try {
      const response = await fetch('/api/knowledge/retrieve?q=' + encodeURIComponent($('evidenceQuery').value));
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || '检索失败');
      results.replaceChildren(); if (data.message) { const p = document.createElement('p'); p.textContent = data.message; results.append(p); }
      data.sources.forEach(source => { const card = document.createElement('button'); card.type = 'button'; card.className = 'source-card evidence-hit';
        const title = document.createElement('strong'); title.textContent = `[${source.citation}] ${source.title}`;
        const excerpt = document.createElement('p'); excerpt.textContent = source.excerpt;
        card.append(title, excerpt); card.onclick = () => showEvidence(source); results.append(card); });
    } catch (error) { results.textContent = error.message; } finally { button.disabled = false; }
  };
  try {
    const response = await fetch('/api/knowledge/catalog'); const data = await response.json(); if (!response.ok) throw new Error(data.detail);
    catalogNode.replaceChildren();
    const count = document.createElement('p'); count.textContent = `${data.documents.length} 份来源 · ${data.chunks} 个独立片段 · 版本 ${data.version}`; catalogNode.append(count);
    data.documents.forEach(doc => { const p = document.createElement('p'); p.textContent = `${doc.title}｜${doc.publisher}｜${doc.published_at || '日期未注明'}｜${(doc.audiences || ['unspecified']).map(a => audienceLabels[a] || a).join('、')}｜${evidenceKindLabels[doc.evidence_kind] || '类型未注明'}`; catalogNode.append(p); });
  } catch (error) { catalogNode.textContent = error.message; }
  try {
    const response = await fetch('/api/knowledge/explore'); if (!response.ok) return; const data = await response.json();
    if (!data.questions.length) return;
    const section = document.createElement('details'); const title = document.createElement('summary'); title.textContent = '中文开源问法探索（非证据）'; section.append(title);
    const note = document.createElement('p'); note.textContent = '以下问题取自开源问答样本，仅用于探索；答案仍需检索原文。点击只填入检索框，不调用聊天模型。'; section.append(note);
    data.questions.slice(0,12).forEach(item => { const p = document.createElement('p'); const button = document.createElement('button'); button.type = 'button'; button.textContent = item.question;
      button.onclick = () => { $('evidenceQuery').value = item.question; $('evidenceQuery').focus(); }; p.append(button); section.append(p); });
    const datasets = document.createElement('p'); datasets.textContent = data.datasets.map(d => `${d.id}：${d.selected_rows} 条，${d.use === 'question_exploration_only' ? '问法探索' : '独立评测'}`).join('；'); section.append(datasets); content.append(section);
  } catch {}
}
$('refreshPrompts').onclick = () => {
  questionGroup = (questionGroup + 1) % questionGroups.length;
  $('questionChips').replaceChildren();
  questionGroups[questionGroup].forEach(([label, question]) => {
    const button = document.createElement('button');
    button.type = 'button'; button.dataset.question = question;
    button.textContent = label;
    const arrow = document.createElement('span'); arrow.textContent = '↗'; button.append(arrow);
    $('questionChips').append(button);
  });
};

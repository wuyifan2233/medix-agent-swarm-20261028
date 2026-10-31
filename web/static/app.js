const $ = (id) => document.getElementById(id);
const state = {demo:false, chatId: crypto.randomUUID(), images: [], busy: false, health: null, count: 0,
  voice: {mode:null, recognition:null, recorder:null, stream:null, chunks:[], startedAt:0, timer:null, stopping:false, abortController:null},
  audio:null, speechAbort:null, speakingButton:null, speechToken:0
};
let authEpoch = 0;
window.addEventListener('medix-signout', () => {
  state.eventSource?.close(); state.eventSource=null; state.jobId=null; $('conversationList').replaceChildren();
  authEpoch++; cancelVoiceInput(); stopSpeaking(); state.busy = false; state.images = []; state.chatId = crypto.randomUUID(); state.count = 0;
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
state.caseId = '';
async function refreshCases(selected = state.caseId) {
  await MedixAuth.ready;
  if (!MedixAuth.user) return;
  const owner=MedixAuth.user.id;
  const response = await MedixAuth.fetch('/api/cases');
  if (!response.ok) return;
  const data = await response.json();
  if (MedixAuth.user?.id !== owner) return;
  $('caseContext').replaceChildren(new Option('新对话，不关联历史',''));
  data.cases.forEach(item => $('caseContext').add(new Option(`${item.name} · ${item.records} 条记录`,item.id)));
  $('caseContext').value=selected;
}
const icon = (id) => `<svg aria-hidden="true"><use href="#i-${id}"/></svg>`;
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const escapeText = (value) => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
function toast(message) { $('toast').textContent = message; $('toast').classList.add('show'); clearTimeout(state.toast); state.toast = setTimeout(() => $('toast').classList.remove('show'), 4200); }
function scrollDown() { $('conversation').scrollTop = $('conversation').scrollHeight; }
function updateComposer() {
  const blocked=state.busy || state.opening;
  window.MedixProfile?.setBusy(blocked);
  $('sendButton').disabled = blocked || (!$('message').value.trim() && !state.images.length);
  $('attachButton').disabled = blocked;
  $('message').disabled = blocked;
  $('newChat').disabled = blocked;
  $('stopGeneration').hidden = !state.busy;
  $('stopGeneration').disabled = !state.jobId;
  document.querySelectorAll('.session-more,.session-menu-panel button').forEach(button=>button.disabled=blocked);
  document.querySelectorAll('[data-action="upload"], [data-prompt], [data-example], #refreshPrompts').forEach(button => { button.disabled = blocked; });
  $('remember').disabled = blocked || !MedixAuth.user || !state.health?.memory_configured;
  $('voiceButton').disabled = blocked || Boolean(state.voice.mode);
  $('autoSpeak').disabled = blocked;
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
function voiceSupported() {
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition ||
    (state.health?.speech_api_configured && navigator.mediaDevices && window.MediaRecorder));
}
function getAutoSpeakPreference() {
  try {
    const preference = localStorage.getItem('medix-auto-speak');
    return preference === null ? true : preference === 'true';
  } catch { return true; }
}
function setAutoSpeakPreference(enabled) {
  try { localStorage.setItem('medix-auto-speak', String(enabled)); } catch { /* Storage may be disabled in private contexts. */ }
}
function setVoicePanel(open) {
  $('voicePanel').hidden = !open;
  $('voiceButton').setAttribute('aria-pressed', String(open));
  if (!open) {
    $('voiceRecordActions').hidden = false;
    $('voiceWave').hidden = false;
  }
}
function stopVoiceTracks() {
  if (state.voice.stream) state.voice.stream.getTracks().forEach(track => track.stop());
  state.voice.stream = null;
}
function clearVoiceTimer() {
  if (state.voice.timer) clearInterval(state.voice.timer);
  state.voice.timer = null;
}
function resetVoiceState() {
  const previousVoice = state.voice;
  if (previousVoice.abortController) previousVoice.abortController.abort();
  clearVoiceTimer();
  stopVoiceTracks();
  state.voice = {mode: null, recognition: null, recorder: null, stream: null, chunks: [], startedAt: 0, timer: null, stopping: false, cancelled: false, finalText: '', interimText: '', abortController: null};
  setVoicePanel(false);
  updateComposer();
}
function updateVoiceElapsed() {
  if (!state.voice.startedAt) return;
  const seconds = Math.max(0, Math.floor((Date.now() - state.voice.startedAt) / 1000));
  $('voiceElapsed').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  if (seconds >= 90 && ['browser', 'recorder'].includes(state.voice.mode)) {
    $('voiceStatus').textContent = '已达到 90 秒时长上限，正在整理文字…';
    stopVoiceInput();
  }
}
function beginVoiceUi(title, status) {
  setVoicePanel(true);
  $('voiceTitle').textContent = title;
  $('voiceStatus').textContent = status;
  $('voiceRecordActions').hidden = false;
  $('voiceWave').hidden = false;
  state.voice.startedAt = Date.now();
  updateVoiceElapsed();
  clearVoiceTimer();
  state.voice.timer = setInterval(updateVoiceElapsed, 500);
  updateComposer();
}
function insertVoiceTranscript(text) {
  const transcript = String(text || '').trim();
  if (!transcript) return;
  clearVoiceTimer();
  stopVoiceTracks();
  const input = $('message');
  const draft = input.value;
  const separator = draft && !/\s$/.test(draft) ? '\n' : '';
  input.value = `${draft}${separator}${transcript}`.slice(0, 8000);
  resetVoiceState();
  updateComposer();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  input.classList.remove('transcript-added');
  void input.offsetWidth;
  input.classList.add('transcript-added');
  setTimeout(() => input.classList.remove('transcript-added'), 1100);
}
function startBrowserRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new Recognition();
  state.voice.mode = 'browser';
  state.voice.recognition = recognition;
  setVoicePanel(true);
  $('voiceTitle').textContent = '准备听写';
  $('voiceStatus').textContent = '等待浏览器麦克风权限';
  updateComposer();
  state.voice.finalText = '';
  const session = state.voice;
  recognition.lang = 'zh-CN';
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  recognition.onstart = () => { if (state.voice === session) beginVoiceUi('正在听你说', '说完后点击结束录音'); };
  recognition.onresult = event => {
    if (state.voice !== session) return;
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const chunk = event.results[i][0]?.transcript || '';
      if (event.results[i].isFinal) session.finalText += chunk;
      else interim += chunk;
    }
    $('voiceStatus').textContent = '正在识别';
    session.interimText = interim;
  };
  recognition.onerror = event => {
    if (state.voice !== session || event.error === 'aborted' || session.stopping || session.cancelled) return;
    const canUseAudioApi = state.health?.speech_api_configured && ['network', 'service-not-allowed'].includes(event.error);
    resetVoiceState();
    if (canUseAudioApi) { toast('浏览器听写暂不可用，已切换到录音识别。'); startRecorderFallback(); }
    else toast(event.error === 'not-allowed' ? '麦克风权限被拒绝，请允许浏览器使用麦克风。' : '浏览器听写没有完成，请重试或改用文字输入。');
  };
  recognition.onend = () => {
    if (state.voice !== session) return;
    const text = `${session.finalText || ''} ${session.interimText || ''}`.trim();
    if (session.cancelled) return resetVoiceState();
    if (!session.stopping) session.stopping = true;
    if (text) insertVoiceTranscript(text);
    else { resetVoiceState(); toast('没有识别到清晰语音，请再试一次。'); }
  };
  try { recognition.start(); }
  catch { resetVoiceState(); toast('语音输入暂时无法启动，请重试。'); }
}
async function startRecorderFallback() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    toast('当前浏览器不支持语音输入，请使用 Chrome 或 Edge，或直接输入文字。');
    return;
  }
  if (!state.health?.speech_api_configured) {
    toast('当前浏览器不支持原生听写，且服务端 ASR 未配置；请使用 Chrome/Edge 或直接输入文字。');
    return;
  }
  const recordingSession = state.voice;
  recordingSession.mode = 'requesting-mic';
  beginVoiceUi('等待麦克风权限', '请允许使用麦克风');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    if (state.voice !== recordingSession || recordingSession.cancelled) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type)) || '';
    const recorder = new MediaRecorder(stream, mime ? {mimeType: mime} : undefined);
    recordingSession.mode = 'recorder'; recordingSession.recorder = recorder; recordingSession.stream = stream; recordingSession.chunks = [];
    recorder.ondataavailable = event => { if (event.data.size && state.voice === recordingSession) recordingSession.chunks.push(event.data); };
    recorder.onstop = async () => {
      if (state.voice !== recordingSession) return;
      const cancelled = recordingSession.cancelled;
      const blob = new Blob(recordingSession.chunks, {type: recorder.mimeType || 'audio/webm'});
      recordingSession.chunks = [];
      stopVoiceTracks(); clearVoiceTimer();
      if (cancelled) return resetVoiceState();
      recordingSession.mode = 'uploading'; $('voiceTitle').textContent = '正在转成文字'; $('voiceStatus').textContent = '音频发送至已配置的识别服务；不会保存在 MediX'; $('voiceRecordActions').hidden = true;
      try {
        const abortController = new AbortController();
        recordingSession.abortController = abortController;
        const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(blob); });
        if (state.voice !== recordingSession) return;
        const response = await MedixAuth.fetch('/api/voice/transcribe', {method:'POST', body:JSON.stringify({audio:encoded, content_type:blob.type || 'audio/webm'}), signal:abortController.signal});
        const data = await response.json();
        if (state.voice !== recordingSession) return;
        recordingSession.abortController = null;
        if (!response.ok) throw new Error(data.detail || '语音识别暂时不可用。');
        if (!data.text?.trim()) throw new Error('没有识别出清晰语音，请重试。');
        insertVoiceTranscript(data.text);
      } catch (error) { if (state.voice === recordingSession) { resetVoiceState(); if (error.name !== 'AbortError') toast(error.message); } }
    };
    recorder.start(250);
    beginVoiceUi('正在录音', '说完后点击结束录音');
  } catch { if (state.voice === recordingSession) resetVoiceState(); toast('无法访问麦克风，请检查浏览器权限。'); }
}
function startVoiceInput() {
  if (state.busy || state.voice.mode) return;
  if (!voiceSupported()) { toast('当前浏览器不支持语音输入，请使用 Chrome 或 Edge，或直接输入文字。'); return; }
  if (window.SpeechRecognition || window.webkitSpeechRecognition) startBrowserRecognition();
  else startRecorderFallback();
}
function stopVoiceInput() {
  if (state.voice.mode === 'requesting-mic') {
    state.voice.cancelled = true; resetVoiceState(); return;
  }
  if (state.voice.mode === 'browser' && state.voice.recognition) {
    if (state.voice.stopping) return;
    state.voice.stopping = true; $('voiceStatus').textContent = '正在整理文字…'; state.voice.recognition.stop();
  } else if (state.voice.mode === 'recorder' && state.voice.recorder) {
    if (state.voice.stopping) return;
    state.voice.stopping = true; $('voiceStatus').textContent = '正在整理录音…'; state.voice.recorder.stop();
  }
}
function cancelVoiceInput() {
  const voice = state.voice;
  voice.cancelled = true;
  if (voice.abortController) { voice.abortController.abort(); resetVoiceState(); return; }
  if (voice.recognition) { try { voice.recognition.abort(); } catch {} resetVoiceState(); return; }
  if (voice.recorder && voice.recorder.state !== 'inactive') { try { voice.recorder.stop(); return; } catch {} }
  resetVoiceState();
}
function retryVoiceInput() { cancelVoiceInput(); setTimeout(startVoiceInput, 80); }
$('attachButton').onclick = () => $('fileInput').click();
$('fileInput').onchange = (event) => { addFiles(event.target.files); event.target.value = ''; };
$('voiceButton').onclick = startVoiceInput;
$('stopVoice').onclick = stopVoiceInput;
$('cancelVoice').onclick = cancelVoiceInput;
$('message').oninput = updateComposer;
$('autoSpeak').checked = getAutoSpeakPreference();
$('autoSpeak').onchange = () => { setAutoSpeakPreference($('autoSpeak').checked); };

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

function speechSafeText(value) {
  return String(value || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^\s*\|.*\|\s*$/gm, ' ')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[>*_`#]/g, '')
    .replace(/\[([^\]]+\.pdf)\]/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
}
function stopSpeaking() {
  state.speechToken++;
  state.speechAbort?.abort(); state.speechAbort = null;
  if (state.audio) {
    const audio = state.audio; state.audio = null;
    audio.onended = null; audio.onerror = null; audio.onplaying = null; audio.onwaiting = null;
    audio.pause(); audio.removeAttribute('src'); audio.load();
  }
  if (state.speakingButton) {
    state.speakingButton.classList.remove('speaking');
    state.speakingButton.setAttribute('aria-pressed', 'false');
    state.speakingButton.innerHTML = `${icon('volume')}<span>${state.speakingIdleLabel || '朗读'}</span>`;
    state.speakingButton = null;
  }
}
async function speakAnswer(answer, button, preview = null) {
  if (state.speakingButton) { const sameButton = state.speakingButton === button; stopSpeaking(); if (sameButton) return; }
  const text = speechSafeText(answer);
  if (!text) return;
  const token = ++state.speechToken;
  const controller = new AbortController(); state.speechAbort = controller;
  state.speakingIdleLabel = preview ? '试听当前声音' : '朗读';
  state.speakingButton = button; button.classList.add('speaking'); button.setAttribute('aria-pressed', 'true');
  button.innerHTML = `${icon('stop')}<span>连接中 · 停止</span>`;
  try {
    const response = await MedixAuth.fetch(preview ? '/api/voice/speech/preview' : '/api/voice/speech/prepare', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(preview || {text}), signal: controller.signal
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || '云端语音生成失败，请重新朗读。');
    }
    const prepared = await response.json();
    if (state.speechToken !== token) return;
    if (!/^\/api\/voice\/speech\/stream\/[a-f0-9]{32}$/.test(prepared.url || '')) throw new Error('音频地址无效，请重新朗读。');
    if (prepared.voice?.label) button.title = `当前声音：${prepared.voice.label}`;
    state.speechAbort = null;
    // Native Audio progressively decodes the HTTP MP3 stream; no response.blob().
    const audio = new Audio(); state.audio = audio;
    audio.preload = 'auto';
    audio.onplaying = () => {
      if (state.speechToken === token) button.innerHTML = `${icon('stop')}<span>停止</span>`;
    };
    audio.onwaiting = () => {
      if (state.speechToken === token) button.innerHTML = `${icon('stop')}<span>缓冲中 · 停止</span>`;
    };
    audio.onended = () => { if (state.speechToken === token) stopSpeaking(); };
    audio.onerror = () => {
      if (state.speechToken !== token) return;
      stopSpeaking(); toast('云端语音连接中断或音频不可用，请重新朗读。');
    };
    audio.src = prepared.url;
    button.innerHTML = `${icon('stop')}<span>生成中 · 停止</span>`;
    await audio.play();
  } catch (error) {
    if (state.speechToken !== token) return;
    stopSpeaking();
    if (error.name !== 'AbortError') toast(error.name === 'NotAllowedError'
      ? '浏览器暂未允许自动播放，请点击回答下的朗读按钮。'
      : (error.message || '云端语音暂时不可用，请重新朗读。'));
  }
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
  if (result.case_id) {state.caseId=result.case_id; refreshCases().catch(()=>{});}
  if (result.case_changes?.length) {
    document.querySelectorAll('.message.assistant').forEach(previous => {
      if (previous === row || !previous.caseRefs || previous.dataset.caseStale) return;
      if (result.case_changes.some(change => previous.caseRefs.some(ref=>ref.id===change.id && ref.revision<change.revision))) {
        const note=document.createElement('p');note.className='case-update-note';note.textContent='这条回答引用的病例信息已更新，请以最新回复为准。';
        previous.querySelector('.message-main').prepend(note);previous.dataset.caseStale='true';
      }
    });
  }
  row.caseRefs=result.case_sources || [];

  const main = row.querySelector('.message-main'); main.replaceChildren();
  const profileNote = document.createElement('p'); profileNote.className = 'profile-reference';
  profileNote.textContent = result.profile_used
    ? `本轮参考本人档案 v${result.profile_revision} · 字段：${(result.profile_fields || []).map(field=>({age:"年龄",sex:"性别",conditions:"病史",allergies:"过敏",medications:"用药",symptoms:"症状",followups:"建议与待核实事项"}[field])).join("、")}（确认于 ${new Date(result.profile_confirmed_at * 1000).toLocaleString()}）。仅作历史背景，现状仍需核对；本轮暂停云端记忆。`
    : '本轮未使用健康档案。';
  if(result.reply_preferences_used){const detail={brief:'简短重点',standard:'适中解释',detailed:'详细说明'}[result.reply_preferences_detail] || '';profileNote.textContent+=result.reply_preferences_status==='applied'?` 已应用回答偏好 v${result.reply_preferences_revision} · ${detail}；本轮暂停云端记忆。`:' 回答偏好整理未完成，已保留原始完整回答；可重新发送。本轮暂停云端记忆。';}

  const names=participatingAssistants(result.usage?.calls,result.agents || []);
  const label = document.createElement('div'); label.className = 'message-label';
  const labelText=document.createElement('small');labelText.textContent=result.generation === 'not_called' ? '本地证据检索 · 未调用模型' : names.length ? names.join('、')+'完成回答' : '已完成回答';
  label.append(document.createTextNode('MediX '),labelText);main.append(label);
  if (result.case_changes?.length) {
    const notice=document.createElement('p'); notice.className='case-update-note';
    const revised=result.case_changes.filter(item=>item.action!=='add');
    notice.textContent=revised.length ? `已按本轮说明更新 ${revised.map(item=>item.name).join('、')}，后续使用最新记录。` : `已在本机记录 ${result.case_changes.length} 条本次病例信息。`;
    main.append(notice);
  }
  if (result.case_switched) {const notice=document.createElement('p');notice.className='case-update-note';notice.textContent='已按你的说明开始新的病例，本次不引用上一位的记录。';main.append(notice);}
  (result.data_warnings || []).forEach(message => {
    const notice=document.createElement('p'); notice.className='case-update-note';
    notice.setAttribute('role', 'status'); notice.textContent=message; main.append(notice);
  });
  if (result.case_sources?.length) {
    const block=document.createElement('details');block.className='observations case-evidence';
    const summary=document.createElement('summary');summary.textContent=`本次结合的病例资料 · ${result.case_sources.length} 条`;
    block.append(summary);
    result.case_sources.forEach(source=>{const p=document.createElement('p');p.textContent=`${source.date||'日期未提供'} · ${source.name}：${source.value} ${source.unit}（${source.origin}，v${source.revision}${source.certainty==='uncertain'?'，待核实':''}）`;block.append(p);});
    main.append(block);
  }
  renderMemory(main, result);
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
  const answerActions = document.createElement('div'); answerActions.className = 'answer-actions';
  const speak = document.createElement('button'); speak.type = 'button'; speak.className = 'speak-button'; speak.setAttribute('aria-label', '朗读回答'); speak.setAttribute('aria-pressed', 'false'); speak.innerHTML = `${icon('volume')}<span>朗读</span>`; speak.onclick = () => speakAnswer(result.answer, speak);
  const copyAnswer = document.createElement('button'); copyAnswer.type = 'button'; copyAnswer.className = 'answer-tool'; copyAnswer.innerHTML = `${icon('check')}<span>复制文字</span>`; copyAnswer.onclick = async () => { try { await navigator.clipboard.writeText(result.answer); toast('回答文字已复制。'); } catch { toast('复制失败，请手动选择文字。'); } };
  answerActions.append(speak, copyAnswer); main.append(answerActions);
  const meta = document.createElement('div'); meta.className = 'message-meta';
  const tags = [...(result.generation === 'not_called' ? ['仅检索原文'] : []), ...(result.image_context_used ? ['沿用本轮图片信息'] : []), ...(result.memory_enabled ? ['长期记忆已启用'] : []), ...(result.partial ? ['部分任务超时'] : [])];
  tags.forEach(text => { const tag = document.createElement('span'); tag.className = 'meta-pill'; tag.textContent = text; meta.append(tag); });
  if(result.usage)appendUsage(main,result.usage);
  if(tags.length)main.append(meta);
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
  const playbackEpoch = authEpoch, playbackToken = state.speechToken;
  if ($('autoSpeak').checked) setTimeout(() => {
    if (authEpoch === playbackEpoch && state.speechToken === playbackToken && speak.isConnected && $('autoSpeak').checked) speakAnswer(result.answer, speak);
  }, 80);
  scrollDown();
}
async function submit(message, images, retryRow, requestId = crypto.randomUUID()) {
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
    const response = await MedixAuth.fetch('/api/chat', {method:'POST', body:JSON.stringify({chat_id:state.chatId, case_id:state.caseId, request_id:requestId, message, images, remember:$('remember').checked, ...profileChoice})});
    const data = await response.json();
    if (epoch !== authEpoch) return;
    if (!response.ok) throw new Error(data.detail || '问题提交失败，请重试。');
    $('message').value = ''; state.images = []; renderAttachments();
    rememberActiveChat(); refreshConversations().catch(()=>{});
    await streamTurn(data.job_id,row,message,epoch);
    await refreshConversations();
  } catch (error) {
    if (epoch !== authEpoch) return;
    const main = row.querySelector('.message-main'); main.replaceChildren();
    const text = document.createElement('div'); text.className = 'error-text'; text.textContent = error.message;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'retry-button'; button.textContent = '重新分析'; button.onclick = () => { row.remove(); submit(message, images, pendingMessage(), crypto.randomUUID()); };
    main.append(text, button); scrollDown();
  } finally { if (epoch === authEpoch) { state.busy = false; state.jobId=null; updateComposer(); $('message').focus(); } }
}
$('chatForm').onsubmit = event => { event.preventDefault(); submit($('message').value.trim(), [...state.images]); };
$('newChat').onclick = () => { if (state.busy) return; cancelVoiceInput(); stopSpeaking(); state.chatId = crypto.randomUUID(); state.images = []; state.count = 0; $('messages').replaceChildren(); $('messages').classList.remove('active'); $('welcome').hidden = false; $('chatTitle').textContent = '新的健康对话'; $('message').value = ''; document.body.classList.remove('chatting'); closeSidebar(); renderAttachments(); $('conversation').scrollTop = 0; $('message').focus(); };
const resetChat = $('newChat').onclick;
$('newChat').onclick = () => {if(state.busy)return; resetChat();state.caseId='';$('caseContext').value='';};
$('caseContext').onchange = () => {const selected=$('caseContext').value;resetChat();state.caseId=selected;$('caseContext').value=selected;};
refreshCases().catch(()=>{});
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
    $('kbState').textContent = data.knowledge === 'ready' ? `${data.knowledge_backend === 'mini' ? '文本后备 · ' : ''}${data.documents} 个片段` : data.knowledge === 'error' ? '初始化失败' : '准备中'; $('kbDot').className = `status-dot ${data.knowledge === 'ready' ? 'ready' : data.knowledge === 'error' ? 'error' : ''}`;
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
    $('dialogContent').innerHTML = '<p><strong>01 · 描述你的问题</strong><br>可以说说具体症状、持续时间和已经了解的情况。不确定怎么描述，也可以直接问。</p><p><strong>02 · 图片也能一起问</strong><br>上传清晰的报告、药盒或记录；支持粘贴和拖入图片。最多 3 张，每张不超过 8 MB，支持 JPG、PNG、WebP。</p><p><strong>03 · 接着聊，不必重复</strong><br>可根据本轮图片继续追问。会话和压缩后的图片保存在本机账号数据库，刷新或重启后可从历史会话继续。删除会话会删除其消息、图片和用量记录；独立病例与Mem0记忆需分别管理。</p><p>默认关闭长期记忆。开启后，对话和图片解读摘要会发送至 Mem0，供后续会话检索。</p>';
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
const evidenceKindLabels = {popular_science:'健康科普，非核准药品说明书',clinical_guideline:'指南或专业规范（请核对版本）',medical_encyclopedia:'专业平台疾病资料，非政府发布',drug_reference:'专业平台药物资料，非具体制剂核准说明书'};
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
    const count = document.createElement('p'); count.textContent = `${data.document_total || data.documents.length} 份来源 · ${data.chunks} 个独立片段 · 版本 ${data.version}`; catalogNode.append(count);
    data.documents.forEach(doc => { const p = document.createElement('p'); p.textContent = `${doc.title}｜${doc.publisher}｜${doc.published_at || '日期未注明'}｜${(doc.audiences || ['unspecified']).map(a => audienceLabels[a] || a).join('、')}｜${evidenceKindLabels[doc.evidence_kind] || '类型未注明'}`; catalogNode.append(p); });
    if (data.next_offset !== null && data.next_offset !== undefined) {
      const more = document.createElement('button'); more.type = 'button'; more.textContent = '再查看50份来源'; let offset = data.next_offset; catalogNode.append(more);
      more.onclick = async () => { more.disabled = true; try {
        const response = await fetch(`/api/knowledge/catalog?offset=${offset}&limit=50`); if (!response.ok) throw new Error('加载失败'); const page = await response.json();
        page.documents.forEach(doc => { const p = document.createElement('p'); p.textContent = `${doc.title}｜${doc.publisher}｜${doc.published_at || '日期未注明'}｜${evidenceKindLabels[doc.evidence_kind] || '类型未注明'}`; catalogNode.insertBefore(p, more); });
        offset = page.next_offset; if (offset === null) more.remove();
      } catch { more.textContent = '加载失败，点击重试'; } finally { more.disabled = false; } };
    }
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

window.addEventListener("medix-auth-change",()=>refreshCases().catch(()=>{}));
window.addEventListener("medix-signout",()=>{state.caseId="";$("caseContext").replaceChildren(new Option("新对话，不关联历史",""));});

async function changeMemory(id, action, demo, container) {
  try {
    const response = await MedixAuth.fetch(`/api/memories/${encodeURIComponent(id)}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action, demo:!!demo, chat_id:state.chatId})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '操作未完成');
    if (container.memoryRecord && ['retire','delete'].includes(action)) {
      const record = {...container.memoryRecord};
      if (action === 'retire') record.active = 0;
      else record.deleted = true;
      refreshMemoryViews(record);
    }
    container.replaceChildren();
    const note = document.createElement('p'); note.textContent = action === 'exclude' ? '已排除此关联；下次提问不再引用。本次回答尚未重新分析。' : action === 'retire' ? '已停用这条旧信息，后续不再引用。' : data.backend === 'mem0' ? '已从 Mem0 删除这条记录并核验结果。' : '已从本机删除这条记录。';
    container.append(note); toast('已更新记忆，并清除旧的对话上下文');
  } catch (error) { toast(error.message); }
}
function memoryCard(record, demo, candidate=false, library=false) {
  const card = document.createElement('div'); card.className = 'memory-card';
  card.dataset.memoryId = record.id; card.memoryRecord = record; card.memoryOptions = {demo, candidate, library};
  const title = document.createElement('strong');
  const date = new Date(record.created).toLocaleString('zh-CN', {month:'long', day:'numeric', hour:'2-digit', minute:'2-digit'});
  title.textContent = `${record.active === 0 ? '已停用 · ' : ''}${library ? '已保存的健康记录' : candidate ? '发现可能相关的记录 · 回答未标注来源编号' : '本次回答参考的记录'} · ${date}`;
  const who = document.createElement('small'); who.textContent = `人物：${({self:'本人',father:'父亲',mother:'母亲'})[record.patient] || '其他'} · 来源：${record.edited_at ? '用户修改的记忆' : '当时的用户原文'} · ${record.backend === 'mem0' ? 'Mem0 云端' : record.backend === 'local_legacy' ? '本机旧记录（未上传）' : '本机记录'}`;
  const text = document.createElement('p'); text.textContent = record.content;
  const preview = document.createElement('button'); preview.type = 'button'; preview.className = 'memory-preview'; preview.onclick = () => showMemorySource(record);
  preview.append(title, who, text);
  if (record.reason) { const reason = document.createElement('p'); reason.className = 'memory-reason'; reason.textContent = `${record.reason}。同主题不代表同一次病程。`; preview.append(reason); }
  const hint = document.createElement('span'); hint.className = 'source-open-hint'; hint.textContent = '查看原始记录 ↗'; preview.append(hint); card.append(preview);
  const actions = document.createElement('div'); actions.className = 'memory-actions';
  const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = '编辑记忆'; edit.onclick = () => openMemoryEditor(record,demo); actions.append(edit);
  if (record.edited_at) { const updated = document.createElement('p'); updated.className = 'memory-edited'; updated.textContent = `已修改 · ${new Date(record.edited_at).toLocaleString('zh-CN')} · 已有回答未重新分析`; card.append(updated); }
  for (const [action, label] of [['exclude','这次不是同一件事'],['retire','信息已过时'],['delete','删除记录']]) {
    if (library && action === 'exclude') continue;
    if (record.active === 0 && action !== 'delete') continue;
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.onclick = () => changeMemory(record.id, action, demo, card); actions.append(button);
  }
  card.append(actions); return card;
}
function renderMemory(main, result) {
  if (result.demo) { const note = document.createElement('div'); note.className = 'demo-banner'; note.textContent = '虚构交互演示：使用真实的本机存储、关联与纠正逻辑；回答为预置文案，未调用医疗模型，不写入你的正式记忆。'; main.append(note); }
  const references = result.memory_references || [];
  const candidates = result.memory_candidates || [];
  references.forEach(record => main.append(memoryCard(record, result.demo)));
  candidates.forEach(record => main.append(memoryCard(record, result.demo, true)));
  const statuses = {saved:'已保存本次健康描述到 Mem0，并核验原文',skipped:'模型判断本次无需新增长期记忆',error:'本次记忆读写未完全成功，请稍后重试'};
  if (result.memory_status && statuses[result.memory_status]) {
    if (result.memory_status === 'skipped' && result.memory_decision?.reason) statuses.skipped += '：' + result.memory_decision.reason;
    if (result.memory_status === 'skipped' && result.patient_resolution) {
      const subject = result.patient_resolution.subject;
      if (['unknown','multiple'].includes(subject)) statuses.skipped = '人物尚未明确，本次未读取或保存个人记忆';
      else if (subject === 'general') statuses.skipped = '闲聊或通用问题，本次不保存个人记忆';
      else if (subject === 'other') statuses.skipped = '当前亲友暂不建立长期记忆';
      if (result.patient_resolution.method === 'unavailable') statuses.skipped = '自动记忆判断暂未完成，本次未读取或保存个人记忆';
    }
    const note = document.createElement('div'); note.className = 'memory-status'; note.textContent = statuses[result.memory_status] + (result.memory_error ? ' · ' + result.memory_error : '');
    if (result.memory_enabled && result.patient_resolution?.patient !== 'other' && !references.length && !candidates.length && result.memory_status !== 'error') note.textContent += ' · 未发现相关的健康记忆';
    if (result.memory_saved) { const detail = document.createElement('details'); const title = document.createElement('summary'); title.textContent = '查看本次保存内容'; const text = document.createElement('p'); text.textContent = `${result.memory_saved.patient}：${result.memory_saved.content}`; detail.append(title,text); note.append(detail); }
    main.append(note);
  }
}
async function openMemoryLibrary(family=false) {
  if (!await MedixAuth.requireLogin()) return;
  closeSidebar(); $('dialogTitle').textContent = family ? '亲友健康记忆 · Mem0' : state.demo ? '我的虚构演示记忆' : '我的健康记忆 · Mem0'; $('dialogContent').replaceChildren(); $('infoDialog').showModal();
  const demo = !!state.demo;
  const loading = document.createElement('p'); loading.textContent = demo ? '正在读取演示记忆…' : '正在从 Mem0 读取记忆…'; $('dialogContent').append(loading);
  try {
    const response = await MedixAuth.fetch(`/api/memories?demo=${demo}&scope=${family ? 'family' : 'self'}`); const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '无法加载记忆');
    loading.remove();
    const note = document.createElement('p'); note.textContent = family ? '按人物分别查看父亲、母亲的健康原文。模型会结合描述与本轮上下文判断人物。其他亲友暂不自动保存，避免混淆。点击记录可查看完整原文。' : '显示本人的最近 100 条记录（包含已停用）。点击记录可查看原文。历史描述不等于确诊或当前状态；记忆可随时编辑、停用或删除。'; note.textContent += demo ? ' 当前为本机虚构演示。' : ' 新记录保存于 Mem0；本机旧记录单独标明且不会自动上传。'; $('dialogContent').append(note);
    const groups = family ? [['father','父亲'],['mother','母亲']] : [['self','本人']];
    for (const [patient,label] of groups) {
      const records = data.memories.filter(record => record.patient === patient);
      let target = $('dialogContent');
      if (family) {
        const group = document.createElement('details'); group.className = 'family-group'; group.records = records;
        const bar = document.createElement('summary'); bar.className = 'family-bar';
        const avatar = document.createElement('span'); avatar.className = 'family-avatar'; avatar.textContent = label.slice(0,1);
        const info = document.createElement('span'); info.className = 'family-info';
        const name = document.createElement('strong'); name.textContent = label;
        const count = document.createElement('span'); count.className = 'family-count';
        const description = document.createElement('span'); description.className = 'family-description';
        const chevron = document.createElement('span'); chevron.className = 'family-chevron'; chevron.textContent = '›';
        info.append(name,count,description); bar.append(avatar,info,chevron);
        const body = document.createElement('div'); body.className = 'family-records';
        group.append(bar,body); target.append(group); updateFamilySummary(group); target = body;
      }
      if (!records.length) {
        const empty = document.createElement('p'); empty.className = 'memory-empty'; empty.textContent = family ? `还没有${label}的记录。在咨询时直接提到「${label}」，即可开始记录。` : '还没有本人的记录。模型判断值得长期保留、且人物明确的健康描述会保存在这里。'; target.append(empty);
      }
      records.forEach(record => target.append(memoryCard(record, demo, false, true)));
    }
  } catch(error) { $('dialogContent').textContent = error.message; }
}
$('memoryLibrary').onclick = () => openMemoryLibrary(false);
$('familyMemory').onclick = () => openMemoryLibrary(true);

function updateFamilySummary(group) {
  const summary = summarizeFamily(group.records);
  group.querySelector('.family-count').textContent = `${summary.total} 条记忆${summary.inactive ? ` · ${summary.inactive} 条已停用` : ''}`;
  group.querySelector('.family-description').textContent = `记录主题：${summary.description}`;
}
function refreshMemoryViews(updated) {
  document.querySelectorAll('.memory-card').forEach(card => {
    if (card.dataset.memoryId !== updated.id) return;
    const options = card.memoryOptions;
    const record = {...updated}; delete record.reason; delete record.highlight_terms;
    if (record.deleted) { card.replaceChildren(document.createTextNode('这条记忆已删除。')); return; }
    card.replaceWith(memoryCard(record,options.demo,options.candidate,options.library));
  });
  document.querySelectorAll('.family-group').forEach(group => {
    group.records = group.records.map(record => record.id === updated.id ? updated : record);
    updateFamilySummary(group);
  });
  if (state.sourceRecord?.id === updated.id && $('sourceDialog').open && !updated.deleted) showMemorySource(updated);
}
function openMemoryEditor(record,demo=false) {
  if (state.memorySaving) return;
  state.editMemory = {record:{...record}, demo:record.backend ? false : !!demo};
  $('memoryEditTitle').textContent = `编辑${({self:'本人',father:'父亲',mother:'母亲'})[record.patient] || ''}的健康记忆`;
  const cloud = record.backend === 'mem0';
  $('memoryEditHelp').textContent = cloud ? '保存后覆盖 Mem0 中这条记忆的内容，保留人物归属和记录编号。已有回答不会自动改写。' : '这是一条本机记录，修改仅保存到本机，不会自动上传到 Mem0。';
  $('memoryEditContent').value = record.content; $('memoryEditObservations').value = record.observations || '';
  $('memoryEditError').textContent = ''; $('saveMemoryEdit').textContent = cloud ? '保存并覆盖 Mem0 原记忆' : '保存本机修改';
  if (!$('memoryEditDialog').open) $('memoryEditDialog').showModal();
}
function closeMemoryEditor() { if (!state.memorySaving) $('memoryEditDialog').close(); }
$('closeMemoryEdit').onclick = $('cancelMemoryEdit').onclick = closeMemoryEditor;
$('memoryEditDialog').addEventListener('cancel',event => { if (state.memorySaving) event.preventDefault(); });
$('memoryEditForm').onsubmit = async event => {
  event.preventDefault(); if (state.memorySaving) return;
  const {record,demo} = state.editMemory;
  const content = $('memoryEditContent').value.trim();
  if (!content) { $('memoryEditError').textContent = '记忆内容不能为空。'; return; }
  state.memorySaving = true;
  ['saveMemoryEdit','cancelMemoryEdit','closeMemoryEdit','memoryEditContent','memoryEditObservations'].forEach(id => $(id).disabled = true);
  $('saveMemoryEdit').textContent = '正在覆盖并核验…'; $('memoryEditError').textContent = '';
  try {
    const response = await MedixAuth.fetch(`/api/memories/${encodeURIComponent(record.id)}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      content, observations:$('memoryEditObservations').value, expected_revision:record.revision || 0, demo, chat_id:state.chatId})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '保存未完成');
    $('memoryEditDialog').close(); refreshMemoryViews(data.record);
    toast(data.backend === 'mem0' ? '已覆盖 Mem0 原记忆并核验，记录编号保持不变。' : '已保存本机修改。');
  } catch(error) { $('memoryEditError').textContent = error.message; }
  finally {
    state.memorySaving = false;
    ['saveMemoryEdit','cancelMemoryEdit','closeMemoryEdit','memoryEditContent','memoryEditObservations'].forEach(id => $(id).disabled = false);
    $('saveMemoryEdit').textContent = record.backend === 'mem0' ? '保存并覆盖 Mem0 原记忆' : '保存本机修改';
  }
};

function sourceText(label, text, ranges=[]) {
  const heading = document.createElement('h3'); heading.textContent = label;
  const pre = document.createElement('pre'); pre.className = 'source-original';
  let cursor = 0;
  for (const [start,end] of ranges) {
    pre.append(document.createTextNode(text.slice(cursor,start)));
    const mark = document.createElement('mark'); mark.className = 'reference-highlight'; mark.textContent = text.slice(start,end);
    pre.append(mark); cursor = end;
  }
  pre.append(document.createTextNode(text.slice(cursor)));
  $('sourceContent').append(heading, pre);
  return pre;
}
function focusReference(container) {
  requestAnimationFrame(() => {
    if (!$('sourceDialog').open || !container.isConnected) return;
    const mark = container.querySelector('mark');
    if (mark) mark.scrollIntoView({block:'center', behavior:'instant'});
  });
}
function referenceLegend(text) {
  const note = document.createElement('p'); note.className = 'reference-legend'; note.textContent = text; $('sourceContent').append(note);
}
function openSource(title) {
  $('sourceTitle').textContent = title; $('sourceContent').replaceChildren();
  if (!$('sourceDialog').open) $('sourceDialog').showModal();
  $('sourceContent').scrollTop = 0;
}
function showMemorySource(record) {
  state.sourceRecord = record;
  openSource('健康记忆 · 原始记录');
  const meta = document.createElement('p'); meta.textContent = `人物：${({self:'本人',father:'父亲',mother:'母亲'})[record.patient] || '其他'} · 记录时间：${new Date(record.created).toLocaleString('zh-CN')} · ${record.active === 0 ? '已停用' : '可用'} · ${record.backend === 'mem0' ? 'Mem0 云端原文' : record.backend === 'local_legacy' ? '本机旧记录（未上传）' : '本机记录'}`; $('sourceContent').append(meta);
  const terms = record.highlight_terms || record.topics || [];
  referenceLegend(record.highlight_terms ? '黄色部分：与本次问题关联的健康描述。同主题不代表同一次病程。' : '黄色部分：本条记录中的健康主题描述。');
  const original = sourceText(record.edited_at ? '当前记忆内容（已修改）' : '用户当时的完整描述', record.content, SourceHighlights.sentenceRanges(record.content, terms));
  let observations;
  if (record.observations) observations = sourceText('当次图片的客观读取结果（可能有识别误差）', record.observations, SourceHighlights.sentenceRanges(record.observations, terms));
  focusReference(original.querySelector('mark') ? original : observations || original);
  const note = document.createElement('p'); note.textContent = `记录编号：${record.id}。${record.edited_at ? '当前显示用户于 ' + new Date(record.edited_at).toLocaleString('zh-CN') + ' 修改后的内容。' : '这条来源保留用户原文和图片读取文字。'}不保存原始上传图片，也不等同于完整聊天记录或确诊。`; $('sourceContent').append(note);
  const edit = document.createElement('button'); edit.className = 'memory-enable'; edit.textContent = '编辑这条记忆'; edit.onclick = () => openMemoryEditor(record,!!state.demo); $('sourceContent').append(edit);
}
async function showKnowledgeSource(source) {
  openSource(`${source.title || '医学资料'} · 原文`);
  const meta = document.createElement('p'); meta.textContent = `来源文件：${source.file}`; $('sourceContent').append(meta);
  const excerpt = source.highlight_excerpt || source.reference_excerpt || source.content?.slice(0,750) || source.excerpt;
  referenceLegend('黄色部分：本次参考片段中与问题最相关的段落；其余内容保留供核对上下文。');
  const preview = document.createElement('section'); $('sourceContent').append(preview);
  const initial = sourceText('本次命中的片段', source.content || source.excerpt,
    SourceHighlights.referenceRanges(source.content || source.excerpt, [excerpt]));
  preview.append(initial.previousElementSibling, initial);
  focusReference(initial);
  const status = document.createElement('p'); status.textContent = '正在加载来源文件全文…'; $('sourceContent').append(status);
  try {
    const response = await MedixAuth.fetch(`/api/knowledge/source/${encodeURIComponent(source.file)}`);
    const data = await response.json();
    if (!$('sourceContent').contains(status)) return;
    if (!response.ok) throw new Error();
    $('sourceTitle').textContent = `${data.title || source.title || '医学资料'} · 原文`;
    const ranges = SourceHighlights.referenceRanges(data.content, [excerpt]);
    status.remove();
    if (ranges.length) preview.remove();
    else referenceLegend('未能在文件全文中定位该片段，已保留上方命中内容；未推测高亮位置。');
    const full = sourceText('来源文件全文', data.content, ranges);
    if (ranges.length) focusReference(full);
  } catch {
    if ($('sourceContent').contains(status)) status.textContent = '未找到对应的本地原始文件；上方仍展示本次返回的检索片段。';
  }
}
$('closeSource').onclick = $('sourceDone').onclick = () => $('sourceDialog').close();
$('sourceDialog').addEventListener('click', event => {
  if (event.target !== $('sourceDialog')) return;
  const bounds = $('sourceDialog').getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $('sourceDialog').close();
});
async function runMemoryDemo(scenario) {
  if (state.busy) return;
  state.busy = true; state.demo = true; updateComposer();
  try {
    const response = await MedixAuth.fetch('/api/memory/demo', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({chat_id:state.chatId, scenario})});
    const result = await response.json(); if (!response.ok) throw new Error(result.detail || '演示失败');
    document.body.classList.add('chatting'); $('welcome').hidden = true; $('messages').classList.add('active'); $('chatTitle').textContent = '记忆体验 · 虚构演示';
    userMessage(result.question, []); const row = pendingMessage(); resultMessage(row, result);
    const choices = document.createElement('div'); choices.className = 'memory-actions';
    for (const [value,label] of [['related','再次提问：关联病例'],['family','改问父亲：避免串联'],['unrelated','换个症状：不强行回忆']]) {
      const button = document.createElement('button'); button.textContent = label; button.onclick = () => runMemoryDemo(value); choices.append(button);
    }
    row.querySelector('.message-main').append(choices); scrollDown();
  } catch(error) { toast(error.message); }
  finally { state.busy = false; updateComposer(); }
}
$('memoryDemo').onclick = () => { closeSidebar(); runMemoryDemo('related'); };

window.addEventListener("medix-signout",()=>{state.demo=false;state.editMemory=null;state.sourceRecord=null;["memoryEditDialog","sourceDialog","infoDialog"].forEach(id=>{if($(id).open)$(id).close();});});

state.channel='wechat';state.cursors={wechat:0,qq:0};state.linkQr='';
state.seenReminders = new Set();
function showReminder(item) {
  document.body.classList.add('chatting');
  $('welcome').hidden = true;
  $('messages').classList.add('active');
  const row = document.createElement('article');
  row.className = 'message assistant reminder';
  row.dataset.sessionId = item.session_id || '';
  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.innerHTML = icon(item.kind === 'medication' ? 'pill' : 'heart');
  const main = document.createElement('div');
  main.className = 'message-main';
  const label = document.createElement('div');
  label.className = 'message-label';
  label.innerHTML = `${escapeText(item.label)} <small>定时提醒</small>`;
  const answer = document.createElement('div');
  answer.className = 'answer';
  const text = document.createElement('p');
  text.textContent = item.canonical_text;
  answer.append(text);
  main.append(label, answer);
  row.append(avatar, main);
  $('messages').append(row);
  scrollDown();
}
function renderUpcoming(items) {
  const list = $('reminderList');
  list.replaceChildren();
  $('reminderCount').textContent = items.length ? String(items.length) : '';
  $('reminderEmpty').hidden = items.length > 0;
  items.forEach(item => {
    const card = document.createElement('div');
    card.className = 'reminder-card';
    const title = document.createElement('strong');
    title.textContent = item.label;
    const when = document.createElement('small');
    when.textContent = item.next_fire_at;
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = '取消';
    button.setAttribute('aria-label', `取消${item.label}`);
    button.onclick = () => cancelReminder(item.id);
    card.append(title, when, button);
    list.append(card);
  });
}
async function cancelReminder(id) {
  const response = await MedixAuth.fetch(`/api/reminders/${id}/cancel`, {method: 'POST', headers: {'Content-Type':'application/json'}, body:'{}'});
  if (!response.ok) { toast('没有取消这条提醒。'); return; }
  toast('已取消这条提醒。');
  refreshReminders();
}
async function refreshReminders() {
  await MedixAuth.ready.catch(()=>{});
  if (!MedixAuth.user) return;
  const owner=MedixAuth.user.id;
  try {
    const response = await MedixAuth.fetch('/api/reminders');
    if (!response.ok) return;
    const data = await response.json();
    if (typeof owner!=="undefined" && MedixAuth.user?.id!==owner) return;
    renderUpcoming(data.upcoming || []);
    const fresh = (data.unread || []).filter(item => !state.seenReminders.has(item.id));
    if (!fresh.length) return;
    fresh.forEach(item => { state.seenReminders.add(item.id); showReminder(item); });
    await MedixAuth.fetch('/api/reminders/read', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids: fresh.map(item => item.id)})});
  } catch { /* 下一轮轮询再试 */ }
}
refreshReminders();
setInterval(refreshReminders, 15000);
const linkLabels = {idle: '未连接', waiting: '等待扫码', scanned: '请在手机确认', need_code: '需要配对码', connected: '已连接', expired: '二维码过期', error: '连接失败', taken: '其他页面已连接', connecting: '正在连接'};
function linkApi() { return state.channel === 'qq' ? '/api/qq' : '/api/wechat'; }
function showPhoneMessage(event) {
  document.body.classList.add('chatting');
  $('welcome').hidden = true;
  $('messages').classList.add('active');
  const from = event.origin === 'qq' ? 'QQ' : '微信';
  if (event.role === 'user') {
    userMessage(event.text, []);
    if (!state.count++) $('chatTitle').textContent = (event.text || from + '对话').slice(0, 18);
    scrollDown();
    return;
  }
  const row = document.createElement('article');
  row.className = 'message assistant';
  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.innerHTML = icon('heart');
  const main = document.createElement('div');
  main.className = 'message-main';
  const label = document.createElement('div');
  label.className = 'message-label';
  label.innerHTML = `MediX <small>来自${from}</small>`;
  const answer = document.createElement('div');
  answer.className = 'answer';
  answer.innerHTML = richText(event.text);
  main.append(label, answer);
  row.append(avatar, main);
  $('messages').append(row);
  scrollDown();
}
function paintChannel() {
  const qq = state.channel === 'qq';
  $('pickWechat').setAttribute('aria-pressed', qq ? 'false' : 'true');
  $('pickQq').setAttribute('aria-pressed', qq ? 'true' : 'false');
  $('channelTitle').textContent = qq ? 'QQ MediX' : '微信 MediX';
}
async function refreshLink() {
  await MedixAuth.ready.catch(()=>{});
  if (!MedixAuth.user) return;
  const owner=MedixAuth.user.id;
  try {
    const response = await MedixAuth.fetch(linkApi() + '?after=' + (state.cursors[state.channel] || 0));
    if (!response.ok) return;
    const data = await response.json();
    if (typeof owner!=="undefined" && MedixAuth.user?.id!==owner) return;
    $('wechatState').textContent = linkLabels[data.status] || '未连接';
    $('wechatHint').textContent = data.hint || '';
    const qr = $('wechatQr');
    const nextQr = data.qr || '';
    qr.alt = state.channel === 'qq' ? '用手机 QQ 扫描登录' : '用微信扫描，添加 MediX';
    if (nextQr !== state.linkQr) {
      state.linkQr = nextQr;
      if (nextQr) { qr.src = nextQr; qr.hidden = false; qr.scrollIntoView({block: 'nearest'}); }
      else { qr.hidden = true; qr.removeAttribute('src'); }
    }
    $('wechatCodeForm').hidden = state.channel !== 'wechat' || data.status !== 'need_code';
    $('qqFriendForm').hidden = state.channel !== 'qq' || data.status === 'taken';
    const linked = data.status === 'connected';
    $('wechatLogout').hidden = !linked;
    $('wechatLogin').hidden = linked || data.status === 'taken';
    if (state.channel === 'qq') $('wechatLogin').textContent = data.status === 'waiting' ? '刷新二维码' : '扫码登录';
    else $('wechatLogin').textContent = data.status === 'waiting' || data.status === 'scanned' ? '刷新二维码' : '扫码添加';
    (data.events || []).forEach(showPhoneMessage);
    if (Number.isInteger(data.cursor)) state.cursors[state.channel] = data.cursor;
  } catch { /* 下一轮再同步手机连接 */ }
}
async function chooseChannel(channel) {
  if (state.channel === channel) return;
  try {
    const response = await MedixAuth.fetch('/api/channel', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({channel})});
    if (!response.ok) { toast('没有切换到这个聊天。'); return; }
    state.channel = channel;
    state.linkQr = '';
    paintChannel();
    await refreshLink();
  } catch { toast('没有切换到这个聊天。'); }
}
$('pickWechat').onclick = () => chooseChannel('wechat');
$('pickQq').onclick = () => chooseChannel('qq');
$('qqFriendForm').onsubmit = async event => {
  event.preventDefault();
  const userId = $('qqFriendId').value.trim();
  const button = event.submitter;
  if (button) button.disabled = true;
  try {
    const response = await MedixAuth.fetch('/api/qq/friend', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_id: userId})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { toast(data.detail || '没有添加这个好友。'); return; }
    $('qqFriendId').value = '';
    await refreshLink();
  } catch { toast('没有添加这个好友。'); }
  finally { if (button) button.disabled = false; }
};
$('wechatLogin').onclick = async () => {
  $('wechatLogin').disabled = true;
  const name = state.channel === 'qq' ? 'QQ' : '微信';
  try {
    const response = await MedixAuth.fetch(linkApi() + '/login', {method: 'POST', headers: {'Content-Type':'application/json'}, body:'{}'});
    if (!response.ok) { toast('暂时无法连接' + name + '。'); return; }
    await refreshLink();
  } catch { toast('暂时无法连接' + name + '。'); }
  finally { $('wechatLogin').disabled = false; }
};
$('wechatCodeForm').onsubmit = async event => {
  event.preventDefault();
  const code = $('wechatCode').value.trim();
  try {
    const response = await MedixAuth.fetch('/api/wechat/code', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { toast(data.detail || '配对码是 4 到 8 位数字。'); return; }
    $('wechatCode').value = '';
    await refreshLink();
  } catch { toast('配对码没有提交成功。'); }
};
$('wechatLogout').onclick = async () => {
  try { await MedixAuth.fetch(linkApi() + '/logout', {method: 'POST', headers: {'Content-Type':'application/json'}, body:'{}'}); } catch { /* 仍刷新本地状态 */ }
  state.cursors[state.channel] = 0;
  state.linkQr = '';
  refreshLink();
};
paintChannel();
Promise.resolve(MedixAuth.ready).then(()=>MedixAuth.user ? MedixAuth.fetch('/api/channel') : null).then(response => response?.ok ? response.json() : null).then(data => {
  if (data && (data.channel === 'wechat' || data.channel === 'qq')) state.channel = data.channel;
  paintChannel();
  refreshLink();
}).catch(() => refreshLink());
setInterval(refreshLink, 2000);

window.addEventListener('medix-auth-change',()=>{refreshReminders();refreshLink();});
window.addEventListener('medix-signout',()=>{state.seenReminders.clear();state.cursors={wechat:0,qq:0};state.linkQr='';state.channel='wechat';$('wechatQr').hidden=true;$('wechatQr').removeAttribute('src');$('wechatState').textContent='未连接';$('wechatHint').textContent='请登录后连接微信或 QQ。';renderUpcoming([]);});

// Durable conversations and resumable, server-originated model chunks.
function rememberActiveChat() {
  if (MedixAuth.user) localStorage.setItem(`medix-active-${MedixAuth.user.id}`,state.chatId);
}
function usageText(usage) {
  const charge=usage.charge;
  const used=charge?.recorded ? `使用 ${formatPoints(charge.points)} 关怀点${charge.held_points>0?'（部分待结算）':''}` : '';
  const counts=new Map();
  for(const call of usage.calls || []){
    if(!call.agent || call.agent.startsWith('stage:'))continue;
    const name=walletAgentName(call.agent);counts.set(name,(counts.get(name) || 0)+1);
  }
  const assistants=[...counts].map(([name,count])=>`${name}调用 ${count} 次`).join('、');
  return [used,assistants].filter(Boolean).join(' · ');
}
function appendUsage(main,usage) {
  let line=main.querySelector('.care-usage,.usage-details');const text=usageText(usage);
  if(!text){line?.remove();return;}
  if(!line || line.tagName!=='P'){line?.remove();line=document.createElement('p');line.className='care-usage';main.append(line);}
  line.textContent=text;
}
function draftArea(row) {
  let draft=row.querySelector('.stream-answer');
  if (!draft) {draft=document.createElement('div');draft.className='answer stream-answer';row.querySelector('.message-main').append(draft);}
  return draft;
}
function stoppedMessage(row,turn) {
  row.querySelector('.process')?.remove();
  const label=row.querySelector('.message-label small');if(label)label.textContent='生成已结束';
  const message=document.createElement('p'); message.className='error-text';message.textContent=turn.error || '生成已中断；以上为未完成草稿。';
  row.querySelector('.message-main').append(message);
  if(turn.usage)appendUsage(row.querySelector('.message-main'),turn.usage);
}
function streamTurn(jobId,row,message,epoch,after=0) {
  state.jobId=jobId; updateComposer();
  return new Promise((resolve,reject)=>{
    const source=new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events?after=${after}`);
    state.eventSource=source;
    let outage;
    source.onopen=()=>{clearTimeout(outage);outage=null;};
    source.onerror=()=>{
      if(epoch!==authEpoch){source.close();resolve();return;}
      const label=row.querySelector('.phase-label');if(label)label.textContent='连接中断，正在恢复；不会重复调用模型';
      if(!outage)outage=setTimeout(()=>{source.close();reject(new Error('连接尚未恢复，刷新页面可恢复历史任务。'));},30000);
    };
    source.onmessage=event=>{
      if(epoch!==authEpoch){source.close();clearTimeout(outage);resolve();return;}
      let data;try{data=JSON.parse(event.data);}catch{return;}
      if(data.type==='stage') {const label=row.querySelector('.phase-label');if(label)label.textContent=data.label;}
      if(data.type==='draft_start') {
        row.dataset.streamCall=data.call_id;draftArea(row).textContent='';
        const label=row.querySelector('.phase-label');if(label)label.textContent=`${walletAgentName(data.agent)}正在生成草稿，完成后校验`;
      }
      if(data.type==='draft_clear' && row.dataset.streamCall===data.call_id)draftArea(row).textContent='';
      if(data.type==='delta' && row.dataset.streamCall===data.call_id){draftArea(row).textContent+=data.text;scrollDown();}
      if(data.type==='usage'){appendUsage(row.querySelector('.message-main'),data.usage);refreshWallet().catch(()=>{});}
      if(data.type==='done') {
        source.close();clearTimeout(outage);state.eventSource=null;
        if(data.status==='completed' && data.result)resultMessage(row,data.result,message,jobId);
        else stoppedMessage(row,data);
        refreshWallet().catch(()=>{});scrollDown();resolve();
      }
    };
  });
}
$('stopGeneration').onclick=async()=>{
  if(!state.jobId)return;
  $('stopGeneration').disabled=true;
  try{
    const response=await MedixAuth.fetch(`/api/jobs/${state.jobId}/cancel`,{method:'POST'});
    if(!response.ok)throw new Error('停止失败，请重试。');
    toast('已请求停止，正在关闭模型连接并保存已有内容。');
  }catch(error){toast(error.message);$('stopGeneration').disabled=false;}
};
async function refreshConversations() {
  if(!MedixAuth.user)return;
  const owner=MedixAuth.user.id;
  const response=await MedixAuth.fetch('/api/conversations');
  if(!response.ok)return;
  const data=await response.json();
  if(MedixAuth.user?.id!==owner)return;
  $('conversationList').replaceChildren();
  data.conversations.forEach(item=>{
    const row=document.createElement('div');row.className='session-row';
    const button=document.createElement('button');button.type='button';button.className='conversation-item';
    const channelLabel=({qq:'QQ',wechat:'微信'})[item.channel];
    button.textContent=(channelLabel?channelLabel+' · ':'')+item.title;button.title=button.textContent;
    button.setAttribute('aria-current',String(item.id===state.chatId));
    button.onclick=()=>openConversation(item.id).catch(error=>toast(error.message));
    const more=document.createElement('button');more.type='button';more.className='session-more';more.textContent='···';more.setAttribute('aria-label',`更多操作：${item.title}`);
    const panel=document.createElement('div');panel.className='session-menu-panel';panel.setAttribute('popover','auto');
    const rename=document.createElement('button');rename.type='button';rename.textContent='重命名';
    rename.onclick=()=>{panel.hidePopover();editConversation(item,'rename');};
    const remove=document.createElement('button');remove.type='button';remove.textContent='删除对话';remove.className='session-delete';
    remove.onclick=()=>{panel.hidePopover();editConversation(item,'delete');};panel.append(rename,remove);
    more.onclick=()=>{
      if(state.busy || state.opening)return;
      document.querySelectorAll('.session-menu-panel:popover-open').forEach(menu=>menu.hidePopover());
      panel.showPopover();const rect=more.getBoundingClientRect();panel.style.left=`${rect.right+6}px`;panel.style.top=`${Math.min(rect.top,innerHeight-120)}px`;
    };
    row.append(button,more,panel);$('conversationList').append(row);
  });
}
async function openConversation(id) {
  if(state.busy || state.opening)return;
  state.opening=true;updateComposer();
  try {
  const epoch=authEpoch;
  const response=await MedixAuth.fetch(`/api/conversations/${encodeURIComponent(id)}`);
  const data=await response.json();
  if(epoch!==authEpoch)return;
  if(!response.ok)throw new Error(data.detail || '会话加载失败。');
  resetChat();state.caseId='';$('caseContext').value='';state.chatId=id;state.count=data.turns.length;rememberActiveChat();
  $('chatTitle').textContent=data.title;
  $('welcome').hidden=true;$('messages').classList.add('active');document.body.classList.add('chatting');
  let totalRequests=0,totalTokens=0;
  for(const turn of data.turns){
    userMessage(turn.payload.message,turn.payload.images.map((data,i)=>({data,name:`已保存图片 ${i+1}`})));
    const row=pendingMessage();
    if(turn.label)row.querySelector('.phase-label').textContent=turn.label;
    totalRequests+=turn.usage.requests;totalTokens+=turn.usage.input_tokens+turn.usage.output_tokens;
    if(turn.status==='completed' && turn.result)resultMessage(row,turn.result,turn.payload.message,turn.id);
    else {
      if(turn.draft)draftArea(row).textContent=turn.draft;
      row.dataset.streamCall=turn.draft_call || '';
      if(['queued','running'].includes(turn.status)){
        state.busy=true;updateComposer();
        try{await streamTurn(turn.id,row,turn.payload.message,epoch,turn.cursor);}
        finally{if(epoch===authEpoch){state.busy=false;state.jobId=null;updateComposer();}}
      } else stoppedMessage(row,turn);
    }
  }
  if(epoch!==authEpoch)return;

  refreshConversations().catch(()=>{});scrollDown();
  } finally {state.opening=false;updateComposer();}
}
let conversationAction=null;
function editConversation(item,kind){
  if(state.busy || state.opening)return;
  conversationAction={...item,kind};
  $('conversationDialogTitle').textContent=kind==='rename'?'为这段对话起个名字':'删除这段对话？';
  $('conversationDialogHint').textContent=kind==='rename'?'一个好记的名字，方便下次接着聊。':'消息和保存的图片将被删除。独立病例、健康档案和长期记忆需分别管理；已消耗的关怀点不会退回。';
  $('conversationName').hidden=kind==='delete';$('conversationName').value=item.title;
  $('conversationDialogSave').textContent=kind==='rename'?'保存名称':'删除对话';
  $('conversationDialogSave').classList.toggle('danger',kind==='delete');$('conversationEditError').textContent='';
  $('conversationDialog').showModal();if(kind==='rename'){$('conversationName').focus();$('conversationName').select();}
}
$('conversationDialogClose').onclick=$('conversationDialogCancel').onclick=()=>$('conversationDialog').close();
$('conversationEditForm').onsubmit=async event=>{
  event.preventDefault();const action=conversationAction;if(!action)return;
  const title=$('conversationName').value.trim();if(action.kind==='rename' && !title)return;
  $('conversationDialogSave').disabled=true;
  try{
    const response=await MedixAuth.fetch(`/api/conversations/${action.id}`,{method:action.kind==='rename'?'PATCH':'DELETE',body:JSON.stringify(action.kind==='rename'?{title}:{})});
    if(!response.ok)throw new Error((await response.json()).detail || '操作未完成');
    $('conversationDialog').close();
    if(action.id===state.chatId){if(action.kind==='delete')$('newChat').click();else $('chatTitle').textContent=title;}
    await refreshConversations();
  }catch(error){$('conversationEditError').textContent=error.message;}
  finally{$('conversationDialogSave').disabled=false;}
};
const originalNewChat=$('newChat').onclick;
$('newChat').onclick=()=>{originalNewChat();if(!state.busy){rememberActiveChat();refreshConversations();}};
function formatPoints(value){return Number(value).toLocaleString('zh-CN',{maximumFractionDigits:3});}
async function refreshWallet(){
  if(!MedixAuth.user){$('careWallet').hidden=true;return;}
  const owner=MedixAuth.user.id;const response=await MedixAuth.fetch('/api/wallet');
  if(!response.ok)return;const wallet=await response.json();if(MedixAuth.user?.id!==owner)return;
  state.wallet=wallet;$('careWallet').hidden=false;$('careBalance').textContent=formatPoints(wallet.available)+' 点';
  $('walletAmount').textContent=formatPoints(wallet.available)+' 点';
  $('walletHeld').hidden=!wallet.held;
  $('walletHeld').textContent=wallet.held?`另有 ${formatPoints(wallet.held)} 点待核对结算。`:'';
  $('walletRules').textContent=`每个账户初始赠送 ${formatPoints(wallet.initial)} 关怀点。${formatPoints(wallet.points_per_cny)} 点对应 ¥1 模型消耗，按本轮全部模型调用扣除，精确到 0.001 点。`;
}
let walletHistoryOffset=0, walletHistoryEpoch=0;
function walletElement(tag,className,text){
  const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;
}
function walletAgentName(agent){
  return ({'stage:patient':'人物判断','stage:case':'病例整理','stage:agents':'任务路由','stage:vision':'图片读取','stage:presentation':'回答整理','stage:answer':'原文阅读','stage:memory':'记忆核对','stage:patient_resolve':'人物判断','stage:case_prepare':'病例整理','stage:route':'任务路由',
    'stage:search':'DeepSeek 网页搜索','stage:initial':'流程准备','stage:synthesize':'回答整理','general':'健康咨询助手',
    'consultation_agent':'健康咨询助手','diagnostic_agent':'诊断分析助手','research_agent':'医学研究助手','lead_synthesis':'协作汇总助手','evidence_reader':'原文阅读助手','health_consultant':'健康咨询助手','general_practitioner':'健康咨询助手'})[agent] || (agent?.startsWith('stage:')?'流程处理':agent || '助手');
}
function participatingAssistants(calls,fallback=[]){
  const ids=Array.isArray(calls)?calls.map(call=>call.agent):fallback;
  return [...new Set(ids.filter(id=>typeof id==='string' && !id.startsWith('stage:')).map(walletAgentName))];
}
function walletRecord(entry){
  const record=walletElement('details','wallet-record');
  const summary=walletElement('summary','wallet-record-summary');
  summary.append(walletElement('span','wallet-record-mark','✧'));
  const info=walletElement('div','wallet-record-info');info.append(walletElement('strong','',entry.title));
  const date=new Date(entry.created*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
  const channel=({qq:'QQ',wechat:'微信',web:'网页'})[entry.channel] || '网页';
  const assistants=participatingAssistants(entry.calls);
  const meta=entry.deleted ? `${date} · ${channel} · 对话已删除` : `${date} · ${channel} · ${assistants.join('、') || '流程处理'} · ${entry.requests} 次模型请求${entry.search_requests?' · '+entry.search_requests+' 次搜索':''}`;
  info.append(walletElement('span','',meta));summary.append(info);
  const amount=walletElement('div','wallet-record-amount');amount.append(walletElement('strong','',`−${formatPoints(entry.points)}`));
  amount.append(walletElement('span','',entry.held_points>0?'有额度待结算':'关怀点'));summary.append(amount,walletElement('span','wallet-record-chevron','⌄'));record.append(summary);
  const content=walletElement('div','wallet-record-body');
  if(entry.deleted){content.append(walletElement('p','wallet-record-note','该对话已删除，用量明细已清理。已结算的关怀点保留记录。'));record.append(content);return record;}
  const metrics=walletElement('div','wallet-metrics');
  for(const [label,value] of [['输入 Token',entry.input_tokens],['输出 Token',entry.output_tokens],['缓存命中',entry.cache_hit_tokens]]){
    const metric=walletElement('div','');metric.append(walletElement('span','',label),walletElement('strong','',formatPoints(value)));metrics.append(metric);
  }
  content.append(metrics);
  const assistantLine=`${assistants.length?'参与助手：'+assistants.join('、'):'本轮仅有流程处理'} · 助手调用 ${entry.assistant_requests} 次 · 模型请求 ${entry.requests} 次${entry.search_requests?' · 网页搜索 '+entry.search_requests+' 次':''}`;
  content.append(walletElement('p','wallet-call-caption',assistantLine));
  const groups=new Map();
  for(const call of entry.calls){
    const key=call.agent || 'unknown';let group=groups.get(key);
    if(!group){group={agent:key,kind:call.usage_kind || 'model',calls:0,input:0,output:0,points:0,unknown:false};groups.set(key,group);}
    group.calls++;group.input+=call.input_tokens || 0;group.output+=call.output_tokens || 0;group.points+=call.points;group.unknown ||= !call.usage_known;
  }
  const list=walletElement('div','wallet-call-list');
  for(const group of groups.values()){
    const row=walletElement('div','wallet-call-row');const identity=walletElement('div','');identity.append(walletElement('strong','',walletAgentName(group.agent)),walletElement('span','',group.kind==='search'?`${group.calls} 次搜索${group.unknown?' · 费用待核对':''}`:`${group.calls} 次调用 · ${formatPoints(group.input)} 输入 / ${formatPoints(group.output)} 输出${group.unknown?' · 用量待核对':''}`));
    row.append(identity,walletElement('span','wallet-call-points',`${formatPoints(group.points)} 点`));list.append(row);
  }
  content.append(list);
  if(entry.held_points>0)content.append(walletElement('p','wallet-record-note',`${formatPoints(entry.held_points)} 关怀点待结算，已知消耗已计入记录。`));
  if(entry.unknown_requests && !entry.held_points)content.append(walletElement('p','wallet-record-note','部分用量尚未返回，以上仅统计已知用量。'));
  record.append(content);return record;
}
async function loadWalletHistory(reset=false){
  if(!MedixAuth.user)return;
  if(reset){walletHistoryOffset=0;walletHistoryEpoch++;$('walletHistory').replaceChildren(walletElement('p','wallet-empty','正在整理关怀记录…'));$('walletMore').hidden=true;}
  const epoch=walletHistoryEpoch,owner=MedixAuth.user.id,offset=walletHistoryOffset;
  $('walletMore').disabled=true;
  try{
    const response=await MedixAuth.fetch(`/api/wallet/history?offset=${offset}`);
    if(!response.ok)throw new Error('暂时无法读取记录');const data=await response.json();
    if(epoch!==walletHistoryEpoch || owner!==MedixAuth.user?.id)return;
    if(reset)$('walletHistory').replaceChildren();
    if(!data.entries.length && !offset)$('walletHistory').append(walletElement('p','wallet-empty','还没有消耗记录，下一次对话将在这里留下足迹。'));
    data.entries.forEach(entry=>$('walletHistory').append(walletRecord(entry)));
    walletHistoryOffset=data.next_offset;$('walletMore').hidden=!data.has_more;$('walletMore').textContent='查看更多记录';
  }catch{
    if(epoch!==walletHistoryEpoch || owner!==MedixAuth.user?.id)return;
    if(reset)$('walletHistory').replaceChildren(walletElement('p','wallet-empty','记录暂时无法加载，请稍后重试。'));
    $('walletMore').hidden=false;$('walletMore').textContent='重新加载';
  }finally{if(epoch===walletHistoryEpoch)$('walletMore').disabled=false;}
}
$('walletMore').onclick=()=>loadWalletHistory(walletHistoryOffset===0);
$('careWallet').onclick=()=>{refreshWallet().catch(()=>{});loadWalletHistory(true);walletTab('usage');loadRecharge();$('walletDialog').showModal();};
$('walletClose').onclick=()=>$('walletDialog').close();
window.addEventListener('medix-auth-change',()=>refreshWallet().catch(()=>{}));
window.addEventListener('medix-signout',()=>{walletHistoryEpoch++;rechargeEpoch++;rechargeRequest=null;rechargePlans=[];selectedRecharge=null;$('rechargePlans').replaceChildren();$('walletOrders').replaceChildren();$('rechargeFeedback').textContent='';$('walletHistory').replaceChildren();$('careWallet').hidden=true;$('walletDialog').close();$('conversationDialog').close();});
MedixAuth.ready.then(()=>refreshWallet()).catch(()=>{});
async function loadSavedConversations() {
  if(!MedixAuth.user)return;
  await refreshConversations();
  const id=localStorage.getItem(`medix-active-${MedixAuth.user.id}`);
  if(id && !state.busy && !state.count && !$('message').value.trim())await openConversation(id).catch(()=>{});
}
window.addEventListener('medix-auth-change',()=>loadSavedConversations().catch(()=>{}));
MedixAuth.ready.then(()=>loadSavedConversations()).catch(()=>{});

// Recharge is an unpaid order preview until a merchant payment service is enabled.
let rechargePlans=[],selectedRecharge=null,rechargeRequest=null,rechargeEpoch=0,ordersOffset=0;
function walletTab(name){
  $('walletContent').scrollTop=0;
  for(const [key,title] of [['usage','Usage'],['recharge','Recharge'],['orders','Orders']]){
    $(`wallet${title}Panel`).hidden=key!==name;
    $(`wallet${title}Tab`).setAttribute('aria-selected',String(key===name));
    $(`wallet${title}Tab`).tabIndex=key===name?0:-1;
  }
}
document.querySelectorAll('[data-wallet-tab]').forEach(button=>{
  button.onclick=()=>walletTab(button.dataset.walletTab);
  button.onkeydown=event=>{
    const buttons=[...document.querySelectorAll('[data-wallet-tab]')];let index=buttons.indexOf(button);
    if(event.key==='ArrowRight')index=(index+1)%buttons.length;
    else if(event.key==='ArrowLeft')index=(index+buttons.length-1)%buttons.length;
    else if(event.key==='Home')index=0;else if(event.key==='End')index=buttons.length-1;else return;
    event.preventDefault();buttons[index].click();buttons[index].focus();
  };
});
$('walletRechargeOpen').onclick=()=>walletTab('recharge');
function rechargeMoney(fen){return '¥'+(fen/100).toLocaleString('zh-CN',{maximumFractionDigits:2});}
function renderRechargePlans(){
  $('rechargePlans').replaceChildren();
  for(const plan of rechargePlans){
    const button=walletElement('button','recharge-plan');button.type='button';button.setAttribute('aria-pressed',String(plan.id===selectedRecharge));
    button.append(walletElement('span','recharge-plan-name',plan.name),walletElement('strong','recharge-plan-points',formatPoints(plan.points)),walletElement('span','recharge-plan-unit','关怀点'),walletElement('span','recharge-plan-price',rechargeMoney(plan.amount_fen)));
    button.onclick=()=>{if(selectedRecharge!==plan.id){rechargeRequest=null;$('rechargeFeedback').textContent='';}selectedRecharge=plan.id;renderRechargePlans();};
    $('rechargePlans').append(button);
  }
  const selected=rechargePlans.find(plan=>plan.id===selectedRecharge);
  $('rechargeTotal').textContent=selected?rechargeMoney(selected.amount_fen):'—';$('rechargeCreate').disabled=!selected;
}
async function loadRecharge(){
  const epoch=++rechargeEpoch,owner=MedixAuth.user?.id;if(!owner)return;
  rechargePlans=[];selectedRecharge=null;rechargeRequest=null;$('rechargeFeedback').textContent='';
  $('rechargePlans').replaceChildren(walletElement('p','wallet-empty','正在读取充值档位…'));$('rechargeCreate').disabled=true;
  loadRechargeOrders(true);
  try{
    const response=await MedixAuth.fetch('/api/wallet/plans');if(!response.ok)throw new Error();const data=await response.json();
    if(epoch!==rechargeEpoch || owner!==MedixAuth.user?.id)return;
    rechargePlans=data.plans;selectedRecharge=rechargePlans[0]?.id || null;renderRechargePlans();
  }catch{if(epoch===rechargeEpoch && owner===MedixAuth.user?.id)$('rechargePlans').replaceChildren(walletElement('p','wallet-empty','档位暂时无法加载，请重新打开关怀点页面。'));}
}
function rechargeOrderCard(order){
  const card=walletElement('article','recharge-order');
  const top=walletElement('div','recharge-order-top');const title=walletElement('div','');title.append(walletElement('strong','',order.plan_name),walletElement('span','',`${formatPoints(order.points)} 关怀点 · ${rechargeMoney(order.amount_fen)}`));
  const labels={awaiting_payment:'未支付 · 未到账',cancelled:'已取消',expired:'已过期'};
  top.append(title,walletElement('span',`order-status order-${order.status}`,labels[order.status] || '待核对'));card.append(top);
  const bottom=walletElement('div','recharge-order-bottom');const meta=walletElement('div','');
  meta.append(walletElement('span','',new Date(order.created*1000).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})),walletElement('span','order-number','订单号 '+order.id));bottom.append(meta);
  if(order.status==='awaiting_payment'){
    const cancel=walletElement('button','order-cancel','取消订单');cancel.type='button';
    cancel.onclick=async()=>{
      const epoch=rechargeEpoch,owner=MedixAuth.user?.id;cancel.disabled=true;
      try{
        const response=await MedixAuth.fetch(`/api/wallet/orders/${order.id}/cancel`,{method:'POST',body:'{}'});
        if(!response.ok)throw new Error((await response.json()).detail || '取消未完成');
        if(epoch!==rechargeEpoch || owner!==MedixAuth.user?.id)return;await loadRechargeOrders(true);
      }catch(error){if(epoch===rechargeEpoch && owner===MedixAuth.user?.id){toast(error.message);cancel.disabled=false;}}
    };
    bottom.append(cancel);
  }
  card.append(bottom);return card;
}
async function loadRechargeOrders(reset=false){
  const epoch=rechargeEpoch,owner=MedixAuth.user?.id;if(!owner)return;
  if(reset){ordersOffset=0;$('walletOrders').replaceChildren(walletElement('p','wallet-empty','正在读取订单…'));$('walletOrdersMore').hidden=true;}
  const offset=ordersOffset;$('walletOrdersMore').disabled=true;
  try{
    const response=await MedixAuth.fetch(`/api/wallet/orders?offset=${offset}`);if(!response.ok)throw new Error();const data=await response.json();
    if(epoch!==rechargeEpoch || owner!==MedixAuth.user?.id)return;
    if(reset)$('walletOrders').replaceChildren();
    if(!offset && !data.orders.length)$('walletOrders').append(walletElement('p','wallet-empty','还没有充值订单，愿每一次关心都从容。'));
    data.orders.forEach(order=>$('walletOrders').append(rechargeOrderCard(order)));ordersOffset=data.next_offset;
    $('walletOrdersMore').hidden=!data.has_more;$('walletOrdersMore').textContent='查看更多订单';
  }catch{
    if(epoch!==rechargeEpoch || owner!==MedixAuth.user?.id)return;
    if(reset)$('walletOrders').replaceChildren(walletElement('p','wallet-empty','订单暂时无法加载，请稍后重试。'));
    $('walletOrdersMore').hidden=false;$('walletOrdersMore').textContent='重新加载';
  }finally{if(epoch===rechargeEpoch)$('walletOrdersMore').disabled=false;}
}
$('walletOrdersMore').onclick=()=>loadRechargeOrders(ordersOffset===0);
$('rechargeCreate').onclick=async()=>{
  if(!selectedRecharge || !MedixAuth.user)return;
  const epoch=rechargeEpoch,owner=MedixAuth.user.id,plan=selectedRecharge;
  rechargeRequest ||= crypto.randomUUID();const requestId=rechargeRequest;
  $('rechargeCreate').disabled=true;$('rechargeFeedback').textContent='正在创建订单…';
  try{
    const response=await MedixAuth.fetch('/api/wallet/orders',{method:'POST',body:JSON.stringify({plan_id:plan,request_id:requestId})});
    const data=await response.json();if(!response.ok)throw new Error(data.detail || '订单未能创建，请稍后重试。');
    if(epoch!==rechargeEpoch || owner!==MedixAuth.user?.id)return;
    rechargeRequest=null;$('rechargeFeedback').textContent='订单已保存，暂未开放付款，关怀点余额未变。';
    await loadRechargeOrders(true);if(epoch===rechargeEpoch && owner===MedixAuth.user?.id)walletTab('orders');
  }catch(error){if(epoch===rechargeEpoch && owner===MedixAuth.user?.id)$('rechargeFeedback').textContent=typeof error.message==='string'?error.message:'订单未能创建，请稍后重试。';}
  finally{if(epoch===rechargeEpoch)$('rechargeCreate').disabled=!selectedRecharge;}
};
// Settings previews share the answer player, including stop and stale-response guards.
window.MedixVoice = Object.freeze({
  preview: (profile_id, tone, button) => speakAnswer('试听', button, {profile_id, tone}),
  stop: stopSpeaking,
  stopPreview: () => { if (state.speakingButton?.id === 'rpVoicePreview') stopSpeaking(); }
});

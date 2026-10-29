/* Independent feature; identity/CSRF are owned by MedixAuth. No health data in localStorage. */
(() => {
  const tools = document.createElement('section'); tools.className = 'health-profile-tools';
  tools.innerHTML = `<button type="button" id="hpOpen">我的健康档案</button><label><input type="checkbox" id="hpUse" disabled>本次为本人咨询，参考已确认档案</label><small id="hpStatus">登录后可编辑；默认不使用档案</small>`;
  document.querySelector('.composer-region').prepend(tools);
  const dialog = document.createElement('dialog'); dialog.id = 'healthProfileDialog'; dialog.className = 'health-profile-dialog'; dialog.setAttribute('aria-labelledby','hpTitle');
  dialog.innerHTML = `<div class="hp-heading"><h2 id="hpTitle">我的健康档案</h2><button type="button" id="hpClose">关闭</button></div>
  <p>仅记录本人信息。保存后请逐项核对并主动确认。病历图片、模型推断不会自动写入；未知不等于没有疾病、过敏或用药。记录年龄为填写时年龄，不自动推算。</p>
  <p>档案保存在本机账号数据库。仅在勾选“本次为本人咨询”时，随问题发给配置的模型服务，并暂停本轮云端记忆。请勿用于他人的报告；历史记录不代表当前诊断或正在用药。</p>
  <form id="hpForm"><div class="hp-basics"><label>记录年龄<input id="hpAge" type="number" min="0" max="130" step="1" placeholder="未知可留空"></label><label>性别<select id="hpSex"><option value="unknown">未知</option><option value="female">女</option><option value="male">男</option><option value="other">其他</option><option value="undisclosed">不愿透露</option></select></label></div><div id="hpGroups"></div><p id="hpMeta"></p><div class="hp-actions"><button type="submit" id="hpSave">保存为待确认草稿</button><button type="button" id="hpReload">重新加载</button></div></form>
  <div class="hp-confirm"><label><input type="checkbox" id="hpAck">我已核对已保存的各项内容，理解它们是自述历史记录，不能代表当前情况。</label><button type="button" id="hpConfirm" disabled>确认已保存的档案</button></div>
  <details><summary>清空档案</summary><p>清空本账号的结构化档案并作废确认。不会删除其他模块的聊天或云端记忆。</p><button type="button" id="hpDelete">清空我的档案</button></details><p id="hpFeedback" role="status" aria-live="polite"></p>`;
  document.body.append(dialog);
  const el = id => document.getElementById(id), names = {conditions:'基础病史',allergies:'过敏记录',medications:'用药记录'};
  let record = null, identity = null, epoch = 0, dirty = false, working = false, chatBusy = false;
  const date = value => value ? new Date(value*1000).toLocaleString() : '未确认';
  const feedback = text => { el('hpFeedback').textContent = text; };
  function availability() {
    const usable = !!record?.usable && !dirty && !working && !chatBusy;
    el('hpUse').disabled = !usable; if (!usable) el('hpUse').checked = false;
    el('hpOpen').disabled = chatBusy;
    el('hpConfirm').disabled = !record?.revision || dirty || working || !el('hpAck').checked;
    el('hpForm').querySelectorAll('input,select,button').forEach(node => { node.disabled = working || !identity; });
    el('hpDelete').disabled = working || !record?.revision;
    const labels = {empty:'尚未建立档案',draft:'草稿待确认',confirmed:'已确认',review_required:'距确认超过90天，请重新核对'};
    el('hpStatus').textContent = identity ? `${labels[record?.status] || '正在读取'}；每次提问单独勾选，使用档案时暂停云端记忆` : '登录后可编辑；默认不使用档案';
  }
  function changed() { dirty = true; el('hpAck').checked = false; el('hpMeta').textContent = '有未保存修改，请先保存草稿，再核对确认。'; availability(); }
  function input(row,key,label,value='',max=160) {
    const wrap = document.createElement('label'); wrap.textContent = label;
    const node = document.createElement('input'); node.dataset.field = key; node.value = value; node.maxLength = max; node.required = key === 'name'; wrap.append(node); row.append(wrap);
  }
  function addRow(field,item={}) {
    const list = el(`hp-${field}-items`); if (list.children.length >= 20) { feedback('每类最多20条记录。'); return; }
    const row = document.createElement('div'); row.className = 'hp-item'; input(row,'name',field === 'medications' ? '药品名称' : '名称',item.name,80);
    const wrap = document.createElement('label'); wrap.textContent = '记录性质'; const select = document.createElement('select'); select.dataset.field = 'status';
    for (const [value,text] of [['reported','曾报告 / 待核对现状'],['historical','明确为历史记录'],['unknown','不确定']]) { const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option); }
    select.value = item.status || 'reported'; wrap.append(select); row.append(wrap);
    if (field === 'medications') { input(row,'dose','记录剂量（可空）',item.dose,60); input(row,'frequency','记录频次（可空）',item.frequency,60); }
    input(row,'note','补充说明 / 病历日期（可空）',item.note);
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '移除条目'; remove.onclick = () => { row.remove(); if (!list.children.length) el(`hp-${field}-status`).value = 'unknown'; changed(); }; row.append(remove); list.append(row);
  }
  for (const [field,label] of Object.entries(names)) {
    const group = document.createElement('fieldset'); group.innerHTML = `<legend>${label}</legend><label>记录状态<select id="hp-${field}-status"><option value="unknown">未知 / 未填写</option><option value="none_reported">本人自述无记录</option><option value="reported">有记录（请填写条目）</option></select></label><div id="hp-${field}-items"></div><button type="button" id="hp-${field}-add">添加${label}</button>`; el('hpGroups').append(group);
    el(`hp-${field}-add`).onclick = () => { el(`hp-${field}-status`).value = 'reported'; addRow(field); changed(); };
    el(`hp-${field}-status`).onchange = event => { if (event.target.value !== 'reported') el(`hp-${field}-items`).replaceChildren(); else if (!el(`hp-${field}-items`).children.length) addRow(field); changed(); };
  }
  function render(data) {
    record = data; dirty = false; el('hpUse').checked = false; el('hpAck').checked = false; el('hpAge').value = data.data.age ?? ''; el('hpSex').value = data.data.sex;
    for (const field of Object.keys(names)) { el(`hp-${field}-status`).value = data.data[field].status; el(`hp-${field}-items`).replaceChildren(); data.data[field].items.forEach(item => addRow(field,item)); }
    el('hpMeta').textContent = `版本 ${data.revision} · 保存：${date(data.updated_at)} · 主动确认：${date(data.confirmed_at)}`; availability();
  }
  async function request(path,options={}) {
    const mine = epoch, actor = identity; if (!actor || actor !== MedixAuth.user?.id) throw new Error('请先登录当前账号。');
    const response = await MedixAuth.fetch(path,options);
    if (mine !== epoch || actor !== MedixAuth.user?.id) throw new Error('账号已切换，请重新操作。');
    if (!response.ok) throw new Error(await MedixAuth.detail(response)); return response.json();
  }
  async function operate(path,options,message) {
    const mine = epoch; working = true; availability();
    try { const data = await request(path,options); if (mine === epoch) { render(data); feedback(message); } }
    catch (error) { if (mine === epoch) { el('hpUse').checked = false; feedback(error.message); } }
    finally { if (mine === epoch) { working = false; availability(); } }
  }
  const load = () => operate('/api/profile',{},'请逐项核对，再决定是否确认。');
  const mutate = (path,method,body,message) => operate(path,{method,body:JSON.stringify(body)},message);
  el('hpOpen').onclick = async () => { if (!await MedixAuth.requireLogin()) return; dialog.showModal(); await load(); };
  el('hpClose').onclick = () => dialog.close(); el('hpReload').onclick = load;
  el('hpForm').addEventListener('input',changed); el('hpAck').onchange = availability;
  el('hpForm').onsubmit = event => {
    event.preventDefault(); const data = {age:el('hpAge').value === '' ? null : Number(el('hpAge').value),sex:el('hpSex').value};
    for (const field of Object.keys(names)) data[field] = {status:el(`hp-${field}-status`).value,items:[...el(`hp-${field}-items`).children].map(row => Object.fromEntries([...row.querySelectorAll('[data-field]')].map(node => [node.dataset.field,node.value.trim()])))};
    mutate('/api/profile','PUT',{expected_revision:record?.revision || 0,data},'草稿已保存，尚不会用于检索。请核对后主动确认。');
  };
  el('hpConfirm').onclick = () => mutate('/api/profile/confirm','POST',{expected_revision:record.revision,acknowledged:true},'档案已确认。需要时在每次发送前勾选“本次为本人咨询”。');
  el('hpDelete').onclick = () => { if (record?.revision && confirm('确认清空本人结构化健康档案？旧档案将不能再用于新请求。')) mutate('/api/profile','DELETE',{expected_revision:record.revision},'档案内容已清空，旧确认已作废。'); };
  function reset() {
    epoch++; record = null; identity = null; dirty = false; working = false; el('hpForm').reset(); for (const field of Object.keys(names)) el(`hp-${field}-items`).replaceChildren(); el('hpAck').checked = false; el('hpUse').checked = false; el('hpMeta').textContent = ''; feedback(''); dialog.close(); availability();
  }
  function authChanged(user) { if ((user?.id || null) === identity) return; reset(); identity = user?.id || null; availability(); if (identity) load(); }
  window.addEventListener('medix-signout',reset); window.addEventListener('medix-auth-change',event => authChanged(event.detail)); MedixAuth.ready.then(authChanged).catch(reset);
  window.MedixProfile = {
    setBusy(value) { chatBusy = value; availability(); },
    choice() { if (!el('hpUse').checked) return {use_profile:false}; if (!record?.usable || dirty || identity !== MedixAuth.user?.id) throw new Error('请先保存并确认当前账号的档案。'); const result = {use_profile:true,profile_revision:record.revision}; el('hpUse').checked = false; return result; }
  };
  availability();
})();

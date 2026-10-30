/* Report import, evidence review and profile history. Never stores health records in browser storage. */
(() => {
  const sameRecord=(a,b)=>a.normalize('NFKC').replace(/\s/g,'').toLowerCase()===b.normalize('NFKC').replace(/\s/g,'').toLowerCase();
  const base=document.getElementById('healthProfileDialog');
  const open=document.createElement('button'); open.type='button';open.id='peOpen';open.textContent='从病历提取 / 历史版本 / 导出';
  base.querySelector('.hp-heading').after(open);
  const dialog=document.createElement('dialog');dialog.id='profileEvolutionDialog';dialog.className='health-profile-dialog';dialog.setAttribute('aria-labelledby','peTitle');
  dialog.innerHTML=`<div class="hp-heading"><h2 id="peTitle">病历与本人自述更新</h2><button type="button" id="peClose">关闭</button></div>
  <p>先确认病历归属和日期，再提取候选。提取不等于确诊；不清晰或疑似条目需要额外核对，所有选项默认不采纳。</p>
  <form id="peForm"><label>信息来源<select id="peMode"><option value="report">病历文字或图片</option><option value="conversation">本人对话自述（未经医学核实）</option></select></label><label>信息名称<input id="peLabel" required maxlength="100" placeholder="例如：2025年门诊记录"></label><label>病历日期<input type="date" id="peDate" required></label>
  <label>原始描述 / 病历文字<textarea id="peText" maxlength="12000" rows="5" placeholder="粘贴病历原文；也可添加图片"></textarea></label>
  <label>病历图片（PNG / JPEG / WebP，最多3张，每张8MB）<input id="peFiles" type="file" accept="image/png,image/jpeg,image/webp" multiple></label>
  <label class="pe-check"><input type="checkbox" id="peSelf" required>我确认描述属于本人实际经历，不是假设或他人情况；病历日期已核对</label>
  <label class="pe-check"><input type="checkbox" id="peConsent" required>我同意将上述文字与图片发送给配置的模型服务进行提取</label>
  <button type="submit">提取候选信息</button></form>
  <section id="peReview" hidden><h3>逐项对比并采纳</h3><p>年龄为病历日期时的年龄。旧用药默认历史记录，不能推定仍在使用。仅同名记录可更新；不同内容请追加，未选内容保持原样。</p><div id="peCandidates"></div><button type="button" id="peApply">将选中项保存为待确认草稿</button><button type="button" id="peDiscard">丢弃候选</button></section>
  <hr><h3>档案维护</h3><button type="button" id="peHistory">加载最近50个版本</button><button type="button" id="peExport">导出当前档案 JSON</button><div id="peVersions"></div><p id="peFeedback" role="status" aria-live="polite"></p>`;
  document.body.append(dialog);
  const el=id=>document.getElementById(id), labels={age:'年龄',sex:'性别',conditions:'基础病史',allergies:'过敏记录',medications:'用药记录',symptoms:'症状与近期身体状况',followups:'建议与待核实事项（非病情事实）'};
  let identity=null,epoch=0,busy=false,record=null,batch=null;
  function message(value){el('peFeedback').textContent=value;}
  function lock(value){busy=value;dialog.querySelectorAll('button,input,select,textarea').forEach(node=>{if(node.id!=='peClose')node.disabled=value;});}
  async function api(path,options={}){
    const actor=identity,mine=epoch;
    if(!actor || actor!==MedixAuth.user?.id)throw new Error('请登录当前账号。');
    const response=await MedixAuth.fetch(path,options);
    if(mine!==epoch || actor!==MedixAuth.user?.id)throw new Error('账号已切换，请重新操作。');
    if(!response.ok)throw new Error(await MedixAuth.detail(response));
    return response.status===204 ? null : response.json();
  }
  async function run(action){if(busy)return;const mine=epoch;lock(true);try{await action(mine);}catch(error){if(mine===epoch)message(error.message);}finally{if(mine===epoch)lock(false);}}
  function clear(){epoch++;identity=MedixAuth.user?.id || null;record=null;batch=null;busy=false;el('peForm').reset();el('peCandidates').replaceChildren();el('peVersions').replaceChildren();el('peReview').hidden=true;message('');dialog.close();lock(false);}
  function present(value){
    const words={unknown:'未知 / 未填写',none_reported:'本人自述无记录',reported:'曾报告，现状待核对',historical:'历史记录',current:'本人在确认时自述当前使用 / 存在',stopped:'本人自述已停用',female:'女',male:'男',other:'其他',undisclosed:'不愿透露'};
    if(value==null)return '未知';
    if(typeof value!=='object')return words[value] || String(value);
    if(Array.isArray(value.items))return `${words[value.status] || value.status}\n${value.items.map(present).join('\n\n') || '无已填写条目'}`;
    if(value.name)return [value.name,'记录性质：'+(words[value.status] || value.status),value.dose?'记录剂量：'+value.dose:'',value.frequency?'记录频次：'+value.frequency:'',value.note?'说明：'+value.note:'',value.source?`来源：${value.source.label} / ${value.source.report_date || '日期未知'}`:''].filter(Boolean).join('\n');
    if('age' in value)return Object.keys(labels).map(field=>labels[field]+'：\n'+present(value[field])).join('\n\n');
    return '暂无可展示内容';
  }
  function renderBatch(){
    el('peCandidates').replaceChildren();el('peReview').hidden=false;
    for(const candidate of batch.candidates){
      const card=document.createElement('fieldset');card.dataset.candidate=candidate.id;
      const title=document.createElement('legend');title.textContent=labels[candidate.field]+(candidate.uncertain?' · 不确定，须核对':'');card.append(title);
      const choose=document.createElement('label');choose.className='pe-check';const checked=document.createElement('input');checked.type='checkbox';checked.dataset.role='selected';choose.append(checked,document.createTextNode('采纳这一项'));card.append(choose);
      for(const [label,value] of [['新候选',candidate.value],['现有记录',candidate.existing],['原文依据',candidate.evidence],['来源 / 日期',candidate.source.label+' / '+candidate.source.report_date]]){
        const heading=document.createElement('strong');heading.textContent=label;const pre=document.createElement('pre');pre.textContent=present(value);card.append(heading,pre);
      }
      const select=document.createElement('select');select.dataset.role='action';select.setAttribute('aria-label','采纳方式');
      const add=(value,text)=>{const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);};
      if(['age','sex'].includes(candidate.field))add('replace','明确替换基础字段');
      else {add('append',candidate.existing?.status==='none_reported'?'追加（将自述无记录改为有记录）':'追加并保留旧条目');(candidate.existing?.items||[]).forEach((item,index)=>{if(sameRecord(item.name,candidate.value.name))add('replace:'+index,`更新同名记录：${item.name}`);});}
      card.append(select);
      if(select.children.length===1){
        select.hidden=true;
        const explanation=document.createElement('p');explanation.className='profile-apply-note';
        explanation.textContent=['age','sex'].includes(candidate.field)?'采纳后将更新'+labels[candidate.field]+'，原值可在历史版本中查看。':(candidate.existing?.status==='none_reported'?'采纳后追加保存，并将“自述无记录”改为“有记录”。':'采纳后追加保存，保留已有记录。');
        card.append(explanation);
      }
      if(candidate.uncertain){const label=document.createElement('label');label.className='pe-check';const ack=document.createElement('input');ack.type='checkbox';ack.dataset.role='uncertainty';label.append(ack,document.createTextNode('我已核对这条不确定内容；它仍作为待核对记录保存'));card.append(label);}
      el('peCandidates').append(card);
    }
    message(batch.candidates.length ? '请选择需要采纳的候选。保存后仍需回到档案页面主动确认。' : '没有提取到有原文依据的候选，请检查原文或手动填写。');
  }
  open.onclick=()=>run(async mine=>{if(!await MedixAuth.requireLogin())return;identity=MedixAuth.user.id;record=await api('/api/profile');if(mine!==epoch)return;dialog.showModal();message('当前档案版本 '+record.revision+'。本页面不会自动采纳任何字段。');});
  window.MedixConversationUpdate=async text=>{
    if(!await MedixAuth.requireLogin())return;
    if(batch){dialog.showModal();message('请先采纳或丢弃当前候选，再整理新的对话。');return;}
    identity=MedixAuth.user.id;el('peMode').value='conversation';el('peLabel').value='本人对话自述';el('peDate').value=new Date().toLocaleDateString('en-CA');el('peDate').required=false;el('peText').value=text || '';el('peFiles').value='';el('peSelf').checked=false;el('peConsent').checked=false;dialog.showModal();message('请确认这是本人实际经历，并授权整理。系统无法核实病情真伪，不会自动保存或确诊。');
  };
  el('peMode').onchange=()=>{el('peDate').required=el('peMode').value==='report';};
  el('peClose').onclick=()=>dialog.close();
  el('peForm').onsubmit=event=>{event.preventDefault();run(async mine=>{
    if(batch){message('请先丢弃或采纳当前候选，再重新提取。');return;}
    record=await api('/api/profile');const files=[...el('peFiles').files];
    if(files.length>3 || files.some(file=>file.size>8*1024*1024 || !['image/png','image/jpeg','image/webp'].includes(file.type)))throw new Error('请使用最多3张PNG、JPEG或WebP图片，每张不超过8MB。');
    const images=await Promise.all(files.map(file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('图片读取失败'));reader.readAsDataURL(file);})));if(mine!==epoch)return;
    message('正在提取，请稍候。提取不修改档案。');
    const conversation=el('peMode').value==='conversation';
    if(conversation && images.length)throw new Error('对话更新只整理用户文字；图片请选病历模式。');
    const payload=conversation ? {text:el('peText').value.trim(),subject:'self',consent_to_model:el('peConsent').checked,expected_revision:record.revision} : {text:el('peText').value.trim(),images,label:el('peLabel').value.trim(),report_date:el('peDate').value,subject:'self',consent_to_model:el('peConsent').checked,expected_revision:record.revision};
    const result=await api(conversation?'/api/profile/conversation-candidates':'/api/profile/imports',{method:'POST',body:JSON.stringify(payload)});
    if(mine!==epoch)return;batch=result;el('peFiles').value='';el('peText').value='';renderBatch(); if(result.clarifications?.length)message(result.clarifications.join('；')+'。请补充清晰描述后重新提取，不能直接作为档案事实。');
  });};
  el('peApply').onclick=()=>run(async mine=>{
    const selections=[...el('peCandidates').children].filter(card=>card.querySelector('[data-role=selected]').checked).map(card=>{const value=card.querySelector('[data-role=action]').value;return {candidate_id:card.dataset.candidate,action:value.split(':')[0],target_index:value.includes(':')?Number(value.split(':')[1]):null,acknowledge_uncertainty:card.querySelector('[data-role=uncertainty]')?.checked||false};});
    if(!selections.length)throw new Error('请至少选择一项；不需要的候选可直接丢弃。');
    const result=await api('/api/profile/imports/'+batch.id+'/apply',{method:'POST',body:JSON.stringify({expected_revision:batch.base_revision,selections})});if(mine!==epoch)return;
    record=result;batch=null;el('peCandidates').replaceChildren();el('peReview').hidden=true;
    window.dispatchEvent(new Event('medix-profile-updated'));message('已保存为草稿 v'+record.revision+'。关闭本窗口，逐项核对并重新确认后才能用于对话。');
  });
  el('peDiscard').onclick=()=>run(async mine=>{if(!batch)return;await api('/api/profile/imports/'+batch.id,{method:'DELETE',body:'{}'});if(mine!==epoch)return;batch=null;el('peCandidates').replaceChildren();el('peReview').hidden=true;message('候选已丢弃，未修改档案。');});
  el('peHistory').onclick=()=>run(async mine=>{
    const result=await api('/api/profile/history');if(mine!==epoch)return;el('peVersions').replaceChildren();
    for(const item of result.items){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=`v${item.revision} · ${new Date(item.saved_at*1000).toLocaleString()} · ${({baseline:"升级前基线",edit:"手工修改",report_import:"病历采纳",restore:"恢复旧版",clear:"清空档案"}[item.action] || "档案保存")} · ${item.confirmed_at?'曾确认':'待确认'}`;const pre=document.createElement('pre');pre.textContent=present(item.data);const button=document.createElement('button');button.type='button';button.textContent='将此版本恢复为新草稿';button.onclick=()=>run(async mine=>{const current=await api('/api/profile');const restored=await api('/api/profile/restore',{method:'POST',body:JSON.stringify({expected_revision:current.revision,target_revision:item.revision})});if(mine!==epoch)return;record=restored;window.dispatchEvent(new Event('medix-profile-updated'));message('已恢复为新草稿 v'+record.revision+'，请核对并重新确认。');});details.append(summary,pre,button);el('peVersions').append(details);}
    message(result.items.length?'恢复版本会生成待确认草稿，不会自动授权。':'暂无历史版本。');
  });
  el('peExport').onclick=()=>run(async mine=>{const data=await api('/api/profile/export');if(mine!==epoch)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='medix-health-profile.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('当前档案已导出到下载目录，请妥善保存。');});
  window.addEventListener('medix-signout',clear);window.addEventListener('medix-auth-change',event=>{if((event.detail?.id||null)!==identity)clear();});MedixAuth.ready.then(()=>{identity=MedixAuth.user?.id||null;});
})();

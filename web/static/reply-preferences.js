/* Account preferences: explicit save, no browser persistence or clinical profile writes. */
(() => {
  const open=document.getElementById('voicePreferencesOpen');
  const dialog=document.createElement('dialog');dialog.id='replyPreferencesDialog';dialog.setAttribute('aria-labelledby','rpTitle');
  dialog.innerHTML=`<header><div><small>让回答更适合你</small><h2 id="rpTitle">回答偏好</h2></div><button type="button" id="rpClose">关闭</button></header>
  <p class="rp-intro">设置称呼、语气、阅读方式与播报声音。健康信息仍在“我的健康档案”中管理，使用时需要单独授权。</p>
  <form id="rpForm"><label class="rp-enable"><input type="checkbox" name="enabled">在后续问答中使用已保存的回答偏好</label>
  <section><h3>怎么称呼、怎么说</h3><div class="rp-grid">
  <label>称呼我<input name="nickname" maxlength="20" placeholder="可留空，例如：小林" autocomplete="off"></label>
  <label>沟通语气<select name="tone"><option value="neutral">客观平和</option><option value="supportive">温和鼓励</option><option value="direct">直接清楚</option></select></label>
  <label>回答详略<select name="detail"><option value="brief">简短重点</option><option value="standard">适中解释</option><option value="detailed">详细说明</option></select></label>
  <label>建议呈现<select name="format"><option value="summary_first">先结论，再依据与下一步</option><option value="steps">分步骤行动建议</option><option value="explanation">解释原因与选择依据</option></select></label>
  <label>术语程度<select name="terminology"><option value="plain">通俗易懂</option><option value="professional">可使用专业术语</option></select></label>
  <label>个性化声音<select name="voice_profile" aria-describedby="rpVoiceHint"><option value="child">默认</option><option value="gentle">柔和女声</option><option value="clear">明亮男声</option><option value="steady">平和女声</option></select></label></div>
  <div class="rp-voice-listen"><button type="button" id="rpVoicePreview" aria-pressed="false"><svg aria-hidden="true"><use href="#i-volume"/></svg><span>试听当前声音</span></button><p id="rpVoiceHint" role="status" aria-live="polite"></p></div>
  </section>
  <section><h3>再了解一点你的偏好</h3><label>希望怎样和你沟通 <span>选填 · 最多200字</span><textarea name="communication_note" maxlength="200" rows="3" placeholder="例如：先告诉我最重要的一件事，再解释原因；避免过多寒暄。"></textarea></label>
  <label>日常安排与执行偏好 <span>选填 · 最多200字</span><textarea name="daily_context" maxlength="200" rows="3" placeholder="例如：工作日时间紧，希望建议拆成每次5分钟可完成的步骤。疾病、过敏和用药请填入健康档案。"></textarea></label></section>
  <p class="rp-hint">勾选上方开关并保存后，文字偏好从下次提问生效，声音从下次播报生效；已有回答不会自动改写。温和表达不会省略必要的风险提示，偏好也不代表疾病诊断。启用时，本轮暂停云端记忆。</p>
  <footer><button type="submit" id="rpSave">保存回答偏好</button><button type="button" id="rpReset">恢复默认并关闭偏好</button></footer></form><p id="rpStatus" role="status" aria-live="polite"></p>`;
  document.body.append(dialog);
  const form=dialog.querySelector('form'),status=dialog.querySelector('#rpStatus');
  let revision=0,epoch=0,actor=null,busy=false,loaded=false,catalog=null,catalogRequest=0;
  const preview=dialog.querySelector('#rpVoicePreview'),summary=document.getElementById('voicePreferenceSummary');
  const defaults={enabled:false,nickname:'',tone:'neutral',detail:'standard',format:'summary_first',terminology:'plain',communication_note:'',daily_context:'',voice_profile:'child'};
  const voiceLabels={child:'默认',gentle:'柔和女声',clear:'明亮男声',steady:'平和女声'};
  const legacyToneVoices={neutral:'steady',supportive:'gentle',direct:'clear'};
  function saveLabel(){dialog.querySelector('#rpSave').textContent=form.elements.namedItem('enabled').checked?'保存并启用回答偏好':'仅保存设置（尚未启用）';}
  form.elements.namedItem('enabled').addEventListener('change',saveLabel);
  function render(data){const values={...defaults,...data};if(values.voice_profile==='auto')values.voice_profile=legacyToneVoices[values.tone] || 'steady';for(const [key,value] of Object.entries(values)){const node=form.elements.namedItem(key);if(!node)continue;if(node.type==='checkbox')node.checked=value;else node.value=value;}saveLabel();updateVoiceHint();}
  function lock(value){busy=value;form.querySelectorAll('input,select,textarea,button').forEach(node=>{node.disabled=value;});}
  function updateVoiceHint(){
    const selected=form.elements.namedItem('voice_profile').value || 'child';
    const voice=catalog?.profiles.find(item=>item.id===selected);
    dialog.querySelector('#rpVoiceHint').textContent=voice
      ? `${voiceLabels[selected]} · ${voice.description}`
      : '选择喜欢的声音，点击试听。';
  }
  form.addEventListener('change',()=>{window.MedixVoice?.stopPreview();updateVoiceHint();});
  preview.onclick=()=>window.MedixVoice?.preview(form.elements.namedItem('voice_profile').value,form.elements.namedItem('tone').value,preview);
  async function refreshVoices(){
    const owner=MedixAuth.user?.id,mine=epoch,query=++catalogRequest;
    if(!owner){if(summary)summary.textContent='默认男童声音 · 登录后可设置回答偏好。';return;}
    try{
      const response=await MedixAuth.fetch('/api/voice/voices');
      if(!response.ok)throw new Error('voice catalog unavailable');
      const result=await response.json();
      if(mine!==epoch || query!==catalogRequest || MedixAuth.user?.id!==owner)return;
      catalog=result;
      if(summary)summary.textContent=`${result.effective.follows_tone?'跟随沟通语气 · ':''}${voiceLabels[result.effective.id] || result.effective.label} · 可在回答偏好中调整。`;
      updateVoiceHint();
    }catch{if(mine===epoch && query===catalogRequest && summary)summary.textContent='云端自然语音 · 可在回答偏好中设置，声音以播报时的账号偏好为准。';}
  }
  async function request(options={}){
    const mine=epoch,owner=actor;
    if(!owner || owner!==MedixAuth.user?.id)throw new Error('请先登录当前账号。');
    const response=await MedixAuth.fetch('/api/profile/reply-preferences',options);
    if(mine!==epoch || owner!==MedixAuth.user?.id)throw new Error('账号已变化，请重新打开偏好设置。');
    if(!response.ok)throw new Error(await MedixAuth.detail(response));
    const data=await response.json();
    if(mine!==epoch || owner!==MedixAuth.user?.id)throw new Error('账号已变化，请重新打开偏好设置。');
    return data;
  }
  async function persist(data){
    if(!loaded)return;
    const mine=epoch;lock(true);status.textContent='正在保存…';
    try{const result=await request({method:'PUT',body:JSON.stringify({expected_revision:revision,data})});revision=result.revision;render(result.data);window.MedixVoice?.stop();refreshVoices();status.textContent=data.enabled?'已启用 v'+result.revision+'，文字偏好从下次提问生效，声音从下次播报生效。':'设置已保存，但偏好开关关闭：回答使用默认表达，播报使用默认声音。请勾选开关，再点击“保存并启用回答偏好”。';}
    catch(error){if(mine===epoch)status.textContent=error.message;}
    finally{if(mine===epoch)lock(false);}
  }
  open.onclick=async()=>{
    if(!await MedixAuth.requireLogin())return;
    actor=MedixAuth.user.id;loaded=false;const mine=epoch;dialog.showModal();lock(true);status.textContent='正在读取当前账号的偏好…';
    try{const result=await request();revision=result.revision;loaded=true;refreshVoices();render(result.data);status.textContent=result.data.enabled?'已启用 v'+result.revision+'；修改后请保存，声音从下次播报生效。':'当前未启用。请勾选上方开关并保存，设置才会用于下一次回答。';}
    catch(error){if(mine===epoch)status.textContent=error.message;return;}
    finally{if(mine===epoch)lock(!loaded);}
  };
  dialog.querySelector('#rpClose').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>window.MedixVoice?.stopPreview());
  form.onsubmit=event=>{event.preventDefault();if(busy)return;const data=Object.fromEntries(new FormData(form));data.enabled=form.elements.namedItem('enabled').checked;persist(data);};
  dialog.querySelector('#rpReset').onclick=()=>{if(!busy)persist(defaults);};
  function reset(){epoch++;catalog=null;window.MedixVoice?.stopPreview();loaded=false;revision=0;actor=MedixAuth.user?.id || null;render(defaults);status.textContent='';lock(false);dialog.close();}
  window.addEventListener('medix-signout',reset);
  window.addEventListener('medix-auth-change',event=>{if((event.detail?.id || null)!==actor)reset();refreshVoices();});
  render(defaults);
  Promise.resolve(MedixAuth.ready).then(refreshVoices);
})();

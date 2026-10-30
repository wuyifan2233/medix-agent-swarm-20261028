/* Inline, opt-in selection of facts from the user's message; never auto-saves. */
(() => {
  const labels={age:'年龄',sex:'性别',conditions:'本人自述诊断',allergies:'过敏',medications:'用药',symptoms:'症状与近期身体状况'};
  const sex={female:'女',male:'男',unknown:'未知',other:'其他',undisclosed:'不愿透露'};
  function showValue(value){
    if(value===null || value===undefined)return '未知';
    if(typeof value!=='object')return sex[value] || String(value);
    if(value.items)return value.items.length ? value.items.map(showValue).join('；') : (value.status==='none_reported'?'本人自述无记录':'未知 / 未填写');
    return [value.name,value.note,value.dose,value.frequency].filter(Boolean).join(' · ');
  }
  window.MedixInlineProfilePicker=(parent,text)=>{
    const panel=document.createElement('section');panel.className='conversation-profile-picker';
    panel.innerHTML='<h4>选择本轮哪些内容加入健康档案</h4><p>只整理你的本轮原话，不使用助手推断。病情真实性不能通过聊天核实，保存后仍需主动确认。</p><label><input type="checkbox" data-role="self">我确认拟加入的内容为本人实际经历，不是假设或他人情况</label><label><input type="checkbox" data-role="consent">同意将本轮描述发给模型筛选候选（会产生额外调用）</label><button type="button" data-role="extract">筛选本轮描述</button><div data-role="items"></div><button type="button" data-role="save" hidden>仅将选中项加入待确认草稿</button><button type="button" data-role="cancel">暂不加入</button><p role="status" aria-live="polite" data-role="status"></p>';
    parent.append(panel);
    const el=role=>panel.querySelector(`[data-role="${role}"]`),actor=MedixAuth.user?.id;
    let batch=null,busy=false,closed=false;
    const status=text=>{el('status').textContent=text;};
    function lock(value){busy=value;panel.querySelectorAll('input,select,button').forEach(node=>{node.disabled=value;});}
    async function api(path,options={}){
      if(!actor || MedixAuth.user?.id!==actor)throw new Error('账号已变化，请重新提问。');
      const response=await MedixAuth.fetch(path,options);
      if(MedixAuth.user?.id!==actor)throw new Error('账号已变化，已停止显示旧资料。');
      if(!response.ok)throw new Error(await MedixAuth.detail(response));
      return response.status===204?null:response.json();
    }
    async function discard(){if(batch){await api('/api/profile/imports/'+batch.id,{method:'DELETE',body:'{}'});batch=null;}}
    el('extract').onclick=async()=>{
      if(busy)return;
      if(!el('self').checked || !el('consent').checked){status('请先确认本人实际经历并授权筛选。');return;}
      lock(true);status('正在筛选，本步骤不会修改档案。');
      try{
        await discard();el('items').replaceChildren();el('save').hidden=true;
        const profile=await api('/api/profile');
        batch=await api('/api/profile/conversation-candidates',{method:'POST',body:JSON.stringify({text,subject:'self',consent_to_model:true,expected_revision:profile.revision})});
        if(closed){await discard();return;}
        for(const candidate of batch.candidates){
          const card=document.createElement('fieldset');card.dataset.id=candidate.id;
          const legend=document.createElement('legend');legend.textContent=labels[candidate.field] || candidate.field;
          const choice=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.dataset.role='chosen';choice.append(check,document.createTextNode('加入这一项：'+showValue(candidate.value)));
          const evidence=document.createElement('p');evidence.textContent='你的原话：'+candidate.evidence;
          const previous=document.createElement('p');previous.textContent='现有档案：'+showValue(candidate.existing);
          const modeLabel=document.createElement('label');modeLabel.textContent='加入方式';
          const mode=document.createElement('select');mode.dataset.role='mode';
          const option=(value,label)=>{const node=document.createElement('option');node.value=value;node.textContent=label;mode.append(node);};
          if(['age','sex'].includes(candidate.field))option('replace','明确替换此字段');
          else{option('append','追加并保留现有条目');(candidate.existing?.items || []).forEach((item,index)=>option('replace:'+index,'替换：'+item.name));}
          modeLabel.append(mode);card.append(legend,choice,evidence,previous,modeLabel);
          if(candidate.uncertain){const warning=document.createElement('label'),ack=document.createElement('input');ack.type='checkbox';ack.dataset.role='uncertain';warning.append(ack,document.createTextNode('这条信息存在不确定性，我已核对并同意作为不确定记录保存'));card.append(warning);}
          el('items').append(card);
        }
        el('save').hidden=!batch.candidates.length;
        status([batch.candidates.length?'所有项默认不加入，请逐项勾选；不勾选的内容不会保存。':'没有可直接采纳的本人信息。',...(batch.clarifications || [])].join(' '));
      }catch(error){status(error.message);}finally{lock(false);}
    };
    el('save').onclick=async()=>{
      if(busy || !batch)return;
      if(!el('self').checked){status('请确认拟加入的内容属于本人实际经历。');return;}
      const selections=[...el('items').children].filter(card=>card.querySelector('[data-role="chosen"]').checked).map(card=>{
        const mode=card.querySelector('select').value;
        return {candidate_id:card.dataset.id,action:mode.split(':')[0],target_index:mode.includes(':')?Number(mode.split(':')[1]):null,acknowledge_uncertainty:card.querySelector('[data-role="uncertain"]')?.checked || false};
      });
      if(!selections.length){status('没有选中任何内容；你也可以点击“暂不加入”。');return;}
      lock(true);
      try{
        const profile=await api('/api/profile/imports/'+batch.id+'/apply',{method:'POST',body:JSON.stringify({expected_revision:batch.base_revision,selections})});
        batch=null;el('items').replaceChildren();el('save').hidden=true;el('extract').hidden=true;
        el('cancel').textContent='关闭';status('选中内容已保存为待确认草稿 v'+profile.revision+'。请打开“我的健康档案”核对确认后再用于问答。');
        window.dispatchEvent(new Event('medix-profile-updated'));
      }catch(error){status(error.message);}finally{lock(false);}
    };
    el('cancel').onclick=async()=>{
      if(busy)return;lock(true);
      try{await discard();closed=true;panel.remove();}catch(error){status(error.message);lock(false);}
    };
    window.addEventListener('medix-signout',()=>{closed=true;batch=null;panel.remove();},{once:true});
    return panel;
  };
})();

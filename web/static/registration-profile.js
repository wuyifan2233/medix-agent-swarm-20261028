(() => {
 const tools=document.createElement('section');tools.className='health-profile-tools';
 tools.innerHTML='<button type="button" id="hpOpen">我的基本信息</button><small id="hpStatus">登录后查看基本信息</small>';
 document.querySelector('.composer-region').prepend(tools);
 const fields={age:'注册时年龄',sex:'性别',height_cm:'注册时身高',weight_kg:'注册时体重'};
 const dialog=document.createElement('dialog');dialog.className='health-profile-dialog';dialog.id='registrationProfileDialog';dialog.setAttribute('aria-labelledby','baselineTitle');
 dialog.innerHTML='<div class="hp-heading"><h2 id="baselineTitle">注册时身体基本信息</h2><button type="button" id="baselineClose">关闭</button></div><p>仅记录注册时的一般情况，不包含病情、过敏或用药。保存后不再更新，不能代表当前测量结果。</p><p id="baselineStamp"></p><dl id="baselineValues"></dl><p id="baselineFeedback" role="status"></p>';document.body.append(dialog);
 const use={checked:true,disabled:false},status=tools.querySelector('#hpStatus');let record=null,actor=null,epoch=0,busy=false;
 function availability(){status.textContent=!actor?'登录后查看基本信息':record?.usable?'注册信息默认用于个性化回答，记录只读':'未在注册时填写基本信息';}
 function render(){const values=dialog.querySelector('#baselineValues');values.replaceChildren();for(const [key,label] of Object.entries(fields)){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;const value=record?.data?.[key];dd.textContent=value==null||value==='undisclosed'?'未提供':key==='sex'?({female:'女',male:'男'}[value] || '未提供'):value+({age:' 岁',height_cm:' cm',weight_kg:' kg'}[key] || '');values.append(dt,dd);}dialog.querySelector('#baselineStamp').textContent=record?.confirmed_at?'记录日期：'+new Date(record.confirmed_at*1000).toLocaleString():'';dialog.querySelector('#baselineFeedback').textContent=record?.usable?'此记录不提供编辑、提取、追加或恢复操作。':'该账号未在注册时记录基本信息，旧病情档案不会在此显示，也不会自动用于问答。';}
 async function load(){const mine=epoch,owner=actor;if(!owner)return;try{const response=await MedixAuth.fetch('/api/profile');if(mine!==epoch || owner!==MedixAuth.user?.id)return;if(!response.ok)throw new Error(await MedixAuth.detail(response));record=await response.json();if(mine!==epoch)return;render();availability();}catch(error){if(mine===epoch){record=null;availability();dialog.querySelector('#baselineFeedback').textContent=error.message;}}}
 function auth(user){epoch++;actor=user?.id||null;record=null;use.checked=false;dialog.close();render();availability();if(actor)load();}
 tools.querySelector('#hpOpen').onclick=async()=>{if(!await MedixAuth.requireLogin())return;dialog.showModal();await load();};dialog.querySelector('#baselineClose').onclick=()=>dialog.close();
 window.addEventListener('medix-signout',()=>auth(null));window.addEventListener('medix-auth-change',event=>auth(event.detail));MedixAuth.ready.then(auth).catch(()=>auth(null));
 window.MedixProfile={setBusy(value){busy=value;},choice(){return {};}};availability();
})();

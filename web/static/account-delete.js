(() => {
const entry=document.createElement('button');entry.type='button';entry.className='account-delete-link';entry.textContent='申请注销';
entry.textContent='注销账号';
const save=document.querySelector('#settings-passwordForm > .settings-primary');
const actions=document.createElement('div');actions.className='security-form-actions';
save.before(actions);actions.append(save,entry);
const dialog=document.createElement('dialog');dialog.className='settings-dialog phone-dialog';
dialog.innerHTML='<div class="phone-dialog-heading"><h2>注销账号</h2><button type="button" aria-label="关闭注销">×</button></div><form><p class="sms-help">注销将永久删除当前账号、头像及登录会话，释放手机号。重新注册会创建全新账号，不能找回原账号资料和记忆。其他模块或外部服务保存的数据不保证随此操作删除。</p><label>手机验证码</label><div class="sms-code-row"><input autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required><button type="button">获取验证码</button></div><label>输入“注销账号”以确认</label><input autocomplete="off" required pattern="注销账号" placeholder="注销账号"><div class="avatar-crop-actions"><button type="button" class="settings-secondary">取消</button><button type="submit" class="settings-primary account-delete-confirm">永久注销账号</button></div><p class="settings-feedback" role="status"></p></form>';
document.body.append(dialog);
const form=dialog.querySelector('form'),inputs=form.querySelectorAll('input'),buttons=form.querySelectorAll('button'),status=form.querySelector('[role=status]');
let challenge='',until=0,sending=false,busy=false,generation=0;
entry.onclick=()=>dialog.showModal();dialog.querySelector('button').onclick=()=>dialog.close();buttons[1].onclick=()=>dialog.close();
dialog.addEventListener('close',()=>{generation++;challenge='';form.reset();status.textContent='';});
function tick(){const n=Math.max(0,Math.ceil((until-Date.now())/1000));buttons[0].disabled=sending||n>0;buttons[0].textContent=sending?'发送中…':n?`${n} 秒后重发`:'获取验证码';}
const timer=setInterval(tick,250);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
buttons[0].onclick=async()=>{if(sending||Date.now()<until)return;const mine=generation;sending=true;tick();try{const r=await MedixAuth.fetch('/api/auth/account/delete/send',{method:'POST',body:'{}'});if(r.status===429)until=Date.now()+(Number(r.headers.get('Retry-After'))||60)*1000;if(!r.ok)throw new Error(await MedixAuth.detail(r));const d=await r.json();until=Date.now()+d.retry_after*1000;if(mine===generation){challenge=d.challenge_id;status.textContent='验证码已发送，5 分钟内有效。';}}catch(e){if(mine===generation)status.textContent=e.message;}finally{sending=false;tick();}};
form.onsubmit=async e=>{e.preventDefault();if(busy)return;if(!challenge){status.textContent='请先获取验证码。';return;}busy=true;buttons[2].disabled=true;try{const r=await MedixAuth.fetch('/api/auth/account',{method:'DELETE',body:JSON.stringify({challenge_id:challenge,code:inputs[0].value,confirmation:inputs[1].value})});if(!r.ok)throw new Error(await MedixAuth.detail(r));dialog.close();document.getElementById('settingsDialog').close();MedixAuth.leave(true);}catch(e){status.textContent=e.message;}finally{busy=false;buttons[2].disabled=false;}};
function render(user){entry.hidden=!user||user.role==='admin';if(!user&&dialog.open)dialog.close();}
MedixAuth.ready.then(render).catch(()=>{});window.addEventListener('medix-auth-change',e=>render(e.detail));
})();

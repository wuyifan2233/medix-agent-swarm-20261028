(() => {
const name=document.getElementById('settings-displayName');
const edit=document.createElement('button');edit.type='button';edit.className='nickname-edit';edit.setAttribute('aria-label','修改昵称');edit.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15Z"/></svg>';name.after(edit);
const dialog=document.createElement('dialog');dialog.className='settings-dialog phone-dialog';dialog.setAttribute('aria-labelledby','nicknameTitle');
dialog.innerHTML='<div class="phone-dialog-heading"><h2 id="nicknameTitle">修改昵称</h2><button type="button" aria-label="关闭修改昵称">×</button></div><form><label for="nicknameInput">昵称</label><input id="nicknameInput" name="nickname" autocomplete="off" maxlength="20" required><p class="sms-help">1–20 个字符，仅用于显示，不影响手机号登录。</p><div class="avatar-crop-actions"><button type="button" class="settings-secondary">取消</button><button type="submit" class="settings-primary">保存</button></div><p class="settings-feedback" role="status"></p></form>';
document.body.append(dialog);
const input=dialog.querySelector('input'),form=dialog.querySelector('form'),feedback=dialog.querySelector('[role=status]'),save=form.querySelector('[type=submit]');let busy=false,version=0;
edit.onclick=()=>{input.value=MedixAuth.user?.display_name||'';feedback.textContent='';dialog.showModal();input.focus();input.select();};
dialog.querySelector('.phone-dialog-heading button').onclick=()=>dialog.close();form.querySelector('[type=button]').onclick=()=>dialog.close();
dialog.addEventListener('close',()=>{version++;form.reset();feedback.textContent='';});
function render(user){name.textContent=user?.display_name||'';if(!user&&dialog.open)dialog.close();}
window.addEventListener('medix-auth-change',e=>render(e.detail));
form.onsubmit=async e=>{e.preventDefault();if(busy)return;const nickname=input.value.trim();if(!nickname){feedback.textContent='请输入昵称。';return;}const mine=version;busy=true;save.disabled=true;
try{const r=await MedixAuth.fetch('/api/auth/nickname',{method:'PATCH',body:JSON.stringify({nickname})});if(!r.ok)throw new Error(await MedixAuth.detail(r));await MedixAuth.refresh();if(mine===version)dialog.close();}catch(e){if(mine===version)feedback.textContent=e.message;}finally{busy=false;save.disabled=false;}};
})();

(() => {
const dialog = document.getElementById('settingsDialog');
const byId = id => document.getElementById('settings-' + id);
const loginUsernameRow=document.createElement('div');
loginUsernameRow.className='settings-row';
const loginUsernameLabel=document.createElement('span');loginUsernameLabel.textContent='登录用户名';
const loginUsernameValue=document.createElement('span');
loginUsernameRow.append(loginUsernameLabel,loginUsernameValue);

const passwordUsernameHint=document.createElement('p');passwordUsernameHint.className='sms-help';
byId('passwordForm').before(passwordUsernameHint);
MedixPasswordPolicy.attachHints(byId('newPassword'));
let offset = 0, epoch = 0;
function showError(error) { if (dialog.open) byId('feedback').textContent = error.message; }
async function users() {
  const mine = epoch;
  const response = await MedixAuth.fetch(`/api/admin/users?offset=${offset}&limit=20`);
  if (!response.ok) throw new Error(await MedixAuth.detail(response));
  const data = await response.json(); if (mine !== epoch || !dialog.open || MedixAuth.user?.role !== 'admin') return; byId('users').replaceChildren();
  for (const user of data.items) {
    const row = document.createElement('tr');
    for (const text of [user.username, user.display_name, user.role === 'admin' ? '管理员' : '普通用户', user.is_active ? '正常' : '已停用']) {
      const cell = document.createElement('td'); cell.textContent = text; row.append(cell);
    }
    const action = document.createElement('td');
    if (user.role !== 'admin') {
      const button = document.createElement('button'); button.textContent = user.is_active ? '停用账号' : '启用账号';
      button.onclick = async () => {
        if (user.is_active && !confirm(`确认停用账号 ${user.username}？该用户的所有登录将失效。`)) return;
        button.disabled = true;
        try {
          const result = await MedixAuth.fetch(`/api/admin/users/${user.id}/status`, {method:'PATCH', body:JSON.stringify({is_active:!user.is_active})});
          if (!result.ok) throw new Error(await MedixAuth.detail(result));
          await users();
        } catch (error) { showError(error); button.disabled = false; }
      };
      action.append(button);
    }
    row.append(action); byId('users').append(row);
  }
  byId('pageInfo').textContent = `第 ${Math.floor(offset / 20) + 1} 页 · 共 ${data.total} 人`;
  byId('previous').disabled = offset === 0; byId('next').disabled = offset + 20 >= data.total;
}
byId('previous').onclick = () => { offset = Math.max(0, offset - 20); users().catch(showError); };
byId('next').onclick = () => { offset += 20; users().catch(showError); };
let setupChallenge='';
const setupFields=document.createElement('div');
setupFields.hidden=true;
setupFields.innerHTML='<p class="sms-help">验证码登录可直接使用。设置密码后，也可用手机号和密码登录。</p><label>手机验证码</label><div class="sms-code-row"><input autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6"><button type="button">获取验证码</button></div>';
byId('passwordForm').prepend(setupFields);
let setupUntil=0;
const setupSend=setupFields.querySelector('button');
let setupSending=false;
function tickSetup(){const remaining=Math.max(0,Math.ceil((setupUntil-Date.now())/1000));setupSend.disabled=setupSending||remaining>0;setupSend.textContent=setupSending?'发送中…':remaining?`${remaining} 秒后重发`:'获取验证码';}
const tickSetupTimer=setInterval(tickSetup,250);
window.addEventListener('pagehide',()=>clearInterval(tickSetupTimer),{once:true});
setupSend.onclick=async()=>{
 if(Date.now()<setupUntil)return;
 setupSending=true;tickSetup();
 try{const r=await MedixAuth.fetch('/api/auth/password/send',{method:'POST',body:'{}'});if(r.status===429) setupUntil=Date.now()+Math.min(900,Number(r.headers.get('Retry-After'))||60)*1000;if(!r.ok)throw new Error(await MedixAuth.detail(r));const d=await r.json();setupChallenge=d.challenge_id;setupUntil=Date.now()+d.retry_after*1000;byId('feedback').textContent='验证码已发送，5 分钟内有效。';}catch(e){showError(e);}finally{setupSending=false;tickSetup();}
};
function renderPasswordMode(user){
 loginUsernameValue.textContent=user?.username||'';
 passwordUsernameHint.textContent=user?.phone_masked?'登录手机号：'+user.phone_masked:'';
 const setup=user?.has_password===false;
 byId('oldPassword').hidden=setup;byId('oldPassword').required=!setup;
 dialog.querySelector('label[for="settings-oldPassword"]').hidden=setup;
 setupFields.hidden=!setup;setupFields.querySelector('input').required=setup;
 document.querySelector('#settingsSecurity > h3').textContent=setup?'设置密码':'修改密码';
 dialog.querySelector('label[for="settings-newPassword"]').textContent=setup?'密码':'新密码';
 dialog.querySelector('label[for="settings-confirmPassword"]').textContent=setup?'确认密码':'确认新密码';
 byId('passwordForm').querySelector('button[type="submit"],button.settings-primary').textContent=setup?'设置密码':'保存新密码';
 setupChallenge='';setupFields.querySelector('input').value='';
}
MedixAuth.ready.then(renderPasswordMode).catch(()=>{});
window.addEventListener('medix-auth-change',e=>renderPasswordMode(e.detail));
byId('passwordForm').onsubmit = async event => {
  const mine = epoch;
  event.preventDefault(); byId('feedback').textContent = '';
  const policyError = MedixPasswordPolicy.error(byId('newPassword').value);
  if (policyError) return showError(new Error(policyError));
  if (byId('newPassword').value !== byId('confirmPassword').value) return showError(new Error('两次输入的新密码不一致。'));
  const button = event.target.querySelector('.settings-primary'); button.disabled = true;
  try {
    const setup=MedixAuth.user?.has_password===false;
    if(setup&&!setupChallenge)throw new Error('请先获取验证码。');
    const payload=setup?{challenge_id:setupChallenge,code:setupFields.querySelector('input').value,new_password:byId('newPassword').value}:{current_password:byId('oldPassword').value,new_password:byId('newPassword').value};
    const response = await MedixAuth.fetch(setup?'/api/auth/password/set':'/api/auth/change-password', {method:'POST',body:JSON.stringify(payload)});
    if (mine !== epoch) return;
    if (!response.ok) throw new Error(await MedixAuth.detail(response));
    event.target.reset(); MedixAuth.leave(true); MedixAuth.open();
  } catch (error) { if (mine === epoch) showError(error); } finally { button.disabled = false; }
};

const avatarButton = document.getElementById('settingsAvatarButton');
const avatarFile = document.getElementById('settingsAvatarFile');
const avatarReset = document.getElementById('settingsAvatarReset');
let avatarBusy = false;
function renderAvatar(user) {
  document.getElementById('settingsAvatar').src = user?.avatar_url || '/assets/default-avatar.svg';
  avatarReset.hidden = !user?.avatar_url;
}
async function saveAvatar(data) {
  if (avatarBusy) return;
  const mine = epoch;
  avatarBusy = true; avatarButton.disabled = avatarReset.disabled = true;
  byId('feedback').textContent = '正在保存头像…';
  try {
    const response = await MedixAuth.fetch('/api/auth/avatar', {method:data ? 'PUT' : 'DELETE', body:JSON.stringify(data ? {data} : {})});
    if (mine !== epoch) return;
    if (!response.ok) throw new Error(await MedixAuth.detail(response));
    await MedixAuth.refresh();
    if (mine === epoch) byId('feedback').textContent = '头像已更新。';
  } catch (error) { if (mine === epoch) showError(error); }
  finally { avatarBusy=false; avatarButton.disabled=avatarReset.disabled=false; avatarFile.value=''; }
}
avatarButton.onclick = () => avatarFile.click();
avatarReset.onclick = () => saveAvatar(null);
avatarFile.onchange = () => {
  const file=avatarFile.files[0]; if(!file) return;
  if(file.size>2*1024*1024) { avatarFile.value=''; return showError(new Error('头像图片不能超过 2 MB。')); }
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)) { avatarFile.value=''; return showError(new Error('请上传 JPG、PNG 或 WebP 图片。')); }
  const reader = new FileReader(), mine = epoch;
  reader.onload = async () => {
    if(mine!==epoch || !dialog.open) return;
    try {
      const cropped = await MedixAvatarCrop.open(reader.result);
      if(cropped && mine===epoch && dialog.open) await saveAvatar(cropped);
    } catch (error) { if(mine===epoch) showError(new Error('无法读取或裁剪图片，请换一张图片。')); }
    finally { avatarFile.value=''; }
  };
  reader.onerror = () => showError(new Error('无法读取图片，请重新选择。'));
  reader.readAsDataURL(file);
};

let pending = false;
const tabs = [...dialog.querySelectorAll('[data-settings-tab]')];
function select(id) {
  tabs.forEach(tab => { const selected = tab.dataset.settingsTab === id; tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1; document.getElementById(tab.dataset.settingsTab).hidden = !selected; });
  byId('feedback').textContent = '';
}
tabs.forEach(tab => tab.onclick = () => { select(tab.dataset.settingsTab); if (tab.id === 'settingsAdminTab') users().catch(showError); });
dialog.querySelector('.settings-nav').addEventListener('keydown', event => {
  if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
  event.preventDefault(); const visible = tabs.filter(t => !t.hidden); let index = visible.indexOf(document.activeElement);
  index = event.key === 'Home' ? 0 : event.key === 'End' ? visible.length-1 : (index + (['ArrowLeft','ArrowUp'].includes(event.key) ? -1 : 1) + visible.length) % visible.length;
  visible[index].click(); visible[index].focus();
});
function openSettings() {
  const user = MedixAuth.user;
  if (!user) { pending = true; MedixAuth.open(); return; }
  if (dialog.open) return;
  pending = false; epoch++; offset = 0;
  renderAvatar(user);
  byId('displayName').textContent = user.display_name || user.username;
  byId('passwordUsername').value = user.username;
  byId('role').textContent = user.role === 'admin' ? '管理员' : '普通用户';
  document.getElementById('settingsAdminTab').hidden = user.role !== 'admin';
  select('settingsAccount'); dialog.showModal();
}
document.getElementById('settingsClose').onclick = () => dialog.close();
dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const r=dialog.getBoundingClientRect();
  if (event.clientX<r.left || event.clientX>r.right || event.clientY<r.top || event.clientY>r.bottom) dialog.close();
});
dialog.addEventListener('close', () => {
  epoch++; byId('passwordForm').reset(); byId('users').replaceChildren(); byId('feedback').textContent='';
  byId('displayName').textContent=''; byId('role').textContent='';
  const url=new URL(location.href); url.searchParams.delete('settings'); history.replaceState(null,'',url.pathname+url.search+url.hash);
  document.getElementById('profileTrigger').focus();
});
window.addEventListener('medix-settings-request', openSettings);
window.addEventListener('medix-signout', () => { pending=false; epoch++; if(dialog.open) dialog.close(); });
window.addEventListener('medix-auth-change', event => { renderAvatar(event.detail); if (pending && event.detail) queueMicrotask(openSettings); });
MedixAuth.ready.then(() => { if(new URL(location.href).searchParams.get('settings') === 'account') openSettings(); }).catch(() => {});
})();

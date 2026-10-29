(() => {
const dialog = document.getElementById('settingsDialog');
const byId = id => document.getElementById('settings-' + id);
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
byId('logout').onclick = () => MedixAuth.logout().catch(showError);
byId('passwordForm').onsubmit = async event => {
  const mine = epoch;
  event.preventDefault(); byId('feedback').textContent = '';
  const policyError = MedixPasswordPolicy.error(byId('newPassword').value);
  if (policyError) return showError(new Error(policyError));
  if (byId('newPassword').value !== byId('confirmPassword').value) return showError(new Error('两次输入的新密码不一致。'));
  const button = event.target.querySelector('button'); button.disabled = true;
  try {
    const response = await MedixAuth.fetch('/api/auth/change-password', {method:'POST', body:JSON.stringify({current_password:byId('oldPassword').value, new_password:byId('newPassword').value})});
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
  reader.onload = () => { if(mine===epoch && dialog.open) saveAvatar(reader.result); };
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
  byId('username').textContent = '@' + user.username;
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
  byId('displayName').textContent=''; byId('username').textContent=''; byId('role').textContent='';
  const url=new URL(location.href); url.searchParams.delete('settings'); history.replaceState(null,'',url.pathname+url.search+url.hash);
  document.getElementById('profileTrigger').focus();
});
window.addEventListener('medix-settings-request', openSettings);
window.addEventListener('medix-signout', () => { pending=false; epoch++; if(dialog.open) dialog.close(); });
window.addEventListener('medix-auth-change', event => { renderAvatar(event.detail); if (pending && event.detail) queueMicrotask(openSettings); });
MedixAuth.ready.then(() => { if(new URL(location.href).searchParams.get('settings') === 'account') openSettings(); }).catch(() => {});
})();

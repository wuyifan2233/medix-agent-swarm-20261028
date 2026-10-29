const byId = id => document.getElementById(id);
let offset = 0;
function showError(error) { byId('feedback').textContent = error.message; }
async function users() {
  const response = await MedixAuth.fetch(`/api/admin/users?offset=${offset}&limit=20`);
  if (!response.ok) throw new Error(await MedixAuth.detail(response));
  const data = await response.json(); byId('users').replaceChildren();
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
byId('logoutAll').onclick = () => MedixAuth.logout(true).catch(showError);
byId('passwordForm').onsubmit = async event => {
  event.preventDefault(); byId('feedback').textContent = '';
  if (byId('newPassword').value !== byId('confirmPassword').value) return showError(new Error('两次输入的新密码不一致。'));
  const button = event.target.querySelector('button'); button.disabled = true;
  try {
    const response = await MedixAuth.fetch('/api/auth/change-password', {method:'POST', body:JSON.stringify({current_password:byId('oldPassword').value, new_password:byId('newPassword').value})});
    if (!response.ok) throw new Error(await MedixAuth.detail(response));
    event.target.reset(); MedixAuth.leave(true);
  } catch (error) { showError(error); } finally { button.disabled = false; }
};
MedixAuth.ready.then(user => {
  if (!user) return;
  byId('displayName').textContent = user.display_name; byId('username').textContent = `@${user.username}`;
  byId('passwordUsername').value = user.username;
  byId('role').textContent = user.role === 'admin' ? '管理员' : '普通用户';
  if (user.role === 'admin') { byId('adminPanel').hidden = false; users().catch(showError); }
}).catch(() => {});

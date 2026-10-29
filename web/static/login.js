const byId = id => document.getElementById(id);
let registering = false;
function mode(value) {
  registering = value;
  byId('loginTab').setAttribute('aria-selected', String(!value));
  byId('registerTab').setAttribute('aria-selected', String(value));
  for (const id of ['nameField', 'confirmField', 'passwordHint']) byId(id).hidden = !value;
  byId('displayName').required = value; byId('confirmPassword').required = value;
  byId('password').minLength = value ? 15 : 1;
  byId('password').autocomplete = value ? 'new-password' : 'current-password';
  byId('formTitle').textContent = value ? '创建你的健康空间' : '欢迎回来';
  byId('formIntro').textContent = value ? '从一个属于自己的账号开始。' : '登录账号，开启今天的健康对话。';
  byId('submitButton').textContent = value ? '创建账号 →' : '登录我的空间 →';
  byId('feedback').textContent = ''; byId('password').value = ''; byId('confirmPassword').value = '';
}
byId('loginTab').onclick = () => mode(false);
byId('registerTab').onclick = () => mode(true);
byId('authForm').onsubmit = async event => {
  event.preventDefault();
  const isRegister = registering, password = byId('password').value;
  if (isRegister && password !== byId('confirmPassword').value) { byId('feedback').textContent = '两次输入的密码不一致。'; return; }
  const button = byId('submitButton'); button.disabled = true;
  byId('loginTab').disabled = byId('registerTab').disabled = true;
  byId('feedback').textContent = '';
  try {
    const payload = {username: byId('username').value, password};
    if (isRegister) payload.display_name = byId('displayName').value.trim();
    const response = await MedixAuth.raw(isRegister ? '/api/auth/register' : '/api/auth/login', {method:'POST', body:JSON.stringify(payload)});
    if (!response.ok) throw new Error(await MedixAuth.detail(response));
    if (isRegister) { mode(false); byId('feedback').textContent = '账号创建成功，请登录。'; byId('password').focus(); }
    else { MedixAuth.announceLogin(); location.replace('/'); }
  } catch (error) { byId('feedback').textContent = error.message || '连接失败，请稍后重试。'; }
  finally { button.disabled = false; byId('loginTab').disabled = byId('registerTab').disabled = false; }
};

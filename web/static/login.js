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
  byId('formIntro').textContent = value ? '创建账号，开启你的健康对话。' : '登录 MediX，开启你的健康对话。';
  byId('submitButton').textContent = value ? '创建账号' : '登 录';
  byId('feedback').textContent = ''; byId('password').value = ''; byId('confirmPassword').value = '';
  byId('password').type = 'password';
  byId('togglePassword').textContent = '显示';
  byId('togglePassword').setAttribute('aria-label', '显示密码');
  byId('togglePassword').setAttribute('aria-pressed', 'false');
}
byId('togglePassword').onclick = () => {
  const showing = byId('password').type === 'password';
  byId('password').type = showing ? 'text' : 'password';
  byId('togglePassword').textContent = showing ? '隐藏' : '显示';
  byId('togglePassword').setAttribute('aria-label', showing ? '隐藏密码' : '显示密码');
  byId('togglePassword').setAttribute('aria-pressed', String(showing));
};
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

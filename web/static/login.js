/* Native modal: focus stays inside; Escape and backdrop both dismiss it. */
(() => {
  const el = id => document.getElementById(id);
  const dialog = el('authDialog');
  let registering = false, busy = false, generation = 0, requestController = null;
  function fitViewport() {
    const viewport = window.visualViewport;
    dialog.style.setProperty('--auth-height', `${viewport?.height || innerHeight}px`);
  }
  window.visualViewport?.addEventListener('resize', fitViewport);
  window.addEventListener('resize', fitViewport);
  fitViewport();
  function mode(value) {
    registering = value;
    el('loginTab').setAttribute('aria-selected', String(!value));
    el('registerTab').setAttribute('aria-selected', String(value));
    for (const id of ['confirmField', 'passwordHint']) el(id).hidden = !value;
    el('confirmPassword').required = value;
    el('password').minLength = value ? 15 : 1;
    el('password').autocomplete = value ? 'new-password' : 'current-password';
    el('formTitle').textContent = value ? '注册 MediX' : '登录 MediX';
    el('formIntro').textContent = value ? '创建账号，开启你的健康对话。' : '登录后，开始你的健康对话。';
    el('submitButton').textContent = value ? '创建账号' : '登录';
    el('feedback').textContent = ''; el('password').value = ''; el('confirmPassword').value = '';
    el('password').type = 'password'; el('togglePassword').textContent = '显示';
    el('togglePassword').setAttribute('aria-label', '显示密码');
    el('togglePassword').setAttribute('aria-pressed', 'false');
  }
  function resetBusy() {
    busy = false;
    el('submitButton').disabled = el('loginTab').disabled = el('registerTab').disabled = false;
    el('submitButton').textContent = registering ? '创建账号' : '登录';
  }
  function open() {
    if (MedixAuth.user || dialog.open) return;
    mode(false); dialog.showModal(); document.body.classList.add('auth-modal-open');
  }
  window.addEventListener('medix-login-request', open);
  window.addEventListener('medix-auth-change', event => { if (event.detail && dialog.open) dialog.close(); });
  el('topLoginButton').onclick = open;
  el('profileLogin').onclick = open;
  el('closeAuth').onclick = () => dialog.close();
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const controls = [...dialog.querySelectorAll('button, input, [href], [tabindex]')]
      .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => {
    generation++; requestController?.abort(); requestController = null;
    document.body.classList.remove('auth-modal-open');
    el('authForm').reset(); mode(false); resetBusy();
    const url = new URL(location.href);
    url.searchParams.delete('login');
    url.searchParams.delete('next');
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  });
  el('togglePassword').onclick = () => {
    const show = el('password').type === 'password';
    el('password').type = show ? 'text' : 'password';
    el('togglePassword').textContent = show ? '隐藏' : '显示';
    el('togglePassword').setAttribute('aria-label', show ? '隐藏密码' : '显示密码');
    el('togglePassword').setAttribute('aria-pressed', String(show));
  };
  el('loginTab').onclick = () => mode(false);
  el('registerTab').onclick = () => mode(true);
  for (const id of ['loginTab', 'registerTab']) el(id).addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); if (busy) return;
      mode(!registering); el(registering ? 'registerTab' : 'loginTab').focus();
    }
  });
  el('authForm').onsubmit = async event => {
    event.preventDefault(); if (busy) return;
    const mine = generation, isRegister = registering, password = el('password').value;
    if (isRegister && password !== el('confirmPassword').value) { el('feedback').textContent = '两次输入的密码不一致。'; return; }
    busy = true; requestController = new AbortController();
    el('submitButton').disabled = el('loginTab').disabled = el('registerTab').disabled = true;
    el('submitButton').textContent = isRegister ? '创建中…' : '登录中…'; el('feedback').textContent = '';
    try {
      const payload = {username:el('username').value, password};
      const response = await MedixAuth.raw(isRegister ? '/api/auth/register' : '/api/auth/login', {
        method:'POST', body:JSON.stringify(payload), signal:requestController.signal
      });
      if (mine !== generation) return;
      if (!response.ok) throw new Error(await MedixAuth.detail(response));
      if (isRegister) {
        mode(false); el('feedback').textContent = '账号创建成功，请登录。'; el('password').focus();
      } else {
        const payload = await response.json();
        if (mine !== generation) return;
        const next = new URL(location.href).searchParams.get('next');
        MedixAuth.completeLogin(payload);
        if (dialog.open) dialog.close();
        if (next === '/account') location.assign('/account');
      }
    } catch (error) {
      if (mine === generation && error.name !== 'AbortError') el('feedback').textContent = error.message || '连接失败，请稍后重试。';
    } finally { if (mine === generation) resetBusy(); }
  };
  MedixAuth.ready.then(user => {
    if (!user && new URL(location.href).searchParams.get('login') === '1') open();
  }).catch(() => {});
})();

/* Native modal: focus stays inside; Escape and backdrop both dismiss it. */
(() => {
  const el = id => document.getElementById(id);
  const dialog = el('authDialog');
  const basics=document.createElement('fieldset');basics.id='registerBasics';basics.hidden=true;
  basics.innerHTML='<legend>身体基本信息</legend><p>不询问疾病或用药。可留空或选择不愿提供，注册后不再修改。</p><div class="register-basics-grid"><label>注册时年龄（岁）<input id="regAge" type="number" min="0" max="130" step="1" placeholder="不愿提供可留空"></label><label>性别<select id="regSex"><option value="undisclosed">不愿提供</option><option value="female">女</option><option value="male">男</option></select></label><label>注册时身高（cm）<input id="regHeight" type="number" min="30" max="250" step="0.1" placeholder="不愿提供可留空"></label><label>注册时体重（kg）<input id="regWeight" type="number" min="1" max="400" step="0.1" placeholder="不愿提供可留空"></label></div><label class="register-basic-ack"><input id="regBasicAck" type="checkbox">我已核对所填基本信息，理解注册后只读；问答时需单独授权使用。</label>';
  el('authForm').insertBefore(basics,el('feedback'));
  let registering = false, busy = false, generation = 0, requestController = null;
  const updatePasswordHints = MedixPasswordPolicy.attachHints(el('password'), () => registering);
  function fitViewport() {
    const viewport = window.visualViewport;
    dialog.style.setProperty('--auth-height', `${viewport?.height || innerHeight}px`);
  }
  window.visualViewport?.addEventListener('resize', fitViewport);
  window.addEventListener('resize', fitViewport);
  fitViewport();
  function mode(value) {
    registering = value;basics.hidden=!value;basics.querySelectorAll('input,select').forEach(node=>{node.disabled=!value;});el('regBasicAck').required=value;
    el('loginTab').setAttribute('aria-selected', String(!value));
    el('registerTab').setAttribute('aria-selected', String(value));
    el('confirmField').hidden = !value;
    el('confirmPassword').required = value;
    el('password').minLength = value ? MedixPasswordPolicy.min : 1;
    el('password').autocomplete = value ? 'new-password' : 'current-password';
    el('formTitle').textContent = value ? '注册 MediX' : '登录 MediX';
    el('formIntro').textContent = value ? '创建账号，开启你的健康对话。' : '登录后，开始你的健康对话。';
    el('submitButton').textContent = value ? '创建账号' : '登录';
    el('feedback').textContent = ''; el('password').value = ''; el('confirmPassword').value = '';
    el('password').type = 'password';
    el('togglePassword').classList.remove('is-visible');
    el('togglePassword').setAttribute('aria-label', '显示密码');
    el('togglePassword').title = '显示密码';
    el('togglePassword').setAttribute('aria-pressed', 'false');
    updatePasswordHints();
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
  el('closeAuth').onclick = () => dialog.close();
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const controls = [...dialog.querySelectorAll('button, input, select, [href], [tabindex]')]
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
    el('togglePassword').classList.toggle('is-visible', show);
    el('togglePassword').setAttribute('aria-label', show ? '隐藏密码' : '显示密码');
    el('togglePassword').title = show ? '隐藏密码' : '显示密码';
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
    if (isRegister && MedixPasswordPolicy.error(password)) { el('feedback').textContent = MedixPasswordPolicy.error(password); return; }
    if (isRegister && password !== el('confirmPassword').value) { el('feedback').textContent = '两次输入的密码不一致。'; return; }
    busy = true; requestController = new AbortController();
    el('submitButton').disabled = el('loginTab').disabled = el('registerTab').disabled = true;
    el('submitButton').textContent = isRegister ? '创建中…' : '登录中…'; el('feedback').textContent = '';
    try {
      const payload = {username:el('username').value, password};
      if(isRegister){const number=id=>el(id).value===''?null:Number(el(id).value);payload.basic_profile={age:number('regAge'),sex:el('regSex').value,height_cm:number('regHeight'),weight_kg:number('regWeight'),acknowledged:el('regBasicAck').checked};}
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

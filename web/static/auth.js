/* Shared same-origin API client. No credential is stored in JS or localStorage. */
window.MedixAuth = (() => {
  let csrf = '', currentUser = null, leaving = false;
  const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('medix-account') : null;
  function announce() {
    channel?.postMessage('changed');
    try { localStorage.setItem('medix-account-event', crypto.randomUUID()); } catch (_) { /* Storage may be disabled. */ }
  }
  function leave(notify = false) {
    if (leaving) return;
    leaving = true; csrf = ''; currentUser = null;
    document.documentElement.setAttribute('data-auth-pending', '');
    window.dispatchEvent(new Event('medix-signout'));
    if (notify) {
      announce(); // event only; no secret or user data
    }
    location.replace('/login');
  }
  if (channel) channel.onmessage = () => leave();
  window.addEventListener('storage', event => { if (event.key === 'medix-account-event') leave(); });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  function headersFor(options) {
    const headers = new Headers(options.headers);
    const method = (options.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      headers.set('Content-Type', 'application/json');
      headers.set('X-Medix-Request', '1');
      if (csrf) headers.set('X-CSRF-Token', csrf);
    }
    return headers;
  }
  async function raw(url, options = {}) {
    return fetch(url, {...options, headers: headersFor(options), credentials: 'same-origin', cache: 'no-store'});
  }
  async function detail(response) {
    const body = await response.json().catch(() => ({}));
    return typeof body.detail === 'string' ? body.detail : '请检查输入内容后重试。';
  }
  const isLogin = location.pathname === '/login';
  const ready = isLogin ? Promise.resolve(null) : (async () => {
    const response = await raw('/api/auth/me');
    if (response.status === 401) { leave(); throw new Error('请先登录。'); }
    if (!response.ok) throw new Error('无法确认登录状态，请刷新页面。');
    currentUser = await response.json();
    const tokenResponse = await raw('/api/auth/csrf');
    if (tokenResponse.status === 401) { leave(); throw new Error('登录已失效。'); }
    if (!tokenResponse.ok) throw new Error('无法初始化安全校验，请刷新页面。');
    csrf = (await tokenResponse.json()).csrf_token;
    document.documentElement.removeAttribute('data-auth-pending');
    return currentUser;
  })();
  ready.catch(error => {
    if (!leaving) {
      document.documentElement.removeAttribute('data-auth-pending');
      document.body.replaceChildren();
      const message = document.createElement('p'); message.textContent = error.message;
      const reload = document.createElement('button'); reload.textContent = '重新加载'; reload.onclick = () => location.reload();
      document.body.append(message, reload);
    }
  });
  window.addEventListener('focus', async () => {
    if (!currentUser || leaving) return;
    try {
      const response = await raw('/api/auth/me');
      if (response.status === 401) return leave();
      if (response.ok && (await response.json()).id !== currentUser.id) leave();
    } catch (_) { /* A temporary network failure does not clear a valid login. */ }
  });
  return {
    ready, raw, detail, leave,
    async fetch(url, options = {}) {
      await ready;
      if (leaving) throw new Error('登录已结束。');
      const response = await raw(url, options);
      if (response.status === 401) { leave(true); throw new Error('登录已失效，请重新登录。'); }
      return response;
    },
    async logout(all = false) {
      const response = await this.fetch(all ? '/api/auth/logout-all' : '/api/auth/logout', {method: 'POST', body: '{}'});
      if (!response.ok) throw new Error(await detail(response));
      leave(true);
    },
    announceLogin() {
      announce();
    }
  };
})();

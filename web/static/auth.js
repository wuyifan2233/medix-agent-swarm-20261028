/* Cookies stay HttpOnly. The public home shell can be used before authentication. */
window.MedixAuth = (() => {
  let csrf = '', currentUser = null, revision = 0;
  const protectedPage = location.pathname === '/account' || location.pathname === '/assets/account.html';
  const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('medix-account') : null;
  function announce() {
    channel?.postMessage('changed');
    try { localStorage.setItem('medix-account-event', crypto.randomUUID()); } catch (_) {}
  }
  function open() { window.dispatchEvent(new Event('medix-login-request')); }
  function setUser(user) {
    const previous = currentUser;
    currentUser = user;
    if (previous && previous.id !== user?.id) {
      window.dispatchEvent(new Event('medix-signout'));
      if (protectedPage) {
        document.documentElement.setAttribute('data-auth-pending', '');
        location.replace(user ? '/account' : '/?login=1&next=/account');
      }
    }
    window.dispatchEvent(new CustomEvent('medix-auth-change', {detail:user}));
  }
  function leave(notify = false) {
    revision++; csrf = ''; setUser(null);
    if (notify) announce();
    if (protectedPage) location.replace('/?login=1&next=/account');
  }
  function headersFor(options) {
    const headers = new Headers(options.headers);
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes((options.method || 'GET').toUpperCase())) {
      headers.set('Content-Type', 'application/json'); headers.set('X-Medix-Request', '1');
      if (csrf) headers.set('X-CSRF-Token', csrf);
    }
    return headers;
  }
  async function raw(url, options = {}) {
    return fetch(url, {...options, headers:headersFor(options), credentials:'same-origin', cache:'no-store'});
  }
  async function detail(response) {
    const body = await response.json().catch(() => ({}));
    return typeof body.detail === 'string' ? body.detail : '请检查输入内容后重试。';
  }
  async function refresh() {
    const mine = ++revision;
    const response = await raw('/api/auth/me');
    if (mine !== revision) return currentUser;
    if (response.status === 401) {
      csrf = ''; setUser(null);
      if (protectedPage) location.replace('/?login=1&next=/account');
      return null;
    }
    if (!response.ok) throw new Error('无法确认登录状态，请稍后重试。');
    const user = await response.json();
    const tokenResponse = await raw('/api/auth/csrf');
    if (mine !== revision) return currentUser;
    if (tokenResponse.status === 401) { leave(); return null; }
    if (!tokenResponse.ok) throw new Error('无法初始化安全校验，请刷新页面。');
    const payload = await tokenResponse.json();
    if (mine !== revision) return currentUser;
    csrf = payload.csrf_token; setUser(user);
    return user;
  }
  const ready = refresh().finally(() => document.documentElement.removeAttribute('data-auth-pending'));
  ready.catch(error => window.dispatchEvent(new CustomEvent('medix-auth-error', {detail:error.message})));
  function resync() { refresh().catch(() => {}); }
  if (channel) channel.onmessage = resync;
  window.addEventListener('storage', event => { if (event.key === 'medix-account-event') resync(); });
  window.addEventListener('focus', resync);
  window.addEventListener('pageshow', event => { if (event.persisted) resync(); });
  return {
    ready, raw, detail, leave, open, refresh,
    get user() { return currentUser; },
    async requireLogin() {
      await ready.catch(() => {});
      if (currentUser) return true;
      open(); return false;
    },
    completeLogin(payload) {
      revision++; csrf = payload.csrf_token; setUser(payload.user); announce();
    },
    async fetch(url, options = {}) {
      if (!await this.requireLogin()) throw new Error('请登录后继续。');
      const response = await raw(url, options);
      if (response.status === 401) { leave(true); open(); throw new Error('登录已失效，请重新登录。'); }
      return response;
    },
    async logout(all = false) {
      const response = await this.fetch(all ? '/api/auth/logout-all' : '/api/auth/logout', {method:'POST', body:'{}'});
      if (!response.ok) throw new Error(await detail(response));
      leave(true);
    }
  };
})();

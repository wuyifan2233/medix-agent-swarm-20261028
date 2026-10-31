/* Account identity stays in MedixAuth; this component only renders its menu. */
(() => {
  const trigger = document.getElementById('profileTrigger');
  const menu = document.getElementById('profileMenu');
  const sidebar = document.getElementById('sidebar');
  let previousUserId = null;
  const open = () => !menu.hidden;
  function close() {
    menu.hidden = true;
    menu.removeAttribute('data-open');
    trigger.setAttribute('aria-expanded', 'false');
  }
  function position() {
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(248, innerWidth - 24);
    const above = rect.top - 12, below = innerHeight - rect.bottom - 12;
    const upwards = above >= Math.min(220, below);
    menu.style.width = `${width}px`;
    menu.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`;
    menu.style.top = upwards ? 'auto' : `${rect.bottom + 8}px`;
    menu.style.bottom = upwards ? `${innerHeight - rect.top + 8}px` : 'auto';
    menu.style.maxHeight = `${Math.max(80, (upwards ? above : below) - 8)}px`;
  }
  function show(last = false) {
    if (!MedixAuth.user) { MedixAuth.open(); return; }
    position();
    menu.hidden = false;
    menu.setAttribute('data-open', '');
    trigger.setAttribute('aria-expanded', 'true');
    const items = [...menu.querySelectorAll('[role="menuitem"]')];
    items[last ? items.length - 1 : 0]?.focus();
  }
  function render(user) {
    if (previousUserId !== (user?.id || null)) close();
    previousUserId = user?.id || null;
    const name = user?.display_name || user?.username || '登录 / 注册';
    document.getElementById('profileName').textContent = name;
    document.getElementById('profileMenuName').textContent = name;
    document.getElementById('profileMenuUsername').textContent = user ? `@${user.username}` : '';
    trigger.setAttribute('aria-label', user ? `${name}，打开账号菜单` : '登录账号');
    trigger.setAttribute('aria-haspopup', user ? 'menu' : 'dialog');
    trigger.setAttribute('aria-controls', user ? 'profileMenu' : 'authDialog');
  }
  trigger.addEventListener('click', event => {
    if (!MedixAuth.user) { event.preventDefault(); MedixAuth.open(); return; }
    if (open()) close(); else show();
  });
  trigger.addEventListener('keydown', event => {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault(); show(event.key === 'ArrowUp');
    }
  });
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault(); close(); trigger.focus(); return;
    }
    const items = [...menu.querySelectorAll('[role="menuitem"]')];
    const index = items.indexOf(document.activeElement);
    let next;
    if (event.key === 'ArrowDown') next = (index + 1) % items.length;
    if (event.key === 'ArrowUp') next = (index - 1 + items.length) % items.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = items.length - 1;
    if (next !== undefined) { event.preventDefault(); items[next].focus(); }
  });
  // focusout may run before a pointer click reaches the next menu item.
  // Wait for the actual new focus target instead of hiding during that gap.
  document.addEventListener('focusin', event => {
    if (!menu.contains(event.target) && !trigger.contains(event.target)) close();
  });
  document.addEventListener('pointerdown', event => {
    if (!menu.contains(event.target) && !trigger.contains(event.target)) close();
  });
  document.addEventListener('click', event => {
    if (!menu.contains(event.target) && !trigger.contains(event.target)) close();
  });
  document.getElementById('profileSettings').addEventListener('click', close);
  document.getElementById('hpOpen').addEventListener('click', close);
  document.getElementById('logoutButton').addEventListener('click', async event => {
    const button = event.currentTarget;
    if (button.disabled) return;
    button.disabled = true;
    const label = button.querySelector('span');
    if (label) label.textContent = '正在退出…';
    try { await MedixAuth.logout(); close(); trigger.focus(); }
    catch (error) { window.dispatchEvent(new CustomEvent('medix-auth-error', {detail:error.message})); }
    finally { button.disabled = false; if (label) label.textContent = '退出登录'; }
  });
  sidebar.addEventListener('scroll', close);
  window.addEventListener('resize', () => {
    if (open()) { if (sidebar.inert) close(); else position(); }
  });
  window.addEventListener('medix-sidebar-close', close);
  window.addEventListener('medix-login-request', close);
  window.addEventListener('medix-signout', close);
  window.addEventListener('medix-auth-change', event => render(event.detail));
  MedixAuth.ready.then(render).catch(() => render(null));
})();

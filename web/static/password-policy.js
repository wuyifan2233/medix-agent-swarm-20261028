/* Keep in sync with auth/password_policy.py. Existing-password login is unaffected. */
window.MedixPasswordPolicy = Object.freeze({
  min: 8,
  max: 20,
  hint: '8–20 位，大写字母、小写字母、数字、特殊字符中至少包含三类。',
  status(value) {
    const symbol = [...value].some(c => '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'.includes(c));
    const types = [/[A-Z]/.test(value), /[a-z]/.test(value), /[0-9]/.test(value), symbol];
    return {length:[...value].length, types, count:types.filter(Boolean).length};
  },
  error(value) {
    const status = this.status(value);
    if (!status.length) return '请输入密码。';
    if (status.length < this.min) return '密码至少需要 8 位。';
    if (status.length > this.max) return '密码不能超过 20 位。';
    if (status.count < 3) return `请再加入 ${3 - status.count} 种字符类型。`;
    return '';
  },
  attachHints(input, enabled = () => true) {
    let wrapper = input.parentElement;
    if (!wrapper.classList.contains('auth-password')) {
      wrapper = document.createElement('div');
      wrapper.className = 'password-tooltip-wrapper';
      input.before(wrapper); wrapper.append(input);
    }
    const tip = document.createElement('div');
    tip.className = 'password-tooltip'; tip.id = `${input.id}Rules`;
    tip.setAttribute('role', 'tooltip'); tip.hidden = true;
    tip.textContent = '8–20 位；大写、小写、数字、符号中任选 3 类。';
    wrapper.append(tip);
    input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), tip.id].filter(Boolean).join(' '));
    let dismissed = false;
    const update = () => { tip.hidden = !enabled() || document.activeElement !== input || dismissed; };
    input.addEventListener('focus', () => { dismissed = false; update(); });
    input.addEventListener('blur', update);
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !tip.hidden) {
        event.preventDefault(); event.stopPropagation(); dismissed = true; update();
      }
    });
    update(); return update;
  }
});

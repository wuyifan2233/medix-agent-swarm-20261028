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
  attachHints(input, anchor, enabled = () => true) {
    const panel = document.createElement('div');
    panel.className = 'password-rules'; panel.hidden = true;
    panel.id = `${input.id}Rules`;
    const summary = document.createElement('div'); summary.className = 'password-rules-summary';
    const length = document.createElement('span'), count = document.createElement('span');
    summary.append(length, count);
    const types = document.createElement('div'); types.className = 'password-rules-types';
    const labels = ['大写字母', '小写字母', '数字', '符号'];
    const chips = labels.map(label => { const chip = document.createElement('span'); chip.textContent = label; types.append(chip); return chip; });
    panel.append(summary, types); anchor.after(panel);
    const describedBy = [input.getAttribute('aria-describedby'), anchor.id, panel.id].filter(Boolean).join(' ');
    input.setAttribute('aria-describedby', describedBy);
    const update = () => {
      const on = enabled();
      const focused = document.activeElement === input ||
        (input.parentElement.classList.contains('auth-password') && input.parentElement.contains(document.activeElement));
      panel.hidden = !on || !(input.value || focused);
      const status = this.status(input.value);
      length.textContent = `${status.length >= this.min && status.length <= this.max ? '✓ ' : ''}8–20 位`;
      length.classList.toggle('is-met', status.length >= this.min && status.length <= this.max);
      count.textContent = `至少 3 类 · ${Math.min(status.count, 3)}/3`;
      count.classList.toggle('is-met', status.count >= 3);
      chips.forEach((chip, i) => {
        chip.textContent = `${status.types[i] ? '✓ ' : ''}${labels[i]}`;
        chip.classList.toggle('is-met', status.types[i]);
      });
    };
    for (const event of ['input', 'focus', 'blur']) input.addEventListener(event, update);
    input.parentElement.addEventListener('focusout', () => queueMicrotask(update));
    input.parentElement.addEventListener('focusin', update);
    update(); return update;
  }
});

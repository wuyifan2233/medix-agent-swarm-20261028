/* Keep in sync with auth/password_policy.py. Existing-password login is unaffected. */
window.MedixPasswordPolicy = Object.freeze({
  min: 8,
  max: 20,
  hint: '8–20 位，包含大写字母、小写字母、数字和特殊字符。',
  error(value) {
    const symbol = [...value].some(c => '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'.includes(c));
    return value.length >= this.min && value.length <= this.max && /[A-Z]/.test(value)
      && /[a-z]/.test(value) && /[0-9]/.test(value) && symbol
      ? '' : `密码须为 ${this.hint}`;
  }
});

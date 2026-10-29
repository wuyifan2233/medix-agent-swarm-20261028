/* Keep in sync with auth/password_policy.py. Existing-password login is unaffected. */
window.MedixPasswordPolicy = Object.freeze({
  min: 8,
  max: 20,
  hint: '8–20 位，大写字母、小写字母、数字、特殊字符中至少包含三类。',
  error(value) {
    const symbol = [...value].some(c => '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'.includes(c));
    const categories = [/[A-Z]/.test(value), /[a-z]/.test(value), /[0-9]/.test(value), symbol].filter(Boolean).length;
    return value.length >= this.min && value.length <= this.max && categories >= 3
      ? '' : `密码须为 ${this.hint}`;
  }
});

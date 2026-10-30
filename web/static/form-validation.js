(() => {
  document.addEventListener('invalid', event => {
    const input=event.target;
    if(!input.matches('input,textarea,select'))return;
    event.preventDefault();
    const form=input.form;if(!form)return;
    const feedback=form.querySelector('[role="status"],.settings-feedback,#feedback')||form.closest('dialog')?.querySelector('#feedback,#settings-feedback');
    const phone=input.type==='tel';
    const message=phone?'请输入正确的 11 位手机号。':input.validity.valueMissing?'请填写此项。':input.type==='password'?'请检查密码长度及要求。':input.autocomplete==='one-time-code'?'请输入 6 位短信验证码。':'请检查输入内容是否符合要求。';
    input.setAttribute('aria-invalid','true');
    if(feedback){feedback.textContent=message;feedback.setAttribute('role','status');}
  },true);
  document.addEventListener('input',event=>event.target.removeAttribute?.('aria-invalid'));
  document.querySelectorAll('input[type="tel"]').forEach((input,index)=>{
    input.inputMode='tel';input.removeAttribute('maxlength');
    const hint=document.createElement('span');
    hint.className='phone-field-hint';hint.id='phone-hint-'+index;
    hint.setAttribute('aria-live','polite');input.after(hint);
    input.setAttribute('aria-describedby',((input.getAttribute('aria-describedby')||'')+' '+hint.id).trim());
    function validate(blur=false){
      const value=input.value;
      const partialCountryPrefix=!blur&&['+','+8'].includes(value);
      const badPrefix=value.length>=2&&!/^1[3-9]/.test(value);
      const invalid=!partialCountryPrefix&&( /[^0-9]/.test(value)||badPrefix||value.length>11||(blur&&value.length>0&&value.length!==11));
      hint.textContent=invalid?'请输入正确的 11 位手机号。':'';
      input.setAttribute('aria-invalid',String(invalid));
      input.setCustomValidity(invalid?'请输入正确的 11 位手机号。':'');
    }
    function normalize(){
      // Only known formatting characters are removed; invalid letters stay visible.
      input.value=input.value.replace(/[\s\-‐‑–—]/g,'').replace(/^\+86/,'');
    }
    input.addEventListener('input',()=>{normalize();validate();});
    input.addEventListener('blur',()=>{normalize();validate(true);});
    input.form?.addEventListener('reset',()=>{hint.textContent='';input.removeAttribute('aria-invalid');input.setCustomValidity('');});
  });
})();

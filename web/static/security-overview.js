(() => {
const section=document.getElementById('settingsSecurity');
const overview=document.createElement('div');overview.className='security-overview';
overview.innerHTML='<h3>账号管理</h3><div class="security-list"><div class="security-list-row"><span class="security-row-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="3"/><path d="M10 18h4"/></svg></span><span>手机号</span><span id="securityPhoneState" class="security-row-value"></span></div><button type="button" id="securityPasswordRow" class="security-list-row"><span class="security-row-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg></span><span>登录密码</span><span id="securityPasswordState" class="security-row-value"></span><span class="security-row-chevron"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></span></button></div><div class="security-list security-danger-list" id="securityDeleteGroup"></div>';
section.prepend(overview);
const entry=section.querySelector('.account-delete-link');
if(entry){entry.className='security-list-row security-delete-row';entry.innerHTML='<span class="security-row-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/></svg></span><span>注销账号</span><span class="security-row-value"></span><span class="security-row-chevron"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></span>';overview.querySelector('#securityDeleteGroup').append(entry);}
const back=document.createElement('button');back.type='button';back.className='security-back';back.textContent='‹ 返回账号管理';section.insertBefore(back,overview.nextSibling);
function home(){section.dataset.view='overview';}
back.onclick=home;overview.querySelector('#securityPasswordRow').onclick=()=>{section.dataset.view='password';};
document.getElementById('settingsSecurityTab').addEventListener('click',home);
document.getElementById('settingsDialog').addEventListener('close',home);
function render(user){document.getElementById('securityPhoneState').textContent=user?.phone_masked||'未绑定';document.getElementById('securityPasswordState').textContent=user?.has_password===false?'未设置':'已设置';}
MedixAuth.ready.then(render).catch(()=>{});window.addEventListener('medix-auth-change',e=>render(e.detail));home();
})();

(() => {
const el=id=>document.getElementById(id);let offset=0,q='',version=0,pending=null;
function guard(user){if(user?.role!=='admin'){version++;el('rows').replaceChildren();location.replace('/?login=1');return false;}return true;}
async function load(){const mine=++version;el('feedback').textContent='';try{
const results=await Promise.all([MedixAuth.fetch('/api/admin/overview'),MedixAuth.fetch(`/api/admin/users?offset=${offset}&limit=20&q=${encodeURIComponent(q)}`)]);
for(const r of results)if(!r.ok)throw new Error(await MedixAuth.detail(r));
const [stats,data]=await Promise.all(results.map(r=>r.json()));if(mine!==version)return;
for(const key of ['total','active','disabled','admins'])el(key).textContent=stats[key];el('rows').replaceChildren();
for(const user of data.items){const row=document.createElement('tr');const name=document.createElement('td');const wrap=document.createElement('div');wrap.className='user-cell';const img=document.createElement('img');img.src=user.avatar_url||'/assets/default-avatar.svg';img.alt='';const label=document.createElement('span');label.textContent=user.display_name;wrap.append(img,label);name.append(wrap);row.append(name);
for(const value of [user.phone_masked||'未绑定',user.role==='admin'?'管理员':'普通用户',new Date(user.created_at*1000).toLocaleString('zh-CN')]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}
const state=document.createElement('td');const badge=document.createElement('span');badge.className='status'+(user.is_active?'':' off');badge.textContent=user.is_active?'正常':'已停用';state.append(badge);row.append(state);const action=document.createElement('td');if(user.role==='admin')action.textContent='—';else{const button=document.createElement('button');button.textContent=user.is_active?'停用':'恢复';button.onclick=()=>{pending=user;el('confirmTitle').textContent=user.is_active?'停用账号':'恢复账号';el('confirmText').textContent=user.is_active?`确认停用 ${user.display_name}？该账号的登录会话会立即失效。`:`确认恢复 ${user.display_name} 的登录权限？`;el('confirmDialog').showModal();};action.append(button);}row.append(action);el('rows').append(row);}
if(!data.items.length){const row=document.createElement('tr');const td=document.createElement('td');td.colSpan=6;td.className='empty';td.textContent='没有找到匹配的用户';row.append(td);el('rows').append(row);}
el('pageInfo').textContent=`共 ${data.total} 个用户 · 第 ${Math.floor(offset/20)+1} 页`;el('previous').disabled=offset===0;el('next').disabled=offset+20>=data.total;
}catch(e){if(mine===version)el('feedback').textContent=e.message;}}
el('searchForm').onsubmit=e=>{e.preventDefault();q=el('search').value.trim();offset=0;load();};el('refresh').onclick=load;el('previous').onclick=()=>{offset=Math.max(0,offset-20);load();};el('next').onclick=()=>{offset+=20;load();};el('cancelAction').onclick=()=>el('confirmDialog').close();
el('confirmAction').onclick=async()=>{if(!pending)return;const user=pending;el('confirmAction').disabled=true;try{const r=await MedixAuth.fetch(`/api/admin/users/${encodeURIComponent(user.id)}/status`,{method:'PATCH',body:JSON.stringify({is_active:!user.is_active})});if(!r.ok)throw new Error(await MedixAuth.detail(r));pending=null;el('confirmDialog').close();await load();}catch(e){el('confirmDialog').close();el('feedback').textContent=e.message;}finally{el('confirmAction').disabled=false;}};
MedixAuth.ready.then(user=>{if(guard(user))load();}).catch(e=>{el('feedback').textContent=e.message;});window.addEventListener('medix-auth-change',e=>guard(e.detail));
})();

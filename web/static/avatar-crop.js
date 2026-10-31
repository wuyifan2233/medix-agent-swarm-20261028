/* Local pixel editing only; upload begins after the user confirms the crop. */
window.MedixAvatarCrop = (() => {
  const dialog = document.getElementById('avatarCropDialog');
  const canvas = document.getElementById('avatarCropCanvas');
  const zoom = document.getElementById('avatarCropZoom');
  const context = canvas.getContext('2d');
  let image = null, scale = 1, minimum = 1, x = 0, y = 0, drag = null, resolve = null;
  const size = canvas.width;
  function draw() {
    if (!image) return;
    x = Math.max(size - image.width * scale, Math.min(0, x));
    y = Math.max(size - image.height * scale, Math.min(0, y));
    context.fillStyle = '#fff'; context.fillRect(0, 0, size, size);
    context.drawImage(image, x, y, image.width * scale, image.height * scale);
  }
  function reset() {
    scale = minimum; zoom.value = '1';
    x = (size - image.width * scale) / 2; y = (size - image.height * scale) / 2; draw();
  }
  zoom.oninput = () => {
    const next = minimum * Number(zoom.value), ratio = next / scale;
    x = size / 2 - (size / 2 - x) * ratio;
    y = size / 2 - (size / 2 - y) * ratio; scale = next; draw();
  };
  canvas.onpointerdown = event => {
    if (event.button !== 0) return;
    drag = {id:event.pointerId, x:event.clientX, y:event.clientY};
    canvas.setPointerCapture(event.pointerId);
  };
  canvas.onpointermove = event => {
    if (!drag || drag.id !== event.pointerId) return;
    const factor = size / canvas.getBoundingClientRect().width;
    x += (event.clientX - drag.x) * factor; y += (event.clientY - drag.y) * factor;
    drag.x = event.clientX; drag.y = event.clientY; draw();
  };
  canvas.onpointerup = canvas.onpointercancel = () => { drag = null; };
  canvas.onkeydown = event => {
    const delta = event.shiftKey ? 20 : 5;
    const directions = {ArrowLeft:[-delta,0], ArrowRight:[delta,0], ArrowUp:[0,-delta], ArrowDown:[0,delta]};
    if (!directions[event.key]) return;
    event.preventDefault(); x += directions[event.key][0]; y += directions[event.key][1]; draw();
  };
  document.getElementById('avatarCropReset').onclick = reset;
  document.getElementById('avatarCropCancel').onclick = () => dialog.close();
  document.getElementById('avatarCropClose').onclick = () => dialog.close();
  document.getElementById('avatarCropSave').onclick = () => {
    const result = canvas.toDataURL('image/webp', .9);
    const done = resolve; resolve = null; dialog.close(); done?.(result);
  };
  dialog.addEventListener('close', () => {
    const done = resolve; resolve = null; image = null; drag = null;
    context.clearRect(0, 0, size, size); done?.(null);
  });
  window.addEventListener('medix-signout', () => { if (dialog.open) dialog.close(); });
  return {
    async open(data) {
      if (dialog.open) return null;
      const loaded = new Image(); loaded.src = data; await loaded.decode();
      if (loaded.width * loaded.height > 20_000_000) throw new Error('图片分辨率过大，请缩小后再上传。');
      image = loaded; minimum = Math.max(size / image.width, size / image.height); reset();
      return new Promise(done => { resolve = done; dialog.showModal(); });
    }
  };
})();

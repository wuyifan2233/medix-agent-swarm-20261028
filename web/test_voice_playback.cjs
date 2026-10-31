const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(process.argv[2] || path.resolve(__dirname, '..'), 'web/static/app.js'), 'utf8');
assert(!/speechSynthesis|SpeechSynthesisUtterance|useBrowserSpeech/.test(source), 'Browser TTS fallback must be absent');
const code = source.slice(source.indexOf('function speechSafeText('), source.indexOf('\nfunction userMessage('));
function fixture() {
  const played = [], messages = [];
  const state = {speechToken: 0, health: {speech_api_configured: false}, audio: null, speakingButton: null};
  class Audio {
    constructor(url) { this.url = url; }
    async play() { played.push(this); this.onplaying?.(); }
    pause() { this.paused = true; }
    removeAttribute(name) { delete this[name]; }
    load() { this.unloaded = true; }
  }
  const ctx = {state, icon: () => '', toast: text => messages.push(text), AbortController, Audio,
    fetch: async () => ({ok: true, json: async () => ({url: '/api/voice/speech/stream/' + 'a'.repeat(32)})})};
  ctx.MedixAuth = {fetch: (...args) => ctx.fetch(...args)};
  vm.createContext(ctx); vm.runInContext(code, ctx);
  const button = () => ({classList: {add() {}, remove() {}}, attributes: {},
    setAttribute(k,v) { this.attributes[k] = v; }, innerHTML: ''});
  return {ctx, state, played, messages, button};
}
async function main() {
  let passed = 0;
  {
    const f = fixture(), b = f.button();
    await f.ctx.speakAnswer('你好', b);
    assert.equal(f.played.length, 1); assert.equal(b.attributes['aria-pressed'], 'true');
    await f.ctx.speakAnswer('你好', b);
    assert.equal(f.played[0].paused, true); assert.equal(f.state.speakingButton, null);
    assert.equal(f.played[0].unloaded, true); assert.equal(b.attributes['aria-pressed'], 'false'); passed++;
  }
  {
    const f = fixture(), b = f.button(); let signal;
    f.ctx.fetch = (_, options) => new Promise((resolve, reject) => {
      signal = options.signal;
      signal.addEventListener('abort', () => reject(Object.assign(new Error('cancelled'), {name: 'AbortError'})));
    });
    const pending = f.ctx.speakAnswer('你好', b); f.ctx.stopSpeaking(); await pending;
    assert(signal.aborted); assert.equal(f.played.length, 0); assert.equal(f.messages.length, 0); passed++;
  }
  {
    const f = fixture(); let finish;
    f.ctx.fetch = () => new Promise(resolve => { finish = resolve; });
    const first = f.ctx.speakAnswer('第一条', f.button());
    f.ctx.fetch = async () => ({ok:true, json:async()=>({url: '/api/voice/speech/stream/' + 'a'.repeat(32)})});
    await f.ctx.speakAnswer('第二条', f.button());
    finish({ok:true, json:async()=>({url: '/api/voice/speech/stream/' + 'a'.repeat(32)})}); await first;
    assert.equal(f.played.length, 1, 'A stale result must never interrupt the newer answer'); passed++;
  }
  {
    const f = fixture(), b = f.button();
    f.ctx.fetch = async () => ({ok:false, json:async()=>({detail:'云端不可用，请重试'})});
    await f.ctx.speakAnswer('你好', b);
    assert.equal(f.played.length, 0); assert.equal(f.messages.length, 1);
    assert.equal(f.state.speakingButton, null); assert.equal(b.attributes['aria-pressed'], 'false'); passed++;
  }
  {
    const f = fixture();
    f.ctx.Audio.prototype.play = async function() { throw Object.assign(new Error('blocked'), {name:'NotAllowedError'}); };
    await f.ctx.speakAnswer('你好', f.button());
    assert(f.messages[0].includes('朗读按钮')); assert.equal(f.state.audio, null); passed++;
  }
  {
    const f = fixture(), b = f.button(); await f.ctx.speakAnswer('你好', b);
    f.played[0].onended(); assert.equal(f.state.speakingButton, null);
    assert.equal(f.played[0].unloaded, true); passed++;
  }
  {
    const f = fixture(), b = f.button(); await f.ctx.speakAnswer('你好', b);
    f.played[0].onwaiting(); assert(b.innerHTML.includes('缓冲中'));
    f.played[0].onplaying(); assert(!b.innerHTML.includes('缓冲中'));
    f.played[0].onerror(); assert.equal(f.state.audio, null);
    assert.equal(f.messages.length, 1); assert.equal(f.played[0].unloaded, true); passed++;
  }
  {
    const f = fixture();
    f.ctx.fetch = async () => ({ok:true, json:async()=>({url:'https://elsewhere.example/audio'})});
    await f.ctx.speakAnswer('你好', f.button());
    assert.equal(f.played.length, 0); assert.equal(f.messages.length, 1); passed++;
  }
  {
    const input = {value:'已有草稿', classList:{remove(){}, add(){}}, focus(){this.focused=true;}, setSelectionRange(a,b){this.selection=[a,b];}};
    let submitted = false;
    const ctx = {String, state:{}, $: id => {assert.equal(id,'message');return input;},
      clearVoiceTimer(){}, stopVoiceTracks(){}, resetVoiceState(){}, updateComposer(){}, setTimeout(){},
      submit(){submitted=true;}};
    vm.createContext(ctx);
    const insertion = source.slice(source.indexOf('function insertVoiceTranscript('), source.indexOf('function startBrowserRecognition('));
    vm.runInContext(insertion, ctx); ctx.insertVoiceTranscript('识别的文字');
    assert.equal(input.value, '已有草稿\n识别的文字');
    assert(input.focused); assert.equal(submitted, false);
    input.value += '，手动修正'; assert(input.value.endsWith('手动修正')); passed++;
  }
  {
    const handlers = {}, calls = [];
    const ctx = {authEpoch:0, state:{}, crypto:{randomUUID:()=> 'new-chat'},
      window:{addEventListener:(name, fn)=>{handlers[name]=fn;}},
      $:()=>({replaceChildren(){},classList:{remove(){}},value:'',checked:false}),
      document:{body:{classList:{remove(){}}}},
      cancelVoiceInput:()=>calls.push('recording'), stopSpeaking:()=>calls.push('playback'), updateComposer(){}};
    vm.createContext(ctx);
    const listener = source.slice(source.indexOf("window.addEventListener('medix-signout'"), source.indexOf('function renderAccount('));
    vm.runInContext(listener, ctx); handlers['medix-signout']();
    assert.deepEqual(calls,['recording','playback']); assert.equal(ctx.authEpoch,1); passed++;
  }
  console.log(JSON.stringify({passed, failed: 0, browser_tts_fallback: false, native_streaming: true}));
}
main().catch(error => { console.error(error); process.exitCode = 1; });

const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/static/app.js', 'utf8');
const draft = {innerHTML: ''};
const row = {querySelector: () => draft};
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('const escapeText ='), source.indexOf('\n', source.indexOf('const escapeText ='))) + '\n' +
 source.slice(source.indexOf('function richText('), source.indexOf('function speechSafeText(')) + '\n' +
 source.slice(source.indexOf('function draftArea('), source.indexOf('function stoppedMessage(')), context);
context.renderDraft(row, '## 实时标题\n- **第一点**\n');
assert.match(draft.innerHTML, /<h4>实时标题<\/h4>/);
assert.match(draft.innerHTML, /<strong>第一点<\/strong>/);
context.renderDraft(row, '| 项目 | 值 |\n| --- | --- |\n| 示例 | 1 |', true);
assert.match(draft.innerHTML, /<table/);
assert.match(draft.innerHTML, /<td>示例<\/td>/);
context.renderDraft(row, '\n<img src=x onerror=alert(1)> [1]', true);
assert(!draft.innerHTML.includes('<img'));
assert(!draft.innerHTML.includes('citation-anchor'));
context.renderDraft(row, '');
context.renderDraft(row, '**下一轮**', true);
assert.equal(draft.innerHTML, '<p><strong>下一轮</strong></p>');
context.renderDraft(row, '## 恢复的草稿');
context.renderDraft(row, '\n补充内容', true);
assert.match(draft.innerHTML, /<h4>恢复的草稿<\/h4><p>补充内容<\/p>/);
console.log('Live Markdown: headings, lists, tables, escaping, reset and resume passed.');

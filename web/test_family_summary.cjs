const {test} = require('node:test');
const assert = require('node:assert/strict');
const summarize = require('./static/family-summary.js');
test('collapsed bar counts records and shows top three active topics', () => {
  const summary = summarize([
    {topics:['睡眠','睡眠','血压'],active:1},
    {topics:['睡眠','头晕','感冒'],active:1},
    {topics:['咳嗽'],active:0},
    {topics:['发热'],deleted:true}
  ]);
  assert.deepEqual(summary,{total:3,active:2,inactive:1,description:'睡眠 · 血压 · 头晕'});
});
test('cloud serialized topics and missing topics have safe summaries', () => {
  assert.equal(summarize([{topics:'["感冒"]'}]).description,'感冒');
  assert.equal(summarize([{topics:'malformed'}]).description,'健康记录待归类');
  assert.equal(summarize([{topics:{bad:true}}]).description,'健康记录待归类');
  assert.equal(summarize([{active:0}]).description,'暂无有效记录');
  assert.equal(summarize([]).description,'还没有健康记录');
});
test('summary changes after editing same record without increasing count', () => {
  const before = [{id:'one',topics:['感冒']}];
  const after = before.map(record=>({...record,topics:['睡眠']}));
  assert.equal(summarize(after).total,1);
  assert.equal(summarize(after).description,'睡眠');
});

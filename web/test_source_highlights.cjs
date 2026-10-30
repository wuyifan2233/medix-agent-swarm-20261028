const {test} = require('node:test');
const assert = require('node:assert/strict');
const {referenceRanges, sentenceRanges} = require('./static/source-highlights.js');
test('finds middle evidence and preserves its original whitespace', () => {
  const original = '前文\r\n每日钠摄入 < 2g，约 5g 食盐\r\n后文';
  const ranges = referenceRanges(original, ['每日钠摄入<2g，约5g食盐']);
  assert.equal(ranges.length,1);
  assert.equal(original.slice(...ranges[0]), '每日钠摄入 < 2g，约 5g 食盐');
});
test('does not invent a highlight when the evidence is absent or empty', () => {
  assert.deepEqual(referenceRanges('其他内容',['未找到','']),[]);
});
test('merges overlap and includes repeated source occurrences', () => {
  assert.deepEqual(referenceRanges('abcdef abcdef',['abc','bcde']),[[0,5],[7,12]]);
});
test('memory highlights matching sentences without marking unrelated history', () => {
  const text='我三天晚上头晕。之前只是咳嗽。';
  const ranges=sentenceRanges(text,['头晕','眩晕']);
  assert.equal(text.slice(...ranges[0]),'我三天晚上头晕。');
  assert.equal(ranges.length,1);
});
test('treats HTML-looking source as ordinary source text', () => {
  const text='原文<script>alert(1)</script>结束';
  assert.equal(text.slice(...referenceRanges(text,['<script>alert(1)</script>'])[0]),'<script>alert(1)</script>');
});

test('accepts serialized Mem0 metadata and tolerates absent topics', () => {
  const text='我最近睡眠不好。其他信息。';
  assert.equal(text.slice(...sentenceRanges(text,'["睡眠"]')[0]),'我最近睡眠不好。');
  assert.deepEqual(sentenceRanges(text,null),[]);
});

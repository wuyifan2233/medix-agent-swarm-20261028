(function(root) {
  function summarize(records) {
    const visible = records.filter(record => !record.deleted);
    const active = visible.filter(record => record.active !== 0);
    const counts = new Map();
    active.forEach(record => {
      let topics = record.topics || [];
      if (typeof topics === 'string') { try { topics = JSON.parse(topics); } catch { topics = []; } }
      if (!Array.isArray(topics)) return;
      new Set(topics.filter(topic => typeof topic === 'string' && topic.trim())).forEach(topic => counts.set(topic,(counts.get(topic)||0)+1));
    });
    const keywords = [...counts].sort((a,b)=>b[1]-a[1]).slice(0,3).map(item=>item[0]);
    return {total:visible.length, active:active.length, inactive:visible.length-active.length,
      description:keywords.length ? keywords.join(' · ') : active.length ? '健康记录待归类' : visible.length ? '暂无有效记录' : '还没有健康记录'};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = summarize;
  else root.summarizeFamily = summarize;
})(typeof window !== 'undefined' ? window : {});

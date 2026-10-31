/* Inline source anchors decorate the existing answer DOM without rewriting it. */
(function (root) {
  'use strict';
  const citationPattern = /\[(\d+(?:\s*[,，]\s*\d+)*)\]/g;
  const plain = text => String(text).replace(/\[\d+(?:\s*[,，]\s*\d+)*\]/g, '').replace(/[\s*#`]/g, '').replace(/[。！？.!?]+$/, '');
  function decorate(container, sources, evidenceLinks, openPreview) {
    const doc = container.ownerDocument;
    const byId = new Map(sources.filter(s => Number.isInteger(s.citation)).map(s => [s.citation, s]));
    if (!byId.size) return 0;
    const walker = doc.createTreeWalker(container, 4);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    let count = 0;
    for (const node of nodes) {
      if (node.parentElement?.closest('a,button,code,pre')) continue;
      const value = node.nodeValue;
      citationPattern.lastIndex = 0;
      const matches = [...value.matchAll(citationPattern)];
      if (!matches.length) continue;
      const block = node.parentElement?.closest('p,li,td,th,blockquote,h1,h2,h3,h4') || node.parentElement;
      const fragment = doc.createDocumentFragment();
      let cursor = 0;
      for (const match of matches) {
        fragment.append(doc.createTextNode(value.slice(cursor, match.index)));
        const ids = [...new Set(match[1].split(/[,，]/).map(n => Number(n.trim())))];
        for (const id of ids) {
          const source = byId.get(id);
          if (!source) { fragment.append(doc.createTextNode('[' + id + ']')); continue; }
          const range = doc.createRange(); range.selectNodeContents(block); range.setEnd(node, match.index);
          const prefix = plain(range.toString());
          const annotation = evidenceLinks.find(item => (item.citations || []).includes(id) && plain(item.text) && prefix.endsWith(plain(item.text)));
          const quote = (annotation?.quotes || []).find(q => q.citation === id)?.quote || '';
          const anchor = doc.createElement('button');
          anchor.type = 'button'; anchor.className = 'citation-anchor'; anchor.textContent = '[' + id + ']';
          anchor.dataset.citation = String(id); anchor.title = source.title || '查看参考依据';
          anchor.setAttribute('aria-label', '查看参考依据 ' + id + '：' + (source.title || '本地资料'));
          anchor.setAttribute('aria-haspopup', 'dialog');
          anchor.onclick = () => openPreview(anchor, source, quote);
          fragment.append(anchor); count++;
        }
        cursor = match.index + match[0].length;
      }
      fragment.append(doc.createTextNode(value.slice(cursor))); node.replaceWith(fragment);
    }
    return count;
  }
  root.MedixCitations = {decorate};
  if (typeof module !== 'undefined' && module.exports) module.exports = {decorate};
})(typeof window !== 'undefined' ? window : globalThis);

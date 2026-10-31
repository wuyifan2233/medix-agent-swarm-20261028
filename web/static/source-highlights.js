/* Locate evidence without changing the source text or interpreting it as HTML. */
(function(root) {
  function mergeRanges(ranges) {
    const merged = [];
    for (const range of ranges.sort((a,b) => a[0]-b[0])) {
      const previous = merged[merged.length-1];
      if (previous && range[0] <= previous[1]) previous[1] = Math.max(previous[1], range[1]);
      else merged.push([...range]);
    }
    return merged;
  }
  function compact(text) {
    let value = ''; const offsets = [];
    for (let i=0; i<text.length; i++) {
      if (/\s/.test(text[i])) continue;
      value += text[i]; offsets.push(i);
    }
    return {value, offsets};
  }
  function referenceRanges(text, excerpts) {
    const original = compact(text); const ranges = [];
    for (const excerpt of excerpts) {
      const needle = compact(String(excerpt || '')).value;
      if (!needle) continue;
      let start = 0, found;
      while ((found = original.value.indexOf(needle, start)) !== -1) {
        ranges.push([original.offsets[found], original.offsets[found+needle.length-1]+1]);
        start = found + needle.length;
      }
    }
    return mergeRanges(ranges);
  }
  function sentenceRanges(text, terms) {
    if (typeof terms === 'string') {
      try { terms = JSON.parse(terms); } catch { terms = [terms]; }
    }
    if (!Array.isArray(terms)) terms = [];
    terms = terms.filter(term => typeof term === 'string');
    const ranges = [];
    const expression = /[^。！？\n]+[。！？]?/g;
    for (const match of text.matchAll(expression)) {
      if (terms.some(term => term && match[0].includes(term))) {
        ranges.push([match.index, match.index + match[0].length]);
      }
    }
    return mergeRanges(ranges);
  }
  const api = {referenceRanges, sentenceRanges};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SourceHighlights = api;
})(typeof window !== 'undefined' ? window : {});

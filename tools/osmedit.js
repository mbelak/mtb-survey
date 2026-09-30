// Pure functions for changing a tag on an OSM way. Shared by the map page and the test (node).
// The XML handling is string based, since node has no DOMParser. The format from
// GET /api/0.6/way/<id> is simple and stable: <osm ...><way ...>(<nd .../>|<tag .../>)*</way></osm>.
(function (root) {
  const esc = v => String(v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const unesc = v => v.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

  /** Reads a tag from way XML. null if it is missing. */
  function getWayTag(xml, key) {
    const m = new RegExp('<tag\\s+k="' + esc(key).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '"\\s+v="([^"]*)"\\s*/?>').exec(xml);
    return m ? unesc(m[1]) : null;
  }

  /** Version and id from way XML. */
  function wayInfo(xml) {
    const w = /<way\b([^>]*)>/.exec(xml);
    if (!w) throw new Error('no <way> in the response');
    const attr = n => { const m = new RegExp('\\b' + n + '="([^"]*)"').exec(w[1]); return m ? m[1] : null; };
    return { id: Number(attr('id')), version: Number(attr('version')), changeset: Number(attr('changeset')) };
  }

  /** New way XML with the tag set, and the changeset attribute switched to the open changeset.
   *  Returns { xml, old } where old is the previous value or null. */
  function setWayTag(xml, key, value, changesetId) {
    const info = wayInfo(xml);
    if (!info.id) throw new Error('way has no id');
    const old = getWayTag(xml, key);
    let out = xml.replace(/<way\b([^>]*)>/, (m, a) => {
      a = a.replace(/\s+changeset="[^"]*"/, '').replace(/\s+(timestamp|user|uid)="[^"]*"/g, '');
      return '<way' + a + ' changeset="' + Number(changesetId) + '">';
    });
    const tag = '<tag k="' + esc(key) + '" v="' + esc(value) + '"/>';
    const re = new RegExp('<tag\\s+k="' + esc(key).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '"\\s+v="[^"]*"\\s*/?>');
    out = old !== null ? out.replace(re, tag) : out.replace('</way>', tag + '</way>');
    return { xml: out, old, version: info.version };
  }

  /** XML for opening a changeset. */
  function changesetXml(tags) {
    return '<osm><changeset>' + Object.entries(tags).map(([k, v]) => '<tag k="' + esc(k) + '" v="' + esc(v) + '"/>').join('') + '</changeset></osm>';
  }

  const api = { getWayTag, wayInfo, setWayTag, changesetXml };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.OsmEdit = api;
})(typeof window !== 'undefined' ? window : globalThis);

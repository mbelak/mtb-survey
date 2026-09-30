// Rena funktioner för att ändra en tagg på en OSM-way. Delas av kartsidan och testet (node).
// XML-hanteringen är strängbaserad, eftersom node saknar DOMParser. Formatet från
// GET /api/0.6/way/<id> är enkelt och stabilt: <osm ...><way ...>(<nd .../>|<tag .../>)*</way></osm>.
(function (root) {
  const esc = v => String(v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const unesc = v => v.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

  /** Läser en tagg ur way-XML. null om den saknas. */
  function getWayTag(xml, key) {
    const m = new RegExp('<tag\\s+k="' + esc(key).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '"\\s+v="([^"]*)"\\s*/?>').exec(xml);
    return m ? unesc(m[1]) : null;
  }

  /** Version och id ur way-XML. */
  function wayInfo(xml) {
    const w = /<way\b([^>]*)>/.exec(xml);
    if (!w) throw new Error('ingen <way> i svaret');
    const attr = n => { const m = new RegExp('\\b' + n + '="([^"]*)"').exec(w[1]); return m ? m[1] : null; };
    return { id: Number(attr('id')), version: Number(attr('version')), changeset: Number(attr('changeset')) };
  }

  /** Ny way-XML med taggen satt, och changeset-attributet bytt till det öppna changesetet.
   *  Returnerar { xml, old } där old är tidigare värde eller null. */
  function setWayTag(xml, key, value, changesetId) {
    const info = wayInfo(xml);
    if (!info.id) throw new Error('way saknar id');
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

  /** XML för att öppna ett changeset. */
  function changesetXml(tags) {
    return '<osm><changeset>' + Object.entries(tags).map(([k, v]) => '<tag k="' + esc(k) + '" v="' + esc(v) + '"/>').join('') + '</changeset></osm>';
  }

  const api = { getWayTag, wayInfo, setWayTag, changesetXml };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.OsmEdit = api;
})(typeof window !== 'undefined' ? window : globalThis);

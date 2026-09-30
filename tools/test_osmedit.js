// node tools/test_osmedit.js
const assert = require('assert');
const { getWayTag, wayInfo, setWayTag, changesetXml } = require('./osmedit.js');

const xml = '<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="openstreetmap-cgimap 2.0.1 (123)">\n' +
  '<way id="1125042460" visible="true" version="7" changeset="99" timestamp="2024-01-01T00:00:00Z" user="x" uid="5">\n' +
  '<nd ref="1"/><nd ref="2"/>\n<tag k="highway" v="path"/>\n<tag k="mtb:scale" v="3"/>\n<tag k="surface" v="ground"/>\n</way>\n</osm>';

assert.strictEqual(getWayTag(xml, 'mtb:scale'), '3');
assert.strictEqual(getWayTag(xml, 'name'), null);
assert.deepStrictEqual(wayInfo(xml), { id: 1125042460, version: 7, changeset: 99 });

// replace an existing tag
let r = setWayTag(xml, 'mtb:scale', 2, 555);
assert.strictEqual(r.old, '3');
assert.strictEqual(r.version, 7);
assert.strictEqual(getWayTag(r.xml, 'mtb:scale'), '2');
assert.ok(/<way id="1125042460" visible="true" version="7" changeset="555">/.test(r.xml), r.xml);
assert.ok(!/timestamp=|user=|uid=/.test(r.xml));
assert.strictEqual((r.xml.match(/<tag k="mtb:scale"/g) || []).length, 1);
assert.ok(r.xml.includes('<tag k="surface" v="ground"/>'));   // other tags untouched
assert.ok(r.xml.includes('<nd ref="1"/><nd ref="2"/>'));

// add a missing tag
const xml2 = xml.replace('<tag k="mtb:scale" v="3"/>\n', '');
r = setWayTag(xml2, 'mtb:scale', 1, 7);
assert.strictEqual(r.old, null);
assert.strictEqual(getWayTag(r.xml, 'mtb:scale'), '1');
assert.ok(r.xml.includes('<tag k="mtb:scale" v="1"/></way>'));

// special characters in values are escaped
assert.strictEqual(changesetXml({ comment: 'a "b" & <c>' }), '<osm><changeset><tag k="comment" v="a &quot;b&quot; &amp; &lt;c&gt;"/></changeset></osm>');
assert.strictEqual(getWayTag('<way id="1" version="1"><tag k="name" v="A &amp; B"/></way>', 'name'), 'A & B');

// error: no way
assert.throws(() => setWayTag('<osm></osm>', 'mtb:scale', 1, 1), /no <way>/);
console.log('osmedit: all tests passed');

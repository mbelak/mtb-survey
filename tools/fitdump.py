#!/usr/bin/env python3
"""Minimal FIT decoder (stdlib only). Prints every record message
with timestamp, lat/lon and all developer fields (e.g. mtb_scale)."""
import struct, sys

BASE = {0x00:('B',1),0x01:('b',1),0x02:('B',1),0x83:('h',2),0x84:('H',2),0x85:('i',4),
        0x86:('I',4),0x07:('s',1),0x88:('f',4),0x89:('d',8),0x0A:('B',1),0x8B:('H',2),
        0x8C:('I',4),0x0D:('B',1),0x8E:('q',8),0x8F:('Q',8),0x90:('Q',8)}
INVALID = {0x00:0xFF,0x01:0x7F,0x02:0xFF,0x83:0x7FFF,0x84:0xFFFF,0x85:0x7FFFFFFF,
           0x86:0xFFFFFFFF,0x0A:0,0x8B:0,0x8C:0,0x0D:0xFF}

def val(raw, bt, endian):
    if bt == 0x07:
        return raw.split(b'\0')[0].decode('utf-8', 'replace')
    fmt, size = BASE.get(bt, ('B', 1))
    n = len(raw) // size
    vals = struct.unpack(endian + fmt * n, raw[:n * size])
    vals = [None if v == INVALID.get(bt) or (isinstance(v, float) and v != v) else v for v in vals]   # v != v: NaN
    return vals[0] if n == 1 else list(vals)

def parse(path):
    d = open(path, 'rb').read()
    hsize = d[0]
    dsize = struct.unpack('<I', d[4:8])[0]
    assert d[8:12] == b'.FIT', 'not a FIT file'
    pos, end = hsize, hsize + dsize
    defs, devfields, out = {}, {}, []
    last_ts = 0
    while pos < end:
        hdr = d[pos]; pos += 1
        if hdr & 0x80:                      # compressed timestamp header
            local = (hdr >> 5) & 0x3; offs = hdr & 0x1F
            ts = (last_ts & ~0x1F) + offs
            if offs < (last_ts & 0x1F): ts += 0x20
            last_ts = ts; is_def = False; comp_ts = ts
        else:
            local = hdr & 0x0F; is_def = bool(hdr & 0x40); comp_ts = None
        if is_def:
            has_dev = bool(hdr & 0x20)
            arch = d[pos + 1]; endian = '>' if arch else '<'
            gnum = struct.unpack(endian + 'H', d[pos + 2:pos + 4])[0]
            nf = d[pos + 4]; pos += 5
            fields = [(d[pos + 3*i], d[pos + 3*i + 1], d[pos + 3*i + 2]) for i in range(nf)]
            pos += 3 * nf
            dev = []
            if has_dev:
                nd = d[pos]; pos += 1
                dev = [(d[pos + 3*i], d[pos + 3*i + 1], d[pos + 3*i + 2]) for i in range(nd)]
                pos += 3 * nd
            defs[local] = (gnum, endian, fields, dev)
            continue
        gnum, endian, fields, dev = defs[local]
        msg = {}
        for num, size, bt in fields:
            msg[num] = val(d[pos:pos + size], bt, endian); pos += size
        devvals = {}
        for num, size, ddi in dev:
            name, bt = devfields.get((ddi, num), ('dev%d_%d' % (ddi, num), 0x02))
            devvals[name] = val(d[pos:pos + size], bt, endian); pos += size
        if 253 in msg and msg[253] is not None: last_ts = msg[253]
        if gnum == 206:                     # field_description
            devfields[(msg.get(0), msg.get(1))] = (msg.get(3), msg.get(2))
            out.append(('field_description', {'name': msg.get(3), 'units': msg.get(8),
                        'base_type': msg.get(2), 'native_mesg_num': msg.get(14)}, {}))
        elif gnum == 20:                    # record
            ts = msg.get(253, comp_ts)
            lat = msg.get(0); lon = msg.get(1)
            sc = 180.0 / 2**31
            alt = msg.get(78)                   # enhanced_altitude, otherwise altitude
            if alt is None: alt = msg.get(2)
            dist = msg.get(5)
            spd = msg.get(73)                   # enhanced_speed, otherwise speed (mm/s)
            if spd is None: spd = msg.get(6)
            out.append(('record', {'ts': ts, 'speed': None if spd is None else spd / 1000,
                        'hr': msg.get(3), 'cad': msg.get(4),
                        'lat': None if lat is None else round(lat * sc, 6),
                        'lon': None if lon is None else round(lon * sc, 6),
                        'alt': None if alt is None else round(alt / 5 - 500, 1),
                        'dist': None if dist is None else dist / 100}, devvals))
        elif gnum == 23:                    # device_info: connected sensors, e.g. heart rate chest strap (type 120)
            out.append(('device_info', {'device_type': msg.get(1), 'source_type': msg.get(25),
                                        'manufacturer': msg.get(2), 'product': msg.get(4)}, {}))
        elif gnum == 21:                    # event
            out.append(('event', {'ts': msg.get(253), 'event': msg.get(0), 'type': msg.get(1)}, {}))
    return out

if __name__ == '__main__':
    rows = parse(sys.argv[1])
    t0 = None; nrec = 0; nscale = 0; nll = 0
    for kind, m, dev in rows:
        if kind == 'record':
            nrec += 1
            if t0 is None: t0 = m['ts']
            if dev.get('mtb_scale') is not None: nscale += 1
            if m['lat'] is not None: nll += 1
            print('record t+%-4s lat=%s lon=%s dev=%s' % (m['ts'] - t0 if m['ts'] is not None else '?', m['lat'], m['lon'], dev))
        else:
            print(kind, m)
    print('SUMMARY records=%d with_mtb_scale=%d with_position=%d' % (nrec, nscale, nll))
    for name in ('roughness', 'jolt', 'steer'):
        n = sum(1 for k, m, dev in rows if k == 'record' and dev.get(name) is not None)
        if n: print('        with_%s=%d' % (name, n))
    n = sum(1 for k, m, dev in rows if k == 'record' and m.get('cad') is not None)
    if n: print('        with_cadence=%d' % n)

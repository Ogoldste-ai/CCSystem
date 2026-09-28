#!/usr/bin/env python3
"""Low-level text editing for PDFs with plain (uncompressed) content streams.

Built for Hilan-style Hebrew payslips, where every visible string is its own
`BT ... (text) Tj ... ET` block at an absolute position, Hebrew is stored in
*visual* (reversed) order, and there is no ToUnicode map - so normal text
extraction produces garbage but byte-level editing is exact.

Two payslip generations are supported and detected automatically per font:
  * older: simple TrueType fonts, single-byte cp1255, widths from /Widths
  * newer: /Type0 CID fonts, two-byte UTF-16BE codes, widths from the
    descendant font's /W indexed through the embedded CMap

Commands
--------
  dump         list text blocks (page, x, y, font, size, text)
  set          replace the string of one block, identified by x/y
  replace-word replace a word and re-position it so its RIGHT edge stays put
  delete-row   delete every text block on a given y (removes a whole line)
  insert       add a new text block at x/y
  render       rasterise a page (optionally a crop) to PNG for verification

All edits are byte-exact: nothing else in the PDF is touched.
"""
import argparse
import os
import re
import sys

import pypdf
from pypdf.generic import DecodedStreamObject

HEAD = re.compile(
    rb'BT\n(/F\d+) ([\d.]+) Tf\n([^\n]*)\n0 Tc\n(-?[\d.]+) (-?[\d.]+) Td\n\(')
TAIL = b') Tj\nET\n'

# Hebrew output must survive the Windows console's legacy code page.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass


def is_heb(s):
    return any('\u0590' <= c <= '\u05ff' for c in s)


# --------------------------------------------------------------- encoding --
class Font:
    """Per-font codec + metrics, for both payslip generations."""

    def __init__(self, page, name):
        fo = page['/Resources']['/Font'][name].get_object()
        self.two_byte = fo.get('/Subtype') == '/Type0'
        if self.two_byte:
            df = fo['/DescendantFonts'][0].get_object()
            self.dw = float(df.get('/DW', 1000))
            self.w = {}
            W, i = df['/W'], 0
            while i < len(W):
                start = int(W[i])
                if isinstance(W[i + 1], list):
                    for j, v in enumerate(W[i + 1]):
                        self.w[start + j] = float(v)
                    i += 2
                else:
                    v = float(W[i + 2])
                    for c in range(start, int(W[i + 1]) + 1):
                        self.w[c] = v
                    i += 3
            self.cid = {}
            cm = fo['/Encoding'].get_object().get_data().decode('latin1')
            body = cm.split('begincidrange')
            for chunk in body[1:]:
                for a, b, c in re.findall(
                        r'<([0-9A-Fa-f]+)><([0-9A-Fa-f]+)>\s*(\d+)',
                        chunk.split('endcidrange')[0]):
                    a, b, c = int(a, 16), int(b, 16), int(c)
                    for k in range(a, b + 1):
                        self.cid[k] = c + k - a
            for chunk in cm.split('begincidchar')[1:]:
                for a, c in re.findall(r'<([0-9A-Fa-f]+)>\s*(\d+)',
                                       chunk.split('endcidchar')[0]):
                    self.cid[int(a, 16)] = int(c)
        else:
            self.first = int(fo['/FirstChar'])
            self.widths = [float(v) for v in fo['/Widths']]

    # -- codec ------------------------------------------------------------
    def decode(self, raw):
        """Stream bytes -> readable logical text (reverses Hebrew runs back)."""
        s = (raw.decode('utf-16-be', 'replace') if self.two_byte
             else raw.decode('cp1255', 'replace'))
        return s[::-1] if is_heb(s) else s

    def encode(self, text, visual=False):
        """Logical text -> stream bytes (Hebrew reversed to visual order)."""
        if not visual and is_heb(text):
            text = text[::-1]
        return (text.encode('utf-16-be') if self.two_byte
                else text.encode('cp1255'))

    # -- metrics ----------------------------------------------------------
    def width(self, text, size, visual=False):
        if isinstance(size, (bytes, bytearray)):
            size = size.decode()
        if self.two_byte:
            total = sum(self.w.get(self.cid.get(ord(c), -1), self.dw)
                        for c in text)
        else:
            b = text.encode('cp1255')
            total = sum(self.widths[c - self.first] for c in b)
        return total * float(size) / 1000.0


class Block:
    """One `BT ... (text) Tj ... ET` run, tied to its byte span."""

    def __init__(self, data, m, end, font):
        self.name, self.size, self.pre = m.group(1), m.group(2), m.group(3)
        self.x, self.y = float(m.group(4)), float(m.group(5))
        self.raw = data[m.end():end - len(TAIL)]
        self.start, self.end = m.start(), end
        self.font = font

    @property
    def text(self):
        return self.font.decode(self.raw)

    def build(self, raw=None, x=None):
        return (b'BT\n' + self.name + b' ' + self.size + b' Tf\n' + self.pre
                + b'\n0 Tc\n' + fmt(self.x if x is None else x) + b' '
                + fmt(self.y) + b' Td\n('
                + (self.raw if raw is None else raw) + b') Tj\nET\n')


def blocks(page, data):
    """Scan text blocks, honouring balanced/escaped parens inside strings."""
    cache, out = {}, []
    for m in HEAD.finditer(data):
        i, depth = m.end(), 1
        while i < len(data):
            c = data[i:i + 1]
            if c == b'\\':
                i += 2
                continue
            if c == b'(':
                depth += 1
            elif c == b')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if not data[i:].startswith(TAIL):
            continue
        name = m.group(1).decode()
        if name not in cache:
            cache[name] = Font(page, name)
        out.append(Block(data, m, i + len(TAIL), cache[name]))
    return out


def page_font(page, index):
    return Font(page, '/F%d' % index)


# ------------------------------------------------------------------ utils --
def load(path):
    return pypdf.PdfWriter(clone_from=path)


def stream(page):
    return page.get_contents().get_data()


def store(page, data):
    ds = DecodedStreamObject()
    ds.set_data(data)
    page.replace_contents(ds)


def save(writer, src, dst):
    """Write out; if dst is in use (open in a viewer) fall back to -vN."""
    if dst is None:
        dst = src
    tmp = dst + '.tmp'
    writer.write(tmp)
    try:
        if os.path.exists(dst):
            os.remove(dst)
        os.replace(tmp, dst)
    except PermissionError:
        base, ext = os.path.splitext(dst)
        n = 2
        while os.path.exists('%s-v%d%s' % (base, n, ext)):
            n += 1
        dst = '%s-v%d%s' % (base, n, ext)
        os.replace(tmp, dst)
        print('! target was locked, wrote %s instead' % dst, file=sys.stderr)
    print(dst)
    return dst


def fmt(x):
    return ('%g' % round(x, 3)).encode()


def find_at(page, data, x, y, text=None):
    """Return the single block at (x, y), optionally checking its text."""
    hits = [b for b in blocks(page, data)
            if abs(b.x - x) < 0.01 and abs(b.y - y) < 0.01
            and (text is None or b.text == text)]
    if len(hits) != 1:
        raise SystemExit('expected 1 block at %s %s, found %d' % (x, y, len(hits)))
    return hits[0]


def apply(data, edits):
    """edits: list of (start, end, replacement bytes), applied right-to-left."""
    for s, e, rep in sorted(edits, reverse=True):
        data = data[:s] + rep + data[e:]
    return data


# --------------------------------------------------------------- commands --
def cmd_dump(a):
    r = pypdf.PdfReader(a.file)
    for i, p in enumerate(r.pages):
        if a.page is not None and i != a.page:
            continue
        for b in blocks(p, stream(p)):
            if a.y is not None and abs(b.y - a.y) > 0.01:
                continue
            t = b.text
            if a.grep and a.grep not in t:
                continue
            print('p%d  x=%-9s y=%-9s %s/%s  %s' % (
                i, fmt(b.x).decode(), fmt(b.y).decode(),
                b.name.decode(), b.size.decode(), t))


def cmd_set(a):
    w = load(a.file)
    p = w.pages[a.page]
    d = stream(p)
    b = find_at(p, d, a.x, a.y, a.old)
    new = b.font.encode(a.new, a.visual)
    if len(new) != len(b.raw):
        print('! length changed (%d -> %d): check alignment in the render'
              % (len(b.raw), len(new)), file=sys.stderr)
    store(p, apply(d, [(b.start, b.end, b.build(raw=new))]))
    save(w, a.file, a.out)


def cmd_replace_word(a):
    """Swap a word and shift x so the RIGHT edge is unchanged (RTL-safe)."""
    w = load(a.file)
    p = w.pages[a.page]
    d = stream(p)
    b = find_at(p, d, a.x, a.y, a.old)
    x = a.x + b.font.width(a.old, b.size) - b.font.width(a.new, b.size)
    store(p, apply(d, [(b.start, b.end,
                        b.build(raw=b.font.encode(a.new, a.visual), x=x))]))
    print('x %.3f -> %.3f' % (a.x, x), file=sys.stderr)
    save(w, a.file, a.out)


def cmd_delete_row(a):
    w = load(a.file)
    p = w.pages[a.page]
    d = stream(p)
    hits = [b for b in blocks(p, d) if abs(b.y - a.y) < 0.01]
    if not hits:
        raise SystemExit('no blocks at y=%s' % a.y)
    print('removed %d blocks' % len(hits), file=sys.stderr)
    store(p, apply(d, [(b.start, b.end, b'') for b in hits]))
    save(w, a.file, a.out)


def cmd_insert(a):
    w = load(a.file)
    p = w.pages[a.page]
    d = stream(p)
    anchor = find_at(p, d, a.after_x, a.after_y)
    font = page_font(p, a.font)
    blk = (b'BT\n/F%d %s Tf\n' % (a.font, str(a.size).encode()) + anchor.pre
           + b'\n0 Tc\n' + fmt(a.x) + b' ' + fmt(a.y) + b' Td\n('
           + font.encode(a.text, a.visual) + b') Tj\nET\n')
    store(p, apply(d, [(anchor.end, anchor.end, blk)]))
    save(w, a.file, a.out)


def cmd_render(a):
    import pypdfium2 as pdfium
    im = pdfium.PdfDocument(a.file)[a.page].render(scale=a.scale).to_pil()
    if a.crop:
        im = im.crop(tuple(int(v) for v in a.crop.split(',')))
    im.save(a.out)
    print('%s  %dx%d' % (a.out, im.size[0], im.size[1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(s):
        s.add_argument('file')
        s.add_argument('--page', type=int, default=0)
        s.add_argument('--visual', action='store_true',
                       help='text is already in stream (reversed) order')
        s.add_argument('-o', '--out', help='default: edit in place')

    s = sub.add_parser('dump', help='list text blocks')
    s.add_argument('file')
    s.add_argument('--page', type=int)
    s.add_argument('--y', type=float)
    s.add_argument('--grep')
    s.add_argument('--visual', action='store_true')
    s.set_defaults(fn=cmd_dump)

    s = sub.add_parser('set', help="replace one block's text, position kept")
    common(s)
    s.add_argument('--x', type=float, required=True)
    s.add_argument('--y', type=float, required=True)
    s.add_argument('--old')
    s.add_argument('--new', required=True)
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser('replace-word', help='replace a word, right edge fixed')
    common(s)
    s.add_argument('--x', type=float, required=True)
    s.add_argument('--y', type=float, required=True)
    s.add_argument('--old', required=True)
    s.add_argument('--new', required=True)
    s.set_defaults(fn=cmd_replace_word)

    s = sub.add_parser('delete-row', help='delete every block on a y line')
    common(s)
    s.add_argument('--y', type=float, required=True)
    s.set_defaults(fn=cmd_delete_row)

    s = sub.add_parser('insert', help='add a text block')
    common(s)
    s.add_argument('--x', type=float, required=True)
    s.add_argument('--y', type=float, required=True)
    s.add_argument('--text', required=True)
    s.add_argument('--font', type=int, default=0, help='0=regular 1=bold')
    s.add_argument('--size', type=int, default=10)
    s.add_argument('--after-x', type=float, required=True, help='anchor block x')
    s.add_argument('--after-y', type=float, required=True, help='anchor block y')
    s.set_defaults(fn=cmd_insert)

    s = sub.add_parser('render', help='page -> PNG (verification)')
    s.add_argument('file')
    s.add_argument('out')
    s.add_argument('--page', type=int, default=0)
    s.add_argument('--scale', type=float, default=2.0)
    s.add_argument('--crop', help='x0,y0,x1,y1 in pixels')
    s.set_defaults(fn=cmd_render)

    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()

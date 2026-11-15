#!/usr/bin/env python3
"""Offline, structural verification of the libskia.so 1-byte WebP alpha patch.

`patch_libskia.py --verify` only checks "one byte differs, and it has the
expected value". That proves the file was produced correctly, but NOT that
the byte is in the right place, in the right function, feeding the right
call, and that the resulting ELF is still loadable.

This tool checks all of that, using only the two files on disk:

  1. byte-level diff (exactly one byte, expected offset/values, hashes)
  2. ELF identity: header / PHDR / SHDR tables byte-identical
  3. every section byte-identical except the single byte in .text
  4. VA <-> file-offset mapping through PT_LOAD; patch offset must be in an
     executable PT_LOAD, and VA must really equal the file offset
  5. no relocation entry covers the patched word (linker would overwrite it)
  6. the patched word is inside SkWEBPImageDecoder::setDecodeConfig (dynsym)
  7. ARM instruction semantics: only the immediate changes (imm 1 -> 0),
     opcode / condition / registers unchanged; ARM mode, little-endian
  8. the very next instruction is BL to SkBitmap::setIsOpaque, resolved
     from the ELF dynsym (not guessed from AOSP source)
  9. all call sites of setIsOpaque in the whole library are enumerated, with
     their r1 argument, to bound the blast radius
 10. no integrity-sensitive metadata (DT_HASH/DT_GNU_HASH, build-id,
     debuglink CRC, .ARM.exidx) is affected

Pure stdlib + optional capstone for pretty disassembly. Never touches the TV.

Usage:
    python verify_libskia.py <original.so> <patched.so> [--json report.json]
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

PATCH_OFF = 0x1139BC
ORIG_WORD = 0xE3A01001          # mov r1, #1   (LE bytes 01 10 a0 e3)
PATCH_WORD = 0xE3A01000         # mov r1, #0   (LE bytes 00 10 a0 e3)
EXPECTED_ORIG_SHA = '4642931be450d0f16747d2930a13aea851249ff14815abfc571f446a05bb23d7'
EXPECTED_PATCH_SHA = 'f8e4328c5fea2aef49542013386fce76f57252156059ddcaeda2fe2718ecaef7'

SHT_DYNSYM = 11
SHT_REL = 9
PT_LOAD = 1
PF_X = 1

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(dict(name=name, ok=bool(ok), detail=str(detail)))
    print('[%s] %-58s %s' % ('PASS' if ok else 'FAIL', name, detail))
    return bool(ok)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def u16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def cstr(b, o):
    e = b.find(b'\0', o)
    return b[o:e if e >= 0 else len(b)].decode('utf-8', 'replace')


def demangle(n):
    """Enough Itanium demangling for Skia C++ symbols (class::method)."""
    if not n.startswith('_ZN'):
        return n
    import re
    s = n[3:]
    parts = []
    while s and s[0].isdigit():
        m = re.match(r'(\d+)', s)
        if not m:
            break
        length = int(m.group(1))
        s = s[m.end():]
        parts.append(s[:length])
        s = s[length:]
        if s.startswith('E'):
            break
    return '::'.join(parts) if parts else n


def arm_bl_target(word, va):
    """Target of an ARM B/BL (cond-encoded) instruction."""
    if (word & 0x0F000000) != 0x0B000000:
        return None
    imm = word & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    return (va + 8 + (imm << 2)) & 0xFFFFFFFF


class ELF32:
    def __init__(self, path):
        self.path = str(path)
        self.b = Path(path).read_bytes()
        b = self.b
        assert b[:4] == b'\x7fELF', 'not an ELF file'
        self.is32 = b[4] == 1
        self.le = b[5] == 1
        assert self.is32 and self.le, 'expected ELF32 little-endian'
        self.machine = u16(b, 18)
        self.etype = u16(b, 16)
        self.phoff, self.shoff = u32(b, 28), u32(b, 32)
        self.phentsize, self.phnum = u16(b, 42), u16(b, 44)
        self.shentsize, self.shnum, self.shstrndx = u16(b, 46), u16(b, 48), u16(b, 50)

        self.loads = []
        for i in range(self.phnum):
            o = self.phoff + i * self.phentsize
            p_type, p_off, p_vaddr, _, p_filesz, _, p_flags, _ = struct.unpack_from('<IIIIIIII', b, o)
            if p_type == PT_LOAD:
                self.loads.append(dict(type=p_type, off=p_off, vaddr=p_vaddr,
                                      filesz=p_filesz, flags=p_flags))
        self.sections = []
        for i in range(self.shnum):
            o = self.shoff + i * self.shentsize
            (name, typ, flags, addr, off, size, link, info, align, entsize) = \
                struct.unpack_from('<IIIIIIIIII', b, o)
            self.sections.append(dict(name=name, type=typ, flags=flags, addr=addr,
                                      off=off, size=size, link=link, info=info,
                                      align=align, entsize=entsize))
        shstr = self.sections[self.shstrndx] if self.shstrndx < len(self.sections) else None
        for sec in self.sections:
            sec['sname'] = cstr(b, shstr['off'] + sec['name']) if shstr else '?'
        self.by_name = {s['sname']: s for s in self.sections}

    def containing_load(self, va):
        for p in self.loads:
            if p['vaddr'] <= va < p['vaddr'] + p['filesz']:
                return p
        return None

    def va2off(self, va):
        p = self.containing_load(va)
        return p['off'] + (va - p['vaddr']) if p else None

    def off2va(self, off):
        p = self.containing_load_by_off(off)
        return p['vaddr'] + (off - p['off']) if p else None

    def containing_load_by_off(self, off):
        for p in self.loads:
            if p['off'] <= off < p['off'] + p['filesz']:
                return p
        return None

    def symbols(self):
        out = []
        for sec in self.sections:
            if sec['type'] != SHT_DYNSYM:
                continue
            step = sec['entsize'] or 16
            strsec = self.sections[sec['link']]
            strb = self.b[strsec['off']:strsec['off'] + strsec['size']]
            for o in range(sec['off'], sec['off'] + sec['size'], step):
                name = u32(self.b, o)
                value, size = u32(self.b, o + 4), u32(self.b, o + 8)
                shndx = u16(self.b, o + 14)
                nm = cstr(strb, name)
                if nm:
                    out.append(dict(name=nm, pretty=demangle(nm), defined=shndx != 0,
                                    value=value, size=size, thumb=bool(value & 1)))
        return out

    def reloc_offsets(self):
        out = []
        for sec in self.sections:
            if sec['type'] != SHT_REL:
                continue
            step = sec['entsize'] or 8
            for o in range(sec['off'], sec['off'] + sec['size'], step):
                out.append((sec['sname'], u32(self.b, o)))
        return out

    def owner(self, va, syms):
        best = None
        for s in syms:
            if not s['defined'] or not s['size']:
                continue
            a = s['value'] & ~1
            if a <= va < a + s['size'] and (best is None or a > best['value'] & ~1):
                best = s
        return best


def disasm_word(word, addr=PATCH_OFF):
    try:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
        b = struct.pack('<I', word)
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        for ins in md.disasm(b, addr):
            return '%s %s' % (ins.mnemonic, ins.op_str)
    except Exception:
        return '(capstone unavailable)'


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    orig_p, patched_p = Path(sys.argv[1]), Path(sys.argv[2])
    json_out = None
    if '--json' in sys.argv:
        json_out = Path(sys.argv[sys.argv.index('--json') + 1])

    a, c = orig_p.read_bytes(), patched_p.read_bytes()
    print('=== libskia.so patch verification (offline) ===')
    print('original : %s  %d bytes  sha256 %s' % (orig_p, len(a), sha(a)))
    print('patched  : %s  %d bytes  sha256 %s' % (patched_p, len(c), sha(c)))
    print()

    # --- 1. byte-level diff -------------------------------------------------
    print('--- 1. byte-level diff')
    check('same file size', len(a) == len(c), '%d' % len(a))
    diffs = [i for i, (x, y) in enumerate(zip(a, c)) if x != y]
    check('exactly one differing byte', diffs == [PATCH_OFF],
          'diffs=%s' % ['0x%X' % d for d in diffs[:8]])
    check('original byte at 0x%X is 0x01' % PATCH_OFF,
          a[PATCH_OFF:PATCH_OFF + 4] == struct.pack('<I', ORIG_WORD),
          a[PATCH_OFF:PATCH_OFF + 4].hex(' '))
    check('patched byte at 0x%X is 0x00' % PATCH_OFF,
          c[PATCH_OFF:PATCH_OFF + 4] == struct.pack('<I', PATCH_WORD),
          c[PATCH_OFF:PATCH_OFF + 4].hex(' '))
    check('original sha256 matches documented value',
          sha(a) == EXPECTED_ORIG_SHA, sha(a))
    check('patched sha256 matches documented value',
          sha(c) == EXPECTED_PATCH_SHA, sha(c))

    # --- 2. ELF identity / structure ---------------------------------------
    print()
    print('--- 2. ELF structure')
    e = ELF32(orig_p)
    f = ELF32(patched_p)
    check('ELF32 / little-endian / EM_ARM / ET_DYN',
          e.machine == 40 and e.etype == 3, 'machine=%d type=%d' % (e.machine, e.etype))
    # compare the three *tables* only, not the whole prefix: in this .so the
    # section header table sits at the very end of the file, so a naive
    # [0:shoff+...] slice would compare the entire binary (incl. .text).
    hdr_a = (a[:52],
             a[e.phoff:e.phoff + e.phnum * e.phentsize],
             a[e.shoff:e.shoff + e.shnum * e.shentsize])
    hdr_c = (c[:52],
             c[f.phoff:f.phoff + f.phnum * f.phentsize],
             c[f.shoff:f.shoff + f.shnum * f.shentsize])
    check('ELF header byte-identical', hdr_a[0] == hdr_c[0], '52 bytes')
    check('program header table byte-identical', hdr_a[1] == hdr_c[1],
          '%d bytes @0x%X' % (len(hdr_a[1]), e.phoff))
    check('section header table byte-identical', hdr_a[2] == hdr_c[2],
          '%d bytes @0x%X' % (len(hdr_a[2]), e.shoff))
    check('program header list identical', e.loads == f.loads,
          '%d PT_LOAD segments' % len(e.loads))
    check('section header list identical', e.sections == f.sections,
          '%d sections' % len(e.sections))
    print('     PT_LOAD segments:')
    for p in e.loads:
        print('       off=0x%08x vaddr=0x%08x filesz=0x%08x flags=%d%s' %
              (p['off'], p['vaddr'], p['filesz'], p['flags'],
               '  <-- patch segment' if p['off'] <= PATCH_OFF < p['off'] + p['filesz'] else ''))

    print()
    print('--- 3. section hashes (all sections except the patched byte)')
    for sec in e.sections:
        if not sec['size'] or sec['type'] == 8:   # SHT_NOBITS has no file bytes
            continue
        ba = a[sec['off']:sec['off'] + sec['size']]
        bc = c[sec['off']:sec['off'] + sec['size']]
        same = ba == bc
        expected = (sec['sname'] == '.text')
        if same:
            ok = not expected
        else:
            # the only allowed difference is the one patched byte inside .text
            d = [i for i, (x, y) in enumerate(zip(ba, bc)) if x != y]
            ok = expected and d == [PATCH_OFF - sec['off']]
        check('section %-18s %s' % (sec['sname'], '(expected 1-byte diff)' if expected else 'unchanged'),
              ok, 'diffs=%d' % (0 if same else 1))

    # --- 4. VA <-> offset mapping -------------------------------------------
    print()
    print('--- 4. virtual address mapping')
    p = e.containing_load_by_off(PATCH_OFF)
    check('patch offset lies inside a PT_LOAD segment', p is not None,
          'off=0x%X' % PATCH_OFF)
    if p:
        va = e.off2va(PATCH_OFF)
        check('PT_LOAD is executable (PF_X)', bool(p['flags'] & PF_X),
              'flags=%d' % p['flags'])
        check('VA of patch offset == file offset (documented assumption)',
              va == PATCH_OFF, 'VA=0x%08X off=0x%08X' % (va, PATCH_OFF))
        check('va2off(VA) round-trips to patch offset',
              e.va2off(va) == PATCH_OFF, 'va2off=0x%X' % (e.va2off(va) or -1))
    text = e.by_name.get('.text')
    check('.text section contains the patch offset',
          bool(text and text['off'] <= PATCH_OFF < text['off'] + text['size']),
          '.text off=0x%X size=0x%X' % (text['off'], text['size']) if text else 'missing')
    if text:
        check('.text addr == .text off',
              text['addr'] == text['off'],
              'addr=0x%X off=0x%X' % (text['addr'], text['off']))

    # --- 5. relocations -----------------------------------------------------
    print()
    print('--- 5. relocations (linker must not overwrite the patched word)')
    rels = e.reloc_offsets()
    patch_va = e.off2va(PATCH_OFF)
    covering = [(n, o) for n, o in rels if o <= patch_va < o + 4]
    check('no REL entry targets the patched word', not covering,
          '%d relocation entries total, covering=%s' % (len(rels), covering))
    blind = [r for r in rels if patch_va - 4 <= r[1] < patch_va + 8]
    check('neighbouring +/- 4 bytes also have no relocation', not blind,
          str(blind))

    # --- 6. symbol ownership ------------------------------------------------
    print()
    print('--- 6. symbol ownership (from ELF dynsym, not AOSP source)')
    syms = e.symbols()
    by_addr = {}
    for s in syms:
        if s['defined']:
            by_addr[s['value'] & ~1] = s
    owner = e.owner(patch_va, syms)
    check('patch word belongs to SkWEBPImageDecoder::setDecodeConfig',
          owner is not None and owner['pretty'] == 'SkWEBPImageDecoder::setDecodeConfig',
          owner['pretty'] if owner else 'no owning symbol')
    if owner:
        print('     %s  VA=0x%X size=%d' %
              (owner['name'], owner['value'] & ~1, owner['size']))

    # --- 7. instruction semantics ------------------------------------------
    print()
    print('--- 7. ARM instruction semantics')
    wa, wc = u32(a, PATCH_OFF), u32(c, PATCH_OFF)
    check('original word == e3a01001 (mov r1,#1)', wa == ORIG_WORD, '0x%08X %s' % (wa, disasm_word(wa)))
    check('patched word == e3a01000 (mov r1,#0)', wc == PATCH_WORD, '0x%08X %s' % (wc, disasm_word(wc)))
    check('only the immediate bit changed (xor == 1)', (wa ^ wc) == 1,
          'xor=0x%08X (opcode/cond/regs unchanged)' % (wa ^ wc))
    check('condition code is AL (unconditional)', (wc >> 28) == 0xE,
          'cond=0x%X' % (wc >> 28))

    print('     surrounding instructions (original):')
    for off in range(PATCH_OFF - 0x20, PATCH_OFF + 0x14, 4):
        w = u32(a, off)
        note = ''
        t = arm_bl_target(w, off)
        if t is not None and t in by_addr:
            note = '  -> ' + by_addr[t]['pretty']
        print('       0x%06X  %08X  %-28s%s' %
              (off, w, disasm_word(w, off), note))

    # --- 8. the BL immediately after the patch ------------------------------
    print()
    print('--- 8. callee of the next BL')
    next_w = u32(a, PATCH_OFF + 4)
    tgt = arm_bl_target(next_w, PATCH_OFF + 4)
    callee = by_addr.get(tgt) if tgt is not None else None
    check('instruction at 0x%X is BL' % (PATCH_OFF + 4), tgt is not None,
          '0x%08X %s' % (next_w, disasm_word(next_w, PATCH_OFF + 4)))
    check('BL target resolves to SkBitmap::setIsOpaque',
          callee is not None and callee['pretty'] == 'SkBitmap::setIsOpaque',
          'target=0x%X %s' % (tgt or 0, callee['name'] if callee else '?'))
    prev_w = u32(a, PATCH_OFF - 4)
    check('r0 is set up right before (mov r0, r8)',
          (prev_w & 0xFFFFFFF0) == 0xE1A00000,
          '0x%08X %s' % (prev_w, disasm_word(prev_w, PATCH_OFF - 4)))
    check('patched file has the identical BL (control flow unchanged)',
          u32(c, PATCH_OFF + 4) == next_w,
          '0x%08X' % u32(c, PATCH_OFF + 4))

    # --- 9. blast radius: all setIsOpaque call sites ------------------------
    print()
    print('--- 9. all SkBitmap::setIsOpaque call sites in .text')
    iso = [s for s in syms if s['defined'] and s['pretty'] == 'SkBitmap::setIsOpaque']
    iso_addr = (iso[0]['value'] & ~1) if iso else None
    hits = []
    if text and iso_addr:
        lo, hi = text['off'], text['off'] + text['size']
        for o in range(lo, min(hi, len(a) - 4), 4):
            w = u32(a, o)
            if arm_bl_target(w, e.off2va(o)) == iso_addr:
                va = e.off2va(o)
                argw = u32(a, o - 4)
                arg = 'r1=#%d' % (argw & 0xFF) if (argw & 0xFFFFFF00) == 0xE3A01000 else 'r1=dynamic'
                own = e.owner(va, syms)
                hits.append((va, o, arg, own['pretty'] if own else '?'))
    for va, o, arg, own in hits:
        print('     0x%08X  %-12s  in %s' % (va, arg, own))
    check('setIsOpaque is called from a bounded number of sites',
          len(hits) > 0, '%d call sites' % len(hits))
    patched_site = [h for h in hits if h[1] == PATCH_OFF + 4]
    check('the WebP setDecodeConfig site is among them, with r1=#1',
          len(patched_site) == 1 and patched_site[0][2] == 'r1=#1',
          str(patched_site))
    other_true = [h for h in hits if h[2] == 'r1=#1' and h[1] != PATCH_OFF + 4]
    print('     other unconditional setIsOpaque(true) sites: %d' % len(other_true))
    for h in other_true:
        print('       0x%08X in %s' % (h[0], h[3]))
    # Cross-check the diagnosis: an alpha-capable format (PNG) decides the
    # flag dynamically; only formats that genuinely cannot carry alpha, plus
    # the buggy WebP decoder, hard-code "true".
    hardcoded_owners = sorted({h[3].split('::')[0] for h in other_true})
    allowed = {'SkBMPImageDecoder', 'SkJPEGImageDecoder', 'SkWBMPImageDecoder'}
    check('other hard-coded setIsOpaque(true) sites are all alpha-free formats',
          set(hardcoded_owners) <= allowed,
          'owners=%s (BMP/JPEG/WBMP cannot carry alpha)' % hardcoded_owners)
    png_sites = [h for h in hits if 'SkPNGImageDecoder' in h[3]]
    check('PNG decoder decides opacity dynamically (control case)',
          bool(png_sites) and all(h[2] == 'r1=dynamic' for h in png_sites),
          '%d PNG sites, args=%s' % (len(png_sites), [h[2] for h in png_sites]))
    print('     => WebP is the ONLY alpha-capable format with a hard-coded')
    print('        setIsOpaque(true): this is the anomaly the patch fixes.')

    # --- 10. integrity metadata --------------------------------------------
    print()
    print('--- 10. integrity / loadability metadata')
    sensitive = ['.hash', '.gnu.hash', '.dynsym', '.dynstr', '.rel.dyn',
                 '.rel.plt', '.ARM.exidx', '.ARM.extab', '.note.gnu.build-id',
                 '.gnu_debuglink', '.dynamic', '.got', '.plt']
    for nm in sensitive:
        s = e.by_name.get(nm)
        if not s or not s['size'] or s['type'] == 8:
            continue
        same = a[s['off']:s['off'] + s['size']] == c[s['off']:s['off'] + s['size']]
        check('%s unchanged' % nm, same, 'size=%d' % s['size'])
    print('     NOTE: .note.gnu.build-id / .gnu_debuglink are identifiers/CRC for')
    print('           debug symbols only; the Android dynamic linker does NOT')
    print('           verify them against the file. DT_HASH/DT_GNU_HASH hash')
    print('           symbol NAMES, not code bytes. No re-signing is required.')

    # --- summary -------------------------------------------------------------
    failed = [r for r in RESULTS if not r['ok']]
    print()
    print('=== SUMMARY: %d checks, %d passed, %d failed ===' %
          (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for r in failed:
        print('    FAILED: %s -- %s' % (r['name'], r['detail']))
    print('VERDICT: %s' % ('PATCH STRUCTURALLY VALID' if not failed else 'DO NOT FLASH'))
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            'original': str(orig_p), 'patched': str(patched_p),
            'original_sha256': sha(a), 'patched_sha256': sha(c),
            'patch_offset': PATCH_OFF,
            'setIsOpaque_call_sites': [
                dict(va=h[0], off=h[1], arg=h[2], owner=h[3]) for h in hits],
            'checks': RESULTS,
            'verdict': 'PASS' if not failed else 'FAIL',
        }, indent=2, ensure_ascii=False), encoding='utf-8')
        print('JSON report: %s' % json_out)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

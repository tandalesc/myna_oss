// pycore.js: the WebAssembly module of the core, made ready for a host that is not JavaScript. python/dbcore_wasm.py (class
// Core, under Pyodide) is written over it; nothing here knows Python, a caller in JavaScript can use it as well.
//
// What it does that the caller cannot:
// - The two imports of the module (dbc_ext_read, dbc_ext_write) are fixed when it is instantiated. Here they forward to
//   functions that each core gets later (set_ext, set_dev, set_store), and to nothing until then.
// - The imports are not told which core calls. Every call into the module that can call out notes its core first.
// - 64-bit values cross as BigInt, 32-bit results come out signed. The functions below take and return plain numbers
//   wherever the value fits (a BigInt above 2^53 - 1).
// - Buffers are copied through dbc_alloc / dbc_dealloc; the views of the module's memory are taken again after it grew.
// - The reserved device numbers ("Reserved device numbers" in the README) go to the read and write functions of the core
//   like any other, with one option: the three store calls of the NAND command machine can be served here, on a chip
//   image that stays a JavaScript buffer (nandStore), without a call of the host's functions.
// - An exception thrown by a function of the host must not unwind the module in the middle of an instruction: it is
//   kept, the run is asked to stop, and the call into the module that caused it throws it when it returns.
//
// A classic script with no import and no export, so that one file serves a classic worker (importScripts('pycore.js')),
// a page (<script>), a module (import './pycore.js') and node (require, or createRequire(import.meta.url) from a module):
// it puts one object, dbcorePy, on globalThis, and on module.exports where that exists.
//
//   const g = dbcorePy.instantiate(bytes or WebAssembly.Module)      synchronous; instantiateAsync returns a promise
//   const k = g.core()                                               one core: the dbc_* calls without the pointer
//   k.set_ext(read, write, user)       read(dev, off, size) -> value, write(dev, off, size, value); user: true = they
//                                      take one more argument in front (always 0)
//   k.set_dev(dev, read, write)        the functions of one external window alone: read(off, size), write(off, size, value)
//   k.set_store(g.nandStore(image))    the chip's contents here (null: back to the read function)
// SPDX-License-Identifier: MIT
(function (root) {
  'use strict';
  const RAW = 0x840, BLOCK = 64, NAND_BUF = 176;               // a page with its spare area; pages per block; NandCmd.buf
  const STORE_READ = 0xFFFFFFFE, STORE_PROGRAM = 0xFFFFFFFD, STORE_ERASE = 0xFFFFFFFC;
  const SAFE = BigInt(Number.MAX_SAFE_INTEGER);
  const big = v => BigInt.asUintN(64, BigInt(v));
  const num = b => { b = BigInt.asUintN(64, b); return b <= SAFE ? Number(b) : b; };

  // The contents of a NAND chip as the store of the command machine. image: Uint8Array of whole pages (RAW bytes each, data
  // and spare area), or null; pages beyond it read as erased. Changed pages go to `overlay` (page -> Uint8Array) and the
  // image is not written; with inPlace they are written into the image, and only pages beyond it go to the overlay.
  function nandStore(image, inPlace) {
    const overlay = new Map(), dirty = new Set();
    const imgPages = image ? Math.floor(image.length / RAW) : 0;
    const s = {
      image, overlay, dirty, inPlace: !!inPlace, reads: 0, programs: 0, erases: 0,
      read(page, dst) {                              // the page into dst (RAW bytes)
        s.reads++;
        const o = overlay.get(page);
        if (o !== undefined) dst.set(o);
        else if (page < imgPages) dst.set(image.subarray(page * RAW, (page + 1) * RAW));
        else dst.fill(0xFF);
        return 0;
      },
      program(page, src) {                           // bits go from 1 to 0 only; 0 = done
        s.programs++;
        let t;
        if (s.inPlace && page < imgPages) { t = image.subarray(page * RAW, (page + 1) * RAW); dirty.add(page); }
        else { t = new Uint8Array(RAW); s.read(page, t); s.reads--; overlay.set(page, t); }
        for (let i = 0; i < RAW; i++) t[i] &= src[i];
        return 0;
      },
      erase(page) {                                  // the block that holds the page
        s.erases++;
        const first = page - page % BLOCK;
        for (let p = first; p < first + BLOCK; p++) {
          if (s.inPlace && p < imgPages) { image.fill(0xFF, p * RAW, (p + 1) * RAW); dirty.add(p); }
          else overlay.set(p, new Uint8Array(RAW).fill(0xFF));
        }
        return 0;
      },
      page(page) { const t = new Uint8Array(RAW); s.read(page, t); s.reads--; return t; },      // a copy, for a caller outside
      changed() { return [...new Set([...overlay.keys(), ...dirty])].sort((a, b) => a - b); },
      // the changed pages as one buffer: per page u32 number, RAW bytes, ascending (the layout of the NAND model's overlay file)
      exportChanged() {
        const pages = s.changed(), out = new Uint8Array(pages.length * (4 + RAW)), d = new DataView(out.buffer);
        pages.forEach((p, i) => { d.setUint32(i * (4 + RAW), p, true); s.read(p, out.subarray(i * (4 + RAW) + 4, (i + 1) * (4 + RAW))); s.reads--; });
        return out;
      },
      importChanged(buf) {
        const d = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
        for (let at = 0; at + 4 + RAW <= buf.length; at += 4 + RAW) {
          const p = d.getUint32(at, true), src = buf.subarray(at + 4, at + 4 + RAW);
          if (s.inPlace && p < imgPages) { image.set(src, p * RAW); dirty.add(p); } else overlay.set(p, src.slice());
        }
      },
    };
    return s;
  }

  function wrap(module) {
    let cur = null;                                  // the core that is inside the module now
    let x = null;
    const fail = (k, e) => { if (k.err === null) k.err = e; x.dbc_request_stop(k.c); };
    const env = {
      dbc_ext_read(dev, off, size) {
        const k = cur;
        if (k === null) return 0;
        try {
          dev >>>= 0; off >>>= 0;
          if (dev >= STORE_ERASE && k.store !== null) {
            const s = k.store, b = new Uint8Array(x.memory.buffer, k.nbuf, RAW);
            return dev === STORE_READ ? s.read(off, b) : dev === STORE_PROGRAM ? s.program(off, b) : dev === STORE_ERASE ? s.erase(off) : 0;
          }
          const f = k.devR[dev];
          if (f !== undefined) return f(off, size);
          if (k.rd !== null) return k.rd(dev, off, size);
          const base = k.bases[dev];                 // no function: the window reads as memory, as natively
          if (base === undefined || x.dbc_mem_read(k.c, (base + off) >>> 0, zone, 4)) return 0;
          return new DataView(x.memory.buffer).getUint32(zone, true);
        } catch (e) { fail(k, e); return 0; }
      },
      dbc_ext_write(dev, off, size, value) {
        const k = cur;
        if (k === null) return;
        try {
          dev >>>= 0;
          const f = k.devW[dev];
          if (f !== undefined) f(off >>> 0, size, value >>> 0);
          else if (k.wr !== null) k.wr(dev, off >>> 0, size, value >>> 0);
        } catch (e) { fail(k, e); }
      },
    };
    x = new WebAssembly.Instance(module, { env }).exports;
    const zone = x.dbc_alloc(64);                    // out-parameters; never moved
    let sp = 0, sn = 0;                              // a scratch buffer for copies, grown as needed
    const scratch = n => {
      if (n > sn) { if (sp) x.dbc_dealloc(sp, sn); sn = Math.max(4096, n); sp = x.dbc_alloc(sn); }
      return sp;
    };
    const release = () => { if (sn > (1 << 20)) { x.dbc_dealloc(sp, sn); sp = sn = 0; } };      // a big copy does not stay
    let dv = null;
    const D = () => (dv !== null && dv.buffer === x.memory.buffer) ? dv : (dv = new DataView(x.memory.buffer));
    const u8 = (p, n) => new Uint8Array(x.memory.buffer, p, n);
    const copyIn = bytes => { const p = scratch(bytes.length); u8(p, bytes.length).set(bytes); return p; };

    const g = {
      exports: x, nandStore,
      // the module's memory, for the structures of dbc_dev_regs: words little-endian, a view (valid until the memory grows), a copy in
      peek32: p => D().getUint32(p, true),
      poke32: (p, v) => D().setUint32(p, v, true),
      peek64: p => num(D().getBigUint64(p, true)),
      poke64: (p, v) => D().setBigUint64(p, big(v), true),
      view: u8,
      put: (p, bytes) => u8(p, bytes.length).set(bytes),
      memory_bytes: () => x.memory.buffer.byteLength,

      core() {
        const c = x.dbc_new();
        const k = { c, rd: null, wr: null, devR: [], devW: [], store: null, nbuf: 0, err: null, bases: [] };
        // a call that can reach the imports: note the core, and afterwards throw what a function of the host threw
        const leave = prev => { cur = prev; if (k.err !== null) { const e = k.err; k.err = null; throw e; } };
        const event = i => {                         // [icount, kind, pc, far, fsr], or undefined past the end
          if (x.dbc_event(c, i, zone, zone + 8, zone + 12, zone + 16, zone + 20)) return undefined;
          const d = D();
          return [num(d.getBigUint64(zone, true)), d.getUint32(zone + 8, true), d.getUint32(zone + 12, true), d.getUint32(zone + 16, true), d.getUint32(zone + 20, true)];
        };
        return {
          ptr: c,
          close() { x.dbc_free(c); },
          map_ram: (addr, size) => x.dbc_map_ram(c, addr, size),
          map_ext(addr, size, dev) { const r = x.dbc_map_ext(c, addr, size, dev); if (!r) k.bases[dev >>> 0] = addr; return r; },
          map_dev: (addr, size, kind) => x.dbc_map_dev(c, addr, size, kind),
          set_ext(rd, wr, user) {
            rd = rd == null ? null : rd; wr = wr == null ? null : wr;
            k.rd = rd !== null && user ? (dev, off, size) => rd(0, dev, off, size) : rd;
            k.wr = wr !== null && user ? (dev, off, size, value) => wr(0, dev, off, size, value) : wr;
          },
          set_dev(dev, rd, wr) {
            if (rd == null) delete k.devR[dev]; else k.devR[dev] = rd;
            if (wr == null) delete k.devW[dev]; else k.devW[dev] = wr;
          },
          set_store(s) { k.store = s == null ? null : s; k.nbuf = x.dbc_dev_regs(c, 7) + NAND_BUF; },
          // memory: mem_read gives a view of a copy, good until the next call that copies; undefined = a bad span
          mem_read(addr, n) { const p = scratch(n); return x.dbc_mem_read(c, addr, p, n) ? undefined : u8(p, n); },
          mem_read32: addr => x.dbc_mem_read(c, addr, zone, 4) ? undefined : D().getUint32(zone, true),
          mem_write(addr, bytes) { const r = x.dbc_mem_write(c, addr, copyIn(bytes), bytes.length); release(); return r; },
          load_snapshot(bytes) { const r = x.dbc_load_snapshot(c, copyIn(bytes), bytes.length); release(); return r; },
          reg: i => x.dbc_reg(c, i) >>> 0,
          set_reg: (i, v) => x.dbc_set_reg(c, i, v),
          regs() { const r = []; for (let i = 0; i < 17; i++) r.push(x.dbc_reg(c, i) >>> 0); return r; },
          set_irq: level => x.dbc_set_irq(c, level),
          set_fiq: level => x.dbc_set_fiq(c, level),
          // instructions completed * 8 + the stop reason
          run(n) { const prev = cur; cur = k; const done = x.dbc_run(c, BigInt(n)); leave(prev); return Number(done) * 8 + x.dbc_stop_reason(c); },
          // whole slices with the host's work between them done in the module (Cpu::run_slices); due, until: ns, -1 = none.
          // The module's result * 8 + the stop reason of the slice left to the host; undefined: a module without the call
          run_slices(n, max, due, until, lastPc) {
            if (x.dbc_run_slices === undefined) return undefined;
            const prev = cur; cur = k; const r = x.dbc_run_slices(c, BigInt(n), max, big(due), big(until), lastPc); leave(prev);
            return Number(r) * 8 + x.dbc_stop_reason(c);
          },
          slice_pc: () => x.dbc_slice_pc(c) >>> 0,
          stop_reason: () => x.dbc_stop_reason(c) >>> 0,
          request_stop: () => x.dbc_request_stop(c),
          add_hook: vaddr => x.dbc_add_hook(c, vaddr),
          del_hook: vaddr => x.dbc_del_hook(c, vaddr),
          icount: () => num(x.dbc_icount(c)),
          event_count: () => x.dbc_event_count(c) >>> 0,
          event,
          events() { const r = [], n = x.dbc_event_count(c) >>> 0; for (let i = 0; i < n; i++) r.push(event(i)); return r; },
          clear_events: () => x.dbc_clear_events(c),
          // compiled devices. dev_read: the value, -1 a bad argument, -2 declined
          dev_read(kind, off, size) {
            const prev = cur; cur = k; const r = x.dbc_dev_read(c, kind, off, size, zone + 32); leave(prev);
            return r < 0 ? -1 : r ? D().getUint32(zone + 32, true) : -2;
          },
          dev_write(kind, off, size, value) { const prev = cur; cur = k; const r = x.dbc_dev_write(c, kind, off, size, value); leave(prev); return r; },
          dev_get: (kind, field) => num(x.dbc_dev_get(c, kind, field)),
          dev_set: (kind, field, value) => x.dbc_dev_set(c, kind, field, big(value)),
          dev_advance(kind) { const prev = cur; cur = k; x.dbc_dev_advance(c, kind); leave(prev); },
          dev_next_event(kind) { const t = BigInt.asUintN(64, x.dbc_dev_next_event(c, kind)); return t === 0xFFFFFFFFFFFFFFFFn ? undefined : num(t); },
          dev_regs: kind => x.dbc_dev_regs(c, kind) >>> 0,
          port_grant(bytes, n, write) { return x.dbc_port_grant(c, write ? 0 : copyIn(bytes), n, write ? 1 : 0); },
          // the count; the bytes a write lease took in are then in taken(count)
          port_take(cap) { return x.dbc_port_take(c, cap ? scratch(cap) : 0, cap) >>> 0; },
          taken: n => u8(sp, n),
          clock_set: (insns, skipped) => x.dbc_clock_set(c, big(insns), big(skipped)),
          clock_rate: ns => x.dbc_clock_rate(c, ns),
          clock_get: what => num(x.dbc_clock_get(c, what)),
          set_line(n, level) { const prev = cur; cur = k; x.dbc_set_line(c, n, level); leave(prev); },
          line: n => x.dbc_line(c, n),
          irq_out: () => x.dbc_irq_out(c) >>> 0,
          // the state container as a buffer of its own; undefined when the module could not write it
          state_save() {
            const n = x.dbc_state_size(c) >>> 0, p = x.dbc_alloc(n);
            const got = x.dbc_state_save(c, p, n) >>> 0;
            const out = n && got === n ? u8(p, n).slice() : undefined;
            x.dbc_dealloc(p, n);
            return out;
          },
          state_load(bytes) { const p = x.dbc_alloc(bytes.length); u8(p, bytes.length).set(bytes); const r = x.dbc_state_load(c, p, bytes.length); x.dbc_dealloc(p, bytes.length); return r; },
        };
      },
    };
    return g;
  }

  const api = {
    nandStore,
    instantiate: wasm => wrap(wasm instanceof WebAssembly.Module ? wasm : new WebAssembly.Module(wasm)),
    instantiateAsync: wasm => Promise.resolve(wasm instanceof WebAssembly.Module ? wasm : WebAssembly.compile(wasm)).then(wrap),
  };
  root.dbcorePy = api;
  if (typeof module === 'object' && module !== null && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : self);

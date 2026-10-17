// dbreplay RECORDING [REPEATS] [--split]: run a recorded stretch again on a fresh core, with no host. A recording
// (python/record.py, which also documents the file) holds the state at the start and then, in order, every call the host
// made into the core and every call the core made out. This program makes the same calls, answers each read callback
// with the recorded value, and compares what the core does with the records: every callback and its arguments, every
// result, and at the end the registers, the counts and the SHA-256 of the state container. The first difference is
// named with its record and ends the program with status 1. A version 3 recording ends with a checksum record (the
// SHA-256 of every byte before it): it is checked before anything runs, and a file that fails is refused (status 1) with the
// two hashes named; a version 2 file has none, and a line on stderr says so.
// One JSON line per repeat, the same text as tools/replay_wasm.mjs and the page print but for the time: instructions
// run, last stop reason, seconds, million instructions per second, accesses served by the compiled devices (reads,
// writes), callbacks answered, host calls made, exceptions taken by kind, r0-r15 + CPSR, the hash of the final state.
// --split adds a line to stderr: the seconds spent inside dbc_run, and of those inside the callbacks.
// SPDX-License-Identifier: MIT

use dbcore::*;
use std::ffi::c_void;
use std::time::Instant;

const TEXT: u8 = 1; const STATE: u8 = 2; const HOOKS: u8 = 3; const END: u8 = 4; const CHECKSUM: u8 = 5;
const RUN: u8 = 0x10; const RUN_END: u8 = 0x11; const CLOCK_SET: u8 = 0x12; const CLOCK_RATE: u8 = 0x13; const SET_LINE: u8 = 0x14;
const SET_IRQ: u8 = 0x15; const SET_FIQ: u8 = 0x16; const DEV_ADVANCE: u8 = 0x17; const DEV_SET: u8 = 0x18; const DEV_WRITE: u8 = 0x19;
const DEV_READ: u8 = 0x1A; const PORT_GRANT: u8 = 0x1B; const PORT_TAKE: u8 = 0x1C; const SHARED: u8 = 0x1D; const MEM_WRITE: u8 = 0x1E;
const SET_REG: u8 = 0x1F; const REQUEST_STOP: u8 = 0x20; const ADD_HOOK: u8 = 0x21; const DEL_HOOK: u8 = 0x22; const MAP_RAM: u8 = 0x23;
const MAP_EXT: u8 = 0x24; const MAP_DEV: u8 = 0x25; const CLEAR_EVENTS: u8 = 0x26; const STATE_LOAD: u8 = 0x27; const RESULT: u8 = 0x2F;
const RD: u8 = 0x30; const RD_END: u8 = 0x31; const WR: u8 = 0x32; const WR_END: u8 = 0x33;
const SHARED_MAX: usize = 1 << 20;
const END_LEN: usize = 344;
const EVENTS_KEEP: u32 = 4096;
const DEVICES: [&str; 9] = ["nand_data", "nand_ctrl", "nand_ale", "timer", "vic0", "vic1", "nand_cle", "sysctl", "clkprof"];
const EVENTS: [&str; 6] = ["dabt", "pabt", "swi", "und", "irq", "fiq"];

fn name(kind: u8) -> &'static str {
    match kind {
        TEXT => "text", STATE => "state", HOOKS => "hooks", END => "end", RUN => "run", RUN_END => "run_end", CLOCK_SET => "clock_set",
        CLOCK_RATE => "clock_rate", SET_LINE => "set_line", SET_IRQ => "set_irq", SET_FIQ => "set_fiq", DEV_ADVANCE => "dev_advance",
        DEV_SET => "dev_set", DEV_WRITE => "dev_write", DEV_READ => "dev_read", PORT_GRANT => "port_grant", PORT_TAKE => "port_take",
        SHARED => "shared", MEM_WRITE => "mem_write", SET_REG => "set_reg", REQUEST_STOP => "request_stop", ADD_HOOK => "add_hook",
        DEL_HOOK => "del_hook", MAP_RAM => "map_ram", MAP_EXT => "map_ext", MAP_DEV => "map_dev", CLEAR_EVENTS => "clear_events",
        STATE_LOAD => "state_load", RESULT => "result", RD => "rd", RD_END => "rd_end", WR => "wr", WR_END => "wr_end", _ => "?",
    }
}

fn u32at(b: &[u8], o: usize) -> u32 { u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]) }
fn u64at(b: &[u8], o: usize) -> u64 { u32at(b, o) as u64 | (u32at(b, o + 4) as u64) << 32 }

/// One record: its number, kind, byte offset in the file and payload.
#[derive(Clone, Copy)]
struct Rec<'a> { i: u64, kind: u8, at: usize, p: &'a [u8] }

/// The replay of one recording on one core. Reached from the callbacks through a raw pointer, so nothing here is held
/// across a call into the core.
struct Replay<'a> {
    core: *mut Core,
    data: &'a [u8],
    pos: usize,
    next_i: u64,
    done: u64, rd: u64, wr: u64, host: u64,
    ev: [u64; 6],
    split: bool, cb_secs: f64, run_secs: f64, depth: u32,
}

impl<'a> Replay<'a> {
    /// A difference, named with record `r`; None: the file itself is broken.
    fn fail(&self, r: Option<Rec<'a>>, what: &str) -> ! {
        match r {
            Some(r) => eprintln!("dbreplay: MISMATCH at record #{} ({}, byte {}): {}", r.i, name(r.kind), r.at, what),
            None => eprintln!("dbreplay: {}", what),
        }
        std::process::exit(1);
    }
    fn next(&mut self) -> Rec<'a> {
        let d = self.data;
        if self.pos + 5 > d.len() { self.fail(None, &format!("the recording ends after record #{} with no end record", self.next_i.wrapping_sub(1))); }
        let (kind, n) = (d[self.pos], u32at(d, self.pos + 1) as usize);
        if self.pos + 5 + n > d.len() { self.fail(None, &format!("the recording is cut short in record #{}", self.next_i)); }
        let r = Rec { i: self.next_i, kind, at: self.pos, p: &d[self.pos + 5..self.pos + 5 + n] };
        self.pos += 5 + n; self.next_i += 1;
        r
    }
    fn need(&self, r: Rec<'a>, n: usize) { if r.p.len() < n { self.fail(Some(r), &format!("payload of {} bytes, {} needed", r.p.len(), n)); } }
    unsafe fn count_events(&mut self) {
        let mut k = 0u32;
        for i in 0..dbc_event_count(self.core) {
            dbc_event(self.core, i, std::ptr::null_mut(), &mut k, std::ptr::null_mut(), std::ptr::null_mut(), std::ptr::null_mut());
            if (1..=6).contains(&k) { self.ev[k as usize - 1] += 1; }
        }
        dbc_clear_events(self.core);
    }
}

/// The record that has to follow a call with a result.
unsafe fn result<'a>(r: *mut Replay<'a>, call: Rec<'a>, got: i64, aux: u32, bytes: &[u8]) {
    let x = (*r).next();
    if x.kind != RESULT { (*r).fail(Some(x), &format!("the result of {} (record #{}) is expected here", name(call.kind), call.i)); }
    (*r).need(x, 12);
    let (want, waux) = (u64at(x.p, 0) as i64, u32at(x.p, 8));
    if want != got || waux != aux || &x.p[12..] != bytes {
        (*r).fail(Some(x), &format!("{} (record #{}) returned {} / {:#x} / {} bytes here, recorded {} / {:#x} / {} bytes{}", name(call.kind), call.i, got, aux, bytes.len(),
            want, waux, x.p.len() - 12, if want == got && waux == aux && x.p.len() - 12 == bytes.len() { " (the bytes differ)" } else { "" }));
    }
}

/// Make the call of record `c`.
unsafe fn call<'a>(r: *mut Replay<'a>, c: Rec<'a>) {
    let core = (*r).core;
    let p = c.p;
    (*r).host += 1;
    match c.kind {
        RUN => {
            (*r).need(c, 8);
            let t = if (*r).split { Some(Instant::now()) } else { None };
            (*r).depth += 1;
            let done = dbc_run(core, u64at(p, 0));
            (*r).depth -= 1;
            if let Some(t) = t { (*r).run_secs += t.elapsed().as_secs_f64(); }
            let why = dbc_stop_reason(core);
            let x = (*r).next();
            if x.kind != RUN_END {
                (*r).fail(Some(x), &format!("the run (record #{}) ended here after {} instructions with stop reason {}; in the recording the core went on to this", c.i, done, why));
            }
            (*r).need(x, 12);
            if u64at(x.p, 0) != done || u32at(x.p, 8) != why {
                (*r).fail(Some(x), &format!("the run (record #{}) completed {} instructions with stop reason {}, recorded {} with {}", c.i, done, why, u64at(x.p, 0), u32at(x.p, 8)));
            }
            (*r).done += done;
            if (*r).depth == 0 && dbc_event_count(core) >= EVENTS_KEEP { (*r).count_events(); }
        }
        CLOCK_SET => { (*r).need(c, 16); dbc_clock_set(core, u64at(p, 0), u64at(p, 8)); }
        CLOCK_RATE => { (*r).need(c, 8); dbc_clock_rate(core, f64::from_bits(u64at(p, 0))); }
        SET_LINE => { (*r).need(c, 8); dbc_set_line(core, u32at(p, 0), u32at(p, 4) as i32); }
        SET_IRQ => { (*r).need(c, 4); dbc_set_irq(core, u32at(p, 0) as i32); }
        SET_FIQ => { (*r).need(c, 4); dbc_set_fiq(core, u32at(p, 0) as i32); }
        DEV_ADVANCE => { (*r).need(c, 4); dbc_dev_advance(core, u32at(p, 0)); }
        DEV_SET => { (*r).need(c, 16); dbc_dev_set(core, u32at(p, 0), u32at(p, 4), u64at(p, 8)); }
        DEV_WRITE => { (*r).need(c, 16); let x = dbc_dev_write(core, u32at(p, 0), u32at(p, 4), u32at(p, 8), u32at(p, 12)); result(r, c, x as i64, 0, &[]); }
        DEV_READ => {
            (*r).need(c, 12);
            let mut v = 0u32;
            let x = dbc_dev_read(core, u32at(p, 0), u32at(p, 4), u32at(p, 8), &mut v);
            result(r, c, x as i64, if x == 1 { v } else { 0 }, &[]);
        }
        PORT_GRANT => {
            (*r).need(c, 8);
            let (write, len) = (u32at(p, 0), u32at(p, 4));
            let data = &p[8..];
            if !data.is_empty() && data.len() != len as usize { (*r).fail(Some(c), "the bytes of the lease do not have the length given"); }
            let x = dbc_port_grant(core, if data.is_empty() { std::ptr::null() } else { data.as_ptr() }, len, write as i32);
            result(r, c, x as i64, 0, &[]);
        }
        PORT_TAKE => {
            (*r).need(c, 4);
            let cap = (u32at(p, 0) as usize).min(dev::nand::LEASE_MAX);
            let filled = dbc_dev_get(core, 1, 3) != 0;
            let mut out = vec![0u8; cap.max(1)];
            let n = dbc_port_take(core, out.as_mut_ptr(), cap as u32);
            result(r, c, n as i64, 0, if filled { &out[..(n as usize).min(cap)] } else { &[] });
        }
        SHARED => {
            (*r).need(c, 12);
            let (kind, off, total, n) = (u32at(p, 0), u32at(p, 4) as usize, u32at(p, 8) as usize, p.len() - 12);
            let dst = dbc_dev_regs(core, kind);
            if dst.is_null() { (*r).fail(Some(c), &format!("this core shares no structure for device kind {}", kind)); }
            if total > SHARED_MAX || off + n > total || ((1..=3).contains(&kind) && total != 48) { (*r).fail(Some(c), "the span does not lie in the structure"); }
            std::ptr::copy_nonoverlapping(p[12..].as_ptr(), dst.add(off), n);
        }
        MEM_WRITE => { (*r).need(c, 4); let x = dbc_mem_write(core, u32at(p, 0), p[4..].as_ptr(), (p.len() - 4) as u32); result(r, c, x as i64, 0, &[]); }
        SET_REG => { (*r).need(c, 8); dbc_set_reg(core, u32at(p, 0), u32at(p, 4)); }
        REQUEST_STOP => dbc_request_stop(core),
        ADD_HOOK => { (*r).need(c, 4); let x = dbc_add_hook(core, u32at(p, 0)); result(r, c, x as i64, 0, &[]); }
        DEL_HOOK => { (*r).need(c, 4); dbc_del_hook(core, u32at(p, 0)); }
        MAP_RAM => { (*r).need(c, 8); let x = dbc_map_ram(core, u32at(p, 0), u32at(p, 4)); result(r, c, x as i64, 0, &[]); }
        MAP_EXT => { (*r).need(c, 12); let x = dbc_map_ext(core, u32at(p, 0), u32at(p, 4), u32at(p, 8)); result(r, c, x as i64, 0, &[]); }
        MAP_DEV => { (*r).need(c, 12); let x = dbc_map_dev(core, u32at(p, 0), u32at(p, 4), u32at(p, 8)); result(r, c, x as i64, 0, &[]); }
        CLEAR_EVENTS => (*r).count_events(),
        STATE_LOAD => { let x = dbc_state_load(core, p.as_ptr(), p.len() as u32); result(r, c, x as i64, 0, &[]); }
        _ => (*r).fail(Some(c), "a call of the host is expected here"),
    }
}

/// Inside a callback: make the host's calls up to the record that ends it, and return that record.
unsafe fn inside<'a>(r: *mut Replay<'a>, end: u8) -> Rec<'a> {
    loop {
        let x = (*r).next();
        if x.kind == end { return x; }
        if !(RUN..RESULT).contains(&x.kind) { (*r).fail(Some(x), &format!("the callback is not closed: {} expected", name(end))); }
        call(r, x);
    }
}

unsafe extern "C" fn ext_read(user: *mut c_void, dev: u32, off: u32, size: u32) -> u32 {
    let r = user as *mut Replay;
    let t = if (*r).split { Some(Instant::now()) } else { None };
    let x = (*r).next();
    if x.kind != RD || x.p.len() < 12 || (u32at(x.p, 0), u32at(x.p, 4), u32at(x.p, 8)) != (dev, off, size) {
        let was = if x.kind == RD && x.p.len() >= 12 { format!("device {} offset {:#x} size {}", u32at(x.p, 0), u32at(x.p, 4), u32at(x.p, 8)) } else { "no read callback".to_string() };
        (*r).fail(Some(x), &format!("the core reads device {} offset {:#x} size {} here; recorded: {}", dev, off, size, was));
    }
    (*r).rd += 1;
    let e = inside(r, RD_END);
    (*r).need(e, 4);
    if let Some(t) = t { (*r).cb_secs += t.elapsed().as_secs_f64(); }
    u32at(e.p, 0)
}

unsafe extern "C" fn ext_write(user: *mut c_void, dev: u32, off: u32, size: u32, value: u32) {
    let r = user as *mut Replay;
    let t = if (*r).split { Some(Instant::now()) } else { None };
    let x = (*r).next();
    if x.kind != WR || x.p.len() < 16 || (u32at(x.p, 0), u32at(x.p, 4), u32at(x.p, 8), u32at(x.p, 12)) != (dev, off, size, value) {
        let was = if x.kind == WR && x.p.len() >= 16 { format!("device {} offset {:#x} size {} value {:#x}", u32at(x.p, 0), u32at(x.p, 4), u32at(x.p, 8), u32at(x.p, 12)) } else { "no write callback".to_string() };
        (*r).fail(Some(x), &format!("the core writes device {} offset {:#x} size {} value {:#x} here; recorded: {}", dev, off, size, value, was));
    }
    (*r).wr += 1;
    inside(r, WR_END);
    if let Some(t) = t { (*r).cb_secs += t.elapsed().as_secs_f64(); }
}

// ---- SHA-256 (FIPS 180-4) ---------------------------------------------------------------------------------------------
const K256: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];

fn sha256(data: &[u8]) -> [u8; 32] {
    let mut h: [u32; 8] = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    let mut block = |b: &[u8]| {
        let mut w = [0u32; 64];
        for i in 0..16 { w[i] = u32::from_be_bytes([b[4 * i], b[4 * i + 1], b[4 * i + 2], b[4 * i + 3]]); }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ w[i - 15] >> 3;
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ w[i - 2] >> 10;
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = v[4] & v[5] ^ !v[4] & v[6];
            let t1 = v[7].wrapping_add(s1).wrapping_add(ch).wrapping_add(K256[i]).wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let t2 = s0.wrapping_add(v[0] & v[1] ^ v[0] & v[2] ^ v[1] & v[2]);
            v = [t1.wrapping_add(t2), v[0], v[1], v[2], v[3].wrapping_add(t1), v[4], v[5], v[6]];
        }
        for i in 0..8 { h[i] = h[i].wrapping_add(v[i]); }
    };
    let whole = data.len() / 64 * 64;
    for b in data[..whole].chunks_exact(64) { block(b); }
    let mut tail = data[whole..].to_vec();
    tail.push(0x80);
    while tail.len() % 64 != 56 { tail.push(0); }
    tail.extend_from_slice(&(data.len() as u64 * 8).to_be_bytes());
    for b in tail.chunks_exact(64) { block(b); }
    let mut out = [0u8; 32];
    for i in 0..8 { out[4 * i..4 * i + 4].copy_from_slice(&h[i].to_be_bytes()); }
    out
}

const TRAILER: usize = 5 + 32;

/// The checksum of a recording, checked before it runs: the text to say, or the text of the refusal.
fn check(data: &[u8]) -> Result<String, String> {
    if data.len() < 12 || &data[..8] != b"DBCREC1\0" || !(u32at(data, 8) == 2 || u32at(data, 8) == 3) { return Err("not a recording (no DBCREC1, version 2 or 3)".into()); }
    if u32at(data, 8) == 2 { return Ok("no checksum (a version 2 recording)".into()); }
    let none = || "CHECKSUM FAILED: the file (version 3) does not end with a checksum record: it is cut short or damaged".to_string();
    if data.len() < 12 + TRAILER { return Err(none()); }
    let n = data.len() - TRAILER;
    if data[n] != CHECKSUM || u32at(data, n + 1) != 32 { return Err(none()); }
    let found = hex(&sha256(&data[..n]));
    let want = hex(&data[n + 5..]);
    if found != want { return Err(format!("CHECKSUM FAILED: the file says SHA-256 {} over its first {} bytes, but they hash to {}: the file is damaged or cut short", want, n, found)); }
    Ok(format!("checksum good: SHA-256 {} over the first {} bytes of the file", found, n))
}

fn hex(b: &[u8]) -> String { b.iter().map(|x| format!("{:02x}", x)).collect() }

/// One replay of the whole recording. Returns the line; a difference ends the program.
unsafe fn replay(data: &[u8], split: bool) -> String {
    let core = dbc_new();
    let mut rp = Replay { core, data, pos: 12, next_i: 0, done: 0, rd: 0, wr: 0, host: 0, ev: [0; 6], split, cb_secs: 0.0, run_secs: 0.0, depth: 0 };
    let r: *mut Replay = &mut rp;
    dbc_set_ext(core, Some(ext_read), Some(ext_write), r as *mut c_void);
    // the head: text, state, hooks
    let mut loaded = false;
    let first = loop {
        let x = (*r).next();
        match x.kind {
            TEXT => {}
            STATE => { if dbc_state_load(core, x.p.as_ptr(), x.p.len() as u32) != 0 { (*r).fail(Some(x), "the core does not load this state container"); } loaded = true; }
            HOOKS => { for o in (0..x.p.len() / 4 * 4).step_by(4) { dbc_add_hook(core, u32at(x.p, o)); } }
            _ => break x,
        }
    };
    if !loaded { (*r).fail(Some(first), "no state record before the first call"); }
    let t = Instant::now();
    let mut x = first;
    while x.kind != END {
        if !(RUN..RESULT).contains(&x.kind) || x.kind == RUN_END { (*r).fail(Some(x), "a call of the host is expected here"); }
        call(r, x);
        x = (*r).next();
    }
    let secs = t.elapsed().as_secs_f64();
    // the end: what the run was at this point when it was recorded
    if x.p.len() != END_LEN { (*r).fail(Some(x), "the end record does not have its length"); }
    (*r).count_events();
    let stop = dbc_stop_reason(core);
    let regs: Vec<u32> = (0..17).map(|i| dbc_reg(core, i)).collect();
    let served: Vec<u64> = (1..10).flat_map(|k| [dbc_dev_get(core, k, 0xF0), dbc_dev_get(core, k, 0xF1)]).collect();
    let n = dbc_state_size(core);
    let mut state = vec![0u8; n as usize];
    if n == 0 || dbc_state_save(core, state.as_mut_ptr(), n) != n { (*r).fail(Some(x), "dbc_state_save failed"); }
    let digest = sha256(&state);
    let p = x.p;
    let mut bad: Vec<String> = Vec::new();
    if u64at(p, 0) != (*r).done { bad.push(format!("instructions run {} (recorded {})", (*r).done, u64at(p, 0))); }
    if u64at(p, 8) != dbc_icount(core) { bad.push(format!("instruction count {} (recorded {})", dbc_icount(core), u64at(p, 8))); }
    if u32at(p, 16) != stop { bad.push(format!("stop reason {} (recorded {})", stop, u32at(p, 16))); }
    for i in 0..17 { if u32at(p, 20 + 4 * i) != regs[i] { bad.push(format!("{} {:08x} (recorded {:08x})", if i == 16 { "CPSR".to_string() } else { format!("r{}", i) }, regs[i], u32at(p, 20 + 4 * i))); } }
    for i in 0..6 { if u64at(p, 88 + 8 * i) != (*r).ev[i] { bad.push(format!("{} exceptions {} (recorded {})", EVENTS[i], (*r).ev[i], u64at(p, 88 + 8 * i))); } }
    for i in 0..18 { if u64at(p, 136 + 8 * i) != served[i] { bad.push(format!("{} {} served {} (recorded {})", DEVICES[i / 2], if i & 1 == 0 { "reads" } else { "writes" }, served[i], u64at(p, 136 + 8 * i))); } }
    if u64at(p, 280) != (*r).rd || u64at(p, 288) != (*r).wr { bad.push(format!("callbacks {} / {} (recorded {} / {})", (*r).rd, (*r).wr, u64at(p, 280), u64at(p, 288))); }
    if u64at(p, 296) != (*r).host { bad.push(format!("host calls {} (recorded {})", (*r).host, u64at(p, 296))); }
    if u64at(p, 304) != n as u64 { bad.push(format!("state container of {} bytes (recorded {})", n, u64at(p, 304))); }
    if p[312..344] != digest { bad.push(format!("state hash {} (recorded {})", hex(&digest), hex(&p[312..344]))); }
    if !bad.is_empty() { (*r).fail(Some(x), &format!("every call was replayed, but the end differs: {}", bad.join("; "))); }
    if (*r).pos + if data[8] == 3 { TRAILER } else { 0 } != data.len() { (*r).fail(None, "bytes after the end record"); }
    if split { eprintln!("dbreplay: {:.4} s in all, {:.4} s inside dbc_run, of those {:.4} s inside the callbacks (replayed host calls included)", secs, (*r).run_secs, (*r).cb_secs); }
    let line = format!("{{\"done\":{},\"stop\":{},\"secs\":{:.4},\"mips\":{:.1},\"served\":{{{}}},\"callbacks\":{{\"rd\":{},\"wr\":{}}},\"host_calls\":{},\"events\":{{{}}},\"regs\":\"{}\",\"state\":\"{}\"}}",
        (*r).done, stop, secs, if secs > 0.0 { (*r).done as f64 / secs / 1e6 } else { 0.0 },
        (0..DEVICES.len()).map(|i| format!("\"{}\":[{},{}]", DEVICES[i], served[2 * i], served[2 * i + 1])).collect::<Vec<_>>().join(","),
        (*r).rd, (*r).wr, (*r).host,
        (0..6).map(|i| format!("\"{}\":{}", EVENTS[i], (*r).ev[i])).collect::<Vec<_>>().join(","),
        regs.iter().map(|x| format!("{:08x}", x)).collect::<Vec<_>>().join(" "), hex(&digest));
    dbc_free(core);
    line
}

fn main() {
    let mut a: Vec<String> = std::env::args().skip(1).collect();
    let split = a.iter().any(|x| x == "--split");
    a.retain(|x| x != "--split");
    if a.is_empty() || a.len() > 2 { eprintln!("usage: dbreplay RECORDING [REPEATS] [--split]"); std::process::exit(2); }
    let data = match std::fs::read(&a[0]) { Ok(d) => d, Err(e) => { eprintln!("dbreplay: {}: {}", a[0], e); std::process::exit(2); } };
    match check(&data) { Ok(t) => eprintln!("dbreplay: {}", t), Err(t) => { eprintln!("dbreplay: {}", t); std::process::exit(1); } }
    let reps: usize = a.get(1).map(|x| x.parse().expect("repeats")).unwrap_or(1);
    for _ in 0..reps { println!("{}", unsafe { replay(&data, split) }); }
}

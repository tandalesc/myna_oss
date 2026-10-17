// The compiled NAND flash model: the data port, the register file of the controller, and the command state machine of the
// chip with the ECC engine. The contents of the chip stay outside, behind three calls (the store).
//
// Two ways of working, chosen by the model outside through `NandCmd::on`:
//
// off: the model outside keeps commands, addresses, the page register, ECC, program and erase, and the core helps with
// - the data port: the model leases the rest of its page register to the port (grant). Until it takes the lease back, a
//   read of the data window hands out the next bytes, little-endian, and nothing else happens; with a write lease the
//   bytes of a write go into the buffer. Whatever the port cannot serve (no lease of that kind, not enough bytes left)
//   is declined and reaches the model as before, which first takes the lease back and accounts for the bytes;
// - the register file (served only while `reg_on` is set): the ready poll of the controller window (2 = ready; a busy
//   count is used up one poll at a time), its two timing registers (stored), and address cycles in the address-latch
//   window (queued for the model, at most eight, while `ale_ok` is set). The model shares these words through NandRegs.
//
// on: the state of the chip and of the controller is here (NandCmd, which the model outside filled in), and every access
// to the four windows is served here: command and address cycles, data in and out of the page register, the status and
// ID bytes, the ECC accumulator over the data stream, the control, status, ECC, ready and timing registers. A command
// that reads, programs or erases calls the store once: the host is asked through its read callback with one of the
// device numbers STORE_* and the page number as the offset, and finds or leaves the page in `NandCmd::buf`. What the
// machine does not hold is declined with nothing changed (a row outside the chip, a ninth address cycle, another
// register of the controller, a position past POS_MAX, a full log, no store) and reaches the model outside, which takes
// the state back first.
// SPDX-License-Identifier: MIT

use crate::state::{Rd, Wr};

/// Longest lease, bytes.
pub const LEASE_MAX: usize = 1 << 20;
/// A page with its spare area: the page register.
pub const RAW: usize = 0x840;
const BLOCK_PAGES: u32 = 64;
/// Entries of the log; with the log switched on the machine declines what would add to a full one.
pub const LOG_CAP: usize = 1024;
/// "None" of prog_page, cb_page, last_row; `cmd` when no command was written yet.
pub const NONE: u32 = 0xFFFF_FFFF;
pub const NO_CMD: u32 = 0x100;
/// Above this position in the page register the machine declines (the model outside counts without a limit).
pub const POS_MAX: u32 = 0x7FFF_0000;

// Device numbers of the store calls (through the host's read callback; offset = page, size 4).
/// Fill `NandCmd::buf` with the page (data and spare area). The value returned is not used.
pub const STORE_READ: u32 = 0xFFFF_FFFE;
/// Program the page from `NandCmd::buf`: bits go from 1 to 0 only. Returns 0, or 1 when the program failed.
pub const STORE_PROGRAM: u32 = 0xFFFF_FFFD;
/// Erase the block that holds the page. Returns 0, or 1 when the erase failed.
pub const STORE_ERASE: u32 = 0xFFFF_FFFC;

// NandCmd::mode
pub const M_IDLE: u32 = 0;
pub const M_ID: u32 = 1;
pub const M_READ: u32 = 2;
pub const M_STATUS: u32 = 3;
pub const M_PROG: u32 = 5;
pub const M_ADDR: u32 = 6;

// Kinds of log entries and indices of `NandCmd::count`. An entry is two words: kind | value << 8 | row << 32, and a
// second number. ECC: value = the register read, row = the last page read, second = bytes fed. READ: row, second =
// column. CBREAD, PROGRAM: row. ERASE: row = first page of the block. UNKNOWN: value = the command byte.
pub const L_ECC: usize = 1;
pub const L_READ: usize = 2;
pub const L_CBREAD: usize = 3;
pub const L_PROGRAM: usize = 4;
pub const L_ERASE: usize = 5;
pub const L_UNKNOWN: usize = 6;
pub const L_RESET: usize = 7;

/// The words the model outside reads and writes directly (dbc_dev_regs, kinds 1-3). Layout fixed: 64 bytes.
#[repr(C)]
pub struct NandRegs {
    /// 0: every register access goes to the model.
    pub reg_on: u32,
    /// Ready polls that still read "busy".
    pub busy: u32,
    /// The two timing registers.
    pub tim: [u32; 2],
    /// Address cycles may be queued here; number queued; the queue.
    pub ale_ok: u32,
    pub npend: u32,
    pub pend: [u8; 8],
    /// Offsets in the controller window: the ready poll, the timing registers.
    pub off_ready: u32,
    pub off_tim0: u32,
    pub off_tim1: u32,
    pub pad: u32,
    /// Reads and writes served here.
    pub served: u64,
    pub wserved: u64,
}

/// The state of the chip and of the controller while the command machine is on (dbc_dev_regs, kind 7). The model outside
/// fills it in and sets `on`, and reads it back after clearing `on`. Layout fixed (the README lists the offsets).
#[repr(C)]
pub struct NandCmd {
    /// 0: the model outside has the state and serves; the core does what the text above says under "off".
    pub on: u32,
    /// M_*.
    pub mode: u32,
    /// The last command byte, NO_CMD before the first.
    pub cmd: u32,
    /// Address cycles since the last command that starts an address; the bytes.
    pub naddr: u32,
    pub addr: [u8; 8],
    /// Position in the page register (or in the ID bytes).
    pub pos: u32,
    /// The status byte of the chip: 0xC0, bit 0 = the last program or erase failed.
    pub status: u32,
    /// The page register holds a page that was read.
    pub buf_valid: u32,
    /// The control register: bit 6 = the ECC engine takes in the data stream.
    pub ctrl_val: u32,
    /// Page of the open program, the source of a copy-back, the last page read (NONE when there is none).
    pub prog_page: u32,
    pub cb_page: u32,
    pub last_row: u32,
    /// Pages of the chip.
    pub pages: u32,
    /// ECC engine: bytes fed; row parities of the bytes with an odd / even index bit; column parities.
    pub ecc_idx: u64,
    pub ecc_odd: u32,
    pub ecc_even: u32,
    pub ecc_col: u32,
    /// The ID bytes.
    pub nids: u32,
    pub ids: [u8; 8],
    /// Offsets in the controller window: control, status, ECC accumulator.
    pub off_ctrl: u32,
    pub off_status: u32,
    pub off_ecc: u32,
    /// The log of commands and ECC reads is kept; entries in it.
    pub log_on: u32,
    pub nlog: u32,
    /// Bytes of this structure (set by the core).
    pub size: u32,
    /// Commands and ECC reads served, by L_*.
    pub count: [u64; 8],
    /// The page register.
    pub buf: [u8; RAW],
    pub log: [[u64; 2]; LOG_CAP],
}

/// What a command needs from the store before it completes.
#[derive(Clone, Copy, PartialEq)]
pub enum Need { Nothing, Read(u32), Program(u32), Erase(u32) }

/// Column parities of a byte: bit 2k = parity of its bits whose index has bit k clear, bit 2k + 1 = bit k set.
const COL: [u8; 256] = {
    let mut t = [0u8; 256];
    let mut b = 0;
    while b < 256 {
        let mut k = 0;
        while k < 3 {
            let mut m1 = 0u32;
            let mut j = 0;
            while j < 8 { if (j >> k) & 1 != 0 { m1 |= 1 << j; } j += 1; }
            let x = b as u32;
            t[b] |= (((x & m1).count_ones() & 1) as u8) << (2 * k + 1);
            t[b] |= (((x & !m1 & 0xff).count_ones() & 1) as u8) << (2 * k);
            k += 1;
        }
        b += 1;
    }
    t
};

impl NandCmd {
    fn new() -> NandCmd {
        NandCmd { on: 0, mode: M_IDLE, cmd: NO_CMD, naddr: 0, addr: [0; 8], pos: 0, status: 0xC0, buf_valid: 0, ctrl_val: 0, prog_page: NONE, cb_page: NONE,
                  last_row: NONE, pages: 0, ecc_idx: 0, ecc_odd: 0, ecc_even: 0, ecc_col: 0, nids: 0, ids: [0; 8], off_ctrl: 0x40, off_status: 0x44,
                  off_ecc: 0x54, log_on: 0, nlog: 0, size: core::mem::size_of::<NandCmd>() as u32, count: [0; 8], buf: [0; RAW], log: [[0; 2]; LOG_CAP] }
    }
    #[inline(always)] fn ecc_feed(&mut self, b: u8) {
        if b.count_ones() & 1 != 0 { let i = self.ecc_idx as u32 & 511; self.ecc_odd ^= i; self.ecc_even ^= !i & 511; }
        self.ecc_col ^= COL[b as usize] as u32;
        self.ecc_idx += 1;
    }
    /// The 24 parities: bit 2k / 2k + 1 = row parity k of the even / odd side (k = 0..8), bits 18-23 the column parities.
    pub fn ecc_fn(&self) -> u32 {
        let mut v = self.ecc_col << 18;
        for k in 0..9 { v |= (self.ecc_even >> k & 1) << (2 * k) | (self.ecc_odd >> k & 1) << (2 * k + 1); }
        v
    }
    fn ecc_reg(&self) -> u32 { !self.ecc_fn() & 0xFF_FFFF }
    fn col(&self) -> u32 { if self.naddr >= 2 { (self.addr[0] as u32 | (self.addr[1] as u32) << 8) & 0xFFF } else { 0 } }
    /// The row from the address cycles after the first `skip`.
    fn row(&self, skip: usize) -> u64 {
        let mut r = 0u64;
        for i in skip..self.naddr as usize { r |= (self.addr[i] as u64) << (8 * (i - skip)); }
        r
    }
    fn two(&self) -> bool { self.cmd == 0x80 || self.cmd == 0x85 }
    /// The data of a program begins: the page is the row of the address cycles (a second 85h with a column only keeps it).
    fn prog_begin(&mut self) {
        let (col, row) = (self.col(), self.row(2));
        if self.cmd == 0x80 { self.prog_page = row as u32; self.buf = [0xFF; RAW]; }
        else if self.naddr > 2 { self.prog_page = row as u32; }
        self.pos = col; self.mode = M_PROG;
    }
    /// prog_begin would name a page outside the chip.
    fn prog_begin_bad(&self) -> bool { (self.cmd == 0x80 || self.naddr > 2) && self.row(2) >= self.pages as u64 }
    fn log(&mut self, kind: usize, value: u32, row: u32, second: u64) {
        self.count[kind] += 1;
        if self.log_on != 0 && (self.nlog as usize) < LOG_CAP {
            self.log[self.nlog as usize] = [kind as u64 | (value as u64) << 8 | (row as u64) << 32, second];
            self.nlog += 1;
        }
    }
    fn log_full(&self) -> bool { self.log_on != 0 && self.nlog as usize >= LOG_CAP }
}

pub struct Nand {
    pub regs: NandRegs,
    pub cmd: NandCmd,
    buf: Vec<u8>,
    pub pos: u32,
    pub limit: u32,
    pub active: bool,
    pub wactive: bool,
}

impl Nand {
    pub fn new() -> Nand {
        Nand { regs: NandRegs { reg_on: 0, busy: 0, tim: [0; 2], ale_ok: 0, npend: 0, pend: [0; 8], off_ready: 0, off_tim0: 0, off_tim1: 0, pad: 0, served: 0, wserved: 0 },
               cmd: NandCmd::new(), buf: Vec::new(), pos: 0, limit: 0, active: false, wactive: false }
    }

    /// Lease `data` to reads, or a buffer of the same length to writes. False: too long.
    pub fn grant(&mut self, data: &[u8], write: bool) -> bool {
        if data.len() > LEASE_MAX { return false; }
        self.buf.clear(); self.buf.extend_from_slice(data);
        self.pos = 0; self.limit = data.len() as u32;
        if write { self.wactive = true } else { self.active = true }
        true
    }
    /// End the lease: the number of bytes handed out or taken in, and the bytes taken in by a write lease.
    pub fn take(&mut self) -> (u32, &[u8]) {
        let n = self.pos as usize;
        let filled = if self.wactive { n } else { 0 };
        self.active = false; self.wactive = false; self.pos = 0; self.limit = 0;
        (n as u32, &self.buf[..filled])
    }

    pub fn data_read(&mut self, n: u32) -> Option<u32> {
        if self.cmd.on != 0 { return self.m_data_read(n); }
        if !self.active || self.pos + n > self.limit { return None; }
        let p = self.pos as usize;
        let mut x = 0u32;
        for i in 0..n as usize { x |= (self.buf[p + i] as u32) << (8 * i); }
        self.pos += n; self.regs.served += 1;
        Some(x)
    }
    pub fn data_write(&mut self, n: u32, x: u32) -> bool {
        if self.cmd.on != 0 { return self.m_data_write(n, x); }
        if !self.wactive || self.pos + n > self.limit { return false; }
        let p = self.pos as usize;
        for i in 0..n as usize { self.buf[p + i] = (x >> (8 * i)) as u8; }
        self.pos += n; self.regs.wserved += 1;
        true
    }
    pub fn ctrl_read(&mut self, off: u32) -> Option<u32> {
        if self.cmd.on != 0 { return self.m_ctrl_read(off); }
        let r = &mut self.regs;
        if r.reg_on == 0 || off != r.off_ready { return None; }
        r.served += 1;
        if r.busy != 0 { r.busy -= 1; Some(0) } else { Some(2) }
    }
    pub fn ctrl_write(&mut self, off: u32, x: u32) -> bool {
        if self.cmd.on != 0 { return self.m_ctrl_write(off, x); }
        let r = &mut self.regs;
        if r.reg_on == 0 || (off != r.off_tim0 && off != r.off_tim1) { return false; }
        r.tim[(off == r.off_tim1) as usize] = x; r.wserved += 1;
        true
    }
    pub fn ale_write(&mut self, x: u32) -> bool {
        if self.cmd.on != 0 { return self.m_ale_write(x); }
        let r = &mut self.regs;
        if r.reg_on == 0 || r.ale_ok == 0 || r.npend >= 8 { return false; }
        r.pend[r.npend as usize] = x as u8; r.npend += 1; r.wserved += 1;
        true
    }
    /// A read of the command-latch or address-latch window: zero, while the machine is on.
    pub fn latch_read(&mut self) -> Option<u32> {
        if self.cmd.on == 0 { return None; }
        self.regs.served += 1;
        Some(0)
    }

    // ---- the command machine (cmd.on != 0) ----------------------------------------------------------------------------

    fn m_data_read(&mut self, n: u32) -> Option<u32> {
        let k = &mut self.cmd;
        if k.pos >= POS_MAX { return None; }
        let ecc = k.ctrl_val & 0x40 != 0;
        let mut x = 0u32;
        if k.mode == M_READ && k.pos as usize + n as usize <= RAW {          // streaming a page
            let p = k.pos as usize;
            for i in 0..n as usize { let b = k.buf[p + i]; if ecc { k.ecc_feed(b); } x |= (b as u32) << (8 * i); }
            k.pos += n;
        } else {
            // 00h with no address cycle after it goes back to the page that was read
            if k.mode == M_ADDR && k.cmd == 0 && k.naddr == 0 && k.buf_valid != 0 { k.mode = M_READ; }
            for i in 0..n as usize {
                let b = match k.mode {
                    M_READ => { let b = if (k.pos as usize) < RAW { k.buf[k.pos as usize] } else { 0xFF }; k.pos += 1; b }
                    M_STATUS => k.status as u8,
                    M_ID => { let b = if k.pos < k.nids { k.ids[k.pos as usize] } else { 0 }; k.pos += 1; b }
                    _ => 0xFF,
                };
                if ecc { k.ecc_feed(b); }
                x |= (b as u32) << (8 * i);
            }
        }
        self.regs.served += 1;
        Some(x)
    }
    fn m_data_write(&mut self, n: u32, x: u32) -> bool {
        let k = &mut self.cmd;
        if k.pos >= POS_MAX { return false; }
        if k.mode == M_ADDR && k.two() {
            if k.prog_begin_bad() { return false; }
            k.prog_begin();
        }
        let ecc = k.ctrl_val & 0x40 != 0;
        for i in 0..n as usize {
            let b = (x >> (8 * i)) as u8;
            if k.mode == M_PROG {
                if (k.pos as usize) < RAW { k.buf[k.pos as usize] = b; }
                k.pos += 1;
            }
            if ecc { k.ecc_feed(b); }
        }
        self.regs.wserved += 1;
        true
    }
    fn m_ale_write(&mut self, x: u32) -> bool {
        let k = &mut self.cmd;
        if k.naddr >= 8 { return false; }
        k.addr[k.naddr as usize] = x as u8; k.naddr += 1;
        if k.two() { k.mode = M_ADDR; }
        self.regs.wserved += 1;
        true
    }
    fn m_ctrl_read(&mut self, off: u32) -> Option<u32> {
        let (r, k) = (&mut self.regs, &mut self.cmd);
        let x = if off == r.off_ready { if r.busy != 0 { r.busy -= 1; 0 } else { 2 } }
            else if off == k.off_status { 0x40 }
            else if off == k.off_ecc {
                if k.log_full() { return None; }
                let x = k.ecc_reg();
                k.log(L_ECC, x, k.last_row, k.ecc_idx);
                x
            }
            else if off == k.off_ctrl { k.ctrl_val }
            else if off == r.off_tim0 { r.tim[0] }
            else if off == r.off_tim1 { r.tim[1] }
            else { return None };
        r.served += 1;
        Some(x)
    }
    fn m_ctrl_write(&mut self, off: u32, x: u32) -> bool {
        let (r, k) = (&mut self.regs, &mut self.cmd);
        if off == k.off_ctrl {
            let old = k.ctrl_val;
            k.ctrl_val = x;
            // the driver clears bits 7:6 and then sets bit 6 to restart the accumulator
            if x & 0x40 != 0 && old & 0x40 == 0 { k.ecc_idx = 0; k.ecc_odd = 0; k.ecc_even = 0; k.ecc_col = 0; }
        } else if off == r.off_tim0 { r.tim[0] = x; }
        else if off == r.off_tim1 { r.tim[1] = x; }
        else { return false; }
        r.wserved += 1;
        true
    }

    /// First half of a command byte: decline (None, nothing changed), or do what comes before the store call and say which
    /// call the command needs. `host`: there is a store to call.
    pub fn cle_pre(&mut self, c: u8, host: bool) -> Option<Need> {
        let k = &mut self.cmd;
        if k.on == 0 || k.log_full() { return None; }
        let pages = k.pages as u64;
        match c {
            0x30 if k.cmd == 0 => { let row = k.row(2); if row >= pages || !host { return None; } Some(Need::Read(row as u32)) }
            0x35 => { let row = k.row(2); if row >= pages || !host { return None; } Some(Need::Read(row as u32)) }
            0x85 => {
                // a destination row with no data after it, then 85h again: the row is kept
                if k.mode == M_ADDR && k.two() && k.naddr > 2 {
                    if k.prog_begin_bad() { return None; }
                    k.prog_begin();
                }
                Some(Need::Nothing)
            }
            0x10 | 0x15 => {
                let begin = k.mode == M_ADDR && k.two();
                if begin && k.prog_begin_bad() { return None; }
                let page = k.two() && (k.prog_page != NONE || (begin && (k.cmd == 0x80 || k.naddr > 2)));
                if page && !host { return None; }
                if begin { k.prog_begin(); }
                Some(if page { Need::Program(k.prog_page) } else { Need::Nothing })
            }
            0xD0 if k.cmd == 0x60 => { let row = k.row(0); if row >= pages || !host { return None; } Some(Need::Erase(row as u32)) }
            _ => Some(Need::Nothing),
        }
    }
    /// Second half: `r` is what the store call returned.
    pub fn cle_post(&mut self, c: u8, need: Need, r: u32) {
        let (regs, k) = (&mut self.regs, &mut self.cmd);
        match c {
            0xFF => { k.mode = M_STATUS; k.cmd = 0xFF; k.naddr = 0; regs.busy = 3; k.log(L_RESET, 0, 0, 0); }
            0x90 => { k.mode = M_ID; k.cmd = 0x90; k.naddr = 0; k.pos = 0; }
            0x00 | 0x05 | 0x60 => { k.cmd = c as u32; k.naddr = 0; k.mode = M_ADDR; }
            0x30 => {
                if let Need::Read(row) = need {
                    let col = k.col();
                    k.pos = col; k.mode = M_READ; k.buf_valid = 1; k.cb_page = NONE; regs.busy = 3; k.last_row = row;
                    k.log(L_READ, 0, row, col as u64);
                }
                k.cmd = 0x30;
            }
            0x35 => {                               // copy-back read: the page register is loaded, no data comes out
                if let Need::Read(row) = need { k.cb_page = row; k.log(L_CBREAD, 0, row, 0); }
                k.mode = M_IDLE; k.cmd = 0x35; regs.busy = 3;
            }
            0xE0 => { if k.cmd == 0x05 { k.pos = k.col(); k.mode = M_READ; } k.cmd = 0xE0; }
            0x70 => { k.mode = M_STATUS; k.cmd = 0x70; }
            0x80 => { k.cmd = 0x80; k.naddr = 0; k.mode = M_ADDR; k.buf = [0xFF; RAW]; k.cb_page = NONE; }
            0x85 => { k.cmd = 0x85; k.naddr = 0; k.mode = M_ADDR; }
            0x10 | 0x15 => {
                if let Need::Program(row) = need { k.status = k.status & !1 | r & 1; k.log(L_PROGRAM, 0, row, 0); }
                k.mode = M_STATUS; k.cmd = c as u32; regs.busy = 3; k.prog_page = NONE;
            }
            0xD0 => {
                if let Need::Erase(row) = need { k.status = k.status & !1 | r & 1; k.log(L_ERASE, 0, row / BLOCK_PAGES * BLOCK_PAGES, 0); }
                k.mode = M_STATUS; k.cmd = 0xD0; regs.busy = 3;
            }
            _ => { k.cmd = c as u32; k.log(L_UNKNOWN, c as u32, 0, 0); }
        }
        regs.wserved += 1;
    }

    pub const VERSION: u32 = 2;
    pub fn save(&self, w: &mut Wr) {
        let r = &self.regs;
        w.words(&[r.reg_on, r.busy, r.tim[0], r.tim[1], r.ale_ok, r.npend]); w.bytes(&r.pend);
        w.words(&[r.off_ready, r.off_tim0, r.off_tim1]); w.u64(r.served); w.u64(r.wserved);
        w.words(&[self.pos, self.limit, self.active as u32, self.wactive as u32]);
        w.u32(self.buf.len() as u32); w.bytes(&self.buf);
        let k = &self.cmd;
        w.words(&[k.on, k.mode, k.cmd, k.naddr]); w.bytes(&k.addr);
        w.words(&[k.pos, k.status, k.buf_valid, k.ctrl_val, k.prog_page, k.cb_page, k.last_row, k.pages]);
        w.u64(k.ecc_idx); w.words(&[k.ecc_odd, k.ecc_even, k.ecc_col, k.nids]); w.bytes(&k.ids);
        w.words(&[k.off_ctrl, k.off_status, k.off_ecc, k.log_on, k.nlog]);
        for x in &k.count { w.u64(*x); }
        w.bytes(&k.buf);
        for e in &k.log[..(k.nlog as usize).min(LOG_CAP)] { w.u64(e[0]); w.u64(e[1]); }
    }
    pub fn load(&mut self, rd: &mut Rd) -> Option<()> {
        let mut f = [0u32; 6]; rd.words(&mut f)?;
        let pend = rd.bytes(8)?;
        let mut g = [0u32; 3]; rd.words(&mut g)?;
        let (served, wserved) = (rd.u64()?, rd.u64()?);
        let mut h = [0u32; 4]; rd.words(&mut h)?;
        let n = rd.u32()? as usize;
        if n > LEASE_MAX || h[1] as usize > n || h[0] > h[1] || f[5] > 8 { return None; }
        let buf = rd.bytes(n)?;
        let mut a = [0u32; 4]; rd.words(&mut a)?;
        let addr = rd.bytes(8)?;
        let mut b = [0u32; 8]; rd.words(&mut b)?;
        let ecc_idx = rd.u64()?;
        let mut e = [0u32; 4]; rd.words(&mut e)?;
        let ids = rd.bytes(8)?;
        let mut o = [0u32; 5]; rd.words(&mut o)?;
        let mut count = [0u64; 8];
        for x in count.iter_mut() { *x = rd.u64()?; }
        let page = rd.bytes(RAW)?;
        if a[3] > 8 || e[3] > 8 || o[4] as usize > LOG_CAP { return None; }
        let r = &mut self.regs;
        r.reg_on = f[0]; r.busy = f[1]; r.tim = [f[2], f[3]]; r.ale_ok = f[4]; r.npend = f[5]; r.pend.copy_from_slice(pend);
        r.off_ready = g[0]; r.off_tim0 = g[1]; r.off_tim1 = g[2]; r.served = served; r.wserved = wserved;
        self.pos = h[0]; self.limit = h[1]; self.active = h[2] != 0; self.wactive = h[3] != 0;
        self.buf.clear(); self.buf.extend_from_slice(buf);
        let k = &mut self.cmd;
        k.on = a[0]; k.mode = a[1]; k.cmd = a[2]; k.naddr = a[3]; k.addr.copy_from_slice(addr);
        k.pos = b[0]; k.status = b[1]; k.buf_valid = b[2]; k.ctrl_val = b[3]; k.prog_page = b[4]; k.cb_page = b[5]; k.last_row = b[6]; k.pages = b[7];
        k.ecc_idx = ecc_idx; k.ecc_odd = e[0]; k.ecc_even = e[1]; k.ecc_col = e[2]; k.nids = e[3]; k.ids.copy_from_slice(ids);
        k.off_ctrl = o[0]; k.off_status = o[1]; k.off_ecc = o[2]; k.log_on = o[3]; k.nlog = o[4];
        k.count = count; k.buf.copy_from_slice(page);
        for i in 0..k.nlog as usize { k.log[i] = [rd.u64()?, rd.u64()?]; }
        Some(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The 24 parities of the model's definition, bit by bit.
    fn slow(data: &[u8]) -> u32 {
        let mut f = [0u32; 24];
        for (i, &b) in data.iter().enumerate() {
            let p = b.count_ones() & 1;
            for k in 0..9 { f[2 * k + (i >> k & 1)] ^= p; }
            for j in 0..8 { if b >> j & 1 != 0 { for k in 0..3 { f[18 + 2 * k + (j >> k & 1)] ^= 1; } } }
        }
        (0..24).fold(0, |v, i| v | f[i] << i)
    }

    #[test]
    fn the_ecc_of_a_sector_is_the_hamming_code_of_the_definition() {
        let mut seed = 0x1234_5678u32;
        let mut next = || { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; seed };
        for round in 0..40 {
            let data: Vec<u8> = (0..512).map(|_| next() as u8).collect();
            let mut k = NandCmd::new();
            for &b in &data { k.ecc_feed(b); }
            assert_eq!(k.ecc_fn(), slow(&data), "round {}", round);
            assert_eq!(k.ecc_idx, 512);
        }
        let mut k = NandCmd::new();
        k.ecc_feed(0x01);
        assert_eq!(k.ecc_fn(), 0x55_5555, "one bit at byte 0, bit 0: every even-side parity");
        assert_eq!(k.ecc_reg(), 0xAA_AAAA);
    }

    const WIN: u32 = 0x1000_0000;
    struct Host { c: *mut crate::ffi::Core, calls: Vec<(u32, u32, u32)>, page: Vec<u8>, programmed: Vec<u8>, fail: u32 }
    unsafe extern "C" fn rd(user: *mut core::ffi::c_void, dev: u32, off: u32, size: u32) -> u32 {
        let h = &mut *(user as *mut Host);
        h.calls.push((dev, off, size));
        let k = &mut *(crate::ffi::dbc_dev_regs(h.c, crate::dev::K_NAND_CLE) as *mut NandCmd);
        match dev {
            STORE_READ => { k.buf.copy_from_slice(&h.page); 0 }
            STORE_PROGRAM => { h.programmed = k.buf.to_vec(); h.fail }
            STORE_ERASE => h.fail,
            _ => 0x5a,
        }
    }
    unsafe extern "C" fn wr(user: *mut core::ffi::c_void, dev: u32, off: u32, size: u32, value: u32) {
        (*(user as *mut Host)).calls.push((dev, off, size | value << 8));
    }
    /// `mov r2,#b ; strb r2,[rn]` for every (rn, b).
    fn bytes_to(code: &mut Vec<u32>, seq: &[(u32, u32)]) { for &(rn, b) in seq { code.push(0xe3a0_2000 | b); code.push(0xe5c0_2000 | rn << 16); } }

    #[test]
    fn guest_code_reads_programs_and_erases_through_the_store() { unsafe {
        use crate::dev::*;
        use crate::ffi::*;
        let (cle, ale) = (5, 6);                                    // r5, r6: the latch windows; r0 data, r7 controller
        let mut code = Vec::new();
        // read page 0x012345 from column 4: 00h, five address cycles, 30h, four ready polls, two words and a byte of data
        bytes_to(&mut code, &[(cle, 0x00), (ale, 4), (ale, 0), (ale, 0x45), (ale, 0x23), (ale, 0x01), (cle, 0x30)]);
        for r in [8, 8, 8, 9] { code.push(0xe597_00c8 | r << 12); }  // ldr r8 / r9,[r7,#0xc8]
        code.extend([0xe590_a000, 0xe590_b000, 0xe5d0_c000]);       // ldr r10,[r0] ; ldr r11,[r0] ; ldrb ip,[r0]
        let n_read = code.len() as u64;
        // program page 0x000102: 80h, addresses, one word of data, 10h; then 70h and the status byte
        bytes_to(&mut code, &[(cle, 0x80), (ale, 0), (ale, 0), (ale, 2), (ale, 1), (ale, 0), (cle, 0x80 | 0), (ale, 0), (ale, 0), (ale, 2), (ale, 1), (ale, 0)]);
        code.push(0xe580_3000);                                     // str r3,[r0]
        bytes_to(&mut code, &[(cle, 0x10), (cle, 0x70)]);
        code.push(0xe5d0_4000);                                     // ldrb r4,[r0]
        let n_prog = code.len() as u64;
        // erase the block of page 0x000145, then a read of a row outside the chip, which the machine declines
        bytes_to(&mut code, &[(cle, 0x60), (ale, 0x45), (ale, 1), (ale, 0), (cle, 0xd0), (cle, 0x00), (ale, 0), (ale, 0), (ale, 0), (ale, 0), (ale, 0x7f), (cle, 0x30)]);
        let n_all = code.len() as u64;

        let c = dbc_new();
        assert_eq!(dbc_map_ram(c, 0, 0x10_0000), 0);
        for (i, w) in code.iter().enumerate() { dbc_mem_write(c, 0x8000 + 4 * i as u32, w.to_le_bytes().as_ptr(), 4); }
        assert_eq!(dbc_map_ext(c, WIN, 0x40000, 9), 0);
        for (i, kind) in [K_NAND_DATA, K_NAND_CLE, K_NAND_ALE].into_iter().enumerate() { assert_eq!(dbc_map_dev(c, WIN + 0x10000 * i as u32, 0x10000, kind), 0); }
        assert_eq!(dbc_map_dev(c, WIN + 0x30000, 0x1000, K_NAND_CTRL), 0);
        let mut h = Host { c, calls: Vec::new(), page: (0..RAW).map(|i| (i * 7 + 1) as u8).collect(), programmed: Vec::new(), fail: 1 };
        dbc_set_ext(c, Some(rd), Some(wr), &mut h as *mut Host as *mut core::ffi::c_void);
        dbc_set_reg(c, 16, 0xd3); dbc_set_reg(c, 15, 0x8000);
        for (r, v) in [(0, WIN), (5, WIN + 0x10000), (6, WIN + 0x20000), (7, WIN + 0x30000), (3, 0x1122_3344)] { dbc_set_reg(c, r, v); }
        (*(dbc_dev_regs(c, K_NAND_DATA) as *mut NandRegs)).off_ready = 0xc8;

        assert_eq!(dbc_run(c, 2), 2);
        assert_eq!(h.calls, vec![(9, 0x10000, 1 | 0 << 8)], "the machine is off: the command reaches the host as a window write");
        h.calls.clear(); dbc_set_reg(c, 15, 0x8000);
        let k = dbc_dev_regs(c, K_NAND_CLE) as *mut NandCmd;
        assert_eq!((*k).size as usize, core::mem::size_of::<NandCmd>());
        (*k).pages = 0x20000; (*k).on = 1;

        assert_eq!(dbc_run(c, n_read), n_read);
        assert_eq!(h.calls, vec![(STORE_READ, 0x012345, 4)], "one call for the page, nothing else reaches the host");
        assert_eq!((dbc_reg(c, 8), dbc_reg(c, 9)), (0, 2), "busy for three polls");
        let b = |i: usize| h.page[i] as u32;
        assert_eq!(dbc_reg(c, 10), b(4) | b(5) << 8 | b(6) << 16 | b(7) << 24);
        assert_eq!((dbc_reg(c, 11) & 0xff, dbc_reg(c, 12)), (b(8), b(12)));
        assert_eq!(((*k).mode, (*k).pos, (*k).last_row, (*k).cmd), (M_READ, 13, 0x012345, 0x30));
        assert_eq!(dbc_dev_get(c, K_NAND_CLE, 0x10 + L_READ as u32), 1);

        h.calls.clear();
        assert_eq!(dbc_run(c, n_prog - n_read), n_prog - n_read);
        assert_eq!(h.calls, vec![(STORE_PROGRAM, 0x000102, 4)]);
        assert_eq!(&h.programmed[..6], &[0x44, 0x33, 0x22, 0x11, 0xff, 0xff], "the page register: erased, then the data");
        assert_eq!(dbc_reg(c, 4), 0xc1, "the store said the program failed");

        h.calls.clear(); h.fail = 0;
        assert_eq!(dbc_run(c, n_all - n_prog), n_all - n_prog);
        assert_eq!(h.calls, vec![(STORE_ERASE, 0x000145, 4), (9, 0x10000, 1 | 0x30 << 8)], "the erase; then a row outside the chip: declined, to the host");
        assert_eq!(((*k).status, (*k).cmd, (*k).naddr), (0xc0, 0x00, 5), "a declined command changes nothing");

        let n = dbc_state_size(c);
        let mut blob = vec![0u8; n as usize];
        assert_eq!(dbc_state_save(c, blob.as_mut_ptr(), n), n);
        let d = dbc_new();
        assert_eq!(dbc_state_load(d, blob.as_ptr(), n), 0);
        let k2 = dbc_dev_regs(d, K_NAND_CLE) as *mut NandCmd;
        let (ka, kb) = (&*k, &*k2);
        assert_eq!((kb.on, kb.naddr, kb.addr, kb.count), (1, 5, ka.addr, ka.count));
        assert!(kb.buf[..] == ka.buf[..]);
        dbc_free(c); dbc_free(d);
    } }

    #[test]
    fn the_shared_structures_keep_their_layout() {
        assert_eq!(core::mem::size_of::<NandRegs>(), 64);
        let k = NandCmd::new();
        let base = &k as *const NandCmd as usize;
        assert_eq!(&k.ecc_idx as *const u64 as usize - base, 56);
        assert_eq!(&k.count as *const [u64; 8] as usize - base, 112);
        assert_eq!(&k.buf as *const [u8; RAW] as usize - base, 176);
        assert_eq!(&k.log as *const [[u64; 2]; LOG_CAP] as usize - base, 2288);
        assert_eq!(core::mem::size_of::<NandCmd>(), 18672);
    }
}

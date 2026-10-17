// The compiled devices and what they share: the clock, the interrupt lines and the timed events.
//
// A window of the bus can belong to a compiled device (Mem::map_dev). Its accesses are dispatched here from the same slow
// path that calls the host for an external window; a device may decline an access, which then goes to the host.
//
// Time: one clock (clock.rs). The scheduler sets it between slices, so a device reads the time of the slice start.
// Timed events: a device with an event gives its time (next_event) and fires what is due when it is advanced (advance);
// the scheduler advances the devices between slices, never inside one.
// Interrupt lines: 64 level inputs. With the compiled interrupt controllers in use they take the lines and drive the IRQ
// input of the CPU at once (the FIQ output is computed and not connected, as in the machine this was moved from).
// Otherwise the controller is outside: a line that a compiled device changes is reported to the host through the write
// callback with device number LINES_DEV (offset = line, size 4, value = level).
// SPDX-License-Identifier: MIT

pub mod clock;
pub mod nand;
pub mod sysctl;
pub mod timer;
pub mod vic;

use crate::cpu::Cpu;

// Window kinds (Mem::map_dev) and device numbers of the interface.
pub const K_NAND_DATA: u32 = 1;
pub const K_NAND_CTRL: u32 = 2;
pub const K_NAND_ALE: u32 = 3;
pub const K_TIMER: u32 = 4;
pub const K_VIC0: u32 = 5;
pub const K_VIC1: u32 = 6;
pub const K_NAND_CLE: u32 = 7;
pub const K_SYSCTL: u32 = 8;
pub const K_CLKPROF: u32 = 9;
pub const KINDS: usize = 10;
/// Device number of the line reports to the host.
pub const LINES_DEV: u32 = 0xFFFF_FFFF;

// Fields of dev_get / dev_set that every kind has.
pub const F_ON: u32 = 0xFE;
pub const F_READS: u32 = 0xF0;
pub const F_WRITES: u32 = 0xF1;

pub struct Devs {
    pub clock: clock::Clock,
    pub nand: nand::Nand,
    pub sysctl: sysctl::SysCtl,
    pub clkprof: sysctl::ClkProf,
    pub timer: timer::Timer,
    pub vic: vic::VicPair,
    /// The compiled interrupt controllers are in use.
    pub vic_on: bool,
    /// Levels last reported to a controller outside.
    pub ext_lines: u64,
    /// Accesses served per kind: reads, writes.
    pub served: [[u64; 2]; KINDS],
}

impl Devs {
    pub fn new() -> Devs {
        Devs { clock: clock::Clock::new(), nand: nand::Nand::new(), sysctl: sysctl::SysCtl::new(), clkprof: sysctl::ClkProf::new(), timer: timer::Timer::new(), vic: vic::VicPair::new(), vic_on: false, ext_lines: 0, served: [[0; 2]; KINDS] }
    }
}

impl Cpu {
    /// A read of a window of compiled device `kind`. None: declined, the host is to be asked.
    pub(crate) fn dev_read(&mut self, kind: u32, off: u32, n: u32) -> Option<u32> {
        let d = &mut *self.dev;
        let x = match kind {
            K_NAND_DATA => d.nand.data_read(n)?,
            K_NAND_CTRL => d.nand.ctrl_read(off)?,
            K_NAND_ALE | K_NAND_CLE => d.nand.latch_read()?,
            K_TIMER => d.timer.read(&d.clock, off),
            K_VIC0 | K_VIC1 => {
                let (x, changed) = d.vic.read((kind - K_VIC0) as usize, off);
                if changed { self.vic_update(); }
                x
            }
            K_SYSCTL => d.sysctl.read(off),
            K_CLKPROF => d.clkprof.read(off),
            _ => return None,
        };
        self.dev.served[kind as usize][0] += 1;
        Some(x)
    }
    /// A write to a window of compiled device `kind`. False: declined.
    pub(crate) fn dev_write(&mut self, kind: u32, off: u32, n: u32, x: u32) -> bool {
        let d = &mut *self.dev;
        match kind {
            K_NAND_DATA => if !d.nand.data_write(n, x) { return false; },
            K_NAND_CTRL => if !d.nand.ctrl_write(off, x) { return false; },
            K_NAND_ALE => if !d.nand.ale_write(x) { return false; },
            K_NAND_CLE => if !self.nand_command(x as u8) { return false; },
            K_TIMER => if d.timer.write(&d.clock, off, x) { self.timer_lines(); },
            K_VIC0 | K_VIC1 => { d.vic.write((kind - K_VIC0) as usize, off, x); self.vic_update(); }
            K_SYSCTL => if !d.sysctl.write(off, x) { return false; },
            K_CLKPROF => d.clkprof.write(off, x),
            _ => return false,
        }
        self.dev.served[kind as usize][1] += 1;
        true
    }

    /// A command byte to the NAND chip, with the call to the store that the command needs. False: declined.
    fn nand_command(&mut self, c: u8) -> bool {
        let host = self.has_host(false);
        let need = match self.dev.nand.cle_pre(c, host) { Some(n) => n, None => return false };
        let r = match need {
            nand::Need::Nothing => 0,
            nand::Need::Read(page) => self.host_read(nand::STORE_READ, page, 4).unwrap_or(0),
            nand::Need::Program(page) => self.host_read(nand::STORE_PROGRAM, page, 4).unwrap_or(0),
            nand::Need::Erase(page) => self.host_read(nand::STORE_ERASE, page, 4).unwrap_or(0),
        };
        self.dev.nand.cle_post(c, need, r);
        true
    }

    fn vic_update(&mut self) {
        if let Some(level) = self.dev.vic.update() { self.set_irq(level); }
    }
    fn timer_lines(&mut self) {
        let (s, l0, l1) = (self.dev.timer.status, self.dev.timer.line0, self.dev.timer.line1);
        self.set_line(l0, s & 1 != 0); self.set_line(l1, s & 2 != 0);
    }
    /// Level of interrupt line `n` (0-63), from a compiled device or from the host.
    pub fn set_line(&mut self, n: u32, level: bool) {
        let n = n & 63;
        if self.dev.vic_on {
            self.dev.vic.set_line(n, level); self.vic_update();
        } else if (self.dev.ext_lines >> n & 1 != 0) != level {
            self.dev.ext_lines ^= 1 << n;
            self.host_write(LINES_DEV, n, 4, level as u32);
        }
    }
    pub fn line(&self, n: u32) -> bool {
        let n = n & 63;
        if self.dev.vic_on { self.dev.vic.line(n) } else { self.dev.ext_lines >> n & 1 != 0 }
    }
    /// Bit 0: interrupt output of the compiled controllers, bit 1: their FIQ output.
    pub fn irq_out(&self) -> u32 { self.dev.vic.irq_out as u32 | (self.dev.vic.fiq_out as u32) << 1 }

    /// Fire the events of compiled device `kind` that are due at the clock's time (0: of every device).
    pub fn dev_advance(&mut self, kind: u32) {
        if kind == 0 || kind == K_TIMER {
            let d = &mut *self.dev;
            d.timer.advance(&d.clock);
            self.timer_lines();
        }
    }
    /// Time of the next event of device `kind` (0: the earliest of all), ns; u64::MAX when there is none.
    pub fn dev_next_event(&self, kind: u32) -> u64 {
        if kind == 0 || kind == K_TIMER { self.dev.timer.next_event_ns(&self.dev.clock) } else { u64::MAX }
    }
    /// A span of an external window becomes a window of compiled device `kind` (0: of the host alone again).
    pub fn map_dev(&mut self, addr: u32, size: u32, kind: u32) -> i32 {
        if kind as usize >= KINDS { return -1; }
        let r = self.mem.map_dev(addr, size, kind);
        if r == 0 && (kind == K_VIC0 || kind == K_VIC1) { self.dev.vic_on = true; }
        self.flush();
        r
    }

    /// One word of a device's state (the fields are listed in the README). Unknown fields read as zero.
    pub fn dev_get(&self, kind: u32, field: u32) -> u64 {
        let d = &*self.dev;
        if kind as usize >= KINDS { return 0; }
        match field { F_READS => return d.served[kind as usize][0], F_WRITES => return d.served[kind as usize][1], _ => {} }
        match kind {
            K_NAND_DATA | K_NAND_CTRL | K_NAND_ALE | K_NAND_CLE => match field {
                0 => d.nand.pos as u64, 1 => d.nand.limit as u64, 2 => d.nand.active as u64, 3 => d.nand.wactive as u64,
                0x10..=0x17 => d.nand.cmd.count[(field - 0x10) as usize], 0x20 => d.nand.cmd.on as u64, 0x21 => d.nand.cmd.size as u64, _ => 0 },
            K_TIMER => { let t = &d.timer; match field {
                0 => t.status as u64, 1 => t.deadline0, 2 => t.fired, 3 => t.extra, 4 => t.written as u64, 5 => t.held_reads, 6 => t.arms,
                7 => t.line0 as u64, 8 => t.line1 as u64, 9 => t.read_step as u64,
                0x1000..=0x1FFF => t.regs[(field - 0x1000) as usize] as u64, _ => 0 } }
            K_VIC0 | K_VIC1 => { let v = &d.vic.v[(kind - K_VIC0) as usize]; match field {
                0 => v.lines as u64, 1 => v.soft as u64, 2 => v.enable as u64, 3 => v.select as u64, 4 => v.protection as u64, 5 => v.defvect as u64,
                6 => v.reads_vect, 7 => v.writes_vect, 8 => v.nprio as u64, 9 => d.vic.irq_edges,
                0x10..=0x1F => v.vectaddr[(field - 0x10) as usize] as u64, 0x20..=0x2F => v.vectcntl[(field - 0x20) as usize] as u64,
                0x30..=0x3F => v.prio[(field - 0x30) as usize] as u64, F_ON => d.vic_on as u64, _ => 0 } }
            K_SYSCTL => match field { 0 => d.sysctl.wr_out as u64, 0x1000..=0x1FFF => d.sysctl.regs[(field - 0x1000) as usize] as u64, _ => 0 },
            K_CLKPROF => match field { 0x1000..=0x1FFF => d.clkprof.regs[(field - 0x1000) as usize >> 2] as u64, _ => 0 },
            _ => 0,
        }
    }
    /// Set one word of a device's state (for the half of a model that stays outside, and for tests). The outputs of the
    /// interrupt controllers follow at once.
    pub fn dev_set(&mut self, kind: u32, field: u32, x: u64) {
        let d = &mut *self.dev;
        match kind {
            K_TIMER => { let t = &mut d.timer; match field {
                0 => t.status = x as u32 & 3, 1 => t.deadline0 = x, 2 => t.fired = x, 3 => t.extra = x, 4 => t.written = x != 0, 5 => t.held_reads = x, 6 => t.arms = x,
                7 => t.line0 = x as u32 & 63, 8 => t.line1 = x as u32 & 63, 9 => t.read_step = x as u32,
                0x1000..=0x1FFF => t.regs[(field - 0x1000) as usize] = x as u32, _ => {} } }
            K_VIC0 | K_VIC1 => {
                let v = &mut d.vic.v[(kind - K_VIC0) as usize];
                match field {
                    0 => v.lines = x as u32, 1 => v.soft = x as u32, 2 => v.enable = x as u32, 3 => v.select = x as u32, 4 => v.protection = x as u32, 5 => v.defvect = x as u32,
                    6 => v.reads_vect = x, 7 => v.writes_vect = x, 8 => v.nprio = (x as u32).min(16), 9 => d.vic.irq_edges = x,
                    0x10..=0x1F => v.vectaddr[(field - 0x10) as usize] = x as u32, 0x20..=0x2F => v.vectcntl[(field - 0x20) as usize] = x as u32,
                    0x30..=0x3F => v.prio[(field - 0x30) as usize] = x as u8, F_ON => d.vic_on = x != 0, _ => {} }
                if d.vic_on { self.vic_update(); }
            }
            K_SYSCTL => match field { 0 => d.sysctl.wr_out = x != 0, 0x1000..=0x1FFF => d.sysctl.regs[(field - 0x1000) as usize] = x as u32, _ => {} },
            K_CLKPROF => if let 0x1000..=0x1FFF = field { d.clkprof.regs[(field - 0x1000) as usize >> 2] = x as u32; },
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ffi::*;
    use core::ffi::c_void;

    const CODE: u32 = 0x8000;
    const WIN: u32 = 0x1000_0000;

    /// What the host saw: (device, offset, size, value; a read has value u32::MAX and is answered with 0x5a).
    unsafe extern "C" fn rd(user: *mut c_void, dev: u32, off: u32, size: u32) -> u32 { (*(user as *mut Vec<(u32, u32, u32, u32)>)).push((dev, off, size, u32::MAX)); 0x5a }
    unsafe extern "C" fn wr(user: *mut c_void, dev: u32, off: u32, size: u32, value: u32) { (*(user as *mut Vec<(u32, u32, u32, u32)>)).push((dev, off, size, value)); }

    /// 1 MB of RAM at 0, `b .` on the vectors, ARM code at CODE, an external window of 64K (device 9) at WIN - 0x2000.
    unsafe fn machine(code: &[u32], log: &mut Vec<(u32, u32, u32, u32)>) -> *mut Core {
        let c = dbc_new();
        assert_eq!(dbc_map_ram(c, 0, 0x10_0000), 0);
        for v in 0..8u32 { dbc_mem_write(c, 4 * v, 0xeaff_fffeu32.to_le_bytes().as_ptr(), 4); }
        for (i, w) in code.iter().enumerate() { dbc_mem_write(c, CODE + 4 * i as u32, w.to_le_bytes().as_ptr(), 4); }
        assert_eq!(dbc_map_ext(c, WIN - 0x2000, 0x10000, 9), 0);
        dbc_set_ext(c, Some(rd), Some(wr), log as *mut _ as *mut c_void);
        dbc_set_reg(c, 16, 0xd3); dbc_set_reg(c, 15, CODE);
        c
    }

    #[test]
    fn a_compiled_window_serves_and_passes_on_what_it_declines() { unsafe {
        let mut log = Vec::new();
        // ldr r0,[r1] ; ldr r2,[r1,#4] ; str r3,[r1,#8] ; ldr r4,[r1]
        let c = machine(&[0xe591_0000, 0xe591_2004, 0xe581_3008, 0xe591_4000], &mut log);
        assert_eq!(dbc_map_dev(c, WIN, 0x1000, K_NAND_DATA), 0);
        assert_eq!(dbc_map_dev(c, 0x2000, 0x1000, K_TIMER), -1, "memory is not an external window");
        assert_eq!(dbc_map_dev(c, WIN - 0x3000, 0x2000, K_TIMER), -1, "a span that leaves the external window");
        dbc_set_reg(c, 1, WIN); dbc_set_reg(c, 3, 0x1234_5678);
        let data = [1u8, 2, 3, 4, 5, 6, 7, 8];
        assert_eq!(dbc_port_grant(c, data.as_ptr(), 8, 0), 0);
        assert_eq!(dbc_run(c, 3), 3);
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 2)), (0x0403_0201, 0x0807_0605));
        assert_eq!(log, vec![(9, 0x2008, 4, 0x1234_5678)], "the write has no lease: to the host, with the numbers of its window");
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(dbc_reg(c, 4), 0x5a, "lease used up: the host answers");
        assert_eq!(log[1], (9, 0x2000, 4, u32::MAX));
        assert_eq!(dbc_port_take(c, core::ptr::null_mut(), 0), 8);
        let mut b = [0u8; 4]; dbc_mem_read(c, WIN + 4, b.as_mut_ptr(), 4);
        assert_eq!(b, [5, 6, 7, 8], "shadow of a compiled window");
        assert_eq!((dbc_dev_get(c, K_NAND_DATA, F_READS), dbc_dev_get(c, K_NAND_DATA, F_WRITES)), (2, 0));
        assert_eq!(dbc_map_dev(c, WIN, 0x1000, 0), 0);
        dbc_set_reg(c, 15, CODE); assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(log[2], (9, 0x2000, 4, u32::MAX), "kind 0: the host alone again");
        dbc_free(c);
    } }

    #[test]
    fn a_write_lease_fills_the_buffer() { unsafe {
        let mut log = Vec::new();
        // str r3,[r1] ; strb r3,[r1] ; strh r3,[r1] ; str r3,[r1]
        let c = machine(&[0xe581_3000, 0xe5c1_3000, 0xe1c1_30b0, 0xe581_3000], &mut log);
        assert_eq!(dbc_map_dev(c, WIN, 0x1000, K_NAND_DATA), 0);
        dbc_set_reg(c, 1, WIN); dbc_set_reg(c, 3, 0xa1b2_c3d4);
        assert_eq!(dbc_port_grant(c, core::ptr::null(), 8, 1), 0);
        assert_eq!(dbc_run(c, 4), 4);
        assert_eq!(log, vec![(9, 0x2000, 4, 0xa1b2_c3d4)], "the fourth store does not fit: to the host");
        let mut out = [0u8; 8];
        assert_eq!(dbc_port_take(c, out.as_mut_ptr(), 8), 7);
        assert_eq!(out, [0xd4, 0xc3, 0xb2, 0xa1, 0xd4, 0xd4, 0xc3, 0]);
        dbc_free(c);
    } }

    #[test]
    fn the_timer_fires_between_slices_and_reports_its_line() { unsafe {
        let mut log = Vec::new();
        let c = machine(&[0xe1a0_0000; 4], &mut log);
        assert_eq!(dbc_map_dev(c, WIN, 0x1000, K_TIMER), 0);
        assert_eq!(dbc_dev_write(c, K_TIMER, 0x2C, 4, 1), 1);
        assert_eq!(dbc_dev_next_event(c, K_TIMER), 4_000_000, "periodic: the next coarse step, 4 ms");
        dbc_clock_set(c, 399_999, 0); dbc_dev_advance(c, 0);
        assert!(log.is_empty() && dbc_dev_get(c, K_TIMER, 0) == 0, "3.99999 ms: not yet");
        dbc_clock_set(c, 400_000, 0);
        assert_eq!(dbc_dev_get(c, K_TIMER, 0), 0, "the event waits for advance()");
        dbc_dev_advance(c, 0);
        assert_eq!(log, vec![(LINES_DEV, 28, 4, 1)]);
        assert_eq!(dbc_dev_next_event(c, K_TIMER), 8_000_000);
        assert_eq!(dbc_dev_write(c, K_TIMER, 0x28, 4, 1), 1);
        assert_eq!(log[1], (LINES_DEV, 28, 4, 0));
        assert_eq!(dbc_clock_get(c, 0), 4_000_000);
        dbc_clock_set(c, 400_000, 123); assert_eq!(dbc_clock_get(c, 0), 4_000_123);
        dbc_free(c);
    } }

    #[test]
    fn the_compiled_controllers_drive_the_interrupt_input() { unsafe {
        let mut log = Vec::new();
        // msr cpsr_c,#0x13 ; nop ; nop
        let c = machine(&[0xe321_f013, 0xe1a0_0000, 0xe1a0_0000], &mut log);
        assert_eq!(dbc_map_dev(c, WIN, 0x1000, K_VIC0), 0);
        assert_eq!(dbc_map_dev(c, WIN + 0x1000, 0x1000, K_VIC1), 0);
        assert_eq!(dbc_dev_write(c, K_VIC1, 0x10, 4, 1 << 3), 1);            // enable line 35
        dbc_set_line(c, 35, 1);
        assert_eq!((dbc_irq_out(c), dbc_line(c, 35), dbc_line(c, 3)), (1, 1, 0));
        assert!(log.is_empty(), "no report to the host with the controllers inside");
        assert_eq!(dbc_run(c, 2), 2);
        assert_eq!(dbc_reg(c, 15), 0x18, "taken after the unmasking instruction; the handler is a branch to itself");
        assert_eq!(dbc_reg(c, 16) & 0x1f, 0x12);
        dbc_set_line(c, 35, 0);
        assert_eq!(dbc_irq_out(c), 0);
        dbc_set_reg(c, 16, 0x13); dbc_set_reg(c, 15, CODE + 4);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(dbc_reg(c, 15), CODE + 8, "line low: the input is low again");
        dbc_free(c);
    } }

    #[test]
    fn the_state_goes_into_a_fresh_core() { unsafe {
        let mut log = Vec::new();
        let c = machine(&[0xe591_0000, 0xe591_2004], &mut log);
        assert_eq!(dbc_map_dev(c, WIN, 0x1000, K_NAND_DATA), 0);
        assert_eq!(dbc_map_dev(c, WIN + 0x1000, 0x1000, K_TIMER), 0);
        dbc_set_reg(c, 1, WIN);
        let data = [9u8, 8, 7, 6, 5, 4, 3, 2];
        dbc_port_grant(c, data.as_ptr(), 8, 0);
        dbc_dev_write(c, K_TIMER, 0x2C, 4, 1); dbc_clock_set(c, 1000, 77);
        assert_eq!(dbc_run(c, 1), 1);
        let n = dbc_state_size(c);
        let mut blob = vec![0u8; n as usize];
        assert_eq!(dbc_state_save(c, blob.as_mut_ptr(), n - 1), 0, "buffer too small");
        assert_eq!(dbc_state_save(c, blob.as_mut_ptr(), n), n);
        let d = dbc_new();
        assert_eq!(dbc_state_load(d, blob.as_ptr(), n), 0);
        let mut log2: Vec<(u32, u32, u32, u32)> = Vec::new();
        dbc_set_ext(d, Some(rd), Some(wr), &mut log2 as *mut _ as *mut c_void);
        for x in [c, d] { assert_eq!(dbc_run(x, 1), 1); }
        assert_eq!((dbc_reg(d, 0), dbc_reg(d, 2), dbc_icount(d)), (0x0607_0809, 0x0203_0405, 2));
        for i in 0..53 { assert_eq!(dbc_reg(c, i), dbc_reg(d, i), "register {}", i); }
        assert_eq!((dbc_clock_get(d, 0), dbc_dev_next_event(d, K_TIMER)), (10_077, 4_000_000));
        assert!(log.is_empty() && log2.is_empty());
        assert_eq!(dbc_state_load(d, blob.as_ptr(), n / 2), -1);
        dbc_free(c); dbc_free(d);
    } }

    unsafe fn state(c: *mut Core) -> Vec<u8> {
        let n = dbc_state_size(c); let mut b = vec![0u8; n as usize];
        assert_eq!(dbc_state_save(c, b.as_mut_ptr(), n), n);
        b
    }

    /// dbc_run_slices against a host that runs the slices one by one and does between them what the call does itself:
    /// the instructions charged to the clock, the timer advanced, and the same reasons to stop. Two cores, the same
    /// program (a counting loop that reads a register of the external window now and then and sleeps once), the same
    /// calls with changing limits: the results, the calls that reached the host and the whole state must be equal.
    #[test]
    fn slices_in_the_core_are_the_slices_a_host_runs_one_by_one() { unsafe {
        // loop: add r0,r0,#1 ; cmp r0,#700 ; bne loop ; ldr r2,[r1] ; add r3,r3,#1 ; cmp r3,#9 ; mcreq p15,0,r0,c7,c0,4 ; moveq r3,#0 ; mov r0,#0 ; b loop
        let code = [0xe280_0001, 0xe350_0fafu32, 0x1aff_fffc, 0xe591_2000, 0xe283_3001, 0xe353_0009, 0x0e07_0f90, 0x03a0_3000, 0xe3a0_0000, 0xeaff_fff5];
        let (mut la, mut lb) = (Vec::new(), Vec::new());
        let (a, b) = (machine(&code, &mut la), machine(&code, &mut lb));
        for c in [a, b] {
            dbc_set_reg(c, 1, WIN - 0x2000);
            assert_eq!(dbc_map_ext(c, 0x2000_0000, 0x1000, 3), 0);
            assert_eq!(dbc_map_dev(c, 0x2000_0000, 0x1000, K_TIMER), 0);
            dbc_dev_set(c, K_VIC0, 0xFE, 1);                       // the lines stay in the core
            dbc_clock_rate(c, 1000.0);                             // a coarse step of the timer (4 ms) every 4000 instructions
            assert_eq!(dbc_dev_write(c, K_TIMER, 0x2C, 4, 1), 1); assert_eq!(dbc_dev_write(c, K_TIMER, 0x10, 4, 0), 1);
        }
        const Q: u64 = 997;
        let (mut insns, mut last, mut whole, mut left, mut stops) = (0u64, 0xFFFF_FFFFu32, 0u64, 0u32, [0u32; 6]);
        for round in 0..400u64 {
            let max = 1 + (round % 7) as u32;
            let now = dbc_clock_get(a, 0);
            let due = if round % 5 == 3 { now + 2_500_000 } else { u64::MAX };
            let until = if round % 11 == 7 { now + 1_200_000 } else { u64::MAX };
            // the host's way, on core a
            let (mut k, mut same, mut done, mut l) = (0u64, false, 0u64, last);
            loop {
                let seen = la.len();
                done = dbc_run(a, Q);
                if dbc_stop_reason(a) != 0 || done != Q { break; }
                done = 0; k += 1; insns += Q;
                dbc_clock_set(a, insns, dbc_clock_get(a, 2)); dbc_dev_advance(a, K_TIMER);
                let pc = dbc_reg(a, 15); same = pc == l; l = pc;
                let t = dbc_clock_get(a, 0);
                let why = [same, la.len() != seen, t >= due, t > until, k >= max as u64];
                for (i, &w) in why.iter().enumerate() { stops[i] += w as u32; }
                if why.iter().any(|&w| w) { break; }
            }
            // the core's way, on core b
            let r = dbc_run_slices(b, Q, max, due, until, last);
            assert_eq!((r >> 33, r >> 32 & 1 != 0, r & 0xFFFF_FFFF), (k, same && k != 0, done), "round {}", round);
            assert_eq!(dbc_stop_reason(b), dbc_stop_reason(a), "round {}", round);
            if k != 0 { assert_eq!(dbc_slice_pc(b), l); last = l; }
            whole += k;
            if dbc_stop_reason(a) == 1 {                           // asleep: the slice is the host's; it wakes the CPU and goes on
                left += 1; stops[5] += 1;
                insns += done;
                for c in [a, b] { dbc_clock_set(c, insns, dbc_clock_get(c, 2) + 777); dbc_dev_advance(c, K_TIMER); dbc_set_reg(c, 15, dbc_reg(c, 15)); }
                last = dbc_reg(a, 15);
            }
            assert_eq!(la, lb, "round {}: the calls that reached the host", round);
            assert!(state(a) == state(b), "round {}: the state", round);
        }
        assert!(whole > 600 && left > 3, "{} whole slices, {} left to the host", whole, left);
        assert!(stops.iter().all(|&n| n > 0), "every reason to stop was met: {:?}", stops);
        assert!(dbc_dev_get(a, K_TIMER, 2) > 20, "the timer's event fired");
        assert_eq!(dbc_run_slices(b, 0, 4, u64::MAX, u64::MAX, 0), 0);            // no slice length: nothing runs
        assert_eq!(dbc_run_slices(b, 1 << 32, 4, u64::MAX, u64::MAX, 0), 0);
        dbc_free(a); dbc_free(b);
    } }
}

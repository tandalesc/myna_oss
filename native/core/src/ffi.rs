// The C interface (`dbc_*`). `Core*` is an opaque pointer from dbc_new. A null core is accepted everywhere and does nothing.
// The native library takes the callbacks of the external windows through dbc_set_ext; the WebAssembly module imports them
// as `dbc_ext_read` / `dbc_ext_write` from module `env` and exports dbc_alloc / dbc_dealloc for passing buffers in.
// SPDX-License-Identifier: MIT

use crate::cpu::Cpu;

pub type Core = Cpu;

#[inline(always)] unsafe fn core<'a>(c: *mut Core) -> Option<&'a mut Cpu> { c.as_mut() }

#[no_mangle] pub extern "C" fn dbc_new() -> *mut Core { Box::into_raw(Cpu::new()) }
#[no_mangle] pub unsafe extern "C" fn dbc_free(c: *mut Core) { if !c.is_null() { drop(Box::from_raw(c)); } }

/// Zeroed RAM; address and size multiples of 4K. 0 = ok, -1 = bad span. Pages already mapped keep their contents.
#[no_mangle] pub unsafe extern "C" fn dbc_map_ram(c: *mut Core, addr: u32, size: u32) -> i32 { match core(c) { Some(c) => c.map_ram(addr, size), None => -1 } }
/// External window; address and size multiples of 4K. Memory already there becomes the window's shadow; a page with none
/// gets its shadow at the first access, so mapping costs nothing.
#[no_mangle] pub unsafe extern "C" fn dbc_map_ext(c: *mut Core, addr: u32, size: u32, dev: u32) -> i32 { match core(c) { Some(c) => c.map_ext(addr, size, dev), None => -1 } }

#[cfg(not(target_arch = "wasm32"))]
#[no_mangle] pub unsafe extern "C" fn dbc_set_ext(c: *mut Core, rd: Option<crate::cpu::ExtRead>, wr: Option<crate::cpu::ExtWrite>, user: *mut core::ffi::c_void) {
    if let Some(c) = core(c) { c.ext = (rd, wr, user); }
}

/// 0 = ok, -1 = the span leaves the address space. Unmapped memory and window pages never accessed read as zeros.
#[no_mangle] pub unsafe extern "C" fn dbc_mem_read(c: *mut Core, addr: u32, buf: *mut u8, n: u32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    if n == 0 { return 0; }
    if buf.is_null() { return -1; }
    if c.mem().read(addr, core::slice::from_raw_parts_mut(buf, n as usize)) { 0 } else { -1 }
}
/// 0 = ok, -1 = the span leaves the address space. Unmapped pages become RAM; external pages take the bytes into their shadow.
#[no_mangle] pub unsafe extern "C" fn dbc_mem_write(c: *mut Core, addr: u32, buf: *const u8, n: u32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    if n == 0 { return 0; }
    if buf.is_null() { return -1; }
    if c.mem().write(addr, core::slice::from_raw_parts(buf, n as usize)) { 0 } else { -1 }
}
/// 0 = ok, -1 = not a snapshot.
#[no_mangle] pub unsafe extern "C" fn dbc_load_snapshot(c: *mut Core, data: *const u8, len: u32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    if data.is_null() { return -1; }
    if c.load(core::slice::from_raw_parts(data, len as usize)) { 0 } else { -1 }
}

#[no_mangle] pub unsafe extern "C" fn dbc_reg(c: *mut Core, id: u32) -> u32 { match core(c) { Some(c) => c.reg(id), None => 0 } }
#[no_mangle] pub unsafe extern "C" fn dbc_set_reg(c: *mut Core, id: u32, value: u32) { if let Some(c) = core(c) { c.set_reg(id, value); } }
#[no_mangle] pub unsafe extern "C" fn dbc_set_irq(c: *mut Core, level: i32) { if let Some(c) = core(c) { c.set_irq(level != 0); } }
#[no_mangle] pub unsafe extern "C" fn dbc_set_fiq(c: *mut Core, level: i32) { if let Some(c) = core(c) { c.set_fiq(level != 0); } }
#[no_mangle] pub unsafe extern "C" fn dbc_run(c: *mut Core, max_insns: u64) -> u64 { match core(c) { Some(c) => c.run(max_insns), None => 0 } }
/// Slices with the host's work between them done in the core while nothing needs the host: see Cpu::run_slices.
#[no_mangle] pub unsafe extern "C" fn dbc_run_slices(c: *mut Core, quantum: u64, max: u32, due_ns: u64, until_ns: u64, last_pc: u32) -> u64 {
    match core(c) { Some(c) => c.run_slices(quantum, max, due_ns, until_ns, last_pc), None => 0 }
}
/// The pc at the end of the last whole slice of dbc_run_slices.
#[no_mangle] pub unsafe extern "C" fn dbc_slice_pc(c: *mut Core) -> u32 { match core(c) { Some(c) => c.slice_pc, None => 0 } }
#[no_mangle] pub unsafe extern "C" fn dbc_stop_reason(c: *mut Core) -> u32 { match core(c) { Some(c) => c.stop_reason(), None => 0 } }
#[no_mangle] pub unsafe extern "C" fn dbc_request_stop(c: *mut Core) { if let Some(c) = core(c) { c.request_stop(); } }
/// 0 = added, 1 = it was there already.
#[no_mangle] pub unsafe extern "C" fn dbc_add_hook(c: *mut Core, vaddr: u32) -> i32 { match core(c) { Some(c) => if c.add_hook(vaddr) { 0 } else { 1 }, None => -1 } }
#[no_mangle] pub unsafe extern "C" fn dbc_del_hook(c: *mut Core, vaddr: u32) { if let Some(c) = core(c) { c.del_hook(vaddr); } }
#[no_mangle] pub unsafe extern "C" fn dbc_icount(c: *mut Core) -> u64 { match core(c) { Some(c) => c.icount(), None => 0 } }
#[no_mangle] pub unsafe extern "C" fn dbc_event_count(c: *mut Core) -> u32 { match core(c) { Some(c) => c.events().len() as u32, None => 0 } }
/// Entry `i` of the event log; any output pointer may be null. 0 = ok, -1 = no such entry.
#[no_mangle] pub unsafe extern "C" fn dbc_event(c: *mut Core, i: u32, icount: *mut u64, kind: *mut u32, pc: *mut u32, far: *mut u32, fsr: *mut u32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    let e = match c.events().get(i as usize) { Some(e) => *e, None => return -1 };
    if !icount.is_null() { icount.write_unaligned(e.icount); }
    if !kind.is_null() { kind.write_unaligned(e.kind); }
    if !pc.is_null() { pc.write_unaligned(e.pc); }
    if !far.is_null() { far.write_unaligned(e.far); }
    if !fsr.is_null() { fsr.write_unaligned(e.fsr); }
    0
}
#[no_mangle] pub unsafe extern "C" fn dbc_clear_events(c: *mut Core) { if let Some(c) = core(c) { c.clear_events(); } }

// ---- compiled devices, clock, interrupt lines ------------------------------------------------------------------------

/// A span that lies in one external window becomes a window of compiled device `kind` (dev::K_*; 0 = of the host alone
/// again). 0 = ok, -1 = bad span, not (all) in one external window, or no such kind.
#[no_mangle] pub unsafe extern "C" fn dbc_map_dev(c: *mut Core, addr: u32, size: u32, kind: u32) -> i32 { match core(c) { Some(c) => c.map_dev(addr, size, kind), None => -1 } }
/// An access to a compiled device, as one from the CPU to its window but without the shadow. 1 = served (the value read is
/// stored through `value`), 0 = the device declines (nothing changed), -1 = bad argument.
#[no_mangle] pub unsafe extern "C" fn dbc_dev_read(c: *mut Core, kind: u32, off: u32, size: u32, value: *mut u32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    if !matches!(size, 1 | 2 | 4) { return -1; }
    match c.dev_read(kind, off, size) {
        Some(x) => { if !value.is_null() { value.write_unaligned(x & (0xffff_ffffu32 >> (32 - 8 * size))); } 1 }
        None => 0,
    }
}
#[no_mangle] pub unsafe extern "C" fn dbc_dev_write(c: *mut Core, kind: u32, off: u32, size: u32, value: u32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    if !matches!(size, 1 | 2 | 4) { return -1; }
    c.dev_write(kind, off, size, value & (0xffff_ffffu32 >> (32 - 8 * size))) as i32
}
/// One word of the state of a compiled device; the fields are listed in the README.
#[no_mangle] pub unsafe extern "C" fn dbc_dev_get(c: *mut Core, kind: u32, field: u32) -> u64 { match core(c) { Some(c) => c.dev_get(kind, field), None => 0 } }
#[no_mangle] pub unsafe extern "C" fn dbc_dev_set(c: *mut Core, kind: u32, field: u32, value: u64) { if let Some(c) = core(c) { c.dev_set(kind, field, value); } }
/// Fire the events of compiled device `kind` that are due at the time of the clock (0 = of every device).
#[no_mangle] pub unsafe extern "C" fn dbc_dev_advance(c: *mut Core, kind: u32) { if let Some(c) = core(c) { c.dev_advance(kind); } }
/// Time of the next event of compiled device `kind` (0 = the earliest of all) in ns, UINT64_MAX when none is armed.
#[no_mangle] pub unsafe extern "C" fn dbc_dev_next_event(c: *mut Core, kind: u32) -> u64 { match core(c) { Some(c) => c.dev_next_event(kind), None => u64::MAX } }
/// The words a compiled device shares with the half of its model that stays outside: the NAND kinds 1-3 dev::nand::NandRegs,
/// kind 7 dev::nand::NandCmd (the state of the command machine, with the page register the store calls fill and read).
/// Valid until dbc_free; null for a kind that shares none.
#[no_mangle] pub unsafe extern "C" fn dbc_dev_regs(c: *mut Core, kind: u32) -> *mut u8 {
    match core(c) {
        Some(c) if (crate::dev::K_NAND_DATA..=crate::dev::K_NAND_ALE).contains(&kind) => &mut c.dev.nand.regs as *mut crate::dev::nand::NandRegs as *mut u8,
        Some(c) if kind == crate::dev::K_NAND_CLE => &mut c.dev.nand.cmd as *mut crate::dev::nand::NandCmd as *mut u8,
        _ => core::ptr::null_mut(),
    }
}
/// Lease `len` bytes to the NAND data port: `write` = 0, reads of the data window hand out data[0..len) in order; else
/// writes fill a buffer of `len` bytes (`data` is then not read and may be null). 0 = ok, -1 = too long.
#[no_mangle] pub unsafe extern "C" fn dbc_port_grant(c: *mut Core, data: *const u8, len: u32, write: i32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    let ok = if write != 0 || data.is_null() { c.dev.nand.grant(&vec![0u8; (len as usize).min(crate::dev::nand::LEASE_MAX + 1)], write != 0) }
             else { c.dev.nand.grant(core::slice::from_raw_parts(data, len as usize), false) };
    if ok { 0 } else { -1 }
}
/// End the lease. Returns the bytes handed out or taken in since the grant; the bytes a write lease took in are copied to
/// `out` (at most `cap`).
#[no_mangle] pub unsafe extern "C" fn dbc_port_take(c: *mut Core, out: *mut u8, cap: u32) -> u32 {
    let c = match core(c) { Some(c) => c, None => return 0 };
    let (n, filled) = c.dev.nand.take();
    if !out.is_null() { let k = filled.len().min(cap as usize); core::ptr::copy_nonoverlapping(filled.as_ptr(), out, k); }
    n
}

/// The clock: instructions charged and time skipped in sleep (ns). Time = insns * ns_per_insn + skipped.
#[no_mangle] pub unsafe extern "C" fn dbc_clock_set(c: *mut Core, insns: u64, skipped_ns: u64) { if let Some(c) = core(c) { c.dev.clock.insns = insns; c.dev.clock.skipped_ns = skipped_ns; } }
#[no_mangle] pub unsafe extern "C" fn dbc_clock_rate(c: *mut Core, ns_per_insn: f64) { if let Some(c) = core(c) { c.dev.clock.ns_per_insn = ns_per_insn; } }
/// what: 0 = the time in ns, 1 = instructions charged, 2 = ns skipped, 3 = the bits of ns_per_insn (a double).
#[no_mangle] pub unsafe extern "C" fn dbc_clock_get(c: *mut Core, what: u32) -> u64 {
    match core(c) { Some(c) => { let k = &c.dev.clock; match what { 0 => k.now_ns(), 1 => k.insns, 2 => k.skipped_ns, 3 => k.ns_per_insn.to_bits(), _ => 0 } } None => 0 }
}

/// Interrupt line `n` (0-63), level-sensitive; may be called from inside a callback.
#[no_mangle] pub unsafe extern "C" fn dbc_set_line(c: *mut Core, n: u32, level: i32) { if let Some(c) = core(c) { c.set_line(n, level != 0); } }
#[no_mangle] pub unsafe extern "C" fn dbc_line(c: *mut Core, n: u32) -> i32 { match core(c) { Some(c) => c.line(n) as i32, None => 0 } }
/// Outputs of the compiled interrupt controllers: bit 0 IRQ, bit 1 FIQ.
#[no_mangle] pub unsafe extern "C" fn dbc_irq_out(c: *mut Core) -> u32 { match core(c) { Some(c) => c.irq_out(), None => 0 } }

// ---- state -------------------------------------------------------------------------------------------------------------

/// Bytes dbc_state_save would write now (0 when that is more than 4 GB).
#[no_mangle] pub unsafe extern "C" fn dbc_state_size(c: *mut Core) -> u32 { match core(c) { Some(c) => u32::try_from(c.state_size()).unwrap_or(0), None => 0 } }
/// Write the state container into buf. Returns the bytes written, 0 when `cap` is too small.
#[no_mangle] pub unsafe extern "C" fn dbc_state_save(c: *mut Core, buf: *mut u8, cap: u32) -> u32 {
    let c = match core(c) { Some(c) => c, None => return 0 };
    if buf.is_null() { return 0; }
    let v = c.save_state();
    if v.len() > cap as usize { return 0; }
    core::ptr::copy_nonoverlapping(v.as_ptr(), buf, v.len());
    v.len() as u32
}
/// 0 = loaded, -1 = not a container or cut short, -2 = a section in a version this core does not know.
#[no_mangle] pub unsafe extern "C" fn dbc_state_load(c: *mut Core, buf: *const u8, len: u32) -> i32 {
    let c = match core(c) { Some(c) => c, None => return -1 };
    if buf.is_null() { return -1; }
    c.load_state(core::slice::from_raw_parts(buf, len as usize))
}

/// A buffer of `len` bytes in the module's memory (WebAssembly: where the host puts a snapshot before dbc_load_snapshot).
#[cfg(target_arch = "wasm32")]
#[no_mangle] pub extern "C" fn dbc_alloc(len: u32) -> *mut u8 {
    let mut v = std::mem::ManuallyDrop::new(Vec::<u8>::with_capacity(len.max(1) as usize));
    v.as_mut_ptr()
}
#[cfg(target_arch = "wasm32")]
#[no_mangle] pub unsafe extern "C" fn dbc_dealloc(p: *mut u8, len: u32) { if !p.is_null() { drop(Vec::from_raw_parts(p, 0, len.max(1) as usize)); } }

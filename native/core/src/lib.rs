//! dbcore: the CPU core of the DB3210 phone simulator. An ARM926EJ-S interpreter (ARM and Thumb state, ARMv5 MMU, cp15,
//! exceptions, level-sensitive interrupt inputs) with physical memory and external windows, behind a small C interface
//! (`dbc_*`, see ffi.rs and the README). No dependencies; builds as a native C library and as a WebAssembly module.
// SPDX-License-Identifier: MIT
#![allow(clippy::all)]

pub mod cpu;
pub mod dev;
pub mod ffi;
pub mod mem;
pub mod mmu;
pub mod state;

pub use cpu::{Cpu, Event};
pub use ffi::*;

#[cfg(test)]
mod tests {
    use super::ffi::*;
    use core::ffi::c_void;

    const CODE: u32 = 0x8000;
    const WIN: u32 = 0x1000_0000;
    const B_SELF: u32 = 0xeaff_fffe;

    /// A core with 1 MB of RAM at 0, `b .` on every vector, ARM code at CODE, SVC mode with interrupts masked, pc at CODE.
    unsafe fn machine(code: &[u32]) -> *mut Core {
        let c = dbc_new();
        assert_eq!(dbc_map_ram(c, 0, 0x10_0000), 0);
        for v in 0..8 { poke(c, 4 * v, B_SELF); }
        for (i, w) in code.iter().enumerate() { poke(c, CODE + 4 * i as u32, *w); }
        dbc_set_reg(c, 16, 0xd3); dbc_set_reg(c, 15, CODE);
        c
    }
    unsafe fn poke(c: *mut Core, a: u32, w: u32) { assert_eq!(dbc_mem_write(c, a, w.to_le_bytes().as_ptr(), 4), 0); }
    unsafe fn poke16(c: *mut Core, a: u32, w: u16) { assert_eq!(dbc_mem_write(c, a, w.to_le_bytes().as_ptr(), 2), 0); }
    unsafe fn peek(c: *mut Core, a: u32) -> u32 { let mut b = [0u8; 4]; assert_eq!(dbc_mem_read(c, a, b.as_mut_ptr(), 4), 0); u32::from_le_bytes(b) }
    unsafe fn event(c: *mut Core, i: u32) -> (u64, u32, u32, u32, u32) {
        let (mut n, mut k, mut pc, mut far, mut fsr) = (0u64, 0u32, 0u32, 0u32, 0u32);
        assert_eq!(dbc_event(c, i, &mut n, &mut k, &mut pc, &mut far, &mut fsr), 0);
        (n, k, pc, far, fsr)
    }

    #[test]
    fn irq_taken_at_the_unmasking_instruction() { unsafe {
        let c = machine(&[0xe3a0_0001 /* mov r0,#1 */, 0xe321_f013 /* msr cpsr_c,#0x13 */, 0xe3a0_0002 /* mov r0,#2 */]);
        dbc_set_irq(c, 1);
        assert_eq!(dbc_run(c, 3), 3);                    // mov, msr, then the instruction at the vector
        assert_eq!(dbc_stop_reason(c), 0);
        assert_eq!(dbc_event_count(c), 1);
        assert_eq!(event(c, 0), (2, 5, CODE + 8, 0, 0));
        assert_eq!(dbc_reg(c, 0), 1);                    // mov r0,#2 did not run
        assert_eq!(dbc_reg(c, 15), 0x18);
        assert_eq!(dbc_reg(c, 16), 0x92);                // IRQ mode, I set
        assert_eq!(dbc_reg(c, 14), CODE + 12);           // lr = next instruction + 4
        assert_eq!(dbc_reg(c, 17), 0x13);                // spsr
        assert_eq!(dbc_reg(c, 26), 0x13);                // the same through the banked id (irq spsr)
        assert_eq!(dbc_icount(c), 3);
        dbc_free(c);
    } }

    #[test]
    fn irq_with_high_vectors_and_from_thumb() { unsafe {
        let c = machine(&[]);
        dbc_map_ram(c, 0xffff_0000, 0x1000); poke(c, 0xffff_0018, B_SELF);
        poke16(c, CODE, 0x2001); poke16(c, CODE + 2, 0x2002);   // movs r0,#1 ; movs r0,#2
        dbc_set_reg(c, 46, 0x2000);                     // SCTLR.V
        dbc_set_reg(c, 16, 0x33);                       // SVC, Thumb, unmasked
        assert_eq!(dbc_run(c, 1), 1);
        dbc_set_irq(c, 1);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 15), dbc_reg(c, 14), dbc_reg(c, 17), dbc_reg(c, 16)), (1, 0xffff_0018, CODE + 6, 0x33, 0x92));
        dbc_free(c);
    } }

    #[test]
    fn fiq_before_irq_and_masks() { unsafe {
        let c = machine(&[0xe3a0_0001, 0xe3a0_0002]);
        dbc_set_reg(c, 16, 0x13);
        dbc_set_irq(c, 1); dbc_set_fiq(c, 1);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(event(c, 0), (0, 6, CODE, 0, 0));
        assert_eq!((dbc_reg(c, 15), dbc_reg(c, 16), dbc_reg(c, 14)), (0x1c, 0xd1, CODE + 4));
        assert_eq!(dbc_event_count(c), 1);               // the IRQ stays pending: I is set
        dbc_free(c);
    } }

    struct Bus { core: *mut Core, log: Vec<(u32, u32, u32, u32, u32)>, irq_on_write: bool, stop_on_write: bool, next: u32 }
    unsafe extern "C" fn bus_rd(user: *mut c_void, dev: u32, off: u32, size: u32) -> u32 {
        let b = &mut *(user as *mut Bus);
        b.next = b.next.wrapping_add(0x1111_1111);
        b.log.push((0, dev, off, size, b.next)); b.next
    }
    unsafe extern "C" fn bus_wr(user: *mut c_void, dev: u32, off: u32, size: u32, value: u32) {
        let b = &mut *(user as *mut Bus);
        b.log.push((1, dev, off, size, value));
        if b.irq_on_write { dbc_set_irq(b.core, 1); }
        if b.stop_on_write { dbc_request_stop(b.core); }
    }
    unsafe fn with_bus(c: *mut Core) -> Box<Bus> {
        let mut b = Box::new(Bus { core: c, log: Vec::new(), irq_on_write: false, stop_on_write: false, next: 0x8091_a2b3 });
        assert_eq!(dbc_map_ext(c, WIN, 0x2000, 7), 0);
        dbc_set_ext(c, Some(bus_rd), Some(bus_wr), &mut *b as *mut Bus as *mut c_void);
        b
    }

    #[test]
    fn irq_raised_by_an_ext_write_is_taken_before_the_next_instruction() { unsafe {
        let c = machine(&[0xe3a0_1201 /* mov r1,#0x10000000 */, 0xe581_0000 /* str r0,[r1] */, 0xe3a0_2005 /* mov r2,#5 */]);
        let mut b = with_bus(c); b.irq_on_write = true;
        dbc_set_reg(c, 16, 0x13);
        assert_eq!(dbc_run(c, 3), 3);
        assert_eq!(event(c, 0), (2, 5, CODE + 8, 0, 0));
        assert_eq!((dbc_reg(c, 2), dbc_reg(c, 15), dbc_reg(c, 14)), (0, 0x18, CODE + 12));
        assert_eq!(b.log, vec![(1, 7, 0, 4, 0)]);
        dbc_free(c);
    } }

    #[test]
    fn stop_requested_from_a_callback_ends_the_run_after_the_instruction() { unsafe {
        let c = machine(&[0xe3a0_1201, 0xe581_0000, 0xe3a0_2005, 0xe3a0_3006]);
        let mut b = with_bus(c); b.stop_on_write = true;
        assert_eq!(dbc_run(c, 100), 2);
        assert_eq!((dbc_stop_reason(c), dbc_reg(c, 15), dbc_reg(c, 2)), (2, CODE + 8, 0));
        b.stop_on_write = false;
        assert_eq!(dbc_run(c, 2), 2);
        assert_eq!((dbc_stop_reason(c), dbc_reg(c, 2), dbc_reg(c, 3)), (0, 5, 6));
        dbc_free(c);
    } }

    #[test]
    fn wfi_halts_and_an_input_wakes() { unsafe {
        let c = machine(&[0xe3a0_0001, 0xee07_0f90 /* mcr p15,0,r0,c7,c0,4 */, 0xe3a0_0002, 0xe321_f013, 0xe3a0_0003]);
        assert_eq!(dbc_run(c, 100), 2);                  // the wait-for-interrupt completes and counts
        assert_eq!((dbc_stop_reason(c), dbc_reg(c, 15), dbc_icount(c)), (1, CODE + 8, 2));
        assert_eq!(dbc_run(c, 100), 0);                  // still halted
        assert_eq!(dbc_stop_reason(c), 1);
        dbc_set_irq(c, 1);
        assert_eq!(dbc_run(c, 1), 1);                    // woken with I set: goes on, no interrupt
        assert_eq!((dbc_reg(c, 0), dbc_event_count(c), dbc_stop_reason(c)), (2, 0, 0));
        assert_eq!(dbc_run(c, 2), 2);                    // the msr unmasks; the interrupt is taken before mov r0,#3
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 15)), (2, 0x18));
        assert_eq!(event(c, 0), (4, 5, CODE + 16, 0, 0));
        dbc_free(c);
    } }

    #[test]
    fn wfi_wakes_into_the_handler_when_unmasked() { unsafe {
        let c = machine(&[0xee07_0f90, 0xe3a0_0002]);
        dbc_set_reg(c, 16, 0x13);
        assert_eq!(dbc_run(c, 100), 1);
        assert_eq!(dbc_stop_reason(c), 1);
        dbc_set_irq(c, 1);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!((dbc_reg(c, 15), dbc_reg(c, 14), dbc_reg(c, 0)), (0x18, CODE + 8, 0));
        dbc_free(c);
    } }

    /// MMU on: the first megabyte mapped flat as one section (domain 0, client, read / write), the next one not mapped.
    unsafe fn mmu_on(c: *mut Core) {
        poke(c, 0x4000, 0x0000_0c12);
        dbc_set_reg(c, 47, 0x4000); dbc_set_reg(c, 48, 1); dbc_set_reg(c, 46, 1);
    }

    #[test]
    fn faulting_ldm_keeps_the_words_before_the_fault_and_the_base() { unsafe {
        let c = machine(&[0xe8b0_001e /* ldmia r0!,{r1-r4} */]);
        mmu_on(c);
        poke(c, 0xf_fff8, 0x1111_1111); poke(c, 0xf_fffc, 0x2222_2222);
        dbc_set_reg(c, 0, 0xf_fff8);
        for i in 1..5 { dbc_set_reg(c, i, 0xa0 + i); }
        assert_eq!(dbc_run(c, 1), 1);                    // the abort is taken, then the instruction at the vector runs
        assert_eq!(event(c, 0), (0, 1, CODE, 0x10_0000, 5));
        // the two words before the fault are loaded, the rest and the base are as before
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 1), dbc_reg(c, 2), dbc_reg(c, 3), dbc_reg(c, 4)), (0xf_fff8, 0x1111_1111, 0x2222_2222, 0xa3, 0xa4));
        assert_eq!((dbc_reg(c, 15), dbc_reg(c, 14), dbc_reg(c, 16), dbc_reg(c, 17)), (0x10, CODE + 8, 0x97 | 0x40, 0xd3));
        assert_eq!((dbc_reg(c, 50), dbc_reg(c, 52)), (5, 0x10_0000));
        assert_eq!(dbc_icount(c), 1);                    // the faulting instruction is not counted
        dbc_free(c);
    } }

    #[test]
    fn faulting_loads_and_stores_with_write_back_leave_the_base() { unsafe {
        // each: (instruction, r0, r1..r4 afterwards, the word at 0xffffc afterwards); the access touches the unmapped megabyte.
        // Single transfers change nothing; the double and multiple ones keep what went through before the fault.
        const M: u32 = 0x5555_5555;
        let cases: [(u32, u32, [u32; 4], u32); 9] = [
            (0xe490_1004, 0x10_0000, [0xa1, 0xa2, 0xa3, 0xa4], M),      // ldr r1,[r0],#4
            (0xe5b0_1008, 0xf_fff8, [0xa1, 0xa2, 0xa3, 0xa4], M),       // ldr r1,[r0,#8]!
            (0xe480_1004, 0x10_0000, [0xa1, 0xa2, 0xa3, 0xa4], M),      // str r1,[r0],#4
            (0xe0d0_10b2, 0x10_0000, [0xa1, 0xa2, 0xa3, 0xa4], M),      // ldrh r1,[r0],#2
            (0xe1e0_20d8, 0xf_fff4, [0xa1, M, 0xa3, 0xa4], M),          // ldrd r2,r3,[r0,#8]!    second word faults
            (0xe0c0_20d8, 0xf_fffc, [0xa1, M, 0xa3, 0xa4], M),          // ldrd r2,r3,[r0],#8     second word faults
            (0xe0c0_20f8, 0xf_fffc, [0xa1, 0xa2, 0xa3, 0xa4], 0xa2),    // strd r2,r3,[r0],#8     second word faults
            (0xe920_001e, 0x10_0008, [0xa1, 0xa2, 0xa3, 0xa4], 0xa2),   // stmdb r0!,{r1-r4}      the two upper words fault
            (0xe100_1092, 0x10_0000, [0xa1, 0xa2, 0xa3, 0xa4], M),      // swp r1,r2,[r0]
        ];
        for (k, (op, base, regs, word)) in cases.iter().enumerate() {
            let c = machine(&[*op]);
            mmu_on(c);
            poke(c, 0xf_fffc, M);
            dbc_set_reg(c, 0, *base);
            for i in 1..5 { dbc_set_reg(c, i, 0xa0 + i); }
            assert_eq!(dbc_run(c, 1), 1, "case {}", k);
            assert_eq!(event(c, 0).1, 1, "case {}", k);
            assert_eq!(dbc_reg(c, 0), *base, "case {}: base", k);
            assert_eq!([dbc_reg(c, 1), dbc_reg(c, 2), dbc_reg(c, 3), dbc_reg(c, 4)], *regs, "case {}", k);
            assert_eq!(peek(c, 0xf_fffc), *word, "case {}: memory", k);
            assert_eq!(dbc_reg(c, 14), CODE + 8, "case {}", k);
            dbc_free(c);
        }
    } }

    #[test]
    fn faulting_thumb_push_and_pop_leave_the_stack_pointer() { unsafe {
        // push: r4-r6 are stored below the boundary, then the fault; pop: r4 and r5 are loaded, then the fault
        for (op, sp, regs) in [(0xb5f0u16 /* push {r4-r7,lr} */, 0x10_0008u32, [0xb4u32, 0xb5, 0xb6, 0xb7]), (0xbdf0 /* pop {r4-r7,pc} */, 0xf_fff8, [0x4444, 0x5555, 0xb6, 0xb7])] {
            let c = machine(&[]);
            mmu_on(c);
            poke16(c, CODE, op);
            poke(c, 0xf_fff8, 0x4444); poke(c, 0xf_fffc, 0x5555);
            dbc_set_reg(c, 16, 0xf3); dbc_set_reg(c, 13, sp);
            for i in 4..8 { dbc_set_reg(c, i, 0xb0 + i); }
            assert_eq!(dbc_run(c, 1), 1);
            assert_eq!(event(c, 0).1, 1);
            assert_eq!(dbc_reg(c, 32), 0xf3);            // abt spsr: the Thumb state at the fault
            assert_eq!(dbc_reg(c, 27), sp);              // svc sp unchanged
            assert_eq!([dbc_reg(c, 4), dbc_reg(c, 5), dbc_reg(c, 6), dbc_reg(c, 7)], regs);
            if op == 0xb5f0 { assert_eq!((peek(c, 0xf_fff4), peek(c, 0xf_fff8), peek(c, 0xf_fffc)), (0xb4, 0xb5, 0xb6)); }
            assert_eq!(dbc_reg(c, 14), CODE + 8);
            dbc_free(c);
        }
    } }

    #[test]
    fn a_base_in_the_list_keeps_its_value_when_a_later_word_faults() { unsafe {
        // the word of the base is read below the boundary, the fault comes after it: the restarted instruction needs the base
        for (name, op) in [("ldmia r0,{r0-r3}", 0xe890_000fu32), ("ldmia r0,{r0-r3}^", 0xe8d0_000f), ("ldrd r0,r1,[r0]", 0xe1c0_00d0)] {
            for mode in [0xd3u32, 0xdf] {
                let c = machine(&[op]);
                mmu_on(c);
                poke(c, 0xf_fffc, 0x7777_7777);
                dbc_set_reg(c, 16, mode); dbc_set_reg(c, 0, 0xf_fffc);
                for i in 1..4 { dbc_set_reg(c, i, 0xa0 + i); }
                assert_eq!(dbc_run(c, 1), 1, "{}", name);
                assert_eq!(event(c, 0), (0, 1, CODE, 0x10_0000, 5), "{}", name);
                assert_eq!([dbc_reg(c, 0), dbc_reg(c, 1), dbc_reg(c, 2), dbc_reg(c, 3)], [0xf_fffc, 0xa1, 0xa2, 0xa3], "{}, mode {:#x}", name, mode);
                dbc_free(c);
                // and complete: the base takes its word
                let c = machine(&[op]);
                mmu_on(c);
                for i in 0..4 { poke(c, 0xe_0000 + 4 * i, 0x10 + i); }
                dbc_set_reg(c, 16, mode); dbc_set_reg(c, 0, 0xe_0000);
                assert_eq!(dbc_run(c, 1), 1, "{}", name);
                assert_eq!((dbc_event_count(c), dbc_reg(c, 0), dbc_reg(c, 1)), (0, 0x10, 0x11), "{}, mode {:#x}", name, mode);
                dbc_free(c);
            }
        }
    } }

    #[test]
    fn hook_stops_before_the_instruction_once_per_arrival() { unsafe {
        let c = machine(&[0xe3a0_0001, 0xe3a0_0002, 0xe3a0_0003, 0xeaff_fffc /* b CODE+4 */]);
        assert_eq!(dbc_add_hook(c, CODE + 8), 0);
        assert_eq!(dbc_add_hook(c, CODE + 8), 1);
        assert_eq!(dbc_run(c, 100), 2);
        assert_eq!((dbc_stop_reason(c), dbc_reg(c, 15), dbc_reg(c, 0)), (3, CODE + 8, 2));
        assert_eq!(dbc_run(c, 100), 3);                  // goes on past the hook and round the loop to it again
        assert_eq!((dbc_stop_reason(c), dbc_reg(c, 15), dbc_reg(c, 0), dbc_icount(c)), (3, CODE + 8, 2, 5));
        dbc_del_hook(c, CODE + 8);
        assert_eq!(dbc_run(c, 100), 100);
        assert_eq!(dbc_stop_reason(c), 0);
        // a run that ends by budget at a hooked address has not reported the hook yet
        let c2 = machine(&[0xe3a0_0001, 0xe3a0_0002]);
        dbc_add_hook(c2, CODE + 4);
        assert_eq!(dbc_run(c2, 1), 1);
        assert_eq!(dbc_stop_reason(c2), 0);
        assert_eq!(dbc_run(c2, 1), 0);
        assert_eq!(dbc_stop_reason(c2), 3);
        assert_eq!(dbc_run(c2, 1), 1);
        assert_eq!((dbc_stop_reason(c2), dbc_reg(c2, 0)), (0, 2));
        dbc_free(c); dbc_free(c2);
    } }

    #[test]
    fn thumb_bl_pair_counts_two_only_across_a_1k_boundary() { unsafe {
        let c = machine(&[]);
        // target = address + 4 + 0x100; `b .` at both targets
        for a in [0x83feu32, 0x93fc] { poke16(c, a, 0xf000); poke16(c, a + 2, 0xf880); poke16(c, a + 0x104, 0xe7fe); }
        dbc_set_reg(c, 16, 0xf3); dbc_set_reg(c, 15, 0x83fe);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(dbc_reg(c, 15), 0x8400);              // only the first half ran
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!((dbc_reg(c, 15), dbc_reg(c, 14)), (0x8502, 0x8403));
        dbc_set_reg(c, 15, 0x93fc);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!((dbc_reg(c, 15), dbc_reg(c, 14), dbc_icount(c)), (0x9500, 0x9401, 3));
        dbc_free(c);
    } }

    #[test]
    fn ext_window_sizes_order_and_shadow() { unsafe {
        let c = machine(&[
            0xe3a0_1201,          // mov r1,#0x10000000
            0xe591_2000,          // ldr r2,[r1]
            0xe5d1_3004,          // ldrb r3,[r1,#4]
            0xe1d1_40b8,          // ldrh r4,[r1,#8]
            0xe581_0010,          // str r0,[r1,#0x10]
            0xe5c1_0014,          // strb r0,[r1,#0x14]
            0xe1c1_01b8,          // strh r0,[r1,#0x18]
            0xe981_0070,          // stmib r1,{r4,r5,r6}
            0xe891_0600,          // ldmia r1,{r9,r10}
        ]);
        let b = with_bus(c);
        dbc_set_reg(c, 0, 0xcafe_f00d); dbc_set_reg(c, 5, 0x55); dbc_set_reg(c, 6, 0x66);
        assert_eq!(dbc_run(c, 9), 9);
        assert_eq!(dbc_event_count(c), 0);
        let v = |k: u32| 0x8091_a2b3u32.wrapping_add(0x1111_1111u32.wrapping_mul(k));
        assert_eq!(b.log, vec![
            (0, 7, 0, 4, v(1)), (0, 7, 4, 1, v(2)), (0, 7, 8, 2, v(3)),
            (1, 7, 0x10, 4, 0xcafe_f00d), (1, 7, 0x14, 1, 0x0d), (1, 7, 0x18, 2, 0xf00d),
            (1, 7, 4, 4, v(3) & 0xffff), (1, 7, 8, 4, 0x55), (1, 7, 12, 4, 0x66),
            (0, 7, 0, 4, v(4)), (0, 7, 4, 4, v(5)),
        ]);
        assert_eq!((dbc_reg(c, 2), dbc_reg(c, 3), dbc_reg(c, 4)), (v(1), v(2) & 0xff, v(3) & 0xffff));
        assert_eq!((dbc_reg(c, 9), dbc_reg(c, 10)), (v(4), v(5)));
        // the shadow holds the last value that crossed the bus, at its size
        assert_eq!(peek(c, WIN), v(4)); assert_eq!(peek(c, WIN + 4), v(5)); assert_eq!(peek(c, WIN + 8), 0x55); assert_eq!(peek(c, WIN + 12), 0x66);
        assert_eq!(peek(c, WIN + 0x10), 0xcafe_f00d); assert_eq!(peek(c, WIN + 0x14), 0x0d); assert_eq!(peek(c, WIN + 0x18), 0xf00d);
        // writing the shadow from outside calls nobody
        poke(c, WIN + 0x20, 0x1234_5678);
        assert_eq!(peek(c, WIN + 0x20), 0x1234_5678);
        assert_eq!(b.log.len(), 11);
        dbc_free(c);
    } }

    /// First address of the megabyte after the one of WIN.
    const EDGE: u32 = WIN + 0x10_0000;
    /// The block transfers: (name, Thumb, instruction, base register by interface id, words, descending from the base,
    /// a load). Each is run with its last words in the megabyte after EDGE and with all words below EDGE.
    const BLOCKS: [(&str, bool, u32, u32, u32, bool, bool); 16] = [
        ("ldmia r0!,{r1-r3}", false, 0xe8b0_000e, 0, 3, false, true),
        ("stmia r0!,{r1-r3}", false, 0xe8a0_000e, 0, 3, false, false),
        ("ldmdb r0!,{r1-r4}", false, 0xe930_001e, 0, 4, true, true),
        ("stmdb r0!,{r1-r4}", false, 0xe920_001e, 0, 4, true, false),
        ("ldmia r0,{r1,pc}", false, 0xe890_8002, 0, 2, false, true),
        ("ldmia r0,{r1-r3}^", false, 0xe8d0_000e, 0, 3, false, true),
        ("stmia r0,{r1-r3}^", false, 0xe8c0_000e, 0, 3, false, false),
        ("ldrd r2,r3,[r0],#8", false, 0xe0c0_20d8, 0, 2, false, true),
        ("strd r2,r3,[r0],#8", false, 0xe0c0_20f8, 0, 2, false, false),
        ("push {r4-r7,lr}", true, 0xb5f0, 27, 5, true, false),
        ("push {r4,lr}", true, 0xb510, 27, 2, true, false),
        ("pop {r4-r7,pc}", true, 0xbdf0, 27, 5, false, true),
        ("pop {r4,pc}", true, 0xbd10, 27, 2, false, true),
        ("pop {r4-r6}", true, 0xbc70, 27, 3, false, true),
        ("ldmia r0!,{r1-r3} (Thumb)", true, 0xc80e, 0, 3, false, true),
        ("stmia r0!,{r1-r3} (Thumb)", true, 0xc00e, 0, 3, false, false),
    ];
    /// A machine with one block transfer at CODE. MMU on: megabyte 0 and the megabyte of WIN flat; `next`: the first-level
    /// entry of the megabyte at EDGE (0 = not mapped). The last page below EDGE is a window of device 9, and with
    /// `kind` != 0 it belongs to that compiled device. r1-r7 hold 0xa1-0xa7, lr 0xae.
    unsafe fn block_machine(thumb: bool, op: u32, kind: u32, next: u32) -> (*mut Core, Box<Bus>) {
        let c = machine(&[]);
        if thumb { poke16(c, CODE, op as u16); } else { poke(c, CODE, op); }
        let b = with_bus(c);
        poke(c, 0x4000, 0x0000_0c12); poke(c, 0x4000 + 4 * 0x100, 0x1000_0c12); poke(c, 0x4000 + 4 * 0x101, next);
        dbc_set_reg(c, 47, 0x4000); dbc_set_reg(c, 48, 1); dbc_set_reg(c, 46, 1);
        assert_eq!(dbc_map_ext(c, EDGE - 0x1000, 0x1000, 9), 0);
        if kind != 0 { assert_eq!(dbc_map_dev(c, EDGE - 0x1000, 0x1000, kind), 0); }
        dbc_set_reg(c, 16, if thumb { 0xf3 } else { 0xd3 });
        for i in 1..8 { dbc_set_reg(c, i, 0xa0 + i); }
        dbc_set_reg(c, 14, 0xae);
        (c, b)
    }
    const K_TIMER: u32 = crate::dev::K_TIMER;
    unsafe fn served(c: *mut Core) -> u64 { dbc_dev_get(c, K_TIMER, crate::dev::F_READS) + dbc_dev_get(c, K_TIMER, crate::dev::F_WRITES) }

    #[test]
    fn a_block_transfer_that_is_going_to_abort_reaches_no_device() { unsafe {
        // every word but the last lies in the window, the last one in the megabyte that is not mapped
        for kind in [0, K_TIMER] {
            for (name, thumb, op, breg, n, down, _) in BLOCKS {
                let what = format!("{}, kind {}", name, kind);
                let (c, b) = block_machine(thumb, op, kind, 0);
                let base = if down { EDGE + 4 } else { EDGE - 4 * (n - 1) };
                dbc_set_reg(c, breg, base);
                assert_eq!(dbc_run(c, 1), 1, "{}", what);            // the abort, then the instruction at the vector
                assert_eq!(dbc_event_count(c), 1, "{}", what);
                assert_eq!(event(c, 0), (0, 1, CODE, EDGE, 5), "{}", what);
                assert_eq!((dbc_reg(c, 50), dbc_reg(c, 52)), (5, EDGE), "{}: DFSR, FAR", what);
                assert_eq!((dbc_reg(c, 15), dbc_reg(c, 14)), (0x10, CODE + 8), "{}", what);
                assert!(b.log.is_empty(), "{}: the host was called: {:x?}", what, b.log);
                assert_eq!(served(c), 0, "{}: the compiled device was reached", what);
                assert_eq!(dbc_reg(c, breg), base, "{}: base", what);
                for i in 1..8 { assert_eq!(dbc_reg(c, i), 0xa0 + i, "{}: r{}", what, i); }
                assert_eq!(dbc_reg(c, 28), 0xae, "{}: lr", what);
                for a in (EDGE - 0x20..EDGE).step_by(4) { assert_eq!(peek(c, a), 0, "{}: shadow at {:#x}", what, a); }
                dbc_free(c);
            }
        }
    } }

    #[test]
    fn the_abort_taken_before_a_device_word_is_the_one_of_the_first_faulting_word() { unsafe {
        // the megabyte at EDGE is mapped with no access for anybody: a permission fault of a section (status 13), reported
        // for the first word in it although two more words follow; a store and a load
        for kind in [0, K_TIMER] {
            for (op, base) in [(0xe8a0_00feu32 /* stmia r0!,{r1-r7} */, EDGE - 16), (0xe8b0_00fe /* ldmia r0!,{r1-r7} */, EDGE - 16)] {
                let (c, b) = block_machine(false, op, kind, 0x1010_0012);
                dbc_set_reg(c, 0, base);
                assert_eq!(dbc_run(c, 1), 1);
                assert_eq!(event(c, 0), (0, 1, CODE, EDGE, 13));
                assert!(b.log.is_empty() && served(c) == 0);
                assert_eq!(dbc_reg(c, 0), base);
                for i in 1..8 { assert_eq!(dbc_reg(c, i), 0xa0 + i); }
                dbc_free(c);
            }
        }
    } }

    #[test]
    fn a_block_transfer_that_completes_reaches_the_device_once_per_word_in_ascending_order() { unsafe {
        for kind in [0, K_TIMER] {
            for (name, thumb, op, breg, n, down, load) in BLOCKS {
                let what = format!("{}, kind {}", name, kind);
                let (c, b) = block_machine(thumb, op, kind, 0);
                let base = if down { EDGE } else { EDGE - 4 * n };
                dbc_set_reg(c, breg, base);
                assert_eq!(dbc_run(c, 1), 1, "{}", what);
                assert_eq!(dbc_event_count(c), 0, "{}", what);
                if kind == 0 {
                    let want: Vec<(u32, u32, u32, u32)> = (0..n).map(|i| (!load as u32, 9, 0x1000 - 4 * n + 4 * i, 4)).collect();
                    let got: Vec<(u32, u32, u32, u32)> = b.log.iter().map(|e| (e.0, e.1, e.2, e.3)).collect();
                    assert_eq!(got, want, "{}", what);
                } else {
                    assert!(b.log.is_empty(), "{}", what);
                    assert_eq!(dbc_dev_get(c, K_TIMER, if load { crate::dev::F_READS } else { crate::dev::F_WRITES }), n as u64, "{}", what);
                    assert_eq!(served(c), n as u64, "{}", what);
                }
                dbc_free(c);
            }
        }
    } }

    #[test]
    fn memory_words_before_the_window_are_transferred_and_the_window_words_follow() { unsafe {
        // the last word of a page of memory, then two words of the window; and the same stored
        let (c, b) = block_machine(false, 0xe8b0_000e /* ldmia r0!,{r1-r3} */, 0, 0);
        poke(c, EDGE - 0x1004, 0x1234_5678);
        dbc_set_reg(c, 0, EDGE - 0x1004);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 1), dbc_reg(c, 2), dbc_reg(c, 3)), (EDGE - 0x1004 + 12, 0x1234_5678, 0x91a2_b3c4, 0xa2b3_c4d5));
        assert_eq!(b.log, vec![(0, 9, 0, 4, 0x91a2_b3c4), (0, 9, 4, 4, 0xa2b3_c4d5)]);
        dbc_free(c);
        let (c, b) = block_machine(false, 0xe8a0_000e /* stmia r0!,{r1-r3} */, 0, 0);
        dbc_set_reg(c, 0, EDGE - 0x1004);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!((peek(c, EDGE - 0x1004), dbc_reg(c, 0)), (0xa1, EDGE - 0x1004 + 12));
        assert_eq!(b.log, vec![(1, 9, 0, 4, 0xa2), (1, 9, 4, 4, 0xa3)]);
        dbc_free(c);
    } }

    #[test]
    fn memory_words_before_a_fault_are_transferred_when_no_device_word_lies_between() { unsafe {
        // as before the rule for devices: the page below EDGE is memory here (kind 0 window given back by mapping RAM)
        let (c, b) = block_machine(false, 0xe8b0_000e /* ldmia r0!,{r1-r3} */, 0, 0);
        assert_eq!(dbc_map_ram(c, EDGE - 0x1000, 0x1000), 0);
        poke(c, EDGE - 8, 0x1111_1111); poke(c, EDGE - 4, 0x2222_2222);
        dbc_set_reg(c, 0, EDGE - 8);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(event(c, 0), (0, 1, CODE, EDGE, 5));
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 1), dbc_reg(c, 2), dbc_reg(c, 3)), (EDGE - 8, 0x1111_1111, 0x2222_2222, 0xa3));
        assert!(b.log.is_empty());
        dbc_free(c);
    } }

    #[test]
    fn a_window_with_no_callback_and_no_device_is_memory_for_a_block_transfer_too() { unsafe {
        let (c, _b) = block_machine(false, 0xe8a0_000e /* stmia r0!,{r1-r3} */, 0, 0);
        dbc_set_ext(c, None, None, core::ptr::null_mut());
        dbc_set_reg(c, 0, EDGE - 8);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(event(c, 0), (0, 1, CODE, EDGE, 5));
        assert_eq!((peek(c, EDGE - 8), peek(c, EDGE - 4), dbc_reg(c, 0)), (0xa1, 0xa2, EDGE - 8));
        dbc_free(c);
    } }

    #[test]
    fn a_window_costs_nothing_until_a_page_of_it_is_accessed() { unsafe {
        // the four hardware windows of the simulator, 1.28 GB: the state names them and holds no page of them
        let c = machine(&[0xe590_1000 /* ldr r1,[r0] */, 0xe580_2004 /* str r2,[r0,#4] */, 0xe1a0_f003 /* mov pc,r3 */]);
        let n0 = dbc_state_size(c);
        let mut b = Box::new(Bus { core: c, log: Vec::new(), irq_on_write: false, stop_on_write: false, next: 0x8091_a2b3 });
        dbc_set_ext(c, Some(bus_rd), Some(bus_wr), &mut *b as *mut Bus as *mut c_void);
        for (i, (a, size)) in [(0xa000_0000u32, 0x1000_0000u32), (0xc000_0000, 0x1000_0000), (0x6000_0000, 0x1000_0000), (0x8000_0000, 0x2000_0000)].iter().enumerate() {
            assert_eq!(dbc_map_ext(c, *a, *size, 1 + i as u32), 0);
        }
        assert_eq!(dbc_map_dev(c, 0xc001_a000, 0x1000, K_TIMER), 0);
        let n1 = dbc_state_size(c);
        assert!(n1 - n0 < 400, "the windows take {} bytes of state", n1 - n0);
        assert_eq!(peek(c, 0x9fff_fffc), 0);                 // a read from outside allocates nothing
        assert_eq!(dbc_state_size(c), n1);
        // the first access gives the page its shadow, and the access goes to the device of its window
        dbc_set_reg(c, 0, 0x8fff_f000); dbc_set_reg(c, 2, 0x77); dbc_set_reg(c, 3, 0x6000_0000);
        assert_eq!(dbc_run(c, 2), 2);
        assert_eq!(b.log, vec![(0, 4, 0x0fff_f000, 4, 0x91a2_b3c4), (1, 4, 0x0fff_f004, 4, 0x77)]);
        assert_eq!((peek(c, 0x8fff_f000), peek(c, 0x8fff_f004)), (0x91a2_b3c4, 0x77));
        assert_eq!(dbc_state_size(c), n1 + 12 + 4096 + 12);  // one page with contents; the run of pages without is now two
        // a fetch from a page of a window that was never accessed reads zeros (andeq r0,r0,r0), as before
        assert_eq!(dbc_run(c, 3), 3);
        assert_eq!((dbc_stop_reason(c), dbc_reg(c, 15)), (0, 0x6000_0008));
        // save, and load into a fresh core: the same windows, with and without shadow, and the compiled one
        let n = dbc_state_size(c);
        let mut blob = vec![0u8; n as usize];
        assert_eq!(dbc_state_save(c, blob.as_mut_ptr(), n), n);
        let d = dbc_new();
        assert_eq!(dbc_state_load(d, blob.as_ptr(), n), 0);
        let mut again = vec![0u8; n as usize];
        assert_eq!(dbc_state_save(d, again.as_mut_ptr(), n), n);
        assert!(blob == again, "a loaded state saves as the same bytes");
        let mut b2 = Box::new(Bus { core: d, log: Vec::new(), irq_on_write: false, stop_on_write: false, next: 0 });
        dbc_set_ext(d, Some(bus_rd), Some(bus_wr), &mut *b2 as *mut Bus as *mut c_void);
        assert_eq!(peek(d, 0x8fff_f000), 0x91a2_b3c4);
        dbc_set_reg(d, 15, CODE); dbc_set_reg(d, 0, 0xa123_4000);
        assert_eq!(dbc_run(d, 1), 1);
        assert_eq!(b2.log, vec![(0, 1, 0x0123_4000, 4, 0x1111_1111)]);
        dbc_set_reg(d, 15, CODE); dbc_set_reg(d, 0, 0xc001_a020);
        assert_eq!(dbc_run(d, 2), 2);
        assert_eq!((b2.log.len(), served(d)), (1, 2), "the timer's window is the timer's in the loaded core");
        // memory mapped over a window page that has no shadow is memory
        assert_eq!(dbc_map_ram(d, 0xa200_0000, 0x1000), 0);
        dbc_set_reg(d, 15, CODE); dbc_set_reg(d, 0, 0xa200_0000);
        assert_eq!(dbc_run(d, 2), 2);
        assert_eq!((b2.log.len(), peek(d, 0xa200_0004)), (1, 0x77));
        dbc_free(c); dbc_free(d);
    } }

    #[test]
    fn swi_undefined_and_unmapped_fetch() { unsafe {
        let c = machine(&[0xef00_0042 /* swi */, 0xe7f0_00f0 /* undefined */]);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(event(c, 0), (0, 3, CODE, 0, 0));
        assert_eq!((dbc_reg(c, 15), dbc_reg(c, 14), dbc_reg(c, 16)), (0x08, CODE + 4, 0xd3));
        dbc_set_reg(c, 15, CODE + 4);
        assert_eq!(dbc_run(c, 1), 1);
        assert_eq!(event(c, 1), (1, 4, CODE + 4, 0, 0));
        assert_eq!((dbc_reg(c, 15), dbc_reg(c, 14), dbc_reg(c, 16)), (0x04, CODE + 8, 0xdb));
        dbc_set_reg(c, 15, 0x4000_0000);
        assert_eq!(dbc_run(c, 5), 0);
        assert_eq!((dbc_stop_reason(c), dbc_reg(c, 15)), (4, 0x4000_0000));
        dbc_clear_events(c);
        assert_eq!(dbc_event_count(c), 0);
        dbc_free(c);
    } }

    #[test]
    fn registers_by_id_follow_the_mode() { unsafe {
        let c = machine(&[]);
        dbc_set_reg(c, 13, 0x1000);                      // svc sp (current)
        dbc_set_reg(c, 18, 0x2000);                      // usr sp
        dbc_set_reg(c, 24, 0x3000);                      // irq sp
        dbc_set_reg(c, 36, 0xf8);                        // fiq r8
        dbc_set_reg(c, 8, 0x88);                         // r8 (current = the usr one)
        assert_eq!((dbc_reg(c, 27), dbc_reg(c, 41)), (0x1000, 0x88));
        dbc_set_reg(c, 16, 0xd1);                        // to FIQ mode
        assert_eq!((dbc_reg(c, 8), dbc_reg(c, 41), dbc_reg(c, 36), dbc_reg(c, 27)), (0xf8, 0x88, 0xf8, 0x1000));
        dbc_set_reg(c, 16, 0xd2);
        assert_eq!((dbc_reg(c, 13), dbc_reg(c, 8)), (0x3000, 0x88));
        dbc_set_reg(c, 16, 0xdf);                        // system mode shares the user registers
        assert_eq!(dbc_reg(c, 13), 0x2000);
        dbc_free(c);
    } }

    #[test]
    fn snapshot_round_trip_and_bad_data() { unsafe {
        let c = dbc_new();
        let mut s: Vec<u8> = b"SNAP1\0\0\0".to_vec();
        let mut w = [0u32; 50];
        w[0] = 7; w[15] = CODE; w[16] = 0xd3; w[25] = 0x1234;      // r0, pc, cpsr, irq lr
        s.extend_from_slice(&50u32.to_le_bytes());
        for x in w { s.extend_from_slice(&x.to_le_bytes()); }
        s.extend_from_slice(&1u32.to_le_bytes());
        s.extend_from_slice(&CODE.to_le_bytes()); s.extend_from_slice(&4096u32.to_le_bytes());
        let mut page = vec![0u8; 4096]; page[..4].copy_from_slice(&0xe280_0001u32.to_le_bytes());   // add r0,r0,#1
        page[4..8].copy_from_slice(&B_SELF.to_le_bytes());
        s.extend_from_slice(&page);
        assert_eq!(dbc_load_snapshot(c, s.as_ptr(), s.len() as u32), 0);
        assert_eq!(dbc_run(c, 10), 10);
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 15), dbc_reg(c, 25), dbc_icount(c)), (8, CODE + 4, 0x1234, 10));
        assert_eq!(dbc_load_snapshot(c, s.as_ptr(), s.len() as u32 - 1), -1);
        assert_eq!(dbc_load_snapshot(c, s.as_ptr().add(1), s.len() as u32 - 1), -1);
        dbc_free(c);
    } }
}

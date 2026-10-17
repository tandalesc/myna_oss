# dbcore: the compiled CPU core

An ARM926EJ-S interpreter with its memory, written in Rust with no dependencies: Myna's engine, in a terminal and in a
browser tab. The same source builds a native C library (`libdbcore.dylib` / `.so`) and a WebAssembly module
(`dbcore.wasm`, target `wasm32-unknown-unknown`). Devices are outside, reached through callbacks to the simulator's
Python device models, except those that have moved in: the NAND flash controller and its command machine (the contents
of the chip stay outside), the sleep / OS timer with the clock, the two interrupt controllers, and two blocks of stored
registers (system control, clock profile).

| file | what |
|---|---|
| `src/cpu.rs` | ARM and Thumb state, the ARMv5TE instructions, exceptions, interrupt inputs, instruction counting, entry hooks |
| `src/mmu.rs` | the ARMv5 table walk (sections, coarse and fine tables, all page sizes, domains, S / R bits, FCSE), a software TLB, cp15 |
| `src/mem.rs` | physical memory in 4K pages, external windows with shadow pages made at the first access |
| `src/dev/` | the compiled devices (`nand.rs`, `timer.rs`, `vic.rs`, `sysctl.rs`), the clock, and their shared dispatch |
| `src/state.rs` | state save and load: one container with a section per part |
| `src/ffi.rs` | the C interface (`dbc_*`); each function's comment is its specification |
| `python/dbcore.py` | a `ctypes` binding, class `Core`, standard library only |
| `python/dbcore_wasm.py`, `web/pycore.js` | the same class `Core` over the WebAssembly module, for Python under Pyodide (the phone page) |
| `python/machine.py` | the simulator's `Machine` on this core: the Python device models behind the external windows |
| `tools/dbrun.rs`, `tools/dbreplay.rs` | the two programs of `Cargo.toml`: run a memory snapshot, replay a recording |

## Build

```
sh native/core/build.sh          # into native/core/build/, or into $DBCORE_OUT
```

It needs `rustc` and `cargo` and downloads nothing (`Cargo.lock` lists the package itself only). The native library is
built for the CPU of the build machine (`DBCORE_RUSTFLAGS=` gives a portable one). The WebAssembly module needs the
`wasm32-unknown-unknown` standard library: installed in the toolchain (`rustup target add wasm32-unknown-unknown`) or in
a sysroot named by `DBCORE_WASM_SYSROOT` (`DBCORE_WASM_LINKER` when the toolchain's own `rust-lld` is not to be used).
Without it the WebAssembly build is skipped with a message.

`python/dbcore.py` finds the library through `DBCORE_LIB` (a file), else `DBCORE_OUT` (a folder), else `build/`. The
launcher uses the core with `--core own`; Myna's tests use it by default.

## Interface

All functions are `extern "C"`; `Core*` is opaque; addresses are physical unless said otherwise. The core maps RAM and
external windows (`dbc_map_ram`, `dbc_map_ext`; the host's read and write callbacks through `dbc_set_ext`, or imported as
`dbc_ext_read` / `dbc_ext_write` from module `env` in the WebAssembly build), runs in slices of instructions with the
interrupt inputs, entry hooks and a stop request (`dbc_run`, `dbc_run_slices`, `dbc_set_irq`, `dbc_add_hook`,
`dbc_request_stop`), gives the registers and memory (`dbc_reg`, `dbc_mem_read`, ...) and saves and loads its whole
state. `src/ffi.rs` lists every function with its contract.

## Licence

MIT (`LICENSE` at the top of the tree).

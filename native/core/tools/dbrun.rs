// dbrun SNAPSHOT INSTRUCTIONS [REPEATS]: load a snapshot into the core (no external windows: every address is memory), run,
// and print one JSON line per repeat: instructions done, stop reason, seconds, million instructions per second, events,
// table walks and r0-r15 + CPSR. For speed measurements and for comparing two builds of the core.
// SPDX-License-Identifier: MIT

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() < 3 { eprintln!("usage: dbrun SNAPSHOT INSTRUCTIONS [REPEATS]"); std::process::exit(2); }
    let data = std::fs::read(&a[1]).expect("snapshot file");
    let n: u64 = a[2].parse::<f64>().expect("instruction count") as u64;
    let reps: usize = a.get(3).map(|x| x.parse().expect("repeats")).unwrap_or(1);
    for _ in 0..reps {
        let mut c = dbcore::Cpu::new();
        if !c.load(&data) { eprintln!("not a snapshot: {}", a[1]); std::process::exit(1); }
        let t = std::time::Instant::now();
        let done = c.run(n);
        let dt = t.elapsed().as_secs_f64();
        let regs: Vec<String> = (0..17).map(|i| format!("{:08x}", c.reg(i))).collect();
        println!("{{\"done\": {}, \"stop\": {}, \"secs\": {:.4}, \"mips\": {:.1}, \"events\": {}, \"walks\": {}, \"regs\": \"{}\"}}",
            done, c.stop_reason(), dt, done as f64 / dt / 1e6, c.events().len(), c.walks, regs.join(" "));
    }
}

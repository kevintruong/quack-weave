//! Direct embedded RelateDB client for the provider comparison benchmark.
use relate::{Database, Value};
use serde_json::json;
use std::{env, error::Error, io, io::BufRead, mem::MaybeUninit, time::Instant};

fn usage() -> io::Result<libc::rusage> {
    let mut usage = MaybeUninit::uninit();
    // getrusage initializes its output on success.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { usage.assume_init() })
}

fn cpu_ms(usage: &libc::rusage) -> f64 {
    [usage.ru_utime, usage.ru_stime]
        .iter()
        .map(|t| t.tv_sec as f64 * 1000.0 + t.tv_usec as f64 / 1000.0)
        .sum()
}

fn main() -> Result<(), Box<dyn Error>> {
    let path = env::args().nth(1).ok_or("expected a frozen .rl path")?;
    let start = Instant::now();
    let database = Database::open_read_only(&path)?;
    let mut connection = database.connect()?;
    println!(
        "{}",
        json!({"open_ms": start.elapsed().as_secs_f64() * 1000.0})
    );
    for line in io::stdin().lock().lines() {
        let statement: String = serde_json::from_str(&line?)?;
        let before = usage()?;
        let start = Instant::now();
        let result = connection.query(&statement)?;
        if result.header.columns.as_slice() != ["id"] {
            return Err("standalone case must return one id column".into());
        }
        let ids: Vec<i64> = result
            .rows
            .iter()
            .map(|row| match row.as_slice() {
                [Value::Int(id)] => Ok(*id),
                _ => Err("standalone case returned a non-integer id"),
            })
            .collect::<Result<_, _>>()?;
        let wall_ms = start.elapsed().as_secs_f64() * 1000.0;
        let after = usage()?;
        // JSON transport and oracle verification lie outside the timed region.
        println!(
            "{}",
            json!({"wall_ms": wall_ms, "cpu_ms": cpu_ms(&after) - cpu_ms(&before),
                              "ids": ids})
        );
    }
    // The tracker targets the macOS arm64 release. Darwin reports bytes.
    println!(
        "{}",
        json!({"peak_rss_mib": usage()?.ru_maxrss as f64 / 1048576.0})
    );
    Ok(())
}

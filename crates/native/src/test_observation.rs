use std::cell::Cell;
use std::fmt::Write;

#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum Fault {
    ArrowAfterBatch,
    Timeout,
    Execution,
}

#[derive(Clone, Copy)]
struct Invocation {
    case_id: &'static str,
    invocation_id: &'static str,
    sequence: usize,
    fault: Option<Fault>,
}

thread_local! {
    static ACTIVE: Cell<Option<Invocation>> = const { Cell::new(None) };
}

pub(crate) fn capture(
    case_id: &'static str,
    invocation_id: &'static str,
    fault: Option<Fault>,
    run: impl FnOnce(),
) {
    assert!(
        ACTIVE
            .replace(Some(Invocation {
                case_id,
                invocation_id,
                sequence: 0,
                fault
            }))
            .is_none(),
        "observation scopes cannot overlap"
    );
    // The Rust harness writes its test name on an unfinished line under --nocapture.
    println!();
    event("start", "ok", "");
    run();
    event("end", "ok", "");
    ACTIVE.set(None);
}

pub(crate) fn fault() -> Option<Fault> {
    ACTIVE.get().and_then(|invocation| invocation.fault)
}

pub(crate) fn event(name: &str, outcome: &str, value: &str) {
    ACTIVE.with(|active| {
        let Some(mut invocation) = active.get() else {
            return;
        };
        assert!(!value.bytes().any(|b| matches!(b, b'\t' | b'\r' | b'\n')));
        println!(
            "QW_OBSERVATION\t1\t{}\t{}\t{}\t{name}\t{outcome}\t{value}",
            invocation.case_id, invocation.invocation_id, invocation.sequence
        );
        invocation.sequence += 1;
        active.set(Some(invocation));
    });
}

pub(crate) fn hex(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut output, "{byte:02x}").unwrap();
    }
    output
}

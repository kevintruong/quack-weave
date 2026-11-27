"""Attach provider-reported phase timings to verified diagnostic submissions."""
import math
import time


def ns():
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC)


def check_uninstrumented(stderr):
    if any(line.startswith(("QW_PHASE ", "QW_RELATE_PHASE ")) for line in stderr.splitlines()):
        raise ValueError("Use an uninstrumented extension for release latency measurements")


def attach_trace(samples, stderr, provider="ladybug"):
    prefix = "QW_RELATE_PHASE " if provider == "relate" else "QW_PHASE "
    events = [line.split() for line in stderr.splitlines() if line.startswith(prefix)]
    if len(events) != len(samples):
        raise ValueError(f"Expected one native execution per submission, got {len(events)} for {len(samples)}")
    for sample, event in zip(samples, events):
        if provider == "relate":
            parse, plan, engine = map(float, event[1:])
            if not all(math.isfinite(t) and t >= 0 for t in (parse, plan, engine)):
                raise ValueError("Invalid RelateDB query summary")
            sample.update(parse_ms=parse, plan_ms=plan, engine_ms=engine)
            continue
        _, start, end, compiling, engine = event
        t0, t1 = int(start), int(end)
        compiling, engine = float(compiling), float(engine)
        if not sample["start_ns"] <= t0 <= t1 <= sample["end_ns"]:
            raise ValueError("Native execution falls outside the client call")
        if not all(math.isfinite(value) and value >= 0 for value in (compiling, engine)):
            raise ValueError("Invalid Ladybug query summary")
        sample.update(before_native_ms=(t0-sample["start_ns"])/1e6, native_call_ms=(t1-t0)/1e6,
                      after_native_ms=(sample["end_ns"]-t1)/1e6, compile_ms=compiling, engine_ms=engine)

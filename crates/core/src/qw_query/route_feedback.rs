//! Shadow ranking of completed graph scans within a single registration.
use std::{sync::Mutex, time::Duration};

use duckdb_neo::{
    DuckDBType, FromValue, Result, ToValue,
    connection::{Context, SettingScope},
    custom_option::{CustomOptionBuilder, CustomOptionCallbacks},
    error::Error,
    extension::Extension,
    log::{Log, LogLevel},
    value::Value,
};

const OPTION: &str = "qw_graph_route_feedback";
const LOG_TYPE: &str = "QuackWeaveGraphFeedback";

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Mode {
    Off,
    Shadow,
    HostSample,
}

impl Mode {
    fn parse(value: &str) -> Result<Self> {
        match value {
            "off" => Ok(Self::Off),
            "shadow" => Ok(Self::Shadow),
            "host_sample" => Ok(Self::HostSample),
            _ => Err(Error::invalid_input(
                "QW_CONFIG: qw_graph_route_feedback accepts off, shadow, or host_sample",
            )),
        }
    }

    pub(super) fn read(context: &Context) -> Result<Self> {
        let (value, _) = context.config()?.get_value(OPTION)?;
        Self::parse(&String::from_value(&value)?.unwrap_or_default())
    }
}

struct FeedbackOption;

impl CustomOptionCallbacks for FeedbackOption {
    fn update(
        &self,
        context: &Context,
        value: Value,
        scope: SettingScope,
        is_reset: bool,
    ) -> Result<Value> {
        if !matches!(scope, SettingScope::Session) {
            return Err(Error::invalid_input(
                "QW_CONFIG: Use SET SESSION for qw_graph_route_feedback",
            ));
        }
        if is_reset {
            return "off".to_owned().value(context);
        }
        Mode::parse(&String::from_value(&value)?.unwrap_or_default())?;
        Ok(value)
    }
}

pub(super) fn register(extension: &Extension) -> Result<()> {
    CustomOptionBuilder::new(
        OPTION,
        "Compare completed graph routes in shadow mode, or collect an explicit host sample",
        String::logical_type(extension)?,
        FeedbackOption,
    )
    .default_value("off".to_owned().value(extension)?)
    .default_scope(SettingScope::Session)
    .register(extension)
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct Shape {
    pub(super) base: String,
    pub(super) output_slots: Vec<usize>,
    pub(super) key_slot: usize,
    pub(super) exact_keys: Vec<i64>,
    /// The bound ORDER BY slot and limit, independent of the session's top-k setting.
    pub(super) top: Option<(usize, u64)>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Route {
    Exact,
    Host,
    Bounded,
}

impl Route {
    const ALL: [Self; 3] = [Self::Exact, Self::Host, Self::Bounded];

    fn sample_name(self) -> &'static str {
        match self {
            Self::Exact => "sample_exact",
            Self::Host => "sample_host",
            Self::Bounded => "sample_bounded",
        }
    }

    fn comparison_name(self) -> &'static str {
        match self {
            Self::Exact => "comparison_ready_exact",
            Self::Host => "comparison_ready_host",
            Self::Bounded => "comparison_ready_bounded",
        }
    }
}

#[derive(Debug)]
struct Entry {
    shape: Shape,
    times: [Option<Duration>; 3],
}

/// Keep one comparable shape per snapshot. Concurrent scans only hold this
/// lock while publishing a finished sample, and replacement gets a fresh cache.
#[derive(Debug, Default)]
pub(super) struct Feedback(Mutex<Option<Entry>>);

impl Feedback {
    fn record(&self, shape: Shape, route: Route, elapsed: Duration) -> Option<Route> {
        let mut cached = self.0.lock().ok()?;
        if cached.as_ref().is_none_or(|entry| entry.shape != shape) {
            *cached = Some(Entry {
                shape,
                times: [None; 3],
            });
        }
        let entry = cached.as_mut()?;
        entry.times[route as usize] = Some(elapsed);
        let incumbent = entry.times[Route::Exact as usize]?;
        let mut best = Route::Exact;
        let mut best_time = incumbent;
        let mut has_alternative = false;
        for candidate in Route::ALL.into_iter().skip(1) {
            if let Some(time) = entry.times[candidate as usize] {
                has_alternative = true;
                if time < best_time {
                    best = candidate;
                    best_time = time;
                }
            }
        }
        has_alternative.then_some(best)
    }
}

pub(super) struct Observation {
    pub(super) shape: Shape,
    pub(super) route: Route,
    pub(super) mode: Mode,
    pub(super) elapsed: Duration,
}

impl Observation {
    pub(super) fn finish(self, feedback: &Feedback, context: &Context) {
        let comparison = feedback.record(self.shape, self.route, self.elapsed);
        let _ = Log::log_on_context(context, LogLevel::Info, self.route.sample_name(), LOG_TYPE);
        if self.mode == Mode::Shadow
            && let Some(choice) = comparison
        {
            let _ =
                Log::log_on_context(context, LogLevel::Info, choice.comparison_name(), LOG_TYPE);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shape(key: i64, top: Option<(usize, u64)>) -> Shape {
        Shape {
            base: "MATCH (a:airport) RETURN a.k AS qw_col0".to_owned(),
            output_slots: vec![0],
            key_slot: 0,
            exact_keys: vec![key],
            top,
        }
    }

    #[test]
    fn compares_only_matching_completed_samples() {
        let old = Feedback::default();
        let exact = Duration::from_millis(8);
        let host = Duration::from_millis(4);
        let bounded = Duration::from_millis(2);
        assert_eq!(old.record(shape(10, None), Route::Exact, exact), None);
        assert_eq!(
            old.record(shape(10, None), Route::Host, host),
            Some(Route::Host)
        );
        assert_eq!(
            old.record(shape(10, Some((0, 1))), Route::Bounded, bounded),
            None
        );
        assert_eq!(
            old.record(shape(10, Some((0, 1))), Route::Exact, exact),
            Some(Route::Bounded)
        );
        assert_eq!(
            old.record(shape(20, Some((0, 1))), Route::Exact, exact),
            None
        );
        let replacement = Feedback::default();
        assert_eq!(
            replacement.record(shape(10, None), Route::Exact, exact),
            None
        );
    }
}

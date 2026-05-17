//! Pattern matchers for policy rules.
//!
//! Ports `matchers.py`. Three families:
//!
//! - **target_matches** — glob OR regex over a target string (file path,
//!   URL, command head).
//! - **command_matches** — same shape against the full Bash command.
//! - **time_window_matches** — temporal gating.

use chrono::{DateTime, Datelike, Local, TimeZone, Timelike};
use chrono_tz::Tz;
use regex::Regex;

use super::types::TimeWindow;

/// Match `target` against a list of patterns. If `is_regex` is `true`,
/// patterns are treated as regexes (anchor-free); otherwise as Unix
/// globs via `globset`.
pub fn target_matches(target: &str, patterns: &[String], is_regex: bool) -> bool {
    if is_regex {
        for p in patterns {
            // Same semantics as Python `re.search` — find pattern anywhere
            // in the target.
            if let Ok(r) = Regex::new(p) {
                if r.is_match(target) {
                    return true;
                }
            }
        }
        false
    } else {
        // Glob. Python's `fnmatch.fnmatch` is shell-style with **
        // expansion via the convention of `**/`. We use the `globset`
        // crate, which supports `*`, `?`, `[abc]`, and `**` for any
        // sequence including `/`.
        for p in patterns {
            let builder = globset::GlobBuilder::new(p)
                .literal_separator(false) // matches Python's permissive default
                .build();
            if let Ok(g) = builder {
                if g.compile_matcher().is_match(target) {
                    return true;
                }
            }
        }
        false
    }
}

/// Match `full_command` against a list of patterns. Same shape as
/// `target_matches` but conventionally used over the entire Bash
/// command string instead of just the first token.
pub fn command_matches(full_command: &str, patterns: &[String], is_regex: bool) -> bool {
    target_matches(full_command, patterns, is_regex)
}

/// Negative match: returns `true` if `full_command` contains **none** of
/// the `must_not_contain` strings (so the rule should fire), or `false`
/// if any of them appear (so the rule should be skipped).
pub fn command_lacks(full_command: &str, must_not_contain: &[String]) -> bool {
    must_not_contain.iter().all(|s| !full_command.contains(s))
}

/// Returns `true` if `now` falls inside the time window.
///
/// Default behavior when both `allowed_hours` and `allowed_days` are
/// `None`: `true` (the window doesn't gate at all).
pub fn time_window_matches<Tz1: TimeZone>(
    window: &TimeWindow,
    now: DateTime<Tz1>,
) -> bool {
    // If both fields are None, the window is effectively open.
    if window.allowed_hours.is_none() && window.allowed_days.is_none() {
        return true;
    }

    // Convert `now` into the window's timezone (or use it as-is if no
    // timezone was specified).
    let local: DateTime<chrono::FixedOffset> = if let Some(tz_name) = &window.timezone {
        match tz_name.parse::<Tz>() {
            Ok(tz) => now.with_timezone(&tz).fixed_offset(),
            Err(_) => now.fixed_offset(),
        }
    } else {
        now.fixed_offset()
    };

    if let Some((start, end)) = window.allowed_hours {
        let h = local.hour() as u8;
        let in_hours = if start <= end {
            h >= start && h <= end
        } else {
            // Wrap-around window (e.g. 22..2 = 10pm to 2am)
            h >= start || h <= end
        };
        if !in_hours {
            return false;
        }
    }
    if let Some(days) = &window.allowed_days {
        // chrono's `weekday().num_days_from_sunday()` returns 0=Sunday … 6=Saturday
        let dow = local.weekday().num_days_from_sunday() as u8;
        if !days.contains(&dow) {
            return false;
        }
    }
    true
}

/// Convenience for callers in non-timezone-aware contexts: use system
/// local time.
pub fn time_window_matches_now(window: &TimeWindow) -> bool {
    time_window_matches(window, Local::now())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn glob_target_match() {
        let patterns = vec!["**/.env".into(), "**/.aws/credentials".into()];
        assert!(target_matches("/home/u/.env", &patterns, false));
        assert!(target_matches("project/.env", &patterns, false));
        assert!(target_matches("/home/u/.aws/credentials", &patterns, false));
        assert!(!target_matches("/home/u/.bashrc", &patterns, false));
    }

    #[test]
    fn regex_target_match() {
        let patterns = vec![r"rm\s+-".into(), r"mkfs\.".into()];
        assert!(target_matches("rm -rf /tmp/foo", &patterns, true));
        assert!(target_matches("rm -f file", &patterns, true));
        assert!(target_matches("mkfs.ext4 /dev/sda", &patterns, true));
        assert!(!target_matches("rm foo", &patterns, true)); // no flag, no match
        assert!(!target_matches("cat /etc/hostname", &patterns, true));
    }

    #[test]
    fn command_lacks_check() {
        let patterns = vec!["GITHUB_PAT".into(), "@github.com".into()];
        assert!(command_lacks("git push origin main", &patterns));
        assert!(!command_lacks("git push https://x:$GITHUB_PAT@github.com/r.git", &patterns));
        assert!(!command_lacks("git push https://x:tok@github.com/r.git", &patterns));
    }

    #[test]
    fn time_window_open_by_default() {
        assert!(time_window_matches_now(&TimeWindow::default()));
    }

    #[test]
    fn time_window_hours_inclusive() {
        let mut win = TimeWindow::default();
        win.allowed_hours = Some((9, 17));
        // 12:00 noon
        let now: DateTime<chrono::Utc> = chrono::Utc.with_ymd_and_hms(2026, 5, 16, 12, 0, 0).unwrap();
        assert!(time_window_matches(&win, now));
        // 8am
        let too_early = chrono::Utc.with_ymd_and_hms(2026, 5, 16, 8, 0, 0).unwrap();
        assert!(!time_window_matches(&win, too_early));
    }

    #[test]
    fn time_window_days_filter() {
        let mut win = TimeWindow::default();
        win.allowed_days = Some(vec![1, 2, 3, 4, 5]); // weekdays
        let saturday = chrono::Utc.with_ymd_and_hms(2026, 5, 16, 12, 0, 0).unwrap(); // 2026-05-16 is a Saturday
        assert!(!time_window_matches(&win, saturday));
        let monday = chrono::Utc.with_ymd_and_hms(2026, 5, 18, 12, 0, 0).unwrap();
        assert!(time_window_matches(&win, monday));
    }
}

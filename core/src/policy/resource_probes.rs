//! Live readings for gated resources (#1548): the community's body sense.
//!
//! THE GATE MUST NEVER WAIT LONG ON A PROBE. A probe of `/mnt/c` on WSL goes through the Windows
//! drive bridge, and that bridge has hung for days before (cbp, 2026-11-08: interop relays stuck
//! in `accept` for 46 hours). So every reading runs on its own thread, a call waits at most
//! [`DEADLINE`] for the readings it needs, and a reading that misses the deadline is `None`
//! (unknown; what that means is the resource's `on_unknown`). A probe already in flight is not
//! started again, so a hung bridge costs one parked thread, not one per gate call.
//!
//! CONCURRENT CALLS SHARE ONE READING (codex and kimi-code on #1551). A call that finds a probe in
//! flight WAITS for that reading, within its own deadline, instead of reading unknown at once;
//! otherwise a second act arriving a millisecond after the first would pass an enforced floor on
//! "unknown" while the first act's reading came back short.
//!
//! Readings are cached briefly. Many acts arrive within a second of each other and the machine's
//! free disk does not change meaningfully in that time.

use std::collections::HashMap;
use std::sync::{Condvar, Mutex, OnceLock};
use std::time::{Duration, Instant};

use super::resources::{Probe, Sampler};

/// How long a reading is reused.
const CACHE_FOR: Duration = Duration::from_secs(5);
/// How long the gate waits for a reading before treating it as unknown.
pub const DEADLINE: Duration = Duration::from_millis(400);

/// A probe in flight longer than this is reported as stuck: a health reading in its own right
/// (cbp, 2026-11-08: the drive bridge hung for 46 hours and nothing said so).
pub const STUCK_AFTER: Duration = Duration::from_secs(120);

#[derive(Default)]
struct Cache {
    readings: HashMap<Probe, (Instant, Option<u64>)>,
    /// Probes whose thread has not returned, with when it started.
    in_flight: HashMap<Probe, Instant>,
}

/// Can this platform read `probe` at all? A probe it cannot read is `unsupported`, which is
/// recorded distinctly from a reading that timed out, and refused when law is written, so a
/// declaration is never silently inert (a macOS seat has no `/proc`).
pub fn supported(probe: &Probe) -> bool {
    match probe {
        Probe::DiskFree { .. } | Probe::DiskFreePermille { .. } => cfg!(unix),
        Probe::MemAvailable | Probe::ProcessRunning { .. } => cfg!(target_os = "linux"),
    }
}

/// Probes in flight for at least `older_than`, with how long. A hung filesystem or drive bridge
/// shows up here long before anything else notices.
pub fn stuck_probes(older_than: Duration) -> Vec<(Probe, Duration)> {
    let c = cache().lock().unwrap_or_else(|p| p.into_inner());
    c.in_flight
        .iter()
        .filter_map(|(p, at)| {
            let age = at.elapsed();
            (age >= older_than).then(|| (p.clone(), age))
        })
        .collect()
}

fn cache() -> &'static Mutex<Cache> {
    static CACHE: OnceLock<Mutex<Cache>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(Cache::default()))
}

/// Signalled whenever a probe thread stores a reading.
fn landed() -> &'static Condvar {
    static LANDED: OnceLock<Condvar> = OnceLock::new();
    LANDED.get_or_init(Condvar::new)
}

fn fresh(c: &Cache, p: &Probe) -> Option<Option<u64>> {
    c.readings
        .get(p)
        .filter(|(at, _)| at.elapsed() < CACHE_FOR)
        .map(|(_, v)| *v)
}

/// The daemon's sampler: reads the live machine.
pub struct LiveSampler;

impl LiveSampler {
    /// Read every probe within one [`DEADLINE`]. Probes run concurrently, and a probe another
    /// call already started is waited for rather than skipped.
    pub fn sample_all(probes: &[Probe]) -> HashMap<Probe, Option<u64>> {
        let deadline = Instant::now() + DEADLINE;
        let mut c = cache().lock().unwrap_or_else(|p| p.into_inner());
        for p in probes {
            if !supported(p) || fresh(&c, p).is_some() || c.in_flight.contains_key(p) {
                continue;
            }
            c.in_flight.insert(p.clone(), Instant::now());
            let probe = p.clone();
            std::thread::spawn(move || {
                let v = read(&probe);
                let mut c = cache().lock().unwrap_or_else(|e| e.into_inner());
                c.in_flight.remove(&probe);
                c.readings.insert(probe, (Instant::now(), v));
                drop(c);
                landed().notify_all();
            });
        }
        loop {
            let waiting = probes
                .iter()
                .any(|p| supported(p) && fresh(&c, p).is_none());
            let now = Instant::now();
            if !waiting || now >= deadline {
                break;
            }
            c = landed()
                .wait_timeout(c, deadline - now)
                .map(|(g, _)| g)
                .unwrap_or_else(|e| e.into_inner().0);
        }
        probes
            .iter()
            .map(|p| {
                let v = if supported(p) {
                    fresh(&c, p).flatten()
                } else {
                    None
                };
                (p.clone(), v)
            })
            .collect()
    }
}

impl Sampler for LiveSampler {
    fn sample(&self, probe: &Probe) -> Option<u64> {
        Self::sample_all(std::slice::from_ref(probe))
            .get(probe)
            .copied()
            .flatten()
    }
}

/// Test seam: a probe that answers `value` after `delay`, so overlapping calls and slow probes
/// can be exercised deterministically.
#[cfg(test)]
fn scripted() -> &'static Mutex<HashMap<Probe, (Duration, Option<u64>)>> {
    static S: OnceLock<Mutex<HashMap<Probe, (Duration, Option<u64>)>>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Take one reading, blocking. Only ever called on a probe thread.
fn read(probe: &Probe) -> Option<u64> {
    #[cfg(test)]
    {
        let script = scripted().lock().unwrap().get(probe).copied();
        if let Some((delay, value)) = script {
            std::thread::sleep(delay);
            return value;
        }
    }
    match probe {
        Probe::DiskFree { path } => disk_free_mb(path),
        Probe::DiskFreePermille { path } => disk_free_permille(path),
        Probe::MemAvailable => mem_available_mb(),
        Probe::ProcessRunning { pattern } => processes_matching(pattern),
    }
}

#[cfg(unix)]
fn disk_free_mb(path: &str) -> Option<u64> {
    let st = statvfs(path)?;
    #[allow(clippy::unnecessary_cast)]
    let bytes = (st.f_bavail as u128) * (st.f_frsize as u128);
    u64::try_from(bytes / (1024 * 1024)).ok()
}

#[cfg(not(unix))]
fn disk_free_mb(_path: &str) -> Option<u64> {
    None
}

#[cfg(unix)]
fn disk_free_permille(path: &str) -> Option<u64> {
    let st = statvfs(path)?;
    #[allow(clippy::unnecessary_cast)]
    let (avail, total) = (st.f_bavail as u128, st.f_blocks as u128);
    if total == 0 {
        return None;
    }
    u64::try_from(avail * 1000 / total).ok()
}

#[cfg(not(unix))]
fn disk_free_permille(_path: &str) -> Option<u64> {
    None
}

#[cfg(unix)]
fn statvfs(path: &str) -> Option<libc::statvfs> {
    let c = std::ffi::CString::new(path).ok()?;
    // SAFETY: `c` is a valid NUL-terminated path; `st` is a plain-old-data out parameter that
    // statvfs fills on success, and it is returned only when the call returned 0.
    let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
    let rc = unsafe { libc::statvfs(c.as_ptr(), &mut st) };
    (rc == 0).then_some(st)
}

/// `MemAvailable` in MB. Linux only; elsewhere unknown.
fn mem_available_mb() -> Option<u64> {
    let text = std::fs::read_to_string("/proc/meminfo").ok()?;
    parse_mem_available_kb(&text).map(|kb| kb / 1024)
}

fn parse_mem_available_kb(meminfo: &str) -> Option<u64> {
    meminfo
        .lines()
        .find_map(|l| l.strip_prefix("MemAvailable:"))
        .and_then(|rest| rest.split_whitespace().next())
        .and_then(|n| n.parse().ok())
}

/// Processes (other than this one) whose command line contains `pattern`. Linux only.
fn processes_matching(pattern: &str) -> Option<u64> {
    let me = std::process::id().to_string();
    let entries = std::fs::read_dir("/proc").ok()?;
    let mut n = 0u64;
    for e in entries.flatten() {
        let name = e.file_name();
        let Some(pid) = name.to_str() else { continue };
        if pid == me || !pid.bytes().all(|b| b.is_ascii_digit()) {
            continue;
        }
        let Ok(raw) = std::fs::read(e.path().join("cmdline")) else {
            continue;
        };
        let cmd: String = String::from_utf8_lossy(&raw).replace('\0', " ");
        if cmd.contains(pattern) {
            n += 1;
        }
    }
    Some(n)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mem_available_is_read_from_meminfo() {
        let text =
            "MemTotal:       24610000 kB\nMemFree:  4400000 kB\nMemAvailable:   20230000 kB\n";
        assert_eq!(parse_mem_available_kb(text), Some(20_230_000));
        assert_eq!(parse_mem_available_kb("MemTotal: 1 kB\n"), None);
    }

    #[cfg(unix)]
    #[test]
    fn the_live_sampler_reads_this_machine() {
        let disk = Probe::DiskFree { path: "/".into() };
        let missing = Probe::DiskFree {
            path: "/no/such/path/for/hestia".into(),
        };
        let r = LiveSampler::sample_all(&[disk.clone(), missing.clone(), Probe::MemAvailable]);
        assert!(r[&disk].is_some(), "statvfs of / should read");
        assert_eq!(r[&missing], None, "an unreadable path is unknown, not zero");
        // A second call inside the cache window answers from the cache.
        let again = LiveSampler::sample_all(std::slice::from_ref(&disk));
        assert_eq!(again[&disk], r[&disk]);
    }

    #[test]
    fn support_is_stated_per_platform() {
        let disk = Probe::DiskFree { path: "/".into() };
        assert_eq!(supported(&disk), cfg!(unix));
        assert_eq!(supported(&Probe::MemAvailable), cfg!(target_os = "linux"));
    }

    #[test]
    fn an_overlapping_call_waits_for_the_reading_in_flight() {
        // Call A starts a 150 ms reading that comes back SHORT; call B arrives 30 ms later.
        // B must see A's reading, not "unknown" (codex/kimi-code finding 2 on #1551).
        let probe = Probe::ProcessRunning {
            pattern: "overlap-test-probe-41aa".into(),
        };
        scripted()
            .lock()
            .unwrap()
            .insert(probe.clone(), (Duration::from_millis(150), Some(7)));
        let a = {
            let p = probe.clone();
            std::thread::spawn(move || LiveSampler::sample_all(std::slice::from_ref(&p)))
        };
        std::thread::sleep(Duration::from_millis(30));
        let b = LiveSampler::sample_all(std::slice::from_ref(&probe));
        let a = a.join().unwrap();
        assert_eq!(a[&probe], Some(7));
        assert_eq!(
            b[&probe],
            Some(7),
            "the overlapping call must share the reading"
        );
        scripted().lock().unwrap().remove(&probe);
    }

    #[test]
    fn a_reading_slower_than_the_deadline_is_unknown_and_not_restarted() {
        let probe = Probe::ProcessRunning {
            pattern: "slow-test-probe-93bd".into(),
        };
        scripted()
            .lock()
            .unwrap()
            .insert(probe.clone(), (DEADLINE * 3, Some(1)));
        let started = Instant::now();
        let r = LiveSampler::sample_all(std::slice::from_ref(&probe));
        assert_eq!(r[&probe], None);
        assert!(
            started.elapsed() < DEADLINE * 2,
            "the gate waited past its deadline"
        );
        assert!(cache().lock().unwrap().in_flight.contains_key(&probe));
        scripted().lock().unwrap().remove(&probe);
    }

    #[test]
    fn a_probe_that_never_returns_is_reported_stuck() {
        let probe = Probe::ProcessRunning {
            pattern: "stuck-test-probe-7c1e".into(),
        };
        {
            let mut c = cache().lock().unwrap();
            c.in_flight
                .insert(probe.clone(), Instant::now() - Duration::from_secs(300));
        }
        let stuck = stuck_probes(STUCK_AFTER);
        assert!(
            stuck
                .iter()
                .any(|(p, age)| p == &probe && *age >= STUCK_AFTER)
        );
        // A stuck probe is not started again: it reads unknown.
        assert_eq!(
            LiveSampler::sample_all(std::slice::from_ref(&probe))[&probe],
            None
        );
        cache().lock().unwrap().in_flight.remove(&probe);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn process_count_is_zero_for_a_pattern_nothing_runs() {
        assert!(processes_matching("a-pattern-no-process-has-0d9f").is_some_and(|n| n == 0));
    }
}

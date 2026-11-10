//! Live readings for gated resources (#1548): the community's body sense.
//!
//! THE GATE MUST NEVER WAIT ON A PROBE. A probe of `/mnt/c` on WSL goes through the Windows
//! drive bridge, and that bridge has hung for days before (cbp, 2026-11-08: interop relays stuck
//! in `accept` for 46 hours). So every reading runs on its own thread with a deadline, a reading
//! that misses the deadline is `None` (unknown, which never refuses), and a probe still in flight
//! from an earlier call is not started again: it reads as unknown until it returns, so a hung
//! bridge costs one parked thread, not one per gate call.
//!
//! Readings are cached briefly. Many acts arrive within a second of each other and the machine's
//! free disk does not change meaningfully in that time.

use std::collections::{HashMap, HashSet};
use std::sync::mpsc;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use super::resources::{Probe, Sampler};

/// How long a reading is reused.
const CACHE_FOR: Duration = Duration::from_secs(5);
/// How long the gate waits for a reading before treating it as unknown.
const DEADLINE: Duration = Duration::from_millis(400);

#[derive(Default)]
struct Cache {
    readings: HashMap<Probe, (Instant, Option<u64>)>,
    in_flight: HashSet<Probe>,
}

fn cache() -> &'static Mutex<Cache> {
    static CACHE: OnceLock<Mutex<Cache>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(Cache::default()))
}

/// The daemon's sampler: reads the live machine.
pub struct LiveSampler;

impl LiveSampler {
    /// Read every probe, each within the deadline. Probes run concurrently, so a call costs at
    /// most one deadline however many probes it names.
    pub fn sample_all(probes: &[Probe]) -> HashMap<Probe, Option<u64>> {
        let mut out = HashMap::new();
        let mut pending = Vec::new();
        {
            let mut c = cache().lock().unwrap_or_else(|p| p.into_inner());
            for p in probes {
                if let Some((at, v)) = c.readings.get(p) {
                    if at.elapsed() < CACHE_FOR {
                        out.insert(p.clone(), *v);
                        continue;
                    }
                }
                if c.in_flight.contains(p) {
                    out.insert(p.clone(), None);
                    continue;
                }
                c.in_flight.insert(p.clone());
                pending.push(p.clone());
            }
        }
        let receivers: Vec<(Probe, mpsc::Receiver<Option<u64>>)> = pending
            .into_iter()
            .map(|p| {
                let (tx, rx) = mpsc::channel();
                let probe = p.clone();
                std::thread::spawn(move || {
                    let v = read(&probe);
                    let mut c = cache().lock().unwrap_or_else(|e| e.into_inner());
                    c.in_flight.remove(&probe);
                    c.readings.insert(probe, (Instant::now(), v));
                    let _ = tx.send(v);
                });
                (p, rx)
            })
            .collect();
        let deadline = Instant::now() + DEADLINE;
        for (p, rx) in receivers {
            let left = deadline.saturating_duration_since(Instant::now());
            out.insert(p, rx.recv_timeout(left).ok().flatten());
        }
        out
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

/// Take one reading, blocking. Only ever called on a probe thread.
fn read(probe: &Probe) -> Option<u64> {
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
        let again = LiveSampler::sample_all(&[disk.clone()]);
        assert_eq!(again[&disk], r[&disk]);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn process_count_is_zero_for_a_pattern_nothing_runs() {
        assert!(processes_matching("a-pattern-no-process-has-0d9f").is_some_and(|n| n == 0));
    }
}

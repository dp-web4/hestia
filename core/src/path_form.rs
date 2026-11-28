//! One spelling per path, on POSIX and on Windows (hestia #1743, step 1).
//!
//! The daemon RECORDS a scope grant and the plugin gate ENFORCES it, so the two must agree on
//! what "the same file" means. On POSIX, `state::normalize_scope_path` has done that lexically
//! since #597. On Windows the same file has several spellings: `C:\Users\x`, `C:/Users/x`,
//! `c:\users\x`, `\\?\C:\Users\x`, and, inside Git Bash, `/c/Users/x`. A grant recorded under one
//! spelling and checked under another grants nothing, or worse, a deny written under one spelling
//! misses an act written under another.
//!
//! This module converts every spelling it can prove to one form, and refuses the rest with a
//! reason. Nothing here touches the filesystem. Junctions, symlinks and 8.3 short names
//! (`PROGRA~1`) need the filesystem; the gate's `realpath` handles those, and this conversion runs
//! first, so `realpath` always gets a drive-rooted path.
//!
//! The comparison form on Windows is `C:/Users/x`: drive letter in upper case, `/` separators, the
//! rest in the case it was given. The Python gate already compares in that form, since it runs
//! `os.path.realpath(...).replace("\\", "/")`. Matching is case-insensitive through
//! [`match_key`].
//!
//! The Python mirror is `plugins/_shared/hestia_path_form.py`. Both read the case table in
//! `fixtures/path-form/cases.json`, so neither can change a result without the other's tests
//! failing.

use std::fmt;

/// Which rules give a path its meaning. The caller says which; nothing here infers it from the
/// text, because the same text means different files under different rules.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Dialect {
    /// Linux and macOS. `\` is an ordinary filename character and `/c/x` is a real path.
    Posix,
    /// Native Windows: PowerShell, cmd, the Windows file APIs, an agent's file tools. A path
    /// rooted without a drive (`\x`, `/c/x`) means the CURRENT drive, which this layer cannot know.
    Windows,
    /// Windows, as written in Git Bash (MSYS). `/c/x` is drive C. Other rooted paths (`/tmp`,
    /// `/usr`, `/`) are mounts whose target depends on the Git install.
    GitBash,
}

impl Dialect {
    /// The host's native dialect: [`Dialect::Windows`] on Windows, [`Dialect::Posix`] elsewhere.
    /// Never [`Dialect::GitBash`]: only a caller that knows an act came through Git Bash may say so.
    pub const fn host() -> Self {
        if cfg!(windows) {
            Dialect::Windows
        } else {
            Dialect::Posix
        }
    }

    /// The name used in `fixtures/path-form/cases.json` and by the Python mirror.
    pub fn as_str(self) -> &'static str {
        match self {
            Dialect::Posix => "posix",
            Dialect::Windows => "windows",
            Dialect::GitBash => "gitbash",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "posix" => Some(Dialect::Posix),
            "windows" => Some(Dialect::Windows),
            "gitbash" => Some(Dialect::GitBash),
            _ => None,
        }
    }

    fn is_windows(self) -> bool {
        !matches!(self, Dialect::Posix)
    }
}

/// Why a spelling has no canonical form. Each variant carries a way forward in [`Refusal::reason`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refusal {
    Empty,
    NulByte,
    Relative,
    Tilde,
    /// `C:x` or `C:`: relative to that drive's current directory.
    DriveRelative,
    /// `\x`, or `/x` outside Git Bash: rooted on the current drive.
    CurrentDrive,
    /// `/tmp`, `/usr/...`, `/mnt/c/...`, `/`: a Git Bash mount.
    GitBashMount,
    /// A `:` after the drive, as in `f.txt::$DATA`: an NTFS stream, another name for the file.
    Stream,
    /// `<`, `>`, `"`, `|`, `?`, `*` or a control character: not part of any Windows file name.
    InvalidChar,
    /// `\\server\share`, `\\?\UNC\...`.
    Unc,
    /// `\\.\...`, or `\\?\` followed by something other than a drive.
    DeviceNamespace,
    /// A segment ending in `.` or space under `\\?\`, where it is literal rather than stripped.
    VerbatimTrailing,
    /// A name ending in `.` or space that is not the last name in the path, or a last name made
    /// only of dots and spaces. Win32 strips trailing dots and spaces from the last name only.
    TrailingDotSpace,
}

impl Refusal {
    /// The stable code used in the fixture and by the Python mirror.
    pub fn code(self) -> &'static str {
        match self {
            Refusal::Empty => "empty",
            Refusal::NulByte => "nul_byte",
            Refusal::Relative => "relative",
            Refusal::Tilde => "tilde",
            Refusal::DriveRelative => "drive_relative",
            Refusal::CurrentDrive => "current_drive",
            Refusal::GitBashMount => "gitbash_mount",
            Refusal::Stream => "stream",
            Refusal::InvalidChar => "invalid_char",
            Refusal::Unc => "unc",
            Refusal::DeviceNamespace => "device_namespace",
            Refusal::VerbatimTrailing => "verbatim_trailing",
            Refusal::TrailingDotSpace => "trailing_dot_space",
        }
    }

    pub fn reason(self) -> &'static str {
        match self {
            Refusal::Empty => "the path is empty",
            Refusal::NulByte => "the path contains a NUL byte",
            Refusal::Relative => {
                "the path is relative; its meaning depends on a working directory the daemon and \
                 the gate may not share. Name it from the root (C:/... on Windows, /... elsewhere)"
            }
            Refusal::Tilde => {
                "the path starts with ~; expand the home directory before naming the path"
            }
            Refusal::DriveRelative => {
                "C:x and C: are relative to that drive's current directory; write C:/x"
            }
            Refusal::CurrentDrive => {
                "a path rooted without a drive letter means the current drive, which differs by \
                 process; name the drive (C:/...)"
            }
            Refusal::GitBashMount => {
                "a Git Bash mount (/tmp, /usr, /mnt/..., /) points wherever that Git install puts \
                 it; resolve it with `cygpath -w` and name the Windows path"
            }
            Refusal::Stream => {
                "a ':' after the drive names an NTFS stream, another name for the same file; name \
                 the file itself"
            }
            Refusal::InvalidChar => {
                "the path contains a character no Windows file name can hold (< > \" | ? * or a \
                 control character); a glob is not a path"
            }
            Refusal::Unc => {
                "network (UNC) paths are not supported yet; name a local drive path (hestia #1743)"
            }
            Refusal::DeviceNamespace => {
                "device-namespace paths (\\\\.\\, \\\\?\\ without a drive) are not file paths the \
                 gate can scope"
            }
            Refusal::VerbatimTrailing => {
                "under \\\\?\\ a trailing '.' or space is part of the name, so it names a different \
                 file from the one without it; remove it or drop the \\\\?\\ prefix"
            }
            Refusal::TrailingDotSpace => {
                "a folder name ending in '.' or a space, or a name made only of dots and spaces, \
                 can name a different folder from the one without them: Windows strips them from \
                 the last name in a path only. Name each folder as it appears on disk"
            }
        }
    }
}

impl fmt::Display for Refusal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.reason())
    }
}

impl std::error::Error for Refusal {}

/// The one absolute spelling of `raw` under `dialect`, or why there is none.
///
/// A grant suffix such as `/**` is the caller's to strip first: under the Windows dialects `*` is
/// refused, because no Windows file name holds it.
pub fn canonical(raw: &str, dialect: Dialect) -> Result<String, Refusal> {
    if raw.contains('\0') {
        return Err(Refusal::NulByte);
    }
    let raw = trim_input(raw, dialect);
    if raw.is_empty() {
        return Err(Refusal::Empty);
    }
    match dialect {
        Dialect::Posix => canonical_posix(raw),
        Dialect::Windows | Dialect::GitBash => canonical_windows(raw, dialect),
    }
}

/// What surrounding whitespace is dropped before conversion.
///
/// - POSIX: Unicode whitespace at both ends, as `normalize_scope_path` does.
/// - Windows: ASCII whitespace only. Win32 keeps every other character, so `file\u{3000}` names
///   a different file from `file`. Under `\\?\` the end is never trimmed: a verbatim name may end
///   in a space, which then reaches the segment rules and is refused (Nova, #1745), instead of
///   being trimmed into the name without it.
fn trim_input(raw: &str, dialect: Dialect) -> &str {
    if !dialect.is_windows() {
        return raw.trim();
    }
    let s = raw.trim_start_matches(|c: char| c.is_ascii_whitespace());
    if strip_prefix_either(s, "\\\\?\\").is_some() {
        s
    } else {
        s.trim_end_matches(|c: char| c.is_ascii_whitespace())
    }
}

fn canonical_posix(raw: &str) -> Result<String, Refusal> {
    if raw.starts_with('~') {
        return Err(Refusal::Tilde);
    }
    let Some(rest) = raw.strip_prefix('/') else {
        return Err(Refusal::Relative);
    };
    let mut out: Vec<&str> = Vec::new();
    for seg in rest.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                out.pop();
            }
            s => out.push(s),
        }
    }
    Ok(format!("/{}", out.join("/")))
}

fn canonical_windows(raw: &str, dialect: Dialect) -> Result<String, Refusal> {
    // `\\?\` (verbatim) and `\\.\` (device) prefixes, in either separator.
    let mut verbatim = false;
    let mut s: &str = raw;
    if let Some(rest) = strip_prefix_either(s, "\\\\?\\") {
        if rest.get(..3).is_some_and(|u| u.eq_ignore_ascii_case("UNC"))
            && rest.as_bytes().get(3).copied().is_some_and(is_sep)
        {
            return Err(Refusal::Unc);
        }
        if !starts_with_drive(rest) {
            return Err(Refusal::DeviceNamespace);
        }
        verbatim = true;
        s = rest;
    } else if strip_prefix_either(s, "\\\\.\\").is_some() {
        return Err(Refusal::DeviceNamespace);
    }

    let rooted_by_backslash = s.starts_with('\\');
    let s = s.replace('\\', "/");
    if s.starts_with("//") {
        return Err(Refusal::Unc);
    }
    if s.starts_with('~') {
        return Err(Refusal::Tilde);
    }

    let (drive, rest): (char, &str) = if starts_with_drive(&s) {
        let b = s.as_bytes();
        if b.len() == 2 || b[2] != b'/' {
            return Err(Refusal::DriveRelative);
        }
        ((b[0] as char).to_ascii_uppercase(), &s[3..])
    } else if let Some(after) = s.strip_prefix('/') {
        if rooted_by_backslash || dialect == Dialect::Windows {
            return Err(Refusal::CurrentDrive);
        }
        // Git Bash: `/c` and `/c/...` are drive C; every other rooted path is a mount.
        let (first, remainder) = match after.split_once('/') {
            Some((f, r)) => (f, r),
            None => (after, ""),
        };
        let fb = first.as_bytes();
        if fb.len() == 1 && fb[0].is_ascii_alphabetic() {
            ((fb[0] as char).to_ascii_uppercase(), remainder)
        } else {
            return Err(Refusal::GitBashMount);
        }
    } else {
        return Err(Refusal::Relative);
    };

    // Pass 1: `.` and `..` resolve first, as Win32 does, so a name `..` removes is never opened.
    let mut out: Vec<&str> = Vec::new();
    for seg in rest.split('/') {
        match seg {
            "" | "." => continue,
            ".." => {
                out.pop();
                continue;
            }
            _ => {}
        }
        if seg.contains(':') {
            return Err(Refusal::Stream);
        }
        if seg.chars().any(is_invalid_windows_char) {
            return Err(Refusal::InvalidChar);
        }
        out.push(seg);
    }
    // Pass 2: trailing dots and spaces. Win32 strips them from the LAST name only, and only when
    // no separator follows it: `Windows.` opens `Windows`, but `a.\b`, `...\b` and `a \` keep
    // the name as written, which can be a different folder (Nova, #1745). Those are refused,
    // not guessed. A path ending in `.`, `..` or a separator has no last name to strip.
    let last_raw = rest.rsplit('/').next().unwrap_or("");
    let ends_in_name = !matches!(last_raw, "" | "." | "..");
    let n = out.len();
    let mut canon: Vec<&str> = Vec::with_capacity(n);
    for (i, seg) in out.into_iter().enumerate() {
        let trimmed = seg.trim_end_matches(['.', ' ']);
        if trimmed.len() != seg.len() {
            if verbatim {
                return Err(Refusal::VerbatimTrailing);
            }
            if i + 1 != n || !ends_in_name || trimmed.is_empty() {
                return Err(Refusal::TrailingDotSpace);
            }
        }
        canon.push(trimmed);
    }
    Ok(format!("{drive}:/{}", canon.join("/")))
}

fn strip_prefix_either<'a>(s: &'a str, backslashed: &str) -> Option<&'a str> {
    if let Some(r) = s.strip_prefix(backslashed) {
        return Some(r);
    }
    let forward = backslashed.replace('\\', "/");
    s.strip_prefix(forward.as_str())
}

fn is_sep(b: u8) -> bool {
    b == b'\\' || b == b'/'
}

fn starts_with_drive(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() >= 2 && b[0].is_ascii_alphabetic() && b[1] == b':'
}

fn is_invalid_windows_char(c: char) -> bool {
    matches!(c, '<' | '>' | '"' | '|' | '?' | '*') || (c as u32) < 0x20
}

/// The key two canonical paths are compared by. POSIX compares exactly. The Windows dialects
/// compare case-insensitively, as NTFS does: each character in the Basic Multilingual Plane maps
/// to its simple (single-character) upper case, and every other character is kept. NTFS's upcase
/// table works the same way, per UTF-16 unit, so `ß` stays `ß` and `é` matches `É`.
pub fn match_key(canonical: &str, dialect: Dialect) -> String {
    if !dialect.is_windows() {
        return canonical.to_string();
    }
    canonical
        .chars()
        .map(|c| {
            if (c as u32) > 0xFFFF {
                return c;
            }
            let mut up = c.to_uppercase();
            match (up.next(), up.next()) {
                (Some(u), None) if (u as u32) <= 0xFFFF => u,
                _ => c,
            }
        })
        .collect()
}

/// Whether `candidate` is `root` or lies beneath it, both already canonical under `dialect`.
/// Containment is tested at a separator, so `C:/ab` is not within `C:/a`. A root that ends in `/`
/// (`C:/`, `/`) contains everything on it.
pub fn is_within(root: &str, candidate: &str, dialect: Dialect) -> bool {
    let root = match_key(root, dialect);
    let cand = match_key(candidate, dialect);
    if cand == root {
        return true;
    }
    if root.ends_with('/') {
        return cand.starts_with(&root);
    }
    cand.len() > root.len() && cand.starts_with(&root) && cand.as_bytes()[root.len()] == b'/'
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    /// The table both implementations answer to. Rust and Python read the same file.
    const CASES: &str = include_str!("../../fixtures/path-form/cases.json");

    fn cases() -> Value {
        serde_json::from_str(CASES).expect("fixtures/path-form/cases.json parses")
    }

    fn dialect_of(case: &Value) -> Dialect {
        let name = case["dialect"].as_str().expect("case names a dialect");
        Dialect::parse(name).unwrap_or_else(|| panic!("unknown dialect {name}"))
    }

    #[test]
    fn every_canonical_case_in_the_shared_table_holds() {
        let table = cases();
        let rows = table["canonical"].as_array().expect("canonical rows");
        assert!(rows.len() >= 40, "the table shrank to {} rows", rows.len());
        let mut failures = Vec::new();
        for case in rows {
            let raw = case["raw"].as_str().expect("raw");
            let dialect = dialect_of(case);
            let got = canonical(raw, dialect);
            let ok = match (
                case.get("ok").and_then(Value::as_str),
                case.get("refused").and_then(Value::as_str),
            ) {
                (Some(want), None) => got.as_deref() == Ok(want),
                (None, Some(code)) => matches!(got, Err(r) if r.code() == code),
                _ => panic!("case {raw:?} must name exactly one of ok / refused"),
            };
            if !ok {
                failures.push(format!(
                    "{} {raw:?}: got {got:?}, want {case}",
                    dialect.as_str()
                ));
            }
        }
        assert!(
            failures.is_empty(),
            "{} case(s) failed:\n{}",
            failures.len(),
            failures.join("\n")
        );
    }

    #[test]
    fn every_same_and_within_case_in_the_shared_table_holds() {
        let table = cases();
        let mut failures = Vec::new();
        for case in table["same"].as_array().expect("same rows") {
            let d = dialect_of(case);
            let a = case["a"].as_str().unwrap();
            let b = case["b"].as_str().unwrap();
            let want = case["same"].as_bool().unwrap();
            let got = match (canonical(a, d), canonical(b, d)) {
                (Ok(x), Ok(y)) => match_key(&x, d) == match_key(&y, d),
                other => panic!("same-case {a:?}/{b:?} must both convert: {other:?}"),
            };
            if got != want {
                failures.push(format!("same {} {a:?} {b:?}: got {got}", d.as_str()));
            }
        }
        for case in table["within"].as_array().expect("within rows") {
            let d = dialect_of(case);
            let root = canonical(case["root"].as_str().unwrap(), d).expect("root converts");
            let cand =
                canonical(case["candidate"].as_str().unwrap(), d).expect("candidate converts");
            let want = case["within"].as_bool().unwrap();
            if is_within(&root, &cand, d) != want {
                failures.push(format!(
                    "within {} {root:?} {cand:?}: want {want}",
                    d.as_str()
                ));
            }
        }
        assert!(failures.is_empty(), "{}", failures.join("\n"));
    }

    #[test]
    fn every_refusal_code_is_exercised_by_the_table() {
        let table = cases();
        let used: std::collections::BTreeSet<&str> = table["canonical"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|c| c.get("refused").and_then(Value::as_str))
            .collect();
        for r in [
            Refusal::Empty,
            Refusal::NulByte,
            Refusal::Relative,
            Refusal::Tilde,
            Refusal::DriveRelative,
            Refusal::CurrentDrive,
            Refusal::GitBashMount,
            Refusal::Stream,
            Refusal::InvalidChar,
            Refusal::Unc,
            Refusal::DeviceNamespace,
            Refusal::VerbatimTrailing,
            Refusal::TrailingDotSpace,
        ] {
            assert!(
                used.contains(r.code()),
                "no case in the table is refused as {}",
                r.code()
            );
        }
    }

    #[test]
    fn a_canonical_path_is_its_own_canonical_form() {
        let table = cases();
        for case in table["canonical"].as_array().unwrap() {
            if let Some(want) = case.get("ok").and_then(Value::as_str) {
                let d = dialect_of(case);
                assert_eq!(
                    canonical(want, d).as_deref(),
                    Ok(want),
                    "{} {want:?} is not a fixed point",
                    d.as_str()
                );
            }
        }
    }

    /// The table's Windows claims, checked against a real NTFS filesystem rather than asserted:
    /// every spelling the table accepts opens the same file, and the stream spelling it refuses
    /// really is another name for that file.
    #[cfg(windows)]
    #[test]
    fn on_windows_the_spellings_the_table_accepts_open_the_same_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        let file = dir.path().join("Path Form.txt");
        std::fs::write(&file, b"one file").expect("write");
        let verbatim = std::fs::canonicalize(&file).expect("canonicalize");
        let verbatim = verbatim.to_str().expect("utf-8").to_string();
        assert!(
            verbatim.starts_with(r"\\?\"),
            "canonicalize returned {verbatim:?}"
        );
        // From the canonicalized path, not `file`: a runner's temp dir can carry an 8.3 short
        // name (RUNNER~1), which is the filesystem's to resolve, not this layer's.
        let native = verbatim[4..].to_string();

        let want = match_key(
            &canonical(&verbatim, Dialect::Windows).expect("verbatim converts"),
            Dialect::Windows,
        );
        let spellings = [
            native.clone(),
            native.replace('\\', "/"),
            native.to_lowercase(),
            native.to_uppercase(),
            format!("{native}."),
            format!("{native} . "),
            verbatim.clone(),
        ];
        for s in &spellings {
            let got =
                canonical(s, Dialect::Windows).unwrap_or_else(|r| panic!("{s:?} refused: {r}"));
            assert_eq!(
                match_key(&got, Dialect::Windows),
                want,
                "{s:?} keyed differently"
            );
            assert_eq!(
                std::fs::read(s).unwrap_or_else(|e| panic!("{s:?} does not open: {e}")),
                b"one file",
                "{s:?}"
            );
        }

        let stream = format!("{native}::$DATA");
        assert_eq!(
            std::fs::read(&stream).expect("the default stream opens"),
            b"one file"
        );
        assert_eq!(canonical(&stream, Dialect::Windows), Err(Refusal::Stream));

        let git_bash = format!(
            "/{}/{}",
            native[..1].to_lowercase(),
            native[3..].replace('\\', "/")
        );
        let got = canonical(&git_bash, Dialect::GitBash).expect("Git Bash spelling converts");
        assert_eq!(match_key(&got, Dialect::Windows), want, "{git_bash:?}");
        assert_eq!(
            canonical(&git_bash, Dialect::Windows),
            Err(Refusal::CurrentDrive)
        );
    }

    /// The other half, also against NTFS (Nova, #1745): spellings the table REFUSES for a
    /// trailing dot or space really can name a different file or folder, so stripping them
    /// would have pointed a grant or a deny at the wrong one.
    #[cfg(windows)]
    #[test]
    fn on_windows_a_kept_trailing_dot_or_space_is_a_different_name() {
        let dir = tempfile::tempdir().expect("tempdir");
        let v = std::fs::canonicalize(dir.path()).expect("canonicalize");
        let v = v.to_str().expect("utf-8").to_string();
        assert!(v.starts_with(r"\\?\"), "canonicalize returned {v:?}");
        let native = v[4..].to_string();

        // A verbatim file name ending in a space is its own file.
        std::fs::write(format!(r"{v}\file "), b"with space").expect("write 'file '");
        std::fs::write(format!(r"{v}\file"), b"plain").expect("write 'file'");
        assert_eq!(std::fs::read(format!(r"{v}\file ")).unwrap(), b"with space");
        assert_eq!(std::fs::read(format!(r"{v}\file")).unwrap(), b"plain");
        assert_eq!(
            canonical(&format!(r"{v}\file "), Dialect::Windows),
            Err(Refusal::VerbatimTrailing),
            "the input's end is not trimmed under \\\\?\\"
        );
        assert_eq!(
            canonical(&format!(r"{native}\file"), Dialect::Windows)
                .map(|c| match_key(&c, Dialect::Windows)),
            canonical(&format!(r"{v}\file"), Dialect::Windows)
                .map(|c| match_key(&c, Dialect::Windows)),
        );

        // A folder name ending in '.' is its own folder.
        std::fs::create_dir(format!(r"{v}\dd.")).expect("mkdir 'dd.'");
        std::fs::create_dir(format!(r"{v}\dd")).expect("mkdir 'dd'");
        std::fs::write(format!(r"{v}\dd.\x"), b"dotted").expect("write in 'dd.'");
        std::fs::write(format!(r"{v}\dd\x"), b"plain").expect("write in 'dd'");
        assert_eq!(std::fs::read(format!(r"{v}\dd.\x")).unwrap(), b"dotted");
        assert_eq!(std::fs::read(format!(r"{v}\dd\x")).unwrap(), b"plain");
        assert_eq!(
            canonical(&format!(r"{native}\dd.\x"), Dialect::Windows),
            Err(Refusal::TrailingDotSpace)
        );
        assert_eq!(
            canonical(&format!(r"{native}\dd \x"), Dialect::Windows),
            Err(Refusal::TrailingDotSpace)
        );
    }

    #[test]
    fn the_host_dialect_is_never_git_bash() {
        assert_ne!(Dialect::host(), Dialect::GitBash);
        assert_eq!(Dialect::host() == Dialect::Windows, cfg!(windows));
    }
}

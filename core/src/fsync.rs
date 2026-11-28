//! Portable fsync of a file someone else wrote, and of a directory entry (hestia #342).
//!
//! On Unix, `fsync` works on any descriptor, read-only included, and a directory is fsynced to make
//! a create or rename in it durable. On Windows neither carries over:
//! - `FlushFileBuffers` (what `sync_data`/`sync_all` call) needs a handle with write access; on a
//!   read-only handle it fails with ACCESS_DENIED. Before this module the witness chain opened its
//!   WAL read-only to fsync it, so on Windows the first sync at open failed, the chain poisoned
//!   itself, and the daemon could not start.
//! - Directory sync is not implemented on Windows. The helper is a no-op there, so callers do not
//!   get a post-create or post-rename persistence barrier. NTFS journaling alone does not establish
//!   that a particular namespace change is durable when this helper returns.

use std::fs::File;
use std::io;
use std::path::Path;

/// Open an existing file in the mode its platform needs to flush it: read-only on Unix (as before),
/// write access on Windows. Never creates or truncates. Std's Windows share mode (read, write,
/// delete) lets this coexist with SQLite's own handle on the same file.
pub fn open_for_sync(path: &Path) -> io::Result<File> {
    #[cfg(windows)]
    {
        std::fs::OpenOptions::new().write(true).open(path)
    }
    #[cfg(not(windows))]
    {
        File::open(path)
    }
}

/// `fdatasync` an existing file through a handle opened for it.
pub fn sync_file_data(path: &Path) -> io::Result<()> {
    open_for_sync(path)?.sync_data()
}

/// On Unix, fsync `dir` to persist its entries after a create or rename. On Windows this is a no-op:
/// success does not establish namespace durability, and a Windows publication protocol is still
/// needed wherever surviving power loss is part of the caller's contract.
pub fn sync_dir(dir: &Path) -> io::Result<()> {
    #[cfg(unix)]
    {
        File::open(dir)?.sync_all()
    }
    #[cfg(not(unix))]
    {
        let _ = dir;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn a_file_held_open_by_a_writer_can_be_synced_by_path() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("wal");
        let mut writer = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .open(&p)
            .unwrap();
        writer.write_all(b"frames").unwrap();
        sync_file_data(&p).unwrap();
        drop(writer);
        assert_eq!(
            std::fs::read(&p).unwrap(),
            b"frames",
            "syncing does not truncate"
        );
    }

    #[test]
    fn syncing_a_missing_file_is_not_found_and_creates_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("absent");
        assert_eq!(
            sync_file_data(&p).unwrap_err().kind(),
            io::ErrorKind::NotFound
        );
        assert!(!p.exists());
    }

    #[test]
    fn a_directory_can_be_synced() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("f"), b"x").unwrap();
        sync_dir(dir.path()).unwrap();
    }
}

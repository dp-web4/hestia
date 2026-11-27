//! Owner-only files and directories on every platform (hestia #342).
//!
//! WHY ONE MODULE. Hestia keeps secrets on disk: the vault ciphertext, `operator.key` (a plaintext
//! Ed25519 seed minted at genesis), and `.passphrase` (the daemon's vault passphrase, read by
//! `serve`). On Unix each was protected with a mode set at its own call site, `0o600` through
//! `std::os::unix::fs::PermissionsExt`, which does not compile on Windows. Gating those calls
//! `#[cfg(unix)]` would compile and silently ship a Windows vault whose files inherit whatever the
//! parent directory grants, so the Windows side is a real access-control list, not a no-op:
//!
//! - **Unix:** files `0o600`, directories `0o700`, exactly the modes used before this module.
//! - **Windows:** a *protected* DACL (parent inheritance cut) holding one allow ACE for the
//!   current process user's SID, with full access. On a directory that ACE is inheritable, so files
//!   created inside it start owner-only. This is the nearest equivalent to `0o600`/`0o700`: the
//!   owning account only. As with root on Unix, an Administrator can still take ownership; this
//!   protects against other ordinary accounts and processes running as them, which is what the
//!   Unix mode protects against too.
//!
//! [`write_private_new`] creates a file that is private from its first byte (Unix: `O_CREAT|O_EXCL`
//! with mode `0o600`; Windows: `CreateFileW(CREATE_NEW)` with the owner-only descriptor), instead of
//! writing and then restricting, which leaves a window where the bytes are readable.
//!
//! [`is_private`] reads the protection back, so a test (and later, a startup check) verifies the
//! result on the real filesystem rather than trusting that the call returned Ok.

use std::io;
use std::path::Path;

/// Restrict an existing file to its owner (Unix `0o600`; Windows owner-only protected DACL).
pub fn restrict_file(path: &Path) -> io::Result<()> {
    imp::restrict(path, false)
}

/// Restrict an existing directory to its owner (Unix `0o700`; Windows owner-only protected DACL,
/// inherited by files and directories created inside it afterwards).
pub fn restrict_dir(path: &Path) -> io::Result<()> {
    imp::restrict(path, true)
}

/// Create `path` (it must not exist), owner-only from the first byte, write `bytes`, and sync.
pub fn write_private_new(path: &Path, bytes: &[u8]) -> io::Result<()> {
    use std::io::Write;
    let mut f = imp::create_private_new(path)?;
    f.write_all(bytes)?;
    f.sync_all()
}

/// Whether only the owner can reach `path`. Unix: no group or other permission bits. Windows: the
/// DACL (explicit and inherited ACEs alike) is present, non-empty, and every ACE in it is an allow
/// ACE for the current user.
pub fn is_private(path: &Path) -> io::Result<bool> {
    imp::is_private(path)
}

#[cfg(unix)]
mod imp {
    use std::fs::{self, File, OpenOptions};
    use std::io;
    use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
    use std::path::Path;

    pub fn restrict(path: &Path, dir: bool) -> io::Result<()> {
        fs::set_permissions(
            path,
            fs::Permissions::from_mode(if dir { 0o700 } else { 0o600 }),
        )
    }

    pub fn create_private_new(path: &Path) -> io::Result<File> {
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)
    }

    pub fn is_private(path: &Path) -> io::Result<bool> {
        Ok(fs::metadata(path)?.permissions().mode() & 0o077 == 0)
    }
}

#[cfg(windows)]
mod imp {
    use std::ffi::c_void;
    use std::fs::File;
    use std::io;
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::FromRawHandle;
    use std::path::Path;
    use std::ptr;

    use windows_sys::Win32::Foundation::{
        CloseHandle, ERROR_SUCCESS, GENERIC_WRITE, HANDLE, INVALID_HANDLE_VALUE, LocalFree,
    };
    use windows_sys::Win32::Security::Authorization::{
        GetNamedSecurityInfoW, SE_FILE_OBJECT, SetNamedSecurityInfoW,
    };
    use windows_sys::Win32::Security::{
        ACCESS_ALLOWED_ACE, ACE_HEADER, ACL, ACL_REVISION, ACL_SIZE_INFORMATION,
        AclSizeInformation, AddAccessAllowedAceEx, CONTAINER_INHERIT_ACE,
        DACL_SECURITY_INFORMATION, EqualSid, GetAce, GetAclInformation, GetLengthSid,
        GetTokenInformation, InitializeAcl,
        InitializeSecurityDescriptor, OBJECT_INHERIT_ACE, PROTECTED_DACL_SECURITY_INFORMATION,
        PSECURITY_DESCRIPTOR, SE_DACL_PROTECTED, SECURITY_ATTRIBUTES, SECURITY_DESCRIPTOR,
        SetSecurityDescriptorControl, SetSecurityDescriptorDacl, TOKEN_QUERY, TOKEN_USER,
        TokenUser,
    };
    use windows_sys::Win32::Storage::FileSystem::{
        CREATE_NEW, CreateFileW, FILE_ALL_ACCESS, FILE_ATTRIBUTE_NORMAL,
    };
    use windows_sys::Win32::System::SystemServices::{
        ACCESS_ALLOWED_ACE_TYPE, SECURITY_DESCRIPTOR_REVISION,
    };
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    fn wide(path: &Path) -> Vec<u16> {
        path.as_os_str()
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }

    fn check(ok: i32) -> io::Result<()> {
        if ok == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }

    /// The current process user's TOKEN_USER, held in an 8-byte-aligned buffer the SID points into.
    struct CurrentUser {
        buf: Vec<u64>,
    }

    impl CurrentUser {
        fn get() -> io::Result<Self> {
            unsafe {
                let mut token: HANDLE = ptr::null_mut();
                check(OpenProcessToken(
                    GetCurrentProcess(),
                    TOKEN_QUERY,
                    &mut token,
                ))?;
                let mut len = 0u32;
                // Size query: fails with ERROR_INSUFFICIENT_BUFFER and sets `len`.
                GetTokenInformation(token, TokenUser, ptr::null_mut(), 0, &mut len);
                let mut buf = vec![0u64; (len as usize).div_ceil(8).max(1)];
                let r = GetTokenInformation(
                    token,
                    TokenUser,
                    buf.as_mut_ptr() as *mut c_void,
                    len,
                    &mut len,
                );
                let err = io::Error::last_os_error();
                CloseHandle(token);
                if r == 0 {
                    return Err(err);
                }
                Ok(Self { buf })
            }
        }

        fn sid(&self) -> *mut c_void {
            unsafe { (*(self.buf.as_ptr() as *const TOKEN_USER)).User.Sid }
        }
    }

    /// An ACL with one allow ACE: the current user, full access; inheritable when `dir`.
    struct OwnerAcl {
        buf: Vec<u64>,
        _user: CurrentUser,
    }

    impl OwnerAcl {
        fn new(dir: bool) -> io::Result<Self> {
            let user = CurrentUser::get()?;
            unsafe {
                let sid = user.sid();
                let size = std::mem::size_of::<ACL>() + std::mem::size_of::<ACCESS_ALLOWED_ACE>()
                    - std::mem::size_of::<u32>()
                    + GetLengthSid(sid) as usize;
                let mut buf = vec![0u64; size.div_ceil(8)];
                let acl = buf.as_mut_ptr() as *mut ACL;
                check(InitializeAcl(acl, size as u32, ACL_REVISION))?;
                let flags = if dir {
                    OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE
                } else {
                    0
                };
                check(AddAccessAllowedAceEx(
                    acl,
                    ACL_REVISION,
                    flags,
                    FILE_ALL_ACCESS,
                    sid,
                ))?;
                Ok(Self { buf, _user: user })
            }
        }

        fn as_ptr(&self) -> *const ACL {
            self.buf.as_ptr() as *const ACL
        }
    }

    pub fn restrict(path: &Path, dir: bool) -> io::Result<()> {
        let acl = OwnerAcl::new(dir)?;
        let name = wide(path);
        let r = unsafe {
            SetNamedSecurityInfoW(
                name.as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                acl.as_ptr(),
                ptr::null(),
            )
        };
        if r != ERROR_SUCCESS {
            return Err(io::Error::from_raw_os_error(r as i32));
        }
        Ok(())
    }

    pub fn create_private_new(path: &Path) -> io::Result<File> {
        let acl = OwnerAcl::new(false)?;
        let name = wide(path);
        unsafe {
            let mut sd: SECURITY_DESCRIPTOR = std::mem::zeroed();
            let psd = &mut sd as *mut SECURITY_DESCRIPTOR as PSECURITY_DESCRIPTOR;
            check(InitializeSecurityDescriptor(
                psd,
                SECURITY_DESCRIPTOR_REVISION,
            ))?;
            check(SetSecurityDescriptorDacl(psd, 1, acl.as_ptr(), 0))?;
            check(SetSecurityDescriptorControl(
                psd,
                SE_DACL_PROTECTED,
                SE_DACL_PROTECTED,
            ))?;
            let sa = SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: psd,
                bInheritHandle: 0,
            };
            let h = CreateFileW(
                name.as_ptr(),
                GENERIC_WRITE,
                0,
                &sa,
                CREATE_NEW,
                FILE_ATTRIBUTE_NORMAL,
                ptr::null_mut(),
            );
            if h == INVALID_HANDLE_VALUE {
                return Err(io::Error::last_os_error());
            }
            Ok(File::from_raw_handle(h))
        }
    }

    pub fn is_private(path: &Path) -> io::Result<bool> {
        let user = CurrentUser::get()?;
        let name = wide(path);
        unsafe {
            let mut dacl: *mut ACL = ptr::null_mut();
            let mut psd: PSECURITY_DESCRIPTOR = ptr::null_mut();
            let r = GetNamedSecurityInfoW(
                name.as_ptr(),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                &mut dacl,
                ptr::null_mut(),
                &mut psd,
            );
            if r != ERROR_SUCCESS {
                return Err(io::Error::from_raw_os_error(r as i32));
            }
            let verdict = (|| -> io::Result<bool> {
                // A NULL DACL grants everyone everything.
                if dacl.is_null() {
                    return Ok(false);
                }
                // Protection is NOT required: the DACL read here already holds the inherited ACEs,
                // so it states the effective grants. A file inside an owner-only home inherits one
                // ACE for its owner and is private without being protected itself.
                let mut info: ACL_SIZE_INFORMATION = std::mem::zeroed();
                check(GetAclInformation(
                    dacl,
                    &mut info as *mut ACL_SIZE_INFORMATION as *mut c_void,
                    std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                    AclSizeInformation,
                ))?;
                if info.AceCount == 0 {
                    return Ok(false);
                }
                for i in 0..info.AceCount {
                    let mut ace: *mut c_void = ptr::null_mut();
                    check(GetAce(dacl, i, &mut ace))?;
                    let header = &*(ace as *const ACE_HEADER);
                    if header.AceType as u32 != ACCESS_ALLOWED_ACE_TYPE {
                        return Ok(false);
                    }
                    let allowed = &*(ace as *const ACCESS_ALLOWED_ACE);
                    let sid = &allowed.SidStart as *const u32 as *mut c_void;
                    if EqualSid(sid, user.sid()) == 0 {
                        return Ok(false);
                    }
                }
                Ok(true)
            })();
            LocalFree(psd as _);
            verdict
        }
    }

    /// (volume serial, file index): the identity two paths share when they are the same file,
    /// including through a hard link. Windows' equivalent of Unix (dev, ino).
    pub fn file_identity(path: &Path) -> io::Result<(u32, u64)> {
        use std::os::windows::io::AsRawHandle;
        use windows_sys::Win32::Storage::FileSystem::{
            BY_HANDLE_FILE_INFORMATION, GetFileInformationByHandle,
        };
        let f = File::open(path)?;
        unsafe {
            let mut info: BY_HANDLE_FILE_INFORMATION = std::mem::zeroed();
            check(GetFileInformationByHandle(
                f.as_raw_handle() as HANDLE,
                &mut info,
            ))?;
            Ok((
                info.dwVolumeSerialNumber,
                ((info.nFileIndexHigh as u64) << 32) | info.nFileIndexLow as u64,
            ))
        }
    }
}

/// Whether two existing paths are the same file (a hard link, or the same path twice).
/// Unix compares (dev, ino); Windows compares (volume serial, file index).
pub fn same_file(a: &Path, b: &Path) -> io::Result<bool> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let (ma, mb) = (std::fs::metadata(a)?, std::fs::metadata(b)?);
        Ok((ma.dev(), ma.ino()) == (mb.dev(), mb.ino()))
    }
    #[cfg(windows)]
    {
        Ok(imp::file_identity(a)? == imp::file_identity(b)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_restricted_file_is_private() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("f");
        std::fs::write(&p, b"x").unwrap();
        restrict_file(&p).unwrap();
        assert!(is_private(&p).unwrap());
    }

    #[test]
    fn a_file_created_private_is_private_and_holds_its_bytes() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("key");
        write_private_new(&p, b"secret").unwrap();
        assert!(is_private(&p).unwrap());
        assert_eq!(std::fs::read(&p).unwrap(), b"secret");
    }

    #[test]
    fn creating_private_refuses_an_existing_file() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("key");
        std::fs::write(&p, b"old").unwrap();
        let e = write_private_new(&p, b"new").unwrap_err();
        assert_eq!(e.kind(), std::io::ErrorKind::AlreadyExists);
        assert_eq!(std::fs::read(&p).unwrap(), b"old");
    }

    #[test]
    fn a_file_created_inside_a_restricted_dir_is_private() {
        let dir = tempfile::tempdir().unwrap();
        let home = dir.path().join("home");
        std::fs::create_dir(&home).unwrap();
        restrict_dir(&home).unwrap();
        assert!(is_private(&home).unwrap());
        let p = home.join(".passphrase");
        std::fs::write(&p, b"pp").unwrap();
        // Unix: the directory's 0o700 is what protects the file, and the file keeps its umask mode,
        // so only Windows (where the inheritable ACE reaches the file itself) asserts the file.
        #[cfg(windows)]
        assert!(is_private(&p).unwrap());
    }

    #[test]
    fn an_unrestricted_file_is_not_reported_private() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("open");
        std::fs::write(&p, b"x").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o644)).unwrap();
        }
        // Windows: a fresh file in the temp dir inherits the parent's DACL, which is not protected.
        assert!(!is_private(&p).unwrap());
    }

    #[test]
    fn a_hard_link_is_the_same_file_and_a_copy_is_not() {
        let dir = tempfile::tempdir().unwrap();
        let a = dir.path().join("a");
        std::fs::write(&a, b"x").unwrap();
        let link = dir.path().join("link");
        std::fs::hard_link(&a, &link).unwrap();
        let copy = dir.path().join("copy");
        std::fs::copy(&a, &copy).unwrap();
        assert!(same_file(&a, &link).unwrap());
        assert!(!same_file(&a, &copy).unwrap());
    }
}

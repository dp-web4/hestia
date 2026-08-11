//! Public, locked-state projection of the vault-authoritative society identity.
//!
//! `public-identity.json` is deliberately **not** identity authority. It contains
//! only a shareable LCT id so a locked node can answer “who are you?” before the
//! vault is unlocked. The authoritative identity remains the sealed Society doc.
//!
//! Because this file is a projection, missing/stale/corrupt bytes are repaired on
//! every successful daemon open. That makes old vaults migrate forward without
//! re-genesis and prevents a cleartext artifact from becoming a second source of
//! truth.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;

const PUBLIC_IDENTITY_FILE: &str = "public-identity.json";

/// The minimum locked-tier identity fact Hestia can always derive from the vault.
///
/// `init` may add provenance such as `minted_by` when it genuinely knows the mint
/// event. A later daemon open must NOT overwrite that field with its own version:
/// projecting an old identity is not minting it. Serde ignores those extra fields
/// when we validate the one fact this module owns.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct PublicIdentityProjection {
    sovereign_lct: String,
}

fn expected(sovereign_lct: &str) -> PublicIdentityProjection {
    PublicIdentityProjection {
        sovereign_lct: sovereign_lct.to_string(),
    }
}

/// Project the vault-backed Society LCT into the clear, public tier.
///
/// The caller must supply the LCT read/minted from the unlocked authoritative
/// vault. This function never invents an identity and never reads identity from
/// the clear file.
pub(super) fn project(home: &Path, sovereign_lct: &str) -> Result<()> {
    let target = home.join(PUBLIC_IDENTITY_FILE);
    let wanted = expected(sovereign_lct);

    // Quiet fast path: if the identity is current, preserve any honest mint-time
    // provenance `init` wrote beside it. We compare identity, not producer version.
    if let Ok(bytes) = std::fs::read(&target) {
        if serde_json::from_slice::<PublicIdentityProjection>(&bytes)
            .ok()
            .as_ref()
            == Some(&wanted)
        {
            return Ok(());
        }
    }

    std::fs::create_dir_all(home)
        .with_context(|| format!("creating public identity directory {}", home.display()))?;
    // Migration knows only the identity observed in the authoritative vault. Do
    // not fabricate `minted_by`: an old node may have been minted by any version.
    let bytes = serde_json::to_vec_pretty(&wanted).context("encoding public identity")?;
    let tmp = home.join(format!(
        ".{PUBLIC_IDENTITY_FILE}.tmp-{}",
        std::process::id()
    ));
    std::fs::write(&tmp, &bytes)
        .with_context(|| format!("writing public identity temp file {}", tmp.display()))?;

    // `rename` atomically replaces on Unix. Windows refuses replacement of an
    // existing target, so fall back to remove+rename there. A brief missing
    // projection is safe: the vault remains authority and the next serve heals it.
    match std::fs::rename(&tmp, &target) {
        Ok(()) => Ok(()),
        Err(first) if target.exists() => {
            std::fs::remove_file(&target).with_context(|| {
                format!(
                    "replacing stale public identity {} after rename failed: {first}",
                    target.display()
                )
            })?;
            std::fs::rename(&tmp, &target).with_context(|| {
                format!("installing public identity projection {}", target.display())
            })
        }
        Err(e) => {
            let _ = std::fs::remove_file(&tmp);
            Err(e).with_context(|| format!("installing public identity {}", target.display()))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read(path: &Path) -> PublicIdentityProjection {
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
    }

    #[test]
    fn missing_projection_is_created_from_authoritative_identity() {
        let dir = tempfile::TempDir::new().unwrap();
        project(dir.path(), "lct:web4:mb32:bone").unwrap();
        let got = read(&dir.path().join(PUBLIC_IDENTITY_FILE));
        assert_eq!(got, expected("lct:web4:mb32:bone"));
    }

    #[test]
    fn stale_or_corrupt_projection_is_replaced_not_trusted() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join(PUBLIC_IDENTITY_FILE);
        std::fs::write(
            &path,
            br#"{"sovereign_lct":"lct:web4:mb32:WRONG","minted_by":"old"}"#,
        )
        .unwrap();
        project(dir.path(), "lct:web4:mb32:bright").unwrap();
        assert_eq!(read(&path), expected("lct:web4:mb32:bright"));

        std::fs::write(&path, b"not-json").unwrap();
        project(dir.path(), "lct:web4:mb32:bright").unwrap();
        assert_eq!(read(&path), expected("lct:web4:mb32:bright"));
    }

    #[test]
    fn current_identity_preserves_honest_mint_provenance() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join(PUBLIC_IDENTITY_FILE);
        let original = br#"{"sovereign_lct":"lct:web4:mb32:bstable","minted_by":"hestia 0.0.1"}"#;
        std::fs::write(&path, original).unwrap();
        project(dir.path(), "lct:web4:mb32:bstable").unwrap();
        assert_eq!(
            std::fs::read(&path).unwrap(),
            original,
            "projecting an old identity must not rewrite who minted it"
        );
    }
}

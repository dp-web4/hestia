#!/usr/bin/env python3
"""#828: target identity follows manifest dependencies, never caller cwd."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SHIM = Path(os.environ.get("BUILD_LOCK_SHIM", ROOT / "deploy" / "build-lock" / "cargo"))
FAKE_CARGO = """#!/usr/bin/env bash
if [ "${1:-}" = metadata ]; then
  if [ -n "${FAKE_METADATA_LOG:-}" ]; then printf '%s\\n' "$*" > "$FAKE_METADATA_LOG"; fi
  if [ -n "${FAKE_METADATA_ERROR:-}" ]; then exit 1; fi
  case " $* " in
    *" --filter-platform "*) ;;
    # Real `--offline` metadata wants every platform's deps cached unless filtered to the host.
    *) if [ -n "${FAKE_METADATA_UNFILTERED_FAILS:-}" ]; then exit 101; fi ;;
  esac
  cat "$FAKE_METADATA"
  exit $?
fi
printf 'CARGO_TARGET_DIR=%s\\n' "${CARGO_TARGET_DIR:-}"
printf 'CARGO_ARGS=%s\\n' "$*"
"""
FAKE_RUSTC = """#!/usr/bin/env bash
printf 'rustc 1.0.0\\nhost: x86_64-fake-linux\\n'
"""


def check(name, condition, detail):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"ok  {name}")


def main():
    with tempfile.TemporaryDirectory(prefix="build-lock-manifest-") as raw:
        parent = Path(raw).resolve()  # macOS: /var/folders -> /private/var/folders
        home = parent / "home"
        shim_dir = parent / "shim"
        real_bin = parent / "real-bin"
        home.mkdir()
        shim_dir.mkdir()
        real_bin.mkdir()
        fake = real_bin / "cargo"
        fake.write_text(FAKE_CARGO, encoding="utf-8")
        fake.chmod(0o755)
        fake_rustc = real_bin / "rustc"
        fake_rustc.write_text(FAKE_RUSTC, encoding="utf-8")
        fake_rustc.chmod(0o755)
        target_root = parent / "target-root"
        metadata = parent / "metadata.json"
        metadata_log = parent / "metadata-args.log"

        main_repo = parent / "main"
        main_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=main_repo, check=True)
        subprocess.run(["git", "config", "user.email", "probe@example.invalid"],
                       cwd=main_repo, check=True)
        subprocess.run(["git", "config", "user.name", "probe"], cwd=main_repo, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-qm", "fixture"], cwd=main_repo, check=True)
        worktree = parent / "worktree"
        subprocess.run(["git", "worktree", "add", "-q", str(worktree)],
                       cwd=main_repo, check=True)
        for repo in (main_repo, worktree):
            (repo / "core").mkdir()
            (repo / "core" / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
        non_git = parent / "non-git"
        non_git.mkdir()

        def write_metadata(root, dependency):
            document = {
                "workspace_root": str(root),
                "packages": [{"name": "web4-core", "manifest_path": str(dependency),
                              "source": None}],
            }
            metadata.write_text(json.dumps(document), encoding="utf-8")

        def run(cwd, *args, explicit_target=False, metadata_error=False, subcommand="build",
                unfiltered_fails=False):
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "PATH": f"{shim_dir}:{real_bin}:{env['PATH']}",
                "FAKE_METADATA": str(metadata),
                "FAKE_METADATA_LOG": str(metadata_log),
                "HESTIA_BUILD_TARGET": str(target_root),
                "HESTIA_BUILD_LOCK_WAIT": "0",
            })
            env.pop("CARGO_TARGET_DIR", None)
            if explicit_target:
                env["CARGO_TARGET_DIR"] = str(parent / "explicit-target")
            if metadata_error:
                env["FAKE_METADATA_ERROR"] = "1"
            else:
                env.pop("FAKE_METADATA_ERROR", None)
            env.pop("RUSTC", None)
            if unfiltered_fails:
                env["FAKE_METADATA_UNFILTERED_FAILS"] = "1"
            else:
                env.pop("FAKE_METADATA_UNFILTERED_FAILS", None)
            if metadata_log.exists():
                metadata_log.unlink()
            return subprocess.run([str(SHIM), subcommand, *args], cwd=cwd, env=env,
                                  capture_output=True, text=True, timeout=20)

        canonical_dependency = parent / "canonical" / "web4-core"
        write_metadata(main_repo, canonical_dependency)
        main_run = run(main_repo / "core")
        check("main checkout succeeds", main_run.returncode == 0, main_run.stderr)
        main_target = main_run.stdout.split("CARGO_TARGET_DIR=", 1)[1].splitlines()[0]
        check("main target is selected, not a silent fallback", main_target, main_run.stdout)

        worktree_run = run(worktree / "core")
        worktree_target = worktree_run.stdout.split("CARGO_TARGET_DIR=", 1)[1].splitlines()[0]
        check("worktree shares main's dependency identity", worktree_target == main_target,
              f"{main_target} != {worktree_target}")

        write_metadata(worktree, canonical_dependency)
        outside_run = run(non_git, "--manifest-path", str(worktree / "core" / "Cargo.toml"))
        outside_target = outside_run.stdout.split("CARGO_TARGET_DIR=", 1)[1].splitlines()[0]
        check("non-git cwd plus --manifest-path selects the same target",
              outside_target == main_target, f"{main_target} != {outside_target}")
        forwarded = metadata_log.read_text(encoding="utf-8")
        check("manifest argument reaches metadata", "--manifest-path" in forwarded, forwarded)
        check("diagnostics name the selected manifest root",
              f"manifest_root={worktree}" in outside_run.stderr, outside_run.stderr)
        check("diagnostics name the target and lock",
              "target_dir=" in outside_run.stderr and "lock=" in outside_run.stderr,
              outside_run.stderr)

        write_metadata(worktree, parent / "different" / "web4-core")
        changed = run(worktree / "core")
        changed_target = changed.stdout.split("CARGO_TARGET_DIR=", 1)[1].splitlines()[0]
        check("a different dependency identity gets a distinct target",
              changed_target != main_target, f"{main_target} == {changed_target}")

        failed = run(worktree / "core", metadata_error=True)
        check("metadata failure is loud and selects no fallback",
              failed.returncode == 2 and "CARGO_TARGET_DIR=" not in failed.stdout,
              f"rc={failed.returncode}, stdout={failed.stdout}, stderr={failed.stderr}")

        explicit = run(worktree / "core", explicit_target=True, metadata_error=True)
        check("an explicit target bypasses discovery without a metadata read",
              explicit.returncode == 0
              and "CARGO_TARGET_DIR=" + str(parent / "explicit-target") in explicit.stdout,
              f"rc={explicit.returncode}, stdout={explicit.stdout}, stderr={explicit.stderr}")

        # An unprimed non-host platform dep must not refuse a cached host build (sweep finding 1).
        write_metadata(main_repo, canonical_dependency)
        host_only = run(main_repo / "core", unfiltered_fails=True)
        check("metadata is filtered to the host platform",
              host_only.returncode == 0
              and "--filter-platform x86_64-fake-linux" in metadata_log.read_text(encoding="utf-8"),
              f"rc={host_only.returncode}, stderr={host_only.stderr}")

        # Outside git there is no shared target to split: pass through as before #828.
        write_metadata(non_git, canonical_dependency)
        plain = run(non_git)
        check("a non-git crate builds untouched",
              plain.returncode == 0 and "CARGO_TARGET_DIR=\n" in plain.stdout,
              f"rc={plain.returncode}, stdout={plain.stdout}, stderr={plain.stderr}")
        plain_fail = run(non_git, metadata_error=True)
        check("outside git a metadata failure is not refused",
              plain_fail.returncode == 0 and "CARGO_TARGET_DIR=\n" in plain_fail.stdout,
              f"rc={plain_fail.returncode}, stdout={plain_fail.stdout}, stderr={plain_fail.stderr}")

        # A registry install (no --path) has no local manifest: never discovered, even in git.
        listed = run(worktree, "--list", subcommand="install", metadata_error=True)
        check("install without --path skips discovery",
              listed.returncode == 0 and not metadata_log.exists(),
              f"rc={listed.returncode}, stdout={listed.stdout}, stderr={listed.stderr}")
        write_metadata(worktree, canonical_dependency)
        local = run(non_git, "--path", str(worktree / "core"), subcommand="install")
        local_target = local.stdout.split("CARGO_TARGET_DIR=", 1)[1].splitlines()[0]
        check("install --path is identified by that crate's manifest",
              local.returncode == 0 and local_target == main_target
              and f"--manifest-path {worktree / 'core' / 'Cargo.toml'}"
              in metadata_log.read_text(encoding="utf-8"),
              f"rc={local.returncode}, {main_target} != {local_target}, stderr={local.stderr}")

    print("all build-lock manifest identity checks pass")


if __name__ == "__main__":
    sys.exit(main())

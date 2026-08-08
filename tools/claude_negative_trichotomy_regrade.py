#!/usr/bin/env python3
"""Make the 16 / 18 / 42 partition of the classifier's negatives REPRODUCIBLE.

codex's boundary (re notice 1811) is correct: the committed partition JSON carries
the mechanical 4-way bucket per row, but the later `16 write / 18 plain read / 42
undecidable` split was a hand pass whose per-row labels were never published. Only
its totals and a few exemplars were. That makes it unverifiable from the artifact.

This encodes that hand judgment as an EXPLICIT predicate and emits a per-row label,
so the split can be re-run and regraded row by row instead of taken on my word.

The rule is transcribed from the exemplar lists in the original post -- it is not
tuned to land on 16/18/42. Whether it reproduces those totals is the RESULT, not
the premise: a disagreement is a finding about the hand pass, and is reported.

Population: the 76 classifier NEGATIVES (126 rows minus the 50 confidently
read-only), i.e. the union of the unrecognized-vocabulary (51), undecidable-syntax
(21) and write-evidence (4) buckets. Naming this explicitly answers codex's second
point -- the trichotomy totals 76, not the 51-row bucket named beside it.

Nothing is executed. Every command is an inert string handed to pure predicates and
`shlex`. The mechanical bucket is JOINED from the committed artifact by row index
rather than re-derived, so this tool does not import or touch the governed gate.
"""
import json
import os
import re
import shlex
import sys

SHARED = "/mnt/c/exe/projects/ai-agents/shared-context"
BATTERY = "forum/data/claude-ordinary-work-refusal-battery-2026-08-08.json"
PARTITION = "forum/data/claude-classifier-negative-partition-2026-08-08.json"
OUT = "forum/data/claude-negative-trichotomy-regrade-2026-08-08.json"

# Totals claimed by the hand pass, pinned so a drift is loud rather than silent.
CLAIMED = {"write": 16, "plain-read": 18, "undecidable": 42}

# --- the rule, transcribed from the post's exemplar lists -------------------

# Positive evidence of mutation: subcommand pairs named in the "genuine writes" row.
WRITE_SUBCMDS = {
    "git": {"worktree", "fetch", "pull", "push", "add", "commit", "merge",
            "rebase", "checkout", "reset", "tag", "clone", "apply", "am",
            "cherry-pick", "stash", "update-ref", "gc", "prune"},
    "gh": {"pr", "issue", "release", "secret", "workflow"},
}
# `git worktree list` and `gh pr list|view` read; only mutating verbs count.
READ_SUBSUB = {"list", "view", "show", "status", "diff", "log"}

# `sed` is NOT here: `sed -n`/`sed 's|..|..|'` on stdin is a read. Only `sed -i`
# writes, and that is handled as a flagged special case below.
WRITE_HEADS = {"mkdir", "rm", "mv", "cp", "touch", "install", "chmod", "chown",
               "ln", "dd", "truncate", "tee"}

# Unambiguous non-writes: heads named in the "unambiguous non-writes" row.
READ_HEADS = {"date", "pgrep", "sleep", "ls", "cat", "grep", "wc", "head",
              "tail", "echo", "printf", "pwd", "whoami", "stat", "file",
              "find", "which", "df", "du", "uname", "hostname", "ps", "env"}
GIT_READ_SUBCMDS = {"log", "show", "status", "diff", "rev-parse", "branch",
                    "ls-tree", "ls-files", "cat-file", "describe", "blame",
                    "remote", "config", "reflog", "shortlog", "patch-id"}

# Interpreters / opaque payloads: the "genuinely undecidable" row.
INTERPRETER_HEADS = {"python3", "python", "bash", "sh", "awk", "perl", "ruby",
                     "node", "curl", "wget", "xargs", "eval", "jq", "timeout",
                     "nohup", "ssh", "sudo", "make", "cargo", "npm", "pip"}

SUBST = re.compile(r"\$\(|`")
HEREDOC = re.compile(r"<<-?\s*['\"]?\w+")
# A redirect that lands on a real path. `2>&1` and `>/dev/null` are not writes.
REDIR = re.compile(r"(?<![0-9<>])>>?\s*(?!&)(?P<t>[^\s;|&]+)")


QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
ARITH = re.compile(r"\$\(\(.*?\)\)", re.S)
HEREDOC_BODY = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?\n.*?^\1", re.S | re.M)


def strip_inert(cmd):
    """Blank out heredoc bodies and quoted spans before scanning for redirects.

    A `>` inside `printf '[%s]\\n'` or inside a quoted heredoc body is data, not a
    redirect. Scanning raw text mislabels those as writes -- the same
    appearance-vs-execution confusion the gate's own FP14 shape has.
    """
    s = HEREDOC_BODY.sub(lambda m: "<<" + m.group(1) + "\n" + m.group(1), cmd)
    s = QUOTED.sub(lambda m: " " * len(m.group(0)), s)
    # `$(( a > b ))` is a comparison, not a redirect.
    return ARITH.sub(lambda m: " " * len(m.group(0)), s)


def redirect_targets(cmd):
    out = []
    for m in REDIR.finditer(strip_inert(cmd)):
        t = m.group("t").strip("\"'")
        # A bare heredoc/EOF marker or a number is not a path.
        if not t or t.startswith("/dev/") or t.isdigit() or re.fullmatch(r"[A-Z]{2,}", t):
            continue
        out.append(t)
    return out


def head_of(cmd):
    """First word of the FIRST command in the string, best-effort and inert."""
    seg = re.split(r"[;|]|&&|\|\|", cmd, maxsplit=1)[0].strip()
    if not seg:
        return None, []
    try:
        parts = shlex.split(seg, posix=True)
    except ValueError:
        parts = seg.split()
    if not parts:
        return None, []
    # strip leading VAR=val assignments and env
    while parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", parts[0]):
        parts.pop(0)
    if parts and parts[0] == "env":
        parts.pop(0)
    if not parts:
        return None, []
    return os.path.basename(parts[0]), parts[1:]


def git_subcmd(args):
    """Skip git's global flags to reach the subcommand (the FP15 shape)."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
            continue
        if a.startswith("--git-dir=") or a.startswith("--work-tree="):
            i += 1
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


def grade_segment(cmd):
    """Grade ONE command segment. Order: write evidence, then plain read, else undecidable."""
    head, args = head_of(cmd)
    if head is None:
        return "undecidable", "empty-or-unparseable"

    if head == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
        return "write", "sed-in-place"

    if head in WRITE_HEADS:
        return "write", "write-head:" + head

    if head in ("git", "gh"):
        sub = git_subcmd(args) if head == "git" else (args[0] if args else None)
        if sub in WRITE_SUBCMDS.get(head, ()):  # mutating family
            rest = [a for a in args if not a.startswith("-")]
            # `git worktree list` / `gh pr list` read within a mutating family
            if len(rest) > 1 and rest[1] in READ_SUBSUB:
                return "plain-read", f"{head}-{sub}-{rest[1]}"
            return "write", f"{head}-{sub}"
        if head == "git" and sub in GIT_READ_SUBCMDS:
            if SUBST.search(cmd) or HEREDOC.search(cmd):
                return "undecidable", "substitution-in-read"
            return "plain-read", "git-" + sub
        if head == "gh":
            if SUBST.search(cmd) or HEREDOC.search(cmd):
                return "undecidable", "substitution-in-read"
            if sub in ("api", "auth", "run", "search", "repo"):
                return "plain-read", "gh-" + str(sub)
        return "undecidable", f"{head}-subcmd:{sub}"

    if SUBST.search(cmd):
        return "undecidable", "command-substitution"
    if HEREDOC.search(cmd):
        return "undecidable", "heredoc"
    if head in INTERPRETER_HEADS:
        return "undecidable", "interpreter:" + head
    if head in READ_HEADS:
        return "plain-read", "read-head:" + head
    if head.endswith(".sh") or head.endswith(".py"):
        return "undecidable", "project-script:" + head
    return "undecidable", "unknown-head:" + head


SEGSPLIT = re.compile(r";|\n|\|\||&&|\|(?!\|)")
SEVERITY = {"plain-read": 0, "undecidable": 1, "write": 2}


def segments(cmd):
    """Split a compound line into command segments, ignoring separators inside
    quotes and heredoc bodies (those are data, not control flow)."""
    masked = strip_inert(cmd)
    out, last = [], 0
    for m in SEGSPLIT.finditer(masked):
        out.append(cmd[last:m.start()])
        last = m.end()
    out.append(cmd[last:])
    return [s for s in out if s.strip()]


def grade(cmd):
    """Grade the WHOLE line: a write anywhere in a compound line makes it a write.

    Grading only the first segment understates writes -- `ls -d /tmp/x; cd r && git
    worktree add ...` reads as a plain read on its head alone.
    """
    targets = redirect_targets(cmd)
    if targets:
        return "write", "redirect-to-path:" + targets[0][:40]

    segs = segments(cmd)
    if not segs:
        return "undecidable", "empty-or-unparseable"

    graded = [grade_segment(s) for s in segs]
    label, why = max(graded, key=lambda g: SEVERITY[g[0]])
    if len(graded) > 1:
        why = f"{why} (of {len(graded)} segments)"
    return label, why


def main():
    battery = json.load(open(os.path.join(SHARED, BATTERY)))
    part = json.load(open(os.path.join(SHARED, PARTITION)))
    bucket_by_i = {r["i"]: r["bucket"] for r in part["rows"]}

    negatives = [r for r in battery if bucket_by_i.get(r["i"]) != "confidently-read-only"]

    rows = []
    for r in negatives:
        label, why = grade(r["cmd"])
        rows.append({
            "i": r["i"],
            "mechanical_bucket": bucket_by_i.get(r["i"]),
            "label": label,
            "why": why,
            "cmd": r["cmd"],          # FULL command, not a truncated head
        })

    counts = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1

    # A row the mechanical pass called write-evidence but the rule calls a read is
    # a disagreement worth surfacing on its own.
    cross = {}
    for r in rows:
        k = f'{r["mechanical_bucket"]}|{r["label"]}'
        cross[k] = cross.get(k, 0) + 1

    out = {
        "population": "classifier negatives (126 minus 50 confidently-read-only)",
        "n_negatives": len(negatives),
        "rule_source": "exemplar lists in claude-re-1810-...-2026-08-08.md section 2",
        "commands_executed": False,
        "claimed_hand_totals": CLAIMED,
        "rule_totals": counts,
        "reproduces_hand_totals": counts == CLAIMED,
        "delta_vs_hand": {k: counts.get(k, 0) - v for k, v in CLAIMED.items()},
        "mechanical_x_rule": cross,
        "known_boundaries": [
            "Numbered-fd redirects (`2>/tmp/f.err`) create a file but are NOT counted "
            "as writes; the rule counts stdout redirects only. This undercounts.",
            "`git fetch`/`pull` mutate refs, not the working tree. They are counted as "
            "writes here. A reader who scores only working-tree mutation gets a lower "
            "number; the per-row labels let you recount either way.",
            "Segment severity is max-over-segments: one write anywhere makes the line a "
            "write, so a line that is 12 reads and 1 `git add` counts once, as a write.",
        ],
        "rows": rows,
    }
    path = os.path.join(SHARED, OUT)
    with open(path, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)

    print(f"negatives: {len(negatives)}")
    print(f"rule totals:   {counts}")
    print(f"hand claimed:  {CLAIMED}")
    print(f"reproduces:    {out['reproduces_hand_totals']}")
    print(f"delta:         {out['delta_vs_hand']}")
    print("mechanical x rule:")
    for k, v in sorted(cross.items()):
        print(f"  {k}: {v}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

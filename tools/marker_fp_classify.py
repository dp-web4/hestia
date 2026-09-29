#!/usr/bin/env python3
"""Classify a gate escalation as MARKER FALSE POSITIVE vs GENUINE GATED WRITE.

CALIBRATION (do not quote a number from this without re-reading this block).
Scored against kimi-code's hand-labelled set of all 36 unclaimed-approved Bash
escalations on their seat (issue #668 comment 5437030428): this classifier says
13 write / 23 not-a-write, kimi's hand labels say 12 / 24 -- one row apart in
aggregate. Per-row agreement is NOT established: kimi published counts, not row
ids. The write arm is the calibrated one; treat the split INSIDE the non-write
bucket (READ_ONLY vs AMBIGUOUS) as a statement about evidence quality in the
chain record, not about the act.

KNOWN ERROR DIRECTION. Residual errors put true FPs into the WRITE bucket, never
the reverse (each fixed error was of that form). So any finding of the shape
"WRITE acts claim LESS than READ_ONLY acts" is CONSERVATIVE under contamination:
diluting WRITE with FPs pulls its rate toward the FP rate, not away from it.

The reframe over #668's abandoned regex: the question is NOT "is this command a
write?" (compound commands with a `>` anywhere defeat that). The question is
"does the token THE MARKER MATCHED sit in a WRITE POSITION?"  A marker false
positive is a refusal where the gated path is only ever read or named.

Outputs a three-way verdict so the FP rate can be quoted as a BAND, never a point:
  READ_ONLY  -> every marker-matching token is in a read position   (FP floor)
  AMBIGUOUS  -> cannot decide (var indirection, unknown verb, censored)
  WRITE      -> some marker-matching token is a write destination   (genuine)
"""
import re, fnmatch, shlex

CENSOR = ("…[truncated]", "[truncated]", "[REDACTED")

# verbs whose ARGUMENTS are all written to
WRITE_ALL = {"rm","rmdir","truncate","touch","mkdir","chmod","chown","chgrp","shred","unlink"}
# verbs whose LAST argument is the destination
WRITE_LAST = {"cp","mv","install","ln","rsync"}
# verbs that only read their arguments
READ_ALL = {"cat","grep","egrep","fgrep","rg","head","tail","less","more","wc","sha256sum",
            "md5sum","sha1sum","cksum","ls","find","stat","file","diff","od","xxd","strings",
            "awk","cut","sort","uniq","nl","basename","dirname","realpath","readlink","test","["}
GIT_WRITE = {"add","checkout","restore","apply","rm","mv","stash","clean","commit"}
GIT_READ  = {"show","diff","status","log","ls-files","cat-file","blame","rev-parse","worktree","grep"}

SPLIT = re.compile(r'(?:\|\||&&|[;\n|])')

NOOP = {"cd","pushd","popd","sleep","set","export","unset","true"}
_ALLVERBS = None

def _resplit(seg):
    """`cd X chmod +x Y git add Z` -> three segments. The record flattens newlines
    to spaces, which collapses a multi-line script into one `cd`-headed segment and
    hides every write in it."""
    global _ALLVERBS
    if _ALLVERBS is None:
        _ALLVERBS = WRITE_ALL | WRITE_LAST | READ_ALL | {"git","tee","sed","echo","printf","python3"}
    w = seg.split()
    if not w or w[0].split("/")[-1] not in NOOP:
        return [seg]
    out, cur = [], []
    for x in w:
        if cur and x.split("/")[-1] in _ALLVERBS and not cur[-1].startswith("-"):
            out.append(" ".join(cur)); cur = [x]
        else:
            cur.append(x)
    if cur:
        out.append(" ".join(cur))
    return out

def _segments(cmd):
    segs = []
    for s in SPLIT.split(cmd):
        s = s.strip()
        if s:
            segs.extend(_resplit(s))
    return segs

def _matches(tok, marker):
    t = tok.strip("'\"").lower(); m = marker.lower()
    if "*" in m:
        # glob marker: match against the path and every prefix of it
        parts = t.split("/")
        for i in range(len(parts)):
            for j in range(i+1, len(parts)+1):
                if fnmatch.fnmatch("/".join(parts[i:j]), m):
                    return True
        return False
    return m in t

def _under_tmp(tok, cwd_tmp=False):
    t = tok.strip("'\"")
    if t.startswith("/tmp/") or t == "/tmp" or "/tmp/" in t:
        return True
    return cwd_tmp and not t.startswith("/")   # relative path resolved under a /tmp cwd

def classify(cmd, marker, tool="Bash"):
    """`stated_reason` has a DIFFERENT GRAMMAR per tool. Edit/Write record a bare
    destination path; only Bash records a command line. Parsing an Edit row with the
    shell parser is a category error that manufactures spurious READ_ONLY verdicts."""
    if tool == "apply_patch":
        t = (cmd or "")
        if "[REDACTED" in t:
            return "REDACTED", "patch withheld"
        files = re.findall(r'\*\*\*\s*(?:Update|Add|Delete)\s+File:\s*(\S+)', t)
        if not files:
            return "AMBIGUOUS", "patch header names no file"
        hits = [f for f in files if _matches(f, marker)]
        if not hits:
            return "READ_ONLY", f"marker matches no patched file; named only in the diff BODY ({len(files)} files patched)"
        if all(_under_tmp(f) for f in hits):
            return "READ_ONLY", f"patched files under /tmp: {hits[:2]}"
        return "WRITE", f"patch writes marker-matched file(s): {hits[:2]}"
    if tool in ("Edit", "Write", "NotebookEdit"):
        t = (cmd or "").strip()
        if not t:
            return "AMBIGUOUS", "empty destination"
        if "[REDACTED" in t:
            return "REDACTED", "destination withheld"
        if _under_tmp(t):
            return "READ_ONLY", f"destination under /tmp, not a gated path: {t}"
        if _matches(t, marker):
            return "WRITE", f"{tool} destination is the marker-matched path: {t}"
        return "AMBIGUOUS", f"{tool} destination does not contain the marker: {t}"
    return _classify_bash(cmd, marker)


def _classify_bash(cmd, marker):
    if not cmd or not cmd.strip():
        return "AMBIGUOUS", "empty stated_reason"
    if "[REDACTED" in cmd:
        return "REDACTED", "act withheld from the record entirely"
    truncated = any(c in cmd for c in ("\u2026[truncated]", "[truncated]"))
    body = re.sub(r'^(?:Bash|Edit|Write|apply_patch)\s*:\s*', '', cmd.strip())
    body = re.sub(r'\u2026?\[truncated\]$', '', body.strip())
    # prose rationale, not a command line: no shell verb anywhere
    if not truncated and not re.search(r'[/$>|&;=]', body) and len(body.split()) < 14:
        return "PROSE", "member-stated rationale, not a command"
    # resolve simple VAR=<path> assignments so indirection is followed, not guessed
    for vm in re.finditer(r'(?:^|[;&\s])([A-Za-z_]\w*)=([^\s;|&]+)', body):
        body = body.replace("$" + vm.group(1), vm.group(2)).replace("${%s}" % vm.group(1), vm.group(2))
    # mine command substitutions as their own segments
    body = body.replace("$(", " ; ").replace("`", " ; ")

    # Gate 1a is a raw substring match over the WHOLE command text, so the marker
    # trips on paths named inside quoted data too. Those are namings, never writes.
    # Pull heredoc bodies and long quoted flag-values out before positional parsing.
    named_as_data = []
    def _pull(pat, label):
        nonlocal body
        for m in re.finditer(pat, body, re.S):
            chunk = m.group(0)
            if _matches(chunk, marker):
                named_as_data.append(label)
        body = re.sub(pat, " ", body, flags=re.S)
    _pull(r"<<-?\s*'?\\?\"?(\w+)'?\"?.*?\\b\\1\\b", "heredoc body")
    _pull(r"--(?:reason|message|body|m|desc|comment)[= ]\s*'[^']*'", "quoted flag value")
    _pull(r"--(?:reason|message|body|m|desc|comment)[= ]\s*\"[^\"]*\"", "quoted flag value")

    # cwd tracking: `cd /tmp/x && cp a b/c` writes under /tmp, not to a gated path.
    cwd_tmp = bool(re.match(r'^\s*cd\s+(/tmp\b|/tmp/)', body))

    verdicts = []          # per marker-matching token
    var_from_marker = set()
    for seg in _segments(body):
        # redirect destinations anywhere in the segment
        for m in re.finditer(r'(?:>>?|(?<=\b)of=)\s*([^\s;|&)]+)', seg):
            tok = m.group(1)
            if _matches(tok, marker):
                verdicts.append(("WRITE" if not _under_tmp(tok, cwd_tmp) else "READ", "redirect target " + tok))
        try:
            words = shlex.split(seg, posix=True)
        except ValueError:
            words = seg.split()
        if not words:
            continue
        # variable assignment sourcing a marker path -> indirection risk
        for w in words:
            am = re.match(r'^([A-Za-z_]\w*)=(.*)$', w)
            if am and _matches(am.group(2), marker):
                var_from_marker.add(am.group(1))
        # strip env-assignments / sudo / time to find the verb
        i = 0
        while i < len(words) and (re.match(r'^[A-Za-z_]\w*=', words[i]) or words[i] in ("sudo","time","env","nohup")):
            i += 1
        if i >= len(words):
            continue
        verb = words[i].split("/")[-1]
        args = [w for w in words[i+1:] if not w.startswith(">")]
        sub = None
        if verb == "git":
            gsub = next((a for a in args if not a.startswith("-")), None)
            # `git -C <path> <sub>` : -C path is a cwd, not a target
            if gsub in ("-C",):
                gsub = None
            rest = args
            for k, a in enumerate(args):
                if a == "-C" and k+1 < len(args):
                    rest = args[k+2:]
                    break
            sub = next((a for a in rest if not a.startswith("-")), None)
        pos_args = [a for a in args if not a.startswith("-")]
        for k, a in enumerate(pos_args):
            if not _matches(a, marker):
                continue
            if _under_tmp(a, cwd_tmp):
                verdicts.append(("READ", f"/tmp lookalike: {a}")); continue
            if verb == "git":
                if sub in GIT_WRITE and a != sub:
                    verdicts.append(("WRITE", f"git {sub} target {a}"))
                elif sub in GIT_READ:
                    verdicts.append(("READ", f"git {sub} reads {a}"))
                else:
                    verdicts.append(("AMB", f"git {sub} unknown disposition on {a}"))
            elif verb in WRITE_ALL:
                verdicts.append(("WRITE", f"{verb} target {a}"))
            elif verb in WRITE_LAST:
                if k == len(pos_args) - 1:
                    verdicts.append(("WRITE", f"{verb} destination {a}"))
                else:
                    verdicts.append(("READ", f"{verb} source {a}"))
            elif verb == "tee":
                verdicts.append(("WRITE", f"tee target {a}"))
            elif verb == "sed":
                verdicts.append(("WRITE" if any(x.startswith("-i") for x in args) else "READ",
                                 f"sed {'in-place' if any(x.startswith('-i') for x in args) else 'read'} {a}"))
            elif verb in READ_ALL:
                verdicts.append(("READ", f"{verb} reads {a}"))
            elif verb in ("cd","pushd","popd"):
                verdicts.append(("READ", f"{verb} navigates to {a}"))
            elif verb in ("echo","printf","for","do","if","then","while","[[","export","local"):
                verdicts.append(("READ", f"{verb} names {a} as data"))
            else:
                verdicts.append(("AMB", f"unknown verb {verb!r} on {a}"))
        # indirection: a marker-derived var used by a writing verb
        if var_from_marker:
            for a in args:
                for v in var_from_marker:
                    if f"${v}" in a or f"${{{v}}}" in a:
                        if verb in WRITE_ALL or verb in WRITE_LAST or verb == "tee":
                            verdicts.append(("AMB", f"marker-derived ${v} used by {verb}"))
    verdicts += [("READ", f"marker named inside {l}") for l in named_as_data]
    if not verdicts:
        return "AMBIGUOUS", "marker matched nothing parseable (spliced token / indirection)"

    kinds = {k for k, _ in verdicts}
    why = "; ".join(w for _, w in verdicts[:4])
    if "WRITE" in kinds:
        return "WRITE", why          # sound even if truncated: writes are monotone
    if "AMB" in kinds:
        return "AMBIGUOUS", why
    if truncated:
        return "READ_ONLY_PREFIX", "visible prefix all reads, tail withheld: " + why
    return "READ_ONLY", why

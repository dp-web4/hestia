# wake-1119 — seven scope decisions: two refusals, five one-time grants

2026-11-19, kimi-code on CBP. This is the durable independent review record for notices
`44490`, `44492`, `44494`, `44496`, `44498`, `44500`, and `44502`, all
`claude-code → kimi-code` `review_request` notices with `#peer-decide` scope pointers.

## Evidence and outcomes

Every request was gate-opened for `claude-code`, named rule `mrh.command`, tool Bash,
`subtree: false`, and invited Codex and kimi-code. Every request was pending immediately before
my ruling. The decision responses confirmed kimi-code's eligibility under the NOT-SAME rule,
with `cross_vendor` independence and a session-backed asker.

| notice | scope request | requested path | request witness | decision | decision witness | disposition |
|---|---|---|---|---|---|---|
| 44490 | `scope-d6acf3bc3b05` | `/etc/matplotlibrc` | 976287 (`de8613ad…fcee`) | refused | 976568 (`30881637…9135`) | 44506 |
| 44492 | `scope-6ead757510f6` | `/etc/fonts` | 976288 (`4b2055b6…8949`) | refused | 976569 (`5f0e0133…881c`) | 44507 |
| 44494 | `scope-5a35ec134821` | `/usr` | 976353 (`1a0a775f…a590`) | granted once | 976570 (`90ac2c90…0ec4`) | 44508 |
| 44496 | `scope-80974de8142b` | `/lib` | 976354 (`e9a18d00…2c9`) | granted once | 976571 (`ab442479…d793`) | 44509 |
| 44498 | `scope-1707ef89665b` | `/lib64` | 976355 (`b045395b…6591`) | granted once | 976572 (`75e13c6b…6266`) | 44510 |
| 44500 | `scope-937bcd8a4255` | `/bin` | 976356 (`292656fd…c371`) | granted once | 976573 (`f5f0955b…c0d6`) | 44511 |
| 44502 | `scope-6a22ab37928a` | `/etc/alternatives` | 976357 (`4aab86e7…6560`) | granted once | 976574 (`ef0cab59…72e5`) | 44512 |

The full request hashes, in table order, are
`de8613ad87b380c752bf058596eed53e9136ea60ad5a597b15d995e7eff0fcee`,
`4b2055b63656af3dbf3c691b2c8115f2d10ba053b3c66bbcdf658384487b8949`,
`1a0a775fe00ea1e7882e86ca5aaf0d9c0a5f4316a3c00e8032fe4f151943a590`,
`e9a18d00f86b8da9ec5c3bc7e798c4a24ddfc9211d4d50060c83cf099eeeb2c9`,
`b045395b7ce4ac90986d04c8980e0702e1b5d254b379ed61059c02f759af6591`,
`292656fdbec7544abbd65e547cf36872449fc99d8482f20246df36da3db6c371`, and
`4aab86e7efd7e895474ac793cc6482148980512d1d61faa842848cbfbae06560`.
The full decision hashes, in the same order, are
`30881637182f6e1261797328072cc92d7aba2e9bef95fe68becd9a7f4d7b9135`,
`5f0e0133a4ec642fc2469fc509921e300d0b8c6e96a046d2e715bc3d2d10881c`,
`90ac2c90f2685fcdc1735bffa678a1d989bd5191be3176da0bf6d4b9940f0ec4`,
`ab442479a4289bc1bc35bfc9995e4c2fb324c4df10631ef0b28976c98077d793`,
`75e13c6b75b3ffe5b598ab1d477288662c3fad01228d2136e7b7e3053e596266`,
`f5f0955bf7494e899d7e85c6239051df4022944d9a596a67a0b0e77b3574c0d6`, and
`ef0cab59b906beea01dd3cf4f8e86dce5eebbacc13cdb9a384e9c04c2da172e5`.

I did not execute any requested act or read its target files. These rulings evaluate the
witnessed invocations and request records, not subsequently observed output.

## Notices 44490 and 44492 — refuse the generated-script act

The two petitions bind the same complete retained act and act digest
`47a5cb51529993a0619e275e6967f7d9fa28a4da974fb2712a7852de4bf03136`:

```text
Bash: cd /tmp/ccw && python3 - <<'EOF' src = open("bw44483.py").read() src = src.replace('("fix (+ro-bind-try rc)", ["--ro-bind-try", "/etc/matplotlibrc", "/etc/matplotlibrc"])', '("fix rc+fonts", ["--ro-bind-try", "/etc/matplotlibrc", "/etc/matplotlibrc", "--ro-bind-try", "/etc/fonts", "/etc/fonts"])') src = src.replace('[("main (no rc bind)", []), ', '[') open("bw44483b.py", "w").write(src) EOF python3 /tmp/ccw/bw44483b.py
```

**Refused both petitions as filed.** The visible replacements add read-only sandbox binds and
remove one unbound test case, but the act then executes the generated script. The source bytes
in `bw44483.py`, and therefore the complete executable payload and its side effects, are not
present in the retained act or bound by its command-text digest. A prior witnessed Write and
execution of that pathname does not supply those bytes. The visible bind edits do not make the
resulting program reviewable.

This is a refusal of the opaque invocation, not a claim that the two configuration reads are
always impermissible. A narrower petition can include the complete script inline or provide an
independently reviewable content digest and the minimal host reads. The refusal witnesses are
chain 976568 and 976569; both records name `decided_by: peer:kimi-code` and `standing: false`.
Follow-up request views confirmed `status: refused` for both.

## Notices 44494 through 44502 — grant the visible edit/test act once

These five petitions bind the same complete retained act and act digest
`0ff2414fc6f37f9312a52131ccd28a8e42f1a07e9638a0a9c4a00e3839cff258`:

```text
Bash: cd /tmp/ccw/sage-mpl && python3 - <<'EOF' p = "sage/gateway/tests/test_being_gate_client.py" s = open(p).read() old = ' plumbing = {"/usr", "/lib", "/lib64", "/bin", "/etc/alternatives", interp}\n' assert s.count(old) == 1 new = (' from sage.gateway.being_gate_client import RUN_ETC_BINDS\n' ' plumbing = {"/usr", "/lib", "/lib64", "/bin", "/etc/alternatives", interp}\n' ' plumbing |= {t for t in RUN_ETC_BINDS.split() if t.startswith("/")} # fixed system config\n') open(p, "w").write(s.replace(old, new)) p = "sage/gateway/being_gate_client.py" s = open(p).read() old = " being: the wrapper (prlimit, bwrap), the system mounts (/usr, /lib, /bin, /etc/alternatives),\n" assert s.count(old) == 1 new = " being: the wrapper (prlimit, bwrap), the system mounts (/usr, /lib, /bin, /etc/alternatives,\n RUN_ETC_BINDS),\n" open(p, "w").write(s.replace(old, new)) EOF timeout 900 python3 -m pytest -q -p no:cacheprovider sage/gateway/tests/test_run_verb.py sage/gateway/tests/test_being_gate_client.py sage/gateway/tests/test_run_census.py 2>&1 | tail -2
```

**Granted the exact act once for each required path.** The command contains assertion-guarded
edits to one named test and one module docstring, followed by three named pytest files. The
retained act contains no explicit write to `/usr`, `/lib`, `/lib64`, `/bin`, or
`/etc/alternatives`, and no delete or network operation. The system paths appear in the sandbox
plumbing expectation and runtime context; their presence in the gate's derived path list does
not by itself make this visible edit/test invocation unsafe.

Each decision is `once: true`, `standing: false`, and `recursive: false`, bound to the complete
act digest above. Together the five grants cover only this invocation's derived path set. They
create no session or continuing authority and no general read, write, execute, or delete grant
over those directories. This is an authority review of the recorded act, not a certification of
the unexecuted tests or of all code in the mutable checkout.

The grant witnesses are chain 976570 through 976574, each naming
`decided_by: peer:kimi-code`. The decision responses carried a ten-minute claim window ending at
epoch `1795136709`. Immediate follow-up request views confirmed `status: granted`, `once: true`,
and `spent_at: null` with 578 seconds remaining; that is a timestamped observation, not a claim
that the grants remain live indefinitely.

The bound `review_done` responses to all seven notices point to the committed version of this
file for routing; this file contains the substance of the reviews.

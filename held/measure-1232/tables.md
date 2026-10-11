# #1232 refusal-rate measurement output

Scripts: `corpus.py` (the corpus reader), `replay.py` (judge every command under each core in `MEASURE_CORES`, with and without `grants-proposed.txt`), `aggregate.py`, `shapes.py`. Rows (`results.jsonl`: seat, timestamp, verdict class per core; no command text) are not committed.

## 2026-10-11: main 7e901d3c vs c36101e4 (v1) vs the literal rule (lit) — replay of 53,844 commands

### Window of the 2026-10-05 run (2026-09-20 .. 2026-10-05T20:05Z): 33054 commands (claude-code 24536, codex 3359, kimi-code 5159)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| v1 | none | 7051 (21.3%) | 2773 | 4278 | 0 | 6080 (24.8%) | 76 (2.3%) | 895 (17.3%) |
| v1 | proposed | 5660 (17.1%) | 1079 | 4581 | 0 | 5182 (21.1%) | 36 (1.1%) | 442 (8.6%) |
| lit | none | 5539 (16.8%) | 2773 | 2766 | 0 | 4690 (19.1%) | 76 (2.3%) | 773 (15.0%) |
| lit | proposed | 4048 (12.2%) | 1080 | 2968 | 0 | 3699 (15.1%) | 36 (1.1%) | 313 (6.1%) |

### Full window (2026-09-20 .. now): 53844 commands (claude-code 41355, codex 5780, kimi-code 6709)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| v1 | none | 13401 (24.9%) | 4137 | 9264 | 0 | 12069 (29.2%) | 133 (2.3%) | 1199 (17.9%) |
| v1 | proposed | 11499 (21.4%) | 1695 | 9804 | 0 | 10871 (26.3%) | 70 (1.2%) | 558 (8.3%) |
| lit | none | 10722 (19.9%) | 4137 | 6585 | 0 | 9523 (23.0%) | 133 (2.3%) | 1066 (15.9%) |
| lit | proposed | 8661 (16.1%) | 1696 | 6965 | 0 | 8173 (19.8%) | 70 (1.2%) | 418 (6.2%) |

main itself refuses 1427 of 53844 (pass 1/2, unchanged by this PR)

## 2026-10-11: reproduced with the committed scripts (53,995 commands)

### Window of the 2026-10-05 run (2026-09-20 .. 2026-10-05T20:05Z): 33054 commands (claude-code 24536, codex 3359, kimi-code 5159)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| lit | none | 5539 (16.8%) | 2773 | 2766 | 0 | 4690 (19.1%) | 76 (2.3%) | 773 (15.0%) |
| lit | proposed | 4048 (12.2%) | 1080 | 2968 | 0 | 3699 (15.1%) | 36 (1.1%) | 313 (6.1%) |

### Full window (2026-09-20 .. now): 53995 commands (claude-code 41452, codex 5834, kimi-code 6709)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| lit | none | 10743 (19.9%) | 4140 | 6603 | 0 | 9543 (23.0%) | 134 (2.3%) | 1066 (15.9%) |
| lit | proposed | 8682 (16.1%) | 1698 | 6984 | 0 | 8193 (19.8%) | 71 (1.2%) | 418 (6.2%) |

main itself refuses 1429 of 53995 (pass 1/2, unchanged by this PR)

## 2026-10-10: main d3c731fc vs 01e68a1c as reviewed (orig), merged onto main (before), narrowed (after)

### Window of the 2026-10-05 run (2026-09-20 .. 2026-10-05T20:05Z): 33054 commands (claude-code 24536, codex 3359, kimi-code 5159)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| orig | none | 3415 (10.3%) | 2612 | 0 | 799 | 2726 (11.1%) | 67 (2.0%) | 622 (12.1%) | errors=4
| orig | proposed | 1607 (4.9%) | 783 | 0 | 820 | 1432 (5.8%) | 27 (0.8%) | 148 (2.9%) | errors=4
| before | none | 3415 (10.3%) | 2612 | 0 | 799 | 2726 (11.1%) | 67 (2.0%) | 622 (12.1%) | errors=4
| before | proposed | 1607 (4.9%) | 783 | 0 | 820 | 1432 (5.8%) | 27 (0.8%) | 148 (2.9%) | errors=4
| after | none | 7051 (21.3%) | 2773 | 4278 | 0 | 6080 (24.8%) | 76 (2.3%) | 895 (17.3%) |
| after | proposed | 5660 (17.1%) | 1079 | 4581 | 0 | 5182 (21.1%) | 36 (1.1%) | 442 (8.6%) |

### Full window (2026-09-20 .. now): 53502 commands (claude-code 41142, codex 5651, kimi-code 6709)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| orig | none | 6629 (12.4%) | 3841 | 0 | 2784 | 5655 (13.7%) | 114 (2.0%) | 860 (12.8%) | errors=4
| orig | proposed | 4025 (7.5%) | 1156 | 0 | 2865 | 3777 (9.2%) | 51 (0.9%) | 197 (2.9%) | errors=4
| before | none | 6629 (12.4%) | 3841 | 0 | 2784 | 5655 (13.7%) | 114 (2.0%) | 860 (12.8%) | errors=4
| before | proposed | 4025 (7.5%) | 1156 | 0 | 2865 | 3777 (9.2%) | 51 (0.9%) | 197 (2.9%) | errors=4
| after | none | 13265 (24.8%) | 4125 | 9140 | 0 | 11941 (29.0%) | 125 (2.2%) | 1199 (17.9%) |
| after | proposed | 11364 (21.2%) | 1687 | 9677 | 0 | 10744 (26.1%) | 62 (1.1%) | 558 (8.3%) |

main itself refuses 1426 of 53502 (pass 1/2, unchanged by this PR)

## once-only requests left by the literal rule (proposed grants, full window)
```
once-only requests after the proposed grants: 6984
    2739   39.2%  variable: assigned an EXPANSION in the same command
    1373   19.7%  variable: a for-loop variable
    1020   14.6%  variable: assigned a LITERAL in the same command (one assignment)
     520    7.4%  command substitution used as a path
     275    3.9%  an expansion exported in …
     253    3.6%  an expansion handed to … in …
     195    2.8%  an expansion used as the program
     128    1.8%  a process substitution used as a path
      92    1.3%  variable: a `read` variable (stdin)
      84    1.2%  argv built from stdin (…)
      78    1.1%  a home spelling after HOME is reassigned
      76    1.1%  variable: from the environment / unknown
      57    0.8%  parameter expansion ${…}
      29    0.4%  positional parameter
      22    0.3%  variable: assigned a LITERAL in the same command (several)
      19    0.3%  brace expansion
      13    0.2%  an unbalanced double quote
       6    0.1%  an unbalanced single quote
       2    0.0%  a relative path after a directory change to …
       1    0.0%  more than 16 directory changes
       1    0.0%  <incomplete: more distinct paths than the gate judges in one
       1    0.0%  a heredoc form the parser does not model
```

## 2026-10-11: main 7e901d3c vs f4644ef4 (lit) vs the Codex-20536 repairs (fix) — 54,099 commands

### Window of the 2026-10-05 run (2026-09-20 .. 2026-10-05T20:05Z): 33054 commands (claude-code 24536, codex 3359, kimi-code 5159)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| lit | none | 5539 (16.8%) | 2773 | 2766 | 0 | 4690 (19.1%) | 76 (2.3%) | 773 (15.0%) |
| lit | proposed | 4048 (12.2%) | 1080 | 2968 | 0 | 3699 (15.1%) | 36 (1.1%) | 313 (6.1%) |
| fix | none | 6288 (19.0%) | 2773 | 3515 | 0 | 5378 (21.9%) | 76 (2.3%) | 834 (16.2%) |
| fix | proposed | 4822 (14.6%) | 1079 | 3743 | 0 | 4412 (18.0%) | 36 (1.1%) | 374 (7.2%) |

### Full window (2026-09-20 .. now): 54099 commands (claude-code 41509, codex 5881, kimi-code 6709)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| lit | none | 10764 (19.9%) | 4149 | 6615 | 0 | 9560 (23.0%) | 138 (2.3%) | 1066 (15.9%) |
| lit | proposed | 8702 (16.1%) | 1702 | 7000 | 0 | 8210 (19.8%) | 74 (1.3%) | 418 (6.2%) |
| fix | none | 12099 (22.4%) | 4149 | 7950 | 0 | 10830 (26.1%) | 139 (2.4%) | 1130 (16.8%) |
| fix | proposed | 10075 (18.6%) | 1701 | 8374 | 0 | 9518 (22.9%) | 75 (1.3%) | 482 (7.2%) |

main itself refuses 1431 of 54099 (pass 1/2, unchanged by this PR)

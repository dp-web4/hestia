# Fleet deployment

This folder is the lab notebook of Hestia going onto the dp-web4
machines. Not a rollout — a sequence of probes.

- `cbp/README.md` — first probe (CBP, the oversight machine, done)
- `fleet/replication-plan.md` — order of operations for the rest of
  the fleet, why each machine in that order
- `templates/hestia.service` — copy this into `~/.config/systemd/user/`
  on Linux machines; per-machine env via `%h` substitution
- `templates/` — drop-ins for other machine types as we add them
  (`io.hestia.tools.plist` for McNugget, etc.)

The pattern at every stage:

1. Install daemon
2. Wire whatever agent runs on the box (Claude Code, ARC solver,
   custom worker)
3. Let it accumulate witness data
4. Read the chain — what did the agent actually do? What surprised us?
5. Decide the next move based on what showed up, not what we
   thought would show up.

Hestia is the substrate that makes step 4 cheap. The whole point of
the deployment is steps 4 and 5.

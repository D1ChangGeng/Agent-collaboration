---
kind: guide
status: active
scope:
  - ".agents/manifest.json"
  - ".agents/config.yaml"
  - "assets/scaffold/.agents/README.md"
  - "assets/scaffold/.agents/config.yaml"
use_when:
  - "changing ACHP runtime semantics"
  - "designing a handoff, relay, or repository synchronization flow"
  - "checking whether a state belongs in runtime, coordination, repository, or knowledge storage"
review_when:
  - "a new adapter, broker, daemon, or persistent state plane is proposed"
---

# Four runtime planes

ACHP separates:

1. **Execution Plane** — sessions and agents perform actual work.
2. **Coordination Plane** — roles, tasks, handoffs, and relay envelopes.
3. **Repository State Plane** — branch, commit, push, fetch, pull, and exact
   receiver baseline.
4. **Knowledge Plane** — durable, reviewed project knowledge under
   `.agents/knowledge/`.

Harness-specific adapters are optional edges around these planes. An adapter is
not protocol authority and must not become a prerequisite for normal work.

# Local versus durable state

Harness/session context holds machine-local capability observations. It is not a
project surface or universal source of truth. In contrast, `.agents/knowledge/`
is the project-level shared Knowledge Plane and can be committed when the
finding passes the future-action-value test.

The installed scaffold under `assets/scaffold/.agents/` is a template for other
projects. The root `.agents/` tree is the state of this repository itself; never
write this project's development knowledge into the template.

# Setup lifecycle invariant

```text
agent-collaboration-setup
        -> bootstrap/adopt/upgrade/repair
        -> AGENTS.md + .agents/
        -> Skill exits the normal runtime chain
```

`runtime_dependency_on_setup_skill` must remain false. Default uninstall removes
setup-managed files while preserving project-owned knowledge unless an explicit
purge is requested.

# Verification

Use the setup validator for structural state and inspect the manifest for the
runtime dependency boundary. Use `kb check` for Knowledge Plane structure. For a
runtime change, verify both the root project and the scaffold template remain
consistent where intended.

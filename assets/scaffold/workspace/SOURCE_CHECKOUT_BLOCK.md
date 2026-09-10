<!-- ACHP-SOURCE-CHECKOUT:BEGIN -->
## Local source checkout and Git working directory

- Local source checkout relative to this Management Root: `{{SOURCE_CHECKOUT_RELATIVE}}`.
  Resolve this path from the directory containing this `AGENTS.md`, then use
  the resolved source checkout as the repository working directory.
- Run repository synchronization, `fetch`, `pull`, `status`, `diff`, `add`,
  `commit`, `merge`, and `push` with the working directory set to that local
  source checkout. This also applies when the Agent session starts in the
  Management Root. Change the command working directory or use
  `git -C <resolved-source-checkout> ...` explicitly.
- The Management Root scopes coordination and knowledge files; the containing
  source checkout scopes Git operations for both product and management files.
  Verify branch, HEAD, working-tree state, and upstream before synchronization.
<!-- ACHP-SOURCE-CHECKOUT:END -->

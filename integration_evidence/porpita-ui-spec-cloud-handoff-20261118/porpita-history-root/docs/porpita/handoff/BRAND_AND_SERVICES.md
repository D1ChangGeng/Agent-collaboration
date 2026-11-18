# Porpita identity and service inventory

| ID | Product surface | Ownership and default |
| --- | --- | --- |
| B01 | Visible name and onboarding | Porpita. The app keeps the inherited workbench and native Provider labels. Device pairing opens its local code flow. |
| B02 | Windows executable, installer, shortcut and uninstall | Porpita, using the bundled Porpita icon family. The actual signature state is recorded alongside each installer hash. |
| B03 | App identity and deep links | `io.github.d1changgeng.porpita`, `porpita:`. The app owns a separate single-instance namespace. |
| B04 | Data | Own Porpita profile, logs, private ACS/Python/PostgreSQL storage and encrypted Agent/Client credentials. The NSIS default keeps user data on uninstall. Explicit history/profile import copies selected sources. |
| B05 | CLI, daemon and public skills | `porpita`, `porpitad`, `porpita-orchestration` and `PORPITA_CLI_COMMAND`. The host retains internal compatibility commands used by installed adapters. |
| B06 | Updates | Manual installer. `src/shared/porpita-product.json` sets `updateEndpoint: null`; packaging and updater use that setting. |
| B07 | Telemetry and crash reports | No configured collector or crash endpoint in the candidate. See observability initialization and product settings; local diagnostics remain available. |
| B08 | Account, push, feedback, support | The app does not need a product account for workspaces or ACS. Product-owned services require their own endpoints. Existing service login uses the address and user key provided by the operator. |
| B09 | Remote runtime and dependencies | The shipped server template uses pinned Node assets and the Porpita runtime. Windows private Core, Python, PostgreSQL and initial Harnesses ship in the package. Provider and upstream dependency provenance is locked. |
| B10 | Model, Git and user SSH providers | Existing provider workflows keep their own endpoints and user credentials. SSH targets are user configured. |
| B11 | Licensing | The inherited Orca MIT notice, ACS Sustainable Use License 1.0 and actual bundled dependencies' notices remain in the release materials. |
| B12 | Wire names and data formats | Internal `orca` authority, Native input owner, session storage formats and DTO names remain as compatibility identifiers. |
| B13 | Plugin API | Inherited globals such as `window.orca` remain available to compatible plugins. The desktop product does not depend on a separately shipped Orca plugin. |
| B14 | Provenance | Orca 1.4.214 source `26179069b664b2fc172963564ed419d97892b6c9`. The ACS Core build is pinned to the base plus nine exact overlays; these changes are also available in `c6bf795be35cc1db8a444ff07837a46009ae99e0`. |
| B15 | Product version and artifact | Porpita `0.1.0`. Windows x64: `Porpita-0.1.0-windows-x64-setup.exe`. |

The Windows run and verified cross-target build resources are recorded separately. An unsigned internal candidate does not imply a public distribution channel.


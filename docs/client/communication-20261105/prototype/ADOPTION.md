# ACS correspondence reading prototype

This is a local, interactive design demonstration. All messages are authored fixtures. Sending appends one message to local memory; no ACS/Core request is made, no Agent is actually invoked, and refresh resets sent messages. Drafts are stored per peer in browser localStorage when the host permits it.

## Mature foundation

Pigi, `whycatdothis/pigi`, commit `7f8e1c629460599737306b0692802ac036166d4c`, Apache-2.0. The exact source is retained under `vendor/pigi`. `LICENSE-PIGI` travels with the offline build. Tabler SVG icons are from the installed `@tabler/icons` package under MIT; `LICENSE-TABLER` travels with the build.

The Pigi official website is itself a presentation port of its application. This prototype adopts that presentation in static HTML plus a vanilla state adapter, rather than running Pigi's Electron/React runtime. It does not claim to run the complete upstream application.

Adopted source responsibility:

- `website/src/components/app/AppWindow.astro`: straight sidebar/main join, single-background application canvas, 44px toolbar, column and composer relationship. The ACS target fills the browser viewport. The source trial retains the original 1200×800 desktop geometry and window decoration.
- `Sidebar.astro`: 244px sidebar, 32px rows, 8px side padding, project hierarchy and selected-row material. The ACS Client replaces sessions with projects, Route navigation and authorized peers.
- `demos/Transcript.astro`, `ViewModes.astro`, `src/renderer/src/lib/layoutConstants.ts`: centered 860px column, 20px inline padding, 24px top inset, 32px end inset; 820px composer.
- `AssistantMessage.astro`, `UserMessage.astro`, `MessageActions.astro`: assistant text directly on the canvas, right-aligned short user bubble with 85% maximum width, 15px reading type, bubble spacing, message action family. Author labels and reply references use the communication fixture.
- `ChatInput.astro`, `website/src/lib/appUi.ts`: complete composer contour, semantic radius, fine border, shadow, spacing and action row. The model controls are replaced with ACS recipient, explicit reply target and delivery choice.
- `src/shared/designTokens.css`, `semanticTokens.css`, `website/src/styles/global.css`: retained tokens, typography, markdown rhythm, colors, hover/focus and tooltip treatment. The source files are copied unchanged. Stylesheet import paths remain source-relative inside the vendor tree.

`app.js` keeps these source class strings and composes them through the `appUi.ts` constants. Tailwind 4 compiles the selected presentation into the standalone HTML. Source preservation establishes implementation provenance; screenshot and continuous-use evidence establish the observed reading experience. The concrete UI remains a candidate for user review.

## ACS reading adapter

The study explores communication and explicit reply reading for ACS. Its product-specific controls cover the full/focus scope strip, directed reply closure, inline reply preview and additional-parent jump, return-to-reading anchor, loaded-range explanation, optional context and collapsible sidebar. They use the selected Pigi visual system, action classes and surface tokens. Long outgoing reports share the full reading column: outbound content longer than 300 characters uses the source bubble treatment at full column width, while short outbound messages retain Pigi's 85% cap. This threshold is a prototype convention to evaluate double-sided long-form reading.

Fixture records project the Core v2.3.1 communication model using `id`, `sequence`, `from`, `to`, `content`, and `reply_to` (array); a live adapter must preserve the original Core handles. The projection is a Client view over current actor↔peer messages, ordered by sequence. The final fixture includes `m9`, an outgoing reply to merged message `m6` that only discusses the separate permission audit. It remains in focus from `m1` through the explicit successor chain; the other original `m2` body remains a separate reference. This expresses explicit relationship reachability. Core communication history, this Client projection and Harness native sessions retain their separate meanings.

## Running and reproducible states

Open `dist/index.html` directly. It has all CSS, JS, icons and fixtures inline and does not fetch runtime assets. `npm run serve` serves the same build at `http://127.0.0.1:4178` when HTTP is useful.

- Full: `index.html` (Alt+1 returns from focus).
- Focus: `index.html?view=focus&m=m1` (Alt+2 focuses #1).
- Partial: `index.html?range=partial&view=focus&m=m3`.
- Collapsed sidebar: `index.html?sidebar=closed`.
- Source comparison: `source-trial.html`, original Pigi website presentation geometry and representative original content. It is an adapter trial, not the original Astro runtime.

Click `聚焦回复` on a message. Click its inline quoted preview or `同时关联 …` to visit an original; `返回刚才` restores prior view and anchor. `完整往来` restores the full-view entry anchor. Focus keeps `reply_to` unchanged. Incoming-message `回复` creates an input chip. Clearing it starts a new message. Switch peer to exercise draft continuity; Reviewer provides an empty local-fixture state. Search acts on loaded peer messages. Range explains missing parents and can load earlier fixtures. Dark/light switch uses upstream tokens.

Rebuild: `npm install` then `npm run build`. Test: `npm test`. Browser verification: `npm run test:browser` uses the installed Windows Chrome in headless mode; its executable path in `test/browser.cjs` is environment-specific. Node 24 is used for the upstream TypeScript class module. The offline artifact is directly reviewable without those dependencies.

## Verification and limits

`test/graph.test.cjs` checks fixture legality, sequence sorting, exact #1 focus `[m1,m3,m4,m6,m9]`, unrelated-branch exclusion, multi-parent uniqueness, partial-range missing parents and reply eligibility. `test/browser.cjs` exercised the offline build in headless Chrome at 1440×1000 and 1100×900, including full/focus, both return anchors, per-peer draft and reading-state restoration, explicit reply chips, invoke/message-only local sends, partial loading, empty peer, outgoing Markdown, sidebar/context/search and the source trial. `verification/browser-results.json` records measurements and zero page errors/network requests. At 1440 the incoming content is 820px wide and long outgoing text is 792px within the full-column bubble's 14px side padding; at 1100 the measured reading width is 807px and composer width 815px. Full/focus/long-outgoing screenshots were visually reviewed. Native GUI observations and their evidence boundaries are recorded in the study's desktop verification note. Production authentication, cursor integration, delivery persistence and actual Agent invocation require Core integration and their own acceptance scenarios.

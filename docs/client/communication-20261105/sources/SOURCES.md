# Mature source research — ACS thread study

Research date: 2026-11-05. Scope: public implementation acquisition, license/dependency assessment and original-image inspection. This file does not select the final product UI or claim local runtime/owner acceptance.

## Decision-useful facts

| Candidate | Exact source | License | Useful reuse scope | Main cost / evidence limit |
| --- | --- | --- | --- | --- |
| Pigi 0.5.1 | whycatdothis/pigi @ 7f8e1c629460599737306b0692802ac036166d4c | Apache-2.0; original LICENSE and THIRD_PARTY_NOTICES retained | Coherent app shell, 244px sidebar, 44px toolbar, transcript, message bubbles, composer, type/color/role tokens. The official Astro demos import actual app tokens/layout constants and copy app class strings, with an upstream drift checker. | Lowest useful presentation boundary: website AppWindow + Transcript + app components; full Electron/PI runtime unnecessary. Our source snapshot has not been built. |
| T3 Code web 0.1.7 | pingdotgg/t3code @ a21d788752695764028e6d26ba924f3963e05806 | MIT; original LICENSE retained | ComposerSurface is a genuine pure React presentation block; index.css carries typography, surfaces, glass, message rhythm. Larger timeline and markdown sources acquired for comparison. | Current full timeline imports Effect, client-runtime/contracts, LegendList, stores and many agent-specific components. Adopting the full app is substantially larger than a fixture presentation trial. |
| Paseo app 0.15.0 | getpaseo/paseo @ 5d1a2c10f8a493e2329f3f9bee51dfb94ccd28af | Apache-2.0 except separately licensed third-party components; original LICENSE retained | Strong desktop/mobile conversation reference; actual message renderer and theme acquired. | Expo 57, React Native 0.86, React Native Web, Unistyles 3, Reanimated plus protocol/client contexts. Higher adaptation cost than Pigi for this web-only fixture. |
| OpenCode session-ui 2.2.5 | anomalyco/opencode default dev branch, metadata inspected without pinning/downloading implementation | MIT | Explicit markdown/message/timeline/dock-prompt exports; useful future alternative. | Solid + Kobalte + workspace packages + Effect. No original render inspected in this inquiry; not an adopted candidate. |

## Official sources

- [Pigi repository and README](https://github.com/whycatdothis/pigi/tree/7f8e1c629460599737306b0692802ac036166d4c); official website is **https://pigi.pink**, explicitly named by README and package homepage.
- [Pigi source license](https://github.com/whycatdothis/pigi/blob/7f8e1c629460599737306b0692802ac036166d4c/LICENSE).
- [Pigi original AppWindow](https://github.com/whycatdothis/pigi/blob/7f8e1c629460599737306b0692802ac036166d4c/website/src/components/app/AppWindow.astro).
- [Pigi original Transcript](https://github.com/whycatdothis/pigi/blob/7f8e1c629460599737306b0692802ac036166d4c/website/src/components/demos/Transcript.astro).
- [T3 official repository](https://github.com/pingdotgg/t3code/tree/a21d788752695764028e6d26ba924f3963e05806), linked by https://t3.codes.
- [T3 ComposerSurface](https://github.com/pingdotgg/t3code/blob/a21d788752695764028e6d26ba924f3963e05806/apps/web/src/components/chat/ComposerSurface.tsx).
- [Paseo official repository](https://github.com/getpaseo/paseo/tree/5d1a2c10f8a493e2329f3f9bee51dfb94ccd28af), linked by https://paseo.sh.
- [OpenCode session-ui package](https://github.com/anomalyco/opencode/blob/dev/packages/session-ui/package.json).

The geoqiao article was a discovery lead, not a rights grant or implementation source.

## Acquired local source

See source-inventory.json for every file present.

Pigi:
- LICENSE, README.md, package.json, licenses/THIRD_PARTY_NOTICES.md.
- src/shared/designTokens.css, src/shared/platform.ts.
- src/renderer/src/assets/semanticTokens.css, components/terminal/terminalTheme.css, lib/layoutConstants.ts, components/message/markdownMessage.tsx.
- website/package.json, src/styles/global.css.
- website/src/components/app/{AppWindow,AssistantMessage,ChatInput,MessageActions,ReadGroup,SessionToolbar,SessionTreeHelpButton,Sidebar,ThinkingBlock,ToolCard,UserMessage}.astro.
- website/src/components/demos/{Transcript,ViewModes,ViewModeMenu,SlashMenu,Minimap}.astro, components/Icon.astro.
- website/src/lib/{appLayout,appUi,appCopy,icons,sessions}.ts, scripts/interactions.ts.
- resources/hi-pigi.png: original official screenshot, successfully decoded and actually viewed.

T3:
- LICENSE, root and apps/web package.json.
- apps/web/src/index.css, components/{AppSidebarLayout,ChatMarkdown}.tsx.
- components/chat/{ChatCanvas,ComposerSurface,MessagesTimeline,TimelineAssistantRows,TimelineUserMessageRow}.tsx.

Paseo:
- LICENSE, packages/app/package.json, src/components/message.tsx, src/styles/theme.ts.
- packages/website/public/hero-mockup.png: original official marketing composite, successfully decoded and actually viewed.

Acquisition used the GitHub connector. A shallow Git clone failed because the configured local proxy was unavailable; direct DNS also failed. No repository checkout, node_modules install or original application run is claimed. Pigi minimal-view.png was requested, but the connector returned empty base64 for this larger file; it was not saved or viewed.

## Visually inspected original evidence

### Pigi hi-pigi.png

Official desktop screenshot; static short-session evidence, not a running ACS client. At whole-frame scale it has a quiet pale sidebar, thin toolbar separator, extensive clear reading space, a right-aligned user bubble, assistant text directly on the canvas and one softly elevated composer. There is only one dominant content column.

Source constants confirm 244px default sidebar, 860px message container with 20px inline padding (820px content), matching 820px composer and 24px top inset. The original screenshot supports that spatial relationship; it cannot establish long-message scrolling, disclosure timing or CJK quality.

Preserve the shared text/composer width, low-contrast surface hierarchy, assistant text without extra cards, quiet utility controls and source typography rhythm when adapting ACS content. Do not transfer model selection, timestamps or tool traces as ACS facts.

### Paseo hero-mockup.png

Official desktop/mobile marketing composite, static. The desktop gives substantial width to a source-control pane and a project/session rail; the central conversation mixes short muted tool rows and open prose. The phone overlay demonstrates mobile reading but obscures part of the desktop. It supports appearance only, not observed interaction, and its pane allocation is less aligned with ACS's central-reading goal. The picture is a reference; its source message renderer is not plug-and-play React DOM.

## Adoption and presentation trial

Pigi offers the highest coherent useful source boundary for this fixture study. The selected ACS adapter preserves its shell, reading column, composer and shared tokens.

The local source comparison route retains AppWindow, Transcript and the original assistant/user/composer presentation with representative source content. The ACS adapter uses the same shell and column with communication fixtures. The prototype's ADOPTION.md records the retained source responsibilities; research/ACS-DESKTOP-VERIFICATION.md records the actual comparison and continuous-use evidence. Concrete UI acceptance remains with the user.

Original website scripts: npm run dev => astro dev. website/package.json requires Node >=24; local node was checked as v24.20.0. Main relevant dev dependencies are Astro ^7.4.0, Tailwind ^4.3.3, @tailwindcss/vite ^4.3.3 and @tabler/icons ^3.49.0. An Astro trial needs a config with the original Tailwind plugin and a page entry; this snapshot is a selected source collection. The delivered offline comparison route is a static presentation adapter. The original Astro application runtime was not started.

The website AppWindow's fixed 1200x800 canvas, traffic lights and narrow-screen picture scaling describe an upstream product demonstration. They are not a verified responsive ACS application. Preserve/adapt the core shell relationships; test actual desktop viewports, short heights and CJK content in the ACS fixture.

## ACS semantic adaptation boundary

- Central complete correspondence is one ordered reading column.
- A focused related discussion is an explicit projection of the loaded reply graph, with return anchor and shared source message identity.
- Only sequence and explicit reply_to edges establish ordering/relationships. Multi-parent messages remain one message even when projected into several related views.
- Show the loaded history range; read_message's first clear reply is not all descendants.
- No fabricated message timestamps, native reasoning/tool activity or model/Harness state.
- Composer is fixture-only. No ACS sending, model or Harness connection.
- Delivery/notification details are light, on-demand ACS facts rather than a coding trace.

## Outstanding verification

Original source acquisition, actual adoption and retained visual craft are separate. The delivered prototype's ADOPTION.md, browser results and desktop verification note record the actual local trial, CJK long-report appearance, anchoring, focus/return and graph checks. Core integration, large histories, new-message continuity and final user acceptance retain their own verification scope.


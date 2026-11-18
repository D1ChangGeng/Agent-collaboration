# Windows visual research — 2026-11-05

This is research evidence for ACS conversation reading, reply context, history location and return. It does not choose the formal UI or establish owner acceptance. UI Spec Studio 1.20.6 and its eight common references were read; agent-desktop desktop/platform guides and observation/interaction/system references were read.

## Evidence boundary

- The six screenshots from the named August 2026 article were **not obtained or inspected**. Initial supplied raw filenames returned 404/SSL failure; opening the corresponding GitHub directory through web returned restricted URL. Research stopped on that directory and its raw paths as directed. No image or author preference is promoted to an observed product fact.
- Instead, actual pixels were inspected in the existing official Codex Windows and OpenCode captures, the independently acquired Pigi repository image, and three Discord official help images. These are separate versions/sources, not the six article screenshots.
- Screenshots are research references. They do not establish an implementation license or prove sticky behavior, animation, runtime performance, keyboard behavior, return restoration, long histories, or current product state.
- All GUI observations used one newly opened Chrome Incognito window. No existing private page contents were read. Existing window metadata was used solely to create the new window. No login, message, download of an app or commercial installation occurred.

## Most useful visual relationships

| Evidence | Actually visible | Research implication and boundary |
|---|---|---|
| [Pigi whole frame](pigi-source-hi-pigi.png), [center crop](pigi-center-crop.png) | About one fifth of app width is sidebar; main transcript has equal left/right insets and a wide aligned composer. A right-aligned user bubble is followed by a low-contrast thinking panel, an outlined command/result group, then plain final prose. Header and utility icons occupy a shallow band. | This provides a source-backed reading/composer relationship and a way to make tools subordinate to the final answer. The tiny example has only one short result; it leaves long reading measure, dense turns, overflow and sticky input unverified. |
| [Codex Windows whole frame](fallback-codex-official.webp), [center crop](codex-center-crop.png) | Sidebar is roughly 22% of app width. The main panel is wider than the actual text column: prose and composer align around a narrower central measure. Muted process lines lead to a horizontal `Worked for…` separator and darker result paragraphs, then a file-change summary and composer. | Large central workspace does not require text to fill every pixel. Hierarchy comes from contrast and spacing rather than a card around every turn. A static screenshot cannot establish scroll fixation or automatic process collapsing. |
| [OpenCode whole frame](fallback-opencode-official.png) | The review pane is approximately half the working surface; the response/composer occupy the remaining left pane. Prompt and response have different shapes; `Show steps` is small and separate from final prose. | Useful counterexample: a permanent auxiliary pane can consume enough width to constrain the principal reading surface. ACS should justify simultaneous inspection before inheriting this width allocation. No drag or pane-toggle behavior was operated. |
| [Discord reply context](discord-reply-context.png) | A one-line, subdued original-message excerpt sits above the later reply; a bent connector and small avatar associate it with the reply. The current speaker and reply body remain stronger. A date line separates chronological groups. | Keep an understandable relation to an older message without repeating its full body. This screenshot supports the association, not an implemented click-to-jump or back stack. |
| [Discord reply action](discord-reply-action.png), [composer target](discord-reply-composer.png) | Reply is a hover action on the message. The composer has an explicit `Replying to…` bar, a recipient-ping switch and a cancel icon. | Reply target is visible before sending and separable from notification behavior. These are 2020 help captures with explanatory overlays, not current application-wide measurements. |

Crop coordinates in original image pixels: Codex (558,84)-(1640,1095), source 1919×1145; Pigi (510,107)-(2422,1620), source 2454×1646. Crops preserve the main region rather than fabricate a new layout. Rough ratios describe depicted source pixels, not CSS measurements or a universal target.

## Native observation episode

Tool state: Windows accessibility granted; automation and screen recording not_required; adapter reports 1.1.0, envelope 2.6. New research window: **w-49942690**, Chrome process pid 37528. The tool server's global headed/session flags were not changed.

1. `launch --no-attach` for Edge and Chrome safely refused because each was already running. Default Edge attachment was ambiguous across helper PIDs. msedge_proxy launched but did not produce a confirmed research window; its launch is not claimed as successful navigation.
2. A known Chrome window was focused without reading its contents. Ctrl+Shift+N was delivered once; `wait event window-opened` independently confirmed **New Incognito Tab**, w-49942690. Prior unsuccessful focus attempts were not_delivered and retry safe.
3. In the new window, semantic set-value of the address bar followed by Enter reached **pigi.sh**. [Captured and viewed error](pigi-network-error.png): ERR_CONNECTION_CLOSED. This was the initially supplied wrong website; the correct official site, pigi.pink, was later established from Pigi README. No GUI claim about pigi.pink is made.
4. Semantic address-bar navigation reached [Discord Replies FAQ](https://support.discord.com/hc/en-us/articles/360057382374-Replies-FAQ). [Before-scroll viewport](discord-help-before-scroll.png) was captured and viewed at 1920×2160 physical pixels, display scale 1.5. The article title, introductory explanation and part of the official message example were visible. This is a carrier help page, not a Discord chat session.
5. Scroll on its document ref returned ACTION_FAILED: live offscreen true / Invalid scroll viewport metrics, not_delivered, retry safe. [After-scroll viewport](discord-help-after-scroll.png) was captured and viewed; it remains at the same document position. No scrolling or app-level reply interaction was established.
6. Native ownership was handed back to root after all pending calls ended. Last page: Discord Replies FAQ. Last address ref was @sz4qbtu4kf9sj:e12; the next operator should take a fresh snapshot.

## History and unread: documented versus observed

- Discord [Replies FAQ](https://support.discord.com/hc/en-us/articles/360057382374-Replies-FAQ) describes reply entry through hover/menu and the ping toggle. The three downloaded help images were actually viewed. [Inbox FAQ](https://support.discord.com/hc/en-us/articles/360045027712-Inbox-FAQ) describes Unreads/Mentions and a Jump action that opens the source channel. This is published behavior, not a personally operated account flow; the page also warns that inbox layouts may vary in experiments.
- Telegram [Replies 2.0](https://telegram.org/blog/reply-revolution), dated October 28, 2023, describes tapping a quote to focus the exact passage and cross-chat replies opening their source when access permits. [Mentions API guidance](https://core.telegram.org/api/mentions) describes a blue mention indicator, separate unread mention count, and an in-chat @ button for navigating mention history. These pages were read as primary text. No Telegram product render, continuous video or account interaction was observed this round.
- Neither of those documents establishes the precise back/return experience required by ACS. A claim that the product restores the original viewport or maintains a stack of jump origins remains unverified here. QQ/WeChat were not investigated in this bounded round.

## Source and acquisition

- Pigi: https://github.com/whycatdothis/pigi ; official site confirmed in README as https://pigi.pink ; actual local source image `../sources/pigi/resources/hi-pigi.png`; repository LICENSE inspected as Apache 2.0. Code availability is a possible adoption route; retained craft still requires current-project trial. The image alone is not proof that a copied implementation is integrated.
- Codex and OpenCode captures came from the previous research directory: `D:/Chatgpt/Agent-collaboration/docs/client/review-20261105/research`. Their prior research note retains original official provenance; copied unchanged into this folder for inspectability.
- Discord official attachments: context https://support.discord.com/hc/article_attachments/360099599573 ; action https://support.discord.com/hc/article_attachments/360099594313 ; composer https://support.discord.com/hc/article_attachments/360099600013 . Downloaded and viewed. Treat as reference-only; no reusable code rights established.

## Decision-useful remaining question

The local ACS trial should test an actual episode: read an older message → select reply/quote context → jump to its origin → see a localized target highlight → return to the departure position → retain draft and reply target while a new message arrives. Follow-live versus inspect-history are separate intentions. This is a proposed verification question, not an observed mature-product behavior or authorization to construct new visible UI.

---
name: Campus Care
description: A warm, paper-toned campus facilities reporting application.
colors:
  navy: "#172b42"
  navy-soft: "#243b55"
  paper: "#f5f1e8"
  paper-deep: "#ebe5d7"
  white: "#fffdf8"
  ink: "#202c35"
  muted: "#6b7478"
  line: "#ded8cb"
  coral: "#c85a45"
  coral-light: "#f4e3dc"
  teal: "#287869"
  teal-light: "#e2eee8"
  gold: "#c79a2c"
  gold-light: "#f4edcf"
  danger: "#a63f39"
  focus: "#dfab40"
typography:
  display:
    fontFamily: "Newsreader, Georgia, serif"
    fontSize: "clamp(36px, 4vw, 54px)"
    fontWeight: 500
    lineHeight: 1.06
    letterSpacing: "-.035em"
  body:
    fontFamily: "DM Sans, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "DM Sans, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    letterSpacing: ".13em"
rounded:
  control: "5px"
  button: "6px"
  navigation: "7px"
  card: "8px"
  auth-card: "9px"
components:
  button-primary:
    backgroundColor: "{colors.teal}"
    textColor: "#ffffff"
    rounded: "{rounded.button}"
    padding: "0 16px"
    height: "43px"
  button-secondary:
    backgroundColor: "{colors.white}"
    textColor: "{colors.navy}"
    rounded: "{rounded.button}"
    padding: "0 16px"
    height: "43px"
---

## Overview

Campus Care is an operate-first facilities reporting UI: familiar navigation and controls carry the work, while a restrained campus noticeboard character comes through in warm paper tones, dated report markers, and a serif headline voice. Keep the interface scan-friendly and practical; the noticeboard is an atmosphere for a standard application, not a replacement for its navigation or task controls.

The branded mark is a small inline building SVG, not a supplied university logo. The implementation uses no paper grain, campus map, or decorative photography. Report photos appear only when attached to a report. Demo reports and demo locations are explicitly identified as illustrative rather than verified campus data. The admin workspace includes people/access, a managed building-and-room directory, service analytics, and system settings.

## Colors

The CSS custom properties in `static/css/app.css` are the source of truth:

- **Campus anchor:** `navy` (`#172b42`) anchors the sidebar, headings, and primary text accents; `navy-soft` (`#243b55`) is a defined companion.
- **Paper and reading surfaces:** `paper` (`#f5f1e8`) is the page canvas, `white` (`#fffdf8`) the main card/list surface, and `paper-deep` (`#ebe5d7`) a defined deeper paper tone. `ink` (`#202c35`), `muted` (`#6b7478`), and `line` (`#ded8cb`) carry text and separators.
- **Department accent:** `teal` (`#287869`) is the primary action, link, and progress accent; `teal-light` (`#e2eee8`) provides its quieter companion surface.
- **Notice and urgency accent:** `gold` (`#c79a2c`) appears in demo markers and report-note dots; `coral` (`#c85a45`) accents the error page. `gold-light` (`#f4edcf`), `coral-light` (`#f4e3dc`), and `danger` (`#a63f39`) are also declared.
- **Focus:** `focus` (`#dfab40`) is the high-contrast keyboard outline color.

`navy-soft`, `paper-deep`, `coral-light`, `gold-light`, and `danger` are declared palette values but are not referenced by current component rules; treat them as inactive until implementation uses them.

Some state colors are literal component values rather than custom properties. Keep those paired tones and visible text labels together:

| State | Foreground | Background |
| --- | --- | --- |
| New report | `#9a6e19` | `#f7efd7` |
| Assigned | `#426d77` | `#e4eef0` |
| In progress | `#326e5f` | `#e2eee8` |
| Resolved | `#667167` | `#e9eee7` |
| Low priority | `#477362` | `#e5eee6` |
| Normal priority | `#6f653d` | `#f1eddd` |
| High priority | `#8f4e28` | `#f7e9d5` |
| Urgent priority | `#a33e36` | `#f5e1dc` |

Default flash messages use green (`#275b4c` on `#e5f0e8`); error flashes use red (`#8f4038` on `#f6e8e3`). Demo badges and notice strips use muted gold. The latest-progress strip is a subdued paper tint (`#f3f0e5`) with green-gray text (`#56675e`) and a gold date (`#85794f`). The settings switch is gray (`#d3d1c7`) when off and teal when on; the density control uses a pale green active/pressed state (`#e4eee6`). Status chips include a dot, and status/urgency labels remain visible so color is not the only signal.

## Typography

**Display Font:** Newsreader, Georgia, serif
**Body Font:** DM Sans, Segoe UI, sans-serif

The pairing balances editorial warmth in prominent headings with a compact, familiar sans-serif for operational details. Newsreader and DM Sans are requested from Google Fonts; the listed local/system fallbacks remain in use if those fonts are unavailable.

### Hierarchy

- **Display / page headline** (500, `clamp(36px, 4vw, 54px)`, line-height 1.06): page titles and the authentication heading; report-detail titles use a slightly narrower `clamp(32px, 3.5vw, 46px)` range.
- **Section title** (Newsreader 500, 23–27px): section and form headings.
- **Item title** (Newsreader 500, 16–18px): report titles in the list.
- **Body** (DM Sans 400, 16px, line-height 1.55): base text. Supporting copy uses 14–16px; detail descriptions use 16px with 1.8 line-height.
- **Label and metadata** (DM Sans, 14–16px; labels often 700 weight): field labels, dates, status, and reference metadata. Keep compact metadata at 14px, with overlines using uppercase and loose tracking (commonly `.1–.14em`).

## Layout

The signed-in shell is a two-column workspace: a 252px sticky navy sidebar and a flexible main region. The top bar is 66px high, with breadcrumb and account/demo controls; page content is centered at a maximum width of 1440px with fluid horizontal padding. At widths of 1500px and above, top content padding and report-row height increase slightly.

The default spacing is generous around page headings and sections, with tighter, repeatable gaps within forms, lists, and metadata. Page content uses 43px top padding and `clamp(22px, 5vw, 72px)` horizontal padding on larger screens; paper forms and detail surfaces use `clamp(20px, 3vw, 33px)` padding. Report rows are at least 91px high on desktop, with date, summary, state, and disclosure affordance in distinct columns.

### Responsive behavior

- At **1050px and below**, the sidebar narrows to 220px, page gutters reduce, and form/detail side columns tighten.
- At **780px and below**, the shell becomes single-column. Navigation becomes a 270px off-canvas drawer controlled by the menu button; clicking outside closes it. The top bar shortens to 58px, and form/detail layouts stack. Form-aside notes and detail actions can share a two-column arrangement.
- At **560px and below**, gutters shrink again; headings, forms, and side panels stack. Report rows compact into date/content/arrow columns, with status moved below the title. Search spans the tools row; status, issue-type/location, and density controls share a two-column tool grid. Analytics becomes a single-column reading flow, its summary ledger becomes two columns, and the date-range action spans the form. Location entry and response-target fields stack for a narrow screen. Progress and metadata remain legible at the compact 14px minimum. The file browse affordance is hidden while the upload label remains.
- The document has a 320px minimum viewport width.

The signed-out authentication page uses the same palette and type, with a centered card up to 440px wide instead of the sidebar workspace.

### Accessibility and motion

Use the existing semantic heading order, labeled search and filter controls, navigation label, descriptive link names, and flash-message live/status announcements. The density control exposes its pressed state with `aria-pressed`; report rows are hidden when filters exclude them and a no-match message appears. The location selector groups rooms under building labels, and unavailable directory state explains why new reports cannot be submitted. Work logs are visible only to authorized maintenance staff and administrators, never on public detail pages. Response targets are optional until an approved value is configured; analytics does not infer overdue work without one. Decorative inline icons are hidden from assistive technology. Keyboard focus is generally shown with a 3px gold outline and 3px offset; text inputs instead use a teal border and soft teal focus halo, and custom checkboxes and settings switches outline their visual controls. The search input currently suppresses its native focus outline without a corresponding focused style on its wrapper, and the filtered-list/no-match updates are not announced through a live region.

Transitions are short and state-focused: buttons lift by 1px on hover, links and rows change color/surface, and the mobile drawer slides. `prefers-reduced-motion: reduce` disables smooth scrolling and reduces transitions/animations to near-zero duration.

## Elevation & Depth

Depth is mostly tonal: off-white panels, warm page paper, fine borders, and restrained color blocks establish grouping without a card-shadow stack. The top bar uses a translucent paper fill, bottom rule, and 12px backdrop blur. The mobile drawer has a stronger shadow to separate it from the page; transient flash messages use a soft navy-tinted shadow. Do not add elevation to every surface.

## Shapes

The shape language is quietly rounded, not pill-based: controls are usually 5–6px, navigation and list containers 7–8px, and the auth card 9px. Status and urgency chips are compact, with 3–4px corners; circular dots, avatars, and progress markers are reserved for indicators. The building mark has its own asymmetrical rounded-square silhouette. Borders are thin and warm gray; the photo upload zone is the notable dashed outline.

## Components

### Buttons

- **Shape:** 6px corners; 43px minimum height, 16px horizontal padding.
- **Primary:** teal fill with white text; hover deepens the teal and lifts the button by 1px.
- **Secondary:** warm-white fill, navy text, and a muted border; hover warms the fill and strengthens the border.
- **Quiet:** transparent with subdued text; hover adds a light paper surface.
- **Focus:** use the shared visible gold outline.

### Chips and status

Status chips use a small colored dot, a paired pale fill, and a readable text label. Urgency chips use the same compact grammar, with warm brown for high and red for urgent. Demo/live badges are small contextual markers rather than actions; the live account state is teal, demo state gold.

### Report list tools

The list toolbar combines issue search, a status select, a grouped issue-type/location select, and a compact-density button. Search matches report title, location, category, or reference; the selects filter by status and by either category or location. The density control starts with the comfortable list and reads “Compact list”; when pressed it changes the report list to compact rows and changes its own label to “Comfortable list.” The pressed style is pale green. Compact rows reduce their minimum height from 91px to 67px, reduce date/title sizing and tighten the progress strip; the view is session-local and has no persisted preference.

### Latest-progress strip

Private report/work rows show a slim, warm-gray-green strip below location and priority when a latest update note exists. It pairs the update date with a single-line, clipped note. It is omitted from public-board rows. This preview complements—not replaces—the full dated update timeline on the private report detail view.

### Cards and containers

Paper forms, report details, action panels, authentication cards, and report lists use warm-white surfaces with fine beige borders and restrained 7–9px corners. Keep content groups separated with padding, dividers, and color rather than stacked shadows. Empty states use a dashed border and a quiet icon field.

### Inputs and fields

Labels sit above familiar full-width controls. Inputs are at least 42px high, use a near-white fill, a 1px warm-gray border, and 5px corners; focus changes the border to teal with a soft halo. Textareas resize vertically. The photo picker is a dashed drop zone, and the anonymity option is a custom checkbox with a visible checked mark and keyboard outline.

### Navigation

Desktop navigation is a persistent dark sidebar with icon-and-label links. Student/lecturer links include their reports, the campus board, and new report; maintenance has a work queue and campus board; admins also have people/access and system settings. Hover uses a lighter navy surface; the current destination is white on a brighter navy surface with a narrow gold leading bar. On small screens the same navigation becomes a dismissible drawer; retain the labeled menu button and its expanded state. The sticky top bar keeps breadcrumb and account context in a standard application pattern.

### Admin system settings

Settings are presented in a bordered warm-white panel, with one full-width row per visibility switch and a separate save footer. The shipped controls toggle public campus-board access and whether anonymous reporting is offered; each uses a native checkbox visually rendered as a 38×22px rounded switch, gray off and teal on, plus an explicit On/Off label. Approved urgency response targets are plain numeric hour fields; blank means no overdue target. A gold focus outline highlights the switch track. On narrow screens the rows align to the start, response targets become a two-column label/input list, and the save note and button stack with the button full width.

### Campus location directory

Administrators add and deactivate building/room entries in a straightforward ledger. The report form uses a native select with optgroups by building and room options inside each group. Deactivated locations remain on historical reports but are omitted from new-report choices. Demo entries are visibly labeled illustrative and must not be treated as an approved UPSA catalog.

### Service analytics

The admin analytics page uses a date-range form, a ruled definition-list summary, and plain grouped lists for recurring categories/locations and overdue reports. It does not use a chart or imply a target where none was approved. Overdue rows link to private report detail and only appear when an urgency response target has been configured.

### Maintenance work logs

Authorized maintenance staff and admins add visit entries from the private report detail: labor minutes, parts/materials, a required completion note, and an optional follow-up date. Entries are chronological, attributed, and private to facilities roles; the public board and reporter-facing detail do not expose parts or labor notes.

### Dated progress timeline

The report detail view presents updates as a vertical, ordered timeline: a thin connecting rule, muted circular markers, and a teal-emphasized first entry, with status and timestamp on each entry. Keep each update attached to its report and preserve the date/status pairing.

## Do's and Don'ts

### Do:

- **Do** keep the noticeboard character in warm paper tones, dated report markers, and restrained department teal while preserving ordinary application navigation and controls.
- **Do** keep status and urgency text visible alongside their color chips.
- **Do** keep public board summaries separate from private reporter details; the public view is designed not to expose those details.
- **Do** identify illustrative/demo reports as samples, not verified campus records.
- **Do** keep the dated progress timeline visually attached to its report.

### Don't:

- **Don't** invent a university logo, campus map, real report, testimonial, or supplied photographic asset.
- **Don't** turn the interface into a literal bulletin-board illustration or replace standard controls with decorative treatments.
- **Don't** treat currently unused palette declarations as established component states without implementation evidence.
- **Don't** assume a dark theme; the shipped stylesheet declares a light color scheme.



Name: bmsoheneba
Email: bmsoheneba@gmail.com
Password: 1realoheneba1.
# DESIGN.md — Supermarkt-Preisvergleich

Extracted from the existing UI (branch 3: implicit design system) before the
iteration-7 redesign. Every colour, size, and spacing value in the UI must
trace to a token here.

## 1. Principles

1. **The price is the content.** Results are a price list with unit prices, not
   a card gallery; prices use tabular numerals and the largest type on the card.
2. **One primary action per screen.** Search is the primary action; every other
   control is secondary or tertiary.
3. **Calm utility.** No hero imagery, no gradients as decoration, no motion
   without a cause. The product is used weekly, often on a phone in a shop.
4. **Honest states.** Empty, loading, error, partial-coverage and "no baseline"
   are all designed, never silent.
5. **Accessible by default.** WCAG 2.2 AA in both themes; the data reads at
   320 px without horizontal scrolling.

## 2. Colour

Single accent (green = savings/grocery). Neutrals are one cool-grey ramp.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f6f7f5` | `#0e1110` | Page background (slightly warm-neutral) |
| `--surface` | `#ffffff` | `#161a18` | Cards, inputs |
| `--surface-alt` | `#eef0ec` | `#1e2320` | Chips, secondary buttons |
| `--text` | `#191d1a` | `#e9eee9` | Body and headings |
| `--muted` | `#5b6560` | `#9aa8a0` | Labels, meta (≥4.5:1 on bg) |
| `--line` | `#dfe3dd` | `#2a302c` | Hairlines, dividers |
| `--accent` | `#0f6b46` | `#3fc284` | Primary action, savings, links |
| `--accent-contrast` | `#ffffff` | `#052112` | Text on accent |
| `--danger` | `#a5271d` | `#ff9188` | Errors, expired |
| `--amber` / `--amber-bg` | `#7a4a05` / `#fbf0d2` | `#f7cf6b` / `#372a09` | Preview, partial |
| `--info` / `--info-bg` | `#145070` / `#e3f1f8` | `#a9d6ef` / `#12303f` | Standard/community price |

Store badges keep the retailer's own brand colour (identity, not decoration).

## 3. Typography

- **Display / h1 / h2:** `ui-serif, Georgia, "Times New Roman", serif`,
  weight 600, tracking `-0.02em`. Gives the tool an editorial voice without a
  webfont request (the UI must stay self-contained).
- **UI / body / data:** `system-ui, -apple-system, "Segoe UI", Roboto,
  "Helvetica Neue", Arial, sans-serif`.
- **Numbers:** `font-variant-numeric: tabular-nums` on every price, unit price,
  sum and count.
- **Scale (≥1.25× between heading steps):**
  | Role | Size | Weight |
  |---|---|---|
  | Display h1 | `clamp(2rem, 4vw, 2.75rem)` | 600 |
  | Section h2 | `1.5rem` | 600 |
  | Card h3 / product | `1.05rem` | 650 |
  | Body | `1rem / 1.55` | 400 |
  | Small / meta | `.85rem` | 400 |
  | Label (uppercase) | `.75rem` + `.06em` tracking | 600 |
- Body measure: 62ch maximum for prose blocks.

## 4. Layout

`Layout: single-column document shell (max 1120px) → search panel (2-col grid, 1-col < 720px) → chips row → full-width result list grid → recipes grid (auto-fit 260px) → optimizer panels (2-col ≥ 900px) → footer.`

- Space above a section heading ≥ 1.5× the space below it.
- Group gap ≥ 2× internal gap (list rows 14px, groups 32px).
- Cards carry hairlines, not heavy shadows; nested cards are forbidden.
- Touch targets ≥ 44px; pointer targets ≥ 24px.

## 5. Components (primitives + states)

| Primitive | Source | States |
|---|---|---|
| `button.primary` | project kit | default, hover, active, focus-visible, disabled/loading |
| `button.secondary` | project kit | default, hover, active, focus-visible, disabled |
| `.action-btn` (card action) | project kit | default, hover, focus-visible |
| `.store-chip` | project kit | unchecked, checked, hover, focus-visible |
| `.switch` | project kit | off, on, hover, focus-visible |
| `.offer` (result row) | project kit | prospect, standard, community, expired |
| `.validity` badge | project kit | today, upcoming, expired, standard, community |
| `.chip` (quick filter) | project kit | inactive, active (exclusion), focus-visible |
| `.recipe` | project kit | default, hover (button only) |
| `.share-bar` | project kit | default; `.copy` → copied |
| `.modal` | project kit | closed, open, error |
| `.modal--detail` + `.range-tabs` | project kit | tab selected/unselected, focus-visible |
| `.verdict` | project kit | top, good, expensive, unknown/building |
| `.metric` (price stats) | project kit | default, highlight |
| `.chart` (SVG step line) | project kit | empty, 1 point, series, average line |
| `.offer-media` / `.detail-media` | project kit | image, category placeholder, broken image |
| `.admin-block` | project kit | default, status ok/error, disabled action |
| `.review-item` (moderation) | project kit | plausible, flagged, actions |
| Admin table (`/admin`) | project kit | default, hover, empty, pager |
| Edit dialog (`/admin`) | project kit | open, error, saving |
| `.drawer` | project kit | closed, open |

Icons: inline SVG (stroke 1.75, currentColor). Emoji are not used as icons.

## 6. Motion

- Only for feedback: hover/press transitions 120–200 ms, `transform`/`opacity`.
- Listening state pulses; under `prefers-reduced-motion` it becomes a static
  outline.
- No scroll animation, no entrance animation.

## 7. Surfaces

- Flat surfaces + 1px hairline + one soft shadow token for the search panel.
- No glass/blur, no neumorphism, no gradient decoration.
- Standard-price rows are marked by a tonal wash
  (`color-mix(in srgb, var(--info) 6%, var(--surface))`), never by a coloured
  side stripe.
- Browser surfaces themed: `::selection`, `caret-color`, `scrollbar-color`,
  `:focus-visible` ring, underline offset.

## 8. Accepted debt / constraints

- **No system OCR** (Tesseract absent): image receipts answer 503 by design.
- **No websafe display webfont**: self-containment test forbids external font
  requests, so the serif display uses a system serif stack.
- **Screenshots**: no headless browser engine is installed in this
  environment; the before/after evidence is computed-value probes
  (`getComputedStyle`) plus DOM structure checks, recorded in the iteration
  report.

## 9. Gap ledger (iteration 7)

| ID | Gap | Rule | Fix |
|---|---|---|---|
| G1 | Standard-price cards use `border-left: 3px solid` | Draft guard: no coloured side stripe | Tonal surface + badge |
| G2 | Emoji as icons (mic, basket, badges) | Icons: one SVG set, never emoji | Inline SVG sprite |
| G3 | Headings in system sans, no display voice | Redesign: headlines lack presence | Serif display + tighter tracking |
| G4 | No `::selection`, `caret-color`, `scrollbar-color` | Craft floor: browser surfaces | Themed from tokens |
| G5 | Header uses a decorative gradient | Draft guard: dated surface | Flat surface + hairline |
| G6 | No skip link | A11y: keyboard entry | `Zum Inhalt springen` |
| G7 | Prices in proportional figures | Craft floor: tabular numerals | `font-variant-numeric` |
| G8 | No meta description / favicon | Redesign checklist | Meta + inline SVG icon |
| G9 | Recipe cards + nested cards read as card soup | Cards only for hierarchy | Hairline sections, fewer boxes |
| G10 | Body copy unbounded measure on desktop | 65–75 characters | `max-width: 62ch` on prose |
| G11 | No price-history surface | Product detail + chart | Modal with tabs, metrics, verdict |
| G12 | Stealth build had no index/access story | SEO + gate | robots/noindex meta, login gate |
| G13 | Cards were text-only ("kahles" design) | Product imagery | 84 px media tile, lazy loading, category placeholders |
| G14 | No admin path for backup/restore | Operations | Footer "Admin" dialog with download/restore |

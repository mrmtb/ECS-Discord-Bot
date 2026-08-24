<!-- Hallmark · genre: playful · macrostructure: per-page (see § 12) · theme: custom "Sunday league, Sunday paper" · nav: N1b + season chip · footer: Ft8 · display: Big Shoulders · ground: cool newsprint · photography: untreated · pre-emit critique: P5 H5 E5 S5 R5 V5 -->

# Design — ECS Pub League public site

**Locked design system.** Every public-facing surface defers to this file. Nine
implementation owners read it independently and must produce visually identical
work. If this file and a template disagree, this file wins. Amend deliberately;
do not override locally.

**The diversification rule is INVERTED here.** This is one site, not a series of
one-off pages. Pages MUST share the type scale, the palette, the component voice
and the motion vocabulary. Structural variety comes only from each page using a
different *section composition* within the shared vocabulary (§ 12).

---

## 0 · Thesis

> **A Sunday-league sign-up sheet with the confidence of a Sunday newspaper:
> big honest type, one green, one blue, plenty of air — so that a nervous
> beginner reads "you're already welcome here" before they read a single word.**

Every decision below serves one action: **register, or join the waitlist.**
Confidence comes from scale, space and a single well-behaved brand green — never
from shouting, never from decoration.

Genre: **playful** (soft surfaces, low chroma, hover-responsive motion,
friendly-but-restrained type). Never childish, never quirk-for-quirk.

### Pre-emit critique (this system, not any one page)

| Axis | Score | Note |
|---|---|---|
| **A · Philosophy** | 5 | One thesis, one action, one audience. Every token has a stated role. |
| **B · Hierarchy** | 4 | Two h2 tiers + a real ink ladder fix the flat page; final proof depends on authors picking `prominence: lead` on the right 2–3 headings per page. |
| **C · Execution** | 4 | Contrast, focus, motion and states are fully specified; two derived tokens must be generated at runtime (O1) before any of it is true. |
| **D · Specificity** | 5 | Big Shoulders + ECS green + PLOP vocabulary + Seattle. Could not be another site. |
| **E · Restraint** | 4 | Ft3 index footer, two icon-tile grids and four bespoke error palettes are being deleted, not added to. |
| **F · Variety** | 5 | Nine distinct macrostructures over one shared system — the inverted rule, satisfied. |

Nothing scores below 3. Ship.

---

## 1 · Hard constraints that override taste

These are production constraints. Where Hallmark's own references disagree, the
constraint wins and the reference is noted as waived.

| # | Constraint | Consequence for this system |
|---|---|---|
| **C1** | ~~`section_converter.py` cannot restyle an existing page.~~ **AMENDED 2026-08-23** — it can now, explicitly and manually, through `rebuild_pages()` and `flask rebuild-public-pages`. | The old wording was true of `convert_all` (which skips any page that already has sections) and it cost this project an entire redesign. § 12's per-page shapes landed in the vocabulary and in the builders, were verified, shipped — and changed nothing live, because every page was still rendering the JSON it was converted with. Restyling reached the pages; **reshaping could not.** A structural change must now be made in the builders AND applied with the rebuild command, which snapshots each page to a `pre-rebuild` revision first. |
| **C2** | All colour must stay CSS-var-backed so the Appearance picker still re-skins the site. | **No literal hex, no arbitrary colour, and no frozen Tailwind palette stop in any public template.** The var-backed allowlist is § 3.1. |
| **C3** | Tailwind + Flowbite utilities only. No new `.css` files. Dynamic values only via `public_theme.theme_vars()` → a `<style>` block of custom properties. | New utilities go in `tailwind.config.js` — **O1 only**. |
| **C4** | Tailwind purge scans `app/templates/**/*.html`, `app/static/js/**`, `app/static/custom_js/**`, `app/services/public_theme.py` only. | A Tailwind class emitted from any other Python file is silently purged. |
| **C5** | The site editor depends on `macros.html` markup contracts: `data-sid`, `data-bid`/`data-btype`, `data-editable="html"`, the edit-mode placeholders, and every macro's **name and signature**. | Restyle inside the contracts. Add macros; never rename or remove one. |
| **C6** | `render_single_section()` renders a one-section document, so a Jinja loop index is always 0. | Anything positional is CSS (`+`, `:nth-of-type`, `:not([class*=bg-])`). Never a Jinja index. |
| **C7** | Dark mode is class-based (`darkMode:'class'`, driven by `localStorage`). | Every colour utility needs a `dark:` pair. `prefers-color-scheme` alone is a bug. |
| **C8** | Mobile floors: **320 / 375 / 414 / 768 px.** No horizontal page scroll. No two-line clickable text. Image-bearing grid tracks use `minmax(0,1fr)`. Display headings carry `break-words`. **Always include an `sm:` step when going past one column.** | See § 5 and § 11. |
| **C9** | Never commit; never write `.sql`. | This change set needs no SQL. |
| **C10** | Keep `:focus-visible` rings ≥ 3:1, `aria-*`, `sr-only`, `motion-reduce:` on every animation, alt text. The footer marquee's `aria-hidden` duplicate + `sr-only` real copy is deliberate. | § 7, § 8. |

**Waived Hallmark references, with reason:**
- *color.md "OKLCH only"* — waived. The Appearance screen stores hex and emits
  RGB triplets; OKLCH would break C2. We keep the *discipline* (tinted paper, no
  pure extremes, one accent) inside the RGB pipeline.
- *typography.md "no Inter"* — partially waived. Inter stays as the **body/UI**
  face (already self-hosted, metric-matched, and the portal shares it). The ban
  that matters — *Inter as the display face* — is enforced: Big Shoulders
  takes every heading.
- *layout-and-space.md `--space-*` tokens* — waived in favour of Tailwind's
  scale, which is the project's only sanctioned channel (C3).

---

## 2 · Type system

**Two faces. Big Shoulders Display headlines. Inter reads.** That is the whole
rule. A third family is banned (2+1 rule); the outlier slot is spent on JetBrains
Mono, which is not a fourth voice but the utility face — labels, eyebrows, the
scoreboard captions — and never sets a sentence.

**THE DISPLAY FACE IS BIG SHOULDERS (amended 2026-08-23; supersedes Bricolage
Grotesque).** Two things forced the change and both are worth recording.

The first is that Bricolage was chosen for a *width* axis it does not deliver
here. The self-hosted file carried weight only, so a re-host at
`opsz=96` + `wdth 75–100` was cut and shipped — and then the utility to drive it
did not exist. **Tailwind 4.3.3 ships `font-stretch` with keyword values only**
(`condensed`, `expanded`); `font-stretch-75` is not a class and never renders.
The narrow register was therefore reachable only through an arbitrary property,
which meant the "two widths from one family" idea cost 74KB to express one width.

The second is the reason not to go back. Bricolage Grotesque is now prescribed
*by name* in published anti-slop guides, which makes it the exact opposite of
what a display face is for — it has become a default, and a default is a tell.

**Big Shoulders Display** is a condensed American-sign grotesque. It is narrow by
construction, so the compression that Bricolage needed an axis to reach is simply
the shape of the letterform, and it arrives in **25.9KB latin + 22.6KB latin-ext**
(against Bricolage's 74KB) with `wght` instanced to **600–900** — the range the
site actually sets. It reads as scoreboard, fixture list and league table, which
is the register the content is in.

| Register | Where | How |
|---|---|---|
| **Display** | D1 hero headlines, lead-card titles (the division names), the facts numerals, the marquee | `font-display`, **uppercase**, `leading-[1.02]` floor |
| **Utility** | eyebrows, scoreboard labels, step ordinals, the E tier | `font-mono` |
| Body | everything that is a sentence | `font-sans` (Inter) |

**A condensed face is set uppercase or it is not doing its job.** The D1 ramp
therefore carries `uppercase` and a `leading-[1.02]` floor — a condensed cut at
`leading-none` clips its own diacritics — plus `[overflow-wrap:anywhere]
min-w-0` for the mobile gate (§ responsive 51). That last pair has a trap:
`overflow-wrap: anywhere` will break a word mid-syllable if the box is too
narrow, and it did — "EVERYONE" rendered as "EVERYO / NE" in the split hero's
column at 128px. **The fix is to size the type to the column, not to remove the
wrap.** D1 tops out at `lg:text-8xl` (96px) for exactly this reason.

**The filenames carry no version suffix, and the preload must byte-match.** The
`<link rel="preload">` carries no `?v=` cache-buster, because its href must
byte-match the `url()` in the `@font-face` or the browser fetches the font twice.
The preload and the `@font-face` therefore always change together. **Six
templates preload it:** both shells (`base_public.html`,
`base_public_minimal.html`) and the four error pages (403, 404, 429, 500).

### 2.1 Wiring (SHIPPED)

- `public_theme.FONT_PAIRS['display']` is `DEFAULT_FONT_PAIR`:
  - `heading: "'Big Shoulders Display', 'Haettenschweiler', 'Arial Narrow', system-ui, sans-serif"`
  - `body:    "'Inter', system-ui, -apple-system, sans-serif"`
  - `mono:    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"`
  ⚠️ The fallbacks are chosen, not filler: **Haettenschweiler and Arial Narrow
  are the two condensed faces that ship on Windows and macOS respectively.** If
  the woff2 fails, the page still reads condensed rather than snapping to a
  normal-width system sans, which would silently undo the whole type voice.
- `theme_vars()` emits `--font-mono` alongside `--font-heading` / `--font-body`,
  so an admin re-skin carries all three.
- Both shells and the four error pages carry a
  `<link rel="preload" as="font" type="font/woff2" crossorigin>` for
  `vendor/fonts/big-shoulders/big-shoulders-latin.woff2`, then
  `<link rel="stylesheet" href="{{ static_v('vendor/fonts/big-shoulders.css') }}">`.
  **No `fonts.googleapis.com` link — the public CSP blocks it and the whole type
  system falls back silently, with no error anywhere.**
- `tailwind.config.js` `theme.extend.fontFamily` mirrors the pair *inside* the
  `var()` fallback, so the class still resolves if the token is absent:
  - `display: ["var(--font-heading, 'Big Shoulders Display')", 'Big Shoulders Display', 'Haettenschweiler', 'Arial Narrow', 'system-ui', 'sans-serif']`
  - `sans:    ["var(--font-body, 'Inter')", 'Inter', 'system-ui', '-apple-system', 'sans-serif']`
  - `mono:    ["var(--font-mono, 'JetBrains Mono')", 'JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace']`
- The `<style>` block in `base_public.html` binding `body` and `h1..h6` sits in
  `@layer base`, so a `font-display` / `font-sans` / `font-mono` utility still
  overrides it.

### 2.2 Weights

- **Big Shoulders** loads **600–900** — the file is instanced to that range, so
  anything below 600 renders faux-light and anything above 900 does not exist.
  Display headings use **800**; the marquee and the facts numerals use **900**.
  **`font-normal` / `font-medium` are BANNED on any `font-display` element.**
- **Inter** loads 300–700. **`font-extrabold` (800) is BANNED on any Inter
  element** — it is outside the loaded axis and renders faux-bold. Inter's
  emphasis ceiling is `font-bold` (700).
- **JetBrains Mono** is used at `font-medium` / `font-semibold` only, always with
  `uppercase tracking-[0.14em]` and never above `text-sm`. A mono face set large
  reads as a code block, which is not what a fixture label is.
- Body is one weight: `font-normal`. `font-medium` for a link, `font-semibold`
  for a UI label, `font-bold` for a heading. Nothing else.

### 2.3 The ramp — literal class strings, copy exactly

Every string below is complete. Do not add tracking, leading or balance
utilities on top; they are already in the string.

| Tier | Role | Class string |
|---|---|---|
| **D1** | Hero `h1` / display | `font-display text-[2.75rem] sm:text-6xl lg:text-7xl font-extrabold leading-[1.02] tracking-[-0.035em] text-balance break-words` |
| **D2** | Section opener `h2` — *argument* headings only (`prominence: lead`) | `font-display text-3xl sm:text-4xl lg:text-5xl font-extrabold leading-[1.06] tracking-[-0.025em] text-balance break-words` |
| **D3** | Default `h2` — incl. every long-form `[&_h2]` | `font-display text-2xl sm:text-3xl lg:text-4xl font-extrabold leading-[1.1] tracking-[-0.02em] text-balance break-words` |
| **D4** | `h3` — incl. every long-form `[&_h3]` | `font-display text-xl sm:text-2xl font-bold leading-[1.15] tracking-[-0.015em] text-pretty break-words` |
| **D5** | `h4` — incl. every long-form `[&_h4]` | `font-display text-lg sm:text-xl font-bold leading-snug tracking-normal break-words` |
| **L** | Lead / lede paragraph | `text-lg sm:text-xl lg:text-2xl font-normal leading-[1.45] text-pretty` |
| **B** | Body copy | `text-base sm:text-lg font-normal leading-[1.65]` |
| **BL** | Long-form body (guide, legal, article) | `text-base sm:text-lg font-normal leading-[1.7]` |
| **S** | Small / caption / meta | `text-sm font-normal leading-normal` |
| **E** | Eyebrow / label / column head | `text-xs font-bold uppercase tracking-[0.14em]` |
| **N** | Nav link | `text-[0.9375rem] font-semibold leading-none` |
| **W** | Wordmark | `font-display text-xl sm:text-2xl font-extrabold tracking-[-0.03em] leading-none` |
| **BTN** | Button label | `text-base font-semibold leading-none` (small: `text-sm font-semibold leading-none`) |

**Ladder at `lg`:** 72 / 48 / 36 / 24 / 20 / 18 body. Six sizes, one ratio family.
That is the ceiling — if you need more hierarchy use **weight, ink and space**,
never a seventh size.

### 2.4 Two h2 tiers — the fix for "ten equally-weighted announcements"

`block_heading` takes a new optional `block.prominence`:

- `prominence: 'lead'` → **D2**. At most **two or three per page.** Reserved for
  the headings that carry the page's argument.
- anything else → **D3**.

Everything a page says at D3 reads as supporting material. This, plus § 6.4's
merge of orphan heading sections, is what turns a list of announcements into an
argument. `section_converter.py` (O9) seeds `prominence: 'lead'` on new pages;
existing pages get it authored in the site editor.

### 2.5 Headline length → size step-down (mandatory)

Measured on the **rendered** text of the heading block. Applied by
`block_heading` as a Jinja `{{ block.html | striptags | length }}` bucket. This
is content-derived, not positional, so C6 is satisfied.

| Rendered length | D1 cap | D2 cap |
|---|---|---|
| ≤ 24 chars | `lg:text-7xl xl:text-8xl` | D2 as written |
| 25–55 chars | **D1 as written** (`lg:text-7xl`) | D2 as written |
| 56–90 chars | `text-[2.25rem] sm:text-5xl lg:text-6xl` | step to D3 |
| > 90 chars | `text-[2rem] sm:text-4xl lg:text-5xl` | step to D3 |

The live home `h1` is 62 characters → it renders at the 56–90 bucket. It never
reaches `text-8xl` again. **`xl:text-8xl` is banned outside the ≤ 24-char bucket.**

### 2.6 Measure and long-form rhythm

- Body prose caps at `max-w-[65ch]`. Long-form reading columns cap at
  `max-w-[62ch]`.
- **The measure lives on the reading element, not the wrapper.** A `<dd>` that
  steps down to `text-base` inside a `text-lg` box must carry its own
  `[&_dd]:max-w-[62ch]`, or it reads at 80 characters.
- Long-form paragraph rhythm is **em-based** so it tracks the type:
  `[&_p]:mt-[1.15em] [&_p]:first:mt-0`, `[&_li]:mt-[0.5em]`,
  `[&_ul]:mt-[1.15em]`, `[&_ol]:mt-[1.15em]`.
  `mt-3` on 28px leading (0.43 of a line) is banned.
- Section container width must match its content: a prose-only section uses
  `narrow` (`max-w-3xl`), never `normal` with a 350px dead gutter.

### 2.7 Numerals and punctuation

- `tabular-nums` on every stacked figure: dates, times, scores, stats, prices,
  pagination.
- Typographic punctuation only: `’ “ ” —`. Straight `'` and `"` are a defect in
  templates. (Copy stored in the database is a user TODO — § 14.)

---

## 3 · Colour

### 3.1 Roles — the whole palette, and the only legal stops

**Blue is ACTION. Green is BRAND.** That single split resolves every colour
finding in the audits: the green stops being asked to do a job it cannot do at
2.78:1, and the primary CTA stops competing with the active-nav state.

| Utility | CSS var | Default | Role — the ONLY role |
|---|---|---|---|
| `ecs-green` | `--color-primary-rgb` | `#40b050` | **Identity green.** Fills, tints, rules, icon tiles, dots, the logo mark. **Never carries text and never IS text.** |
| `ecs-green-dark` | `--color-primary-dark-rgb` | `#338d40` | Hover step for green fills. Not an ink. |
| **`ecs-green-ink`** *(new)* | **`--color-primary-ink-rgb`** | **`#266a30`** | **Brand ink.** Green *text* on light grounds — and nothing else. 5.44:1 on `paper`, 6.59:1 on white, 4.62:1 on the worst legal tinted ground (§ 3.2). **It stopped being a ground when `pitch-ground` split off**; a token cannot be both the darkest legal text colour and a comfortable fill. |
| **`ecs-green-300`** *(re-bound)* | **`--color-primary-on-dark-rgb`** | **`#70c47c`** | Brand ink **in dark mode**. 8.84:1 on `paper-dark`. |
| **`ecs-pitch`** *(new 2026-08-23)* | **`--color-pitch-ground-rgb`** | **`#2f823b`** | **The green section ground** — the one heavyweight brand band per page, and the ground under white body copy. Derived, not typed: plain `primary` (`#40b050`) carries white at only **4.35:1**, which fails AA, so a section painted in the raw brand colour either fails contrast or is forced to shout in large type. `_ink(primary, '#ffffff', 4.6)` darkens it until white clears — **4.80:1** — by exactly the mechanism the brand ink uses, so an admin re-skin keeps working instead of freezing a hex. |
| `ecs-blue` / `-600` | `--color-blue-rgb` | `#203090` | **Primary action.** Filled CTA ground. White on it = 11.1:1. |
| `ecs-blue-700` | `--color-blue-dark-rgb` | `#1a2776` | Primary action hover/active. |
| **`ecs-blue-300`** *(re-bound)* | **`--color-blue-on-dark-rgb`** | **`#7983bc`** | Accent ink in dark mode. 5.18:1 on `paper-dark`. |
| `ecs-blue-400` | `--color-blue-light-rgb` | `#2e46d1` | **RETIRED from the public site.** 2.79:1 on dark. Every `dark:text-ecs-blue-400` becomes `dark:text-ecs-green-300` (brand roles) or `dark:text-ecs-blue-300` (action roles). |
| **`paper`** *(new)* | **`--color-paper-rgb`** | **`#e5ebe4`** | Page ground, light. **COOL GREY-GREEN NEWSPRINT (amended 2026-08-23; supersedes both the pale mint and the warm cream).** It began as the primary mixed 97% toward white, which lands on a pale mint — a mint ground under a green tint band under white cards made the whole page three near-whites of one hue, with nothing on it carrying any weight. The first fix was a warm cream (`#fbf8ec`) and it was wrong twice over: **warm cream plus a display face plus an earth accent is the single most-recognised generated-design palette in circulation**, and against this club's green it reads frankly yellow. The ground is now a cool grey-green newsprint — `PAPER_WARM_BASE` nudged `PAPER_WARM_MIX` toward the primary, so an admin re-skin still tints it while the green stays green rather than becoming the page colour. ⚠️ The constant is still *named* `PAPER_WARM_*` from the cream pass; the name is a fossil, the value is not. Never `#fff`. |
| **`paper-dark`** *(new)* | **`--color-paper-dark-rgb`** | **`#09140c`** | Page ground, dark. Never `#000`, never flat `gray-950`. |

**Nothing else is legal in a public template.** Frozen stops
(`ecs-green-50…950` numeric, `ecs-blue-50/100/200/500/800/900`, `emerald-*`,
`purple-*`, `pink-*`, any hex, any `[#...]` arbitrary value) are **banned**.

**The one sanctioned exception — semantic status colour.** Errors and warnings
are not brand roles and the Appearance picker must not re-skin them. Use exactly:
- error text `text-red-700 dark:text-red-400`; error boundary `ring-red-600 dark:ring-red-400`
- warning text `text-amber-700 dark:text-amber-400`
- success text `text-ecs-green-ink dark:text-ecs-green-300` (success *is* a brand moment)
- neutral ink `text-gray-800 dark:text-gray-200`; muted `text-gray-600 dark:text-gray-300`;
  faint `text-gray-500 dark:text-gray-400`. **Bare `text-gray-400` in light mode
  is banned** (2.55:1).

### 3.2 Derivations — deterministic, admin-proof (O1)

The three new tokens are computed in `public_theme.theme_vars()`, not typed in.
An admin picking a pale colour must not be able to re-break contrast.

```python
def _ink(rgb, ground, min_ratio=4.6):
    """Darken toward black until it clears min_ratio against `ground`.
       Two callers, two grounds — that is the whole point:
         _ink(primary, ink_ground_hex, 4.6) -> #266a30  the brand INK
         _ink(primary, '#ffffff',      4.6) -> #2f823b  the pitch GROUND"""
    f, out = 1.0, rgb
    while f > 0.30 and contrast_ratio(_hex(out), ground) < min_ratio:
        f = round(f - 0.02, 2); out = _scale(rgb, f)
    return out

def _on_dark(rgb, ground='#09140c', min_ratio=5.0, start=0.25):
    """Mix toward white, never less than `start`, until it clears the dark ground.
       green -> t=0.25 -> #70c47c (8.84:1); blue -> t=0.40 -> #7983bc (5.18:1)."""
    t, out = start, _mix_white(rgb, start)
    while t < 0.80 and contrast_ratio(_hex(out), ground) < min_ratio:
        t = round(t + 0.05, 2); out = _mix_white(rgb, t)
    return out

paper      = _mix_toward(primary, PAPER_WARM_BASE, PAPER_WARM_MIX)  # #e5ebe4
paper_dark = _mix_toward(primary, PAPER_DARK_BASE, 0.06)            # #09140c

# The darkest LIGHT-mode ground the brand ink is allowed to be text on.
ink_ground = _mix_toward(primary, paper, INK_TINT_FLOOR)            # #c4dfc6
primary_ink   = _ink(primary, _hex(ink_ground), 4.6)                # #266a30
pitch_ground  = _ink(primary, '#ffffff',        4.6)                # #2f823b
```

**`INK_TINT_FLOOR = 0.20` is a measured constant, not a guess, and it is the one
number here that has been wrong twice.** It states the deepest tinted surface the
brand ink may sit on, as a fraction of the primary composited over `paper`. The
vocabulary paints exactly four such grounds — `bg-ecs-green/[0.05]` (callouts,
forms, empty states), `/[0.06]` (section theme `light`), `/[0.08]` (inactive
chip) and `/10` (icon and date plates, the ghost button's hover ground) — and
**they nest**. The floor was first set at 0.15, modelling a `/10` plate inside a
`light` section. The contact page goes one layer deeper: a `/10` icon plate
inside a `/[0.05]` callout inside a `/[0.06]` section composites to **~0.196** of
the primary, and the brand ink measured **4.19:1** on those social buttons —
under the 4.5 floor for their 16px label.

⚠️ **The lesson is not "raise the floor".** Raising it to 0.20 only reached
4.37:1, because darkening the ink globally to rescue one deeply-nested component
is the wrong lever — it costs contrast-headroom on every other surface to fix a
surface almost nothing uses. **The fix was at the source: the social icon plate
dropped from `/10` to `/[0.06]`.** The floor stayed at 0.20 anyway, because 0.15
was genuinely under-modelling the nesting. Set this constant from the DEEPEST
real nesting on the site, not the common one; under-modelling it produces exactly
one class of almost-passing contrast bug that no single-layer probe will catch.

Every ink is measured against a real derived surface, so changing the ground
re-derives every ink automatically and nothing is hand-tuned. **Measured
2026-08-23 against the shipped tokens:**

| Pair | Ratio |
|---|---|
| brand ink `#266a30` on `paper` `#e5ebe4` | **5.44:1** |
| brand ink on white (cards) | **6.59:1** |
| white on `pitch-ground` `#2f823b` | **4.80:1** |
| `green-300` `#70c47c` on `paper-dark` | **8.84:1** |
| `blue-300` `#7983bc` on `paper-dark` | **5.18:1** |
| `gray-700` body on `paper` | **8.51:1** |
| `gray-900` on `paper` | **14.64:1** |

⚠️ **Verify contrast by compositing the alpha stack the way a browser paints
it.** A probe that reads a semi-transparent background as an opaque colour cries
wolf on every `/[0.06]` tint — this one reported three failures that did not
exist before it was rewritten to composite properly. Full-site sweep after that:
**95/95 text elements pass AA across home, register, faqs, contact and guests, in
both themes.**

`theme_vars()` already computes `primary_contrast` and throws it away. It must
now **also return `primary_ink_contrast` and gate the Appearance save**: if the
chosen primary cannot reach 4.6:1 even at f=0.30, warn on the Appearance screen.

### 3.3 On-colour rules

| Ground | Heading | Body | Link | Ring / boundary |
|---|---|---|---|---|
| `bg-paper` / `bg-white` | `text-gray-900 dark:text-white` | `text-gray-700 dark:text-gray-200` | `text-ecs-green-ink dark:text-ecs-green-300` + underline | `ring-gray-400/70 dark:ring-white/20` |
| `bg-ecs-green/[0.06]` tint | same as above | same | same | `ring-ecs-green-ink/20 dark:ring-white/10` |
| **`bg-ecs-pitch`** (brand band) | `text-white` | `text-white` (**never `text-white/90`** — 4.80 → 4.2, fails) | `text-white underline decoration-white/60` | `ring-white/70` |
| dark section **`bg-paper-dark`** (amended 2026-08-23; was `bg-gray-900`, a frozen Tailwind stop that quietly broke C2) | `text-white` | `text-gray-200` | `text-ecs-green-300` | `ring-white/20` |
| photo hero | `text-white` + real legibility treatment (§ 4.5) | `text-white` | `text-white underline` | `ring-white/80` |

**`bg-ecs-green` never carries text.** Every text-bearing green surface — brand
bands, the footer marquee, filled secondary buttons, the
active-state fill — uses a *derived* green, never the raw primary. Plain
`ecs-green` survives as tints (`bg-ecs-green/[0.06]`), rules
(`border-ecs-green-ink/25`), plate grounds and the logo.

**Which derived green depends on which side of the text you are on** — this is
the split that `pitch-ground` exists for, and getting it backwards is the easiest
contrast bug on the site to write:

| You are painting | Token | Why |
|---|---|---|
| green **text** on a light ground | `text-ecs-green-ink` (`#266a30`) | derived to clear 4.6:1 against the *worst legal tint*, so it is darker than it looks like it needs to be |
| a green **ground** under white text | `bg-ecs-pitch` (`#2f823b`) | derived to carry white at 4.6:1; `THEME_SECTION['brand']` is exactly this |

⚠️ **`bg-ecs-green-ink` as a section ground is now wrong.** It is a text colour
that happened to be dark enough to double as a fill before the split; using it as
a band today makes an unnecessarily heavy rectangle. The section vocabulary uses
`bg-ecs-pitch`.

### 3.4 The unlayered `<style>` bug (O2, blocking)

`base_public.html` emits an **unlayered** `main a, header a, footer a {
text-decoration: none }`. Unlayered declarations beat every Tailwind utility in
`@layer utilities`, so every `underline` and `hover:underline` in the section
vocabulary, the news templates and the guide is dead, and every prose link is
distinguished by a 2.78:1 colour alone.

**Fix:** delete the two `text-decoration: none` rules. Scope the reset to nav
chrome only and put it in `@layer base`:

```css
@layer base {
  header a, footer nav a, .nav-pill { text-decoration: none; }
  body { font-family: var(--font-body, 'Inter', system-ui, sans-serif); }
  h1,h2,h3,h4,h5,h6 { font-family: var(--font-heading, 'Big Shoulders Display','Arial Narrow',system-ui,sans-serif); }
}
```

Delete the dead `.prose a { text-underline-offset: 2px }` rule — no public
section ever emits a `prose` class outside `news_detail.html`.

### 3.5 Dark mode

- Ground `paper-dark`; **elevation is lightness, never shadow.** Every raised
  surface is `dark:bg-white/[0.045]` (composites correctly on any ground);
  nested/inset is `dark:bg-white/[0.02]`. `shadow-*` is `dark:shadow-none`.
- Brand hue **never changes between modes.** Green stays green
  (`ecs-green` → `ecs-green-300`), blue stays blue (`ecs-blue-600` →
  `ecs-blue-300`). The site's accent must not become a different colour when the
  OS setting flips.
- Icon tile ground and glyph move together:
  `bg-ecs-green/10 text-ecs-green-ink dark:bg-ecs-green/15 dark:text-ecs-green-300`.
- Every `THEME_SECTION` key gets a real, distinct dark pair (§ 4.2). Two themes
  resolving to the same dark colour is a bug.
- Theme resolution is class-based off `localStorage`. **`prefers-color-scheme`
  is the unset default only, and must not be persisted on first visit** — a
  visitor who never chose must keep following their OS.

---

## 4 · Surface, elevation and radius

### 4.1 Radius scale — three values, no others

| Value | Class | Used for |
|---|---|---|
| 999px | `rounded-full` | buttons, chips, pills, badges, avatars, icon buttons |
| 12px | `rounded-xl` | cards, panels, images, media wells, empty states, form panels |
| 8px | `rounded-lg` | inputs, selects, textareas, small tiles, code |

`rounded-2xl` and larger are **banned** (playful caps card radius at 12px).
`rounded-sm`/`rounded-md` are banned as decoration; `rounded` on a focus target
is fine only where it is `rounded-full` or `rounded-lg`.

### 4.2 The four surfaces

| Surface | Light | Dark |
|---|---|---|
| **Page** | `bg-paper` | `dark:bg-paper-dark` |
| **Card / raised** | `bg-white ring-1 ring-inset ring-black/[0.07] shadow-sm` | `dark:bg-white/[0.045] dark:ring-white/10 dark:shadow-none` |
| **Inset / quiet panel** | `bg-ecs-green/[0.05] ring-1 ring-inset ring-ecs-green-ink/15` | `dark:bg-white/[0.02] dark:ring-white/10` |
| **Brand band** | `bg-ecs-pitch` | `dark:bg-ecs-pitch` (same — it clears white on both) |

`THEME_SECTION` becomes:

```jinja
'inherit': '',
'light':   'bg-ecs-green/[0.06] dark:bg-white/[0.03]',
'dark':    'bg-paper-dark dark:bg-black/40 dark:ring-1 dark:ring-inset dark:ring-white/5',
'brand':   'bg-ecs-pitch'
```

A card on a light page is **white on tinted paper** — that is where light-mode
surface hierarchy comes from. `bg-white` on `bg-white` is banned.

**THE INK GROUND IS A FIRST-CLASS LIGHT-MODE SURFACE (added 2026-08-23).** The
`dark` theme used to resolve to `bg-gray-900`, a frozen Tailwind stop that
quietly broke C2, and in practice no page used it — so the light palette was
three near-whites and one green band, and over 5,500px of home page nothing had
enough weight for the eye to land on. `bg-paper-dark` is var-backed, carries the
brand's green cast, and gives every page one heavyweight section.

**Grounds are now a ladder, and green is rationed.** Flat `ecs-green-ink` used
to be the ground of every photoless hero AND the scrim over every photographic
one AND every closing band — the same rectangle four or five times a page, on
nine pages, until the brand colour meant nothing.

| Ground | Budget per page |
|---|---|
| `bg-paper` (newsprint) | the default |
| `bg-ecs-green/[0.06]` (tint) | one or two quiet bands |
| **`bg-paper-dark` (ink)** | one heavyweight section, plus every photoless hero |
| **`bg-ecs-pitch` (brand)** | **exactly one section on the page** |

⚠️ **"Exactly one" means one section, not "one closing band".** The brand green
is a budget, not a slot — on the home page it is spent on the *steps* ladder and
the closing band is ink, because the ladder is where the page most needs weight.
`test_home_spends_brand_green_once` enforces the budget; it deliberately does
**not** enforce which section gets it. (That test caught this exact mistake
during the build, when green was put on two sections at once.)

### 4.3 Elevation and hover-lift

- `shadow-sm` at rest, `shadow-md` on hover. Never `shadow-lg` or `shadow-xl`
  on the public site; `shadow-xs` is invisible and banned as a card's only
  boundary.
- **The hover-lift belongs to cards only** — `hover:-translate-y-0.5` +
  `hover:shadow-md`, and only when the whole surface is a click target. A
  button, a news tile, a social chip and a card all doing the same lift flattens
  the feedback vocabulary. § 7 assigns one signal per element class.

### 4.4 Card contract (block_card, news card, calendar event card — one shape)

**A CARD IS NOT THE DEFAULT CONTAINER (added 2026-08-23).** This one shape used
to wrap value-prop tiles, division blocks, step tiles and news tiles
identically — four jobs, one container — which is what made the site read as
templated. A card earns its container only when elevation communicates real
hierarchy. Three equal-weight value propositions have no hierarchy for a card to
express, so they are a rule-separated list (`block_steps`, style `plain`) with
no container, no shadow and no icon chip. The 2026 field has moved hard away
from "corporate soft UI"; a uniform 16px radius on everything is a named AI-slop
signature.

**Two prominences.** `default` is the tile above. `lead` is the same card asked
to carry a whole section — the two division blocks — and differs in exactly
three ways: the title steps up to D2 in the condensed cut, the media is 4:3
rather than 16:9, and the call to action is a **real button inside the card**
(`cta_kind`, live) rather than a stretched title link. The division CTAs used to
be loose `cta_live` siblings floating below their cards, which is DO-NOT 18 and,
with the old centred column alignment, is why Classic and Premier never lined
up. The two link treatments are mutually exclusive: a stretched `::after` link
behind a real button would swallow the button's clicks.

**The seal (added 2026-08-23).** A `lead` card may carry a stamped circular seal
— `badge` + `badge_sub` + `badge_tone` — straddling the seam between its media
and its body: `absolute right-6 top-0 -translate-y-1/2 rotate-[-9deg]`, `h-24 w-24
lg:h-28 lg:w-28`, `ring-4 ring-white`, on `bg-ecs-pitch` (brand) or
`bg-ecs-blue-600` (action, per § 3.1's blue-is-action rule). It is
`aria-hidden` — every word on it is already in the card's own copy.

**A seal must name something, not decorate.** Classic reads *Start here* and
Premier reads *Step up*: the badge tells you what the division is **for**, which
is the one question the two cards exist to answer. A seal carrying the division's
own name, a number, or an adjective would be pure ornament and is banned.

⚠️ **Position it against the media, not the card.** The first attempt used
`top: calc(5/3 * 100% / 2)` to land the seal on the 4:3 media's bottom edge —
but percentage `top` resolves against the *card's* height, not the media's, so
the seal drifted with the body copy's length and sat differently on each card.
It is anchored to the body wrapper's top edge instead, which is the seam by
definition.


```
group relative flex flex-col overflow-hidden rounded-xl
bg-white ring-1 ring-inset ring-black/[0.07] shadow-sm
dark:bg-white/[0.045] dark:ring-white/10 dark:shadow-none
transition-[transform,box-shadow,background-color] duration-200 ease-out
motion-reduce:transform-none motion-reduce:transition-none
```
Interactive cards add `hover:-translate-y-0.5 hover:shadow-md
dark:hover:bg-white/[0.07] group-focus-within:-translate-y-0.5`.
Media well: `aspect-video w-full overflow-hidden bg-ecs-green/[0.06] dark:bg-white/[0.04]`.
Padding `p-6 lg:p-8`. Title **D4**. Body **B**, `text-gray-700 dark:text-gray-200`.
Card CTA is `mt-auto pt-4` so CTAs align across a grid row.

**One real link per card** — the *stretched link* pattern: a single `<a>` on the
title carrying `after:absolute after:inset-0 after:content-['']`; the image gets
`alt=""`; secondary chips lift above with `relative z-10`. Three links to the
same URL per card is banned.

### 4.5 Images

**PHOTOGRAPHY SHIPS UNTREATED. THE DUOTONE WAS TRIED AND REVERTED
(2026-08-23).** It went live for one deploy and was wrong. On the real page the
single full-colour photograph read as obviously better than the two duotoned
ones directly above it — the treatment was making good photography worse, and at
full strength it flattened team photos into a pale mint wash that looks like a
broken colour profile rather than a design decision.

The problem it was solving is real: the photos come from many phones over many
seasons and do not obviously belong together. The right answer is not to process
them. A consistent aspect ratio, the newsprint ground and one dark anchor already do
the unifying work, and every club site worth studying — Vermont Green, Ballard
FC, Oakland Roots — runs full-colour photography. `treatment: 'duotone'` remains
selectable per block for a deliberate one-off; it is not the house style and
nothing in the builders opts into it. `tests/test_public_site_builder.py::
test_photography_ships_untreated` holds that line.

**The scrim over a photo is still BLACK, never brand green** — that half of the
change stands, and matters more now that the photography is in full colour. A
green wash does not read as a scrim; it stains the picture. Measured on the
rebuilt hero: white text sits at 6.65:1 worst case over the photograph.

The mechanism, kept for the record and for the opt-in:

**~~DUOTONE IS THE HOUSE TREATMENT~~ (superseded).** The photography comes
from many phones over many seasons in every kind of Seattle light; shown raw it
reads as a shoebox rather than as one club. Every photo is flattened to
greyscale and mapped between the same two brand tones, so a blurry 2019 team
photo and a sharp 2026 one belong to the same set.

The mechanism is `grayscale contrast-110` on the `<img>`, then
`bg-ecs-green-ink mix-blend-color` (brand hue and saturation over the photo's
own luminance) and `bg-paper mix-blend-multiply` (highlights land on the page's
paper, not on white). The wrapper must carry `isolate`, or the blends reach past
the photo and blend with the page.

`mix-blend-lighten` was the first attempt and is subtly wrong: lighten is a
per-channel max, so it only reaches pixels already darker than the green and
leaves every midtone stubbornly grey — a muddy photo rather than a treated one.

**Identical in both themes.** § 3.5 forbids the brand hue changing between light
and dark, and the duotone *is* the brand hue applied to an image, so it gets no
`dark:` pair. Only the scrim above it changes.

**`treatment: 'full-colour'` is the opt-out, and a page gets AT MOST ONE** —
normally the celebration shot. The break only reads as a break while everything
around it is treated.

**The scrim over a photo is BLACK, never brand green.** A green wash does not
read as a scrim; it stains the picture. Black darkens without tinting, so the
duotone is the only thing colouring the image and the two treatments stop
fighting.


- Hero image goes through `_img_tag` so it inherits `srcset` + `width`/`height`,
  plus `fetchpriority="high" decoding="async"` and no `loading="lazy"` — it is
  the LCP element on every page that has one.
- Above-the-fold grid images (first row, `loop.index <= 3`) are
  `loading="eager" fetchpriority="high"`; the rest are `loading="lazy"`.
- **Every image reserves its box in CSS** (`aspect-*` inside an
  `overflow-hidden` wrapper) so a missing `width`/`height` in the media row can
  never shift layout.
- `<picture>` only when a `webp_srcset` actually exists. An empty `<picture>`
  wrapper is banned.
- Photo-hero legibility: the green overlay carries the contrast. Delete the
  second bottom scrim and `drop-shadow-xs` (a 1px 5%-black shadow does nothing
  at 72px). If a headline still needs help, use
  `[text-shadow:0_2px_12px_rgb(0_0_0/0.35)]`.
- `alt=""` on a content photograph is banned. Decorative → `alt=""` **plus**
  a caption or nothing; content → real alt text.

---

## 5 · Spacing, containers, rhythm

### 5.1 Section padding — bottom-weighted (gate 44a)

`PAD` in `macros.html`:

```jinja
'sm': 'pt-10 pb-14 sm:pt-12 sm:pb-16',
'md': 'pt-14 pb-20 sm:pt-16 sm:pb-24',
'lg': 'pt-20 pb-28 sm:pt-24 sm:pb-36',
'xl': 'pt-24 pb-32 sm:pt-28 sm:pb-40'
```

`section_band` **must read `PAD`** (it currently hardcodes `py-20 sm:py-24` and
ignores `s.padding`, which is why every band on the site is identical). Default
`lg`.

Hero `pads`:

```jinja
'sm': 'pt-16 pb-24 sm:pt-20 sm:pb-28',
'md': 'pt-20 pb-28 sm:pt-24 sm:pb-36 lg:pt-28 lg:pb-40',
'lg': 'pt-24 pb-32 sm:pt-28 sm:pb-40 lg:pt-32 lg:pb-44',
'xl': 'pt-28 pb-40 sm:pt-32 sm:pb-48 lg:pt-36 lg:pb-56'
```

**Fold budget (must be verified at 1280×800, not 1440×900):** sticky header 80 +
hero `lg` top 128 + D1 at the 56–90 bucket (3 lines × 60px ≈ 180) + lede 60 +
one CTA row 48 + gaps ≈ 520px. The primary CTA is above the fold. It is not
today (~450px below).

### 5.2 Containers and gutters

- `narrow` `max-w-3xl` · `normal` `max-w-5xl` · `wide` `max-w-7xl`.
- Gutter is **`px-4 sm:px-6 lg:px-8` everywhere**, including the utility pages
  and the legal pages. `px-6` at 320px is banned.
- **One page, one left edge.** A decorative image at `max-w-7xl` beside body
  copy at `max-w-5xl` is a misalignment, not a break.

⚠️ **The width token is an INNER wrapper; the outer container is always
`max-w-7xl`.** `section_content` used to apply it to the section's own centring
container, so left-aligned body copy started at **x=240** while every hero,
`columns` and `band` on the same page started at **x=112**. Fixed 2026-08-23 —
the full account is § 6.0, which is where this rule lives.

### 5.3 Internal rhythm — relational, not uniform

`space-y-6` on every child of every section is why the 26px status badge sits
the same distance from a 72px headline as two buttons sit from each other.
Replace the flat gap with a relational one, keyed on **block type** (CSS
sibling selectors — C6-safe), on the blocks wrapper of `section_hero`,
`section_content`, `section_band` and each `section_columns` column:

```
flex flex-col
[&>*+*]:mt-6
[&>[data-btype=heading]+[data-btype=richtext]]:mt-3
[&>[data-btype=richtext]+[data-btype=heading]]:mt-10
[&>[data-btype=button]+[data-btype=button]]:mt-0
[&>[data-btype=cta\_live]+[data-btype=button]]:mt-0
[&>[data-btype=registration\_status]+*]:mt-5
```

**Consecutive buttons sit in a ROW, not a column.** Add to the same wrapper:

```
[&>[data-btype=cta\_live]]:inline-block [&>[data-btype=button]]:inline-block
```
…or, preferred, a real `_btn_row` wrapper in `macros.html` that collects
consecutive `button`/`cta_live` blocks into
`flex flex-wrap items-center gap-3 sm:gap-4` (`justify-center` when the section
is centre-aligned). Two stacked equally-weighted centred buttons is banned.

### 5.4 Section rhythm — new default `auto`

The current `hairline` default is `border-ecs-green/15` = **1.15:1** — invisible
— and it draws a rule straight through the middle of two sections that share a
tint. Replace the default:

```python
'auto': {
    'label': 'Automatic — a rule only where the ground does not change',
    'classes': ('[&>section:not([class*=bg-])+section:not([class*=bg-])]:border-t '
                '[&>section:not([class*=bg-])+section:not([class*=bg-])]:border-ecs-green-ink/20 '
                'dark:[&>section:not([class*=bg-])+section:not([class*=bg-])]:border-white/10'),
},
```
`DEFAULT_SECTION_RHYTHM = 'auto'`. A ground change carries the seam where one
exists; the hairline fills in only where it does not. Purely additive, purely
CSS-positional (C6). `hairline` stays as an admin option but is raised to
`/25 … dark:/15`; `tint` and `none` are unchanged.

**Anything that is a direct child of `<main>` and is not a `<section>` breaks
this selector.** Pagination rows, the calendar subscribe card and page-level
`<script>` tags must be moved inside a `<section>` or into `{% block extra_js %}`.

### 5.5 Anchors and the sticky stack

Stop hand-tuning three numbers against three heights. `base_public.html` emits
one custom property into the existing theme `:root` block:

```
--sticky-stack: calc(4rem + <0px | 3rem admin bar>);   /* 5rem at ≥640px */
```
`html { scroll-padding-top: calc(var(--sticky-stack) + 1.5rem); }` in
`@layer base`. Then **drop `scroll-mt-24` from headings** and give
`[&_h2] [&_h3] [&_h4]` in `block_richtext` nothing at all — the scroll-padding
covers it. Every long-form `h3` and `h4` gets a server-rendered slug `id`.

---

## 6 · Layout vocabulary

### 6.0 One left edge (added 2026-08-23)

**Every section type shares one outer container: `mx-auto max-w-7xl px-4 sm:px-6
lg:px-8`.** Hero, content, columns and band all start their content at the same
x. The reading measure (`narrow` / `normal` / `wide`) is an **inner** wrapper and
never moves a section's left edge.

It was the other way round and it was the most visible flaw on the redesigned
site: `section_content` centred a narrower container, so a left-aligned content
section began ~130px right of every hero, columns and band section on the same
page. Centring the page hid it; left-aligning the page exposed it as a ragged
edge running down the whole document. `wide` therefore means "no measure", not
"a wider container".

### 6.1 Column layouts — the `sm:` step is mandatory (C8)

```jinja
'50-50': 'grid gap-8 sm:grid-cols-2 sm:gap-10 lg:gap-14',
'33-67': 'grid gap-8 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:gap-10 lg:gap-14',
'67-33': 'grid gap-8 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:gap-10 lg:gap-14',
'3col':  'grid gap-8 sm:grid-cols-2 lg:grid-cols-3 lg:gap-10'
```
Bare `1fr` tracks are banned — always `minmax(0,1fr)`; a bare track will not let
its image shrink below intrinsic width and blows out the mobile layout.

**Columns default to grid STRETCH, not `lg:items-center` (amended 2026-08-23).**
`align` is still a setting (`start` / `center`), but the default flipped, and the
reason is worth keeping: `lg:items-center` vertically centres columns of unequal
height, which is why the Classic and Premier division cards started at different
Y and their CTAs landed at different Y. Centring is right for *a tall photo
beside short text*; it is wrong for *two cards that should read as a pair*, and
the pair is by far the more common case.

⚠️ **Do NOT "fix" alignment by adding `h-full` to the column.** `h-full` on an
already-stretched grid item overrides the `align: 'center'` opt-in, so the
setting silently stops working. What aligns the CTAs is the card's own `grow`
inside a stretched grid item — `COL_RHYTHM` carries
`[&>[data-btype=card]:first-child]:grow` and nothing else. Measured aligned to
1px.

### 6.2 Grid monotony

At most **one** icon-above-heading card grid per page. Two on one page is the
named auto-fail. When content is genuinely ordinal (Register's three steps,
Home's "How to join"), it becomes a **numbered step ladder**, not cards: a
single `max-w-3xl` column of rows, each row `grid grid-cols-[auto_minmax(0,1fr)]
gap-5 sm:gap-8` with a `font-display text-4xl sm:text-5xl font-extrabold
tabular-nums text-ecs-green-ink/35 dark:text-ecs-green-300/35` numeral, the step
title at D4, the copy at B, and a hairline between rows. Ordinal eyebrows are
earned here and only here.

### 6.3 A page-level CTA is never a grid cell

`_b('button', col=1, …)` parked inside the middle column of a three-up is banned.
A page-level action lives in the section head or in its own full-width row.

### 6.4 `section_columns` gains a head slot (the single biggest structural fix)

Today a heading is authored as its own centred `content` section, so the heading
that labels a grid is separated from it by ~96px of padding **and** a rule. Give
`section_columns` (and `section_content`) an optional head slot rendered above
the grid **in the same `<section>`**:

```jinja
{% set head = section.blocks | selectattr('slot','equalto','head') | list %}
{% set body = section.blocks | rejectattr('slot','equalto','head') | list %}
```
`slot: 'head'` blocks render in a `max-w-3xl` stack above the grid with
`mb-10 sm:mb-14`. Blocks with no `slot` behave exactly as today, so nothing
existing changes until an author moves a block. **One section = one idea.**

### 6.5 Layout variants — the escape from "one shape per section type"

Two settings exist so a page can change *composition* without changing its
vocabulary. Both are opt-in; the stored default is the original shape.

**`hero.layout: 'split'`** — copy on the section ground at left, photography
bleeding off the right edge at `lg:w-[42%]`. Below `lg` it stacks. This is the
home page's hero and it exists because **an overlay hero puts the headline on
top of a photograph, where it needs a scrim to be legible at all**; a split hero
puts the headline on a real surface and lets the photograph be a photograph. It
also closes the "every hero wastes the right 55%" finding — the old shape was a
`max-w-2xl` text column inside `max-w-7xl` with nothing beside it.

⚠️ **A split hero's headline lives in a ~42%-narrower box, and the D1 ramp must
be sized for it.** At 128px, `overflow-wrap: anywhere` (mandatory for gate 51)
broke "EVERYONE" mid-word as "EVERYO / NE". D1 tops out at `lg:text-8xl` (96px)
for that reason. Do not restore the larger step and do not remove the wrap.

**`content.layout: 'side-head'`** — the heading sits in a left column with the
body copy beside it, rather than stacked above it. It is the third composition
family on a page that would otherwise alternate two, and exists to satisfy the
section-layout-repetition rule (§ 6.2): a page with 8 sections uses at least 4
different layout families.

### 6.6 `block_facts` — the scoreboard

A 4-up `<dl>` on the ink ground: season, team count, player count, next PLOP.
Display numerals at 900, `font-mono` labels, `tabular-nums`, hairline rules
between columns, and an add-to-calendar link inside the PLOP column. It is a
dynamic block (§ site_renderer `_dyn_facts`) and it is **the only thing on the
home page that proves a league is actually running** — the rest of the page is
claims, this is evidence.

Three rules that make it evidence rather than decoration:

1. **A column renders only when its value is real.** No zeroes, no em-dash
   placeholders, no "coming soon". A scoreboard with an empty slot is worse than
   a three-column scoreboard.
2. **Captions are derived or absent.** Nothing is written to fill the slot under
   a number. Inventing a caption is the same offence as inventing the number.
3. **A failing resolver must set `g.public_render_degraded`.** `RenderContext.
   _prefetch` catches resolver exceptions and falls back, but unlike
   `_dynamic_page_cache` it does not set that flag on its own — so without it a
   degraded facts band gets baked into the 300s render cache and the page serves
   *empty* instead of *stale* for five minutes.

---

## 7 · Component voice

### 7.1 Buttons — one base, three variants, eight states

**There is exactly one button geometry on this site.** `block_button`,
`block_cta_live`, the form submit, the news CTA, the calendar pills and the
error-page CTA all render from one `_btn_base` macro. Two buttons in the same
stack with different radius or padding is banned.

**Base (`_btn_base(size='md')`):**
```
inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full
px-6 py-3 min-h-11 font-semibold leading-none text-base
transition-[background-color,box-shadow,transform,color,outline-color] duration-150 ease-out
focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-offset-2
focus-visible:ring-offset-paper dark:focus-visible:ring-offset-paper-dark
motion-reduce:transition-none motion-reduce:transform-none
```
`size='sm'` swaps to `px-4 py-2.5 min-h-11 text-sm gap-1.5`. **`px-6.5` is off
the 4px scale and is deleted.** `min-h-11` is a hard floor everywhere.

| Variant | Off-colour | On brand/dark ground |
|---|---|---|
| **primary** (the ask) | `bg-ecs-blue-600 text-white shadow-sm hover:bg-ecs-blue-700 hover:shadow-md focus-visible:ring-ecs-blue-600` | `bg-white text-ecs-green-ink shadow-sm hover:bg-white/90 focus-visible:ring-white focus-visible:ring-offset-ecs-green-ink` |
| **secondary** (the brand action) | `bg-ecs-green-ink text-white hover:bg-ecs-green-ink/90 focus-visible:ring-ecs-green-ink` | `bg-white/20 text-white ring-1 ring-inset ring-white/70 hover:bg-white/30 focus-visible:ring-white` |
| **ghost** (the aside) | `text-ecs-green-ink ring-1 ring-inset ring-ecs-green-ink/35 hover:bg-ecs-green/10 hover:ring-ecs-green-ink/60 dark:text-ecs-green-300 dark:ring-white/25 dark:hover:bg-white/10 focus-visible:ring-ecs-green-ink dark:focus-visible:ring-ecs-green-300` | `text-white ring-1 ring-inset ring-white/60 hover:bg-white/15 focus-visible:ring-white` |

**Eight states, all required:**

1. **default** — as above.
2. **hover** — background/ring step **only**. No transform on a button (the lift
   is the card's signal).
3. **focus-visible** — 2px ring + 2px offset, **instant** (never inside the
   transition property list), ≥3:1 against both the button and the ground. The
   old `ring-ecs-green/50` with no offset (1.65:1, and invisible on a green
   button) is deleted everywhere.
4. **active** — `active:translate-y-px active:shadow-none active:brightness-95`.
   On touch this is the only feedback that exists; it is not optional.
5. **disabled** — `disabled:opacity-55 disabled:cursor-not-allowed
   disabled:shadow-none disabled:pointer-events-none aria-disabled:…` (same set
   for anchor-buttons).
6. **loading** — `aria-busy="true"`, `pointer-events-none`, leading icon swaps
   to `<i class="ti ti-loader-2 animate-spin motion-reduce:animate-none">`,
   label and width unchanged, shown only after 150ms.
7. **error** — the button never turns red. It returns to default; an inline
   `role="alert"` summary appears **above** the form and focus moves to it.
8. **success** — no celebratory modal, no toast. The form is **replaced** by a
   `role="status"` panel in the inset surface with specific copy.

**Colour-only `hover:opacity-90` is banned** — it dims the label too, so the
hover state has *less* contrast than rest.

### 7.2 Form fields — one spec

```
block w-full rounded-lg min-h-11 px-3.5 py-2.5 text-base
bg-white text-gray-900 placeholder:text-gray-500
dark:bg-white/[0.05] dark:text-white dark:placeholder:text-gray-400
border-0 ring-1 ring-inset ring-gray-400/70 dark:ring-white/20
hover:ring-gray-500 dark:hover:ring-white/30
focus:outline-hidden focus:ring-2 focus:ring-ecs-blue-600 dark:focus:ring-ecs-green-300
aria-[invalid=true]:ring-2 aria-[invalid=true]:ring-red-600 dark:aria-[invalid=true]:ring-red-400
disabled:opacity-55 disabled:cursor-not-allowed
transition-[box-shadow] duration-150 ease-out motion-reduce:transition-none
```

- `border-0` + `ring` so focus never shifts layout. The `@tailwindcss/forms`
  `border-gray-300` (1.47:1 — an invisible white box on a white page) is gone.
- `text-base` is mandatory: below 16px iOS Safari zooms the viewport on focus.
- **Every field reserves a helper slot**: `<p class="mt-1.5 min-h-5 text-sm
  text-gray-600 dark:text-gray-300">` rendered always, so an appearing error
  never reflows the form.
- **Required marker is a word, not a red asterisk**:
  `<span class="ml-1.5 text-sm font-normal text-gray-500 dark:text-gray-400">Required</span>`
  plus `aria-required="true"`. Red is reserved for the error state.
- `autocomplete` by field type (`name`, `email`, `off`). `aria-invalid`,
  `aria-describedby` wired to the helper slot.
- Radios/checkboxes get the same dark pair as text inputs
  (`dark:bg-white/[0.05] dark:border-white/20`), and any sr-only-radio +
  styled-span scale carries `peer-focus-visible:ring-2
  peer-focus-visible:ring-ecs-blue-600 peer-focus-visible:ring-offset-2`.
- `<select>` styles its options: `[&>option]:bg-white dark:[&>option]:bg-gray-900`;
  the placeholder option is `disabled`.
- **A validation miss must never destroy typed input.** Round-trip the submitted
  values, redirect to the form anchor, render per-field errors inline.
- The form is the page's object: it sits on the **inset surface** panel
  (`rounded-xl p-6 sm:p-8`) and fills its column.

### 7.3 Chips and badges — one spec each

| | Class string |
|---|---|
| **Interactive chip** (filter, tag link, category) | `inline-flex items-center gap-2 rounded-full px-4 py-2 min-h-11 text-sm font-semibold ring-1 ring-inset transition-colors duration-150 ease-out motion-reduce:transition-none focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-paper dark:focus-visible:ring-offset-paper-dark focus-visible:ring-ecs-green-ink` |
| — inactive | `bg-ecs-green/[0.08] text-gray-800 ring-ecs-green-ink/20 hover:bg-ecs-green/15 dark:bg-white/[0.05] dark:text-gray-100 dark:ring-white/15` |
| — active | `bg-ecs-green-ink text-white ring-ecs-green-ink` **+ `aria-current="page"` + a `ti-check` glyph** (selection must not be colour-only) |
| **Static badge** (status, type, program) | `inline-flex items-center gap-1.5 rounded-full px-3 py-1 min-h-6 text-xs font-bold uppercase tracking-[0.08em] ring-1 ring-inset` |

**The shared classes live outside the ternary.** An active chip losing its focus
ring because the ring string was inside the inactive branch is the exact bug this
rule prevents.

### 7.4 Links

- **Prose link:** `font-medium text-ecs-green-ink underline decoration-1
  underline-offset-2 decoration-ecs-green-ink/40 hover:decoration-2
  hover:decoration-ecs-green-ink dark:text-ecs-green-300
  dark:decoration-ecs-green-300/40` + the standard focus ring.
- **Nav / footer / button links:** no underline; the shape is the affordance.
- **On-colour link:** `text-white underline decoration-white/60`.
- Colour-alone links are banned (WCAG 1.4.1). `hover:underline` in a template
  where § 3.4's reset is still live is banned — fix the reset first.

### 7.5 Accordion (`<details>`)

- Padding on the **`<summary>`**, not the `<details>`, so the whole row is a
  ≥44px target.
- The question is a real heading inside the summary (`<h3 class="{D4}">`).
- `id` = slug + the scroll-padding from § 5.5, so every answer is linkable.
- `[&::-webkit-details-marker]:hidden` + `list-none`.
- Chevron: `transition-transform duration-150 ease-out group-open:rotate-180
  motion-reduce:transition-none` — never bare `transition`.
- Open state shifts the surface: `open:bg-ecs-green/[0.05]
  open:ring-ecs-green-ink/25 dark:open:bg-white/[0.05]`.

### 7.6 Tables

Wrapper `overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0`; table `min-w-[36rem] w-full`.
`<th scope="col">` at **E** with `text-gray-600 dark:text-gray-300` on a
transparent ground (no coloured header fill). Rows
`divide-y divide-black/[0.08] dark:divide-white/10`. Numeric cells `tabular-nums`.
A two-column key/value table becomes a `<dl>` instead.

### 7.7 Empty states

No dashed borders (Bootstrap-era tell), no centred-icon-plus-"check back soon".

```
rounded-xl bg-ecs-green/[0.05] ring-1 ring-inset ring-ecs-green-ink/15
dark:bg-white/[0.03] dark:ring-white/10 p-8 sm:p-10 text-left
```
Headline at **D4**, one sentence at **B**, and **exactly one action** — the live
CTA. Copy branches on cause: filtered-and-empty says what was filtered and offers
"Show all"; genuinely empty says what will land here and offers the waitlist.
An empty calendar or archive is the conversion moment, not a dead end.

### 7.8 Pagination

`grid grid-cols-[1fr_auto_1fr] items-center` with both end slots always
occupied (an `invisible` pill holds the space) so the label never jumps sideways
between pages. Pills at `min-h-11 px-5 py-2.5 text-sm font-semibold`.
`aria-current="page"`. Container width matches the content it paginates. Wrapped
in a `<section>` (§ 5.4).

### 7.9 Icons

Tabler only; no emoji as ornament. **Every decorative `<i class="ti …">` carries
`aria-hidden="true"`.** Where the glyph is the only content of a control, keep
`aria-hidden` on the glyph and add an `<span class="sr-only">` label. Icon-only
buttons are `h-11 w-11 inline-flex items-center justify-center rounded-full`.

---

## 8 · Motion

**Three primitives. Nothing else animates.**

| # | Primitive | Where | Spec |
|---|---|---|---|
| **1** | **Lift** | Cards only (whole-surface targets) | `hover:-translate-y-0.5 hover:shadow-md`, `duration-200 ease-out` |
| **2** | **Tint** | Buttons, chips, nav links, rows, inputs, accordions | background / ring / colour step, `duration-150 ease-out` |
| **3** | **Nudge** | A trailing arrow inside a hovered link or card | `group-hover:translate-x-0.5`, `duration-150 ease-out` |

Plus one **decorative exception**: the footer marquee (`animate-marquee-x`).

**NO SCROLL-REVEAL. (added 2026-08-23 — removed, not fixed.)** A `.rise`
IntersectionObserver fade-up shipped and was pulled. It was broken in a way worth
recording — only the *first* observed element ever fired, because a fast scroll
outruns the observer and everything below the fold is already intersecting by the
time it registers — but the reason it is gone is that it should not have been
there. **An identical fade-up on every element is a named AI tell.** Fixing the
observer would have delivered the tell working correctly. Content is present at
paint.

**Rules**

- Easing is Tailwind `ease-out` everywhere. **No spring, no overshoot, no bounce.**
- One signal per element class. A button, a card, a news tile and a social chip
  all doing the lift is banned.
- **`transition-all` and bare `transition` are banned.** Always name the
  properties: `transition-[background-color,box-shadow,transform,color]` or
  `transition-colors` / `transition-transform`.
- Never animate `width`, `height`, `top`, `left`, `margin`, `padding`.
- **Focus rings never transition** — `outline-color`/`ring-color` must be outside
  the transition property list or the ring fades in.
- **`motion-reduce:transform-none motion-reduce:transition-none` on every
  animated utility**, and `motion-reduce:animate-none` on the marquee and any
  spinner.
- **Smooth scrolling is opt-in per user**: every `scrollIntoView({behavior:
  'smooth'})` and `window.scrollTo` reads
  `matchMedia('(prefers-reduced-motion: reduce)')` and passes `'auto'` when set.
  A 14,000-word page's TOC jump is the canonical vestibular trigger.
- **The marquee needs a user-operable pause** (WCAG 2.2.2): `hover:
  [animation-play-state:paused] focus-within:[animation-play-state:paused]`
  **plus** a real pause control. `motion-reduce:animate-none` alone does not
  satisfy it.
- No scroll-triggered reveals, no parallax, no auto-rotating carousels.

---

## 9 · Nav and footer

### 9.1 Nav — **N1b (canonical SaaS three-section) + an inline season chip**

*Previous nav: N1a "AI nav" (wordmark-left · six inline links right-grouped ·
filled CTA hard-right · sticky · white · border-bottom) — the named fingerprint.
This build: **N1b + season chip**, because the site has six real destinations, a
persistent CTA, and one live fact (registration open / waitlist open / closed)
that is currently buried at 12px inside the hero. N7 is too loud for an audience
whose blocker is intimidation; N12's retracting banner adds a moving part to a
sticky stack that is already mis-measured, so the strip is fixed and scrolls away.*

**Structure, top to bottom:**

1. **Season chip** — *inside the bar, not a strip above it.* `font-mono
   text-[0.68rem] uppercase tracking-[0.14em]`, separated from the wordmark by a
   `border-l` hairline, carrying the live season and CTA state
   (`2026 Fall · Waitlist open`). `hidden md:flex` — below `md` the bar has no
   room and the state is the hero's job anyway.

   ⚠️ **It is nested inside grid column 1, alongside the wordmark — not added as
   a fourth grid child.** The bar's `grid-template-columns` is explicit and
   three-wide; a fourth child wraps to a second row and doubles the bar's
   height. This is the whole reason the chip lives in a flex row with the
   wordmark rather than standing on its own.

   *(This replaces the full-width `bg-ecs-green-ink` status strip. The strip was
   one more flat green rectangle on a site that already had four per page, and
   it spent 32px of vertical chrome on every page to say what the hero says
   louder.)*
2. **Bar** — `sticky top-0 z-40 bg-paper/95 dark:bg-paper-dark/95 backdrop-blur-sm
   border-b-2 border-ecs-green-ink` · `h-16 sm:h-20`.
   - **Left:** logo mark `h-10 w-10` + wordmark at **W** in Big Shoulders, visible
     from **320px** (`alt=""` on the mark, `aria-label="ECS Pub League — home"`
     on the anchor).
   - **Centre:** the link cluster at **N**, `gap-1`, each pill
     `rounded-full px-3.5 py-2 min-h-11 whitespace-nowrap`.
   - **Right:** `Log in` text link + **one filled `ecs-blue-600` primary pill**
     + theme toggle at `h-11 w-11`.
   - **Breakpoint is `lg:`, not `md:`.** Measured content is ~940px against
     736px available at 768px; today it silently clips the CTA under
     `overflow-x-clip`. The hamburger owns everything below 1024px.
3. **Active state is NOT a filled pill.** The primary CTA owns the only filled
   pill in the bar. Active = `text-ecs-green-ink font-bold` +
   `bg-ecs-green/[0.10]` + `aria-current="page"`, and the **same treatment
   appears in the mobile panel** (today it appears in neither).
4. **Submenus use the Flowbite dropdown** (`data-dropdown-toggle`), not
   `group-hover`/`group-focus-within` — iOS Safari never fires `:focus-within`
   on a clicked button, so today the submenus are unreachable on iPad. Needs
   `aria-haspopup`, `aria-expanded`, `aria-controls`, Escape, outside-click.
5. **Hamburger swaps glyph and label** on open (`ti-menu-2` ↔ `ti-x`,
   "Open menu" ↔ "Close menu") via `group-aria-expanded:` variants. The panel is
   `max-h-[calc(100dvh-5rem)] overflow-y-auto overscroll-contain`.
6. **Skip link** as the first child of `<body>`; `<main id="main" tabindex="-1">`.
7. `<nav aria-label="Main">` / `aria-label="Mobile">`.

### 9.2 Footer — **Ft8 Marquee + colophon.** Ft3 is deleted. ~~Ft5 Statement~~ is deleted too (2026-08-23).

**Why the statement went.** "No experience needed. Seriously." plus a lone
Waitlist button sat byte-identical on all nine pages, directly beneath the
marquee, directly beneath each page's own closing CTA band. The tail of every
page was therefore a four-part sequence — page CTA, marquee, statement,
colophon — of which three parts never changed, so the last screenful of the site
was the same everywhere and each page's real closing argument was only the
third-loudest thing on it. **One closer per page now:** the page's own CTA band,
then the marquee, then the colophon. The footer keeps no call to action of its
own; the header's Join button is sticky at every scroll position, so nothing is
lost by not repeating it a fourth time. The marquee takes the condensed cut.

*The current footer stapled a marquee on top of the Ft3 index columns it claimed
to replace — "Explore" mirrors the nav 1:1, so six of twelve footer links are
duplication of a bar the visitor can already see. Ft3 is the named AI footer
fingerprint and this page is not a hub.*

1. **Marquee band** — `bg-ecs-green-ink text-white`, **short brand tokens**, not
   a 60-character sentence with a full stop:
   `ECS PUB LEAGUE · NO EXPERIENCE NEEDED · EVERYONE PLAYS · SEATTLE ·`
   at **E**. Duration 32s. Keep the `aria-hidden` duplicate track + the
   `sr-only` real copy exactly as they are (C10). Add the pause control (§ 8).
2. **Statement** — one Big Shoulders display sentence at **D2**, ≤ 38ch, answering
   the audience's real question: *"No experience needed. Seriously."* — followed
   by **one** primary CTA. Nothing else.
3. **Colophon** — a single `flex flex-wrap gap-x-5 gap-y-2` row at **S**:
   `Contact · Discord · Email · Privacy · Terms · © 2026 Emerald City Supporters
   Pub League · Seattle, WA`. **"All rights reserved" is deleted.**
   No `<h2>` column heads (they polluted every page's outline with three 12px
   h2s); if any grouping survives, it is `<nav aria-label="…">` with a `<p>`
   label.
4. The `<footer>`'s green `border-t-2` is invisible against the green marquee it
   sits on — the rule moves **below** the band or is dropped.

---

## 10 · Copy voice

Warm, direct, specific. Written for someone who is worried they are not good
enough. **State the welcome before the ask.**

- **Headings are claims, not labels.** `About ECS Pub League` → `Everybody plays.`
  `PLOP Guest Policy` → `Bringing a friend to PLOP`. `Ready to give it a try?` →
  `Think you're not good enough? Come out anyway.` A heading that only restates
  the nav item is wasting the largest type on the page.
- **CTAs escalate by position; they do not repeat.** Seven identical
  "Join the Waitlist" labels on one page means the fifth carries no more urgency
  than the first. Nav = `Join` · hero = `Join the Fall waitlist` · division cards
  = `Join Classic` / `Join Premier` · closing band = `Come play with us` ·
  footer = `Waitlist`. Same destination, rising commitment.
- **Labels must fit on one line at 320px** (C8). 26 characters at 16px bold does
  not. `whitespace-nowrap` on every button + short labels.
- **Expand the in-group vocabulary once, warmly, and early.** `PLOP = Pub League
  Offseason Practice — a drop-in kickabout. Come to one to check us out.` Pick
  ONE expansion of PLOP and use it everywhere (the site currently ships two).
- **Never `Success` / `Error` / `Info` as a title.** The message is the content.
  Errors are inline `role="alert"`; success replaces the thing that succeeded
  with a `role="status"` panel. No SweetAlert modal on a marketing page.
- **Empty states say what will appear and offer the action.** Never "check back
  soon."
- **Scope signals on long pages.** A 14,000-word guide states its length,
  chapter count and last-updated date in the hero. An unbounded wall of text with
  no scope signal is a bounce.
- Typographic punctuation (§ 2.7). No em-dash/hyphen mixing: title separator is
  ` — ` everywhere (`Terms of Service — ECS Pub League`).

### 10.1 The AI-copy pass (added 2026-08-23)

Every string in the builders was swept for generated-prose patterns. The bans
that matter here, beyond the obvious vocabulary list (*seamless, elevate,
empower, unlock, transform, journey, vibrant, robust, curated, thriving, foster,
delve, leverage, ecosystem, immersive, unparalleled*):

- **The `Whether you're a ___ or a ___` construction.** Also `Join a community
  of ___`, `Take your game to the next level`, `Where ___ meets ___`, and
  `It's not just soccer, it's ___`.
- **Any headline with no proper noun and no number in it.** This is the single
  most reliable test on the page; a headline that could sit on any league's site
  is filler regardless of how it is phrased.
- **The triple-parallel closer** (*"Every age. Every level. Every game."*) more
  than once per site. It is a good device and it stops being one immediately.
- ⚠️ **"Premier" is a division name here.** It stays as a proper noun and is
  banned only as a marketing adjective.

⚠️ **A factual claim in marketing copy must be checked against the source
pages, not against what sounds right.** The draft carried *"No tryouts."* — a
clean, confident, on-voice line, and false: the About page says *"We hold
'tryouts' in both divisions only to make sure we can build evenly balanced
teams."* It ships as **"Nobody gets cut."**, which is the true version of the
reassurance the line was reaching for. An invented fact in the hero is worse
than a dull hero.

---

## 11 · Responsive contract

- Floors **320 / 375 / 414 / 768**, verified. Plus **1024** (the nav band) and
  **1280×800** (the fold budget).
- `overflow-x-clip` on `html`/`body` is a safety net, **not a layout tool.** If
  something is being clipped, it is broken — `overflow-x-clip` is why the nav CTA
  disappearing at 768px produced no visible error.
- **`sm:` step is mandatory** whenever a layout goes past one column, and
  whenever type steps between mobile and `lg:`. Jumping `text-sm` → `lg:text-base`
  strands the entire 640–1023px band.
- **44px minimum hit area** on every interactive element, everywhere: nav links,
  theme toggle, hamburger, chips, tags, pagination, social circles, form
  controls, accordion summaries, TOC rows, calendar pills. `h-10 w-10` icon
  buttons become `h-11 w-11`.
- **No two-line clickable text.** Ever.
- Wide content (tables, month grids, code) scrolls **inside its own
  `overflow-x-auto` container**, which must carry `tabindex="0"` and an
  accessible name so keyboard users can scroll it. A container that scrolls the
  *shape* of a table while shredding its *content* is not responsive — restructure
  below `sm:` instead.
- Breadcrumb-style truncation never cuts the specific end: show the leaf at
  narrow widths and the full path from `sm:` up.

---

## 12 · Per-page macrostructure assignment

One system, nine shapes. No page may adopt another page's macrostructure.

**HOW THESE REACH THE SITE (amended 2026-08-23).** The original note here said
every change below was "reachable through the rendering vocabulary and section
settings (C1)". That was the whole mistake. The vocabulary can restyle a stored
document; it cannot *reshape* one, and the changes in this table are reshapes —
moving a heading into a head slot, replacing a card grid with a ladder, deleting
a section. They live in the builders in `section_converter.py`, and they only
reach a live page when someone runs:

```
flask rebuild-public-pages --dry-run      # read the plan for all pages
flask rebuild-public-pages                # apply; snapshots each page first
```

Editing a builder without running that command changes nothing a visitor sees.
Editing the vocabulary without touching the builders changes how the *old* shape
is painted. Both halves, every time.

| Page | Macrostructure | The one structural change that gets it there |
|---|---|---|
| **Home** | **03 · Marquee Hero** | **SHIPPED 2026-08-23, rebuilt to the approved mockup.** A **split hero** — copy on the ground at left, photography bleeding off the right edge at `lg:w-[42%]` — replaces the full-bleed overlay, so the headline sits on a real surface instead of on an image. Orphan heading sections fold into what they label via `slot: 'head'` (§ 6.4). **Both** icon-tile three-ups are gone: the value propositions are a card-less `steps` list (style `plain`) and the join sequence is a real numbered `steps` ladder, which is the section that spends the page's brand green. The divisions are `lead` cards owning their own live CTA, each stamped with a **seal** straddling the photo seam — green "Start here" for Classic, blue "Step up" for Premier — so the badge names the division's job rather than decorating it. A **4-up `facts` scoreboard** on the ink ground carries the season, the team and player counts and the next PLOP with an add-to-calendar link; it is the only thing on the page that proves a league is running. **All photography full-colour.** The closing band is ink. |
| **About** | **15 · Split Studio** | Keep the alternating diptychs (they already are the shape) and give them `lg:items-center`. Replace the headingless two-photo `columns` section with **one `block_gallery`** with real captions, and promote the four-clause *"come out anyway"* run to a full-width **`block_quote` at D2** in its own section — the page's single Marquee moment and its emotional payload. |
| **Guide** | **02 · Long Document** | One editorial grid: a **server-rendered TOC side-rail** in the currently-dead right gutter at `lg:` (the toolbar stops being client-injected above the hero and stops shifting the document 48px on every load), body at BL with em-rhythm, `size='sm'` hero carrying chapter count + reading time + "jump to the lexicon". |
| **Guests** | **06 · Conversational FAQ** | The page already *is* four questions (TL;DR / Why we're cautious / But exceptions? / So what should I do?) trapped inside one richtext `<div>`. Split it into four Q-headed `content` sections at D3/D4 and **add a closing band with a real action** — today `<main>` contains zero focusable elements on a page whose message is "just reach out." |
| **FAQs** | **13 · Index-First** | The list IS the page. Hero absorbs a category jump-strip (the `Faq.category` column already exists and is unused); questions group under sticky category heads; every `<details>` gets a slug `id`; the hero stops being a 208px green slab with one word in it. |
| **Register** | **14 · Narrative Workflow** | **SHIPPED 2026-08-23 (5 sections, 12 blocks).** The ask lands after the prerequisite: live registration state (loud, § 12.1) → the three steps as a real `steps` ladder (§ 6.2) → the division choice → the CTA. The hero is the ink ground, not a green slab. Every section shares `width: normal`, so the page has one left edge instead of three. |
| **Contact** | **12 · Letter** | Lead with a short first-person lede in the site's voice, then the form as the page's single object on the inset surface, filling its column. "Other ways to reach us" demotes to a colophon-weight footnote, and the page gains a closing band back to the waitlist. |
| **News** | **20 · Ecosystem Index** | A **lead card** (`sm:col-span-2`, taller media, title at D3) breaks the twelve identical tiles, and posts group by a derived axis (year, or a title-prefix series) so the archive has structure even before anyone tags a post. Article detail gains a hero band so list and detail open the same way. |
| **Calendar** | **04 · Stat-Led** | The hero becomes the **next PLOP** — date, time and venue as the giant fact, with the register CTA under it — computed from data already in the template. The subscribe cluster demotes to outline pills inside a proper `<section>`; the month grid restructures to a day-grouped list below `sm:` instead of scrolling a 640px table sideways. |

### 12.1 Registration status is the loudest live element, not the quietest

`block_registration_status` currently renders all three genuinely different
states through one green pill at `text-xs` — so "Registration closed" reads as a
positive green badge, and the only live signal on `/register` is smaller than the
footer copyright. `site_renderer` must return `mode`, and the block branches:

| mode | Treatment |
|---|---|
| `open` | `bg-ecs-green-ink text-white` + `ti-door-enter` |
| `waitlist` | `bg-amber-100 text-amber-900 ring-amber-600/40 dark:bg-amber-400/15 dark:text-amber-200` + `ti-hourglass` |
| `closed` | `bg-gray-100 text-gray-700 ring-gray-400/50 dark:bg-white/[0.06] dark:text-gray-200` + `ti-lock` |

At **`text-sm sm:text-base`**, `min-h-8`, with a real sentence beside it on
`/register` ("Registration is closed — the 2026 Fall waitlist is open").

---

## 13 · DO-NOT — the AI tells found in these audits

Every item below was **found live on this site** and must not survive.

**Status note, 2026-08-23.** A live re-audit found that items **16** (two icon
three-ups on one page), **17** (a heading authored as its own section, a full
section's padding and a rule away from what it labels), **18** (a page-level CTA
parked in a grid cell) and **21** (a centred hero with everything on one axis)
were all still shipping — not because the rules were wrong but because they were
never applied to the stored documents. See the amended C1 and § 12. They are
fixed now, and `tests/test_public_site_builder.py::TestRebuiltDocuments` asserts
several of them so they cannot come back silently.

Two to add, from the 2026 field rather than from this site:

45. **A uniform 16px radius plus a soft shadow on every container.** "Corporate
    soft UI" is the look the field has moved hard away from, and a single radius
    applied to everything is a named AI-slop signature. A card must earn its
    container (§ 4.4).
46. **A flat colour wash over a photograph.** Where a photo needs to carry
    text, the answer is a black-based directional gradient scrim, never a hue
    laid over the image (§ 4.5). ⚠️ Note this DO-NOT survived the duotone's
    reversal — it was always about the *wash*, and the duotone turned out to be
    a more elaborate way of committing the same offence.

**Typography**
1. Inter as the display face. Any `font-extrabold` on an Inter element.
2. `xl:text-8xl` outside the ≤24-char headline bucket.
3. Display headings at `line-height: 1` (Tailwind's default above `text-5xl`).
4. One tracking value (`tracking-[-0.03em]`) applied from 96px down to 18px.
5. The same semantic level rendering at two sizes depending on which block
   authored it (a heading-block `h2` at 48px, a richtext `h2` at 24px).
6. An `h4` that is the same size and colour as body copy.
7. Straight quotes and `-` where an em dash belongs.
8. Dead classes that look like styling (`class="lead"`, `class="pl-guide-lex"`).

**Colour**
9. Any literal hex, `emerald-*`, `purple-*`, `pink-*`, or a frozen numeric stop
   in a public template. Seven different hardcoded brand greens/blues currently
   ship.
10. White text on `bg-ecs-green` (2.78:1). `text-white/90` on a brand band.
11. `text-ecs-green` as body text on white. `dark:text-ecs-blue-400` as the
    universal dark-mode accent (2.79:1).
12. **The brand hue changing between light and dark mode.**
13. Bare `text-gray-400` in light mode (2.55:1).
14. `#fff` page ground / flat `gray-950` dark ground.
15. White text painted on an arbitrary colour that came out of the database.

**Structure**
16. Two icon-above-heading three-column feature grids on one page.
17. A section heading authored as its own section, separated from what it labels
    by ~96px of padding **and** a rule.
18. A page-level CTA parked inside a grid cell.
19. Ft3 index-column footer whose first column mirrors the nav 1:1.
20. N1a "AI nav": wordmark-left, six inline links right-grouped, filled CTA
    hard-right.
21. A full-viewport centred hero with eyebrow, headline, lede and CTA all on the
    same centred axis (the error pages).
22. An eyebrow that restates the headline verbatim (`404 · Page not found` /
    "We couldn't find that page.").
23. Symmetric hero padding. Every section on the same `py-16 sm:py-20`.
24. A `<div>` between two `<section>`s that silently kills the site's rhythm rule.
25. Byte-identical duplicate templates (four error pages, three legal pages).

**Interaction**
26. Bare `transition` / `transition-all`.
27. The same `hover:-translate-y-*` on six unrelated element classes.
28. `hover:opacity-90` as a button's entire hover state.
29. Any interactive element missing `active:` or `disabled:` (currently: all of
    them).
30. A focus ring that is invisible (`ring-ecs-green/50` at 1.65:1, no offset,
    green-on-green).
31. A focus ring that exists only in one branch of a ternary.
32. Hover-only affordances: a `title=` attribute as the only route to content;
    `group-hover` submenus with no click path.
33. `SweetAlert` modals titled "Success" / "Error" / "Info" on a marketing page.
34. A celebratory success toast for something the user can already see.
35. Smooth-scroll with no `prefers-reduced-motion` check.
36. An auto-scrolling marquee with no user-operable pause.

**Content & craft**
37. Dashed-border empty states with a centred icon and "check back soon."
38. `alt=""` on a content photograph. Unlabelled `<i class="ti …">`.
39. Twelve identical "Read more" links with no distinguishing accessible name.
40. Three links to the same URL inside one card.
41. Lazy-loaded above-the-fold LCP images with no `srcset` and no dimensions.
42. Client-injected chrome that shifts the document on every load.
43. Hardcoded link rows that drift from the admin-editable nav.
44. `prefers-color-scheme` on a site whose dark mode is class-based.

---

## 14 · Out of scope for the implementation agents (user TODO)

These are real findings that **cannot** be fixed in a template, because the
content lives in the database or the media library. They are listed so nobody
tries and nobody forgets.

- Alt text and captions for the About/Guide photographs (media-library rows).
- Responsive variants + WebP + `width`/`height` for `/static/img/publeague/*` —
  until this runs, `_img_tag`'s `<picture>`/`srcset` branch is inert and every
  phone downloads 1024px JPEGs.
- A ≥2400px hero crop (the current hero is an 889×742 source upscaled 2.2×).
- Straight→curly punctuation in the stored section JSON.
- Tagging the news archive so the category/tag layer stops rendering nothing.
- Setting focal points (every image is at the 50%/50% default).
- Picking `prominence: 'lead'` on the two or three argument headings per page.
- **Standings and results.** Deliberately deferred, not overlooked. `Standings`
  is a real materialised table with `idx_standings_team_id_season_id`, so a
  results band is a plain indexed read whenever it is wanted. It needs
  `joinedload(Standings.team)`, and any match list **must** exclude special-week
  self-vs-self placeholder rows (`home_team_id != away_team_id`,
  `is_special_week.isnot(True)`) or the page renders "Ball Lobbers 0–0 Ball
  Lobbers".
- **Crests as a visual index** (needs crest assets), **form guide as graphics**
  (needs the standings band first), and a **counter-scrolling twin marquee** (a
  second row must carry real fixtures or results, or it is filler).

⚠️ **`_static_image_size()` now closes the CLS half of this.** `ctx.image()`
resolves intrinsic `width`/`height` for `/static/` images through PIL +
`safe_join`, cached at 512 entries, so the 8 marketing photos ship with
dimensions even though they are filesystem images rather than `MediaAsset` rows.
The `srcset` branch above is still inert — that one genuinely needs the media
work.

---

## 15 · Exports

`app/services/public_theme.py` is the source of truth for colour and font
tokens; `tailwind.config.js` binds them to utilities. For a Tailwind v4 `@theme`
block or a DTCG `tokens.json`, ask *"extend design.md with Tailwind exports"*.

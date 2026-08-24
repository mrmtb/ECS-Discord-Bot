# app/services/public_theme.py

"""
Public-site theming — the ONE source of truth for the palette + typography that
re-skin the whole marketing site from the Appearance screen.

Colors: two brand roles the public design actually uses — PRIMARY (green:
`ecs-green` utilities) and ACCENT (blue: `ecs-blue` utilities, CTAs + dark-mode
links). Each is stored as a hex and expanded here into the RGB-triplet CSS
variables the Tailwind config binds to, plus derived light/dark stops so a
single hex re-skins buttons, hovers, and links together.

DERIVED CONTRAST STOPS (design.md 3.1/3.2). The raw logo green is #40b050 —
2.78:1 against white. That is a *fill*, not an ink: it can never carry text and
white can never sit on it. So the design splits the roles, and the inks are
COMPUTED here rather than typed in, because an admin picking a pale green from
the Appearance colour picker must not be able to silently re-break contrast:

  --color-primary-ink-rgb      brand ink on light  (darken until >= 4.6:1 on the TINT FLOOR)
  --color-primary-on-dark-rgb  brand ink on dark   (mix toward white until >= 5:1 on paper-dark)
  --color-blue-on-dark-rgb     action ink on dark  (same, from the accent)
  --color-paper-rgb            page ground, light  (primary mixed 97% to white — never #fff)
  --color-paper-dark-rgb       page ground, dark   (near-black carrying a trace of the brand hue)

EVERY INK IS MEASURED AGAINST A REAL SURFACE, NEVER AGAINST WHITE. The public
site paints no white: the page is `paper`, sections tint to bg-ecs-green/[0.06],
panels and plates go to /[0.05] and /10. An ink derived against #ffffff clears
4.6:1 on a ground that does not exist and then lands at 4.05–4.46:1 on the ones
that do. So `_ink()` takes the tint floor (INK_TINT_FLOOR of the primary over
paper) as its ground, exactly as `_on_dark()` takes paper-dark as its.

`theme_vars()` also returns `primary_ink_contrast` — against that same tint
floor — so the Appearance screen can warn when a chosen primary cannot reach
4.6:1 even fully darkened.

Typography: a small set of curated, self-contained font PAIRS (system/loaded
stacks — no external font CDN, which the public CSP would block anyway),
emitted as `--font-heading` / `--font-body` and cascaded onto the page.

Everything here is pure (no DB) so it's cheap to call per request and easy to
test; the Appearance route reads the stored hexes/pair and passes them in.
"""

# slug -> {label, heading stack, body stack}
#
# EVERY family named below must actually resolve on a visitor's machine: either
# self-hosted (Bricolage Grotesque, Inter — see app/static/vendor/fonts/) or a
# system face, and always with a real fallback chain. Pointing a stack at a
# webfont that is not self-hosted is a SILENT failure here: the public CSP
# blocks font CDNs, so the page renders in system-ui with no error anywhere.
FONT_PAIRS = {
    # The default. Bricolage Grotesque is a warm, slightly irregular display
    # grotesk that gives the marketing site a voice Inter (a UI face) cannot;
    # Inter keeps the body copy, so the portal and the public site still read
    # as one product. Both are self-hosted variable fonts.
    'display':   {'label': 'Display — Big Shoulders headings, Inter body',
                  'heading': "'Big Shoulders Display', 'Haettenschweiler', 'Arial Narrow', system-ui, sans-serif",
                  'body': "'Inter', system-ui, -apple-system, sans-serif",
                  'mono': "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"},
    'modern':    {'label': 'Modern — clean sans (Inter)',
                  'heading': "'Inter', system-ui, -apple-system, sans-serif",
                  'body': "'Inter', system-ui, -apple-system, sans-serif"},
    'classic':   {'label': 'Classic — serif headings, sans body',
                  'heading': "Georgia, 'Times New Roman', serif",
                  'body': "'Inter', system-ui, -apple-system, sans-serif"},
    'editorial': {'label': 'Editorial — all serif',
                  'heading': "Georgia, 'Times New Roman', serif",
                  'body': "Georgia, 'Times New Roman', serif"},
    'friendly':  {'label': 'Friendly — rounded sans',
                  'heading': "'Trebuchet MS', 'Segoe UI', system-ui, sans-serif",
                  'body': "'Segoe UI', system-ui, sans-serif"},
    'strong':    {'label': 'Strong — bold geometric',
                  'heading': "'Futura', 'Century Gothic', 'Trebuchet MS', system-ui, sans-serif",
                  'body': "'Inter', system-ui, sans-serif"},
}
DEFAULT_FONT_PAIR = 'display'


def font_pair(slug):
    """Resolve a stored font-pair slug to its {label, heading, body} dict.

    Callers should route through this (or pass the slug straight to
    `theme_vars`) instead of hardcoding a fallback slug — an unknown or missing
    value must land on DEFAULT_FONT_PAIR, so that changing the default here
    actually changes the site.
    """
    return FONT_PAIRS.get(slug) or FONT_PAIRS[DEFAULT_FONT_PAIR]

# Section rhythm — how consecutive sections are separated on a public page.
#
# WHY THIS IS A SETTING AND NOT A HARDCODED STYLE: a page's sections are composed
# by a volunteer at runtime, and each section already carries its own `theme`
# (inherit/light/dark/brand). Baking a separator into the section macros would
# override an authoring decision nobody could undo. Making it a site-wide
# Appearance choice keeps ONE person (the admin) in control of page rhythm
# without touching any individual section.
#
# Implemented as CSS adjacent-sibling / nth-of-type utilities applied to <main>,
# NOT as an index passed into the macros. That matters: render_single_section()
# renders a ONE-section document for the editor's swap payload, so any Jinja
# index would always be 0 and a swapped section would visibly change appearance
# on edit and change back on reload. CSS re-evaluates against real DOM position,
# so it stays correct through editor swaps.
SECTION_RHYTHM = {
    'auto': {
        'label': 'Automatic — a rule only where the ground does not change',
        # The default (design.md 5.4). The old 'hairline' default drew a rule
        # between EVERY pair of sections, including two that already share a
        # tint or that step from light to brand — where the ground change is
        # itself the seam, so the rule was redundant, and at border-ecs-green/15
        # (1.15:1) it was invisible anyway. This draws the hairline only where
        # BOTH neighbours declined a background of their own; a themed section
        # carries its own seam. Additive and purely positional-in-CSS, so it
        # survives the editor's single-section swap (see the note above).
        #
        # NOTE FOR TEMPLATE OWNERS: this selector matches `<main> > section +
        # section`. Anything that is a direct child of <main> and is NOT a
        # <section> (a bare pagination <div>, a page-level <script>) breaks the
        # adjacency for the rest of the page.
        'classes': ('[&>section:not([class*=bg-])+section:not([class*=bg-])]:border-t '
                    '[&>section:not([class*=bg-])+section:not([class*=bg-])]:border-ecs-green-ink/20 '
                    'dark:[&>section:not([class*=bg-])+section:not([class*=bg-])]:border-white/10'),
    },
    'none': {
        'label': 'None — sections separated by spacing only',
        'classes': '',
    },
    'hairline': {
        'label': 'Hairline — a soft rule between every section',
        # Additive only: draws a rule between adjacent sections. Never changes a
        # section's own background, so a volunteer's theme choice is untouched.
        # Raised from ecs-green/15 (1.15:1 — below the threshold at which a 1px
        # rule registers at all) to the brand ink at /25, which reads as a rule
        # without reading as a divider.
        'classes': '[&>section+section]:border-t [&>section+section]:border-ecs-green-ink/25 '
                   'dark:[&>section+section]:border-white/15',
    },
    'tint': {
        'label': 'Alternating tint — every other section on a warm ground',
        # Only paints sections that did NOT opt into their own background, so an
        # explicitly light/dark/brand section keeps exactly what the author chose.
        'classes': '[&>section:nth-of-type(even):not([class*=bg-])]:bg-ecs-green/[0.04] '
                   'dark:[&>section:nth-of-type(even):not([class*=bg-])]:bg-white/[0.02]',
    },
}
DEFAULT_SECTION_RHYTHM = 'auto'


def section_rhythm_classes(key):
    """Tailwind utility string for the chosen rhythm. Unknown/missing -> none."""
    return SECTION_RHYTHM.get(key, SECTION_RHYTHM[DEFAULT_SECTION_RHYTHM])['classes']

DEFAULT_PRIMARY = '#40b050'   # ECS Pub League logo green
DEFAULT_ACCENT = '#203090'    # ECS Pub League logo blue

# The near-black the dark page ground is built from. Not #000 and not a flat
# neutral: the primary is mixed 6% into it so the dark site still sits on a
# ground that belongs to the brand (design.md 3.1).
PAPER_DARK_BASE = (6, 10, 8)

# The WARM PAPER BASE. The page ground used to be `_mix_white(primary, 0.97)` —
# the brand green mixed 97% toward pure white, which lands on a pale mint. That
# reads as "a tint of the brand" rather than as paper, and it is the single
# biggest reason the public site looked templated: with a mint ground, a green
# tint band and white cards, the whole page was three near-whites of the same
# hue and nothing had any weight.
#
# The replacement is a COOL grey-green newsprint, not a warm cream. Warm cream
# paired with a display face and an earth accent is the most-recognised
# generated-design palette going, and against this club's green it also reads
# yellow. A cool ground lets the green stay green. `paper` is that ground,
# nudged a trace toward the primary so an admin re-skin still tints it.
PAPER_WARM_BASE = (232, 236, 230)

# How far `paper` is pulled from the newsprint base toward the primary.
# Deliberately tiny. The trace has to survive an Appearance re-skin (a
# red-branded site should get a faintly warm-red paper, not this exact grey)
# without the brand colour reasserting itself as the page colour. At 0.015 the
# default lands on #e5ebe4.
#
# NOTE the PAPER_WARM_* names are a fossil of the warm-cream pass that this
# replaced; the values are cool. Renaming them would touch design.md, the tests
# and two call sites for no behavioural gain, so the names stay and this comment
# is the correction.
PAPER_WARM_MIX = 0.015

# The TINT FLOOR: the darkest light-mode surface the brand ink is allowed to be
# text on, expressed as a fraction of the primary composited over `paper`.
#
# The design vocabulary paints exactly four tinted grounds under ink-coloured
# text — bg-ecs-green/[0.05] (callouts, forms, empty states), /[0.06] (section
# theme 'light'), /[0.08] (inactive chip) and /10 (icon + date plates, the ghost
# button's hover ground). The worst real case is the deepest of those nested
# inside a 'light' section: 0.10 over 0.06 == 0.154 of the primary over paper.
# MEASURED 2026-08-23 and raised to 0.20. The 0.15 figure modelled /10 over a
# 'light' section. The contact page goes one layer deeper — an icon plate at /10
# inside a callout at /[0.05] inside a 'light' section at /[0.06] composites to
# ~0.196 of the primary — and the brand ink landed at 4.19:1 on those social
# buttons, below the 4.5 floor for 16px text. The constant is the DEEPEST real
# nesting, not the common one; under-modelling it produces exactly one class of
# almost-passing contrast bug.
INK_TINT_FLOOR = 0.20


def _hex_to_rgb(hex_str):
    try:
        h = (hex_str or '').lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) != 6:
            return None
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return None


def _hex(rgb):
    """RGB tuple -> '#rrggbb'. Inverse of _hex_to_rgb."""
    if not rgb:
        return None
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _triplet(rgb):
    return f'{rgb[0]} {rgb[1]} {rgb[2]}' if rgb else None


def _scale(rgb, factor):
    """Lighten (factor>1) or darken (factor<1) an RGB tuple, clamped."""
    if not rgb:
        return None
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)


def _mix_white(rgb, t):
    """Move `rgb` a fraction `t` (0..1) of the way toward white."""
    if not rgb:
        return None
    return tuple(max(0, min(255, round(c + (255 - c) * t))) for c in rgb)


def _mix_toward(rgb, base, t):
    """Return `base` nudged a fraction `t` (0..1) of the way toward `rgb`.

    t=0 is `base` untouched, t=1 is `rgb`. Used to tint the near-black dark
    ground with a trace of the brand hue.
    """
    if not rgb or not base:
        return None
    return tuple(max(0, min(255, round(b + (c - b) * t)))
                 for c, b in zip(rgb, base))


def _rel_luminance(rgb):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a, hex_b='#ffffff'):
    """WCAG contrast ratio between two hex colors (default vs white). Returns a
    float; >= 4.5 passes AA for normal text, >= 3.0 for large text / UI."""
    a, b = _hex_to_rgb(hex_a), _hex_to_rgb(hex_b)
    if not a or not b:
        return 0.0
    la, lb = _rel_luminance(a), _rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def _ink(rgb, ground=None, min_ratio=4.6):
    """Darken `rgb` toward black until it clears `min_ratio` against `ground`.

    The result is the BRAND INK: the only green that may be text on a light
    ground, and the only green that may sit under white text.

    WHY `ground` IS NOT WHITE. The obvious reference is `#ffffff`, and that is
    what the first cut of this used — but **no public surface is white.** The
    page ground is `paper` (the primary mixed 97% toward white), section theme
    'light' is `bg-ecs-green/[0.06]`, callouts / forms / empty states are
    `bg-ecs-green/[0.05]`, icon and date plates are `bg-ecs-green/10`, and the
    ghost button's hover ground is `bg-ecs-green/10` — which, inside a tinted
    section, composites to ~15% of the primary over paper. Every one of those is
    darker than white, so an ink measured against white spends its whole 4.6:1
    headroom before the text is drawn: the stock green landed at 4.05–4.46:1 on
    the tinted panels (prose links, "Read every story", ghost buttons, the
    calendar month-grid pills at 11px). Measuring against the DARKEST surface the
    ink is allowed to sit on makes the pass real everywhere, and white ground —
    being lighter — passes automatically with room to spare.

    #40b050 -> ground #ddf1e0 -> f=0.68 -> #2c7836 -> 4.61:1 on the tint floor,
    5.46:1 on white, and 5.46:1 for white text sitting ON it (brand bands).

    Bottoms out at f=0.30 rather than looping forever; if a pathologically pale
    primary still cannot clear the bar, the caller sees it in
    `primary_ink_contrast` and the Appearance screen can warn.
    """
    if not rgb:
        return None
    ground = ground or '#ffffff'
    f, out = 1.0, rgb
    while f > 0.30 and contrast_ratio(_hex(out), ground) < min_ratio:
        f = round(f - 0.02, 2)
        out = _scale(rgb, f)
    return out


def _on_dark(rgb, ground=None, min_ratio=5.0, start=0.25):
    """Mix `rgb` toward white — never less than `start` — until it clears
    `min_ratio` against the dark page ground.

    This is the same hue read on a dark ground, NOT a different accent: the
    site's green must stay green and its blue must stay blue when the theme
    flips (design.md 3.5).

    green -> t=0.25 -> #70c47c (9.5:1); blue -> t=0.40 -> #7983bc (5.6:1).
    """
    if not rgb:
        return None
    ground = ground or _hex(_mix_toward(_hex_to_rgb(DEFAULT_PRIMARY),
                                        PAPER_DARK_BASE, 0.06))
    t, out = start, _mix_white(rgb, start)
    while t < 0.80 and contrast_ratio(_hex(out), ground) < min_ratio:
        t = round(t + 0.05, 2)
        out = _mix_white(rgb, t)
    return out


def theme_vars(primary_hex=None, accent_hex=None, font_pair=None):
    """Return the CSS-variable map + resolved font stacks the public shell
    injects. Falls back to brand defaults for any missing/invalid value."""
    primary = _hex_to_rgb(primary_hex) or _hex_to_rgb(DEFAULT_PRIMARY)
    accent = _hex_to_rgb(accent_hex) or _hex_to_rgb(DEFAULT_ACCENT)
    pair = FONT_PAIRS.get(font_pair) or FONT_PAIRS[DEFAULT_FONT_PAIR]

    # Grounds first — every ink is measured against a real page surface, so the
    # surfaces have to exist before the inks are computed.
    paper = _mix_toward(primary, PAPER_WARM_BASE, PAPER_WARM_MIX)
    paper_dark = _mix_toward(primary, PAPER_DARK_BASE, 0.06)
    paper_dark_hex = _hex(paper_dark)
    # The darkest LIGHT-mode ground the brand ink may be text on: the primary at
    # INK_TINT_FLOOR over paper (_mix_toward nudges `paper` that fraction toward
    # `primary`, which is exactly what `bg-ecs-green/15` composites to).
    # The GREEN SECTION GROUND. Plain `primary` is too light to carry white body
    # copy — #40b050 gives 4.35:1, which fails AA — so a section painted in it
    # either fails contrast or has to shout in large type only. This darkens the
    # primary until white clears 4.5:1 against it, exactly the way the brand ink
    # is derived, so an admin re-skin keeps working instead of freezing a hex.
    pitch_ground = _ink(primary, '#ffffff', 4.6)

    ink_ground = _mix_toward(primary, paper, INK_TINT_FLOOR)
    ink_ground_hex = _hex(ink_ground)

    primary_ink = _ink(primary, ink_ground_hex, 4.6)
    primary_on_dark = _on_dark(primary, paper_dark_hex, 5.0, start=0.25)
    accent_on_dark = _on_dark(accent, paper_dark_hex, 5.0, start=0.30)

    css = {
        '--color-primary-rgb': _triplet(primary),
        '--color-primary-dark-rgb': _triplet(_scale(primary, 0.8)),
        '--color-primary-ink-rgb': _triplet(primary_ink),
        '--color-primary-on-dark-rgb': _triplet(primary_on_dark),
        '--color-blue-rgb': _triplet(accent),
        '--color-blue-dark-rgb': _triplet(_scale(accent, 0.82)),
        '--color-blue-light-rgb': _triplet(_scale(accent, 1.45)),
        '--color-blue-on-dark-rgb': _triplet(accent_on_dark),
        '--color-pitch-ground-rgb': _triplet(pitch_ground),
        '--color-paper-rgb': _triplet(paper),
        '--color-paper-dark-rgb': _triplet(paper_dark),
        '--font-heading': pair['heading'],
        '--font-body': pair['body'],
        '--font-mono': pair.get('mono', "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"),
    }
    return {
        'css': css,
        'primary_hex': primary_hex or DEFAULT_PRIMARY,
        'accent_hex': accent_hex or DEFAULT_ACCENT,
        'font_pair': font_pair if font_pair in FONT_PAIRS else DEFAULT_FONT_PAIR,
        # AA contrast of white text on each brand color (buttons use white text).
        'primary_contrast': contrast_ratio(primary_hex or DEFAULT_PRIMARY),
        'accent_contrast': contrast_ratio(accent_hex or DEFAULT_ACCENT),
        # The derived brand ink and its contrast. `primary_contrast` above is
        # the raw fill and is EXPECTED to fail (2.78:1 for the stock green) —
        # that is why the ink exists. This is the number the Appearance screen
        # should warn on: below 4.6 means the chosen primary could not be
        # darkened far enough and green text/bands will fail AA site-wide.
        #
        # It is reported against `ink_ground_hex`, the SAME reference the search
        # used — the darkest tinted panel the ink is allowed to sit on. Quoting
        # it against white instead would have shown a comfortable 5.46:1 while
        # the calendar pills were failing at 4.05:1, i.e. a warning that is
        # truthful only where the problem never was.
        'primary_ink_hex': _hex(primary_ink),
        'primary_ink_contrast': contrast_ratio(_hex(primary_ink), ink_ground_hex),
        # White text ON the ink — the brand band / filled-secondary direction.
        'primary_ink_on_white_contrast': contrast_ratio(_hex(primary_ink)),
        'ink_ground_hex': ink_ground_hex,
        'paper_hex': _hex(paper),
        'paper_dark_hex': paper_dark_hex,
    }


def css_var_block(vars_css):
    """Render the theme CSS-var map into a ``:root{…}`` declaration string."""
    decls = ' '.join(f'{k}: {v};' for k, v in vars_css.items() if v)
    return f':root {{ {decls} }}'

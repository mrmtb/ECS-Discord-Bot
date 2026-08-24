# app/services/section_converter.py

"""
Total conversion to the section model — runs once, idempotently, at boot.

Converts every public page to the ONE composition model (sections_draft /
sections_published), after which the legacy render paths (body_html blobs,
GrapesJS output, hardcoded home.html middle) are dead code:

  * home           — named blocks (home_hero/intro/justforfun/divisions) PLUS
                     the hardcoded home.html middle (value cards, how-to-join,
                     divisions layout, CTA band, latest-news) become one real
                     'home' sections page.
  * about/guide/guests + custom pages — hero_json + rich-text body -> sections.
  * register/contact/faqs — fixed templates re-expressed as section pages with
    live blocks (registration_status, cta_live, form, faq_list).
  * GrapesJS '<style' pages — best-effort embed_raw conversion, revision label
    'converted-needs-review' + warning log for a manual pass.

Also one-time-sanitizes legacy news/FAQ HTML (marker in site_settings so it
runs once), since those rows predate the nh3 save path.

Idempotency: a page is only converted when BOTH sections columns are NULL, so
re-boots and multi-worker races (advisory-locked by the caller) are safe, and
an admin's later edits are never overwritten.

DESIGN NOTE (design.md C1 — read this before "fixing" a live page here).
Because of that idempotency guard, NOTHING in this module restyles a page that
already has sections, and all nine live pages do. Everything below is the shape
a page is BORN with: the Add-New-Page starter templates, and the from-scratch
rebuild of each fixed page. It exists so new content cannot be born in the old
design language. To change a live page you edit the rendering vocabulary
(app/templates/public/sections/macros.html) or the stored section JSON in the
site editor — never this file.

Every composition here follows design.md:
  * per-page macrostructure assignments (§ 12),
  * `slot: 'head'` instead of an orphan heading section (§ 6.4),
  * `prominence: 'lead'` on at most two or three headings per page (§ 2.4),
  * a numbered step ladder — never a second icon-card three-up — for ordinal
    content (§ 6.2),
  * a page-level CTA in its own row, never inside a grid cell (§ 6.3),
  * CTA labels that escalate rather than repeat (§ 10),
  * typographic punctuation only (§ 2.7).

`slot`, `prominence` and the two-column `align` setting are OPTIONAL keys. They
are read by macros.html; app/services/section_schema.py must carry them through
validate_sections() or they are silently dropped (the composition still renders,
it just loses the head/lead distinction). Emitting them is deliberate and
forward-compatible.
"""

import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

_SANITIZE_MARKER = 'legacy_content_sanitized_v1'

# ONE expansion of PLOP, everywhere (design.md § 10). The site used to ship two
# — "Pub League Open Practice" and "Pub League Offseason Practices" — so the
# in-group term got expanded twice, differently. Change it here only.
_PLOP = 'Pub League Offseason Practice'

# Defaults mirrored from the pre-conversion home.html template so a site that
# never customized a block converts to exactly what it was rendering.
_D = {
    # The display face is uppercase and condensed, so the hero headline has to
    # be SHORT — two or three words. "Everyone plays" is the league's own
    # promise and the strongest two words it has. The explanatory sentence moves
    # to the lede, where it belongs.
    'hero_title': 'Everyone plays.',
    'hero_body': '<p>Beginner-friendly adult soccer in Seattle. Nobody gets cut, '
                 'no experience is needed, and everyone on the roster gets '
                 'minutes.</p>',
    'intro_title': 'Soccer for all',
    # Two large sentences, not a paragraph of marketing. Both are the league's
    # own argument, tightened.
    'intro_body': '<p>Seattle has a deep, talented soccer scene, and almost '
                  'nowhere for a beginner to start.</p>'
                  '<p>So we built the league where your opponents high-five you '
                  'for scoring, especially if it’s your first goal ever.</p>',
    'classic_title': 'Classic',
    'classic_body': '<p>For players with little or no experience. Fun and skill '
                    'development over competition, equal playing time, and every '
                    'team makes the playoffs. New players start here.</p>',
    'premier_title': 'Premier',
    'premier_body': '<p>A slightly higher level of friendly competition: still '
                    'low contact and laid-back, with the same emphasis on '
                    'development, team play and fun. Everyone plays.</p>',
    'justforfun_body': '<p>Both divisions play 8v8 on a half-field with unlimited subs. '
                       'If you’ve played in the other Seattle leagues (RATS, GSSL, Arena '
                       'Sports) or have college or club experience, this probably isn’t '
                       'the league for you — our level is well below even their lowest '
                       'divisions, and that’s the point.</p>'
                       '<p>ECS Pub League is part of <a href="https://weareecs.com/fc">ECS FC</a>, '
                       'the nonprofit soccer club established by Emerald City Supporters.</p>',
}

# The ONE icon-above-heading card grid the home page is allowed (design.md
# § 6.2 — two on a page is the named auto-fail).
# The three value propositions. They used to be a row of three cards, each with
# a 40px tinted icon chip above a three-word title — design.md DO-NOT 16, and
# the most recognisable AI-generated layout on the web. They are now a
# rule-separated list (`steps`, style 'plain'): no container, no icon, no
# shadow. Three equal-weight claims have no hierarchy for a card to express, so
# hairlines and space group them instead. The icons went with the cards.
_VALUE_CARDS = [
    ('Radically inclusive', '<p>All skill levels, all backgrounds, all bodies. We mean it.</p>'),
    ('Real community', '<p>A Discord full of teammates who become friends off the pitch too.</p>'),
    ('Beginner-friendly', '<p>Never played? Perfect. Coaches and teammates have your back.</p>'),
]

# Ordinal content -> a numbered step ladder, NOT cards (design.md § 6.2).
# (title, body) pairs feed the `steps` block, which supplies the ordinals
# itself so nobody ships "Step 1 / Step 2" as literal copy and nobody has to
# renumber after a reorder. The icons went with the card grid this replaced.
_JOIN_STEPS = [
    ('Come to a PLOP',
     f'A {_PLOP}: a drop-in kickabout. Meet people, get a feel for the game, '
     'and commit to nothing.'),
    ('Get approved',
     'New players are approved before they register, so every team stays '
     'balanced and every division stays welcoming.'),
    ('Register, or join the waitlist',
     'When registration is open, sign up. When a season is full, the waitlist '
     'is the way in — and it moves.'),
]


def _focal_pair(css_value):
    """'50% 30%' -> [0.5, 0.3]; anything unparseable -> centered."""
    try:
        x, y = (css_value or '').replace('%', '').split()
        return [max(0.0, min(1.0, float(x) / 100)),
                max(0.0, min(1.0, float(y) / 100))]
    except Exception:
        return [0.5, 0.5]


def _static_img(filename_key):
    from app.public_site import _IMG_FILES
    return f'/static/img/publeague/{_IMG_FILES[filename_key]}'


def _s(stype, blocks, theme='inherit', **settings):
    return {'type': stype, 'theme': theme, 'settings': settings, 'blocks': blocks}


def _b(btype, **fields):
    d = {'type': btype}
    d.update(fields)
    return d


def _head(block):
    """Mark a block as the section's head slot (design.md § 6.4): it renders in
    a narrow stack ABOVE the grid, inside the SAME <section>. This is what
    replaces authoring a heading as its own centred `content` section — the
    named structural tell where a heading is separated from the thing it labels
    by a full section's padding AND a rule."""
    block['slot'] = 'head'
    return block


def _esc(value):
    """Escape user/admin-supplied plain text that is about to be dropped into a
    block's `html` field. validate_sections sanitizes on the way in as well;
    this keeps a title with an ampersand or a stray '<' from being mangled or
    swallowed rather than rendered."""
    from markupsafe import escape
    return str(escape((value or '').strip()))


def _callout_blocks(tone, title, html):
    """A `callout` block (design.md § 3.14 / macros.html `block_callout`) when
    the schema knows that type, and the SAME content as heading + richtext when
    it does not.

    Not a stylistic hedge: `validate_sections` DROPS a block whose type it does
    not recognise, so emitting `callout` unconditionally would silently delete
    the content on any deploy where section_schema.py has not registered it.
    The section that carries these blocks is themed `light`, which is the same
    inset surface the callout paints — so the fallback degrades in weight, never
    in meaning."""
    try:
        from app.services.section_schema import VOLUNTEER_BLOCK_TYPES
        supported = 'callout' in VOLUNTEER_BLOCK_TYPES
    except Exception:
        supported = False
    if supported:
        return [_b('callout', tone=tone, title=title, html=html)]
    return [_b('heading', level=3, html=title), _b('richtext', html=html)]


_HEADING_RE = re.compile(r'<(h[34])(?![^>]*\sid=)([^>]*)>(.*?)</\1>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')


def _slugify(text):
    slug = re.sub(r'[^a-z0-9]+', '-', _TAG_RE.sub(' ', text or '').lower()).strip('-')
    return slug[:60].strip('-')


def _add_heading_ids(html, seen):
    """Give every h3/h4 in converted long-form HTML a stable slug id, so the
    guide's ~43 subsection deep links resolve and the reader chrome can build a
    real outline. Headings that already carry an id are left alone; `seen`
    de-duplicates across the whole document."""
    def _repl(m):
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        base = _slugify(inner) or 'section'
        slug, n = base, 2
        while slug in seen:
            slug = f'{base}-{n}'
            n += 1
        seen.add(slug)
        return f'<{tag}{attrs} id="{slug}">{inner}</{tag}>'
    return _HEADING_RE.sub(_repl, html or '')


# --------------------------------------------------------------------------- #
# Doc builders
# --------------------------------------------------------------------------- #

def build_home_doc(session):
    """Home — macrostructure 03 · Marquee Hero (design.md § 12).

    The hero IS the page above the fold: the live registration state, the
    claim, the lede and ONE CTA row. Below it, the ten-section list of
    equally-weighted announcements collapses: every heading that labels a grid
    now rides in that grid's head slot, and the second icon-tile three-up
    becomes a numbered step ladder."""
    from app.models import SitePage
    from app.models.admin_config import AdminConfig

    # Degrade gracefully: if the table/columns aren't there yet (deploy window
    # before the SQL runs), fall back to all-defaults so the home page still
    # renders — matching the pre-builder template's behavior instead of 404ing.
    try:
        blocks = {p.slug: p for p in session.query(SitePage).filter(
            SitePage.slug.in_(['home_hero', 'home_intro', 'home_justforfun',
                               'home_division_classic', 'home_division_premier']),
            SitePage.deleted_at.is_(None)).all()}
    except Exception:
        blocks = {}

    def _block(slug, attr, default):
        pg = blocks.get(slug)
        return (getattr(pg, attr, None) or default) if pg else default

    # THE H1 IS LENGTH-GATED, and that is deliberate.
    #
    # D1 steps its own size down as the headline gets longer (design.md § 2.5),
    # so a long hero title does not overflow — it just renders small. The stored
    # title is 62 characters ("Radically inclusive, beginner-friendly adult
    # soccer in Seattle."), which drops it two buckets and wraps it over four
    # lines at 1440px, with the right half of the hero empty beside it. A hero
    # headline that needs four lines is a copy length problem, not a type
    # problem.
    #
    # So: use the stored title when it fits the top bucket, and fall back to the
    # short line otherwise rather than silently rendering a weak hero. Both
    # strings are the league's own words. Once this page is rebuilt the headline
    # lives in the section document and is editable in the site editor like any
    # other block, so this gate only ever decides what the page is BORN with.
    _stored_title = _block('home_hero', 'title', None)
    hero_title = _stored_title if (_stored_title and len(_stored_title) <= 55) \
        else _D['hero_title']

    hero_img = _block('home_hero', 'og_image_url', None) or _static_img('hero')
    focal = _focal_pair(AdminConfig.get_setting('public_hero_focal', '50% 50%'))
    overlay = AdminConfig.get_setting('public_hero_overlay', 'medium')
    if overlay not in ('none', 'light', 'medium', 'heavy'):
        overlay = 'medium'

    classic_img = _block('home_division_classic', 'og_image_url', None) \
        or '/static/img/publeague/2026-07__ZUZU-TEAM-1024x683.jpg'
    premier_img = _block('home_division_premier', 'og_image_url', None) \
        or '/static/img/publeague/2026-07__Astral_Shield-1024x576.jpg'
    jff_img = _block('home_justforfun', 'og_image_url', None) or _static_img('community2')

    sections = [
        # 1 · MARQUEE HERO — live state, the claim, one CTA row. The two CTA
        #     blocks are CONSECUTIVE on purpose: macros.html collects a run of
        #     button/cta_live blocks into one row (design.md § 5.3) instead of
        #     stacking two equally-weighted centred buttons.
        _s('hero', [
            _b('registration_status'),
            _b('heading', level=1, html=hero_title),
            _b('richtext', html=_block('home_hero', 'body_html', _D['hero_body'])),
            _b('cta_live', kind='waitlist_or_register', style='primary'),
            _b('button', label='See the schedule',
               link={'kind': 'builtin', 'value': 'calendar'}, style='outline'),
        ], size='lg', align='left', overlay=overlay, layout='split',
           image={'url': hero_img, 'focal': focal,
                  'alt': 'ECS Pub League players celebrating on the pitch in Seattle'}),

        # 2 · WHO WE ARE — the claim, then the three value propositions as a
        #     rule-separated list. The heading rides in the head slot rather
        #     than standing as its own centred section (design.md § 6.4).
        _s('content', [
            _b('heading', level=2, prominence='lead',
               html=_block('home_intro', 'title', _D['intro_title'])),
            _b('richtext', html=_block('home_intro', 'body_html', _D['intro_body'])),
            _b('steps', style='plain',
               items=[{'title': t, 'html': h} for t, h in _VALUE_CARDS]),
        ], width='normal', align='left', padding='lg'),

        # 3 · THE LIVE BAND — on the ink ground, the page's one dark anchor.
        #     Teams, players and the next PLOP, read from the portal at render
        #     time. Nothing else on this page proves a league is actually
        #     running; without it the home page could belong to anyone.
        _s('content', [
            _b('facts', show_counts=True, show_plop=True),
        ], theme='dark', width='wide', align='left', padding='lg'),

        # 4 · DIVISIONS — head slot + a two-up diptych of LEAD cards.
        #     Each division owns its own live CTA INSIDE the block. They used to
        #     be a card with a loose `cta_live` sibling floating underneath it,
        #     which is design.md DO-NOT 18 (a page-level CTA parked in a grid
        #     cell) and, combined with the old centred column alignment, is what
        #     made Classic and Premier fail to line up with each other.
        #     No `align` here: plain grid stretch tops the photos out together
        #     and drops both buttons onto one baseline.
        _s('columns', [
            _head(_b('heading', level=2, prominence='lead',
                     html='Two divisions, one community')),
            _head(_b('richtext', html='<p>Start where you’re comfortable. Players '
                                      'move between them season to season, and '
                                      'plenty do.</p>')),
            _b('card', col=0, prominence='lead', cta_kind='division_classic',
               badge='Classic', badge_sub='Start here', badge_tone='brand',
               image={'url': classic_img,
                      'alt': 'ECS Pub League Classic division team'},
               title=_block('home_division_classic', 'title', _D['classic_title']),
               html=_block('home_division_classic', 'body_html', _D['classic_body'])),
            _b('card', col=1, prominence='lead', cta_kind='division_premier',
               badge='Premier', badge_sub='Step up', badge_tone='action',
               image={'url': premier_img,
                      'alt': 'ECS Pub League Premier division team'},
               title=_block('home_division_premier', 'title', _D['premier_title']),
               html=_block('home_division_premier', 'body_html', _D['premier_body'])),
        ], theme='light', layout='50-50', padding='lg'),

        # 5 · JUST FOR FUN — the reassurance diptych.
        _s('columns', [
            _b('image', col=0,
               image={'url': jff_img,
                      'alt': 'ECS Pub League players celebrating after a match'},
               size='full', aspect='4:3'),
            _b('heading', col=1, level=2, html='Just for fun. Genuinely.'),
            _b('richtext', col=1,
               html=_block('home_justforfun', 'body_html', _D['justforfun_body'])),
        ], layout='50-50', align='center', padding='md'),

        # 6 · HOW TO JOIN — a real numbered step ladder (design.md § 6.2), not
        #     a second icon three-up and no longer an <ol> buried in a richtext
        #     block: `steps` sets the ordinals in the condensed display cut and
        #     rules the rows apart. The FAQ link is its OWN full-width row
        #     rather than parked in a grid cell (§ 6.3).
        _s('content', [
            _b('heading', level=2, prominence='lead', html='Turn up once.'),
            _b('richtext', html='<p>New players are always welcome. This is the '
                                'whole path in.</p>'),
            _b('steps', style='numbered',
               items=[{'title': t, 'html': f'<p>{body}</p>'} for t, body in _JOIN_STEPS]),
            _b('button', label='Read the full FAQ',
               link={'kind': 'builtin', 'value': 'faqs'}, style='outline'),
        # On the green ground, per the approved layout. The join sequence is the
        # page's one instructional beat and it earns the colour block; the paper
        # sections either side give it somewhere to land.
        ], theme='brand', width='normal', align='left', padding='lg'),

        # 7 · LATEST NEWS (dynamic)
        _s('content', [
            _b('heading', level=2, html='Latest news'),
            _b('news_latest', count=3),
        ], theme='light', width='wide', align='left', padding='md'),

        # 8 · CLOSING BAND — the top of the CTA escalation (§ 10): the label
        #     rises, the destination does not change.
        _s('band', [
            _b('heading', level=2, html='Come as you are.'),
            _b('richtext', html='<p>Get on the list and we’ll reach out as soon as a '
                                'place opens. Or turn up to a PLOP this Sunday and see '
                                'for yourself first.</p>'),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
        # INK, not green. Green is spent once per page and the join sequence
        # earns it; the closing argument lands harder on the dark ground, with
        # the green marquee immediately beneath it in the shell. This is what
        # the approved layout does, and what test_home_spends_brand_green_once
        # holds the page to.
        ], theme='dark', align='center', padding='lg'),
    ]
    return {'v': 1, 'sections': sections}


def build_richtext_doc(page):
    """about/guide/guests + custom rich-text pages: per-page hero + prose.

    Prose-only, so the reading column is `narrow` (design.md § 2.6 — `normal`
    would leave a dead gutter beside a 65ch measure), and the page ends on a
    real action instead of running out of words."""
    hero = page.hero or {}
    hero_settings = {
        'size': hero.get('size', 'sm'),
        'align': hero.get('align', 'left'),
        'overlay': hero.get('overlay', 'medium'),
    }
    if hero.get('image'):
        hero_settings['image'] = {'url': hero['image']}
    if hero.get('bg_color'):
        hero_settings['bg_color'] = hero['bg_color']

    hero_blocks = [_b('heading', level=1,
                      html=_esc(page.title or page.slug.replace('-', ' ').title()))]
    # A scope signal in the hero beats an unbounded wall of text (§ 10). The
    # page's own summary is the only honest source for one.
    lede = (getattr(page, 'meta_description', None) or getattr(page, 'excerpt', None) or '')
    if lede.strip():
        hero_blocks.append(_b('richtext', html=f'<p>{_esc(lede)}</p>'))

    sections = [
        _s('hero', hero_blocks, **hero_settings),
        _s('content', [_b('richtext', html=page.body_html or '')],
           width='narrow', align='left', padding='lg'),
        _s('band', [
            _b('heading', level=2, html='Come play with us.'),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
        ], theme='brand', align='center', padding='md'),
    ]
    return {'v': 1, 'sections': sections}


_GUIDE_CONTENT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                   'seeds', 'guide_content.json')


_BULLET_P_RE = re.compile(r'<p>(.*?)</p>', re.S)


def _bulletise(html):
    """Turn the guide's run-on asterisk paragraphs into real lists.

    The guide was imported from a Google Doc whose bullets came across as a
    literal ' * ' separator inside one <p>. 32 paragraphs are affected and the
    document contains ZERO <ul> elements, so the longest page on the site
    renders its equipment list, its Discord instructions and its rules as
    single unbroken blocks of prose with asterisks in them. It reads like a
    broken import because it is one.

    Done at LOAD time rather than by hand-editing the seed so that a future
    re-import of the same doc gets the same treatment instead of silently
    regressing.

    Conservative on purpose — a paragraph converts only if it opens with a
    bullet marker or carries at least two of them, so an asterisk used in
    ordinary prose is left alone.
    """
    def repl(m):
        inner = m.group(1).strip()
        marks = inner.count(' * ')
        if not (inner.startswith('* ') or marks >= 2):
            return m.group(0)
        lead = ''
        if not inner.startswith('* '):
            head, _, rest = inner.partition(' * ')
            lead, inner = f'<p>{head.strip()}</p>', '* ' + rest
        items = [i.strip() for i in inner[2:].split(' * ')]
        items = [i for i in items if i]
        if len(items) < 2:
            # A one-item "list" is a paragraph that kept its bullet marker. Drop
            # the marker rather than leaving a stray asterisk in the copy, and
            # do not wrap a single <li> in a <ul> — a one-item list is a tell.
            return f'{lead}<p>{items[0]}</p>' if items else m.group(0)
        lis = ''.join(f'<li>{i}</li>' for i in items)
        return f'{lead}<ul>{lis}</ul>'
    return _BULLET_P_RE.sub(repl, html or '')


def _load_guide_chapters():
    try:
        import json
        with open(_GUIDE_CONTENT_FILE, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        for c in data:
            if isinstance(c, dict) and c.get('html'):
                c['html'] = _bulletise(c['html'])
        return data
    except Exception:
        return []


def build_about_doc(page=None):
    """About — macrostructure 15 · Split Studio (design.md § 12).

    Alternating image/text diptychs, one stats row of real figures, and the
    four-clause "come out anyway" run promoted out of a paragraph into a
    full-width quote — the page's single Marquee moment and its whole emotional
    payload. Same content as the seeded body_html, just arranged; this only
    seeds the initial structure, so later edits win."""
    def img(fn, alt):
        return {'url': f'/static/img/publeague/{fn}', 'alt': alt}

    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='Everybody plays.'),
            _b('richtext', html=(
                '<p>Founded in 2012, ECS Pub League is a non-profit, radically inclusive, '
                'beginner-friendly recreational soccer league in Seattle. We play 8 '
                'players a side (including goalkeepers) on a half-size turf field, with '
                'unlimited substitutions in and out — most shifts last 5 to 10 minutes.</p>')),
        ], theme='dark', size='lg', align='left', overlay='medium',
           image=img('2024-07__449510587_474189858536818_1170912284728314372_n-1024x683.jpg',
                     'ECS Pub League players during a Sunday match')),

        # The facts a nervous beginner is actually scanning for. Every figure
        # here is stated in the copy below — nothing is derived or invented.
        _s('content', [
            _b('stats', items=[
                {'value': '2012', 'label': 'Playing in Seattle since'},
                {'value': '8 a side', 'label': 'Half-size turf, unlimited subs'},
                {'value': '10 weeks', 'label': 'Every Spring and Fall season'},
                {'value': '5–10 min', 'label': 'A typical shift before you sub off'},
            ]),
        ], width='normal', align='left', padding='sm'),

        _s('columns', [
            _b('image', col=0, image=img('2026-07__ZUZU-TEAM-1024x683.jpg',
                                         'A Classic division team before kick-off'),
               size='full', aspect='4:3'),
            _b('heading', col=1, level=2, html='Classic Division'),
            _b('richtext', col=1, html=(
                '<p>The Classic division is meant for players with little to no experience. '
                'It also has plenty of beginner-friendly players who want a more relaxed '
                'environment, many getting back into the game after a little (or a lot) of '
                'time away. Classic plays early Sunday afternoons, right after Premier.</p>')),
        ], layout='50-50', align='center', padding='lg'),

        # The line the whole page exists to say, at display scale.
        _s('content', [
            _b('quote', html=(
                '<p>Haven’t played in years? Come on out anyway. Think you’re too out of '
                'shape? Come on out anyway. Think you’re not good enough? Come on out '
                'anyway. Never played soccer at all? Come on out anyway.</p>'),
               attribution=''),
        ], theme='light', width='normal', align='left', padding='lg'),

        _s('columns', [
            _b('heading', col=0, level=2, html='Premier Division'),
            _b('richtext', col=0, html=(
                '<p>The Premier division is a slightly higher level of competition, but it '
                'is still low/no contact and pretty laid-back compared to most leagues. If '
                'you’ve played in GSSL, RATS, or Arena, this probably isn’t the league for '
                'you. There’s a healthy environment of friendly competition, but we still '
                'focus on development, team play, and fun. Premier plays Sunday mornings, '
                'right before Classic.</p>')),
            _b('image', col=1, image=img('2026-07__Astral_Shield-1024x576.jpg',
                                         'A Premier division team before kick-off'),
               size='full', aspect='16:9'),
        ], layout='50-50', align='center', padding='lg'),

        _s('content', [
            _b('heading', level=2, prominence='lead', html='Balanced teams, equal time'),
            _b('richtext', html=(
                '<p>We hold “tryouts” in both divisions only to make sure we can build '
                'evenly balanced teams. Everyone gets equal playing time, regardless of '
                'ability or fitness, and every team makes the playoffs for a shot at the '
                'Pub League Cup. Unlimited subs and short shifts make it a great place to '
                'learn the game or get back into it later in life.</p>'
                '<p>Both divisions play a ten-week season every Spring (usually April '
                'through June) and Fall (roughly between Labor Day and Thanksgiving). Games '
                'are scheduled so as not to conflict with Sounders home matches or popular '
                'away trips.</p>'
                '<p>We form new teams in both divisions every season to keep it fun and '
                'competitive for everyone — and to build new friendships. Each season, '
                'teams decide their theme and name and design their own custom jerseys. '
                'There’s an end-of-season party for everyone at a sponsor pub where we '
                'celebrate individual and team successes.</p>')),
        ], width='normal', align='left', padding='lg'),

        # Was a headingless two-photo `columns` dump; now one captioned gallery
        # attached to the idea it illustrates (design.md § 12 · About).
        _s('content', [
            _b('heading', level=2, html='Fun Week and the Pub League Cup'),
            _b('richtext', html=(
                '<p>Week 9 is Fun Week. Players wear costumes, there’s a potluck BBQ, and '
                'new rules may be instituted at any time — including the ever-popular '
                '“multiball.”</p>')),
            _b('gallery', layout='grid-2', crop=True, items=[
                {'image': img('2025-11__Ball-Lobbers-F25-Cup-1024x768.jpeg',
                              'The Ball Lobbers at the Fall 2025 Pub League Cup'),
                 'caption': 'Ball Lobbers — Fall 2025 Pub League Cup'},
                {'image': img('2025-11__Wasteland-Wanders-F25-Cup-1024x768.jpeg',
                              'The Wasteland Wanders at the Fall 2025 Pub League Cup'),
                 'caption': 'Wasteland Wanders — Fall 2025 Pub League Cup'},
            ]),
        ], width='wide', align='left', padding='lg'),

        _s('columns', [
            _b('image', col=0, image=img('2024-03__PLOP-1024x536.png',
                                         'An open PLOP kickabout on a Sunday'),
               size='full', aspect='16:9'),
            _b('heading', col=1, level=2, html='Come to a PLOP first'),
            _b('richtext', col=1, html=(
                f'<p>PLOP is a {_PLOP} — an open, informal kickabout we run most Sundays '
                'through the summer and winter offseasons. It is the easiest way to check '
                'us out, and it gives us a chance to find the right place for you to play. '
                'Every player new to the league attends a PLOP and is approved before '
                'registering.</p>')),
        ], layout='50-50', align='center', padding='lg'),

        _s('content', [
            _b('heading', level=2, prominence='lead', html='Why we exist'),
            _b('richtext', html=(
                '<h3>Our mission</h3>'
                '<p>Fun and friendly soccer for adults. We’re radically inclusive, but '
                'we’re not for everyone. ECS Pub League is made up of soccer fans of '
                'beginner/newcomer/low-intermediate levels who get together to play in a '
                'fun, safe, and organized environment for the love of the game and a '
                'little friendly competition.</p>'
                '<h3>Our vision</h3>'
                '<p>Originally founded as the ECS FC Academy, the ECSPL is an excellent way '
                'for our fellow supporters, their friends, and family to play in an '
                'organized league and have fun in the process. All matches are played '
                'using modified FIFA outdoor rules (no going to the ground, no challenges '
                'from behind or blind spots, etc.).</p>'
                '<p>ECS Pub League is part of ECS FC, the nonprofit soccer club '
                'established by Emerald City Supporters, a Sounders FC supporters group.</p>')),
        ], width='normal', align='left', padding='lg'),

        _s('band', [
            _b('heading', level=2, html='Come out anyway.'),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
        ], theme='brand', align='center', padding='lg'),
    ]}


def build_guests_doc():
    """Guests — macrostructure 06 · Conversational FAQ (design.md § 12).

    The page already IS four questions; it was just trapped inside one richtext
    <div> with no heading structure and — on a page whose entire message is
    "just reach out" — no focusable element anywhere in <main>. Each question
    becomes its own section, the TL;DR sits on the inset surface, and the page
    ends on a real action."""
    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='Bringing a friend to PLOP'),
            _b('richtext', html=(
                '<p>We love that folks want to bring friends and family out to kick the '
                'ball around with us — it’s part of what makes our community great. Here’s '
                f'where we stand on non-league players, including minors, joining a {_PLOP} '
                '(PLOP).</p>')),
        ], size='sm', align='left', overlay='medium'),

        # The TL;DR on the quiet inset surface.
        _s('content', _callout_blocks('key-facts', 'The short version', (
            '<ul>'
            '<li>PLOPs are for league players first.</li>'
            '<li>Potential league-appropriate players actively considering the league '
            '— especially adult beginners — are always welcome.</li>'
            '<li>Minors are generally discouraged from playing.</li>'
            '<li>If you’re not sure, ask first.</li>'
            '</ul>')),
           theme='light', width='narrow', align='left', padding='md'),

        _s('content', [
            _b('heading', level=2, html='Why we’re cautious'),
            _b('richtext', html=(
                '<ul>'
                '<li>Safety is our first priority, and mixing minors and/or more '
                'experienced players with Pub League players isn’t always a great fit.</li>'
                '<li>We’ve got limited space, gear, and time, and we want to make sure '
                'current league players can maximize playing time.</li>'
                '<li>Players of any age who are above our level and/or pace of play can '
                'throw off the chill and inclusive vibe unique to our league.</li>'
                '</ul>')),
        ], width='narrow', align='left', padding='md'),

        _s('content', [
            _b('heading', level=2, html='But exceptions?'),
            _b('richtext', html=(
                '<p>Yeah, they’ve happened — and sometimes they’ve worked out just fine. '
                'We’re more inclined to grant exceptions where exceptional circumstances '
                'are involved, but we’d rather talk it through first, not after.</p>')),
        ], width='narrow', align='left', padding='md'),

        _s('content', [
            _b('heading', level=2, prominence='lead', html='So what should I do?'),
            _b('richtext', html=(
                '<p>If you’re thinking of bringing someone who isn’t already in the league '
                '— especially if they’re under 21 — just reach out. We’re not trying to be '
                'gatekeepers, but we do want to make sure everyone has a good (and safe) '
                'time, and that league players get a good experience.</p>')),
        ], width='narrow', align='left', padding='md'),

        _s('band', [
            _b('heading', level=2, html='Ask us first — we’re friendly.'),
            _b('button', label='Ask us', link={'kind': 'builtin', 'value': 'contact'},
               style='primary', align='center'),
        ], theme='brand', align='center', padding='lg'),
    ]}


def build_guide_doc():
    """Guide — macrostructure 02 · Long Document (design.md § 12).

    A `size='sm'` hero carrying a real scope signal (chapter count, reading
    time, a jump to the lexicon — all derived from the loaded seed, none of it
    invented), a contents landmark, then one section per chapter with slug ids
    on every h3/h4 so the subsection deep links resolve. Falls back to a
    link-out placeholder if the content file is missing."""
    chapters = _load_guide_chapters()
    doc_url = ('https://docs.google.com/document/d/'
               '1ubX6prasXWGot6l_PpmYZOfYJMcHzAr3bG8X9vehjjM/edit?usp=sharing')
    if not chapters:
        return {'v': 1, 'sections': [
            _s('hero', [_b('heading', level=1, html='The Pub League Guide')],
               size='sm', align='left'),
            _s('content', [_b('richtext', html=(
                '<p>Our unofficial guide for new players and people new to soccer. '
                f'<a href="{doc_url}" target="_blank" rel="noopener">Read or '
                'download the full guide &rarr;</a></p>'))],
               width='narrow', align='left', padding='lg'),
        ]}

    # Scope signal, computed from the seed itself (design.md § 10 — an
    # unbounded wall of text with no scope signal is a bounce).
    words = sum(len(_TAG_RE.sub(' ', c.get('html', '')).split()) for c in chapters)
    minutes = max(5, int(round(words / 200.0 / 5.0)) * 5)
    lexicon = next((c for c in chapters if c.get('slug', '').startswith('lexicon')), None)
    scope = (f'<p>{len(chapters)} chapters, about a {minutes}-minute read — written by '
             'players and coaches for people new to the league, and to soccer.')
    if lexicon:
        scope += (f' Only after the on-field shouting? <a href="#{lexicon["slug"]}">'
                  'Jump to the lexicon</a>.')
    scope += '</p>'

    # ⚠️ NO <nav> WRAPPER. The richtext sanitizer strips it — verified — so the
    # landmark never reached the page, and the JS that keyed on
    # nav[aria-label="Guide contents"] to hide this card silently matched
    # nothing for as long as it existed. The guide has been shipping two
    # contents lists. The card is now gated by the section's own hide_at='xl'
    # and the heading below is a real <h2>, which the sanitizer does keep.
    toc = '<h2>What’s inside</h2><ul>'
    for c in chapters:
        toc += f'<li><a href="#{c.get("slug", "")}">{c.get("title", "")}</a></li>'
    toc += '</ul>'

    def img(fn, alt):
        return {'url': f'/static/img/publeague/{fn}', 'alt': alt}
    # Photos interleaved between chapter groups to break up the long read.
    # Real alt text, not alt="" — a photograph of people is content. Better
    # per-photo alt/captions are a media-library task (design.md § 14).
    breaks = [('2025-01__354555603_261773156445157_1463948238121785202_n-edited-1.jpg',
               'ECS Pub League players during a Sunday match'),
              ('2024-07__449616069_475069395115531_7943264348607003846_n-1024x576.jpg',
               'ECS Pub League players lining up before kick-off')]

    sections = [
        _s('hero', [
            _b('heading', level=1, html='The Pub League Guide'),
            _b('richtext', html=scope),
        ], theme='dark', size='sm', align='left', overlay='medium',
           image=img('2024-07__449510587_474189858536818_1170912284728314372_n-1024x683.jpg',
                     'ECS Pub League players during a Sunday match')),
        _s('content', [
            _b('richtext', html=(
                '<p class="lead">This unofficial guide was created by players and coaches '
                'to help people of all ages and experience levels who are new to ECS Pub '
                'League — especially those new to soccer, learning the game in the Classic '
                'division. Always defer to your coach; this is a friendly companion, not '
                'official rules.</p>'
                f'<p><a href="{doc_url}" target="_blank" rel="noopener">Read or download '
                'the original on Google Docs &rarr;</a></p>')),
        ], width='narrow', align='left', padding='md'),
        # 'What's inside' contents, set apart on the quiet inset surface.
        # hide_at='xl' — above 1280px the fixed gutter rail
        # (public/_guide_chrome.html) is the contents and this card would be the
        # same list twice on one screen. Below it there is no gutter, so this IS
        # the contents. Gating it in the section rather than in JS is what keeps
        # the page from reflowing after paint.
        _s('content', [_b('richtext', html=toc)],
           theme='light', width='narrow', align='left', padding='md',
           hide_at='xl'),
    ]
    seen_ids = {c.get('slug', '') for c in chapters}
    for i, c in enumerate(chapters):
        # Each chapter is its OWN section (padding + anchor) — not one endless
        # block — and every h3/h4 inside it gets a stable slug id.
        body = _add_heading_ids(c.get('html', ''), seen_ids)
        sections.append(_s('content', [
            _b('richtext', html=f'<h2 id="{c.get("slug", "")}">{c.get("title", "")}</h2>\n{body}'),
        ], width='normal', align='left', padding='md'))
        if (i + 1) % 3 == 0 and i < len(chapters) - 1:
            fn, alt = breaks[(i // 3) % len(breaks)]
            sections.append(_s('content', [
                _b('image', image=img(fn, alt), size='full', aspect='16:9'),
            ], width='normal', align='left', padding='sm'))
    sections.append(_s('band', [
        _b('heading', level=2, html='Now go play.'),
        _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
    ], theme='brand', align='center', padding='lg'))
    return {'v': 1, 'sections': sections}


def build_placeholder_doc(title):
    """Minimal graceful-degradation doc for a fixed page whose content row is
    missing (deploy window before seeding, or a trashed page) — renders a
    hero + 'being updated' note instead of 404ing, matching the pre-builder
    template's fallback. Even this one ends on an action, and routes through a
    typed builtin link rather than a hardcoded href that can drift."""
    return {'v': 1, 'sections': [
        _s('hero', [_b('heading', level=1, html=_esc(title) or 'This page')],
           size='sm', align='left'),
        _s('content', [_b('richtext',
            html='<p>This page is being updated. If you were looking for '
                 'something in particular, ask us — we’ll point you the right '
                 'way.</p>')], width='narrow', align='left', padding='md'),
        _s('band', [
            _b('heading', level=2, html='Ask us anything.'),
            _b('button', label='Contact us',
               link={'kind': 'builtin', 'value': 'contact'},
               style='primary', align='center'),
        ], theme='brand', align='center', padding='md'),
    ]}


def build_builder_page_doc(page):
    """GrapesJS '<style' pages: best-effort — sanitized markup in an admin-only
    embed_raw block (layout CSS is intentionally dropped; needs manual review)."""
    sections = [
        _s('hero', [_b('heading', level=1, html=_esc(page.title or page.slug))],
           size='sm', align='left'),
        _s('content', [_b('embed_raw', html=page.body_html or '')],
           width='wide', align='left', padding='lg'),
    ]
    return {'v': 1, 'sections': sections}


# --------------------------------------------------------------------------- #
# "Add New Page" starter templates
# --------------------------------------------------------------------------- #
# Squarespace-style page templates for the Add New Page picker: each seeds a
# whole designed skeleton (sections + placeholder copy) so a non-technical
# volunteer edits obvious placeholders inside a finished layout instead of
# assembling a page from a blank canvas. Every skeleton is built from the SAME
# section/block vocabulary as everything else and is run through
# validate_sections at create time — a template can never produce an
# off-design page. Keep keys stable; the picker's wireframe previews in
# page_new_flowbite.html are matched by key.
#
# Each template is one of design.md § 12's macrostructures, so a volunteer
# lands on something that already reads as this site and not as a blank CMS:
#   info     -> 02 Long Document      landing -> 03 Marquee Hero
#   program  -> 14 Narrative Workflow gallery -> 20 Ecosystem Index
#   contact  -> 12 Letter             blank   -> nothing
# CHANGING A TEMPLATE'S SHAPE MEANS CHANGING ITS WIREFRAME PREVIEW IN
# page_new_flowbite.html. Update both together or the picker starts lying.
#
# Two rules every template obeys:
#   * it ends on a real action (a page with no focusable element in <main> is
#     a dead end — design.md § 12 · Guests), and
#   * a heading that labels a grid rides in that grid's head slot, never in a
#     centred section of its own (§ 6.4).

PAGE_TEMPLATES = [
    {'key': 'info', 'label': 'Simple info page',
     'desc': 'A banner, a short lede and readable prose — for rules, policies and how-tos.'},
    {'key': 'landing', 'label': 'Landing page',
     'desc': 'Big banner with the ask, three highlights, a photo story, and a closing call to action.'},
    {'key': 'program', 'label': 'Program or event',
     'desc': 'What it is, the practical details, upcoming dates, and a way to ask a question.'},
    {'key': 'gallery', 'label': 'Photo gallery',
     'desc': 'A short intro and a captioned grid of match-day and event photos.'},
    {'key': 'contact', 'label': 'Get in touch',
     'desc': 'A short note in your own voice, the form underneath, and other ways to reach you.'},
    {'key': 'blank', 'label': 'Blank page',
     'desc': 'Start from nothing and add sections yourself.'},
]


def build_page_template(key, title):
    """Sections for one Add-New-Page template. `title` is user input — it is
    escaped here because heading blocks carry HTML."""
    t = _esc(title) or 'New page'

    if key == 'info':
        # 02 · Long Document — a reading page. Prose caps at `narrow` so the
        # measure is right (design.md § 2.6), and it still ends on an action.
        return [
            _s('hero', [
                _b('heading', level=1, html=t),
                _b('richtext', html='<p>One sentence saying what this page covers '
                                    'and who it is for.</p>'),
            ], size='sm', align='left'),
            _s('content', [
                _b('heading', level=2, prominence='lead', html='What you need to know'),
                # Placeholder copy must read sanely if published untouched —
                # never reference the editor UI (buttons, clicking, placeholders).
                _b('richtext', html='<p>Write the main explanation here. A few short '
                                    'paragraphs read better than one long one.</p>'),
            ], width='narrow', align='left', padding='lg'),
            _s('content', [
                _b('heading', level=2, html='The details'),
                _b('richtext', html='<p>Use this second section for the specifics — '
                                    'dates, costs, exceptions, anything people ask '
                                    'about twice.</p>'),
            ], width='narrow', align='left', padding='lg'),
            _s('band', [
                _b('heading', level=2, html='Still have a question?'),
                _b('button', label='Ask us',
                   link={'kind': 'builtin', 'value': 'contact'},
                   style='primary', align='center'),
            ], theme='brand', align='center', padding='md'),
        ]

    if key == 'landing':
        # 03 · Marquee Hero — the hero is the page above the fold, and the ask
        # sits in it. Section headings ride in the head slot of the grid they
        # label (§ 6.4) rather than in centred sections of their own.
        return [
            _s('hero', [
                _b('heading', level=1, html=t),
                _b('richtext', html='<p>One sentence on why this matters to the '
                                    'person reading it.</p>'),
                _b('cta_live', kind='waitlist_or_register', style='primary'),
            ], theme='dark', size='lg', align='left', overlay='medium'),
            _s('columns', [
                _head(_b('heading', level=2, prominence='lead', html='Why come along')),
                _head(_b('richtext', html='<p>A line of context under the heading, '
                                          'if it needs one.</p>')),
                # Card copy is tag-free plain text: it is edited through the
                # card's Text field (a plain textarea), not inline TinyMCE.
                _b('card', col=0, icon='star', title='First highlight',
                   html='A short selling point.'),
                _b('card', col=1, icon='users-group', title='Second highlight',
                   html='Another short selling point.'),
                _b('card', col=2, icon='calendar', title='Third highlight',
                   html='One more short selling point.'),
            ], layout='3col', padding='lg'),
            _s('columns', [
                _b('image', col=0, image={}, size='full', aspect='4:3'),
                _b('heading', col=1, level=2, html='Tell the story'),
                _b('richtext', col=1, html='<p>Pair a photo with a couple of '
                                           'paragraphs that tell the story.</p>'),
            ], layout='50-50', align='center', padding='lg'),
            _s('band', [
                _b('heading', level=2, html='Come along.'),
                _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
            ], theme='brand', align='center', padding='lg'),
        ]

    if key == 'gallery':
        # 20 · Ecosystem Index — the grid IS the page, so the intro rides in
        # the hero instead of taking a section of its own, and the heading sits
        # in the same section as the photos it labels.
        return [
            _s('hero', [
                _b('heading', level=1, html=t),
                _b('richtext', html='<p>A sentence or two about these photos — who '
                                    'is in them and when they were taken.</p>'),
            ], size='sm', align='left'),
            _s('content', [
                _b('heading', level=2, prominence='lead', html='The photos'),
                _b('gallery', layout='grid-3', crop=True, items=[]),
            ], width='wide', align='left', padding='lg'),
            _s('band', [
                _b('heading', level=2, html='Want to be in the next one?'),
                _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
            ], theme='brand', align='center', padding='md'),
        ]

    if key == 'program':
        # 14 · Narrative Workflow — what it is, then the practical facts, then
        # the dates, then the ask. Key/value facts are a <dl>, not a two-column
        # table (design.md § 7.6).
        return [
            _s('hero', [
                _b('heading', level=1, html=t),
                _b('richtext', html='<p>One line on what this is and who it is for.</p>'),
            ], size='md', align='left'),
            _s('columns', [
                _head(_b('heading', level=2, prominence='lead', html='What it is')),
                _b('image', col=0, image={}, size='full', aspect='4:3'),
                _b('richtext', col=1, html='<p>Describe the program or event — who '
                                           'it is for, what happens, and what to '
                                           'expect if it is someone’s first time.</p>'),
            ], layout='50-50', align='center', padding='lg'),
            _s('content', [
                _b('heading', level=2, html='The details'),
                _b('richtext', html='<dl>'
                                    '<dt>When</dt><dd>Add the day and time.</dd>'
                                    '<dt>Where</dt><dd>Add the location.</dd>'
                                    '<dt>Cost</dt><dd>Add the cost, or say it’s free.</dd>'
                                    '<dt>Who it’s for</dt><dd>Add who should come along.</dd>'
                                    '</dl>'),
            ], width='narrow', align='left', padding='lg'),
            _s('content', [
                _b('heading', level=2, html='Upcoming dates'),
                _b('calendar_teaser', count=4),
            ], theme='light', width='narrow', align='left', padding='lg'),
            _s('band', [
                _b('heading', level=2, html='Questions before you come?'),
                _b('button', label='Ask us',
                   link={'kind': 'builtin', 'value': 'contact'},
                   style='primary', align='center'),
            ], theme='brand', align='center', padding='md'),
        ]

    if key == 'contact':
        # 12 · Letter — a short note in the site's own voice, then the form as
        # the page's single object, then the other routes demoted to a
        # colophon-weight footnote (design.md § 12 · Contact).
        return [
            _s('hero', [
                _b('heading', level=1, html=t),
                _b('richtext', html='<p>Say who reads these messages and what you '
                                    'can help with. A real name goes a long way.</p>'),
            ], size='sm', align='left'),
            _s('content', [
                _b('form', form='contact'),
            ], width='narrow', align='left', padding='lg'),
            _s('content', [
                _b('heading', level=4, html='Other ways to reach us'),
                _b('richtext', html='<p>Add an email address, or point people at the '
                                    'community Discord.</p>'),
            ], width='narrow', align='left', padding='sm'),
            _s('band', [
                _b('heading', level=2, html='Or just come and play.'),
                _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
            ], theme='brand', align='center', padding='md'),
        ]

    return []   # 'blank' and anything unknown


def build_register_doc():
    """Register — macrostructure 14 · Narrative Workflow (design.md § 12).

    The ask lands AFTER the prerequisite: the live registration state first
    (it is the loudest live element on this page, not the quietest), then the
    three steps as a numbered ladder, then the division choice, then the CTA.
    The closing band repeats the LIVE CTA instead of routing to two other
    pages."""
    return {'v': 1, 'sections': [
        # A PHOTOLESS HERO SITS ON THE INK GROUND, NOT ON BRAND GREEN.
        # Flat ecs-green-ink used to be the ground of every image-less hero AND
        # the scrim over every photographic one AND every closing band, so the
        # same green rectangle appeared four or five times on every page and the
        # brand colour stopped meaning anything. Green is now spent once per
        # page, on the closing band; the ink ground carries the openings.
        _s('hero', [
            _b('heading', level=1, html='Join the league'),
            _b('richtext', html='<p>New players are always welcome — including people '
                                'who have never played. Here’s exactly how to get on '
                                'the pitch.</p>'),
        ], theme='dark', size='md', align='left'),

        # 1 · Where the season actually stands, before anything is asked of you.
        _s('content', [
            _b('registration_status'),
            _b('richtext', html='<p>Registration opens twice a year, for the Spring and '
                                'Fall seasons. When a season is full, the waitlist is '
                                'the way in — and it moves.</p>'),
        # Every section on this page shares `normal`, so the page has ONE left
        # edge. Mixing widths made the status block, the ladder and the division
        # choice each start at a different x, which reads as three unrelated
        # pages stacked rather than one argument.
        ], width='normal', align='left', padding='md'),

        # 2 · The prerequisite, as a real numbered ladder rather than a card
        #     three-up or an <ol> buried inside a richtext block.
        _s('content', [
            _b('heading', level=2, prominence='lead', html='Three steps and you’re in.'),
            _b('steps', style='numbered',
               items=[{'title': t, 'html': f'<p>{body}</p>'} for t, body in _JOIN_STEPS]),
        ], width='normal', align='left', padding='lg'),

        # 3 · The choice.
        _s('content', [
            _b('heading', level=2, html='Which division?'),
            _b('richtext', html='<p>Not sure which one fits? Start with Classic — it is '
                                'built for people with little or no experience, and you '
                                'can always move later.</p>'),
            _b('cta_live', kind='division_classic', style='secondary', align='left'),
            _b('cta_live', kind='division_premier', style='secondary', align='left'),
        ], theme='light', width='normal', align='left', padding='lg'),

        # 4 · The ask, last.
        _s('band', [
            _b('heading', level=2, html='Come play with us.'),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
        ], theme='brand', align='center', padding='lg'),
    ]}


def build_contact_doc():
    """Contact — macrostructure 12 · Letter (design.md § 12).

    A short lede in the site's own voice, the form as the page's single object,
    "other ways to reach us" demoted to a colophon-weight footnote, and a
    closing band back to the waitlist."""
    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='Talk to us'),
            _b('richtext', html='<p>Questions about joining, about PLOP, or about how a '
                                'season works? Ask away — a real human reads every '
                                'message, and no question is too basic.</p>'),
        ], size='sm', align='left'),
        _s('content', [
            _b('form', form='contact'),
        ], width='narrow', align='left', padding='lg'),
        _s('content', [
            _b('heading', level=4, html='Other ways to reach us'),
            _b('richtext', html='<p>Email <a href="mailto:ecspubleague@gmail.com">'
                                'ecspubleague@gmail.com</a>, or hop into the community '
                                'Discord and say hi.</p>'),
            _b('social_links', items=[
                {'kind': 'discord', 'url': 'https://discord.gg/weareecs'},
                {'kind': 'email', 'url': 'mailto:ecspubleague@gmail.com'},
            ]),
        ], width='narrow', align='left', padding='sm'),
        _s('band', [
            _b('heading', level=2, html='Or skip the email and come play.'),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
        ], theme='brand', align='center', padding='md'),
    ]}


def build_faqs_doc():
    """FAQs — macrostructure 13 · Index-First (design.md § 12).

    The list IS the page, so the hero stays small and hands straight off to it
    (the category jump-strip is built by block_faq_list from the Faq.category
    column, not seeded here)."""
    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='Questions, answered.'),
            _b('richtext', html='<p>Everything new players usually want to know — how '
                                'good you need to be (you don’t), what a season costs, '
                                'and what happens at your first PLOP.</p>'),
        ], size='sm', align='left'),
        _s('content', [_b('faq_list')], width='narrow', align='left', padding='lg'),
        _s('band', [
            _b('heading', level=2, html='Not on the list? Just ask.'),
            _b('button', label='Ask us', link={'kind': 'builtin', 'value': 'contact'},
               style='primary', align='center'),
            _b('cta_live', kind='waitlist_or_register', style='secondary', align='center'),
        ], theme='brand', align='center', padding='lg'),
    ]}


# --------------------------------------------------------------------------- #
# Conversion driver
# --------------------------------------------------------------------------- #

def _finalize(session, page, raw_doc, label):
    """Validate + store a converted doc as draft AND published (live pages),
    with a revision snapshot so conversion itself is restorable."""
    from app.models import SitePageRevision
    from app.services.section_schema import validate_sections
    doc, notes = validate_sections(raw_doc, is_admin=True)
    if notes:
        logger.info('convert %s: %s', page.slug, '; '.join(notes[:8]))
    now = datetime.utcnow()
    page.sections_draft = doc
    if page.status == 'published' and page.deleted_at is None:
        page.sections_published = doc
        page.published_at = now
    page.draft_rev = (page.draft_rev or 0) + 1
    page.draft_updated_at = now
    session.add(SitePageRevision(page_id=page.id, title=page.title, sections=doc,
                                 kind='publish', label=label, created_at=now))


def _get_or_create(session, slug, title):
    from app.models import SitePage
    page = session.query(SitePage).filter_by(slug=slug).first()
    if not page:
        page = SitePage(slug=slug, title=title, status='published')
        session.add(page)
        session.flush()
    return page


_BLOCK_SLUGS = ('home_hero', 'home_intro', 'home_justforfun',
                'home_division_classic', 'home_division_premier', 'home_body')
_FIXED_PAGES = (('home', 'Home'), ('register', 'How to join'),
                ('contact', 'Contact us'), ('faqs', 'FAQs'))


def build_doc_for_page(session, page):
    """The section doc a page WOULD get from conversion — the same content the
    public renderer falls back to while sections are still NULL. Centralised so
    the editor's /state can seed THIS (never an empty doc): seeding empty over a
    page that still renders fallback content means the first structural edit +
    Publish silently overwrites that live content with nothing. Mirrors the
    per-slug selection convert_all uses to persist."""
    slug = page.slug
    if slug == 'home':
        return build_home_doc(session)
    if slug == 'register':
        return build_register_doc()
    if slug == 'contact':
        return build_contact_doc()
    if slug == 'faqs':
        return build_faqs_doc()
    if slug == 'guide':
        return build_guide_doc()
    if slug == 'about':
        return build_about_doc(page)
    if slug == 'guests':
        return build_guests_doc()
    if page.body_html and '<style' in page.body_html:
        return build_builder_page_doc(page)
    return build_richtext_doc(page)


def convert_all(session):
    """Idempotent total conversion. Returns the number of pages converted."""
    from app.models import SitePage

    converted = 0

    # Fixed pages (home/register/contact/faqs) — created if missing.
    builders = {'home': lambda: build_home_doc(session),
                'register': build_register_doc,
                'contact': build_contact_doc,
                'faqs': build_faqs_doc}
    for slug, title in _FIXED_PAGES:
        page = _get_or_create(session, slug, title)
        if page.sections_draft is None and page.sections_published is None:
            _finalize(session, page, builders[slug](), 'converted')
            converted += 1

    # Every other real page (about/guide/guests + custom), skipping the retired
    # home_* block rows.
    pages = (session.query(SitePage)
             .filter(~SitePage.slug.in_(_BLOCK_SLUGS + tuple(b[0] for b in _FIXED_PAGES)))
             .all())
    for page in pages:
        if page.sections_draft is not None or page.sections_published is not None:
            continue
        if page.slug == 'guide':
            _finalize(session, page, build_guide_doc(), 'converted')
        elif page.slug == 'about':
            _finalize(session, page, build_about_doc(page), 'converted')
        elif page.slug == 'guests':
            _finalize(session, page, build_guests_doc(), 'converted')
        elif page.body_html and '<style' in page.body_html:
            _finalize(session, page, build_builder_page_doc(page), 'converted-needs-review')
            logger.warning('Page %r was GrapesJS-built; converted best-effort — '
                           'REVIEW ITS LAYOUT in the site editor.', page.slug)
        else:
            _finalize(session, page, build_richtext_doc(page), 'converted')
        converted += 1

    return converted


# --------------------------------------------------------------------------- #
# Force rebuild
# --------------------------------------------------------------------------- #

# The nine real pages, in the order a rebuild reports them. `home_*` block rows
# are migration artifacts, not pages, and are never rebuilt.
REBUILDABLE_SLUGS = ('home', 'about', 'guide', 'guests', 'faqs',
                     'register', 'contact')


def rebuild_pages(session, slugs=None, dry_run=False):
    """Re-derive stored section documents from the builders in this module,
    OVERWRITING what is currently published.

    THIS IS THE LEVER `convert_all` DELIBERATELY IS NOT, and the reason the last
    redesign did not reach the site. `convert_all` skips any page that already
    has sections — correct for a boot hook, since it must never clobber an
    admin's edits — but all nine live pages have had sections since the first
    conversion. The consequence was that a whole redesign could land in the
    rendering vocabulary and in these builders, be verified, ship, and change
    nothing at all on the live site, because every page was still rendering the
    section JSON it was converted with. Restyling reached the pages; RESHAPING
    them never could.

    So this exists, it is explicit, and it is never automatic: no boot hook, no
    request path, no scheduled task. Someone types the command.

    Reversible in two ways, on purpose. This writes a `pre-rebuild` revision of
    the page's CURRENT sections before touching anything, and `_finalize` then
    writes its own revision of the new document — so the admin Revisions screen
    shows both the state before and the state after, per page, and either can be
    restored without a database edit.

    Returns a list of (slug, n_sections, n_blocks) for what was (or would be)
    written.
    """
    from app.models import SitePage, SitePageRevision

    wanted = tuple(slugs) if slugs else REBUILDABLE_SLUGS
    unknown = [s for s in wanted if s not in REBUILDABLE_SLUGS]
    if unknown:
        raise ValueError(f'not rebuildable: {", ".join(unknown)} '
                         f'(known: {", ".join(REBUILDABLE_SLUGS)})')

    results = []
    for slug in wanted:
        page = (session.query(SitePage)
                .filter(SitePage.slug == slug, SitePage.deleted_at.is_(None))
                .first())
        if not page:
            logger.warning('rebuild: no page %r — skipped', slug)
            continue

        doc = build_doc_for_page(session, page)
        sections = doc.get('sections', [])
        n_blocks = sum(len(sec.get('blocks') or []) for sec in sections)
        results.append((slug, len(sections), n_blocks))
        if dry_run:
            continue

        # Snapshot what is there NOW, before it is replaced. Skipped when the
        # page has no sections yet: an empty "before" revision is a restore
        # point to a blank page, which is worse than no restore point.
        current = page.sections_published or page.sections_draft
        if current:
            session.add(SitePageRevision(
                page_id=page.id, title=page.title, sections=current,
                kind='publish', label='pre-rebuild',
                created_at=datetime.utcnow()))
        _finalize(session, page, doc, 'rebuild')

    return results


def sanitize_legacy_content(session):
    """One-time nh3 pass over pre-sanitizer news/FAQ HTML (marker-guarded)."""
    from app.models import NewsPost, Faq, SiteSetting
    from app.utils.html_sanitizer import sanitize_html

    if session.query(SiteSetting).get(_SANITIZE_MARKER):
        return 0
    touched = 0
    for post in session.query(NewsPost).all():
        clean = sanitize_html(post.body_html) or None
        if clean != post.body_html:
            post.body_html = clean
            touched += 1
    for faq in session.query(Faq).all():
        clean = sanitize_html(faq.answer_html)
        if clean != faq.answer_html:
            faq.answer_html = clean
            touched += 1
    session.add(SiteSetting(key=_SANITIZE_MARKER,
                            value={'at': datetime.utcnow().isoformat(),
                                   'rows_changed': touched}))
    return touched


def seed_contact_form(session):
    """The ONE forms system's seeded contact definition (idempotent).

    Email is REQUIRED: the form's whole promise is "a real human reads every
    message", and without a reply-to the promise cannot be kept. `help`,
    `placeholder` and `autocomplete` ride along per field (design.md § 7.2 —
    every field reserves a rendered helper slot, so supplying real help text
    costs no layout)."""
    from app.models import FormDefinition
    if session.query(FormDefinition).filter_by(name='contact').first():
        return False
    session.add(FormDefinition(
        name='contact', title='Contact us',
        fields=[
            {'name': 'name', 'label': 'Your name', 'type': 'text', 'required': True,
             'autocomplete': 'name', 'maxlength': 120,
             'help': 'First name is plenty.'},
            {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True,
             'autocomplete': 'email', 'maxlength': 200,
             'help': 'So we can write back. We don’t add you to any list.'},
            {'name': 'subject', 'label': 'Subject', 'type': 'text', 'required': False,
             'autocomplete': 'off', 'maxlength': 160,
             'help': 'Optional — a few words about what this is.'},
            {'name': 'message', 'label': 'Message', 'type': 'textarea', 'required': True,
             'autocomplete': 'off', 'maxlength': 4000,
             'help': 'No question is too basic. Really.'},
        ],
        success_message='Thanks — we got your message and we’ll get back to you soon.',
        mirror_to_feedback=True,
    ))
    return True


def run_conversion(app):
    """Boot hook (called after seeding, same style: never breaks startup).
    Safe pre-SQL: if the new columns/tables don't exist yet, it logs and skips."""
    try:
        with app.app_context():
            from app.core import db
            from sqlalchemy import text
            session = db.session
            # Serialize concurrent gunicorn workers with a Postgres advisory
            # lock. Best-effort: if it's unavailable (non-Postgres backend, or
            # any error) we proceed WITHOUT it — the per-page idempotency guards
            # (skip when sections already exist) make double-conversion a no-op,
            # so the lock is an optimization, not a correctness requirement.
            try:
                session.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                                {"k": 748291036})  # distinct from the seeder's lock
            except Exception:
                session.rollback()
            n_forms = seed_contact_form(session)
            n_pages = convert_all(session)
            n_sanitized = sanitize_legacy_content(session)
            if n_pages or n_sanitized or n_forms:
                session.commit()
                logger.info('Section conversion: %d pages converted, %d legacy rows '
                            'sanitized%s.', n_pages, n_sanitized,
                            ', contact form seeded' if n_forms else '')
            else:
                session.rollback()
    except Exception as e:
        logger.warning('Section conversion skipped (%s: %s) — run the builder SQL '
                       'and restart.', e.__class__.__name__, e)

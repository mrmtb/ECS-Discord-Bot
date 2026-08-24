import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import flowbitePlugin from 'flowbite/plugin';
import formsPlugin from '@tailwindcss/forms';
import { createRequire } from 'module';

// Official Tailwind Typography plugin — the Tailwind-native way to style
// CMS/rich-text content (`prose`). Loaded defensively so a build before the
// package is installed (npm ci) still succeeds; `prose` activates once the
// image is rebuilt with the new dependency.
const _require = createRequire(import.meta.url);
let typographyPlugin = null;
try { typographyPlugin = _require('@tailwindcss/typography'); } catch (e) { typographyPlugin = null; }

// Get directory path for ESM
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    // Use absolute paths to ensure content is found regardless of where Tailwind runs
    resolve(__dirname, 'app/templates/**/*.html'),
    resolve(__dirname, 'app/static/js/**/*.js'),
    // custom_js was NOT scanned, but those modules build DOM with Tailwind classes
    // (modal-builder.js constructs the whole report-match modal client-side). Any
    // class used ONLY there was silently purged out of the stylesheet — no error,
    // just an unstyled element.
    resolve(__dirname, 'app/static/custom_js/**/*.js'),
    // Python that emits Tailwind class strings. public_theme.SECTION_RHYTHM holds
    // the Appearance panel's "Page rhythm" utilities as the SINGLE source of truth
    // (the same dict validates the saved value), so the classes exist only here —
    // and without this glob they are purged exactly like the custom_js case above:
    // the setting saves, the class renders, and nothing changes on the page.
    resolve(__dirname, 'app/services/public_theme.py'),
    resolve(__dirname, 'node_modules/flowbite/**/*.js'),
  ],
  theme: {
    extend: {
      colors: {
        // ECS Brand Colors
        'ecs-green': {
          // Themed to the ECS Pub League LOGO green (#40b050), slightly deepened
          // for readable white text. Overridable via Appearance (--color-primary-rgb).
          DEFAULT: 'rgb(var(--color-primary-rgb, 64 176 80) / <alpha-value>)',
          dark: 'rgb(var(--color-primary-dark-rgb, 46 157 68) / <alpha-value>)',
          // BRAND INK (public site). The DEFAULT green above is a FILL: at
          // 2.78:1 on white it can neither be text nor sit under white text.
          // `ink` is the same hue darkened until it clears 4.6:1 against the
          // DARKEST tinted panel it may sit on (public_theme.INK_TINT_FLOOR),
          // so it is the only green allowed to carry text, and the only green
          // allowed under white text (brand bands, filled secondary buttons).
          // Derived in public_theme._ink(), not typed in, so the Appearance
          // colour picker cannot re-break it. The literal below only mirrors
          // that derivation for the stock #40b050 — no portal page uses this
          // stop, and the public shell always sets the var.
          ink: 'rgb(var(--color-primary-ink-rgb, 44 120 54) / <alpha-value>)',
          50: '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          // RE-BOUND (was the frozen Tailwind stop #86efac). This is now the
          // brand ink IN DARK MODE — the same hue mixed toward white until it
          // clears 5:1 on the dark page ground, so green stays green when the
          // theme flips.
          //
          // THE FALLBACK MUST STAY EXACTLY #86efac (134 239 172). Only the
          // PUBLIC shell emits --color-primary-on-dark-rgb; the portal loads
          // this same stylesheet and never sets it, so the fallback is what 23
          // live portal usages of `ecs-green-300` actually render (admin panel,
          // feedback, store, season rollover, three event-delegation JS files).
          // Putting the derived public value here instead silently re-tinted
          // every one of them. Freezing it at the old stop keeps a public-site
          // change from leaking into the portal, while the public :root always
          // wins on the public site.
          300: 'rgb(var(--color-primary-on-dark-rgb, 134 239 172) / <alpha-value>)',
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          800: '#1a472a',
          900: '#14532d',
          950: '#052e16',
        },
        'ecs-gold': {
          DEFAULT: 'rgb(var(--color-accent-rgb, 201 162 39) / <alpha-value>)',
          50: '#fefce8',
          100: '#fef9c3',
          200: '#fef08a',
          300: '#fde047',
          400: '#facc15',
          500: '#c9a227',
          600: '#ca8a04',
          700: '#a16207',
          800: '#854d0e',
          900: '#713f12',
        },
        // ECS Pub League LOGO blue (#203090) — the brand ACCENT. The shades the
        // public site actually uses (DEFAULT/400/600/700) are CSS-var-backed so
        // the public Appearance "accent color" re-skins every blue button/link
        // site-wide. Own var namespace (--color-blue-*) so it never collides
        // with ecs-gold's --color-accent-rgb. Portal pages don't set these vars,
        // so they fall back to the brand blue and are unaffected.
        'ecs-blue': {
          DEFAULT: 'rgb(var(--color-blue-rgb, 32 48 144) / <alpha-value>)',
          50: '#eef1fb',
          100: '#d8def5',
          200: '#b3bdec',
          // RE-BOUND (was the frozen #8593de). The ACTION ink in dark mode,
          // derived the same way as ecs-green-300. Public templates use this
          // wherever they used to reach for `ecs-blue-400`.
          //
          // Same rule as ecs-green-300 above: the fallback stays EXACTLY
          // #8593de (133 147 222) because the portal shares this stylesheet,
          // never sets --color-blue-on-dark-rgb, and still ships live uses of
          // `ecs-blue-300`. The public shell always sets the var, so the
          // derived action ink is what the public site renders.
          300: 'rgb(var(--color-blue-on-dark-rgb, 133 147 222) / <alpha-value>)',
          // Kept for the portal. RETIRED from the public site: 2.79:1 on the
          // dark ground, which is why it is not an ink anywhere.
          400: 'rgb(var(--color-blue-light-rgb, 94 111 208) / <alpha-value>)',
          500: '#3a49a8',
          600: 'rgb(var(--color-blue-rgb, 32 48 144) / <alpha-value>)',
          700: 'rgb(var(--color-blue-dark-rgb, 26 39 117) / <alpha-value>)',
          800: '#161f5e',
          900: '#121847',
        },
        // PUBLIC-SITE PAGE GROUNDS. Neither is a neutral: `paper` is the
        // primary mixed 97% toward white (a trace of the brand hue instead of
        // a flat #fff) and `paper-dark` is a near-black carrying 6% of it.
        // Both are derived in public_theme.theme_vars(), so the Appearance
        // picker re-tints the paper along with everything else. Portal pages
        // never set these vars and never use these utilities.
        // The GREEN SECTION GROUND. Plain ecs-green cannot carry white body copy
        // (4.35:1, fails AA); this is the primary darkened until white clears
        // 4.6:1, derived in theme_vars() so an Appearance re-skin still works.
        'ecs-pitch': 'rgb(var(--color-pitch-ground-rgb, 47 130 59) / <alpha-value>)',
        'paper': 'rgb(var(--color-paper-rgb, 229 235 228) / <alpha-value>)',
        'paper-dark': 'rgb(var(--color-paper-dark-rgb, 9 20 12) / <alpha-value>)',
        // Dark theme backgrounds (matching Flowbite dark mode)
        'dark': {
          'bg': '#111827',
          'card': '#1f2937',
          'border': '#374151',
          'hover': '#374151',
        },
        // Theme-customizable colors (via Admin Panel > Appearance)
        // These reference CSS variables that can be overridden per-site
        // Default values match ECS Brand + Flowbite/Tailwind palette
        'theme': {
          'primary': 'var(--color-primary, #1a472a)',           // ECS Green
          'primary-light': 'var(--color-primary-light, #15803d)',
          'primary-dark': 'var(--color-primary-dark, #14532d)',
          'secondary': 'var(--color-secondary, #6b7280)',       // Gray-500
          'accent': 'var(--color-accent, #c9a227)',             // ECS Gold
          'success': 'var(--color-success, #16a34a)',           // Green-600
          'warning': 'var(--color-warning, #d97706)',           // Amber-600
          'danger': 'var(--color-danger, #dc2626)',             // Red-600
          'info': 'var(--color-info, #2563eb)',                 // Blue-600
        },
        'theme-text': {
          'heading': 'var(--color-text-heading, #111827)',      // Gray-900
          'body': 'var(--color-text-body, #374151)',            // Gray-700
          'muted': 'var(--color-text-muted, #6b7280)',          // Gray-500
          'link': 'var(--color-text-link, #1a472a)',            // ECS Green
        },
        'theme-bg': {
          'body': 'var(--color-bg-body, #f9fafb)',              // Gray-50
          'card': 'var(--color-bg-card, #ffffff)',
          'input': 'var(--color-bg-input, #ffffff)',
          'sidebar': 'var(--color-bg-sidebar, #111827)',        // Gray-900
        },
        'theme-border': {
          'DEFAULT': 'var(--color-border, #e5e7eb)',            // Gray-200
          'input': 'var(--color-border-input, #d1d5db)',        // Gray-300
        },
      },
      // Two faces, bound to the Appearance screen's font pair. `--font-heading`
      // / `--font-body` are emitted by public_theme.theme_vars() into the
      // public shell's :root; the public default pair is Bricolage Grotesque
      // headings + Inter body, both self-hosted (app/static/vendor/fonts/).
      //
      // THE IN-var() FALLBACKS ARE LOAD-BEARING, not belt-and-braces. Portal
      // pages load tailwind.css but NOT the public shell, so --font-body /
      // --font-heading are UNDEFINED there. A bare `var(--font-body)` would be
      // invalid-at-computed-value-time on every portal page, which for an
      // inherited property means `font-sans` silently resolves to whatever the
      // parent is — e.g. the `font-sans` spans nested inside `font-mono`
      // tables in the admin panel would render monospace. With the fallback,
      // the declaration is always valid and the public :root simply wins.
      fontFamily: {
        display: ["var(--font-heading, 'Big Shoulders Display')", 'Big Shoulders Display', 'Haettenschweiler', 'Arial Narrow', 'system-ui', 'sans-serif'],
        sans: ["var(--font-body, 'Inter')", 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
        // Data and labels: season strips, counts, eyebrows, dates, step
        // ordinals. It is what makes a fixture list read as a fixture list
        // rather than as marketing copy.
        mono: ["var(--font-mono, 'JetBrains Mono')", 'JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      // Ft8 marquee footer (public site). Declared here rather than as a custom
      // <style> block so it stays inside Tailwind — the project rule is Tailwind
      // + Flowbite utilities only. Translating -50% pairs with two identical
      // duplicated tracks to give a seamless loop. The consumer MUST also carry
      // motion-reduce:animate-none; the animation is decorative and the text is
      // duplicated aria-hidden with a visually-hidden real copy for screen readers.
      keyframes: {
        'marquee-x': {
          from: { transform: 'translateX(0)' },
          to: { transform: 'translateX(-50%)' },
        },
      },
      animation: {
        'marquee-x': 'marquee-x 32s linear infinite',
      },
    },
  },
  plugins: [
    flowbitePlugin,
    formsPlugin,
    ...(typographyPlugin ? [typographyPlugin] : []),
  ],
};

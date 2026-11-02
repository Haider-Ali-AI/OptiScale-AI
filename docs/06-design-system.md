# 06 · Design system: "Marketing Intelligence Flight Deck"

Implemented in `frontend/app/globals.css` (tokens + component classes) and `frontend/components/ui.tsx` / `charts.tsx`. Nothing is inherited from the reference `design.md` / `design-2.md` (light lime/charcoal rounded bento).

## Tokens
| Token | Dark (primary) | Light (separate palette) | Use |
|---|---|---|---|
| `--canvas` | #0B1220 | #F3F1EC (warm paper) | page |
| `--rail` | #0E1728 | #14213A (stays dark) | navigation rail |
| `--surface` | #121F33 | #FBFAF7 | inputs, flat panels |
| `--card` | #18273E | #FFFFFF | working panels |
| `--teal` | #39D7C8 | #0B7F76 | primary action, signal |
| `--peri` | #8A87F6 | #4F4BC4 | ML / analysis emphasis |
| `--amber` | #FFB860 | #9A5800 | recommendation / decision |
| `--text` / `--text-2` / `--text-3` | #F6F8FC / #A7B7CE / #8798B2 | #121A2B / #4A5568 / #5F6B7D | hierarchy |
| `--line` | #2A3A52 | #DCD7CC | borders |
| `--critical` | #F37D83 | #B3261E | real errors only |

Light mode darkens accents to keep AA contrast on white rather than inverting. The preference persists in `localStorage` and is applied by an inline pre-paint script (no flash); with no stored choice the OS `prefers-color-scheme` decides.

## Platform semantics (identical on every screen)
| Platform | Colour (dark) | Marker shape |
|---|---|---|
| Facebook | #5B9BFF | circle |
| Instagram | #E879B9 | diamond |
| Google | #E8C547 | square |
| TikTok | #4DD4E8 | triangle |
| YouTube | #FF7A59 | cross |

Shapes plus text labels satisfy WCAG 1.4.1 (not colour alone). No platform logos are used (trademark rules).

## Type & numbers
Manrope 400–800 (UI and display, tight negative tracking on headlines), IBM Plex Mono for IDs/hashes/formulas. All financial values use tabular numerals. PKR format `Rs 1,234.56`; large values `Rs 1.95 Cr` / `Lakh` with the exact value as sub-text.

## Layout
Slim dark navigation rail (248px, grouped Start / Analyse / Decide / Extend) → off-canvas drawer below 1024px with Escape to close. Sticky top bar: breadcrumb, source picker with synthetic/real badge, theme toggle. Wide analysis canvas (max 1480px); `cols-main-side` pairs a primary chart with a contextual insight panel only where useful. KPI strip is a single hairline-divided band, not separate cards.

## Components
PageHead, Panel, KPI strip, Notice (info/warn/error/ok with icon + role), Busy/Skeleton, Empty, Segmented control, sortable/paginated data table with `aria-sort`, native `<dialog>` confirm, disclosure, source badge, platform marker. Charts: platform bars, spend/revenue area timeline, bespoke log-scale funnel, opportunity scatter matrix, allocation stack bar, response curves, benchmark log-scale lines. **Every chart has a "Show chart data as a table" alternative.**

## Motion & accessibility
150–200 ms transitions only; skeleton shimmer; `prefers-reduced-motion` disables animation. Skip link, visible focus ring, labelled controls, `role=alert` for errors, `aria-live` busy states, no hover-only actions.

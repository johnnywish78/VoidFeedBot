# VoidFeed Studio — UI Icon Inventory

Family: Lucide outline icon system (vendored from lucide-react v1.53.0, ISC) — inline sprite in `app.js` `UI_ICONS`.
Style: 24×24 viewBox, stroke-width 2, round caps/joins, `fill:none`, `stroke: currentColor` (theme-aware). No emoji-based icon substitution.
No emoji are used as interface icons (verified by DOM scan, 2026-11-27).

| Icon key    | Semantic purpose                     | Path / source                       | Used in |
|-------------|--------------------------------------|-------------------------------------|---------|
| home        | Main navigation: Home                | icons/ui/home.svg                   | bottom-nav |
| channels    | Main navigation: Channels/Chats (message mark) | icons/ui/channels.svg     | bottom-nav |
| network     | Connections (technical)              | inline sprite `network`             | Connections panel, nav |
| posts       | Posts / file-text                    | icons/ui/posts.svg                  | bottom-nav, drawer |
| schedule    | Calendar-clock / Schedule            | icons/ui/schedule.svg               | bottom-nav, editor schedule |
| history     | History / clock-rotate-left          | icons/ui/history.svg                | bottom-nav |
| profile     | User-round / Profile                 | icons/ui/profile.svg                | bottom-nav, drawer |
| menu        | Drawer/menu toggle                   | icons/ui/menu.svg                   | topbar, drawer head |
| refresh     | RefreshCw                           | icons/ui/refresh.svg                | topbar |
| sun / moon  | Theme toggle (destination icon)      | inline sprite `sun`/`moon`          | topbar theme control |
| languages    | Language / globe                     | inline sprite `languages`           | drawer lang item |
| back        | Arrow-left / back                    | icons/ui/back.svg                   | drawer |
| help        | Circle-help                          | icons/ui/help.svg                   | drawer, help |
| cancel      | X / close/cancel                     | icons/ui/cancel.svg                 | drawer, dialogs |
| squarePen   | Create post / edit                   | inline sprite `squarePen`           | drawer create, FAB |
| penLine     | Rewrite/edit line                    | inline sprite `penLine`             | editor rewrite |
| shrink      | Shorter text                         | inline sprite `shrink`              | editor |
| smile       | Add emoji                           | inline sprite `smile`               | editor |
| paperclip   | Attach media                        | inline sprite `paperclip`           | editor attach |
| images      | Media library                       | inline sprite `images`              | editor library, sheet |
| layoutTemplate | Templates (layout-template)        | inline sprite `layoutTemplate`      | editor templates, sheet |
| media       | Image/media generation               | icons/ui/media.svg                  | editor mgen |
| eye        | Preview                             | inline sprite `eye`                 | editor preview, sheet |
| send       | Publish (paper-plane)               | inline sprite `send`                | editor publish |
| copy       | Copy                                | inline sprite `copy`                | editor |
| sparkles    | AI generate                         | inline sprite `sparkles`            | editor AI, AI card |
| link       | Link preview toggle                  | inline sprite `link`                | drawer switch |
| repeat     | Auto-save forwards / repeat          | inline sprite `repeat`              | drawer switch |
| wrench     | Setup required (technical)           | inline sprite `wrench`              | Connections technical badge |
| circleMinus | Unsupported (technical)             | inline sprite `circleMinus`         | Connections technical badge |
| badgeCheck | Verified link badge                  | inline sprite `badgeCheck`          | Profile/Connections verified |
| download   | Fetch news / import                  | inline sprite `download`            | news fetch button |
| target     | Target networks                       | inline sprite `target`              | editor networks title |
| brand      | VoidFeed wormhole mark (UI only)     | inline sprite `brand`               | splash/brand contexts |

Semantic rule enforced: same action → same icon everywhere; different concepts → distinct icons.
The `applyStudioIcons()` helper swaps legacy emoji glyphs to these SVG glyphs at runtime.

# Figma Design System Integration Guide
# Invictus Hiring — Frontend

This document describes the design system conventions used in this codebase, intended as a reference for integrating Figma designs via MCP or manual implementation.

---

## 1. Token Definitions

Tokens are defined in **`src/index.css`** using Tailwind v4's `@theme` block. There is no separate token file or transformation pipeline — the CSS custom properties are the source of truth.

```css
/* src/index.css */
@import "tailwindcss";

@theme {
  /* Brand palette (green — used sparingly in this app) */
  --color-brand-50:  #f0fdf4;
  --color-brand-100: #dcfce7;
  --color-brand-500: #22c55e;
  --color-brand-600: #16a34a;
  --color-brand-700: #15803d;

  /* Semantic surface tokens */
  --color-surface: #fafaf9;   /* page background */
  --color-card:    #ffffff;   /* card / panel background */
  --color-border:  #e7e5e4;   /* default border */
  --color-muted:   #78716c;   /* secondary text */
  --color-text:    #1c1917;   /* primary text */

  /* Typography */
  --font-sans: "Inter", system-ui, sans-serif;

  /* Border radius */
  --radius: 0.75rem;          /* base radius → rounded-xl on panels */
}
```

### Effective colour palette

The UI is dominated by **violet** and **stone** from Tailwind's default scale (not custom tokens). These are used directly as utility classes throughout the codebase:

| Purpose | Tailwind class | Hex |
|---------|---------------|-----|
| Primary action / brand accent | `violet-600` | #7c3aed |
| Primary hover | `violet-700` | #6d28d9 |
| Focus ring | `violet-500` | #8b5cf6 |
| Light tint / chip bg | `violet-50` | #f5f3ff |
| Light border | `violet-200` | #ddd6fe |
| Body text | `stone-900` | #1c1917 |
| Secondary text | `stone-500` | #78716c |
| Subtle text | `stone-400` | #a8a29e |
| Page background | `stone-50` / `violet-50` | #fafaf9 |
| Card background | `white` | #ffffff |
| Border | `stone-200` | #e7e5e4 |
| Success / posted | `emerald-*` | |
| Warning / expiry | `amber-*` | |
| Destructive | `red-*` | |

> **When implementing Figma designs:** map primary/CTA colours to `violet-600`, hover to `violet-700`, and muted elements to the `stone-*` scale. Do not introduce new custom CSS variables unless unavoidable.

---

## 2. Component Library

### Location
```
frontend/src/components/
├── ui/           ← primitive shadcn/ui components (Button, Badge, Input, Label, Textarea, Card)
├── jd/           ← JD workflow feature components
├── dashboard/    ← Dashboard & quality panel
├── auth/         ← Login page
├── agents/       ← Agent pipeline visualiser
└── layout/       ← PageShell wrapper
```

### Architecture
Components use **shadcn/ui** conventions:
- Primitives in `components/ui/` are thin wrappers over **Radix UI** + **CVA (class-variance-authority)**
- Variants declared with `cva()` — never via conditional className strings
- All class merging goes through `cn()` from `src/lib/utils.ts` (`clsx` + `tailwind-merge`)
- `React.forwardRef` used on all form primitives
- No Storybook

### Primitive component patterns

```tsx
// Button — cva variants + Radix Slot for asChild
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default:     'bg-violet-600 text-white hover:bg-violet-700',
        outline:     'border border-violet-200 bg-white hover:bg-violet-50 text-stone-700',
        ghost:       'hover:bg-violet-100 text-stone-700',
        destructive: 'bg-red-500 text-white hover:bg-red-600',
        secondary:   'bg-stone-100 text-stone-800 hover:bg-stone-200',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm:      'h-7 px-3 text-xs',
        lg:      'h-11 px-6',
        icon:    'h-9 w-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  }
)
```

```tsx
// Badge — rounded-full pill, four semantic variants
const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default:     'bg-violet-100 text-violet-800',
        secondary:   'bg-stone-100 text-stone-700',
        warning:     'bg-amber-100 text-amber-800',
        destructive: 'bg-red-100 text-red-700',
      },
    },
  }
)
```

```tsx
// Input — consistent focus ring, stone borders
'flex h-9 w-full rounded-lg border border-stone-200 bg-white px-3 py-1 text-sm
 text-stone-900 placeholder:text-stone-400
 focus:outline-none focus:ring-2 focus:ring-violet-500
 disabled:cursor-not-allowed disabled:opacity-50'
```

### Feature panel pattern (`PanelWrapper`)

All right-column panels use `PanelWrapper` — a collapsible/expandable container:

```tsx
<PanelWrapper
  icon={<CheckCircle className="h-4 w-4 text-violet-600" />}
  title="Panel Title"
  borderColor="border-violet-200"
  headerBg="bg-violet-50"
  headerHover="hover:bg-violet-100"
>
  {/* content */}
</PanelWrapper>
```

Supported states: `normal` | `minimized` | `maximized` (full-screen overlay via `fixed inset-0 z-50`).

---

## 3. Frameworks & Libraries

| Concern | Library | Version |
|---------|---------|---------|
| UI framework | React | 19 |
| Routing | React Router DOM | 7 |
| Styling | Tailwind CSS | 4 (Vite plugin — no `tailwind.config.*` file) |
| Component primitives | Radix UI | various |
| Variant API | class-variance-authority (CVA) | 0.7 |
| Class merging | clsx + tailwind-merge | latest |
| Icons | lucide-react | 1.12 |
| Build / dev server | Vite | 8 |
| Language | TypeScript | 6 |

> **Tailwind v4 note:** There is **no `tailwind.config.js`**. Configuration lives entirely in `src/index.css` via `@theme {}`. The Vite plugin (`@tailwindcss/vite`) handles compilation. Do not create a `tailwind.config.*` file.

---

## 4. Asset Management

```
frontend/src/assets/
├── hero.png       ← landing/dashboard hero image (imported directly in TSX)
├── react.svg      ← unused default
└── vite.svg       ← unused default
```

Assets are imported as ES modules:
```tsx
import hero from '@/assets/hero.png'
<img src={hero} />
```

No CDN, no image optimisation pipeline, no public/ directory usage. For new assets, drop them in `src/assets/` and import with the `@/` alias.

---

## 5. Icon System

**Library:** `lucide-react` (tree-shaken, named imports only)

```tsx
import { Briefcase, CheckCircle, ChevronLeft, MapPin } from 'lucide-react'

// Usage — always sized via className, never width/height props
<Briefcase className="h-4 w-4 text-violet-600" />
<CheckCircle className="h-3.5 w-3.5" />
```

### Conventions
- Size classes used throughout: `h-3 w-3`, `h-3.5 w-3.5`, `h-4 w-4`, `h-5 w-5`
- Colour applied via `text-*` (inherits currentColor)
- `animate-spin` added for loading states: `<Loader2 className="h-4 w-4 animate-spin" />`
- No custom SVG icons; no sprite sheets; no icon font

> **When implementing Figma icons:** find the closest `lucide-react` match. If no match exists, inline the SVG as a React component in the same file — do not add a separate icon library.

---

## 6. Styling Approach

### Method
**Utility-first Tailwind CSS** — no CSS Modules, no Styled Components, no CSS-in-JS.

### Class composition rules
1. All conditional/merged classes go through `cn()`:
   ```tsx
   import { cn } from '@/lib/utils'
   <div className={cn('base-classes', condition && 'conditional-class', className)} />
   ```
2. Variant logic uses `cva()` — never ternaries for multi-variant components
3. `tailwind-merge` (via `cn`) handles deduplication when consumers override classes

### Global styles (`src/index.css`)
```css
body {
  font-family: var(--font-sans);   /* Inter */
  background-color: var(--color-surface);
  color: var(--color-text);
  margin: 0;
}

#root { min-height: 100svh; }

/* Thin scrollbar on chat panels */
.chat-scroll::-webkit-scrollbar { width: 4px; }
.chat-scroll::-webkit-scrollbar-thumb { background: #e7e5e4; border-radius: 2px; }
```

### Responsive design
No mobile-first breakpoints are used in the HR app — it is a desktop-only tool. The public job board (`JobBoardPage`, `JobDetailPage`) uses `max-w-4xl mx-auto` centering with `px-6` gutters. No `sm:`/`md:`/`lg:` breakpoints are needed unless expanding to mobile.

### Spacing scale (common values observed)
- Gap between items: `gap-2`, `gap-3`, `gap-4`
- Section padding: `px-4 py-3` (panel headers), `px-6 py-8` (page sections)
- Card padding: `p-4`, `p-5`
- Micro spacing: `p-1.5`, `px-2.5 py-0.5` (badges/chips)

---

## 7. Project Structure

```
frontend/
├── src/
│   ├── App.tsx                  ← root router (BrowserRouter + Routes)
│   ├── main.tsx                 ← React 19 createRoot entry
│   ├── index.css                ← Tailwind @theme tokens + global styles
│   │
│   ├── api/                     ← typed fetch wrappers (no axios)
│   │   ├── auth.ts
│   │   ├── candidates.ts        ← fetchJobs (paginated), fetchJob, submitApplication
│   │   ├── jd.ts                ← draft, chat, approve, publish, revert
│   │   └── analytics.ts
│   │
│   ├── components/
│   │   ├── ui/                  ← shadcn/ui primitives
│   │   │   ├── button.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── input.tsx
│   │   │   ├── label.tsx
│   │   │   ├── textarea.tsx
│   │   │   └── card.tsx
│   │   ├── auth/
│   │   │   └── LoginPage.tsx
│   │   ├── dashboard/
│   │   │   ├── DashboardHome.tsx
│   │   │   └── QualityPanel.tsx
│   │   ├── jd/                  ← JD workflow panels (right column)
│   │   │   ├── PanelWrapper.tsx ← collapsible/maximizable panel shell
│   │   │   ├── JDChat.tsx       ← main chat + layout orchestrator
│   │   │   ├── ApprovalBar.tsx
│   │   │   ├── PublishingPanel.tsx
│   │   │   ├── ApplicationsPanel.tsx
│   │   │   ├── InterviewPanel.tsx
│   │   │   ├── ChatMessage.tsx  ← renders markdown + ML result cards
│   │   │   ├── SessionSidebar.tsx
│   │   │   └── RequirementsForm.tsx
│   │   ├── agents/
│   │   │   └── AgentPipeline.tsx
│   │   └── layout/
│   │       └── PageShell.tsx
│   │
│   ├── hooks/
│   │   └── useJDSession.ts      ← central state machine (idle→drafting→…→published)
│   │
│   ├── pages/                   ← public-facing (no auth required)
│   │   ├── JobBoardPage.tsx     ← paginated job listing
│   │   └── JobDetailPage.tsx    ← single job + application form
│   │
│   ├── lib/
│   │   ├── utils.ts             ← cn() helper
│   │   └── download.ts          ← file download util
│   │
│   └── assets/
│       └── hero.png
│
├── vite.config.ts               ← Vite + React plugin + Tailwind v4 plugin + @ alias
├── tsconfig.json
└── package.json
```

### Path alias
`@/` maps to `src/`. Always use `@/` imports — never relative `../../` paths.

```tsx
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { fetchJobs } from '@/api/candidates'
```

### Feature organisation pattern
Features are grouped by domain under `components/<domain>/`. Each domain folder contains all the components for that feature area — there is no separation of container vs presentational components. State lives in `hooks/useJDSession.ts` (single hook for the entire JD workflow).

---

## 8. Implementing Figma Designs — Quick Rules

1. **Colours:** use `violet-*` for primary/brand, `stone-*` for neutral, `emerald-*` for success, `amber-*` for warning, `red-*` for destructive. Never hardcode hex values.
2. **New components:** create in `components/ui/` if primitive, or `components/<feature>/` if domain-specific.
3. **Variants:** use `cva()` for any component with ≥2 visual variants.
4. **Class merging:** always wrap in `cn()` when accepting external `className` prop.
5. **Icons:** import from `lucide-react`; size with `h-*/w-*`; colour with `text-*`.
6. **Spacing:** stick to Tailwind's default scale — no arbitrary values unless unavoidable.
7. **Panels:** wrap new right-column panels in `<PanelWrapper>` with a `borderColor`, `headerBg`, and `headerHover` from the `violet-*` or `stone-*` family.
8. **No new CSS files** — everything in Tailwind utility classes. Only `index.css` holds global styles.
9. **No `tailwind.config.*`** — add new tokens in `src/index.css` `@theme {}` block if genuinely needed.
10. **Radix UI** — use existing Radix primitives (Dialog, Select, ScrollArea, Label, Separator) for accessible interactive components. Check `package.json` before pulling in new headless libs.
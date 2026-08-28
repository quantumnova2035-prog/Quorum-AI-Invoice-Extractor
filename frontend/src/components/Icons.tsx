/* Inline SVG rather than an icon package: there are nine of them, they need to
   inherit `currentColor` to work on both glass and the solid blue pill, and a
   dependency for nine paths is not worth the bytes. 24x24 grid, 1.6 stroke. */

type P = { size?: number; className?: string }

const base = (size: number) => ({
  width: size, height: size, viewBox: '0 0 24 24',
  fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.6, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
  'aria-hidden': true,
})

export const IconHome = ({ size = 19, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M3.5 10.4 12 3.8l8.5 6.6" />
    <path d="M5.6 9v10.2h12.8V9" />
    <path d="M9.6 19.2v-5.4h4.8v5.4" />
  </svg>
)

export const IconUpload = ({ size = 19, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 15.5V4.2" />
    <path d="m7.6 8.4 4.4-4.2 4.4 4.2" />
    <path d="M4.5 14.6v3.6a1.8 1.8 0 0 0 1.8 1.8h11.4a1.8 1.8 0 0 0 1.8-1.8v-3.6" />
  </svg>
)

export const IconSettings = ({ size = 19, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="2.9" />
    <path d="M19.1 14.4a1.5 1.5 0 0 0 .3 1.7l.1.1a1.8 1.8 0 1 1-2.5 2.5l-.1-.1a1.5 1.5 0 0 0-1.7-.3 1.5 1.5 0 0 0-.9 1.4v.2a1.8 1.8 0 1 1-3.6 0v-.1a1.5 1.5 0 0 0-1-1.4 1.5 1.5 0 0 0-1.7.3l-.1.1a1.8 1.8 0 1 1-2.5-2.5l.1-.1a1.5 1.5 0 0 0 .3-1.7 1.5 1.5 0 0 0-1.4-.9h-.2a1.8 1.8 0 1 1 0-3.6h.1a1.5 1.5 0 0 0 1.4-1 1.5 1.5 0 0 0-.3-1.7l-.1-.1A1.8 1.8 0 1 1 7.7 4.8l.1.1a1.5 1.5 0 0 0 1.7.3h.1a1.5 1.5 0 0 0 .9-1.4v-.2a1.8 1.8 0 1 1 3.6 0v.1a1.5 1.5 0 0 0 .9 1.4 1.5 1.5 0 0 0 1.7-.3l.1-.1a1.8 1.8 0 1 1 2.5 2.5l-.1.1a1.5 1.5 0 0 0-.3 1.7v.1a1.5 1.5 0 0 0 1.4.9h.2a1.8 1.8 0 1 1 0 3.6h-.1a1.5 1.5 0 0 0-1.4.9Z" />
  </svg>
)

export const IconDoc = ({ size = 19, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M13.6 3.4H7.2a1.8 1.8 0 0 0-1.8 1.8v13.6a1.8 1.8 0 0 0 1.8 1.8h9.6a1.8 1.8 0 0 0 1.8-1.8V8.2Z" />
    <path d="M13.6 3.4v4.8h5" />
  </svg>
)

export const IconClose = ({ size = 13, className }: P) => (
  <svg {...base(size)} className={className} strokeWidth={2}>
    <path d="M17 7 7 17M7 7l10 10" />
  </svg>
)

export const IconChevrons = ({ size = 15, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="m11.5 17-5-5 5-5M18 17l-5-5 5-5" />
  </svg>
)

export const IconSearch = ({ size = 15, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="10.8" cy="10.8" r="6.4" />
    <path d="m20 20-4.7-4.7" />
  </svg>
)

export const IconPlus = ({ size = 17, className }: P) => (
  <svg {...base(size)} className={className} strokeWidth={2}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)

export const IconAlert = ({ size = 14, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M12 8v4.6M12 15.8h.01" />
  </svg>
)

export const IconCheck = ({ size = 14, className }: P) => (
  <svg {...base(size)} className={className} strokeWidth={2.2}>
    <path d="m5.5 12.5 4 4 9-9" />
  </svg>
)

/* Where the API lives.

   Default is the empty string, meaning every call is relative - `/api/health`
   goes to whatever origin served the page. That is what the Vite dev proxy
   handles locally, and what a hosting rewrite rule handles in production. It is
   the better arrangement when it works: the browser sees a single origin, so
   there is no CORS preflight on any request and no build-time configuration.

   Set VITE_API_BASE to an absolute origin when that is not available - a host
   whose rewrite rules will not proxy to an external URL, or an API on a
   deliberately separate domain. Then the browser talks to the API directly and
   CORS_ORIGINS on the backend must name this site's exact origin, or every
   request fails the preflight.

   This is read at BUILD time, not at run time. Vite substitutes the literal
   into the bundle, so changing it on the host requires a rebuild, not a
   restart. */
const RAW = import.meta.env.VITE_API_BASE ?? ''

// A trailing slash here would produce `https://host//api/health`, which some
// servers 404 rather than normalise.
const BASE = RAW.replace(/\/+$/, '')

/** Build a URL for an API path. Always pass the leading `/api/...`. */
export const api = (path: string) => `${BASE}${path}`

// Sert /data/local/* depuis R2 (variante wrangler.r2.toml). Lecture seule : GET et HEAD.
// Les en-têtes de _headers ne s'appliquent pas aux réponses d'un Worker : ils sont repris ici.
const ENTETES = {
  'Content-Security-Policy':
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'",
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Resource-Policy': 'same-origin',
  'Strict-Transport-Security': 'max-age=31536000',
  'Cache-Control': 'public, max-age=3600, stale-while-revalidate=86400',
}
const CLE = /^local\/[A-Za-z0-9_\-./]+\.json$/

function reponse(corps, statut, extra = {}) {
  return new Response(corps, { status: statut, headers: { ...ENTETES, ...extra } })
}

export default {
  async fetch(requete, env) {
    const url = new URL(requete.url)
    if (!url.pathname.startsWith('/data/local/')) return env.ASSETS.fetch(requete)
    if (requete.method !== 'GET' && requete.method !== 'HEAD') return reponse('Méthode non permise', 405, { Allow: 'GET, HEAD' })
    const cle = decodeURIComponent(url.pathname.slice('/data/'.length))
    if (!CLE.test(cle) || cle.includes('..')) return reponse('Introuvable', 404, { 'Content-Type': 'text/plain; charset=utf-8' })
    const objet = await env.LOCAL.get(cle, { onlyIf: requete.headers })
    if (objet === null) return reponse('Introuvable', 404, { 'Content-Type': 'text/plain; charset=utf-8' })
    const extra = { 'Content-Type': 'application/json; charset=utf-8', ETag: objet.httpEtag }
    // onlyIf non satisfait (If-None-Match identique) : l'objet est rendu sans corps
    if (!('body' in objet) || !objet.body) return reponse(null, 304, { ETag: objet.httpEtag })
    return reponse(requete.method === 'HEAD' ? null : objet.body, 200, extra)
  },
}

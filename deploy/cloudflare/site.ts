// Worker du site « Le billet découpé » : sert les fichiers statiques (web/dist) tels quels, en-têtes de _headers
// compris, et compte de façon anonyme les pages HTML vues (audience.ts) si la base D1 AUDIENCE est liée.
// Sans liaison AUDIENCE, le comportement est exactement celui d'avant (fichiers statiques seuls).
import { compter, purger, type D1Like } from './audience'

interface Env {
  ASSETS: { fetch(requete: Request): Promise<Response> }
  AUDIENCE?: D1Like
}

export default {
  async fetch(requete: Request, env: Env, ctx: { waitUntil(p: Promise<unknown>): void }): Promise<Response> {
    const reponse = await env.ASSETS.fetch(requete)
    compter(requete, reponse, env.AUDIENCE, ctx)
    return reponse
  },

  // Déclencheur planifié (wrangler.toml, [triggers]) : purge des agrégats de plus de 13 mois.
  async scheduled(_evenement: unknown, env: Env, ctx: { waitUntil(p: Promise<unknown>): void }): Promise<void> {
    if (env.AUDIENCE) ctx.waitUntil(purger(env.AUDIENCE).catch(() => {}))
  },
}

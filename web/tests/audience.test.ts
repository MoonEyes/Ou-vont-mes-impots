// Comptage anonyme côté serveur (deploy/cloudflare/audience.ts et site.ts) : heuristique robot, normalisation du
// chemin et du référent, aucune donnée personnelle dans la ligne écrite, page servie même si D1 échoue.
import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  _reinitialiser,
  aCompter,
  appareil,
  compter,
  domaineReferent,
  enregistrer,
  estRobot,
  ligne,
  normaliserChemin,
  PURGE,
  type D1Like,
} from '../../deploy/cloudflare/audience'
import site from '../../deploy/cloudflare/site'

const FIREFOX = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0'
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1'
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36'
const IP = '203.0.113.42'

function navigation(adresse: string, entetes: Record<string, string> = {}, methode = 'GET'): Request {
  const r = new Request(adresse, {
    method: methode,
    headers: {
      'User-Agent': FIREFOX,
      'Accept-Language': 'fr-FR,fr;q=0.9',
      Accept: 'text/html,application/xhtml+xml',
      'Sec-Fetch-Mode': 'navigate',
      'CF-Connecting-IP': IP,
      ...entetes,
    },
  })
  Object.defineProperty(r, 'cf', { value: { country: 'FR', city: 'Nantes', latitude: '47.2', asn: 3215 } })
  return r
}
const html = (statut = 200) => new Response('<!doctype html>', { status: statut, headers: { 'Content-Type': 'text/html; charset=utf-8' } })

/** Fausse base D1 qui garde les requêtes et paramètres reçus. */
function base(echoue = false) {
  const appels: { sql: string; valeurs: unknown[] }[] = []
  const db: D1Like = {
    prepare: (sql) => ({
      bind: (...valeurs) => ({
        run: async () => {
          appels.push({ sql, valeurs })
          if (echoue) throw new Error('D1 indisponible')
          return {}
        },
      }),
    }),
  }
  return { db, appels }
}
function contexte() {
  const promesses: Promise<unknown>[] = []
  return { promesses, waitUntil: (p: Promise<unknown>) => void promesses.push(p) }
}

beforeEach(() => _reinitialiser())

describe('heuristique robot et appareil', () => {
  it.each([
    'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
    'Mozilla/5.0 (compatible; bingbot/2.0)',
    'curl/8.5.0',
    'Wget/1.21',
    'python-requests/2.32',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/131.0 Safari/537.36',
    'facebookexternalhit/1.1',
    'Mozilla/5.0 (compatible; UptimeRobot/2.0)',
    'Site24x7 monitoring',
    'Slackbot-LinkExpanding 1.0',
    'Mozilla/5.0 (compatible; AhrefsBot/7.0)',
    'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2)',
  ])('robot : %s', (ua) => expect(estRobot(ua, 'fr')).toBe(true))

  it.each([FIREFOX, IPHONE, ANDROID, 'Mozilla/5.0 (Linux; Android 13; CUBOT X30) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36'])(
    'humain : %s',
    (ua) => expect(estRobot(ua, 'fr-FR')).toBe(false),
  )

  it('sans Accept-Language ou sans user-agent : robot', () => {
    expect(estRobot(FIREFOX, null)).toBe(true)
    expect(estRobot(FIREFOX, '  ')).toBe(true)
    expect(estRobot(null, 'fr')).toBe(true)
  })

  it('mobile ou ordinateur seulement', () => {
    expect(appareil(IPHONE)).toBe('mobile')
    expect(appareil(ANDROID)).toBe('mobile')
    expect(appareil(FIREFOX)).toBe('ordinateur')
    expect(appareil(null)).toBe('ordinateur')
  })
})

describe('normalisation', () => {
  it('chemin sans paramètres ni fragment, index.html retiré', () => {
    expect(normaliserChemin('https://lebilletdecoupe.fr/methode/?utm_source=x&id=42#/calcul')).toBe('/methode/')
    expect(normaliserChemin('https://lebilletdecoupe.fr/Local/44109-Nantes/index.html')).toBe('/local/44109-nantes/')
    expect(normaliserChemin('https://lebilletdecoupe.fr//a//b/')).toBe('/a/b/')
    expect(normaliserChemin('https://lebilletdecoupe.fr/')).toBe('/')
  })
  it('chemin inattendu ou trop long : « /autre »', () => {
    expect(normaliserChemin('https://lebilletdecoupe.fr/%3Cscript%3E')).toBe('/autre')
    expect(normaliserChemin('https://lebilletdecoupe.fr/%E0%A4%A')).toBe('/autre')
    expect(normaliserChemin('https://lebilletdecoupe.fr/' + 'a'.repeat(300))).toBe('/autre')
    expect(normaliserChemin('pas une adresse')).toBe('/autre')
  })
  it('référent : nom de domaine seul, jamais le chemin ni la requête', () => {
    expect(domaineReferent('https://www.google.com/search?q=mon+salaire+3200', 'lebilletdecoupe.fr')).toBe('google.com')
    expect(domaineReferent('https://m.facebook.com/groups/123/posts/456', 'lebilletdecoupe.fr')).toBe('m.facebook.com')
    expect(domaineReferent(null, 'lebilletdecoupe.fr')).toBe('aucun')
    expect(domaineReferent('https://lebilletdecoupe.fr/methode/', 'lebilletdecoupe.fr')).toBe('interne')
    expect(domaineReferent('https://www.lebilletdecoupe.fr/', 'lebilletdecoupe.fr')).toBe('interne')
    expect(domaineReferent('android-app://com.google.android.gm/', 'lebilletdecoupe.fr')).toBe('autre')
    expect(domaineReferent('n’importe quoi', 'lebilletdecoupe.fr')).toBe('autre')
    expect(domaineReferent('https://user:motdepasse@exemple.org:8443/x', 'lebilletdecoupe.fr')).toBe('exemple.org')
  })
})

describe('requêtes comptées', () => {
  it('page HTML de navigation : oui', () => expect(aCompter(navigation('https://lebilletdecoupe.fr/'), html())).toBe(true))
  it('HEAD, POST : non', () => {
    expect(aCompter(navigation('https://lebilletdecoupe.fr/', {}, 'HEAD'), html())).toBe(false)
    expect(aCompter(navigation('https://lebilletdecoupe.fr/', {}, 'POST'), html())).toBe(false)
  })
  it('assets, données, sw.js : non', () => {
    for (const p of ['/assets/index-abc.js', '/data/meta.json', '/sw.js']) expect(aCompter(navigation('https://lebilletdecoupe.fr' + p), html())).toBe(false)
  })
  it('réponse non HTML ou non 200 (404, redirection) : non', () => {
    expect(aCompter(navigation('https://lebilletdecoupe.fr/x'), html(404))).toBe(false)
    expect(aCompter(navigation('https://lebilletdecoupe.fr/methode'), new Response(null, { status: 307, headers: { Location: '/methode/' } }))).toBe(false)
    expect(aCompter(navigation('https://lebilletdecoupe.fr/og.png'), new Response('x', { headers: { 'Content-Type': 'image/png' } }))).toBe(false)
  })
  it('requête du service worker, préchargement : non', () => {
    expect(aCompter(navigation('https://lebilletdecoupe.fr/', { 'Sec-Fetch-Mode': 'same-origin' }), html())).toBe(false)
    expect(aCompter(navigation('https://lebilletdecoupe.fr/', { 'Sec-Purpose': 'prefetch' }), html())).toBe(false)
  })
  it('opposition par Do Not Track ou Global Privacy Control : non', () => {
    expect(aCompter(navigation('https://lebilletdecoupe.fr/', { DNT: '1' }), html())).toBe(false)
    expect(aCompter(navigation('https://lebilletdecoupe.fr/', { 'Sec-GPC': '1' }), html())).toBe(false)
  })
})

describe('ligne écrite : aucune donnée personnelle', () => {
  it('seulement des catégories, ni IP, ni user-agent, ni ville, ni paramètre, ni URL de référent', async () => {
    const req = navigation('https://lebilletdecoupe.fr/methode/?email=a@b.fr', {
      Referer: 'https://www.google.com/search?q=salaire+3200+euros',
      'User-Agent': IPHONE,
      Cookie: 'x=1',
    })
    const l = ligne(req, new Date('2026-11-21T23:30:00Z'))
    expect(l).toEqual({ jour: '2026-11-22', chemin: '/methode/', pays: 'FR', referent: 'google.com', appareil: 'mobile', robot: 0 })
    const { db, appels } = base()
    await enregistrer(db, l)
    const ecrit = JSON.stringify(appels)
    for (const interdit of [IP, 'iPhone', 'Mozilla', 'Nantes', '47.2', '3215', 'a@b.fr', 'email', 'salaire', 'search', 'x=1', 'fr-FR'])
      expect(ecrit).not.toContain(interdit)
    expect(appels[0].sql).toMatch(/^CREATE TABLE IF NOT EXISTS visites/)
    expect(appels[1].sql).toMatch(/ON CONFLICT \(jour, chemin, pays, referent, appareil, robot\) DO UPDATE SET vues = vues \+ 1/)
    expect(appels[1].valeurs).toEqual(['2026-11-22', '/methode/', 'FR', 'google.com', 'mobile', 0])
  })
  it('pays absent ou invalide : « XX »', () => {
    const r = new Request('https://lebilletdecoupe.fr/', { headers: { 'User-Agent': FIREFOX, 'Accept-Language': 'fr' } })
    expect(ligne(r).pays).toBe('XX')
  })
  it('schéma : aucune colonne IP, user-agent, identifiant ni heure', () => {
    const sql = readFileSync(new URL('../../deploy/cloudflare/audience.sql', import.meta.url), 'utf8')
    const colonnes = [...sql.matchAll(/^\s+([a-z_]+) (TEXT|INTEGER)/gm)].map((m) => m[1])
    expect(colonnes).toEqual(['jour', 'chemin', 'pays', 'referent', 'appareil', 'robot', 'vues'])
  })
  it('purge au-delà de 13 mois', () => expect(PURGE).toContain("'-13 months'"))
})

describe('Worker du site', () => {
  const assets = { fetch: async () => html() }

  it('sans liaison AUDIENCE : page servie, rien de différé', async () => {
    const ctx = contexte()
    const r = await site.fetch(navigation('https://lebilletdecoupe.fr/'), { ASSETS: assets }, ctx)
    expect(r.status).toBe(200)
    expect(await r.text()).toBe('<!doctype html>')
    expect(ctx.promesses).toHaveLength(0)
  })

  it('D1 en échec : page servie quand même, erreur avalée', async () => {
    const { db } = base(true)
    const ctx = contexte()
    const r = await site.fetch(navigation('https://lebilletdecoupe.fr/'), { ASSETS: assets, AUDIENCE: db }, ctx)
    expect(r.status).toBe(200)
    expect(ctx.promesses).toHaveLength(1)
    await expect(Promise.all(ctx.promesses)).resolves.toBeDefined()
  })

  it('D1 qui lève dès prepare : page servie', async () => {
    const db = { prepare: () => { throw new Error('liaison cassée') } } as unknown as D1Like
    const ctx = contexte()
    const r = await site.fetch(navigation('https://lebilletdecoupe.fr/'), { ASSETS: assets, AUDIENCE: db }, ctx)
    expect(r.status).toBe(200)
    await expect(Promise.all(ctx.promesses)).resolves.toBeDefined()
  })

  it('la réponse des fichiers statiques est renvoyée telle quelle (en-têtes de _headers compris)', async () => {
    const reponse = html()
    const { db } = base()
    const r = await site.fetch(navigation('https://lebilletdecoupe.fr/'), { ASSETS: { fetch: async () => reponse }, AUDIENCE: db }, contexte())
    expect(r).toBe(reponse)
  })

  it('compter sans base : sans effet', () => {
    const ctx = contexte()
    compter(navigation('https://lebilletdecoupe.fr/'), html(), undefined, ctx)
    expect(ctx.promesses).toHaveLength(0)
  })

  it('wrangler.toml : base D1 à activer ou activée avec un vrai identifiant ; le Worker ne passe pas sur assets, données ni sw.js', () => {
    const conf = readFileSync(new URL('../../deploy/cloudflare/wrangler.toml', import.meta.url), 'utf8')
    expect(conf).toMatch(/^main = "site.ts"$/m)
    expect(conf).toMatch(/^run_worker_first = \["\/\*", "!\/assets\/\*", "!\/data\/\*", "!\/sw\.js"\]$/m)
    if (/^binding = "AUDIENCE"$/m.test(conf)) {
      // activée : identifiant collé, plus de marqueur
      expect(conf).toMatch(/^database_id = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"$/m)
    } else {
      expect(conf).toMatch(/^# binding = "AUDIENCE"$/m)
      expect(conf).toContain('COLLER_ICI_L_IDENTIFIANT_DE_LA_BASE')
    }
  })
})

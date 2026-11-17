// Monte la page (index.html) dans happy-dom et sert les fixtures à la place du réseau.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { vi } from 'vitest'

const RACINE = process.cwd()
const FIXTURES = join(RACINE, 'tests', 'fixtures')
export const requetes: string[] = []

export function monterPage() {
  const html = readFileSync(join(RACINE, 'index.html'), 'utf8')
  const corps = /<body>([\s\S]*)<\/body>/.exec(html)![1].replace(/<script[\s\S]*?<\/script>/g, '')
  document.body.innerHTML = corps
  vi.stubGlobal('fetch', async (url: string) => {
    requetes.push(String(url))
    const u = String(url)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = join(FIXTURES, u.split('?')[0])
    if (!existsSync(f)) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })) as never
  window.scrollTo = (() => {}) as never
}

export const attendre = (ms = 0) => new Promise((r) => setTimeout(r, ms))

export async function attendreQue(cond: () => boolean, delai = 20000) {
  const debut = Date.now()
  while (!cond()) {
    if (Date.now() - debut > delai) throw new Error('délai dépassé')
    await attendre(20)
  }
}

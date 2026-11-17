import './styles.css'
import { afficher } from './routeur'
import { ROUTES } from './routes'

export { ROUTES }

function demarrer() {
  const main = document.getElementById('contenu') as HTMLElement
  const plus = document.querySelector<HTMLButtonElement>('#bouton-plus')
  const feuille = document.getElementById('feuille-plus')
  const fermer = () => {
    plus?.setAttribute('aria-expanded', 'false')
    if (feuille) feuille.hidden = true
  }
  plus?.addEventListener('click', () => {
    const ouvert = plus.getAttribute('aria-expanded') === 'true'
    plus.setAttribute('aria-expanded', String(!ouvert))
    if (feuille) feuille.hidden = ouvert
    if (!ouvert) feuille?.querySelector<HTMLElement>('a')?.focus()
  })
  feuille?.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('a')) fermer()
  })
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && feuille && !feuille.hidden) {
      fermer()
      plus?.focus()
    }
  })
  window.addEventListener('hashchange', () => {
    fermer()
    afficher(ROUTES, main)
  })
  afficher(ROUTES, main, location.hash, false)
}

if (typeof document !== 'undefined' && document.getElementById('contenu')) demarrer()

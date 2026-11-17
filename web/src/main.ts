import './styles.css'
import { afficher, type Route } from './routeur'

export const ROUTES: Route[] = [
  { chemin: '/', titre: 'Ton salaire', charger: () => import('./ecrans/saisie') },
  { chemin: '/paie', titre: 'Ce que tu finances', charger: () => import('./ecrans/paie') },
  { chemin: '/etat', titre: 'Sur 100 € dépensés par l’État', charger: () => import('./ecrans/etat') },
  { chemin: '/detail', titre: 'Le détail du budget de l’État', charger: () => import('./ecrans/detail') },
  { chemin: '/concret', titre: 'Concrètement', charger: () => import('./ecrans/concret') },
  { chemin: '/beneficiaires', titre: 'Qui reçoit l’argent', charger: () => import('./ecrans/beneficiaires') },
  { chemin: '/realisations', titre: 'Ce qui a été fait', charger: () => import('./ecrans/realisations') },
  { chemin: '/vie-politique', titre: 'Vie politique', charger: () => import('./ecrans/viepolitique') },
  { chemin: '/recettes', titre: 'Les recettes', charger: () => import('./ecrans/recettes') },
  { chemin: '/methode', titre: 'Méthode et sources', charger: () => import('./ecrans/methode') },
  { chemin: '/mentions', titre: 'Mentions légales et confidentialité', charger: () => import('./ecrans/mentions') },
]

function demarrer() {
  const main = document.getElementById('contenu') as HTMLElement
  const bouton = document.querySelector<HTMLButtonElement>('.menu-bouton')
  const nav = document.getElementById('navigation')
  bouton?.addEventListener('click', () => {
    const ouvert = bouton.getAttribute('aria-expanded') === 'true'
    bouton.setAttribute('aria-expanded', String(!ouvert))
    nav?.classList.toggle('ouverte', !ouvert)
  })
  nav?.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('a') && bouton) {
      bouton.setAttribute('aria-expanded', 'false')
      nav.classList.remove('ouverte')
    }
  })
  window.addEventListener('hashchange', () => afficher(ROUTES, main))
  afficher(ROUTES, main, location.hash, false)
}

if (typeof document !== 'undefined' && document.getElementById('contenu')) demarrer()

# Procédure du coordinateur d'une session de renfort (vague 3)

Tu ne fais que lancer et suivre des agents sur les missions de ta liste, sur cette machine. La session principale fusionnera leurs branches. Français, pas de tiret long, jamais de push sur main, aucune action hors de cette procédure.

1. Clone et accès en écriture
   git clone https://github.com/MoonEyes/Ou-vont-mes-impots ~/ovmi && cd ~/ovmi && git fetch origin base/vague3 coordination/vague3
   Test : git push origin refs/remotes/origin/base/vague3:refs/heads/agent/test-acces-<session> puis git push origin --delete agent/test-acces-<session>
   Si c'est refusé : utilise une fois l'outil add_repo (owner MoonEyes, repo Ou-vont-mes-impots, access push), puis réessaie. Si c'est encore refusé : ne lance aucun agent et passe directement à l'étape 6 avec l'erreur exacte.
2. Coordination : git -C ~/ovmi worktree add --detach ~/coord refs/remotes/origin/coordination/vague3
   Règles des agents : ~/coord/coordination/REGLES.md ; missions : ~/coord/coordination/missions/
3. Dépendances, une seule fois : pip install -r ~/ovmi/requirements.txt (ajoute --break-system-packages si pip le demande) ; cd ~/ovmi/web && npm ci
4. Pour chaque mission qNN_<nom> de ta liste, dans l'ordre :
   git -C ~/ovmi worktree add ~/wt/<nom> -b agent/<nom> refs/remotes/origin/base/vague3
   ln -s ~/ovmi/web/node_modules ~/wt/<nom>/web/node_modules
   Puis lance un agent en arrière-plan (outil Agent, description « <nom> ») avec exactement ce texte, adapté :
   « Ta mission complète est dans ~/coord/coordination/missions/qNN_<nom>.md et tes règles dans ~/coord/coordination/REGLES.md (le dossier de coordination est ~/coord) : lis les deux en entier en premier. Ton dossier de travail à toi est ~/wt/<nom>, sur la branche agent/<nom> : travaille uniquement dedans (et dans /tmp), commite et pousse cette branche. »
   Lance autant d'agents à la fois que ta limite le permet ; lance les suivants dès qu'une place se libère. Vérifie l'espace disque (df -h ~) avant chaque nouveau dossier : sous 8 Go libres, attends qu'un agent finisse et supprime son dossier (git -C ~/ovmi worktree remove --force ~/wt/<nom>) une fois sa branche poussée.
5. Suivi : à la fin de chaque agent, vérifie git ls-remote origin agent/<nom>. Si des commits de son dossier n'ont pas été poussés, pousse-les (git -C ~/wt/<nom> push -u origin agent/<nom>). Ne modifie jamais le travail d'un agent.
6. Rapport : quand toutes les missions sont finies (ou à l'étape 1 en cas d'échec), écris ~/rapport.md : une ligne par mission (nom, branche, hash, résumé en une phrase, statut GitHub Actions via gh run list --branch agent/<nom> -L 1) et pousse-le sur une branche orpheline :
   rm -rf ~/rapport-git && mkdir ~/rapport-git && cd ~/rapport-git && git init -q && cp ~/rapport.md . && git add rapport.md && git -c user.name=MoonEyes -c user.email=14891700+MoonEyes@users.noreply.github.com commit -qm "Rapport <session>" && git push https://github.com/MoonEyes/Ou-vont-mes-impots HEAD:refs/heads/rapport/<session>
   Termine par ce même rapport comme réponse finale.

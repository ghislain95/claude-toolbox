# background-tasks

Mod Claude Code actif dans tous les projets : le panneau « En arrière-plan ».

- **Services** : les commandes que Claude a laissées tourner en arrière-plan (serveur de dev, watcher), avec leur port quand la commande le dit, la commande et depuis quand. La liste est mise à jour à chaque fin de tour de Claude.
- **Workflows** : les runs du projet des trois derniers jours. Un run en cours montre son but, une barre de progression, ses phases (faites, en cours avec ses agents, à venir) et, pour chaque agent, son modèle, ses tokens et son temps. Les runs terminés tiennent sur une ligne.
- **Agents de cette session** : ceux qui travaillent encore, avec modèle, tokens et dernier outil.

Le panneau s'ouvre tout seul au démarrage de chaque session, pour que les tâches se voient d'un coup d'œil, sauf dans un projet OpenSpec, où le cockpit les affiche dans sa section « En arrière-plan » (l'app range deux panneaux en onglets, elle ne les empile pas). Si tu le fermes (croix ou `/arriere-plan`), il reste fermé dans les sessions suivantes ; `/arriere-plan` le rouvre et rétablit l'ouverture automatique. La pastille « N en arrière-plan » de la bande `session-hud` y mène aussi (« Tout afficher »). Un run qui se termine l'annonce une fois (toast et notification).

Le panneau ne se redessine qu'au rafraîchissement (30 s) et en fin de tour, et seulement si quelque chose a changé : jamais à chaque appel d'outil des agents.

Code partagé : `hooks/shared/` est une copie de `mods/shared/` (`mods/scripts/sync-shared.sh`) ; on modifie l'original.

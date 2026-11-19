# session-hud

Mod Claude Code actif dans tous les projets : une ligne au-dessus du prompt.

De gauche à droite : un point qui pulse quand Claude travaille, l'anneau et le pourcentage du contexte (vert, puis ambre à 60 %, rouge à 85 %), le coût de la session ou, sans coût, la limite d'usage la plus haute, la durée de la session, le nombre d'appels d'outils et d'erreurs, le modèle. À droite, une pastille « N en arrière-plan » quand des tâches tournent encore (services, workflows, agents) ; un clic déplie leur liste au-dessus de la bande, et « Tout afficher » ouvre le panneau du mod `background-tasks` s'il est installé.

La bande ne se redessine qu'au rafraîchissement (30 s) et en fin de tour, jamais à chaque appel d'outil. Dans le terminal, elle tient sur une ligne de texte.

La bande se pose directement dans le cadre que l'app dessine au-dessus du prompt, sans fond à elle, et reste aussi fine qu'une ligne de texte ; la pastille des tâches est ocre.

Sur desktop, le mod sait aussi poser un fond animé derrière la conversation (trois halos flous qui dérivent lentement et un grain léger, clair ou sombre selon le thème de l'app). Il est **éteint par défaut** : le look Galet se pose sur le fond de l'app. `/fond` l'allume ou l'éteint, et le choix est gardé d'une session à l'autre. Le mouvement s'arrête quand le système demande de réduire les animations.

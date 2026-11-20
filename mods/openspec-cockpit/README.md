# openspec-cockpit (v0.15)

Mod Claude Code qui ajoute un panneau OpenSpec à l'app desktop. Il s'active seul dans tout projet qui a `openspec/` ou `.claude/passation/`, et reste muet ailleurs. Ce qui dépend d'un outil du projet n'apparaît que si le projet l'a (voir « Selon le projet »).

Depuis la v0.14, le mod ne fait plus que le panneau, les portes du cycle, la ligne de statut et l'outil `status`. Le reste a sa place dans d'autres mods du même dépôt :
- les cartes du fil, les cartes d'outils, le spinner et la consigne de format sont dans `conversation-cards` ;
- la bande au-dessus du prompt et le fond animé sont dans `session-hud` ;
- le panneau séparé des agents, workflows et services est dans `background-tasks` ; le cockpit en affiche le contenu dans sa propre section.

Thème : Galet (voir `../README.md`), en clair ou en sombre selon le thème de l'app : surfaces pastel arrondies sans trait, aucun dégradé ni emoji. Nord, Argile et `/cockpit-theme` ont disparu.

## Le panneau (barre latérale droite, ouvert seul)

De haut en bas. Chaque section se replie au clic sur son titre (la flèche et le titre forment un seul bouton), et cet état est mémorisé.

1. **Tête** : un anneau fin rempli au prorata des tâches du change (« 50% »), le nom du change, son étape et « n tâches sur m », la branche. Dessous, la **frise des 7 étapes** du cycle en segments arrondis : faits pleins, l'étape en cours à moitié, la suite en gris.
2. **Prochaine action** : la règle du cycle appliquée à l'état réel, avec un bouton.
   - Graph périmé : `graphify update .`.
   - Apply : « groupe N, x sur y » et `/opsx:apply`.
   - Clôture : review, puis verify avec la copie du commit, puis archive.
   - Post-archive : le rituel.

   La carte prend la teinte de son état (ocre en cours, miel ou rose quand une porte retient, sauge quand tout est fait) ; les pastilles des portes sont dessous.
3. **En arrière-plan** : une ligne par chose qui tourne : un service avec son port, un workflow avec sa phase, ses agents, sa durée et une barre douce dessous, un agent de la session, les deux derniers runs terminés. Le détail (phases, modèle, tokens) reste dans le panneau du mod `background-tasks`. Comme l'app range deux panneaux en onglets au lieu de les empiler, le cockpit montre ce résumé pour qu'on voie tout d'un coup d'œil. Dans un projet OpenSpec, le panneau séparé ne s'ouvre donc plus tout seul.
4. **Progression par groupe** : une ligne par groupe de `tasks.md`, avec une barre douce. Les groupes finis sont en sauge pâle, le groupe courant est surligné. Aucun bouton dans cette liste.
5. **Décisions** : prises, choix d'agents « à confirmer » et « ouvertes », chacune avec sa pastille. Elles sont lues dans `verification/owner-points.md` et dans la dernière passation. Un clic préremplit « Sur « … » : ».
6. **Post-archive** : la checklist du rituel.
7. **Passation** : les étapes et le bouton [Reprendre].

## Selon le projet

- **graphify** : la pastille du graph, l'alerte avant `/opsx:new` et `/opsx:apply`, le bouton `graphify update .` et l'étape « graph rafraîchi » du rituel n'existent que si le projet a un `graphify-out/` ou un skill `.claude/skills/graphify`.
- **Backlog** : l'étape « backlog → ✅ SHIPPED » du rituel cherche un fichier `*backlog*.md` à la racine, puis jusqu'à trois niveaux sous `docs/` (sauf `docs/archive`). Sans fichier, l'étape disparaît.
- **Notifications** : leur titre est le nom du dossier du projet.

## Commandes

- `/cockpit` ouvre ou ferme le panneau.
- `/ou-en-suis-je` donne le résumé texte.
- `/cockpit-toggle [statut|portes|panneau] [on|off]` coupe une brique ; le choix est mémorisé.

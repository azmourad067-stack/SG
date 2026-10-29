# simplegagnant : pronostics « Simple Gagnant » orientés valeur

Outil Python qui ne cherche pas le gagnant le plus probable. Il cherche les chevaux
**dont la cote paie plus que leur probabilité réelle de victoire**, et il ne joue
rien quand il n'en trouve pas.

## Résultat honnête (à lire en premier)

| Jeu de données | Courses testées hors échantillon | Paris du modèle | ROI modèle (IC 90 %) | Favori systématique | Hasard |
|---|---|---|---|---|---|
| PMU France, 29/08 → 27/10/2026, décision à T-15 min, rapports réels | 1 371 | 99 | +2,6 % [−54 ; +75] | −15,8 % | −19,7 % |
| Hong Kong 1997-2005 (6 320 courses, cote finale = majorant optimiste) | 4 825 | 1 | — | −13,7 % | −23,7 % |

**Aucune rentabilité robuste n'est démontrée.** Sur le PMU, le +2,6 % repose sur
99 paris : l'intervalle de confiance va de −54 % à +75 %, c'est indiscernable du
hasard. Surtout, les probabilités du modèle ne battent pas les cotes brutes hors
échantillon : l'écart de log-vraisemblance est de +0,0002 par course, avec un
IC 90 % de [−0,005 ; +0,005]. Aucun des 22 « patterns » testés ne survit à la
validation hors échantillon. Sur 8 ans de Hong Kong, le modèle colle au marché
et ne trouve presque jamais de valeur.

Ce n'est pas un défaut du code. Un test sur données simulées, où un avantage
existe réellement, vérifie que le moteur le détecte : ses probabilités y battent
le marché hors échantillon (`tests/test_moteur.py`). Simplement, avec les variables disponibles et ces
historiques courts, le marché est déjà efficient. Il faut environ **25 000 paris**
pour distinguer un ROI de +5 % de zéro à la cote moyenne jouée (≈ 17).

Rapports détaillés : `resultats/pmu_france/rapport.html` et `resultats/hongkong/rapport.html`.

## Sélection des courses du jour (`selection_courses.py`)

Script court, à lancer après `entrainer` :

1. Il filtre le programme PMU : au moins N partants, et une part de victoires de non-favoris
   suffisante sur les N dernières courses de l'hippodrome.
2. Pour chaque course retenue, il affiche :
   - les chevaux sous-cotés par le marché ;
   - le non-favori le plus probable ;
   - le pari à valeur éventuel.

```bash
python selection_courses.py --historique donnees/pmu.csv --modele modele.pkl \
    --min-partants 10 --n-dernieres 3 --taux-non-favoris 0.30
```

La « prédiction hors favori » est le non-favori que le modèle juge le plus probable. Ce n'est pas
une recommandation de pari : seule la ligne « PARI À VALEUR » en est une.

## Version spécialisée PLAT

Option `--plat` (ligne de commande) ou « Plat uniquement » (interface Streamlit), réglages dans `config_plat.json`.

**Ce qu'elle ajoute** (module `simplegagnant/plat.py`, variables connues avant la course) :

- **Corde** : rang de la stalle parmi les partants, renforcé en sprint (≤ 1 400 m) et dans les
  grands pelotons (≥ 14).
- **Poids** : poids relatif en handicap, décharge d'apprenti (poids porté < poids attribué),
  variation de poids et de valeur handicap depuis la dernière sortie.
- **Signaux d'intention** : oeillères posées pour la 1re fois ou retirées, changement de jockey.
- **Forme et carrière** : forme en plat (musique filtrée sur les courses de plat), taux de
  victoire et de place en carrière.
- **Corrections du marché selon le rang de cote** : favori, 2e à 5e choix, taille du peloton.
  Le modèle apprend sur le passé de combien corriger le favori ou les 2e-5e choix ; la
  régularisation le ramène aux cotes s'il n'y a pas de preuve.
- **Plafond de cote appris** : les tranches de grosses cotes où le marché surestime les chevaux
  sont exclues. Sur le PMU plat : **25** (les chevaux cotés de 25 à 40 gagnent 34 % de moins que
  leur cote ne l'annonce).
- **Patterns plat testés hors échantillon** : corde en sprint, poids en handicap, décharge,
  oeillères, changement de jockey, 2e-5e favori en grand peloton, etc.

Les historiques de jockeys et de chevaux sont calculés sur toutes les disciplines, puis seules les
courses de plat servent au modèle et aux paris.

**Votre constat est juste, mais il ne suffit pas.** Sur les 743 courses de plat PMU, le favori ne
gagne que 28 % des courses. Le marché le sait :

- le favori est légèrement **surjoué** (0,92 victoire réelle pour 1 attendue) ;
- les 2e à 5e choix sont un peu **sous-estimés** (1,08 à 1,13), de façon stable sur les deux moitiés
  de la période ;
- mais jouer systématiquement chacun de ces rangs reste perdant, de −16 % à −21 %. L'avantage
  d'environ 10 % ne couvre ni le prélèvement d'environ 16 % ni la baisse des cotes de ces chevaux
  dans les dernières minutes.

**Résultats du backtest plat** (hors échantillon) :

| Jeu | Courses testées | Paris | ROI modèle (IC 90 %) | Le modèle bat-il les cotes ? | Favori systématique |
|---|---|---|---|---|---|
| PMU plat, 19/09 → 27/10/2026 | 525 | 106 | +8,3 % [−48 ; +65] | **Non : il fait moins bien** (−0,014 par course, IC [−0,025 ; −0,003]) | −15,9 % |
| Hong Kong 1997-2005 (plat, cote finale) | 4 825 | 7 | — | Non (−0,0008, IC [−0,003 ; +0,001]) | −13,7 % |

Le +8,3 % du PMU plat est du hasard. Le modèle plat fait **moins bien** que les cotes brutes : avec
34 variables et seulement 200 à 700 courses d'entraînement, il surajuste. Il lui faut un historique
plus long, collecté avec `construire-donnees pmu`, qui récupère poids, décharge, catégorie de
course, terrain, changement de jockey et carrière. Les données de démonstration n'ont le poids et
la valeur que pour 42 % des partants, et aucun pour la période de test. Aucun pattern plat ne
survit à la validation.

```bash
python -m simplegagnant backtest donnees/pmu.csv --plat --sortie resultats/plat
python -m simplegagnant patterns donnees/pmu.csv --plat
python -m simplegagnant entrainer donnees/pmu.csv --plat --modele modele_plat.pkl
python -m simplegagnant pronostiquer --modele modele_plat.pkl --historique donnees/pmu.csv --bankroll 500
```

Le modèle entraîné avec `--plat` ne pronostique que les courses de plat. Rapports :
`resultats/pmu_plat/rapport.html` et `resultats/hongkong_plat/rapport.html`.

## Principe

1. **Probabilités** : modèle en deux étapes (méthode de Benter, 1994).
   - Étape 1, « fondamental » : un logit conditionnel par course sur la musique, la
     ferrure, la corde, les historiques du jockey, de l'entraîneur et du cheval, etc.,
     **sans les cotes**.
   - Étape 2, « combinaison » : le marché (log de la probabilité implicite) sert de
     point de départ. Le modèle apprend combien s'en écarter, sur une période plus
     récente que l'étape 1. La régularisation ramène vers les cotes tant que les
     données ne prouvent pas mieux.
2. **Valeur** : `EV = p_modèle × rapport_attendu − 1`.
   - Le rapport attendu corrige la cote de décision de la dérive habituelle jusqu'au
     départ, apprise sur l'historique.
   - Au PMU, les gagnants à 4-10 paient en médiane environ 15 % de moins que la cote
     T-15.
3. **Sélection** : un cheval est retenu si :
   - `cote_min ≤ cote ≤ cote_max` ;
   - `p ≥ proba_min` ;
   - `EV ≥ marge_ev` (10 % par défaut) ;
   - et au plus un cheval par course. Sinon, on ne joue pas.
4. **Exclusion des favoris sous-payés** : `cote_min` est **appris à chaque pli** sur
   les seules données d'entraînement. On exclut les tranches de petites cotes où le
   marché ne sous-estime pas les chevaux (victoires réelles / attendues ≤ 1).
   - Sur le PMU : seuil **3** dans chaque pli. Contrôle sur la période de test : favoris
     à moins de 2, rapport 0,88 ; de 2 à 3, 0,89 ; ROI de −9 % et −17 %.
   - Le seuil est borné entre 2 et 6, modifiable dans la configuration.
5. **Mise** : deux méthodes, comparées dans le backtest.
   - Mise fixe.
   - Kelly fractionné : ¼ de Kelly, au plus 2 % de la bankroll par cheval et 4 % par course.

## Installation

Python ≥ 3.10, avec `pandas`, `numpy`, `scipy` et `matplotlib`. `tabulate` et
`markdown` servent aux rapports.

```bash
pip install pandas numpy scipy matplotlib tabulate markdown
cd pronostic-simple-gagnant
python -m unittest discover -s tests -v      # 13 tests, dont les tests anti-fuite
```

## Interface graphique (Streamlit)

```bash
pip install -r requirements.txt
streamlit run app.py          # depuis le dossier pronostic-simple-gagnant
```

Le navigateur s'ouvre sur trois onglets :

- **Pronostics** : courses du jour via l'API PMU, ou fichier de partants. Affiche les
  paris à valeur et leur mise Kelly.
- **Backtest** : lance le backtest et affiche le verdict, les stratégies et les graphiques.
- **Données** : contrôle de l'historique.

Les paramètres (marge, cotes min/max, bankroll, Kelly) se règlent dans la barre latérale.

## Utilisation en ligne de commande

### 1. Constituer l'historique

**A. Depuis l'API PMU** (à lancer chez vous ; elle était inaccessible depuis l'environnement de développement) :

```bash
python -m simplegagnant construire-donnees pmu --debut 2024-01-01 --fin 2026-10-26 \
    --specialisation OFFLINE --sortie donnees/pmu.csv
```

- **Débit** : 1 requête par seconde ; les réponses sont mises en cache dans `cache_pmu/`.
  Comptez environ 3 à 4 requêtes par course, soit environ 20 h pour un an de courses.
- **Masses de paris** : `OFFLINE` correspond aux points de vente, `INTERNET` à la masse
  séparée de pmu.fr. Choisissez celle où vous jouez réellement.
- **Cote de décision** : sur l'historique, c'est la cote de **référence**, relevée
  environ 30 min avant le départ. La dernière cote de l'API est la cote finale,
  postérieure au départ : l'utiliser serait une fuite.

**B. Relevés de cotes en direct** : c'est le meilleur historique pour décider à T-15 ou
T-5. Planifiez la commande suivante toutes les 5 minutes (cron, ou Planificateur de
tâches sous Windows) :

```bash
python -m simplegagnant releve-cotes --fichier releves_cotes.csv
```

Puis : `construire-donnees pmu ... --releves releves_cotes.csv --minutes-avant 15`.

**C. Vos propres fichiers** (Aspiturf, export d'abonnement, etc.) : produisez un CSV au
format décrit dans `simplegagnant/schema.py`.

- **Colonnes obligatoires** : `course_id`, `date`, `num`, `cheval`, `cote_decision`.
- **Pour le backtest** : `gagnant` et `rapport_gagnant`.
- **Colonnes optionnelles** : musique, jockey, entraîneur, ferrure, corde, poids,
  `cote_t30`, `cote_t90`, etc.

**D. Jeux fournis**

- `donnees/pmu_turf_engine.csv` : vraies courses PMU, reconstituées à partir des
  archives publiques du dépôt `Moriah12783/turf-engine`. L'adaptateur est
  `adapters/turf_engine.py`.
- `donnees/hongkong_1997_2005.csv` : jeu public « hkracing ».

### 2. Backtester

```bash
python -m simplegagnant backtest donnees/pmu.csv --sortie resultats/mon_backtest
python -m simplegagnant config-defaut --sortie config.json   # puis modifier, et :
python -m simplegagnant backtest donnees/pmu.csv --config config.json --sortie resultats/v2
```

Le rapport `rapport.md` / `rapport.html` contient :

- le verdict ;
- la comparaison avec le favori systématique, le hasard, « tous les chevaux de la
  plage » et le « marché seul » : ROI, IC bootstrap, profit, nombre de paris, taux de
  réussite, rapport moyen des gagnants, drawdown, série perdante ;
- le test « le modèle bat-il le marché ? » ;
- la justification du seuil de cote ;
- la dérive des cotes ;
- une grille de sensibilité, descriptive seulement ;
- une validation exploration / confirmation ;
- les patterns.

### 3. Pronostiquer de nouvelles courses

```bash
python -m simplegagnant entrainer donnees/pmu.csv --modele modele.pkl          # chaque semaine
python -m simplegagnant pronostiquer --modele modele.pkl --historique donnees/pmu.csv \
    --bankroll 500 --sortie pronos_du_jour.csv           # interroge l'API PMU pour aujourd'hui
# ou, avec vos propres partants :
python -m simplegagnant pronostiquer --modele modele.pkl --historique donnees/pmu.csv \
    --partants partants.csv --bankroll 500
```

Exemple de sortie (jeu PMU, courses du 27/10/2026 traitées comme « à venir ») :

```
R3C1_27102026_LYON-PARILLY : aucun pari (pas de valeur suffisante)
R3C5_27102026_LYON-PARILLY : n°12 MY MILLION D'ANSY — cote 24, p modèle 4.4 % vs marché 3.5 %, EV +18 %, mise Kelly 0.87
R1C1_27102026_DEAUVILLE : n°10 BREAK DANCE — cote 11, p modèle 11.9 % vs marché 7.6 %, EV +29 %, mise Kelly 3.71
```

Le CSV détaille pour chaque partant :

- la probabilité du marché et celle du modèle ;
- l'EV et la décision ;
- la raison du refus, par exemple « exclu : cote < cote_min (favori sous-payé) ».

### 4. Chercher des patterns

```bash
python -m simplegagnant patterns donnees/pmu.csv --part-test 0.4 --alpha 0.10
```

Une liste de situations est fixée à l'avance (cote en baisse, déferré, 2e ligne en
autostart, jockey sous-coté…). Pour chacune :

- sur la période ancienne, on calcule le rapport victoires réelles / attendues et sa
  significativité, avec la correction de Benjamini-Hochberg pour les tests multiples ;
- elle n'est validée que si elle reste sous-cotée **et** rentable sur la période récente.

## Garde-fous contre le surajustement et les fuites

- **Validation chronologique** (walk-forward) : le modèle est ré-entraîné à chaque pli
  sur le passé uniquement. Les statistiques de jockey, d'entraîneur et de cheval
  n'utilisent que les jours précédents (testé).
- **Décision et gain** : la décision se prend sur la cote disponible avant le départ. Le
  gain est calculé sur le **rapport réellement payé**, prélèvement et arrondi inclus.
- **Hyperparamètres** : pénalités, marge et seuils sont fixés a priori, jamais optimisés
  sur le test. La grille de sensibilité est affichée mais pas utilisée pour choisir.
- **Intervalles de confiance** : bootstrap par **jour**, car les courses d'un même jour
  sont corrélées.
- **Coûts** : `commission_gains` pour une commission supplémentaire sur gains,
  `remise_mises` pour un éventuel cashback de fidélité. Les deux sont à 0 par défaut.

## Limites connues

- **Historique français** : il est court (2 mois) ici. Un vrai verdict demande plusieurs
  années, à collecter avec la commande `pmu`, et surtout des relevés de cotes à T-5 ou
  T-2, car l'information se concentre dans les dernières minutes.
- **Propre mise** : elle n'est pas modélisée. Une mise de 100 € fait baisser le rapport
  sur les petites masses (pmu.fr : masse médiane d'environ 24 k€ en Simple Gagnant).
- **Prélèvement** : il est intégré via les rapports réels. Le taux exact reste
  contradictoire selon les sources :
  - ANJ : 84,6 % de retour en points de vente depuis le 6 octobre 2025 ;
  - source secondaire : 14,05 % de prélèvement en points de vente et 11,8 % en ligne.
- **Données PMU** : elles sont protégées. Usage personnel uniquement, à faible débit,
  sans redistribution.
- **Avertissement** : les paris comportent un risque de perte. Rien ici n'est un conseil
  financier. Le résultat attendu d'un parieur est négatif tant qu'un avantage n'a pas été
  démontré sur des milliers de paris réels.

## Organisation du code

```
simplegagnant/
  schema.py      format canonique + validation (overround, non-partants)
  musique.py     lecture de la musique PMU
  features.py    variables sans fuite
  clogit.py      logit conditionnel (softmax par course, L2, offset marché)
  model.py       modèle deux étapes
  value.py       EV, sélection, Kelly
  backtest.py    walk-forward, simulations, références, métriques, diagnostics
  patterns.py    recherche de patterns + validation hors échantillon
  report.py      rapport Markdown/HTML + graphiques
  pronostic.py   entraînement final + pronostics
  cli.py         ligne de commande
  adapters/      pmu_api.py (API turfinfo), turf_engine.py, hkracing.py
tests/           tests unitaires (anti-fuite, gains, sélection, lecture API)
```

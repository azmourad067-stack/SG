# Rapport de backtest — PMU France (août–oct. 2026, cote T-15)

## Verdict

**Pas de rentabilité démontrée.** Le ROI hors échantillon du modèle est de +2.6 % sur 99 paris, avec un intervalle de confiance à 90 % de [-54.2 ; 75.2] % : la vraie valeur peut aussi bien être fortement négative que positive. L'écart de log-vraisemblance du modèle par rapport aux cotes brutes est de +0.0001 par course (IC 90 % [-0.0049 ; +0.0052]) : le modèle n'apporte pas d'information prouvée au-delà du marché. Pour distinguer un ROI de +5 % de zéro à la cote moyenne jouée, il faudrait environ 24 986 paris.



## Données

- Période : 2026-08-29 → 2026-10-27 (58 jours de courses)
- 1939 courses, 22572 partants
- Disciplines : {'TROT_ATTELE': 827, 'PLAT': 743, 'TROT_MONTE': 150, 'HAIES': 121, 'STEEPLE': 88, 'CROSS': 10}
- Somme médiane des 1/cote par course : 1.185 → taux de retour implicite ≈ 84.4 % (prélèvement + arrondi ≈ 15.6 %)

## Protocole (aucune information du futur)

- Validation chronologique par plis de 7 jours ; fenêtre croissante, au moins 21 jours d'entraînement avant le premier test.
- 6 plis ; période de test : 2026-09-19 → 2026-10-27 (1371 courses jamais vues par le modèle au moment de la prédiction).
- Dans chaque pli : étape 1 (modèle fondamental, sans cotes) entraînée sur la partie ancienne de la fenêtre, étape 2 (combinaison avec le marché) sur les 30 % les plus récents.
- Décision prise avec `cote_decision` ; gain calculé avec le **rapport réellement payé** (prélèvement inclus). Le rapport attendu tient compte de la dérive habituelle des cotes entre la décision et le départ.
- Disciplines : toutes ; profil de variables : general.
- Sélection : cote ∈ [cote_min apprise dans chaque pli sur ses seules données d'entraînement (3) ; 40], EV ≥ 10 %, p ≥ 0.03, au plus 1 cheval par course. Une course sans valeur n'est pas jouée.
- Remise sur mises : 0 % ; commission sur gains : 0 %.

## Comparaison des stratégies (mêmes courses de test)

![Profit cumulé](profit_cumule.png)

| strategie                               |   paris |   courses_jouees |   profit |   roi_pct | roi_ic90_pct                |   proba_roi_negatif |   taux_reussite_pct |   cote_moy_paris |   rapport_moy_gagnants |   drawdown_max |   serie_perdante_max |   bankroll_finale |   drawdown_max_pct |
|:----------------------------------------|--------:|-----------------:|---------:|----------:|:----------------------------|--------------------:|--------------------:|-----------------:|-----------------------:|---------------:|---------------------:|------------------:|-------------------:|
| Modèle value — mise fixe                |      99 |               99 |     2.6  |      2.63 | [-54.2 ; 75.2]              |               0.487 |               10.1  |            17.26 |                  10.16 |          44    |                   44 |            nan    |             nan    |
| Modèle value — Kelly 0.25               |      99 |               99 |    -3.26 |     -7.13 | [-42.6 ; 47.9]              |               0.607 |               10.1  |            17.26 |                  10.16 |          20.41 |                   44 |             96.74 |              19.62 |
| Marché seul value — mise fixe           |      65 |               65 |   -21.1  |    -32.46 | [-83.2 ; 44.7]              |               0.785 |                7.69 |            16.65 |                   8.78 |          38    |                   26 |            nan    |             nan    |
| Favori systématique                     |    1371 |             1371 |  -217.1  |    -15.84 | [-22.4 ; -9.2]              |               1     |               28.37 |             3.14 |                   2.97 |         219.1  |                   21 |            nan    |             nan    |
| Tous les chevaux dans la plage de cotes |   12674 |             1371 | -1598    |    -12.61 | [-18.4 ; -6.9]              |               1     |                8.66 |            15.19 |                  10.1  |        1995.2  |                   40 |            nan    |             nan    |
| Hasard (1 cheval/course)                |    1371 |             1371 |  -225.9  |    -19.71 | [-37.9 ; 0.1] (simulations) |               0.95  |                9.92 |            21.8  |                   8.42 |         284.3  |                   54 |            nan    |             nan    |
| Hasard dans la plage de cotes           |    1371 |             1371 |  -365.6  |    -15.33 | [-32.8 ; 3.9] (simulations) |               0.911 |                8.97 |            14.97 |                   8.17 |         391.1  |                   42 |            nan    |             nan    |

Lecture : `roi_ic90_pct` est l'intervalle de confiance à 90 % du ROI (bootstrap des jours) ; `proba_roi_negatif` la proportion de rééchantillonnages où le ROI est ≤ 0. Pour le hasard, moyenne de 2000 simulations.

![Bankroll Kelly](bankroll_kelly.png)

## Le modèle bat-il le marché ?

Log-vraisemblance moyenne par course sur la période de test (plus haut = meilleures probabilités) :

| modele                         |   logvrais_par_course |
|:-------------------------------|----------------------:|
| Marché brut (1/cote normalisé) |              -2.05514 |
| Marché recalibré               |              -2.05818 |
| Fondamental seul (sans cotes)  |              -2.28147 |
| Modèle complet                 |              -2.05494 |

- Écart modèle complet − cotes brutes : **+0.0001** par course, IC 90 % [-0.0049 ; +0.0052]
- Écart modèle complet − marché recalibré : +0.0032, IC 90 % [+0.0002 ; +0.0068]

Repère : chez Benter (Hong Kong, 1994), l'apport du modèle sur le marché était modeste (pseudo-R² 0,1218 → 0,1396) et suffisait pourtant à être rentable. Un écart dont l'intervalle contient 0 signifie qu'aucun apport n'est démontré.

Coefficients du dernier pli (variables standardisées) :

```json
{
 "etape1": {
  "mus_n": -0.1186,
  "mus_inedit": -0.1166,
  "mus_reprise": -0.074,
  "mus_derniere": -0.1022,
  "mus_moy3": -0.2011,
  "mus_moy5": -0.1355,
  "mus_victoires5": 0.2164,
  "mus_top3_5": 0.0823,
  "mus_incidents5": 0.2891,
  "mus_meme_disc5": 0.0766,
  "mus_derniere_gagnee": 0.011,
  "fer_D4": 0.1122,
  "fer_DA": 0.0026,
  "fer_DP": 0.0951,
  "oeilleres_oui": 0.0104,
  "corde_rel_plat": -0.0019,
  "jk_n": 0.3476,
  "jk_ae": -0.0931,
  "jk_tv": 0.1881,
  "ent_n": 0.3336,
  "ent_ae": -0.1315,
  "ent_tv": 0.1125,
  "chv_nb_courses": 0.023,
  "chv_victoires_ant": -0.0036,
  "chv_jours_repos": 0.0467,
  "chv_pos_rel_prec": -0.1179,
  "chv_pos_rel_moy3": 0.1125,
  "chv_surplus_marche": -0.0473,
  "chv_jours_repos__manquant": -0.028,
  "chv_pos_rel_prec__manquant": -0.028,
  "chv_pos_rel_moy3__manquant": -0.028,
  "chv_surplus_marche__manquant": -0.028
 },
 "etape2": {
  "score_fondamental": 0.1878,
  "log_q (écart à 1)": -0.0485,
  "derive_t90 (std)": -0.1633,
  "derive_t30 (std)": 0.0647
 }
}
```

## Justification du seuil de cote minimale

Calculée sur les données **antérieures au premier test** (2026-08-29 → 2026-09-18), selon une règle fixée à l'avance : on exclut les tranches de petites cotes consécutives où le marché ne sous-estime pas les chevaux (réel/attendu ≤ 1).

| tranche   |   partants |   victoires |   attendues |   reel_sur_attendu |   roi_tous_pct |
|:----------|-----------:|------------:|------------:|-------------------:|---------------:|
| [1;2)     |        111 |          53 |        59   |              0.899 |           -5.1 |
| [2;3)     |        207 |          67 |        71.6 |              0.935 |          -13.7 |
| [3;4)     |        240 |          63 |        58.4 |              1.08  |           -4   |
| [4;6)     |        539 |         105 |        91.6 |              1.146 |          -11.3 |
| [6;10)    |       1048 |         129 |       114.7 |              1.125 |          -14.1 |
| [10;15)   |        985 |          71 |        70.3 |              1.01  |          -17.3 |
| [15;25)   |       1358 |          56 |        61.9 |              0.905 |          -27.1 |
| [25;40)   |        929 |          19 |        25.7 |              0.738 |          -39.5 |
| ≥40       |       1085 |           6 |        14.8 |              0.405 |          -64.4 |

→ Seuil suggéré par les données : **3**. Seuil réellement appliqué : cote_min apprise dans chaque pli sur ses seules données d'entraînement (3).

Même tableau sur la période de test (contrôle, pas utilisé pour choisir) :

![Biais favori-outsider](biais_favori_outsider.png)

| tranche   |   partants |   victoires |   attendues |   reel_sur_attendu |   roi_tous_pct |
|:----------|-----------:|------------:|------------:|-------------------:|---------------:|
| [1;2)     |        216 |         101 |       114.4 |              0.883 |           -8.9 |
| [2;3)     |        490 |         149 |       166.8 |              0.893 |          -17.2 |
| [3;4)     |        592 |         141 |       144.3 |              0.977 |          -16.7 |
| [4;6)     |       1393 |         252 |       239.2 |              1.054 |          -19.5 |
| [6;10)    |       2550 |         310 |       277.1 |              1.119 |          -14.4 |
| [10;15)   |       2487 |         165 |       177.5 |              0.93  |          -23.3 |
| [15;25)   |       3415 |         170 |       155.5 |              1.094 |            9.4 |
| [25;40)   |       2152 |          58 |        59.4 |              0.976 |          -25.9 |
| ≥40       |       2775 |          26 |        36.9 |              0.705 |          -51.3 |

`roi_tous_pct` : ROI obtenu en pariant TOUS les chevaux de la tranche aux rapports réels. Un réel/attendu supérieur à ≈ 1.19 serait nécessaire pour être rentable.

## Le favori gagne-t-il ? (période de test)

| rang    |   partants |   victoires |   part_des_victoires_pct |   reel_sur_attendu |   roi_systematique_pct |
|:--------|-----------:|------------:|-------------------------:|-------------------:|-----------------------:|
| favori  |       1371 |         389 |                     28.4 |              0.924 |                  -15.8 |
| 2e      |       1371 |         262 |                     19.1 |              1.121 |                  -13.6 |
| 3e      |       1371 |         165 |                     12   |              1     |                  -28.3 |
| 4e      |       1370 |         137 |                     10   |              1.075 |                  -15.6 |
| 5e      |       1366 |         104 |                      7.6 |              1.034 |                  -22.6 |
| 6e et + |       9221 |         315 |                     23   |              0.974 |                  -19.1 |

`part_des_victoires_pct` : part des courses gagnées par chaque rang de cote. `reel_sur_attendu` > 1 : le marché sous-estime ce rang. `roi_systematique_pct` : ROI en jouant ce rang dans toutes les courses. Que la majorité des gagnants ne soient pas le favori ne suffit pas : il faut que leur cote paie plus que leur chance réelle, prélèvement compris.

## Dérive de la cote entre la décision et le départ (gagnants)

| tranche   |   gagnants |   ratio_moyen |   ratio_median |
|:----------|-----------:|--------------:|---------------:|
| [1;2)     |        101 |         1.223 |          1.182 |
| [2;3)     |        149 |         1.116 |          1.048 |
| [3;4)     |        141 |         1.013 |          0.967 |
| [4;6)     |        252 |         0.921 |          0.867 |
| [6;10)    |        310 |         0.913 |          0.836 |
| [10;15)   |        165 |         0.987 |          0.94  |
| [15;25)   |        170 |         1.238 |          0.966 |
| [25;40)   |         58 |         0.919 |          0.778 |
| ≥40       |         26 |         0.979 |          0.96  |

Un ratio médian < 1 : le gagnant paie moins que la cote vue au moment de parier (l'argent tardif fait baisser les cotes des chevaux qui gagnent).

## Sensibilité aux paramètres (descriptif)

ROI en mise fixe selon la cote minimale (lignes) et la marge d'EV (colonnes), nombre de paris entre parenthèses. **Choisir la meilleure case de ce tableau serait du surajustement** : il montre seulement la stabilité.

|   cote_min | 0.0           | 0.05          | 0.1           | 0.2          | 0.3          |
|-----------:|:--------------|:--------------|:--------------|:-------------|:-------------|
|          1 | -13.0 % (483) | -4.7 % (241)  | +7.7 % (128)  | -58.9 % (45) | -75.3 % (17) |
|          2 | -11.3 % (394) | -4.5 % (212)  | +10.6 % (118) | -58.9 % (45) | -75.3 % (17) |
|          3 | -17.6 % (327) | -8.1 % (175)  | +2.6 % (99)   | -83.7 % (43) | -75.3 % (17) |
|          4 | -20.0 % (300) | -12.1 % (168) | -0.1 % (94)   | -82.9 % (41) | -73.8 % (16) |
|          6 | -23.8 % (289) | -13.8 % (162) | -5.6 % (91)   | -89.5 % (40) | -72.0 % (15) |
|          8 | -28.5 % (284) | -18.2 % (160) | -12.3 % (88)  | -88.3 % (36) | -67.7 % (13) |

## Exploration puis confirmation

Paramètres choisis sur 2026-09-19 → 2026-10-09 : {'cote_min': 3.0, 'marge_ev': 0.05} (ROI en exploration -17.1 %).
Puis mesurés, figés, sur 2026-10-10 → 2026-10-27 : **67 paris, ROI +6.6 %**, IC 90 % [-52.7 ; 143.6].

## Patterns : situations sous-cotées par le marché ?

Entraînement avant le 2026-10-04, test ensuite. A/E = victoires réelles / attendues selon les cotes. Retenu si significatif après correction de Benjamini-Hochberg (α = 0.1) ; validé seulement si A/E > 1 et ROI > 0 en test.

| pattern                                                  |   n_entr |   AE_entr |   roi_pct_entr |   z_entr | retenu_entr_BH   |   n_test |   AE_test |   roi_pct_test | valide_test   |
|:---------------------------------------------------------|---------:|----------:|---------------:|---------:|:-----------------|---------:|----------:|---------------:|:--------------|
| ≥ 2 incidents (D/A/T) sur 5 dernières                    |     2071 |     1.159 |            2.6 |     2.01 | False            |     1610 |     1.032 |          -25   | False         |
| Déferré antérieurs ou postérieurs                        |      664 |     1.233 |            4.7 |     1.85 | False            |      942 |     1.045 |          -24.2 | False         |
| Musique faible (moyenne 3 dernières ≥ 8)                 |     2915 |     1.138 |           -4.1 |     1.73 | False            |     2423 |     0.857 |          -36.8 | False         |
| 2e favori                                                |     1135 |     1.11  |          -16.8 |     1.68 | False            |      834 |     1.114 |          -10.4 | False         |
| A gagné sa dernière course                               |     1424 |     1.065 |          -20.8 |     1.11 | False            |      994 |     1.095 |          -14.5 | False         |
| Jockey/driver historiquement sous-coté (A/E passé > 1,2) |     1886 |     1.074 |           -9.5 |     1.09 | False            |     1792 |     1.09  |          -16.5 | False         |
| Cote en forte hausse T-90 → décision (> 25 %)            |     3839 |     1.067 |          -25.8 |     0.93 | False            |     2830 |     0.988 |          -36.6 | False         |
| Recourt dans les 10 jours                                |      715 |     1.094 |          -25.3 |     0.76 | False            |      726 |     1.009 |          -27.1 | False         |
| Changement de distance > 15 %                            |      926 |     1.073 |          -13.3 |     0.69 | False            |     1932 |     0.962 |          -23.5 | False         |
| Plat, corde intérieure (1er tiers)                       |     1597 |     1.003 |          -19   |     0.04 | False            |     1259 |     0.968 |          -26.1 | False         |
| Cote en baisse T-30 → décision (> 10 %)                  |     2284 |     0.997 |          -18.1 |    -0.07 | False            |     1856 |     0.984 |          -20   | False         |
| Déferré des 4 pieds                                      |     2926 |     0.993 |          -21.2 |    -0.13 | False            |     2012 |     1.083 |           -9.2 | False         |
| Outsider 10-25 dans un petit peloton (≤ 8)               |      478 |     0.975 |          -27.5 |    -0.14 | False            |      369 |     1.193 |          -14.8 | False         |
| Reprise (pas couru cette année)                          |      181 |     0.951 |          -50.6 |    -0.18 | False            |       82 |     0.437 |          -79.9 | False         |
| ≥ 3 podiums sur 5 dernières                              |     2588 |     0.987 |          -24.8 |    -0.28 | False            |     1863 |     0.996 |          -24   | False         |
| Plat, corde extérieure (dernier tiers)                   |     1597 |     0.971 |          -21.6 |    -0.39 | False            |     1259 |     0.954 |          -32.4 | False         |
| Jockey/driver historiquement sur-coté (A/E passé < 0,8)  |     1312 |     0.961 |          -27.3 |    -0.52 | False            |     1345 |     1.021 |          -29.4 | False         |
| A fait mieux que ses cotes (surplus passé > 0)           |      281 |     0.926 |          -36.4 |    -0.58 | False            |      798 |     1.216 |            5   | False         |
| Entraîneur historiquement sous-coté (A/E passé > 1,2)    |      991 |     0.945 |          -15.2 |    -0.64 | False            |      nan |   nan     |          nan   | False         |
| Inédit                                                   |      532 |     0.838 |          -42.7 |    -1.16 | False            |      376 |     1.037 |           24.7 | False         |
| Cote en forte baisse T-90 → décision (> 25 %)            |     1522 |     0.919 |          -17.4 |    -1.45 | False            |     1283 |     0.941 |          -22   | False         |
| Aucun incident sur 5 dernières (trot)                    |     2875 |     0.911 |          -39.6 |    -1.57 | False            |     2050 |     0.968 |          -27.6 | False         |

→ **0 pattern(s) validé(s) hors échantillon** sur 22 testés.

## Limites

- En pari mutuel, la cote finale n'est connue qu'après le départ et votre propre mise la fait baisser (négligeable pour de petites mises sur des masses de plusieurs milliers d'euros, pas pour des courses à faible enjeu).
- Le nombre de paris nécessaire pour prouver un avantage est très élevé aux cotes moyennes jouées : ≈ 24 986 paris pour distinguer +5 % de 0.
- Les hyperparamètres (pénalités, marge, seuils) sont fixés a priori ; aucune optimisation n'a été faite sur la période de test.

Fichiers : `predictions_test.csv` (toutes les probabilités hors échantillon), `paris_fixe.csv`, `paris_kelly.csv`, `comparaison_strategies.csv`.
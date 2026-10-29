"""simplegagnant — moteur de pronostics « Simple Gagnant » orienté valeur.

L'objectif n'est pas de trouver le gagnant le plus probable mais les chevaux
dont la cote paie plus que leur probabilité réelle de victoire estimée.

Modules :
    schema     – format canonique des données (une ligne = un partant)
    musique    – lecture de la « musique » PMU (performances récentes)
    features   – variables explicatives, calculées SANS information du futur
    clogit     – logit conditionnel (softmax par course), le modèle de base
    model      – modèle en deux étapes (fondamental puis combinaison avec le marché)
    value      – sélection des paris à valeur et gestion de mise
    backtest   – validation chronologique (walk-forward), métriques, références
    patterns   – recherche et validation hors échantillon de situations sous-cotées
    report     – rapport Markdown + graphiques
"""

__version__ = "1.0.0"

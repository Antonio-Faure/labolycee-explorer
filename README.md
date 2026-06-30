# Labolycée Explorer

Un **scraper** qui explore le site [labolycee.org](https://labolycee.org/) et récupère automatiquement la liste de tous les exercices de physique-chimie avec leurs infos (titre, points, durée, thème, lien vers le sujet PDF et le corrigé PDF).

Les résultats sont sauvegardés dans un **fichier CSV** qui peut être exploré avec le **navigateur web** (`index.html`) pour filtrer les exercices.

---

## Installation

```bash
# 1. Créer un environnement virtuel (optionnel mais recommandé)
python3 -m venv .venv
source .venv/bin/activate

# 2. Installer les dépendances
pip install -r requirements.txt
```

## Lancer le scraper

```bash
python main.py
```

Le script va :
1. Parcourir tout le site labolycee.org
2. Extraire les infos de chaque exercice
3. Générer les fichiers :
   - `labolycee.org.txt` — toutes les URLs trouvées
   - `labolycee.org_exercises.csv` — la liste des exercices (ouvrable dans un tableur)
   - `labolycee.org.png` — graphique d'avancement
   - `data/v_YYYY-MM-DD_HH-MM-SS/` — dossier avec une sauvegarde complète

## Explorer les exercices

Ouvre `index.html` dans ton navigateur. Tu peux :
- Filtrer par titre, thème, nombre de points, durée
- Accéder directement au sujet ou au corrigé PDF

> Il utilise le fichier `labolycee.org_exercises.csv` généré par le scraper.

## Structure du CSV

| Colonne | Description |
|---|---|
| `header` | Titre de l'exercice |
| `url` | Lien vers la page de l'exercice |
| `nb_points` | Nombre de points |
| `theme` | Thèmes (séparés par `\|`) |
| `duree` | Durée de l'exercice |
| `sujet_url` | Lien vers le PDF du sujet |
| `correction_url` | Lien vers le PDF du corrigé |

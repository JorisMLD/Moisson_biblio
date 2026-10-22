# Veille scientifique en didactique des mathématiques

Un outil qui suit, à intervalles réguliers, la parution d'articles dans une
quinzaine de revues de didactique des mathématiques, et les range dans une base
de données locale. À chaque passage, il signale les nouveautés, cherche les
versions en accès ouvert, complète les bibliographies et produit un fichier
BibTeX prêt pour JabRef ou Zotero.

Il fonctionne sous Windows, macOS et Linux, sans connaissance de Python : un
double-clic sur le lanceur de son système suffit. Le [mode d'emploi](MODE_EMPLOI.md)
explique tout, de l'installation à l'ajout d'une revue.

## Ce que fait l'outil

À chaque mise à jour, quatre étapes s'enchaînent :

1. **Moisson.** Chaque revue est interrogée depuis son dernier passage. Les
   nouvelles notices (titre, auteurs, année, résumé, DOI) entrent dans la base ;
   un même article vu par deux sources n'est compté qu'une fois.
2. **Liens PDF.** Pour chaque notice, l'outil cherche un PDF en accès ouvert,
   d'abord chez la revue, puis dans les archives ouvertes (version auteur HAL).
   Il ne garde que le lien : les PDF ne sont pas stockés, par économie de place
   et par respect des revues, dont les statistiques de visite comptent.
3. **Bibliographies.** Les références citées par chaque article sont
   complétées, ce qui permet de suivre la circulation des notions.
4. **Exports.** Une note des nouveautés du jour (Markdown), un BibTeX complet,
   et une liste des liens PDF récents pour un téléchargement groupé délibéré.

## Revues suivies

| Revue | Source des données | Accès au texte |
| :--- | :--- | :--- |
| Annales de didactique et de sciences cognitives | OpenEdition (OAI-PMH) | ouvert |
| Éducation et didactique | OpenEdition (OAI-PMH) | ouvert, selon embargo |
| Recherches en didactique des mathématiques | Crossref (Episciences, depuis 2024) | ouvert |
| Rematec | entrepôt OJS (OAI-PMH) | ouvert |
| Educational Studies in Mathematics | Crossref | abonnement, quelques articles ouverts |
| ZDM Mathematics Education | Crossref | abonnement, quelques articles ouverts |
| Journal for Research in Mathematics Education | Crossref | abonnement |
| Journal of Mathematical Behavior | Crossref | abonnement, quelques articles ouverts |
| Asian Journal for Mathematics Education | Crossref | ouvert |
| New ICMI Study Series (volumes des ICMI Studies) | Crossref, au grain du chapitre | plusieurs volumes ouverts |
| For the Learning of Mathematics | site de la revue (numéro courant) | abonnement, ouvert après 3 ans |
| Petit x | site de l'IREM de Grenoble | ouvert |
| Grand N | site de l'IREM de Grenoble | ouvert |
| Repères IREM | site de l'IREM de Grenoble | ouvert |
| Revue de mathématiques pour l'école (RMé) | inactive : entrepôt à confirmer | |

Quelques limites connues, détaillées dans le mode d'emploi : RDM n'est couverte
que depuis son passage sur Episciences (2024) ; ZDM depuis l'adoption de ses
ISSN actuels (milieu des années 2000) ; FLM et les revues de l'IREM de Grenoble,
faute d'API, sont lues sur leurs pages web, qui peuvent changer sans préavis.

## Démarrage rapide

```
Windows : double-cliquer sur  Veille-Windows.bat
macOS   : double-cliquer sur  Veille-Mac.command
Linux   : ./Veille-Linux.sh
```

Le premier lancement installe l'outil, demande une adresse email de contact
(que Crossref et OpenAlex souhaitent connaître), puis ouvre un menu. Choisir
« Mettre à jour la veille » : la première fois, compter une à deux heures, puis
quelques minutes les fois suivantes.

En ligne de commande, l'équivalent est :

```
python -m veille setup
python -m veille routine
```

## Organisation du dépôt

```
Veille-Windows.bat, Veille-Mac.command, Veille-Linux.sh   lanceurs
sources.seed.json      liste des revues suivies (à modifier pour en ajouter)
veille/                code Python
  run.py               commandes et menu
  connectors/          un connecteur par type de source (oai, metadata, scraper)
  resolve.py           recherche des liens PDF
  references.py        complétion des bibliographies
  export.py            BibTeX et liste de liens
  db.py                base SQLite (schéma, dédoublonnage)
tests/                 tests automatiques, sans réseau
donnees/               créé au premier lancement : base, réglages, exports.
                       Jamais versionné.
```

Trois types de connecteurs alimentent la même base : `oai` pour les entrepôts
OAI-PMH (OpenEdition, OJS), `metadata` pour les revues indexées par Crossref,
`scraper` pour les sites sans API. Chacun produit des notices au même format,
dédoublonnées par DOI, ou à défaut par titre, année et revue.

## Contribuer

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

Les tests n'utilisent pas le réseau. Ils tournent automatiquement sur Windows,
macOS et Linux à chaque envoi sur GitHub (voir `.github/workflows/tests.yml`),
y compris un essai des trois lanceurs. Python 3.9 ou plus récent est requis.

## Licence

À préciser par le porteur du projet avant diffusion publique.

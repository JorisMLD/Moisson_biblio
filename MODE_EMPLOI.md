# Mode d'emploi

Ce document s'adresse à toute personne qui veut utiliser la veille, y compris
sans aucune expérience de Python ou du terminal. Les parties 1 et 2 suffisent
pour un usage courant ; les suivantes servent à aller plus loin.

**Sommaire**

1. [Installation](#1-installation)
2. [Utilisation courante](#2-utilisation-courante)
3. [Les commandes](#3-les-commandes)
4. [Réglages : email et clé OpenAlex](#4-réglages--email-et-clé-openalex)
5. [Ajouter ou retirer une revue](#5-ajouter-ou-retirer-une-revue)
6. [Automatiser la mise à jour](#6-automatiser-la-mise-à-jour)
7. [Dépannage](#7-dépannage)
8. [Comment ça marche](#8-comment-ça-marche)

## 1. Installation

### 1.1 Récupérer l'outil

Deux possibilités :

* **Avec git** (recommandé, pour recevoir les mises à jour) :
  `git clone <adresse du dépôt>` dans le dossier de votre choix.
* **Sans git** : sur la page du dépôt, bouton *Code*, puis *Download ZIP* ;
  décompresser l'archive dans un dossier de votre choix, par exemple
  `Documents/veille`.

Évitez un dossier synchronisé en continu (OneDrive, Dropbox, iCloud) : la base
de données s'y abîme parfois quand le service la copie pendant une écriture.

### 1.2 Installer Python (une seule fois)

Il faut Python 3.9 ou plus récent. Les lanceurs vérifient sa présence et vous
guident s'il manque.

**Windows.** Télécharger Python sur <https://www.python.org/downloads/> et lancer
l'installateur. **Sur le premier écran, cocher « Add python.exe to PATH »**, puis
*Install Now*. Évitez la version du Microsoft Store, moins prévisible.

**macOS.** Télécharger Python sur <https://www.python.org/downloads/> et lancer
l'installateur. À défaut, le Python fourni par les outils en ligne de commande
d'Apple (proposés automatiquement au premier usage) convient aussi.

**Linux.** Python est déjà présent. Sous Debian ou Ubuntu, il faut en plus le
module de création d'environnements :

```
sudo apt install python3-venv
```

### 1.3 Premier lancement

| Système | Action |
| :--- | :--- |
| Windows | double-cliquer sur `Veille-Windows.bat` |
| macOS | double-cliquer sur `Veille-Mac.command` (voir l'encadré ci-dessous) |
| Linux | dans un terminal ouvert dans le dossier : `./Veille-Linux.sh` |

Au premier lancement, le lanceur crée un environnement Python propre à l'outil
(dossier `.venv`, sans rien modifier au reste de l'ordinateur), installe les deux
bibliothèques nécessaires, crée la base, puis demande une adresse email de
contact. Une à deux minutes suffisent. Les lancements suivants ouvrent
directement le menu.

> **macOS : « développeur non identifié ».** Au premier double-clic, macOS peut
> refuser d'ouvrir le fichier. Faire un clic droit (ou Ctrl+clic) sur
> `Veille-Mac.command`, choisir *Ouvrir*, puis confirmer. Sur les versions
> récentes, aller dans *Réglages système > Confidentialité et sécurité* et
> cliquer sur *Ouvrir quand même*. Autre solution : ouvrir le Terminal dans le
> dossier et taper `bash Veille-Mac.command`.

## 2. Utilisation courante

### 2.1 Le menu

```
=== Veille scientifique 1.0.0 ===
14 revues actives, 12873 notices en base. Contact : prenom.nom@univ.fr
  1  Mettre à jour la veille (moisson, liens PDF, références, exports)
  2  Lire les nouveautés du dernier passage
  3  Ouvrir le dossier des exports (BibTeX pour JabRef, liens PDF)
  4  Bilan par revue
  5  Régler mon adresse email
  0  Quitter
```

**1, Mettre à jour.** C'est l'opération principale, à lancer aussi souvent que
vous voulez (chaque semaine, chaque mois). La première fois, comptez une à deux
heures : toute l'histoire des revues est récupérée. Ensuite, quelques minutes.
Vous pouvez interrompre à tout moment avec Ctrl+C : rien n'est perdu, le travail
reprend où il en était au lancement suivant.

**2, Nouveautés.** Ouvre la note des notices apparues lors de la dernière mise à
jour, classées par revue, avec auteurs, année, lien DOI et résumé. C'est un
fichier Markdown, lisible dans n'importe quel éditeur de texte, ou joliment mis
en forme dans Obsidian, Typora, VS Code.

**3, Exports.** Ouvre le dossier qui contient `veille.bib` (toutes les notices)
et `liens-pdf-recents.txt` (les liens PDF en accès ouvert de l'année en cours et
de la précédente).

**4, Bilan.** Pour chaque revue : nombre de notices, de liens PDF, de
bibliographies, et date du dernier passage. Une revue qui n'avance plus signale
souvent un site qui a changé (voir [Dépannage](#7-dépannage)).

### 2.2 Où sont mes données ?

Tout ce qui vous est propre vit dans le dossier `donnees/`, créé au premier
lancement :

```
donnees/
  veille.db                  la base (toutes les notices)
  config.json                vos réglages (email, clé OpenAlex)
  digests/2026-10-22.md      les nouveautés de chaque mise à jour
  exports/veille.bib         BibTeX complet, régénéré à chaque mise à jour
  exports/liens-pdf-recents.txt
  pdfs/                      seulement si vous utilisez la commande download
```

Ce dossier n'est jamais envoyé sur git. Pour sauvegarder votre veille, copiez-le.
Pour repartir de zéro, supprimez-le.

### 2.3 Utiliser les notices dans JabRef ou Zotero

`veille.bib` est **réécrit à chaque mise à jour**. Ne le modifiez donc pas
directement : servez-vous-en comme d'un catalogue.

* **JabRef** : *Fichier > Ouvrir une bibliothèque*, choisir
  `donnees/exports/veille.bib`. Il s'ouvre dans un onglet à part ; cherchez,
  triez, puis copiez les entrées utiles dans votre propre bibliothèque.
* **Zotero** : *Fichier > Importer*, choisir le fichier. Pour ne pas réimporter
  tout le catalogue à chaque fois, n'importez que les nouveautés (voir
  ci-dessous).

Pour un fichier ne contenant que les notices récentes ou une seule revue :

```
veille export --bib nouveautes.bib --new-since 2026-10-01
veille export --bib petitx.bib --journal "Petit x"
```

Le champ `url` de chaque entrée pointe vers la page de l'article chez la revue
(ou vers son DOI), pas vers le PDF : on lit et on cite chez l'éditeur.

### 2.4 Télécharger des PDF, ponctuellement

Par choix, la veille ne télécharge pas les PDF : elle en garde les liens. Pour
une récolte délibérée, deux options.

La commande intégrée, qui fonctionne sur tous les systèmes, ne prend que les
notices de l'année en cours (modifiable), vérifie que chaque fichier est bien un
PDF et les range dans `donnees/pdfs/` :

```
veille download                       année en cours
veille download --min-year 2025 --limit 30
```

Ou un téléchargeur externe, à partir de la liste de liens, en restant poli
(pause entre deux fichiers) :

```
wget --wait=2 -i donnees/exports/liens-pdf-recents.txt -P donnees/pdfs
```

Certains liens (OpenEdition notamment) ne donnent le PDF que depuis le réseau
d'une institution abonnée : hors de ce réseau, ils sont simplement ignorés.

## 3. Les commandes

Le menu suffit au quotidien. Pour le reste, chaque action existe aussi en
commande. Dans ce document, `veille <commande>` signifie, selon votre système :

| Système | Ce qu'il faut taper |
| :--- | :--- |
| Windows (invite de commandes) | `Veille-Windows.bat <commande>` |
| Windows (PowerShell) | `.\Veille-Windows.bat <commande>` |
| macOS | `./Veille-Mac.command <commande>` |
| Linux | `./Veille-Linux.sh <commande>` |
| Python géré à la main | `python -m veille <commande>` |

Ouvrez le terminal dans le dossier de l'outil. Sous Windows : dans
l'explorateur, cliquer dans la barre d'adresse du dossier, taper `cmd`, Entrée.

| Commande | Rôle |
| :--- | :--- |
| `menu` | le menu (comportement par défaut des lanceurs) |
| `setup` | installe la base, recharge la liste des revues, demande l'email |
| `routine` | mise à jour complète : les quatre étapes ci-dessous, puis les exports |
| `update` | moisson seule ; `--source 11` pour une seule revue ; `--digest` pour écrire les nouveautés |
| `resolve` | recherche des liens PDF ; `--min-year 0` pour toutes les années |
| `references` | complétion des bibliographies |
| `export` | `--bib FICHIER`, `--urls FICHIER`, filtres `--min-year`, `--journal`, `--new-since`, `--with-pdf` |
| `download` | téléchargement ponctuel de PDF récents |
| `stats` | bilan par revue |
| `sources` | liste des revues et de leur numéro |
| `check` | vérifie que Crossref connaît les revues de type `metadata` |
| `discover URL` | explore un entrepôt OAI-PMH (pour ajouter une revue) |

`veille <commande> --help` détaille les options de chaque commande. L'option
générale `-v` affiche chaque requête envoyée, utile pour comprendre un blocage.

## 4. Réglages : email et clé OpenAlex

**L'adresse email** est transmise à Crossref et OpenAlex, et à eux seuls. Ces
services la demandent pour pouvoir prévenir en cas d'usage anormal ; en échange,
ils traitent les requêtes identifiées plus vite. Sans email, l'outil fonctionne,
plus lentement. Pour la changer : menu, choix 5, ou
`veille setup --email prenom.nom@univ.fr`.

**La clé OpenAlex** est facultative. OpenAlex facture désormais une partie de
son service au-delà d'un forfait quotidien gratuit : les interrogations par DOI
restent gratuites, les recherches groupées consomment un peu de ce forfait. Sans
clé, le forfait couvre largement une veille normale ; une clé gratuite le
multiplie par dix, utile pour un premier passage très volumineux. Pour en
obtenir une : créer un compte sur <https://openalex.org>, copier la clé depuis
*Settings > API*, puis :

```
veille setup --openalex-key VOTRE_CLE
```

Les réglages sont dans `donnees/config.json`. Ils peuvent aussi venir des
variables d'environnement `VEILLE_EMAIL` et `OPENALEX_API_KEY`.

## 5. Ajouter ou retirer une revue

La liste des revues est le fichier `sources.seed.json`, à la racine. Chaque revue
y est décrite par quelques champs. Après modification, `veille setup` recharge
la liste sans rien perdre de ce qui est déjà en base.

**Retirer une revue** : passer son champ `"enabled"` à `0`. Ses notices restent
en base, elle n'est simplement plus moissonnée.

**Ajouter une revue indexée par Crossref** (le cas le plus fréquent : presque
toutes les revues qui attribuent des DOI). Il suffit de ses ISSN :

```json
{
  "name": "Nom de la revue",
  "connector": "metadata",
  "issn_print": "1234-5678",
  "issn_online": "8765-4321",
  "enabled": 1,
  "notes": "pourquoi on la suit, particularités"
}
```

**Ajouter une revue disposant d'un entrepôt OAI-PMH** (OpenEdition, OJS,
Episciences). Explorer d'abord l'entrepôt pour connaître le nom de son ensemble
(`setSpec`) :

```
veille discover https://metadata.openedition.org/oai
```

puis :

```json
{
  "name": "Nom de la revue",
  "connector": "oai",
  "base_url": "https://metadata.openedition.org/oai",
  "oai_set": "journals:nomdelarevue",
  "enabled": 1
}
```

Pour une revue sous OJS, l'adresse est en général celle de la revue suivie de
`/oai`, sans `oai_set`.

**Vérifier puis moissonner** la nouvelle revue seule :

```
veille setup
veille sources                  repérer son numéro, disons 16
veille check                    pour une revue metadata : Crossref la connaît-il ?
veille update --source 16
veille stats
```

Une revue sans API ni entrepôt (comme FLM ou les revues de l'IREM de Grenoble)
demande d'écrire un analyseur de pages dans `veille/connectors/scraper.py` :
c'est un travail de programmation, pour lequel les deux analyseurs existants
servent de modèles.

## 6. Automatiser la mise à jour

Facultatif : lancer la mise à jour à la main depuis le menu marche très bien.
Pour une exécution régulière sans intervention :

**Windows.** Ouvrir le *Planificateur de tâches*, *Créer une tâche de base*,
choisir la fréquence ; action *Démarrer un programme* : programme
`Veille-Windows.bat` (chemin complet), argument `routine`, champ *Commencer dans*
: le dossier de l'outil.

**Linux.** Une minuterie systemd rattrape les passages manqués quand la
machine était éteinte. Créer `~/.config/systemd/user/veille.service` :

```ini
[Service]
Type=oneshot
ExecStart=/chemin/vers/veille/Veille-Linux.sh routine
```

et `~/.config/systemd/user/veille.timer` :

```ini
[Timer]
OnCalendar=Mon 09:00
Persistent=true

[Install]
WantedBy=timers.target
```

puis `systemctl --user enable --now veille.timer`.

**macOS.** Le plus simple est une ligne cron (`crontab -e`) :
`0 9 * * 1 /chemin/vers/veille/Veille-Mac.command routine`. Si le dossier est
dans *Documents*, macOS peut demander d'accorder à cron l'accès disque
(*Réglages système > Confidentialité et sécurité > Accès complet au disque*).

## 7. Dépannage

**« Python est introuvable » sous Windows alors qu'il est installé.** La case
« Add python.exe to PATH » n'a pas été cochée. Relancer l'installateur Python,
choisir *Modify*, cocher *Add Python to environment variables*.

**Rien ne se passe au double-clic sous Linux.** Les gestionnaires de fichiers
ouvrent souvent les scripts dans un éditeur. Lancer depuis un terminal :
`./Veille-Linux.sh`. En cas de « Permission non accordée » :
`chmod +x Veille-Linux.sh outils/lanceur.sh` (même chose pour
`Veille-Mac.command` sur Mac).

**« L'installation a échoué ».** Il faut une connexion internet au premier
lancement. Derrière un proxy d'établissement, définir les variables
`HTTPS_PROXY` et `HTTP_PROXY` avant de relancer.

**Une revue est « en échec ».** Le message indique la raison. Une coupure réseau
ou un serveur indisponible se règlent seuls : la revue est reprise au passage
suivant, sans rien perdre. Si l'échec se répète pour FLM ou une revue de l'IREM
de Grenoble, leur site a probablement changé de structure : l'analyseur est à
adapter (voir partie 5).

**« Serveur saturé (429) ».** Le service demande de ralentir ; l'outil attend
puis reprend tout seul.

**« OpenAlex refuse de nouvelles requêtes (quota du jour atteint ?) ».** La
recherche de PDF s'arrête proprement et reprendra le lendemain là où elle en
était. Une clé OpenAlex gratuite (partie 4) relève ce quota.

**« database is locked ».** Deux mises à jour tournent en même temps (deux
fenêtres, ou une tâche planifiée). Fermer l'une des deux.

**Les nouveautés semblent nombreuses pour une revue Crossref.** Crossref signale
aussi les notices mises à jour (corrections, nouvelles citations). L'outil les
reconnaît et ne les compte pas comme nouvelles dans le digest ; seul le journal
affiche « mises à jour ».

**Mettre à jour l'outil.** Avec git : `git pull` dans le dossier, puis relancer ;
le lanceur réinstalle les dépendances si besoin, et la base est mise à niveau
automatiquement. Sans git : télécharger la nouvelle archive et y recopier votre
dossier `donnees/`.

## 8. Comment ça marche

**Trois façons d'interroger une revue.** Les revues sur OpenEdition, OJS ou
Episciences exposent un entrepôt OAI-PMH, protocole standard des archives
ouvertes (connecteur `oai`). Les revues qui attribuent des DOI sont décrites
chez Crossref, interrogé par ISSN (connecteur `metadata`), avec repli sur
OpenAlex pour les résumés manquants. Les autres sont lues sur leurs pages web
(connecteur `scraper`).

**Incrémental.** Chaque revue garde la date de son dernier passage réussi ; on
ne demande que ce qui a paru ou changé depuis. De même, chaque notice garde la
date de sa dernière recherche de PDF et de bibliographie, pour ne pas reposer
la même question à chaque passage. Une notice restée sans PDF est réexaminée au
bout de six mois (un article peut passer en accès ouvert à la fin d'un
embargo) ; pour les bibliographies, `veille references --recheck 365` relance
volontairement la recherche sur les notices restées sans références depuis un an.

**Dédoublonnage.** Une notice est identifiée par son DOI ; sans DOI, par son
titre normalisé (sans accents ni ponctuation), son année et sa revue. Un article
vu par deux sources n'est enregistré qu'une fois, et chaque source complète ce
qui manque.

**Liens PDF.** Dans l'ordre : pour OpenEdition, le lien se déduit du DOI ;
ensuite OpenAlex, interrogé par lots de cinquante DOI ; enfin HAL, pour une
version déposée par les auteurs, marquée comme telle. Seuls de vrais liens vers
des PDF sont retenus. La recherche se limite par défaut aux notices depuis 2000 :
avant, l'accès ouvert est rarissime.

**Limites de couverture.** RDM est couverte depuis 2024 (Episciences) ; les
numéros antérieurs ne sont pas indexés par Crossref. ZDM l'est depuis le milieu
des années 2000. FLM n'est lue que pour son numéro courant : la veille couvre
FLM à partir de la première mise à jour. Les revues de l'IREM de Grenoble n'ont
pas de résumé en ligne. La New ICMI Study Series est une collection d'ouvrages :
`veille check` confirme que Crossref la retrouve par ses ISSN de collection.

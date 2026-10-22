# Extrait reel de la page de consultation Petit x (structure conservee).
# Couvre les trois eres d'URL, un hors-serie, un numero double et un numero
# thematique, plus du bruit de plan de site (classe lien_interne seule) qui
# ne doit PAS etre ramasse.

LISTING = """<html><body>
<div id="menumobile-principal"><div class="plan-site"><ul class="plan-site__1">
  <li><span class="plan-site__rubrique"><a href="https://irem.univ-grenoble-alpes.fr/revues/petit-x/consultation/numero-1-petit-x/" class="lien_interne">Numéro 1 Petit x</a></span></li>
  <li><span class="plan-site__rubrique"><a href="https://irem.univ-grenoble-alpes.fr/revues/petit-x/consultation/numero-2-petit-x/" class="lien_interne">Numéro 2 Petit x</a></span></li>
</ul></div></div>

<h2 class="titre__page__centre">Consultation des anciens numéros de Petit x</h2>
<span class="klist"><ul class="liste__objets liste__articles flex-non  ">
  <li class="liste__objets__style0026 ">
    <span class="icon icon-fleche_menu liens_fond_blanc "></span>
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/numero-123-petit-x-2025--1742582.kjsp?RH=1541685528129">
      <em>Numéro 123 - Petit x (2025)</em>
    </a>
  </li>
  <li class="liste__objets__style0026 ">
    <span class="icon icon-fleche_menu liens_fond_blanc "></span>
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/revues/petit-x/consultation/numero-121-petit-x/numero-121-petit-x-2024--1547194.kjsp?RH=1541685528129">
      <em>Numéro 121 - Petit x (2024)</em>
    </a>
  </li>
  <li class="liste__objets__style0026 ">
    <span class="icon icon-fleche_menu liens_fond_blanc "></span>
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/revues/petit-x/consultation/numero-119-thematique-sur-l-informatique-petit-x/numero-119-thematique-sur-l-informatique-petit-x-2023--1351520.kjsp?RH=1541685528129">
      <em>Numéro 119 thématique sur l'informatique - Petit x (2023)</em>
    </a>
  </li>
  <li class="liste__objets__style0026 ">
    <span class="icon icon-fleche_menu liens_fond_blanc "></span>
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/revues/petit-x/consultation/hors-serie-activites-/hors-serie-activites-n-4-1081112.kjsp?RH=1541685528129">
      <em>Hors-série "Activités" n°4</em>
    </a>
  </li>
  <li class="liste__objets__style0026 ">
    <span class="icon icon-fleche_menu liens_fond_blanc "></span>
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/revues/petit-x/consultation/numero-110-111-petit-x/numero-110-111-petit-x-2019--650322.kjsp?RH=1541685528129">
      <em>Numéro 110-111- Petit x (2019)</em>
    </a>
  </li>
</ul></span>
</body></html>"""


# Page d'un numero : les articles reutilisent la meme classe liste__objets__titre
# (structure reelle observee sur num123.html), plus du bruit de plan de site.
ISSUE_PAGE = """<html><body>
<div class="plan-site"><ul><li><a href="https://irem.univ-grenoble-alpes.fr/revues/petit-x/consultation/numero-1-petit-x/" class="lien_interne">Numéro 1 Petit x</a></li></ul></div>
<span class="klist"><ul class="liste__objets liste__articles flex-non  ">
  <li class="liste__objets__style0026 ">
    <span class="icon icon-fleche_menu liens_fond_blanc "></span>
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/1-logarithmes-en-jeu-raisonnements-en-action-et-verbalisations-1742585.kjsp?RH=1774606601620">
      <em>Logarithmes en jeu : raisonnements en action et verbalisations</em>
    </a>
  </li>
  <li class="liste__objets__style0026 ">
    <span class="icon icon-fleche_menu liens_fond_blanc "></span>
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/2-vers-un-autre-jeu-de-postures-avec-la-ludopedagogie-1742587.kjsp?RH=1774606601620">
      <em>Vers un autre jeu de postures avec la ludopédagogie</em>
    </a>
  </li>
</ul></span>
</body></html>"""

# Page de consultation reduite a un seul numero, pour tester le drill-down.
ONE_ISSUE = """<html><body>
<span class="klist"><ul class="liste__objets liste__articles">
  <li class="liste__objets__style0026 ">
    <a class="liste__objets__titre lien_interne" href="https://irem.univ-grenoble-alpes.fr/numero-123-petit-x-2025--1742582.kjsp?RH=1541685528129">
      <em>Numéro 123 - Petit x (2025)</em>
    </a>
  </li>
</ul></span>
</body></html>"""


# Page d'article reelle (metadonnees utiles : DC.Creator, bloc fichiers-joints).
# Le resume n'est pas expose ; DC.Date est l'annee de mise en ligne (a ignorer).
ART_PAGE = """<html><head>
<meta name="DC.Title" content="1 : Logarithmes en jeu - IREM Grenoble" />
<meta name="DC.Creator" content="Benjamin Wack" />
<meta name="DC.Description" content="" />
<meta name="DC.Date.created" content="20260327 11:20:12.0" />
<meta name="author" content="Université Grenoble Alpes" />
</head><body>
<h2 class="titre__page__centre">1 : Logarithmes en jeu : raisonnements en action et verbalisations</h2>
<ul class="fichiers-joints"><li class="fichiers-joints__item">
  <a class="pdf fichiers-joints__lien" href="https://irem.univ-grenoble-alpes.fr/medias/fichier/123x1_1774606864373-pdf">
    <span class="fichiers-joints__titre">Logarithmes en jeu</span></a>
  <span class="fichiers-joints__type-poids">(PDF, 2 Mo)</span>
</li></ul>
</body></html>"""

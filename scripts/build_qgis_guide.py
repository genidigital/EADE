"""Build the EADE operations guide for QGIS (PDF, French).

    <QGIS>/bin/python-qgis.bat scripts/qgis_screenshots.py      # once: real screenshots -> build/qgis_shots
    python scripts/build_qgis_guide.py [-o docs/EADE_Guide_exploitation_QGIS.pdf]

Shares its page design with the integration guide (build_integration_guide.py).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_integration_guide as g  # noqa: E402
from build_integration_guide import (BODY, BULLET, H1, H2, H3, NAVY, OK, ROOT, SMALL, SOFT, WARN, S,  # noqa: E402
                                     bullets, code, note, p, table)
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, NextPageTemplate, PageBreak, Spacer, Table,  # noqa: E402
                                TableStyle)

SHOTS = ROOT / "build" / "qgis_shots"
CAPTION = S("caption", fontSize=8.2, leading=11, textColor=SOFT, spaceBefore=3, spaceAfter=10)
PLUGIN_VERSION = "0.1.0"


def figure(name: str, caption: str, width_mm: float = 120, max_height_mm: float = 150, keep: bool = True):
    path = SHOTS / f"{name}.png"
    if not path.exists():
        raise SystemExit(f"missing screenshot {path}: run scripts/qgis_screenshots.py with QGIS's Python first")
    from PIL import Image as PILImage
    w, h = PILImage.open(path).size
    width = width_mm * mm
    height = width * h / w
    if height > max_height_mm * mm:
        height = max_height_mm * mm
        width = height * w / h
    img = Image(str(path), width=width, height=height)
    frame = Table([[img]], colWidths=[width + 2])
    frame.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, g.LINE), ("LEFTPADDING", (0, 0), (-1, -1), 1),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    frame.hAlign = "LEFT"
    parts = [frame, p(caption, CAPTION)]
    return [KeepTogether(parts)] if keep else parts


def side_by_side(left, right, widths=(84, 84)):
    """Two columns; neither may be taller than a page."""
    t = Table([[left, right]], colWidths=[w * mm for w in widths])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    return [t]


def steps(items):
    return [p(f"<font name='Plex-Semi' color='#1F6FD6'>{i}.</font>&nbsp;&nbsp;{t}",
              S(f"step{i}", leftIndent=14, firstLineIndent=-14, spaceAfter=3)) for i, t in enumerate(items, 1)]


# ------------------------------------------------------------------- cover

def cover():
    logo = Image(str(ROOT / "docs" / "assets" / "eade-logo.png"), width=62 * mm, height=62 * mm * 445 / 482)
    logo.hAlign = "LEFT"
    t = date.today()
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
              "novembre", "décembre"]
    return [
        logo, Spacer(1, 22 * mm),
        p("GUIDE D'EXPLOITATION · QGIS", S("c0", fontName="Mono-Medium", fontSize=10, textColor=g.BLUE, leading=14)),
        Spacer(1, 3 * mm),
        p("Détecter, corriger et valider avec EADE dans QGIS", S("c1", fontName="Plex-Bold", fontSize=27, leading=33)),
        Spacer(1, 6 * mm),
        p("Installation du plugin, préparation des levés drone, détection, campagnes, atelier de correction, "
          "validation experte, contrôle qualité, administration de la connaissance et exploitation courante.",
          S("c2", fontSize=11.5, leading=17, textColor=SOFT)),
        Spacer(1, 26 * mm),
        table(["Plugin", "QGIS", "Date", "Public"],
              [[PLUGIN_VERSION, "3.34 et plus, 4.x", f"{t.day} {months[t.month - 1]} {t.year}",
                "Opérateurs SIG, experts, responsables EADE"]],
              [24 * mm, 34 * mm, 34 * mm, 70 * mm])[0],
        NextPageTemplate("body"), PageBreak(),
    ]


def toc():
    from reportlab.platypus.tableofcontents import TableOfContents
    t = TableOfContents()
    # this guide has more sub-sections: a tighter sommaire keeps it on one page
    t.levelStyles = [S("qtoc1", fontName="Plex-Semi", fontSize=9.4, leading=12.6),
                     S("qtoc2", fontSize=8.4, leading=10.2, leftIndent=14, textColor=SOFT)]
    return [p("Sommaire", g.TOC_TITLE), t, PageBreak()]


# ----------------------------------------------------------------- content

def s_roles():
    out = [p("1. Avant de commencer", H1)]
    out += [p("Ce guide décrit l'utilisation quotidienne d'EADE dans QGIS. Le plugin ajoute un groupe "
              "<b>EADE</b> à la boîte à outils de traitements et un <b>atelier</b> ancré à côté de la carte. "
              "Selon votre rôle, commencez par :")]
    out += table(["Rôle", "Ce que vous faites", "Chapitres"],
                 [["Opérateur SIG", "Préparer les données, lancer les campagnes, corriger dans l'atelier",
                   "3, 4, 5, 6"],
                  ["Expert cadastral", "Valider ou rejeter les corrections soumises", "7"],
                  ["Responsable qualité", "Mesurer, évaluer les détections et les versions", "8, 9"],
                  ["Responsable EADE", "Installer, activer, gérer les versions de connaissance, publier, "
                   "arrêter en urgence", "2, 9, 10, 11"]],
                 [36 * mm, 100 * mm, 34 * mm], bold_first=True)
    out += [p("Le cycle dans QGIS", H2)]
    out += steps([
        "<b>Préparer</b> le MNS, le MNT, l'orthophoto et les parcelles du levé (chapitre 3).",
        "<b>Détecter</b> rapidement sur une zone, ou <b>lancer une campagne</b> enregistrée dans un projet EADE "
        "(chapitres 4 et 5).",
        "<b>Corriger</b> parcelle par parcelle dans l'atelier, puis <b>soumettre</b> (chapitre 6).",
        "<b>Valider</b> : l'expert confirme ou rejette les corrections (chapitre 7).",
        "<b>Apprendre et publier</b> : le responsable construit, évalue et publie une nouvelle version "
        "(chapitre 9). Les campagnes suivantes l'appliquent.",
    ])
    out += note("EADE ne crée aucun contour par lui-même et n'écrit rien hors de son projet : ni parcelle, ni "
                "barème, ni valeur cadastrale. Une prédiction n'est jamais une vérité cadastrale : elle doit être "
                "revue et validée.", g.BLUE, "Rappel")
    out += note("les captures de ce guide sont faites sur le jeu de démonstration synthétique fourni avec le "
                "plugin (40 m × 40 m, trois parcelles). Votre interface QGIS peut être en français ou en "
                "anglais : « Run » correspond à « Exécuter », « Parameters » à « Paramètres ».", SOFT, "Captures")
    return out


def s_install():
    out = [p("2. Installer et vérifier le plugin", H1)]
    out += [p("Prérequis", H2)]
    out += bullets([
        "QGIS 3.34 ou plus récent, ou QGIS 4.x (le plugin fonctionne en Qt5 comme en Qt6). Vérifié sur "
        "QGIS 4.2.3 sous Windows.",
        "Rien d'autre à installer : le moteur EADE est embarqué dans le plugin et utilise le GDAL de QGIS.",
        "Le fichier <font name='Mono'>eade_qgis-0.1.0.zip</font>, fourni par l'équipe ou construit avec "
        "<font name='Mono'>python scripts/build_qgis_plugin.py</font>.",
    ])
    out += [p("Installation", H2)]
    out += steps([
        "Menu <b>Extensions › Installer/Gérer les extensions</b>, onglet <b>Installer depuis un ZIP</b>.",
        "Choisissez <font name='Mono'>eade_qgis-x.y.z.zip</font>, puis <b>Installer l'extension</b>.",
        "Onglet <b>Installées</b> : cochez <b>EADE</b>. La version actuelle est marquée expérimentale ; si elle "
        "n'apparaît pas, cochez « Afficher les extensions expérimentales » dans l'onglet <b>Paramètres</b>.",
    ])
    out += [p("Vérifier que tout est en place", H2)]
    out += table(["Où regarder", "Ce que vous devez voir"],
                 [["Menu Extensions › EADE", "Atelier de correction · Détecter les bâtiments… · Lancer une campagne…"],
                  ["Barre d'outils", "L'icône EADE (bascule l'atelier)"],
                  ["Boîte à outils de traitements", "Groupe EADE : Détecter les bâtiments (levé drone), Mesurer des "
                   "emprises, Évaluer des détections, Lancer une campagne dans un projet EADE"]],
                 [55 * mm, 115 * mm], bold_first=True)
    out += [p("Mettre à jour ou désinstaller", H2)]
    out += [p("Réinstallez simplement le nouveau ZIP par la même procédure : il remplace l'ancien plugin. Les "
              "projets EADE (.eade) ne sont pas touchés et restent lisibles. Pour désinstaller : onglet "
              "<b>Installées</b>, <b>Désinstaller l'extension</b>.")]
    return out


def s_data():
    out = [p("3. Préparer les données", H1)]
    out += table(["Couche", "Obligatoire", "Exigences"],
                 [["MNS (modèle numérique de surface)", "oui pour détecter",
                   "GeoTIFF ou COG, projection métrique (UTM…). C'est la grille de référence."],
                  ["MNT (modèle numérique de terrain)", "non",
                   "Même référence altimétrique que le MNS. Sans MNT, le sol est estimé sur 30 m autour de "
                   "chaque objet."],
                  ["Orthophoto", "recommandée", "RGB ou RGBA, 8 bits. Autre résolution ou projection acceptée."],
                  ["Parcelles", "recommandées", "GeoPackage ou Shapefile (fichier), géométries valides, un champ "
                   "identifiant unique (ex. PARCELLE)."]],
                 [48 * mm, 28 * mm, 94 * mm], bold_first=True)
    out += figure("01_donnees", "Figure 1 — Orthophoto et parcelles du jeu de démonstration chargées dans QGIS.",
                  width_mm=85)
    out += [p("Contrôles à faire dans QGIS", H2)]
    out += bullets([
        "<b>Projection</b> : Propriétés de la couche › Information. Le MNS doit être en mètres (UTM ou projection "
        "locale), jamais en degrés ; sinon reprojetez-le avec <i>Raster › Projections › Projection (warp)</i>.",
        "<b>Altitudes</b> : affichez MNS et MNT côte à côte avec l'outil Identifier. Sur un sol nu, les deux "
        "valeurs doivent être très proches. Un écart constant de plusieurs mètres trahit deux références "
        "différentes : corrigez avant toute campagne.",
        "<b>Parcelles</b> : <i>Vecteur › Outils de géométrie › Vérifier la validité</i>, puis <i>Réparer les "
        "géométries</i> si besoin. Vérifiez l'unicité de l'identifiant (table attributaire, tri sur le champ).",
        "<b>Emprise</b> : les parcelles et les rasters doivent se recouvrir ; un objet hors des rasters ne peut "
        "pas être détecté.",
    ])
    out += [p("Grands levés", H2)]
    out += bullets([
        "EADE lit les rasters par tuiles de 200 m : la taille du levé n'est pas un problème de mémoire.",
        "Préférez le format COG ou un GeoTIFF tuilé et compressé ; plusieurs dalles se rassemblent dans un "
        "raster virtuel (<i>Raster › Divers › Construire un raster virtuel</i>), que le plugin lit comme un "
        "seul fichier.",
        "Pour un premier essai, limitez-vous à quelques îlots avec le paramètre <b>Emprise</b> : une section "
        "entière se traite ensuite sans changement.",
    ])
    return out


def s_detect():
    out = [p("4. Détection rapide", H1)]
    out += [p("L'algorithme <b>Détecter les bâtiments (levé drone)</b> donne une couche de résultats sans créer de "
              "projet. C'est l'outil idéal pour un essai, un contrôle ponctuel ou un traitement par lots.")]
    out += figure("09_dialogue_detect", "Figure 2 — Fenêtre de l'algorithme de détection.", width_mm=120)
    out += table(["Paramètre", "Rôle"],
                 [["Modèle numérique de surface (MNS)", "Obligatoire. Grille de référence."],
                  ["Modèle numérique de terrain (MNT)", "Facultatif ; estimé à partir du MNS s'il manque."],
                  ["Orthophoto", "Facultative ; apporte couleur, végétation, ombre et texture."],
                  ["Parcelles, Identifiant de parcelle", "Rattachent chaque objet à sa parcelle et ajoutent les "
                   "mesures de contexte."],
                  ["Version de connaissance (JSON)", "Règles à appliquer. Vide : verdicts du moteur classique seuls."],
                  ["Emprise", "Limite le calcul à une zone (dessinée sur la carte ou prise d'une couche)."],
                  ["Objets détectés", "Couche de sortie : temporaire ou fichier (GeoPackage conseillé)."]],
                 [62 * mm, 108 * mm], bold_first=True)
    out += figure("02_detection", "Figure 3 — Résultat : orange retenu, gris pointillé écarté par le moteur "
                  "(l'arbre et la voiture).", width_mm=80)
    out += [p("Lire les résultats", H2)]
    out += table(["Champ", "Signification"],
                 [["decision", "ACCEPTED (retenu), REVIEW (en revue), REJECTED (écarté)"],
                  ["score", "Force de décision entre 0 et 1 ; ce n'est pas une probabilité"],
                  ["classic_ok, classic_why", "Verdict du moteur classique (1/0) et motif : SMALL (trop petit), "
                   "VEGETATION, LOW (trop bas)"],
                  ["rules", "Codes des règles de la version qui se sont déclenchées"],
                  ["measure", "Surface en m²"],
                  ["parcel_id", "Parcelle qui contient la plus grande part de l'objet"],
                  ["kn_version, fingerprint", "Version et empreinte de la connaissance appliquée"],
                  ["explain", "Explication complète en JSON (composantes, règles avec les valeurs lues, garde-fous)"]],
                 [44 * mm, 126 * mm], mono_cols=(0,))
    out += [p("Pour styler la couche comme l'atelier, utilisez une symbologie <b>Catégorisée</b> sur le champ "
              "<font name='Mono'>decision</font> : orange pour ACCEPTED, jaune pour REVIEW, contour gris "
              "pointillé sans remplissage pour REJECTED. L'outil <b>Identifier</b> affiche le champ "
              "<font name='Mono'>explain</font> d'un objet.")]
    return out


def s_campaign():
    out = [p("5. Projets et campagnes", H1)]
    out += [p("Un <b>projet EADE</b> est un fichier <font name='Mono'>.eade</font> qui conserve tout : campagnes, "
              "prédictions, corrections, exemples validés, versions de connaissance, évaluations et journal. Une "
              "<b>campagne</b> est une détection enregistrée dans ce projet ; c'est elle que l'atelier fait réviser.")]
    out += figure("10_dialogue_campagne", "Figure 4 — Fenêtre « Lancer une campagne dans un projet EADE ».",
                  width_mm=96)
    out += steps([
        "<b>Projet EADE</b> : choisissez un fichier .eade existant, ou tapez le chemin d'un nouveau fichier : il "
        "est créé au lancement.",
        "<b>Libellé</b> : un nom parlant, par exemple « Section HT – lot 1 ».",
        "Choisissez le MNS, le MNT et l'orthophoto, puis les <b>Parcelles</b>. Elles doivent provenir d'un "
        "fichier (GeoPackage, Shapefile) : la campagne mémorise son chemin.",
        "Laissez <b>Appliquer EADE</b> coché. La version active est figée au lancement : la publier ou la "
        "changer pendant la campagne n'a pas d'effet sur celle-ci.",
        "<b>Exécuter</b>. Une seule campagne tourne à la fois dans un projet. Le bouton <b>Annuler</b> arrête "
        "le calcul entre deux tuiles ; les objets déjà calculés restent enregistrés.",
    ])
    out += note("EADE n'est appliqué que s'il est <b>activé</b> dans le projet et qu'une <b>version est active</b> "
                "(chapitre 9). Sinon la campagne garde les verdicts du moteur classique : c'est le comportement "
                "voulu quand EADE est désactivé. Le journal de traitement indique ce qui a été appliqué.",
                g.BLUE, "Quand EADE s'applique-t-il ?")
    out += [p("Où ranger le projet", H2)]
    out += bullets([
        "Sur un <b>disque local</b> ou un disque attaché au poste. Un projet est une base SQLite : évitez de "
        "l'ouvrir depuis plusieurs postes à la fois à travers un partage réseau.",
        "Pour une équipe (plusieurs opérateurs et un expert en même temps), centralisez le projet sur un serveur "
        "EADE (<font name='Mono'>eade serve</font>) avec des jetons par rôle : voir le guide d'intégration.",
        "Sauvegardez le fichier .eade comme toute donnée de production (chapitre 11).",
    ])
    out += [p("Reprendre une campagne interrompue", H2)]
    out += [KeepTogether([
        p("Si QGIS est fermé ou plante pendant une campagne, elle passe à l'état « interrompue ». Pour la "
          "reprendre à la tuile suivante, sans doublon, utilisez la console Python (chapitre 9) :"),
        *code("""
ws = Workspace(r"D:\\songon\\songon.eade")
ws.run_campaign(moi, 3)          # 3 = numéro de la campagne interrompue
""")])]
    return out


def s_atelier():
    out = [p("6. Atelier de correction", H1)]
    out += [p("Ouvrez l'atelier avec l'icône EADE ou <b>Extensions › EADE › Atelier de correction</b>, puis "
              "choisissez le projet. L'atelier ajoute trois couches à la carte : les objets de la campagne, les "
              "contours corrigés et la couche de tracé « EADE – tracés ».")]
    left = figure("03_atelier_correction", "Figure 5 — L'atelier, onglet Correction.", width_mm=70,
                  max_height_mm=140, keep=False)
    right = [p("Se repérer", H3)] + bullets([
        "<b>Projet, Campagne</b> : le fichier .eade et la campagne à revoir.",
        "<b>File</b> : l'ordre de la file des parcelles.",
        "<b>Ligne d'état</b> : EADE actif ou non, mode, version active, utilisateur.",
        "<b>Liste du haut</b> : les parcelles à revoir, avec le nombre d'objets à revoir, en revue, en "
        "brouillon et déjà soumis.",
        "<b>Liste du milieu</b> : les objets de la parcelle, ceux en revue d'abord. Un clic sélectionne "
        "l'objet sur la carte.",
        "<b>Fiche</b> : qui a décidé quoi, le score, les règles déclenchées avec les valeurs lues, les règles "
        "non évaluables et les principales mesures.",
        "<b>Boutons</b> : les actions, avec leur touche entre crochets.",
    ]) + [p("Ordres de la file", H3)] + bullets([
        "<b>Incertitude</b> : d'abord les parcelles où le moteur n'a pas su trancher.",
        "<b>Aléatoire</b> : un échantillon qui inclut des cas faciles. À utiliser régulièrement : c'est ce qui "
        "mesure honnêtement la qualité.",
        "<b>Ordre</b> : dans l'ordre des identifiants de parcelle.",
    ])
    out += side_by_side(left, right, widths=(74, 96))
    out += [p("Couleurs de la carte", H2)]
    out += table(["Couleur", "Signification"],
                 [["<font color='#F07C1E'><b>Orange</b></font>", "Proposé par le moteur (retenu)"],
                  ["<font color='#E69600'><b>Jaune</b></font>", "En revue : le moteur ne tranche pas"],
                  ["<font color='#788291'><b>Gris pointillé</b></font>", "Écarté par le moteur (arbre, ombre…) ; "
                   "reste visible"],
                  ["<font color='#2F9E44'><b>Vert</b></font>", "Accepté ou corrigé par l'opérateur ; contours "
                   "ajoutés ou redessinés"],
                  ["<font color='#E03131'><b>Rouge</b></font>", "Rejeté ou reclassé par l'opérateur"],
                  ["<font color='#12B6D8'><b>Cyan</b></font>", "Tracé en cours sur la couche « EADE – tracés »"],
                  ["<font color='#C9A227'><b>Jaune clair</b></font>", "Limites de parcelles (votre propre couche)"]],
                 [40 * mm, 130 * mm])
    out += [p("Les actions", H2)]
    out += table(["Action", "Touche", "Quand"],
                 [["Accepter", "A", "Le contour et la classe sont justes"],
                  ["Rejeter", "R, puis le motif 1 à 8", "Ce n'est pas un objet de cette classe"],
                  ["Reclasser", "liste + bouton", "C'est une cour, de la végétation, une clôture…"],
                  ["Tracer", "bouton", "Commencer un contour sur la couche de tracé"],
                  ["Redessiner", "D", "Le contour est faux : remplacez-le par votre tracé"],
                  ["Manquant", "B", "Le moteur a oublié un objet : enregistrez votre tracé"],
                  ["Parcelle suivante / précédente", "N / P", "Naviguer dans la file"],
                  ["Soumettre la parcelle", "Ctrl+Entrée", "La parcelle est revue : envoi à l'expert"]],
                 [52 * mm, 40 * mm, 78 * mm], bold_first=True)
    out += note("les touches agissent quand l'atelier a le focus : cliquez dans l'atelier (par exemple sur la "
                "liste des objets) avant de les utiliser, sinon elles vont à la carte de QGIS.", WARN, "Raccourcis")
    out += [p("Motifs de rejet", H2)]
    out += table(["Touche", "Motif", "Touche", "Motif"],
                 [["1", "Cour ou dalle au sol", "5", "Appartient au voisin"],
                  ["2", "Végétation", "6", "Doublon"],
                  ["3", "Ombre", "7", "Chantier ou ruine"],
                  ["4", "Véhicule ou objet mobile", "8", "Autre"]],
                 [16 * mm, 69 * mm, 16 * mm, 69 * mm])
    out += [p("Le motif compte : c'est lui qui apprend au moteur pourquoi il s'est trompé.")]

    out += [p("Corriger une parcelle, pas à pas", H2)]
    out += steps([
        "Cliquez une parcelle dans la file : la carte se centre dessus et ses objets s'affichent.",
        "Pour chaque objet de la liste du milieu, lisez la fiche, regardez l'orthophoto, puis appliquez "
        "l'action. Le motif de rejet se choisit dans la liste à côté de <b>Rejeter</b> (ou avec les touches 1 à 8).",
        "Pour un contour faux : <b>Tracer</b>, dessinez le contour sur la carte (clic gauche pour chaque sommet, "
        "<b>clic droit</b> pour terminer), sélectionnez l'objet dans la liste, puis <b>Redessiner</b>.",
        "Pour un bâtiment oublié : <b>Tracer</b>, dessinez, choisissez la classe dans la liste, puis "
        "<b>Manquant</b>. Le contour est mesuré automatiquement sur les rasters de la campagne.",
        "Quand la parcelle est revue : <b>Soumettre la parcelle</b>. Les corrections partent à l'expert et ne "
        "sont plus modifiables ; la parcelle quitte la file.",
    ])
    out += side_by_side(
        figure("05_trace_manquant", "Figure 6 — Un bâtiment oublié tracé (cyan) avant enregistrement.",
               width_mm=80, keep=False),
        figure("06_apres_corrections", "Figure 7 — Après correction : accepté (vert), rejeté (rouge), "
               "ajouté (vert foncé).", width_mm=80, keep=False))
    out += [p("Bonnes pratiques", H2)]
    out += bullets([
        "Ne corrigez que ce que vous voyez nettement. Sous un arbre ou dans l'ombre, laissez en revue et "
        "signalez-le à l'équipe.",
        "Si un vrai bâtiment a été écarté par le moteur (gris pointillé), sélectionnez-le et <b>acceptez</b>-le.",
        "Passez régulièrement par la file <b>Aléatoire</b>.",
        "Une correction en brouillon se remplace : refaire une action sur le même objet remplace votre brouillon.",
    ])
    out += [p("Ce que l'atelier ne permet pas, volontairement : modifier une correction soumise ou validée, ou "
              "celle d'un collègue ; changer la proposition du moteur ; toucher aux valeurs cadastrales. "
              "Scinder et fusionner des objets ne sont pas encore dans l'atelier : utilisez la console "
              "(chapitre 9) ou l'API.", SMALL)]
    return out


def s_validation():
    out = [p("7. Valider les corrections", H1)]
    left = figure("08_atelier_validation", "Figure 8 — Onglet Validation : trois corrections soumises.",
                  width_mm=70, max_height_mm=140, keep=False)
    right = steps([
        "Ouvrez l'atelier, choisissez le projet et la campagne, puis l'onglet <b>Validation</b>.",
        "La liste montre chaque correction soumise : action, classe avant → après, surface avant → après, "
        "motif et auteur. Un clic centre la carte sur l'objet.",
        "Sélectionnez les corrections à juger (Ctrl ou Maj pour en prendre plusieurs).",
        "Saisissez une <b>justification</b> : elle est obligatoire et inscrite au journal.",
        "<b>Valider la sélection</b> ou <b>Rejeter la sélection</b>.",
    ]) + [Spacer(1, 6)] + bullets([
        "Validez ce qui est juste à l'orthophoto, pas « à peu près ». Une correction validée est définitive.",
        "En mode <b>collecte</b> ou <b>administration</b>, une correction validée devient un <b>exemple "
        "d'apprentissage</b> : une erreur validée apprend l'erreur.",
        "Une correction rejetée renvoie l'objet dans la file de l'opérateur.",
        "Chaque exemple est rangé dans une maille de 200 m ; une maille sur cinq est réservée au test et ne "
        "sert jamais à apprendre.",
    ])
    out += side_by_side(left, right, widths=(74, 96))
    out += note("celui qui corrige ne devrait pas valider ses propres corrections. Dans QGIS, sur un fichier "
                "local, l'atelier agit sous votre nom d'utilisateur Windows avec tous les droits : la séparation "
                "des rôles relève de l'organisation de l'équipe, ou d'un serveur EADE avec jetons par rôle. Le "
                "journal garde l'auteur de chaque geste.", WARN, "Séparer les rôles")
    return out


def s_quality():
    out = [p("8. Contrôle qualité", H1)]
    out += [p("Mesurer des emprises", H2)]
    out += [p("<b>Mesurer des emprises</b> calcule, pour chaque polygone d'une couche (tracé à la main, importé "
              "d'un autre logiciel…), les mêmes mesures que le moteur : surface, rectangularité, hauteurs, "
              "couleur, texture, ombre. Les colonnes s'ajoutent aux attributs. Utile pour comprendre une règle, "
              "comparer deux sources ou préparer de nouvelles règles.")]
    out += [p("Évaluer des détections", H2)]
    out += figure("11_dialogue_evaluer", "Figure 9 — Fenêtre de l'algorithme d'évaluation.", width_mm=120)
    out += [p("<b>Évaluer des détections</b> compare une couche de détections à une couche de contours de "
              "référence validés (par exemple une zone entièrement revue par un expert). Seuls les objets "
              "ACCEPTED sont comptés comme retenus ; un appariement exige un IoU d'au moins 0,5 par défaut.")]
    out += table(["Mesure", "Lecture", "Meilleur si"],
                 [["IoU moyen (MEAN_IOU)", "Recouvrement des détections justes, rapporté aux vrais positifs + "
                   "faux positifs + oublis. La mesure principale.", "plus haut"],
                  ["Précision (PRECISION)", "Part des objets retenus qui sont justes", "plus haut"],
                  ["Rappel (RECALL)", "Part des objets vrais retrouvés", "plus haut"],
                  ["Faux positifs", "Objets retenus à tort ou trop mal contourés", "plus bas"],
                  ["Oublis (MISSES)", "Objets vrais non retenus", "plus bas"]],
                 [42 * mm, 104 * mm, 24 * mm], bold_first=True)
    out += [p("Le rapport complet peut être écrit en JSON (paramètre <b>Rapport</b>). Sur le jeu de "
              "démonstration, les deux bâtiments sont retrouvés : précision 1, rappel 1, IoU moyen supérieur à "
              "0,85.")]
    return out


def s_admin():
    out = [p("9. Administrer depuis la console Python", H1)]
    out += [p("Les réglages du projet, les versions de connaissance, l'apprentissage et la publication n'ont pas "
              "encore d'écran dans le plugin. Ils se font depuis la <b>console Python de QGIS</b> "
              "(<i>Extensions › Console Python</i>), avec les mêmes contrôles que le serveur : permissions, "
              "justifications obligatoires, journal. Toutes les commandes ci-dessous ont été vérifiées dans "
              "QGIS 4.2.3.")]
    out += [p("Ouvrir un projet", H2)]
    out += code("""
from eade_qgis.bootstrap import ensure_eade; ensure_eade()
import getpass, json
from eade import Rule, Effect
from eade.store import Workspace, Actor, PERMISSIONS

moi = Actor(getpass.getuser(), frozenset(PERMISSIONS))
ws = Workspace(r"D:\\songon\\songon.eade")
ws.settings()                    # enabled, mode, active_version, critères de publication
ws.campaigns()                   # campagnes, état et décompte
""")
    out += [p("Activer EADE et choisir le mode", H2)]
    out += table(["Mode", "Les campagnes appliquent", "Les corrections validées", "Publication"],
                 [["désactivé", "Le moteur classique seul", "Sont enregistrées, sans apprentissage", "—"],
                  ["READ_ONLY", "Classique + version active", "Sont enregistrées, sans apprentissage", "Manuelle"],
                  ["COLLECT", "Classique + version active", "Deviennent des exemples", "Manuelle"],
                  ["ADMIN", "Classique + version active", "Deviennent des exemples", "Évaluée ou manuelle"]],
                 [24 * mm, 46 * mm, 56 * mm, 44 * mm], bold_first=True)
    out += code("""
ws.update_settings(moi, "Pilote Songon", enabled=True, mode="COLLECT")
""")
    out += [p("Écrire des règles", H2)]
    out += code("""
v = ws.new_draft(moi, None, "Règles du pilote")         # ou new_draft(moi, 2, ...) : copie de la v2
v = v.with_rule(Rule("OMBRE", "BUILDING", Effect.ABSTAIN,
                     {"feature": "shadow_share", "op": ">=", "value": 0.5},
                     label="Emprise surtout dans l'ombre"))
ws.save_draft(moi, v, "Couleur illisible dans l'ombre")
""")
    out += [p("Effets : <font name='Mono'>CONFIRM</font> (augmente le score), <font name='Mono'>REJECT</font> "
              "(le diminue ; <font name='Mono'>blocking=True</font> écarte quoi qu'il arrive), "
              "<font name='Mono'>ABSTAIN</font> (renvoie en revue), <font name='Mono'>RECLASSIFY</font> "
              "(change la classe, avec <font name='Mono'>result_class=</font>). Les noms de mesures sont ceux du "
              "dictionnaire (guide d'intégration, section 11) ; une règle qui cite une mesure inconnue est "
              "refusée. Importer une version exportée : <font name='Mono'>ws.import_version(moi, "
              "json.load(open(chemin, encoding=\"utf-8\")))</font>.")]
    out += [p("Simuler, apprendre, évaluer, publier", H2)]
    out += code("""
ws.simulate(moi, v.number, 1)                 # rejoue sur la campagne 1, n'écrit rien
cand, rapport = ws.build_candidate(moi)       # brouillon appris des exemples validés
r = ws.evaluate(moi, cand.number)             # sur les mailles de test
r["verdict"]["accepted"], r["verdict"]["checks"]

ws.update_settings(moi, "Publication de la v3", mode="ADMIN")
ws.publish(moi, cand.number, "Gain IoU +0,04 sur 120 objets de test")
ws.publish(moi, v.number, "Mise en service des règles expertes du pilote", manual=True)
""")
    out += [p("Une publication <b>évaluée</b> exige le mode ADMIN et une évaluation acceptée de la version dans "
              "son état actuel : gain d'IoU d'au moins 0,02 sur 20 objets de test au minimum, sans hausse des "
              "faux positifs ni de l'erreur de surface. La publication <b>manuelle</b> passe outre ; elle exige "
              "15 caractères de justification et garde au journal l'état de la dernière évaluation.")]
    out += [p("Revenir en arrière, arrêter en urgence, consulter le journal", H2)]
    out += code("""
ws.rollback(moi, 2, "La v3 renvoie trop d'objets en revue")   # réactive la v2
ws.emergency_stop(moi, "Décisions manifestement fausses")     # désactive EADE immédiatement
for a in ws.audit(20):
    print(a["at"], a["actor"], a["action"], a["entity_id"], a["justification"])
ws.close()
""")
    out += [p("Scinder et fusionner (en attendant l'atelier)", H2)]
    out += code("""
from eade_qgis.compat import to_shapely
morceaux = [to_shapely(f.geometry()) for f in iface.activeLayer().selectedFeatures()]
# 1542 = numéro de la prédiction, 1 = numéro de la campagne
ws.split(moi, 1542, morceaux, [ws.measure(1, g) for g in morceaux])
ws.merge(moi, [1543, 1544], morceaux[0], ws.measure(1, morceaux[0]))
""")
    return out


def s_automate():
    out = [p("10. Automatiser", H1)]
    out += [p("Les quatre algorithmes EADE sont des algorithmes de traitement QGIS ordinaires : ils s'utilisent "
              "dans le <b>modeleur graphique</b>, en <b>traitement par lots</b> (bouton « Exécuter comme "
              "processus de lot » de chaque fenêtre) et depuis la console Python.")]
    out += code("""
import processing
for section in ["HT", "HU", "HV"]:
    res = processing.run("eade:campaign", {
        "WORKSPACE": r"D:\\songon\\songon.eade", "LABEL": f"Section {section}",
        "DSM": rf"D:\\songon\\{section}\\mns.tif", "DTM": rf"D:\\songon\\{section}\\mnt.tif",
        "ORTHO": rf"D:\\songon\\{section}\\ortho.tif",
        "PARCELS": r"D:\\songon\\parcelles.gpkg", "PARCEL_ID": "PARCELLE",
        "OUTPUT": rf"D:\\songon\\{section}\\predictions.gpkg"})
    print(section, res["CAMPAIGN"])
""")
    out += table(["Algorithme", "Identifiant", "Sorties"],
                 [["Détecter les bâtiments (levé drone)", "eade:detect", "OUTPUT, ACCEPTED, REVIEW, REJECTED"],
                  ["Mesurer des emprises", "eade:measure", "OUTPUT"],
                  ["Évaluer des détections", "eade:evaluate", "MEAN_IOU, PRECISION, RECALL, FALSE_POSITIVES, "
                   "MISSES, REPORT"],
                  ["Lancer une campagne dans un projet EADE", "eade:campaign", "OUTPUT, CAMPAIGN"]],
                 [62 * mm, 30 * mm, 78 * mm], mono_cols=(1,))
    return out


def s_operations():
    out = [p("11. Exploitation courante", H1)]
    out += [p("Sauvegarde", H2)]
    out += bullets([
        "Le projet est un seul fichier <font name='Mono'>.eade</font> : copiez-le quand QGIS ne l'utilise pas "
        "(atelier fermé, aucune campagne en cours). Les fichiers <font name='Mono'>.eade-wal</font> et "
        "<font name='Mono'>.eade-shm</font> qui l'accompagnent pendant l'utilisation disparaissent à la fermeture.",
        "Les rasters et les parcelles se sauvegardent à part ; la campagne mémorise leurs chemins : ne les "
        "déplacez pas tant que la campagne est en révision, sinon les tracés ne pourront plus être mesurés.",
        "Exportez les versions publiées en JSON (<font name='Mono'>ws.export_version</font>) : elles se "
        "réimportent dans n'importe quel projet.",
    ])
    out += [p("Garanties", H2)]
    out += bullets([
        "Une prédiction ne change jamais : une correction s'enregistre à côté.",
        "Une version publiée, un exemple validé et une correction jugée sont figés ; le journal ne peut être ni "
        "modifié ni effacé, même en ouvrant le fichier avec un autre outil.",
        "Chaque prédiction garde la version qui l'a produite : après un retour arrière, on sait exactement "
        "quels objets revoir.",
    ])
    out += [p("Routine conseillée", H2)]
    out += table(["Quand", "Qui", "Quoi"],
                 [["Chaque jour", "Opérateurs", "File par incertitude, puis un passage en file aléatoire ; "
                   "soumettre chaque parcelle revue"],
                  ["Chaque jour", "Expert", "Onglet Validation : vider la liste des corrections soumises"],
                  ["Chaque semaine", "Responsable qualité", "Simuler la version active et la candidate sur la "
                   "dernière campagne ; évaluer"],
                  ["À chaque version", "Responsable EADE", "Publier seulement si l'évaluation est acceptée ; "
                   "noter la justification ; exporter la version"],
                  ["À chaque fin de lot", "Responsable EADE", "Sauvegarder le .eade ; relire le journal"]],
                 [32 * mm, 38 * mm, 100 * mm], bold_first=True)
    return out


def s_troubleshooting():
    out = [p("12. Dépannage", H1)]
    out += table(["Symptôme", "Cause et solution"],
                 [["Le plugin n'apparaît pas", "Activez-le dans Extensions › Installées ; cochez « Afficher les "
                   "extensions expérimentales »."],
                  ["« Les rasters doivent être dans une projection métrique »", "Le MNS est en degrés : "
                   "reprojetez-le (UTM)."],
                  ["« Un modèle numérique de surface (MNS) est requis »", "La détection par hauteur exige un MNS."],
                  ["« Les parcelles doivent provenir d'un fichier »", "Pour une campagne, enregistrez la couche de "
                   "parcelles en GeoPackage."],
                  ["« a campaign is already running »", "Une seule campagne à la fois par projet ; attendez ou "
                   "annulez-la."],
                  ["Campagne « interrompue »", "QGIS a été fermé pendant le calcul : reprenez-la depuis la console "
                   "(chapitre 5)."],
                  ["La campagne n'apparaît pas dans l'atelier", "L'atelier ne liste que les campagnes terminées, "
                   "annulées ou interrompues qui contiennent des objets."],
                  ["Les touches A, R, D… ne font rien", "Cliquez dans l'atelier pour lui donner le focus."],
                  ["« Tracez d'abord le contour avec Tracer »", "Terminez le polygone par un clic droit avant "
                   "Redessiner ou Manquant."],
                  ["« the new outline is more than 30 m away »", "Le tracé est trop loin de l'objet : utilisez "
                   "Manquant pour un objet ailleurs."],
                  ["« a rejection needs a reason »", "Choisissez un motif (touches 1 à 8) avant Rejeter."],
                  ["« justification is required »", "Saisissez la justification avant de valider ou rejeter."],
                  ["« the campaign rasters cannot be read »", "Les rasters ont été déplacés ou le disque n'est pas "
                   "monté : rétablissez les chemins de la campagne."],
                  ["Peu d'objets détectés", "Vérifiez la référence altimétrique MNS/MNT ; sans MNT, les très grands "
                   "bâtiments peuvent être sous-estimés."]],
                 [64 * mm, 106 * mm], bold_first=True)
    out += [p("Limites de la version actuelle", H2)]
    out += bullets([
        "Les réglages, versions, l'apprentissage et la publication se font par la console (chapitre 9).",
        "Scinder et fusionner : par la console ou l'API en attendant leur bouton dans l'atelier.",
        "L'atelier travaille sur un fichier local ; la connexion à un serveur EADE multi-utilisateurs est à venir.",
        "Les seuils du détecteur sont réglés sur données de synthèse : à calibrer sur vos levés réels.",
    ])
    return out


def build(path: Path) -> Path:
    g.load_fonts(ROOT / "build" / "fonts")
    story = cover() + toc()
    for section in (s_roles, s_install, s_data, s_detect, s_campaign, s_atelier, s_validation, s_quality,
                    s_admin, s_automate, s_operations, s_troubleshooting):
        story += section()
        story.append(PageBreak())
    story.pop()
    if g.TOO_LONG:
        raise ValueError("code lines too long for the page:\n" + "\n".join(g.TOO_LONG))
    g.Guide(path, header="GUIDE D'EXPLOITATION EADE · QGIS", title="Guide d'exploitation EADE dans QGIS",
            subject="Utiliser le plugin EADE dans QGIS").multiBuild(story)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=str(ROOT / "docs" / "EADE_Guide_exploitation_QGIS.pdf"))
    out = build(Path(ap.parse_args(argv).output))
    print(f"guide written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

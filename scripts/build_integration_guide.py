"""Build the EADE integration guide (PDF, French).

    python scripts/build_integration_guide.py [-o docs/EADE_Guide_integration.pdf]

Needs reportlab (pip install reportlab). The IBM Plex fonts (SIL Open Font
License) are downloaded once into build/fonts. API routes and the feature
dictionary are read from the code, so the guide follows the implementation.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageBreak,  # noqa: E402
                                PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

import eade  # noqa: E402

FONTS = {
    "Plex": "https://github.com/IBM/plex/raw/master/packages/plex-sans/fonts/complete/ttf/IBMPlexSans-Regular.ttf",
    "Plex-Bold": "https://github.com/IBM/plex/raw/master/packages/plex-sans/fonts/complete/ttf/IBMPlexSans-Bold.ttf",
    "Plex-Semi": "https://github.com/IBM/plex/raw/master/packages/plex-sans/fonts/complete/ttf/IBMPlexSans-SemiBold.ttf",
    "Plex-Italic": "https://github.com/IBM/plex/raw/master/packages/plex-sans/fonts/complete/ttf/IBMPlexSans-Italic.ttf",
    "Mono": "https://github.com/google/fonts/raw/main/ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
    "Mono-Medium": "https://github.com/google/fonts/raw/main/ofl/ibmplexmono/IBMPlexMono-Medium.ttf",
}

NAVY = colors.HexColor("#0B2551")
BLUE = colors.HexColor("#1F6FD6")
CYAN = colors.HexColor("#12B6D8")
SOFT = colors.HexColor("#46597A")
LINE = colors.HexColor("#D6DFEA")
PAPER = colors.HexColor("#F2F5F9")
WARN = colors.HexColor("#B26A00")
OK = colors.HexColor("#138A5B")


def load_fonts(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        path = cache / (url.rsplit("/", 1)[1])
        if not path.exists():
            urllib.request.urlretrieve(url, path)
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily("Plex", normal="Plex", bold="Plex-Bold", italic="Plex-Italic",
                                  boldItalic="Plex-Bold")


# ---------------------------------------------------------------- styles

def S(name, **kw) -> ParagraphStyle:
    base = dict(fontName="Plex", fontSize=9.6, leading=14.2, textColor=NAVY, alignment=TA_LEFT)
    base.update(kw)
    return ParagraphStyle(name, **base)


BODY = S("body", spaceAfter=5)
SMALL = S("small", fontSize=8.4, leading=11.8, textColor=SOFT)
H1 = S("h1", fontName="Plex-Bold", fontSize=19, leading=23, spaceBefore=4, spaceAfter=10, keepWithNext=1)
TOC_TITLE = S("toctitle", fontName="Plex-Bold", fontSize=19, leading=23, spaceAfter=10)
H2 = S("h2", fontName="Plex-Semi", fontSize=12.4, leading=16, spaceBefore=12, spaceAfter=5, textColor=BLUE, keepWithNext=1)
H3 = S("h3", fontName="Plex-Semi", fontSize=10.2, leading=14, spaceBefore=8, spaceAfter=3, keepWithNext=1)
EYEBROW = S("eyebrow", fontName="Mono-Medium", fontSize=8, leading=10, textColor=BLUE, spaceAfter=4)
BULLET = S("bullet", leftIndent=12, bulletIndent=2, spaceAfter=2.5)
CELL = S("cell", fontSize=8.4, leading=11.2)
CELL_B = S("cellb", fontName="Plex-Semi", fontSize=8.4, leading=11.2)
CELL_M = S("cellm", fontName="Mono", fontSize=7.8, leading=10.6)
HEAD = S("head", fontName="Plex-Semi", fontSize=8, leading=10.4, textColor=colors.white)
CODE = S("code", fontName="Mono", fontSize=7.4, leading=10.2, textColor=NAVY)
CODE_MAX_WIDTH = 170 * mm - 9 - 6 - 4  # frame width minus the code box paddings and a margin
TOO_LONG: list[str] = []
TOC1 = S("toc1", fontName="Plex-Semi", fontSize=9.6, leading=13.8)
TOC2 = S("toc2", fontSize=8.6, leading=11.0, leftIndent=14, textColor=SOFT)


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def p(text, style=BODY):
    return Paragraph(text, style)


def bullets(items, style=BULLET):
    return [Paragraph(t, style, bulletText="•") for t in items]


def code(text: str):
    text = text.strip("\n")
    TOO_LONG.extend(line for line in text.splitlines()
                    if pdfmetrics.stringWidth(line, CODE.fontName, CODE.fontSize) > CODE_MAX_WIDTH)
    pre = Preformatted(text, CODE)
    t = Table([[pre]], colWidths=[None])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PAPER),
                           ("LINEBEFORE", (0, 0), (0, -1), 2, CYAN),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return [t, Spacer(1, 6)]


def note(text: str, colour=BLUE, title="À retenir"):
    t = Table([[p(f"<font name='Plex-Semi'>{title}.</font> {text}", S("n", fontSize=9, leading=13))]])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.Color(colour.red, colour.green, colour.blue, 0.07)),
                           ("LINEBEFORE", (0, 0), (0, -1), 2.5, colour),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return [Spacer(1, 3), t, Spacer(1, 8)]


def table(header, rows, widths, mono_cols=(), bold_first=False, pad=3.5):
    data = [[p(h, HEAD) for h in header]]
    for r in rows:
        line = []
        for i, c in enumerate(r):
            st = CELL_M if i in mono_cols else (CELL_B if bold_first and i == 0 else CELL)
            line.append(p(c if i not in mono_cols else esc(c), st))
        data.append(line)
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
    ]))
    return [t, Spacer(1, 8)]


# -------------------------------------------------------------- document

class Guide(BaseDocTemplate):
    def __init__(self, path, header="GUIDE D'INTÉGRATION EADE", title="Guide d'intégration EADE",
                 subject="Intégrer le moteur de détection adaptatif EADE", **kw):
        super().__init__(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                         topMargin=22 * mm, bottomMargin=20 * mm, title=title,
                         author="GENI Digital", subject=subject, creator="EADE guide builder", **kw)
        self.header = header
        w, h = A4
        cover = Frame(0, 0, w, h, leftPadding=24 * mm, rightPadding=24 * mm, topPadding=30 * mm, bottomPadding=20 * mm,
                      id="cover")
        body = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates([PageTemplate("cover", [cover], onPage=self._cover_bg),
                               PageTemplate("body", [body], onPage=self._decorate)])
        self._h1 = 0

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name in ("h1", "h2"):
            level = 0 if f.style.name == "h1" else 1
            text = f.getPlainText()
            key = f"s{id(f)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level == 0)
            self.notify("TOCEntry", (level, text, self.page, key))

    @staticmethod
    def _cover_bg(canv, doc):
        w, h = A4
        canv.saveState()
        canv.setFillColor(colors.HexColor("#F4F7FA"))
        canv.rect(0, 0, w, h, stroke=0, fill=1)
        canv.setStrokeColor(colors.Color(0.12, 0.44, 0.84, 0.08))
        canv.setLineWidth(0.5)
        step = 12 * mm
        x = 0
        while x < w:
            canv.line(x, 0, x, h)
            x += step
        y = 0
        while y < h:
            canv.line(0, y, w, y)
            y += step
        canv.setFillColor(NAVY)
        canv.rect(0, 0, w, 16 * mm, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont("Plex", 8)
        canv.drawString(24 * mm, 6.5 * mm, "EADE · eFoncier Adaptive Detection Engine · github.com/genidigital/EADE")
        canv.restoreState()

    @staticmethod
    def _decorate(canv, doc):
        w, h = A4
        canv.saveState()
        canv.setStrokeColor(LINE)
        canv.setLineWidth(0.6)
        canv.line(20 * mm, h - 14 * mm, w - 20 * mm, h - 14 * mm)
        canv.setFont("Mono", 7.4)
        canv.setFillColor(SOFT)
        canv.drawString(20 * mm, h - 11.5 * mm, doc.header)
        canv.drawRightString(w - 20 * mm, h - 11.5 * mm, f"version {eade.__version__}")
        canv.line(20 * mm, 13 * mm, w - 20 * mm, 13 * mm)
        canv.drawString(20 * mm, 9 * mm, "GENI Digital · document de travail, susceptible d'évoluer avec le code")
        canv.drawRightString(w - 20 * mm, 9 * mm, str(doc.page))
        canv.restoreState()


# --------------------------------------------------------------- content

def cover():
    logo = Image(str(ROOT / "docs" / "assets" / "eade-logo.png"), width=62 * mm, height=62 * mm * 445 / 482)
    logo.hAlign = "LEFT"
    today = date.today()
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
              "novembre", "décembre"]
    return [
        logo, Spacer(1, 22 * mm),
        p("GUIDE D'INTÉGRATION", S("c0", fontName="Mono-Medium", fontSize=10, textColor=BLUE, leading=14)),
        Spacer(1, 3 * mm),
        p("Intégrer EADE dans vos applications et vos outils SIG",
          S("c1", fontName="Plex-Bold", fontSize=27, leading=33)),
        Spacer(1, 6 * mm),
        p("Bibliothèque Python, ligne de commande, API REST, OGC API Features, plugin QGIS et fichier projet : "
          "comment brancher le moteur de détection adaptatif EADE, l'alimenter, exploiter ses décisions et "
          "gouverner son apprentissage.", S("c2", fontSize=11.5, leading=17, textColor=SOFT)),
        Spacer(1, 30 * mm),
        table(["Version du moteur", "Date", "Public"],
              [[eade.__version__, f"{today.day} {months[today.month - 1]} {today.year}",
                "Développeurs, intégrateurs SIG, administrateurs"]],
              [45 * mm, 40 * mm, 77 * mm])[0],
        NextPageTemplate("body"), PageBreak(),
    ]


def toc():
    t = TableOfContents()
    t.levelStyles = [TOC1, TOC2]
    t.dotsMinLevel = 0
    return [p("Sommaire", TOC_TITLE), t, PageBreak()]


def section_overview():
    out = [p("1. EADE en bref", H1)]
    out += [p("EADE (eFoncier Adaptive Detection Engine) est un moteur de décision explicable. Il ne dessine pas : "
              "il <b>juge des candidats</b> proposés par un fournisseur de détection (le « moteur classique »), "
              "mesure chacun d'eux, applique les règles d'une <b>version de connaissance</b>, les compare aux cas "
              "déjà validés par des experts, et rend une décision accompagnée de son explication complète.")]
    out += table(["Décision", "Condition", "Ce qu'en fait l'application hôte"],
                 [["<font color='#1F6FD6'><b>ACCEPTED</b></font> (retenu)", "score ≥ seuil d'acceptation (0,60)",
                   "Proposer l'objet ; il reste à revoir avant toute promotion métier."],
                  ["<font color='#B26A00'><b>REVIEW</b></font> (en revue)", "entre les deux seuils",
                   "Le moteur s'abstient : un opérateur décide. À traiter en premier."],
                  ["<font color='#46597A'><b>REJECTED</b></font> (écarté)", "score ≤ seuil de rejet (0,35)",
                   "Masquer par défaut, garder consultable."]],
                 [38 * mm, 50 * mm, 82 * mm])
    out += [p("Le score est une <b>force de décision</b>, pas une probabilité : c'est la moyenne pondérée des "
              "composantes disponibles (verdict du moteur classique, règles pondérées, similarité aux cas validés, "
              "rampes de caractéristiques comme la hauteur). Trois garde-fous s'appliquent ensuite : une règle "
              "bloquante écarte quoi qu'il arrive ; une règle d'abstention renvoie en revue ; un candidat rejeté "
              "par le moteur classique ne dépasse jamais la revue.")]
    out += [p("Principes d'intégration", H2)]
    out += bullets([
        "<b>Optionnel.</b> EADE désactivé, l'application garde son moteur classique tel quel. Aucune écriture hors "
        "des données d'EADE : ni barème, ni valeur cadastrale, ni parcelle.",
        "<b>Explicable.</b> Chaque décision porte sa trace JSON : composantes, règles déclenchées avec les valeurs "
        "lues, règles non évaluables, garde-fous, version et empreinte de la connaissance.",
        "<b>Gouverné.</b> L'apprentissage ne part que de corrections validées par un expert, produit toujours un "
        "brouillon, et une version n'est publiée qu'après évaluation sur un jeu de test indépendant.",
        "<b>Interopérable.</b> GeoTIFF/COG, GeoPackage, GeoJSON, Shapefile via GDAL ; REST/JSON ; OGC API Features.",
    ])
    out += note("ce guide décrit la version de développement du moteur (branche <font name='Mono'>feat/core-engine</font> "
                "du dépôt). Les interfaces peuvent encore évoluer avant la version 1.0 ; la licence du code sera "
                "publiée avant la première version.", WARN, "Statut")
    return out


def section_modes():
    out = [p("2. Choisir son mode d'intégration", H1)]
    out += [p("Les six formes ci-dessous partagent le même moteur, le même format de connaissance et donnent "
              "exactement les mêmes décisions. On les combine librement : un serveur pour la plateforme web, le "
              "plugin pour les opérateurs SIG, la bibliothèque pour les traitements de masse.")]
    out += table(["Forme", "Pour qui, pour quoi", "Point d'entrée"],
                 [["Bibliothèque Python", "Intégrer le moteur dans un traitement, un notebook, un autre logiciel ; "
                   "brancher son propre détecteur.", "<font name='Mono'>import eade</font>"],
                  ["Ligne de commande", "Scripts, traitements par lots, chaînes de production.",
                   "<font name='Mono'>eade …</font>"],
                  ["API REST", "Plateformes web et applications métier (Java, .NET, PHP, JavaScript…), "
                   "multi-utilisateurs avec permissions.", "<font name='Mono'>eade serve</font> → /api/v1"],
                  ["OGC API Features", "Afficher les prédictions dans QGIS, ArcGIS, MapLibre, Leaflet, OpenLayers "
                   "sans code.", "/ogc/collections"],
                  ["Plugin QGIS", "Opérateurs et experts SIG : détection, mesure, évaluation, atelier de "
                   "correction et de validation dans QGIS 3.34+ et 4.x.", "eade_qgis-x.y.z.zip"],
                  ["Fichier projet .eade", "Un projet complet et portable (SQLite) : campagnes, corrections, "
                   "exemples, versions, journal.", "<font name='Mono'>eade.store.Workspace</font>"]],
                 [34 * mm, 92 * mm, 44 * mm], bold_first=True)
    out += [p("Arbre de décision rapide", H2)]
    out += bullets([
        "Votre application n'est pas en Python, ou plusieurs utilisateurs travaillent en même temps → <b>API REST</b>.",
        "Vous voulez seulement voir les résultats sur une carte → <b>OGC API Features</b>.",
        "Vos opérateurs travaillent dans QGIS → <b>plugin QGIS</b> (sur un fichier .eade partagé ou local).",
        "Vous écrivez un traitement ou votre propre détecteur en Python → <b>bibliothèque</b>.",
    ])
    return out


def section_install():
    out = [p("3. Installation", H1)]
    out += [p("Prérequis : Python 3.10 ou plus récent. Le cœur n'a aucune dépendance ; les capacités s'ajoutent "
              "par « extras » pip.")]
    out += table(["Extra", "Apporte", "Dépendances"],
                 [["(aucun)", "Cœur : règles, décision, versions, apprentissage, évaluation, CLI <font name='Mono'>"
                   "eade knowledge|decide</font>", "aucune"],
                  ["<font name='Mono'>geo</font>", "Rasters, vecteurs, détection, 37 caractéristiques, projet .eade",
                   "numpy, scipy, rasterio, shapely, pyproj, pyogrio"],
                  ["<font name='Mono'>server</font>", "API REST et OGC API Features (inclut geo)",
                   "fastapi, uvicorn"],
                  ["<font name='Mono'>dev</font>", "Tests", "pytest, httpx"]],
                 [24 * mm, 86 * mm, 60 * mm])
    out += code("""
# depuis un clone du dépôt
git clone https://github.com/genidigital/EADE.git && cd EADE
python -m venv .venv && .venv\\Scripts\\activate        # Windows (source .venv/bin/activate ailleurs)
pip install -e ".[server]"                            # cœur + géospatial + serveur
eade --version

# ou directement depuis GitHub, sans clone
pip install "eade[geo] @ git+https://github.com/genidigital/EADE.git@feat/core-engine"
""")
    out += [p("Accès aux rasters : rasterio ou GDAL", H2)]
    out += [p("<font name='Mono'>eade.geo</font> lit les rasters avec rasterio s'il est installé, sinon avec les "
              "liaisons Python de GDAL (<font name='Mono'>osgeo</font>) déjà présentes dans QGIS ou ArcGIS Pro. "
              "On n'installe donc jamais une seconde copie de GDAL dans ces logiciels. Pour forcer un choix : "
              "variable d'environnement <font name='Mono'>EADE_RASTER_BACKEND=rasterio</font> ou "
              "<font name='Mono'>gdal</font>.")]
    out += note("EADE n'est pas encore publié sur PyPI. Tant que ce n'est pas le cas, installez depuis le dépôt "
                "et épinglez un commit précis en production.", BLUE, "Distribution")
    return out


def section_concepts():
    out = [p("4. Concepts et données", H1)]
    out += table(["Terme", "Définition"],
                 [["Candidat", "Objet proposé par un fournisseur de détection, avec son verdict propre "
                   "(<font name='Mono'>classic_accepted</font>) et ses mesures. EADE ne juge que des candidats."],
                  ["Caractéristique", "Mesure déclarée dans un dictionnaire (type, unité, normalisation). "
                   "Le cœur ignore ce qu'elle signifie."],
                  ["Règle", "Condition JSON + effet : CONFIRM, REJECT (éventuellement bloquante), ABSTAIN, "
                   "RECLASSIFY. Priorité, poids de 0 à 1, origine EXPERT ou LEARNED."],
                  ["Version de connaissance", "Réglages de fusion, profils, règles, signatures. Statuts DRAFT → "
                   "CANDIDATE → PUBLISHED → ARCHIVED. Une version publiée est figée."],
                  ["Empreinte", "SHA-256 de tout ce qui influe sur les décisions. Renommer une règle ne la change "
                   "pas ; modifier un seuil, si. C'est elle que l'évaluation certifie."],
                  ["Signature", "Portrait moyen (moyennes, écarts) des exemples validés d'une classe, positifs ou "
                   "négatifs ; sert à la similarité."],
                  ["Exemple", "Correction validée par un expert, avec ses mesures : matière de l'apprentissage "
                   "et du test."],
                  ["Maille", "Carré UTM de 200 m. Une maille sur cinq est réservée au test, de façon "
                   "déterministe et définitive."],
                  ["Profil", "Contexte (zone, résolution…) dans lequel des règles et signatures particulières "
                   "s'appliquent."]],
                 [34 * mm, 136 * mm], bold_first=True)
    out += [p("Données géospatiales en entrée", H2)]
    out += bullets([
        "<b>MNS</b> (modèle numérique de surface) : obligatoire pour la détection par hauteur ; c'est la grille de "
        "référence.",
        "<b>MNT</b> (terrain) : facultatif ; sans lui, le sol est estimé à partir du MNS (ouverture "
        "morphologique sur 30 m).",
        "<b>Orthophoto</b> RGB ou RGBA : facultative mais recommandée (couleur, végétation, ombre, texture).",
        "<b>Parcelles</b> : facultatives ; elles ajoutent les caractéristiques de contexte et le rattachement "
        "de chaque objet à sa parcelle.",
        "Projection <b>métrique</b> obligatoire pour la grille de référence (UTM par exemple). Les autres rasters "
        "peuvent avoir une autre résolution ou projection : ils sont rééchantillonnés à la volée.",
        "Les rasters sont lus par tuiles de 200 m avec 25 m de recouvrement : une orthophoto géante n'est jamais "
        "chargée entière, et un objet à cheval sur deux tuiles sort une seule fois.",
    ])
    out += [p("Couche de résultats", H2)]
    out += table(["Champ", "Contenu"],
                 [["candidate_id", "Identifiant stable du candidat (dérivé de son centroïde)"],
                  ["class / final_class", "Classe proposée / classe après reclassement éventuel"],
                  ["decision, score", "ACCEPTED, REVIEW ou REJECTED ; score 0–1 (vide si aucune preuve)"],
                  ["classic_accepted, classic_reason", "Verdict du moteur classique et motif (SMALL, VEGETATION, LOW)"],
                  ["rules_fired", "Codes des règles déclenchées"],
                  ["measure", "Surface (m²) ou longueur (m)"],
                  ["parcel_id", "Parcelle qui contient la plus grande part de l'objet"],
                  ["knowledge_version, fingerprint", "Version et empreinte de la connaissance appliquée"],
                  ["explanation", "Trace JSON complète de la décision"]],
                 [52 * mm, 118 * mm], mono_cols=(0,))
    return out


def section_python():
    out = [p("5. Intégration en Python", H1)]
    out += [p("5.1 Le moteur seul, pour n'importe quel domaine", H2)]
    out += [p("Le cœur ne connaît ni parcelle ni raster. Déclarez vos caractéristiques, écrivez une version et "
              "soumettez des candidats :")]
    out += code("""
from eade import Candidate, Effect, Engine, FeatureCatalog, FeatureDef, KnowledgeVersion, Rule

catalog = FeatureCatalog([
    FeatureDef("amount", label="Montant", unit="XOF"),
    FeatureDef("signed", dtype="boolean", label="Signé"),
])
version = KnowledgeVersion(number=1, rules=(
    Rule("UNSIGNED", "INVOICE", Effect.ABSTAIN, {"feature": "signed", "op": "=", "value": False}),
))
engine = Engine(version, catalog)          # refuse une règle qui cite une caractéristique inconnue
r = engine.decide(Candidate("doc-42", "INVOICE", {"amount": 125000, "signed": False},
                            classic_accepted=True))
r.decision            # Decision.REVIEW
r.guardrails          # ('ABSTAIN_RULE:UNSIGNED',)
r.explanation()       # dict JSON : composantes, règles, garde-fous, version, empreinte
""")
    out += [p("5.2 Détection sur un levé drone", H2)]
    out += code("""
from eade.geo import GeoPipeline, RasterSources
from eade.geo.vector import write_results
from eade.io import knowledge_json

version = knowledge_json.load("connaissance.json")        # ou None : verdicts classiques seuls
run = GeoPipeline(version).run(
    RasterSources(dsm="mns.tif", dtm="mnt.tif", ortho="ortho.tif"),
    bounds=None,                                         # (xmin, ymin, xmax, ymax), SCR du MNS
    parcels="parcelles.gpkg", parcel_id_field="PARCELLE",
    progress=lambda done, total: True)                   # renvoyer False interrompt entre deux tuiles
run.counts()          # {'ACCEPTED': …, 'REVIEW': …, 'REJECTED': …}
run.provenance        # sources, détecteur, moteur raster, version et empreinte
write_results("predictions.gpkg", run.results, run.crs, extra=["parcel_id"])
""")
    out += [p("5.3 Brancher son propre détecteur", H2)]
    out += [p("Tout fournisseur qui produit des <font name='Mono'>Candidate</font> s'intègre : moteur de la "
              "plateforme hôte, réseau de neurones, import d'un autre logiciel. Renvoyez aussi les candidats "
              "que votre moteur rejette (<font name='Mono'>classic_accepted=False</font>) : EADE pourra envoyer en "
              "revue un rejet douteux. Mesurez-les avec l'extracteur EADE Geo pour bénéficier des règles et "
              "signatures existantes :")]
    out += code("""
from eade import Candidate, Engine
from eade.geo import GeoFeatureExtractor, RasterSources, geo_catalog

extractor, engine = GeoFeatureExtractor(), Engine(version, geo_catalog())
with RasterSources(dsm="mns.tif", ortho="ortho.tif").open() as src:
    for obj in mon_detecteur(...):                         # vos géométries shapely, SCR du MNS
        features = extractor.measure(obj.geometry, src)
        result = engine.decide(Candidate(
            obj.id, "BUILDING", features, classic_accepted=obj.ok,
            context={"resolution_m": src.resolution}, geometry=obj.geometry))
""")
    out += [p("5.4 Le cycle complet dans un fichier projet", H2)]
    out += [p("<font name='Mono'>Workspace</font> applique les mêmes règles que le serveur : chaque appel vérifie une "
              "permission et s'inscrit au journal.")]
    out += code("""
from eade.store import Actor, Workspace

from eade.store import PERMISSIONS

admin = Actor("aminata", frozenset(PERMISSIONS))           # toutes les permissions
with Workspace.create("songon.eade") as ws:
    ws.update_settings(admin, "Pilote Songon", enabled=True, mode="COLLECT")
    c = ws.create_campaign(admin, "Lot 1", {"dsm": "mns.tif", "dtm": "mnt.tif", "ortho": "ortho.tif"},
                           parcels="parcelles.gpkg", parcel_id_field="PARCELLE")
    c = ws.run_campaign(admin, c["id"])                  # tuile par tuile, reprend après interruption
    unit = ws.review_queue(c["id"])[0]["unit"]           # parcelle la plus incertaine
    p = ws.predictions(c["id"], parcel_id=unit)[0]
    ws.correct(admin, "ACCEPT", prediction_id=p["id"])
    ws.submit(admin, c["id"], unit)
    ids = [x["id"] for x in ws.corrections(c["id"], "SUBMITTED")]
    ws.review(admin, ids, approve=True, justification="Conforme à l'orthophoto")   # crée les exemples
    candidate, report = ws.build_candidate(admin)        # brouillon appris, rien n'est publié
    ws.simulate(admin, candidate.number, c["id"])         # rejoue sans rien écrire
    ws.evaluate(admin, candidate.number)                  # sur les mailles de test
""")
    return out


def section_cli():
    out = [p("6. Ligne de commande", H1)]
    out += table(["Commande", "Rôle"],
                 [["eade knowledge show FICHIER [--catalog C]", "Résumé d'une version et de ses règles en clair"],
                  ["eade knowledge import FICHIER -o SORTIE", "Importer (natif ou eade-version/1) en brouillon"],
                  ["eade knowledge fingerprint FICHIER", "Afficher l'empreinte"],
                  ["eade decide --knowledge K --catalog C", "Candidats JSON Lines en entrée, explications en sortie"],
                  ["eade geo detect --dsm … -o SORTIE", "Détection, mesure et décision sur un levé"],
                  ["eade geo catalog [-o FICHIER]", "Dictionnaire des caractéristiques en JSON"],
                  ["eade workspace create CHEMIN.eade", "Créer un projet vide"],
                  ["eade serve PROJET.eade [--tokens T]", "Servir un projet en REST et OGC API Features"]],
                 [70 * mm, 100 * mm], mono_cols=(0,))
    out += code("""
eade geo detect --dsm mns.tif --dtm mnt.tif --ortho ortho.tif \\
                --parcels parcelles.gpkg --parcel-id PARCELLE \\
                --knowledge connaissance.json --bounds 368500 590200 369100 590800 \\
                -o predictions.gpkg --provenance run.json
# 4 objects -> predictions.gpkg  (accepted 2, review 0, rejected 2)

# Moteur seul : une ligne JSON par candidat
echo '{"id": "1", "class": "BATIMENT", "classic_accepted": true,
       "features": {"hauteur_mediane_m": 3.1}}' \\
  | eade decide --knowledge v2.json --catalog catalog.json
""")
    out += [p("Formats de sortie selon l'extension : <font name='Mono'>.gpkg</font>, <font name='Mono'>.geojson</font>, "
              "<font name='Mono'>.shp</font>, <font name='Mono'>.fgb</font>. Codes de retour : 0 succès, 2 erreur "
              "d'entrée (message préfixé par <font name='Mono'>eade:</font>).")]
    return out


def section_rest():
    from eade.server import create_app
    from eade.store import Workspace
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "routes.eade"
    app = create_app(Workspace(tmp))
    routes = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods and r.path.startswith("/api"):
            routes.append((",".join(sorted(methods - {"HEAD"})), r.path.replace("/api/v1", "")))
    app.state.workspace.close()

    roles = {
        "/health": ("—", "État du service, mode EADE, version active"),
        "/me": ("VIEW", "Utilisateur et permissions du jeton"),
        "/catalog": ("VIEW", "Dictionnaire des caractéristiques"),
        "/settings": ("VIEW / ADMIN", "Lire ; PATCH : activer, mode, critères (justification)"),
        "/settings/emergency-stop": ("ADMIN", "Désactiver EADE et annuler les campagnes qui l'appliquent"),
        "/versions": ("VIEW / ADMIN", "Lister ; POST : nouveau brouillon"),
        "/versions/{number}": ("VIEW / ADMIN", "Exporter ; PUT : enregistrer un brouillon ; DELETE"),
        "/versions/import": ("ADMIN", "Importer un fichier comme brouillon"),
        "/versions/{number}/publish": ("PUBLISH", "Publier (évaluée ou manuelle)"),
        "/versions/{number}/rollback": ("PUBLISH", "Réactiver une version publiée"),
        "/versions/{number}/simulate": ("QUALITY", "Rejouer sur une campagne, sans écriture"),
        "/versions/{number}/evaluate": ("QUALITY", "Évaluer sur le jeu de test"),
        "/versions/{number}/evaluations": ("VIEW", "Historique des évaluations"),
        "/learning": ("VIEW", "Exemples par classe, polarité, jeu"),
        "/learning/candidate": ("ADMIN", "Construire une version candidate"),
        "/campaigns": ("VIEW / RUN", "Lister ; POST : créer et lancer (202)"),
        "/campaigns/{campaign_id}": ("VIEW", "État, décompte, provenance"),
        "/campaigns/{campaign_id}/resume": ("RUN", "Reprendre une campagne interrompue"),
        "/campaigns/{campaign_id}/cancel": ("RUN", "Arrêter entre deux tuiles"),
        "/campaigns/{campaign_id}/predictions": ("VIEW", "GeoJSON ; filtres decision, parcel_id, bbox, crs"),
        "/predictions/{prediction_id}": ("VIEW", "Une prédiction avec mesures et explication"),
        "/campaigns/{campaign_id}/queue": ("VIEW", "File de revue : uncertainty, random, order"),
        "/campaigns/{campaign_id}/corrections": ("VIEW", "Corrections, filtre status"),
        "/corrections": ("REVIEW", "ACCEPT, REJECT, REDRAW, RECLASSIFY, ADD"),
        "/corrections/split": ("REVIEW", "Scinder un objet"),
        "/corrections/merge": ("REVIEW", "Fusionner des objets"),
        "/corrections/{correction_id}": ("REVIEW", "Retirer un brouillon"),
        "/campaigns/{campaign_id}/submit": ("REVIEW", "Soumettre ses brouillons à l'expert"),
        "/corrections/review": ("VALIDATE", "Valider ou rejeter (justification)"),
        "/audit": ("VIEW", "Journal inaltérable"),
    }
    rows = [[m, path, *roles.get(path, ("", ""))] for m, path in routes]

    out = [p("7. API REST", H1)]
    out += [p("Un serveur sert un projet <font name='Mono'>.eade</font>. Documentation interactive OpenAPI sur "
              "<font name='Mono'>/docs</font>, schéma sur <font name='Mono'>/openapi.json</font> (générez un "
              "client typé dans votre langage à partir de ce schéma).")]
    out += code("""
eade workspace create songon.eade
eade serve songon.eade                                   # local, sans authentification, 127.0.0.1:8765
eade serve songon.eade --host 0.0.0.0 --port 8765 --tokens jetons.json
""")
    out += [p("Authentification", H2)]
    out += [p("Avec <font name='Mono'>--tokens</font>, chaque requête porte <font name='Mono'>Authorization: Bearer "
              "&lt;jeton&gt;</font>. Sans fichier de jetons, le serveur refuse d'écouter ailleurs que sur "
              "127.0.0.1. Générez les jetons avec un outil cryptographique (par exemple "
              "<font name='Mono'>openssl rand -hex 32</font>) et ne versionnez jamais ce fichier.")]
    out += code("""
{
  "9f2c…e1": {"user": "operateur.songon", "permissions": ["VIEW", "RUN", "REVIEW"]},
  "41ab…7d": {"user": "expert.cadastre",  "permissions": ["VIEW", "VALIDATE"]},
  "c03e…90": {"user": "responsable.eade", "permissions": ["VIEW", "QUALITY", "PUBLISH", "ADMIN"]}
}
""")
    out += [p("Conventions", H2)]
    out += bullets([
        "Géométries en <b>GeoJSON WGS 84</b> (RFC 7946) par défaut ; <font name='Mono'>crs=native</font> "
        "(paramètre de requête ou champ <font name='Mono'>crs</font> du corps) pour travailler dans la projection "
        "de la campagne.",
        "Un contour envoyé sans <font name='Mono'>features</font> est <b>mesuré par le serveur</b> sur les rasters "
        "de la campagne (REDRAW, ADD, SPLIT, MERGE).",
        "Les opérations longues répondent <b>202</b> ; on suit la campagne par <font name='Mono'>GET "
        "/campaigns/{id}</font> (status PENDING, RUNNING, DONE, FAILED, CANCELLED, INTERRUPTED).",
        "Erreurs : corps <font name='Mono'>{\"error\": \"…\"}</font> ; <b>401</b> jeton absent ou inconnu, "
        "<b>403</b> permission manquante, <b>404</b> introuvable, <b>409</b> conflit d'état (version figée, "
        "campagne déjà en cours, évaluation absente), <b>422</b> donnée invalide (justification, motif, géométrie), "
        "<b>503</b> rasters inaccessibles.",
    ])
    out += [p("Routes", H2)]
    out += table(["Méthodes", "Chemin (préfixe /api/v1)", "Permission", "Rôle"], rows,
                 [17 * mm, 62 * mm, 25 * mm, 66 * mm], mono_cols=(0, 1))
    out += [p("Exemple de bout en bout", H2)]
    out += code("""
API=http://serveur:8765/api/v1 ; H="Authorization: Bearer $JETON" ; J="Content-Type: application/json"

# 1. lancer une campagne (chemins vus par le serveur)
curl -s -X POST $API/campaigns -H "$H" -H "$J" -d '{
  "label": "Section HT", "dsm": "/data/songon/mns.tif", "dtm": "/data/songon/mnt.tif",
  "ortho": "/data/songon/ortho.tif", "parcels": "/data/songon/parcelles.gpkg",
  "parcel_id_field": "PARCELLE"}'

# 2. suivre, puis récupérer les objets en revue (GeoJSON WGS 84)
curl -s $API/campaigns/1 -H "$H"
curl -s "$API/campaigns/1/predictions?decision=REVIEW&limit=500" -H "$H"

# 3. corriger : redessiner un bâtiment (mesuré par le serveur), puis soumettre la parcelle
curl -s -X POST $API/corrections -H "$H" -H "$J" -d '{
  "action": "REDRAW", "prediction_id": 1542,
  "geometry": {"type": "Polygon", "coordinates": [[[-4.2241, 5.3402], …]]}}'
curl -s -X POST $API/campaigns/1/submit -H "$H" -H "$J" -d '{"parcel_id": "HT/112/1091"}'

# 4. l'expert valide
curl -s -X POST $API/corrections/review -H "Authorization: Bearer $JETON_EXPERT" \\
     -H "$J" -d '{"ids": [87, 88], "approve": true, "justification": "Vérifié"}'

# 5. apprendre, simuler, évaluer, publier
curl -s -X POST $API/learning/candidate -H "$H" -H "$J" -d '{}'
curl -s -X POST $API/versions/3/simulate -H "$H" -H "$J" -d '{"campaign_id": 1}'
curl -s -X POST $API/versions/3/evaluate -H "$H"
curl -s -X POST $API/versions/3/publish -H "$H" -H "$J" \\
     -d '{"justification": "Gain IoU +0,04 sur 120 objets de test"}'
""")
    return out


def section_ogc():
    out = [p("8. OGC API Features", H1)]
    out += [p("Chaque campagne est publiée comme une collection <font name='Mono'>campaign-{id}</font> conforme à "
              "OGC API Features Part 1 (Core, GeoJSON). Les mêmes jetons s'appliquent.")]
    out += table(["URL", "Contenu"],
                 [["/ogc", "Page d'accueil (liens conformance, collections)"],
                  ["/ogc/conformance", "Classes de conformité"],
                  ["/ogc/collections", "Une collection par campagne lancée"],
                  ["/ogc/collections/campaign-1/items?bbox=…&limit=…&offset=…", "Prédictions en GeoJSON WGS 84"]],
                 [86 * mm, 84 * mm], mono_cols=(0,))
    out += bullets([
        "<b>QGIS</b> : Couche › Ajouter une couche › WFS / OGC API Features, URL "
        "<font name='Mono'>http://serveur:8765/ogc</font>, version « OGC API - Features ».",
        "<b>Cartes web</b> : chargez <font name='Mono'>…/items</font> comme source GeoJSON et stylez sur "
        "<font name='Mono'>decision</font> et <font name='Mono'>status</font>.",
    ])
    out += code("""
// MapLibre GL : objets d'une campagne, colorés par décision
map.addSource("eade", { type: "geojson",
  data: "http://serveur:8765/ogc/collections/campaign-1/items?limit=5000" });
map.addLayer({ id: "eade", type: "line", source: "eade", paint: {
  "line-width": 2,
  "line-color": ["match", ["get", "decision"],
                 "ACCEPTED", "#f07c1e", "REVIEW", "#e69600", "REJECTED", "#788291", "#000"] } });
""")
    out += note("un navigateur ne peut pas ajouter d'en-tête Authorization à une source de tuiles ou de GeoJSON "
                "chargée directement par la bibliothèque cartographique. Pour une carte publique, servez les "
                "résultats par un proxy de votre application qui ajoute le jeton côté serveur.", WARN, "Attention")
    return out


def section_qgis():
    out = [p("9. Plugin QGIS", H1)]
    out += bullets([
        "Compatible QGIS 3.34 et plus, et QGIS 4.x (Qt5 et Qt6). Le moteur est embarqué : rien à installer, "
        "il utilise le GDAL de QGIS.",
        "Construction : <font name='Mono'>python scripts/build_qgis_plugin.py</font> produit "
        "<font name='Mono'>dist/eade_qgis-x.y.z.zip</font> ; installation : Extensions › Installer depuis un ZIP.",
        "Données d'essai : <font name='Mono'>python scripts/make_demo.py</font> écrit un levé de 40 m × 40 m, des "
        "parcelles et un projet vide dans <font name='Mono'>dist/demo</font>.",
    ])
    out += [p("Algorithmes de traitement (groupe EADE)", H2)]
    out += table(["Identifiant", "Rôle", "Sorties"],
                 [["eade:detect", "Détecter, mesurer et décider sur un levé (parcelles, connaissance et emprise "
                   "facultatives)", "couche, ACCEPTED, REVIEW, REJECTED"],
                  ["eade:measure", "Mesurer des emprises avec le dictionnaire EADE Geo", "couche"],
                  ["eade:evaluate", "Comparer des détections à des références : IoU, précision, rappel",
                   "MEAN_IOU, PRECISION, RECALL, FALSE_POSITIVES, MISSES, REPORT"],
                  ["eade:campaign", "Enregistrer et exécuter une campagne dans un projet .eade", "couche, CAMPAIGN"]],
                 [26 * mm, 92 * mm, 52 * mm], mono_cols=(0,))
    out += [p("Utilisables dans le modeleur graphique, en lot, ou en Python depuis la console QGIS :")]
    out += code("""
import processing
res = processing.run("eade:detect", {
    "DSM": "D:/songon/mns.tif", "DTM": "D:/songon/mnt.tif", "ORTHO": "D:/songon/ortho.tif",
    "PARCELS": "D:/songon/parcelles.gpkg", "PARCEL_ID": "PARCELLE",
    "KNOWLEDGE": "D:/songon/v3.json", "OUTPUT": "memory:"})
QgsProject.instance().addMapLayer(res["OUTPUT"])
""")
    out += [p("Atelier de correction et de validation", H2)]
    out += [p("Panneau ancré à côté de la carte, ouvert par l'icône EADE. Il charge les objets d'une campagne "
              "(orange retenu, jaune en revue, gris pointillé écarté, vert corrigé, rouge retiré), propose la file "
              "des parcelles et la fiche explicative de chaque objet. Raccourcis : <b>A</b> accepter, <b>R</b> "
              "rejeter, <b>1–8</b> motif, <b>D</b> redessiner, <b>B</b> bâtiment manquant, <b>N/P</b> parcelle "
              "suivante/précédente, <b>Ctrl+Entrée</b> soumettre. Les contours se tracent avec les outils de "
              "numérisation de QGIS sur la couche « EADE – tracés » et sont mesurés automatiquement.")]
    out += note("en mode fichier, l'atelier agit sous le nom de l'utilisateur Windows avec toutes les permissions : "
                "la séparation opérateur / expert n'y est pas imposée. Pour une équipe, centralisez le projet "
                "derrière <font name='Mono'>eade serve</font> avec des jetons par rôle.", WARN, "Limite actuelle")
    return out


def section_knowledge():
    out = [p("10. Format des connaissances", H1)]
    out += [p("Une version s'échange en JSON <font name='Mono'>eade.knowledge/1</font>. L'empreinte est vérifiée à "
              "l'import : un fichier modifié après export est refusé. Un import devient toujours un brouillon, "
              "à évaluer sur le jeu de test de l'installation qui le reçoit.")]
    out += code("""
{
  "format": "eade.knowledge/1", "number": 3, "label": "Règles expertes", "status": "DRAFT",
  "fingerprint": "4aa04cfa3de7…",
  "config": {
    "weights": {"classic": 1, "rules": 1, "similarity": 1},
    "thresholds": {"accept": 0.6, "reject": 0.35},
    "ramps": [{"name": "height", "feature": "height_median_m", "low": 2, "full": 2.6,
               "weight": 0.5, "classes": ["BUILDING"]}],
    "similarity": {"min_count": 5, "max_distance": 3}
  },
  "profiles": [],
  "rules": [{
    "code": "SHADOW", "label": "Emprise surtout dans l'ombre", "target_class": "BUILDING",
    "effect": "ABSTAIN", "condition": {"feature": "shadow_share", "op": ">=", "value": 0.5},
    "weight": 0.5, "priority": 70, "blocking": false, "active": true, "origin": "EXPERT"}],
  "signatures": []
}
""")
    out += [p("Grammaire des conditions", H2)]
    out += table(["Forme", "Sens"],
                 [['{"all": [c1, c2, …]}', "toutes vraies (ET)"],
                  ['{"any": [c1, c2, …]}', "au moins une vraie (OU)"],
                  ['{"not": c}', "négation"],
                  ['{"feature": "k", "op": "<", "value": 3}', "comparaison : <  <=  >  >=  =  !="],
                  ['{"feature": "k", "between": [a, b]}', "a ≤ k ≤ b"],
                  ['{"feature": "k", "in": [v1, v2]}', "appartenance"]],
                 [78 * mm, 92 * mm], mono_cols=(0,), pad=2.2)
    out += [p("Profondeur maximale 6, 50 nœuds au plus. Évaluation à trois valeurs : une caractéristique "
              "absente rend la condition <b>inconnue</b> ; une règle ne s'applique que si sa condition est vraie, "
              "et les règles non évaluables sont signalées dans l'explication.")]
    out += [p("Import depuis eFoncier (eade-version/1)", H2)]
    out += note("les règles importées gardent les noms de caractéristiques d'eFoncier (par exemple "
                "<font name='Mono'>hauteur_mediane_m</font>). Pour les appliquer avec le détecteur EADE Geo, "
                "renommez-les vers le dictionnaire de la section 11 (<font name='Mono'>height_median_m</font>…), "
                "sinon <font name='Mono'>Engine</font> refusera la version. L'empreinte EADE diffère de celle "
                "d'eFoncier : réévaluez avant de publier.", WARN, "Attention")
    out += table(["eFoncier", "EADE"],
                 [["effet CONFIRMER / ECARTER / ABSTENIR / RECLASSER", "CONFIRM / REJECT / ABSTAIN / RECLASSIFY"],
                  ["poids classique / regles / cas", "weights classic / rules / similarity"],
                  ["poids hauteur + hauteur.{classe}.min / plein", "rampe height sur hauteur_mediane_m"],
                  ["seuils retenu / ecarte", "thresholds accept / reject"],
                  ["similarite effectif_min / distance_max", "similarity min_count / max_distance"],
                  ["et / ou / non, car, valeur, entre, dans", "all / any / not, feature, value, between, in"],
                  ["origine APPRENTISSAGE ; profil DEFAUT", "origin LEARNED ; règle générale"]],
                 [85 * mm, 85 * mm], mono_cols=(0, 1), pad=2.2)
    return out


def section_features():
    from eade.geo import geo_catalog
    groups = {"geometry": "géométrie", "elevation": "altimétrie", "spectral": "spectral", "texture": "texture",
              "quality": "qualité", "context": "contexte"}
    fr = {
        "area_m2": "Surface", "perimeter_m": "Périmètre", "compactness": "Compacité",
        "rectangularity": "Rectangularité", "elongation": "Allongement", "orientation_deg": "Orientation",
        "width_m": "Largeur", "vertex_count": "Nombre de sommets",
        "height_median_m": "Hauteur médiane au-dessus du sol", "height_p90_m": "Hauteur P90",
        "height_p10_m": "Hauteur P10", "height_spread_m": "Écart de hauteur P90 – P25",
        "slope_mean": "Pente moyenne de la surface", "steep_edge_share": "Part du pourtour en mur (pente > 45°)",
        "curvature_median": "Courbure médiane de la surface", "rough_share": "Part de surface rugueuse",
        "red_mean": "Rouge moyen", "green_mean": "Vert moyen", "blue_mean": "Bleu moyen",
        "brightness": "Luminosité", "contrast": "Contraste", "saturation": "Saturation",
        "hue_cos": "Teinte (cosinus)", "hue_sin": "Teinte (sinus)", "excess_green": "Indice d'excès de vert",
        "green_share": "Part de pixels verts", "local_variance": "Variance locale",
        "gradient_mean": "Gradient moyen", "edge_density": "Densité de contours",
        "elevation_coverage": "Couverture du MNS", "shadow_share": "Part dans l'ombre",
        "resolution_m": "Taille du pixel", "truncated": "Coupé par le bord des données",
        "parcel_share": "Part dans sa parcelle", "parcel_count": "Parcelles touchées",
        "boundary_distance_m": "Distance du centre à la limite", "touches_boundary": "Touche la limite de parcelle",
    }
    rows = []
    for d in geo_catalog():
        n = d.normalizer
        norm = {"identity": "—", "scale": f"÷ {n.divisor:g}", "log": f"log1p ÷ {n.divisor:g}"}.get(n.kind, n.kind)
        if d.dtype == "boolean":
            norm = "booléen"
        rows.append([d.key, groups.get(d.group, d.group), fr.get(d.key, d.label), d.unit or "—",
                     norm + ("" if d.learnable else " · non appris")])
    out = [p("11. Dictionnaire des caractéristiques (EADE Geo)", H1)]
    out += [p(f"{len(rows)} caractéristiques, version d'extracteur <font name='Mono'>geo-1</font>. Les contextuelles "
              "ne sont calculées que si des parcelles sont fournies. « Non appris » : la caractéristique décrit "
              "l'acquisition et n'est jamais utilisée pour proposer un seuil.")]
    out += table(["Clé", "Groupe", "Libellé", "Unité", "Normalisation"], rows,
                 [40 * mm, 22 * mm, 58 * mm, 16 * mm, 34 * mm], mono_cols=(0,), pad=2.2)
    return out


def section_governance():
    out = [p("12. Gouvernance et sécurité", H1)]
    out += [p("Permissions", H2)]
    out += table(["Permission", "Pour qui", "Permet"],
                 [["VIEW", "Tous", "Consulter campagnes, prédictions, connaissances, journal"],
                  ["RUN", "Opérateur, chef d'équipe", "Lancer, arrêter, reprendre une campagne"],
                  ["REVIEW", "Opérateur", "Corriger et soumettre"],
                  ["VALIDATE", "Expert", "Valider ou rejeter les corrections soumises"],
                  ["QUALITY", "Qualité", "Simuler et évaluer une version"],
                  ["PUBLISH", "Responsable EADE", "Publier, rétablir une version"],
                  ["ADMIN", "Responsable EADE", "Activer, mode, règles, candidates, import, arrêt d'urgence"]],
                 [24 * mm, 44 * mm, 102 * mm], mono_cols=(0,))
    out += [p("Modes", H2)]
    out += table(["Mode", "Campagnes", "Corrections validées", "Publication"],
                 [["Désactivé", "Moteur classique seul", "Enregistrées, sans apprentissage", "—"],
                  ["READ_ONLY", "Classique + version active", "Enregistrées, sans apprentissage", "Manuelle"],
                  ["COLLECT", "Classique + version active", "Deviennent des exemples", "Manuelle"],
                  ["ADMIN", "Classique + version active", "Deviennent des exemples", "Évaluée ou manuelle"]],
                 [24 * mm, 46 * mm, 56 * mm, 44 * mm], bold_first=True)
    out += [p("Conditions de publication évaluée : EADE actif en mode ADMIN ; évaluation acceptée de cette "
              "empreinte exacte contre la version active ; gain d'IoU moyen ≥ 0,02 sur au moins 20 objets de test ; "
              "ni l'erreur de surface ni les faux positifs n'augmentent ; justification. La publication manuelle "
              "exige 15 caractères de justification et garde l'état de la dernière évaluation au journal.")]
    out += [p("Garanties imposées par la base", H2)]
    out += bullets([
        "Une prédiction ne change plus, sauf son statut de revue ; elle ne se supprime pas.",
        "Une version publiée est figée ; un exemple validé est immuable ; une correction jugée ne change plus.",
        "Le journal est en ajout seul : ni modification ni suppression, même en ouvrant le fichier avec un autre outil.",
        "Chaque prédiction garde la version et l'empreinte qui l'ont produite : un retour arrière dit exactement "
        "quels objets revoir.",
    ])
    out += [p("Exploitation", H2)]
    out += bullets([
        "<b>Arrêt d'urgence</b> : <font name='Mono'>POST /settings/emergency-stop</font> désactive EADE "
        "immédiatement et annule les campagnes qui l'appliquent ; le moteur classique continue.",
        "<b>Sauvegarde</b> : le projet est un seul fichier SQLite ; copiez-le serveur arrêté, ou avec "
        "<font name='Mono'>sqlite3 projet.eade \".backup copie.eade\"</font>. Les rasters se sauvegardent à part.",
        "<b>Réseau</b> : sans jetons, écoute locale uniquement ; en production, placez le serveur derrière un "
        "proxy HTTPS et limitez l'accès aux chemins de rasters au serveur lui-même.",
    ])
    return out


def section_efoncier():
    out = [p("13. Intégrer EADE à eFoncier Africa ou à une plateforme existante", H1)]
    out += [p("Le schéma recommandé garde le moteur classique de la plateforme comme fournisseur et place EADE "
              "derrière une interface optionnelle :")]
    out += bullets([
        "<b>Étape 1 — Observer.</b> Servez un projet EADE et lancez des campagnes en mode READ_ONLY sur des zones "
        "déjà expertisées. Affichez les prédictions via OGC API Features, sans rien changer au flux métier.",
        "<b>Étape 2 — Reprendre la connaissance.</b> Importez les versions existantes "
        "(<font name='Mono'>POST /versions/import</font>), renommez les caractéristiques vers le dictionnaire "
        "EADE Geo, simulez sur une campagne de référence.",
        "<b>Étape 3 — Collecter.</b> Passez en mode COLLECT ; les corrections validées par les experts "
        "deviennent des exemples. Utilisez régulièrement la file aléatoire pour mesurer honnêtement la qualité.",
        "<b>Étape 4 — Améliorer.</b> Construisez des candidates, évaluez-les, publiez en mode ADMIN seulement "
        "quand le gain est prouvé. Rétablissez la version précédente au moindre doute.",
        "<b>Toujours</b> : les valeurs cadastrales et les barèmes restent calculés par la plateforme, sur des "
        "objets validés. EADE n'écrit que dans son propre projet.",
    ])
    out += [p("Appel depuis un backend Java (Spring)", H2)]
    out += code("""
RestClient eade = RestClient.builder()
    .baseUrl("http://eade:8765/api/v1")
    .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + jetonService)
    .build();

Map<?, ?> campagne = eade.post().uri("/campaigns")
    .contentType(MediaType.APPLICATION_JSON)
    .body(Map.of("label", "Section HT", "dsm", cheminMns, "dtm", cheminMnt, "ortho", cheminOrtho,
                 "parcels", cheminParcelles, "parcel_id_field", "PARCELLE"))
    .retrieve().body(Map.class);                       // 202 : la campagne tourne en arrière-plan

String geojson = eade.get()
    .uri("/campaigns/{id}/predictions?decision=REVIEW&crs=native", campagne.get("id"))
    .retrieve().body(String.class);
""")
    out += note("si EADE est indisponible (erreur réseau, 503), la plateforme doit continuer avec son moteur "
                "classique, exactement comme quand EADE est désactivé.", OK, "Dégradation contrôlée")
    return out


def section_troubleshooting():
    out = [p("14. Dépannage", H1)]
    out += table(["Message ou symptôme", "Cause et solution"],
                 [["… is not projected: reproject the data to a metric CRS", "Le MNS (ou l'orthophoto de "
                   "référence) est en degrés. Reprojetez-le en UTM ou dans une projection métrique locale."],
                  ["the height detector needs a surface model (DSM)", "La détection par hauteur exige un MNS. "
                   "Sans MNS, utilisez votre propre fournisseur de candidats (section 5.3)."],
                  ["invalid rules in version N: … unknown feature", "Une règle cite une caractéristique absente du "
                   "dictionnaire utilisé : corrigez le nom (souvent après un import eFoncier)."],
                  ["fingerprint mismatch", "Le fichier de connaissance a été modifié après export. Réexportez-le."],
                  ["409 a campaign is already running", "Une seule campagne à la fois par projet. Attendez, ou "
                   "annulez-la (POST /campaigns/{id}/cancel)."],
                  ["409 no accepted evaluation of this exact version", "Évaluez la version dans son état actuel ; "
                   "toute modification change l'empreinte."],
                  ["Campagne INTERRUPTED", "Le serveur s'est arrêté pendant le calcul : POST "
                   "/campaigns/{id}/resume reprend à la tuile suivante, sans doublon."],
                  ["Peu ou pas d'objets détectés", "Vérifiez que MNS et MNT ont la même référence altimétrique ; "
                   "sans MNT, le sol est estimé sur 30 m et peut sous-estimer de grands bâtiments."],
                  ["Le plugin n'apparaît pas dans QGIS", "Activez-le dans Extensions › Installées ; en version "
                   "expérimentale, cochez « Afficher les extensions expérimentales »."]],
                 [62 * mm, 108 * mm], mono_cols=(0,))
    out += [p("Limites actuelles et suite", H2)]
    out += bullets([
        "Les seuils du détecteur par hauteur sont réglés sur données de synthèse : à calibrer sur un vrai levé "
        "avant usage en production.",
        "L'atelier QGIS travaille sur un fichier ; sa connexion au serveur multi-utilisateurs est à venir.",
        "Le logiciel de bureau EADE Studio et son installeur Windows sont en cours de développement.",
        "Publication sur PyPI et choix de la licence avant la version 1.0.",
    ])
    return out


def build(path: Path) -> Path:
    load_fonts(ROOT / "build" / "fonts")
    story = cover() + toc()
    for section in (section_overview, section_modes, section_install, section_concepts, section_python,
                    section_cli, section_rest, section_ogc, section_qgis, section_knowledge, section_features,
                    section_governance, section_efoncier, section_troubleshooting):
        story += section()
        story.append(PageBreak())
    story.pop()
    if TOO_LONG:
        raise ValueError("code lines too long for the page:\n" + "\n".join(TOO_LONG))
    path.parent.mkdir(parents=True, exist_ok=True)
    Guide(path).multiBuild(story)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=str(ROOT / "docs" / "EADE_Guide_integration.pdf"))
    args = ap.parse_args(argv)
    out = build(Path(args.output))
    print(f"guide written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

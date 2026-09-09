# -*- coding: utf-8 -*-
# Erzeugt die Wortmarke, das Zeichen und das Favicon von Exmig -- nicht
# nachgezeichnet, sondern monolinear aus gemessenen Werten aufgebaut. Jede
# Zahl unten steht mit Namen da; wer das Logo aendern will, aendert eine
# davon und laesst das Skript laufen.
#
# Aufruf aus diesem Ordner:  python logo-bauen.py
# Ziel ist ../webui/static/. Fuer die drei SVG/ICO-Dateien braucht es nur
# Python; die .ico zusaetzlich Pillow, sonst wird sie uebersprungen.
#
# Warum das Logo so aussieht und welche Regeln fuer Farben gelten, steht
# in docs/gestaltung.md.
import io, math

STATIC = "../webui/static"

import math

# ---------------------------------------------------------------- Parameter
B      = 713.0     # Grundlinie
XH     = 514.0     # x-Hoehe (Oberkante der geraden Buchstaben m, i)
SN     = 44.0      # Strichstaerke navy  "ex"
ST     = 36.0      # Strichstaerke tuerkis "mig"

# e: Ring + Balken + Fussbalken
E_CX, E_CY, E_R = 208.0, 604.0, 87.0     # Mittellinien-Kreis
E_BALK_Y        = 605.0                   # Balken, Mittellinie
E_BALK_X0       = 170.0                   # linkes Ende (stumpf)
E_FUSS_Y        = E_CY + E_R              # 691 -- tangential an den Kreisboden
E_FUSS_X1       = 345.0                   # rechtes Ende des Fussbalkens
E_RING_ENDE     = 0.0                     # Grad: Ring endet waagerecht auf Kreismitte,
E_BALK_X1       = 317.0                   # der Balken uebernimmt bis zur Aussenkante                   # rechtes Ende des Fussbalkens

# x: zwei 45-Grad-Balken, oben/unten waagerecht auf x-Hoehe und Grundlinie
XA_TOP, XA_BOT  = 321.5, 540.5            # Arm A (fallend nach rechts), Mittellinie
XB_TOP          = 534.0                   # Arm B (fallend nach links), Mittellinie oben
XB_BOT          = 1030.0 - B              # Arm B laeuft bis zur Grundlinie in den e-Fuss

# m
M_S1, M_S2, M_S3 = 595.0, 730.5, 866.0    # Stammmitten
M_BOGEN_Y        = 600.0                  # Mittelpunkt der Boegen (Scheitel auf x-Hoehe)
M_BOGEN_R        = (M_S2 - M_S1) / 2      # 67.75

# i
I_X, I_PUNKT     = 916.5, (915.0, 463.0, 25.0)   # Stamm; Punkt (cx, cy, r)

# g
G_CX, G_CY, G_R  = 1053.0, 613.0, 83.0    # Schuessel, Mittellinie
G_SCHLINGE_CY    = 714.5                  # Schlinge, gleicher Radius
G_SCHLINGE_ENDE  = 168.0                  # Grad, wo die Schlinge offen aufhoert
G_STAMM_X        = G_CX + G_R             # 1136 -- tangential an beide Kreise

# ---------------------------------------------------------------- Geometrie
def dist(p, q):
    return math.hypot(p[0]-q[0], p[1]-q[1])

def in_ring(p, c, r, s, a0=None, a1=None):
    """Punkt im Kreisring der Mittellinie r, Staerke s; optional Winkelbereich in Grad."""
    if abs(dist(p, c) - r) > s/2:
        return False
    if a0 is None:
        return True
    t = math.degrees(math.atan2(p[1]-c[1], p[0]-c[0])) % 360
    a0 %= 360; a1 %= 360
    return (a0 <= t <= a1) if a0 <= a1 else (t >= a0 or t <= a1)

def in_balken(p, x0, y0, x1, y1, s):
    """Punkt im geraden Balken mit stumpfen Enden."""
    dx, dy = x1-x0, y1-y0
    L2 = dx*dx + dy*dy
    t = ((p[0]-x0)*dx + (p[1]-y0)*dy) / L2
    if t < 0 or t > 1:
        return False
    return abs((p[0]-x0)*dy - (p[1]-y0)*dx) / math.sqrt(L2) <= s/2

def in_viereck(p, ecken):
    vz = 0
    for i in range(4):
        ax, ay = ecken[i]; bx, by = ecken[(i+1) % 4]
        k = (bx-ax)*(p[1]-ay) - (by-ay)*(p[0]-ax)
        if k != 0:
            if vz and (k > 0) != (vz > 0):
                return False
            vz = k
    return True

H = SN * math.sqrt(2) / 2      # waagerechte Halbbreite eines 45-Grad-Balkens
D = SN * math.sqrt(2) / 4      # halbe stumpfe Kappe, je Achse

ARM_A = [(XA_TOP-H, XH-20), (XA_TOP+H, XH-20), (XA_BOT+H, B), (XA_BOT-H, B)]
ARM_B = [(XB_TOP-H, XH-20), (XB_TOP+H, XH-20), (XB_BOT+H, B), (XB_BOT-H, B)]

def ist_e(p):
    return (in_ring(p, (E_CX, E_CY), E_R, SN, 90, E_RING_ENDE)
            or in_balken(p, E_BALK_X0, E_BALK_Y, E_BALK_X1, E_BALK_Y, SN)
            or in_balken(p, E_CX, E_FUSS_Y, E_FUSS_X1, E_FUSS_Y, SN))

def ist_x(p):
    return in_viereck(p, ARM_A) or in_viereck(p, ARM_B)

def ist_m(p):
    return (in_balken(p, M_S1, M_BOGEN_Y, M_S1, B, ST)
            or in_balken(p, M_S2, M_BOGEN_Y, M_S2, B, ST)
            or in_balken(p, M_S3, M_BOGEN_Y, M_S3, B, ST)
            or in_ring(p, ((M_S1+M_S2)/2, M_BOGEN_Y), M_BOGEN_R, ST, 180, 360)
            or in_ring(p, ((M_S2+M_S3)/2, M_BOGEN_Y), M_BOGEN_R, ST, 180, 360))

def ist_i(p):
    return (in_balken(p, I_X, XH, I_X, B, ST)
            or dist(p, I_PUNKT[:2]) <= I_PUNKT[2])

def ist_g(p):
    return (in_ring(p, (G_CX, G_CY), G_R, ST)
            or in_balken(p, G_STAMM_X, G_CY, G_STAMM_X, G_SCHLINGE_CY, ST)
            or in_ring(p, (G_CX, G_SCHLINGE_CY), G_R, ST, 0, G_SCHLINGE_ENDE))

TEILE = [('e', ist_e, 'N', (90, 340, 480, 730)), ('x', ist_x, 'N', (280, 600, 480, 730)),
         ('m', ist_m, 't', (560, 900, 500, 730)), ('i', ist_i, 't', (880, 960, 430, 730)),
         ('g', ist_g, 't', (935, 1175, 500, 830))]

# ------------------------------------------------------------- SVG schreiben
OX, OY = 98.0, 437.0
def X(v): return round(v-OX, 2)
def Y(v): return round(v-OY, 2)
def Pk(cx, cy, r, grad):
    t = math.radians(grad)
    return round(cx-OX + r*math.cos(t), 2), round(cy-OY + r*math.sin(t), 2)
def n(v):
    return ("%.2f" % v).rstrip('0').rstrip('.')

EX, MIG, EXD = '#063b6f', '#15bcb4', '#3585d4'
# Die Fassung fuers Navy-Band im Seitenkopf. Sie steht auf einem Grund,
# der in beiden Themen derselbe ist -- deshalb schaltet sie nicht mit.
EXB = '#b8dcfb'
e0 = (X(E_CX), Y(E_CY+E_R)); e1 = Pk(E_CX, E_CY, E_R, E_RING_ENDE)
Hb = SN*math.sqrt(2)/2
armA = [(X(XA_TOP)-Hb, Y(XH-20)), (X(XA_TOP)+Hb, Y(XH-20)), (X(XA_BOT)+Hb, Y(B)), (X(XA_BOT)-Hb, Y(B))]
armB = [(X(XB_TOP)-Hb, Y(XH-20)), (X(XB_TOP)+Hb, Y(XH-20)), (X(XB_BOT)+Hb, Y(B)), (X(XB_BOT)-Hb, Y(B))]
def poly(p): return " ".join("%s,%s" % (n(a), n(b)) for a,b in p)
gl = Pk(G_CX, G_SCHLINGE_CY, G_R, G_SCHLINGE_ENDE)

# Die drei Striche und die zwei Flaechen des "ex" -- einmal beschrieben,
# in Wortmarke und Zeichen dasselbe.
EX_STRICHE = '''      <!-- e: Ring, rechts offen zwischen Balken und Fuß -->
      <path d="M {e0x} {e0y} A {R} {R} 0 1 1 {e1x} {e1y}"/>
      <!-- e: Querbalken, übernimmt rechts die Außenkante des Rings -->
      <path d="M {bx0} {by} H {bx1}"/>
      <!-- e: Fuß, tangential am Kreisboden, läuft nach rechts ins x -->
      <path d="M {fx0} {fy} H {fx1}"/>'''.format(
    e0x=n(e0[0]), e0y=n(e0[1]), R=n(E_R), e1x=n(e1[0]), e1y=n(e1[1]),
    bx0=n(X(E_BALK_X0)), by=n(Y(E_BALK_Y)), bx1=n(X(E_BALK_X1)),
    fx0=n(X(E_CX)), fy=n(Y(E_FUSS_Y)), fx1=n(X(E_FUSS_X1)))
EX_FLAECHEN = '''    <polygon points="%s"/>
    <polygon points="%s"/>''' % (poly(armA), poly(armB))

# Begrenzung des "ex" allein -- Grundlage des Zeichens
EX_L, EX_R = X(E_CX-E_R-SN/2), armA[2][0]
EX_O, EX_U = Y(XH-20), Y(B)

# Zwei Stilbloecke fuer dieselbe Wortmarke. Der gemeinsame Teil steht einmal,
# unterschiedlich ist nur, wie das "ex" auf dunklem Grund gefunden wird.
STIL_KOPF = """<style>
    /* Ein Strich, zwei Farben. Wer das Logo schwerer oder leichter will, ändert
       --strich-ex und --strich-mig -- sonst nichts.

       Dieselben Farbwerte stehen als --marke-ex und --marke-mig in
       webui/static/style.css. Sie müssen zusammen geändert werden: Diese
       Datei wird als Bild eingebunden und kann die Token der Seite nicht
       lesen. */
    .exmig {
      --ex:  %(ex)s;   /* EX  = Expertise */
      --mig: %(mig)s;   /* MIG = Made in Germany */
      --strich-ex:  %(sn)s;
      --strich-mig: %(st)s;
    }"""

STIL_FUSS = """
    #exmig-ex  { fill: var(--ex); }
    #exmig-mig { fill: var(--mig); }
    #exmig-ex  .strich { fill: none; stroke: var(--ex);  stroke-width: var(--strich-ex); }
    #exmig-mig .strich { fill: none; stroke: var(--mig); stroke-width: var(--strich-mig); }
  </style>"""

# Fassung 1 -- fuer den Seitengrund. Sie schaltet mit dem Thema.
STIL_THEMA = (STIL_KOPF % dict(ex=EX, mig=MIG, sn=n(SN), st=n(ST))) + """
    /* Auf dunklem Grund hat das Navy nur 1,6:1 -- es verschwände. Deshalb dort eine
       hellere Fassung: 4,7:1 gegen den Grund und noch 1,6:1 gegen das Türkis, damit
       die beiden Wortteile unterscheidbar bleiben. */
    @media (prefers-color-scheme: dark) {
      .exmig:not([data-thema="hell"]) { --ex: %s; }
    }
    .exmig[data-thema="dunkel"] { --ex: %s; }
""" % (EXD, EXD) + STIL_FUSS

# Fassung 2 -- fuer das Navy-Band im Seitenkopf. Das Band ist in beiden Themen
# dasselbe, also schaltet hier nichts: ein fester Wert, 7,87:1 gegen das Band
# und 1,65:1 gegen das Tuerkis.
STIL_BAND = (STIL_KOPF % dict(ex=EXB, mig=MIG, sn=n(SN), st=n(ST))) + STIL_FUSS

WORTMARKE = '''<svg xmlns="http://www.w3.org/2000/svg" class="exmig" viewBox="0 0 1057 380"
     role="img" aria-labelledby="exmig-name exmig-beschreibung">
  <title id="exmig-name">Exmig</title>
  <desc id="exmig-beschreibung">{DESC}</desc>

  {STIL}

  <!-- Die fill/stroke-Angaben an den Elementen sind der Rückfall, falls das
       Stylesheet nicht mitkommt (etwa beim Einbetten über <img> in alten Browsern). -->
  <g id="exmig-ex" fill="{EXFALL}">
    <g class="strich" fill="none" stroke="{EXFALL}" stroke-width="{SN}">
{EX_STRICHE}
    </g>
    <!-- x: zwei Diagonalen, oben auf x-Höhe und unten auf der Grundlinie waagerecht
         beschnitten. Der linke Unterarm endet im Fuß des e: die Verschmelzung. -->
{EX_FLAECHEN}
  </g>

  <g id="exmig-mig" fill="{MIG}">
    <g class="strich" fill="none" stroke="{MIG}" stroke-width="{ST}">
      <!-- m: drei Stämme, zwei Halbkreisbögen mit Scheitel auf x-Höhe -->
      <path d="M {m1} {mb} V {mo} A {mr} {mr} 0 0 1 {m2} {mo} V {mb}"/>
      <path d="M {m2} {mo} A {mr} {mr} 0 0 1 {m3} {mo} V {mb}"/>
      <!-- i: Stamm -->
      <path d="M {ix} {iy0} V {mb}"/>
      <!-- g: Schüssel, Stamm, offene Unterschlinge (gleicher Radius, Mitte auf der Grundlinie) -->
      <circle cx="{gcx}" cy="{gcy}" r="{gr}"/>
      <path d="M {gsx} {gcy} V {gly}"/>
      <path d="M {gsx} {gly} A {gr} {gr} 0 0 1 {glx1} {gly1}"/>
    </g>
    <!-- i: Punkt -->
    <circle cx="{pcx}" cy="{pcy}" r="{pr}"/>
  </g>
</svg>
'''

# Alles, was in beiden Fassungen gleich ist -- einmal ausgerechnet.
MASSE = dict(MIG=MIG, SN=n(SN), ST=n(ST),
    EX_STRICHE=EX_STRICHE, EX_FLAECHEN=EX_FLAECHEN,
    m1=n(X(M_S1)), m2=n(X(M_S2)), m3=n(X(M_S3)), mb=n(Y(B)), mo=n(Y(M_BOGEN_Y)), mr=n(M_BOGEN_R),
    ix=n(X(I_X)), iy0=n(Y(XH)), pcx=n(X(I_PUNKT[0])), pcy=n(Y(I_PUNKT[1])), pr=n(I_PUNKT[2]),
    gcx=n(X(G_CX)), gcy=n(Y(G_CY)), gr=n(G_R), gsx=n(X(G_STAMM_X)), gly=n(Y(G_SCHLINGE_CY)),
    glx1=n(gl[0]), gly1=n(gl[1]))

BESCHREIBUNG = ('Wortmarke Exmig: „ex“ in %s für Expertise, „mig“ in Türkis für\n'
                '    Made in Germany. Die Buchstaben jedes Wortteils verschmelzen '
                'miteinander.')

wortmarke = WORTMARKE.format(STIL=STIL_THEMA, EXFALL=EX,
                             DESC=BESCHREIBUNG % 'Navy', **MASSE)
# Die Bandfassung nennt ihren Grund, sonst haelt sie jemand fuer die falsche
# Datei und faerbt sie "zurueck".
wortmarke_band = WORTMARKE.format(STIL=STIL_BAND, EXFALL=EXB,
                                  DESC=BESCHREIBUNG % 'Hellblau'
                                  + '\n    Diese Fassung gehört auf das Navy-Band des '
                                    'Seitenkopfs, nicht auf den Seitengrund.',
                                  **MASSE)

# --------------------------------------------------------------- das Zeichen
# Fuenf Buchstaben sind bei 16 Pixeln ein Fleck. Fuers Favicon deshalb nur
# "ex" -- weiss auf einer navy Kachel: Das liest sich am kleinsten Punkt am
# klarsten, und die weissen Buchstaben tragen es auch auf einer dunklen
# Browserleiste, wo ein Zeichen ohne Flaeche verschwaende.
KACHEL, ANTEIL, RUNDUNG = 512.0, 0.84, 0.18
sk = KACHEL*ANTEIL/(EX_R-EX_L)
tx = (KACHEL - (EX_R-EX_L)*sk)/2 - EX_L*sk
ty = (KACHEL - (EX_U-EX_O)*sk)/2 - EX_O*sk

zeichen = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"
     role="img" aria-labelledby="zeichen-name">
  <title id="zeichen-name">Exmig</title>
  <desc>Das Zeichen: „ex“ aus der Wortmarke, weiß auf navy Kachel. Fürs Favicon,
    wo fünf Buchstaben zu einem Fleck würden. Die Kachelfarbe ist --marke-ex
    aus webui/static/style.css und muss mit ihr zusammen geändert werden.</desc>
  <rect width="512" height="512" rx="{rx}" fill="{EX}"/>
  <g transform="translate({tx} {ty}) scale({sk})" fill="#ffffff">
    <g fill="none" stroke="#ffffff" stroke-width="{SN}">
{EX_STRICHE}
    </g>
{EX_FLAECHEN}
  </g>
</svg>
'''.format(rx=n(KACHEL*RUNDUNG), EX=EX, tx=n(tx), ty=n(ty), sk=n(sk),
           SN=n(SN), EX_STRICHE=EX_STRICHE, EX_FLAECHEN=EX_FLAECHEN)

ZIEL = STATIC if 'STATIC' in dir() else '.'
import xml.dom.minidom
for name, inhalt in (("exmig-logo.svg", wortmarke),
                     ("exmig-logo-band.svg", wortmarke_band),
                     ("exmig-zeichen.svg", zeichen)):
    pfad = ZIEL + "/" + name
    io.open(pfad, 'w', encoding='utf-8').write(inhalt)
    xml.dom.minidom.parse(pfad)
    print("%-20s %5d Bytes, gueltiges XML" % (name, len(inhalt.encode('utf-8'))))

# -------------------------------------------------------------- das Favicon
# Browser, die kein SVG als Favicon nehmen, brauchen eine .ico. Sie wird aus
# denselben Formen gerastert, damit beide nicht auseinanderlaufen.
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("favicon.ico uebersprungen -- Pillow fehlt (pip install pillow)")
else:
    ex_form = lambda p: ist_e(p) or ist_x(p)
    L, R2 = EX_L + OX, EX_R + OX          # zurueck in die Messkoordinaten
    O, U = EX_O + OY, EX_U + OY

    def rastern(px, SS=8):
        k = px*SS
        im = Image.new('RGBA', (k, k), (0,0,0,0))
        ImageDraw.Draw(im).rounded_rectangle(
            [0,0,k-1,k-1], radius=int(k*RUNDUNG), fill=(6,59,111,255))
        s = k*ANTEIL/(R2-L)
        ox = (k - (R2-L)*s)/2; oy = (k - (U-O)*s)/2
        p = im.load()
        for j in range(k):
            for i in range(k):
                if ex_form((L + (i+0.5-ox)/s, O + (j+0.5-oy)/s)):
                    p[i,j] = (255,255,255,255)
        return im.resize((px,px), Image.LANCZOS)

    groessen = [16, 32, 48, 64]
    bilder = [rastern(g) for g in groessen]
    bilder[-1].save(STATIC + "/favicon.ico", format="ICO",
                    sizes=[(g,g) for g in groessen])
    print("favicon.ico          %5d Bytes, Groessen %s"
          % (len(io.open(STATIC + "/favicon.ico","rb").read()),
             ", ".join(str(g) for g in groessen)))

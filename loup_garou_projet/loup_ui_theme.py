"""
loup_ui_theme.py – Thème visuel partagé : palette, fonts, primitives de dessin et widgets.

Ce module est importé par tous les écrans du jeu (main, solo, online).
Il ne dépend que de pygame et ne contient aucune logique de jeu.
"""
import math
import random
import pygame

# ── Palette ──────────────────────────────────────────────────────────────────
BG_DEEP       = (6,   4,  14)
BG_TOP        = (10,  8,  22)
BG_MID        = (22, 14,  38)
BG_BOTTOM     = (38, 20,  56)
NIGHT_BLUE    = (14, 20,  52)
MOON_SILVER   = (210, 218, 235)
MOON_GLOW     = (180, 200, 240)
WOLF_RED      = (180,  40,  50)
WOLF_RED_DK   = (100,  20,  28)
BLOOD_RED     = (140,  20,  30)
MIST_PURPLE   = (80,   52, 110)
MIST_LIGHT    = (120,  88, 160)
GOLD_WARM     = (220, 178,  80)
GOLD_PALE     = (200, 168, 100)
CYAN_COOL     = (100, 190, 220)
WHITE_SOFT    = (230, 228, 238)
GREY_DIM      = (100,  96, 118)
GREY_DARK     = (44,   40,  58)
PANEL_BORDER  = (90,  70, 130, 140)
BTN_PRIMARY   = (70,  44, 110)
BTN_PRIMARY_H = (96,  62, 148)
BTN_DANGER    = (110, 28,  40)
BTN_DANGER_H  = (145, 38,  52)
BTN_SUCCESS   = (28,  90,  52)
BTN_SUCCESS_H = (38, 115,  68)
BTN_NEUTRAL   = (40,  36,  72)
BTN_NEUTRAL_H = (58,  52, 100)
BTN_BORDER    = (160, 130, 210)
BTN_BORDER_DIM = (80,  70, 110)
ROLE_WOLF_CLR    = (148, 28,  42)
ROLE_VILLAGE_CLR = (32,  90, 160)
ROLE_NEUTRAL_CLR = (80,  52, 120)

# ── Fonts ─────────────────────────────────────────────────────────────────────
_font_cache: dict = {}


def clear_font_cache():
    """Invalide le cache après un pygame.quit()/init() : les objets Font ne survivent pas."""
    global _font_cache
    _font_cache = {}


def get_font(size: int, bold: bool = False) -> pygame.font.Font:
    """
    Retourne une police depuis le cache, en cherchant parmi les polices serif disponibles.

    :param size: Taille de la police en points (int).
    :param bold: True pour une police en gras (bool).
    :return: pygame.font.Font
    """
    key = (size, bold)
    if key not in _font_cache:
        for name in ("Georgia", "Times New Roman", "Palatino Linotype", "serif"):
            try:
                f = pygame.font.SysFont(name, size, bold=bold)
                _font_cache[key] = f
                break
            except Exception:
                pass
        else:
            _font_cache[key] = pygame.font.Font(None, size)
    return _font_cache[key]


def scaled_fonts(sw: int, sh: int, bw: int, bh: int) -> dict:
    """
    Retourne un dictionnaire de polices redimensionnées selon le rapport entre la fenêtre actuelle
    et la résolution de base.

    :param sw: Largeur actuelle de la fenêtre (int).
    :param sh: Hauteur actuelle de la fenêtre (int).
    :param bw: Largeur de base de référence (int).
    :param bh: Hauteur de base de référence (int).
    :return: dict avec les clés 'xs', 'small', 'medium', 'big', 'title', 'huge' (pygame.font.Font).
    """
    s = min(sw / bw, sh / bh)
    return {
        "xs":     get_font(max(13, int(15 * s))),
        "small":  get_font(max(15, int(18 * s))),
        "medium": get_font(max(20, int(24 * s))),
        "big":    get_font(max(28, int(36 * s)), bold=True),
        "title":  get_font(max(38, int(52 * s)), bold=True),
        "huge":   get_font(max(48, int(66 * s)), bold=True),
    }


# ── Dessin ────────────────────────────────────────────────────────────────────

def draw_gradient_bg(surface: pygame.Surface, top=BG_TOP, bottom=BG_BOTTOM):
    """Dégradé vertical ligne par ligne. Simple et lisible, la perf est acceptable à 60 fps."""
    w, h = surface.get_size()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        pygame.draw.line(surface, c, (0, y), (w, y))


def draw_glass_panel(surface: pygame.Surface, rect: pygame.Rect,
                     radius: int = 18, alpha_fill: int = 210,
                     border_color=PANEL_BORDER, highlight: bool = True):
    """
    Dessine un panneau semi-transparent avec coin arrondi et reflet lumineux en haut (effet verre).

    :param surface: Surface pygame cible (pygame.Surface).
    :param rect: Zone du panneau (pygame.Rect).
    :param radius: Rayon des coins arrondis (int), 18 par défaut.
    :param alpha_fill: Opacité du fond (int, 0-255), 210 par défaut.
    :param border_color: Couleur de la bordure avec alpha (tuple RGBA).
    :param highlight: Si True, ajoute un reflet blanc semi-transparent en haut (bool).
    """
    r = pygame.Rect(rect)
    if r.width <= 0 or r.height <= 0:
        return
    panel = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
    pygame.draw.rect(panel, (*BG_MID, alpha_fill), (0, 0, r.width, r.height), border_radius=radius)
    bc3 = border_color[:3]
    ba  = border_color[3] if len(border_color) == 4 else 180
    pygame.draw.rect(panel, (*bc3, ba), (0, 0, r.width, r.height), width=1, border_radius=radius)
    if highlight and r.height > 6:
        # Reflet lumineux en haut du panneau : blanc semi-transparent qui s'estompe vers le bas
        hl_h = max(2, r.height // 3)
        hl_w = max(1, r.width - 4)
        hl = pygame.Surface((hl_w, hl_h), pygame.SRCALPHA)
        for row in range(hl.get_height()):
            a = int(26 * (1 - row / hl.get_height()))
            pygame.draw.line(hl, (255, 255, 255, a), (2, row), (hl_w - 2, row))
        panel.blit(hl, (2, 2))
    surface.blit(panel, r.topleft)


def draw_text(surface: pygame.Surface, text: str, font: pygame.font.Font,
              color, center=None, topleft=None, topright=None, shadow: bool = False) -> pygame.Rect:
    """
    Dessine du texte sur une surface, optionnellement avec une ombre portée.

    :param surface: Surface pygame cible (pygame.Surface).
    :param text: Texte à afficher (str).
    :param font: Police utilisée (pygame.font.Font).
    :param color: Couleur du texte (tuple RGB ou RGBA).
    :param center: Coordonnées (x, y) du centre (tuple[int, int] ou None).
    :param topleft: Coordonnées (x, y) du coin supérieur gauche (tuple[int, int] ou None).
    :param topright: Coordonnées (x, y) du coin supérieur droit (tuple[int, int] ou None).
    :param shadow: Si True, dessine une ombre noire décalée de 2px (bool).
    :return: pygame.Rect du texte rendu.
    """
    if shadow:
        sh = font.render(text, True, (0, 0, 0))
        sr = sh.get_rect()
        if center:
            sr.center = (center[0] + 2, center[1] + 2)
        elif topleft:
            sr.topleft = (topleft[0] + 2, topleft[1] + 2)
        elif topright:
            sr.topright = (topright[0] + 2, topright[1] + 2)
        surface.blit(sh, sr)
    img = font.render(text, True, color)
    r = img.get_rect()
    if center is not None:
        r.center = center
    if topleft is not None:
        r.topleft = topleft
    if topright is not None:
        r.topright = topright
    surface.blit(img, r)
    return r


def wrap_text(text: str, max_chars: int) -> list:
    """
    Découpe un texte en lignes de longueur maximale sans couper les mots.

    :param text: Texte à découper (str).
    :param max_chars: Nombre maximum de caractères par ligne (int).
    :return: list[str] — liste de lignes.
    """
    if max_chars <= 0:
        return [text] if text else []
    words = text.split()
    if not words:
        return []
    lines, cur = [], ""
    for w in words:
        test = w if not cur else cur + " " + w
        if len(test) <= max_chars:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_moon(surface: pygame.Surface, cx: int, cy: int, radius: int, t: float = 0.0):
    """
    Dessine une lune avec halo animé et cratères décoratifs.

    :param surface: Surface pygame cible (pygame.Surface).
    :param cx: Coordonnée X du centre de la lune (int).
    :param cy: Coordonnée Y du centre de la lune (int).
    :param radius: Rayon de la lune en pixels (int).
    :param t: Temps animé en secondes pour l'oscillation du halo (float).
    """
    if radius <= 0:
        return
    halo_r = int(radius * (1.05 + 0.04 * math.sin(t * 1.5)))
    sz = halo_r * 2 + 20
    halo = pygame.Surface((sz, sz), pygame.SRCALPHA)
    for step in range(8):
        hr = halo_r + step * 3
        a = max(0, 28 - step * 4)
        pygame.draw.circle(halo, (200, 210, 255, a), (sz // 2, sz // 2), hr)
    surface.blit(halo, (cx - sz // 2, cy - sz // 2))
    pygame.draw.circle(surface, (195, 205, 230), (cx, cy), radius)
    pygame.draw.circle(surface, (175, 185, 215), (cx, cy), radius, 2)
    for ox, oy, r2 in [(-radius // 4, -radius // 5, max(1, radius // 8)),
                        (radius // 5,  radius // 4,  max(1, radius // 10)),
                        (-radius // 6, radius // 5,  max(1, radius // 12))]:
        pygame.draw.circle(surface, (170, 180, 210), (cx + ox, cy + oy), r2)
        pygame.draw.circle(surface, (155, 165, 195), (cx + ox, cy + oy), r2, 1)


def draw_tree_silhouette(surface: pygame.Surface, x: int, bottom: int,
                          height: int, color=(8, 12, 24)):
    """
    Dessine la silhouette stylisée d'un sapin (tronc + 3 triangles superposés).

    :param surface: Surface pygame cible (pygame.Surface).
    :param x: Coordonnée X du centre de l'arbre (int).
    :param bottom: Coordonnée Y de la base de l'arbre (int).
    :param height: Hauteur totale de l'arbre en pixels (int).
    :param color: Couleur de remplissage (tuple RGB), noir nuit par défaut.
    """
    if height <= 4:
        return
    tw = max(3, height // 12)
    th = max(3, height // 5)
    pygame.draw.rect(surface, color, (x - tw // 2, bottom - th, tw, th))
    for i, (w, h2) in enumerate([(height // 2, height * 2 // 3),
                                   (height * 2 // 5, height // 2),
                                   (height // 3, height // 3)]):
        if w <= 0 or h2 <= 0:
            continue
        base_y = bottom - th - h2 * i // 3
        pygame.draw.polygon(surface, color, [
            (x - w // 2, base_y),
            (x + w // 2, base_y),
            (x, base_y - h2),
        ])


# ── Particules ────────────────────────────────────────────────────────────────

class Particle:
    # __slots__ limite la mémoire allouée par instance (important quand on en crée des dizaines)
    __slots__ = ("x", "y", "vx", "vy", "size", "alpha", "color", "age", "max_age", "_w", "_h")

    def __init__(self, w: int, h: int):
        """
        Initialise une particule dans les dimensions données.

        :param w: Largeur de l'espace de simulation (int).
        :param h: Hauteur de l'espace de simulation (int).
        """
        self._w, self._h = w, h
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.size = 1.5
        self.alpha = 150
        self.color = (220, 200, 100)
        self.age = 0
        self.max_age = 300
        self.reset(init=True)

    def reset(self, init: bool = False):
        """
        Réinitialise la position et les propriétés de la particule.

        :param init: Si True, positionne la particule aléatoirement en Y (bool) ;
                     sinon la recrée en bas de l'écran.
        """
        self.x = random.uniform(0, self._w)
        self.y = random.uniform(0, self._h) if init else float(self._h + 5)
        self.vy = random.uniform(-0.4, -0.12)
        self.vx = random.uniform(-0.12, 0.12)
        self.size = random.uniform(1.2, 2.8)
        self.alpha = random.randint(120, 200)
        self.color = random.choice([(220, 200, 100), (180, 220, 255),
                                    (160, 100, 220), (200, 220, 180)])
        self.max_age = random.randint(200, 420)
        self.age = 0

    def update(self):
        """Met à jour la position et l'âge de la particule ; la réinitialise si elle sort de l'écran."""
        self.x += self.vx
        self.y += self.vy
        self.age += 1
        if self.y < -10 or self.age >= self.max_age:
            self.reset()

    def draw(self, surface: pygame.Surface):
        """
        Dessine la particule sur la surface avec une opacité décroissante selon son âge.

        :param surface: Surface pygame sur laquelle dessiner (pygame.Surface).
        """
        a = int(self.alpha * max(0.0, 1.0 - self.age / self.max_age))
        if a < 8:
            return
        r = max(1, int(self.size))
        sz = r * 4
        s = pygame.Surface((sz, sz), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.color, a), (sz // 2, sz // 2), r)
        surface.blit(s, (int(self.x) - sz // 2, int(self.y) - sz // 2))


class ParticleSystem:
    def __init__(self, w: int, h: int, count: int = 40):
        """
        Initialise un système de particules flottantes dans la zone donnée.

        :param w: Largeur de la zone de simulation (int).
        :param h: Hauteur de la zone de simulation (int).
        :param count: Nombre de particules à créer (int), 40 par défaut.
        """
        self.w, self.h = w, h
        self.particles = [Particle(w, h) for _ in range(count)]

    def resize(self, w: int, h: int):
        """
        Adapte toutes les particules à une nouvelle taille de fenêtre.

        :param w: Nouvelle largeur (int).
        :param h: Nouvelle hauteur (int).
        """
        self.w, self.h = w, h
        for p in self.particles:
            p._w, p._h = w, h

    def update(self):
        """Met à jour toutes les particules du système."""
        for p in self.particles:
            p.update()

    def draw(self, surface: pygame.Surface):
        """
        Dessine toutes les particules sur la surface.

        :param surface: Surface pygame sur laquelle dessiner (pygame.Surface).
        """
        for p in self.particles:
            p.draw(surface)


# ── Widgets ───────────────────────────────────────────────────────────────────

class Button:
    def __init__(self, text: str, color=BTN_PRIMARY, hover=BTN_PRIMARY_H, icon: str = ""):
        """
        Initialise un bouton UI du thème loup-garou.

        :param text: Texte affiché sur le bouton (str).
        :param color: Couleur de fond au repos (tuple RGB).
        :param hover: Couleur de fond au survol (tuple RGB).
        :param icon: Caractère Unicode optionnel affiché avant le texte (str).
        """
        self.text = text
        self.icon = icon
        self.color = color
        self.hover = hover
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.enabled = True

    def set_rect(self, rect):
        """
        Définit la zone cliquable du bouton.

        :param rect: Tuple (x, y, w, h) ou pygame.Rect.
        """
        self.rect = pygame.Rect(rect)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             mouse_pos, enabled: bool = True):
        """
        Dessine le bouton avec ombre, reflet et gestion de l'état désactivé.

        :param surface: Surface pygame sur laquelle dessiner (pygame.Surface).
        :param font: Police utilisée pour le label (pygame.font.Font).
        :param mouse_pos: Position actuelle de la souris (tuple[int, int]).
        :param enabled: Si False, le bouton est grisé et non cliquable (bool).
        """
        self.enabled = enabled
        hov = enabled and self.rect.collidepoint(mouse_pos)
        col = self.hover if hov else self.color
        if not enabled:
            col = tuple(max(0, c - 40) for c in col[:3])
        # Shadow
        sh = pygame.Surface((self.rect.w, self.rect.h), pygame.SRCALPHA)
        pygame.draw.rect(sh, (0, 0, 0, 65), (3, 4, self.rect.w, self.rect.h), border_radius=14)
        surface.blit(sh, self.rect.topleft)
        pygame.draw.rect(surface, col, self.rect, border_radius=14)
        if hov:
            hl = pygame.Surface((self.rect.w, max(1, self.rect.h // 2)), pygame.SRCALPHA)
            pygame.draw.rect(hl, (255, 255, 255, 18),
                             (0, 0, self.rect.w, self.rect.h // 2), border_radius=14)
            surface.blit(hl, self.rect.topleft)
        pygame.draw.rect(surface, BTN_BORDER if enabled else BTN_BORDER_DIM,
                         self.rect, 2, border_radius=14)
        label = (self.icon + "  " + self.text).strip() if self.icon else self.text
        draw_text(surface, label, font, WHITE_SOFT if enabled else GREY_DIM,
                  center=self.rect.center, shadow=True)

    def is_clicked(self, pos) -> bool:
        """
        Retourne True si la position est dans la zone du bouton et que celui-ci est activé.

        :param pos: Coordonnées (x, y) du clic (tuple[int, int]).
        :return: bool
        """
        return self.enabled and self.rect.collidepoint(pos)


class InputBox:
    def __init__(self, placeholder: str = "", max_len: int = 20):
        """
        Initialise un champ de saisie de texte avec curseur clignotant.

        :param placeholder: Texte affiché en grisé quand le champ est vide (str).
        :param max_len: Nombre maximum de caractères autorisés (int), 20 par défaut.
        """
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.text = ""
        self.active = False
        self.placeholder = placeholder
        self.max_len = max_len
        self._tick = 0

    def set_rect(self, rect):
        """
        Définit la zone du champ de saisie.

        :param rect: Tuple (x, y, w, h) ou pygame.Rect.
        """
        self.rect = pygame.Rect(rect)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        """
        Dessine le champ de saisie avec le texte actuel, le curseur et l'effet de focus.

        :param surface: Surface pygame sur laquelle dessiner (pygame.Surface).
        :param font: Police utilisée pour le texte (pygame.font.Font).
        """
        self._tick += 1
        pygame.draw.rect(surface, (28, 20, 48) if self.active else (18, 14, 36),
                         self.rect, border_radius=12)
        pygame.draw.rect(surface, CYAN_COOL if self.active else (70, 60, 100),
                         self.rect, 2, border_radius=12)
        display = self.text if self.text else self.placeholder
        col = WHITE_SOFT if self.text else (120, 110, 145)
        cursor = "|" if self.active and (self._tick // 30) % 2 == 0 else ""
        img = font.render(display + cursor, True, col)
        max_w = self.rect.width - 28
        if img.get_width() > max_w:
            # Tronque par le début pour toujours montrer la fin du texte (comme un vrai champ de saisie)
            display = display[-max(1, len(display) * max_w // (img.get_width() + 1)):]
            img = font.render(display + cursor, True, col)
        surface.blit(img, (self.rect.x + 14, self.rect.centery - img.get_height() // 2))

    def handle_event(self, event) -> bool:
        """
        Traite les événements clavier et souris du champ de saisie.

        :param event: Événement pygame (pygame.event.Event).
        :return: True si la touche Entrée a été pressée (bool).
        """
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN:
                return True
            elif len(self.text) < self.max_len and event.unicode.isprintable():
                self.text += event.unicode
        return False

    def consume(self) -> str:
        """
        Retourne le texte saisi (nettoyé) et vide le champ.

        :return: Contenu nettoyé du champ (str).
        """
        t = self.text.strip()
        self.text = ""
        return t


class Stepper:
    def __init__(self, label: str, value: int, minimum: int, maximum: int):
        """
        Initialise un widget de sélection numérique avec boutons + et -.

        :param label: Libellé affiché au-dessus du widget (str).
        :param value: Valeur initiale (int).
        :param minimum: Valeur minimale autorisée (int).
        :param maximum: Valeur maximale autorisée (int).
        """
        self.label = label
        self.value = value
        self.minimum = minimum
        self.maximum = maximum
        self._minus = pygame.Rect(0, 0, 0, 0)
        self._plus  = pygame.Rect(0, 0, 0, 0)
        self._disp  = pygame.Rect(0, 0, 0, 0)

    def set_layout(self, x: int, y: int, width: int):
        """
        Positionne les trois éléments du widget (bouton -, affichage, bouton +).

        :param x: Coordonnée X de départ (int).
        :param y: Coordonnée Y de départ (int).
        :param width: Largeur totale du widget (int).
        """
        bw = 44
        self._minus = pygame.Rect(x, y, bw, 44)
        self._disp  = pygame.Rect(x + bw + 8, y, max(1, width - bw * 2 - 16), 44)
        self._plus  = pygame.Rect(x + width - bw, y, bw, 44)

    def draw(self, surface: pygame.Surface, font, small_font, mouse_pos):
        """
        Dessine le stepper avec son label, ses boutons +/- et la valeur courante.

        :param surface: Surface pygame sur laquelle dessiner (pygame.Surface).
        :param font: Police pour la valeur numérique (pygame.font.Font).
        :param small_font: Police pour le label (pygame.font.Font).
        :param mouse_pos: Position actuelle de la souris pour le survol (tuple[int, int]).
        """
        draw_text(surface, self.label, small_font, GOLD_PALE,
                  topleft=(self._minus.x, self._minus.y - 22))
        for btn, sym, col, hcol in [
            (self._minus, "-", BTN_DANGER,  BTN_DANGER_H),
            (self._plus,  "+", BTN_SUCCESS, BTN_SUCCESS_H),
        ]:
            c = hcol if btn.collidepoint(mouse_pos) else col
            pygame.draw.rect(surface, c, btn, border_radius=12)
            pygame.draw.rect(surface, BTN_BORDER, btn, 2, border_radius=12)
            draw_text(surface, sym, font, WHITE_SOFT, center=btn.center)
        pygame.draw.rect(surface, (18, 14, 34), self._disp, border_radius=12)
        pygame.draw.rect(surface, MIST_LIGHT, self._disp, 2, border_radius=12)
        draw_text(surface, str(self.value), font, MOON_SILVER, center=self._disp.center)

    def handle_click(self, pos) -> bool:
        """
        Traite un clic : décrémente si le bouton - est cliqué, incrémente si c'est le +.

        :param pos: Coordonnées (x, y) du clic (tuple[int, int]).
        :return: True si la valeur a changé (bool).
        """
        if self._minus.collidepoint(pos):
            self.value = max(self.minimum, self.value - 1)
            return True
        if self._plus.collidepoint(pos):
            self.value = min(self.maximum, self.value + 1)
            return True
        return False
"""
main.py – Lanceur principal : menu de sélection de mode et pont vers les sous-jeux.

Les sous-jeux (solo, online) appellent pygame.display.quit() mais PAS pygame.quit()
pour que le Launcher puisse recréer la fenêtre proprement après leur fermeture.
"""

# ── Vérification et installation automatique des dépendances ─────────────────
import subprocess
import sys
import importlib
from pathlib import Path

def _check_and_install_dependencies():
    """
    Lit requirements.txt (à côté de ce fichier), vérifie chaque dépendance
    et installe automatiquement celles qui sont manquantes via pip.
    """
    req_file = Path(__file__).parent / "requirements.txt"
    if not req_file.exists():
        return  # Pas de requirements.txt → on continue sans vérifier

    # Mapping nom-package (pip) → nom-module (import)
    IMPORT_MAP = {
        "pygame": "pygame",
    }

    missing = []
    with req_file.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Extraire le nom du package sans la contrainte de version (ex. "pygame>=2.5.0" → "pygame")
            pkg_name = line.split(">=")[0].split("<=")[0].split("==")[0].split("!=")[0].strip()
            module_name = IMPORT_MAP.get(pkg_name.lower(), pkg_name.lower().replace("-", "_"))
            try:
                importlib.import_module(module_name)
            except ImportError:
                missing.append(pkg_name)

    if missing:
        print(f"[Loup-Garou] Dépendances manquantes : {', '.join(missing)}")
        print("[Loup-Garou] Installation en cours…")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet"] + missing
            )
            print("[Loup-Garou] Installation terminée ✔")
        except subprocess.CalledProcessError as err:
            print(f"[Loup-Garou] ⚠ Impossible d'installer les dépendances : {err}")
            print(f"[Loup-Garou]   Lance manuellement : pip install {' '.join(missing)}")
            sys.exit(1)

_check_and_install_dependencies()
# ─────────────────────────────────────────────────────────────────────────────

import threading
import time
import math
import random

import pygame

from loup_garou_online import WerewolfOnlineGame
from loup_garou_solo import WerewolfSoloGame
from chat_moderation import ChatModerator
from loup_server import WerewolfServer
from loup_shared import MIN_PLAYERS, MAX_PLAYERS
from server_discovery import ServerDiscovery
from loup_ui_theme import (
    BG_DEEP, BG_TOP, BG_BOTTOM, BG_MID,
    MOON_SILVER, MOON_GLOW,
    WOLF_RED, MIST_PURPLE, MIST_LIGHT,
    GOLD_WARM, GOLD_PALE,
    CYAN_COOL, WHITE_SOFT, GREY_DIM,
    BTN_PRIMARY, BTN_PRIMARY_H,
    BTN_DANGER, BTN_DANGER_H,
    BTN_SUCCESS, BTN_SUCCESS_H,
    BTN_NEUTRAL, BTN_NEUTRAL_H,
    BTN_BORDER,
    draw_gradient_bg, draw_glass_panel, draw_text, wrap_text,
    draw_moon, draw_tree_silhouette,
    ParticleSystem, Button, InputBox, Stepper,
    scaled_fonts, clear_font_cache,
)

BASE_W, BASE_H = 1100, 760
MIN_W,  MIN_H  = 900,  660


# ── Fond forestier animé ─────────────────────────────────────────────────────

_STARS = None
_STARS_SIZE = (0, 0)


def _init_stars(w, h):
    """
    Initialise (ou réinitialise) le tableau d'étoiles si la taille de la fenêtre a changé.

    :param w: Largeur de la fenêtre en pixels (int).
    :param h: Hauteur de la fenêtre en pixels (int).
    """
    # Recalcule les étoiles uniquement si la taille de la fenêtre a changé
    global _STARS, _STARS_SIZE
    if _STARS is None or _STARS_SIZE != (w, h):
        _STARS = [(random.randint(0, w), random.randint(0, h * 55 // 100),
                   random.uniform(0.5, 1.8), random.uniform(0, math.pi * 2))
                  for _ in range(80)]
        _STARS_SIZE = (w, h)


def draw_forest_scene(surface: pygame.Surface, t: float):
    """
    Dessine la scène de fond forestière animée : ciel dégradé, étoiles scintillantes, lune, brume et silhouettes d'arbres.

    :param surface: Surface Pygame sur laquelle dessiner (pygame.Surface).
    :param t: Temps écoulé en secondes (float), utilisé pour animer les éléments.
    """
    w, h = surface.get_size()
    draw_gradient_bg(surface, BG_DEEP, BG_BOTTOM)
    _init_stars(w, h)
    # Étoiles
    for sx, sy, sr, sp in _STARS:
        a = int(130 + 80 * math.sin(t * 0.7 + sp))
        ss = pygame.Surface((6, 6), pygame.SRCALPHA)
        pygame.draw.circle(ss, (210, 215, 255, a), (3, 3), max(1, int(sr)))
        surface.blit(ss, (sx - 3, sy - 3))
    # Lune
    draw_moon(surface, int(w * 0.80), int(h * 0.16), int(min(w, h) * 0.07), t)
    # Brume basse
    for i in range(3):
        mist = pygame.Surface((w, 36), pygame.SRCALPHA)
        a = int(14 + 8 * math.sin(t * 0.4 + i))
        for mx in range(w):
            wave = int(5 * math.sin(mx / 90 + t * 0.25 + i))
            pygame.draw.line(mist, (130, 110, 170, a), (mx, 18 + wave), (mx, 36 + wave))
        surface.blit(mist, (0, h - 80 + i * 16))
    # Arbres lointains
    for xi, hi in [(0.03, 0.34), (0.11, 0.28), (0.19, 0.36), (0.27, 0.26),
                   (0.62, 0.31), (0.71, 0.38), (0.81, 0.26), (0.93, 0.33)]:
        draw_tree_silhouette(surface, int(xi * w), h, int(hi * h), (10, 8, 22))
    # Arbres proches
    for xi, hi in [(0.0, 0.46), (0.08, 0.40), (0.17, 0.48), (0.28, 0.42),
                   (0.56, 0.44), (0.66, 0.50), (0.77, 0.46), (0.87, 0.42), (0.97, 0.48)]:
        draw_tree_silhouette(surface, int(xi * w), h, int(hi * h), (5, 4, 12))


# ── Lanceur ───────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self):
        """Initialise Pygame, la fenêtre redimensionnable, tous les boutons/champs/steppers, et démarre la découverte réseau."""
        pygame.init()
        self.screen = pygame.display.set_mode((BASE_W, BASE_H), pygame.RESIZABLE)
        pygame.display.set_caption("Loup-Garou")
        self.clock = pygame.time.Clock()
        self.running = True
        self.state = "main"
        self.t = 0.0
        self.particles = ParticleSystem(BASE_W, BASE_H, 45)

        self.input_name = InputBox(placeholder="Entre ton pseudonyme…", max_len=20)
        # Modérateur pour filtrer les pseudos grossiers
        _csv = Path(__file__).parent / "moderation_loup_garou_fr_en.csv"
        self.moderator = ChatModerator(str(_csv))
        self.btn_solo    = Button("MODE SOLO",       BTN_NEUTRAL,  BTN_NEUTRAL_H,  icon="🌙")
        self.btn_online  = Button("MODE EN LIGNE",   BTN_PRIMARY,  BTN_PRIMARY_H,  icon="🐺")
        self.btn_quit    = Button("QUITTER",          BTN_DANGER,   BTN_DANGER_H,   icon="✕")
        self.btn_create  = Button("CREER UN SALON",   BTN_SUCCESS,  BTN_SUCCESS_H,  icon="⚔")
        self.btn_join    = Button("REJOINDRE",         BTN_PRIMARY,  BTN_PRIMARY_H,  icon="🚪")
        self.btn_back    = Button("RETOUR",            BTN_DANGER,   BTN_DANGER_H)
        self.stepper     = Stepper("Nombre de joueurs (IA inclus)", 6, MIN_PLAYERS, 12)
        self.btn_launch  = Button("LANCER LA PARTIE", BTN_SUCCESS,  BTN_SUCCESS_H,  icon="▶")

        self.discovery = ServerDiscovery()
        self.discovery.start()
        self.message       = ""
        self.hosted_server = None
        self.host_thread   = None
        self.selected_idx  = 0
        self.row_rects: list = []
        # Connexion directe par IP (fallback si broadcast bloqué)
        self.ip_input       = InputBox(placeholder="Ex : 192.168.1.42", max_len=15)
        self.btn_connect_ip = Button("CONNEXION DIRECTE", BTN_PRIMARY, BTN_PRIMARY_H, icon="→")
        self.show_ip_input  = False

    # ── Utilitaires ──────────────────────────────────────────────────────────

    def fonts(self) -> dict:
        """
        Retourne le dictionnaire de polices mises à l'échelle selon la taille courante de la fenêtre.

        :return: dict — clés 'title', 'big', 'medium', 'small', 'xs' avec des objets pygame.font.Font.
        """
        w, h = self.screen.get_size()
        return scaled_fonts(w, h, BASE_W, BASE_H)

    def valid_name(self) -> str:
        """
        Retourne le pseudonyme saisi, nettoyé et tronqué à 20 caractères.

        :return: str
        """
        return self.input_name.text.strip()[:20]

    def ensure_name(self) -> bool:
        """
        Vérifie qu'un pseudonyme a été saisi et qu'il ne contient pas de termes grossiers.
        Affiche un message d'erreur approprié si le pseudonyme est invalide.

        :return: True si le pseudonyme est valide (bool).
        """
        name = self.valid_name()
        if not name:
            self.message = "⚠  Choisis un pseudonyme avant de continuer."
            return False
        # Contrôle du pseudo contre la liste de termes grossiers
        _, flagged = self.moderator.moderate(name)
        if flagged:
            self.message = "⚠  Ce pseudonyme contient des termes inappropriés."
            return False
        return True

    def reset_state(self):
        """Revient à l'état principal et remet à zéro la sélection et le message d'information."""
        self.state = "main"
        self.selected_idx = 0
        self.row_rects = []
        self.message = ""

    def restore_window(self, size: tuple):
        """Recrée la fenêtre après qu'un sous-jeu a appelé pygame.display.quit()."""
        if not pygame.get_init():
            pygame.init()
        if not pygame.display.get_init():
            pygame.display.init()
        if not pygame.font.get_init():
            pygame.font.init()
        # Les objets Font ne survivent pas à un reinit de pygame.font → vider le cache
        clear_font_cache()
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.display.set_caption("Loup-Garou")
        self.clock = pygame.time.Clock()
        pygame.event.clear()

    # ── Lancements ───────────────────────────────────────────────────────────

    def launch_online_game(self, host: str, shutdown_after: bool = False):
        """
        Lance le jeu en ligne. Si le joueur choisit "Retour au serveur" en fin de partie,
        une nouvelle connexion est relancée automatiquement vers le même serveur.
        Arrête le serveur hébergé si shutdown_after est True.

        :param host: Adresse IP du serveur à rejoindre (str).
        :param shutdown_after: Si True, arrête le serveur hébergé après la partie (bool).
        """
        sz = self.screen.get_size()
        error_msg = ""
        return_to_lobby = False
        try:
            game = WerewolfOnlineGame(host, self.valid_name())
            game.run()
            return_to_lobby = getattr(game, "return_to_lobby", False)
        except Exception as e:
            error_msg = f"Erreur connexion : {e}"
        self.restore_window(sz)

        if return_to_lobby and not error_msg:
            # Retourner au lobby du même serveur : relancer une connexion
            self.launch_online_game(host, shutdown_after=shutdown_after)
            return

        if shutdown_after and self.hosted_server is not None:
            try:
                self.hosted_server.shutdown()
            except Exception:
                pass
            self.hosted_server = None
            self.host_thread   = None
        self.reset_state()
        if error_msg:
            self.message = error_msg

    def launch_solo_game(self):
        """Lance une partie solo contre des IA avec le nombre de joueurs choisi, puis restaure la fenêtre."""
        sz = self.screen.get_size()
        error_msg = ""
        try:
            game = WerewolfSoloGame(self.valid_name(), self.stepper.value, None)
            game.run()
        except Exception as e:
            error_msg = f"Erreur solo : {e}"
        self.restore_window(sz)
        self.reset_state()
        if error_msg:
            self.message = error_msg

    def create_server(self):
        """Démarre le serveur dans un thread puis rejoint immédiatement en tant qu'hôte."""
        if self.hosted_server is not None:
            try:
                self.hosted_server.shutdown()
            except Exception:
                pass
            self.hosted_server = None
            self.host_thread   = None

        ready_event = threading.Event()
        server = WerewolfServer(
            host_name=self.valid_name(),
            max_players=MAX_PLAYERS,
            role_config=None,
            ready_event=ready_event,
        )
        self.hosted_server = server
        self.host_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.host_thread.start()

        # On attend le signal du serveur avant de se connecter : sans ça, le client
        # arriverait avant que le socket ne soit prêt à accepter des connexions.
        if not ready_event.wait(timeout=3.0) or not server.bind_ok:
            self.message = "Impossible de démarrer le serveur (port occupé ?)."
            self.hosted_server = None
            self.host_thread   = None
            return

        self.launch_online_game("127.0.0.1", shutdown_after=True)

    def join_selected(self):
        """Rejoint le serveur actuellement sélectionné dans la liste de découverte."""
        servers = self.discovery.get_servers()
        if not servers:
            self.message = "Aucun salon trouvé sur le réseau local."
            return
        self.selected_idx = max(0, min(self.selected_idx, len(servers) - 1))
        host = servers[self.selected_idx]["host"]
        self.launch_online_game(host, shutdown_after=False)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _center_panel(self, pw: int = 600, ph: int = 500) -> pygame.Rect:
        """
        Retourne un rectangle centré dans la fenêtre avec les dimensions données.

        :param pw: Largeur du panneau en pixels (int).
        :param ph: Hauteur du panneau en pixels (int).
        :return: pygame.Rect centré dans la fenêtre courante.
        """
        w, h = self.screen.get_size()
        return pygame.Rect(w // 2 - pw // 2, h // 2 - ph // 2, pw, ph)

    def layout_main(self) -> pygame.Rect:
        """
        Positionne les widgets du menu principal et retourne le rectangle du panneau.

        :return: pygame.Rect du panneau principal.
        """
        p = self._center_panel(580, 480)
        bw, bh = p.width - 100, 54
        bx = p.x + 50
        self.input_name.set_rect((bx, p.y + 130, bw, 50))
        self.btn_solo.set_rect  ((bx, p.y + 210, bw, bh))
        self.btn_online.set_rect((bx, p.y + 282, bw, bh))
        self.btn_quit.set_rect  ((bx, p.y + 374, bw, 46))
        return p

    def layout_online(self) -> pygame.Rect:
        """
        Positionne les widgets du menu en ligne et retourne le rectangle du panneau.

        :return: pygame.Rect du panneau en ligne.
        """
        p = self._center_panel(580, 390)
        bw, bh = p.width - 100, 56
        bx = p.x + 50
        self.btn_create.set_rect((bx, p.y + 160, bw, bh))
        self.btn_join.set_rect  ((bx, p.y + 236, bw, bh))
        self.btn_back.set_rect  ((bx, p.y + 318, bw, 46))
        return p

    def layout_solo(self) -> pygame.Rect:
        """
        Positionne les widgets du menu solo et retourne le rectangle du panneau.

        :return: pygame.Rect du panneau solo.
        """
        p = self._center_panel(580, 460)
        bw = p.width - 100
        bx = p.x + 50
        self.stepper.set_layout(bx, p.y + 190, bw)
        self.btn_launch.set_rect((bx, p.y + 300, bw, 54))
        self.btn_back.set_rect  ((bx, p.y + 376, bw, 46))
        return p

    def layout_join(self) -> pygame.Rect:
        """
        Positionne les widgets de l'écran de liste des salons et retourne le rectangle du panneau.
        Réserve une zone en bas pour la connexion directe par IP.

        :return: pygame.Rect occupant presque toute la fenêtre.
        """
        w, h = self.screen.get_size()
        # On laisse 110px en bas pour le bloc connexion directe
        p = pygame.Rect(60, 50, w - 120, h - 180)
        self.btn_back.set_rect((p.x, p.bottom + 70, 180, 42))
        # Champ IP + bouton en bas du panneau
        ip_y = p.bottom + 14
        ip_w = min(280, p.width - 240)
        self.ip_input.set_rect((p.x, ip_y, ip_w, 44))
        self.btn_connect_ip.set_rect((p.x + ip_w + 12, ip_y, 220, 44))
        return p

    # ── Dessin ───────────────────────────────────────────────────────────────

    def _logo(self, panel: pygame.Rect, f: dict):
        """
        Dessine le logo « LOUP-GAROU » avec ses lignes décoratives dans le panneau donné.

        :param panel: Rectangle du panneau dans lequel centrer le logo (pygame.Rect).
        :param f: Dictionnaire de polices retourné par fonts() (dict).
        """
        cx = panel.centerx
        lw = panel.width // 3
        pygame.draw.line(self.screen, GOLD_WARM,
                         (cx - lw // 2, panel.y + 42), (cx + lw // 2, panel.y + 42), 1)
        draw_text(self.screen, "LOUP-GAROU", f["title"], MOON_SILVER,
                  center=(cx, panel.y + 74), shadow=True)
        pygame.draw.line(self.screen, GOLD_WARM,
                         (cx - lw // 2, panel.y + 108), (cx + lw // 2, panel.y + 108), 1)

    def draw_main(self):
        """Dessine le menu principal : panneau vitré, logo, champ de pseudonyme et boutons solo/en ligne/quitter."""
        f = self.fonts()
        p = self.layout_main()
        draw_glass_panel(self.screen, p, radius=24)
        self._logo(p, f)
        draw_text(self.screen, "Choisis ton pseudonyme", f["small"], GOLD_PALE,
                  center=(p.centerx, p.y + 118))
        self.input_name.draw(self.screen, f["medium"])
        mouse = pygame.mouse.get_pos()
        self.btn_solo.draw  (self.screen, f["medium"], mouse)
        self.btn_online.draw(self.screen, f["medium"], mouse)
        self.btn_quit.draw  (self.screen, f["medium"], mouse)
        if self.message:
            draw_text(self.screen, self.message, f["small"], WOLF_RED,
                      center=(p.centerx, p.bottom + 28))

    def draw_online(self):
        """Dessine le menu en ligne : panneau vitré, titre et boutons créer/rejoindre/retour."""
        f = self.fonts()
        p = self.layout_online()
        draw_glass_panel(self.screen, p, radius=24)
        draw_text(self.screen, "MODE EN LIGNE", f["big"], MOON_SILVER,
                  center=(p.centerx, p.y + 52), shadow=True)
        draw_text(self.screen,
                  "Crée un salon ou rejoins-en un sur le réseau local.",
                  f["small"], GOLD_PALE, center=(p.centerx, p.y + 100))
        draw_text(self.screen,
                  "Les rôles se configurent dans le lobby.",
                  f["xs"] if "xs" in f else f["small"], GREY_DIM,
                  center=(p.centerx, p.y + 128))
        mouse = pygame.mouse.get_pos()
        self.btn_create.draw(self.screen, f["medium"], mouse)
        self.btn_join.draw  (self.screen, f["medium"], mouse)
        self.btn_back.draw  (self.screen, f["medium"], mouse)

    def draw_solo(self):
        """Dessine le menu solo : panneau vitré, titre, stepper de joueurs et boutons lancer/retour."""
        f = self.fonts()
        p = self.layout_solo()
        draw_glass_panel(self.screen, p, radius=24)
        draw_text(self.screen, "MODE SOLO", f["big"], MOON_SILVER,
                  center=(p.centerx, p.y + 52), shadow=True)
        draw_text(self.screen,
                  f"Tu joues contre des IA – minimum {MIN_PLAYERS} joueurs",
                  f["small"], GOLD_PALE, center=(p.centerx, p.y + 100))
        draw_text(self.screen,
                  "Rôles classiques (loup, voyante, sorcière) attribués automatiquement.",
                  f["xs"] if "xs" in f else f["small"], GREY_DIM,
                  center=(p.centerx, p.y + 132))
        mouse = pygame.mouse.get_pos()
        self.stepper.draw   (self.screen, f["medium"], f["small"], mouse)
        self.btn_launch.draw(self.screen, f["medium"], mouse)
        self.btn_back.draw  (self.screen, f["medium"], mouse)

    def draw_join(self):
        """Dessine l'écran de liste des salons avec connexion directe par IP en bas."""
        f = self.fonts()
        p = self.layout_join()
        mouse = pygame.mouse.get_pos()

        draw_glass_panel(self.screen, p, radius=22)
        draw_text(self.screen, "Salons disponibles", f["big"], MOON_SILVER,
                  center=(p.centerx, p.y + 44), shadow=True)

        self.row_rects = []
        servers = self.discovery.get_servers()
        y = p.y + 90
        if not servers:
            draw_text(self.screen,
                      "Aucun salon détecté automatiquement.",
                      f["medium"], GREY_DIM, center=(p.centerx, p.y + p.height // 2 - 16))
            draw_text(self.screen,
                      "Utilise la connexion directe ci-dessous si le broadcast est bloqué.",
                      f["small"], GOLD_PALE, center=(p.centerx, p.y + p.height // 2 + 18))
        else:
            self.selected_idx = max(0, min(self.selected_idx, len(servers) - 1))
            for i, srv in enumerate(servers):
                sel = (i == self.selected_idx)
                row = pygame.Rect(p.x + 18, y, p.width - 36, 82)
                pygame.draw.rect(self.screen, (58, 38, 88) if sel else (26, 18, 46),
                                 row, border_radius=16)
                pygame.draw.rect(self.screen, MIST_LIGHT if sel else (52, 42, 78),
                                 row, 2, border_radius=16)
                draw_text(self.screen, srv["name"], f["medium"], MOON_SILVER,
                          topleft=(row.x + 60, row.y + 10))
                draw_text(self.screen,
                          f"{srv['players']}/{srv['max_players']} joueurs  •  {srv['host']}",
                          f["small"], CYAN_COOL, topleft=(row.x + 60, row.y + 36))
                draw_text(self.screen,
                          f"Roles : {srv.get('roles', '')}",
                          f["xs"] if "xs" in f else f["small"], GREY_DIM,
                          topleft=(row.x + 60, row.y + 58))
                draw_text(self.screen, "🌕", f["big"], GOLD_WARM,
                          center=(row.x + 34, row.centery))
                if sel:
                    draw_text(self.screen, "▶ Cliquer pour rejoindre", f["small"],
                              GOLD_WARM, topleft=(row.right - 200, row.y + 30))
                self.row_rects.append((i, row))
                y += 92

        # ── Bloc connexion directe par IP ─────────────────────────────────────
        sep_y = p.bottom + 8
        w_total = self.screen.get_width()
        pygame.draw.line(self.screen, (70, 55, 100),
                         (p.x, sep_y), (p.x + p.width, sep_y), 1)
        draw_text(self.screen, "Connexion directe par IP",
                  f["small"], GOLD_PALE,
                  topleft=(p.x, sep_y + 4))
        # Affiche l'IP locale pour que l'hôte puisse la communiquer facilement
        from server_discovery import get_local_ip
        my_ip = get_local_ip()
        draw_text(self.screen, f"Ton IP : {my_ip}",
                  f["xs"] if "xs" in f else f["small"], GREY_DIM,
                  topleft=(p.x + p.width - 230, sep_y + 4))
        self.ip_input.draw(self.screen, f["medium"])
        self.btn_connect_ip.draw(self.screen, f["medium"], mouse)
        # ──────────────────────────────────────────────────────────────────────

        self.btn_back.draw(self.screen, f["small"], mouse)
        if self.message:
            draw_text(self.screen, self.message, f["small"], WOLF_RED,
                      center=(p.centerx, p.bottom + 118))

    # ── Événements ───────────────────────────────────────────────────────────

    def handle_main(self, event):
        """
        Traite les événements du menu principal : saisie du pseudonyme et clics sur les boutons.

        :param event: Événement Pygame à traiter (pygame.event.Event).
        """
        self.input_name.handle_event(event)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.btn_solo.is_clicked(event.pos):
                if self.ensure_name():
                    self.state = "solo"
            elif self.btn_online.is_clicked(event.pos):
                if self.ensure_name():
                    self.state = "online"
            elif self.btn_quit.is_clicked(event.pos):
                self.running = False

    def handle_online(self, event):
        """
        Traite les événements du menu en ligne : clics sur créer/rejoindre/retour.

        :param event: Événement Pygame à traiter (pygame.event.Event).
        """
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.btn_create.is_clicked(event.pos):
                if self.ensure_name():
                    self.create_server()
            elif self.btn_join.is_clicked(event.pos):
                if self.ensure_name():
                    self.state = "join"
                    self.selected_idx = 0
            elif self.btn_back.is_clicked(event.pos):
                self.reset_state()

    def handle_solo(self, event):
        """
        Traite les événements du menu solo : clics sur le stepper, lancer et retour.

        :param event: Événement Pygame à traiter (pygame.event.Event).
        """
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.stepper.handle_click(event.pos)
            if self.btn_launch.is_clicked(event.pos):
                self.launch_solo_game()
            elif self.btn_back.is_clicked(event.pos):
                self.reset_state()

    def _connect_direct_ip(self):
        """Tente une connexion directe à l'IP saisie dans ip_input."""
        ip = self.ip_input.text.strip()
        if not ip:
            self.message = "Entre une adresse IP avant de te connecter."
            return
        # Validation basique : 4 blocs numériques séparés par des points
        parts = ip.split(".")
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            self.message = f"Adresse IP invalide : {ip}"
            return
        self.message = ""
        self.launch_online_game(ip, shutdown_after=False)

    def handle_join(self, event):
        """
        Traite les événements de l'écran de liste des salons : clic sur une ligne,
        connexion directe par IP, navigation clavier et retour.

        :param event: Événement Pygame à traiter (pygame.event.Event).
        """
        # Le champ IP capture la frappe en priorité
        if self.ip_input.handle_event(event):
            # Entrée validée depuis le champ IP → connexion directe
            self._connect_direct_ip()
            return

        servers = self.discovery.get_servers()
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.btn_back.is_clicked(event.pos):
                self.state = "online"
                return
            if self.btn_connect_ip.is_clicked(event.pos):
                self._connect_direct_ip()
                return
            for i, rect in self.row_rects:
                if rect.collidepoint(event.pos):
                    self.selected_idx = i
                    self.join_selected()
                    return
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.state = "online"
            elif event.key == pygame.K_DOWN and servers:
                self.selected_idx = min(self.selected_idx + 1, len(servers) - 1)
            elif event.key == pygame.K_UP and servers:
                self.selected_idx = max(self.selected_idx - 1, 0)
            elif event.key == pygame.K_RETURN and servers and not self.ip_input.active:
                self.join_selected()

    # ── Boucle principale ────────────────────────────────────────────────────

    def run(self):
        """Lance la boucle principale du lanceur : animation, événements et rendu des différents états."""
        while self.running:
            dt = self.clock.tick(60)
            self.t += dt * 0.001

            draw_forest_scene(self.screen, self.t)
            self.particles.update()
            self.particles.draw(self.screen)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.VIDEORESIZE:
                    nw = max(MIN_W, event.w)
                    nh = max(MIN_H, event.h)
                    self.screen = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
                    self.particles.resize(nw, nh)
                elif self.state == "main":
                    self.handle_main(event)
                elif self.state == "online":
                    self.handle_online(event)
                elif self.state == "solo":
                    self.handle_solo(event)
                else:
                    self.handle_join(event)

            if self.state == "main":
                self.draw_main()
            elif self.state == "online":
                self.draw_online()
            elif self.state == "solo":
                self.draw_solo()
            else:
                self.draw_join()

            pygame.display.flip()

        if self.hosted_server is not None:
            try:
                self.hosted_server.shutdown()
            except Exception:
                pass
        self.discovery.stop()
        pygame.quit()


if __name__ == "__main__":
    Launcher().run()
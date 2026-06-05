"""
loup_garou_online.py – Interface graphique du mode multijoueur.

Communique avec loup_server.py via NetworkClient (JSON sur TCP).
L'état de jeu arrive entièrement du serveur via des paquets "state_sync" :
le client ne calcule rien lui-même, il affiche et envoie des actions.
"""
import json
import socket
import threading

import pygame

from loup_shared import (
    MIN_PLAYERS, MAX_PLAYERS,
    ROLE_CATALOG, CLASSIC_ROLE_NAMES, SPECIAL_ROLE_NAMES, AVAILABLE_ROLES,
    camp_balance, min_players_for_config, normalize_role_config, role_config_error,
    is_wolf_role, is_wolf_player, exclusive_role_conflict,
)
from server_discovery import get_local_ip
from loup_ui_theme import (
    WOLF_RED, BLOOD_RED,
    MIST_PURPLE, MIST_LIGHT,
    GOLD_WARM, GOLD_PALE,
    CYAN_COOL, WHITE_SOFT, GREY_DIM, GREY_DARK,
    MOON_SILVER,
    ROLE_WOLF_CLR, ROLE_VILLAGE_CLR,
    BTN_PRIMARY, BTN_PRIMARY_H,
    BTN_DANGER,
    BTN_SUCCESS, BTN_SUCCESS_H,
    BTN_NEUTRAL, BTN_NEUTRAL_H,
    BTN_BORDER,
    draw_gradient_bg, draw_glass_panel, draw_text, wrap_text,
    draw_moon, draw_tree_silhouette,
    ParticleSystem, Button, InputBox,
    scaled_fonts,
)

BASE_W, BASE_H = 1380, 900
MIN_W,  MIN_H  = 1060, 720
FPS = 60

BAR_VILLAGE = (32,  90, 160)
BAR_WOLVES  = (150, 18,  32)

ROLE_CAMP_COLOR = {
    "Loups":   ROLE_WOLF_CLR,
    "Village": ROLE_VILLAGE_CLR,
    "Solo":    (100, 60, 20),
    "Village / Loups": (80, 80, 40),
}

NIGHT_BG_TOP = (6,   4,  14)
NIGHT_BG_BOT = (30, 16,  50)
DAY_BG_TOP   = (30, 55,  80)
DAY_BG_BOT   = (70, 100, 60)

# Labels compacts pour les 10 étapes de nuit (2 rangées de 5)
NIGHT_STEP_INFO = [
    ("cupidon",    "CUP",  CYAN_COOL),
    ("wild_child", "ENF",  GOLD_WARM),
    ("seer",       "VOY",  CYAN_COOL),
    ("wolves",     "LOU",  WOLF_RED),
    ("father",     "PÈR",  (160, 90, 20)),
    ("witch",      "SOR",  (160, 60, 180)),
    ("salvateur",  "SAL",  (60, 160, 80)),
    ("fox",        "REN",  (180, 140, 40)),
    ("siren",      "SIR",  (60, 120, 200)),
    ("arsonist",   "PYR",  (220, 80, 20)),
]


# ── Réseau ────────────────────────────────────────────────────────────────────

class NetworkClient:
    def __init__(self, host: str, player_name: str, port: int = 5555):
        """
        Ouvre la connexion TCP, démarre le thread de réception et envoie le message de connexion.

        :param host: Adresse IP du serveur (str).
        :param player_name: Pseudonyme du joueur à envoyer au serveur (str).
        :param port: Port TCP du serveur (int), 5555 par défaut.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(8)
        self.sock.connect((host, port))
        self.sock.settimeout(None)
        self.messages: list = []
        self.lock = threading.Lock()
        self.running = True
        threading.Thread(target=self._listen, daemon=True).start()
        self.send({"type": "join", "name": player_name})

    def _listen(self):
        """Lit les messages entrants. Protocole : JSON terminé par '\n', un message par ligne."""
        buf = ""
        try:
            while self.running:
                data = self.sock.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        with self.lock:
                            self.messages.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        finally:
            self.running = False

    def send(self, payload: dict):
        """
        Sérialise payload en JSON et l'envoie au serveur (terminé par '\\n').

        :param payload: Dictionnaire à envoyer (dict).
        """
        try:
            self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError:
            self.running = False

    def pop_messages(self) -> list:
        """
        Retourne et vide la file des messages reçus de manière thread-safe.

        :return: list[dict] — messages JSON reçus depuis le dernier appel.
        """
        with self.lock:
            msgs = self.messages[:]
            self.messages.clear()
        return msgs

    def close(self):
        """Ferme proprement la connexion TCP et arrête le thread de réception."""
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


# ── Jeu en ligne ──────────────────────────────────────────────────────────────

class WerewolfOnlineGame:
    def __init__(self, host: str, player_name: str):
        """
        Initialise la fenêtre, le client réseau, tous les boutons/champs et l'état local synchronisé depuis le serveur.

        :param host: Adresse IP du serveur à rejoindre (str).
        :param player_name: Pseudonyme du joueur local (str).
        """
        pygame.init()
        self.screen = pygame.display.set_mode((BASE_W, BASE_H), pygame.RESIZABLE)
        pygame.display.set_caption("Loup-Garou - En ligne")
        self.clock  = pygame.time.Clock()
        self.t      = 0.0
        self.network = NetworkClient(host, player_name)
        self.running = True
        self.return_to_lobby = False  # True = retour au lobby serveur, False = quitter

        # État de base
        self.state       = "connecting"
        self.server_name = "Salon"
        self.message     = "Connexion au serveur..."
        self.action_hint = ""
        self.players: list     = []
        self.your_id           = None
        self.host_id           = None
        self.phase             = "lobby"
        self.prev_phase        = None
        self.day_count         = 0
        self.winner            = None
        self.selected_target   = None
        self.last_deaths: list = []
        self.night_target_name = None
        self.seer_result       = None
        self.can_act           = False
        self.can_chat          = True
        self.has_voted         = False
        self.votes_cast        = 0
        self.votes_needed      = 0
        self.witch_heal_available   = True
        self.witch_poison_available = True
        self.father_can_infect = False
        self.night_step        = "wolves"
        self.max_players       = 8
        self.role_config       = normalize_role_config({})
        self.chat_history: list = []
        self.chat_scroll        = 0
        self.role_scroll        = 0
        self.selected_role_name = CLASSIC_ROLE_NAMES[0]
        self.show_role_info     = False

        # Nouveaux champs de synchronisation serveur
        self.multi_select_list: list  = []   # sélection multiple (Cupidon x2, Renard x3)
        self.night_targets_needed     = 1    # 1 normal, 2 cupidon, 3 renard
        self.is_hunter_turn           = False
        self.sniper_target_name       = None
        self.fox_result               = None
        self.fox_power_active         = True
        self.lover_partner_name       = None
        self.mentor_name              = None
        self.charmed_list: list       = []
        self.fueled_list: list        = []
        self.salvateur_last_name      = None
        self.wolf_votes_visible: dict = {}   # {nom_votant: nom_cible} — loups seulement
        self.day_votes_visible:  dict = {}   # {nom_votant: nom_cible} — tout le monde
        self.witch_save_blocked       = False  # True si père des loups a infecté cette nuit

        # Historique et journal de jeu
        self.execution_history: list  = []   # [{jour, nom, role}]
        self.daily_deaths: dict       = {}   # {jour_str: [noms]}
        self.initial_roles: dict      = {}   # {player_id: role}
        self._dawn_shown: set         = set()  # jours dont l'aube a déjà été affichée
        self.last_deaths_with_roles: list = []  # [{nom, role}] pour l'affichage aube

        # Boutons de base
        self.btn_start         = Button("LANCER LA PARTIE",  BTN_SUCCESS, BTN_SUCCESS_H)
        self.btn_vote          = Button("VALIDER L'ACTION",  BTN_PRIMARY, BTN_PRIMARY_H)
        self.btn_sync          = Button("SYNC",              BTN_NEUTRAL, BTN_NEUTRAL_H)
        self.btn_skip          = Button("PASSER",            BTN_NEUTRAL, BTN_NEUTRAL_H)
        self.btn_save          = Button("SAUVER",            BTN_SUCCESS,    BTN_SUCCESS_H)
        self.btn_poison        = Button("EMPOISONNER",       (90, 24, 80),   (120, 38, 108))
        self.btn_father_infect = Button("INFECTER",          (140, 60, 10),  (180, 90, 20))
        self.btn_father_skip   = Button("PASSER",            BTN_NEUTRAL,    BTN_NEUTRAL_H)
        self.btn_send_chat     = Button("ENVOYER",           BTN_PRIMARY,    BTN_PRIMARY_H)
        self.btn_end           = Button("RETOUR AU MENU SERVEUR", BTN_NEUTRAL,    BTN_NEUTRAL_H)
        self.btn_dawn_advance  = Button("☀  PASSER AU JOUR",     BTN_SUCCESS,    BTN_SUCCESS_H)
        self.chat_input        = InputBox(placeholder="Écris un message...", max_len=220)

        # Nouveaux boutons pour les rôles additionnels
        self.btn_salvateur_skip  = Button("PASSER",          BTN_NEUTRAL,    BTN_NEUTRAL_H)
        self.btn_siren_skip      = Button("PASSER",          BTN_NEUTRAL,    BTN_NEUTRAL_H)
        self.btn_arsonist_ignite = Button("ENFLAMMER",       (200, 60, 10),  (240, 90, 30))
        self.btn_arsonist_skip   = Button("PASSER",          BTN_NEUTRAL,    BTN_NEUTRAL_H)
        self.btn_hunter_shoot    = Button("TIRER",           (180, 20, 20),  (220, 40, 40))
        self.btn_cupidon_confirm = Button("CONFIRMER",       BTN_SUCCESS,    BTN_SUCCESS_H)
        self.btn_fox_confirm     = Button("SENTIR",          (40, 180, 180), (60, 220, 220))
        self.btn_fox_skip        = Button("PASSER",          BTN_NEUTRAL,    BTN_NEUTRAL_H)
        self.btn_wild_confirm    = Button("CHOISIR MENTOR",  BTN_SUCCESS,    BTN_SUCCESS_H)

        self.player_rects: list    = []
        self.role_row_rects: dict  = {}
        self.role_minus_rects: dict = {}
        self.role_plus_rects: dict  = {}
        self.count_left_rect      = pygame.Rect(0, 0, 0, 0)
        self.count_right_rect     = pygame.Rect(0, 0, 0, 0)
        self.role_list_rect       = pygame.Rect(0, 0, 0, 0)
        self.role_info_close_rect = pygame.Rect(0, 0, 0, 0)
        self.btn_end_rect         = pygame.Rect(0, 0, 0, 0)

        self.particles = ParticleSystem(BASE_W, BASE_H, 35)
        self.compute_layout()

    # ── Fonts / Layout ───────────────────────────────────────────────────────

    def fonts(self) -> dict:
        """
        Retourne le dictionnaire de polices mises à l'échelle selon la taille courante de la fenêtre.

        :return: dict avec les clés 'title', 'big', 'medium', 'small', 'xs'.
        """
        w, h = self.screen.get_size()
        return scaled_fonts(w, h, BASE_W, BASE_H)

    def compute_layout(self):
        """Recalcule les rectangles de toutes les zones et repositionne tous les boutons selon la taille courante."""
        w, h = self.screen.get_size()
        pad = 16
        self.top_rect    = pygame.Rect(pad, pad, w - pad * 2, 66)
        self.left_rect   = pygame.Rect(pad, 90, int(w * 0.22), h - 150)
        self.center_rect = pygame.Rect(self.left_rect.right + pad, 90,
                                       int(w * 0.39), h - 150)
        self.chat_rect   = pygame.Rect(self.center_rect.right + pad, 90,
                                       w - self.left_rect.width - self.center_rect.width - pad * 4,
                                       h - 150)
        self.bottom_rect = pygame.Rect(pad, h - 50, w - pad * 2, 36)

        bx     = self.center_rect.x + 20
        by     = self.center_rect.bottom - 56
        full_w = self.center_rect.width - 40
        bw     = min(250, full_w)
        skip_x = bx + bw + 10
        skip_w = max(80, self.center_rect.right - 20 - skip_x)

        self.btn_start.set_rect((bx, by, full_w, 44))
        self.btn_vote.set_rect ((bx, by, bw, 44))

        # Sorcière : 3 colonnes égales
        wb = max(70, full_w // 3 - 6)
        self.btn_save.set_rect  ((bx,             by, wb, 44))
        self.btn_poison.set_rect((bx + wb + 8,    by, wb, 44))
        self.btn_skip.set_rect  ((bx + wb*2 + 16, by, max(60, full_w - wb*2 - 16), 44))

        # Père des Loups : 2 colonnes
        fw = max(90, full_w // 2 - 6)
        self.btn_father_infect.set_rect((bx,          by, fw, 44))
        self.btn_father_skip.set_rect  ((bx + fw + 8, by, max(60, full_w - fw - 8), 44))

        # Salvateur : vote=protéger + skip
        self.btn_salvateur_skip.set_rect((skip_x, by, skip_w, 44))

        # Sirène : vote=envoûter + skip
        self.btn_siren_skip.set_rect((skip_x, by, skip_w, 44))

        # Pyromane : 3 colonnes (vote=asperger, ignite, skip)
        arb = max(70, full_w // 3 - 6)
        self.btn_arsonist_ignite.set_rect((bx + arb + 8,    by, arb, 44))
        self.btn_arsonist_skip.set_rect  ((bx + arb*2 + 16, by, max(60, full_w - arb*2 - 16), 44))

        # Chasseur : bouton pleine largeur
        self.btn_hunter_shoot.set_rect((bx, by, full_w, 44))

        # Cupidon : bouton confirmer pleine largeur
        self.btn_cupidon_confirm.set_rect((bx, by, full_w, 44))

        # Renard : sentir (bw) + passer (skip_w)
        self.btn_fox_confirm.set_rect((bx,     by, bw,     44))
        self.btn_fox_skip.set_rect   ((skip_x, by, skip_w, 44))

        # Enfant sauvage : confirmer pleine largeur
        self.btn_wild_confirm.set_rect((bx, by, full_w, 44))

        # Fin de partie
        ew = min(300, full_w)
        self.btn_end.set_rect((self.center_rect.centerx - ew // 2, by, ew, 44))

        # Phase aube : bouton "Passer au Jour" (hôte seulement)
        daw = min(260, full_w)
        self.btn_dawn_advance.set_rect((self.center_rect.centerx - daw // 2, by, daw, 44))

        self.btn_sync.set_rect     ((self.top_rect.right - 110, self.top_rect.y + 13, 90, 38))
        self.chat_input.set_rect   ((self.chat_rect.x + 12, self.chat_rect.bottom - 54,
                                     self.chat_rect.width - 110, 40))
        self.btn_send_chat.set_rect((self.chat_rect.right - 96, self.chat_rect.bottom - 54, 80, 40))

        # Sous-zones lobby dans center_rect
        top_x = self.center_rect.x + 14
        top_w = self.center_rect.width - 28
        self.player_count_rect = pygame.Rect(top_x, self.center_rect.y + 80,  top_w, 96)
        self.balance_rect      = pygame.Rect(top_x, self.center_rect.y + 188, top_w, 76)
        self.roles_title_y     = self.center_rect.y + 278
        self.roles_notice_y    = self.center_rect.y + 320
        role_list_top          = self.center_rect.y + 350
        role_list_bot          = self.center_rect.bottom - 70
        self.role_list_rect    = pygame.Rect(top_x, role_list_top,
                                             top_w, max(60, role_list_bot - role_list_top))

    # ── Accesseurs ───────────────────────────────────────────────────────────

    def current_role(self):
        """Retourne le rôle du joueur local ou None si non encore assigné."""
        if self.your_id is None:
            return None
        for p in self.players:
            if p["id"] == self.your_id:
                return p.get("role")
        return None

    def is_host(self) -> bool:
        """Retourne True si le joueur local est l'hôte de la partie."""
        return self.your_id is not None and self.your_id == self.host_id

    # ── Réseau ───────────────────────────────────────────────────────────────

    def process_network(self):
        """Traite tous les messages réseau reçus depuis le serveur et met à jour l'état local en conséquence."""
        for msg in self.network.pop_messages():
            mt = msg.get("type")
            if mt == "state_sync":
                self.state             = "game"
                self.server_name       = msg.get("server_name", self.server_name)
                new_phase              = msg.get("phase", "lobby")
                self.day_count         = msg.get("day_count", 0)
                self.players           = msg.get("players", [])
                self.your_id           = msg.get("your_id", self.your_id)
                self.host_id           = msg.get("host_id", self.host_id)
                self.message           = msg.get("message", self.message)
                self.last_deaths       = msg.get("last_deaths", [])
                self.night_target_name = msg.get("night_target_name")
                self.winner            = msg.get("winner")
                self.can_act           = msg.get("can_act", False)
                self.can_chat          = msg.get("can_chat", True)
                self.has_voted         = msg.get("has_voted", False)
                self.votes_cast        = msg.get("votes_cast", 0)
                self.votes_needed      = msg.get("votes_needed", 0)
                self.action_hint       = msg.get("action_hint", "")
                self.seer_result       = msg.get("seer_result")
                self.max_players       = msg.get("max_players", self.max_players)
                self.witch_heal_available   = msg.get("witch_heal_available", self.witch_heal_available)
                self.witch_poison_available = msg.get("witch_poison_available", self.witch_poison_available)
                self.witch_save_blocked     = msg.get("witch_save_blocked", False)
                self.father_can_infect = msg.get("father_can_infect", False)
                self.night_step        = msg.get("night_step", "wolves")
                self.role_config       = normalize_role_config(
                    msg.get("role_config", self.role_config))

                # Nouveaux champs
                self.night_targets_needed  = msg.get("night_targets_needed", 1)
                self.is_hunter_turn        = msg.get("is_hunter_turn", False)
                self.sniper_target_name    = msg.get("sniper_target_name")
                self.fox_result            = msg.get("fox_result")
                self.fox_power_active      = msg.get("fox_power_active", True)
                self.lover_partner_name    = msg.get("lover_partner_name")
                self.mentor_name           = msg.get("mentor_name")
                self.charmed_list          = msg.get("charmed_list", [])
                self.fueled_list           = msg.get("fueled_list", [])
                self.salvateur_last_name   = msg.get("salvateur_last_name")
                self.wolf_votes_visible    = msg.get("wolf_votes_visible", {})
                self.day_votes_visible     = msg.get("day_votes_visible", {})
                self.execution_history     = msg.get("execution_history", self.execution_history)
                self.daily_deaths          = msg.get("daily_deaths", self.daily_deaths)
                self.initial_roles         = msg.get("initial_roles", self.initial_roles)
                self.last_deaths_with_roles = msg.get("last_deaths_with_roles",
                                                       getattr(self, "last_deaths_with_roles", []))

                # Message amoureux reçu uniquement par les concernés
                lovers_msg = msg.get("lovers_msg")
                if lovers_msg:
                    # Ajoute au chat local si pas déjà présent
                    already = any(e.get("message") == lovers_msg for e in self.chat_history)
                    if not already:
                        self.chat_history.append({
                            "author": "[Systeme]",
                            "message": lovers_msg,
                            "system": True,
                            "wolf_only": False,
                        })

                # Réinitialise la sélection à chaque changement de phase
                if new_phase != self.prev_phase:
                    self.selected_target   = None
                    self.multi_select_list = []
                    self.prev_phase        = new_phase
                self.phase = new_phase

                if (self.selected_role_name is None
                        or self.selected_role_name not in self.role_config):
                    self.selected_role_name = (CLASSIC_ROLE_NAMES[0]
                                               if CLASSIC_ROLE_NAMES else
                                               next(iter(self.role_config), None))
                old = len(self.chat_history)
                new_chat = msg.get("chat_history", [])
                if new_chat:
                    self.chat_history = new_chat
                if len(self.chat_history) > old:
                    self.chat_scroll = 0
                # Annule la sélection si le joueur ciblé est mort
                if (self.selected_target is not None
                        and all(p["id"] != self.selected_target or not p["alive"]
                                for p in self.players)):
                    self.selected_target = None
                self.multi_select_list = [
                    pid for pid in self.multi_select_list
                    if any(p["id"] == pid and p["alive"] for p in self.players)
                ]
            elif mt == "error":
                self.message = "⚠ " + msg.get("message", "")
            elif mt == "info":
                self.message = msg.get("message", self.message)

    def _send_role_config_update(self, role_name: str, delta: int):
        """
        Envoie au serveur une mise à jour du nombre d'exemplaires d'un rôle (hôte uniquement).

        :param role_name: Nom du rôle à modifier (str).
        :param delta: Variation souhaitée (+1 ou -1) (int).
        """
        if not self.is_host() or self.phase != "lobby":
            return
        if role_name == "Villageois":
            self._send_max_players_update(delta)
            return
        new = dict(self.role_config)
        cur = new.get(role_name, 0)
        mx  = ROLE_CATALOG[role_name]["max"]
        val = max(0, min(mx, cur + delta))
        if role_name == "Loup-garou":
            val = max(1, val)
        new[role_name] = val
        # Vérification d'exclusivité (Enfant sauvage ↔ Villageois Maudit)
        if delta > 0 and val > 0:
            conflict_msg = exclusive_role_conflict(role_name, self.role_config)
            if conflict_msg:
                self.message = f"⚠ {conflict_msg}"
                return
        if sum(new.values()) > MAX_PLAYERS:
            self.message = f"Trop de roles (max {MAX_PLAYERS} joueurs)."
            return
        if min_players_for_config(new) > MAX_PLAYERS:
            self.message = "Configuration impossible."
            return
        req = min_players_for_config(new)
        if self.max_players < req:
            self.network.send({"type": "update_max_players", "max_players": req})
        if new != self.role_config:
            self.network.send({"type": "update_role_config", "role_config": new})

    def _send_max_players_update(self, delta: int):
        """
        Envoie au serveur une mise à jour du nombre maximum de joueurs du salon (hôte uniquement).

        :param delta: Variation souhaitée (+1 ou -1) (int).
        """
        if not self.is_host() or self.phase != "lobby":
            return
        req = min_players_for_config(self.role_config)
        tgt = max(MIN_PLAYERS, min(MAX_PLAYERS, self.max_players + delta))
        tgt = max(tgt, len(self.players), req)
        if tgt != self.max_players:
            self.network.send({"type": "update_max_players", "max_players": tgt})

    # ── Méthodes d'envoi des actions ─────────────────────────────────────────

    def send_action(self):
        """Action principale selon la phase (lancer, voter, action de nuit de base)."""
        role = self.current_role()
        if self.phase == "lobby":
            self.network.send({"type": "start_game"})
            return
        if self.phase == "day" and self.selected_target is not None and not self.has_voted:
            self.network.send({"type": "vote_action", "target": self.selected_target})
            self.selected_target = None
            return
        if self.phase == "night" and self.can_act and self.selected_target is not None:
            step = self.night_step
            if step == "wolves" and is_wolf_role(role):
                self.network.send({"type": "night_action", "action": "wolf_kill",
                                   "target": self.selected_target})
                self.selected_target = None
            elif step == "seer" and role == "Voyante":
                self.network.send({"type": "night_action", "action": "seer_peek",
                                   "target": self.selected_target})
                self.selected_target = None
            elif step == "salvateur" and role == "Salvateur":
                self.network.send({"type": "night_action", "action": "salvateur_protect",
                                   "target": self.selected_target})
                self.selected_target = None
            elif step == "siren" and role == "Sirène":
                self.network.send({"type": "night_action", "action": "siren_charm",
                                   "target": self.selected_target})
                self.selected_target = None
            elif step == "arsonist" and role == "Pyromane":
                self.network.send({"type": "night_action", "action": "arsonist_fuel",
                                   "target": self.selected_target})
                self.selected_target = None
            elif step == "wild_child" and role == "Enfant sauvage":
                self.network.send({"type": "night_action", "action": "wild_child_choose",
                                   "target": self.selected_target})
                self.selected_target = None

    def send_witch_save(self):
        """Envoie l'action de soin de la Sorcière au serveur."""
        self.network.send({"type": "night_action", "action": "witch_save"})

    def send_witch_poison(self):
        """Envoie l'action d'empoisonnement de la Sorcière sur la cible sélectionnée."""
        if self.selected_target is not None:
            self.network.send({"type": "night_action", "action": "witch_poison",
                               "target": self.selected_target})
            self.selected_target = None

    def send_witch_skip(self):
        """Envoie le passage de tour de la Sorcière au serveur."""
        self.network.send({"type": "night_action", "action": "witch_skip"})

    def send_father_infect(self):
        """Envoie l'action d'infection du Père des loups sur la victime des loups."""
        self.network.send({"type": "night_action", "action": "father_infect"})

    def send_father_skip(self):
        """Envoie le passage de tour du Père des loups au serveur."""
        self.network.send({"type": "night_action", "action": "father_skip"})

    def send_salvateur_skip(self):
        """Envoie le passage de tour du Salvateur au serveur."""
        self.network.send({"type": "night_action", "action": "salvateur_skip"})

    def send_siren_skip(self):
        """Envoie le passage de tour de la Sirène au serveur."""
        self.network.send({"type": "night_action", "action": "siren_skip"})

    def send_arsonist_ignite(self):
        """Envoie l'action d'ignition du Pyromane (brûle tous les aspergés) au serveur."""
        self.network.send({"type": "night_action", "action": "arsonist_ignite"})

    def send_arsonist_skip(self):
        """Envoie le passage de tour du Pyromane au serveur."""
        self.network.send({"type": "night_action", "action": "arsonist_skip"})

    def send_fox_sense(self):
        """Envoie l'action de flair du Renard sur les 3 joueurs sélectionnés au serveur."""
        if len(self.multi_select_list) == 3:
            self.network.send({"type": "night_action", "action": "fox_sense",
                               "targets": list(self.multi_select_list)})
            self.multi_select_list = []

    def send_fox_skip(self):
        """Envoie le passage de tour du Renard au serveur."""
        self.network.send({"type": "night_action", "action": "fox_skip"})

    def send_cupidon_confirm(self):
        """Envoie la confirmation des 2 amoureux choisis par Cupidon au serveur."""
        if len(self.multi_select_list) == 2:
            self.network.send({"type": "night_action", "action": "cupidon_choose",
                               "targets": list(self.multi_select_list)})
            self.multi_select_list = []

    def send_hunter_shoot(self):
        """Envoie la cible du Chasseur (joueur qu'il emporte dans la mort) au serveur."""
        if self.selected_target is not None:
            self.network.send({"type": "night_action", "action": "hunter_shoot",
                               "target": self.selected_target})
            self.selected_target = None

    def send_chat(self):
        """Envoie le message saisi dans le champ de chat au serveur."""
        txt = self.chat_input.consume()
        if txt:
            self.network.send({"type": "chat_message", "message": txt})

    # ── Fond animé ───────────────────────────────────────────────────────────

    def _draw_bg(self):
        """Dessine le fond animé jour ou nuit (dégradé, astre, silhouettes d'arbres, particules)."""
        w, h = self.screen.get_size()
        is_day = (self.phase == "day")
        if is_day:
            draw_gradient_bg(self.screen, DAY_BG_TOP, DAY_BG_BOT)
            sx, sy = int(w * 0.85), int(h * 0.12)
            sr = max(16, int(min(w, h) * 0.05))
            for step in range(5):
                hr = sr + step * 5
                ss = pygame.Surface((hr * 2 + 4, hr * 2 + 4), pygame.SRCALPHA)
                a = max(0, 38 - step * 8)
                pygame.draw.circle(ss, (255, 230, 100, a), (hr + 2, hr + 2), hr)
                self.screen.blit(ss, (sx - hr - 2, sy - hr - 2))
            pygame.draw.circle(self.screen, (255, 240, 120), (sx, sy), sr)
            tree_col = (18, 48, 24)
        else:
            draw_gradient_bg(self.screen, NIGHT_BG_TOP, NIGHT_BG_BOT)
            draw_moon(self.screen, int(w * 0.86), int(h * 0.13),
                      max(16, int(min(w, h) * 0.055)), self.t)
            tree_col = (5, 4, 12)

        for xi, hi in [(0.0, 0.18), (0.08, 0.14), (0.93, 0.16), (0.99, 0.18)]:
            draw_tree_silhouette(self.screen, int(xi * w), h, int(hi * h), tree_col)

        self.particles.update()
        self.particles.draw(self.screen)

    # ── Liste joueurs ────────────────────────────────────────────────────────

    def draw_player_list(self):
        """Dessine le panneau gauche avec la liste des joueurs, leur statut, rôle révélé et icônes d'état."""
        f = self.fonts()
        draw_glass_panel(self.screen, self.left_rect, radius=22)
        draw_text(self.screen, "Joueurs", f["big"], MOON_SILVER,
                  topleft=(self.left_rect.x + 12, self.left_rect.y + 10), shadow=True)
        alive = sum(1 for p in self.players if p.get("alive"))
        # Compteur vivants / total + indicateur de jour
        jour_label = ""
        if self.phase in ("night", "dawn"):
            jour_label = f" — Nuit {self.day_count}"
        elif self.phase == "day":
            jour_label = f" — Jour {self.day_count}"
        draw_text(self.screen, f"{alive}/{len(self.players)}{jour_label}",
                  f["xs"], GOLD_PALE,
                  topleft=(self.left_rect.x + 12, self.left_rect.y + 48))
        # Dernières exécutions (historique compact)
        if self.execution_history and self.phase in ("day", "dawn", "night"):
            exec_y = self.left_rect.y + 64
            draw_text(self.screen, "Exécutés :", f["xs"], GREY_DIM,
                      topleft=(self.left_rect.x + 12, exec_y))
            for entry in self.execution_history[-3:]:
                exec_y += 14
                if exec_y > self.left_rect.y + 100:
                    break
                draw_text(self.screen,
                          f"J{entry['jour']} {entry['nom'][:10]}",
                          f["xs"], (160, 80, 80),
                          topleft=(self.left_rect.x + 14, exec_y))

        self.player_rects = []
        # Décaler y si on affiche l'historique d'exécutions
        exec_offset = min(3, len(self.execution_history)) * 14 if self.execution_history else 0
        y = self.left_rect.y + 72 + (exec_offset if self.phase in ("day","dawn","night") else 0)
        my_role = self.current_role() or ""

        for p in self.players:
            row_h = 50
            rect  = pygame.Rect(self.left_rect.x + 8, y, self.left_rect.width - 16, row_h)

            if y + row_h > self.left_rect.bottom - 6:
                break

            # Sélectionné si dans multi_select_list ou selected_target
            in_multi = p["id"] in self.multi_select_list
            sel   = (p["id"] == self.selected_target) or in_multi
            is_me = (p["id"] == self.your_id)
            dead  = not p["alive"]

            bg = (14, 10, 28) if dead else ((56, 34, 84) if sel else (26, 18, 48))
            pygame.draw.rect(self.screen, bg, rect, border_radius=12)
            bord_col = GOLD_WARM if in_multi else (MIST_LIGHT if sel else (44, 36, 70))
            pygame.draw.rect(self.screen, bord_col, rect, 2, border_radius=12)

            my_player = next((pl for pl in self.players if pl["id"] == self.your_id), {})
            i_am_wolf_side = is_wolf_player(my_player)
            p_is_wolf_side = is_wolf_player(p)
            reveal = dead or is_me or (p_is_wolf_side and i_am_wolf_side)
            role_str = (p.get("revealed_role") or p.get("role") or "?") if reveal else "?"
            infected_str = (" (Infect)" if (reveal and p.get("infected")
                            and not is_wolf_role(p.get("role", ""))) else "")

            bc = ROLE_WOLF_CLR if (is_wolf_role(role_str) or p.get("infected")) else MIST_PURPLE
            badge = pygame.Rect(rect.x + 7, rect.y + 9, 36, 28)
            pygame.draw.rect(self.screen, bc, badge, border_radius=8)
            # Utiliser l'emoji du catalogue si disponible, sinon 2 premières lettres
            role_icon = ROLE_CATALOG.get(role_str, {}).get("ui_icon", "")
            if not role_icon or role_str == "?":
                role_icon = role_str[:2].upper() if role_str not in ("?",) else "?"
            draw_text(self.screen, role_icon, f["xs"], WHITE_SOFT, center=badge.center)

            name_col = GREY_DARK if dead else (GOLD_WARM if is_me else WHITE_SOFT)
            draw_text(self.screen, p["name"], f["xs"], name_col,
                      topleft=(rect.x + 50, rect.y + 5))
            role_display = (("Elimine - " + role_str) if dead
                            else (role_str + infected_str))
            draw_text(self.screen, role_display,
                      f["xs"], WOLF_RED if dead else CYAN_COOL,
                      topleft=(rect.x + 50, rect.y + 24))

            # Icônes d'état (amoureux, envoûté, aspergé)
            icons = []
            if p.get("is_lover"):
                icons.append(("♥", WOLF_RED))
            if p.get("is_charmed"):
                icons.append(("♪", CYAN_COOL))
            if p.get("is_fueled"):
                icons.append(("🔥", (220, 100, 20)))
            ix = rect.right - 8
            for icon, ic in reversed(icons):
                draw_text(self.screen, icon, f["xs"], ic, topright=(ix, rect.y + 6))
                ix -= 16

            if is_me:
                pygame.draw.circle(self.screen, GOLD_WARM, (rect.right - 10, rect.centery), 5)

            self.player_rects.append((p["id"], rect))
            y += row_h + 4

    # ── Panneau Lobby ────────────────────────────────────────────────────────

    def draw_player_count_selector(self, rect: pygame.Rect, f: dict):
        """
        Dessine le sélecteur de nombre maximum de joueurs du salon avec flèches de navigation.

        :param rect: Rectangle de dessin alloué au widget (pygame.Rect).
        :param f: Dictionnaire des polices (dict).
        """
        draw_text(self.screen, "Joueurs dans le salon", f["medium"], MOON_SILVER,
                  topleft=(rect.x, rect.y + 4))
        pill = pygame.Rect(rect.x, rect.y + 36, rect.width, 44)
        pygame.draw.rect(self.screen, (10, 8, 24), pill, border_radius=22)

        slots = 5
        sw = max(1, pill.width // slots)
        vals = [max(MIN_PLAYERS, min(MAX_PLAYERS, self.max_players - 2 + i))
                for i in range(slots)]
        ax = pill.x + 2 * sw
        pygame.draw.rect(self.screen, MIST_PURPLE,
                         (ax + 3, pill.y + 3, sw - 6, pill.height - 6), border_radius=18)
        for i, v in enumerate(vals):
            cx = pill.x + sw * i + sw // 2
            col  = MOON_SILVER if i == 2 else GREY_DIM
            fnt  = f["medium"] if i == 2 else f["xs"]
            draw_text(self.screen, str(v), fnt, col, center=(cx, pill.centery))

        left_ok  = (self.is_host()
                    and self.max_players > max(MIN_PLAYERS, len(self.players),
                                               min_players_for_config(self.role_config)))
        right_ok = self.is_host() and self.max_players < MAX_PLAYERS
        self.count_left_rect  = pygame.Rect(pill.x + 4,      pill.y + 4, 36, 36)
        self.count_right_rect = pygame.Rect(pill.right - 40,  pill.y + 4, 36, 36)
        for r2, sym, ok in [(self.count_left_rect, "<", left_ok),
                            (self.count_right_rect, ">", right_ok)]:
            col = WHITE_SOFT if ok else GREY_DIM
            pygame.draw.ellipse(self.screen, col, r2)
            draw_text(self.screen, sym, f["medium"], (10, 8, 22), center=r2.center)

    def draw_balance_bar(self, rect: pygame.Rect, f: dict):
        """
        Dessine la barre d'équilibre village/loups et le nombre de joueurs connectés.

        :param rect: Rectangle de dessin alloué au widget (pygame.Rect).
        :param f: Dictionnaire des polices (dict).
        """
        bal = camp_balance(self.max_players, self.role_config)
        draw_text(self.screen, "Equilibre", f["medium"], MOON_SILVER,
                  topleft=(rect.x, rect.y + 2))
        label = ("Equilibre" if 0.38 < bal["village_ratio"] < 0.62
                 else ("Village favori" if bal["village_ratio"] > 0.62 else "Loups favoris"))
        draw_text(self.screen, label, f["xs"], GOLD_PALE,
                  topleft=(rect.x + rect.width // 3, rect.y + 4))
        bar = pygame.Rect(rect.x, rect.y + 32, rect.width, 16)
        vw = max(1, int(bar.width * bal["village_ratio"]))
        ww = max(1, bar.width - vw)
        pygame.draw.rect(self.screen, BAR_VILLAGE, (bar.x, bar.y, vw, bar.height), border_radius=8)
        pygame.draw.rect(self.screen, BAR_WOLVES,  (bar.x + vw, bar.y, ww, bar.height), border_radius=8)
        pygame.draw.ellipse(self.screen, WHITE_SOFT, (bar.x + vw - 8, bar.y - 3, 16, bar.height + 6))
        draw_text(self.screen, f"Connectes : {len(self.players)}/{self.max_players}",
                  f["xs"], CYAN_COOL, topleft=(rect.x, rect.y + 54))

    def _villager_count(self) -> int:
        """
        Calcule le nombre de Villageois génériques restants après attribution des rôles spéciaux.
        Les Villageois sont un rôle de remplissage passif : leur nombre est toujours le résidu
        (joueurs sans rôle spécial) et ne peut pas être augmenté manuellement.

        :return: Nombre de Villageois (int), toujours >= 0.
        """
        special_count = sum(v for k, v in self.role_config.items() if k in AVAILABLE_ROLES)
        return max(0, self.max_players - special_count)

    def draw_role_rows(self, f: dict):
        """
        Dessine la liste défilante des rôles avec sections, compteurs et boutons +/- pour l'hôte.

        :param f: Dictionnaire des polices (dict).
        """
        self.role_row_rects   = {}
        self.role_minus_rects = {}
        self.role_plus_rects  = {}

        sections = [("Roles classiques", CLASSIC_ROLE_NAMES),
                    ("Roles speciaux",   SPECIAL_ROLE_NAMES)]
        ROW_H   = 46
        HEAD_H  = 26
        GAP     = 4
        total_h = 0
        flat: list = []
        for title, names in sections:
            flat.append(("header", title))
            total_h += HEAD_H + 4
            for n in names:
                flat.append(("role", n))
                total_h += ROW_H + GAP
            total_h += 4

        vis_h   = self.role_list_rect.height - 8
        max_scr = max(0, total_h - vis_h)
        self.role_scroll = max(0, min(self.role_scroll, max_scr))
        cy      = self.role_list_rect.y + 4 - self.role_scroll
        old_clip = self.screen.get_clip()
        self.screen.set_clip(self.role_list_rect)
        mouse = pygame.mouse.get_pos()

        for kind, value in flat:
            if kind == "header":
                if cy + HEAD_H > self.role_list_rect.bottom and cy < self.role_list_rect.top:
                    cy += HEAD_H + 4
                    continue
                pygame.draw.rect(self.screen, (60, 44, 98),
                                 (self.role_list_rect.x + 4, cy,
                                  self.role_list_rect.width - 12, HEAD_H),
                                 border_radius=10)
                draw_text(self.screen, value, f["xs"], GOLD_PALE,
                          topleft=(self.role_list_rect.x + 12, cy + 4))
                cy += HEAD_H + 4
                continue

            rn  = value
            det = ROLE_CATALOG.get(rn)
            if det is None:
                cy += ROW_H + GAP
                continue

            row = pygame.Rect(self.role_list_rect.x + 4, cy,
                              self.role_list_rect.width - 12, ROW_H)
            sel = (rn == self.selected_role_name)
            hov = row.collidepoint(mouse)
            bg  = (70, 48, 108) if sel else ((50, 36, 80) if hov else (30, 22, 52))
            pygame.draw.rect(self.screen, bg, row, border_radius=12)
            pygame.draw.rect(self.screen, BTN_BORDER if sel else (46, 36, 72),
                             row, 1, border_radius=12)

            camp_col = ROLE_CAMP_COLOR.get(det["camp"], MIST_PURPLE)
            badge = pygame.Rect(row.x + 6, row.y + 5, 44, 32)
            pygame.draw.rect(self.screen, camp_col, badge, border_radius=10)
            # Icône : emoji du catalogue ou 2 premières lettres
            role_icon = det.get("ui_icon") or rn[:2].upper()
            # Utiliser la fonte "small" pour les emoji (plus lisible)
            draw_text(self.screen, role_icon, f["small"], WHITE_SOFT,
                      center=badge.center)
            draw_text(self.screen, rn,         f["xs"], WHITE_SOFT,
                      topleft=(row.x + 56, row.y + 4))
            draw_text(self.screen, det["camp"], f["xs"], CYAN_COOL,
                      topleft=(row.x + 56, row.y + 22))

            cnt_r = pygame.Rect(row.right - 128, row.y + 7, 38, 28)
            min_r = pygame.Rect(row.right - 84,  row.y + 7, 30, 28)
            pls_r = pygame.Rect(row.right - 46,  row.y + 7, 30, 28)
            is_host = self.is_host()
            if rn == "Villageois":
                # Villageois : pas de boutons +/- (valeur calculée automatiquement)
                minus_en = False
                plus_en  = False
            else:
                minus_en = is_host
                # Désactiver + si un rôle exclusif est déjà actif
                if is_host and self.role_config.get(rn, 0) == 0:
                    plus_en = exclusive_role_conflict(rn, self.role_config) is None
                else:
                    plus_en = is_host
            for r2, sym, en_btn in [(min_r, "-", minus_en), (pls_r, "+", plus_en)]:
                col = (BTN_DANGER if sym == "-" else BTN_SUCCESS) if en_btn else GREY_DARK
                pygame.draw.rect(self.screen, col, r2, border_radius=9)
                pygame.draw.rect(self.screen, BTN_BORDER, r2, 1, border_radius=9)
                draw_text(self.screen, sym, f["xs"], WHITE_SOFT if en_btn else GREY_DIM,
                          center=r2.center)
            pygame.draw.rect(self.screen, (10, 8, 22), cnt_r, border_radius=9)
            pygame.draw.rect(self.screen, BTN_BORDER, cnt_r, 1, border_radius=9)
            display_count = (self._villager_count() if rn == "Villageois"
                             else self.role_config.get(rn, 0))
            draw_text(self.screen, str(display_count), f["xs"], MOON_SILVER,
                      center=cnt_r.center)

            # Badge "OU" pour les rôles exclusifs (Enfant sauvage / Villageois Maudit)
            from loup_shared import EXCLUSIVE_ROLE_GROUPS
            for group in EXCLUSIVE_ROLE_GROUPS:
                if rn in group:
                    draw_text(self.screen, "⊘ exclusif", f["xs"], (180, 100, 60),
                              topleft=(row.x + 52, row.y + 22))
                    break
            draw_text(self.screen, str(display_count), f["xs"], MOON_SILVER,
                      center=cnt_r.center)

            self.role_row_rects[rn]   = row
            self.role_minus_rects[rn] = min_r
            self.role_plus_rects[rn]  = pls_r
            cy += ROW_H + GAP

        self.screen.set_clip(old_clip)

        if total_h > vis_h and max_scr > 0:
            bx  = self.role_list_rect.right - 7
            by2 = self.role_list_rect.y + 4
            bh  = self.role_list_rect.height - 8
            pygame.draw.rect(self.screen, (28, 22, 50), (bx, by2, 5, bh), border_radius=3)
            th  = max(22, int(bh * vis_h / total_h))
            ty  = by2 + int((bh - th) * (self.role_scroll / max_scr))
            pygame.draw.rect(self.screen, CYAN_COOL, (bx, ty, 5, th), border_radius=3)

    def draw_role_info_popup(self, f: dict):
        """
        Affiche la popup de détail du rôle sélectionné (camp, aura, description).

        :param f: Dictionnaire des polices (dict).
        """
        if not self.show_role_info or not self.selected_role_name:
            return
        det = ROLE_CATALOG.get(self.selected_role_name)
        if det is None:
            return
        # Positionner la popup sans chevaucher le footer (- 70 pour le footer de 62px)
        ir = pygame.Rect(self.center_rect.x + 12,
                         self.center_rect.bottom - 270,
                         self.center_rect.width - 24, 144)
        pygame.draw.rect(self.screen, (36, 26, 64), ir, border_radius=14)
        pygame.draw.rect(self.screen, BTN_BORDER, ir, 1, border_radius=14)
        self.role_info_close_rect = pygame.Rect(ir.x + 8, ir.y + 8, 22, 22)
        pygame.draw.rect(self.screen, MIST_PURPLE, self.role_info_close_rect, border_radius=8)
        draw_text(self.screen, "x", f["xs"], WHITE_SOFT,
                  center=self.role_info_close_rect.center)
        draw_text(self.screen, self.selected_role_name, f["small"], CYAN_COOL,
                  topleft=(ir.x + 36, ir.y + 8))
        draw_text(self.screen, f"Camp : {det['camp']}  |  Aura : {det['aura']}",
                  f["xs"], GOLD_PALE, topleft=(ir.x + 10, ir.y + 32))
        lines = wrap_text(det.get("description", ""),
                          max(28, (ir.width - 20) // 8))
        yl = ir.y + 52
        for line in lines:
            if yl + 16 > ir.bottom - 4:
                break
            draw_text(self.screen, line, f["xs"], WHITE_SOFT, topleft=(ir.x + 10, yl))
            yl += 16

    def draw_lobby_panel(self):
        """Dessine le panneau central du lobby (nom du salon, sélecteur de joueurs, équilibre, liste des rôles, bouton démarrer)."""
        f = self.fonts()
        draw_glass_panel(self.screen, self.center_rect, radius=22)
        draw_text(self.screen, self.server_name, f["big"], MOON_SILVER,
                  topleft=(self.center_rect.x + 14, self.center_rect.y + 10), shadow=True)
        draw_text(self.screen, "Lobby - configuration de la partie",
                  f["small"], GOLD_PALE,
                  topleft=(self.center_rect.x + 14, self.center_rect.y + 54))

        draw_glass_panel(self.screen, self.player_count_rect, radius=16, alpha_fill=150)
        self.draw_player_count_selector(self.player_count_rect, f)

        draw_glass_panel(self.screen, self.balance_rect, radius=16, alpha_fill=150)
        self.draw_balance_bar(self.balance_rect, f)

        tx = self.center_rect.x + 14
        tw = self.center_rect.width - 28
        draw_text(self.screen, "Composition des roles", f["medium"], MOON_SILVER,
                  topleft=(tx, self.roles_title_y))
        pygame.draw.line(self.screen, (68, 52, 106),
                         (tx, self.roles_title_y + 28), (tx + tw, self.roles_title_y + 28))

        note = ("Tu peux modifier la composition." if self.is_host()
                else "Seul l'hote peut modifier les roles.")
        draw_text(self.screen, note, f["xs"],
                  GOLD_WARM if self.is_host() else GREY_DIM,
                  topleft=(tx, self.roles_notice_y))
        err = role_config_error(self.max_players, self.role_config)
        if err:
            draw_text(self.screen, err, f["xs"], WOLF_RED,
                      topleft=(tx, self.roles_notice_y + 20))

        pygame.draw.rect(self.screen, (16, 12, 32), self.role_list_rect, border_radius=14)
        pygame.draw.rect(self.screen, (52, 40, 84), self.role_list_rect, 1, border_radius=14)
        self.draw_role_rows(f)

        footer = pygame.Rect(self.center_rect.x + 6, self.center_rect.bottom - 62,
                             self.center_rect.width - 12, 54)
        pygame.draw.rect(self.screen, (22, 16, 42), footer, border_radius=16)
        pygame.draw.rect(self.screen, (52, 40, 84), footer, 1, border_radius=16)
        can_start = (self.is_host()
                     and len(self.players) == self.max_players
                     and err is None)
        self.btn_start.draw(self.screen, f["small"], pygame.mouse.get_pos(),
                            enabled=can_start)
        if not can_start and self.is_host():
            needed = self.max_players - len(self.players)
            hint = (f"En attente de {needed} joueur(s)." if needed > 0
                    else "Corrige la configuration.")
            draw_text(self.screen, hint, f["xs"], GREY_DIM,
                      center=(footer.centerx, footer.y + 14))
        # Popup info rôle dessinée EN DERNIER (par-dessus tout) mais JAMAIS sur le footer
        if self.show_role_info:
            self.draw_role_info_popup(f)

    # ── Panneau jeu ──────────────────────────────────────────────────────────

    def draw_game_panel(self):
        """Dessine le panneau central de jeu (phase, rôle, cible, journal, boutons d'action ou écran de fin)."""
        f     = self.fonts()
        mouse = pygame.mouse.get_pos()
        is_day = (self.phase == "day")

        panel_s = pygame.Surface((self.center_rect.width, self.center_rect.height),
                                  pygame.SRCALPHA)
        col = (28, 48, 32, 205) if is_day else (22, 14, 38, 210)
        pygame.draw.rect(panel_s, col,
                         (0, 0, self.center_rect.width, self.center_rect.height),
                         border_radius=22)
        bord = (56, 96, 64, 160) if is_day else (88, 68, 128, 140)
        pygame.draw.rect(panel_s, bord,
                         (0, 0, self.center_rect.width, self.center_rect.height),
                         width=2, border_radius=22)
        self.screen.blit(panel_s, self.center_rect.topleft)

        if self.phase == "end" and self.winner:
            self._draw_end_screen(f, mouse)
            return

        phase_labels = {
            "night":      (f"  Nuit {self.day_count}", MOON_SILVER),
            "day":        (f"  Jour {self.day_count}",  GOLD_WARM),
            "dawn":       (f"  Aube {self.day_count}",  (255, 220, 120)),
            "hunter_day": (f"  Jour {self.day_count} — Chasseur", WOLF_RED),
        }
        ph_txt, ph_col = phase_labels.get(self.phase, (self.phase.capitalize(), WHITE_SOFT))
        draw_text(self.screen, ph_txt, f["big"], ph_col,
                  topleft=(self.center_rect.x + 18, self.center_rect.y + 12), shadow=True)

        role = self.current_role() or "Non attribue"
        det  = ROLE_CATALOG.get(role, ROLE_CATALOG["Villageois"])
        camp_col = ROLE_CAMP_COLOR.get(det["camp"], MIST_PURPLE)
        rb = pygame.Rect(self.center_rect.x + 18, self.center_rect.y + 56, 140, 28)
        pygame.draw.rect(self.screen, camp_col, rb, border_radius=14)
        draw_text(self.screen, role, f["xs"], WHITE_SOFT, center=rb.center)

        # Badge cible sélectionnée
        tgt_disp = None
        if self.selected_target is not None:
            tgt_disp = next((p["name"] for p in self.players
                             if p["id"] == self.selected_target), "?")
        elif self.multi_select_list:
            names = [p["name"] for p in self.players
                     if p["id"] in self.multi_select_list]
            tgt_disp = ", ".join(names)
        if tgt_disp:
            sr = pygame.Rect(rb.right + 10, rb.y, 180, 28)
            pygame.draw.rect(self.screen, (80, 48, 14), sr, border_radius=14)
            pygame.draw.rect(self.screen, GOLD_WARM, sr, 1, border_radius=14)
            label = f"Cible : {tgt_disp}"[:22]
            draw_text(self.screen, label, f["xs"], GOLD_WARM, center=sr.center)

        # Indicateur d'ordre des tours (nuit)
        if self.phase == "night":
            self._draw_night_steps(f, sy=self.center_rect.y + 90)

        y = self.center_rect.y + (148 if self.phase == "night" else 100)

        def line(txt, col):
            nonlocal y
            if not txt:
                return
            for ln in wrap_text(txt, max(24, (self.center_rect.width - 40) // 9)):
                if y + 16 > self.center_rect.bottom - 76:
                    return
                draw_text(self.screen, ln, f["xs"], col,
                          topleft=(self.center_rect.x + 18, y))
                y += 18
            y += 4

        line(self.message, WHITE_SOFT)
        line(self.action_hint, GOLD_PALE)

        # Infos de vote
        if self.phase == "day" and self.votes_needed > 0:
            line(f"Votes : {self.votes_cast}/{self.votes_needed}",
                 GOLD_WARM if self.has_voted else GREY_DIM)
            if self.has_voted:
                line("Vote enregistré - en attente des autres joueurs.", CYAN_COOL)
            elif self.can_act:
                line("Sélectionnez un joueur puis cliquez VALIDER.", GOLD_PALE)
            # Affichage visuel de qui vote qui
            if self.day_votes_visible:
                line("Votes en cours :", GOLD_WARM)
                for voter, cible in self.day_votes_visible.items():
                    line(f"  {voter} → {cible}", (180, 200, 80))

        # Infos de nuit
        if self.phase == "night":
            if self.night_target_name:
                line(f"Victime des loups : {self.night_target_name}", WOLF_RED)
            # Votes des loups (visible uniquement par les loups)
            if self.wolf_votes_visible and self.night_step == "wolves":
                line("Votes des loups :", WOLF_RED)
                for voter, cible in self.wolf_votes_visible.items():
                    line(f"  {voter} → {cible}", (200, 100, 100))
            if self.seer_result:
                line(self.seer_result, CYAN_COOL)
            if self.fox_result:
                line(f"Renard : {self.fox_result}", (180, 200, 60))
            if not self.fox_power_active and role == "Renard":
                line("Votre pouvoir est perdu.", GREY_DIM)

        # Infos de rôle persistantes
        if self.sniper_target_name:
            alive_flag = next((p["alive"] for p in self.players
                               if p.get("name") == self.sniper_target_name), False)
            status = "vivant" if alive_flag else "elimine"
            line(f"Cible Sniper : {self.sniper_target_name} ({status})", GOLD_WARM)
        if self.mentor_name:
            alive_flag = next((p["alive"] for p in self.players
                               if p.get("name") == self.mentor_name), False)
            status = "vivant" if alive_flag else "elimine - vous etes loup !"
            line(f"Mentor : {self.mentor_name} ({status})",
                 WOLF_RED if not alive_flag else CYAN_COOL)
        if self.lover_partner_name:
            alive_flag = next((p["alive"] for p in self.players
                               if p.get("name") == self.lover_partner_name), False)
            line(f"Amoureux(se) : {self.lover_partner_name} ({'vivant' if alive_flag else 'elimine !'})",
                 WOLF_RED if not alive_flag else (220, 80, 120))
        if self.charmed_list and role == "Sirène":
            line(f"Envoutes : {', '.join(self.charmed_list)}", (60, 140, 220))
        if self.fueled_list and role == "Pyromane":
            line(f"Asperges : {', '.join(self.fueled_list)}", (220, 120, 20))
        if self.salvateur_last_name and role == "Salvateur":
            line(f"Interdit cette nuit : {self.salvateur_last_name}", GREY_DIM)

        if self.last_deaths:
            line("Éliminé(s) : " + ", ".join(self.last_deaths), BLOOD_RED)

        # Phase aube : annonce des morts à tous avant le vote du jour
        if self.phase == "dawn":
            if self.last_deaths_with_roles:
                line("☽  Cette nuit, les éliminés sont :", (255, 180, 80))
                for entry in self.last_deaths_with_roles:
                    nom  = entry.get("nom",  "?")
                    role = entry.get("role", "?")
                    line(f"  💀 {nom} était {role}", BLOOD_RED)
            elif self.last_deaths:
                # Fallback si last_deaths_with_roles non reçu
                line("☽  Cette nuit, les morts sont :", (255, 180, 80))
                for name in self.last_deaths:
                    line(f"  💀 {name}", BLOOD_RED)
            else:
                line("☽  Personne n'est mort cette nuit !", (100, 220, 120))
            if self.is_host():
                line("(Hôte) Cliquez sur 'PASSER AU JOUR' pour lancer le vote.", GOLD_PALE)
            else:
                line("En attente que l'hôte passe au jour...", GREY_DIM)

        pygame.draw.line(self.screen, (58, 48, 88),
                         (self.center_rect.x + 18, y + 4),
                         (self.center_rect.right - 18, y + 4))
        y += 12
        line(f"Aura : {det['aura']}  |  Camp : {det['camp']}", CYAN_COOL)
        for ln in wrap_text(det["description"],
                            max(28, (self.center_rect.width - 36) // 9))[:3]:
            if y + 16 > self.center_rect.bottom - 76:
                break
            draw_text(self.screen, ln, f["xs"], GREY_DIM,
                      topleft=(self.center_rect.x + 18, y))
            y += 17

        # ---- Boutons d'action selon rôle / étape
        self._draw_action_buttons(f, mouse, role)

    def _draw_action_buttons(self, f: dict, mouse, role: str):
        """Sélectionne et affiche les boutons appropriés selon le contexte."""
        # Chasseur en attente (priorité absolue, peut être day ou night ou hunter_day)
        if self.is_hunter_turn and self.can_act:
            self._draw_hunter_buttons(f, mouse)
            return

        # Phase aube : bouton pour passer au jour (hôte seulement)
        if self.phase == "dawn":
            if self.is_host():
                self.btn_dawn_advance.draw(self.screen, f["small"], mouse, enabled=True)
            return

        if self.phase == "night" and self.can_act:
            step = self.night_step
            if role == "Infect Père des Loups" and step == "father":
                self._draw_father_buttons(f, mouse)
            elif role == "Sorcière" and step == "witch":
                self._draw_witch_buttons(f, mouse)
            elif role == "Salvateur" and step == "salvateur":
                self._draw_salvateur_buttons(f, mouse)
            elif role == "Renard" and step == "fox":
                self._draw_fox_buttons(f, mouse)
            elif role == "Sirène" and step == "siren":
                self._draw_siren_buttons(f, mouse)
            elif role == "Pyromane" and step == "arsonist":
                self._draw_arsonist_buttons(f, mouse)
            elif role == "Cupidon" and step == "cupidon":
                self._draw_cupidon_buttons(f, mouse)
            elif role == "Enfant sauvage" and step == "wild_child":
                self._draw_wild_child_buttons(f, mouse)
            else:
                # Loups, Voyante — bouton standard
                lbl = ("VALIDER LE VOTE" if self.phase == "day" else "VALIDER L'ACTION")
                self.btn_vote.text = lbl
                vote_ok = self.selected_target is not None
                self.btn_vote.draw(self.screen, f["small"], mouse, enabled=vote_ok)

        elif self.phase == "day":
            lbl = "VALIDER LE VOTE"
            self.btn_vote.text = lbl
            vote_ok = (self.can_act and self.selected_target is not None
                       and not self.has_voted)
            self.btn_vote.draw(self.screen, f["small"], mouse, enabled=vote_ok)

    # ── Indicateur des étapes de nuit (2 rangées × 5) ────────────────────────

    def _draw_night_steps(self, f: dict, sy: int):
        """
        Dessine la barre d'indicateurs des étapes de nuit (Cupidon, Enfant sauvage, Loups, etc.).

        :param f: Dictionnaire des polices (dict).
        :param sy: Coordonnée y de départ de la rangée d'indicateurs (int).
        """
        total_w = self.center_rect.width - 40
        n_per_row = 5
        pill_w = (total_w - (n_per_row - 1) * 4) // n_per_row
        pill_h = 22
        sx = self.center_rect.x + 20

        # Mapping étape → rôle requis (None = toujours présent)
        STEP_ROLE_REQUIRED = {
            "cupidon":    "Cupidon",
            "wild_child": "Enfant sauvage",
            "seer":       "Voyante",
            "wolves":     None,
            "father":     "Infect Père des Loups",
            "witch":      "Sorcière",
            "salvateur":  "Salvateur",
            "fox":        "Renard",
            "siren":      "Sirène",
            "arsonist":   "Pyromane",
        }
        # Filtre : ne garder que les étapes dont le rôle est dans la config active
        active_steps = []
        for step, label, col in NIGHT_STEP_INFO:
            required_role = STEP_ROLE_REQUIRED.get(step)
            if required_role is None:
                active_steps.append((step, label, col))
            elif self.role_config.get(required_role, 0) > 0:
                active_steps.append((step, label, col))

        for idx, (step, label, col) in enumerate(active_steps):
            row = idx // n_per_row
            col_i = idx % n_per_row
            px = sx + col_i * (pill_w + 4)
            py = sy + row * (pill_h + 4)
            is_cur = (step == self.night_step)
            pill   = pygame.Rect(px, py, pill_w, pill_h)
            surf   = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
            bg_col = (*col, 210) if is_cur else (40, 32, 60, 130)
            pygame.draw.rect(surf, bg_col, (0, 0, pill_w, pill_h), border_radius=9)
            if is_cur:
                pygame.draw.rect(surf, (*col, 255), (0, 0, pill_w, pill_h), 2, border_radius=9)
            self.screen.blit(surf, pill.topleft)
            txt_col = WHITE_SOFT if is_cur else GREY_DIM
            draw_text(self.screen, label, f["xs"], txt_col, center=pill.center)

    # ── Boutons spécifiques aux rôles ────────────────────────────────────────

    def _draw_father_buttons(self, f: dict, mouse):
        """
        Affiche les boutons INFECTER et PASSER pour le Père des loups.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        infect_ok = self.father_can_infect and self.night_target_name is not None
        self.btn_father_infect.text = ("INFECTER " + (self.night_target_name or "")[:10]).strip()
        self.btn_father_skip.text   = "PASSER"
        self.btn_father_infect.draw(self.screen, f["xs"], mouse, enabled=infect_ok)
        self.btn_father_skip.draw  (self.screen, f["xs"], mouse, enabled=True)
        iy = self.btn_father_infect.rect.y - 18
        status = "Pouvoir disponible" if self.father_can_infect else "Pouvoir déjà utilisé"
        draw_text(self.screen, status, f["xs"],
                  (160, 90, 20) if self.father_can_infect else GREY_DIM,
                  topleft=(self.btn_father_infect.rect.x, iy))

    def _draw_witch_buttons(self, f: dict, mouse):
        """
        Affiche les boutons SAUVER, EMPOISONNER et PASSER pour la Sorcière.
        """
        save_ok   = (self.witch_heal_available
                     and self.night_target_name is not None
                     and not self.witch_save_blocked)
        poison_ok = (self.witch_poison_available and self.selected_target is not None)
        self.btn_save.text   = ("SAUVER " + (self.night_target_name or "")[:10]).strip()
        self.btn_poison.text = "EMPOISONNER"
        self.btn_skip.text   = "PASSER"
        self.btn_save.draw  (self.screen, f["xs"], mouse, enabled=save_ok)
        self.btn_poison.draw(self.screen, f["xs"], mouse, enabled=poison_ok)
        self.btn_skip.draw  (self.screen, f["xs"], mouse, enabled=True)
        iy = self.btn_save.rect.y - 18
        if self.witch_save_blocked:
            draw_text(self.screen,
                      "Infecté par le Père des Loups — soin impossible !",
                      f["xs"], WOLF_RED,
                      topleft=(self.btn_save.rect.x, iy))
        else:
            draw_text(self.screen,
                      "Potion soin" if self.witch_heal_available else "Soin épuisé",
                      f["xs"], GOLD_WARM if self.witch_heal_available else GREY_DIM,
                      topleft=(self.btn_save.rect.x, iy))
        draw_text(self.screen,
                  "Potion mort" if self.witch_poison_available else "Mort epuisee",
                  f["xs"], (160, 60, 180) if self.witch_poison_available else GREY_DIM,
                  topleft=(self.btn_poison.rect.x, iy))

    def _draw_salvateur_buttons(self, f: dict, mouse):
        """
        Affiche les boutons PROTEGER et PASSER pour le Salvateur.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        protect_ok = (self.selected_target is not None)
        self.btn_vote.text = "PROTEGER"
        self.btn_vote.draw(self.screen, f["xs"], mouse, enabled=protect_ok)
        self.btn_salvateur_skip.text = "PASSER"
        self.btn_salvateur_skip.draw(self.screen, f["xs"], mouse, enabled=True)
        if self.salvateur_last_name:
            iy = self.btn_vote.rect.y - 18
            draw_text(self.screen, f"Interdit : {self.salvateur_last_name}",
                      f["xs"], GREY_DIM, topleft=(self.btn_vote.rect.x, iy))

    def _draw_fox_buttons(self, f: dict, mouse):
        """
        Affiche les boutons SENTIR (3 cibles) et PASSER pour le Renard.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        n = len(self.multi_select_list)
        sense_ok = (n == 3)
        self.btn_fox_confirm.text = f"SENTIR ({n}/3)"
        self.btn_fox_confirm.draw(self.screen, f["xs"], mouse, enabled=sense_ok)
        self.btn_fox_skip.text = "PASSER"
        self.btn_fox_skip.draw(self.screen, f["xs"], mouse,
                               enabled=(not self.fox_power_active or True))
        iy = self.btn_fox_confirm.rect.y - 18
        draw_text(self.screen, "Cliquez sur 3 joueurs puis SENTIR",
                  f["xs"], GOLD_PALE, topleft=(self.btn_fox_confirm.rect.x, iy))

    def _draw_siren_buttons(self, f: dict, mouse):
        """
        Affiche les boutons ENVOUTER et PASSER pour la Sirène.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        charm_ok = (self.selected_target is not None)
        self.btn_vote.text = "ENVOUTER"
        self.btn_vote.draw(self.screen, f["xs"], mouse, enabled=charm_ok)
        self.btn_siren_skip.text = "PASSER"
        self.btn_siren_skip.draw(self.screen, f["xs"], mouse, enabled=True)
        if self.charmed_list:
            iy = self.btn_vote.rect.y - 18
            draw_text(self.screen, f"Envoutes : {', '.join(self.charmed_list[:3])}",
                      f["xs"], (60, 140, 220), topleft=(self.btn_vote.rect.x, iy))

    def _draw_arsonist_buttons(self, f: dict, mouse):
        """
        Affiche les boutons ASPERGER, ENFLAMMER et PASSER pour le Pyromane.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        fuel_ok   = (self.selected_target is not None)
        ignite_ok = bool(self.fueled_list)
        self.btn_vote.text = "ASPERGER"
        self.btn_vote.draw(self.screen, f["xs"], mouse, enabled=fuel_ok)
        self.btn_arsonist_ignite.text = f"ENFLAMMER ({len(self.fueled_list)})"
        self.btn_arsonist_ignite.draw(self.screen, f["xs"], mouse, enabled=ignite_ok)
        self.btn_arsonist_skip.text = "PASSER"
        self.btn_arsonist_skip.draw(self.screen, f["xs"], mouse, enabled=True)
        iy = self.btn_vote.rect.y - 18
        if self.fueled_list:
            draw_text(self.screen, f"Asperges : {', '.join(self.fueled_list[:3])}",
                      f["xs"], (220, 120, 20), topleft=(self.btn_vote.rect.x, iy))

    def _draw_hunter_buttons(self, f: dict, mouse):
        """
        Affiche le bouton TIRER pour le Chasseur qui doit désigner sa dernière victime.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        shoot_ok = (self.selected_target is not None)
        self.btn_hunter_shoot.text = "TIRER"
        self.btn_hunter_shoot.draw(self.screen, f["small"], mouse, enabled=shoot_ok)
        iy = self.btn_hunter_shoot.rect.y - 18
        draw_text(self.screen, "Chasseur : choisissez votre derniere victime !",
                  f["xs"], WOLF_RED, topleft=(self.btn_hunter_shoot.rect.x, iy))

    def _draw_cupidon_buttons(self, f: dict, mouse):
        """
        Affiche le bouton CONFIRMER LES AMOUREUX (2 sélections requises) pour Cupidon.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        n = len(self.multi_select_list)
        confirm_ok = (n == 2)
        self.btn_cupidon_confirm.text = f"CONFIRMER LES AMOUREUX ({n}/2)"
        self.btn_cupidon_confirm.draw(self.screen, f["small"], mouse, enabled=confirm_ok)
        iy = self.btn_cupidon_confirm.rect.y - 18
        draw_text(self.screen, "Cliquez sur 2 joueurs qui tomberont amoureux",
                  f["xs"], GOLD_PALE, topleft=(self.btn_cupidon_confirm.rect.x, iy))

    def _draw_wild_child_buttons(self, f: dict, mouse):
        """
        Affiche le bouton CHOISIR CE MENTOR pour l'Enfant sauvage.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        ok = (self.selected_target is not None)
        self.btn_wild_confirm.text = "CHOISIR CE MENTOR"
        self.btn_wild_confirm.draw(self.screen, f["small"], mouse, enabled=ok)
        iy = self.btn_wild_confirm.rect.y - 18
        draw_text(self.screen, "Choisissez votre mentor (si il meurt, vous devenez loup)",
                  f["xs"], GOLD_PALE, topleft=(self.btn_wild_confirm.rect.x, iy))

    def _draw_end_screen(self, f: dict, mouse):
        """
        Dessine l'écran de fin de partie enrichi : camp vainqueur, rôles initiaux/finaux,
        états spéciaux (infecté, envoûté, loup-garou transformé), historique des exécutions.

        :param f: Dictionnaire des polices (dict).
        :param mouse: Position actuelle de la souris (tuple[int, int]).
        """
        cr = self.center_rect
        win_colors = {
            "Village":  ((20, 44, 28, 230), (56, 140, 70, 200), (80, 220, 100), "VICTOIRE DU VILLAGE !"),
            "Loups":    ((40, 10, 16, 230), (180, 30, 48, 200), WOLF_RED,       "VICTOIRE DES LOUPS !"),
            "Amoureux": ((40, 10, 40, 230), (200, 60, 160, 200), (240, 100, 200), "VICTOIRE DES AMOUREUX !"),
            "Sniper":   ((20, 30, 50, 230), (60, 80, 160, 200), CYAN_COOL,      "VICTOIRE DU SNIPER !"),
            "Sirène":   ((10, 30, 50, 230), (40, 120, 200, 200), (80, 180, 240), "VICTOIRE DE LA SIRÈNE !"),
            "Pyromane": ((40, 20, 10, 230), (200, 80, 20, 200), (240, 120, 40), "VICTOIRE DU PYROMANE !"),
        }
        bg_col, brd_col, tcol, title = win_colors.get(
            self.winner,
            ((20, 20, 20, 230), (80, 80, 80, 200), WHITE_SOFT, f"VICTOIRE : {self.winner} !"))

        bg = pygame.Surface((cr.width, cr.height), pygame.SRCALPHA)
        pygame.draw.rect(bg, bg_col,  (0, 0, cr.width, cr.height), border_radius=22)
        pygame.draw.rect(bg, brd_col, (0, 0, cr.width, cr.height), width=3, border_radius=22)
        self.screen.blit(bg, cr.topleft)

        draw_text(self.screen, title, f["big"], tcol,
                  center=(cr.centerx, cr.y + 36), shadow=True)
        draw_text(self.screen, self.message, f["xs"], GOLD_PALE,
                  center=(cr.centerx, cr.y + 68))

        # ── En-têtes colonnes ──────────────────────────────────────────────
        header_y = cr.y + 88
        col_w    = cr.width - 28
        cx       = cr.x + 14
        col_name  = cx
        col_init  = cx + int(col_w * 0.28)
        col_final = cx + int(col_w * 0.54)
        col_notes = cx + int(col_w * 0.76)

        draw_text(self.screen, "Joueur",        f["xs"], GOLD_WARM,  topleft=(col_name,  header_y))
        draw_text(self.screen, "Rôle initial",  f["xs"], CYAN_COOL,  topleft=(col_init,  header_y))
        draw_text(self.screen, "Rôle final",    f["xs"], MOON_SILVER, topleft=(col_final, header_y))
        draw_text(self.screen, "États",         f["xs"], MIST_LIGHT, topleft=(col_notes, header_y))
        pygame.draw.line(self.screen, (68, 52, 106),
                         (cx, header_y + 16), (cx + col_w, header_y + 16))

        y = header_y + 20
        row_h = 24

        for p in self.players:
            if y + row_h > cr.bottom - 60:
                break
            pid      = p["id"]
            alive    = p["alive"]
            role_fin = p.get("revealed_role") or p.get("role") or "?"
            role_ini = self.initial_roles.get(pid, role_fin)
            # Ne pas révéler qui a infecté, tué, etc. – seulement l'état du joueur
            is_wolf_fin = is_wolf_role(role_fin)

            bg2 = (52, 14, 14, 160) if is_wolf_fin else                   (24, 52, 28, 140) if alive else (30, 26, 48, 130)
            row = pygame.Rect(cx, y, col_w, row_h - 2)
            row_surf = pygame.Surface((row.width, row.height), pygame.SRCALPHA)
            pygame.draw.rect(row_surf, bg2, (0, 0, row.width, row.height), border_radius=7)
            self.screen.blit(row_surf, row.topleft)

            name_col = WHITE_SOFT if alive else GREY_DIM
            # Indicateur vivant/mort + Nom
            status_icon = "✓ " if alive else "✗ "
            status_col  = (80, 220, 100) if alive else (220, 70, 70)
            draw_text(self.screen, status_icon, f["xs"], status_col, topleft=(col_name + 4, y + 5))
            # Décaler le nom pour laisser la place à l'icône (~14px)
            draw_text(self.screen, p["name"][:13], f["xs"], name_col, topleft=(col_name + 20, y + 5))
            # Rôle initial
            draw_text(self.screen, role_ini[:16],  f["xs"], CYAN_COOL,  topleft=(col_init,  y + 5))
            # Rôle final (en rouge si différent du rôle initial)
            fin_col = WOLF_RED if role_fin != role_ini else (180, 210, 180)
            draw_text(self.screen, role_fin[:16],  f["xs"], fin_col,    topleft=(col_final, y + 5))

            # États spéciaux (sans révéler qui a effectué l'action)
            notes = []
            if p.get("infected"):
                notes.append("Infecté")
            if p.get("maudit_converted"):
                notes.append("Loup (malédiction)")
            if p.get("wild_child_turned"):
                notes.append("Loup (mentor mort)")
            if p.get("is_charmed"):
                notes.append("Envoûté")
            if p.get("is_fueled"):
                notes.append("Aspergé")
            if p.get("is_lover"):
                notes.append("Amoureux")
            notes_str = ", ".join(notes)[:20]
            if notes_str:
                draw_text(self.screen, notes_str, f["xs"], (220, 180, 80), topleft=(col_notes, y + 5))

            y += row_h

        # ── Historique des exécutions ──────────────────────────────────────
        if self.execution_history and y + 22 < cr.bottom - 60:
            y += 4
            pygame.draw.line(self.screen, (68, 52, 106), (cx, y), (cx + col_w, y))
            y += 6
            if y + 16 < cr.bottom - 60:
                draw_text(self.screen, "Exécutions par le village :", f["xs"], GOLD_WARM, topleft=(cx, y))
                y += 16
            for entry in self.execution_history:
                if y + 16 > cr.bottom - 60:
                    break
                jour = entry.get("jour", "?")
                nom  = entry.get("nom", "?")
                role = entry.get("role", "?")
                draw_text(self.screen, f"  Jour {jour} : {nom} ({role})",
                          f["xs"], (180, 160, 100), topleft=(cx, y))
                y += 16

        self.btn_end.draw(self.screen, f["small"], mouse, enabled=True)

    # ── Chat ─────────────────────────────────────────────────────────────────

    def _is_local_player_dead(self) -> bool:
        """Retourne True si le joueur local est mort."""
        if self.your_id is None:
            return False
        for p in self.players:
            if p["id"] == self.your_id:
                return not p.get("alive", True)
        return False

    def draw_chat_panel(self):
        """Dessine le panneau de chat avec historique défilant, barre de scroll et zone de saisie."""
        f = self.fonts()
        draw_glass_panel(self.screen, self.chat_rect, radius=22)
        # Titre avec indicateur mort/vivant
        chat_title = "Chat des Esprits" if (not self.can_chat and self._is_local_player_dead()) else "Chat"
        title_col  = MIST_LIGHT if (not self.can_chat and self._is_local_player_dead()) else MOON_SILVER
        draw_text(self.screen, chat_title, f["big"], title_col,
                  topleft=(self.chat_rect.x + 12, self.chat_rect.y + 10), shadow=True)
        # Bandeau informatif si le joueur est mort
        if not self.can_chat and self._is_local_player_dead():
            draw_text(self.screen, "Seuls les morts vous entendent",
                      f["xs"], (160, 100, 200),
                      topleft=(self.chat_rect.x + 12, self.chat_rect.y + 42))

        vis_top = self.chat_rect.y + 54
        vis_bot = self.chat_rect.bottom - 66
        line_h  = 40
        avail   = max(0, vis_bot - vis_top)
        max_vis = max(1, avail // line_h)

        total   = len(self.chat_history)
        max_scr = max(0, total - max_vis)
        self.chat_scroll = max(0, min(self.chat_scroll, max_scr))
        start   = max(0, total - max_vis - self.chat_scroll)
        visible = self.chat_history[start:start + max_vis]

        y = vis_top
        for entry in visible:
            if y + line_h > vis_bot:
                break
            system    = entry.get("system")
            wolf_only = entry.get("wolf_only", False)
            dead_only = entry.get("dead_only", False)
            author = "[Système]" if system else entry.get("author", "?")
            # Couleur de l'auteur selon le type de message
            if system:
                acol = WOLF_RED
            elif wolf_only:
                acol = WOLF_RED
            elif dead_only:
                acol = (140, 100, 180)  # violet pâle = chat des esprits
            else:
                acol = GOLD_WARM
            prefix = "☽ " if dead_only else ""  # icône lune pour les morts
            draw_text(self.screen, prefix + author + ":", f["xs"], acol,
                      topleft=(self.chat_rect.x + 12, y))
            msg_txt = entry.get("message", "")
            max_c = max(10, (self.chat_rect.width - 24) // 8)
            if len(msg_txt) > max_c:
                msg_txt = msg_txt[:max_c - 2] + ".."
            if wolf_only:
                msg_col = (200, 140, 140)
            elif dead_only:
                msg_col = (180, 150, 210)  # lilas = chat des esprits
            else:
                msg_col = WHITE_SOFT
            draw_text(self.screen, msg_txt, f["xs"], msg_col,
                      topleft=(self.chat_rect.x + 18, y + 18))
            y += line_h

        if total > max_vis and max_scr > 0:
            bx  = self.chat_rect.right - 10
            bh  = vis_bot - vis_top
            pygame.draw.rect(self.screen, (28, 22, 50), (bx, vis_top, 5, bh), border_radius=3)
            th  = max(24, int(bh * max_vis / total))
            ty2 = vis_top + int((bh - th) * (self.chat_scroll / max_scr))
            pygame.draw.rect(self.screen, CYAN_COOL, (bx, ty2, 5, th), border_radius=3)

        chat_allowed = self.can_chat
        if not chat_allowed:
            overlay = pygame.Surface((self.chat_rect.width - 4, 46), pygame.SRCALPHA)
            pygame.draw.rect(overlay, (10, 8, 22, 190), (0, 0, overlay.get_width(), 46), border_radius=12)
            self.screen.blit(overlay, (self.chat_rect.x + 2, self.chat_rect.bottom - 56))
            draw_text(self.screen, "Chat desactive la nuit (loups seulement)",
                      f["xs"], GREY_DIM,
                      center=(self.chat_rect.centerx, self.chat_rect.bottom - 34))
        else:
            self.chat_input.draw(self.screen, f["xs"])
            self.btn_send_chat.draw(self.screen, f["xs"], pygame.mouse.get_pos())

    # ── Draw principal ───────────────────────────────────────────────────────

    def draw(self):
        """Orchestre le dessin complet de la frame : fond, barre titre, liste joueurs, panneau central et chat."""
        self._draw_bg()
        f = self.fonts()

        draw_glass_panel(self.screen, self.top_rect, radius=18)
        title = "LOUP-GAROU  -  " + self.server_name.upper()
        draw_text(self.screen, title, f["title"], MOON_SILVER,
                  center=(self.top_rect.centerx - 55, self.top_rect.centery), shadow=True)
        self.btn_sync.draw(self.screen, f["xs"], pygame.mouse.get_pos())
        # Affiche l'IP locale pour l'hôte (visible uniquement en phase lobby)
        if self.phase == "lobby" and self.is_host():
            my_ip = get_local_ip()
            copied = (self.t - self._ip_copied_at) < 2.0 if hasattr(self, "_ip_copied_at") else False
            ip_label = f"Ton IP : {my_ip}  ✓ Copié !" if copied else f"Ton IP : {my_ip}  [clic pour copier]"
            ip_color = GOLD_PALE if copied else GOLD_WARM
            ip_surf  = f["small"].render(ip_label, True, ip_color)
            self._ip_label_rect = pygame.Rect(
                self.top_rect.x + 12, self.top_rect.y + 8,
                ip_surf.get_width(), ip_surf.get_height())
            # Fond de survol si la souris est dessus
            if self._ip_label_rect.collidepoint(pygame.mouse.get_pos()):
                hover = pygame.Surface((self._ip_label_rect.width + 8, self._ip_label_rect.height + 4), pygame.SRCALPHA)
                hover.fill((255, 200, 80, 40))
                self.screen.blit(hover, (self._ip_label_rect.x - 4, self._ip_label_rect.y - 2))
            self.screen.blit(ip_surf, (self._ip_label_rect.x, self._ip_label_rect.y))
            draw_text(self.screen, "(donne cette IP aux autres joueurs)",
                      f["xs"] if "xs" in f else f["small"], GREY_DIM,
                      topleft=(self.top_rect.x + 12, self.top_rect.y + 32))

        if self.state == "connecting":
            draw_text(self.screen, "Connexion au serveur...", f["big"], MOON_SILVER,
                      center=self.screen.get_rect().center)
            return

        self.draw_player_list()
        if self.phase == "lobby":
            self.draw_lobby_panel()
        else:
            self.draw_game_panel()
        self.draw_chat_panel()

        draw_text(self.screen,
                  "Molette pour défiler  |  Clic sur un joueur pour cibler",
                  f["xs"], GREY_DIM,
                  center=self.bottom_rect.center)

    # ── Événements ───────────────────────────────────────────────────────────

    def _try_select_player(self, pos) -> bool:
        """Tente de sélectionner un joueur. Gère le mode multi-select si besoin.
        Retourne True si un joueur a été sélectionné."""
        role = self.current_role() or ""
        step = self.night_step
        # Multi-select : Cupidon (2) et Renard (3)
        is_multi = (
            self.can_act and self.phase == "night"
            and ((role == "Cupidon" and step == "cupidon" and self.night_targets_needed == 2)
                 or (role == "Renard" and step == "fox" and self.night_targets_needed == 3))
        )
        max_sel = self.night_targets_needed if is_multi else 1

        for pid, rect in self.player_rects:
            if not rect.collidepoint(pos):
                continue
            p = next((pl for pl in self.players if pl["id"] == pid), None)
            if p is None or not p["alive"] or pid == self.your_id:
                continue

            if is_multi:
                if pid in self.multi_select_list:
                    self.multi_select_list.remove(pid)
                elif len(self.multi_select_list) < max_sel:
                    self.multi_select_list.append(pid)
            else:
                self.selected_target = pid
            return True
        return False

    def handle_event(self, event):
        """
        Traite un événement Pygame (molette, redimensionnement, clic) et dispatche l'action appropriée.

        :param event: Événement Pygame à traiter (pygame.event.Event).
        """
        # Clic sur l'IP de l'hôte → copie dans le presse-papier
        if event.type == pygame.MOUSEBUTTONDOWN:
            if (self.phase == "lobby" and self.is_host()
                    and hasattr(self, "_ip_label_rect")
                    and self._ip_label_rect.collidepoint(event.pos)):
                try:
                    pygame.scrap.init()
                    pygame.scrap.put(pygame.SCRAP_TEXT, get_local_ip().encode("utf-8"))
                except Exception:
                    pass
                self._ip_copied_at = self.t
                return

        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self.chat_rect.collidepoint(pos):
                self.chat_scroll = max(0, self.chat_scroll + event.y)
                return
            if self.phase == "lobby" and self.role_list_rect.collidepoint(pos):
                self.role_scroll = max(0, self.role_scroll - event.y * 24)
                self.show_role_info = False
                return

        if event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode(
                (max(MIN_W, event.w), max(MIN_H, event.h)), pygame.RESIZABLE)
            self.compute_layout()
            return

        if self.can_chat and self.chat_input.handle_event(event):
            self.send_chat()
            return

        if event.type != pygame.MOUSEBUTTONDOWN:
            return

        # Fermer popup rôle
        if self.show_role_info:
            if self.role_info_close_rect.collidepoint(event.pos):
                self.show_role_info = False
                return
            on_row = any(r.collidepoint(event.pos) for r in self.role_row_rects.values())
            on_pm  = any(r.collidepoint(event.pos) for r in self.role_minus_rects.values())
            on_pp  = any(r.collidepoint(event.pos) for r in self.role_plus_rects.values())
            if not (on_row or on_pm or on_pp):
                self.show_role_info = False

        if self.btn_sync.is_clicked(event.pos):
            self.network.send({"type": "sync_request"})
            return
        if self.can_chat and self.btn_send_chat.is_clicked(event.pos):
            self.send_chat()
            return

        if self.phase == "lobby":
            # ── Bouton "Lancer la partie" : priorité maximale, jamais bloqué par la popup ──
            if self.btn_start.is_clicked(event.pos):
                self.show_role_info = False
                self.send_action()
                return
            if self.count_left_rect.collidepoint(event.pos):
                self._send_max_players_update(-1)
                return
            if self.count_right_rect.collidepoint(event.pos):
                self._send_max_players_update(+1)
                return
            for rn in list(self.role_row_rects.keys()):
                if self.role_minus_rects.get(rn, pygame.Rect(0,0,0,0)).collidepoint(event.pos):
                    self.selected_role_name = rn
                    self.show_role_info = True
                    self._send_role_config_update(rn, -1)
                    return
                if self.role_plus_rects.get(rn, pygame.Rect(0,0,0,0)).collidepoint(event.pos):
                    self.selected_role_name = rn
                    self.show_role_info = True
                    self._send_role_config_update(rn, +1)
                    return
                if self.role_row_rects[rn].collidepoint(event.pos):
                    self.selected_role_name = rn
                    self.show_role_info = True
                    return
            return

        if self.phase == "end" and self.btn_end.is_clicked(event.pos):
            # Demande au serveur de relancer un lobby (sans fermer la connexion TCP).
            # Tous les joueurs encore connectés reçoivent un snapshot phase='lobby'
            # et restent dans la partie sans avoir à se reconnecter.
            self.network.send({"type": "restart_game"})
            return

        # Phase aube : seul l'hôte passe au jour
        if self.phase == "dawn" and self.is_host():
            if self.btn_dawn_advance.is_clicked(event.pos):
                self.network.send({"type": "dawn_advance"})
                return

        # Sélection joueur (inclut multi-select)
        if self._try_select_player(event.pos):
            return

        # Boutons d'action selon rôle / étape
        role = self.current_role() or ""

        # Chasseur (priorité absolue)
        if self.is_hunter_turn and self.can_act:
            if self.btn_hunter_shoot.is_clicked(event.pos):
                self.send_hunter_shoot()
                return

        if self.phase == "night" and self.can_act:
            step = self.night_step

            # Père des Loups
            if role == "Infect Père des Loups" and step == "father":
                if self.btn_father_infect.is_clicked(event.pos):
                    self.send_father_infect()
                    return
                if self.btn_father_skip.is_clicked(event.pos):
                    self.send_father_skip()
                    return

            # Sorcière
            elif role == "Sorcière" and step == "witch":
                if self.btn_save.is_clicked(event.pos):
                    self.send_witch_save()
                    return
                if self.btn_poison.is_clicked(event.pos):
                    self.send_witch_poison()
                    return
                if self.btn_skip.is_clicked(event.pos):
                    self.send_witch_skip()
                    return

            # Salvateur
            elif role == "Salvateur" and step == "salvateur":
                if self.btn_vote.is_clicked(event.pos):
                    self.send_action()
                    return
                if self.btn_salvateur_skip.is_clicked(event.pos):
                    self.send_salvateur_skip()
                    return

            # Renard
            elif role == "Renard" and step == "fox":
                if self.btn_fox_confirm.is_clicked(event.pos):
                    self.send_fox_sense()
                    return
                if self.btn_fox_skip.is_clicked(event.pos):
                    self.send_fox_skip()
                    return

            # Sirène
            elif role == "Sirène" and step == "siren":
                if self.btn_vote.is_clicked(event.pos):
                    self.send_action()
                    return
                if self.btn_siren_skip.is_clicked(event.pos):
                    self.send_siren_skip()
                    return

            # Pyromane
            elif role == "Pyromane" and step == "arsonist":
                if self.btn_vote.is_clicked(event.pos):
                    self.send_action()
                    return
                if self.btn_arsonist_ignite.is_clicked(event.pos):
                    self.send_arsonist_ignite()
                    return
                if self.btn_arsonist_skip.is_clicked(event.pos):
                    self.send_arsonist_skip()
                    return

            # Cupidon
            elif role == "Cupidon" and step == "cupidon":
                if self.btn_cupidon_confirm.is_clicked(event.pos):
                    self.send_cupidon_confirm()
                    return

            # Enfant sauvage
            elif role == "Enfant sauvage" and step == "wild_child":
                if self.btn_wild_confirm.is_clicked(event.pos):
                    self.send_action()
                    return

            # Loups / Voyante — bouton standard
            elif self.btn_vote.is_clicked(event.pos):
                self.send_action()
                return

        elif self.phase == "day":
            if self.btn_vote.is_clicked(event.pos):
                self.send_action()
                return

    # ── Boucle ───────────────────────────────────────────────────────────────

    def run(self):
        """Boucle principale : traite le réseau, les événements et dessine chaque frame jusqu'à fermeture."""
        while self.running:
            dt = self.clock.tick(FPS)
            self.t += dt * 0.001
            self.process_network()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                else:
                    self.handle_event(event)
            self.draw()
            pygame.display.flip()
        self.network.close()
        # NE PAS appeler pygame.quit() – géré par le Launcher
        pygame.display.quit()
"""
loup_garou_solo.py – Mode solo contre des IA.
Tous les rôles spéciaux sont jouables : Cupidon, Enfant sauvage, Salvateur,
Renard, Villageois Maudit, Sniper, Sirène, Pyromane, Chasseur, Sorcière,
Infect Père des Loups, Voyante.
"""
import random
from collections import Counter
import math

import pygame

from loup_shared import (MAX_PLAYERS, MIN_PLAYERS, ROLE_CATALOG,
                          build_roles, check_winner,
                          serialize_players_for, is_wolf_role, is_wolf_player)
from loup_ui_theme import (
    BG_DEEP, BG_TOP, BG_BOTTOM, BG_MID,
    WOLF_RED, WOLF_RED_DK, BLOOD_RED,
    MIST_PURPLE, MIST_LIGHT,
    GOLD_WARM, GOLD_PALE,
    CYAN_COOL, WHITE_SOFT, GREY_DIM, GREY_DARK,
    MOON_SILVER,
    BTN_PRIMARY, BTN_PRIMARY_H,
    BTN_DANGER, BTN_DANGER_H,
    BTN_SUCCESS, BTN_SUCCESS_H,
    BTN_NEUTRAL, BTN_NEUTRAL_H,
    ROLE_WOLF_CLR, ROLE_VILLAGE_CLR, ROLE_NEUTRAL_CLR,
    draw_gradient_bg, draw_glass_panel, draw_text, wrap_text,
    draw_moon, draw_tree_silhouette,
    ParticleSystem, Button,
    scaled_fonts,
)

BASE_W, BASE_H = 1280, 840
MIN_W,  MIN_H  = 980,  700
FPS = 60

NIGHT_BG_TOP = (6,  4, 14)
NIGHT_BG_BOT = (30, 16, 50)
DAY_BG_TOP   = (30, 55, 80)
DAY_BG_BOT   = (70, 100, 60)

ROLE_BADGE_COLORS = {
    "Loup-garou":            ROLE_WOLF_CLR,
    "Infect Père des Loups": ROLE_WOLF_CLR,
    "Voyante":               (50, 120, 200),
    "Sorcière":              (110, 50, 170),
    "Chasseur":              (130, 90, 40),
    "Cupidon":               (200, 80, 120),
    "Salvateur":             (40, 130, 100),
    "Renard":                (180, 120, 20),
    "Enfant sauvage":        (60, 100, 40),
    "Villageois Maudit":     (90, 60, 130),
    "Sniper":                (60, 60, 60),
    "Sirène":                (20, 120, 180),
    "Pyromane":              (200, 80, 20),
    "Villageois":            (40, 100, 60),
}

_WOLF_MSGS = [
    "Je pense que {} se comporte bizarrement...",
    "Moi je suis innocent. Regardez plutôt {}.",
    "Je suis villageois, faites-moi confiance.",
    "{} n'a pas l'air d'un villageois ordinaire.",
    "Je vote contre {}. Son comportement est suspect.",
]
_VILLAGE_MSGS = [
    "Je soupçonne {} d'être un loup...",
    "Quelqu'un a des informations sur {} ?",
    "{} n'a pas réagi normalement hier soir.",
    "Prudence, les loups sont parmi nous.",
    "Je fais confiance à {}, mais méfiez-vous de {}.",
    "Nous devons voter intelligemment aujourd'hui.",
]
_SEER_MSGS = [
    "J'ai des informations, mais je dois rester prudente.",
    "Je surveille {} de près, quelque chose cloche.",
    "Faisons attention à qui nous votons.",
    "Mon instinct me dit que {} est dangereux.",
]
_WITCH_MSGS = [
    "Je garde mes ressources pour le bon moment.",
    "{} semble suspect, je le surveille.",
    "Votons de manière réfléchie aujourd'hui.",
]


def _role_badge_col(role: str) -> tuple:
    """
    Retourne la couleur RGB associée au badge du rôle donné.

    :param role: Nom du rôle (str).
    :return: Tuple RGB (tuple[int, int, int]).
    """
    return ROLE_BADGE_COLORS.get(role, MIST_PURPLE)


def _ai_chat_msg(player: dict, players: list) -> str:
    """
    Génère un message de chat aléatoire pour un joueur IA selon son rôle.

    :param player: Dictionnaire du joueur IA avec au moins les clés 'role' et 'id' (dict).
    :param players: Liste complète des joueurs de la partie (list[dict]).
    :return: str — message de chat généré.
    """
    role = player.get("role", "Villageois")
    alive = [p for p in players if p["alive"] and p["id"] != player["id"]]
    if not alive:
        return "..."
    if is_wolf_role(role) or is_wolf_player(player):
        non_wolves = [p for p in alive if not is_wolf_player(p)]
        pool = non_wolves if non_wolves else alive
        templates = _WOLF_MSGS
    elif role == "Voyante":
        pool = alive
        templates = _SEER_MSGS
    elif role == "Sorcière":
        pool = alive
        templates = _WITCH_MSGS
    else:
        pool = alive
        templates = _VILLAGE_MSGS
    t1 = random.choice(pool)["name"]
    others = [p for p in alive if p["name"] != t1]
    t2 = random.choice(others)["name"] if others else t1
    tpl = random.choice(templates)
    count = tpl.count("{}")
    if count == 2:
        return tpl.format(t1, t2)
    if count == 1:
        return tpl.format(t1)
    return tpl


class WerewolfSoloGame:
    def __init__(self, player_name="Joueur", player_count=6, role_config=None):
        """
        Initialise le jeu solo : fenêtre, état de partie, joueurs, boutons et lance la partie.

        :param player_name: Pseudonyme du joueur humain (str).
        :param player_count: Nombre total de joueurs humain + IA (int).
        :param role_config: Configuration des rôles {nom_rôle: quantité} (dict ou None).
        """
        pygame.init()
        self.screen = pygame.display.set_mode((BASE_W, BASE_H), pygame.RESIZABLE)
        pygame.display.set_caption("Loup-Garou – Solo")
        self.clock   = pygame.time.Clock()
        self.running = True
        self.t       = 0.0

        self.player_name   = player_name
        self.total_players = max(MIN_PLAYERS, min(MAX_PLAYERS, int(player_count)))
        self.role_config   = role_config
        self.player_id     = 0

        self.players: list       = []
        self.phase: str          = "night"
        self.day_count: int      = 0
        self.message: str        = ""
        self.action_hint: str    = ""
        self.selected_target     = None
        self.winner              = None
        self.last_deaths: list   = []
        self.night_target_name   = None
        self.seer_result         = None
        self.witch_heal_used     = False
        self.witch_poison_used   = False
        self.pending_night: dict = {}

        self.game_ms: int       = 0
        self.action_queue: list = []
        self.is_animating: bool = False

        self.night_log: list = []
        self.chat_log: list  = []
        self.day_votes: dict = {}

        # Chasseur humain
        self.hunter_pending      = False
        self.hunter_pending_done = None

        # Cupidon humain : sélection de 2 joueurs
        self.cupidon_pending       = False
        self.cupidon_pending_done  = None
        self.cupidon_selections: list = []

        # Enfant sauvage humain
        self.wild_child_pending      = False
        self.wild_child_pending_done = None

        # Renard humain : sélection de 3 joueurs
        self.fox_pending       = False
        self.fox_pending_done  = None
        self.fox_selections: list = []

        # Mémoire Voyante IA
        self.seer_known_wolves: set = set()

        # Salvateur
        self.salvateur_last_protected = None

        # Sniper
        self.sniper_target = None

        # Sirène
        self.charmed_players: list = []

        # Pyromane
        self.fueled_players: list = []
        self.pyro_fuel_pending  = False  # en attente de cible fuel
        self.pyro_pending_done  = None

        # Amoureux
        self.lovers: list = []

        # Fox power
        self.fox_power_active = True

        # Résultat Renard (pour humain)
        self.fox_result = None

        # Père des Loups : infection unique
        self.father_infect_used: bool = False
        self.father_pending:     bool = False
        self.father_pending_done      = None

        # Votes des loups (visibles entre loups)
        self.wolf_votes: dict = {}

        # Chasseurs morts de nuit en attente d'agir au matin
        self.pending_hunter_deaths: list = []

        # Log morts
        self.death_log: list = []

        self.btn_restart  = Button("NOUVELLE PARTIE",   BTN_SUCCESS, BTN_SUCCESS_H, icon="")
        self.btn_vote     = Button("VALIDER MON VOTE",  BTN_PRIMARY, BTN_PRIMARY_H, icon="")
        self.btn_hunter   = Button("EMPORTER AVEC MOI", BTN_DANGER,  BTN_DANGER_H,  icon="")
        self.btn_skip     = Button("PASSER",            BTN_NEUTRAL, BTN_NEUTRAL_H)
        self.btn_save     = Button("SAUVER",            BTN_SUCCESS, BTN_SUCCESS_H)
        self.btn_confirm  = Button("CONFIRMER",         BTN_PRIMARY, BTN_PRIMARY_H)
        self.btn_ignite   = Button("METTRE LE FEU",     BTN_DANGER,  BTN_DANGER_H)

        self.particles      = ParticleSystem(BASE_W, BASE_H, 30)
        self.player_rects: list = []
        self.compute_layout()
        self.setup_game()

    # ── Fonts & Layout ────────────────────────────────────────────────────────

    def fonts(self) -> dict:
        """
        Retourne le dictionnaire de polices mises à l'échelle selon la taille courante de la fenêtre.

        :return: dict avec les clés 'title', 'big', 'medium', 'small', 'xs'.
        """
        w, h = self.screen.get_size()
        return scaled_fonts(w, h, BASE_W, BASE_H)

    def compute_layout(self):
        """Recalcule les rectangles des zones d'affichage et repositionne tous les boutons."""
        w, h = self.screen.get_size()
        pad = 16
        self.top_rect    = pygame.Rect(pad, pad, w - pad * 2, 72)
        self.left_rect   = pygame.Rect(pad, 104, int(w * 0.34), h - 170)
        self.right_rect  = pygame.Rect(self.left_rect.right + pad, 104,
                                       w - self.left_rect.width - pad * 3, h - 170)
        self.bottom_rect = pygame.Rect(pad, h - 50, w - pad * 2, 36)

        bw = min(240, self.right_rect.width - 40)
        bx = self.right_rect.x + 20
        by = self.right_rect.bottom - 60
        self.btn_restart.set_rect ((bx, by, self.right_rect.width - 40, 46))
        self.btn_vote.set_rect    ((bx, by, bw, 46))
        self.btn_hunter.set_rect  ((bx, by, bw, 46))
        self.btn_confirm.set_rect ((bx, by, bw, 46))
        self.btn_ignite.set_rect  ((bx, by, bw, 46))
        skip_x = bx + bw + 10
        skip_w = max(80, self.right_rect.right - 20 - skip_x)
        self.btn_skip.set_rect    ((skip_x, by, skip_w, 46))
        self.btn_save.set_rect    ((skip_x, by, skip_w, 46))

    # ── Queue temporisée ──────────────────────────────────────────────────────

    def schedule(self, delay_ms: float, fn):
        """
        Planifie l'exécution d'une fonction après un délai de jeu.

        :param delay_ms: Délai en millisecondes à partir du temps de jeu courant (float).
        :param fn: Fonction sans argument à exécuter (callable).
        """
        self.action_queue.append((self.game_ms + delay_ms, fn))
        self.action_queue.sort(key=lambda x: x[0])

    def update(self, dt_ms: float):
        """
        Avance l'horloge de jeu et exécute les actions planifiées arrivées à échéance.

        :param dt_ms: Temps écoulé depuis la dernière frame en millisecondes (float).
        """
        self.game_ms += dt_ms
        while self.action_queue and self.action_queue[0][0] <= self.game_ms:
            _, fn = self.action_queue.pop(0)
            fn()

    # ── Helpers logs ──────────────────────────────────────────────────────────

    def night_msg(self, msg: str):
        """
        Ajoute un message au journal de nuit (limité à 10 entrées).

        :param msg: Message à afficher dans le journal de nuit (str).
        """
        self.night_log.append(msg)
        if len(self.night_log) > 10:
            self.night_log.pop(0)

    def add_chat(self, author: str, text: str, wolf: bool = False):
        """
        Ajoute un message au chat (limité à 40 entrées).

        :param author: Nom de l'auteur (str).
        :param text: Contenu du message (str).
        :param wolf: True si le message est visible uniquement par les loups (bool).
        """
        self.chat_log.append({"author": author, "text": text, "wolf": wolf})
        if len(self.chat_log) > 40:
            self.chat_log.pop(0)

    # ── Initialisation ────────────────────────────────────────────────────────

    def setup_game(self):
        """Crée les joueurs, distribue les rôles, initialise tous les états et démarre la première nuit."""
        try:
            roles = build_roles(self.total_players, self.role_config)
        except ValueError:
            self.role_config = None
            roles = build_roles(self.total_players, self.role_config)

        self.players = [
            {"id": i,
             "name": self.player_name if i == 0 else f"IA {i}",
             "role": roles[i],
             "alive": True,
             "revealed_role": None,
             "infected":          False,
             "is_lover":          False,
             "lover_id":          None,
             "wild_child_turned": False,
             "wild_child_mentor": None,
             "maudit_converted":  False,
             "is_charmed":        False,
             "is_fueled":         False}
            for i in range(self.total_players)
        ]
        self.phase             = "night"
        self.day_count         = 1
        self.message           = "La nuit s'étend sur le village..."
        self.action_hint       = ""
        self.selected_target   = None
        self.winner            = None
        self.last_deaths       = []
        # Historique des exécutions par vote du village
        self.execution_history: list = []
        # Rôles initiaux de tous les joueurs
        self.initial_roles: dict = {p["id"]: p["role"] for p in self.players}
        # Journal des morts par jour
        self.daily_deaths: dict  = {}
        self.night_target_name = None
        self.seer_result       = None
        self.witch_heal_used   = False
        self.witch_poison_used = False
        self.pending_night     = {"seer_done": False, "witch_done": False}
        self.action_queue      = []
        self.game_ms           = 0
        self.is_animating      = True
        self.night_log         = []
        self.chat_log          = []
        self.day_votes         = {}
        self.hunter_pending      = False
        self.hunter_pending_done = None
        self.cupidon_pending      = False
        self.cupidon_pending_done = None
        self.cupidon_selections   = []
        self.wild_child_pending      = False
        self.wild_child_pending_done = None
        self.fox_pending      = False
        self.fox_pending_done = None
        self.fox_selections   = []
        self.fox_result       = None
        self.fox_power_active = True
        self.seer_known_wolves   = set()
        self.salvateur_last_protected = None
        self.charmed_players = []
        self.fueled_players  = []
        self.pyro_fuel_pending = False
        self.pyro_pending_done = None
        self.lovers            = []
        self.wolf_votes        = {}
        self.father_infect_used  = False
        self.father_pending      = False
        self.father_pending_done = None
        self.pending_hunter_deaths = []
        self.death_log         = []

        # Sniper : cible aléatoire
        sniper = next((p for p in self.players if p["role"] == "Sniper"), None)
        self.sniper_target = None
        if sniper:
            others = [p for p in self.players if p["id"] != sniper["id"]]
            if others:
                self.sniper_target = random.choice(others)["id"]
                if sniper["id"] == self.player_id and self.sniper_target is not None:
                    self.add_chat("Système",
                                  f"Votre cible secrète est : {self.players[self.sniper_target]['name']}",
                                  False)

        self.add_chat("Système", "Bonne chance ! Les rôles ont été distribués.", False)
        self._start_night()

    def current_player(self):
        """Retourne le dictionnaire du joueur humain."""
        return self.players[self.player_id]

    def current_role(self) -> str:
        """Retourne le nom du rôle du joueur humain."""
        return self.current_player()["role"]

    def alive_ids(self) -> list:
        """
        Retourne la liste des IDs des joueurs encore vivants.

        :return: list[int]
        """
        return [p["id"] for p in self.players if p["alive"]]

    def human_can_act(self) -> bool:
        """
        Retourne True si le joueur humain peut actuellement effectuer une action (vote, action de nuit, etc.).

        :return: bool
        """
        if self.winner:
            return False
        if self.hunter_pending or self.cupidon_pending or self.wild_child_pending:
            return True
        if self.fox_pending or self.pyro_fuel_pending or self.father_pending:
            return True
        if not self.current_player()["alive"] or self.is_animating:
            return False
        if self.phase == "day":
            return True
        if self.phase != "night":
            return False
        role = self.current_role()
        if is_wolf_role(role) or is_wolf_player(self.current_player()):
            return True
        if role == "Voyante" and not self.pending_night.get("seer_done"):
            return True
        if role == "Sorcière" and not self.pending_night.get("witch_done"):
            return True
        if role == "Salvateur" and not self.pending_night.get("salvateur_done"):
            return True
        if role == "Renard" and self.fox_power_active and not self.pending_night.get("fox_done"):
            return True
        if role == "Sirène" and not self.pending_night.get("siren_done"):
            return True
        if role == "Pyromane" and not self.pending_night.get("arsonist_done"):
            return True
        return False

    def random_target(self, exclude=None):
        """
        Retourne un ID de joueur vivant choisi aléatoirement, en excluant les IDs indiqués.

        :param exclude: ID ou ensemble d'IDs à exclure (int, set ou None).
        :return: int ou None si aucun joueur disponible.
        """
        if isinstance(exclude, int):
            exclude = {exclude}
        elif exclude is None:
            exclude = set()
        choices = [pid for pid in self.alive_ids() if pid not in exclude]
        return random.choice(choices) if choices else None

    # ── Phase de nuit ─────────────────────────────────────────────────────────

    def _start_night(self):
        """Initialise une nouvelle nuit : remet à zéro les logs et planifie les tours des rôles dans l'ordre."""
        self.is_animating  = True
        self.action_hint   = ""
        self.seer_result   = None
        self.fox_result    = None
        self.night_log     = []
        self.wolf_votes    = {}
        self.pending_night = {
            "seer_done":       False,
            "witch_done":      False,
            "salvateur_done":  False,
            "fox_done":        False,
            "siren_done":      False,
            "arsonist_done":   False,
        }
        self.night_target_name = None
        t = 0
        self.schedule(t, lambda: self.night_msg("Le village s'endort..."))
        t += 1200

        # Nuit 1 : Cupidon et Enfant sauvage
        if self.day_count == 1:
            t = self._chain_cupidon(t)
            t = self._chain_wild_child(t)

        # Le Salvateur protège EN PREMIER (avant les loups et le Pyromane)
        t = self._chain_salvateur(t)
        t = self._chain_wolves(t)

    def _chain_cupidon(self, t: int) -> int:
        """
        Planifie le tour de Cupidon dans la chaîne de nuit.

        :param t: Temps de départ en millisecondes dans la queue d'actions (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        cupidon = next((p for p in self.players if p["alive"] and p["role"] == "Cupidon"), None)
        if not cupidon:
            return t
        self.schedule(t, lambda: self.night_msg("Cupidon se réveille et cherche deux âmes à unir..."))
        t += 900
        if cupidon["id"] == self.player_id:
            self.schedule(t, self._pause_human_cupidon)
        else:
            def _cupidon_act(c=cupidon):
                alive_others = [p for p in self.players if p["alive"] and p["id"] != c["id"]]
                if len(alive_others) >= 2:
                    chosen = random.sample(alive_others, 2)
                    p1, p2 = chosen[0], chosen[1]
                    p1["is_lover"] = True
                    p1["lover_id"] = p2["id"]
                    p2["is_lover"] = True
                    p2["lover_id"] = p1["id"]
                    self.lovers = [p1["id"], p2["id"]]
                    self.night_msg(f"Cupidon unit {p1['name']} et {p2['name']} pour toujours...")
            self.schedule(t, _cupidon_act)
            t += 1400
            self.schedule(t, lambda: self.night_msg("Cupidon se rendort."))
            t += 900
        return t

    def _chain_wild_child(self, t: int) -> int:
        """
        Planifie le tour de l'Enfant sauvage dans la chaîne de nuit.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        wc = next((p for p in self.players if p["alive"] and p["role"] == "Enfant sauvage"), None)
        if not wc:
            return t
        self.schedule(t, lambda: self.night_msg("L'Enfant sauvage choisit son modèle..."))
        t += 900
        if wc["id"] == self.player_id:
            self.schedule(t, self._pause_human_wild_child)
        else:
            def _wc_act(w=wc):
                possible = [p for p in self.players
                            if p["alive"] and p["id"] != w["id"]
                            and not is_wolf_role(p["role"])]
                if not possible:
                    possible = [p for p in self.players if p["alive"] and p["id"] != w["id"]]
                if possible:
                    mentor = random.choice(possible)
                    w["wild_child_mentor"] = mentor["id"]
                    self.night_msg(f"L'Enfant sauvage a choisi son mentor dans l'ombre...")
            self.schedule(t, _wc_act)
            t += 1200
            self.schedule(t, lambda: self.night_msg("L'Enfant sauvage se rendort."))
            t += 800
        return t

    def _chain_wolves(self, t: int) -> int:
        """
        Planifie le tour des loups-garous dans la chaîne de nuit.
        Les votes sont maintenant tous visibles entre loups (humain et IA).
        En cas d'égalité, personne ne meurt.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        wolves = [p for p in self.players if p["alive"] and is_wolf_player(p)]
        if wolves:
            self.schedule(t, lambda: self.night_msg("Les loups-garous se réveillent..."))
            t += 900
            # Réinitialiser les votes des loups pour cette nuit
            self.wolf_votes = {}

            if any(w["id"] == self.player_id for w in wolves):
                # Le joueur humain est loup : les IA loups votent d'abord, puis on attend le joueur
                def _ai_wolves_vote(wlist=wolves):
                    non_wolves = [p for p in self.players
                                  if p["alive"] and not is_wolf_player(p)]
                    if not non_wolves:
                        return
                    for w in wlist:
                        if w["id"] != self.player_id:
                            # Chaque IA loup vote pour une cible parmi les non-loups
                            tgt = random.choice(non_wolves)["id"]
                            self.wolf_votes[w["id"]] = tgt
                    # Afficher les votes IA pour que le joueur humain les voit
                    if self.wolf_votes:
                        lines = [f"{self.players[vid]['name']} → {self.players[tid]['name']}"
                                 for vid, tid in self.wolf_votes.items()]
                        self.night_msg("Votes des autres loups : " + ", ".join(lines))
                self.schedule(t, _ai_wolves_vote)
                t += 800
                self.schedule(t, self._pause_human_wolf)
            else:
                def _wolves_act(wlist=wolves):
                    non_wolves = [p for p in self.players
                                  if p["alive"] and not is_wolf_player(p)]
                    if non_wolves:
                        # Chaque IA loup vote
                        for w in wlist:
                            tgt = random.choice(non_wolves)["id"]
                            self.wolf_votes[w["id"]] = tgt
                        # Résoudre : majorité ou égalité
                        from collections import Counter
                        counts = Counter(self.wolf_votes.values())
                        max_v = max(counts.values())
                        leaders = [pid for pid, cnt in counts.items() if cnt == max_v]
                        if len(leaders) == 1:
                            shared_target = leaders[0]
                            self.pending_night["wolf_target"] = shared_target
                            self.night_target_name = self.players[shared_target]["name"]
                            self.night_msg("Les loups ont choisi leur victime dans l'ombre...")
                        else:
                            self.pending_night["wolf_target"] = None
                            self.night_msg("Égalité dans les votes des loups : personne n'est attaqué !")
                    else:
                        self.night_msg("Les loups ne trouvent pas de cible.")
                self.schedule(t, _wolves_act)
                t += 1600
                self.schedule(t, lambda: self.night_msg("Les loups-garous se rendorment."))
                t += 900
                return self._chain_father(t)
        return self._chain_father(t)

    def _chain_father(self, t: int) -> int:
        """
        Planifie le tour de l'Infect Père des Loups dans la chaîne de nuit.
        Le pouvoir d'infection est utilisable une seule fois dans toute la partie.
        Il peut être différé (passer son tour) et sera définitivement perdu après utilisation.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        father = next((p for p in self.players
                       if p["alive"] and p["role"] == "Infect Père des Loups"), None)
        # Sauter si pas de Père, ou si le pouvoir a déjà été utilisé
        if not father or self.father_infect_used:
            return self._chain_seer(t)

        wolf_tgt = self.pending_night.get("wolf_target")
        # Sauter si aucune victime à infecter
        if wolf_tgt is None:
            return self._chain_seer(t)

        self.schedule(t, lambda: self.night_msg(
            "L'Infect Père des Loups se réveille et observe sa victime..."))
        t += 900

        if father["id"] == self.player_id:
            # Joueur humain : proposer infection ou passer
            self.schedule(t, self._pause_human_father)
            return t
        else:
            # IA : infecte avec 50 % de probabilité, sinon passe (différer)
            def _father_act(f=father, wt=wolf_tgt):
                if not self.father_infect_used and random.random() < 0.50:
                    self.players[wt]["infected"] = True
                    self.father_infect_used = True
                    self.pending_night["infected_target"] = wt
                    self.night_msg(
                        f"Le Père des Loups a infecté {self.players[wt]['name']} ! "
                        f"Il rejoindra la meute.")
                else:
                    self.night_msg(
                        "Le Père des Loups choisit de ne pas utiliser son pouvoir cette nuit.")
            self.schedule(t, _father_act)
            t += 1400
            self.schedule(t, lambda: self.night_msg("Le Père des Loups se rendort."))
            t += 900
            return self._chain_seer(t)

    def _pause_human_father(self):
        """Suspend l'animation et propose au joueur humain Père des Loups d'infecter ou de passer."""
        self.is_animating  = False
        self.father_pending = True
        wolf_tgt = self.pending_night.get("wolf_target")
        if wolf_tgt is not None:
            tgt_name = self.players[wolf_tgt]["name"]
            self.action_hint = (
                f"Tu es le Père des Loups : infecter {tgt_name} (utilisation unique, irréversible) "
                f"ou PASSER pour garder ton pouvoir pour plus tard.")
        else:
            self.action_hint = "Aucune victime à infecter. Clique sur PASSER."


        """
        Planifie le tour de la Voyante dans la chaîne de nuit.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        seer = next((p for p in self.players if p["alive"] and p["role"] == "Voyante"), None)
        if not seer:
            return self._chain_witch(t)
        self.schedule(t, lambda: self.night_msg("La Voyante se réveille..."))
        t += 900
        if seer["id"] == self.player_id:
            self.schedule(t, self._pause_human_seer)
            return t
        else:
            def _seer_act(s=seer):
                self.pending_night["seer_done"] = True
                tid = self.random_target(exclude=s["id"])
                if tid is not None:
                    if is_wolf_player(self.players[tid]):
                        self.seer_known_wolves.add(tid)
                    self.night_msg("La Voyante scrute les âmes dans le noir...")
            self.schedule(t, _seer_act)
            t += 1400
            self.schedule(t, lambda: self.night_msg("La Voyante se rendort."))
            t += 900
            return self._chain_witch(t)

    def _chain_witch(self, t: int) -> int:
        """
        Planifie le tour de la Sorcière dans la chaîne de nuit.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        witch = next((p for p in self.players if p["alive"] and p["role"] == "Sorcière"), None)
        if not witch:
            return self._chain_fox(t)
        self.schedule(t, lambda: self.night_msg("La Sorcière se réveille..."))
        t += 900
        if witch["id"] == self.player_id:
            self.schedule(t, self._pause_human_witch)
            return t
        else:
            def _witch_act():
                wolf_tgt = self.pending_night.get("wolf_target")
                if wolf_tgt is not None and not self.witch_heal_used and random.random() < 0.35:
                    self.pending_night["saved"] = True
                    self.witch_heal_used = True
                    self.night_msg("La Sorcière hésite... et utilise sa potion de soin.")
                elif not self.witch_poison_used and random.random() < 0.20:
                    tid = self.random_target(exclude=witch["id"])
                    if tid is not None:
                        self.pending_night["poison_target"] = tid
                        self.witch_poison_used = True
                        self.night_msg("La Sorcière prépare sa potion de mort...")
                else:
                    self.night_msg("La Sorcière observe et ne fait rien.")
                self.pending_night["witch_done"] = True
            self.schedule(t, _witch_act)
            t += 1600
            self.schedule(t, lambda: self.night_msg("La Sorcière se rendort."))
            t += 900
            return self._chain_fox(t)

    def _chain_salvateur(self, t: int) -> int:
        """
        Planifie le tour du Salvateur dans la chaîne de nuit.
        Le Salvateur agit EN PREMIER, avant les loups et le Pyromane.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        sal = next((p for p in self.players if p["alive"] and p["role"] == "Salvateur"), None)
        if not sal:
            return self._chain_wolves(t)
        self.schedule(t, lambda: self.night_msg("Le Salvateur veille sur le village..."))
        t += 900
        if sal["id"] == self.player_id:
            self.schedule(t, self._pause_human_salvateur)
            return t
        else:
            def _sal_act(s=sal):
                possible = [p["id"] for p in self.players
                            if p["alive"] and p["id"] != self.salvateur_last_protected]
                if not possible:
                    possible = [p["id"] for p in self.players if p["alive"]]
                if possible:
                    chosen = random.choice(possible)
                    self.pending_night["salvateur_protected"] = chosen
                    self.salvateur_last_protected = chosen
                    self.night_msg("Le Salvateur protège quelqu'un cette nuit...")
                self.pending_night["salvateur_done"] = True
            self.schedule(t, _sal_act)
            t += 1200
            self.schedule(t, lambda: self.night_msg("Le Salvateur se rendort."))
            t += 800
            return self._chain_wolves(t)

    def _chain_fox(self, t: int) -> int:
        """
        Planifie le tour du Renard dans la chaîne de nuit.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        fox = next((p for p in self.players if p["alive"] and p["role"] == "Renard"), None)
        if not fox or not self.fox_power_active:
            return self._chain_siren(t)
        self.schedule(t, lambda: self.night_msg("Le Renard tend l'oreille dans la nuit..."))
        t += 900
        if fox["id"] == self.player_id:
            self.schedule(t, self._pause_human_fox)
            return t
        else:
            def _fox_act(f=fox):
                alive_others = [p["id"] for p in self.players
                                if p["alive"] and p["id"] != f["id"]]
                if len(alive_others) >= 3:
                    chosen = random.sample(alive_others, 3)
                    has_wolf = any(is_wolf_player(self.players[c]) for c in chosen)
                    if not has_wolf:
                        self.fox_power_active = False
                        self.night_msg("Le Renard se trompe... et perd son pouvoir !")
                    else:
                        self.night_msg("Le Renard flaire la présence d'un loup...")
                self.pending_night["fox_done"] = True
            self.schedule(t, _fox_act)
            t += 1200
            self.schedule(t, lambda: self.night_msg("Le Renard se rendort."))
            t += 800
            return self._chain_siren(t)

    def _chain_siren(self, t: int) -> int:
        """
        Planifie le tour de la Sirène dans la chaîne de nuit.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        siren = next((p for p in self.players if p["alive"] and p["role"] == "Sirène"), None)
        if not siren:
            return self._chain_arsonist(t)
        self.schedule(t, lambda: self.night_msg("La Sirène chante dans la nuit..."))
        t += 900
        if siren["id"] == self.player_id:
            self.schedule(t, self._pause_human_siren)
            return t
        else:
            def _siren_act(s=siren):
                not_charmed = [p["id"] for p in self.players
                               if p["alive"] and p["id"] != s["id"]
                               and p["id"] not in self.charmed_players]
                if not_charmed:
                    tid = random.choice(not_charmed)
                    self.charmed_players.append(tid)
                    self.players[tid]["is_charmed"] = True
                    self.night_msg(f"La Sirène envoûte une âme dans les ténèbres...")
                self.pending_night["siren_done"] = True
            self.schedule(t, _siren_act)
            t += 1200
            self.schedule(t, lambda: self.night_msg("La Sirène se tait."))
            t += 800
            return self._chain_arsonist(t)

    def _chain_arsonist(self, t: int) -> int:
        """
        Planifie le tour du Pyromane dans la chaîne de nuit.

        :param t: Temps de départ en millisecondes (int).
        :return: Nouveau temps de départ pour la prochaine étape (int).
        """
        pyro = next((p for p in self.players if p["alive"] and p["role"] == "Pyromane"), None)
        if not pyro:
            return self._chain_end(t)
        self.schedule(t, lambda: self.night_msg("Le Pyromane rôde dans l'obscurité..."))
        t += 900
        if pyro["id"] == self.player_id:
            self.schedule(t, self._pause_human_pyro)
            return t
        else:
            def _pyro_act(p=pyro):
                not_fueled = [pl["id"] for pl in self.players
                              if pl["alive"] and pl["id"] != p["id"]
                              and pl["id"] not in self.fueled_players]
                n_fueled = len(self.fueled_players)
                alive_others = len([pl for pl in self.players
                                    if pl["alive"] and pl["id"] != p["id"]])
                # Allume le feu si plus de la moitié sont aspergés
                if n_fueled >= max(2, alive_others // 2) and random.random() < 0.6:
                    burned = set(self.fueled_players)
                    self.fueled_players = []
                    for bid in burned:
                        if bid < len(self.players):
                            self.players[bid]["is_fueled"] = False
                    self.pending_night["arsonist_ignite"] = burned
                    self.night_msg("Le Pyromane craque une allumette... TOUT BRÛLE !")
                elif not_fueled:
                    tid = random.choice(not_fueled)
                    self.fueled_players.append(tid)
                    self.players[tid]["is_fueled"] = True
                    self.night_msg("Le Pyromane asperge une victime d'essence...")
                self.pending_night["arsonist_done"] = True
            self.schedule(t, _pyro_act)
            t += 1200
            self.schedule(t, lambda: self.night_msg("Le Pyromane disparaît dans les ombres."))
            t += 800
            return self._chain_end(t)

    def _chain_end(self, t: int) -> int:
        """
        Termine la chaîne de nuit en planifiant la résolution des actions nocturnes.

        :param t: Temps de départ en millisecondes (int).
        :return: Temps inchangé (int).
        """
        self.schedule(t, self._resolve_night)
        return t

    # ── Pauses humain ─────────────────────────────────────────────────────────

    def _pause_human_cupidon(self):
        """Suspend l'animation et active le mode de sélection pour l'action humaine de Cupidon."""
        self.is_animating       = False
        self.cupidon_pending    = True
        self.cupidon_selections = []
        self.action_hint = ("Tu es Cupidon : clique sur 2 joueurs pour les unir, "
                            "puis valide. (0/2 sélectionnés)")

    def _pause_human_wild_child(self):
        """Suspend l'animation et active le mode de sélection pour l'action humaine de l'Enfant sauvage."""
        self.is_animating   = False
        self.wild_child_pending = True
        self.action_hint = ("Tu es l'Enfant sauvage : choisis ton mentor. "
                            "Si il meurt, tu deviendras loup.")

    def _pause_human_wolf(self):
        """Suspend l'animation et affiche le message d'action pour le joueur humain loup-garou."""
        self.is_animating = False
        self.action_hint  = "Tu es loup-garou : désigne une victime parmi les vivants."

    def _pause_human_seer(self):
        """Suspend l'animation et affiche le message d'action pour la Voyante humaine."""
        self.is_animating = False
        self.action_hint  = "Tu es Voyante : choisis un joueur pour voir son rôle."

    def _pause_human_witch(self):
        """Suspend l'animation et affiche le message contextuel pour la Sorcière humaine."""
        self.is_animating = False
        wolf_tgt = self.pending_night.get("wolf_target")
        if wolf_tgt is not None:
            victim = self.players[wolf_tgt]["name"]
            self.action_hint = (f"Tu es Sorcière : {victim} a été visé par les loups. "
                                f"Sauver ou empoisonner ?")
        else:
            self.action_hint = "Tu es Sorcière : personne n'est visé. Empoisonner quelqu'un ?"

    def _pause_human_salvateur(self):
        """Suspend l'animation et affiche le message d'action pour le Salvateur humain."""
        self.is_animating = False
        last_name = (self.players[self.salvateur_last_protected]["name"]
                     if self.salvateur_last_protected is not None else "personne")
        self.action_hint = (f"Tu es Salvateur : protège un joueur. "
                            f"Interdit : {last_name} (nuit précédente).")

    def _pause_human_fox(self):
        """Suspend l'animation et active le mode de sélection triplex pour le Renard humain."""
        self.is_animating  = False
        self.fox_pending   = True
        self.fox_selections = []
        self.action_hint = ("Tu es le Renard : sélectionne 3 joueurs pour sentir un loup "
                            "parmi eux. (0/3 sélectionnés)")

    def _pause_human_siren(self):
        """Suspend l'animation et affiche la liste des envoûtés pour la Sirène humaine."""
        self.is_animating = False
        charmed = [self.players[i]["name"] for i in self.charmed_players
                   if i < len(self.players)]
        already = (", ".join(charmed)) if charmed else "personne"
        self.action_hint = (f"Tu es la Sirène : envoûte un joueur ou passe. "
                            f"Déjà envoûtés : {already}.")

    def _pause_human_pyro(self):
        """Suspend l'animation et affiche la liste des aspergés pour le Pyromane humain."""
        self.is_animating = False
        fueled = [self.players[i]["name"] for i in self.fueled_players
                  if i < len(self.players)]
        if fueled:
            self.action_hint = (f"Tu es le Pyromane : asperge un joueur "
                                f"OU clique sur METTRE LE FEU "
                                f"(aspergés : {', '.join(fueled)}).")
        else:
            self.action_hint = "Tu es le Pyromane : asperge un joueur d'essence."

    # ── Reprise après action humaine ──────────────────────────────────────────

    def _resume_after_human(self):
        """Reprend la chaîne de nuit après l'action du joueur humain, en passant à l'étape suivante selon son rôle."""
        role = self.current_role()
        self.is_animating = True
        self.action_hint  = ""
        t = 0
        if self.cupidon_pending:
            self.cupidon_pending = False
            self.schedule(t, lambda: self.night_msg("Cupidon se rendort."))
            t += 900
            self.schedule(t, lambda: self._chain_wild_child_then_salvateur_then_wolves(t))
            return
        if self.wild_child_pending:
            self.wild_child_pending = False
            self.schedule(t, lambda: self.night_msg("L'Enfant sauvage se rendort."))
            t += 900
            self._schedule_chain(self._chain_salvateur, t)
            return
        if self.father_pending:
            self.father_pending = False
            self.schedule(t, lambda: self.night_msg("Le Père des Loups se rendort."))
            t += 900
            self._schedule_chain(self._chain_seer, t)
            return
        if self.fox_pending:
            self.fox_pending = False
            self.schedule(t, lambda: self.night_msg("Le Renard se rendort."))
            t += 900
            self._schedule_chain(self._chain_siren, t)
            return
        if self.pyro_fuel_pending:
            self.pyro_fuel_pending = False
            self.schedule(t, lambda: self.night_msg("Le Pyromane disparaît dans les ombres."))
            t += 800
            self._chain_end(t)
            return
        if is_wolf_role(role) or is_wolf_player(self.current_player()):
            self.schedule(t, lambda: self.night_msg("Les loups-garous se rendorment."))
            t += 900
            self._schedule_chain(self._chain_father, t)
        elif role == "Voyante":
            self.schedule(t, lambda: self.night_msg("La Voyante se rendort."))
            t += 900
            self._schedule_chain(self._chain_witch, t)
        elif role == "Sorcière":
            self.schedule(t, lambda: self.night_msg("La Sorcière se rendort."))
            t += 900
            self._schedule_chain(self._chain_fox, t)
        elif role == "Salvateur":
            # Salvateur avant loups : la suite est la chaîne des loups
            self.schedule(t, lambda: self.night_msg("Le Salvateur se rendort."))
            t += 800
            self._schedule_chain(self._chain_wolves, t)
        elif role == "Sirène":
            self.schedule(t, lambda: self.night_msg("La Sirène se tait."))
            t += 800
            self._schedule_chain(self._chain_arsonist, t)
        elif role == "Pyromane":
            self.schedule(t, lambda: self.night_msg("Le Pyromane disparaît."))
            t += 800
            self._chain_end(t)
        else:
            self._chain_end(t)

    def _schedule_chain(self, fn, t: int):
        """
        Planifie l'appel d'une fonction de chaîne avec un offset nul après un délai.

        :param fn: Fonction à appeler, prenant un temps de départ (callable).
        :param t: Délai en millisecondes avant l'appel (int).
        """
        self.schedule(t, lambda: fn(0))

    def _chain_wild_child_then_salvateur_then_wolves(self, t: int):
        """
        Enchaîne : Enfant sauvage → Salvateur → Loups depuis Cupidon (nuit 1).

        :param t: Paramètre de temps non utilisé directement (int).
        """
        new_t = self._chain_wild_child(0)
        if not self.wild_child_pending:
            sal_t = self._chain_salvateur(new_t)
            if not self.pending_night.get("salvateur_done") is False:
                # Le Salvateur humain a pris la main, on attend
                pass
            else:
                self._do_chain_wolves(sal_t)

    def _chain_wild_child_then_wolves(self, t: int):
        """
        Enchaîne le tour de l'Enfant sauvage puis celui des loups, en tenant compte d'une éventuelle pause humaine.

        :param t: Paramètre de temps non utilisé directement (int).
        """
        new_t = self._chain_wild_child(0)
        if not self.wild_child_pending:
            self._do_chain_wolves(new_t)

    def _do_chain_wolves(self, t: int):
        """
        Lance directement la chaîne des loups à partir du temps donné.

        :param t: Temps de départ en millisecondes (int).
        """
        self._chain_wolves(t)

    # ── Résolution de nuit ────────────────────────────────────────────────────

    def _apply_death(self, pid: int, deaths: set):
        """
        Marque un joueur comme mort et enregistre son rôle révélé dans l'ensemble des décès.

        :param pid: Indice du joueur à tuer (int).
        :param deaths: Ensemble des identifiants de joueurs morts ce tour (set), modifié en place.
        """
        if self.players[pid]["alive"]:
            self.players[pid]["alive"]         = False
            self.players[pid]["revealed_role"] = self.players[pid]["role"]
            deaths.add(pid)

    def _check_lover_deaths(self, dead_ids: set) -> set:
        """
        Vérifie si des amoureux doivent mourir de chagrin suite aux décès donnés et les tue.

        :param dead_ids: Ensemble des identifiants des joueurs déjà morts (set).
        :return: Ensemble des nouveaux décès causés par la règle des amoureux (set).
        """
        new_deaths = set()
        for pid in list(dead_ids):
            if self.players[pid].get("is_lover"):
                partner_id = self.players[pid].get("lover_id")
                if (partner_id is not None
                        and partner_id < len(self.players)
                        and self.players[partner_id]["alive"]):
                    self._apply_death(partner_id, new_deaths)
                    self.add_chat("Système",
                                  f"{self.players[partner_id]['name']} meurt de chagrin...",
                                  False)
        return new_deaths

    def _check_wild_child_conversion(self, dead_ids: set):
        """
        Convertit l'Enfant sauvage en loup si son mentor figure parmi les joueurs morts.

        :param dead_ids: Ensemble des identifiants des joueurs morts ce tour (set).
        """
        for p in self.players:
            if (p["alive"]
                    and p["role"] == "Enfant sauvage"
                    and not p.get("wild_child_turned", False)
                    and p.get("wild_child_mentor") in dead_ids):
                p["wild_child_turned"] = True
                self.add_chat("Système",
                              f"{p['name']} (Enfant sauvage) a perdu son mentor et rejoint les loups !",
                              False)

    def _all_deaths_from(self, initial: set) -> set:
        """
        Calcule l'ensemble complet des morts en propageant les effets en chaîne (amoureux, Enfant sauvage).

        :param initial: Ensemble des décès initiaux (set).
        :return: Ensemble étendu de tous les joueurs morts après propagation (set).
        """
        all_dead = set(initial)
        chain = self._check_lover_deaths(initial)
        all_dead |= chain
        if chain:
            chain2 = self._check_lover_deaths(chain)
            all_dead |= chain2
        self._check_wild_child_conversion(all_dead)
        return all_dead

    def _resolve_night(self):
        """Applique toutes les actions nocturnes (loups, poison, feu), propage les morts en chaîne et déclenche les Chasseurs."""
        deaths: set = set()
        salvateur_protected = self.pending_night.get("salvateur_protected")

        wolf_tgt = self.pending_night.get("wolf_target")
        if wolf_tgt is not None and not self.pending_night.get("saved"):
            if wolf_tgt == salvateur_protected:
                self.add_chat("Système", "Le Salvateur a protégé quelqu'un cette nuit !", False)
            elif (self.players[wolf_tgt]["role"] == "Villageois Maudit"
                  and not self.players[wolf_tgt].get("maudit_converted", False)):
                self.players[wolf_tgt]["maudit_converted"] = True
                self.add_chat("Système",
                              f"{self.players[wolf_tgt]['name']} révèle sa malédiction et rejoint les loups !",
                              False)
            else:
                self._apply_death(wolf_tgt, deaths)
                cause = "loup"
                self.death_log.append({
                    "name":  self.players[wolf_tgt]["name"],
                    "role":  self.players[wolf_tgt]["role"],
                    "cause": cause,
                    "round": self.day_count,
                })

        # Poison Sorcière
        pt = self.pending_night.get("poison_target")
        if pt is not None and self.players[pt]["alive"]:
            self._apply_death(pt, deaths)
            self.death_log.append({
                "name":  self.players[pt]["name"],
                "role":  self.players[pt]["role"],
                "cause": "poison",
                "round": self.day_count,
            })

        # Pyromane ignition (si l'IA a décidé d'allumer)
        burned = self.pending_night.get("arsonist_ignite", set())
        for bid in burned:
            if bid < len(self.players) and self.players[bid]["alive"]:
                self._apply_death(bid, deaths)
                self.death_log.append({
                    "name":  self.players[bid]["name"],
                    "role":  self.players[bid]["role"],
                    "cause": "feu",
                    "round": self.day_count,
                })

        all_dead = self._all_deaths_from(deaths)
        self.last_deaths = [self.players[pid]["name"] for pid in all_dead]

        # Sniper : si la cible meurt cette nuit (pas par vote), le Sniper perd sa condition spéciale
        if self.sniper_target is not None and self.sniper_target in all_dead:
            sniper = next((p for p in self.players if p["alive"] and p["role"] == "Sniper"), None)
            if sniper:
                tgt_name = self.players[self.sniper_target]["name"]
                self.add_chat("Système",
                              f"La cible du Sniper ({tgt_name}) est morte cette nuit ! "
                              f"Le Sniper perd sa victoire spéciale et continue comme Villageois.",
                              False)
                self.sniper_target = None  # Perte de la condition spéciale

        # Les Chasseurs morts de nuit agissent APRÈS l'annonce matinale (dans _continue_after_night)
        self.pending_hunter_deaths = [pid for pid in all_dead
                                      if self.players[pid].get("revealed_role") == "Chasseur"]
        self._continue_after_night()

    def _continue_after_night(self):
        """Vérifie les conditions de victoire après la nuit et démarre la phase de jour ou la fin de partie."""
        # Vérifier victoire Pyromane (si tout le monde est mort via ignition)
        pyro = next((p for p in self.players if p["role"] == "Pyromane"), None)
        if pyro and not pyro["alive"]:
            pass  # pyromane mort = pas de victoire
        elif pyro and pyro["alive"]:
            alive_non_pyro = [p for p in self.players if p["alive"] and p["id"] != pyro["id"]]
            if not alive_non_pyro:
                self.winner = "Pyromane"
                self.phase  = "end"
                self.message = "Victoire du Pyromane : tout le village a brûlé !"
                self.is_animating = False
                return

        self.winner = check_winner(self.players)
        if self.winner:
            self.phase   = "end"
            self.message = f"Victoire du camp : {self.winner} !"
            self.is_animating = False
            return

        self.phase = "day"
        if self.last_deaths:
            victims = ", ".join(self.last_deaths)
            self.message = f"Au petit matin... {victims} est retrouvé mort."
            self.add_chat("Système", f"{victims} a été éliminé cette nuit.", False)
        else:
            self.message = "Le village se réveille — personne n'est mort cette nuit !"
            self.add_chat("Système", "Personne n'est mort cette nuit.", False)
        self.selected_target = None
        self.day_votes       = {}

        # Chasseurs morts de nuit : agissent MAINTENANT, après l'annonce matinale
        hunter_deaths = getattr(self, "pending_hunter_deaths", [])
        self.pending_hunter_deaths = []
        if hunter_deaths:
            def _chain(remaining):
                if not remaining:
                    self._start_day()
                    return
                self._trigger_hunter(remaining[0], lambda: _chain(remaining[1:]))
            _chain(hunter_deaths)
        else:
            self._start_day()

    def _trigger_hunter(self, hunter_id: int, on_done):
        """
        Déclenche l'action du Chasseur mort : si humain, attend sa sélection ; si IA, choisit une cible aléatoire.

        :param hunter_id: Indice du Chasseur dans la liste des joueurs (int).
        :param on_done: Callback à appeler une fois l'action terminée (callable).
        """
        hunter = self.players[hunter_id]
        if hunter["id"] == self.player_id:
            self.hunter_pending      = True
            self.hunter_pending_done = on_done
            self.is_animating = False
            self.action_hint  = (f"{hunter['name']} : tu es le Chasseur ! "
                                 f"Désigne un joueur à emporter avec toi.")
        else:
            targets = [p["id"] for p in self.players
                       if p["alive"] and p["id"] != hunter_id]
            if targets:
                tid = random.choice(targets)
                extra = set()
                self._apply_death(tid, extra)
                extra2 = self._all_deaths_from(extra)
                self.last_deaths += [self.players[pid]["name"] for pid in extra2]
                self.death_log.append({
                    "name":  self.players[tid]["name"],
                    "role":  self.players[tid]["role"],
                    "cause": "chasseur",
                    "round": self.day_count,
                })
                self.add_chat("Système",
                              f"{self.players[tid]['name']} est abattu d'une balle !", False)
            on_done()

    # ── Phase de jour ─────────────────────────────────────────────────────────

    def _start_day(self):
        """Démarre la phase de jour : fait parler quelques joueurs IA avant d'ouvrir le vote."""
        self.is_animating = True
        t = 0
        ai_speakers = [p for p in self.players if p["alive"] and p["id"] != self.player_id]
        random.shuffle(ai_speakers)
        speakers = ai_speakers[:min(4, len(ai_speakers))]
        for sp in speakers:
            def _say(player=sp):
                msg = _ai_chat_msg(player, self.players)
                self.add_chat(player["name"], msg, is_wolf_player(player))
            self.schedule(t, _say)
            t += random.randint(1000, 1800)
        self.schedule(t, self._open_vote)

    def _open_vote(self):
        """Ouvre la phase de vote : demande au joueur humain de voter ou déclenche les votes IA s'il est mort."""
        self.message = "C'est l'heure du vote ! Qui est le loup ?"
        if not self.current_player()["alive"]:
            self.add_chat("Système", "Tu es éliminé. Le village vote sans toi.", False)
            self.is_animating = True
            self._ai_votes()
        else:
            self.action_hint = "Clique sur un joueur vivant puis valide ton vote."
            self.is_animating = False

    def _ai_votes(self):
        """Planifie les votes des joueurs IA selon leur rôle (loups coordonnés, Voyante informée, autres aléatoires)."""
        self.is_animating = True
        t = 0
        ai_voters = [p for p in self.players
                     if p["alive"] and p["id"] != self.player_id
                     and p["id"] not in self.day_votes]
        random.shuffle(ai_voters)

        non_wolves_alive = [p for p in self.players
                            if p["alive"] and not is_wolf_player(p)]
        wolf_shared_target = (random.choice(non_wolves_alive)["id"]
                              if non_wolves_alive else None)

        for voter in ai_voters:
            def _vote(v=voter, wt=wolf_shared_target):
                if is_wolf_player(v):
                    if wt is not None and self.players[wt]["alive"]:
                        tid = wt
                    else:
                        pool = [pid for pid in self.alive_ids()
                                if pid != v["id"] and not is_wolf_player(self.players[pid])]
                        if not pool:
                            pool = [pid for pid in self.alive_ids() if pid != v["id"]]
                        if not pool:
                            return
                        tid = random.choice(pool)

                elif v["role"] == "Voyante":
                    living_known = [pid for pid in self.seer_known_wolves
                                    if pid < len(self.players) and self.players[pid]["alive"]]
                    if living_known:
                        tid = random.choice(living_known)
                    else:
                        pool = [pid for pid in self.alive_ids() if pid != v["id"]]
                        tid = random.choice(pool) if pool else None
                        if tid is None:
                            return

                elif v["role"] == "Sniper" and self.sniper_target is not None:
                    if (self.players[self.sniper_target]["alive"]
                            and self.sniper_target in self.alive_ids()
                            and self.sniper_target != v["id"]):
                        tid = self.sniper_target
                    else:
                        pool = [pid for pid in self.alive_ids() if pid != v["id"]]
                        tid = random.choice(pool) if pool else None
                        if tid is None:
                            return

                else:
                    pool = [pid for pid in self.alive_ids() if pid != v["id"]]
                    if not pool:
                        return
                    current_counts = Counter(self.day_votes.values())
                    if current_counts and random.random() < 0.45:
                        sorted_tgts = [pid for pid, _ in current_counts.most_common()
                                       if pid in pool]
                        tid = sorted_tgts[0] if sorted_tgts else random.choice(pool)
                    else:
                        tid = random.choice(pool)

                self.day_votes[v["id"]] = tid
                tgt_name = self.players[tid]["name"]
                self.add_chat(v["name"], f"Je vote contre {tgt_name}.",
                              is_wolf_player(v))

            self.schedule(t, _vote)
            t += random.randint(700, 1300)
        self.schedule(t + 500, self._resolve_day)

    def _resolve_day(self):
        """Dépouillement des votes : gère l'égalité (personne éliminé) ou désigne la cible majoritaire."""
        for p in self.players:
            if p["alive"] and p["id"] not in self.day_votes:
                tid = self.random_target(exclude=p["id"])
                if tid is not None:
                    self.day_votes[p["id"]] = tid

        counts: dict = {}
        for tgt in self.day_votes.values():
            counts[tgt] = counts.get(tgt, 0) + 1

        max_votes = max(counts.values()) if counts else 0
        leaders = [pid for pid, cnt in counts.items() if cnt == max_votes]

        parts = sorted(counts.items(), key=lambda x: -x[1])
        tally = " | ".join(f"{self.players[pid]['name']}: {cnt} voix"
                           for pid, cnt in parts)

        if len(leaders) > 1:
            # Égalité : personne n'est éliminé
            self.message = f"Décompte — {tally}  → Égalité ! Personne n'est éliminé."
            self.add_chat("Système", f"Votes : {tally} — Égalité, personne n'est éliminé.", False)
            self.schedule(2400, self._apply_day_tie)
        else:
            chosen = leaders[0]
            arrow = f"→ {self.players[chosen]['name']} éliminé"
            self.message = f"Décompte — {tally}  {arrow}"
            self.add_chat("Système", f"Votes : {tally}", False)
            self.schedule(2400, lambda c=chosen: self._apply_day_result(c))

    def _apply_day_tie(self):
        """Aucun joueur éliminé à cause d'une égalité : vérifie la victoire puis passe à la nuit."""
        self.winner = check_winner(self.players)
        if self.winner:
            self.phase   = "end"
            self.message = f"Égalité. Victoire : {self.winner} !"
            self.is_animating = False
            return
        self.phase      = "night"
        self.day_count += 1
        self.message    = "Égalité ! Personne n'est éliminé. La nuit tombe..."
        self.selected_target = None
        self.day_votes  = {}
        self.schedule(900, self._start_night)

    def _apply_day_result(self, chosen: int):
        """
        Applique l'élimination du joueur choisi par vote, propage les morts en chaîne et vérifie la victoire.

        :param chosen: Indice du joueur éliminé par le vote (int).
        """
        deaths = set()
        self._apply_death(chosen, deaths)
        role_reveal = self.players[chosen]["role"]
        self.add_chat("Système",
                      f"{self.players[chosen]['name']} est éliminé ! C'était un {role_reveal}.",
                      False)
        self.death_log.append({
            "name":  self.players[chosen]["name"],
            "role":  role_reveal,
            "cause": "vote",
            "round": self.day_count,
        })
        # Enregistrer dans l'historique des exécutions pour l'écran de fin
        if not hasattr(self, "execution_history"):
            self.execution_history = []
        self.execution_history.append({
            "jour": self.day_count,
            "nom":  self.players[chosen]["name"],
            "role": role_reveal,
        })
        if not hasattr(self, "daily_deaths"):
            self.daily_deaths = {}
        self.daily_deaths.setdefault(self.day_count, []).append(self.players[chosen]["name"])

        # Vérification victoire Sniper
        if chosen == self.sniper_target:
            sniper = next((p for p in self.players
                           if p["alive"] and p["role"] == "Sniper"), None)
            if sniper:
                self.winner = "Sniper"
                self.phase  = "end"
                self.message = (f"{self.players[chosen]['name']} éliminé — "
                                f"c'était la cible du Sniper ! Victoire : Sniper !")
                self.last_deaths = [self.players[chosen]["name"]]
                self.is_animating = False
                return

        # Chaîne de morts
        all_dead = self._all_deaths_from(deaths)
        self.last_deaths = [self.players[pid]["name"] for pid in all_dead]

        # Sniper : si la cible meurt en chaîne (pas directement par vote), perte de condition spéciale
        if self.sniper_target is not None and self.sniper_target in all_dead and self.sniper_target != chosen:
            sniper = next((p for p in self.players if p["alive"] and p["role"] == "Sniper"), None)
            if sniper:
                tgt_name = self.players[self.sniper_target]["name"]
                self.add_chat("Système",
                              f"La cible du Sniper ({tgt_name}) est morte en chaîne ! "
                              f"Le Sniper perd sa victoire spéciale et continue comme Villageois.",
                              False)
                self.sniper_target = None

        if role_reveal == "Chasseur" or any(self.players[pid].get("revealed_role") == "Chasseur"
                                             for pid in all_dead):
            hunter_ids = [pid for pid in all_dead
                          if self.players[pid].get("revealed_role") == "Chasseur"]
            def _chain(remaining):
                if not remaining:
                    self._check_winner_day(chosen)
                    return
                self._trigger_hunter(remaining[0], lambda: _chain(remaining[1:]))
            _chain(hunter_ids)
        else:
            self._check_winner_day(chosen)

    def _check_winner_day(self, chosen: int):
        """
        Vérifie la condition de victoire après l'élimination diurne et démarre la nuit suivante si la partie continue.

        :param chosen: Indice du joueur éliminé par vote (int).
        """
        self.winner = check_winner(self.players)
        if self.winner:
            self.phase   = "end"
            self.message = (f"{self.players[chosen]['name']} éliminé. "
                            f"Victoire : {self.winner} !")
            self.is_animating = False
            return
        self.phase      = "night"
        self.day_count += 1
        self.message    = f"{self.players[chosen]['name']} éliminé. La nuit tombe..."
        self.selected_target = None
        self.day_votes  = {}
        self.schedule(900, self._start_night)

    # ── Actions humaines ──────────────────────────────────────────────────────

    def apply_human_action(self):
        """Traite l'action du joueur humain selon l'état courant (vote, action de nuit, Chasseur, Cupidon, etc.)."""
        # Chasseur
        if self.hunter_pending:
            if self.selected_target is None:
                return
            tid = self.selected_target
            deaths = set()
            self._apply_death(tid, deaths)
            all_dead = self._all_deaths_from(deaths)
            self.add_chat("Système",
                          f"{self.players[tid]['name']} est abattu d'une balle !", False)
            self.last_deaths += [self.players[pid]["name"] for pid in all_dead]
            self.death_log.append({"name": self.players[tid]["name"],
                                   "role": self.players[tid]["role"],
                                   "cause": "chasseur", "round": self.day_count})
            self.hunter_pending = False
            self.selected_target = None
            done = self.hunter_pending_done
            self.hunter_pending_done = None
            self.is_animating = True
            self.action_hint  = ""
            done()
            return

        # Cupidon
        if self.cupidon_pending:
            if self.selected_target is None:
                return
            if self.selected_target not in self.cupidon_selections:
                self.cupidon_selections.append(self.selected_target)
                self.selected_target = None
                n = len(self.cupidon_selections)
                if n < 2:
                    self.action_hint = (f"Tu es Cupidon : clique sur 2 joueurs pour les unir, "
                                        f"puis valide. ({n}/2 sélectionnés)")
                    return
            if len(self.cupidon_selections) >= 2:
                p1, p2 = self.cupidon_selections[0], self.cupidon_selections[1]
                self.players[p1]["is_lover"] = True
                self.players[p1]["lover_id"] = p2
                self.players[p2]["is_lover"] = True
                self.players[p2]["lover_id"] = p1
                self.lovers = [p1, p2]
                self.night_msg(f"Tu as uni {self.players[p1]['name']} et {self.players[p2]['name']} !")
                self.selected_target    = None
                self.cupidon_selections = []
                self._resume_after_human()
            return

        # Enfant sauvage
        if self.wild_child_pending:
            if self.selected_target is None:
                return
            mentor_id = self.selected_target
            if mentor_id == self.player_id:
                return
            self.current_player()["wild_child_mentor"] = mentor_id
            self.night_msg(f"Tu as choisi {self.players[mentor_id]['name']} comme mentor.")
            self.selected_target = None
            self._resume_after_human()
            return

        # Père des Loups : infecter la victime des loups (1 seule fois)
        if self.father_pending:
            wolf_tgt = self.pending_night.get("wolf_target")
            if wolf_tgt is not None and not self.father_infect_used:
                self.players[wolf_tgt]["infected"] = True
                self.father_infect_used = True
                self.pending_night["infected_target"] = wolf_tgt
                self.night_msg(
                    f"Tu as infecté {self.players[wolf_tgt]['name']} ! "
                    f"Ce pouvoir est maintenant définitivement épuisé.")
            self.father_pending  = False
            self.selected_target = None
            self._resume_after_human()
            return

        # Renard
        if self.fox_pending:
            if self.selected_target is None:
                return
            if self.selected_target not in self.fox_selections:
                self.fox_selections.append(self.selected_target)
                self.selected_target = None
                n = len(self.fox_selections)
                if n < 3:
                    self.action_hint = (f"Tu es le Renard : sélectionne 3 joueurs. "
                                        f"({n}/3 sélectionnés)")
                    return
            if len(self.fox_selections) >= 3:
                has_wolf = any(is_wolf_player(self.players[i]) for i in self.fox_selections)
                if not has_wolf:
                    self.fox_power_active = False
                    self.fox_result = "Aucun loup parmi ces 3 joueurs. Tu perds ton pouvoir !"
                    self.night_msg("Le Renard se trompe... et perd son pouvoir !")
                    self.add_chat("Système", "Renard : aucun loup parmi les 3 joueurs choisis. Pouvoir perdu !", False)
                else:
                    self.fox_result = "Il y a au moins un loup parmi ces 3 joueurs !"
                    self.night_msg("Le Renard flaire un loup !")
                    self.add_chat("Système", "Renard : un loup se cache parmi les 3 joueurs choisis !", False)
                self.pending_night["fox_done"] = True
                self.selected_target  = None
                self.fox_selections   = []
                self._resume_after_human()
            return

        # Pyromane : ignition
        if self.pyro_fuel_pending:
            return  # géré par btn_ignite et la sélection

        role = self.current_role()
        if self.phase == "day":
            if self.selected_target is None:
                return
            tid = self.selected_target
            self.day_votes[self.player_id] = tid
            self.add_chat(self.player_name,
                          f"Je vote contre {self.players[tid]['name']}.", False)
            self.selected_target = None
            self.is_animating = True
            self._ai_votes()
            return

        if self.phase != "night" or self.selected_target is None:
            return

        if is_wolf_role(role) or is_wolf_player(self.current_player()):
            # Enregistrer le vote du joueur humain loup
            self.wolf_votes[self.player_id] = self.selected_target
            # Résoudre l'ensemble des votes loups (humain + IA déjà votés)
            from collections import Counter as _Counter
            counts = _Counter(self.wolf_votes.values())
            max_v = max(counts.values())
            leaders = [pid for pid, cnt in counts.items() if cnt == max_v]
            if len(leaders) == 1:
                self.pending_night["wolf_target"] = leaders[0]
                self.night_target_name = self.players[leaders[0]]["name"]
                self.night_msg(f"Tu as désigné ta victime : {self.night_target_name}.")
                # Afficher le récap des votes
                lines = [f"{self.players[vid]['name']} → {self.players[tid]['name']}"
                         for vid, tid in self.wolf_votes.items()]
                self.night_msg("Votes loups : " + ", ".join(lines))
            else:
                self.pending_night["wolf_target"] = None
                self.night_msg("Égalité dans les votes des loups : personne n'est attaqué !")
            self.selected_target = None
            self._resume_after_human()

        elif role == "Voyante":
            self.pending_night["seer_done"] = True
            tgt = self.selected_target
            tgt_role = self.players[tgt]["role"]
            suffix = ""
            if is_wolf_player(self.players[tgt]):
                suffix = " — C'EST UN LOUP !"
                self.seer_known_wolves.add(tgt)
            self.seer_result = f"{self.players[tgt]['name']} est {tgt_role}.{suffix}"
            self.night_msg("Tu as observé un joueur dans l'obscurité.")
            self.selected_target = None
            self._resume_after_human()

        elif role == "Salvateur":
            tid = self.selected_target
            if tid == self.salvateur_last_protected:
                self.action_hint = "Impossible : tu as déjà protégé cette personne la nuit dernière."
                return
            self.pending_night["salvateur_protected"] = tid
            self.salvateur_last_protected = tid
            self.pending_night["salvateur_done"] = True
            self.night_msg(f"Tu protèges {self.players[tid]['name']} cette nuit.")
            self.selected_target = None
            self._resume_after_human()

        elif role == "Sirène":
            tid = self.selected_target
            if tid not in self.charmed_players:
                self.charmed_players.append(tid)
                self.players[tid]["is_charmed"] = True
                self.night_msg(f"Tu envoûtes {self.players[tid]['name']}.")
            self.pending_night["siren_done"] = True
            self.selected_target = None
            self._resume_after_human()

        elif role == "Pyromane":
            tid = self.selected_target
            if tid not in self.fueled_players:
                self.fueled_players.append(tid)
                self.players[tid]["is_fueled"] = True
                self.night_msg(f"Tu asperges {self.players[tid]['name']} d'essence.")
            self.pending_night["arsonist_done"] = True
            self.selected_target = None
            self._resume_after_human()

        elif role == "Sorcière":
            # Empoisonner
            self.pending_night["poison_target"] = self.selected_target
            self.pending_night["witch_done"]    = True
            self.witch_poison_used = True
            self.night_msg("Tu as utilisé ta potion de mort.")
            self.selected_target = None
            self._resume_after_human()

    def save_victim(self):
        """Sorcière humaine : utilise la potion de soin pour sauver la victime des loups cette nuit."""
        if self.current_role() != "Sorcière" or self.phase != "night":
            return
        wolf_tgt = self.pending_night.get("wolf_target")
        if wolf_tgt is not None and not self.witch_heal_used:
            self.pending_night["saved"] = True
            self.witch_heal_used = True
            self.night_msg(f"Tu as sauvé {self.players[wolf_tgt]['name']} avec ta potion de soin !")
        self.pending_night["witch_done"] = True
        self.selected_target = None
        self._resume_after_human()

    def skip_action(self):
        """Passe l'action nocturne du joueur humain (Sorcière, Sirène, Pyromane, Renard, Salvateur ou Père des Loups)."""
        role = self.current_role()
        if self.phase == "night":
            if self.father_pending:
                # Le Père passe → il garde son pouvoir pour plus tard
                self.night_msg("Le Père des Loups choisit de ne pas infecter cette nuit.")
                self.father_pending  = False
                self.selected_target = None
                self._resume_after_human()
            elif role == "Sorcière":
                self.night_msg("Tu passes ton tour de Sorcière.")
                self.pending_night["witch_done"] = True
                self.selected_target = None
                self._resume_after_human()
            elif role == "Sirène":
                self.night_msg("La Sirène choisit de ne pas agir.")
                self.pending_night["siren_done"] = True
                self.selected_target = None
                self._resume_after_human()
            elif role == "Pyromane":
                self.night_msg("Le Pyromane attend son heure...")
                self.pending_night["arsonist_done"] = True
                self.selected_target = None
                self.pyro_fuel_pending = False
                self._resume_after_human()
            elif role == "Renard" and self.fox_pending:
                self.fox_pending = False
                self.fox_selections = []
                self.pending_night["fox_done"] = True
                self.selected_target = None
                self._resume_after_human()
            elif role == "Salvateur":
                self.pending_night["salvateur_done"] = True
                self.selected_target = None
                self._resume_after_human()

    def ignite_fire(self):
        """Pyromane allume le feu (brûle tous les aspergés)."""
        if self.current_role() != "Pyromane" or self.phase != "night":
            return
        burned = set(self.fueled_players)
        self.fueled_players = []
        for bid in burned:
            if bid < len(self.players):
                self.players[bid]["is_fueled"] = False
        self.pending_night["arsonist_ignite"] = burned
        self.pending_night["arsonist_done"]   = True
        if burned:
            self.night_msg(f"Tu mets le feu ! {len(burned)} joueur(s) brûlent !")
        else:
            self.night_msg("Pas de joueurs aspergés à brûler.")
        self.selected_target   = None
        self.pyro_fuel_pending = False
        self._resume_after_human()

    # ── Narration fin de partie ───────────────────────────────────────────────

    def _build_narrative(self) -> str:
        """
        Construit et retourne le texte narratif de fin de partie (rôles clés, première victime, vainqueur).

        :return: Paragraphe descriptif de la partie (str).
        """
        wolves = [p for p in self.players if is_wolf_player(p)]
        seer   = next((p for p in self.players if p["role"] == "Voyante"), None)
        witch  = next((p for p in self.players if p["role"] == "Sorcière"), None)
        hunter = next((p for p in self.players if p["role"] == "Chasseur"), None)
        lovers = [p for p in self.players if p.get("is_lover")]
        sniper = next((p for p in self.players if p["role"] == "Sniper"), None)

        lines = []
        wolf_names = [p["name"] for p in wolves]
        if len(wolf_names) == 1:
            lines.append(f"{wolf_names[0]} était le loup tapi dans l'ombre depuis le début.")
        elif len(wolf_names) > 1:
            lines.append(f"{', '.join(wolf_names)} formaient la meute secrète.")
        if seer:
            lines.append(f"{seer['name']} incarnait la Voyante, gardienne des secrets de la nuit.")
        if witch:
            lines.append(f"{witch['name']} détenait les potions de la Sorcière.")
        if hunter:
            lines.append(f"{hunter['name']} était le Chasseur, prêt à emporter un ennemi dans la mort.")
        if lovers and len(lovers) == 2:
            lines.append(f"{lovers[0]['name']} et {lovers[1]['name']} étaient les amoureux de Cupidon.")
        if sniper and self.sniper_target is not None:
            tgt = self.players[self.sniper_target]["name"]
            lines.append(f"{sniper['name']} était le Sniper, avec pour cible secrète {tgt}.")

        cause_txt = {
            "loup":     "dévoré par les loups",
            "poison":   "empoisonné par la Sorcière",
            "vote":     "chassé par le village",
            "chasseur": "emporté par le Chasseur",
            "feu":      "brûlé par le Pyromane",
        }
        if self.death_log:
            first = self.death_log[0]
            lines.append(
                f"Première victime : {first['name']} ({first['role']}), "
                f"{cause_txt.get(first['cause'], 'éliminé')} "
                f"lors de la nuit {first['round']}."
            )

        winner_texts = {
            "Village":  "Le village a triomphé et chassé la menace des ténèbres.",
            "Loups":    "Les loups ont semé la terreur et pris le contrôle du village.",
            "Amoureux": "Les amoureux ont survécu ensemble jusqu'à la fin.",
            "Sirène":   "La Sirène a envoûté tout le village.",
            "Pyromane": "Le Pyromane a tout réduit en cendres.",
            "Sniper":   "Le Sniper a accompli sa mission secrète.",
        }
        if self.winner in winner_texts:
            lines.append(winner_texts[self.winner])

        return "  ".join(lines)

    # ── Écran de fin détaillé ────────────────────────────────────────────────

    def _draw_end_screen(self):
        """Dessine l'écran de fin de partie : overlay, titre du vainqueur, cartes de rôles et narration."""
        w, h = self.screen.get_size()
        f = self.fonts()

        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((8, 4, 18, 215))
        self.screen.blit(overlay, (0, 0))

        winner_col_map = {
            "Loups":    WOLF_RED,
            "Village":  BTN_SUCCESS_H,
            "Amoureux": (220, 80, 140),
            "Sirène":   (20, 160, 220),
            "Pyromane": (220, 80, 20),
            "Sniper":   (80, 80, 80),
        }
        winner_col = winner_col_map.get(self.winner, BTN_SUCCESS_H)
        title_y = int(h * 0.09)
        draw_text(self.screen, f"Victoire du camp : {self.winner} !",
                  f["title"], winner_col,
                  center=(w // 2, title_y), shadow=True)
        draw_text(self.screen, "— Révélation des rôles —",
                  f["small"], GREY_DIM,
                  center=(w // 2, title_y + 52))

        n = len(self.players)
        cols = min(5, n)
        rows = math.ceil(n / cols)
        card_w = min(148, max(100, (w - 80) // cols - 10))
        card_h = 96
        grid_w = cols * (card_w + 8)
        grid_x = (w - grid_w) // 2
        grid_y = title_y + 82

        for i, p in enumerate(self.players):
            col_i = i % cols
            row_i = i // cols
            cx = grid_x + col_i * (card_w + 8)
            cy = grid_y + row_i * (card_h + 10)

            role = p["role"]
            camp = ROLE_CATALOG.get(role, {}).get("camp", "?")
            is_wf = is_wolf_player(p)
            is_solo = camp == "Solo"

            if is_wf:
                accent = WOLF_RED
            elif is_solo:
                accent = MIST_LIGHT
            else:
                accent = (50, 140, 200)

            card_surf = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
            r, g, b = accent
            fill_alpha = 55 if p["alive"] else 25
            card_surf.fill((r, g, b, fill_alpha))
            border_alpha = 200 if p["alive"] else 90
            pygame.draw.rect(card_surf, (r, g, b, border_alpha),
                             (0, 0, card_w, card_h), 2, border_radius=12)
            self.screen.blit(card_surf, (cx, cy))

            cx_center = cx + card_w // 2
            icon = ROLE_CATALOG.get(role, {}).get("ui_icon", role[:2].upper())
            badge = pygame.Rect(cx + card_w // 2 - 18, cy + 6, 36, 24)
            badge_surf = pygame.Surface((36, 24), pygame.SRCALPHA)
            badge_surf.fill((r, g, b, 180 if p["alive"] else 80))
            pygame.draw.rect(badge_surf, (r, g, b, 220), (0, 0, 36, 24), 1, border_radius=6)
            self.screen.blit(badge_surf, badge.topleft)
            draw_text(self.screen, icon, f["xs"], WHITE_SOFT, center=badge.center)

            name_col = WHITE_SOFT if p["alive"] else GREY_DIM
            draw_text(self.screen, p["name"], f["xs"], name_col,
                      center=(cx_center, cy + 38))

            # États spéciaux (sans révéler qui a effectué l'action)
            extra_icons = []
            if p.get("is_lover"):          extra_icons.append("<3")
            if p.get("maudit_converted"):   extra_icons.append("Devenu Loup")
            if p.get("wild_child_turned"):  extra_icons.append("Loup (mentor)")
            if p.get("infected"):           extra_icons.append("Infecté")
            if p.get("is_charmed"):         extra_icons.append("Envoûté")
            if p.get("is_fueled"):          extra_icons.append("Aspergé")
            draw_text(self.screen, role, f["xs"], accent,
                      center=(cx_center, cy + 56))
            extra_str = " · ".join(extra_icons[:2])
            if extra_str:
                draw_text(self.screen, extra_str, f["xs"], (220, 160, 60),
                          center=(cx_center, cy + 70))
                draw_text(self.screen, camp, f["xs"], GREY_DIM,
                          center=(cx_center, cy + 82))
            else:
                draw_text(self.screen, camp, f["xs"], GREY_DIM,
                          center=(cx_center, cy + 72))

            if not p["alive"]:
                dead_surf = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
                dead_surf.fill((0, 0, 0, 60))
                self.screen.blit(dead_surf, (cx, cy))
                draw_text(self.screen, "[x]", f["xs"], WOLF_RED,
                          center=(cx + card_w - 14, cy + 14))
            elif p["id"] == self.player_id:
                draw_text(self.screen, "MOI", f["xs"], GOLD_WARM,
                          center=(cx + card_w - 18, cy + 14))

        narr_y = grid_y + rows * (card_h + 10) + 14
        narr_h = max(60, h - narr_y - 90)
        narr_rect = pygame.Rect(40, narr_y, w - 80, narr_h)
        narr_surf = pygame.Surface((narr_rect.w, narr_rect.h), pygame.SRCALPHA)
        narr_surf.fill((20, 14, 40, 180))
        pygame.draw.rect(narr_surf, (80, 60, 130, 120),
                         (0, 0, narr_rect.w, narr_rect.h), 1, border_radius=10)
        self.screen.blit(narr_surf, narr_rect.topleft)

        narrative = self._build_narrative()
        chars_per_line = max(20, (narr_rect.w - 24) // 8)
        ny = narr_y + 8
        for line in wrap_text(narrative, chars_per_line):
            if ny + 16 > narr_y + narr_h - 6:
                break
            draw_text(self.screen, line, f["xs"], MOON_SILVER,
                      topleft=(narr_rect.x + 12, ny))
            ny += 16
        # Historique des exécutions par vote
        exec_hist = getattr(self, "execution_history", [])
        if exec_hist and ny + 20 < narr_y + narr_h - 6:
            ny += 4
            draw_text(self.screen, "Exécutés par le village :", f["xs"], GOLD_WARM,
                      topleft=(narr_rect.x + 12, ny))
            ny += 16
            for entry in exec_hist:
                if ny + 16 > narr_y + narr_h - 6:
                    break
                draw_text(self.screen,
                          f"  Jour {entry['jour']} : {entry['nom']} ({entry['role']})",
                          f["xs"], (180, 150, 90),
                          topleft=(narr_rect.x + 12, ny))
                ny += 16

        btn_w = 260
        btn_rect = (w // 2 - btn_w // 2, h - 72, btn_w, 48)
        self.btn_restart.set_rect(btn_rect)
        mouse = pygame.mouse.get_pos()
        self.btn_restart.draw(self.screen, f["small"], mouse)

    # ── Dessin ────────────────────────────────────────────────────────────────

    def _draw_background(self):
        """Dessine le fond animé de la scène (ciel jour/nuit, soleil ou lune, étoiles, arbres, particules)."""
        w, h = self.screen.get_size()
        is_day = (self.phase == "day")
        if is_day:
            draw_gradient_bg(self.screen, DAY_BG_TOP, DAY_BG_BOT)
            sx, sy = int(w * 0.82), int(h * 0.14)
            sr = int(min(w, h) * 0.06)
            for step in range(6):
                hr = sr + step * 5
                a  = max(0, 40 - step * 7)
                ss = pygame.Surface((hr * 2 + 4, hr * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(ss, (255, 230, 100, a), (hr + 2, hr + 2), hr)
                self.screen.blit(ss, (sx - hr - 2, sy - hr - 2))
            pygame.draw.circle(self.screen, (255, 240, 120), (sx, sy), sr)
            tree_col = (18, 48, 24)
        else:
            draw_gradient_bg(self.screen, NIGHT_BG_TOP, NIGHT_BG_BOT)
            draw_moon(self.screen, int(w * 0.84), int(h * 0.14),
                      int(min(w, h) * 0.065), self.t)
            for sx2, sy2, sz in [(int(w*.10), int(h*.08), 2), (int(w*.25), int(h*.05), 1),
                                  (int(w*.42), int(h*.12), 2), (int(w*.58), int(h*.06), 1)]:
                a  = int(150 + 60 * math.sin(self.t * 0.9 + sx2))
                ss = pygame.Surface((sz * 3, sz * 3), pygame.SRCALPHA)
                pygame.draw.circle(ss, (210, 215, 255, a), (sz + 1, sz + 1), max(1, sz))
                self.screen.blit(ss, (sx2 - sz - 1, sy2 - sz - 1))
            tree_col = (5, 4, 12)
        for xi, hi in [(0.0, 0.36), (0.08, 0.30), (0.17, 0.38), (0.55, 0.32),
                       (0.66, 0.40), (0.78, 0.34), (0.90, 0.36), (0.98, 0.30)]:
            draw_tree_silhouette(self.screen, int(xi * w), h, int(hi * h), tree_col)
        self.particles.update()
        self.particles.draw(self.screen)

    def _player_row(self, p: dict, rect: pygame.Rect, selected: bool):
        """
        Dessine la ligne d'un joueur dans la liste (badge de rôle, nom, icônes de statut, indicateur mort/vivant).

        :param p: Dictionnaire d'état du joueur (dict).
        :param rect: Rectangle de dessin sur la surface (pygame.Rect).
        :param selected: True si ce joueur est la cible sélectionnée (bool).
        """
        is_dead = not p["alive"]
        is_me   = (p["id"] == self.player_id)
        bg = (14, 10, 26) if is_dead else ((58, 36, 88) if selected else (26, 18, 46))
        pygame.draw.rect(self.screen, bg, rect, border_radius=14)
        bord = MIST_LIGHT if selected else (46, 38, 72)
        pygame.draw.rect(self.screen, bord, rect, 2, border_radius=14)

        f = self.fonts()
        my_role  = self.current_role()

        # Un joueur converti (Enfant sauvage ou Villageois Maudit) compte comme loup
        # → les autres loups peuvent voir son rôle
        p_is_wolf_side = is_wolf_player(p)
        reveal   = (is_dead or is_me
                    or (is_wolf_player(self.current_player()) and p_is_wolf_side)
                    or (self.current_player().get("is_lover")
                        and self.current_player().get("lover_id") == p["id"]))
        role_str = (p.get("revealed_role") or p.get("role") or "?") if reveal else "?"

        # Couleur du badge : rouge si converti côté loups, sinon couleur normale
        is_converted_wolf = (p.get("wild_child_turned") or p.get("maudit_converted"))
        if is_converted_wolf and not is_dead:
            badge_col = ROLE_WOLF_CLR  # Rouge loup
        else:
            badge_col = _role_badge_col(role_str)

        badge = pygame.Rect(rect.x + 9, rect.y + 9, 40, 30)
        pygame.draw.rect(self.screen, badge_col, badge, border_radius=10)
        # Icône emoji du catalogue ou 2 premières lettres si non disponible
        role_icon_disp = ROLE_CATALOG.get(role_str, {}).get("ui_icon", "") if role_str != "?" else "?"
        if not role_icon_disp:
            role_icon_disp = role_str[:2].upper() if role_str != "?" else "?"
        draw_text(self.screen, role_icon_disp, f["xs"], WHITE_SOFT, center=badge.center)

        # Icônes statut (envoûté, aspergé, amoureux)
        icon_x = rect.right - 20
        if p.get("is_charmed"):
            draw_text(self.screen, "(env)", f["xs"], (20, 160, 220),
                      center=(icon_x, rect.y + 10))
            icon_x -= 22
        if p.get("is_fueled"):
            draw_text(self.screen, "[feu]", f["xs"], (220, 80, 20),
                      center=(icon_x, rect.y + 10))
            icon_x -= 22
        # Coeur visible uniquement : soi-meme, son partenaire amoureux, Cupidon
        me = self.current_player()
        i_am_cupidon = (me.get("role") == "Cupidon")
        i_am_lover   = me.get("is_lover", False)
        can_see_lover_icon = (
            is_me
            or i_am_cupidon
            or (i_am_lover and me.get("lover_id") == p["id"])
        )
        if p.get("is_lover") and can_see_lover_icon:
            draw_text(self.screen, "<3", f["xs"], (220, 80, 120),
                      center=(icon_x, rect.y + 10))

        name_col = GREY_DARK if is_dead else (GOLD_WARM if is_me else WHITE_SOFT)
        draw_text(self.screen, p["name"], f["small"], name_col,
                  topleft=(rect.x + 58, rect.y + 5))

        if is_dead:
            draw_text(self.screen, "Éliminé — " + role_str, f["xs"], WOLF_RED,
                      topleft=(rect.x + 58, rect.y + 26))
        elif self.phase == "day" and p["id"] in self.day_votes:
            tgt_id   = self.day_votes[p["id"]]
            tgt_name = self.players[tgt_id]["name"] if tgt_id < len(self.players) else "?"
            draw_text(self.screen, f"▶ {tgt_name}", f["xs"], GOLD_PALE,
                      topleft=(rect.x + 58, rect.y + 26))
        else:
            info = role_str if reveal else "Rôle inconnu"
            draw_text(self.screen, info, f["xs"], CYAN_COOL,
                      topleft=(rect.x + 58, rect.y + 26))

        if selected:
            pygame.draw.circle(self.screen, GOLD_WARM, (rect.right - 16, rect.centery), 6)
        if is_me:
            draw_text(self.screen, "MOI", f["xs"], GOLD_WARM,
                      topleft=(rect.right - 38, rect.y + 5))

    def draw_player_list(self):
        """Dessine le panneau gauche listant tous les joueurs avec leur statut et rôle révélé."""
        f = self.fonts()
        draw_glass_panel(self.screen, self.left_rect, radius=22)
        draw_text(self.screen, "Joueurs", f["big"], MOON_SILVER,
                  topleft=(self.left_rect.x + 16, self.left_rect.y + 12), shadow=True)
        alive = sum(1 for p in self.players if p["alive"])
        draw_text(self.screen, f"{alive}/{len(self.players)} vivants",
                  f["xs"], GOLD_PALE,
                  topleft=(self.left_rect.x + 16, self.left_rect.y + 54))
        self.player_rects = []
        y = self.left_rect.y + 78
        data = serialize_players_for(self.player_id, self.players,
                                     reveal_all=(self.winner is not None))
        for p in data:
            row_h = 52
            rect  = pygame.Rect(self.left_rect.x + 10, y,
                                self.left_rect.width - 20, row_h)
            if y + row_h <= self.left_rect.bottom - 8:
                self._player_row(p, rect, p["id"] == self.selected_target
                                 or p["id"] in self.cupidon_selections
                                 or p["id"] in self.fox_selections)
            self.player_rects.append((p["id"], rect))
            y += row_h + 6

    def draw_info_panel(self):
        """Dessine le panneau droit avec phase, rôle du joueur, message, journal de nuit, chat et boutons d'action."""
        f  = self.fonts()
        is_day = (self.phase == "day")
        rw     = self.right_rect.width - 40

        panel = pygame.Surface((self.right_rect.width, self.right_rect.height), pygame.SRCALPHA)
        pcol  = (30, 50, 35, 205) if is_day else (22, 14, 38, 210)
        bcol  = (60, 100, 70, 160) if is_day else (90, 70, 130, 140)
        pygame.draw.rect(panel, pcol,
                         (0, 0, self.right_rect.width, self.right_rect.height), border_radius=22)
        pygame.draw.rect(panel, bcol,
                         (0, 0, self.right_rect.width, self.right_rect.height),
                         width=2, border_radius=22)
        self.screen.blit(panel, self.right_rect.topleft)

        phase_labels = {
            "night": (f"Nuit {self.day_count}", MOON_SILVER),
            "day":   (f"Jour {self.day_count}",  GOLD_WARM),
            "end":   ("Fin de partie",            WOLF_RED),
        }
        ph_text, ph_col = phase_labels.get(self.phase, (self.phase, WHITE_SOFT))
        draw_text(self.screen, ph_text, f["big"], ph_col,
                  topleft=(self.right_rect.x + 20, self.right_rect.y + 12), shadow=True)

        role = self.current_role()
        rb   = pygame.Rect(self.right_rect.x + 20, self.right_rect.y + 58, 160, 30)
        pygame.draw.rect(self.screen, _role_badge_col(role), rb, border_radius=14)
        role_icon_solo = ROLE_CATALOG.get(role, {}).get("ui_icon", "") or role[:2].upper()
        role_display_solo = f"{role_icon_solo}  {role}" if role_icon_solo != role[:2].upper() else role
        draw_text(self.screen, role_display_solo, f["xs"], WHITE_SOFT, center=rb.center)
        if self.is_animating:
            dots = "." * (int(self.t * 2.5) % 4)
            draw_text(self.screen, f"En cours{dots}", f["xs"], GREY_DIM,
                      topleft=(rb.right + 12, self.right_rect.y + 64))

        # Infos spéciales selon rôle
        y = self.right_rect.y + 102
        chat_reserve = 220

        def line(txt, col):
            nonlocal y
            if not txt:
                return
            for l in wrap_text(txt, max(20, rw // 9)):
                if y + 18 > self.right_rect.bottom - chat_reserve:
                    return
                draw_text(self.screen, l, f["xs"], col,
                          topleft=(self.right_rect.x + 20, y))
                y += 18
            y += 3

        line(self.message, WHITE_SOFT)

        # Sniper : afficher la cible
        if role == "Sniper" and self.sniper_target is not None:
            tgt_name = self.players[self.sniper_target]["name"]
            tgt_alive = self.players[self.sniper_target]["alive"]
            col = WOLF_RED if not tgt_alive else GOLD_PALE
            line(f"Votre cible : {tgt_name} ({'mort' if not tgt_alive else 'vivant'})", col)

        # Wild child : afficher le mentor
        if role == "Enfant sauvage":
            p = self.current_player()
            if p.get("wild_child_mentor") is not None:
                mid = p["wild_child_mentor"]
                mname = self.players[mid]["name"]
                malive = self.players[mid]["alive"]
                if p.get("wild_child_turned"):
                    line(f"Mentor {mname} est mort → vous êtes loup !", WOLF_RED)
                else:
                    col = GOLD_PALE if malive else WOLF_RED
                    line(f"Mentor : {mname} ({'vivant' if malive else 'mort'})", col)
            else:
                line("Choisissez votre mentor cette nuit.", GOLD_PALE)

        # Amoureux : afficher le partenaire
        if self.current_player().get("is_lover"):
            lid = self.current_player().get("lover_id")
            if lid is not None:
                lname = self.players[lid]["name"]
                lalive = self.players[lid]["alive"]
                col = (220, 80, 120) if lalive else WOLF_RED
                line(f"Amoureux de : {lname} ({'vivant' if lalive else 'mort'})", col)

        # Renard : résultat
        if self.fox_result:
            line(self.fox_result, CYAN_COOL)

        if self.action_hint:
            hint_col = WOLF_RED if self.hunter_pending else GOLD_PALE
            line(self.action_hint, hint_col)
        if self.seer_result:
            line(self.seer_result, CYAN_COOL)
        if self.last_deaths:
            line("Éliminés : " + ", ".join(self.last_deaths), WOLF_RED)

        if self.phase == "night" and self.night_log:
            sep_y = y + 4
            if sep_y < self.right_rect.bottom - chat_reserve:
                pygame.draw.line(self.screen, (60, 52, 90),
                                 (self.right_rect.x + 20, sep_y),
                                 (self.right_rect.right - 20, sep_y))
                y = sep_y + 10
            for msg in self.night_log[-6:]:
                if y + 17 > self.right_rect.bottom - chat_reserve:
                    break
                draw_text(self.screen, msg, f["xs"], MOON_SILVER,
                          topleft=(self.right_rect.x + 20, y))
                y += 17

        # Chat log
        chat_top = self.right_rect.bottom - 215
        chat_bot = self.right_rect.bottom - 68
        chat_h   = chat_bot - chat_top
        if chat_h > 20:
            pygame.draw.rect(self.screen, (14, 10, 28),
                             (self.right_rect.x + 10, chat_top,
                              self.right_rect.width - 20, chat_h),
                             border_radius=12)
            pygame.draw.rect(self.screen, (52, 40, 84),
                             (self.right_rect.x + 10, chat_top,
                              self.right_rect.width - 20, chat_h),
                             1, border_radius=12)
            draw_text(self.screen, "Discussion", f["xs"], GREY_DIM,
                      topleft=(self.right_rect.x + 16, chat_top + 4))
            line_h  = 34
            max_vis = max(1, (chat_h - 22) // line_h)
            visible = self.chat_log[-max_vis:]
            cy = chat_top + 20
            for entry in visible:
                if cy + line_h > chat_bot - 2:
                    break
                is_sys = (entry["author"] == "Système")
                a_col  = (200, 80, 80) if is_sys else (WOLF_RED if entry["wolf"] else GOLD_WARM)
                draw_text(self.screen, entry["author"] + ":", f["xs"], a_col,
                          topleft=(self.right_rect.x + 16, cy))
                max_c = max(10, (self.right_rect.width - 32) // 8)
                txt = entry["text"]
                if len(txt) > max_c:
                    txt = txt[:max_c - 2] + ".."
                draw_text(self.screen, txt, f["xs"], WHITE_SOFT,
                          topleft=(self.right_rect.x + 22, cy + 16))
                cy += line_h

        # Boutons
        mouse = pygame.mouse.get_pos()
        if self.hunter_pending:
            can_act = self.selected_target is not None
            self.btn_hunter.draw(self.screen, f["small"], mouse, enabled=can_act)
        elif self.father_pending:
            # Père des Loups : bouton INFECTER (valider sans sélection) + PASSER
            wolf_tgt = self.pending_night.get("wolf_target")
            can_infect = (wolf_tgt is not None and not self.father_infect_used)
            self.btn_vote.text = "INFECTER"
            self.btn_vote.draw(self.screen, f["small"], mouse, enabled=can_infect)
            self.btn_skip.draw(self.screen, f["small"], mouse, enabled=True)
        elif self.cupidon_pending:
            n_sel = len(self.cupidon_selections)
            can_confirm = n_sel >= 2
            self.btn_confirm.text = f"CONFIRMER LE COUPLE ({n_sel}/2)"
            self.btn_confirm.draw(self.screen, f["small"], mouse, enabled=can_confirm)
        elif self.fox_pending:
            n_sel = len(self.fox_selections)
            can_confirm = n_sel >= 3
            self.btn_confirm.text = f"CONFIRMER ({n_sel}/3)"
            self.btn_confirm.draw(self.screen, f["small"], mouse, enabled=can_confirm)
            self.btn_skip.draw(self.screen, f["small"], mouse, enabled=True)
        else:
            can_act = self.human_can_act() and self.selected_target is not None
            if self.phase == "night" and role == "Pyromane":
                can_ignite = bool(self.fueled_players)
                self.btn_vote.text = "ASPERGER"
                self.btn_vote.draw(self.screen, f["small"], mouse, enabled=can_act)
                self.btn_ignite.draw(self.screen, f["small"], mouse, enabled=can_ignite and self.human_can_act())
            elif self.phase == "night" and role == "Sorcière":
                wolf_tgt = self.pending_night.get("wolf_target")
                if wolf_tgt is not None and not self.witch_heal_used:
                    self.btn_save.draw(self.screen, f["small"], mouse,
                                       enabled=self.human_can_act())
                    self.btn_vote.text = "EMPOISONNER"
                    self.btn_vote.draw(self.screen, f["small"], mouse, enabled=can_act)
                else:
                    self.btn_vote.text = "EMPOISONNER"
                    self.btn_vote.draw(self.screen, f["small"], mouse, enabled=can_act)
                    self.btn_skip.draw(self.screen, f["small"], mouse,
                                       enabled=self.human_can_act())
            elif self.phase == "night" and role in ("Sirène", "Salvateur", "Renard"):
                self.btn_vote.text = "VALIDER"
                self.btn_vote.draw(self.screen, f["small"], mouse, enabled=can_act)
                self.btn_skip.draw(self.screen, f["small"], mouse, enabled=self.human_can_act())
            else:
                self.btn_vote.text = "VALIDER MON VOTE" if self.phase == "day" else "VALIDER"
                self.btn_vote.draw(self.screen, f["small"], mouse, enabled=can_act)

    def draw(self):
        """Orchestre le dessin complet de la frame : fond, barre de titre, liste des joueurs et panneau d'info."""
        self._draw_background()
        f = self.fonts()
        draw_glass_panel(self.screen, self.top_rect, radius=18)
        draw_text(self.screen, "LOUP-GAROU  —  MODE SOLO",
                  f["title"], MOON_SILVER,
                  center=(self.top_rect.centerx, self.top_rect.centery), shadow=True)

        if self.phase == "end":
            self._draw_end_screen()
        else:
            self.draw_player_list()
            self.draw_info_panel()
            if self.cupidon_pending:
                hint = f"Cupidon : clique sur 2 joueurs ({len(self.cupidon_selections)}/2 sélectionnés)"
            elif self.fox_pending:
                hint = f"Renard : clique sur 3 joueurs ({len(self.fox_selections)}/3 sélectionnés)"
            elif self.hunter_pending:
                hint = "Chasseur : choisis ta cible puis clique EMPORTER"
            elif self.is_animating:
                hint = "En attente des IA..."
            else:
                hint = "Clique sur un joueur vivant pour le cibler"
            draw_text(self.screen, hint, f["xs"], GREY_DIM,
                      center=self.bottom_rect.center)

    # ── Événements ───────────────────────────────────────────────────────────

    def handle_event(self, event):
        """
        Traite un événement Pygame (redimensionnement, clic souris) et dispatche vers les actions appropriées.

        :param event: Événement Pygame à traiter (pygame.event.Event).
        """
        if event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode(
                (max(MIN_W, event.w), max(MIN_H, event.h)), pygame.RESIZABLE)
            self.compute_layout()
            return
        if event.type != pygame.MOUSEBUTTONDOWN:
            return

        for pid, rect in self.player_rects:
            if rect.collidepoint(event.pos):
                is_alive = self.players[pid]["alive"]
                is_me    = (pid == self.player_id)

                # Cupidon : peut sélectionner n'importe qui dont soi-même
                if self.cupidon_pending and is_alive:
                    if pid not in self.cupidon_selections and len(self.cupidon_selections) < 2:
                        self.cupidon_selections.append(pid)
                        n = len(self.cupidon_selections)
                        self.action_hint = (f"Cupidon : ({n}/2 sélectionnés)")
                    return

                # Fox : peut sélectionner n'importe qui sauf soi
                if self.fox_pending and is_alive and not is_me:
                    if pid not in self.fox_selections and len(self.fox_selections) < 3:
                        self.fox_selections.append(pid)
                        n = len(self.fox_selections)
                        self.action_hint = (f"Renard : ({n}/3 sélectionnés)")
                    return

                can_click = (not is_me and is_alive
                             and (not self.is_animating
                                  or self.hunter_pending
                                  or self.cupidon_pending
                                  or self.fox_pending))
                if can_click:
                    self.selected_target = pid
                return

        if self.phase == "end":
            if self.btn_restart.is_clicked(event.pos):
                self.setup_game()
            return

        if self.hunter_pending:
            if self.btn_hunter.is_clicked(event.pos):
                self.apply_human_action()
            return

        if self.father_pending:
            if self.btn_vote.is_clicked(event.pos):
                self.apply_human_action()
            elif self.btn_skip.is_clicked(event.pos):
                self.skip_action()
            return

        if self.cupidon_pending:
            if self.btn_confirm.is_clicked(event.pos):
                self.apply_human_action()
            return

        if self.fox_pending:
            if self.btn_confirm.is_clicked(event.pos):
                self.apply_human_action()
            elif self.btn_skip.is_clicked(event.pos):
                self.skip_action()
            return

        if not self.is_animating:
            role = self.current_role()
            if self.phase == "night" and role == "Pyromane":
                if self.btn_vote.is_clicked(event.pos):
                    self.apply_human_action()
                elif self.btn_ignite.is_clicked(event.pos):
                    self.ignite_fire()
            elif self.phase == "night" and role == "Sorcière":
                if self.btn_save.is_clicked(event.pos):
                    self.save_victim()
                elif self.btn_vote.is_clicked(event.pos):
                    self.apply_human_action()
                elif self.btn_skip.is_clicked(event.pos):
                    self.skip_action()
            elif self.phase == "night" and role in ("Sirène", "Salvateur"):
                if self.btn_vote.is_clicked(event.pos):
                    self.apply_human_action()
                elif self.btn_skip.is_clicked(event.pos):
                    self.skip_action()
            elif self.phase == "night" and role == "Renard" and not self.fox_pending:
                if self.btn_skip.is_clicked(event.pos):
                    self.skip_action()
                elif self.btn_vote.is_clicked(event.pos):
                    self.apply_human_action()
            else:
                if self.btn_vote.is_clicked(event.pos):
                    self.apply_human_action()

    # ── Boucle principale ────────────────────────────────────────────────────

    def run(self):
        """Boucle principale : met à jour la logique, traite les événements et dessine chaque frame."""
        while self.running:
            dt = self.clock.tick(FPS)
            self.t += dt * 0.001
            self.update(float(dt))
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                else:
                    self.handle_event(event)
            self.draw()
            pygame.display.flip()
        pygame.display.quit()

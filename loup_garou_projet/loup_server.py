"""
loup_server.py – Serveur TCP multithreadé pour le mode en ligne.
Protocole : messages JSON terminés par '\n', un message par ligne.
"""
import json
import random
import socket
import threading
import time
from collections import Counter
from pathlib import Path

from chat_moderation import ChatModerator
from loup_shared import (
    MIN_PLAYERS, MAX_PLAYERS, NIGHT_ORDER,
    build_roles, check_winner, is_wolf_player,
    normalize_role_config, role_config_label,
    serialize_players_for, min_players_for_config, role_config_error,
)
from server_discovery import ServerBroadcaster, get_local_ip

HOST = "0.0.0.0"
PORT = 5555
BASE_DIR = Path(__file__).resolve().parent
MODERATION_CSV = BASE_DIR / "moderation_loup_garou_fr_en.csv"


class WerewolfServer:
    def __init__(self, host_name="Joueur", host=HOST, port=PORT,
                 max_players=MAX_PLAYERS, role_config=None,
                 ready_event: threading.Event = None):
        """
        Initialise le serveur TCP : socket, verrou, broadcaster UDP, modérateur de chat et état du lobby.

        :param host_name: Nom du joueur hôte, utilisé pour nommer le salon (str).
        :param host: Adresse d'écoute TCP (str), '0.0.0.0' par défaut.
        :param port: Port TCP d'écoute (int), 5555 par défaut.
        :param max_players: Nombre maximum de joueurs acceptés (int).
        :param role_config: Configuration des rôles {nom_rôle: quantité} (dict ou None).
        :param ready_event: Événement à déclencher quand le serveur est prêt à accepter des connexions (threading.Event ou None).
        """
        self.host = host
        self.port = port
        self.server_name = f"Salon de {host_name}"
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lock = threading.Lock()
        self.running = True
        self.bind_ok = False
        self.ready_event = ready_event
        self.host_ip = get_local_ip()
        self.max_players = max(MIN_PLAYERS, min(MAX_PLAYERS, int(max_players)))
        self.role_config = normalize_role_config(role_config)
        self.broadcaster = ServerBroadcaster(self.server_name,
                                             host_ip=self.host_ip,
                                             game_port=self.port)
        self.broadcaster.set_room_config(self.max_players, role_config_label(self.role_config))
        self.clients: list = []
        self.chat_history: list = []
        self.moderator = ChatModerator(MODERATION_CSV)
        self._dawn_timer: threading.Timer = None
        self._dawn_start: float = None
        self.reset_lobby_state()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def reset_lobby_state(self):
        """Réinitialise tous les états de partie (joueurs, votes, phases, rôles spéciaux) pour un nouveau lobby."""
        self.players: list = []
        self.host_id = 0
        self.game_started = False
        self.phase = "lobby"
        self._cancel_dawn_timer()
        self.day_count = 0
        self.winner = None
        self.message = f"En attente des joueurs. Minimum : {MIN_PLAYERS}."
        self.last_deaths: list = []
        self.pending_night: dict = {}
        self.wolf_votes: dict = {}
        self.day_votes: dict = {}
        # Sorcière
        self.witch_heal_used = False
        self.witch_poison_used = False
        # Père des Loups
        self.father_infect_used = False
        self.pending_wolf_target = None
        # Nuit : étape courante
        self.night_step = "wolves"
        # Cupidon / Enfant sauvage (nuit 1)
        self.cupidon_done = False
        self.wild_child_done = False
        # Salvateur
        self.salvateur_last_protected = None
        # Renard
        self.fox_power_active = True
        # Sniper
        self.sniper_target = None
        # Amoureux
        self.lovers: list = []
        # Sirène
        self.charmed_players: list = []
        # Pyromane
        self.fueled_players: list = []
        # Chasseur en attente (queue, FIFO)
        self.pending_hunter_queue: list = []
        # Historique des exécutions (votes du village) et morts par jour
        self.execution_history: list = []  # [{jour, nom, role}]
        self.last_deaths_with_roles: list = []  # [{nom, role}] pour l'aube
        self.daily_deaths: dict = {}        # {jour: [nom, ...]}
        # Rôles initiaux (sauvegardés au début de partie)
        self.initial_roles: dict = {}       # {player_id: role}

    def _ensure_slot(self, player_id: int):
        """
        S'assure que la liste self.clients est assez longue pour contenir l'indice player_id.

        :param player_id: Indice du joueur à garantir (int).
        """
        while len(self.clients) <= player_id:
            self.clients.append(None)

    def connected_player_count(self) -> int:
        """
        Retourne le nombre de connexions TCP actives.

        :return: int
        """
        return sum(1 for c in self.clients if c is not None)

    def send_json(self, conn, data: dict):
        """
        Sérialise data en JSON et l'envoie sur la connexion TCP (terminé par '\\n').

        :param conn: Socket client TCP (socket.socket).
        :param data: Dictionnaire à envoyer (dict).
        """
        try:
            conn.sendall((json.dumps(data) + "\n").encode("utf-8"))
        except OSError:
            pass

    def append_chat(self, author: str, message: str, system: bool = False,
                    wolf_only: bool = False, dead_only: bool = False):
        """
        Ajoute un message au chat et conserve les 80 derniers messages.

        :param author: Nom de l'auteur du message (str).
        :param message: Contenu du message, tronqué à 220 caractères (str).
        :param system: True si le message est un message système (bool).
        :param wolf_only: True si le message est visible uniquement par les loups (bool).
        :param dead_only: True si le message est visible uniquement par les joueurs morts (bool).
        """
        entry = {"author": author, "message": message[:220], "system": system,
                 "wolf_only": wolf_only, "dead_only": dead_only}
        self.chat_history.append(entry)
        self.chat_history = self.chat_history[-80:]

    DAWN_DURATION = 10  # secondes avant passage automatique au jour

    def _cancel_dawn_timer(self):
        """Annule le timer d'aube en cours s'il existe."""
        timer = getattr(self, "_dawn_timer", None)
        if timer is not None:
            timer.cancel()
        self._dawn_timer = None
        self._dawn_start = None

    def _start_dawn_timer(self):
        """Lance un timer de DAWN_DURATION secondes puis passe au jour automatiquement."""
        self._cancel_dawn_timer()
        self._dawn_start = time.monotonic()
        self._dawn_timer = threading.Timer(self.DAWN_DURATION, self._auto_dawn_advance)
        self._dawn_timer.daemon = True
        self._dawn_timer.start()

    def _auto_dawn_advance(self):
        """Callback du timer : passe au jour depuis l'aube (thread-safe via le lock)."""
        with self.lock:
            if self.phase != "dawn":
                return
            self._dawn_timer = None
            # Réutilise start_day_from_dawn en tant qu'hôte interne
            self._do_dawn_advance()

    def _do_dawn_advance(self):
        """Logique interne de passage aube→jour (sans vérification hôte ni phase)."""
        if self.pending_hunter_queue:
            hunter_id = self.pending_hunter_queue[0]
            if self.players[hunter_id].get("connected"):
                self.phase = "hunter_day"
                self.message = (f"{self.players[hunter_id]['name']} (Chasseur) a été éliminé cette nuit ! "
                                f"Il doit choisir un joueur à emporter avec lui !")
                self.broadcast_snapshots()
                return
            else:
                self._auto_hunter_shoot(hunter_id)
                self.pending_hunter_queue.pop(0)

        self.winner = check_winner(self.players)
        if self.winner is not None:
            self.phase   = "end"
            self.message = f"Victoire du camp : {self.winner} !"
        else:
            self.phase   = "day"
            self.message = ("Jour : " + ", ".join(self.last_deaths) + " éliminé(s) cette nuit. Votez."
                            if self.last_deaths else "Jour : personne n'est mort cette nuit. Votez.")
        self.broadcast_snapshots()

    def broadcast_snapshots(self):
        """Envoie le snapshot d'état personnalisé à chaque joueur connecté."""
        for player in self.players:
            pid = player["id"]
            if pid >= len(self.clients):
                continue
            conn = self.clients[pid]
            if conn is None or not player.get("connected"):
                continue
            try:
                self.send_json(conn, self.player_snapshot(pid))
            except OSError:
                pass

    # ── Snapshots ────────────────────────────────────────────────────────────

    def player_snapshot(self, player_id: int) -> dict:
        """
        Construit et retourne le snapshot complet de l'état du jeu du point de vue du joueur donné.

        :param player_id: Indice du joueur destinataire (int).
        :return: dict contenant toutes les informations de phase, rôles, actions possibles et chat.
        """
        player = self.players[player_id]
        alive_players = [p for p in self.players if p["alive"]]
        wolves_alive  = [p for p in alive_players if is_wolf_player(p)]
        current_role  = player["role"] if self.game_started else None
        is_wolf = is_wolf_player(player) if self.game_started else False
        can_act = False
        action_hint = ""
        father_can_infect = False
        night_targets_needed = 1  # 1 = single, 2 = cupidon, 3 = fox

        # Chasseur en attente
        is_hunter_turn = (bool(self.pending_hunter_queue)
                          and self.pending_hunter_queue[0] == player_id
                          and self.phase in ("night", "day", "hunter_day", "dawn"))
        if is_hunter_turn and player["alive"] is False:
            can_act = True
            action_hint = "Vous avez été éliminé ! Désignez un joueur à emporter avec vous."

        elif self.phase == "night" and player["alive"] and not is_hunter_turn:
            if is_wolf_player(player) and self.night_step == "wolves":
                can_act = True
                wolves = [p for p in self.players if p.get("connected") and p["alive"] and is_wolf_player(p)]
                if player_id in self.wolf_votes and len(wolves) > 1:
                    action_hint = "Vote enregistré. En attente des autres loups..."
                else:
                    action_hint = "Choisissez une victime parmi les joueurs vivants."

            elif current_role == "Cupidon" and self.night_step == "cupidon" and not self.cupidon_done:
                can_act = True
                night_targets_needed = 2
                action_hint = "Choisissez 2 joueurs qui tomberont amoureux (cliquez sur 2 joueurs puis validez)."

            elif current_role == "Enfant sauvage" and self.night_step == "wild_child" and not self.wild_child_done:
                can_act = True
                action_hint = "Choisissez votre mentor : si il meurt, vous deviendrez loup."

            elif current_role == "Voyante" and self.night_step == "seer" and not self.pending_night.get("seer_done", False):
                can_act = True
                action_hint = "Choisissez un joueur pour découvrir son rôle."

            elif current_role == "Infect Père des Loups" and self.night_step == "father":
                if not self.pending_night.get("father_done", False):
                    can_act = True
                    father_can_infect = not self.father_infect_used
                    if self.pending_wolf_target is not None:
                        tgt_name = self.players[self.pending_wolf_target]["name"]
                        action_hint = (f"Infectez {tgt_name} ou passez votre tour."
                                       if father_can_infect
                                       else "Pouvoir d'infection déjà utilisé. Passez.")
                    else:
                        action_hint = "Aucune victime à infecter. Passez votre tour."

            elif current_role == "Sorcière" and self.night_step == "witch":
                if not self.pending_night.get("witch_done", False):
                    can_act = True
                    heal_ok   = not self.witch_heal_used
                    poison_ok = not self.witch_poison_used
                    parts = []
                    if heal_ok:
                        parts.append("sauver la victime")
                    if poison_ok:
                        parts.append("empoisonner un joueur")
                    action_hint = ("Vous pouvez " + " ou ".join(parts) + "."
                                   if parts else "Passez votre tour.")

            elif current_role == "Salvateur" and self.night_step == "salvateur":
                if not self.pending_night.get("salvateur_done", False):
                    can_act = True
                    last_name = (self.players[self.salvateur_last_protected]["name"]
                                 if self.salvateur_last_protected is not None
                                 and self.salvateur_last_protected < len(self.players)
                                 else "personne")
                    action_hint = (f"Protégez un joueur cette nuit. Interdit : {last_name} (nuit précédente).")

            elif current_role == "Renard" and self.night_step == "fox":
                if not self.pending_night.get("fox_done", False) and self.fox_power_active:
                    can_act = True
                    night_targets_needed = 3
                    action_hint = "Choisissez 3 joueurs : vous saurez s'il y a un loup parmi eux."

            elif current_role == "Sirène" and self.night_step == "siren":
                if not self.pending_night.get("siren_done", False):
                    can_act = True
                    already = [self.players[i]["name"] for i in self.charmed_players
                                if i < len(self.players)]
                    already_str = ", ".join(already) if already else "personne"
                    action_hint = f"Envoûtez un joueur ou passez. Déjà envoûtés : {already_str}."

            elif current_role == "Pyromane" and self.night_step == "arsonist":
                if not self.pending_night.get("arsonist_done", False):
                    can_act = True
                    fueled_names = [self.players[i]["name"] for i in self.fueled_players
                                    if i < len(self.players)]
                    if fueled_names:
                        action_hint = (f"Aspergez un joueur OU mettez le feu "
                                       f"(aspergés : {', '.join(fueled_names)}).")
                    else:
                        action_hint = "Aspergez un joueur d'essence."

            else:
                step_labels = {
                    "cupidon":    "de Cupidon",
                    "wild_child": "de l'Enfant sauvage",
                    "seer":       "de la Voyante",
                    "wolves":     "des Loups-garous",
                    "father":     "du Père des Loups",
                    "witch":      "de la Sorcière",
                    "salvateur":  "du Salvateur",
                    "fox":        "du Renard",
                    "siren":      "de la Sirène",
                    "arsonist":   "du Pyromane",
                }
                label = step_labels.get(self.night_step, "")
                if label:
                    action_hint = f"En attente du tour {label}..."

        elif self.phase == "day" and player["alive"] and not is_hunter_turn:
            can_act = True
            action_hint = "Votez contre un joueur que vous suspectez."

        # Nom de la victime des loups (partagé avec sorcière et père)
        night_target_name = None
        if (self.pending_wolf_target is not None
                and current_role in ("Sorcière", "Infect Père des Loups")
                and self.pending_wolf_target < len(self.players)):
            night_target_name = self.players[self.pending_wolf_target]["name"]

        witch_heal_available   = (current_role == "Sorcière" and not self.witch_heal_used)
        witch_poison_available = (current_role == "Sorcière" and not self.witch_poison_used)
        # La sorcière ne peut pas sauver si le père des loups a infecté cette nuit
        witch_save_blocked = (current_role == "Sorcière"
                              and self.pending_night.get("infected_target") is not None)

        # Chat : logique de permission d'écriture et de visibilité
        is_dead = not player["alive"]
        if is_dead:
            # Les morts peuvent écrire, mais leurs messages sont marqués dead_only
            can_chat = True
        elif self.phase == "night" and self.game_started:
            # La nuit seuls les loups (et infectés) peuvent écrire
            can_chat = is_wolf
        else:
            can_chat = True

        # Visibilité du chat :
        # - Loups : voient tout (y compris wolf_only)
        # - Morts : voient le chat normal + les messages dead_only
        # - Vivants : voient uniquement les messages non wolf_only et non dead_only
        if is_wolf:
            visible_chat = list(self.chat_history)
        elif is_dead:
            visible_chat = [e for e in self.chat_history
                            if not e.get("wolf_only")]
        else:
            visible_chat = [e for e in self.chat_history
                            if not e.get("wolf_only") and not e.get("dead_only")]

        has_voted = (player_id in self.day_votes) if self.phase == "day" else False

        # Infos spécifiques selon rôle
        sniper_target_name = None
        if current_role == "Sniper" and self.sniper_target is not None:
            sniper_target_name = self.players[self.sniper_target]["name"]

        fox_result = self.pending_night.get(f"fox_result_{player_id}")

        # Message d'amoureux : visible uniquement par les deux amoureux et Cupidon
        lovers_msg = None
        lovers_ids = self.pending_night.get("lovers_ids", [])
        if (self.pending_night.get("lovers_msg")
                and (player_id in lovers_ids or current_role == "Cupidon")):
            lovers_msg = self.pending_night["lovers_msg"]

        # Votes des loups : visible uniquement par les loups (affiche qui a voté pour qui)
        wolf_votes_visible = {}
        if is_wolf:
            for voter_id, tgt_id in self.wolf_votes.items():
                if voter_id < len(self.players) and tgt_id < len(self.players):
                    wolf_votes_visible[self.players[voter_id]["name"]] = self.players[tgt_id]["name"]

        # Votes du jour : visibles par tous les joueurs vivants
        day_votes_visible = {}
        for voter_id, tgt_id in self.day_votes.items():
            if voter_id < len(self.players) and tgt_id < len(self.players):
                day_votes_visible[self.players[voter_id]["name"]] = self.players[tgt_id]["name"]

        lover_partner_name = None
        if player.get("is_lover") and player.get("lover_id") is not None:
            lid = player["lover_id"]
            if lid < len(self.players):
                lover_partner_name = self.players[lid]["name"]

        mentor_name = None
        if current_role == "Enfant sauvage" and player.get("wild_child_mentor") is not None:
            mid = player["wild_child_mentor"]
            if mid < len(self.players):
                mentor_name = self.players[mid]["name"]

        charmed_list = [self.players[i]["name"] for i in self.charmed_players
                        if i < len(self.players)]
        fueled_list  = [self.players[i]["name"] for i in self.fueled_players
                        if i < len(self.players)]

        # Sirène : seule elle peut voir la liste complète des envoûtés.
        # Un joueur envoûté sait uniquement qu'il l'est lui-même, pas qui sont les autres.
        if current_role == "Sirène":
            charmed_list_visible = charmed_list  # La Sirène voit tout
        elif player_id in self.charmed_players:
            charmed_list_visible = ["(vous êtes envoûté)"]  # Sait seulement son propre état
        else:
            charmed_list_visible = []  # Les autres ne savent rien

        # Pyromane : seul lui voit la liste des aspergés
        if current_role == "Pyromane":
            fueled_list_visible = fueled_list
        else:
            fueled_list_visible = []  # Les autres ne savent pas qui est aspergé
        salvateur_last_name = None  # Initialisé à None par défaut
        if current_role == "Salvateur" and self.salvateur_last_protected is not None:
            if self.salvateur_last_protected < len(self.players):
                salvateur_last_name = self.players[self.salvateur_last_protected]["name"]

        return {
            "type":                   "state_sync",
            "server_name":            self.server_name,
            "phase":                  self.phase,
            "day_count":              self.day_count,
            "your_id":                player_id,
            "host_id":                self.host_id,
            "players":                serialize_players_for(player_id, self.players,
                                                            reveal_all=(self.winner is not None),
                                                            hide_night_deaths=(self.phase == "night")),
            "game_started":           self.game_started,
            "winner":                 self.winner,
            "message":                self.message,
            "last_deaths":            list(self.last_deaths),
            "night_target_name":      night_target_name,
            "can_act":                can_act,
            "action_hint":            action_hint,
            "father_can_infect":      father_can_infect,
            "seer_result":            self.pending_night.get(f"seer_result_{player_id}"),
            "fox_result":             fox_result,
            "wolf_count":             len(wolves_alive),
            "connected_count":        self.connected_player_count(),
            "max_players":            self.max_players,
            "role_config":            self.role_config,
            "chat_history":           visible_chat,
            "witch_heal_available":   witch_heal_available,
            "witch_poison_available": witch_poison_available,
            "witch_save_blocked":     witch_save_blocked,
            "can_chat":               can_chat,
            "has_voted":              has_voted,
            "votes_cast":             len(self.day_votes),
            "votes_needed":           len([p for p in self.players if p.get("connected") and p["alive"]]),
            "night_step":             self.night_step,
            "night_targets_needed":   night_targets_needed,
            "is_hunter_turn":         is_hunter_turn,
            "sniper_target_name":     sniper_target_name,
            "fox_power_active":       self.fox_power_active,
            "dawn_remaining":         (max(0, round(self.DAWN_DURATION - (time.monotonic() - self._dawn_start)))
                                       if self.phase == "dawn" and self._dawn_start is not None else None),
            "lover_partner_name":     lover_partner_name,
            "mentor_name":            mentor_name,
            "charmed_list":           charmed_list_visible,
            "fueled_list":            fueled_list_visible,
            "salvateur_last_name":    salvateur_last_name,
            "lovers_msg":             lovers_msg,
            "wolf_votes_visible":     wolf_votes_visible,
            "day_votes_visible":      day_votes_visible,
            "execution_history":      list(self.execution_history),
            "daily_deaths":           {str(k): list(v) for k, v in self.daily_deaths.items()},
            "initial_roles":          dict(self.initial_roles),
            "last_deaths_with_roles": list(getattr(self, "last_deaths_with_roles", [])),
        }

    # ── Gestion des connexions ────────────────────────────────────────────────

    def handle_restart_game(self, player_id: int):
        """
        Remet le serveur en phase lobby (nouvelle partie) sans fermer les connexions TCP.
        Les joueurs déjà connectés sont réinscrits automatiquement via reset_lobby_state +
        re-broadcast, puis chaque client en phase « end » reçoit un snapshot indiquant
        phase='lobby' et peut retourner dans le salon sans se reconnecter.

        :param player_id: Indice du joueur qui demande le redémarrage (int).
        :return: Snapshot d'état pour le demandeur (dict).
        """
        # Seul l'hôte peut relancer une partie
        if player_id != self.host_id:
            return {"type": "error", "message": "Seul l'hôte peut relancer une partie."}
        # Mémoriser les noms des joueurs actuellement connectés avant reset
        connected_names = {
            p["id"]: p["name"]
            for p in self.players
            if p.get("connected") and p["id"] < len(self.clients) and self.clients[p["id"]] is not None
        }
        self.reset_lobby_state()
        # Ré-enregistrer chaque joueur encore connecté dans le nouveau lobby
        for pid, name in connected_names.items():
            while len(self.players) <= pid:
                self.players.append({
                    "id":            len(self.players),
                    "name":          f"Joueur {len(self.players) + 1}",
                    "role":          None,
                    "alive":         True,
                    "connected":     False,
                    "revealed_role": None,
                })
            self.players[pid].update({"name": name, "connected": True, "alive": True})
            if self.host_id == 0:
                self.host_id = pid  # premier connecté = hôte
        self.message = "Nouvelle partie ! En attente des joueurs."
        self.append_chat("Systeme", self.message, system=True)
        self.broadcast_snapshots()
        return self.player_snapshot(player_id)

    def remove_client(self, player_id: int):
        """
        Déconnecte un joueur : ferme son slot, le marque mort/déconnecté et diffuse les snapshots.

        :param player_id: Indice du joueur à déconnecter (int).
        """
        if player_id < len(self.clients):
            self.clients[player_id] = None
        if player_id < len(self.players):
            self.players[player_id]["alive"]     = False
            self.players[player_id]["connected"] = False
            self.append_chat("Systeme",
                             f"{self.players[player_id]['name']} a quitte la partie.",
                             system=True)
        self.broadcaster.set_player_count(self.connected_player_count())
        self.message = "Un joueur s'est deconnecte."
        self.winner = check_winner(self.players) if self.game_started else None
        self.broadcast_snapshots()

    # ── Handlers messages ────────────────────────────────────────────────────

    def handle_join(self, player_id: int, msg: dict):
        """
        Enregistre le joueur dans le lobby et diffuse la mise à jour à tous.

        :param player_id: Indice du joueur qui rejoint (int).
        :param msg: Message JSON reçu, avec la clé 'name' (dict).
        :return: Snapshot d'état pour le joueur (dict).
        """
        name = str(msg.get("name", "")).strip()[:20] or f"Joueur {player_id + 1}"
        while len(self.players) <= player_id:
            self.players.append({
                "id":            len(self.players),
                "name":          f"Joueur {len(self.players) + 1}",
                "role":          None,
                "alive":         True,
                "connected":     False,
                "revealed_role": None,
            })
        self.players[player_id].update({"name": name, "connected": True, "alive": True})
        self.message = f"{name} a rejoint la partie."
        self.append_chat("Systeme", self.message, system=True)
        self.broadcaster.set_player_count(self.connected_player_count())
        self.broadcast_snapshots()
        return self.player_snapshot(player_id)

    def update_role_config(self, player_id: int, msg: dict):
        """
        Met à jour la configuration des rôles du lobby si le demandeur est l'hôte.

        :param player_id: Indice du joueur demandant la modification (int).
        :param msg: Message JSON avec la clé 'role_config' (dict).
        :return: Snapshot d'état ou dict d'erreur (dict).
        """
        if player_id != self.host_id:
            return {"type": "error", "message": "Seul l'hote peut modifier les roles."}
        if self.game_started or self.phase != "lobby":
            return {"type": "error", "message": "Modification impossible en cours de partie."}
        new_config = normalize_role_config(msg.get("role_config", {}))
        required = min_players_for_config(new_config)
        if required > MAX_PLAYERS:
            return {"type": "error", "message": f"Configuration impossible : max {MAX_PLAYERS} joueurs."}
        self.role_config = new_config
        if self.max_players < required:
            self.max_players = required
        self.broadcaster.set_room_config(self.max_players, role_config_label(self.role_config))
        self.message = "Configuration des roles mise a jour."
        self.broadcast_snapshots()
        return self.player_snapshot(player_id)

    def update_max_players(self, player_id: int, msg: dict):
        """
        Modifie le nombre maximum de joueurs du salon si le demandeur est l'hôte.

        :param player_id: Indice du joueur demandant la modification (int).
        :param msg: Message JSON avec la clé 'max_players' (dict).
        :return: Snapshot d'état ou dict d'erreur (dict).
        """
        if player_id != self.host_id:
            return {"type": "error", "message": "Seul l'hote peut modifier le nombre de joueurs."}
        if self.game_started or self.phase != "lobby":
            return {"type": "error", "message": "Modification impossible en cours de partie."}
        requested = int(msg.get("max_players", self.max_players))
        requested = max(MIN_PLAYERS, min(MAX_PLAYERS, requested))
        requested = max(requested, self.connected_player_count(),
                        min_players_for_config(self.role_config))
        self.max_players = requested
        self.broadcaster.set_room_config(self.max_players, role_config_label(self.role_config))
        self.message = f"Salon regle sur {self.max_players} joueurs."
        self.broadcast_snapshots()
        return self.player_snapshot(player_id)

    def start_game(self, player_id: int):
        """
        Lance la partie si l'hôte le demande et que le salon est complet et valide.

        :param player_id: Indice du joueur demandant le lancement (int).
        :return: None si succès, dict d'erreur sinon.
        """
        if player_id != self.host_id:
            return {"type": "error", "message": "Seul l'hote peut lancer la partie."}
        active = [p for p in self.players if p.get("connected")]
        if len(active) < MIN_PLAYERS:
            return {"type": "error", "message": f"Il faut au moins {MIN_PLAYERS} joueurs."}
        if len(active) != self.max_players:
            return {"type": "error",
                    "message": f"Il faut exactement {self.max_players} joueurs connectes."}
        err = role_config_error(self.max_players, self.role_config)
        if err:
            return {"type": "error", "message": err}
        try:
            roles = build_roles(len(active), self.role_config)
        except ValueError as exc:
            return {"type": "error", "message": str(exc)}

        for p, role in zip(active, roles):
            p["role"]                     = role
            p["alive"]                    = True
            p["revealed_role"]            = None
            p["infected"]                 = False
            p["is_lover"]                 = False
            p["lover_id"]                 = None
            p["wild_child_turned"]        = False
            p["wild_child_mentor"]        = None
            p["maudit_converted"]         = False
            p["is_charmed"]               = False
            p["is_fueled"]                = False

        # Attribuer une cible aléatoire au Sniper
        sniper = next((p for p in active if p["role"] == "Sniper"), None)
        if sniper:
            targets = [p for p in active if p["id"] != sniper["id"]]
            if targets:
                self.sniper_target = random.choice(targets)["id"]

        # Sauvegarder les rôles initiaux pour l'écran de fin
        self.initial_roles = {p['id']: p['role'] for p in active}
        self.execution_history = []
        self.daily_deaths = {}
        self.game_started = True
        self.winner = None
        self.day_count = 0
        self.message = "La partie commence !"
        self.append_chat("Systeme",
                         f"La partie demarre : {role_config_label(self.role_config)}.",
                         system=True)
        if self.sniper_target is not None:
            sn_name = self.players[self.sniper_target]["name"]
            self.append_chat("Systeme",
                             f"Le Sniper a reçu sa cible secrète.",
                             system=True)
        self.start_night()
        return None

    # ── Phases ───────────────────────────────────────────────────────────────

    def alive_ids(self) -> list:
        """
        Retourne la liste des ID des joueurs encore vivants et connectés.

        :return: list[int]
        """
        return [p["id"] for p in self.players if p.get("connected") and p["alive"]]

    def start_night(self):
        """Démarre une nouvelle nuit : réinitialise les votes, définit l'étape de nuit initiale et diffuse les snapshots."""
        self.phase = "night"
        self.day_count += 1
        self.last_deaths = []
        self.pending_night = {
            "seer_done":       False,
            "witch_done":      False,
            "father_done":     False,
            "cupidon_done":    False,
            "wild_child_done": False,
            "salvateur_done":  False,
            "fox_done":        False,
            "siren_done":      False,
            "arsonist_done":   False,
        }
        self.wolf_votes = {}
        self.day_votes  = {}
        self.pending_wolf_target = None
        self.pending_hunter_queue = []

        if self.day_count == 1:
            self.night_step = "cupidon"
        else:
            self.night_step = "salvateur"  # Le Salvateur agit en premier dès la nuit 2
        self._advance_if_no_role()
        self.message = f"Nuit {self.day_count} : les rôles de nuit agissent dans l'ordre."
        self.broadcast_snapshots()

    def _next_night_step(self):
        """Passe à l'étape suivante dans l'ordre des nuits."""
        try:
            idx = NIGHT_ORDER.index(self.night_step)
            self.night_step = NIGHT_ORDER[idx + 1] if idx + 1 < len(NIGHT_ORDER) else "done"
        except ValueError:
            self.night_step = "done"

    def _advance_if_no_role(self):
        """Saute les étapes dont le rôle n'est pas présent ou déjà fait."""
        connected = [p for p in self.players if p.get("connected")]
        while self.night_step != "done":
            step = self.night_step

            if step == "cupidon":
                if (self.day_count == 1
                        and not self.cupidon_done
                        and any(p["alive"] and p["role"] == "Cupidon" for p in connected)):
                    break
                self._next_night_step()

            elif step == "wild_child":
                if (self.day_count == 1
                        and not self.wild_child_done
                        and any(p["alive"] and p["role"] == "Enfant sauvage" for p in connected)):
                    break
                self._next_night_step()

            elif step == "seer":
                if any(p["alive"] and p["role"] == "Voyante" for p in connected):
                    break
                self._next_night_step()

            elif step == "wolves":
                if any(p["alive"] and is_wolf_player(p) for p in connected):
                    break
                self._next_night_step()

            elif step == "father":
                if (not self.father_infect_used
                        and any(p["alive"] and p["role"] == "Infect Père des Loups"
                                for p in connected)):
                    break
                self._next_night_step()

            elif step == "witch":
                if any(p["alive"] and p["role"] == "Sorcière" for p in connected):
                    break
                self._next_night_step()

            elif step == "salvateur":
                if any(p["alive"] and p["role"] == "Salvateur" for p in connected):
                    break
                self._next_night_step()

            elif step == "fox":
                if (self.fox_power_active
                        and any(p["alive"] and p["role"] == "Renard" for p in connected)):
                    break
                self._next_night_step()

            elif step == "siren":
                if any(p["alive"] and p["role"] == "Sirène" for p in connected):
                    break
                self._next_night_step()

            elif step == "arsonist":
                if any(p["alive"] and p["role"] == "Pyromane" for p in connected):
                    break
                self._next_night_step()

            else:
                self.night_step = "done"
                break

    def resolve_wolves_if_ready(self) -> bool:
        """
        Calcule la cible des loups si tous les loups ont voté.
        En cas d'égalité stricte, aucune victime n'est désignée (personne ne meurt).

        :return: True si le vote est résolu (cible trouvée, égalité, ou aucun loup) (bool).
        """
        wolves = [p for p in self.players
                  if p.get("connected") and p["alive"] and is_wolf_player(p)]
        if not wolves:
            return True
        if len(self.wolf_votes) == len(wolves):
            counts = Counter(self.wolf_votes.values())
            max_votes = max(counts.values())
            leaders = [pid for pid, cnt in counts.items() if cnt == max_votes]
            if len(leaders) == 1:
                # Majorité claire : une seule victime désignée
                self.pending_wolf_target = leaders[0]
            else:
                # Égalité : personne ne meurt cette nuit
                self.pending_wolf_target = None
                self.append_chat("Systeme",
                                 "Égalité dans les votes des loups : personne n'est attaqué cette nuit.",
                                 system=True, wolf_only=True)
            return True
        return False

    def resolve_night_if_ready(self):
        """Déclenche la résolution de nuit uniquement si toutes les étapes de nuit sont terminées."""
        if self.night_step != "done":
            return
        self._resolve_night()

    # ── Helpers morts spéciales ───────────────────────────────────────────────

    def _apply_death(self, pid: int, deaths: set):
        """Applique la mort d'un joueur si encore vivant."""
        if pid < len(self.players) and self.players[pid]["alive"]:
            self.players[pid]["alive"]         = False
            self.players[pid]["revealed_role"] = self.players[pid]["role"]
            deaths.add(pid)

    def _check_lover_deaths(self, dead_ids: set) -> set:
        """Fait mourir le partenaire amoureux si son amoureux vient de mourir."""
        new_deaths = set()
        for pid in list(dead_ids):
            if pid < len(self.players) and self.players[pid].get("is_lover"):
                partner_id = self.players[pid].get("lover_id")
                if (partner_id is not None
                        and partner_id < len(self.players)
                        and self.players[partner_id]["alive"]):
                    self._apply_death(partner_id, new_deaths)
                    self.append_chat("Systeme",
                                     f"{self.players[partner_id]['name']} meurt de chagrin...",
                                     system=True)
        return new_deaths

    def _check_wild_child_conversion(self, dead_ids: set):
        """Convertit l'Enfant sauvage en loup si son mentor vient de mourir."""
        for p in self.players:
            if (p["alive"]
                    and p["role"] == "Enfant sauvage"
                    and not p.get("wild_child_turned", False)
                    and p.get("wild_child_mentor") in dead_ids):
                p["wild_child_turned"] = True
                self.append_chat("Systeme",
                                 f"{p['name']} (Enfant sauvage) bascule du côté des loups !",
                                 system=True)

    def _queue_hunter_deaths(self, dead_ids: set):
        """Ajoute les Chasseurs morts dans la queue d'attente."""
        for pid in dead_ids:
            if (pid < len(self.players)
                    and self.players[pid].get("revealed_role") == "Chasseur"
                    and pid not in self.pending_hunter_queue):
                self.pending_hunter_queue.append(pid)

    def _all_deaths_from(self, initial_dead: set) -> set:
        """
        Calcule la chaîne complète de morts :
        loups + poison → amoureux → Enfant sauvage converti.
        Retourne l'ensemble complet des IDs morts.
        """
        all_dead = set(initial_dead)
        lover_chain = self._check_lover_deaths(initial_dead)
        all_dead |= lover_chain
        # Lover deaths can chain again (shouldn't normally happen but handle it)
        if lover_chain:
            second_chain = self._check_lover_deaths(lover_chain)
            all_dead |= second_chain
        self._check_wild_child_conversion(all_dead)
        return all_dead

    # ── Résolution de nuit ────────────────────────────────────────────────────

    def _resolve_night(self):
        """Applique toutes les morts de la nuit (loups, poison, Salvateur, Villageois Maudit), gère les chaînes et passe au jour."""
        deaths: set = set()
        salvateur_protected = self.pending_night.get("salvateur_protected")
        infected_this_night = self.pending_night.get("infected_target")

        wolf_tgt = self.pending_wolf_target
        if wolf_tgt is not None and not self.pending_night.get("saved", False):
            if wolf_tgt == salvateur_protected:
                # Sauvé par le Salvateur
                self.append_chat("Systeme",
                                 "Le Salvateur a protégé quelqu'un cette nuit !",
                                 system=True)
            elif (self.players[wolf_tgt]["role"] == "Villageois Maudit"
                  and not self.players[wolf_tgt].get("maudit_converted", False)):
                # Villageois Maudit : conversion au lieu de mort
                self.players[wolf_tgt]["maudit_converted"] = True
                self.append_chat("Systeme",
                                 f"{self.players[wolf_tgt]['name']} révèle sa malédiction et rejoint les loups !",
                                 system=True)
            elif wolf_tgt != infected_this_night:
                self._apply_death(wolf_tgt, deaths)

        pt = self.pending_night.get("poison_target")
        if pt is not None:
            self._apply_death(pt, deaths)

        # Chaîne complète de morts (amoureux, enfant sauvage)
        all_dead = self._all_deaths_from(deaths)

        self.last_deaths = [self.players[pid]["name"] for pid in all_dead]
        # Enregistrer les morts nocturnes par jour
        if all_dead:
            jour = self.day_count  # encore la nuit du jour courrant
            self.daily_deaths.setdefault(jour, [])
            self.daily_deaths[jour].extend(self.players[pid]["name"] for pid in all_dead)

        # Sniper : si la cible meurt cette nuit (pas par vote), perte de la condition spéciale
        if self.sniper_target is not None and self.sniper_target in all_dead:
            sniper = next((p for p in self.players if p["alive"] and p["role"] == "Sniper"), None)
            if sniper:
                tgt_name = self.players[self.sniper_target]["name"]
                self.append_chat("Systeme",
                                 f"La cible du Sniper ({tgt_name}) est morte cette nuit ! "
                                 f"Le Sniper perd sa victoire spéciale et continue comme Villageois.",
                                 system=True)
                self.sniper_target = None

        # Queue les Chasseurs morts (ils agiront à l'aube, après le reveal)
        self._queue_hunter_deaths(all_dead)

        self.winner = check_winner(self.players)
        if self.winner is not None:
            self.phase   = "end"
            self.message = f"Victoire du camp : {self.winner} !"
            self.broadcast_snapshots()
        else:
            # Phase aube : tout le monde voit les morts AVANT que le vote du jour commence.
            # Le Chasseur agit aussi à l'aube (start_day_from_dawn), jamais pendant la nuit.
            self.phase = "dawn"
            # Construire last_deaths_with_roles pour l'affichage aube
            self.last_deaths_with_roles = [
                {"nom": self.players[pid]["name"],
                 "role": self.players[pid].get("revealed_role") or self.players[pid]["role"]}
                for pid in all_dead
            ]
            if self.last_deaths:
                self.message = ("Aube : " + ", ".join(self.last_deaths) +
                                f" éliminé(s) cette nuit. Le jour commence dans {self.DAWN_DURATION}s.")
            else:
                self.last_deaths_with_roles = []
                self.message = f"Aube : personne n'est mort cette nuit. Le jour commence dans {self.DAWN_DURATION}s."
            self._start_dawn_timer()
            self.broadcast_snapshots()

    def start_day_from_dawn(self, player_id: int):
        """
        Appelé quand l'hôte valide l'aube pour passer au vote du jour.
        Si un Chasseur est en attente, c'est maintenant qu'il agit.
        """
        if self.phase != "dawn":
            return self.player_snapshot(player_id)
        if player_id != self.host_id:
            return {"type": "error", "message": "Seul l'hôte peut passer au jour."}

        # Annuler le timer automatique (l'hôte passe manuellement)
        self._cancel_dawn_timer()
        self._do_dawn_advance()
        return self.player_snapshot(player_id)

    def _auto_hunter_shoot(self, hunter_id: int):
        """Le Chasseur déconnecté tire aléatoirement et annonce sa cible."""
        targets = [p["id"] for p in self.players
                   if p["alive"] and p["id"] != hunter_id]
        if targets:
            tid = random.choice(targets)
            extra = set()
            self._apply_death(tid, extra)
            extra2 = self._all_deaths_from(extra)
            self.last_deaths += [self.players[pid]["name"] for pid in extra2]
            self._check_wild_child_conversion(extra2)
            self.append_chat("Systeme",
                             f"{self.players[tid]['name']} est abattu d'une balle !",
                             system=True)

    def _proceed_after_hunter(self):
        """Reprend après que le Chasseur ait agi."""
        if self.pending_hunter_queue:
            # D'autres Chasseurs en attente
            next_hunter = self.pending_hunter_queue[0]
            if self.players[next_hunter].get("connected"):
                self.broadcast_snapshots()
                return
            else:
                self._auto_hunter_shoot(next_hunter)
                self.pending_hunter_queue.pop(0)
                self._proceed_after_hunter()
                return

        self.winner = check_winner(self.players)
        if self.winner is not None:
            self.phase   = "end"
            self.message = f"Victoire du camp : {self.winner} !"
        elif self.phase == "hunter_day":
            # Chasseur de nuit → retour au vote du jour
            self.phase   = "day"
            self.message = ("Jour : " + ", ".join(self.last_deaths) + " éliminé(s). Votez."
                            if self.last_deaths else "Jour : personne n'est mort cette nuit. Votez.")
        else:
            # Chasseur du jour → retour à la nuit
            self.phase = "day"
            self.message = ("Jour : " + ", ".join(self.last_deaths) + " éliminé(s). La nuit tombe..."
                            if self.last_deaths else "Nuit.")
        self.broadcast_snapshots()

    # ── Actions de nuit ──────────────────────────────────────────────────────

    def handle_night_action(self, player_id: int, msg: dict):
        """
        Traite l'action de nuit d'un joueur selon son rôle et l'étape courante.

        :param player_id: Indice du joueur agissant (int).
        :param msg: Message JSON avec les clés 'action', 'target', 'targets' (dict).
        :return: Snapshot d'état ou dict d'erreur (dict).
        """
        if self.phase != "night" and not self.pending_hunter_queue:
            return {"type": "error", "message": "Ce n'est pas la nuit."}
        player = self.players[player_id]
        action = msg.get("action")
        target = msg.get("target")
        targets = msg.get("targets", [])

        # ── Chasseur ──────────────────────────────────────────────────────────
        if action == "hunter_shoot":
            if not self.pending_hunter_queue or self.pending_hunter_queue[0] != player_id:
                return {"type": "error", "message": "Ce n'est pas votre tour de Chasseur."}
            if target not in [p["id"] for p in self.players if p["alive"]]:
                return {"type": "error", "message": "Cible invalide."}
            extra = set()
            self._apply_death(target, extra)
            extra2 = self._all_deaths_from(extra)
            self.last_deaths += [self.players[pid]["name"] for pid in extra2]
            self._queue_hunter_deaths(extra2 - {player_id})
            self.pending_hunter_queue.pop(0)
            # Message officiel selon les règles
            self.append_chat("Systeme",
                             f"{self.players[target]['name']} est abattu d'une balle !",
                             system=True)
            self._proceed_after_hunter()
            return self.player_snapshot(player_id)

        if self.phase != "night":
            return {"type": "error", "message": "Ce n'est pas la nuit."}
        if not player["alive"]:
            return {"type": "error", "message": "Tu es éliminé."}

        # ── Cupidon ───────────────────────────────────────────────────────────
        if action == "cupidon_choose":
            if player["role"] != "Cupidon" or self.cupidon_done:
                return {"type": "error", "message": "Action Cupidon indisponible."}
            if self.night_step != "cupidon":
                return {"type": "error", "message": "Ce n'est pas le tour de Cupidon."}
            alive_list = self.alive_ids()
            if len(targets) != 2 or not all(t in alive_list for t in targets) or targets[0] == targets[1]:
                return {"type": "error", "message": "Choisissez exactement 2 joueurs vivants différents."}
            p1, p2 = targets[0], targets[1]
            self.players[p1]["is_lover"] = True
            self.players[p1]["lover_id"] = p2
            self.players[p2]["is_lover"] = True
            self.players[p2]["lover_id"] = p1
            self.lovers = [p1, p2]
            self.cupidon_done = True
            self.pending_night["cupidon_done"] = True
            # Message discret visible de tous (pas de noms)
            self.append_chat("Systeme",
                             "Cupidon a lancé ses flèches dans la nuit...",
                             system=True, wolf_only=False)
            # Message avec les noms : stocké séparément, envoyé uniquement aux concernés
            n1, n2 = self.players[p1]["name"], self.players[p2]["name"]
            self.pending_night["lovers_msg"] = f"{n1} et {n2} sont tombés amoureux !"
            self.pending_night["lovers_ids"] = [p1, p2]
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Enfant sauvage ────────────────────────────────────────────────────
        if action == "wild_child_choose":
            if player["role"] != "Enfant sauvage" or self.wild_child_done:
                return {"type": "error", "message": "Action Enfant sauvage indisponible."}
            if self.night_step != "wild_child":
                return {"type": "error", "message": "Ce n'est pas le tour de l'Enfant sauvage."}
            if target not in self.alive_ids() or target == player_id:
                return {"type": "error", "message": "Cible invalide."}
            player["wild_child_mentor"] = target
            self.wild_child_done = True
            self.pending_night["wild_child_done"] = True
            mname = self.players[target]["name"]
            self.append_chat("Systeme",
                             f"L'Enfant sauvage a choisi son mentor dans les ténèbres...",
                             system=True)
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Loups ─────────────────────────────────────────────────────────────
        if action == "wolf_kill":
            if not is_wolf_player(player):
                return {"type": "error", "message": "Action réservée aux loups-garous."}
            if self.night_step != "wolves":
                return {"type": "error", "message": "Ce n'est pas encore le tour des loups."}
            if target == player_id or target not in self.alive_ids():
                return {"type": "error", "message": "Cible invalide."}
            if is_wolf_player(self.players[target]):
                return {"type": "error", "message": "Vous ne pouvez pas viser un loup."}
            self.wolf_votes[player_id] = target
            # Diffuser immédiatement pour que les autres loups voient le vote
            self.broadcast_snapshots()
            wolves = [p for p in self.players
                      if p.get("connected") and p["alive"] and is_wolf_player(p)]
            if len(self.wolf_votes) == len(wolves):
                # Tous les loups ont voté : calcul avec gestion d'égalité
                counts = Counter(self.wolf_votes.values())
                max_votes = max(counts.values())
                leaders = [pid for pid, cnt in counts.items() if cnt == max_votes]
                if len(leaders) == 1:
                    self.pending_wolf_target = leaders[0]
                else:
                    # Égalité : personne ne meurt
                    self.pending_wolf_target = None
                    self.append_chat("Systeme",
                                     "Égalité dans les votes des loups : personne n'est attaqué cette nuit.",
                                     system=True, wolf_only=True)
                self._next_night_step()
                self._advance_if_no_role()
                if self.night_step == "done":
                    self._resolve_night()
                else:
                    self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Père des Loups ────────────────────────────────────────────────────
        if action == "father_infect":
            if player["role"] != "Infect Père des Loups" or self.pending_night.get("father_done", False):
                return {"type": "error", "message": "Action Père des Loups indisponible."}
            if self.night_step != "father":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Père des Loups."}
            if self.father_infect_used:
                return {"type": "error", "message": "Pouvoir d'infection déjà utilisé."}
            if self.pending_wolf_target is None:
                return {"type": "error", "message": "Aucune victime à infecter."}
            tgt = self.pending_wolf_target
            self.players[tgt]["infected"] = True
            self.pending_night["infected_target"] = tgt
            self.pending_night["father_done"] = True
            self.father_infect_used = True
            self.append_chat("Systeme",
                             "Le Père des Loups agit dans l'ombre...",
                             system=True, wolf_only=True)
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "father_skip":
            if player["role"] != "Infect Père des Loups" or self.pending_night.get("father_done", False):
                return {"type": "error", "message": "Action Père des Loups indisponible."}
            if self.night_step != "father":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Père des Loups."}
            self.pending_night["father_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Voyante ───────────────────────────────────────────────────────────
        if action == "seer_peek":
            if player["role"] != "Voyante" or self.pending_night.get("seer_done", False):
                return {"type": "error", "message": "Action Voyante indisponible."}
            if self.night_step != "seer":
                return {"type": "error", "message": "Ce n'est pas encore le tour de la Voyante."}
            if target not in self.alive_ids() or target == player_id:
                return {"type": "error", "message": "Cible invalide."}
            tgt_role = self.players[target]["role"]
            result = f"{self.players[target]['name']} est {tgt_role}."
            if self.players[target].get("infected"):
                result += " (infecté — c'est un loup !)"
            elif self.players[target].get("wild_child_turned"):
                result += " (devenu loup !)"
            self.pending_night[f"seer_result_{player_id}"] = result
            self.pending_night["seer_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Sorcière ──────────────────────────────────────────────────────────
        if action == "witch_save":
            if player["role"] != "Sorcière" or self.pending_night.get("witch_done", False):
                return {"type": "error", "message": "Action Sorcière indisponible."}
            if self.night_step != "witch":
                return {"type": "error", "message": "Ce n'est pas encore le tour de la Sorcière."}
            if self.witch_heal_used:
                return {"type": "error", "message": "Potion de soin déjà utilisée."}
            # L'infecte père des loups : la sorcière ne peut pas sauver la victime infectée
            if self.pending_night.get("infected_target") is not None:
                return {"type": "error", "message": "L'Infect Père des Loups a agi — la sorcière ne peut pas contrer son pouvoir !"}
            self.pending_night["saved"]      = True
            self.pending_night["witch_done"] = True
            self.witch_heal_used = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "witch_poison":
            if player["role"] != "Sorcière" or self.pending_night.get("witch_done", False):
                return {"type": "error", "message": "Action Sorcière indisponible."}
            if self.night_step != "witch":
                return {"type": "error", "message": "Ce n'est pas encore le tour de la Sorcière."}
            if self.witch_poison_used:
                return {"type": "error", "message": "Potion de mort déjà utilisée."}
            if target not in self.alive_ids() or target == player_id:
                return {"type": "error", "message": "Cible invalide."}
            self.pending_night["poison_target"] = target
            self.pending_night["witch_done"]    = True
            self.witch_poison_used = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "witch_skip":
            if player["role"] != "Sorcière" or self.pending_night.get("witch_done", False):
                return {"type": "error", "message": "Action Sorcière indisponible."}
            if self.night_step != "witch":
                return {"type": "error", "message": "Ce n'est pas encore le tour de la Sorcière."}
            self.pending_night["witch_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Salvateur ─────────────────────────────────────────────────────────
        if action == "salvateur_protect":
            if player["role"] != "Salvateur" or self.pending_night.get("salvateur_done", False):
                return {"type": "error", "message": "Action Salvateur indisponible."}
            if self.night_step != "salvateur":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Salvateur."}
            if target not in self.alive_ids():
                return {"type": "error", "message": "Cible invalide."}
            if target == self.salvateur_last_protected:
                return {"type": "error", "message": "Impossible de protéger la même personne deux nuits de suite."}
            self.pending_night["salvateur_protected"] = target
            self.salvateur_last_protected = target
            self.pending_night["salvateur_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "salvateur_skip":
            if player["role"] != "Salvateur" or self.pending_night.get("salvateur_done", False):
                return {"type": "error", "message": "Action Salvateur indisponible."}
            if self.night_step != "salvateur":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Salvateur."}
            self.pending_night["salvateur_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Renard ────────────────────────────────────────────────────────────
        if action == "fox_sense":
            if player["role"] != "Renard" or self.pending_night.get("fox_done", False):
                return {"type": "error", "message": "Action Renard indisponible."}
            if self.night_step != "fox":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Renard."}
            if not self.fox_power_active:
                return {"type": "error", "message": "Vous avez perdu votre pouvoir."}
            alive_list = self.alive_ids()
            if (len(targets) != 3
                    or not all(t in alive_list for t in targets)
                    or len(set(targets)) != 3):
                return {"type": "error", "message": "Choisissez exactement 3 joueurs vivants différents."}
            has_wolf = any(is_wolf_player(self.players[t]) for t in targets)
            if not has_wolf:
                self.fox_power_active = False
                result = "Aucun loup parmi ces 3 joueurs. Vous perdez votre pouvoir !"
            else:
                result = "Il y a au moins un loup parmi ces 3 joueurs !"
            self.pending_night[f"fox_result_{player_id}"] = result
            self.pending_night["fox_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "fox_skip":
            if player["role"] != "Renard" or self.pending_night.get("fox_done", False):
                return {"type": "error", "message": "Action Renard indisponible."}
            if self.night_step != "fox":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Renard."}
            self.pending_night["fox_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Sirène ────────────────────────────────────────────────────────────
        if action == "siren_charm":
            if player["role"] != "Sirène" or self.pending_night.get("siren_done", False):
                return {"type": "error", "message": "Action Sirène indisponible."}
            if self.night_step != "siren":
                return {"type": "error", "message": "Ce n'est pas encore le tour de la Sirène."}
            if target not in self.alive_ids() or target == player_id:
                return {"type": "error", "message": "Cible invalide."}
            if target not in self.charmed_players:
                self.charmed_players.append(target)
                self.players[target]["is_charmed"] = True
                self.append_chat("Systeme",
                                 f"La Sirène chante dans la nuit...",
                                 system=True)
            self.pending_night["siren_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "siren_skip":
            if player["role"] != "Sirène" or self.pending_night.get("siren_done", False):
                return {"type": "error", "message": "Action Sirène indisponible."}
            if self.night_step != "siren":
                return {"type": "error", "message": "Ce n'est pas encore le tour de la Sirène."}
            self.pending_night["siren_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        # ── Pyromane ──────────────────────────────────────────────────────────
        if action == "arsonist_fuel":
            if player["role"] != "Pyromane" or self.pending_night.get("arsonist_done", False):
                return {"type": "error", "message": "Action Pyromane indisponible."}
            if self.night_step != "arsonist":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Pyromane."}
            if target not in self.alive_ids():
                return {"type": "error", "message": "Cible invalide."}
            if target not in self.fueled_players:
                self.fueled_players.append(target)
                self.players[target]["is_fueled"] = True
            self.pending_night["arsonist_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "arsonist_ignite":
            if player["role"] != "Pyromane" or self.pending_night.get("arsonist_done", False):
                return {"type": "error", "message": "Action Pyromane indisponible."}
            if self.night_step != "arsonist":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Pyromane."}
            burned = set(self.fueled_players)
            self.fueled_players = []
            for pid in burned:
                if pid < len(self.players):
                    self.players[pid]["is_fueled"] = False
                    self._apply_death(pid, burned)
            if burned:
                self.append_chat("Systeme",
                                 f"Un terrible incendie éclate ! {len(burned)} joueur(s) périssent dans les flammes !",
                                 system=True)
            all_dead = self._all_deaths_from(burned)
            self.last_deaths = [self.players[pid]["name"] for pid in all_dead
                                 if pid < len(self.players)]
            self.pending_night["arsonist_done"] = True
            # Vérifier victoire Pyromane
            alive_others = [p for p in self.players if p["alive"] and p["id"] != player_id]
            if not alive_others:
                self.winner = "Pyromane"
                self.phase  = "end"
                self.message = "Victoire du Pyromane : tout le village a brûlé !"
                self.broadcast_snapshots()
                return self.player_snapshot(player_id)
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        if action == "arsonist_skip":
            if player["role"] != "Pyromane" or self.pending_night.get("arsonist_done", False):
                return {"type": "error", "message": "Action Pyromane indisponible."}
            if self.night_step != "arsonist":
                return {"type": "error", "message": "Ce n'est pas encore le tour du Pyromane."}
            self.pending_night["arsonist_done"] = True
            self._next_night_step()
            self._advance_if_no_role()
            if self.night_step == "done":
                self._resolve_night()
            else:
                self.broadcast_snapshots()
            return self.player_snapshot(player_id)

        return {"type": "error", "message": "Action inconnue."}

    def handle_vote(self, player_id: int, msg: dict):
        """
        Enregistre le vote diurne d'un joueur et résout l'élimination quand tous ont voté.

        :param player_id: Indice du joueur qui vote (int).
        :param msg: Message JSON avec la clé 'target' (dict).
        :return: Snapshot d'état ou dict d'erreur (dict).
        """
        if self.phase != "day":
            return {"type": "error", "message": "Ce n'est pas le moment de voter."}
        if not self.players[player_id]["alive"]:
            return {"type": "error", "message": "Tu es elimine."}
        target = msg.get("target")
        if target not in self.alive_ids() or target == player_id:
            return {"type": "error", "message": "Cible invalide."}
        self.day_votes[player_id] = target
        alive_voters = [p for p in self.players if p.get("connected") and p["alive"]]
        if len(self.day_votes) == len(alive_voters):
            counts = Counter(self.day_votes.values())
            max_votes = max(counts.values())
            leaders = [pid for pid, cnt in counts.items() if cnt == max_votes]

            if len(leaders) > 1:
                # Égalité au vote du village : personne n'est éliminé
                self.last_deaths = []
                self.append_chat("Systeme",
                                 "Égalité au vote du village : personne n'est éliminé aujourd'hui.",
                                 system=True)
                self.winner = check_winner(self.players)
                if self.winner is not None:
                    self.phase   = "end"
                    self.message = f"Égalité. Victoire : {self.winner} !"
                else:
                    self.message = "Égalité ! Personne n'est éliminé. La nuit tombe..."
                    self.start_night()
                    return self.player_snapshot(player_id)
                self.broadcast_snapshots()
                return self.player_snapshot(player_id)

            chosen = leaders[0]
            eliminated = set()
            self._apply_death(chosen, eliminated)
            self.players[chosen]["revealed_role"] = self.players[chosen]["role"]
            # Enregistrer dans l'historique des exécutions
            self.execution_history.append({
                "jour":   self.day_count,
                "nom":    self.players[chosen]["name"],
                "role":   self.players[chosen]["role"],
            })
            # Enregistrer dans les morts par jour
            self.daily_deaths.setdefault(self.day_count, [])
            self.daily_deaths[self.day_count].append(self.players[chosen]["name"])

            # Vérification Sniper
            if (self.sniper_target == chosen):
                sniper = next((p for p in self.players
                               if p["alive"] and p["role"] == "Sniper"), None)
                if sniper:
                    self.winner = "Sniper"
                    self.phase  = "end"
                    self.last_deaths = [self.players[chosen]["name"]]
                    self.message = (f"{self.players[chosen]['name']} éliminé — "
                                    f"c'était la cible du Sniper ! Victoire : Sniper !")
                    self.broadcast_snapshots()
                    return self.player_snapshot(player_id)

            # Chaîne de morts (amoureux, enfant sauvage)
            all_dead = self._all_deaths_from(eliminated)
            self.last_deaths = [self.players[pid]["name"] for pid in all_dead]

            # Chasseur éliminé par vote : agit APRÈS l'annonce de mort (phase hunter_day)
            self._queue_hunter_deaths(all_dead)
            if self.pending_hunter_queue:
                hunter_id = self.pending_hunter_queue[0]
                if self.players[hunter_id].get("connected"):
                    self.phase = "hunter_day"
                    self.message = (f"{self.players[chosen]['name']} éliminé. "
                                    f"Le Chasseur {self.players[hunter_id]['name']} a décidé de tirer !")
                    self.broadcast_snapshots()
                    return self.player_snapshot(player_id)
                else:
                    self._auto_hunter_shoot(hunter_id)
                    self.pending_hunter_queue.pop(0)

            self.winner = check_winner(self.players)
            if self.winner is not None:
                self.phase   = "end"
                self.message = (f"{self.players[chosen]['name']} elimine. "
                                f"Victoire : {self.winner} !")
            else:
                self.message = f"{self.players[chosen]['name']} éliminé. La nuit tombe..."
                self.start_night()
                return self.player_snapshot(player_id)
        self.broadcast_snapshots()
        return self.player_snapshot(player_id)

    def handle_chat(self, player_id: int, msg: dict):
        """
        Traite un message de chat : applique la modération, filtre les loups la nuit et diffuse à tous.

        :param player_id: Indice de l'auteur du message (int).
        :param msg: Message JSON avec la clé 'message' (dict).
        :return: Snapshot d'état (dict).
        """
        raw = str(msg.get("message", "")).strip()
        if not raw:
            return self.player_snapshot(player_id)
        raw = raw[:220]
        player = self.players[player_id] if player_id < len(self.players) else None
        if player is None:
            return self.player_snapshot(player_id)
        is_dead = not player.get("alive", True)
        is_wolf = is_wolf_player(player)
        # La nuit, seuls les loups et les morts peuvent écrire
        if self.phase == "night" and self.game_started:
            if not is_wolf and not is_dead:
                return {"type": "error",
                        "message": "Seuls les loups-garous peuvent parler la nuit."}
        # Un mort ne peut écrire que dans le chat des morts
        clean, flagged = self.moderator.moderate(raw)
        author = player.get("name", f"Joueur {player_id + 1}")
        if flagged:
            clean = "*" * len(raw)
        # wolf_only : uniquement pour les loups vivants la nuit
        wolf_only = (self.phase == "night" and self.game_started and is_wolf and not is_dead)
        # dead_only : messages des joueurs morts, invisibles aux vivants
        dead_only = is_dead
        entry = {
            "author":    author,
            "message":   clean,
            "system":    False,
            "wolf_only": wolf_only,
            "dead_only": dead_only,
        }
        self.chat_history.append(entry)
        if flagged:
            self.append_chat("Systeme", f"Message de {author} modéré.", system=True)
        self.broadcast_snapshots()
        return self.player_snapshot(player_id)

    # ── Boucle serveur ───────────────────────────────────────────────────────

    def handle_client(self, conn, player_id: int):
        """
        Boucle de réception TCP pour un joueur : lit les messages JSON ligne par ligne et dispatche les handlers.

        :param conn: Socket TCP du joueur (socket.socket).
        :param player_id: Indice du joueur connecté (int).
        """
        buf = ""
        try:
            while self.running:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    with self.lock:
                        kind = msg.get("type")
                        if kind == "join":
                            response = self.handle_join(player_id, msg)
                        elif kind == "update_role_config":
                            response = self.update_role_config(player_id, msg)
                        elif kind == "start_game":
                            response = self.start_game(player_id)
                        elif kind == "dawn_advance":
                            response = self.start_day_from_dawn(player_id)
                        elif kind == "update_max_players":
                            response = self.update_max_players(player_id, msg)
                        elif kind == "night_action":
                            response = self.handle_night_action(player_id, msg)
                        elif kind == "vote_action":
                            response = self.handle_vote(player_id, msg)
                        elif kind == "chat_message":
                            response = self.handle_chat(player_id, msg)
                        elif kind == "sync_request":
                            response = self.player_snapshot(player_id)
                        elif kind == "restart_game":
                            response = self.handle_restart_game(player_id)
                        else:
                            response = {"type": "error", "message": "Commande inconnue."}
                    if response is not None:
                        self.send_json(conn, response)
        except (ConnectionResetError, json.JSONDecodeError, OSError):
            pass
        except Exception as e:
            print(f"[SERVEUR] Erreur inattendue joueur {player_id}: {e}")
        finally:
            with self.lock:
                if player_id < len(self.clients) and self.clients[player_id] is conn:
                    self.remove_client(player_id)
            try:
                conn.close()
            except OSError:
                pass

    def shutdown(self):
        """Arrête le serveur proprement : notifie les clients, ferme toutes les connexions et le socket TCP."""
        self.running = False
        self._cancel_dawn_timer()
        self.broadcaster.stop()
        with self.lock:
            for i, conn in enumerate(self.clients):
                if conn is not None:
                    try:
                        self.send_json(conn, {"type": "info", "message": "Le serveur s'arrete."})
                    except OSError:
                        pass
                    try:
                        conn.close()
                    except OSError:
                        pass
                    self.clients[i] = None
        try:
            self.server.close()
        except OSError:
            pass

    def serve_forever(self):
        """Démarre le serveur TCP : bind, écoute, annonce UDP, et accepte les connexions dans une boucle infinie."""
        try:
            self.server.bind((self.host, self.port))
        except OSError as e:
            print(f"[SERVEUR] Impossible de binder sur {self.host}:{self.port} : {e}")
            if self.ready_event:
                self.ready_event.set()
            return
        self.server.listen(MAX_PLAYERS + 2)
        self.server.settimeout(1.0)
        self.broadcaster.start()
        self.bind_ok = True
        if self.ready_event:
            self.ready_event.set()
        print(f"[SERVEUR] Lance sur {self.host}:{self.port}")
        print(f"[SERVEUR] IP locale : {self.host_ip}")
        print(f"[SERVEUR] Config : max {self.max_players} | {role_config_label(self.role_config)}")
        while self.running:
            try:
                conn, addr = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self.lock:
                try:
                    player_id = self.clients.index(None)
                except ValueError:
                    if len(self.clients) < MAX_PLAYERS:
                        player_id = len(self.clients)
                        self.clients.append(None)
                    else:
                        self.send_json(conn, {"type": "error", "message": "Serveur plein."})
                        conn.close()
                        continue
                self.clients[player_id] = conn
                self.broadcaster.set_player_count(self.connected_player_count())
            print(f"[SERVEUR] Joueur {player_id + 1} connecte depuis {addr}")
            threading.Thread(target=self.handle_client,
                             args=(conn, player_id), daemon=True).start()


if __name__ == "__main__":
    server = WerewolfServer()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArret demande.")
    finally:
        server.shutdown()
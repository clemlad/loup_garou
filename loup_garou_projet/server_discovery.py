"""
server_discovery.py – Découverte automatique des serveurs sur le réseau local.

Utilise UDP broadcast : le serveur envoie une annonce toutes les secondes sur
le port DISCOVERY_PORT, et les clients écoutent ce port pour lister les salons
disponibles. Les serveurs non reçus depuis SERVER_TIMEOUT secondes sont supprimés.
"""
import json
import socket
import threading
import time

DISCOVERY_PORT    = 37020   # port UDP d'annonce (distinct du port TCP de jeu)
GAME_PORT         = 5555    # port TCP du serveur de jeu
DISCOVERY_INTERVAL = 1.0   # fréquence d'envoi des annonces (secondes)
SERVER_TIMEOUT    = 3.5     # délai avant de considérer un serveur disparu
ANNOUNCE_TYPE     = "werewolf_server_announce"


def get_local_ip():
    """
    Détermine l'IP locale de la machine en établissant une connexion UDP factice
    vers 8.8.8.8 (aucune donnée n'est envoyée) pour laisser l'OS choisir l'interface.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class ServerBroadcaster:
    """Diffuse périodiquement une annonce UDP pour rendre le serveur visible sur le réseau."""

    def __init__(self, server_name, host_ip=None, game_port=GAME_PORT):
        """
        Initialise le broadcaster avec le nom du serveur et les paramètres réseau.

        :param server_name: Nom du salon à diffuser (str).
        :param host_ip: Adresse IP locale du serveur (str ou None pour autodétection).
        :param game_port: Port TCP du jeu (int), 5555 par défaut.
        """
        self.server_name  = server_name
        self.host_ip      = host_ip or get_local_ip()
        self.game_port    = game_port
        self.running      = False
        self.thread       = None
        self.player_count = 1
        self.max_players  = 12
        self.role_summary = "1 loup(s), voyante, sorcière"

    def set_player_count(self, count):
        """
        Met à jour le nombre de joueurs connectés diffusé dans les annonces.

        :param count: Nombre actuel de joueurs connectés (int).
        """
        self.player_count = count

    def set_room_config(self, max_players=None, role_summary=None):
        """
        Met à jour la configuration du salon diffusée dans les annonces.

        :param max_players: Nombre maximum de joueurs du salon (int ou None pour ne pas modifier).
        :param role_summary: Résumé textuel des rôles configurés (str ou None pour ne pas modifier).
        """
        if max_players is not None:
            self.max_players = max_players
        if role_summary is not None:
            self.role_summary = role_summary

    def start(self):
        """Démarre le thread de diffusion UDP si ce n'est pas déjà fait."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        """Arrête le thread de diffusion UDP."""
        self.running = False

    def _run(self):
        """Boucle d'envoi : reconstruit le payload à chaque itération pour refléter
        les valeurs les plus récentes (joueurs connectés, config des rôles).
        Envoie en broadcast ET en loopback pour que la machine hôte se détecte elle-même."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        payload = {
            "type":        ANNOUNCE_TYPE,
            "name":        self.server_name,
            "host":        self.host_ip,
            "port":        self.game_port,
            "players":     self.player_count,
            "max_players": self.max_players,
            "roles":       self.role_summary,
        }
        # Adresses de destination : broadcast réseau + loopback (auto-découverte)
        destinations = ["255.255.255.255", "127.0.0.1"]
        try:
            while self.running:
                # Mise à jour des champs dynamiques avant chaque envoi
                payload["players"]     = self.player_count
                payload["max_players"] = self.max_players
                payload["roles"]       = self.role_summary
                data = json.dumps(payload).encode("utf-8")
                for dest in destinations:
                    try:
                        sock.sendto(data, (dest, DISCOVERY_PORT))
                    except OSError:
                        pass
                time.sleep(DISCOVERY_INTERVAL)
        finally:
            sock.close()


class ServerDiscovery:
    """Écoute les annonces UDP et maintient une liste à jour des serveurs actifs."""

    def __init__(self):
        """Initialise le listener UDP : liste des serveurs vide et verrou thread-safe."""
        self.running        = False
        self.thread         = None
        self.lock           = threading.Lock()
        self.found_servers  = {}   # clé : (host, port)

    def start(self):
        """Démarre le thread d'écoute UDP si ce n'est pas déjà fait."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

    def stop(self):
        """Arrête le thread d'écoute UDP."""
        self.running = False

    def _listen(self):
        """Écoute les paquets UDP et met à jour found_servers."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT permet au broadcaster et au listener de coexister sur le même port
        # (Linux/macOS uniquement — ignoré silencieusement sur Windows)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.bind(("", DISCOVERY_PORT))
        sock.settimeout(1.0)   # timeout pour pouvoir vérifier self.running régulièrement
        try:
            while self.running:
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    # Pas de paquet reçu → on profite du timeout pour nettoyer les vieux serveurs
                    self._cleanup()
                    continue
                except OSError:
                    break

                try:
                    msg = json.loads(data.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if msg.get("type") != ANNOUNCE_TYPE:
                    continue

                host = msg.get("host") or addr[0]
                port = msg.get("port", GAME_PORT)
                key  = (host, port)
                with self.lock:
                    self.found_servers[key] = {
                        "name":        msg.get("name", "Serveur"),
                        "host":        host,
                        "port":        port,
                        "players":     msg.get("players", 0),
                        "max_players": msg.get("max_players", 12),
                        "roles":       msg.get("roles", "Configuration par défaut"),
                        "last_seen":   time.time(),
                    }
                self._cleanup()
        finally:
            sock.close()

    def _cleanup(self):
        """Supprime les serveurs dont la dernière annonce date de plus de SERVER_TIMEOUT secondes."""
        now = time.time()
        with self.lock:
            expired = [key for key, info in self.found_servers.items()
                       if now - info["last_seen"] > SERVER_TIMEOUT]
            for key in expired:
                del self.found_servers[key]

    def get_servers(self):
        """Retourne une copie triée de la liste des serveurs actifs."""
        with self.lock:
            servers = list(self.found_servers.values())
        servers.sort(key=lambda s: (s["name"].lower(), s["host"], s["port"]))
        return servers
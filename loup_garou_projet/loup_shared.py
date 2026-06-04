"""
loup_shared.py – Logique de jeu partagée entre le mode solo et le mode en ligne.
Contient le catalogue des rôles, les fonctions de construction de parties
et les fonctions de vérification de victoire.
"""
import random
from collections import Counter

MIN_PLAYERS = 3
MAX_PLAYERS = 12

ROLE_CATALOG = {
    "Loup-garou": {
        "camp": "Loups",
        "aura": "Sombre",
        "max": 4,
        "night_action": True,
        "weight": 2.2,
        "description": "Chaque nuit, les loups-garous choisissent ensemble une victime parmi les autres joueurs vivants.",
        "ui_icon": "LG",
    },
    "Infect Père des Loups": {
        "camp": "Loups",
        "aura": "Sombre",
        "max": 1,
        "night_action": True,
        "weight": 2.5,
        "description": "Loup spécial. Après le vote des loups, il peut infecter la victime désignée UNE seule fois. La victime devient loup tout en conservant ses capacités d'origine.",
        "ui_icon": "IP",
    },
    "Voyante": {
        "camp": "Village",
        "aura": "Claire",
        "max": 1,
        "night_action": True,
        "weight": 1.8,
        "description": "Chaque nuit, vous choisissez un joueur pour découvrir son rôle exact.",
        "ui_icon": "VO",
    },
    "Cupidon": {
        "camp": "Village",
        "aura": "Claire",
        "max": 1,
        "night_action": True,
        "weight": 1.1,
        "description": "La première nuit uniquement, vous choisissez deux joueurs qui tombent amoureux. Si l'un meurt, l'autre meurt de chagrin. S'ils sont les deux derniers survivants, ils gagnent ensemble.",
        "ui_icon": "CU",
    },
    "Sorcière": {
        "camp": "Village",
        "aura": "Claire",
        "max": 1,
        "night_action": True,
        "weight": 2.0,
        "description": "Vous avez une potion de soin (sauver la victime des loups) et une potion de mort (empoisonner n'importe quel joueur). Chacune ne peut être utilisée qu'une seule fois.",
        "ui_icon": "SO",
    },
    "Chasseur": {
        "camp": "Village",
        "aura": "Claire",
        "max": 1,
        "night_action": False,
        "weight": 1.4,
        "description": "Lorsque vous mourez (nuit ou jour), vous choisissez immédiatement un joueur à éliminer avec vous.",
        "ui_icon": "CH",
    },
    "Sniper": {
        "camp": "Solo",
        "aura": "Inconnue",
        "max": 1,
        "night_action": False,
        "weight": 1.0,
        "description": "Une cible secrète vous est attribuée en début de partie. Vous gagnez seul si cette cible est éliminée par le vote du village pendant que vous êtes encore en vie.",
        "ui_icon": "SN",
    },
    "Salvateur": {
        "camp": "Village",
        "aura": "Claire",
        "max": 1,
        "night_action": True,
        "weight": 1.3,
        "description": "Chaque nuit, vous protégez un joueur de l'attaque des loups. Vous ne pouvez pas protéger la même personne deux nuits consécutives.",
        "ui_icon": "SA",
    },
    "Renard": {
        "camp": "Village",
        "aura": "Claire",
        "max": 1,
        "night_action": True,
        "weight": 1.2,
        "description": "Chaque nuit, choisissez 3 joueurs : vous saurez s'il y a un loup parmi eux. Si vous vous trompez (aucun loup parmi les 3), vous perdez définitivement ce pouvoir.",
        "ui_icon": "RE",
    },
    "Enfant sauvage": {
        "camp": "Village / Loups",
        "aura": "Claire",
        "max": 1,
        "night_action": True,
        "weight": 0.8,
        "description": "La première nuit, vous choisissez un mentor parmi les joueurs vivants. Si votre mentor meurt (quelle qu'en soit la cause), vous basculez du côté des loups.",
        "ui_icon": "ES",
    },
    "Villageois Maudit": {
        "camp": "Village / Loups",
        "aura": "Claire",
        "max": 1,
        "night_action": False,
        "weight": 0.8,
        "description": "Villageois ordinaire au départ. Si les loups vous choisissent comme victime une nuit, au lieu de mourir vous vous transformez en loup-garou. Ce pouvoir ne se déclenche qu'une seule fois.",
        "ui_icon": "VM",
    },
    "Sirène": {
        "camp": "Solo",
        "aura": "Inconnue",
        "max": 1,
        "night_action": True,
        "weight": 1.1,
        "description": "Chaque nuit, vous envoûtez un joueur. Vous gagnez seule si tous les joueurs encore en vie (hors vous) sont envoûtés au moment de la vérification de victoire.",
        "ui_icon": "SI",
    },
    "Pyromane": {
        "camp": "Solo",
        "aura": "Inconnue",
        "max": 1,
        "night_action": True,
        "weight": 1.3,
        "description": "Chaque nuit, vous aspergez un joueur d'essence (ou allumez le feu pour tuer tous les aspergés). Vous gagnez seul si vous éliminez ainsi tous les autres joueurs en vie.",
        "ui_icon": "PY",
    },
    "Villageois": {
        "camp": "Village",
        "aura": "Claire",
        "max": 99,
        "night_action": False,
        "weight": 1.0,
        "description": "Le villageois n'a pas de pouvoir spécial et vote le jour pour éliminer les loups.",
        "ui_icon": "VI",
    },
}

AVAILABLE_ROLES = [role for role in ROLE_CATALOG.keys() if role != "Villageois"]
ROLES_ORDER = list(AVAILABLE_ROLES) + ["Villageois"]

CLASSIC_ROLE_NAMES = ["Loup-garou", "Voyante", "Sorcière", "Villageois"]
SPECIAL_ROLE_NAMES = [
    "Infect Père des Loups",
    "Cupidon",
    "Chasseur",
    "Salvateur",
    "Renard",
    "Enfant sauvage",
    "Villageois Maudit",
    "Sniper",
    "Sirène",
    "Pyromane",
]

DEFAULT_ROLE_CONFIG = {
    "Loup-garou": 1,
    "Voyante": 1,
    "Sorcière": 1,
}

# Groupes de rôles mutuellement exclusifs : dans chaque groupe,
# un seul rôle peut être actif (count > 0) à la fois.
EXCLUSIVE_ROLE_GROUPS = [
    {"Enfant sauvage", "Villageois Maudit"},
]

# Ordre officiel des tours de nuit
NIGHT_ORDER = [
    "cupidon",    # nuit 1 seulement
    "wild_child", # nuit 1 seulement
    "seer",
    "wolves",
    "father",
    "witch",
    "salvateur",
    "fox",
    "siren",
    "arsonist",
]


def role_details(role_name):
    """
    Retourne le dictionnaire de détails d'un rôle depuis le catalogue, ou les détails de Villageois si inconnu.

    :param role_name: Nom du rôle recherché (str).
    :return: dict avec les clés 'camp', 'aura', 'max', 'night_action', 'weight', 'description', 'ui_icon'.
    """
    return ROLE_CATALOG.get(role_name, ROLE_CATALOG["Villageois"])


def is_wolf_role(role_name):
    """
    Retourne True si le nom de rôle correspond à un rôle loup de base.

    :param role_name: Nom du rôle à tester (str).
    :return: bool
    """
    return role_name in {"Loup-garou", "Infect Père des Loups"}


def is_wolf_player(player):
    """Un joueur est loup s'il a un rôle loup, s'il est infecté, ou si l'Enfant sauvage a basculé."""
    return (is_wolf_role(player.get("role", ""))
            or player.get("infected", False)
            or player.get("wild_child_turned", False)
            or player.get("maudit_converted", False))


def check_winner(players):
    """
    Vérifie si une équipe a gagné.
    Retourne "Village", "Loups", "Amoureux", "Sirène", "Pyromane", ou None.
    Les joueurs infectés/convertis comptent dans le camp des loups.
    """
    alive = [p for p in players if p["alive"]]
    if not alive:
        return "Village"

    # Amoureux : exactement les 2 amoureux sont les seuls survivants
    lovers_alive = [p for p in alive if p.get("is_lover")]
    if len(lovers_alive) == 2 and len(alive) == 2:
        return "Amoureux"

    # Sirène : tous les autres vivants sont envoûtés
    siren = next((p for p in alive if p.get("role") == "Sirène"), None)
    if siren:
        others = [p for p in alive if p["id"] != siren["id"]]
        if others and all(p.get("is_charmed") for p in others):
            return "Sirène"

    # Pyromane : tous les autres vivants sont aspergés (vérifié après ignition dans le code appelant)
    pyro = next((p for p in alive if p.get("role") == "Pyromane"), None)
    if pyro:
        others = [p for p in alive if p["id"] != pyro["id"]]
        if not others:
            return "Pyromane"

    alive_wolves = sum(1 for p in alive if is_wolf_player(p))
    alive_non_wolves = len(alive) - alive_wolves

    if alive_wolves == 0:
        return "Village"
    if alive_wolves >= alive_non_wolves:
        return "Loups"
    return None


def exclusive_role_conflict(role_name: str, role_config: dict) -> str | None:
    """
    Vérifie si l'ajout du rôle role_name entraîne un conflit d'exclusivité.
    Retourne un message d'erreur si conflit, sinon None.

    :param role_name: Nom du rôle que l'on tente d'activer (str).
    :param role_config: Config actuelle {nom_rôle: quantité} (dict).
    :return: str message d'erreur ou None.
    """
    for group in EXCLUSIVE_ROLE_GROUPS:
        if role_name in group:
            conflicting = [r for r in group if r != role_name and role_config.get(r, 0) > 0]
            if conflicting:
                names = " et ".join(conflicting)
                return f"« {role_name} » est incompatible avec « {names} » (choisir l'un ou l'autre)."
    return None


def normalize_role_config(role_config=None):
    """
    Retourne une configuration de rôles normalisée en appliquant les valeurs par défaut et en respectant les maximums.

    :param role_config: Dict optionnel {nom_rôle: quantité} fourni par l'utilisateur (dict ou None).
    :return: dict {nom_rôle: quantité} complet pour tous les rôles disponibles.
    """
    config = {role: 0 for role in AVAILABLE_ROLES}
    for role, value in DEFAULT_ROLE_CONFIG.items():
        config[role] = value
    if role_config:
        for role in AVAILABLE_ROLES:
            value = int(role_config.get(role, config.get(role, 0)))
            max_count = ROLE_CATALOG[role]["max"]
            if role == "Loup-garou":
                config[role] = max(1, min(max_count, value))
            else:
                config[role] = max(0, min(max_count, value))
    return config


def configured_special_roles(role_config=None):
    """
    Retourne la liste aplatie des rôles spéciaux actifs selon la configuration (sans les Villageois de remplissage).

    :param role_config: Dict optionnel {nom_rôle: quantité} (dict ou None).
    :return: list[str] — liste des noms de rôles répétés selon leur quantité.
    """
    config = normalize_role_config(role_config)
    roles = []
    for role in AVAILABLE_ROLES:
        roles.extend([role] * config.get(role, 0))
    return roles


def min_players_for_config(role_config=None):
    """
    Retourne le nombre minimum de joueurs requis pour la configuration donnée.

    :param role_config: Dict optionnel {nom_rôle: quantité} (dict ou None).
    :return: int
    """
    return max(MIN_PLAYERS, len(configured_special_roles(role_config)))


def role_config_error(player_count, role_config=None):
    """
    Retourne un message d'erreur si le nombre de joueurs est insuffisant pour la configuration, sinon None.

    :param player_count: Nombre de joueurs dans la partie (int).
    :param role_config: Dict optionnel {nom_rôle: quantité} (dict ou None).
    :return: str ou None
    """
    required = min_players_for_config(role_config)
    if player_count < required:
        return f"Il faut au moins {required} joueurs pour cette composition."
    return None


def camp_balance(player_count, role_config=None):
    """
    Calcule et retourne les ratios de puissance Village/Loups pour la configuration donnée.

    :param player_count: Nombre total de joueurs (int).
    :param role_config: Dict optionnel {nom_rôle: quantité} (dict ou None).
    :return: dict avec les clés 'village_ratio', 'wolves_ratio', 'counts' (float, float, dict).
    """
    config = normalize_role_config(role_config)
    wolf_power    = 0.0
    village_power = 0.0
    n_wolves = 0
    n_village_specials = 0

    for role, count in config.items():
        if count == 0:
            continue
        det = ROLE_CATALOG.get(role, {})
        w   = det.get("weight", 1.0)
        camp = det.get("camp", "Village")
        if camp == "Loups":
            wolf_power += w * count
            n_wolves += count
        else:
            village_power += w * count
            n_village_specials += count

    n_plain_villagers = max(0, player_count - n_wolves - n_village_specials)
    village_power += n_plain_villagers * ROLE_CATALOG["Villageois"]["weight"]

    total = wolf_power + village_power
    if total <= 0 or player_count <= 0:
        return {"village_ratio": 0.5, "wolves_ratio": 0.5,
                "counts": {"Villageois": 0, "Loups": 0}}

    return {
        "village_ratio": village_power / total,
        "wolves_ratio":  wolf_power / total,
        "counts": {
            "Villageois": player_count - n_wolves,
            "Loups":      n_wolves,
            "Specials":   n_village_specials,
        },
    }


def build_roles(player_count, role_config=None):
    """
    Génère et retourne une liste de rôles mélangés pour une partie, complétée par des Villageois.

    :param player_count: Nombre de joueurs (int), doit être >= MIN_PLAYERS.
    :param role_config: Dict optionnel {nom_rôle: quantité} (dict ou None).
    :return: list[str] — liste des noms de rôles dans un ordre aléatoire.
    :raises ValueError: Si player_count est trop faible ou si trop de rôles spéciaux sont configurés.
    """
    if player_count < MIN_PLAYERS:
        raise ValueError(f"Il faut au moins {MIN_PLAYERS} joueurs.")
    roles = configured_special_roles(role_config)
    if len(roles) > player_count:
        raise ValueError("Trop de rôles spéciaux pour ce nombre de joueurs.")
    while len(roles) < player_count:
        roles.append("Villageois")
    random.shuffle(roles)
    return roles


def role_config_label(role_config):
    """
    Retourne une chaîne lisible résumant la configuration de rôles actifs, ex. : « Loup-garou, Voyante x2 ».

    :param role_config: Dict {nom_rôle: quantité} (dict).
    :return: str
    """
    config = normalize_role_config(role_config)
    parts = []
    for role in AVAILABLE_ROLES:
        count = config.get(role, 0)
        if count:
            parts.append(role if count == 1 else f"{role} x{count}")
    return ", ".join(parts) if parts else "Villageois uniquement"


def count_alive_by_role(players):
    """
    Retourne un compteur du nombre de joueurs vivants par rôle.

    :param players: Liste de dicts joueurs avec les clés 'alive' et 'role' (list[dict]).
    :return: collections.Counter {nom_rôle: nombre_de_vivants}.
    """
    counter = Counter()
    for p in players:
        if p["alive"]:
            counter[p["role"]] += 1
    return counter


def serialize_players_for(player_id, players, reveal_all=False):
    """
    Sérialise la liste des joueurs du point de vue de player_id.
    Inclut les informations sur les amoureux, les envoûtés, les aspergés, etc.
    """
    data = []
    current_player = players[player_id] if 0 <= player_id < len(players) else None
    current_is_wolf_side = is_wolf_player(current_player) if current_player else False
    my_lover_id = current_player.get("lover_id") if current_player else None

    # Récupère les amoureux côté serveur pour savoir qui peut voir "is_lover"
    cupidon_id = None
    for p in players:
        if p.get("role") == "Cupidon":
            cupidon_id = p["id"]
            break

    for p in players:
        entry = {
            "id":             p["id"],
            "name":           p["name"],
            "alive":          p["alive"],
            "revealed_role":  p.get("revealed_role"),
            "infected":       False,
            # is_lover visible uniquement : soi-même, son partenaire, Cupidon, fin de partie
            "is_lover":       False,
            "lover_id":       None,
            "is_charmed":     p.get("is_charmed", False),
            "is_fueled":      p.get("is_fueled", False),
            "wild_child_turned": False,
            "maudit_converted":  False,
        }

        can_see_role = (reveal_all
                        or p["id"] == player_id
                        or (is_wolf_player(p) and current_is_wolf_side)
                        or my_lover_id == p["id"])

        # Peut voir les infos d'amoureux si : soi-même, son partenaire amoureux, Cupidon, ou fin de partie
        can_see_lover = (reveal_all
                         or p["id"] == player_id
                         or (current_player is not None and current_player.get("is_lover")
                             and (p["id"] == my_lover_id or player_id == p.get("lover_id")))
                         or player_id == cupidon_id)

        if can_see_lover and p.get("is_lover"):
            entry["is_lover"] = True
            entry["lover_id"] = p.get("lover_id")

        if can_see_role:
            entry["role"]              = p["role"]
            entry["infected"]          = p.get("infected", False)
            entry["wild_child_turned"] = p.get("wild_child_turned", False)
            entry["maudit_converted"]  = p.get("maudit_converted", False)
        data.append(entry)
    return data
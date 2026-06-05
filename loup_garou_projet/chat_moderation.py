"""
chat_moderation.py – Filtre automatique des messages du chat.

Charge une liste de termes interdits depuis un fichier CSV et remplace
les occurrences trouvées par des astérisques. Supporte les variantes
leetspeak (ex: "1" → "i/l/!"), les séparateurs multiples, la
normalisation des accents, la réduction des lettres répétées et les
acronymes à points.

Format CSV attendu : colonnes canonical_term, variants_or_patterns, acronym,
match_type (word | substring | phrase | acronym | pattern), category.
"""
import csv
import re
import unicodedata
from pathlib import Path


def _strip_accents(text: str) -> str:
    """Convertit les lettres accentuées en leur équivalent ASCII (é→e, à→a, ç→c…)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    """
    Normalise un message avant comparaison :
    - minuscules
    - suppression des accents
    - réduction des lettres répétées (coooonnard → conard)
    - suppression des séparateurs intercalés (f.d.p → fdp, f_d_p → fdp)
    """
    text = text.lower()
    text = _strip_accents(text)
    # Réduction des répétitions de caractères (3+ occurrences → 2)
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    # Suppression des séparateurs courants entre les lettres
    text = re.sub(r"(?<=[a-z0-9])([.\-_*!]{1,3})(?=[a-z0-9])", "", text)
    return text


class ChatModerator:
    def __init__(self, csv_path):
        """
        Initialise le modérateur en chargeant les patterns de modération depuis le fichier CSV.

        :param csv_path: Chemin vers le fichier CSV de termes interdits (str ou Path).
        """
        self.csv_path = Path(csv_path)
        self.patterns = []   # liste de (regex_originale, regex_normalisée, match_type)
        self._load_patterns()

    # ── Compilation ───────────────────────────────────────────────────────────

    @staticmethod
    def _leet(text: str) -> str:
        """
        Remplace les caractères dans un pattern regex pour qu'ils correspondent
        aussi à leurs équivalents visuels leetspeak et inversement.
        Ex : "o" → "[0o]", "0" → "[0o]", "a" → "[4a@]", "4" → "[4a@]".
        """
        # Correspondances bidirectionnelles chiffre↔lettre
        replacements = [
            ("0",  "[0o]"),
            ("o",  "[0o]"),
            ("1",  "[1i!l]"),
            ("i",  "[1i!l]"),
            ("l",  "[1il!]"),
            ("3",  "[3e]"),
            ("e",  "[3e]"),
            ("4",  "[4a@]"),
            ("a",  "[4a@]"),
            ("5",  "[5s$]"),
            ("s",  "[5s$]"),
            ("7",  "[7t]"),
            ("t",  "[7t]"),
            ("8",  "[8b]"),
            ("b",  "[8b]"),
            ("9",  "[9g]"),
            ("g",  "[9g]"),
        ]
        result = []
        i = 0
        while i < len(text):
            ch = text[i]
            found = False
            for src, dst in replacements:
                if ch == src:
                    result.append(dst)
                    found = True
                    break
            if not found:
                result.append(re.escape(ch))
            i += 1
        return "".join(result)

    def _build_regex_for_term(self, term: str, match_type: str):
        """
        Construit une regex pour un terme unique (après normalisation/leet).
        Retourne (regex_brute, regex_normalisée) ou None si terme vide.
        """
        term = (term or "").strip().lower()
        if not term:
            return None

        # Séparateur | pour les variantes au sein d'un même champ
        variants = [v.strip() for v in term.split("|") if v.strip()]
        if not variants:
            return None

        def make_pattern(variant: str, normalized: bool) -> str:
            """Fabrique un pattern regex pour une variante donnée."""
            if normalized:
                # Sur le texte normalisé, leetspeak et accents sont déjà résolus
                # On autorise quand même des séparateurs entre les chars
                chars = list(_strip_accents(variant.lower()))
                # Réduire les répétitions dans la variante aussi
                chars_str = re.sub(r"(.)\1{2,}", r"\1\1", "".join(chars))
                escaped = re.escape(chars_str)
                # Autorise 0 ou 1 séparateur entre chaque caractère sur le texte normalisé
                return escaped
            else:
                # Sur le texte original : leet + séparateurs optionnels + accents
                stripped = _strip_accents(variant.lower())
                built = self._leet(stripped)
                # Autorise séparateurs intercalés
                built = re.sub(r"(?<=\w)\\s\+(?=\w)", r"[\\s._*-]*", built)
                return built

        def wrap_boundary(pattern: str, mt: str) -> str:
            """Entoure le pattern avec les assertions de limite adaptées au type."""
            if mt in ("word", "acronym"):
                return rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
            # phrase / substring / pattern → pas de limite stricte
            return pattern

        raw_parts  = [wrap_boundary(make_pattern(v, False), match_type) for v in variants]
        norm_parts = [wrap_boundary(make_pattern(v, True),  match_type) for v in variants]

        joined_raw  = "(?:" + "|".join(raw_parts)  + ")"
        joined_norm = "(?:" + "|".join(norm_parts) + ")"

        try:
            rx_raw  = re.compile(rf"(?i){joined_raw}")
            rx_norm = re.compile(rf"(?i){joined_norm}")
            return rx_raw, rx_norm
        except re.error:
            return None

    def _load_patterns(self):
        """Charge les patterns depuis le CSV. Les lignes 'normalization_rule' sont ignorées."""
        if not self.csv_path.exists():
            return
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                cat = (row.get("category") or "").strip().lower()
                if cat == "normalization_rule":
                    continue
                match_type = (row.get("match_type") or "word").strip().lower()
                # Chaque ligne peut fournir jusqu'à 3 formes du même terme
                values = [
                    row.get("canonical_term", ""),
                    row.get("variants_or_patterns", ""),
                    row.get("acronym", ""),
                ]
                for value in values:
                    result = self._build_regex_for_term(value, match_type)
                    if result is not None:
                        self.patterns.append(result)

    # ── Modération ───────────────────────────────────────────────────────────

    @staticmethod
    def _mask(match):
        """Remplace chaque caractère non-espace par '*'."""
        text = match.group(0)
        return "".join("*" if not ch.isspace() else ch for ch in text)

    def moderate(self, message: str):
        """
        Applique tous les patterns au message (texte brut + version normalisée).
        Retourne (message_nettoyé, a_été_flaggé).

        Stratégie double passe :
        1. Matching sur le texte original (pour leetspeak, séparateurs visibles).
        2. Matching sur le texte normalisé (accents supprimés, répétitions réduites,
           séparateurs invisibles supprimés) afin de détecter les contournements.
        Pour la passe normalisée, les positions trouvées sont reportées sur l'original.
        """
        clean = message
        hit   = False

        # Passe 1 : texte brut avec leet + séparateurs autorisés
        for rx_raw, _ in self.patterns:
            new, count = rx_raw.subn(self._mask, clean)
            if count:
                clean = new
                hit   = True

        # Passe 2 : texte normalisé → reconstruire les remplacements sur le texte original
        norm_message = _normalize(message)
        # On ne reporte que si un match sur la version normalisée n'a PAS déjà été masqué
        # Méthode : masquer dans le texte normalisé, puis aligner position par position
        norm_clean = norm_message
        norm_hit   = False
        for _, rx_norm in self.patterns:
            new, count = rx_norm.subn(self._mask, norm_clean)
            if count:
                norm_clean = new
                norm_hit   = True

        if norm_hit:
            # Reconstruire le masquage sur le message original en se basant sur les '*' du normalisé
            # Approche simple : si la version normalisée est masquée, on masque le message entier
            # pour les zones identifiées (approximation sûre : on censure le mot entier)
            hit = True
            # Réapplication des patterns bruts pour être sûr (le texte normalisé peut
            # différer trop du brut pour un alignement caractère par caractère fiable)
            for rx_raw, _ in self.patterns:
                new, count = rx_raw.subn(self._mask, clean)
                if count:
                    clean = new

            # Dernier filet : si le texte normalisé est presque entièrement masqué,
            # masquer aussi le message original intégralement
            stars_ratio = norm_clean.count("*") / max(1, len(norm_clean))
            if stars_ratio > 0.5 and len(norm_clean) < 30:
                clean = "*" * len(clean)

        return clean, hit

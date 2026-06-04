"""
chat_moderation.py – Filtre automatique des messages du chat.

Charge une liste de termes interdits depuis un fichier CSV et remplace
les occurrences trouvées par des astérisques. Supporte les variantes
leetspeak (ex: "1" → "i/l/!") et les séparateurs multiples.

Format CSV attendu : colonnes canonical_term, variants_or_patterns, acronym,
match_type (word | substring), category.
"""
import csv
import re
from pathlib import Path


class ChatModerator:
    def __init__(self, csv_path):
        """
        Initialise le modérateur en chargeant les patterns de modération depuis le fichier CSV.

        :param csv_path: Chemin vers le fichier CSV de termes interdits (str ou Path).
        """
        self.csv_path = Path(csv_path)
        self.patterns = []   # liste de regex compilées, chargées depuis le CSV
        self._load_patterns()

    def _compile_variant(self, text, match_type):
        """
        Compile un terme (ou liste de termes séparés par |) en regex.
        Applique des substitutions leetspeak : 0→o, 1→i/l/!, 3→e, etc.
        match_type='word' ajoute des assertions de limite de mot (\b équivalent).
        """
        text = (text or "").strip().lower()
        if not text:
            return None
        parts = re.split(r"\|", text)
        regex_parts = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            escaped = re.escape(part)
            # Autorise des espaces multiples entre les mots
            escaped = escaped.replace(r"\ ", r"\s+")
            escaped = escaped.replace(r"\*", r"[*\\w]?")
            # Correspondances leetspeak communes
            escaped = escaped.replace("0", "[0o]")
            escaped = escaped.replace("1", "[1i!l]")
            escaped = escaped.replace("3", "[3e]")
            escaped = escaped.replace("4", "[4a]")
            escaped = escaped.replace("5", "[5s]")
            escaped = escaped.replace("7", "[7t]")
            regex_parts.append(escaped)
        if not regex_parts:
            return None
        joined = "(?:" + "|".join(regex_parts) + ")"
        # word : détection uniquement quand le terme n'est pas collé à d'autres lettres
        if match_type == "word":
            return re.compile(rf"(?i)(?<!\w){joined}(?!\w)")
        return re.compile(rf"(?i){joined}")

    def _load_patterns(self):
        """Charge les patterns depuis le CSV. Les lignes 'normalization_rule' sont ignorées."""
        if not self.csv_path.exists():
            return
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if (row.get("category") or "").strip().lower() == "normalization_rule":
                    continue
                match_type = (row.get("match_type") or "word").strip().lower()
                # Chaque ligne peut fournir jusqu'à 3 formes du même terme
                values = [
                    row.get("canonical_term", ""),
                    row.get("variants_or_patterns", ""),
                    row.get("acronym", ""),
                ]
                for value in values:
                    pattern = self._compile_variant(value, match_type)
                    if pattern is not None:
                        self.patterns.append(pattern)

    @staticmethod
    def _mask(match):
        """Remplace chaque caractère non-espace par '*'."""
        text = match.group(0)
        return "".join("*" if not ch.isspace() else ch for ch in text)

    def moderate(self, message):
        """
        Applique tous les patterns au message.
        Retourne (message_nettoyé, a_été_flaggé).
        """
        clean = message
        hit   = False
        for pattern in self.patterns:
            clean, count = pattern.subn(self._mask, clean)
            if count:
                hit = True
        return clean, hit

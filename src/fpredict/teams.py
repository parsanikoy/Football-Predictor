"""Map Odds API team names to PitchAPI team ids. Fuzzy matches are reported for review."""
import difflib, json, pathlib, re, unicodedata

ALIASES_FILE = pathlib.Path(__file__).resolve().parents[2] / "data" / "team_aliases.json"
_DROP = {"fc", "f", "c", "afc", "cf", "ac", "as", "sc", "bc", "ca", "rc", "and", "hove", "albion", "de",
         "club", "real", "1", "tsg", "fsv", "vfb", "ssc", "us", "calcio"}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w not in _DROP)


def load_aliases():
    return json.loads(ALIASES_FILE.read_text()) if ALIASES_FILE.exists() else {}


def resolve(league, odds_name, teams, aliases=None):
    """teams: {team_id: pitch_name}. Returns (team_id, pitch_name, method)."""
    aliases = aliases if aliases is not None else load_aliases()
    target = aliases.get(league, {}).get(odds_name)
    if target:
        for tid, nm in teams.items():
            if nm == target:
                return tid, nm, "alias"
    by_norm = {norm(v): k for k, v in teams.items()}
    n = norm(odds_name)
    if n in by_norm:
        return by_norm[n], teams[by_norm[n]], "exact"
    best = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.0)
    if not best:
        return None, None, "unmatched"
    tid = by_norm[best[0]]
    return tid, teams[tid], "fuzzy"

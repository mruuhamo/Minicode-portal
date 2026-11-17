from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
TITLES_FILE = DATA_DIR / "recordings" / "titles.txt"
TAXONOMY_FILE = DATA_DIR / "taxonomy" / "taxonomy.yaml"

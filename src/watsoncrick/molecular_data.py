import json
from pathlib import Path

# The lab's own data ships inside the app, so the app is self-contained.
DATA_PATH = Path(__file__).resolve().parent / 'data' / 'molecular_structures.json'


def load_molecular_data():
    """Load molecular structures from JSON."""
    with open(DATA_PATH, 'r') as f:
        return json.load(f)


MOLECULAR_DATA = load_molecular_data()


def get_base(symbol: str):
    """Retrieve molecular data for a base (A, T, G, C)."""
    symbol_to_key = {'A': 'adenine', 'T': 'thymine', 'G': 'guanine', 'C': 'cytosine'}
    key = symbol_to_key.get(symbol.upper())
    if not key:
        raise ValueError(f"Unknown base: {symbol}")
    return MOLECULAR_DATA['bases'][key]


def get_all_bases():
    """Return all four bases."""
    return MOLECULAR_DATA['bases']


def is_purine(symbol: str) -> bool:
    """Check if base is a purine."""
    return get_base(symbol)['category'] == 'purine'


def is_pyrimidine(symbol: str) -> bool:
    """Check if base is a pyrimidine."""
    return get_base(symbol)['category'] == 'pyrimidine'

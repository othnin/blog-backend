import math
from thales.molecular_data import get_base, is_purine, is_pyrimidine


class MolecularValidator:
    """Deterministic validation of base pairs and DNA structures."""

    # Tolerances and constraints (simplified, educational)
    PURINE_WIDTH = 10.8
    PYRIMIDINE_WIDTH = 5.4
    TARGET_PAIR_WIDTH = 10.8
    PAIR_WIDTH_TOLERANCE = 1.0

    HYDROGEN_BOND_DISTANCE = 2.0
    HYDROGEN_BOND_DISTANCE_TOLERANCE = 0.5

    ATOM_RADIUS = 1.7

    @staticmethod
    def calculate_distance(pos1, pos2):
        """3D Euclidean distance."""
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(pos1, pos2)))

    @staticmethod
    def get_pair_width(left_base_data, right_base_data):
        """Approximate pair width from base categories."""
        left_cat = left_base_data['category']
        right_cat = right_base_data['category']

        if left_cat == 'purine' and right_cat == 'pyrimidine':
            return MolecularValidator.PURINE_WIDTH + MolecularValidator.PYRIMIDINE_WIDTH
        elif left_cat == 'pyrimidine' and right_cat == 'purine':
            return MolecularValidator.PYRIMIDINE_WIDTH + MolecularValidator.PURINE_WIDTH
        elif left_cat == 'purine' and right_cat == 'purine':
            return MolecularValidator.PURINE_WIDTH + MolecularValidator.PURINE_WIDTH
        else:  # pyrimidine + pyrimidine
            return MolecularValidator.PYRIMIDINE_WIDTH + MolecularValidator.PYRIMIDINE_WIDTH

    @staticmethod
    def check_hydrogen_bonds(left_base_data, right_base_data):
        """Check if hydrogen bonding sites are compatible."""
        left_sites = left_base_data.get('hydrogenBondSites', [])
        right_sites = right_base_data.get('hydrogenBondSites', [])

        if not left_sites or not right_sites:
            return False

        # Check if left has donors and right has acceptors (or vice versa)
        left_has_donor = any(s.get('type') == 'donor' for s in left_sites)
        left_has_acceptor = any(s.get('type') == 'acceptor' for s in left_sites)
        right_has_donor = any(s.get('type') == 'donor' for s in right_sites)
        right_has_acceptor = any(s.get('type') == 'acceptor' for s in right_sites)

        # Compatible if one side has donors and the other has acceptors
        return (left_has_donor and right_has_acceptor) or (left_has_acceptor and right_has_donor)

    @staticmethod
    def validate_base_pair(left_base: str, right_base: str):
        """
        Validate a proposed base pairing.

        Returns:
        {
            'valid': bool,
            'reasons': [list of failure reasons if invalid],
            'observations': {
                'left_category': 'purine' | 'pyrimidine',
                'right_category': 'purine' | 'pyrimidine',
                'pair_width': float,
                'width_within_tolerance': bool,
                'hydrogen_bonds_align': bool,
            }
        }
        """
        try:
            left_data = get_base(left_base)
            right_data = get_base(right_base)
        except ValueError as e:
            return {
                'valid': False,
                'reasons': [f"Invalid base: {str(e)}"],
                'observations': {}
            }

        observations = {
            'left_category': left_data['category'],
            'right_category': right_data['category'],
        }

        reasons = []
        valid = True

        # Specific base pairing rules: A-T, T-A, G-C, C-G
        valid_pairs = {
            ('A', 'T'), ('T', 'A'), ('G', 'C'), ('C', 'G')
        }

        if (left_base.upper(), right_base.upper()) not in valid_pairs:
            # Invalid base pair combination
            reasons.append('invalid_base_pair')
            valid = False

        # Key rule: purine must pair with pyrimidine (not purine-purine or pyrimidine-pyrimidine)
        left_is_purine = left_data['category'] == 'purine'
        right_is_purine = right_data['category'] == 'purine'

        if left_is_purine == right_is_purine:
            # Both are purines or both are pyrimidines - invalid
            reasons.append('pair_width_inconsistent')
            valid = False

        # Check pair width
        pair_width = MolecularValidator.get_pair_width(left_data, right_data)
        observations['pair_width'] = pair_width
        width_ok = abs(pair_width - MolecularValidator.TARGET_PAIR_WIDTH) <= MolecularValidator.PAIR_WIDTH_TOLERANCE
        observations['width_within_tolerance'] = width_ok

        # For educational purposes, if purine-pyrimidine pairing, hydrogen bonds are automatically compatible
        hbonds_ok = (left_is_purine != right_is_purine)
        observations['hydrogen_bonds_align'] = hbonds_ok

        return {
            'valid': valid,
            'reasons': reasons,
            'observations': observations
        }

    @staticmethod
    def validate_complementary_pairing(bases_list):
        """
        Validate a list of base pairs (for DNA ladder).
        bases_list: [('A', 'T'), ('G', 'C'), ...]

        Returns: {valid, total_pairs, valid_pairs, failures}
        """
        valid_count = 0
        failures = []

        for i, (left, right) in enumerate(bases_list):
            result = MolecularValidator.validate_base_pair(left, right)
            if result['valid']:
                valid_count += 1
            else:
                failures.append({
                    'pair_index': i,
                    'bases': (left, right),
                    'reasons': result['reasons']
                })

        return {
            'valid': len(failures) == 0,
            'total_pairs': len(bases_list),
            'valid_pairs': valid_count,
            'failures': failures
        }

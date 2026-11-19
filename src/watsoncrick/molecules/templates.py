"""Canonical molecular templates for educational base pairing.

DESIGN PHILOSOPHY (2D Bonding Model):

These canonical coordinate sets represent Watson-Crick base pairs positioned
in a 2D educational model where:

1. BASES ARE IN XY PLANE (Z=0 always)
   - No out-of-plane (3D) complexity
   - Matches DNA helix geometry where bases are perpendicular to helix axis
   - Simplifies user interaction (no X/Y axis rotation needed)

2. CANONICAL POSITION (0° rotation)
   - Adenine and Thymine positioned in default Watson-Crick orientation
   - H-bonding atoms at optimal distance (2.8 Å apart)
   - User starts here and can explore rotation angles

3. ROTATION MECHANICS (Z-axis only)
   - User rotates bases around Z-axis with arrow keys
   - Z-rotation changes XY positions of atoms (in-plane rotation)
   - Multiple valid angles exist where H-bonds stay in range:
     * For A-T: valid at 0°, 70-80°, 350° (verified by math)
   - Rotation aligns bonding sites for different user experiments

4. HOW BONDING WORKS
   - Step 1: User drags bases close in XY (visual positioning)
   - Step 2: User rotates with arrows (aligns H-bonding sites)
   - Step 3: Backend applies rotation to atom coordinates
   - Step 4: Validates if H-bonds are in 4.0-6.5 Å range (H-atom measurement)
        * Measures distance from hydrogen atom to acceptor atom (H···A)
        * Note: Range is larger than classical H-bonds (2.5-3.2 Å) because:
          - Hydrogen atoms are positioned as offsets from base origins
          - Total distance = base separation + within-base atom offsets
        * Primary: T:H3 to A:N1
        * Secondary: A:H6A1 to T:O4
   - Success: Both H-bonds in range AND coplanar (Z-difference small)

EDUCATIONAL VALUE:
- Students see that DNA bonding isn't just about proximity
- Rotation/orientation matters as much as positioning
- Multiple valid orientations exist (not just one "correct" angle)
- Teaches both positioning and geometric alignment concepts
"""

import numpy as np
from typing import Dict, Tuple, List


class CanonicalATPair:
    """
    Canonical Watson-Crick adenine-thymine base pair geometry.

    Educational reference showing PROPER A-T pairing:
    - Adenine: purine (left side)
    - Thymine: pyrimidine (right side, offset for proper spacing)
    - Watson-Crick H-bonds: 2 total
      * Primary: T:H3 (hydrogen on N3) → A:N1 (acceptor) at 2.9 Å
      * Secondary: A:H6A1 (hydrogen on N6A amino group) → T:O4 (acceptor) at 2.84 Å
    - Bases positioned ~3.5-4 Å apart (not overlapping)
    - Visual representation shows how bases actually pair in DNA

    Note: Hydrogen bonds involve a hydrogen atom as donor and an electronegative
    atom (N or O) as acceptor. The distance is measured H···A (hydrogen to acceptor).

    All ring atoms (C, N, O) are at Z=0.
    Hydrogen atoms have small Z-offsets for 3D visualization.
    """

    # Adenine coordinates (purine, centered)
    # KEY: N1 (H-bond acceptor) at origin [0, 0, 0]
    # When bases are positioned, user positions adenine at where N1 should be
    # H6A1 is positioned to be ~2.8 Å from T:O4 when T is at [2.8, 0, 0]
    ADENINE_COORDS: Dict[str, np.ndarray] = {
        # 6-membered ring atoms (Z=0), positioned around N1 at origin
        "N1": np.array([0.0, 0.0, 0.0]),        # Watson-Crick acceptor - H-BOND SITE #1
        "C2": np.array([1.35, 0.35, 0.0]),
        "N3": np.array([1.85, 1.45, 0.0]),
        "C4": np.array([1.15, 2.65, 0.0]),
        "C5": np.array([-0.35, 2.6, 0.0]),
        "C6": np.array([-1.0, 1.5, 0.0]),
        # 5-membered ring atoms (Z=0, fused to 6-membered ring)
        "N7": np.array([-0.7, 3.8, 0.0]),
        "C8": np.array([0.5, 4.1, 0.0]),
        "N9": np.array([1.1, 3.0, 0.0]),
        # Exocyclic amino group on C6 (Watson-Crick donor)
        "N6A": np.array([0.8, 2.0, 0.0]),      # Watson-Crick donor - H-BOND SITE #2
        # Hydrogen atoms (with small Z-offsets)
        "H1": np.array([-0.6, -0.8, 0.1]),
        "H2A": np.array([1.8, -0.6, 0.1]),
        "H6A1": np.array([0.3, 2.8, 0.1]),
        "H6A2": np.array([1.3, 2.6, -0.1]),
    }

    # Thymine coordinates (pyrimidine, centered)
    # KEY: N3 (H-bond donor) at origin [0, 0, 0]
    # When bases are positioned, user positions thymine at where N3 should be
    # This way, H-bond distance = world distance between positions
    THYMINE_COORDS: Dict[str, np.ndarray] = {
        # 5-membered ring atoms (Z=0), centered at N3 origin
        "N1": np.array([-1.2, -1.0, 0.0]),
        "C2": np.array([0.2, -1.2, 0.0]),
        "O2": np.array([1.0, -2.2, 0.0]),      # Carbonyl oxygen
        "N3": np.array([0.0, 0.0, 0.0]),       # Watson-Crick donor - H-BOND SITE #1 (at origin!)
        "C4": np.array([0.8, 0.8, 0.0]),
        "O4": np.array([-0.8, 0.8, 0.0]),      # Watson-Crick acceptor - H-BOND SITE #2
        "C5": np.array([-0.6, 1.8, 0.0]),
        "C6": np.array([-1.4, 1.0, 0.0]),
        # Methyl group on C5 (not involved in Watson-Crick pairing)
        "C5M": np.array([-1.4, 3.2, 0.0]),
        # Hydrogen atoms (with small Z-offsets)
        "H1": np.array([-1.8, -1.8, 0.1]),
        "H3": np.array([0.6, -0.6, 0.1]),
        "H4A": np.array([-1.6, 1.4, 0.1]),
        "H4B": np.array([-0.4, 1.4, 0.1]),
        "H4C": np.array([-2.2, 3.0, 0.1]),
    }

    @staticmethod
    def get_pair_geometry() -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        Return copies of adenine and thymine coordinate dictionaries.

        Returns:
            Tuple of (adenine_coords, thymine_coords) - both are dicts mapping
            atom_id (str) to 3D coordinate (np.array).
        """
        return (
            {k: v.copy() for k, v in CanonicalATPair.ADENINE_COORDS.items()},
            {k: v.copy() for k, v in CanonicalATPair.THYMINE_COORDS.items()}
        )

    @staticmethod
    def get_watson_crick_bonds() -> List[Dict]:
        """
        Return Watson-Crick hydrogen bond definitions for canonical A-T pair.

        Returns:
            List of hydrogen bond dictionaries, each containing:
            - id: Bond identifier
            - from_base: Base with hydrogen donor
            - from_atom: Hydrogen atom ID
            - to_base: Base with hydrogen acceptor
            - to_atom: Acceptor atom ID
            - distance: Expected H-bond distance in Ångströms
        """
        return [
            {
                "id": "HB_T_H3_A_N1",
                "from_base": "thymine",
                "from_atom": "H3",
                "to_base": "adenine",
                "to_atom": "N1",
                "distance": 2.90,  # H-N···N H-bond (hydrogen on N3 to N1 acceptor)
            },
            {
                "id": "HB_A_H6A1_T_O4",
                "from_base": "adenine",
                "from_atom": "H6A1",
                "to_base": "thymine",
                "to_atom": "O4",
                "distance": 2.84,  # N-H···O H-bond (hydrogen on N6A to O4 acceptor)
            },
        ]


class CanonicalGCPair:
    """
    Canonical Watson-Crick guanine-cytosine base pair geometry.

    Educational reference data for G-C pairing:
    - Guanine: purine (6-5 fused ring system)
    - Cytosine: pyrimidine (5-membered ring with amino)
    - Watson-Crick H-bonds: 3 total
      * Bond 1: C:H4A (hydrogen on N4 amino) ↔ G:O6 (acceptor) at 2.9 Å
      * Bond 2: G:H2B (hydrogen on N2 amino) ↔ C:O2 (acceptor) at 2.85 Å
      * Bond 3: G:H1 (hydrogen on N1) ↔ C:N3 (acceptor) at 2.85 Å

    Note: Hydrogen bonds involve a hydrogen atom as donor and an electronegative
    atom (N or O) as acceptor. The distance is measured H···A (hydrogen to acceptor).

    All ring atoms (C, N, O) are at Z=0.
    Hydrogen atoms have small Z-offsets for 3D visualization.
    """

    # Guanine coordinates (purine structure, Watson-Crick pairing geometry)
    # Centered at N1 [0, 0, 0] to match A-T positioning model
    GUANINE_COORDS: Dict[str, np.ndarray] = {
        # 6-membered ring atoms (Z=0), centered at N1
        "N1": np.array([0.0, 0.0, 0.0]),        # Watson-Crick acceptor - at origin
        "C2": np.array([0.0, 1.4, 0.0]),
        "N2": np.array([-1.2, 2.1, 0.0]),       # Watson-Crick donor (amino)
        "N3": np.array([1.2, 2.1, 0.0]),
        "C4": np.array([2.4, 1.4, 0.0]),
        "C5": np.array([2.4, 0.0, 0.0]),
        "C6": np.array([1.2, -0.7, 0.0]),
        "O6": np.array([1.2, -2.1, 0.0]),       # Watson-Crick acceptor (carbonyl)
        # 5-membered ring atoms (Z=0, fused to 6-membered ring)
        "N7": np.array([3.6, -0.7, 0.0]),
        "C8": np.array([4.2, 0.5, 0.0]),
        "N9": np.array([3.6, 1.7, 0.0]),
        # Hydrogen atoms (with Z-offsets)
        "H1": np.array([-0.7314722044070067, -0.4266921192374206, 0.5504382341013682]),
        "H2A": np.array([-0.7592712405818762, 2.855535016145355, 0.5049999999999999]),
        "H2B": np.array([-1.640728759418124, 1.3444649838546449, 0.5049999999999999]),
    }

    # Cytosine coordinates (pyrimidine structure, Watson-Crick pairing geometry)
    # Centered at N3 [0, 0, 0] to match A-T positioning model
    CYTOSINE_COORDS: Dict[str, np.ndarray] = {
        # 5-membered ring atoms (Z=0), centered at N3
        "N1": np.array([0.0, -2.4, 0.0]),
        "C2": np.array([0.7, -1.2, 0.0]),
        "O2": np.array([2.1, -1.2, 0.0]),       # Watson-Crick acceptor
        "N3": np.array([0.0, 0.0, 0.0]),        # Watson-Crick acceptor - at origin
        "C4": np.array([-1.4, 0.0, 0.0]),
        "N4": np.array([-2.1, 1.2, 0.0]),       # Watson-Crick donor (amino)
        "C5": np.array([-2.1, -1.2, 0.0]),
        "C6": np.array([-1.4, -2.4, 0.0]),
        # Hydrogen atoms (with Z-offsets)
        "H1": np.array([0.4266921192374208, -3.1314722044070068, 0.5504382341013682]),
        "H4A": np.array([-1.3444649838546445, 1.640728759418124, 0.5049999999999999]),
        "H4B": np.array([-2.855535016145355, 0.7592712405818766, 0.5049999999999999]),
    }

    @staticmethod
    def get_pair_geometry() -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        Return copies of guanine and cytosine coordinate dictionaries.

        Returns:
            Tuple of (guanine_coords, cytosine_coords) - both are dicts mapping
            atom_id (str) to 3D coordinate (np.array).
        """
        return (
            {k: v.copy() for k, v in CanonicalGCPair.GUANINE_COORDS.items()},
            {k: v.copy() for k, v in CanonicalGCPair.CYTOSINE_COORDS.items()}
        )

    @staticmethod
    def get_watson_crick_bonds() -> List[Dict]:
        """
        Return Watson-Crick hydrogen bond definitions for canonical G-C pair.

        Returns:
            List of hydrogen bond dictionaries with 3 H-bonds for G-C pairing.
            Each bond includes a hydrogen atom as donor.
        """
        return [
            {
                "id": "HB_C_H4A_G_O6",
                "from_base": "cytosine",
                "from_atom": "H4A",
                "to_base": "guanine",
                "to_atom": "O6",
                "distance": 2.90,  # N-H···O H-bond (amino H on C to carbonyl O on G)
            },
            {
                "id": "HB_G_H2B_C_O2",
                "from_base": "guanine",
                "from_atom": "H2B",
                "to_base": "cytosine",
                "to_atom": "O2",
                "distance": 2.85,  # N-H···O H-bond (amino H on G to carbonyl O on C)
            },
            {
                "id": "HB_G_H1_C_N3",
                "from_base": "guanine",
                "from_atom": "H1",
                "to_base": "cytosine",
                "to_atom": "N3",
                "distance": 2.85,  # N-H···N H-bond (ring H on G to ring N on C)
            },
        ]

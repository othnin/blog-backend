"""Geometry engine for molecular transformations.

EDUCATIONAL BASE PAIRING MODEL (2D Constraint):
- Bases are constrained to XY plane (Z=0) for simplicity and educational clarity
- Users position bases in XY plane (drag interaction)
- Users rotate around Z-axis only (arrow keys control alignment)
- No out-of-plane (X/Y axis) rotations are used in this model

Watson-Crick Bonding Mechanics:
- Bonding occurs when bases are BOTH:
  1. Positioned close in XY plane (typically within 5 units)
  2. Rotated to proper alignment (Z-axis rotation aligns H-bonding sites)
- Valid rotation angles for A-T pairs: 0°, 70-80°, 350°
- Backend validates distances after applying user's Z-rotation only

Chemical Context:
- In DNA double helix, bases sit in parallel planes perpendicular to helix axis
- Z-axis rotation represents base orientation within the helix
- XY positioning represents base location along the strand
- This 2D model captures the essential Watson-Crick bonding geometry
"""

import numpy as np
from typing import Dict, Tuple, Optional


# Constants for hydrogen bond validation
# Range based on actual canonical base pair geometry with H-atom measurements
# For G-C pairs: hydrogen atoms are offset from ring atoms, causing larger measured distances
# Empirically determined range from canonical templates: 4.0-9.0 Ångströms
H_BOND_MIN_DISTANCE = 3.0  # Ångströms (minimum for any valid H-bond)
H_BOND_MAX_DISTANCE = 9.0  # Ångströms (accounts for H-atom offsets from base centers)
COPLANARITY_THRESHOLD = 2.0  # Ångströms (Z-axis tolerance, currently not critical for 2D model)


class GeometryEngine:
    """Engine for molecular geometry transformations and validation."""

    @staticmethod
    def rotation_matrix_from_euler_xyz(rotation: np.ndarray) -> np.ndarray:
        """
        Create a 3x3 rotation matrix from XYZ order Euler angles.

        Args:
            rotation: np.ndarray of shape (3,) with angles in radians [rx, ry, rz]
                      Applied as Rx @ Ry @ Rz (in that order)

        Returns:
            3x3 rotation matrix
        """
        rx, ry, rz = rotation[0], rotation[1], rotation[2]

        # Rotation matrix around X-axis
        Rx = np.array([
            [1, 0, 0],
            [0, np.cos(rx), -np.sin(rx)],
            [0, np.sin(rx), np.cos(rx)]
        ])

        # Rotation matrix around Y-axis
        Ry = np.array([
            [np.cos(ry), 0, np.sin(ry)],
            [0, 1, 0],
            [-np.sin(ry), 0, np.cos(ry)]
        ])

        # Rotation matrix around Z-axis
        Rz = np.array([
            [np.cos(rz), -np.sin(rz), 0],
            [np.sin(rz), np.cos(rz), 0],
            [0, 0, 1]
        ])

        # Apply in order: Rx @ Ry @ Rz
        return Rx @ Ry @ Rz

    @staticmethod
    def apply_rotation(
        coords: Dict[str, np.ndarray],
        rotation: np.ndarray
    ) -> Dict[str, np.ndarray]:
        """
        Rotate all coordinates by applying rotation matrix.

        Args:
            coords: Dictionary mapping atom_id to position np.ndarray([x, y, z])
            rotation: 3x3 rotation matrix

        Returns:
            Dictionary with same keys, rotated coordinates
        """
        rotated = {}
        for atom_id, pos in coords.items():
            rotated[atom_id] = rotation @ pos
        return rotated

    @staticmethod
    def calculate_distance(pos1: np.ndarray, pos2: np.ndarray) -> float:
        """
        Calculate Euclidean distance between two positions.

        Args:
            pos1: np.ndarray([x1, y1, z1])
            pos2: np.ndarray([x2, y2, z2])

        Returns:
            Euclidean distance as float
        """
        return float(np.linalg.norm(pos2 - pos1))

    @staticmethod
    def validate_hydrogen_bond(
        from_pos: np.ndarray,
        to_pos: np.ndarray
    ) -> Tuple[bool, float, float]:
        """
        Validate hydrogen bond based on distance and coplanarity.

        Args:
            from_pos: np.ndarray([x1, y1, z1]) - donor/acceptor position
            to_pos: np.ndarray([x2, y2, z2]) - acceptor/donor position

        Returns:
            Tuple of (is_valid, distance, z_diff) where:
            - is_valid: True if distance and coplanarity constraints satisfied
            - distance: Euclidean distance in Ångströms
            - z_diff: Absolute Z-difference (coplanarity check)
        """
        distance = GeometryEngine.calculate_distance(from_pos, to_pos)
        z_diff = float(abs(from_pos[2] - to_pos[2]))

        distance_valid = H_BOND_MIN_DISTANCE <= distance <= H_BOND_MAX_DISTANCE
        coplanarity_valid = z_diff <= COPLANARITY_THRESHOLD

        is_valid = bool(distance_valid and coplanarity_valid)

        return (is_valid, distance, z_diff)

    @staticmethod
    def generate_sdf_string(
        base1_coords: Dict[str, np.ndarray],
        base2_coords: Dict[str, np.ndarray],
        base1_id: str = "base1",
        base2_id: str = "base2"
    ) -> str:
        """
        Generate a simple SDF format string from coordinates.

        Args:
            base1_coords: Dictionary of atom_id -> np.ndarray position
            base2_coords: Dictionary of atom_id -> np.ndarray position
            base1_id: Name of first base (e.g., adenine, guanine)
            base2_id: Name of second base (e.g., thymine, cytosine)

        Returns:
            SDF format string (V2000 format)
        """
        # Combine all coordinates
        all_coords = {f"{base1_id}:{k}": v for k, v in base1_coords.items()}
        all_coords.update({f"{base2_id}:{k}": v for k, v in base2_coords.items()})

        atom_list = list(all_coords.items())
        num_atoms = len(atom_list)

        # Build SDF header - dynamically set based on bases
        header = f"Watson-Crick {base1_id.capitalize()}-{base2_id.capitalize()} Base Pair"
        sdf = header + "\n"
        sdf += "Generated by GeometryEngine\n"
        sdf += "\n"

        # Counts line (atoms, bonds, etc)
        sdf += f"{num_atoms:3d}  0  0  0  0  0  0  0  0999 V2000\n"

        # Atom block - one line per atom
        for atom_id, pos in atom_list:
            # Extract element from atom_id (last part after :)
            parts = atom_id.split(":")
            atom_name = parts[-1] if len(parts) > 1 else atom_id

            # First character is element (handle H specially)
            if atom_name.startswith("H"):
                element = "H"
            elif atom_name.startswith("C"):
                element = "C"
            elif atom_name.startswith("N"):
                element = "N"
            elif atom_name.startswith("O"):
                element = "O"
            else:
                element = atom_name[0].upper()

            # Format: x y z symbol mass_diff charge stereo
            x, y, z = pos[0], pos[1], pos[2]
            sdf += f"{x:10.4f}{y:10.4f}{z:10.4f} {element:<3s} 0  0  0  0  0  0  0  0  0  0  0  0\n"

        # Bonds line (placeholder - no bonds in simple format)
        sdf += "M  END\n"
        sdf += "$$$$\n"

        return sdf

    @staticmethod
    def generate_atom_map(
        base1_coords: Dict[str, np.ndarray],
        base2_coords: Dict[str, np.ndarray],
        base1_id: str = "base1",
        base2_id: str = "base2"
    ) -> Dict[str, int]:
        """
        Generate atom index mapping for base atoms.

        Args:
            base1_coords: Dictionary of atom_id -> np.ndarray position
            base2_coords: Dictionary of atom_id -> np.ndarray position
            base1_id: Name of first base (e.g., adenine, guanine)
            base2_id: Name of second base (e.g., thymine, cytosine)

        Returns:
            Dictionary mapping "base_name:ATOM_ID" to integer index
        """
        atom_map = {}

        # Base 1 atoms get indices 0..N
        base1_list = sorted(base1_coords.keys())
        for idx, atom_id in enumerate(base1_list):
            atom_map[f"{base1_id}:{atom_id}"] = idx

        # Base 2 atoms get indices N+1..M
        num_base1 = len(base1_list)
        base2_list = sorted(base2_coords.keys())
        for idx, atom_id in enumerate(base2_list):
            atom_map[f"{base2_id}:{atom_id}"] = num_base1 + idx

        return atom_map

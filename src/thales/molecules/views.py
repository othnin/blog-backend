"""API endpoints for molecular structures and base-pair generation."""

import os
import json
import numpy as np
from typing import Dict
from ninja import Router
from ninja.errors import HttpError

from helpers.api_auth import ThalesAccessJWTAuth
from .schemas import MoleculeDefinition, BasePairRequest, BasePairResponse
from .rdkit_validator import RDKitValidator
from .geometry_engine import GeometryEngine
from .templates import CanonicalATPair, CanonicalGCPair

router = Router(auth=[ThalesAccessJWTAuth()])
MOLECULES: Dict[str, MoleculeDefinition] = {}


def _extract_atom_id_from_hb_site(site_id: str, base_id: str = None) -> str:
    """Extract atom ID from hydrogen bond site ID.

    Handles special naming cases where the HB site doesn't directly match an atom.

    Examples:
        "HB_N1" -> "N1"
        "HB_N6" (adenine) -> "N6A"  # Amino group
        "HB_N7" -> "N7"
    """
    if not site_id.startswith("HB_"):
        return site_id

    atom_hint = site_id[3:]  # Remove "HB_" prefix

    # Special case: HB_N6 in adenine refers to the amino group N6A
    if base_id == "adenine" and atom_hint == "N6":
        return "N6A"

    return atom_hint


def _extract_atom_id_from_attachment(attachment_data: dict) -> str:
    """Extract atom ID from attachment point data.

    Since attachment points don't have explicit atom references in the JSON,
    we infer from common patterns. For base pairing, this is typically N9 (purine).
    """
    # For now, assume attachment is always at the linking atom
    # This is a simplification; Task 6 will make this explicit
    if "atom" in attachment_data:
        return attachment_data["atom"]
    # Default assumption for nucleobases
    return "N9"


def load_molecules():
    """Load molecular definitions from JSON file at module import time."""
    global MOLECULES

    # Construct path to molecular_structures.json
    json_path = os.path.join(
        os.path.dirname(__file__),
        "../../data/molecular_structures.json"
    )

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Molecular structures JSON not found at {json_path}")

    with open(json_path, "r") as f:
        data = json.load(f)

    # Parse each base from the JSON
    for base_id, base_data in data.get("bases", {}).items():
        try:
            # Include all atom data (id, element, position)
            atoms = [
                {
                    "id": atom["id"],
                    "element": atom["element"],
                    "position": atom.get("position", [0, 0, 0])  # fallback to origin if missing
                }
                for atom in base_data.get("atoms", [])
            ]

            # Keep bonds as-is
            bonds = base_data.get("bonds", [])

            # Extract hydrogen bond sites
            # Map from JSON format (with position, orientation) to schema format (atom reference, roles)
            hb_sites = []
            for site in base_data.get("hydrogenBondSites", []):
                atom_id = _extract_atom_id_from_hb_site(site["id"], base_id)

                # Infer roles from site type and atom ID
                # This is a simplification; Task 6 will make roles explicit
                roles = []
                if site["type"] == "acceptor":
                    if "watson_crick" in site.get("roles", []) or atom_id in ["N1", "N3"]:
                        roles.append("watson_crick")
                elif site["type"] == "donor":
                    if "watson_crick" in site.get("roles", []) or atom_id in ["N6A", "O4"]:
                        roles.append("watson_crick")

                # Default roles if none detected
                if not roles:
                    roles.append("watson_crick")

                hb_sites.append({
                    "id": site["id"],
                    "atom": atom_id,
                    "type": site["type"],
                    "roles": roles
                })

            # Extract attachment points
            attachment_points = []
            for ap in base_data.get("attachmentPoints", []):
                atom_id = _extract_atom_id_from_attachment(ap)
                attachment_points.append({
                    "name": ap["name"],
                    "atom": atom_id,
                    "orientation": ap.get("orientation", [0, 0, -1])
                })

            # Create MoleculeDefinition
            mol = MoleculeDefinition(
                id=base_id,
                symbol=base_data["symbol"],
                category=base_data["category"],
                atoms=atoms,
                bonds=bonds,
                hydrogenBondSites=hb_sites,
                attachmentPoints=attachment_points if attachment_points else None
            )

            MOLECULES[base_id] = mol
        except Exception as e:
            print(f"Warning: Error loading molecule {base_id}: {e}")


# Load molecules at import time
load_molecules()


@router.get("/{base}")
def get_molecule(request, base: str):
    """Get molecular definition for a base (topology and coordinates).

    Args:
        base: Base identifier (e.g., 'adenine', 'thymine', 'guanine', 'cytosine')

    Returns:
        MoleculeDefinition with atoms (including positions), bonds, and hydrogen bond sites.

    Raises:
        404: If base not found
    """
    if base not in MOLECULES:
        raise HttpError(404, f"Base '{base}' not found")

    return MOLECULES[base].dict()


@router.post("/base-pairs/")
def post_base_pair(request, data: BasePairRequest):
    """Generate a base-pair geometry with validation.

    Currently supports only:
    - Bases: adenine + thymine
    - Pair type: watson_crick

    Args:
        data: BasePairRequest with base1, base2, pairType, and optional rotations

    Returns:
        BasePairResponse with:
        - molecule.data: SDF string of combined structure
        - atomMap: Atom index mapping
        - educational.hydrogenBonds: List of H-bond geometries
        - validation: Validity of H-bonds and structure

    Raises:
        400: If bases unknown, pair type unsupported, or validation fails
        500: For internal errors
    """
    # Validate that both bases are known
    if data.base1 not in MOLECULES:
        raise HttpError(400, f"Unknown base: {data.base1}")
    if data.base2 not in MOLECULES:
        raise HttpError(400, f"Unknown base: {data.base2}")

    # Validate Watson-Crick pairing rules
    if data.pairType != "watson_crick":
        raise HttpError(400, "Currently only watson_crick pairing is supported")

    # Watson-Crick base pairing rules: A-T and G-C (in any order)
    bases_set = {data.base1, data.base2}
    valid_pairs = [
        {"adenine", "thymine"},
        {"guanine", "cytosine"}
    ]
    if bases_set not in valid_pairs:
        raise HttpError(
            400,
            f"Invalid base pairing: {data.base1} + {data.base2}. Valid Watson-Crick pairs: A-T, G-C"
        )

    try:
        # Determine which pair we're validating
        bases_set = {data.base1, data.base2}
        is_at_pair = bases_set == {"adenine", "thymine"}
        is_gc_pair = bases_set == {"guanine", "cytosine"}

        # Get canonical geometry
        engine = GeometryEngine()
        swapped = False

        if is_at_pair:
            base1_coords, base2_coords = CanonicalATPair.get_pair_geometry()
            hb_bond_defs = CanonicalATPair.get_watson_crick_bonds()
            # Determine which base is which
            if data.base1 == "adenine":
                base1_id, base2_id = "adenine", "thymine"
                swapped = False
            else:
                base1_id, base2_id = "thymine", "adenine"
                base1_coords, base2_coords = base2_coords, base1_coords
                swapped = True
        elif is_gc_pair:
            base1_coords, base2_coords = CanonicalGCPair.get_pair_geometry()
            hb_bond_defs = CanonicalGCPair.get_watson_crick_bonds()
            # Determine which base is which
            if data.base1 == "guanine":
                base1_id, base2_id = "guanine", "cytosine"
                swapped = False
            else:
                base1_id, base2_id = "cytosine", "guanine"
                base1_coords, base2_coords = base2_coords, base1_coords
                swapped = True
        else:
            raise HttpError(400, "Unsupported base pair")

        # If we swapped coordinates, swap the hydrogen bond definitions too
        if swapped:
            hb_bond_defs = [
                {
                    "id": bond["id"],
                    "from_base": bond["to_base"],
                    "from_atom": bond["to_atom"],
                    "to_base": bond["from_base"],
                    "to_atom": bond["from_atom"],
                    "distance": bond["distance"],
                }
                for bond in hb_bond_defs
            ]

        # Apply rotations if provided
        if data.base1Rotation:
            rotation_matrix = engine.rotation_matrix_from_euler_xyz(
                np.array(data.base1Rotation)
            )
            base1_coords = engine.apply_rotation(base1_coords, rotation_matrix)

        if data.base2Rotation:
            rotation_matrix = engine.rotation_matrix_from_euler_xyz(
                np.array(data.base2Rotation)
            )
            base2_coords = engine.apply_rotation(base2_coords, rotation_matrix)

        # Apply translations (positions) if provided
        if data.base1Position:
            translation = np.array(data.base1Position)
            base1_coords = {
                atom_id: pos + translation
                for atom_id, pos in base1_coords.items()
            }

        if data.base2Position:
            translation = np.array(data.base2Position)
            base2_coords = {
                atom_id: pos + translation
                for atom_id, pos in base2_coords.items()
            }

        # Validate molecular structures with RDKit
        validator = RDKitValidator()
        validation_1 = validator.validate(MOLECULES[data.base1])
        validation_2 = validator.validate(MOLECULES[data.base2])

        if not validation_1.valid or not validation_2.valid:
            errors = validation_1.errors + validation_2.errors
            error_msgs = [e.message for e in errors]
            raise HttpError(400, f"Validation failed: {'; '.join(error_msgs)}")

        # Calculate hydrogen bond geometry
        h_bonds = []
        all_valid = True

        for bond_def in hb_bond_defs:
            from_base = bond_def["from_base"]
            from_atom = bond_def["from_atom"]
            to_base = bond_def["to_base"]
            to_atom = bond_def["to_atom"]

            # Get atom positions based on which base is base1 vs base2
            # Use base1_id (what's actually in base1_coords) not data.base1 (what user submitted)
            # because coordinates may have been swapped
            if from_base == base1_id:
                from_pos = base1_coords[from_atom]
                to_pos = base2_coords[to_atom]
            else:
                from_pos = base2_coords[from_atom]
                to_pos = base1_coords[to_atom]

            # Calculate H-bond geometry
            is_valid, distance, z_diff = engine.validate_hydrogen_bond(
                from_pos, to_pos
            )

            h_bonds.append({
                "id": bond_def["id"],
                "from": from_atom,
                "from_base": from_base,
                "to": to_atom,
                "to_base": to_base,
                "distance": distance,
                "valid": is_valid
            })

            if not is_valid:
                all_valid = False

        # Generate SDF (use appropriate base names in order)
        sdf_string = engine.generate_sdf_string(base1_coords, base2_coords, data.base1, data.base2)

        # Generate atom map
        atom_map = engine.generate_atom_map(base1_coords, base2_coords, data.base1, data.base2)

        # Build response
        response = {
            "molecule": {
                "format": "sdf",
                "data": sdf_string
            },
            "atomMap": atom_map,
            "educational": {
                "pairType": data.pairType,
                "bases": [data.base1, data.base2],
                "hydrogenBonds": h_bonds
            },
            "validation": {
                "valid": all_valid,
                "errors": [],
                "warnings": []
            }
        }

        return response

    except HttpError:
        raise
    except Exception as e:
        raise HttpError(500, f"Internal error: {str(e)}")

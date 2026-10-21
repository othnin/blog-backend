"""Pydantic models for molecular structures and base pair geometry."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class AtomDefinition(BaseModel):
    """Definition of a single atom in a molecule.

    Examples:
        - id: "N1", element: "N", position: [-1.2, -0.7, 0.0] (Adenine N1)
        - id: "C2", element: "C", position: [-0.1, 0.1, 0.0] (Adenine C2)
        - id: "N6A", element: "N", position: [1.3, 0.7, 0.0] (Adenine N6 modified)
    """
    id: str = Field(..., description="Unique atom identifier within molecule (e.g., N1, C2, N6A)")
    element: str = Field(..., description="Chemical element symbol (C, N, O, H, S, P)")
    position: List[float] = Field(..., description="3D coordinates [x, y, z] in Angstroms")


class BondDefinition(BaseModel):
    """Definition of a chemical bond between two atoms."""
    atom1: str = Field(..., description="ID of first atom in bond")
    atom2: str = Field(..., description="ID of second atom in bond")
    type: str = Field(..., description="Bond type (single, double, triple, aromatic)")


class HydrogenBondSite(BaseModel):
    """A site on a molecule capable of hydrogen bonding.

    Hydrogen bond sites reference atoms by ID only (no independent coordinates).
    This ensures one source of truth per relationship.
    """
    id: str = Field(..., description="Unique identifier for hydrogen bond site")
    atom: str = Field(..., description="Reference to atom ID in molecule (e.g., N1, O6)")
    type: str = Field(..., description="Type of hydrogen bond (donor, acceptor)")
    roles: List[str] = Field(
        ...,
        description="Possible roles in Watson-Crick interactions (e.g., watson_crick, major_groove)"
    )


class AttachmentPoint(BaseModel):
    """An attachment point on a molecule for connecting to other structures.

    Example:
        - name: "sugar_link"
        - atom: "N9"
        - orientation: [0, 0, -1]
    """
    name: str = Field(..., description="Name of attachment point (e.g., sugar_link)")
    atom: str = Field(..., description="Atom ID where attachment occurs")
    orientation: List[float] = Field(..., description="Normal vector for attachment [x, y, z]")


class MoleculeDefinition(BaseModel):
    """Complete definition of a nucleobase molecule (A, T, G, C).

    This model represents the chemical structure of a base and its interaction sites.
    Hydrogen bond sites reference atoms by ID only, ensuring one source of truth.
    """
    id: str = Field(..., description="Unique molecule identifier (e.g., adenine, thymine)")
    symbol: str = Field(..., description="Single-letter base code (A, T, G, C)")
    category: str = Field(..., description="Base category (purine, pyrimidine)")
    atoms: List[AtomDefinition] = Field(..., description="List of atoms in molecule")
    bonds: List[BondDefinition] = Field(..., description="List of bonds in molecule")
    hydrogenBondSites: List[HydrogenBondSite] = Field(
        ...,
        description="List of hydrogen bonding sites"
    )
    attachmentPoints: Optional[List[AttachmentPoint]] = Field(
        default=None,
        description="Optional list of attachment points for sugar/backbone"
    )


class BasePairRequest(BaseModel):
    """Request to generate a base pair geometry.

    Specifies two bases and their positions/orientations for generating
    the 3D structure of a Watson-Crick base pair.
    """
    base1: str = Field(..., description="ID of first base (e.g., adenine)")
    base2: str = Field(..., description="ID of second base (e.g., thymine)")
    pairType: str = Field(..., description="Type of base pair (watson_crick, wobble)")
    base1Position: Optional[List[float]] = Field(
        default=None,
        description="Optional 3D position [x, y, z] for base1 centroid in Angstroms"
    )
    base2Position: Optional[List[float]] = Field(
        default=None,
        description="Optional 3D position [x, y, z] for base2 centroid in Angstroms"
    )
    base1Rotation: Optional[List[float]] = Field(
        default=None,
        description="Optional Euler angles [rx, ry, rz] in radians for base1"
    )
    base2Rotation: Optional[List[float]] = Field(
        default=None,
        description="Optional Euler angles [rx, ry, rz] in radians for base2"
    )


class HydrogenBondGeometry(BaseModel):
    """Geometric properties of a hydrogen bond between two atoms.

    This mirrors the wire format that POST /api/thales/molecules/base-pairs/
    actually returns. The aliases matter: the JSON keys are "from" and "to"
    (which are reserved words in Python), so the Python attribute names are
    from_atom/to_atom and the aliases restore the JSON spelling.
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique identifier for this hydrogen bond")
    from_atom: str = Field(..., alias="from", description="Donor atom ID")
    from_base: str = Field(..., description="Base the donor atom belongs to")
    to_atom: str = Field(..., alias="to", description="Acceptor atom ID")
    to_base: str = Field(..., description="Base the acceptor atom belongs to")
    distance: float = Field(..., description="Distance in Angstroms")
    valid: bool = Field(..., description="Whether geometry meets validation criteria")


class BasePairResponse(BaseModel):
    """Response containing generated base pair structure and metadata.

    Response includes 3D coordinates, atom mapping, educational metadata,
    and validation results.
    """
    molecule: dict = Field(..., description="3D structure data (SDF or coordinate format)")
    atomMap: dict = Field(..., description="Mapping of atoms between base1 and base2")
    educational: dict = Field(..., description="Educational metadata (H-bonds, roles)")
    validation: dict = Field(..., description="Validation results and warnings")

"""Tests for molecular structure schemas and API endpoints."""

import numpy as np
from django.test import TestCase, Client as DjangoClient
import json
from thales.molecules.schemas import (
    AtomDefinition,
    BondDefinition,
    HydrogenBondSite,
    AttachmentPoint,
    MoleculeDefinition,
    BasePairRequest,
    BasePairResponse,
    HydrogenBondGeometry,
)
from thales.molecules.rdkit_validator import RDKitValidator
from thales.molecules.geometry_engine import GeometryEngine
from thales.molecules.templates import CanonicalATPair
from thales.tests.utils import authenticate, make_thales_user


class MoleculeSchemaTestCase(TestCase):
    def test_atom_definition_valid(self):
        """Test that AtomDefinition instantiates with valid data."""
        atom = AtomDefinition(id="N1", element="N", position=[0.0, 0.0, 0.0])
        assert atom.id == "N1"
        assert atom.element == "N"

        # Test with different examples from brief
        atom_c2 = AtomDefinition(id="C2", element="C", position=[0.0, 0.0, 0.0])
        assert atom_c2.id == "C2"
        assert atom_c2.element == "C"

        atom_n6a = AtomDefinition(id="N6A", element="N", position=[0.0, 0.0, 0.0])
        assert atom_n6a.id == "N6A"
        assert atom_n6a.element == "N"
    def test_bond_definition_valid(self):
        """Test that BondDefinition instantiates with valid bond types."""
        bond = BondDefinition(atom1="N1", atom2="C2", type="single")
        assert bond.atom1 == "N1"
        assert bond.atom2 == "C2"
        assert bond.type == "single"

        # Test other bond types
        for bond_type in ["single", "double", "triple", "aromatic"]:
            bond = BondDefinition(atom1="C1", atom2="N3", type=bond_type)
            assert bond.type == bond_type
    def test_hydrogen_bond_site_valid(self):
        """Test that HydrogenBondSite instantiates with valid data."""
        hb_site = HydrogenBondSite(
            id="HB1",
            atom="N1",
            type="acceptor",
            roles=["watson_crick", "major_groove"]
        )
        assert hb_site.id == "HB1"
        assert hb_site.atom == "N1"
        assert hb_site.type == "acceptor"
        assert hb_site.roles == ["watson_crick", "major_groove"]
    def test_attachment_point_valid(self):
        """Test that AttachmentPoint instantiates with valid data."""
        attach = AttachmentPoint(
            name="sugar_link",
            atom="N9",
            orientation=[0, 0, -1]
        )
        assert attach.name == "sugar_link"
        assert attach.atom == "N9"
        assert attach.orientation == [0, 0, -1]
    def test_molecule_definition_complete(self):
        """Test that MoleculeDefinition with all subfields parses correctly."""
        mol = MoleculeDefinition(
            id="adenine",
            symbol="A",
            category="purine",
            atoms=[
                AtomDefinition(id="N1", element="N", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="C2", element="C", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="N6", element="N", position=[0.0, 0.0, 0.0]),
            ],
            bonds=[
                BondDefinition(atom1="N1", atom2="C2", type="single"),
                BondDefinition(atom1="C2", atom2="N6", type="double"),
            ],
            hydrogenBondSites=[
                HydrogenBondSite(
                    id="HB1",
                    atom="N1",
                    type="acceptor",
                    roles=["watson_crick"]
                ),
                HydrogenBondSite(
                    id="HB2",
                    atom="N6",
                    type="donor",
                    roles=["watson_crick"]
                ),
            ],
            attachmentPoints=[
                AttachmentPoint(
                    name="sugar_link",
                    atom="N9",
                    orientation=[0, 0, -1]
                )
            ]
        )
        assert mol.id == "adenine"
        assert mol.symbol == "A"
        assert mol.category == "purine"
        assert len(mol.atoms) == 3
        assert len(mol.bonds) == 2
        assert len(mol.hydrogenBondSites) == 2
        assert len(mol.attachmentPoints) == 1
    def test_molecule_definition_optional_attachment_points(self):
        """Test that MoleculeDefinition works without optional attachmentPoints."""
        mol = MoleculeDefinition(
            id="thymine",
            symbol="T",
            category="pyrimidine",
            atoms=[
                AtomDefinition(id="O2", element="O", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="C4", element="C", position=[0.0, 0.0, 0.0]),
            ],
            bonds=[
                BondDefinition(atom1="O2", atom2="C4", type="double"),
            ],
            hydrogenBondSites=[
                HydrogenBondSite(
                    id="HB1",
                    atom="O2",
                    type="acceptor",
                    roles=["watson_crick"]
                ),
            ]
        )
        assert mol.attachmentPoints is None
        assert mol.id == "thymine"
    def test_base_pair_request_optional_rotations(self):
        """Test that BasePairRequest with optional rotation defaults works."""
        # Without rotations
        req = BasePairRequest(
            base1="adenine",
            base2="thymine",
            pairType="watson_crick"
        )
        assert req.base1 == "adenine"
        assert req.base2 == "thymine"
        assert req.pairType == "watson_crick"
        assert req.base1Rotation is None
        assert req.base2Rotation is None

        # With rotations
        req_with_rot = BasePairRequest(
            base1="adenine",
            base2="thymine",
            pairType="watson_crick",
            base1Rotation=[1, 0, 0, 0, 1, 0, 0, 0, 1],
            base2Rotation=[1, 0, 0, 0, 1, 0, 0, 0, 1]
        )
        assert req_with_rot.base1Rotation is not None
        assert len(req_with_rot.base1Rotation) == 9
    def test_hydrogen_bond_geometry_valid(self):
        """Test that HydrogenBondGeometry instantiates correctly.

        The field names follow the wire format used by the base-pairs
        endpoint: the JSON keys are "from"/"to" (reserved words in Python),
        so the Python attributes are from_atom/to_atom and the aliases put
        the JSON spelling back.
        """
        hb = HydrogenBondGeometry(
            id="HB_A-T_1",
            from_atom="H6A1",
            from_base="adenine",
            to_atom="O4",
            to_base="thymine",
            distance=2.85,
            valid=True
        )
        assert hb.id == "HB_A-T_1"
        assert hb.from_atom == "H6A1"
        assert hb.from_base == "adenine"
        assert hb.to_atom == "O4"
        assert hb.to_base == "thymine"
        assert hb.distance == 2.85
        assert hb.valid is True

        # The aliases must round-trip back to the JSON spelling, because that
        # is what the API actually puts on the wire.
        dumped = hb.model_dump(by_alias=True)
        assert dumped["from"] == "H6A1"
        assert dumped["to"] == "O4"
        assert "from_atom" not in dumped
    def test_base_pair_response_valid(self):
        """Test that BasePairResponse instantiates with dict fields."""
        response = BasePairResponse(
            molecule={"sdf": "structure_data"},
            atomMap={"A_N1": "T_O2", "A_N6": "T_N3"},
            educational={"hydrogen_bonds": 2, "roles": ["watson_crick"]},
            validation={"valid": True, "warnings": []}
        )
        assert response.molecule == {"sdf": "structure_data"}
        assert response.atomMap == {"A_N1": "T_O2", "A_N6": "T_N3"}
        assert response.educational == {"hydrogen_bonds": 2, "roles": ["watson_crick"]}
        assert response.validation == {"valid": True, "warnings": []}


class RDKitValidatorTestCase(TestCase):
    def test_rdkit_validator_valid_adenine(self):
        """Test RDKit validator with valid adenine-like structure."""
        mol = MoleculeDefinition(
            id="adenine",
            symbol="A",
            category="purine",
            atoms=[
                AtomDefinition(id="N1", element="N", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="C2", element="C", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="C3", element="C", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="N6", element="N", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="N7", element="N", position=[0.0, 0.0, 0.0]),
            ],
            bonds=[
                BondDefinition(atom1="N1", atom2="C2", type="aromatic"),
                BondDefinition(atom1="C2", atom2="C3", type="aromatic"),
                BondDefinition(atom1="C3", atom2="N7", type="aromatic"),
                BondDefinition(atom1="N7", atom2="N1", type="aromatic"),
                BondDefinition(atom1="C2", atom2="N6", type="single"),
            ],
            hydrogenBondSites=[
                HydrogenBondSite(
                    id="HB1",
                    atom="N1",
                    type="acceptor",
                    roles=["watson_crick"]
                ),
                HydrogenBondSite(
                    id="HB2",
                    atom="N6",
                    type="donor",
                    roles=["watson_crick"]
                ),
            ],
            attachmentPoints=[
                AttachmentPoint(
                    name="sugar_link",
                    atom="N1",
                    orientation=[0, 0, -1]
                )
            ]
        )

        validator = RDKitValidator()
        result = validator.validate(mol)

        assert result.valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
    def test_rdkit_validator_invalid_bond_reference(self):
        """Test RDKit validator fails with invalid bond references."""
        mol = MoleculeDefinition(
            id="adenine",
            symbol="A",
            category="purine",
            atoms=[
                AtomDefinition(id="N1", element="N", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="C2", element="C", position=[0.0, 0.0, 0.0]),
            ],
            bonds=[
                BondDefinition(atom1="N1", atom2="C2", type="single"),
                BondDefinition(atom1="N1", atom2="INVALID", type="single"),  # Invalid ref
            ],
            hydrogenBondSites=[
                HydrogenBondSite(
                    id="HB1",
                    atom="N1",
                    type="acceptor",
                    roles=["watson_crick"]
                ),
            ]
        )

        validator = RDKitValidator()
        result = validator.validate(mol)

        assert result.valid is False
        assert len(result.errors) > 0
        assert any(e.type_ == "invalid_bond_reference" for e in result.errors)
    def test_rdkit_validator_invalid_hb_reference(self):
        """Test RDKit validator fails with invalid H-bond site references."""
        mol = MoleculeDefinition(
            id="adenine",
            symbol="A",
            category="purine",
            atoms=[
                AtomDefinition(id="N1", element="N", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="C2", element="C", position=[0.0, 0.0, 0.0]),
            ],
            bonds=[
                BondDefinition(atom1="N1", atom2="C2", type="single"),
            ],
            hydrogenBondSites=[
                HydrogenBondSite(
                    id="HB1",
                    atom="INVALID",  # Invalid atom reference
                    type="acceptor",
                    roles=["watson_crick"]
                ),
            ]
        )

        validator = RDKitValidator()
        result = validator.validate(mol)

        assert result.valid is False
        assert len(result.errors) > 0
        assert any(e.type_ == "invalid_hb_reference" for e in result.errors)
    def test_rdkit_validator_n7_watson_crick_warning(self):
        """Test RDKit validator warns about N7 in Watson-Crick."""
        mol = MoleculeDefinition(
            id="adenine",
            symbol="A",
            category="purine",
            atoms=[
                AtomDefinition(id="N7", element="N", position=[0.0, 0.0, 0.0]),
                AtomDefinition(id="C2", element="C", position=[0.0, 0.0, 0.0]),
            ],
            bonds=[
                BondDefinition(atom1="N7", atom2="C2", type="single"),
            ],
            hydrogenBondSites=[
                HydrogenBondSite(
                    id="HB1",
                    atom="N7",
                    type="acceptor",
                    roles=["watson_crick"]  # N7 in Watson-Crick should warn
                ),
            ]
        )

        validator = RDKitValidator()
        result = validator.validate(mol)

        assert result.valid is True  # Still valid, just warns
        assert len(result.errors) == 0
        assert len(result.warnings) > 0
        assert any(w.type_ == "unusual_chemistry" for w in result.warnings)


class GeometryEngineTestCase(TestCase):
    def test_rotation_matrix_identity(self):
        """Test that zero rotation returns identity matrix."""
        rotation = np.array([0, 0, 0])
        R = GeometryEngine.rotation_matrix_from_euler_xyz(rotation)

        # Should be approximately identity matrix
        assert np.allclose(R, np.eye(3), atol=1e-10)
    def test_rotation_matrix_z_axis(self):
        """Test 90° Z rotation transforms (1,0,0) to (0,1,0)."""
        # 90 degrees = pi/2 radians
        rotation = np.array([0, 0, np.pi/2])
        R = GeometryEngine.rotation_matrix_from_euler_xyz(rotation)

        # Rotate point (1, 0, 0)
        point = np.array([1, 0, 0])
        rotated = R @ point

        # Should be close to (0, 1, 0)
        expected = np.array([0, 1, 0])
        assert np.allclose(rotated, expected, atol=1e-10)
    def test_apply_rotation(self):
        """Test rotating a dictionary of coordinates."""
        # 90 degree Z-axis rotation
        rotation = np.array([0, 0, np.pi/2])
        R = GeometryEngine.rotation_matrix_from_euler_xyz(rotation)

        coords = {
            "atom1": np.array([1.0, 0.0, 0.0]),
            "atom2": np.array([0.0, 1.0, 0.0]),
        }

        rotated = GeometryEngine.apply_rotation(coords, R)

        # atom1 (1,0,0) should become approximately (0,1,0)
        assert np.allclose(rotated["atom1"], np.array([0, 1, 0]), atol=1e-10)

        # atom2 (0,1,0) should become approximately (-1,0,0)
        assert np.allclose(rotated["atom2"], np.array([-1, 0, 0]), atol=1e-10)
    def test_calculate_distance(self):
        """Test Euclidean distance calculation."""
        pos1 = np.array([0, 0, 0])
        pos2 = np.array([3, 4, 0])

        distance = GeometryEngine.calculate_distance(pos1, pos2)

        # 3-4-5 triangle
        assert np.isclose(distance, 5.0)
    def test_validate_hydrogen_bond_valid(self):
        """Test a valid hydrogen bond: inside the distance range and coplanar.

        The accepted range is H_BOND_MIN_DISTANCE..H_BOND_MAX_DISTANCE from
        thales.molecules.geometry_engine, i.e. 3.0-9.0 A for this model.
        """
        from_pos = np.array([0.0, 0.0, 0.0])
        to_pos = np.array([3.5, 0.0, 0.0])  # 3.5 A apart, coplanar

        is_valid, distance, z_diff = GeometryEngine.validate_hydrogen_bond(from_pos, to_pos)

        assert is_valid is True
        assert np.isclose(distance, 3.5)
        assert np.isclose(z_diff, 0.0)

    def test_validate_hydrogen_bond_too_close(self):
        """Test an invalid hydrogen bond that is too close to be a bond."""
        from_pos = np.array([0.0, 0.0, 0.0])
        to_pos = np.array([1.0, 0.0, 0.0])  # 1.0 A apart - below the minimum

        is_valid, distance, z_diff = GeometryEngine.validate_hydrogen_bond(from_pos, to_pos)

        assert is_valid is False
        assert np.isclose(distance, 1.0)
        assert np.isclose(z_diff, 0.0)

    def test_validate_hydrogen_bond_too_far(self):
        """Test an invalid hydrogen bond that is beyond the maximum distance."""
        from_pos = np.array([0.0, 0.0, 0.0])
        to_pos = np.array([10.0, 0.0, 0.0])  # 10.0 A apart - beyond the maximum

        is_valid, distance, z_diff = GeometryEngine.validate_hydrogen_bond(from_pos, to_pos)

        assert is_valid is False
        assert np.isclose(distance, 10.0)
        assert np.isclose(z_diff, 0.0)

    def test_validate_hydrogen_bond_not_coplanar(self):
        """Test an invalid hydrogen bond that breaks the coplanarity rule."""
        from_pos = np.array([0.0, 0.0, 0.0])
        to_pos = np.array([3.5, 0.0, 3.0])  # in range, but 3.0 A out of plane

        is_valid, distance, z_diff = GeometryEngine.validate_hydrogen_bond(from_pos, to_pos)

        assert is_valid is False
        assert np.isclose(distance, np.sqrt(3.5**2 + 3.0**2))
        assert np.isclose(z_diff, 3.0)

    def test_generate_atom_map(self):
        """Test atom map generation with adenine and thymine."""
        adenine_coords = {
            "N1": np.array([0, 0, 0]),
            "C2": np.array([1, 0, 0]),
            "N6": np.array([0, 1, 0]),
        }
        thymine_coords = {
            "N3": np.array([2, 0, 0]),
            "O4": np.array([2, 1, 0]),
        }

        atom_map = GeometryEngine.generate_atom_map(
            adenine_coords, thymine_coords, "adenine", "thymine"
        )

        # Keys are "<base_id>:<ATOM_ID>"
        assert set(atom_map.keys()) == {
            "adenine:N1", "adenine:C2", "adenine:N6",
            "thymine:N3", "thymine:O4",
        }

        # base1 atoms take the first indices, base2 atoms continue after them.
        adenine_indices = sorted(
            v for k, v in atom_map.items() if k.startswith("adenine:")
        )
        thymine_indices = sorted(
            v for k, v in atom_map.items() if k.startswith("thymine:")
        )
        assert adenine_indices == [0, 1, 2]
        assert thymine_indices == [3, 4]
    def test_canonical_at_pair_geometry(self):
        """Test that canonical A-T pair geometry is properly defined."""
        adenine_coords, thymine_coords = CanonicalATPair.get_pair_geometry()

        # Verify adenine has all required atoms
        required_adenine_atoms = {
            "N1", "C2", "N3", "C4", "C5", "C6",  # 6-membered ring
            "N7", "C8", "N9",                      # 5-membered ring
            "N6A",                                 # Amino group
            "H1", "H2A", "H6A1", "H6A2"           # Hydrogen atoms
        }
        assert set(adenine_coords.keys()) == required_adenine_atoms

        # Verify thymine has all required atoms
        required_thymine_atoms = {
            "N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C5M",  # Ring atoms
            "H1", "H3", "H4A", "H4B", "H4C"                           # Hydrogen atoms
        }
        assert set(thymine_coords.keys()) == required_thymine_atoms

        # Verify all coordinates are numpy arrays
        for atom_id, coord in adenine_coords.items():
            assert isinstance(coord, np.ndarray), f"Adenine {atom_id} is not ndarray"
            assert coord.shape == (3,), f"Adenine {atom_id} shape is {coord.shape}, not (3,)"

        for atom_id, coord in thymine_coords.items():
            assert isinstance(coord, np.ndarray), f"Thymine {atom_id} is not ndarray"
            assert coord.shape == (3,), f"Thymine {atom_id} shape is {coord.shape}, not (3,)"
    def test_canonical_at_pair_h_bond_definition(self):
        """Test that Watson-Crick H-bond definitions are correct."""
        bonds = CanonicalATPair.get_watson_crick_bonds()

        # Verify we have exactly 2 H-bonds
        assert len(bonds) == 2, f"Expected 2 H-bonds, got {len(bonds)}"

        # Primary H-bond: T:H3 (donor H) -> A:N1 (acceptor N)
        assert bonds[0]["id"] == "HB_T_H3_A_N1"
        assert bonds[0]["from_base"] == "thymine"
        assert bonds[0]["from_atom"] == "H3"
        assert bonds[0]["to_base"] == "adenine"
        assert bonds[0]["to_atom"] == "N1"

        # Secondary H-bond: A:H6A1 (donor H) -> T:O4 (acceptor O)
        assert bonds[1]["id"] == "HB_A_H6A1_T_O4"
        assert bonds[1]["from_base"] == "adenine"
        assert bonds[1]["from_atom"] == "H6A1"
        assert bonds[1]["to_base"] == "thymine"
        assert bonds[1]["to_atom"] == "O4"

    def test_canonical_at_pair_local_frames_are_centred(self):
        """Each base's local frame is centred on its own Watson-Crick site.

        Adenine is centred on N1 and thymine on N3. That is what makes
        "place the two frames so the sites face each other" meaningful:
        the frames describe each base internally, the *relative* placement
        is supplied by the request.
        """
        adenine_coords, thymine_coords = CanonicalATPair.get_pair_geometry()

        assert np.allclose(adenine_coords["N1"], np.zeros(3))
        assert np.allclose(thymine_coords["N3"], np.zeros(3))

    def test_canonical_at_pair_h_bond_distances_when_placed(self):
        """Both A-T hydrogen bonds are valid once the pair is placed.

        The canonical frames fix each base internally but not relative to
        each other, so a placement offset is needed before the H-bond
        geometry means anything. With thymine 3.6 A to the -X side of
        adenine both bonds fall inside the accepted 3.0-9.0 A range and
        stay coplanar.

        See docs/THALES_INTEGRATION.md for a note on the open question of
        whether these thresholds should be tightened towards the classical
        2.5-3.2 A H-bond range.
        """
        adenine_coords, thymine_coords = CanonicalATPair.get_pair_geometry()
        offset = np.array([-3.6, 0.0, 0.0])
        placed_thymine = {k: v + offset for k, v in thymine_coords.items()}

        # T:H3 -> A:N1
        h3_distance = np.linalg.norm(
            placed_thymine["H3"] - adenine_coords["N1"]
        )
        is_valid, distance, z_diff = GeometryEngine.validate_hydrogen_bond(
            placed_thymine["H3"], adenine_coords["N1"]
        )
        assert np.isclose(distance, h3_distance)
        assert is_valid is True, f"T:H3-A:N1 distance {distance:.2f} A is not valid"

        # A:H6A1 -> T:O4
        h6a1_distance = np.linalg.norm(
            adenine_coords["H6A1"] - placed_thymine["O4"]
        )
        is_valid, distance, z_diff = GeometryEngine.validate_hydrogen_bond(
            adenine_coords["H6A1"], placed_thymine["O4"]
        )
        assert np.isclose(distance, h6a1_distance)
        assert is_valid is True, f"A:H6A1-T:O4 distance {distance:.2f} A is not valid"

# ============================================================================
# API Endpoint Tests (Integration)


# ============================================================================
# API Endpoint Tests (Integration)
# ============================================================================

class MoleculeAPITestCase(TestCase):
    """Integration tests for molecule API endpoints."""
    
    def setUp(self):
        """Set up an authorized test client."""
        self.client = DjangoClient()
        self.user = make_thales_user("molecules-api-user")
        authenticate(self.client, self.user)
    
    def test_get_molecule_adenine(self):
        """Test GET /api/thales/molecules/adenine returns adenine topology."""
        response = self.client.get("/api/thales/molecules/adenine", content_type="application/json")
        
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        
        # Verify topology fields
        self.assertIn("id", data)
        self.assertEqual(data["id"], "adenine")
        self.assertEqual(data["symbol"], "A")
        self.assertEqual(data["category"], "purine")
        
        # Verify atoms (id, element and 3D position)
        self.assertIn("atoms", data)
        self.assertGreater(len(data["atoms"]), 0)
        for atom in data["atoms"]:
            self.assertIn("id", atom)
            self.assertIn("element", atom)
            # The frontend renders atoms from these coordinates, so they
            # are part of the contract.
            self.assertIn("position", atom)
            self.assertEqual(len(atom["position"]), 3)
        
        # Verify bonds
        self.assertIn("bonds", data)
        self.assertGreater(len(data["bonds"]), 0)
        
        # Verify hydrogen bond sites
        self.assertIn("hydrogenBondSites", data)
        self.assertGreater(len(data["hydrogenBondSites"]), 0)
    
    def test_get_molecule_thymine(self):
        """Test GET /api/thales/molecules/thymine returns thymine topology."""
        response = self.client.get("/api/thales/molecules/thymine", content_type="application/json")
        
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data["id"], "thymine")
        self.assertEqual(data["symbol"], "T")
        self.assertEqual(data["category"], "pyrimidine")
    
    def test_get_molecule_not_found(self):
        """Test GET /api/thales/molecules/unknown returns 404."""
        response = self.client.get("/api/thales/molecules/unknown", content_type="application/json")
        
        self.assertEqual(response.status_code, 404)
    
    def test_post_base_pair_at(self):
        """Test POST /api/thales/molecules/base-pairs with adenine-thymine pair.

        The bases are positioned explicitly: the canonical frames fix each
        base internally, but the relative placement is what the request
        supplies, and without it both bases sit on top of each other.
        """
        payload = {
            "base1": "adenine",
            "base2": "thymine",
            "pairType": "watson_crick",
            "base1Position": [0.0, 0.0, 0.0],
            "base2Position": [-3.6, 0.0, 0.0],
        }
        
        response = self.client.post(
            "/api/thales/molecules/base-pairs/",
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        
        # Verify molecule.data (SDF string)
        self.assertIn("molecule", data)
        self.assertIn("data", data["molecule"])
        sdf_string = data["molecule"]["data"]
        self.assertIsInstance(sdf_string, str)
        self.assertGreater(len(sdf_string), 0)
        
        # Verify atomMap
        self.assertIn("atomMap", data)
        self.assertIsInstance(data["atomMap"], dict)
        self.assertGreater(len(data["atomMap"]), 0)
        self.assertTrue(any("adenine:" in key for key in data["atomMap"].keys()))
        self.assertTrue(any("thymine:" in key for key in data["atomMap"].keys()))
        
        # Verify educational metadata
        self.assertIn("educational", data)
        self.assertIn("hydrogenBonds", data["educational"])
        
        h_bonds = data["educational"]["hydrogenBonds"]
        
        # Verify exactly 2 hydrogen bonds
        self.assertEqual(len(h_bonds), 2)
        
        # Verify each H-bond has the wire-format fields
        for hb in h_bonds:
            self.assertIn("id", hb)
            self.assertIn("from", hb)
            self.assertIn("from_base", hb)
            self.assertIn("to", hb)
            self.assertIn("to_base", hb)
            self.assertIn("distance", hb)
            self.assertIn("valid", hb)
            
            # Verify distance is a number inside the accepted range
            distance = hb["distance"]
            self.assertIsInstance(distance, float)
            self.assertGreaterEqual(distance, 3.0)
            self.assertLessEqual(distance, 9.0)
            
            # All bonds should be valid at this placement
            self.assertTrue(hb["valid"])
        
        # Verify Watson-Crick bonds are present
        hb_atoms = [(hb["from"], hb["to"]) for hb in h_bonds]
        self.assertIn(("H3", "N1"), hb_atoms)
        self.assertIn(("H6A1", "O4"), hb_atoms)
        
        # Verify validation results
        self.assertIn("validation", data)
        self.assertIn("valid", data["validation"])
        self.assertTrue(data["validation"]["valid"])

    def test_post_base_pair_too_far_is_invalid(self):
        """Test that bases placed out of range produce invalid H-bonds.

        The endpoint always answers 200 - it reports on the geometry it was
        given rather than rejecting it. Only a pair that cannot exist at all
        is a 400.
        """
        payload = {
            "base1": "adenine",
            "base2": "thymine",
            "pairType": "watson_crick",
            "base1Position": [0.0, 0.0, 0.0],
            "base2Position": [20.0, 0.0, 0.0],
        }
        
        response = self.client.post(
            "/api/thales/molecules/base-pairs/",
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertFalse(data["validation"]["valid"])
        for hb in data["educational"]["hydrogenBonds"]:
            self.assertFalse(hb["valid"])
    
    def test_post_base_pair_unsupported_pair(self):
        """Test POST /api/thales/molecules/base-pairs with unsupported pair returns 400."""
        payload = {
            "base1": "adenine",
            "base2": "guanine",
            "pairType": "watson_crick"
        }
        
        response = self.client.post(
            "/api/thales/molecules/base-pairs/",
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 400)
    
    def test_post_base_pair_unknown_base(self):
        """Test POST /api/thales/molecules/base-pairs with unknown base returns 400."""
        payload = {
            "base1": "adenine",
            "base2": "unknown",
            "pairType": "watson_crick"
        }
        
        response = self.client.post(
            "/api/thales/molecules/base-pairs/",
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 400)
"""RDKit validator for molecular topology and chemical consistency.

This module provides the chemical authority for the backend, validating:
- Bond topology (bonds reference existing atoms)
- Hydrogen bond sites (reference existing atoms)
- Warnings for common chemistry issues (e.g., N7 in Watson-Crick)

Does NOT generate conformers or modify structures.
"""

from typing import List, Optional
from pydantic import BaseModel
from rdkit import Chem
from .schemas import MoleculeDefinition


class ValidationError(BaseModel):
    """A validation error in molecular structure."""
    type_: str
    message: str
    atom_ids: List[str] = []


class ValidationWarning(BaseModel):
    """A validation warning in molecular structure."""
    type_: str
    message: str


class ValidationResult(BaseModel):
    """Result of molecular validation."""
    valid: bool
    errors: List[ValidationError] = []
    warnings: List[ValidationWarning] = []


class RDKitValidator:
    """Validates molecular topology and chemistry consistency."""

    def validate(self, molecule: MoleculeDefinition) -> ValidationResult:
        """Validate molecular structure for topology and chemistry consistency.

        Args:
            molecule: MoleculeDefinition to validate

        Returns:
            ValidationResult with errors and warnings
        """
        errors = []
        warnings = []

        # Build RDKit molecule to check basic valence/structure
        rdkit_mol, build_errors, build_warnings = self._build_rdkit_molecule(molecule)
        errors.extend(build_errors)
        warnings.extend(build_warnings)

        # Validate bonds reference existing atoms
        bond_errors = self._validate_bonds(molecule)
        errors.extend(bond_errors)

        # Validate hydrogen bond sites reference existing atoms
        hb_errors = self._validate_hb_sites(molecule)
        errors.extend(hb_errors)

        # Check for warnings
        check_warnings = self._check_warnings(molecule)
        warnings.extend(check_warnings)

        # Valid if no errors
        valid = len(errors) == 0

        return ValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings
        )

    def _build_rdkit_molecule(self, molecule: MoleculeDefinition) -> tuple:
        """Build RDKit molecule from topology.

        Args:
            molecule: MoleculeDefinition with atoms and bonds

        Returns:
            Tuple of (RDKit molecule, list of ValidationErrors, list of ValidationWarnings)
        """
        errors = []
        warnings = []
        try:
            # Create editable molecule
            editable_mol = Chem.RWMol()

            # Add atoms
            atom_map = {}
            for atom_def in molecule.atoms:
                atom = Chem.Atom(atom_def.element)
                atom_idx = editable_mol.AddAtom(atom)
                atom_map[atom_def.id] = atom_idx

            # Add bonds
            for bond_def in molecule.bonds:
                atom1_idx = atom_map.get(bond_def.atom1)
                atom2_idx = atom_map.get(bond_def.atom2)

                if atom1_idx is None or atom2_idx is None:
                    continue

                # Convert bond type string to RDKit BondType
                bond_type_map = {
                    "single": Chem.BondType.SINGLE,
                    "double": Chem.BondType.DOUBLE,
                    "triple": Chem.BondType.TRIPLE,
                    "aromatic": Chem.BondType.AROMATIC,
                }
                bond_type = bond_type_map.get(bond_def.type, Chem.BondType.SINGLE)
                editable_mol.AddBond(atom1_idx, atom2_idx, bond_type)

            # Convert to molecule (skip strict sanitization for educational molecules)
            rdkit_mol = editable_mol.GetMol()
            try:
                Chem.SanitizeMol(rdkit_mol)
            except Exception as sanitize_err:
                # For educational purposes, warn but don't fail on valence issues
                # (coordinates and explicit hydrogens in JSON may not match RDKit's expectations)
                warnings.append(
                    ValidationWarning(
                        type_="rdkit_sanitization",
                        message=f"RDKit sanitization warning (non-critical): {str(sanitize_err)}"
                    )
                )
                # Continue anyway - structure is still usable for visualization

        except Exception as e:
            errors.append(
                ValidationError(
                    type_="structure_error",
                    message=f"Failed to build RDKit molecule: {str(e)}",
                    atom_ids=[]
                )
            )
            rdkit_mol = None

        return rdkit_mol, errors, warnings

    def _validate_bonds(self, molecule: MoleculeDefinition) -> List[ValidationError]:
        """Validate that all bonds reference existing atoms.

        Args:
            molecule: MoleculeDefinition to validate

        Returns:
            List of ValidationErrors
        """
        errors = []
        atom_ids = {atom.id for atom in molecule.atoms}

        for bond_def in molecule.bonds:
            if bond_def.atom1 not in atom_ids:
                errors.append(
                    ValidationError(
                        type_="invalid_bond_reference",
                        message=f"Bond references unknown atom: {bond_def.atom1}",
                        atom_ids=[bond_def.atom1]
                    )
                )
            if bond_def.atom2 not in atom_ids:
                errors.append(
                    ValidationError(
                        type_="invalid_bond_reference",
                        message=f"Bond references unknown atom: {bond_def.atom2}",
                        atom_ids=[bond_def.atom2]
                    )
                )

        return errors

    def _validate_hb_sites(self, molecule: MoleculeDefinition) -> List[ValidationError]:
        """Validate that all hydrogen bond sites reference existing atoms.

        Args:
            molecule: MoleculeDefinition to validate

        Returns:
            List of ValidationErrors
        """
        errors = []
        atom_ids = {atom.id for atom in molecule.atoms}

        for hb_site in molecule.hydrogenBondSites:
            if hb_site.atom not in atom_ids:
                errors.append(
                    ValidationError(
                        type_="invalid_hb_reference",
                        message=f"H-bond site {hb_site.id} references unknown atom: {hb_site.atom}",
                        atom_ids=[hb_site.atom]
                    )
                )

        return errors

    def _check_warnings(self, molecule: MoleculeDefinition) -> List[ValidationWarning]:
        """Check for common chemistry issues.

        Args:
            molecule: MoleculeDefinition to check

        Returns:
            List of ValidationWarnings
        """
        warnings = []

        # Check for N7 in Watson-Crick (should warn)
        # N7 is typically used in non-Watson-Crick (e.g., Hoogsteen) pairing
        for hb_site in molecule.hydrogenBondSites:
            if hb_site.atom == "N7" and "watson_crick" in hb_site.roles:
                warnings.append(
                    ValidationWarning(
                        type_="unusual_chemistry",
                        message=f"N7 in Watson-Crick pairing is unusual (H-bond site {hb_site.id})"
                    )
                )

        return warnings

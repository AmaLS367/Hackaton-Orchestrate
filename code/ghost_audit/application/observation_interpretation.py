"""Adapt provenance format metadata to the pure record interpreter."""

from pathlib import PurePosixPath

from ghost_audit.domain.association_models import AssociatedObservation
from ghost_audit.domain.models import ResourceRef
from ghost_audit.domain.record_interpretation import interpret as interpret_record
from ghost_audit.domain.temporal_models import TemporalObservation


def interpret(item: AssociatedObservation, reference: ResourceRef) -> TemporalObservation:
    """The file format affects representation, never ownership or policy."""
    suffix = PurePosixPath(item.observation.provenance.file_path).suffix.lower()
    return interpret_record(item, reference, source_suffix=suffix)

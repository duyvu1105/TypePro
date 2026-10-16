"""TypePro workflows: data processing, training, inference and publication.

Legacy support modules remain importable during the migration; entry points
delegate to stage packages without duplicating their implementations.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_DIR = REPO_ROOT / 'codet5p_type_retrieval'
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))

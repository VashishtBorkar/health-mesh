"""Read an explicitly configured local experiment report; never run inference."""
import json
import os
from pathlib import Path


def modeling_report():
    location = os.getenv('HEALTHMESH_MODEL_REPORT')
    if os.getenv('HEALTHMESH_PROFILE') != 'personal' or not location:
        return {'available': False}
    path = Path(location).expanduser()
    if not path.is_file():
        return {'available': False}
    if path.stat().st_size > 2_000_000:
        raise ValueError('Model report exceeds size limit')
    report = json.loads(path.read_text())
    if (report.get('available') is not True or not isinstance(report.get('points'), list)
            or not all(key in report for key in ('selectedModel', 'baseline', 'testModels', 'developmentModels', 'testRange'))):
        raise ValueError('Invalid model report')
    return report

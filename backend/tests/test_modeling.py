import json

import pytest

from healthmesh.services.modeling import modeling_report


def test_report_requires_personal_profile_and_explicit_file(tmp_path, monkeypatch):
    path = tmp_path / 'report.json'
    report = {'available': True, 'points': [], 'selectedModel': 'ridge/combined',
              'baseline': 'trailing_median_7', 'testModels': [], 'developmentModels': [], 'testRange': {}}
    path.write_text(json.dumps(report))
    monkeypatch.setenv('HEALTHMESH_MODEL_REPORT', str(path))
    monkeypatch.setenv('HEALTHMESH_PROFILE', 'default')
    assert modeling_report() == {'available': False}
    monkeypatch.setenv('HEALTHMESH_PROFILE', 'personal')
    assert modeling_report() == report
    monkeypatch.delenv('HEALTHMESH_MODEL_REPORT')
    assert modeling_report() == {'available': False}


def test_missing_and_invalid_reports(tmp_path, monkeypatch):
    path = tmp_path / 'report.json'
    monkeypatch.setenv('HEALTHMESH_PROFILE', 'personal')
    monkeypatch.setenv('HEALTHMESH_MODEL_REPORT', str(path))
    assert modeling_report() == {'available': False}
    path.write_text('{')
    with pytest.raises(ValueError):
        modeling_report()
    path.write_text('{"available":true}')
    with pytest.raises(ValueError):
        modeling_report()

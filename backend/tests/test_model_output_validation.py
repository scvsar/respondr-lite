from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import pytest
from app.llm import extract_details_from_text


@pytest.mark.parametrize('output', [
    [], None, 'invalid', {},
    {'status':'invented-status','confidence':1.0},
    {'status':'Responding','confidence':float('nan')},
    {'status':'Responding','confidence':2.0},
    {'status':'Responding','vehicle':42,'confidence':0.9},
    {'status':'Responding','eta_iso':'2026-01-01T12:00:00','confidence':0.9},
])
def test_invalid_model_output_is_explicitly_uncertain(output):
    if isinstance(output,dict) and output:
        output={'vehicle':'Unknown','status':'Responding','eta_iso':'Unknown','confidence':0.8,**output}
    with patch('app.llm._call_llm_only',return_value=output):
        result=extract_details_from_text('Responding with SAR 7, ETA unknown')
    assert result['arrival_status']=='Unknown'
    assert result['vehicle']=='Unknown'
    assert result['status_confidence']==0.0
    assert result['extraction_failed'] is True
    assert result['eta_timestamp_utc'] is None


def test_valid_canonical_output_is_preserved():
    with patch('app.llm._call_llm_only',return_value={
        'vehicle':'SAR78','status':'Responding','eta_iso':'Unknown','confidence':0.8,
    }):
        result=extract_details_from_text('Responding in SAR 78, ETA unknown')
    assert result['vehicle']=='SAR-78'
    assert result['arrival_status']=='Responding'
    assert result['status_confidence']==0.8


def test_eta_correction_does_not_invent_a_vehicle():
    now=datetime.now(timezone.utc)
    initial={'vehicle':'Unknown','status':'Responding','eta_iso':(now+timedelta(hours=5)).isoformat(),'confidence':0.8}
    corrected={**initial,'vehicle':'SAR-99','confidence':0.99,'eta_iso':(now+timedelta(minutes=30)).isoformat()}
    with (patch('app.llm._call_llm_only',side_effect=[initial,corrected]),
          patch('app.llm._validate_eta_against_context',side_effect=[False,True])):
        result=extract_details_from_text('Responding, ETA 30 minutes',base_time=now)
    assert result['correction_applied'] is True
    assert result['vehicle']=='Unknown'
    assert result['status_confidence']==0.8

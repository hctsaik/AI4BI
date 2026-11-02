from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from ai4bi_web_api.errors import AppError
from ai4bi_web_api.rfm import analyze
from test_workspace_api import client, workspace, wait_job
from test_change_analysis import saved_command as rfm_command


def rfm_payload(**changes):
    settings = dict(block_id='fab_wafer_yield', customer_column='product_family', date_column='test_date',
                    monetary_column='good_die', anchor='2099-01-01')
    settings.update(changes)
    return dict(name='Saved RFM', page_id='main', selected_component_id='bar_yield_prod', settings=settings)


def test_saved_rfm_replay_page_copy_and_removal(client):
    import copy
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.rfm import run_saved_analyses
    from ai4bi_web_api.report_extensions import prune_removed_content
    ids, path, _ = workspace(client)
    response = rfm_command(client, path, 1, 'save_rfm_analysis', rfm_payload())
    assert response.status_code == 200, response.text
    aid = response.json()['report']['web_extensions']['rfm_analyses'][0]['analysis_id']
    store = client.app.state.store
    snapshot = make_snapshot(store, ids['workspace_id'], ids['report_id'], 2, {'exploration_page_id':'main'})
    contracts = load_contracts(store.root, snapshot['datasets'])
    first = run_saved_analyses(snapshot, contracts)
    assert first[aid]['included_rows'] == 100
    copied = rfm_command(client, path, 2, 'duplicate_page', {'page_id':'main'})
    assert copied.status_code == 200, copied.text
    body = copied.json()['report']
    definitions = body['web_extensions']['rfm_analyses']
    assert len(definitions) == 2
    clone = definitions[1]
    assert clone['analysis_id'] != aid and clone['page_id'] != 'main'
    assert clone['selected_component_id'] in body['pages'][clone['page_id']]['visuals']
    removed = copy.deepcopy(body)
    del removed['pages'][clone['page_id']]
    pruned = prune_removed_content(removed, body)
    assert len(pruned['web_extensions']['rfm_analyses']) == 1
    assert rfm_command(client,path,3,'delete_rfm_analysis',{'analysis_id':aid}).status_code == 200
    assert run_saved_analyses(snapshot,contracts) == first


def test_saved_rfm_identity_repair_without_source():
    from ai4bi_web_api.rfm import settings_command, validate_saved_analyses
    from ai4bi_web_api.report_extensions import extensions
    snapshot, contracts = snapshot_fixture()
    body = settings_command(snapshot['report'],'save_rfm_analysis',rfm_payload(),contracts)
    definitions = extensions(body).rfm_analyses
    next(c for c in contracts['fab_wafer_yield'].columns if c.name=='good_die').data_type='float'
    with pytest.raises(AppError) as error:
        validate_saved_analyses(body,contracts,definitions)
    assert error.value.code == 'RFM_SETTINGS_INCOMPATIBLE'
    renamed = settings_command(body,'rename_rfm_analysis',{'analysis_id':definitions[0].analysis_id,'name':'Repair'}, {})
    deleted = settings_command(renamed,'delete_rfm_analysis',{'analysis_id':definitions[0].analysis_id},{})
    assert not extensions(deleted).rfm_analyses


@pytest.mark.parametrize('format',['json','csv','xlsx','pdf'])
def test_saved_rfm_all_document_formats(client,format):
    import io,json,zipfile
    _,path,_=workspace(client)
    saved=rfm_command(client,path,1,'save_rfm_analysis',rfm_payload())
    assert saved.status_code==200,saved.text
    definition=saved.json()['report']['web_extensions']['rfm_analyses'][0]
    accepted=client.post(path+'/exports',json=dict(format=format,base_revision=2,idempotency_key='rfm-format-'+format))
    assert accepted.status_code==202,accepted.text
    job=wait_job(client,accepted.json()['job_id'])
    assert job['status']=='succeeded',job
    response=client.get('/api/v1/artifacts/'+job['result']['artifact_id'])
    assert response.status_code==200
    if format in ('json','csv'):
        if format=='json':document=response.json()
        else:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                document=json.loads(archive.read('analysis.json'))
                manifest=json.loads(archive.read('manifest.json'))
                entry=next(e for e in manifest['tables'] if e.get('kind')=='rfm_customers')
                assert entry['row_count']==5
                assert 'monetary' in archive.read(entry['file']).decode('utf-8-sig')
        analysis=document['analysis']['rfm_analyses'][definition['analysis_id']]
        assert analysis['settings']==definition and analysis['execution_contract']=='web-query-v7'
        assert analysis['customer_count']==len(analysis['rows'])==5
    elif format=='xlsx':
        book=pd.ExcelFile(io.BytesIO(response.content))
        assert len(pd.read_excel(book,'RFM_002_customers'))==5
        summary=pd.read_excel(book,'RFM_001_summary')
        assert definition['analysis_id'] in summary['value'].astype(str).tolist()
    else:
        from pypdf import PdfReader
        text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(response.content)).pages)
        for token in ['Saved RFM','monetary','Logic-A','Memory-Y',definition['analysis_id'],'web-query-v7']:
            assert token in text


def test_rfm_fixed_publication_survives_draft_delete(client):
    _,path,_=workspace(client)
    saved=rfm_command(client,path,1,'save_rfm_analysis',rfm_payload())
    definition=saved.json()['report']['web_extensions']['rfm_analyses'][0]
    accepted=client.post(path+'/publications',json=dict(base_revision=2,idempotency_key='rfm-fixed-publish'))
    job=wait_job(client,accepted.json()['job_id'])
    assert job['status']=='succeeded',job
    target=path+'/publications/'+job['result']['publication_id']
    detail=client.get(target).json()
    assert detail['checks']['rfm_analyses'][definition['analysis_id']]['customer_count']==5
    assert rfm_command(client,path,2,'delete_rfm_analysis',{'analysis_id':definition['analysis_id']}).status_code==200
    query=client.post(target+'/queries',json=dict(base_revision=2,idempotency_key='rfm-fixed-replay',include_rfm=True))
    result=wait_job(client,query.json()['job_id'])
    assert result['status']=='succeeded',result
    original=result['result']['rfm_analyses'][definition['analysis_id']]
    exported=client.post(target+'/exports',json=dict(base_revision=2,idempotency_key='rfm-fixed-export',format='json'))
    export=wait_job(client,exported.json()['job_id'])
    assert export['status']=='succeeded',export
    document=client.get('/api/v1/artifacts/'+export['result']['artifact_id']).json()
    replay=document['analysis']['rfm_analyses'][definition['analysis_id']]
    for field in ['settings','rows','anchor','data_versions']:
        assert replay[field]==original[field]


def run(data, **changes):
    options = dict(customer_column="id", date_column="day", monetary_column="amount", anchor=date(2026, 9, 6))
    options.update(changes)
    return analyze(pd.DataFrame(data, columns=["id", "day", "amount"]), **options)


def test_counts_cutoff_distinct_days_and_refunds():
    result = run([("A", "2026-09-01", 100), ("A", "2026-09-01T23:00:00Z", 20),
                  ("A", "2026-09-06", -5), ("B", "2026-09-05", 50),
                  ("C", "2026-09-07", 99), (None, "2026-09-01", 1), ("D", None, 2)])
    assert result["included_rows"] == 4
    assert result["excluded_after_anchor"] == 1
    assert result["excluded_missing_identity_or_date"] == 2
    rows = {r["customer"]: r for r in result["rows"]}
    assert (rows["A"]["frequency"], rows["A"]["monetary"], rows["A"]["recency_days"]) == (2, 115, 0)
    assert (rows["B"]["frequency"], rows["B"]["monetary"], rows["B"]["recency_days"]) == (1, 50, 1)


def test_quintiles_match_hand_calculation():
    result = run([(str(i), f"2026-09-0{i}", i * 10) for i in range(1, 6)])
    rows = {r["customer"]: r for r in result["rows"]}
    for i in range(1, 6):
        assert rows[str(i)]["r"] == i
        assert rows[str(i)]["m"] == i
        assert rows[str(i)]["f"] == 3
        assert rows[str(i)]["at_risk"] == (i <= 2)


def test_exact_money_and_identifiers():
    result = run([(2**53 + 1, "2026-09-01", Decimal("9007199254740993.000000000001")),
                  (2**53 + 1, "2026-09-02", Decimal("0.000000000009"))])
    assert result["rows"][0]["customer"] == "9007199254740993"
    assert result["rows"][0]["monetary"] == "9007199254740993.000000000010"


def test_utc_days_and_stable_order():
    data = [("B", "2026-09-06T00:00:00+08:00", 1), ("A", "2026-09-05T16:00:00Z", 1)]
    result = run(data)
    assert result == run(list(reversed(data)))
    assert [r["customer"] for r in result["rows"]] == ["A", "B"]
    assert result["rows"][0]["recency_days"] == 1


@pytest.mark.parametrize("amount", [None, float("nan"), float("inf"), True, "12"])
def test_invalid_amount_rejected(amount):
    with pytest.raises(AppError, match="有限數值"):
        run([("A", "2026-09-01", amount)])


@pytest.mark.parametrize("value", ["wrong", "NaT", "2026-02-30", 20260901])
def test_invalid_dates_rejected(value):
    with pytest.raises(AppError, match="無效值"):
        run([("A", value, 1)])


def test_identity_types_not_coerced():
    with pytest.raises(AppError, match="型別不可混用"):
        run([(1, "2026-09-01", 1), ("1", "2026-09-01", 2)])


def test_empty_and_limit(monkeypatch):
    assert run([])["rows"] == []
    assert run([("A", "2026-09-07", 1)])["customer_count"] == 0
    monkeypatch.setattr("ai4bi_web_api.rfm.MAX_CUSTOMERS", 1)
    with pytest.raises(AppError, match="客戶數"):
        run([("A", "2026-09-01", 1), ("B", "2026-09-01", 1)])


def test_large_adjacent_amounts_keep_distinct_scores():
    result = run([(str(i), "2026-09-01", Decimal(2**53 + i)) for i in range(1, 6)])
    assert {r["customer"]: r["m"] for r in result["rows"]} == {str(i): i for i in range(1, 6)}


@pytest.mark.parametrize("amount", [Decimal("1e309"), Decimal("1e-1001")])
def test_amount_size_bounded(amount):
    with pytest.raises(AppError, match="數值範圍"):
        run([("A", "2026-09-01", amount)])


def test_input_unchanged_and_column_names_do_not_collide():
    frame = pd.DataFrame([("A", "2026-09-01", 5)], columns=["R", "最近購買", "累計金額"])
    original = frame.copy(deep=True)
    result = analyze(frame, customer_column="R", date_column="最近購買", monetary_column="累計金額", anchor=date(2026, 9, 6))
    pd.testing.assert_frame_equal(frame, original)
    assert result["rows"][0]["monetary"] == 5


def snapshot_fixture():
    from test_change_analysis import snapshot_fixture as fixture
    snapshot, contracts = fixture(anchor="2026-09-06")
    snapshot.update(analysis_contract="rfm-v1", customer_column="product_family", monetary_column="good_die")
    return snapshot, contracts


def test_snapshot_filters_and_exact_sql_precision():
    from ai4bi_web_api.rfm import analyze_snapshot
    snapshot, contracts = snapshot_fixture()
    records = contracts['fab_wafer_yield'].data_source.records
    for i, row in enumerate(records):
        row['good_die'] = 2**53 + i + 1
    snapshot['filters'] = [dict(block_id='fab_wafer_yield', column_name='product_family', operator='eq', value='A')]
    result = analyze_snapshot(snapshot, contracts)
    assert result['included_rows'] == 3 and result['customer_count'] == 1
    assert result['rows'][0]['monetary'] == str(sum(2**53 + i + 1 for i in range(3)))
    assert result['rows'][0]['frequency'] == 3
    assert result['applied_filters'] == [{**snapshot['filters'][0], 'source_visual_id': None}]


@pytest.mark.parametrize('field,value,code', [('analysis_contract','old','RFM_INCOMPATIBLE'),
    ('anchor','2026-02-30','RFM_SETTINGS_INVALID'), ('customer_column','test_date','RFM_SETTINGS_INVALID'),
    ('monetary_column','product_family','RFM_SETTINGS_INVALID'), ('block_id','missing','INVALID_RFM_CONTEXT')])
def test_snapshot_rejects_incompatible_configuration(field, value, code):
    from ai4bi_web_api.rfm import analyze_snapshot
    snapshot, contracts = snapshot_fixture()
    snapshot[field] = value
    with pytest.raises(AppError) as error:
        analyze_snapshot(snapshot, contracts)
    assert error.value.code == code


def test_http_rfm_snapshot_and_deduplication(client):
    ids, path, _ = workspace(client)
    request = dict(block_id='fab_wafer_yield', customer_column='product_family', date_column='test_date',
        monetary_column='good_die', anchor='2099-01-01', exploration_page_id='main',
        base_revision=1, idempotency_key='rfm-worker-request')
    accepted = client.post(path + '/analyses/rfm', json=request)
    assert accepted.status_code == 202, accepted.text
    assert client.post(path + '/analyses/rfm', json=request).json() == accepted.json()
    result = wait_job(client, accepted.json()['job_id'])
    assert result['status'] == 'succeeded', result
    assert result['result']['analysis_contract'] == 'rfm-v1'
    from ai4bi_web_api.core import template
    from ai4bi.blocks.datastore import materialize_dataframe
    _, contracts = template('fab')
    source = materialize_dataframe(contracts['fab_wafer_yield'])
    assert result['result']['included_rows'] == len(source)
    expected = source.groupby('product_family').good_die.sum().to_dict()
    assert {r['customer']: r['monetary'] for r in result['result']['rows']} == expected
    assert result['result']['data_versions']
    assert client.post(path + '/analyses/rfm', json={**request, 'analysis_contract':'old'}).status_code == 422


def test_saved_rfm_crud_history_and_idempotency(client):
    _, path, _ = workspace(client)
    first = rfm_command(client, path, 1, "save_rfm_analysis", rfm_payload(), key="rfm-save-history")
    assert first.status_code == 200, first.text
    assert rfm_command(client, path, 1, "save_rfm_analysis", rfm_payload(), key="rfm-save-history").json() == first.json()
    item = first.json()["report"]["web_extensions"]["rfm_analyses"][0]
    assert item["analysis_contract"] == "rfm-v1" and len(item["field_types"]) == 3
    update = {**rfm_payload(anchor="2098-01-01"), "analysis_id": item["analysis_id"]};update.pop("name")
    response = rfm_command(client, path, 2, "update_rfm_analysis", update)
    assert response.status_code == 200, response.text
    assert response.json()["report"]["web_extensions"]["rfm_analyses"][0]["anchor"] == "2098-01-01"
    assert rfm_command(client, path, 3, "rename_rfm_analysis", dict(analysis_id=item["analysis_id"], name="Renamed")).status_code == 200
    removed = rfm_command(client, path, 4, "delete_rfm_analysis", dict(analysis_id=item["analysis_id"]))
    assert removed.status_code == 200 and removed.json()["report"]["web_extensions"]["rfm_analyses"] == []
    restored = rfm_command(client, path, 5, "undo", {})
    assert restored.status_code == 200
    assert restored.json()["report"]["web_extensions"]["rfm_analyses"][0]["name"] == "Renamed"
    redone = rfm_command(client, path, 6, "redo", {})
    assert redone.status_code == 200 and redone.json()["report"]["web_extensions"]["rfm_analyses"] == []


def delivery_fixture(empty=False):
    from ai4bi_web_api.rfm import settings_command, run_saved_analyses
    snapshot, contracts = snapshot_fixture()
    snapshot['report']=settings_command(snapshot['report'],'save_rfm_analysis',rfm_payload(),contracts)
    if empty:
        snapshot['filters']=[dict(block_id='fab_wafer_yield',column_name='product_family',operator='eq',value='missing')]
    return snapshot['report'], {'rfm_analyses':run_saved_analyses(snapshot,contracts)}


@pytest.mark.parametrize('empty',[False,True])
def test_delivery_checks_accept_complete_and_empty(empty):
    from ai4bi_web_api.rfm import delivery_checks, validate_delivery_checks
    body,result=delivery_fixture(empty)
    checks=delivery_checks(body,result)
    validate_delivery_checks(body,checks)
    assert next(iter(checks.values()))['customer_count']==(0 if empty else 2)


@pytest.mark.parametrize('field,value', [('customer_count',1),('included_rows',True),('source_rows',999),
    ('excluded_after_anchor',1),('anchor','2026-01-01'),('analysis_id','other'),('name','other'),
    ('page_id','other'),('exploration_page_id','other'),('analysis_contract','old'),('settings',{}),
    ('frequency_basis','orders'),('risk_basis','probability'),('rows',[])])
def test_delivery_rejects_changed_metadata(field,value):
    from ai4bi_web_api.rfm import delivery_checks
    body,result=delivery_fixture()
    next(iter(result['rfm_analyses'].values()))[field]=value
    with pytest.raises(AppError) as error:delivery_checks(body,result)
    assert error.value.code=='RFM_DELIVERY_INVALID'


@pytest.mark.parametrize('field,value',[('r',5),('f',0),('m',False),('monetary','230'),
    ('monetary',float('inf')),('last_purchase','2026-02-30'),('recency_days',-1),('frequency',999),
    ('at_risk','yes'),('segment','VIP'),('customer',False)])
def test_delivery_rejects_changed_customer_values(field,value):
    from ai4bi_web_api.rfm import delivery_checks
    body,result=delivery_fixture()
    next(iter(result['rfm_analyses'].values()))['rows'][0][field]=value
    with pytest.raises(AppError) as error:delivery_checks(body,result)
    assert error.value.code=='RFM_DELIVERY_INVALID'


def test_delivery_duplicate_identity_and_tampered_receipt():
    from ai4bi_web_api.rfm import delivery_checks, validate_delivery_checks
    body,result=delivery_fixture()
    checks=delivery_checks(body,result)
    next(iter(checks.values()))['settings_signature']='changed'
    with pytest.raises(AppError):validate_delivery_checks(body,checks)
    rows=next(iter(result['rfm_analyses'].values()))['rows']
    rows[1]['customer']=rows[0]['customer']
    with pytest.raises(AppError):delivery_checks(body,result)


def test_delivery_preserves_large_exact_amounts_and_rejects_numeric_coercion():
    from ai4bi_web_api.rfm import settings_command, run_saved_analyses, delivery_checks
    snapshot,contracts=snapshot_fixture()
    for i,row in enumerate(contracts['fab_wafer_yield'].data_source.records):
        row['good_die']=2**53+i+1
    snapshot['report']=settings_command(snapshot['report'],'save_rfm_analysis',rfm_payload(),contracts)
    result={'rfm_analyses':run_saved_analyses(snapshot,contracts)}
    delivery_checks(snapshot['report'],result)
    row=next(iter(result['rfm_analyses'].values()))['rows'][0]
    assert isinstance(row['monetary'],str)
    row['monetary']=float(row['monetary'])
    with pytest.raises(AppError) as error:delivery_checks(snapshot['report'],result)
    assert error.value.code=='RFM_DELIVERY_INVALID'

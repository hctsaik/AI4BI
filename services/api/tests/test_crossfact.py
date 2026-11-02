import copy

import pandas as pd
import pytest
from pydantic import ValidationError

from ai4bi.blocks.contracts import CachedDataSource, ColumnSchema
from ai4bi.blocks.datastore import put_dataframe
from ai4bi.report.fab_template import fab_contracts
from ai4bi_web_api.crossfact import analyze
from ai4bi_web_api.errors import AppError
from ai4bi_web_api.schemas import CrossFactSettings
from test_workspace_api import client, workspace, wait_job, command


def request(**changes):
    return dict(block_a='fab_process_move', block_b='fab_wafer_yield', key_a='lot_id', key_b='lot_id',
                metric_a=dict(kind='aggregate', column='queue_time_hr', aggregation='AVG'),
                metric_b=dict(kind='aggregate', column='yield_pct', aggregation='AVG'),
                quantiles=5, operation='ratio', base_revision=1, idempotency_key='crossfact-request',
                exploration_page_id='main', **changes)


def saved_settings():
    settings = {k:v for k,v in request().items() if k not in {'base_revision','idempotency_key','exploration_page_id'}}
    return dict(name='Saved crossfact', settings=settings, page_id='main', selected_component_id='bar_qt_step')


@pytest.mark.parametrize('active_index', [0, 1])
@pytest.mark.parametrize('drilled', [False, True])
@pytest.mark.parametrize('weighted', [False, True])
def test_crossfact_scope_matrix_matches_independent_filtered_aggregation(client, monkeypatch, active_index, drilled, weighted):
    from ai4bi_web_api import core
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.crossfact import run_saved_analyses
    from ai4bi.blocks.datastore import materialize_dataframe
    ids,path,_=workspace(client)
    payload=saved_settings()
    if weighted:
        payload['settings']['metric_b']=dict(kind='weighted_ratio',numerator_column='good_die',denominator_column='tested_die',scale=100.)
    assert command(client,path,1,'save_crossfact_analysis',payload,key='scope-matrix-save').status_code==200
    copied=command(client,path,2,'duplicate_page',{'page_id':'main'},key='scope-matrix-copy')
    assert copied.status_code==200,copied.text
    report=copied.json()['report'];definitions=report['web_extensions']['crossfact_analyses']
    for definition in definitions:
        visual=report['pages'][definition['page_id']]['visuals'][definition['selected_component_id']]
        visual['visualization']['extra']['drill_hierarchy']=['step_name','tool_id']
        visual['query']['filters']=[dict(block_id='fab_process_move',column_name='queue_time_hr',operator='gt',value=1.)]
    changed=command(client,path,3,'replace_report',{'report':report},key='scope-matrix-configure')
    assert changed.status_code==200,changed.text
    revision=changed.json()['revision']
    conditions=[dict(scope='report',block_id='fab_wafer_yield',column_name='yield_pct',operator='gte',value=80.)]
    for definition,step in zip(definitions,['Etch','Lithography']):
        conditions.extend([
            dict(scope='page',page_id=definition['page_id'],block_id='fab_process_move',column_name='step_name',operator='eq',value=step),
            dict(scope='visual',page_id=definition['page_id'],visual_id=definition['selected_component_id'],block_id='fab_process_move',column_name='queue_time_hr',operator='lt',value=6.),
        ])
    for index,condition in enumerate(conditions):
        response=command(client,path,revision,'add_filter',{'filter':condition},key='scope-matrix-filter-'+str(index))
        assert response.status_code==200,response.text
        revision=response.json()['revision']
    active=definitions[active_index]
    step=['Etch','Lithography'][active_index]
    if drilled:
        options=dict(exploration_page_id=active['page_id'],drill_state={active['selected_component_id']:{
            'block_id':'fab_process_move','hierarchy':['step_name','tool_id'],'field_types':['string','string'],
            'path':[{'column':'step_name','value':step}]}},filters=[dict(source_visual_id=active['selected_component_id'],
            block_id='fab_process_move',column_name='tool_id',operator='eq',value='ETCH-02' if active_index==0 else 'PHOTO-01')])
    else:
        options=dict(exploration_page_id=active['page_id'],filters=[dict(block_id='fab_process_move',column_name='queue_time_hr',operator='gte',value=4.)])
    store=client.app.state.store
    snapshot=make_snapshot(store,ids['workspace_id'],ids['report_id'],revision,options)
    before=copy.deepcopy(snapshot);reads=[];read=core._read_source
    def observed(*args):
        reads.append(args[1]['dataset_id']);return read(*args)
    monkeypatch.setattr(core,'_read_source',observed)
    contracts=core.load_contracts(store.root,snapshot['datasets'])
    frames={key:materialize_dataframe(contracts[key]).copy() for key in ['fab_process_move','fab_wafer_yield']}
    results=run_saved_analyses(snapshot,contracts)
    assert len(reads)==len(snapshot['datasets']) and snapshot==before
    for index,definition in enumerate(definitions):
        result=results[definition['analysis_id']]
        left=frames['fab_process_move'];right=frames['fab_wafer_yield']
        left=left[(left.step_name==['Etch','Lithography'][index]) & (left.queue_time_hr>1) & (left.queue_time_hr<6)]
        right=right[right.yield_pct>=80]
        if index==active_index:
            left=left[left.tool_id==options['filters'][0]['value']] if drilled else left[left.queue_time_hr>=4]
        a=left.groupby('lot_id').queue_time_hr.mean()
        b=(right.groupby('lot_id').good_die.sum()/right.groupby('lot_id').tested_die.sum()*100
           if weighted else right.groupby('lot_id').yield_pct.mean())
        expected=pd.concat([a.rename('a'),b.rename('b')],axis=1,join='inner').sort_index()
        assert result['sources']['a']['input_rows']==len(left)
        assert result['sources']['b']['input_rows']==len(right)
        assert result['aligned_count']==len(expected)
        assert [row['key'] for row in result['rows']]==list(expected.index)
        for row,(_,values) in zip(result['rows'],expected.iterrows()):
            assert row['a']==pytest.approx(values.a) and row['b']==pytest.approx(values.b)
            assert row['result']==pytest.approx(round(values.a/values.b,2))
        if len(expected)>=3 and expected.a.nunique()>1 and expected.b.nunique()>1:
            assert result['correlation']['r']==round(expected.a.corr(expected.b),3)
        assert bool(result['filters'])==(index==active_index)
        assert bool(result['drill_context']['path'])==(drilled and index==active_index)
        if drilled and index==active_index:assert result['paired_count']>0
        assert result['settings']==definition
    for key,frame in frames.items():pd.testing.assert_frame_equal(materialize_dataframe(contracts[key]),frame)


def test_crossfact_bookmark_replays_captured_filter_after_current_filter_changes(client):
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.crossfact import run_saved_analyses
    from ai4bi.blocks.datastore import materialize_dataframe
    ids,path,_=workspace(client)
    assert command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-bookmark-analysis').status_code==200
    filtered=command(client,path,2,'add_filter',{'filter':dict(scope='report',block_id='fab_process_move',column_name='step_name',operator='eq',value='Etch')},key='crossfact-bookmark-filter')
    assert filtered.status_code==200
    fid=filtered.json()['report']['web_extensions']['persistent_filters'][0]['filter_id']
    bookmark=command(client,path,3,'save_bookmark',{'name':'Captured Etch','view':dict(page_id='main',selected_visual_id='bar_qt_step',filters=[])},key='crossfact-bookmark-save')
    assert bookmark.status_code==200,bookmark.text
    bid=bookmark.json()['report']['web_extensions']['bookmarks'][0]['bookmark_id']
    assert command(client,path,4,'delete_filter',{'filter_id':fid},key='crossfact-bookmark-remove').status_code==200
    assert command(client,path,5,'add_filter',{'filter':dict(scope='report',block_id='fab_process_move',column_name='step_name',operator='eq',value='Lithography')},key='crossfact-bookmark-current').status_code==200
    store=client.app.state.store;results=[]
    for bookmark_id,step in [(None,'Lithography'),(bid,'Etch')]:
        snapshot=make_snapshot(store,ids['workspace_id'],ids['report_id'],6,dict(exploration_page_id='main',filter_bookmark_id=bookmark_id))
        contracts=load_contracts(store.root,snapshot['datasets']);original=copy.deepcopy(snapshot)
        result=next(iter(run_saved_analyses(snapshot,contracts).values()))
        frame=materialize_dataframe(contracts['fab_process_move'])
        expected=frame[frame.step_name==step].groupby('lot_id').queue_time_hr.mean()
        assert result['sources']['a']['input_rows']==100 and result['aligned_count']==20
        for row in result['rows']:assert row['a']==pytest.approx(expected.loc[row['key']])
        assert result['filter_bookmark_id']==bookmark_id and snapshot==original
        results.append(result)
    assert results[0]['rows']!=results[1]['rows'] and results[0]['data_versions']==results[1]['data_versions']


def test_crossfact_selected_b_drill_filters_only_b_before_alignment(client):
    from ai4bi_web_api import core
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi.blocks.datastore import materialize_dataframe
    ids,path,state=workspace(client)
    report=client.get(path).json()['report'];vid='bar_yield_prod'
    report['pages']['main']['visuals'][vid]['visualization']['extra']['drill_hierarchy']=['product_family','lot_id']
    assert command(client,path,1,'replace_report',{'report':report},key='crossfact-b-drill-configure').status_code==200
    payload=saved_settings();payload['selected_component_id']=vid
    payload['settings']['metric_b']=dict(kind='weighted_ratio',numerator_column='good_die',denominator_column='tested_die',scale=100.)
    saved=command(client,path,2,'save_crossfact_analysis',payload,key='crossfact-b-drill-save')
    assert saved.status_code==200,saved.text
    aid=saved.json()['report']['web_extensions']['crossfact_analyses'][0]['analysis_id']
    options=dict(include_crossfact=True,exploration_page_id='main',drill_state={vid:{
        'block_id':'fab_wafer_yield','hierarchy':['product_family','lot_id'],'field_types':['string','string'],
        'path':[{'column':'product_family','value':'Logic-A'}]}})
    store=client.app.state.store
    snapshot=make_snapshot(store,ids['workspace_id'],ids['report_id'],3,options)
    result=core.run_query(store.root,snapshot)['crossfact_analyses'][aid]
    contracts=core.load_contracts(store.root,snapshot['datasets'])
    left=materialize_dataframe(contracts['fab_process_move'])
    right=materialize_dataframe(contracts['fab_wafer_yield']);right=right[right.product_family=='Logic-A']
    a=left.groupby('lot_id').queue_time_hr.mean()
    b=right.groupby('lot_id').good_die.sum()/right.groupby('lot_id').tested_die.sum()*100
    expected=pd.concat([a.rename('a'),b.rename('b')],axis=1,join='inner').sort_index()
    assert result['sources']['a']['input_rows']==600 and result['sources']['b']['input_rows']==len(right)<100
    assert result['aligned_count']==len(expected)>0
    assert result['drill_context']['block_id']=='fab_wafer_yield'
    for row,(_,values) in zip(result['rows'],expected.iterrows()):
        assert row['key']==values.name and row['a']==pytest.approx(values.a) and row['b']==pytest.approx(values.b)
        assert row['result']==pytest.approx(round(values.a/values.b,2))


@pytest.mark.parametrize('failure',['invalid_second_definition','second_calculation_fails'])
def test_crossfact_multi_analysis_validation_and_failure_are_atomic(client,monkeypatch,failure):
    from ai4bi_web_api import core,crossfact
    from ai4bi_web_api.jobs import make_snapshot
    ids,path,_=workspace(client)
    assert command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-atomic-save').status_code==200
    assert command(client,path,2,'duplicate_page',{'page_id':'main'},key='crossfact-atomic-copy').status_code==200
    snapshot=make_snapshot(client.app.state.store,ids['workspace_id'],ids['report_id'],3,{})
    contracts=core.load_contracts(client.app.state.store.root,snapshot['datasets'])
    if failure=='invalid_second_definition':
        snapshot['report']['web_extensions']['crossfact_analyses'][1]['field_types']['a']['queue_time_hr']='integer'
    calls=[];original=crossfact.analyze_snapshot
    def observed(*args):
        if failure=='invalid_second_definition':pytest.fail('Computed before validating all definitions')
        calls.append(args[0]['analysis_id'])
        if len(calls)==2:raise AppError('CROSSFACT_STATISTICS_UNAVAILABLE','Injected second calculation failure',503)
        return original(*args)
    monkeypatch.setattr(crossfact,'analyze_snapshot',observed)
    before=copy.deepcopy(snapshot)
    with pytest.raises(AppError) as exc:crossfact.run_saved_analyses(snapshot,contracts)
    assert exc.value.code==('CROSSFACT_SETTINGS_INCOMPATIBLE' if failure=='invalid_second_definition' else 'CROSSFACT_STATISTICS_UNAVAILABLE')
    assert len(calls)==(0 if failure=='invalid_second_definition' else 2) and snapshot==before


def delivery_fixture(frame=None, **changes):
    from ai4bi_web_api.report_extensions import SavedCrossFactAnalysis
    contracts, settings = setup(frame, frame)
    settings.update(changes)
    analysis = analyze(contracts, settings)
    definition = SavedCrossFactAnalysis(**settings, analysis_id='crossfact_receipt', name='Receipt',
                                       page_id='main', field_types=analysis['field_types']).model_dump()
    analysis.update(analysis_id=definition['analysis_id'], name=definition['name'], page_id='main', settings=definition)
    return {'web_extensions': {'crossfact_analyses': [definition]}}, {'crossfact_analyses': {definition['analysis_id']: analysis}}


@pytest.mark.parametrize('state', ['ready', 'empty', 'constant', 'null', 'zero', 'ties', 'large_integer'])
def test_crossfact_delivery_checks_accept_complete_results(state):
    from ai4bi_web_api.crossfact import delivery_checks, validate_delivery_checks
    values = {'ready': [1., 2., 3., 4., 5.], 'empty': [], 'constant': [1.] * 5,
              'null': [float('nan')] * 5, 'zero': [0., 1., 2., 3., 4.],
              'ties': [1., 1., 1., 1., 2.], 'large_integer': [2**53 + 1, 2**53 + 3, 2**53 + 5]}[state]
    frame = pd.DataFrame({'key': [str(i) for i in range(len(values))], 'value': pd.Series(values, dtype='int64' if state == 'large_integer' else 'float64')})
    body, result = delivery_fixture(frame)
    before = copy.deepcopy(result)
    checks = delivery_checks(body, result)
    validate_delivery_checks(body, checks)
    assert checks['crossfact_receipt']['aligned_count'] == len(values)
    assert result == before


@pytest.mark.parametrize('path,value', [
    (('analysis_id',), 'another'), (('name',), 'another'), (('page_id',), 'another'),
    (('settings', 'operation'), 'diff'), (('field_types', 'a', 'key'), 'integer'),
    (('analysis_contract',), 'old'), (('aligned_count',), 2), (('paired_count',), True),
    (('missing_pair_count',), 1), (('zero_denominator_count',), 1),
    (('status',), 'empty'), (('requested_quantiles',), 2), (('actual_quantiles',), 2),
    (('rows',), []), (('rows', 1, 'key'), 'x'), (('rows', 0, 'a'), None),
    (('rows', 0, 'b'), float('inf')), (('rows', 0, 'result'), None),
    (('rows', 0, 'result'), True), (('rows', 0, 'a'), '30'),
    (('rows', 0, 'a'), 10**400), (('correlation_status',), []),
    (('correlation',), None), (('correlation', 'n'), 2), (('correlation', 'r'), 1.01),
    (('correlation', 'r'), float('nan')), (('correlation', 'direction'), ''),
    (('cohort_status',), 'constant_metric'), (('cohorts',), []),
    (('cohorts', 0, 'count'), 2), (('cohorts', 0, 'mean_b'), float('inf')),
    (('cohorts', 1, 'bucket'), 'Q1'), (('sources',), {}),
    (('sources', 'a', 'unmatched_groups'), 1), (('sources', 'a', 'excluded_key_rows'), 5),
    (('sources', 'b', 'missing_measure_rows'), -1),
])
def test_crossfact_delivery_rejects_incomplete_or_mismatched_results(path, value):
    from ai4bi_web_api.crossfact import delivery_checks
    body, result = delivery_fixture()
    target = result['crossfact_analyses']['crossfact_receipt']
    # Keep saved definitions independent so changing a result cannot change expectations.
    result = copy.deepcopy(result)
    target = result['crossfact_analyses']['crossfact_receipt']
    for part in path[:-1]: target = target[part]
    target[path[-1]] = value
    with pytest.raises(AppError) as exc: delivery_checks(body, result)
    assert exc.value.code == 'CROSSFACT_DELIVERY_INVALID'


def test_crossfact_delivery_requires_exact_saved_analysis_set():
    from ai4bi_web_api.crossfact import delivery_checks, validate_delivery_checks
    body, result = delivery_fixture()
    for malformed in ({}, {'crossfact_analyses': None}, {'crossfact_analyses': {'unexpected': {}}}):
        with pytest.raises(AppError): delivery_checks(body, malformed)
    checks = delivery_checks(body, result)
    for malformed in (None, {}, {'unexpected': next(iter(checks.values()))}):
        with pytest.raises(AppError): validate_delivery_checks(body, malformed)
    assert delivery_checks({}, {}) == {}
    validate_delivery_checks({}, None)


@pytest.mark.parametrize('field,value', [('paired_count', 2), ('aligned_count', -1),
                                        ('requested_quantiles', 10), ('actual_quantiles', 4),
                                        ('correlation_status', 'missing'), ('cohort_status', 'insufficient_pairs')])
def test_crossfact_publication_receipt_rejects_inconsistent_counts(field, value):
    from ai4bi_web_api.crossfact import delivery_checks, validate_delivery_checks
    body, result = delivery_fixture()
    checks = delivery_checks(body, result)
    checks['crossfact_receipt'][field] = value
    with pytest.raises(AppError) as exc: validate_delivery_checks(body, checks)
    assert exc.value.code == 'CROSSFACT_DELIVERY_INVALID'


def test_saved_crossfact_survives_service_restart(tmp_path):
    from fastapi.testclient import TestClient
    from ai4bi_web_api.app import create_app
    from test_workspace_api import CODE
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.crossfact import run_saved_analyses
    root=tmp_path/'restart'
    def pair(c):
        assert c.post('/api/v1/session',json={'code':CODE}).status_code==200
        c.headers.update({'x-ai4bi-request':'1'})
    with TestClient(create_app(root,CODE)) as c:
        pair(c);ids,path,_=workspace(c)
        response=command(c,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-restart-save')
        expected=response.json()['report']['web_extensions']['crossfact_analyses']
        assert command(c,path,2,'save',key='crossfact-restart-checkpoint').status_code==200
        snapshot=make_snapshot(c.app.state.store,ids['workspace_id'],ids['report_id'],2,{})
        before=run_saved_analyses(snapshot,load_contracts(root,snapshot['datasets']))
    with TestClient(create_app(root,CODE)) as c:
        pair(c)
        assert c.get(path).json()['report']['web_extensions']['crossfact_analyses']==expected
        assert run_saved_analyses(snapshot,load_contracts(root,snapshot['datasets']))==before


def test_saved_crossfact_names_and_limits_are_atomic(client):
    from ai4bi_web_api.crossfact import settings_command
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.report_extensions import duplicate_page
    ids,path,_=workspace(client)
    response=command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-limit-save')
    body=response.json()['report'];item=body['web_extensions']['crossfact_analyses'][0]
    contracts=load_contracts(client.app.state.store.root,client.app.state.store.datasets(ids['workspace_id']))
    payload={**saved_settings(),'name':item['name'].upper()}
    with pytest.raises(AppError) as exc:settings_command(body,'save_crossfact_analysis',payload,contracts)
    assert exc.value.code=='DUPLICATE_CROSSFACT_SETTINGS'
    body['web_extensions']['crossfact_analyses']=[{**copy.deepcopy(item),'analysis_id':'cf_'+str(i),'name':'CF '+str(i)} for i in range(30)]
    before=copy.deepcopy(body)
    with pytest.raises(AppError) as exc:settings_command(body,'save_crossfact_analysis',saved_settings(),contracts)
    assert exc.value.code=='CROSSFACT_SETTINGS_LIMIT'
    with pytest.raises(AppError) as exc:duplicate_page(body,'main')
    assert exc.value.code=='CROSSFACT_SETTINGS_LIMIT'
    assert body==before


def test_crossfact_saved_settings_history_and_replay(client):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.crossfact import run_saved_analyses
    ids, path, _ = workspace(client)
    payload = saved_settings()
    saved = command(client,path,1,'save_crossfact_analysis',payload,key='crossfact-settings-save')
    assert saved.status_code == 200, saved.text
    definition = saved.json()['report']['web_extensions']['crossfact_analyses'][0]
    assert definition['field_types'] == {'a':{'lot_id':'string','queue_time_hr':'float'},'b':{'lot_id':'string','yield_pct':'float'}}
    assert command(client,path,1,'save_crossfact_analysis',payload,key='crossfact-settings-save').json() == saved.json()
    root = client.app.state.store.root
    snapshot = make_snapshot(client.app.state.store,ids['workspace_id'],ids['report_id'],2,{})
    contracts = load_contracts(root,snapshot['datasets'])
    original = run_saved_analyses(snapshot,contracts)
    assert original[definition['analysis_id']]['aligned_count'] == 20
    settings = {**payload['settings'],'operation':'diff'}
    assert command(client,path,2,'update_crossfact_analysis',dict(analysis_id=definition['analysis_id'],settings=settings,page_id='main',selected_component_id='bar_qt_step'),key='crossfact-settings-update').status_code == 200
    assert command(client,path,3,'rename_crossfact_analysis',dict(analysis_id=definition['analysis_id'],name='Renamed'),key='crossfact-settings-rename').status_code == 200
    assert command(client,path,4,'save',key='crossfact-save-checkpoint').status_code == 200
    checkpoint = client.get(path).json()
    removed = command(client,path,checkpoint['revision'],'delete_crossfact_analysis',dict(analysis_id=definition['analysis_id']),key='crossfact-settings-delete')
    assert removed.status_code == 200
    assert removed.json()['report']['web_extensions']['crossfact_analyses'] == []
    undone = command(client,path,removed.json()['revision'],'undo',key='crossfact-settings-undo')
    assert undone.json()['report']['web_extensions']['crossfact_analyses'] == checkpoint['report']['web_extensions']['crossfact_analyses']
    assert run_saved_analyses(snapshot,contracts) == original


def test_crossfact_duplicate_page_and_prune(client):
    from ai4bi_web_api.report_extensions import prune_removed_content
    _, path, _ = workspace(client)
    assert command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-copy-save').status_code == 200
    response = command(client,path,2,'duplicate_page',{'page_id':'main'},key='crossfact-copy-page')
    assert response.status_code == 200,response.text
    body = response.json()['report']
    first,second = body['web_extensions']['crossfact_analyses']
    assert first['analysis_id'] != second['analysis_id'] and first['name'] != second['name']
    assert second['selected_component_id'] in body['pages'][second['page_id']]['visuals']
    edited = copy.deepcopy(body);del edited['pages'][second['page_id']]
    assert prune_removed_content(edited,body)['web_extensions']['crossfact_analyses'] == [first]


def test_crossfact_offline_metadata_repair(client,monkeypatch):
    _,path,_ = workspace(client)
    response=command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-offline-save')
    aid=response.json()['report']['web_extensions']['crossfact_analyses'][0]['analysis_id']
    monkeypatch.setattr('ai4bi_web_api.core.load_contracts',lambda *args:pytest.fail('Metadata repair read source'))
    assert command(client,path,2,'rename_crossfact_analysis',dict(analysis_id=aid,name='Offline'),key='crossfact-offline-rename').status_code==200
    assert command(client,path,3,'delete_crossfact_analysis',dict(analysis_id=aid),key='crossfact-offline-delete').status_code==200


def test_crossfact_invalid_saved_types_reject_before_compute(client,monkeypatch):
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.core import load_contracts
    from ai4bi_web_api.crossfact import run_saved_analyses
    ids,path,_=workspace(client)
    assert command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-types-save').status_code==200
    snapshot=make_snapshot(client.app.state.store,ids['workspace_id'],ids['report_id'],2,{})
    contracts=load_contracts(client.app.state.store.root,snapshot['datasets'])
    snapshot['report']['web_extensions']['crossfact_analyses'][0]['field_types']['a']['queue_time_hr']='integer'
    monkeypatch.setattr('ai4bi_web_api.crossfact.analyze_snapshot',lambda *args:pytest.fail('Computed incompatible settings'))
    with pytest.raises(AppError) as exc:run_saved_analyses(snapshot,contracts)
    assert exc.value.code=='CROSSFACT_SETTINGS_INCOMPATIBLE'


@pytest.mark.parametrize('operation',['json','csv','xlsx','pdf','publish'])
def test_saved_crossfact_delivery_contains_complete_analysis(client,operation):
    import io, json, zipfile
    _,path,_=workspace(client)
    saved=command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-delivery-save')
    assert saved.status_code==200
    definition=saved.json()['report']['web_extensions']['crossfact_analyses'][0]
    aid=definition['analysis_id']
    route='/publications' if operation=='publish' else '/exports'
    payload={'base_revision':2,'idempotency_key':'crossfact-delivery-'+operation}
    if operation!='publish':payload['format']=operation
    accepted=client.post(path+route,json=payload)
    assert accepted.status_code==202,accepted.text
    job=wait_job(client,accepted.json()['job_id'])
    assert job['status']=='succeeded',job
    if operation=='publish':
        detail=client.get(path+'/publications/'+job['result']['publication_id']).json()
        assert detail['checks']['crossfact_analyses'][aid]['aligned_count']==20
        assert detail['checks']['execution_contract']=='web-query-v7'
        return
    response=client.get('/api/v1/artifacts/'+job['result']['artifact_id'])
    assert response.status_code==200
    if operation in ('json','csv'):
        if operation=='json':document=response.json()
        else:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert archive.testzip() is None
                document=json.loads(archive.read('analysis.json'))
                tables=[entry for entry in json.loads(archive.read('manifest.json'))['tables'] if entry.get('analysis_id')==aid]
                assert len(tables)==4
                assert next(t['row_count'] for t in tables if t['kind']=='crossfact_aligned')==20
        analysis=document['analysis']['crossfact_analyses'][aid]
        assert analysis['settings']==definition and len(analysis['rows'])==20
        assert analysis['correlation']['r']==-.716 and sum(c['count'] for c in analysis['cohorts'])==20
        assert analysis['data_versions']==document['analysis']['data_versions']
        assert analysis['execution_contract']=='web-query-v7'
    elif operation=='xlsx':
        from openpyxl import load_workbook
        book=load_workbook(io.BytesIO(response.content))
        assert book['CF_002_aligned'].max_row==21 and book['CF_002_aligned']['A1'].comment.text==aid
        assert book['CF_003_correlation']['B2'].value==-.716
        assert book['CF_004_cohorts'].max_row==6
    else:
        from pypdf import PdfReader
        text='\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(response.content)).pages)
        for token in [aid,'LOT-1001','LOT-1020','-0.716','web-query-v7']:assert token in text


def test_crossfact_published_query_and_export_remain_fixed_after_draft_delete(client):
    _,path,_=workspace(client)
    saved=command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-fixed-save')
    definition=saved.json()['report']['web_extensions']['crossfact_analyses'][0]
    accepted=client.post(path+'/publications',json={'base_revision':2,'idempotency_key':'crossfact-fixed-publish'})
    job=wait_job(client,accepted.json()['job_id']);assert job['status']=='succeeded',job
    target=path+'/publications/'+job['result']['publication_id']
    assert command(client,path,2,'delete_crossfact_analysis',{'analysis_id':definition['analysis_id']},key='crossfact-fixed-delete').status_code==200
    assert client.get(target).json()['report']['web_extensions']['crossfact_analyses']==[definition]
    accepted=client.post(target+'/queries',json={'base_revision':2,'idempotency_key':'crossfact-fixed-query','include_crossfact':True})
    query=wait_job(client,accepted.json()['job_id']);assert query['status']=='succeeded',query
    expected=query['result']['crossfact_analyses'][definition['analysis_id']]
    assert expected['settings']==definition and expected['aligned_count']==20
    accepted=client.post(target+'/exports',json={'base_revision':2,'idempotency_key':'crossfact-fixed-export','format':'json'})
    export=wait_job(client,accepted.json()['job_id']);assert export['status']=='succeeded',export
    actual=client.get('/api/v1/artifacts/'+export['result']['artifact_id']).json()['analysis']['crossfact_analyses'][definition['analysis_id']]
    for field in ('settings','rows','correlation','cohorts','data_versions'):assert actual[field]==expected[field]
    assert client.post(path+'/exports',json={'base_revision':3,'idempotency_key':'crossfact-no-optout','include_crossfact':False}).status_code==422
    assert client.post(path+'/queries',json={'base_revision':3,'idempotency_key':'crossfact-invalid-optin','include_crossfact':'yes'}).status_code==422


def test_default_query_does_not_compute_crossfact(client,monkeypatch):
    from ai4bi_web_api.core import run_query
    from ai4bi_web_api.jobs import make_snapshot
    ids,path,_=workspace(client)
    assert command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-default-save').status_code==200
    snapshot=make_snapshot(client.app.state.store,ids['workspace_id'],ids['report_id'],2,{})
    monkeypatch.setattr('ai4bi_web_api.crossfact.run_saved_analyses',lambda *args:pytest.fail('Implicit analysis'))
    assert run_query(client.app.state.store.root,snapshot)['crossfact_analyses']=={}


@pytest.mark.parametrize('mutation',['missing','wrong_count'])
def test_crossfact_publication_commit_rechecks_receipt(client,mutation):
    import json,time
    from ai4bi_web_api.publications import check_publication
    from ai4bi_web_api.storage import encode
    ids,path,_=workspace(client)
    assert command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-commit-save').status_code==200
    jobs=client.app.state.jobs;store=client.app.state.store;jobs.close()
    accepted=client.post(path+'/publications',json={'base_revision':2,'idempotency_key':'crossfact-commit-publish'})
    assert accepted.status_code==202
    jid=accepted.json()['job_id']
    with store.transaction() as db:
        snapshot=json.loads(db.execute('SELECT input FROM jobs WHERE id=?',(jid,)).fetchone()[0])
        db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
    result=check_publication(store.root,snapshot)
    if mutation=='missing':result['checks'].pop('crossfact_analyses')
    else:next(iter(result['checks']['crossfact_analyses'].values()))['paired_count']=0
    from ai4bi_web_api.publications import complete_publication
    with pytest.raises(AppError) as exc:
        with store.transaction() as db:complete_publication(db,jid,ids['workspace_id'],result)
    assert exc.value.code=='CROSSFACT_DELIVERY_INVALID'
    folder=store.root/'staging'/'jobs'/jid;folder.mkdir(parents=True)
    (folder/'result.json').write_text(encode({'result':result}),encoding='utf-8')
    class Finished:
        returncode=0
        def poll(self):return 0
    jobs.running[jid]=Finished(),ids['workspace_id'],time.monotonic()
    jobs.tick()
    assert jobs.get(jid)['status']=='failed' and jobs.get(jid)['error']['code']=='PUBLICATION_INVALID'
    assert client.get(path+'/publications').json()==[]


@pytest.mark.parametrize('operation',['json','csv','xlsx','pdf','publish'])
def test_crossfact_incomplete_results_prevent_any_delivery(client,tmp_path,monkeypatch,operation):
    from ai4bi_web_api import crossfact
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.exports import export_snapshot
    from ai4bi_web_api.publications import check_publication
    ids,path,_=workspace(client)
    assert command(client,path,1,'save_crossfact_analysis',saved_settings(),key='crossfact-incomplete-save').status_code==200
    snapshot=make_snapshot(client.app.state.store,ids['workspace_id'],ids['report_id'],2,{'format':operation})
    original=crossfact.analyze_snapshot
    def truncated(*args):
        result=original(*args);result['rows']=result['rows'][:1];return result
    monkeypatch.setattr(crossfact,'analyze_snapshot',truncated)
    output=tmp_path/'incomplete';output.mkdir()
    with pytest.raises(AppError) as exc:
        if operation=='publish':check_publication(client.app.state.store.root,snapshot)
        else:export_snapshot(client.app.state.store.root,snapshot,output)
    assert exc.value.code=='CROSSFACT_DELIVERY_INVALID' and list(output.iterdir())==[]


@pytest.mark.parametrize('format',['csv','xlsx','pdf'])
def test_crossfact_document_projections_preserve_saved_metrics_and_results(client,tmp_path,format):
    import json,csv,io,zipfile
    from ai4bi_web_api import core,exports
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.crossfact import run_saved_analyses
    ids,path,_=workspace(client)
    payload=saved_settings();payload['name']='=Crossfact/$literal$'
    payload['settings']['metric_b']=dict(kind='weighted_ratio',numerator_column='good_die',denominator_column='tested_die',scale=100)
    assert command(client,path,1,'save_crossfact_analysis',payload,key='crossfact-document-save').status_code==200
    store=client.app.state.store;snapshot=make_snapshot(store,ids['workspace_id'],ids['report_id'],2,{})
    analyses=run_saved_analyses(snapshot,core.load_contracts(store.root,snapshot['datasets']))
    aid,analysis=next(iter(analyses.items()))
    result=dict(visuals={},crossfact_analyses=analyses,snapshot_id=snapshot['snapshot_id'],execution_contract=snapshot['execution_contract'])
    original=copy.deepcopy(result)
    tables=list(exports.crossfact_tables(snapshot,result))
    assert [part for _,part,_ in tables]==['summary','aligned','correlation','cohorts']
    metadata={row['field']:row['value'] for row in tables[0][2]['rows']}
    assert json.loads(metadata['metric_b'])==analysis['settings']['metric_b']
    assert json.loads(metadata['sources'])==analysis['sources']
    assert json.loads(metadata['data_versions'])==analysis['data_versions']
    assert tables[1][2]['rows']==analysis['rows'] and len(analysis['rows'])==20
    output=tmp_path/('crossfact.'+format)
    if format=='csv':
        exports.csv_bundle(output,snapshot,result)
        with zipfile.ZipFile(output) as archive:
            assert archive.testzip() is None
            manifest=json.loads(archive.read('manifest.json'))
            assert [entry['kind'] for entry in manifest['tables']]==['crossfact_'+part for _,part,_ in tables]
            assert all(entry['analysis_id']==aid for entry in manifest['tables'])
            assert manifest['tables'][0]['protected_cells']
            rows=list(csv.DictReader(io.StringIO(archive.read('crossfact/001-aligned.csv').decode('utf-8-sig'))))
            assert len(rows)==20
            for actual,expected in zip(rows,analysis['rows']):
                assert actual['key']==expected['key']
                for field in ['a','b','result']:assert float(actual[field])==expected[field]
            assert json.loads(archive.read('analysis.json'))['analysis']==result
    elif format=='xlsx':
        import openpyxl
        with pd.ExcelWriter(output,engine='xlsxwriter',engine_kwargs={'options':{'strings_to_formulas':False,'strings_to_urls':False}}) as writer:
            pd.DataFrame([{'keep':'existing'}]).to_excel(writer,sheet_name='CF_001_summary',index=False)
            exports.analysis_excel(writer,snapshot,result,{'cf_001_summary'})
        workbook=openpyxl.load_workbook(output)
        for index,(_,part,table) in enumerate(tables,1):
            sheet=workbook[f'CF_{index:03d}_{part}'+('_2' if index==1 else '')]
            assert sheet['A1'].comment.text==aid
            rows=list(sheet.values);actual=[dict(zip(rows[0],row)) for row in rows[1:]]
            assert len(actual)==len(table['rows'])
            for a,e in zip(actual,table['rows']):
                for key,value in e.items():
                    if isinstance(value,float):assert a[key]==pytest.approx(value)
                    else:assert a[key]==value
        assert all(cell.data_type!='f' for sheet in workbook for row in sheet for cell in row)
    else:
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib.backends.backend_pdf import PdfPages
        from pypdf import PdfReader
        with matplotlib.rc_context({'font.sans-serif':['Microsoft JhengHei'],'pdf.fonttype':42}):
            with PdfPages(output) as pdf:exports.pdf_crossfact_pages(pdf,snapshot,result,'Snapshot '+snapshot['snapshot_id'])
        reader=PdfReader(output);text='\n'.join(page.extract_text() or '' for page in reader.pages)
        for token in [aid,'LOT-1001','LOT-1020','weighted_ratio','good_die','tested_die','correlation','cohorts','web-query-v7']:
            assert token in text,token
        assert len(reader.pages)>=4
    assert result==original


@pytest.mark.parametrize('state',['empty','constant','null'])
def test_crossfact_documents_preserve_degenerate_states(tmp_path,state):
    import json,zipfile
    from ai4bi_web_api import exports
    from pypdf import PdfReader
    import matplotlib
    from matplotlib.backends.backend_pdf import PdfPages
    frame=pd.DataFrame({'key':['x','y','z'],'value':[1.,1.,1.] if state=='constant' else [float('nan')]*3})
    if state=='empty':frame=frame.iloc[:0]
    contracts,settings=setup(frame,frame);analysis=analyze(contracts,settings)
    analysis.update(analysis_id='crossfact_degenerate',name='Degenerate',page_id='main',snapshot_id='fixed-snapshot',revision=1,
                    execution_contract='web-query-v7',data_versions={},filters=[],applied_filters=[],selected_query_filters=[],drill_context=None,filter_bookmark_id=None)
    snapshot={'report':{},'revision':1};result=dict(visuals={},snapshot_id='fixed-snapshot',crossfact_analyses={'crossfact_degenerate':analysis})
    tables=list(exports.crossfact_tables(snapshot,result));correlation=tables[2][2]['rows'][0]
    assert correlation['r'] is None and correlation['status']==analysis['correlation_status']
    archive_path=tmp_path/'degenerate.zip';exports.csv_bundle(archive_path,snapshot,result)
    with zipfile.ZipFile(archive_path) as archive:
        assert json.loads(archive.read('analysis.json'))['analysis']==result
        assert json.loads(archive.read('manifest.json'))['tables'][1]['row_count']==len(analysis['rows'])
    output=tmp_path/'degenerate.pdf'
    with matplotlib.rc_context({'font.sans-serif':['Microsoft JhengHei'],'pdf.fonttype':42}):
        with PdfPages(output) as pdf:exports.pdf_crossfact_pages(pdf,snapshot,result,'fixed-snapshot')
    text='\n'.join(page.extract_text() or '' for page in PdfReader(output).pages)
    assert analysis['correlation_status'] in text and analysis['cohort_status'] in text
    assert 'crossfact_degenerate' in text


def test_crossfact_pdf_keeps_rows_beyond_ui_page(tmp_path):
    from ai4bi_web_api import exports
    import matplotlib
    from matplotlib.backends.backend_pdf import PdfPages
    from pypdf import PdfReader
    frame=pd.DataFrame({'key':[f'KEY-{i:04d}' for i in range(160)],'value':[float(i+1) for i in range(160)]})
    contracts,settings=setup(frame,frame);analysis=analyze(contracts,settings)
    analysis.update(analysis_id='crossfact_full',name='Full rows',page_id='main',snapshot_id='full-snapshot',revision=1,
                    execution_contract='web-query-v7',data_versions={},filters=[],applied_filters=[],selected_query_filters=[],drill_context=None,filter_bookmark_id=None)
    output=tmp_path/'all-rows.pdf'
    with matplotlib.rc_context({'font.sans-serif':['Microsoft JhengHei'],'pdf.fonttype':42}):
        with PdfPages(output) as pdf:exports.pdf_crossfact_pages(pdf,{'report':{}},{'crossfact_analyses':{'crossfact_full':analysis}},'full-snapshot')
    text='\n'.join(page.extract_text() or '' for page in PdfReader(output).pages)
    for i in range(160):assert f'KEY-{i:04d}' in text


def test_http_worker_crossfact_and_idempotent_snapshot(client):
    _, path, _ = workspace(client)
    body = request()
    accepted = client.post(path + '/analyses/crossfact', json=body)
    assert accepted.status_code == 202, accepted.text
    job = wait_job(client, accepted.json()['job_id'])
    assert job['status'] == 'succeeded', job
    result = job['result']
    assert result['aligned_count'] == 20 and result['correlation']['r'] == -.716
    assert result['execution_contract'] == 'web-query-v7' and result['analysis_contract'] == 'crossfact-v1'
    assert len(result['data_versions']) == 3
    assert client.post(path + '/analyses/crossfact', json=body).json() == accepted.json()
    assert client.post(path + '/analyses/crossfact', json={**body, 'operation':'diff'}).status_code == 409
    changed = command(client, path, 1, 'add_filter', {'filter':dict(scope='report',block_id='fab_process_move',column_name='step_name',operator='eq',value='Etch')}, key='crossfact-later-edit')
    assert changed.status_code == 200
    assert client.post(path + '/analyses/crossfact', json=body).json() == accepted.json()
    assert client.get('/api/v1/jobs/' + accepted.json()['job_id']).json()['result'] == result


def test_crossfact_saved_and_transient_scope_intersect(client):
    _, path, _ = workspace(client)
    changed = command(client, path, 1, 'add_filter', {'filter':dict(scope='report',block_id='fab_process_move',column_name='step_name',operator='eq',value='Etch')}, key='crossfact-report-filter')
    assert changed.status_code == 200
    body = {**request(), 'base_revision':2, 'selected_component_id':'bar_qt_step',
            'filters':[dict(source_visual_id='bar_qt_step',block_id='fab_process_move',column_name='step_name',operator='eq',value='Litho')]}
    accepted = client.post(path + '/analyses/crossfact', json=body)
    job = wait_job(client, accepted.json()['job_id'])
    assert job['status'] == 'succeeded', job
    assert job['result']['status'] == 'empty' and job['result']['rows'] == []
    assert job['result']['applied_filters'] == body['filters']


def test_crossfact_invalid_field_has_no_partial_result(client):
    _, path, _ = workspace(client)
    body = {**request(), 'key_a':'missing'}
    accepted = client.post(path + '/analyses/crossfact', json=body)
    job = wait_job(client, accepted.json()['job_id'])
    assert job['status'] == 'failed' and job['result'] is None
    assert job['error']['code'] == 'INVALID_CROSSFACT'
    assert client.post(path + '/analyses/crossfact', json={**request(), 'quantiles':True}).status_code == 422


@pytest.mark.parametrize('field,value,code', [('analysis_contract','old','CROSSFACT_INCOMPATIBLE'),
                                            ('execution_contract','web-query-v4','SNAPSHOT_RUNTIME_INCOMPATIBLE'),
                                            ('execution_contract','web-query-v3','SNAPSHOT_RUNTIME_INCOMPATIBLE')])
def test_crossfact_old_contract_rejected_before_data(client, monkeypatch, field, value, code):
    from ai4bi_web_api.crossfact import run_crossfact
    from ai4bi_web_api.jobs import make_snapshot
    ids, _, _ = workspace(client)
    snapshot = make_snapshot(client.app.state.store, ids['workspace_id'], ids['report_id'], 1,
                             {**request(), 'analysis_contract':'crossfact-v1'})
    snapshot[field] = value
    monkeypatch.setattr('ai4bi_web_api.core.load_contracts', lambda *args: pytest.fail('Read incompatible source'))
    with pytest.raises(AppError) as exc:
        run_crossfact(client.app.state.store.root, snapshot)
    assert exc.value.code == code


def setup(left=None, right=None):
    left = left if left is not None else pd.DataFrame({'key': ['x', 'x', 'y', 'z'], 'value': [10., 20., 40., 60.]})
    right = right if right is not None else pd.DataFrame({'key': ['x', 'x', 'y', 'z'], 'value': [2., 3., 10., 15.]})
    seed = fab_contracts()['fab_process_move']
    contracts = {}
    for name, frame in [('left', left), ('right', right)]:
        contract = seed.model_copy(deep=True)
        contract.block_id = name
        contract.columns = [ColumnSchema(name=c, data_type='string' if c == 'key' else 'float') for c in frame]
        contract.data_source = CachedDataSource(content_hash=put_dataframe(frame), row_count=len(frame))
        contracts[name] = contract
    settings = dict(block_a='left', block_b='right', key_a='key', key_b='key',
                    metric_a=dict(kind='aggregate', column='value', aggregation='SUM'),
                    metric_b=dict(kind='aggregate', column='value', aggregation='SUM'), quantiles=3)
    return contracts, settings


def test_aggregate_before_join_has_no_fanout_and_matches_hand_calculation():
    contracts, settings = setup()
    result = analyze(contracts, settings)
    assert result['rows'] == [dict(key='x', a=30., b=5., result=6.),
                              dict(key='y', a=40., b=10., result=4.),
                              dict(key='z', a=60., b=15., result=4.)]
    assert result['aligned_count'] == result['paired_count'] == 3
    assert result['correlation']['r'] == .982
    assert result['correlation_status'] == result['cohort_status'] == 'ready'
    assert [row['mean_b'] for row in result['cohorts']] == [5., 10., 15.]
    assert result['sources']['a']['input_rows'] == 4


@pytest.mark.parametrize('operation,expected', [('ratio', 6.), ('diff', 25.), ('margin_pct', 83.33)])
def test_combination_operations(operation, expected):
    contracts, settings = setup()
    result = analyze(contracts, {**settings, 'operation': operation})
    assert result['rows'][0]['result'] == expected


@pytest.mark.parametrize('aggregation,expected', [('SUM', 30.), ('AVG', 15.), ('COUNT', 2), ('MIN', 10.), ('MAX', 20.)])
def test_all_original_aggregations(aggregation, expected):
    contracts, settings = setup()
    settings['metric_a']['aggregation'] = aggregation
    assert analyze(contracts, settings)['rows'][0]['a'] == expected


def test_weighted_ratio_uses_additive_totals_not_average_percentages():
    left = pd.DataFrame({'key': ['x', 'x'], 'good': [1., 90.], 'total': [2., 100.]})
    contracts, settings = setup(left)
    settings['metric_a'] = dict(kind='weighted_ratio', numerator_column='good', denominator_column='total', scale=100.)
    result = analyze(contracts, settings)
    assert result['rows'][0]['a'] == pytest.approx(91 / 102 * 100)
    assert result['rows'][0]['a'] != 70
    assert result['sources']['b']['unmatched_groups'] == 2


@pytest.mark.parametrize('operation', ['ratio', 'margin_pct'])
def test_zero_denominator_is_null_and_counted(operation):
    frame = pd.DataFrame({'key': ['x', 'y', 'z'], 'value': [0., 1., 2.]})
    contracts, settings = setup(frame, frame)
    result = analyze(contracts, {**settings, 'operation': operation})
    assert result['rows'][0]['result'] is None
    assert result['zero_denominator_count'] == 1
    assert result['paired_count'] == 3


def test_missing_keys_measures_and_unmatched_groups_are_separate():
    left = pd.DataFrame({'key': ['x', 'x', None, 'only_a', 'null'], 'value': [1., None, 99., 9., None]})
    right = pd.DataFrame({'key': ['x', 'only_b', 'null'], 'value': [2., 4., 3.]})
    contracts, settings = setup(left, right)
    result = analyze(contracts, settings)
    assert result['aligned_count'] == 2 and result['paired_count'] == 1 and result['missing_pair_count'] == 1
    assert result['sources']['a'] == dict(input_rows=5, excluded_key_rows=1, missing_measure_rows=2, group_count=3, unmatched_groups=1)
    assert result['sources']['b']['unmatched_groups'] == 1
    assert next(row for row in result['rows'] if row['key'] == 'null')['a'] is None
    settings['metric_a']['aggregation'] = 'COUNT'
    assert next(row for row in analyze(contracts, settings)['rows'] if row['key'] == 'null')['a'] == 0


def test_weighted_zero_denominator_excludes_pair_without_inventing_zero():
    contracts, settings = setup(pd.DataFrame({'key': ['x'], 'n': [1.], 'd': [0.]}))
    settings['metric_a'] = dict(kind='weighted_ratio', numerator_column='n', denominator_column='d')
    result = analyze(contracts, settings)
    assert result['rows'] == [dict(key='x', a=None, b=5., result=None)]
    assert result['missing_pair_count'] == 1


def test_empty_population_retains_explicit_status():
    contracts, settings = setup(pd.DataFrame({'key': pd.Series(dtype=str), 'value': pd.Series(dtype=float)}))
    result = analyze(contracts, settings)
    assert result['status'] == 'empty' and result['rows'] == []
    assert result['correlation_status'] == result['cohort_status'] == 'insufficient_pairs'


def test_constant_metric_and_tied_quantiles():
    frame = pd.DataFrame({'key': [str(i) for i in range(10)], 'value': [1.] * 10})
    contracts, settings = setup(frame, frame)
    result = analyze(contracts, settings)
    assert result['correlation_status'] == result['cohort_status'] == 'constant_metric'
    assert result['correlation'] is None and result['cohorts'] == []
    frame['value'] = [1.] * 5 + [2.] * 5
    contracts, settings = setup(frame, frame)
    result = analyze(contracts, {**settings, 'quantiles': 5})
    assert result['actual_quantiles'] < 5
    assert sum(row['count'] for row in result['cohorts']) == 10


@pytest.mark.parametrize('value', [float('inf'), float('-inf'), True, '4'])
def test_invalid_numeric_inputs(value):
    contracts, settings = setup(pd.DataFrame({'key': ['x'], 'value': [value]}))
    with pytest.raises(AppError, match='數字|無限'):
        analyze(contracts, settings)


@pytest.mark.parametrize('keys', [[1, 2], ['x', 1], [True, False], [float('inf')], [['x']]])
def test_key_identity_not_coerced(keys):
    contracts, settings = setup(pd.DataFrame({'key': keys, 'value': [1.] * len(keys)}))
    with pytest.raises(AppError) as exc:
        analyze(contracts, settings)
    assert exc.value.code == 'CROSSFACT_KEY_TYPE_MISMATCH'


def test_capacity_rejects_without_silent_truncation(monkeypatch):
    contracts, settings = setup()
    monkeypatch.setattr('ai4bi_web_api.crossfact.MAX_GROUPS', 2)
    with pytest.raises(AppError) as exc:
        analyze(contracts, settings)
    assert exc.value.code == 'CROSSFACT_LIMIT'


def test_projection_handles_user_identifier_quotes_and_output_collisions():
    contracts, settings = setup()
    from ai4bi.blocks.datastore import materialize_dataframe
    for side, bid in [('a', 'left'), ('b', 'right')]:
        key, column = ('key"; DROP TABLE left; --', 'result') if side == 'a' else ('other key', 'group_key')
        frame = materialize_dataframe(contracts[bid]).rename(columns={'key': key, 'value': column})
        contracts[bid].columns = [ColumnSchema(name=key, data_type='string'), ColumnSchema(name=column, data_type='float')]
        contracts[bid].data_source = CachedDataSource(content_hash=put_dataframe(frame), row_count=len(frame))
        settings['key_' + side] = key
        settings['metric_' + side]['column'] = column
    result = analyze(contracts, settings)
    assert result['rows'][0] == dict(key='x', a=30., b=5., result=6.)


@pytest.mark.parametrize('change', [dict(block_b='left'), dict(key_a='value'), dict(key_a='missing')])
def test_invalid_sources_or_fields(change):
    contracts, settings = setup()
    with pytest.raises(AppError):
        analyze(contracts, {**settings, **change})


@pytest.mark.parametrize('change', [dict(quantiles=True), dict(quantiles=1), dict(operation='sql'),
                                   dict(metric_a=dict(kind='aggregate', column='value', aggregation='MEDIAN')),
                                   dict(metric_a=dict(kind='weighted_ratio', numerator_column='value', denominator_column='value', scale=float('inf')))])
def test_settings_reject_unknown_or_unsafe_operations(change):
    _, settings = setup()
    with pytest.raises(ValidationError):
        CrossFactSettings.model_validate({**settings, **change})


def test_fab_result_matches_pinned_core_and_does_not_mutate_contracts():
    from ai4bi.analysis.crossfact import align_two_facts, correlate_facts
    contracts = fab_contracts()
    before = copy.deepcopy(contracts)
    settings = dict(block_a='fab_process_move', block_b='fab_wafer_yield', key_a='lot_id', key_b='lot_id',
                    metric_a=dict(kind='aggregate', column='queue_time_hr', aggregation='AVG'),
                    metric_b=dict(kind='aggregate', column='yield_pct', aggregation='AVG'))
    result = analyze(contracts, settings)
    expected = align_two_facts(contracts, block_a='fab_process_move', block_b='fab_wafer_yield',
                               col_a='queue_time_hr', col_b='yield_pct', agg_a='AVG', agg_b='AVG',
                               alias_a='a', alias_b='b', join_key='lot_id')
    assert result['aligned_count'] == 20
    assert result['correlation'] == correlate_facts(expected, 'a', 'b')
    assert contracts == before


def test_declared_type_mismatch_rejected_before_materialization(monkeypatch):
    contracts, settings = setup()
    contracts['right'].columns[0].data_type = 'integer'
    monkeypatch.setattr('ai4bi.blocks.datastore.materialize_dataframe', lambda *args: pytest.fail('Read before validation'))
    with pytest.raises(AppError) as exc:
        analyze(contracts, settings)
    assert exc.value.code == 'CROSSFACT_KEY_TYPE_MISMATCH'


def test_non_fact_source_rejected_before_materialization(monkeypatch):
    from ai4bi.blocks.contracts import BlockType
    contracts, settings = setup()
    contracts['right'].block_type = BlockType.dimension
    monkeypatch.setattr('ai4bi.blocks.datastore.materialize_dataframe', lambda *args: pytest.fail('Read before validation'))
    with pytest.raises(AppError):
        analyze(contracts, settings)


def test_aggregate_overflow_is_explicit_failure():
    contracts, settings = setup(pd.DataFrame({'key': ['x', 'x'], 'value': [1e308, 1e308]}))
    with pytest.raises(AppError) as exc:
        analyze(contracts, settings)
    assert exc.value.code == 'CROSSFACT_NONFINITE'


def test_combination_overflow_is_explicit_failure():
    contracts, settings = setup(pd.DataFrame({'key': ['x'], 'value': [1e308]}),
                               pd.DataFrame({'key': ['x'], 'value': [1e-308]}))
    with pytest.raises(AppError) as exc:
        analyze(contracts, settings)
    assert exc.value.code == 'CROSSFACT_NONFINITE'


@pytest.mark.parametrize('helper', ['correlate_facts', 'cohort_by_quantile'])
def test_missing_statistics_cannot_be_success(helper, monkeypatch):
    contracts, settings = setup()
    monkeypatch.setattr('ai4bi.analysis.crossfact.' + helper,
                        lambda *args, **kwargs: None if helper == 'correlate_facts' else pd.DataFrame())
    with pytest.raises(AppError) as exc:
        analyze(contracts, settings)
    assert exc.value.code == 'CROSSFACT_STATISTICS_UNAVAILABLE'


def test_numeric_shared_keys_sorted_numerically():
    frame = pd.DataFrame({'key': [10, 2, 1], 'value': [10., 2., 1.]})
    contracts, settings = setup(frame, frame)
    for contract in contracts.values():
        contract.columns[0].data_type = 'integer'
    assert [row['key'] for row in analyze(contracts, settings)['rows']] == [1, 2, 10]


def test_categorical_keys_do_not_create_unobserved_groups():
    frame = pd.DataFrame({'key': pd.Categorical(['x', 'y'], categories=['x', 'y', 'unused']), 'value': [1., 2.]})
    contracts, settings = setup(frame, frame)
    result = analyze(contracts, settings)
    assert result['aligned_count'] == result['sources']['a']['group_count'] == 2

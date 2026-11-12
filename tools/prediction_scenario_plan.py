"""Pure prepared-scenario validation and original-client diagnostic argv."""
from tools.prediction_mobile_plan import (
    EXPIRED_CLICK_MOBILE_FLAGS, validate_cohort_survivor_plan,
    validate_mobile_held_click_plan, validate_mobile_context_move_plan,
    validate_mobile_context_hold_plan, validate_mobile_original_hold_plan,
)


def require(value, message):
    if not value:
        raise AssertionError(message)


def validate_expired_click_plan(plan):
    require('expired_click' not in plan or type(plan['expired_click']) is bool,
            'prepared expired click option must be Boolean')
    if not plan.get('expired_click'):
        return
    require(plan.get('actor_correction') is True and plan.get('scenario') == 'movement' and
            plan.get('lifecycle') == 'natural' and type(plan.get('frames')) is int and plan['frames'] == 650 and
            type(plan.get('expected_matches')) is int and plan['expected_matches'] == 2 and
            type(plan.get('move_slot')) is int and plan['move_slot'] == 0 and plan.get('rtt_ms') == [130,475] and
            all(type(plan.get(key, False)) is bool and not plan.get(key, False) for key in
                (*EXPIRED_CLICK_MOBILE_FLAGS, 'changing_rtt', 'transition_orders')) and
            plan.get('native_position_trace') is None,
            'expired click requires explicit HQ actor correction, natural movement650, slot0,130/475ms and no other fixture')


def validate_held_click_plan(plan):
    require('actor_mirror' not in plan or type(plan['actor_mirror']) is bool,
            'prepared actor mirror option must be Boolean')
    require(not plan.get('actor_mirror') or plan.get('held_click') is True,
            'actor mirror requires explicit held click')
    require('held_click' not in plan or type(plan['held_click']) is bool,
            'prepared held click option must be Boolean')
    if not plan.get('held_click'):
        return
    require(not plan.get('expired_click'), 'held and expired click fixtures are mutually exclusive')
    if plan.get('actor_mirror'):
        require(plan.get('actor_correction') is True and plan.get('scenario') == 'movement' and
            plan.get('lifecycle') == 'natural' and type(plan.get('frames')) is int and plan['frames'] == 650 and
            type(plan.get('expected_matches')) is int and plan['expected_matches'] == 2 and
            type(plan.get('move_slot')) is int and plan['move_slot'] == 0 and plan.get('rtt_ms') == [475,130] and
            all(type(plan.get(key, False)) is bool and not plan.get(key, False) for key in
                (*EXPIRED_CLICK_MOBILE_FLAGS, 'changing_rtt', 'transition_orders')) and
            plan.get('native_position_trace') is None,
            'actor mirror requires held HQ natural movement650, slot0,475/130ms and no other fixture')
        require('actor_fixture' not in plan or plan['actor_fixture'] == actor_fixture_metadata(True),
                'prepared actor mirror metadata changed')
    else:
        validate_expired_click_plan(dict(plan, expired_click=True))


def validate_terminal_timeline_plan(plan):
    require('terminal_timeline' not in plan or type(plan['terminal_timeline']) is bool,
            'prepared terminal timeline option must be Boolean')
    if not plan.get('terminal_timeline'):
        return
    require(plan.get('actor_mirror') is True and plan.get('held_click') is True,
            'terminal timeline requires explicit mirror held click')
    validate_held_click_plan(plan)


def command_extra(plan, index, run):
    from tools import prediction_visual_correction as visual
    from tools import prediction_visual_input as visual_input
    from tools import prediction_visual_click as visual_click
    from tools import prediction_visual_aim as visual_aim
    from tools import prediction_visual_acquire as visual_acquire
    visual.validate_plan(plan)
    visual_input.validate_plan(plan)
    visual_click.validate_plan(plan)
    visual_aim.validate_plan(plan)
    visual_acquire.validate_plan(plan)
    from tools.prediction_close_formation_evidence import validate_plan as validate_close_plan
    from tools.prediction_queued_orders_evidence import validate_plan as validate_queued_plan
    validate_close_plan(plan)
    validate_queued_plan(plan)
    validate_cohort_survivor_plan(plan)
    validate_expired_click_plan(plan)
    validate_held_click_plan(plan)
    validate_terminal_timeline_plan(plan)
    validate_mobile_held_click_plan(plan)
    validate_mobile_context_move_plan(plan)
    validate_mobile_context_hold_plan(plan)
    validate_mobile_original_hold_plan(plan)
    from tools.prediction_multi_unit_evidence import validate_plan as validate_cohort_plan
    validate_cohort_plan(plan)
    role = ('host', 'guest')[index]
    result = [f'-community-match-{role}-smoke', '-lan-smoke', '-dedicated-surrender-smoke',
        '-dedicated-surrender-frame=' + str(plan['surrender_frame']),
        '-prediction-movement-experimental', '-frame-timing',
        '-frame-timing-frames=' + str(plan['frames']), '-lan-audit',
        '-prediction-worker-python=' + plan['files']['python']['path'],
        '-prediction-worker-module-root=' + plan.get('worker_module_root', plan['module_root']),
        '-prediction-worker-heap-helper=' + plan['files']['heap_helper']['path'],
        '-prediction-worker-cooperative=' + plan['files']['cooperative']['path'],
        '-prediction-worker-data-dir=' + str(run / f'worker-data-{index}')]
    if plan['scenario'] == 'movement':
        result += ['-prediction-movement-smoke','-prediction-movement-smoke-slot='+str(index),
            '-prediction-movement-smoke-start-frame='+str(440 if index==plan['move_slot']else 460)]
    if plan.get('close_formation'):
        result.append('-prediction-close-formation-smoke')
        if index==1:result.append('-prediction-movement-observe-cohort='+plan['native_cohort_spec'])
    if plan.get('queued_orders'):
        result.append('-prediction-queued-orders-smoke')
        if index==1:result.append('-prediction-movement-observe-cohort='+plan['native_cohort_spec'])
    if plan.get('actor_correction'):
        result.append('-prediction-actor-correction-smoke')
    if plan.get('actor_mirror'):
        result.append('-prediction-actor-mirror-smoke')
    if plan.get('terminal_timeline'):
        result.append('-prediction-terminal-timeline-smoke')
    if plan.get('expired_click'):
        result.append('-prediction-expired-click-smoke')
    if plan.get('held_click'):
        result.append('-prediction-held-click-smoke')
    if plan.get('mobile_correction'):
        result.append('-prediction-mobile-correction-smoke')
    if plan.get('cohort_survivor'):
        require(plan.get('native_cohort_spec')=='1:1:130:220:8','survivor cohort spec missing/different')
        result.append('-prediction-cohort-survivor-smoke')
        if plan.get('cohort_canonical_death'):result.append('-prediction-cohort-canonical-death-smoke')
        if index==1:result.append('-prediction-movement-observe-cohort='+plan['native_cohort_spec'])
    if plan.get('multi_unit_move'):
        require(plan.get('native_cohort_spec')=='1:1:420:520:8','prepared native cohort observer specification missing/different')
        result.append('-prediction-cohort-smoke')
        if index==1:
            result.append('-prediction-movement-observe-cohort='+plan['native_cohort_spec'])
    if plan.get('mobile_group_intent'):
        result.append('-prediction-mobile-group-intent-smoke')
    if plan.get('mobile_group_user_edits'):
        result.append('-prediction-mobile-group-user-edits-smoke')
    if plan.get('mobile_recovery_stall'):
        result.append('-prediction-mobile-recovery-stall-smoke')
    if plan.get('mobile_recall'):
        result.append('-prediction-mobile-recall-smoke')
    if plan.get('mobile_focus'):
        result.append('-prediction-mobile-focus-smoke')
    if plan.get('mobile_focus_no_start'):
        result.append('-prediction-mobile-focus-no-start-smoke')
    if plan.get('mobile_focus_restart'):
        result.append('-prediction-mobile-focus-restart-smoke')
    if plan.get('mobile_caster_survey'):
        result.append('-prediction-mobile-caster-survey-smoke')
    if plan.get('mobile_caster_lifetime'):
        result.append('-prediction-mobile-caster-lifetime-smoke')
    if plan.get('mobile_ui_cast'):
        result.append('-prediction-mobile-ui-cast-smoke')
    if plan.get('mobile_held_click'):
        result.append('-prediction-mobile-held-click-smoke')
    if plan.get('mobile_context_move'):
        result.append('-prediction-mobile-context-move-smoke')
    if plan.get('mobile_context_hold'):
        result.append('-prediction-mobile-context-hold-smoke')
    if plan.get('mobile_original_hold'):
        result.append('-prediction-mobile-original-hold-smoke')
    if plan.get('changing_rtt') and index == plan['move_slot']:
        result.append('-prediction-movement-smoke-distance=48')
    if plan.get('transition_orders') and index == plan['move_slot']:
        result.append('-prediction-movement-smoke-transition-gates='+str(run/'transition-gates'))
    if plan.get('native_position_trace') is not None and index == plan['move_slot']:
        result.append('-prediction-movement-observe-position='+plan['native_position_trace'])
    if plan.get('visual_correction'):
        result += ['-prediction-visual-correction', '-prediction-presentation-stages']
        if index == plan['move_slot']:result.append('-prediction-visual-observe')
    if plan.get('visual_input') and index == plan['move_slot']:
        result.append('-prediction-visual-input-smoke')
    if plan.get('visual_click') and index == plan['move_slot']:
        result.append('-prediction-visual-click-smoke')
    if plan.get('visual_click_spatial') and index == plan['move_slot']:
        result.append('-prediction-visual-click-spatial')
    if plan.get('visual_click_acquire') and index == plan['move_slot']:
        result.append('-prediction-visual-click-acquire')
    if plan.get('publication_source')=='post-original-qpc' or plan.get('mobile_recovery_stall') or plan.get('multi_unit_move') or plan.get('cohort_survivor') or plan.get('close_formation') or plan.get('queued_orders'):
        result.append('-frame-timing-worlds=2')
    if plan['lifecycle'] == 'natural':
        result += ['-native-quit-smoke', '-native-quit-mode=confirm', '-native-quit-gate-smoke',
                   '-community-match-leave-quit-smoke']
    return result


def actor_fixture_metadata(mirror=False):
    from tools.prediction_actor_fixture import metadata
    return metadata(mirror)

"""Pure mobile fixture plan validation; no runtime or native actions."""


def require(value, message):
    if not value:
        raise AssertionError(message)


def validate_mobile_plan(plan):
    from tools.prediction_multi_unit_evidence import validate_plan as validate_cohort_plan
    validate_cohort_plan(plan)
    validate_mobile_held_click_plan(plan)
    validate_mobile_context_move_plan(plan)
    validate_mobile_context_hold_plan(plan)
    validate_mobile_original_hold_plan(plan)
    require(plan.get('scenario') == 'mobile' and plan.get('mobile_correction') is True and
            plan.get('lifecycle') == 'natural' and plan.get('frames') == 650 and plan.get('expected_matches') == 2 and
            plan.get('move_slot') == 0 and plan.get('rtt_ms') == [130,475] and
            plan.get('generic_movement_not_exercised') is True and not plan.get('actor_correction') and
            not plan.get('changing_rtt') and not plan.get('transition_orders') and plan.get('native_position_trace') is None,
            'prepared mobile scenario scope/fixture/650-frame natural contract differs')
    require(all(key not in plan or type(plan[key]) is bool for key in ('mobile_group_intent','mobile_group_user_edits','mobile_recovery_stall','mobile_recall','mobile_focus','mobile_focus_no_start','mobile_focus_restart','mobile_caster_survey','mobile_caster_lifetime','mobile_ui_cast')) and
            (not plan.get('mobile_group_user_edits') or plan.get('mobile_group_intent') is True) and
            (not plan.get('mobile_recovery_stall') or plan.get('mobile_group_user_edits') is True) and
            (not plan.get('mobile_recall') or (plan.get('mobile_group_intent') is True and
             not plan.get('mobile_group_user_edits') and not plan.get('mobile_recovery_stall'))) and
            (not plan.get('mobile_focus') or (plan.get('mobile_group_intent') is True and not plan.get('mobile_recall') and
             not plan.get('mobile_group_user_edits') and not plan.get('mobile_recovery_stall'))) and
            (not plan.get('mobile_caster_survey') or (plan.get('mobile_group_intent') is True and not plan.get('mobile_focus') and
             not plan.get('mobile_recall') and not plan.get('mobile_group_user_edits') and not plan.get('mobile_recovery_stall'))) and
            (not plan.get('mobile_caster_lifetime') or (plan.get('mobile_group_intent') is True and not plan.get('mobile_focus') and
             not plan.get('mobile_recall') and not plan.get('mobile_caster_survey') and not plan.get('mobile_group_user_edits') and not plan.get('mobile_recovery_stall'))) and
            (not plan.get('mobile_ui_cast') or (plan.get('mobile_group_intent') is True and not plan.get('mobile_caster_lifetime') and
             not plan.get('mobile_focus') and not plan.get('mobile_recall') and not plan.get('mobile_caster_survey') and
             not plan.get('mobile_group_user_edits') and not plan.get('mobile_recovery_stall'))) and
            (not plan.get('mobile_focus_no_start') or (plan.get('mobile_focus') is True and plan.get('mobile_group_intent') is True and
             not any(plan.get(k)for k in('mobile_recall','mobile_group_user_edits','mobile_recovery_stall','mobile_caster_survey','mobile_caster_lifetime','mobile_ui_cast')))) and
            (not plan.get('mobile_focus_restart') or plan.get('mobile_focus_no_start')is True),
            'prepared mobile group edits require typed explicit group intent')


EXPIRED_CLICK_MOBILE_FLAGS = ('mobile_correction', 'mobile_group_intent', 'mobile_group_user_edits',
    'mobile_recovery_stall', 'mobile_recall', 'mobile_focus', 'mobile_focus_no_start', 'mobile_focus_restart',
    'mobile_caster_survey', 'mobile_caster_lifetime', 'mobile_ui_cast', 'mobile_held_click', 'mobile_context_move', 'mobile_context_hold', 'mobile_original_hold')

MOBILE_HELD_EXCLUSIONS = ('actor_correction', 'actor_mirror', 'terminal_timeline', 'held_click',
    'expired_click', 'changing_rtt', 'transition_orders', 'multi_unit_move', 'mobile_group_intent', 'mobile_group_user_edits',
    'mobile_recovery_stall', 'mobile_recall', 'mobile_focus', 'mobile_focus_no_start', 'mobile_focus_restart',
    'mobile_caster_survey', 'mobile_caster_lifetime', 'mobile_ui_cast', 'mobile_context_move', 'mobile_context_hold', 'mobile_original_hold')

MOBILE_CONTEXT_EXCLUSIONS = tuple(key for key in MOBILE_HELD_EXCLUSIONS if key not in ('mobile_context_move','mobile_context_hold')) + ('mobile_held_click',)
MOBILE_ORIGINAL_HOLD_EXCLUSIONS = tuple(key for key in MOBILE_CONTEXT_EXCLUSIONS if key != 'mobile_original_hold') + ('mobile_context_move','mobile_context_hold')
MULTI_UNIT_EXCLUSIONS = tuple(key for key in MOBILE_HELD_EXCLUSIONS if key != 'multi_unit_move') + ('mobile_held_click',)


def validate_mobile_original_hold_plan(plan):
    require('mobile_original_hold' not in plan or type(plan['mobile_original_hold']) is bool,
            'prepared mobile original Hold option must be Boolean')
    if not plan.get('mobile_original_hold'):
        return
    require(plan.get('scenario')=='mobile' and plan.get('mobile_correction') is True and
        plan.get('lifecycle')=='natural' and type(plan.get('frames')) is int and plan['frames']==650 and
        type(plan.get('expected_matches')) is int and plan['expected_matches']==2 and
        type(plan.get('move_slot')) is int and plan['move_slot']==0 and plan.get('rtt_ms')==[130,475] and
        plan.get('native_position_trace') is None and all(type(plan.get(k,False)) is bool and not plan.get(k,False)
            for k in MOBILE_ORIGINAL_HOLD_EXCLUSIONS),'original Hold requires exclusive mobile correction, natural650, slot0,130/475ms')


def validate_mobile_context_hold_plan(plan):
    require('mobile_context_hold' not in plan or type(plan['mobile_context_hold']) is bool,
            'prepared mobile context Hold option must be Boolean')
    if not plan.get('mobile_context_hold'):
        return
    require(plan.get('mobile_context_move') is True, 'mobile context Hold requires explicit genuine context Move')
    validate_mobile_context_move_plan(plan)


def validate_mobile_context_move_plan(plan):
    require('mobile_context_move' not in plan or type(plan['mobile_context_move']) is bool,
            'prepared mobile context Move option must be Boolean')
    if not plan.get('mobile_context_move'):
        return
    require(plan.get('scenario') == 'mobile' and plan.get('mobile_correction') is True and
            plan.get('lifecycle') == 'natural' and type(plan.get('frames')) is int and plan['frames'] == 650 and
            type(plan.get('expected_matches')) is int and plan['expected_matches'] == 2 and
            type(plan.get('move_slot')) is int and plan['move_slot'] == 0 and plan.get('rtt_ms') == [130,475] and
            plan.get('native_position_trace') is None and all(type(plan.get(key,False)) is bool and
                not plan.get(key,False) for key in MOBILE_CONTEXT_EXCLUSIONS),
            'mobile context Move requires explicit mobile correction, natural650, slot0,130/475ms and no other fixture')


def validate_mobile_held_click_plan(plan):
    require('mobile_held_click' not in plan or type(plan['mobile_held_click']) is bool,
            'prepared mobile held click option must be Boolean')
    if not plan.get('mobile_held_click'):
        return
    require(plan.get('scenario') == 'mobile' and plan.get('mobile_correction') is True and
            plan.get('lifecycle') == 'natural' and type(plan.get('frames')) is int and plan['frames'] == 650 and
            type(plan.get('expected_matches')) is int and plan['expected_matches'] == 2 and
            type(plan.get('move_slot')) is int and plan['move_slot'] == 0 and plan.get('rtt_ms') == [130,475] and
            plan.get('native_position_trace') is None and all(type(plan.get(key,False)) is bool and
                not plan.get(key,False) for key in MOBILE_HELD_EXCLUSIONS),
            'mobile held click requires explicit mobile correction, natural650, slot0,130/475ms and no other fixture')

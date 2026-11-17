"""Strategy knobs. All percentages are fractions of weighted starting combinations."""
P = {
    'version': 5,
    'pair_base': 44.0, 'pair_rank': 3.0, 'high_rank': 3.0, 'low_rank': 1.5,
    'suited_bonus': 4.0, 'gap_penalty': 1.4, 'broadway_bonus': 8.0,
    'backup_weight': 0.08,
    'push_bb': 10.0, 'push_bb_heads_up': 12.0, 'push_bb_big_ante': 8.0,
    'big_ante_fraction': 0.15,
    'push_pct': (0.35, 0.35, 0.27, 0.20, 0.17, 0.14, 0.12, 0.10, 0.09, 0.08),
    'shove_call_fraction': 0.5, 'bubble_tighten': 0.75,
    'open_x': 2.5, 'limper_bb': 1.0,
    'open_early': 0.12, 'open_middle': 0.18, 'open_late': 0.28, 'open_sb': 0.35,
    'three_bet_pct': 0.06, 'three_bet_x': 3.0, 'call_next_pct': 0.12, 'call_max_bb': 2.0,
    'defend_minraise': 0.30, 'defend_minraise_bb': 0.50,
    'exploitable_fold': 0.80, 'exploitable_n': 8, 'exploit_threebet': 0.20,
    'real_threebet': 0.15,
    'value_bet': 0.70, 'pair_bet': 0.60, 'air_bet': 0.30, 'call_odds': 0.27,
    'cbet': 0.65, 'bluff_raise_decay': 0.5, 'shove_pot_behind': 1.5,
    'draw_selection_bonus': 2.0, 'selection_pair_bonus': 1.0,
    'selection_kicker_weight': 0.001,
    'min_hands': 12, 'prior_weight': 10.0, 'prior_vpip': 0.25, 'prior_pfr': 0.15,
    'prior_fold': 0.45, 'decay': 0.985,
    'station_vpip': 0.40, 'station_fold': 0.40, 'station_value_bet': 0.90,
    'station_open': 0.18, 'folder_fold': 0.70, 'folder_widen': 0.10,
    'dead_opportunities': 8,
}

P.update({
    'premium_floor_enabled': True, 'commitment_enabled': True, 'short_open_enabled': True,
    'wider_threebet_enabled': True, 'flop_guard_enabled': True,
    'premium_king_jam_bb': 40.0, 'premium_queen_jam_bb': 25.0,
    'premium_queen_call_fraction': 0.25, 'premium_king_call_fraction': 0.15,
    'premium_value_raise_max_fraction': 0.40,
    'aggressive_threebet_pct': 0.10, 'aggressive_threebet_call_next': 0.12,
    'aggressive_threebet_call_fraction': 0.25,
    'commitment_spr': 3.0, 'commitment_invested': 0.30,
    'commitment_big_overpair_spr': 6.0, 'good_kicker_rank': 12,
    'flop_two_pair_commit_spr': 1.5,
})

# V3 is opt-in. Keep the submitted V2 archive as the immutable comparison baseline.
P.update({
    'tag_enabled': False,
    'tag_open_tighten': 0.10, 'tag_call_tighten': 0.12,
    'tag_deep_bb': 40.0, 'tag_no_tighten_bb': 15.0,
    'tag_ante_relief': 2.0, 'tag_late_relief': 0.65,
    'tag_prior_weight': 20.0, 'tag_min_observations': 12.0, 'tag_full_observations': 40.0,
    'tag_confidence_sd': 1.0, 'tag_wide_margin': 0.06, 'tag_signal_scale': 0.18,
    'tag_reraise_prior': 0.10, 'tag_reraise_excess': 0.08,
    'tag_bluff_prior': 0.15, 'tag_bluff_target': 0.28,
    'tag_show_min': 4.0, 'tag_show_full': 16.0,
    'tag_call_prior': 0.40, 'tag_overcall_target': 0.60,
    'tag_bad_call_prior': 0.20, 'tag_bad_call_target': 0.35,
    'tag_expensive_odds': 0.25,
    'tag_value_threebet_extra': 0.025, 'tag_defend_extra': 0.035,
    'tag_max_defend_odds': 0.29, 'tag_max_flat_stack_fraction': 0.12,
    'tag_bluffcatch_extra': 0.10, 'tag_weak_bluffcatch_extra': 0.03,
    'tag_trap_frequency': 0.55, 'tag_trap_min_bb': 15.0,
    'tag_trap_min_spr': 1.5, 'tag_value_bet_extra': 0.22,
    'tag_risk_strength': 0.50, 'tag_cap_pressure_hands': 20,
})

# V5 correctness checks and explicit, independently measurable river range model.
P.update({
    'v5_river': True, 'v5_preflop': True,
    'value_flat_max_odds': 0.36, 'value_flat_max_stack': 0.15,
    'hu_open_call_max_bb': 3.0,
    'river_bluff_weight': 0.12, 'river_pair_weight': 0.60,
    'river_weak_pair_weight': 0.25, 'river_bluff_evidence_weight': 0.80,
    'river_risk_scale': 0.10, 'river_raise_risk': 0.025,
})

# V4 stack-aware policy; runtime memory remains the V3 explicit per-table schema.
P.update({
    'stack_deep_bb': 50.0, 'stack_spec_open_extra': 0.08,
    'stack_spec_call_extra': 0.08, 'stack_spec_call_fraction': 0.05,
    'stack_open_deep': 2.5, 'stack_open_medium': 2.2, 'stack_open_short': 2.0,
    'stack_heads_up_open': 0.65, 'stack_threehanded_open': 0.40,
    'stack_pair_bet': 0.50, 'stack_deep_value_bet': 0.80,
    'stack_station_value_bet': 0.90, 'stack_pair_call_fraction': 0.12,
    'stack_pair_bet_fraction': 0.15, 'stack_weak_call_fraction': 0.05,
    'stack_observe_hands': 6,
    'tag_min_observations': 6.0, 'tag_full_observations': 24.0,
})

# Local V4 improvements; independently switchable for ablation comparisons.
P.update({
    'fix_short_ranges': True, 'fix_river_calls': True, 'fix_selection': True,
    'fourhanded_open': 0.35, 'threehanded_open': 0.50,
    'heads_up_open': 0.68, 'heads_up_defend': 0.50,
    'heads_up_push': 0.60, 'heads_up_push_call': 0.40,
    'threehanded_push': 0.50, 'threehanded_push_call': 0.25,
    'heads_up_station_open': 0.68, 'river_pair_odds': 0.20,
    'select_category': (0.0, 25.0, 60.0, 90.0, 125.0, 155.0, 190.0, 225.0, 260.0),
    'select_pair_rank': 1.5, 'select_kicker': 0.025,
    'select_flush_out': 1.1, 'select_straight_out': 0.9,
    'select_nut_draw': 1.15, 'select_weak_pair_multiway': 1.5,
    'select_draw_multiway': 0.10, 'select_pressure_penalty': 0.5,
    'expose_connected_probability': 0.20,
    'exposure_keep_tie': 0.05,
})

# Correctness switches for isolated comparisons; premium override is preserved.
P.update({'river_guard_enabled': True, 'river_price_authoritative': True, 'diagnostics_enabled': True})

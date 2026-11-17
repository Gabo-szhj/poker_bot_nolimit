"""Bounded stack policy for three-card discard/reveal poker, not a GTO solver.

V2's selection, evaluator, ranking table and short-stack push ranges are retained.
V3's public evidence is used without its blanket deep-stack opening reduction.
No learning lives outside the platform's explicit per-table memory.
"""
from poker_agent_sdk import Action
from bot.params import P
from bot.cards import CARD, preflop_pct, tier, strength, select
from bot.strategy import decide, passive, call_or_free, raise_to, history_info
from bot import opp
from bot.tag_opp import signals
from bot.selection import choose_selection
from bot.aggression import premium_action


def opponent_modes(state, data):
    result = {'station': False, 'folder': False}
    for seat in state.seats:
        if seat.seat == state.seat or seat.status != 'active':
            continue
        e = opp.estimates(data['rows'][seat.seat])
        if e['hands'] < P['stack_observe_hands']:
            continue
        if e['vpip'] >= P['station_vpip'] and e['fold'] <= P['station_fold']:
            result['station'] = True
        if e['fold'] >= P['folder_fold'] or e['dead']:
            result['folder'] = True
        if e['fold_n'] >= P['exploitable_n'] and e['fold'] >= P['exploitable_fold']:
            result['exploit_seat'] = seat.seat
            result['real_threebet'] = e['threebet'] <= P['real_threebet']
    return result


def position(state):
    count = len(state.seats)
    alive = [(state.button + j) % count for j in range(1, count + 1)
             if state.seats[(state.button + j) % count].status != 'busted']
    n = len(alive)
    sb = state.button if n == 2 else alive[0]
    bb = alive[0] if n == 2 else alive[1]
    first = state.button if n == 2 else alive[2 % n]
    order = [(first + j) % count for j in range(count)
             if state.seats[(first + j) % count].status == 'active']
    behind = len(order) - order.index(state.seat) - 1
    # Postflop action starts after the button, including heads-up.
    hero_position = (state.seat - state.button - 1) % count
    in_position = all((s.seat - state.button - 1) % count < hero_position
                      for s in state.seats if s.seat != state.seat
                      and s.status in ('active', 'all_in'))
    return n, behind, sb, bb, in_position


def speculative(cards):
    """Three-card structures that retain a pair, nut suit, or connected options."""
    if len(cards) != 3:
        return False
    values = [CARD[c] for c in cards]
    ranks = sorted({r for r, _ in values})
    if len(ranks) == 2:
        return True  # Pocket pair plus a spare card: genuine set potential.
    if any(r == 14 and any(s == other_s and r != other_r
                          for other_r, other_s in values) for r, s in values):
        return True
    low = sorted(1 if r == 14 else r for r in ranks)
    return len(ranks) == 3 and min(ranks[-1] - ranks[0], low[-1] - low[0]) <= 4


def risk_factor(state, target):
    """Cheap payout-sensitive risk premium; exact ICM remains an offline check."""
    n = state.players_remaining
    payouts = [p for p in state.config.payouts if p > 0]
    if n <= 2 or len(payouts) < 2 or n > len(payouts) + 1:
        return 0.0
    me = state.seats[state.seat]
    hero_stack = me.stack + me.bet
    if target.stack + target.bet < hero_stack:
        return 0.0
    flatness = 1.0 - payouts[0] / sum(payouts)
    short = any(0 < s.stack + s.bet < 0.5 * hero_stack for s in state.seats
                if s.seat not in (state.seat, target.seat) and s.status != 'busted')
    stage = 1.0 if n == len(payouts) + 1 else 0.5
    return min(0.6, flatness * stage * (1.25 if short else 1.0))


def start_stacks(state):
    """Reconstruct public hand-start stacks so big bets cannot erase deep status."""
    invested = [0] * len(state.seats)
    street_bets = [0] * len(state.seats)
    for e in state.history:
        if e.kind == 'board':
            street_bets = [0] * len(state.seats)
        elif e.seat is not None and e.kind in ('ante', 'blind', 'call', 'raise'):
            amount = max(0, e.amount - street_bets[e.seat]) if e.kind == 'raise' else e.amount
            invested[e.seat] += amount
            if e.kind != 'ante':
                street_bets[e.seat] += amount
    return [s.stack + invested[s.seat] for s in state.seats]


def sized_bet(state, fraction, strong=False, cap=None):
    """Use legal total raises, with explicit control over stack commitment."""
    me = state.seats[state.seat]
    legal = state.can('raise')
    if not legal:
        return call_or_free(state) if strong else passive(state)
    extra = max(state.blinds.big_blind, int((state.pot + state.to_call) * fraction))
    total = me.bet + state.to_call + extra
    if strong and me.stack - state.to_call - extra <= state.pot + state.to_call + extra:
        total = legal.max_amount
    if cap is not None:
        total = min(total, me.bet + int(cap))
        if total < legal.min_amount:
            return passive(state)
    return raise_to(state, total)


def sample(state):
    return ((state.hand_number * 2654435761 + len(state.board) * 2246822519
             + state.seat * 3266489917) & 0xffffffff) / 4294967296


def decide_stack(state, modes, data):
    if state.phase == 'select':
        choice = choose_selection(state) if P['fix_selection'] else select(state.cards, state.board)
        return Action('select', cards=choice)
    if state.phase != 'betting':
        return passive(state)
    me = state.seats[state.seat]
    opponents = [s for s in state.seats if s.seat != state.seat
                 and s.status in ('active', 'all_in')]
    if not opponents:
        return passive(state)
    raises, current, hero_bet, turn_called = history_info(state)
    n, behind, sb, bb_seat, in_position = position(state)
    bb = max(1, state.blinds.big_blind)
    # Match the relevant bettor rather than using an unrelated large stack.
    target = max(opponents, key=lambda s: s.bet if state.to_call else s.stack + s.bet)
    effective = min(me.stack + me.bet, target.stack + target.bet)
    depth = effective / bb
    risk = risk_factor(state, target)
    odds = min(state.to_call, me.stack) / max(1, state.pot + min(state.to_call, me.stack))
    if not state.board:
        return preflop(state, modes, data, opponents, raises, n, behind, sb, bb_seat,
                       in_position, target, depth, effective, risk, odds)
    return postflop(state, modes, data, opponents, current, raises, hero_bet,
                    turn_called, in_position, target, depth, effective, risk, odds)


def preflop(state, modes, data, opponents, raises, n, behind, sb, bb_seat,
            in_position, target, depth, effective, risk, odds):
    me = state.seats[state.seat]
    bb = max(1, state.blinds.big_blind)
    rank = preflop_pct(state.cards)
    premium = premium_action(state, raises, depth)
    if premium is not None:
        return premium
    push_limit = P['push_bb_heads_up'] if n == 2 else P['push_bb']
    if n >= 7 and state.blinds.ante / bb >= P['big_ante_fraction']:
        push_limit = P['push_bb_big_ante']
    facing_allin = any(s.status == 'all_in' and s.bet > me.bet for s in opponents)
    if depth <= push_limit:
        if P['short_open_enabled'] and P['fix_short_ranges'] and n == 4 and not raises and not facing_allin:
            if state.to_call == 0 and state.seat == bb_seat:
                return passive(state)
            if rank < P['fourhanded_open'] * (1 - 0.5 * risk):
                legal = state.can('raise')
                return raise_to(state, legal.max_amount) if legal else passive(state)
            return passive(state)
        if P['fix_short_ranges'] and n <= 3:
            # Keep endgame ranges here: returning to V2 would erase HU/3-handed widening.
            if state.to_call == 0 and state.seat == bb_seat and not raises:
                return passive(state)
            opened = bool(raises or facing_allin)
            threshold = (P['heads_up_push_call'] if opened else P['heads_up_push']) if n == 2 else (
                P['threehanded_push_call'] if opened else P['threehanded_push'])
            threshold *= 1 - 0.6 * risk
            if rank >= threshold:
                return passive(state)
            if facing_allin and (n == 2 or state.to_call >= me.stack):
                return call_or_free(state)
            legal = state.can('raise')
            return raise_to(state, legal.max_amount) if legal else call_or_free(state)
        # Retain the tested V2 position-aware push/fold strategy at short depth.
        return decide(state, modes)
    if facing_allin:
        # Deep stacks do not use a short-stack shove range against a large jam.
        cutoff = (0.05 if depth >= 40 else 0.09) * (1 - risk)
        if rank < cutoff and (odds <= 0.45 - 0.08 * risk or rank < 0.01):
            return call_or_free(state)
        return passive(state)
    if not raises:
        pct = (P['stack_heads_up_open'] if n == 2 and state.seat == sb
               else P['open_sb'] if state.seat == sb
               else P['stack_threehanded_open'] if n == 3 and behind <= 2
               else P['open_late'] if behind <= 2
               else P['open_middle'] if behind <= 4 else P['open_early'])
        if P['fix_short_ranges']:
            if n == 2 and state.seat == sb:
                pct = P['heads_up_open']
            elif n == 3:
                pct = P['threehanded_open']
            elif n == 4 and (P['short_open_enabled'] or state.seat != sb):
                pct = P['fourhanded_open']
        if modes.get('folder'):
            pct += P['folder_widen']
        if modes.get('station') and (n > 4 or not P['short_open_enabled']):
            pct = min(pct, P['station_open'] if n > 3 else 0.40)
            if not P['short_open_enabled'] and P['fix_short_ranges'] and n == 2 and state.seat == sb:
                pct = min(P['heads_up_open'], P['heads_up_station_open'])
        deep = depth >= P['stack_deep_bb']
        if deep and speculative(state.cards) and (in_position or behind <= 2):
            pct += P['stack_spec_open_extra'] * (1 - risk)
        pct *= 1 - 0.5 * risk
        if rank >= pct:
            return passive(state)
        limpers = sum(e.kind == 'call' for e in state.history)
        size = (P['stack_open_deep'] if depth >= 50 else
                P['stack_open_medium'] if depth >= 25 else P['stack_open_short'])
        return raise_to(state, bb * (size + limpers))
    last = raises[-1]
    evidence = signals(data['rows'][last.seat])
    base_threebet = P['aggressive_threebet_pct'] if P['wider_threebet_enabled'] else P['three_bet_pct']
    cutoff = base_threebet + P['tag_value_threebet_extra'] * evidence['wide']
    if modes.get('exploit_seat') == last.seat and len(raises) == 1:
        cutoff = P['exploit_threebet']
    cutoff *= 1 - 0.5 * risk
    # Each additional raise represents a stronger range, not permission to 5-bet light.
    if len(raises) >= 2:
        if (P['wider_threebet_enabled'] and len(raises) == 2 and
                rank < base_threebet + P['aggressive_threebet_call_next'] and
                state.to_call <= P['aggressive_threebet_call_fraction'] * me.stack):
            return call_or_free(state)
        cutoff = min(cutoff, 0.035 if len(raises) == 2 else 0.015)
    if rank < cutoff:
        total = last.amount * (2.7 if in_position else 3.2)
        if total - me.bet >= 0.4 * effective:
            # Only premium hands voluntarily commit a medium/deep effective stack.
            if rank < 0.02 * (1 - 0.5 * risk):
                legal = state.can('raise')
                return raise_to(state, legal.max_amount) if legal else call_or_free(state)
            max_odds = P['value_flat_max_odds'] - 0.08 * risk if P['v5_preflop'] else 0.28
            max_stack = P['value_flat_max_stack'] if P['v5_preflop'] else 0.12
            # The hand already qualifies for a value raise. A commitment cap must
            # not silently replace that range with a stricter marginal-call rule.
            return call_or_free(state) if odds <= max_odds and state.to_call <= max_stack * effective else passive(state)
        return raise_to(state, total)
    minraise = len(raises) == 1 and last.amount <= 2 * bb
    call_pct = ((P['defend_minraise_bb'] if state.seat == bb_seat else P['defend_minraise'])
                if minraise else P['three_bet_pct'] + P['call_next_pct'])
    if n <= 3 and minraise:
        call_pct = max(call_pct, 0.55 if state.seat == bb_seat else 0.40)
        if P['fix_short_ranges'] and n == 2 and state.seat == bb_seat:
            call_pct = P['heads_up_defend']
    if modes.get('station'):
        call_pct = min(call_pct, P['station_open'] if n > 3 else 0.40)
        if P['fix_short_ranges'] and n == 2 and state.seat == bb_seat and minraise:
            call_pct = P['heads_up_defend']
    call_pct *= 1 - 0.6 * risk
    affordable = state.to_call <= min(2 * bb, 0.10 * effective)
    if P['v5_preflop'] and n == 2 and len(raises) == 1:
        affordable = state.to_call <= min(P['hu_open_call_max_bb'] * bb, 0.10 * effective)
    if len(raises) == 1 and depth >= P['stack_deep_bb'] and in_position and speculative(state.cards):
        # Cheap speculative calls require the raiser to have enough chips to pay us.
        wide = evidence['wide']
        if wide > 0 or modes.get('station'):
            call_pct += P['stack_spec_call_extra'] * (1 - risk)
            affordable = state.to_call <= P['stack_spec_call_fraction'] * effective
    if len(raises) >= 2:
        call_pct = min(call_pct, 0.07 * (1 - risk))
        affordable = state.to_call <= 0.08 * effective
    return call_or_free(state) if affordable and rank < call_pct and odds <= 0.32 - 0.08 * risk else passive(state)


def postflop(state, modes, data, opponents, current, raises, hero_bet,
             turn_called, in_position, target, depth, effective, risk, odds):
    me = state.seats[state.seat]
    hand_tier, value = tier(state.cards, state.board)
    for s in opponents:
        if s.shown_cards and len(state.board) >= 4 and strength(tuple(s.shown_cards) + state.board) > value:
            return passive(state)  # Publicly beaten hands are never promoted by aggression.
    initial = start_stacks(state)
    start_effective = min(initial[state.seat], initial[target.seat])
    deep = start_effective / max(1, state.blinds.big_blind) >= P['stack_deep_bb']
    remaining = max(0, min(me.stack, target.stack + target.bet - me.bet))
    spr = remaining / max(1, state.pot)
    evidence = signals(data['rows'][target.seat])
    bluff = evidence['bluff'] * (1 - risk) if len(opponents) == 1 else 0.0
    facing = state.to_call > 0
    if P['fix_river_calls'] and len(state.board) == 5 and facing and hand_tier < 3:
        # The river has no remaining draw equity; weak tiers cannot buy another card.
        if hand_tier != 2 or value[0] != 1 or odds > P['river_pair_odds']:
            return passive(state)
    if hand_tier == 3:
        # Strong relative hands can still be vulnerable on a four-flush/straight board.
        suits = [c[1] for c in state.board]
        four_flush = max(suits.count(s) for s in set(suits)) >= 4
        board_ranks = {CARD[c][0] for c in state.board}
        if 14 in board_ranks:
            board_ranks.add(1)
        four_straight = any(sum(r in board_ranks for r in range(low, low + 5)) >= 4
                            for low in range(1, 11))
        vulnerable = (four_flush and value[0] < 5) or (four_straight and value[0] < 4)
        if vulnerable and facing and (odds > 0.25 or len(current) > 1):
            return passive(state)
        if facing and bluff > 0 and sample(state) < P['tag_trap_frequency'] * bluff:
            return call_or_free(state)
        size = (P['stack_station_value_bet'] if modes.get('station') or evidence['overcall'] > 0
                else P['stack_deep_value_bet'] if deep else P['value_bet'])
        allow_commit = not vulnerable
        if P['flop_guard_enabled'] and len(state.board) == 3 and value[0] == 2 and spr > P['flop_two_pair_commit_spr']:
            allow_commit = False
        return sized_bet(state, size, strong=allow_commit)
    if hand_tier == 2:
        # No automatic deep-stack shove with top pair or an overpair.
        limit = P['call_odds'] + P['tag_bluffcatch_extra'] * bluff - 0.07 * risk
        if len(opponents) > 1:
            limit -= 0.04
        if facing:
            if (hero_bet or len(current) > 1) and bluff <= 0:
                return passive(state)
            if deep and (state.to_call > P['stack_pair_call_fraction'] * start_effective
                         or state.to_call >= remaining):
                return passive(state)
            if depth > 15 and spr > 2 and state.to_call > 0.20 * effective:
                return passive(state)
            return call_or_free(state) if odds <= limit else passive(state)
        if hero_bet:
            return passive(state)
        if deep:
            cap = min(P['stack_pair_bet_fraction'] * start_effective,
                      max(0, remaining - max(1, state.blinds.big_blind)))
            return sized_bet(state, P['stack_pair_bet'], cap=cap)
        if spr <= 1.5 and depth <= 15 and len(opponents) == 1:
            return sized_bet(state, P['pair_bet'], strong=True)
        return sized_bet(state, P['stack_pair_bet'], cap=max(0, 0.25 * effective))
    if hand_tier == 1:
        if not facing:
            return passive(state)
        cap = P['stack_weak_call_fraction'] if deep else 0.12
        limit = P['call_odds'] - 0.06 * risk - (0.03 if len(opponents) > 1 else 0)
        return call_or_free(state) if odds <= limit and state.to_call <= cap * start_effective else passive(state)
    # Keep V2's bluff frequency ceiling and heads-up restriction; protect deep stacks.
    if facing or modes.get('station') or len(opponents) != 1 or len(state.board) >= 5 or turn_called or hero_bet:
        return passive(state)
    if not raises or raises[-1].seat != state.seat:
        return passive(state)
    frequency = (1.0 if modes.get('folder') else P['cbet'])
    frequency *= P['bluff_raise_decay'] ** sum(e.seat != state.seat for e in current)
    if sample(state) >= frequency:
        return passive(state)
    return sized_bet(state, P['air_bet'], cap=min(0.08 * start_effective, max(0, remaining - 1)))

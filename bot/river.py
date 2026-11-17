"""Exact river possibility bounds; an explicit weighted model for uncertain hands.

Enumerate every available hidden card compatible with the exposed card. Suit/rank
equivalent candidates share a rank evaluation within this call, never across calls.
Guarantees are independent of the heuristic range weights and tournament premium.
Only a single other non-folded player is supported, avoiding multiway side-pot
shortcuts. Folded public cards and our own private discard remain dead.
"""
from bot.cards import CARD, DECK, strength
from bot.params import P
from bot.strategy import passive, call_or_free
from bot.tag_opp import signals


def eligible_pot(state):
    """Final pot hero can win after calling, excluding unmatchable excess bets."""
    contributions = [0] * len(state.seats)
    bets = [0] * len(state.seats)
    for e in state.history:
        if e.kind == 'board':
            bets = [0] * len(state.seats)
        elif e.seat is not None and e.kind in ('blind', 'ante', 'call', 'raise'):
            paid = max(0, e.amount - bets[e.seat]) if e.kind == 'raise' else e.amount
            contributions[e.seat] += paid
            if e.kind != 'ante':
                bets[e.seat] += paid
    cost = min(state.to_call, state.seats[state.seat].stack)
    ceiling = contributions[state.seat] + cost
    # Incomplete synthetic histories are not sufficient to prove pot eligibility.
    if ceiling <= 0 or abs(sum(contributions) - state.pot) > 1:
        return None
    return ceiling + sum(min(c, ceiling) for i, c in enumerate(contributions) if i != state.seat)


def bounds(state):
    if len(state.board) != 5 or len(state.cards) != 2:
        return None
    opponents = [s for s in state.seats if s.seat != state.seat and s.status in ('active', 'all_in')]
    if len(opponents) != 1 or len(opponents[0].shown_cards) not in (1, 2):
        return None
    opponent = opponents[0]
    base = tuple(state.board) + tuple(opponent.shown_cards)
    if len(set(base + tuple(state.cards))) != len(base) + 2:
        return None
    own = strength(tuple(state.cards) + tuple(state.board))
    known = set(base + tuple(state.cards))
    known.update(state.variant.get('discarded', ()))
    for s in state.seats:
        known.update(s.shown_cards)
    for e in state.history:
        if e.kind in ('reveal', 'show'):
            known.update(e.cards)
    counts = [0] * 4
    for c in base:
        counts[CARD[c][1]] += 1
    flush_suit = next((i for i, n in enumerate(counts) if n >= 4), -1)
    cache = {}
    outcomes = []
    if len(opponent.shown_cards) == 2:
        outcomes.append(strength(base))
    else:
        for c in DECK:
            if c in known:
                continue
            rank, suit = CARD[c]
            key = (rank, suit == flush_suit)
            if key not in cache:
                cache[key] = strength(base + (c,))
            outcomes.append(cache[key])
    if not outcomes:
        return None
    wins = sum(own > value for value in outcomes)
    ties = sum(own == value for value in outcomes)
    return {'opponent': opponent, 'own': own, 'outcomes': outcomes,
            'minimum': min(outcomes), 'maximum': max(outcomes),
            'wins': wins, 'ties': ties, 'losses': len(outcomes) - wins - ties}


def decide_river(state, data, risk, result=None):
    result = bounds(state) if result is None else result
    if result is None or state.to_call <= 0:
        return None, None
    cost = min(state.to_call, state.seats[state.seat].stack)
    pot = eligible_pot(state)
    if not state.can('call'):
        return None, None
    required = cost / max(1, pot if pot is not None else state.pot + cost)
    outcomes = result['outcomes']
    count = len(outcomes)
    uniform = (result['wins'] + 0.5 * result['ties']) / count
    diagnostic = {'equity': uniform, 'uniform_equity': uniform,
                  'required_equity': required, 'risk_adjustment': 0.0,
                  'call_price': cost, 'eligible_pot': pot, 'action_adjustment': 0.0, 'reason': 0}
    if result['wins'] == count:
        diagnostic['reason'] = 1  # Strictly guaranteed winner; risk may not override it.
        return call_or_free(state), diagnostic
    if result['losses'] == count:
        diagnostic['reason'] = 2
        return passive(state), diagnostic
    if pot is None or pot < cost:
        # Proofs above hold even if a partial/reimbursed action history prevents
        # reconstructing the whole pot. Speculative equity calls need eligibility.
        return None, None
    if result['losses'] == 0 and 0.5 >= required:
        diagnostic['reason'] = 3  # At worst a tie, and the eligible pot covers the price.
        return call_or_free(state), diagnostic
    evidence = signals(data['rows'][result['opponent'].seat])
    bluff_weight = P['river_bluff_weight'] + P['river_bluff_evidence_weight'] * evidence['bluff']
    board_value = strength(tuple(state.board))
    board_top = max(CARD[c][0] for c in state.board)
    total_weight = won_weight = 0.0
    for value in outcomes:
        if value <= board_value or value[0] == 0:
            weight = bluff_weight
        elif value[0] == 1:
            weight = P['river_pair_weight'] if value[1] >= board_top else max(P['river_weak_pair_weight'], bluff_weight)
        else:
            weight = 1.0
        total_weight += weight
        won_weight += weight * (1.0 if result['own'] > value else 0.5 if result['own'] == value else 0.0)
    equity = won_weight / total_weight
    # Tournament premium is separate from the exposed-card estimate. An observed
    # raise after our bet is stronger evidence than an unraised first river bet.
    river_events = []
    for e in state.history:
        if e.kind == 'board':
            river_events = []
        elif e.kind == 'raise':
            river_events.append(e)
    action_premium = P['river_raise_risk'] if len(river_events) > 1 else 0.0
    tournament = risk * P['river_risk_scale']
    action_adjustment = action_premium * (1 - evidence['bluff'])
    premium = tournament + action_adjustment
    diagnostic.update(equity=equity, risk_adjustment=tournament,
                      action_adjustment=action_adjustment, reason=4)
    action = call_or_free(state) if equity >= required + premium else passive(state)
    return action, diagnostic


def certainty_action(state, result):
    """A heads-up showdown proof outranks all heuristic recommendations."""
    if result is None or state.to_call <= 0 or not state.can('call'):
        return None, None
    reason = (1 if result['own'] > result['maximum'] else
              2 if result['own'] < result['minimum'] else 0)
    if not reason:
        return None, None
    action = call_or_free(state) if reason == 1 else passive(state)
    cost = min(state.to_call, state.seats[state.seat].stack)
    pot = eligible_pot(state)
    return action, {'equity': float(reason == 1), 'uniform_equity': float(reason == 1),
        'call_price': cost, 'eligible_pot': pot,
        'required_equity': cost / max(1, pot if pot is not None else state.pot + cost),
        'risk_adjustment': 0.0, 'action_adjustment': 0.0, 'reason': reason}

"""Explicit premium and SPR exceptions, bounded by visible guaranteed losses."""
from bot.params import P
from bot.cards import CARD, tier, strength
from bot.strategy import history_info, call_or_free, raise_to


def premium_action(state, raises, depth):
    if not P['premium_floor_enabled']:
        return None
    ranks = [CARD[c][0] for c in state.cards]
    pair = next((r for r in (14, 13, 12) if ranks.count(r) >= 2), 0)
    # Explicit starting-hand floor requested by the user: any two of the three
    # original cards can form AA/KK/QQ/AKs/AKo. It is independent of percentiles.
    hard_premium = pair > 0 or (14 in ranks and 13 in ranks)
    me = state.seats[state.seat]
    opponents = [s for s in state.seats if s.seat != state.seat and s.status in ('active', 'all_in')]
    jam = any(s.status == 'all_in' and s.bet > me.bet for s in opponents)
    qualifies = hard_premium
    if pair == 13:
        qualifies = True
    if pair == 12:
        qualifies = True
    if not qualifies:
        return None
    if state.to_call > 0:
        if jam and len(opponents) == 1:
            return call_or_free(state)
        if pair not in (14, 13):
            # A floor prevents folds; it must not erase affordable value 3-bets.
            total = raises[-1].amount * P['three_bet_x'] if raises else 0
            effective = min(me.stack + me.bet, max(s.stack + s.bet for s in opponents))
            if jam or len(raises) != 1 or total - me.bet > P['premium_value_raise_max_fraction'] * effective:
                return call_or_free(state)
            return raise_to(state, total) if state.can('raise') else call_or_free(state)
    legal = state.can('raise')
    if not legal:
        return call_or_free(state)
    if len(raises) >= 2 or jam:
        return raise_to(state, legal.max_amount)
    total = raises[-1].amount * P['three_bet_x'] if raises else state.blinds.big_blind * P['stack_open_deep']
    return raise_to(state, total)


def commitment_action(state):
    if not P['commitment_enabled'] or state.phase != 'betting' or not state.board or state.to_call <= 0:
        return None
    from bot.stack import start_stacks
    me = state.seats[state.seat]
    opponents = [s for s in state.seats if s.seat != state.seat and s.status in ('active', 'all_in')]
    if not opponents:
        return None
    t, value = tier(state.cards, state.board)
    for s in opponents:
        if len(state.board) + len(s.shown_cards) >= 5 and s.shown_cards and strength(tuple(s.shown_cards) + state.board) > value:
            return None
    top = max(CARD[c][0] for c in state.board)
    own = [CARD[c][0] for c in state.cards]
    overpair = own[0] == own[1] and own[0] > top
    top_good = top in own and max(r for r in own if r != top) >= P['good_kicker_rank'] if own[0] != own[1] else False
    if not (overpair or top_good or t == 3):
        return None
    initial = start_stacks(state)[state.seat]
    remaining = min(me.stack, max(s.stack + s.bet - me.bet for s in opponents))
    # Measure SPR before the outstanding bet, so an enormous overbet alone cannot commit us.
    spr = remaining / max(1, state.pot - min(state.to_call, me.stack))
    invested = (initial - me.stack) / max(1, initial)
    _, current, _, _ = history_info(state)
    single = sum(e.seat != state.seat for e in current) <= 1
    protected = len(state.board) == 3 and overpair and own[0] >= 13 and single and spr <= P['commitment_big_overpair_spr']
    if protected or spr <= P['commitment_spr'] or invested >= P['commitment_invested']:
        return call_or_free(state)
    return None

"""Bounded Bay Area decisions; table state belongs exclusively to memory bytes."""
from poker_agent_sdk import Action
from bot.params import P
from bot.cards import CARD, preflop_pct, select, tier, strength


def passive(state):
    legal = getattr(state, 'legal_actions', ()) or ()
    for kind in ('check', 'fold', 'select', 'call'):
        if any(a.kind == kind for a in legal):
            return Action('select', cards=(2, 0)) if kind == 'select' else Action(kind)
    if legal:
        return Action(legal[0].kind, legal[0].min_amount)
    return Action.fold()


def call_or_free(state):
    if state.can('check'):
        return Action.check()
    if state.can('call'):
        return Action.call()
    return passive(state)


def raise_to(state, total):
    legal = state.can('raise')
    if legal and type(legal.min_amount) is int and type(legal.max_amount) is int:
        low, high = legal.min_amount, legal.max_amount
        if 0 <= low <= high:
            return Action.raise_to(max(low, min(high, int(total))))
    return call_or_free(state)


def bet(state, fraction):
    me = state.seats[state.seat]
    amount = max(state.blinds.big_blind, int(state.pot * fraction))
    total = me.bet + state.to_call + amount
    pot_after = state.pot + state.to_call + amount
    if me.stack - state.to_call - amount < P['shove_pot_behind'] * pot_after:
        legal = state.can('raise')
        if legal:
            total = legal.max_amount
    return raise_to(state, total)


def history_info(state):
    street = 0
    raises = []
    current = []
    hero_bet = False
    turn_called = False
    turn_aggressor = None
    for e in state.history:
        if e.kind == 'board':
            street += len(e.cards)
            current = []
            hero_bet = False
        elif e.kind == 'raise':
            current.append(e)
            if street == 0:
                raises.append(e)
            if e.seat == state.seat:
                hero_bet = True
            if street == 4:
                turn_aggressor = e.seat
        elif e.kind == 'call' and street == 4 and turn_aggressor == state.seat and e.seat != state.seat:
            turn_called = True
    return raises, current, hero_bet, turn_called


def decide(state, modes=None):
    if state.phase == 'select':
        return Action('select', cards=select(state.cards, state.board))
    if state.phase != 'betting':
        return passive(state)
    modes = modes or {}
    station = modes.get('station', False)
    folder = modes.get('folder', False)
    raises, current, hero_bet, turn_called = history_info(state)
    me = state.seats[state.seat]
    opponents = [s for s in state.seats if s.seat != state.seat and s.status in ('active', 'all_in')]
    if not opponents:
        return passive(state)
    if not state.board:
        rank = preflop_pct(state.cards)
        bb = max(1, state.blinds.big_blind)
        effective = min(me.stack, max(s.stack for s in opponents)) / bb
        n = len([s for s in state.seats if s.status != 'busted'])
        # Walk actual occupied seats: eliminated seats must not shift position.
        ring = [(state.button+j) % len(state.seats) for j in range(1, len(state.seats)+1)
                if state.seats[(state.button+j) % len(state.seats)].status != 'busted']
        sb_seat = state.button if n == 2 else ring[0]
        bb_seat = ring[0] if n == 2 else ring[1]
        first = state.button if n == 2 else ring[2 % len(ring)]
        order = [(first+i) % len(state.seats) for i in range(len(state.seats))]
        live_order = [i for i in order if state.seats[i].status == 'active']
        behind = len(live_order) - live_order.index(state.seat) - 1
        covering = any(s.stack > me.stack for s in opponents)
        paid = sum(p > 0 for p in state.config.payouts)
        bubble = covering and paid > 1 and state.players_remaining == paid + 1
        adjust = P['bubble_tighten'] if bubble else 1.0
        push_limit = P['push_bb_heads_up'] if n == 2 else P['push_bb']
        if n >= 7 and state.blinds.ante / bb >= P['big_ante_fraction']:
            push_limit = P['push_bb_big_ante']
        push_pct = P['push_pct'][min(behind, len(P['push_pct'])-1)] * adjust
        facing_allin = any(s.status == 'all_in' and s.bet > me.bet for s in opponents)
        if effective <= push_limit or facing_allin:
            threshold = push_pct * (P['shove_call_fraction'] if raises or facing_allin else 1)
            if station:
                threshold = min(threshold, P['station_open'])
            if rank < threshold:
                if facing_allin and state.to_call >= me.stack:
                    return call_or_free(state)
                legal = state.can('raise')
                return raise_to(state, legal.max_amount) if legal else call_or_free(state)
            return passive(state)
        if not raises:
            limpers = sum(e.kind == 'call' for e in state.history)
            pct = (P['open_sb'] if state.seat == sb_seat else P['open_late'] if behind <= 2
                   else P['open_middle'] if behind <= 4 else P['open_early'])
            if folder:
                pct += P['folder_widen']
            if station:
                pct = min(pct, P['station_open'])
            if rank < pct * adjust:
                return raise_to(state, bb * (P['open_x'] + P['limper_bb'] * limpers))
            return passive(state)
        last = raises[-1]
        threshold = P['three_bet_pct']
        if modes.get('exploit_seat') == last.seat:
            threshold = P['exploit_threebet']
            if len(raises) >= 2 and modes.get('real_threebet', True):
                threshold = P['three_bet_pct']
        if rank < threshold * adjust:
            return raise_to(state, P['three_bet_x'] * last.amount)
        minraise = len(raises) == 1 and last.amount <= 2 * bb
        call_pct = (P['defend_minraise_bb'] if state.seat == bb_seat else P['defend_minraise']) if minraise else threshold + P['call_next_pct']
        if station:
            call_pct = min(call_pct, P['station_open'])
        if state.to_call <= P['call_max_bb'] * bb and rank < call_pct * adjust:
            return call_or_free(state)
        return passive(state)
    hand_tier, value = tier(state.cards, state.board)
    # Exposed cards give a provable lower bound, not an estimate of hidden equity.
    for opponent in opponents:
        if opponent.shown_cards and len(state.board) >= 4:
            visible = strength(tuple(opponent.shown_cards) + state.board)
            if visible > value:
                hand_tier = min(hand_tier, 1)
    facing = state.to_call > 0
    odds = min(state.to_call, me.stack) / max(1, state.pot + min(state.to_call, me.stack))
    if hand_tier == 3:
        return bet(state, P['station_value_bet'] if station else P['value_bet'])
    if hand_tier == 2:
        if facing:
            # A raise after our own bet, or multiple opponent raises, gets respect.
            if hero_bet or len(current) > 1:
                return passive(state)
            return call_or_free(state) if odds <= P['call_odds'] else passive(state)
        if not hero_bet:
            return bet(state, P['station_value_bet'] if station else P['pair_bet'])
        return passive(state)
    if hand_tier == 1:
        return call_or_free(state) if facing and odds <= P['call_odds'] else passive(state)
    # River air never fires; a turn call explicitly prevents a later river bluff.
    if facing or station or len(opponents) != 1 or len(state.board) >= 5 or turn_called or hero_bet:
        return passive(state)
    hero_opened = bool(raises and raises[-1].seat == state.seat)
    if not hero_opened:
        return passive(state)
    frequency = 1.0 if folder else P['cbet']
    frequency *= P['bluff_raise_decay'] ** sum(e.seat != state.seat for e in current)
    sample = ((state.hand_number * 2654435761 + len(state.board) * 2246822519 + state.seat * 3266489917) & 0xffffffff) / 4294967296
    return bet(state, P['air_bet']) if sample < frequency else passive(state)

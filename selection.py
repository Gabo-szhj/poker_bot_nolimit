"""Single bounded keep score, using only information available at sealed selection.

Opponent three-card selection advantage is approximated by reducing weak made-hand
and non-nut-draw value as the number of contesting players increases. This is not
random-two-card equity. All three original cards are removed from draw outs.
This inherited heuristic is not a calibrated equity estimator.
"""
from bot.cards import CARD, strength, select
from bot.params import P


def keep_score(cards, board, discard, opponents, pressure=0):
    hole = tuple(c for i, c in enumerate(cards) if i != discard)
    value = strength(hole + board)
    category = value[0]
    score = P['select_category'][category]
    # A higher made pair must not lose to an unconditional pocket-pair bonus.
    score += (P['select_pair_rank'] if category == 1 else 0.12) * value[1]
    score += sum(rank * P['select_kicker'] / (10 ** j) for j, rank in enumerate(value[2:]))
    known = cards + board
    ranks = {CARD[c][0] for c in hole + board}
    if 14 in ranks:
        ranks.add(1)
    dead_ranks = [CARD[c][0] for c in known]
    flush_outs = 0
    nut_suit = False
    for suit in {CARD[c][1] for c in hole}:
        if sum(CARD[c][1] == suit for c in hole + board) == 4:
            flush_outs = 13 - sum(CARD[c][1] == suit for c in known)
            nut_suit = any(CARD[c] == (14, suit) for c in hole)
            break
    missing = set()
    for low in range(1, 11):
        window = set(range(low, low + 5))
        if len(window - ranks) == 1 and any(CARD[c][0] in window or
                                          (CARD[c][0] == 14 and 1 in window) for c in hole):
            rank = next(iter(window - ranks))
            missing.add(14 if rank == 1 else rank)
    straight_outs = sum(4 - dead_ranks.count(rank) for rank in missing)
    # Non-nut draws realize less equity against opponents who also choose from 3 cards.
    multi = max(0, opponents - 1)
    draw_discount = 1.0 / (1 + P['select_draw_multiway'] * multi)
    flush_weight = P['select_flush_out'] * (P['select_nut_draw'] if nut_suit else draw_discount)
    score += flush_weight * flush_outs + P['select_straight_out'] * straight_outs * draw_discount
    if category <= 1:
        pair_rank = value[1] if category == 1 else 0
        board_top = max(CARD[c][0] for c in board)
        weakness = max(0, board_top - pair_rank) / 12 if category == 1 else 1.0
        score -= weakness * (P['select_weak_pair_multiway'] * multi
                             + P['select_pressure_penalty'] * min(pressure, 3))
    return score, value


def choose_selection(state):
    cards, board = tuple(state.cards), tuple(state.board)
    if len(cards) != 3 or len(board) != 3:
        return select(cards, board)
    opponents = [s for s in state.seats if s.seat != state.seat and s.status in ('active', 'all_in')]
    pressure = sum(e.kind == 'raise' for e in state.history)
    choices = [keep_score(cards, board, i, len(opponents), pressure) for i in range(3)]
    discard = max(range(3), key=lambda i: (choices[i], -i))
    def information(i):
        rank, suit = CARD[cards[i]]
        return (sum(CARD[c][0] == rank for c in board),
                sum(CARD[c][1] == suit for c in board), rank)
    # Exposure may resolve effectively identical keeps, never a meaningful score gap.
    best_score, best_value = choices[discard]
    tied = [i for i in range(3) if choices[i][1] == best_value and
            best_score - choices[i][0] <= P['exposure_keep_tie']]
    discard = min(tied, key=lambda d: min(information(i) for i in range(3) if i != d))
    keep = tuple(i for i in range(3) if i != discard)
    reveal = min(keep, key=information)
    # Exposure is a separately switchable experiment. It cannot influence all-in play.
    mixed = P['expose_connected_probability']
    can_respond = any(s.status == 'active' and s.stack > 0 for s in opponents)
    if mixed > 0 and state.seats[state.seat].stack > 0 and can_respond:
        token = (state.hand_number * 2654435761 + state.seat * 3266489917) & 0xffffffff
        if token / 4294967296 < mixed:
            reveal = max(keep, key=information)
    return discard, reveal

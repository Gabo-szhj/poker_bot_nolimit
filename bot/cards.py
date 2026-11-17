"""Immutable import-time starting ranges and bounded rank/suit evaluation."""
from bot.params import P

RANKS = '23456789TJQKA'
CARD = {r+s: (i+2, j) for i, r in enumerate(RANKS) for j, s in enumerate('cdhs')}
CARD_ID = {c: i for i, c in enumerate(CARD)}
DECK = tuple(CARD)


def pair_key(a, b):
    ar, ass = CARD[a]
    br, bs = CARD[b]
    return max(ar, br), min(ar, br), ass == bs and ar != br


def pair_score(key):
    high, low, suited = key
    if high == low:
        return P['pair_base'] + P['pair_rank'] * high
    return (P['high_rank'] * high + P['low_rank'] * low + P['suited_bonus'] * suited
            - P['gap_penalty'] * max(0, high-low-1)
            + P['broadway_bonus'] * (low >= 10))


KEYS = tuple((h, l, suited) for h in range(2, 15) for l in range(2, h+1)
             for suited in ((False,) if h == l else (False, True)))
SORTED = sorted(KEYS, key=lambda k: (pair_score(k), k), reverse=True)
PAIR_PCT = {}
weight = 0
for key in SORTED:
    combos = 6 if key[0] == key[1] else 4 if key[2] else 12
    PAIR_PCT[key] = weight / 1326
    weight += combos

# Three cards give three candidate pairs, so two-card percentiles overstate strength.
# Calibrate their ordering against all 22,100 possible three-card deals at import.
PAIR_SCORE = {(i, j): pair_score(pair_key(DECK[i], DECK[j]))
              for i in range(52) for j in range(i+1, 52)}
TRIPLES = []
for i in range(50):
    for j in range(i+1, 51):
        for k in range(j+1, 52):
            scores = sorted((PAIR_SCORE[i, j], PAIR_SCORE[i, k], PAIR_SCORE[j, k]), reverse=True)
            TRIPLES.append((scores[0] + P['backup_weight'] * scores[1], (i, j, k)))
TRIPLES.sort(reverse=True)
THREE_PCT = {}
last_score = None
percentile = 0.0
for index, (score, key) in enumerate(TRIPLES):
    if score != last_score:
        percentile = index / 22100
        last_score = score
    THREE_PCT[key] = percentile
del TRIPLES, PAIR_SCORE


def preflop_pct(cards):
    if len(cards) == 3:
        return THREE_PCT[tuple(sorted(CARD_ID[c] for c in cards))]
    return PAIR_PCT[pair_key(cards[0], cards[1])]


def straight(mask):
    if mask & (1 << 14):
        mask |= 2  # A2345
    for high in range(14, 4, -1):
        if (mask >> (high-4)) & 31 == 31:
            return high
    return 0


def strength(cards):
    """Exact standard best-five ranking for 5–7 cards, without enumerating subsets."""
    counts = [0] * 15
    suits = [0] * 4
    suit_counts = [0] * 4
    mask = 0
    for c in cards:
        rank, suit = CARD[c]
        counts[rank] += 1
        mask |= 1 << rank
        suits[suit] |= 1 << rank
        suit_counts[suit] += 1
    flush = next((suits[s] for s in range(4) if suit_counts[s] >= 5), 0)
    if flush and (high := straight(flush)):
        return 8, high
    ranks = [r for r in range(14, 1, -1) if counts[r]]
    quads = [r for r in ranks if counts[r] == 4]
    trips = [r for r in ranks if counts[r] == 3]
    pairs = [r for r in ranks if counts[r] >= 2]
    if quads:
        return 7, quads[0], next(r for r in ranks if r != quads[0])
    if trips and len(pairs) >= 2:
        return 6, trips[0], next(r for r in pairs if r != trips[0])
    if flush:
        return (5, *(r for r in range(14, 1, -1) if flush & (1 << r)))[:6]
    if high := straight(mask):
        return 4, high
    if trips:
        return (3, trips[0], *(r for r in ranks if r != trips[0]))[:4]
    if len(pairs) >= 2:
        return 2, pairs[0], pairs[1], next(r for r in ranks if r not in pairs[:2])
    if pairs:
        return (1, pairs[0], *(r for r in ranks if r != pairs[0]))[:5]
    return (0, *ranks[:5])


def draw(hole, board):
    if len(board) >= 5:
        return False
    cards = hole + board
    suit_counts = [0]*4
    mask = 0
    for c in cards:
        rank, suit = CARD[c]
        suit_counts[suit] += 1
        mask |= 1 << rank
    if any(suit_counts[CARD[c][1]] == 4 for c in hole):
        return True
    if mask & (1 << 14):
        mask |= 2
    # A four-rank window is a draw only when a private card contributes.
    for high in range(14, 4, -1):
        window = 31 << (high-4)
        if (mask & window).bit_count() == 4 and any(window & (1 << CARD[c][0]) for c in hole):
            return True
    return False


def tier(hole, board):
    value = strength(hole + board)
    # Shared board strength alone is not a private value hand.
    board_value = strength(board) if len(board) == 5 else None
    if board_value is not None and value <= board_value:
        return 0, value
    board_counts = [0] * 15
    for c in board:
        board_counts[CARD[c][0]] += 1
    own = [CARD[c][0] for c in hole]
    top = max(CARD[c][0] for c in board)
    if value[0] >= 3:
        # Board trips with only kicker improvement are weak, not value trips.
        if value[0] == 3 and board_counts[value[1]] == 3:
            return 1, value
        return 3, value
    if value[0] == 2:
        private_pairs = [r for r in value[1:3] if r in own]
        if private_pairs and (not any(c >= 2 for c in board_counts) or max(private_pairs) >= top):
            return 3, value
    if (own[0] == own[1] and own[0] > top) or top in own:
        return 2, value
    if any(board_counts[r] for r in own) or own[0] == own[1] or draw(hole, board):
        return 1, value
    return 0, value


def select(cards, board):
    """Compare exactly three legal keeps; hide the more informative retained card."""
    best = None
    chosen = (2, 0)
    for discard in range(3):
        keep = tuple(i for i in range(3) if i != discard)
        hole = tuple(cards[i] for i in keep)
        value = strength(hole + board)
        # Category wins first; among the same category prefer live draws and kickers.
        score = (value[0], P['draw_selection_bonus'] * draw(hole, board)
                 + P['selection_pair_bonus'] * (CARD[hole[0]][0] == CARD[hole[1]][0]),
                 value, -preflop_pct(hole) * P['selection_kicker_weight'])
        if best is None or score > best:
            best = score
            def information(i):
                rank, suit = CARD[cards[i]]
                return (sum(CARD[c][0] == rank for c in board),
                        sum(CARD[c][1] == suit for c in board), rank)
            reveal = min(keep, key=information)
            chosen = discard, reveal
    return chosen

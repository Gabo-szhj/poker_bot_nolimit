"""V3 evidence: positional openings, costly calls, and public river showdowns.

A revealed river bluff is evidence of that observed mistake, not an unbiased estimate
of all unseen bluffs. No hidden hole cards or private discards are inferred.
"""
from math import sqrt
from struct import Struct
from bot import opp
from bot.cards import CARD_ID, DECK, tier
from bot.params import P

OPEN_N, OPEN_Y, OPEN_EXPECT, POST_N, POST_R, PRICE_N, PRICE_Y, BLUFF_N, BLUFF_Y, CALLSHOW_N, BADCALL_Y = range(13, 24)
HEADER = Struct('<4sBBH13I7B')
ROW = Struct('<10d3I11dqq')


def reset_context(d):
    d['tag'] = {'initial': d['live'], 'rb': 0, 'rc': 0, 'shown': 0,
                'weak': 0, 'wins': 0, 'board': [], 'sb': 255, 'bb': 255}


def fresh(state):
    d = opp.fresh(state)
    d['v'] = 3
    for row in d['rows']:
        row.extend([0.0]*11)
    reset_context(d)
    return d


def load(state, memory):
    try:
        values = HEADER.unpack_from(memory)
        magic, n, street, tidlen = values[:4]
        if (magic == b'BA03' and n == len(state.seats) and
            len(memory) == HEADER.size+tidlen+n*ROW.size and
            memory[HEADER.size:HEADER.size+tidlen].decode() == state.config.table_id):
            h, nr, pending, live, vp, pr, ai, initial, rb, rc, shown, weak, wins = values[4:17]
            rows, chips, bets = [], [], []
            offset = HEADER.size+tidlen
            for i in range(n):
                row = ROW.unpack_from(memory, offset+i*ROW.size)
                rows.append(list(row[:24])); chips.append(row[24]); bets.append(row[25])
            return {'v': 3, 't': state.config.table_id, 'n': n, 'h': h, 'street': street,
                    'nr': nr, 'pending': pending, 'live': live, 'vp': vp, 'pr': pr, 'ai': ai,
                    'rows': rows, 'chips': chips, 'bets': bets,
                    'tag': {'initial': initial, 'rb': rb, 'rc': rc, 'shown': shown,
                            'weak': weak, 'wins': wins, 'board': [DECK[x-1] for x in values[17:22] if x],
                            'sb': values[22], 'bb': values[23]}}
    except Exception:
        pass
    return fresh(state)


def dump(d, limit):
    t = d['tag']; tid = d['t'].encode()
    board = [CARD_ID[c]+1 for c in t['board']]
    board.extend([0]*(5-len(board)))
    header = HEADER.pack(b'BA03', d['n'], d['street'], len(tid), d['h'], d['nr'],
                         d['pending'], d['live'], d['vp'], d['pr'], d['ai'],
                         t['initial'], t['rb'], t['rc'], t['shown'], t['weak'], t['wins'],
                         *board, t['sb'], t['bb'])
    blob = header+tid+b''.join(ROW.pack(*r, c, b) for r,c,b in zip(d['rows'], d['chips'], d['bets']))
    return blob if len(blob) <= min(limit, 16384) else b''


def open_expectation(state, d, seat):
    t = d['tag']; initial = t['initial']; n = initial.bit_count()
    if n <= 3:
        return max(P['open_sb'], P['push_pct'][1])
    if seat == t['sb']:
        return P['open_sb']
    bb_seat = t['bb'] if t['bb'] != 255 else state.button
    order = [(bb_seat+j) % d['n'] for j in range(1, d['n']+1)
             if initial & (1 << ((bb_seat+j) % d['n']))]
    behind = len(order)-order.index(seat)-1 if seat in order else n-1
    expected = P['open_late'] if behind <= 2 else P['open_middle'] if behind <= 4 else P['open_early']
    level = state.config.blinds[min(max(0,d['h']-1)//state.config.hands_per_level, len(state.config.blinds)-1)]
    if d['chips'][seat] <= P['push_bb']*level.big_blind:
        expected = max(expected, P['push_pct'][min(behind,len(P['push_pct'])-1)])
    return expected


def observe(state, d, e):
    t = d['tag']; rows = d['rows']
    if e.kind == 'hand':
        if e.amount == d['h']:
            return
        for i, row in enumerate(rows):
            if t['weak'] & (1 << i) and not t['wins'] & (1 << i):
                row[BADCALL_Y] += 1
            for j in range(13,24):
                row[j] *= P['decay']
        reset_context(d)
        # Previous final stack events have already restored exact chip balances.
        d['tag']['initial'] = sum(1 << i for i,c in enumerate(d['chips']) if c > 0)
        return
    if e.kind == 'board':
        t['board'].extend(e.cards)
        return
    seat = e.seat
    if seat is None or not 0 <= seat < d['n']:
        return
    r = rows[seat]; bit = 1 << seat
    if e.kind == 'blind':
        if t['sb'] == 255:
            t['sb'] = seat
        elif t['bb'] == 255:
            t['bb'] = seat
    elif e.kind == 'win':
        t['wins'] |= bit
    elif e.kind == 'show' and len(e.cards) == 2 and len(t['board']) == 5 and not t['shown'] & bit:
        t['shown'] |= bit
        hand_tier, value = tier(tuple(e.cards), tuple(t['board']))
        if t['rb'] & bit:
            r[BLUFF_N] += 1
            r[BLUFF_Y] += hand_tier == 0 and value[0] <= 1
        if t['rc'] & bit:
            r[CALLSHOW_N] += 1
            if hand_tier <= 1:
                t['weak'] |= bit
    elif e.kind in ('fold','check','call','raise'):
        if d['street'] == 0 and d['nr'] == 0:
            r[OPEN_N] += 1
            r[OPEN_Y] += e.kind == 'raise'
            r[OPEN_EXPECT] += open_expectation(state,d,seat)
        if d['street'] > 0:
            r[POST_N] += 1
            r[POST_R] += e.kind == 'raise'
            to_call = max(d['bets'])-d['bets'][seat]
            call = min(to_call,d['chips'][seat])
            pot = state.config.starting_stack*d['n']-sum(d['chips'])
            if call > 0 and call/max(1,pot+call) >= P['tag_expensive_odds']:
                r[PRICE_N] += 1
                r[PRICE_Y] += e.kind == 'call'
            if d['street'] == 5:
                if e.kind == 'raise':
                    t['rb'] |= bit
                elif e.kind == 'call':
                    t['rc'] |= bit


def update(state,memory):
    return opp.update_data(state,load(state,memory),observe)


def evidence(success,n,prior,target,minimum,full):
    if n <= minimum:
        return 0.0
    w=P['tag_prior_weight']
    mean=(success+w*prior)/(n+w)
    lower=mean-P['tag_confidence_sd']*sqrt(mean*(1-mean)/(n+w+1))
    sample=min(1.0,(n-minimum)/max(1.0,full-minimum))
    return sample*max(0.0,min(1.0,(lower-target)/P['tag_signal_scale']))


def signals(row):
    minimum,full=P['tag_min_observations'],P['tag_full_observations']
    expected=row[OPEN_EXPECT]/row[OPEN_N] if row[OPEN_N] else P['open_middle']
    wide=evidence(row[OPEN_Y],row[OPEN_N],expected,expected+P['tag_wide_margin'],minimum,full)
    reraises=evidence(row[opp.T],row[opp.TN],P['tag_reraise_prior'],
                      P['tag_reraise_prior']+P['tag_reraise_excess'],minimum,full)
    bluff=evidence(row[BLUFF_Y],row[BLUFF_N],P['tag_bluff_prior'],P['tag_bluff_target'],
                   P['tag_show_min'],P['tag_show_full'])
    calls=evidence(row[PRICE_Y],row[PRICE_N],P['tag_call_prior'],P['tag_overcall_target'],minimum,full)
    weak_calls=evidence(row[BADCALL_Y],row[CALLSHOW_N],P['tag_bad_call_prior'],
                        P['tag_bad_call_target'],P['tag_show_min'],P['tag_show_full'])
    return {'wide':wide,'reraise':reraises,'bluff':bluff,'overcall':min(calls,weak_calls)}

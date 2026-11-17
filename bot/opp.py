"""Seat-only Bayesian counters serialized into each table's explicit memory.

One pass through new events. Work per event is bounded by ten anonymous seats.
No instance or module state is mutated between decisions.
"""
from struct import Struct
from bot.params import P

# Decayed counters: hands, VPIP, PFR, fold chances, folds, all-ins, raises, calls,
# three-bet chances, three-bets. Raw counters: hands, actions, voluntary actions.
H, V, R, FN, F, AI, AGG, CALL, TN, T, RAW_H, RAW_A, RAW_V = range(13)
HEADER = Struct('<4sBBH7I')
ROW = Struct('<10d3Iqq')


def fresh(state):
    n = len(state.seats)
    return {'v': 2, 't': state.config.table_id, 'n': n, 'h': 0,
            'rows': [[0.0] * 10 + [0, 0, 0] for _ in range(n)],
            'chips': [state.config.starting_stack] * n, 'bets': [0] * n,
            'street': 0, 'nr': 0, 'pending': 0, 'live': (1 << n)-1,
            'vp': 0, 'pr': 0, 'ai': 0}


def load(state, memory):
    try:
        if memory and len(memory) <= 16384:
            magic, n, street, tidlen, hand, nr, pending, live, vp, pr, ai = HEADER.unpack_from(memory)
            table_id = state.config.table_id
            if (magic == b'BA02' and n == len(state.seats) and
                len(memory) == HEADER.size + tidlen + n * ROW.size and
                memory[HEADER.size:HEADER.size+tidlen].decode() == table_id):
                offset = HEADER.size + tidlen
                rows, chips, bets = [], [], []
                for i in range(n):
                    values = ROW.unpack_from(memory, offset+i*ROW.size)
                    rows.append(list(values[:13]))
                    chips.append(values[13])
                    bets.append(values[14])
                return {'v': 2, 't': table_id, 'n': n, 'h': hand, 'street': street,
                        'nr': nr, 'pending': pending, 'live': live, 'vp': vp, 'pr': pr,
                        'ai': ai, 'rows': rows, 'chips': chips, 'bets': bets}
    except Exception:
        pass
    return fresh(state)


def update(state, memory):
    return update_data(state, load(state, memory))


def update_data(state, d, before_event=None):
    rows = d['rows']
    n = len(rows)
    for event in state.events:
        if before_event is not None:
            before_event(state, d, event)
        kind, seat = event.kind, event.seat
        if kind == 'hand':
            if event.amount == d['h']:
                continue
            d['h'] = event.amount
            d['street'] = d['nr'] = d['pending'] = d['vp'] = d['pr'] = d['ai'] = 0
            d['bets'] = [0] * n
            d['live'] = 0
            for i, r in enumerate(rows):
                for j in range(10):
                    r[j] *= P['decay']
                if d['chips'][i] > 0:
                    r[H] += 1
                    r[RAW_H] += 1
                    d['live'] |= 1 << i
            continue
        if kind == 'board':
            d['street'] += len(event.cards)
            d['nr'] = d['pending'] = 0
            d['bets'] = [0] * n
            continue
        if seat is None or not 0 <= seat < n:
            continue
        if kind == 'stack':
            d['chips'][seat] = event.amount
            continue
        bit = 1 << seat
        if kind in ('blind', 'ante'):
            d['chips'][seat] = max(0, d['chips'][seat]-event.amount)
            if kind == 'blind':
                d['bets'][seat] += event.amount
            continue
        if kind not in ('fold', 'check', 'call', 'raise'):
            continue
        r = rows[seat]
        r[RAW_A] += 1
        if d['pending'] & bit:
            r[FN] += 1
            r[F] += kind == 'fold'
            if d['street'] == 0 and d['nr'] == 1:
                r[TN] += 1
                r[T] += kind == 'raise'
        d['pending'] &= ~bit
        if kind in ('call', 'raise'):
            r[RAW_V] += 1
            if d['street'] == 0:
                if not d['vp'] & bit:
                    r[V] += 1
                    d['vp'] |= bit
                if kind == 'raise' and not d['pr'] & bit:
                    r[R] += 1
                    d['pr'] |= bit
            paid = event.amount if kind == 'call' else max(0, event.amount-d['bets'][seat])
            d['chips'][seat] = max(0, d['chips'][seat]-paid)
            d['bets'][seat] += paid
            r[AGG if kind == 'raise' else CALL] += 1
            if not d['chips'][seat] and not d['ai'] & bit:
                r[AI] += 1
                d['ai'] |= bit
        if kind == 'fold':
            d['live'] &= ~bit
        elif kind == 'raise':
            d['nr'] += 1
            # All-in seats have no later betting response to observe.
            active = sum(1 << i for i in range(n) if d['chips'][i] > 0)
            d['pending'] = d['live'] & active & ~bit
    return d


def estimates(row):
    w = P['prior_weight']
    return {'hands': row[RAW_H],
            'vpip': (row[V] + w * P['prior_vpip']) / (row[H] + w),
            'pfr': (row[R] + w * P['prior_pfr']) / (row[H] + w),
            'fold': (row[F] + w * P['prior_fold']) / (row[FN] + w),
            'fold_n': row[FN],
            'allin': row[AI] / max(1, row[H]),
            'aggression': row[AGG] / max(1, row[CALL]),
            'threebet': (row[T] + w * P['prior_pfr']) / (row[TN] + w),
            'dead': row[RAW_A] >= P['dead_opportunities'] and row[RAW_V] == 0}


def modes(state, data):
    result = {'station': False, 'folder': False}
    for opponent in state.seats:
        if opponent.seat == state.seat or opponent.status != 'active':
            continue
        e = estimates(data['rows'][opponent.seat])
        if e['hands'] < P['min_hands']:
            continue
        if e['vpip'] >= P['station_vpip'] and e['fold'] <= P['station_fold']:
            result['station'] = True
        if e['fold'] >= P['folder_fold'] or e['dead']:
            result['folder'] = True
        if e['fold_n'] >= P['exploitable_n'] and e['fold'] >= P['exploitable_fold']:
            result['exploit_seat'] = opponent.seat
            result['real_threebet'] = e['threebet'] <= P['real_threebet']
    return result


def dump(data, limit):
    tid = data['t'].encode()
    header = HEADER.pack(b'BA02', data['n'], data['street'], len(tid), data['h'],
                         data['nr'], data['pending'], data['live'], data['vp'], data['pr'], data['ai'])
    blob = header + tid + b''.join(ROW.pack(*row, chips, bet)
              for row, chips, bet in zip(data['rows'], data['chips'], data['bets']))
    return blob if len(blob) <= min(limit, 16384) else b''

"""Optional last-decision telemetry in table memory; runtime has no logging I/O."""
from struct import Struct

OLD_HEADER = Struct('<4sffffBB')
HEADER = Struct('<4sfffffffBB')
ACTIONS = ('fold', 'check', 'call', 'raise', 'select')
REASONS = {0: 'baseline', 1: 'guaranteed_win', 2: 'guaranteed_loss',
           3: 'nonlosing_tie_bound', 4: 'range_equity_vs_price', 6: 'spr_commitment'}


def unwrap(memory):
    if memory and memory[:4] == b'V5G1':
        return memory[HEADER.size:] if len(memory) >= HEADER.size else b''
    if memory and memory[:4] == b'V5D1':
        return memory[OLD_HEADER.size:] if len(memory) >= OLD_HEADER.size else b''
    return memory


def wrap(payload, diagnostic, action, limit):
    d = diagnostic or {}
    blob = HEADER.pack(b'V5G1', d.get('equity', -1.0), d.get('required_equity', -1.0),
        d.get('risk_adjustment', 0.0), d.get('uniform_equity', -1.0),
        d.get('call_price', -1.0), d.get('eligible_pot') or -1.0,
        d.get('action_adjustment', 0.0), ACTIONS.index(action.kind), d.get('reason', 0)) + payload
    return blob if len(blob) <= min(limit, 16384) else b''


def decode(memory):
    if not memory or memory[:4] != b'V5G1' or len(memory) < HEADER.size:
        return None
    _, equity, required, tournament, raw, price, pot, adjustment, action, reason = HEADER.unpack_from(memory)
    return {'equity': equity if equity >= 0 else None,
        'uniform_equity': raw if raw >= 0 else None,
        'required_equity': required if required >= 0 else None,
        'risk_adjustment': tournament, 'action_adjustment': adjustment,
        'call_price': price if price >= 0 else None, 'eligible_pot': pot if pot >= 0 else None,
        'action': ACTIONS[action], 'reason': reason, 'reason_name': REASONS.get(reason, 'unknown')}

"""V5 river guard: showdown proofs and priced actions survive bookkeeping faults."""
import poker_agent_sdk
from poker_agent_sdk import Action
from bot import tag_opp, diagnostics
from bot.params import P
from bot.strategy import passive
from bot.stack import decide_stack, opponent_modes, risk_factor
from bot.river import bounds, decide_river, certainty_action
from bot.aggression import commitment_action


class Agent(poker_agent_sdk.Agent):
    def act(self, state, memory):
        action = diagnostic = proof = proof_diagnostic = result = data = None
        try:
            river = (P['v5_river'] and state.phase == 'betting'
                     and len(state.board) == 5 and state.to_call > 0)
            # Compute a proof before any optional observation/telemetry can fail.
            if river:
                result = bounds(state)
                if P['river_guard_enabled']:
                    proof, proof_diagnostic = certainty_action(state, result)
            try:
                data = tag_opp.update(state, diagnostics.unwrap(memory))
            except Exception:
                data = tag_opp.fresh(state)
            if proof is not None:
                action, diagnostic = proof, proof_diagnostic
            elif river and result is not None:
                action, diagnostic = decide_river(state, data,
                    risk_factor(state, result['opponent']), result)
            protected = diagnostic and diagnostic.get('reason') in (1, 2, 3)
            priced = action is not None and diagnostic and diagnostic.get('reason') == 4
            if not protected and not (P['river_price_authoritative'] and priced):
                committed = commitment_action(state)
                if committed is not None:
                    action = committed
                    diagnostic = dict(diagnostic or {}, reason=6)
            if action is None:
                action = decide_stack(state, opponent_modes(state, data), data)
        except Exception:
            if action is None:
                try:
                    action = passive(state)
                except Exception:
                    action = Action.fold()
        # Final invariant: no risk, board-danger, evidence, or fallback override.
        if proof is not None:
            action, diagnostic = proof, proof_diagnostic
        # Serializing table memory is independent of the chosen action.
        try:
            limit = state.config.memory_bytes
            payload = tag_opp.dump(data, max(0, limit - diagnostics.HEADER.size))
            new_memory = (diagnostics.wrap(payload, diagnostic, action, limit)
                          if P['diagnostics_enabled'] else payload)
        except Exception:
            try:
                new_memory = (diagnostics.wrap(b'', diagnostic, action, state.config.memory_bytes)
                              if P['diagnostics_enabled'] else b'')
            except Exception:
                new_memory = b''
        return action, new_memory

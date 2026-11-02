//! Exact Imperial Defender dependency for Maxwell's ordinary / Golden Buddy.
use super::*;

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![("BG22_HERO_007_Buddy", Script {
        start_of_turn: Some(|c, me| {
            if let Some(m) = c.minion_mut(me.eid) { m.counter = 0; }
        }),
        on_event: Some(|c, me, e| {
            let Event::SpellCast { side, card, target, data, opt, .. } = e else { return };
            // The engine records friendliness before the spell resolves, including a
            // target removed by that spell. Self, Tavern and untargeted casts do not count.
            if *side != me.side || *target == me.eid || !c.cast_on_friendly { return; }
            let Some(m) = c.minion_mut(me.eid) else { return };
            if !m.alive() || m.counter != 0 { return; }
            // Spend the entity's one use before nested "you cast" events can re-enter.
            // Golden casts twice in that use; it does not gain a second use.
            m.counter = 1;
            for _ in 0..me.g() {
                if !c.minion(me.eid).is_some_and(|m| m.alive()) { break; }
                c.you_cast(me.side, *card, *data, me.eid, *opt);
            }
        }),
        listens: ev::SPELL_CAST,
        flags: flag::TURN_USES,
        ..E
    })]
}

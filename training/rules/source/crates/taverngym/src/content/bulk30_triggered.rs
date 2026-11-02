//! W3 exact target37 triggers and serializable direct-effect choices.
use super::*;
use crate::state::Continuation;

fn effect_cast(c: &mut Ctx, side: Side, card: CardId, target: EntityId, opt: u8, resolving: bool) {
    if script(card).is_some_and(|s| s.has_flag(flag::ONE_PENDING))
        && c.player_ref(side).is_some_and(|p| p.effects.iter().any(|x| x.card == db().normal_of(card))) {
        return;
    }
    let flags = (c.cast_from_hand, c.cast_by_you);
    c.cast_from_hand = false;
    c.cast_by_you = false;
    // The frozen Cagey callable broadcasts resolving without a physical play/counter.
    // An explicit all-casts override already supplies this phase; never double it.
    if resolving && !c.g.cfg.effect_casts_count {
        let phase = std::mem::replace(&mut c.spell_phase, 1);
        c.emit(Event::SpellCast { side, card, target, tavern: is_tavern_spell(card), data: 0, opt });
        c.spell_phase = phase;
    }
    c.cast_spell(side, card, 0, target, opt);
    (c.cast_from_hand, c.cast_by_you) = flags;
}

fn cagey_target(c: &mut Ctx, side: Side, source: EntityId, spell: CardId, opt: u8) -> Option<EntityId> {
    let spec = if opt == 1 && db().get(spell).id == "BG31_886" { TargetSpec::None }
        else { effect_target_spec(spell).unwrap_or(TargetSpec::None) };
    if spec == TargetSpec::None { return Some(0); }
    let legal = c.legal_targets(side, spec, 0);
    if legal.contains(&source) { Some(source) } else { c.g.rng.pick(&legal).copied() }
}

pub fn resume_cagey(c: &mut Ctx, side: Side, source: EntityId, spell: CardId,
                    opt: u8, left: u8, candidates: Vec<CardId>) {
    if let Some(target) = cagey_target(c, side, source, spell, opt) {
        effect_cast(c, side, spell, target, opt, true);
    }
    cagey_sequence(c, side, source, left, candidates);
}

fn cagey_sequence(c: &mut Ctx, side: Side, source: EntityId, mut left: u8, candidates: Vec<CardId>) {
    while left > 0 {
        let Some(spell) = c.g.rng.pick(&candidates).copied() else { return };
        left -= 1;
        if db().get(spell).mech.has(Mech::CHOOSE_ONE) {
            c.push_choose_one(side, spell, Continuation::CageyCast { source, spell, opt: 0, left, candidates }, false);
            return;
        }
        if let Some(target) = cagey_target(c, side, source, spell, 0) {
            effect_cast(c, side, spell, target, 0, true);
        }
    }
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        ("BG32_837", Script {
            end_of_turn: Some(|c, me| {
                if !c.minion(me.eid).is_some_and(|m| m.alive()) { return; }
                for _ in 0..me.g() {
                    for target in c.neighbors(me.eid) {
                        if c.minion(target).is_some_and(|m| m.alive()) {
                            effect_cast(c, me.side, cid("BG28_845"), target, 0, false);
                        }
                    }
                }
            }), ..E
        }),
        ("BG34_925", Script {
            rally: Some(|c, me, _| {
                let Some((side, pos)) = c.locate(me.eid) else { return };
                if side != me.side || !c.minion(me.eid).is_some_and(|m| m.alive()) { return; }
                let Some(target) = c.boards[side].get(pos + 1).filter(|m| m.alive()).map(|m| m.eid) else { return };
                for _ in 0..me.g() {
                    if !c.minion(target).is_some_and(|m| m.alive()) { break; }
                    effect_cast(c, me.side, cid("BG28_518"), target, 0, false);
                }
            }), ..E
        }),
        ("BG36_508", Script {
            activate: Some((1, TargetSpec::None, |c, me, _| {
                if !c.minion(me.eid).is_some_and(|m| m.alive()) { return; }
                let tier = c.tier(me.side);
                let candidates = c.g.spell_universe.iter().copied().filter(|card| {
                    db().get(*card).tier <= tier && script(*card).and_then(|s| s.spell).is_some()
                        && c.g.spell_copies_left(*card) > 0
                }).collect();
                cagey_sequence(c, me.side, me.eid, (2 * me.g()) as u8, candidates);
            })), ..E
        }),
    ]
}

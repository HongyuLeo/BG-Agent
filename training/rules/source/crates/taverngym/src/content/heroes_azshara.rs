//! Frozen target37 Azshara: 30 living recruit Attack -> Naga Conquest (DBF80007).
//! The transformed hero body is the fixed catalogue BG22_HERO_007t; only the
//! base Azshara portrait changes. Acquiring Ambition on another hero does not.
use super::*;

pub fn azshara_check(c: &mut Ctx, side: Side) {
    if c.combat || c.timewarp_suspended(side) { return; }
    let ambition = crate::cardid!("BG22_HERO_007p");
    let Some(slot) = c.player_ref(side)
        .and_then(|p| p.powers.iter().position(|h| h.card == ambition)) else { return; };
    let total = c.boards[side].iter().filter(|m| m.alive())
        .fold(0i32, |n,m| n.saturating_add(m.atk));
    if total < 30 { return; }
    // Replace first, so nested attachment/events cannot trigger the goal twice.
    c.set_hero_power(side, slot, cid("BG22_HERO_007p2"));
    if let Some(p) = c.player(side) {
        if p.hero == Some(cid("BG22_HERO_007")) {
            p.hero = Some(cid("BG22_HERO_007t"));
        }
    }
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        ("BG22_HERO_007p", Script {
            flags: flag::PASSIVE, hero_power_uses: 0,
            on_attach: Some(|c,me| azshara_check(c,me.side)),
            start_of_turn: Some(|c,me| azshara_check(c,me.side)),
            end_of_turn: Some(|c,me| azshara_check(c,me.side)),
            on_event: Some(|c,me,_| azshara_check(c,me.side)),
            listens: ev::SUMMONED | ev::SOLD | ev::PLAYED | ev::SPELL_CAST
                | ev::MAGNETIZED | ev::DIED | ev::CARD_PLAYED | ev::BOUGHT,
            shown: Some(|_,_| vec![30]),
            ..E
        }),
        ("BG22_HERO_007p2", Script {
            hero_power: Some(|c,me,_| {
                let tier=c.tier(me.side);
                c.discover_minion(me.side,me.card,3,|d|
                    d.tier <= tier && d.races.intersects(Races::NAGA));
            }),
            ..E
        }),
    ]
}

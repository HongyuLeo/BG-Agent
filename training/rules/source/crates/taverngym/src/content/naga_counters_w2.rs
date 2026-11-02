//! The three Naga counter families missing from the frozen public4 content set.
use super::*;

fn spell_multiplier(c: &Ctx, side: Side) -> i32 {
    // These cards say "spells", unlike Abyssal Bruiser's explicit "Tavern spells".
    1 + c.player_ref(side).map_or(0, |p| p.stats.spells_cast.max(0) / 3)
}

fn groundbreaker(c: &mut Ctx, me: Me, e: &Event) {
    if let Event::Played { side, played, .. } = e
        && *side == me.side
        && played.races.intersects(Races::NAGA)
        && c.minion(me.eid).is_some_and(|m| m.alive())
    {
        let k = spell_multiplier(c, me.side).saturating_mul(me.g());
        c.buff(me.eid, k, k);
    }
}

fn cyclist(c: &mut Ctx, me: Me) {
    let k = spell_multiplier(c, me.side).saturating_mul(me.g());
    for eid in c.friendly_where(me.side, |m| m.is(Races::NAGA)) {
        c.buff(eid, k.saturating_mul(2), k);
    }
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        (
            "BG31_035",
            Script {
                on_event: Some(groundbreaker),
                listens: ev::PLAYED,
                shown: Some(|c, sh| {
                    let k = spell_multiplier(c, sh.side).saturating_mul(sh.g());
                    vec![k, k, 3]
                }),
                ..E
            },
        ),
        (
            "BG31_925",
            Script {
                deathrattle: Some(cyclist),
                shown: Some(|c, sh| {
                    let k = spell_multiplier(c, sh.side).saturating_mul(sh.g());
                    vec![k.saturating_mul(2), k, 3]
                }),
                ..E
            },
        ),
        // The engine's reversible player-bonus layer applies this card's stats in
        // all zones and after each real Tavern cast. Divine Shield is in card data.
        ("BG35_921", E),
    ]
}

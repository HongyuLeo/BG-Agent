//! Exact Buddy acquisition for Maxwell; no generic/previous-hero fallback.
use super::*;
use crate::state::Player;
use crate::cards::CardKind;

pub fn is_maxwell(card: CardId) -> bool {
    matches!(db().get(card).id.as_str(), "BG35_MagicItem_803" | "BG35_MagicItem_803t")
}

/// Existing Player contract: `hero_power()` is the CURRENT primary power; extras
/// occupy later slots. This is deliberately not the player's original hero portrait.
pub fn buddy_for_player(player: &Player, golden: bool) -> Result<CardId, &'static str> {
    let power = player.hero_power().ok_or("Maxwell: no primary Hero Power")?.base();
    if db().get(power).kind != CardKind::HeroPower {
        return Err("Maxwell: primary power has no Hero Power identity");
    }
    // Inge alternates these exact forms in heroes_active::inge_form; the same
    // Buddy relation is already explicit in buddies_c::power_buddy. This is a
    // form of the CURRENT primary power, never the original portrait or extras.
    let power = match db().get(power).id.as_str() {
        "BG26_HERO_102p2" => cid("BG26_HERO_102p"),
        _ => power,
    };
    let mut buddy = None;
    for hero in db().iter().filter(|h| h.kind == CardKind::Hero && h.hero_power == Some(power)) {
        if let Some(b) = hero.buddy {
            if buddy.is_some_and(|previous| previous != b) {
                return Err("Maxwell: ambiguous primary-power Buddy association");
            }
            buddy = Some(b);
        }
    }
    let buddy = buddy.ok_or("Maxwell: primary power has no Buddy association")?;
    let result = if golden {
        db().get(buddy).golden.ok_or("Maxwell: Buddy has no explicit Golden relation")?
    } else {
        buddy
    };
    if !crate::script::implemented(result) {
        return Err("Maxwell: exact associated Buddy effect is unsupported");
    }
    Ok(result)
}

pub fn preflight(player: &Player, card: CardId) -> Result<(), &'static str> {
    if is_maxwell(card) {
        buddy_for_player(player, db().get(card).id == "BG35_MagicItem_803t")?;
    }
    Ok(())
}

fn gain(c: &mut Ctx, me: Me) {
    let result = c.player_ref(me.side)
        .ok_or("Maxwell: missing owner")
        .and_then(|p| buddy_for_player(p, db().get(me.card).id == "BG35_MagicItem_803t"));
    match result {
        Ok(buddy) => { c.give_card(me.side, buddy); }
        // Normal public acquisition is preflighted before payment/pop. Direct
        // debug/effect grants still record the precise failure, never substitute.
        Err(reason) => c.g.log.push(reason.to_owned()),
    }
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        ("BG35_MagicItem_803", Script {
            on_attach: Some(gain),
            offer_ok: Some(|g, p| buddy_for_player(&g.players[p], false).is_ok()),
            ..E
        }),
        ("BG35_MagicItem_803t", Script {
            on_attach: Some(gain),
            offer_ok: Some(|g, p| buddy_for_player(&g.players[p], true).is_ok()),
            ..E
        }),
    ]
}

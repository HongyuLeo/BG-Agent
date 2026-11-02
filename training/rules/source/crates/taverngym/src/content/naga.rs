//! Naga and Spellcraft, Bounties, and Choose One combining cards.

use super::*;

fn sc_spell(f: crate::script::FxT) -> Script {
    Script {
        spell: Some(f),
        spell_target: TargetSpec::Friendly,
        ..E
    }
}

/// Lava Lurker / Thorned Trailblazer: per-turn uses kept on the minion counter.
fn per_turn_uses() -> Script {
    Script {
        on_create: Some(|m| m.counter = if m.golden { 2 } else { 1 }),
        start_of_turn: Some(|c, me| {
            if let Some(m) = c.minion_mut(me.eid) {
                m.counter = me.g();
            }
        }),
        ..E
    }
}

fn bounties(c: &mut Ctx, me: Me) {
    give_random_of(c, me.side, &BOUNTIES, me.g());
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        // W1: Shell Collector. Both forms generate the existing playable Tavern Coin.
        ("BG23_002", Script {
            battlecry: Some(|c, me, _| give_n(c, me.side, TAVERN_COIN, me.g() as usize)),
            ..E
        }),
        // W1: Zesty Shaker. A played Spellcraft only; effect casts do not spend the use.
        ("BG26_505", Script {
            start_of_turn: Some(|c, me| { if let Some(m) = c.minion_mut(me.eid) { m.counter = 0; } }),
            on_event: Some(|c, me, e| {
                if let Event::SpellCast { side, card, target, .. } = e
                    && *side == me.side && *target == me.eid
                    && c.cast_from_hand && db().get(*card).spellcraft_spell
                    && c.minion(me.eid).is_some_and(|m| m.counter == 0)
                {
                    if let Some(m) = c.minion_mut(me.eid) { m.counter = 1; }
                    let src = c.cast_src;
                    for _ in 0..me.g() { c.give_temp_spell(me.side, *card, src); }
                }
            }),
            listens: ev::SPELL_CAST,
            flags: flag::TURN_USES,
            ..E
        }),
        // W1: Torrential Ruiner. Naga includes dual types, All, and Tavern targets.
        ("BG36_622", Script {
            on_event: Some(|c, me, e| {
                if let Event::SpellCast { side, target, .. } = e
                    && *side == me.side
                    && c.find_any(*target).is_some_and(|m| m.is(Races::NAGA))
                {
                    for t in c.friendly(me.side) { c.buff(t, 2 * me.g(), 3 * me.g()); }
                }
            }),
            listens: ev::SPELL_CAST,
            ..E
        }),
        // W1: Fleeing Fugitive, one independent Health gain per qualifying cast.
        ("BG36_921", Script {
            on_event: Some(|c, me, e| {
                if matches!(e, Event::SpellCast { side, target, .. } if *side == me.side && *target == me.eid) {
                    c.buff(me.eid, 0, me.g());
                }
            }),
            listens: ev::SPELL_CAST,
            ..E
        }),

        // ------------------------------------------------------------ Spellcraft minions
        // (their spell is given by the engine: `Ctx::give_spellcraft`)
        // W2: generation is the shared Spellcraft hook; no pool/eligibility additions.
        ("BG27_514", E),
        ("BG31_920", Script {
            on_create: Some(|m| m.counter = 1),
            end_of_turn: Some(|c, me| {
                let cap = c.g.universe.iter().map(|id| db().get(*id)).filter(|d| d.races.intersects(Races::NAGA)).map(|d| d.tier as i32).max().unwrap_or(1);
                if let Some(m) = c.minion_mut(me.eid) { m.counter = (m.counter.max(1) + 1).min(cap); }
            }),
            // A triple keeps the most improved constituent, rather than resetting its tier.
            on_merge: Some(|m, parts| m.counter = parts.iter().map(|m| m.counter).max().unwrap_or(1).max(1)),
            shown: Some(|_, sh| vec![sh.counter().max(1)]),
            ..E
        }),
        ("BG32_835", E),
        ("BG33_319", E),
        ("BG27_514t", sirens_song()),
        ("BG27_514t_G", sirens_song()),
        ("BG31_920t", Script { spell: Some(evolving_strategy), ..E }),
        ("BG31_920_Gt", Script { spell: Some(evolving_strategy), ..E }),
        ("BG32_835t", Script { spell: Some(meditation), ..E }),
        ("BG32_835_Gt", Script { spell: Some(meditation), ..E }),
        ("BG33_319t", Script { spell: Some(rime_or_reason), ..E }),
        ("BG33_319_Gt", Script { spell: Some(rime_or_reason), ..E }),
        ("BG23_000", E),       // Mini-Myrmidon
        ("BG23_004", E),       // Deep-Sea Angler
        ("BG26_171", E),       // Silent Swimmer
        ("BG23_008", E),       // Glowscale
        ("BG34_Giant_035", E), // Timewarped Glowscale
        ("BG26_501", E),       // Reef Riffer
        ("BG31_830", E),       // Weary Mage
        ("BG23_007", E),       // Waverider
        ("BGS_200", E),        // Warden of Old
        ("BG31_924", E),       // Thaumaturgist
        // Lava Lurker: the first 1 (2) Spellcraft spells played from hand on this each turn
        // are permanent (`sc_permanent`).
        ("BG23_009", per_turn_uses()),
        // ------------------------------------------------------------ Spellcraft spells
        (
            "BG23_000t",
            sc_spell(|c, me, t| sc_buff(c, me, t, 2 * sc_g(me), 0, Kw::NONE)),
        ),
        (
            "BG23_000_Gt",
            sc_spell(|c, me, t| sc_buff(c, me, t, 2 * sc_g(me), 0, Kw::NONE)),
        ),
        (
            "BG23_004t",
            sc_spell(|c, me, t| sc_buff(c, me, t, 2 * sc_g(me), 6 * sc_g(me), Kw::TAUNT)),
        ),
        (
            "BG23_004_Gt",
            sc_spell(|c, me, t| sc_buff(c, me, t, 2 * sc_g(me), 6 * sc_g(me), Kw::TAUNT)),
        ),
        (
            "BG26_171t",
            sc_spell(|c, me, t| sc_buff(c, me, t, 3 * sc_g(me), 4 * sc_g(me), Kw::STEALTH)),
        ),
        (
            "BG26_171_Gt",
            sc_spell(|c, me, t| sc_buff(c, me, t, 3 * sc_g(me), 4 * sc_g(me), Kw::STEALTH)),
        ),
        (
            "BG23_008t",
            sc_spell(|c, me, t| sc_buff(c, me, t, 0, 0, Kw::DIVINE_SHIELD)),
        ),
        (
            "BG23_008_Gt",
            sc_spell(|c, me, t| sc_buff(c, me, t, 0, 0, Kw::DIVINE_SHIELD)),
        ),
        // Timewarped Glowscale: permanent Divine Shield.
        (
            "BG34_Giant_035t",
            sc_spell(|c, _, t| c.give_kw(t, Kw::DIVINE_SHIELD)),
        ),
        (
            "BG34_Giant_035t_G",
            sc_spell(|c, _, t| c.give_kw(t, Kw::DIVINE_SHIELD)),
        ),
        // Reef Riffer: stats equal to your Tier (twice) until next turn.
        (
            "BG26_501t",
            sc_spell(|c, me, t| {
                let k = c.tier(me.side) as i32 * sc_g(me);
                sc_buff(c, me, t, k, k, Kw::NONE)
            }),
        ),
        (
            "BG26_501_Gt",
            sc_spell(|c, me, t| {
                let k = c.tier(me.side) as i32 * sc_g(me);
                sc_buff(c, me, t, k, k, Kw::NONE)
            }),
        ),
        // Weary Mage / Waverider: +2/+2 (permanent); a Naga also gets Reborn / Windfury until
        // next turn.
        (
            "BG31_830t",
            sc_spell(|c, me, t| naga_bonus(c, me, t, Kw::REBORN)),
        ),
        (
            "BG31_830_Gt",
            sc_spell(|c, me, t| naga_bonus(c, me, t, Kw::REBORN)),
        ),
        (
            "BG23_007t",
            sc_spell(|c, me, t| naga_bonus(c, me, t, Kw::WINDFURY)),
        ),
        (
            "BG23_007_Gt",
            sc_spell(|c, me, t| naga_bonus(c, me, t, Kw::WINDFURY)),
        ),
        // Warden of Old: gain 1 (2) Gold.
        (
            "BGS_200t",
            Script {
                spell: Some(|c, me, _| c.gain_gold(me.side, 1)),
                ..E
            },
        ),
        (
            "TB_BaconUps_256t",
            Script {
                spell: Some(|c, me, _| c.gain_gold(me.side, 2)),
                ..E
            },
        ),
        // Thaumaturgist: +1/+1 (+2/+2) until next turn, improved by every 3 spells cast.
        ("BG31_924t", sc_spell(thaumaturgy)),
        ("BG31_924_Gt", sc_spell(thaumaturgy)),
        // ------------------------------------------------------------ Spellcraft support
        // Spitescale Special: get 3 random Spellcraft spells.
        (
            "BG28_606",
            Script {
                spell: Some(|c, me, _| give_random_spellcraft(c, me.side, 3)),
                ..E
            },
        ),
        // Spitescale Sushi Roll: get a Spitescale Special; first two Spellcraft spells each
        // turn cast an extra time (`spell_cast_times`).
        (
            "BG30_MagicItem_920",
            Script {
                on_attach: Some(|c, me| give_n(c, me.side, "BG28_606", 1)),
                ..E
            },
        ),
        // Azsharan Statuette: get 3 random Spellcraft spells now and every turn start.
        (
            "BG32_MagicItem_931",
            Script {
                on_attach: Some(|c, me| give_random_spellcraft(c, me.side, 3)),
                start_of_turn: Some(|c, me| give_random_spellcraft(c, me.side, 3)),
                ..E
            },
        ),
        // Relics of the Deep (hero power): at the start of each turn, a random Spellcraft spell.
        (
            "BG23_HERO_304p",
            Script {
                start_of_turn: Some(|c, me| give_random_spellcraft(c, me.side, 1)),
                flags: flag::PASSIVE,
                ..E
            },
        ),
        // Coral Spear: whenever you cast a Spellcraft spell, cast Might of Stormwind.
        (
            "BG35_MagicItem_925",
            Script {
                on_event: Some(|c, me, e| {
                    if let Event::SpellCast { side, card, .. } = e
                        && *side == me.side
                        && db().get(*card).spellcraft_spell
                    {
                        c.you_cast(me.side, cid("BG35_951"), 0, 0, 0);
                    }
                }),
                listens: ev::SPELL_CAST,
                ..E
            },
        ),
        // Glowscale Portrait: get a Timewarped Glowscale; after you cast a Spellcraft spell,
        // your Divine Shield minions get +3/+3.
        (
            "BG30_MagicItem_548",
            Script {
                on_attach: Some(|c, me| give_n(c, me.side, "BG34_Giant_035", 1)),
                on_event: Some(|c, me, e| {
                    if let Event::SpellCast { side, card, .. } = e
                        && *side == me.side
                        && db().get(*card).spellcraft_spell
                    {
                        for t in c.friendly_where(me.side, |m| m.has(Kw::DIVINE_SHIELD)) {
                            c.buff(t, 3, 3);
                        }
                    }
                }),
                listens: ev::SPELL_CAST,
                ..E
            },
        ),
        // Thaumaturgist Portrait / Weary Portrait: get 2 Thaumaturgists / a Weary Mage; their
        // Spellcrafts are permanent (`sc_permanent`).
        (
            "BG32_MagicItem_920",
            Script {
                on_attach: Some(|c, me| give_n(c, me.side, "BG31_924", 2)),
                ..E
            },
        ),
        (
            "BG32_MagicItem_933",
            Script {
                on_attach: Some(|c, me| give_n(c, me.side, "BG31_830", 1)),
                ..E
            },
        ),
        // Sunken Persistence (Dark Gift): this minion's Spellcrafts are permanent.
        ("BG36_MidGameEffect_000t62", E),
        // ------------------------------------------------------------ Bounties
        // Proud Privateer: your Bounties cast twice (three times) (`spell_cast_times`).
        ("BG33_825", E),
        // Friendly Bounty: get a random minion of your most common type.
        (
            "BG33_814",
            Script {
                spell: Some(|c, me, _| {
                    let Some(r) = c.most_common_race(me.side) else {
                        return;
                    };
                    let tier = c.tier(me.side);
                    if let Some(card) = c.random_minion(|d| d.races.intersects(r) && d.tier <= tier)
                    {
                        c.give_card(me.side, card);
                    }
                }),
                ..E
            },
        ),
        // Lost City Looter: end of turn, get 1 (2) random Bounties.
        (
            "BG33_820",
            Script {
                end_of_turn: Some(bounties),
                ..E
            },
        ),
        // Bigwig Bandit: Rally: get 1 (2) random Bounties.
        (
            "BG33_822",
            Script {
                rally: Some(|c, me, _| bounties(c, me)),
                ..E
            },
        ),
        // Shipwrecked Rascal: Battlecry and Deathrattle: get 1 (2) random Bounties.
        (
            "BG33_821",
            Script {
                battlecry: Some(|c, me, _| bounties(c, me)),
                deathrattle: Some(bounties),
                ..E
            },
        ),
        // Privateer Portrait: get a Proud Privateer and 2 Bounties; 2 more every turn start.
        (
            "BG35_MagicItem_712",
            Script {
                on_attach: Some(|c, me| {
                    give_n(c, me.side, "BG33_825", 1);
                    give_random_of(c, me.side, &BOUNTIES, 2);
                }),
                start_of_turn: Some(|c, me| give_random_of(c, me.side, &BOUNTIES, 2)),
                ..E
            },
        ),
        // Sunken Anchor: get 2 random Bounties now and every turn start.
        (
            "BG35_MagicItem_890",
            Script {
                on_attach: Some(|c, me| give_random_of(c, me.side, &BOUNTIES, 2)),
                start_of_turn: Some(|c, me| give_random_of(c, me.side, &BOUNTIES, 2)),
                ..E
            },
        ),
        // ------------------------------------------------------------ Choose One combined
        // (`Ctx::push_choose_one`)
        ("BG_OG_044", E),          // Fandral Staghelm
        ("BG36_MagicItem_308", E), // Trailblazer Sticker
        // Thorned Trailblazer: 1 (2) per turn.
        (
            "BG31_327",
            Script {
                // "One Choose One card each turn has both effects combined. (1 left!)"; golden:
                // "Two Choose One cards... (2 left!)"
                shown: Some(|_, sh| vec![sh.minion.map_or(sh.g(), |m| m.counter).max(0)]),
                ..per_turn_uses()
            },
        ),
        // Fandral's Fortune: Discover a Choose One card; it has both effects combined.
        (
            "BG31_892",
            Script {
                spell: Some(|c, me, _| {
                    let cands = choose_one_cards(c, me.side);
                    let picks = c.g.rng.sample_indices(cands.len(), 3);
                    let options = picks
                        .into_iter()
                        .map(|i| choose_one_item(c, me.side, cands[i]))
                        .collect();
                    c.offer_discover(me.side, me.card, options);
                }),
                ..E
            },
        ),
    ]
}

fn naga_bonus(c: &mut Ctx, me: Me, t: EntityId, kw: Kw) {
    let k = 2 * sc_g(me);
    c.buff(t, k, k);
    if c.find_any(t).is_some_and(|m| m.is(Races::NAGA)) {
        sc_buff(c, me, t, 0, 0, kw);
    }
}

fn thaumaturgy(c: &mut Ctx, me: Me, t: EntityId) {
    let cast = c
        .player_ref(me.side)
        .map(|p| p.stats.spells_cast)
        .unwrap_or(0);
    let k = (1 + cast / 3) * sc_g(me);
    sc_buff(c, me, t, k, k, Kw::NONE);
}

// Spell tokens have no golden database link: use their exact ids for multiplicity.
fn w2_copies(me: Me) -> i32 {
    if ["BG27_514t_G", "BG31_920_Gt", "BG32_835_Gt", "BG33_319_Gt"].contains(&db().get(me.card).id.as_str()) { 2 } else { 1 }
}
fn sirens_song() -> Script {
    Script {
        spell_target: TargetSpec::TavernExcept(cid("BG27_514")),
        spell: Some(|c, me, t| {
            if !c.legal_targets(me.side, TargetSpec::TavernExcept(cid("BG27_514")), 0).contains(&t) { return; }
            let Some(original) = c.find_any(t).cloned() else { return; };
            for _ in 0..w2_copies(me) {
                let copy = c.full_copy(&original);
                c.add_to_hand(me.side, Item::Minion(copy));
            }
        }),
        ..E
    }
}
fn evolving_strategy(c: &mut Ctx, me: Me, _: EntityId) {
    // Formal source contract reads the living source; once sold, fallback is tier 1.
    let tier = c.minion(c.cast_src).filter(|m| m.is_card("BG31_920")).map_or(1, |m| m.counter.max(1)) as u8;
    for _ in 0..w2_copies(me) {
        // Formal generation requires remaining pool copies; do not use the engine's
        // no-copies-left extra-copy fallback for this identity.
        let available: Vec<CardId> = c.g.universe.iter().copied().filter(|id| c.g.pool.get(*id) > 0).collect();
        if let Some(card) = c.random_minion(|d| d.tier == tier && d.races.intersects(Races::NAGA) && available.contains(&d.cid)) {
            c.give_card(me.side, card);
        }
    }
}
fn meditation(c: &mut Ctx, me: Me, _: EntityId) {
    if let Some(p) = c.player(me.side) {
        p.stats.spell_atk = p.stats.spell_atk.saturating_add(w2_copies(me));
        p.stats.spell_hp = p.stats.spell_hp.saturating_add(w2_copies(me));
    }
}
fn rime_or_reason(c: &mut Ctx, me: Me, _: EntityId) {
    // E03 user contract: unspecified random Tavern spells cannot exceed owner tier.
    // Keep this token-scoped: explicit-tier effects and the shared classifier are unchanged.
    let tier = c.tier(me.side);
    for _ in 0..w2_copies(me) {
        if let Some(card) = c.random_spell(|d| d.tier <= tier && super::buddies_c::STAT_SPELLS.contains(&d.id.as_str())) {
            c.give_card(me.side, card);
        }
    }
}

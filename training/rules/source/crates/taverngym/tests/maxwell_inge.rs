use taverngym::{Action,Game};
use taverngym::cards::{cid,db};
use taverngym::state::{HeroPowerState,Pending};

fn snapshot_game()->Game {
    let path=std::env::var("BG_MAXWELL_SNAPSHOT").expect("exact private snapshot required");
    let value:serde_json::Value=serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let raw=value["snapshot"]["payload"]["native_raw"].as_str().unwrap();
    let mut game:Game=serde_json::from_str(raw).unwrap();
    game.check_loaded().unwrap();
    assert_eq!(serde_json::to_string(&game).unwrap(),raw);
    game
}

#[test]
fn original_seed1025_unedited_snapshot_purchase_succeeds() {
    let mut g=snapshot_game();
    assert_eq!(g.players[0].powers[0].card,cid("BG26_HERO_102p2"));
    let hand=g.players[0].hand.len();let gold=g.players[0].gold;
    g.apply(0,Action::Choose(0)).unwrap();
    assert_eq!(g.players[0].hand.len(),hand+1);
    assert_eq!(g.players[0].hand.last().unwrap().item.card(),cid("BG26_HERO_102_Buddy"));
    assert_eq!(g.players[0].gold,gold-db().get(cid("BG35_MagicItem_803")).cost);
    assert!(g.players[0].trinkets.contains(&cid("BG35_MagicItem_803")));
}

#[test]
fn both_forms_normal_and_golden_exact_buddy_with_unrelated_portrait() {
    for power in ["BG26_HERO_102p","BG26_HERO_102p2"] {
        for (trinket,buddy) in [("BG35_MagicItem_803","BG26_HERO_102_Buddy"),("BG35_MagicItem_803t","BG26_HERO_102_Buddy_G")] {
            let mut g=snapshot_game();
            // Deliberate identity controls only: never use the unrelated portrait's Buddy.
            g.players[0].hero=Some(cid("BG22_HERO_007"));
            g.players[0].powers=vec![HeroPowerState::new(cid(power))];
            g.players[0].pending=vec![Pending::Trinket{options:vec![cid(trinket)],free:false,replace:None}];
            let gold=g.players[0].gold;
            g.apply(0,Action::Choose(0)).unwrap();
            assert_eq!(g.players[0].hand.last().unwrap().item.card(),cid(buddy));
            assert_eq!(g.players[0].gold,gold-db().get(cid(trinket)).cost);
        }
    }
}

use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db};
use taverngym::state::{Pending,Item,Minion,ShopSlot};
use taverngym::types::Kw;
fn game()->Game {let mut g=Game::new(711,RulesConfig{num_players:2,record_log:true,..RulesConfig::default()});for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}for p in &mut g.players {p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.stats=Default::default();p.gold=10;p.tier=6;p.skipping=false;}g.next_eid=100;g.cfg.triple_copies=99;g}
fn raw(g:&Game)->String {serde_json::to_string(g).unwrap()}
fn give(g:&mut Game,id:&str) {g.with_recruit(0,|c|{c.give_card(0,cid(id));});}
fn play(g:&mut Game,hand:usize) {let pos=g.players[0].board.len();g.apply(0,Action::Play{hand,pos}).unwrap();}
fn discover(g:&mut Game,id:&str) {
 g.universe.clear();g.spell_universe.clear();if db().get(cid(id)).kind==taverngym::cards::CardKind::Minion {g.universe.push(cid(id));g.pool.put(cid(id),5);}else {g.spell_universe.push(cid(id));}
 give(g,"BG31_892");let h=g.players[0].hand.len()-1;play(g,h);
 let Some(Pending::Discover{options,..})=g.players[0].pending.last() else {panic!("discover missing")};assert_eq!(options.len(),1);assert_eq!(options[0].card(),cid(id));g.apply(0,Action::Choose(0)).unwrap();
}
#[test]
fn fandral_sinstone_generated_minion_copy_actually_executes_both_effects_without_choice() {
 let mut g=game();g.players[0].trinkets.push(cid("BG30_MagicItem_801"));discover(&mut g,"BG32_237");assert_eq!(g.players[0].hand.len(),2);
 let mut twin=g.clone();for state in [&mut g,&mut twin] {play(state,0);assert!(state.players[0].pending.is_empty(),"first generated card unexpectedly asked Choose One");play(state,0);assert!(state.players[0].pending.is_empty(),"copied generated card lost combined effect");assert_eq!((state.players[0].stats.spell_atk,state.players[0].stats.spell_hp),(2,2));}
 assert_eq!(raw(&g),raw(&twin));
}
fn target(g:&mut Game,eid:u32) {let Some(Pending::Target{options,..})=g.players[0].pending.last() else {panic!("target choice missing")};let i=options.iter().position(|e|*e==eid).unwrap();g.apply(0,Action::Choose(i)).unwrap();}
#[test]
fn copied_generated_forest_bounty_target_combines_both_branches_and_preserves_raw_prefix() {
 let mut g=game();g.players[0].board.push(Minion::new(201,cid("BG23_000")));g.players[0].trinkets.push(cid("BG30_MagicItem_801"));discover(&mut g,"BG31_886");assert_eq!(g.players[0].hand.len(),2);
 let (a,h)=(g.players[0].board[0].atk,g.players[0].board[0].max_hp);let mut twin=g.clone();
 for state in [&mut g,&mut twin] {for _ in 0..2 {play(state,0);let before=raw(state);assert!(state.apply(0,Action::Choose(100)).is_err());assert_eq!(raw(state),before);target(state,201);assert!(state.players[0].pending.is_empty());}}
 assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(a+28,h+28));assert_eq!(raw(&g),raw(&twin));
}
#[test]
fn generated_foodie_combines_growth_and_generated_gems_without_aura() {
 let mut g=game();discover(&mut g,"BG30_123");play(&mut g,0);assert!(g.players[0].pending.is_empty());assert_eq!((g.players[0].stats.gem_atk,g.players[0].stats.gem_hp),(1,1));assert_eq!(g.players[0].hand.len(),4);for h in &g.players[0].hand {assert_eq!(h.item.card(),cid("BG20_GEM"));}
 g.players[0].hand.clear();give(&mut g,"BG32_237");play(&mut g,0);assert!(matches!(g.players[0].pending.last(),Some(Pending::ChooseOne{..})));
}
#[test]
fn ordinary_noncombined_exact_hand_copy_keeps_choice_and_selected_effect_only() {
 let mut g=game();give(&mut g,"BG32_237");let hid=g.players[0].hand[0].hid;g.with_recruit(0,|c|{c.give_copy_of_hand(0,hid);});assert_eq!(g.players[0].hand.len(),2);
 play(&mut g,0);assert!(matches!(g.players[0].pending.last(),Some(Pending::ChooseOne{..})));g.apply(0,Action::Choose(0)).unwrap();assert_eq!((g.players[0].stats.spell_atk,g.players[0].stats.spell_hp),(1,0));
 play(&mut g,0);assert!(matches!(g.players[0].pending.last(),Some(Pending::ChooseOne{..})));g.apply(0,Action::Choose(1)).unwrap();assert_eq!((g.players[0].stats.spell_atk,g.players[0].stats.spell_hp),(1,1));
}
#[test]
fn sinstone_combined_copy_waiting_for_hand_space_is_delivered_and_executes_both() {
 let mut g=game();g.players[0].trinkets.push(cid("BG30_MagicItem_801"));for _ in 0..9 {give(&mut g,"BG20_GEM");}discover(&mut g,"BG32_237");assert_eq!(g.players[0].hand.len(),10);assert_eq!(g.players[0].hand_queue.len(),1);
 let mut twin:Game=serde_json::from_str(&raw(&g)).unwrap();
 for state in [&mut g,&mut twin] {play(state,9);assert!(state.players[0].pending.is_empty());assert!(state.players[0].hand_queue.is_empty());play(state,9);assert!(state.players[0].pending.is_empty());assert_eq!((state.players[0].stats.spell_atk,state.players[0].stats.spell_hp),(2,2));}
 assert_eq!(raw(&g),raw(&twin));
}
#[test]
fn sewer700_provisional_targets_cancel_commit_normal_gold_full_raw() {
 for id in ["BG36_700","BG36_700_G"] {let mut g=game();g.players[0].board=vec![Minion::new(201,cid(id)),Minion::new(202,cid("BG36_703")),Minion::new(203,cid("BG23_000"))];g.players[0].shop.push(ShopSlot::new(204,Item::Minion(Minion::new(204,cid("BG36_703")))));give(&mut g,"BG36_703");g.players[1].board.push(Minion::new(205,cid("BG36_703")));
 let mut expected=g.clone();expected.players[0].actions_this_turn+=2;g.apply(0,Action::Activate(0)).unwrap();let Some(Pending::Target{options,..})=g.players[0].pending.last()else{panic!("target missing")};assert_eq!(options,&vec![202,204]);assert_eq!(g.players[0].gold,10);assert_eq!(g.players[0].board[0].activations,0);let before=raw(&g);assert!(g.apply(0,Action::Choose(100)).is_err());assert_eq!(raw(&g),before);g.apply(0,Action::Cancel).unwrap();assert_eq!(raw(&g),raw(&expected));
 let (a,h)={let m=g.players[0].shop[0].item.as_minion().unwrap();(m.atk,m.max_hp)};g.apply(0,Action::Activate(0)).unwrap();let mut twin=g.clone();target(&mut g,204);target(&mut twin,204);assert_eq!(raw(&g),raw(&twin));let m=g.players[0].shop[0].item.as_minion().unwrap();let n=if id.ends_with("_G"){14}else{7};assert_eq!((m.atk,m.max_hp),(a+n,h+n));assert_eq!(g.players[0].gold,9);assert_eq!(g.players[0].board[0].activations,1);let before=raw(&g);assert!(g.apply(0,Action::Activate(0)).is_err());assert_eq!(raw(&g),before);
 }
}
#[test]
fn sewer700_provisional_missing_keyword_and_all_six_rng_snapshot_no_official_distribution_claim() {
 let all=Kw(Kw::TAUNT.0|Kw::DIVINE_SHIELD.0|Kw::WINDFURY.0|Kw::REBORN.0|Kw::VENOMOUS.0|Kw::STEALTH.0);
 for complete in [false,true] {let mut g=game();g.players[0].board=vec![Minion::new(201,cid("BG36_700")),Minion::new(202,cid("BG36_703"))];g.players[0].board[1].kw=if complete{all}else{Kw(all.0 & !Kw::STEALTH.0)};let mut expected_rng=g.rng.clone();if complete {expected_rng.pick(&[0,1,2,3,4,5]);}else{expected_rng.pick(&[0]);}
 g.apply(0,Action::Activate(0)).unwrap();target(&mut g,202);assert_eq!(g.players[0].board[1].kw.0,all.0);assert_eq!(serde_json::to_string(&g.rng).unwrap(),serde_json::to_string(&expected_rng).unwrap());}
 let mut g=game();g.players[0].board.push(Minion::new(201,cid("BG36_700")));let before=raw(&g);assert!(g.apply(0,Action::Activate(0)).is_err());assert_eq!(raw(&g),before);
}

#[test]
fn generated_scarab_targeted_choose_one_runs_two_branches_with_one_target() {
 let mut g=game();g.players[0].board.push(Minion::new(201,cid("BG27_084")));let (a,h)=(g.players[0].board[0].atk,g.players[0].board[0].max_hp);discover(&mut g,"BG27_084");play(&mut g,0);
 assert!(matches!(g.players[0].pending.last(),Some(Pending::Target{..})));target(&mut g,201);assert!(g.players[0].pending.is_empty());assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(a+5,h+1));assert!(g.players[0].board[0].kw.has(Kw::REBORN));assert!(g.players[0].board[0].kw.has(Kw::WINDFURY));
}
#[test]
fn combined_boundless_generates_two_discoveries_but_descendant_choose_one_card_is_ordinary() {
 let mut g=game();discover(&mut g,"BG31_890");g.players[0].tier=2;g.universe=vec![cid("BG32_237")];g.pool.put(cid("BG32_237"),5);g.spell_universe=vec![cid("BG28_805")];play(&mut g,0);assert_eq!(g.players[0].pending.len(),2);
 let mut restored:Game=serde_json::from_str(&raw(&g)).unwrap();for state in [&mut g,&mut restored] {for _ in 0..2 {assert!(matches!(state.players[0].pending.last(),Some(Pending::Discover{..})));state.apply(0,Action::Choose(0)).unwrap();}assert_eq!(state.players[0].hand.len(),2);let i=state.players[0].hand.iter().position(|h|h.item.card()==cid("BG32_237")).unwrap();play(state,i);assert!(matches!(state.players[0].pending.last(),Some(Pending::ChooseOne{..})));state.apply(0,Action::Choose(1)).unwrap();assert_eq!((state.players[0].stats.spell_atk,state.players[0].stats.spell_hp),(0,1));}assert_eq!(raw(&g),raw(&restored));
}

